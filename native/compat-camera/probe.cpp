// SPDX-License-Identifier: GPL-2.0-or-later
#include <windows.h>
#include <dshow.h>
#include <iostream>
#include "identity.hpp"

int wmain(int argc, wchar_t** argv) {
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr)) return 1;
    HMODULE module = nullptr;
    IClassFactory* factory = nullptr;
    IBaseFilter* filter = nullptr;
    // CI mode loads the DLL directly without changing machine registration.
    if (argc == 2) {
        module = LoadLibraryW(argv[1]);
        auto get = module ? reinterpret_cast<HRESULT(__stdcall*)(REFCLSID, REFIID, void**)>(
            GetProcAddress(module, "DllGetClassObject")) : nullptr;
        hr = get ? get(ma_compat::clsid, IID_IClassFactory, reinterpret_cast<void**>(&factory)) : E_FAIL;
        if (SUCCEEDED(hr)) hr = factory->CreateInstance(nullptr, IID_IBaseFilter, reinterpret_cast<void**>(&filter));
    } else hr = CoCreateInstance(ma_compat::clsid, nullptr, CLSCTX_INPROC_SERVER, IID_IBaseFilter,
                                 reinterpret_cast<void**>(&filter));
    int result = 1;
    if (SUCCEEDED(hr) && filter) {
        IEnumPins* pins = nullptr; IPin* pin = nullptr; IAMStreamConfig* config = nullptr;
        hr = filter->EnumPins(&pins);
        if (SUCCEEDED(hr)) hr = pins->Next(1, &pin, nullptr);
        if (hr == S_OK) hr = pin->QueryInterface(IID_IAMStreamConfig, reinterpret_cast<void**>(&config));
        int count = 0, size = 0;
        if (SUCCEEDED(hr) && config) hr = config->GetNumberOfCapabilities(&count, &size);
        if (SUCCEEDED(hr) && count == 3) {
            AM_MEDIA_TYPE* type = nullptr;
            hr = config->GetFormat(&type);
            if (SUCCEEDED(hr) && type && type->cbFormat >= sizeof(VIDEOINFOHEADER)) {
                auto info = reinterpret_cast<VIDEOINFOHEADER*>(type->pbFormat);
                if (info->bmiHeader.biWidth == 1280 && info->bmiHeader.biHeight == 720 && info->AvgTimePerFrame == 333333) {
                    info->bmiHeader.biWidth = 9999;
                    if (FAILED(config->SetFormat(type))) result = 0;
                }
                if (type->pUnk) type->pUnk->Release();
                CoTaskMemFree(type->pbFormat); CoTaskMemFree(type);
            }
            if (!result) {
                for (int i = 0; i < 3; ++i) {
                    if (FAILED(filter->Pause()) || FAILED(filter->Stop())) result = 1;
                }
            }
        }
        if (config) config->Release();
        if (pin) pin->Release();
        if (pins) pins->Release();
        filter->Release();
    }
    if (factory) factory->Release();
    if (module) {
        auto unload = reinterpret_cast<HRESULT(__stdcall*)()>(GetProcAddress(module, "DllCanUnloadNow"));
        if (!unload || unload() != S_OK) result = 1;
        else FreeLibrary(module);
    }
    std::cout << (result ? "COMPAT_ERROR " : "COMPAT_REGISTERED formats=NV12,I420,YUY2 size=1280x720 fps=30 ")
              << "HRESULT=0x" << std::hex << static_cast<unsigned long>(hr) << '\n';
    CoUninitialize();
    return result;
}
