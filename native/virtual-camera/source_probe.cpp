// Read-only, in-process test. Does NOT install/register a camera or driver.
#include <windows.h>
#include <mfapi.h>
#include <mfidl.h>
#include <wrl/client.h>
#include <iostream>
using Microsoft::WRL::ComPtr;
int wmain(int argc, wchar_t** argv) {
    if (argc != 2) { std::cerr << "Pass the full path to MeetingAssistantMediaSource.dll\n"; return 2; }
    HRESULT init = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(init)) return 3;
    HRESULT startup = MFStartup(MF_VERSION);
    HRESULT hr = startup;
    HMODULE module = nullptr;
    DWORD streams = 0;
    if (SUCCEEDED(hr)) {
        module = LoadLibraryExW(argv[1], nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
        hr = module ? S_OK : HRESULT_FROM_WIN32(GetLastError());
    }
    if (SUCCEEDED(hr)) {
        auto get = reinterpret_cast<HRESULT(__stdcall*)(REFCLSID, REFIID, void**)>(GetProcAddress(module, "DllGetClassObject"));
        CLSID cls{};
        hr = CLSIDFromString(L"{5108191D-9AD8-44F5-B760-7A35D433A427}", &cls);
        ComPtr<IClassFactory> factory;
        ComPtr<IMFActivate> activate;
        ComPtr<IMFMediaSource> source;
        ComPtr<IMFPresentationDescriptor> descriptor;
        if (SUCCEEDED(hr)) hr = get ? get(cls, IID_PPV_ARGS(&factory)) : E_NOINTERFACE;
        if (SUCCEEDED(hr)) hr = factory->CreateInstance(nullptr, IID_PPV_ARGS(&activate));
        if (SUCCEEDED(hr)) hr = activate->ActivateObject(IID_PPV_ARGS(&source));
        if (SUCCEEDED(hr)) hr = source->CreatePresentationDescriptor(&descriptor);
        if (SUCCEEDED(hr)) hr = descriptor->GetStreamDescriptorCount(&streams);
        if (SUCCEEDED(hr) && streams == 0) hr = E_UNEXPECTED;
        if (source) source->Shutdown();
        if (activate) activate->DetachObject();
    }
    // Keep DLL loaded until process exit: WinRT may hold factory caches.
    if (SUCCEEDED(startup)) MFShutdown();
    CoUninitialize();
    std::cout << "{\"source_activated\":" << (SUCCEEDED(hr) ? "true" : "false")
              << ",\"streams\":" << streams << ",\"hresult\":\"0x" << std::hex
              << static_cast<unsigned long>(hr) << "\",\"driver_installed\":false,\"whatsapp_tested\":false}\n";
    return FAILED(hr) ? 1 : 0;
}
