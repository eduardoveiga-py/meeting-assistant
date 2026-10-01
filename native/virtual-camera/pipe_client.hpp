#pragma once
#include <windows.h>
#include <vector>
#include <cstring>
#include <chrono>
#include <thread>
#include "protocol.hpp"
namespace ma {
// All I/O has a deadline, including a server that connects but never replies.
inline bool transfer(HANDLE pipe, void* data, DWORD size, bool write) {
    OVERLAPPED ov{};
    ov.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!ov.hEvent) return false;
    DWORD count = 0;
    BOOL ok = write ? WriteFile(pipe, data, size, &count, &ov) : ReadFile(pipe, data, size, &count, &ov);
    if (!ok && GetLastError() == ERROR_IO_PENDING) {
        if (WaitForSingleObject(ov.hEvent, 150) != WAIT_OBJECT_0) {
            CancelIoEx(pipe, &ov);
            GetOverlappedResult(pipe, &ov, &count, TRUE);
            CloseHandle(ov.hEvent);
            return false;
        }
        ok = GetOverlappedResult(pipe, &ov, &count, FALSE);
    }
    CloseHandle(ov.hEvent);
    return ok && count == size;
}
// The media stream owns this connection and clock. Media Foundation may move
// RequestSample between worker threads, so neither belongs in thread_local storage.
class ProgramReader {
    using Clock = std::chrono::steady_clock;
    HANDLE pipe = INVALID_HANDLE_VALUE;
    Clock::time_point next{};
    std::vector<uint8_t> frame;
public:
    ProgramReader() = default;
    ProgramReader(const ProgramReader&) = delete;
    ProgramReader& operator=(const ProgramReader&) = delete;
    ~ProgramReader() { reset(); }
    void reset() {
        if (pipe != INVALID_HANDLE_VALUE) CloseHandle(pipe);
        pipe = INVALID_HANDLE_VALUE;
    }
    bool read() {
        if (pipe == INVALID_HANDLE_VALUE)
            pipe = CreateFileW(frames_pipe, GENERIC_READ | GENERIC_WRITE, 0, nullptr,
                               OPEN_EXISTING, FILE_FLAG_OVERLAPPED, nullptr);
        if (pipe == INVALID_HANDLE_VALUE) return false;
        char command = 'F', ack = 'A';
        Header h{};
        bool ok = transfer(pipe, &command, 1, true) && transfer(pipe, &h, sizeof(h), false);
        ok = ok && h.signature == magic && h.version == 1 && h.size == sizeof(h)
            && h.w == width && h.h == height && (h.payload == bytes || h.payload == 0)
            && (h.flags & ~3u) == 0 && h.reserved == 0;
        const bool valid = ok && h.payload == bytes && h.flags == (enabled | fresh);
        if (ok && h.payload) {
            frame.resize(bytes);
            ok = transfer(pipe, frame.data(), bytes, false);
        }
        if (ok) ok = transfer(pipe, &ack, 1, true);
        if (!ok) reset();
        return ok && valid;
    }
    // Called under SimpleMediaStream's lock. Padding is respected; stale video is black.
    HRESULT copy_frame(BYTE* target, DWORD length, LONG pitch) {
        if (!target || pitch < static_cast<LONG>(width)
            || length < static_cast<uint64_t>(pitch) * (height + height / 2)) return E_INVALIDARG;
        const auto period = std::chrono::nanoseconds(1000000000 / 30);
        const auto now = Clock::now();
        if (next > now) std::this_thread::sleep_until(next);
        else if (now - next > period) next = now;
        next += period;
        const bool valid = read();
        for (uint32_t row = 0; row < height + height / 2; ++row) {
            BYTE* dest = target + static_cast<size_t>(row) * pitch;
            if (valid) memcpy(dest, frame.data() + static_cast<size_t>(row) * width, width);
            else memset(dest, row < height ? 16 : 128, width);
        }
        return S_OK;
    }
};
}
