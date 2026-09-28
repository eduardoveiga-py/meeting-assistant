// SPDX-License-Identifier: GPL-2.0-or-later
// DirectShow source built on pinned LGPL libdshowcapture output primitives.
#include <windows.h>
#include <source/output-filter.hpp>
#include <source/dshow-formats.hpp>
#include <atomic>
#include <algorithm>
#include <thread>
#include <chrono>
#include <new>
#include "identity.hpp"
#include "pixels.hpp"
#include "../virtual-camera/pipe_client.hpp"

namespace {
HINSTANCE instance;
std::atomic<long> objects{0}, server_locks{0};
constexpr LONGLONG interval = 10000000 / 30;
bool enabled() {
    HANDLE event = OpenEventW(SYNCHRONIZE, FALSE, ma_compat::gate);
    if (!event) return false;
    bool on = WaitForSingleObject(event, 0) == WAIT_OBJECT_0;
    CloseHandle(event);
    return on;
}
class Camera final : public DShow::OutputFilter {
    HANDLE stop_event = nullptr;
    std::thread worker;
    std::atomic<REFERENCE_TIME> start_time{0};
    std::atomic<bool> running{false};
    void loop() {
        using Clock = std::chrono::steady_clock;
        auto deadline = Clock::now();
        REFERENCE_TIME timestamp = 0;
        std::vector<uint8_t> data(ma::bytes);
        while (WaitForSingleObject(stop_event, 0) == WAIT_TIMEOUT) {
            bool valid = enabled() && ma::read_frame(data);
            if (!valid) {
                memset(data.data(), 16, ma::width * ma::height);
                memset(data.data() + ma::width * ma::height, 128, ma::bytes / 3);
            }
            if (WaitForSingleObject(stop_event, 0) != WAIT_TIMEOUT) break;
            BYTE* target = nullptr;
            if (LockSampleData(&target)) {
                int fmt = GetVideoFormat() == DShow::VideoFormat::I420 ? 1 :
                          GetVideoFormat() == DShow::VideoFormat::YUY2 ? 2 : 0;
                ma_compat::convert(data.data(), target, ma::width, ma::height, fmt);
                REFERENCE_TIME clock_time;
                if (running && clock && SUCCEEDED(clock->GetTime(&clock_time)))
                    timestamp = (std::max)(timestamp, clock_time - start_time.load());
                UnlockSampleData(timestamp, timestamp + interval);
                timestamp += interval;
            }
            deadline += std::chrono::nanoseconds(1000000000 / 30);
            auto now = Clock::now();
            if (deadline < now) deadline = now;
            auto delay = std::chrono::duration_cast<std::chrono::milliseconds>(deadline - now).count();
            if (WaitForSingleObject(stop_event, static_cast<DWORD>(delay)) != WAIT_TIMEOUT) break;
        }
    }
public:
    Camera() : OutputFilter(DShow::VideoFormat::NV12, ma::width, ma::height, interval) {
        stop_event = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        if (!stop_event) throw std::bad_alloc();
        AddVideoFormat(DShow::VideoFormat::I420, ma::width, ma::height, interval);
        AddVideoFormat(DShow::VideoFormat::YUY2, ma::width, ma::height, interval);
        ++objects;
    }
    ~Camera() override {
        Stop();
        CloseHandle(stop_event);
        --objects;
    }
    const wchar_t* FilterName() const override { return ma_compat::name; }
    STDMETHODIMP GetClassID(CLSID* out) override {
        if (!out) return E_POINTER;
        *out = ma_compat::clsid; return S_OK;
    }
    STDMETHODIMP Pause() override {
        HRESULT hr = OutputFilter::Pause();
        if (FAILED(hr)) return hr;
        if (!worker.joinable()) {
            ResetEvent(stop_event);
            try { worker = std::thread([this] { loop(); }); }
            catch (...) { OutputFilter::Stop(); return E_FAIL; }
        }
        return S_OK;
    }
    STDMETHODIMP Run(REFERENCE_TIME start) override {
        start_time = start;
        running = true;
        HRESULT hr = Pause();
        return FAILED(hr) ? hr : OutputFilter::Run(start);
    }
    STDMETHODIMP Stop() override {
        running = false;
        SetEvent(stop_event);
        HRESULT hr = OutputFilter::Stop(); // Flush/decommit unblocks downstream allocator.
        if (worker.joinable()) worker.join();
        return hr;
    }
};
class Factory final : public IClassFactory {
    std::atomic<ULONG> refs{1};
public:
    Factory() { ++objects; }
    ~Factory() { --objects; }
    STDMETHODIMP QueryInterface(REFIID iid, void** out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (iid != IID_IUnknown && iid != IID_IClassFactory) return E_NOINTERFACE;
        *out = static_cast<IClassFactory*>(this); AddRef(); return S_OK;
    }
    STDMETHODIMP_(ULONG) AddRef() override { return ++refs; }
    STDMETHODIMP_(ULONG) Release() override { auto n = --refs; if (!n) delete this; return n; }
    STDMETHODIMP CreateInstance(IUnknown* outer, REFIID iid, void** out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (outer) return CLASS_E_NOAGGREGATION;
        try {
            auto camera = new Camera();
            camera->AddRef();
            HRESULT hr = camera->QueryInterface(iid, out);
            camera->Release();
            return hr;
        } catch (...) { return E_OUTOFMEMORY; }
    }
    STDMETHODIMP LockServer(BOOL lock) override { if (lock) ++server_locks; else --server_locks; return S_OK; }
};
HRESULT set_string(const std::wstring& key, const wchar_t* name, const wchar_t* value) {
    HKEY handle;
    auto err = RegCreateKeyExW(HKEY_LOCAL_MACHINE, key.c_str(), 0, nullptr, 0, KEY_WRITE, nullptr, &handle, nullptr);
    if (err) return HRESULT_FROM_WIN32(err);
    err = RegSetValueExW(handle, name, 0, REG_SZ, reinterpret_cast<const BYTE*>(value),
                        static_cast<DWORD>((wcslen(value) + 1) * sizeof(wchar_t)));
    RegCloseKey(handle);
    return HRESULT_FROM_WIN32(err);
}
HRESULT filter_registration(bool install) {
    HRESULT init = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(init) && init != RPC_E_CHANGED_MODE) return init;
    IFilterMapper2* mapper = nullptr;
    HRESULT hr = CoCreateInstance(CLSID_FilterMapper2, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&mapper));
    if (SUCCEEDED(hr)) {
        if (install) {
            REGPINTYPES type{&MEDIATYPE_Video, &MEDIASUBTYPE_NV12};
            REGFILTERPINS pin{nullptr, FALSE, TRUE, FALSE, FALSE, &CLSID_NULL, nullptr, 1, &type};
            REGFILTER2 filter{}; filter.dwVersion = 1; filter.dwMerit = MERIT_DO_NOT_USE;
            filter.cPins = 1; filter.rgPins = &pin;
            hr = mapper->RegisterFilter(ma_compat::clsid, ma_compat::name, nullptr,
                                       &CLSID_VideoInputDeviceCategory, nullptr, &filter);
        } else hr = mapper->UnregisterFilter(&CLSID_VideoInputDeviceCategory, nullptr, ma_compat::clsid);
        mapper->Release();
    }
    if (SUCCEEDED(init)) CoUninitialize();
    return hr;
}
}
STDAPI DllCanUnloadNow() { return objects || server_locks ? S_FALSE : S_OK; }
STDAPI DllGetClassObject(REFCLSID cls, REFIID iid, void** out) {
    if (!out) return E_POINTER;
    *out = nullptr;
    if (cls != ma_compat::clsid) return CLASS_E_CLASSNOTAVAILABLE;
    auto f = new (std::nothrow) Factory();
    if (!f) return E_OUTOFMEMORY;
    HRESULT hr = f->QueryInterface(iid, out); f->Release(); return hr;
}
STDAPI DllUnregisterServer() {
    HRESULT hr = filter_registration(false);
    auto error = RegDeleteTreeW(HKEY_LOCAL_MACHINE, ma_compat::registry);
    if (error && error != ERROR_FILE_NOT_FOUND) return HRESULT_FROM_WIN32(error);
    return FAILED(hr) ? hr : S_OK;
}
STDAPI DllRegisterServer() {
    wchar_t path[32768];
    DWORD size = GetModuleFileNameW(instance, path, 32768);
    if (!size || size >= 32768) return E_FAIL;
    const std::wstring root = ma_compat::registry;
    HRESULT hr = set_string(root, nullptr, ma_compat::name);
    if (SUCCEEDED(hr)) hr = set_string(root + L"\\InprocServer32", nullptr, path);
    if (SUCCEEDED(hr)) hr = set_string(root + L"\\InprocServer32", L"ThreadingModel", L"Both");
    if (SUCCEEDED(hr)) hr = filter_registration(true);
    if (FAILED(hr)) { filter_registration(false); RegDeleteTreeW(HKEY_LOCAL_MACHINE, ma_compat::registry); }
    return hr;
}
BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) instance = inst;
    return TRUE;
}
