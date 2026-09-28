// SPDX-License-Identifier: GPL-2.0-or-later
// Read-only enumeration. Never activates a camera or changes registration.
#include <windows.h>
#include <dshow.h>
#include <mfapi.h>
#include <mfidl.h>
#include <wrl/client.h>
#include <iostream>
#include <iomanip>
#include <sstream>
#include <string>
#include <vector>
using Microsoft::WRL::ComPtr;
struct Inventory { HRESULT result = E_FAIL; std::vector<std::wstring> names; unsigned unreadable = 0; };
std::string quoted(const std::wstring& value) {
    int length = WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
    std::string utf8(length, '\0');
    if (length) WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), utf8.data(), length, nullptr, nullptr);
    std::ostringstream out; out << '"';
    for (unsigned char c : utf8) {
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (c < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<unsigned>(c);
        else out << c;
    }
    out << '"'; return out.str();
}
Inventory directshow() {
    Inventory out;
    ComPtr<ICreateDevEnum> devices; ComPtr<IEnumMoniker> items;
    out.result = CoCreateInstance(CLSID_SystemDeviceEnum, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&devices));
    if (FAILED(out.result)) return out;
    out.result = devices->CreateClassEnumerator(CLSID_VideoInputDeviceCategory, &items, 0);
    if (out.result == S_FALSE) { out.result = S_OK; return out; }
    if (FAILED(out.result)) return out;
    for (;;) {
        ComPtr<IMoniker> item;
        HRESULT next = items->Next(1, &item, nullptr);
        if (next == S_FALSE) break;
        if (FAILED(next)) { out.result = next; break; }
        ComPtr<IPropertyBag> bag;
        VARIANT name; VariantInit(&name);
        HRESULT hr = item->BindToStorage(nullptr, nullptr, IID_PPV_ARGS(&bag));
        if (SUCCEEDED(hr)) hr = bag->Read(L"FriendlyName", &name, nullptr);
        if (SUCCEEDED(hr) && name.vt == VT_BSTR && name.bstrVal)
            out.names.emplace_back(name.bstrVal, SysStringLen(name.bstrVal));
        else ++out.unreadable;
        VariantClear(&name);
    }
    return out;
}
Inventory media_foundation() {
    Inventory out;
    out.result = MFStartup(MF_VERSION, MFSTARTUP_NOSOCKET);
    if (FAILED(out.result)) return out;
    {
        ComPtr<IMFAttributes> attributes;
        out.result = MFCreateAttributes(&attributes, 1);
        if (SUCCEEDED(out.result)) out.result = attributes->SetGUID(MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE, MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_GUID);
        IMFActivate** devices = nullptr; UINT32 count = 0;
        if (SUCCEEDED(out.result)) out.result = MFEnumDeviceSources(attributes.Get(), &devices, &count);
        if (SUCCEEDED(out.result)) {
            for (UINT32 i = 0; i < count; ++i) {
                wchar_t* name = nullptr; UINT32 length = 0;
                HRESULT hr = devices[i]->GetAllocatedString(MF_DEVSOURCE_ATTRIBUTE_FRIENDLY_NAME, &name, &length);
                if (SUCCEEDED(hr) && name) out.names.emplace_back(name, length);
                else ++out.unreadable;
                CoTaskMemFree(name);
                devices[i]->Release();
            }
        }
        CoTaskMemFree(devices);
    }
    MFShutdown(); return out;
}
void print(const char* key, const Inventory& value) {
    std::cout << '"' << key << "\":{\"ok\":" << (SUCCEEDED(value.result) ? "true" : "false")
              << ",\"hresult\":\"0x" << std::hex << std::setw(8) << std::setfill('0')
              << static_cast<unsigned long>(value.result) << std::dec
              << "\",\"unreadable_names\":" << value.unreadable << ",\"devices\":[";
    for (size_t i = 0; i < value.names.size(); ++i) {
        if (i) std::cout << ',';
        std::cout << quoted(value.names[i]);
    }
    std::cout << "]}";
}
int main() {
    HRESULT init = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    Inventory ds, mf;
    if (SUCCEEDED(init)) { ds = directshow(); mf = media_foundation(); CoUninitialize(); }
    else { ds.result = init; mf.result = init; }
    std::cout << "{\"diagnostic_revision\":1,\"process_architecture\":\"x64\",\"capture_started\":false,";
    print("directshow", ds); std::cout << ','; print("media_foundation", mf); std::cout << "}\n";
    // A report with an API error is still a valid report; inspect each 'ok'.
    return 0;
}
