// Windows 11 session-scoped camera host. Closing stdin stops/removes this camera.
#include <windows.h>
#include <mfapi.h>
#include <mfvirtualcamera.h>
#include <wrl/client.h>
#include <iostream>
#include <string>
#pragma comment(lib, "mfplat.lib")
#pragma comment(lib, "mfsensorgroup.lib")
#pragma comment(lib, "ole32.lib")
int main() {
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr)) return 1;
    hr = MFStartup(MF_VERSION);
    if (FAILED(hr)) { CoUninitialize(); return 2; }
    Microsoft::WRL::ComPtr<IMFVirtualCamera> camera;
    hr = MFCreateVirtualCamera(MFVirtualCameraType_SoftwareCameraSource,
        MFVirtualCameraLifetime_Session, MFVirtualCameraAccess_CurrentUser,
        L"Meeting Assistant", L"{5108191D-9AD8-44F5-B760-7A35D433A427}", nullptr, 0, &camera);
    if (SUCCEEDED(hr)) hr = camera->Start(nullptr);
    if (SUCCEEDED(hr)) {
        std::cout << "CAMERA_STARTED" << std::endl;
        std::string command;
        while (std::getline(std::cin, command) && command != "stop") {}
        camera->Stop(); camera->Remove(); camera->Shutdown();
    } else std::cout << "CAMERA_ERROR 0x" << std::hex << static_cast<unsigned long>(hr) << std::endl;
    camera.Reset(); MFShutdown(); CoUninitialize();
    return FAILED(hr) ? 3 : 0;
}
