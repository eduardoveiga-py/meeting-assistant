#pragma once
#include <windows.h>
namespace ma_compat {
inline constexpr GUID clsid = {0xb316823f, 0x42cf, 0x4f77, {0x91, 0x90, 0x31, 0x9d, 0x1b, 0x24, 0x5e, 0xc8}};
inline constexpr wchar_t name[] = L"Meeting Assistant Compat";
inline constexpr wchar_t gate[] = L"Local\\MeetingAssistant.CompatVideo.Enabled.v1";
inline constexpr wchar_t registry[] = L"SOFTWARE\\Classes\\CLSID\\{B316823F-42CF-4F77-9190-319D1B245EC8}";
}
