#pragma once
#include <cstdint>
namespace ma {
constexpr wchar_t frames_pipe[] = L"\\\\.\\pipe\\MeetingAssistant.Program.v1";
constexpr wchar_t preview_pipe[] = L"\\\\.\\pipe\\MeetingAssistant.Preview.v1";
constexpr wchar_t control_pipe[] = L"\\\\.\\pipe\\MeetingAssistant.Control.v1";
constexpr uint32_t magic = 0x3143414d; // MAC1, little endian
constexpr uint32_t width = 1280, height = 720, bytes = width * height * 3 / 2;
constexpr uint32_t enabled = 1, fresh = 2;
#pragma pack(push, 1)
struct Header {
    uint32_t signature = magic, version = 1, size = 48, w = width, h = height;
    uint32_t payload = 0, flags = 0, reserved = 0;
    uint64_t sequence = 0, tick_ms = 0;
};
#pragma pack(pop)
static_assert(sizeof(Header) == 48);
}
