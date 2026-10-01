// SPDX-License-Identifier: GPL-2.0-or-later
// Consumes only the OBS main raw video output. Never selects scenes or windows.
#include <windows.h>
#include <sddl.h>
#include <obs.h>
#include <atomic>
#include <mutex>
#include <thread>
#include <vector>
#include <cstring>
#include <string>
#include "protocol.hpp"
#include "frame_clock.hpp"
namespace {
std::atomic<bool> active{false};
HANDLE quit = nullptr;
std::thread frame_thread, preview_thread, control_thread;
std::mutex frame_mutex;
std::vector<uint8_t> pixels(ma::bytes);
ma::Header state;
ma::FrameClock frame_clock;
decltype(&obs_add_raw_video_callback) add_video = nullptr;
decltype(&obs_remove_raw_video_callback) remove_video = nullptr;

void video(void*, video_data* frame) {
    if (!frame || !frame->data[0] || !frame->data[1]
        || frame->linesize[0] < ma::width || frame->linesize[1] < ma::width) return;
    std::unique_lock<std::mutex> lock(frame_mutex, std::try_to_lock);
    if (!lock) return; // Never wait for an IPC consumer on the rendering callback.
    const auto now = GetTickCount64();
    if (!frame_clock.accept(frame->timestamp)) return;
    for (uint32_t y = 0; y < ma::height; ++y)
        memcpy(pixels.data() + y * ma::width, frame->data[0] + y * frame->linesize[0], ma::width);
    for (uint32_t y = 0; y < ma::height / 2; ++y)
        memcpy(pixels.data() + (ma::height + y) * ma::width,
               frame->data[1] + y * frame->linesize[1], ma::width);
    state.tick_ms = now;
    ++state.sequence;
}
void start() {
    { std::lock_guard<std::mutex> lock(frame_mutex); state.tick_ms = 0; state.sequence = 0; frame_clock = ma::FrameClock{}; }
    video_scale_info conversion{};
    conversion.format = VIDEO_FORMAT_NV12;
    conversion.width = ma::width; conversion.height = ma::height;
    conversion.colorspace = VIDEO_CS_709; conversion.range = VIDEO_RANGE_PARTIAL;
    add_video(&conversion, video, nullptr);
}
void stop() {
    active = false;
    remove_video(video, nullptr);
    std::lock_guard<std::mutex> lock(frame_mutex);
    state.tick_ms = 0;
}
bool io(HANDLE pipe, void* buffer, DWORD size, bool write) {
    OVERLAPPED ov{};
    ov.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!ov.hEvent) return false;
    DWORD count = 0;
    BOOL ok = write ? WriteFile(pipe, buffer, size, &count, &ov) : ReadFile(pipe, buffer, size, &count, &ov);
    if (!ok && GetLastError() == ERROR_IO_PENDING) {
        HANDLE waits[] = {quit, ov.hEvent};
        if (WaitForMultipleObjects(2, waits, FALSE, 300) != WAIT_OBJECT_0 + 1) {
            CancelIoEx(pipe, &ov); GetOverlappedResult(pipe, &ov, &count, TRUE);
            CloseHandle(ov.hEvent); return false;
        }
        ok = GetOverlappedResult(pipe, &ov, &count, FALSE);
    }
    CloseHandle(ov.hEvent);
    return ok && count == size;
}
// Current OBS user plus the Windows camera service. No Everyone/remote access.
PSECURITY_DESCRIPTOR security(bool frames) {
    HANDLE token = nullptr;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) return nullptr;
    DWORD size = 0;
    GetTokenInformation(token, TokenUser, nullptr, 0, &size);
    std::vector<uint8_t> info(size);
    if (!GetTokenInformation(token, TokenUser, info.data(), size, &size)) { CloseHandle(token); return nullptr; }
    CloseHandle(token);
    LPWSTR sid = nullptr;
    if (!ConvertSidToStringSidW(reinterpret_cast<TOKEN_USER*>(info.data())->User.Sid, &sid)) return nullptr;
    std::wstring sddl = L"D:P(A;;GA;;;SY)(A;;GA;;;";
    sddl += sid; sddl += L")";
    LocalFree(sid);
    if (frames) sddl += L"(A;;GRGW;;;LS)";
    PSECURITY_DESCRIPTOR sd = nullptr;
    if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(), SDDL_REVISION_1, &sd, nullptr))
        return nullptr;
    return sd;
}
HANDLE make_pipe(const wchar_t* name, bool frames) {
    auto sd = security(frames);
    if (!sd) return INVALID_HANDLE_VALUE;
    SECURITY_ATTRIBUTES sa{sizeof(sa), sd, FALSE};
    HANDLE p = CreateNamedPipeW(name,
        PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED | FILE_FLAG_FIRST_PIPE_INSTANCE,
        PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
        1, ma::bytes + sizeof(ma::Header), 16, 300, &sa);
    LocalFree(sd);
    return p;
}
void serve(HANDLE pipe, bool frames, bool preview = false) {
    while (WaitForSingleObject(quit, 0) != WAIT_OBJECT_0) {
        OVERLAPPED ov{};
        ov.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        if (!ov.hEvent) break;
        BOOL connected = ConnectNamedPipe(pipe, &ov);
        DWORD error = connected ? ERROR_SUCCESS : GetLastError();
        if (error == ERROR_IO_PENDING) {
            HANDLE waits[] = {quit, ov.hEvent};
            if (WaitForMultipleObjects(2, waits, FALSE, INFINITE) != WAIT_OBJECT_0 + 1) {
                CancelIoEx(pipe, &ov);
                DWORD ignored; GetOverlappedResult(pipe, &ov, &ignored, TRUE);
                CloseHandle(ov.hEvent); break;
            }
            DWORD ignored;
            connected = GetOverlappedResult(pipe, &ov, &ignored, FALSE);
        } else if (error == ERROR_PIPE_CONNECTED) connected = TRUE;
        CloseHandle(ov.hEvent);
        if (!connected) { DisconnectNamedPipe(pipe); continue; }
        char command = 0;
        while (io(pipe, &command, 1, false)) {
            if (!frames && command == 'S') active = true;
            if (!frames && command == 'T') active = false;
            if ((frames && command == 'F') || (!frames && (command == 'S' || command == 'T' || command == 'I'))) {
                ma::Header header;
                std::vector<uint8_t> frame;
                {
                    std::lock_guard<std::mutex> lock(frame_mutex);
                    header = state;
                    header.flags = (preview || active) ? ma::enabled : 0;
                    if ((preview || active) && state.tick_ms && GetTickCount64() - state.tick_ms < 1000)
                        header.flags |= ma::fresh;
                    if (frames && (header.flags & ma::fresh)) { header.payload = ma::bytes; frame = pixels; }
                }
                bool ok = io(pipe, &header, sizeof(header), true);
                if (ok && !frame.empty()) ok = io(pipe, frame.data(), static_cast<DWORD>(frame.size()), true);
                char ack = 0;
                if (!ok || !io(pipe, &ack, 1, false) || ack != 'A') break;
                if (!frames) break; // Control is one command per connection.
            } else break;
        }
        DisconnectNamedPipe(pipe);
    }
    CloseHandle(pipe);
}
}
#define MA_EXPORT extern "C" __declspec(dllexport)
MA_EXPORT void obs_module_set_pointer(obs_module_t*) {}
MA_EXPORT uint32_t obs_module_ver() { return LIBOBS_API_VER; }
MA_EXPORT const char* obs_module_name() { return "Meeting Assistant Program Bridge"; }
MA_EXPORT const char* obs_module_description() { return "Local Program preview and separately authorized camera output."; }
MA_EXPORT bool obs_module_load() {
    auto lib = GetModuleHandleW(L"obs.dll");
    if (!lib) return false;
    add_video = reinterpret_cast<decltype(add_video)>(GetProcAddress(lib, "obs_add_raw_video_callback"));
    remove_video = reinterpret_cast<decltype(remove_video)>(GetProcAddress(lib, "obs_remove_raw_video_callback"));
    if (!add_video || !remove_video) return false;
    quit = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!quit) return false;
    HANDLE frames = make_pipe(ma::frames_pipe, true), control = make_pipe(ma::control_pipe, false);
    HANDLE preview = make_pipe(ma::preview_pipe, false);
    if (frames == INVALID_HANDLE_VALUE || control == INVALID_HANDLE_VALUE || preview == INVALID_HANDLE_VALUE) {
        if (frames != INVALID_HANDLE_VALUE) CloseHandle(frames);
        if (control != INVALID_HANDLE_VALUE) CloseHandle(control);
        if (preview != INVALID_HANDLE_VALUE) CloseHandle(preview);
        CloseHandle(quit); quit = nullptr; return false;
    }
    start(); // Capture Program for local preview; camera delivery remains explicitly disabled.
    frame_thread = std::thread(serve, frames, true, false);
    preview_thread = std::thread(serve, preview, true, true);
    control_thread = std::thread(serve, control, false, false);
    return true;
}
MA_EXPORT void obs_module_unload() {
    if (!quit) return;
    SetEvent(quit);
    if (control_thread.joinable()) control_thread.join();
    if (frame_thread.joinable()) frame_thread.join();
    if (preview_thread.joinable()) preview_thread.join();
    stop(); CloseHandle(quit); quit = nullptr;
}
