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
inline bool read_frame(std::vector<uint8_t>& pixels) {
    // Keep the connection between samples; preview has its own independent pipe.
    struct Connection {
        HANDLE pipe = INVALID_HANDLE_VALUE;
        void reset() { if (pipe != INVALID_HANDLE_VALUE) CloseHandle(pipe); pipe = INVALID_HANDLE_VALUE; }
        ~Connection() { reset(); }
    };
    static thread_local Connection connection;
    if (connection.pipe == INVALID_HANDLE_VALUE)
        connection.pipe = CreateFileW(frames_pipe, GENERIC_READ | GENERIC_WRITE, 0, nullptr,
                                      OPEN_EXISTING, FILE_FLAG_OVERLAPPED, nullptr);
    HANDLE pipe = connection.pipe;
    if (pipe == INVALID_HANDLE_VALUE) return false;
    char command = 'F', ack = 'A';
    Header h{};
    bool ok = transfer(pipe, &command, 1, true) && transfer(pipe, &h, sizeof(h), false);
    ok = ok && h.signature == magic && h.version == 1 && h.size == sizeof(h)
        && h.w == width && h.h == height && h.payload == bytes
        && (h.flags & (enabled | fresh)) == (enabled | fresh);
    if (ok) {
        pixels.resize(bytes);
        ok = transfer(pipe, pixels.data(), bytes, false);
        if (ok) transfer(pipe, &ack, 1, true);
    }
    if (!ok) connection.reset();
    return ok;
}
// The sample negotiates NV12 only. Padding is respected; stale video becomes black.
inline HRESULT copy_frame(BYTE* target, DWORD length, LONG pitch) {
    if (!target || pitch < static_cast<LONG>(width)
        || length < static_cast<uint64_t>(pitch) * (height + height / 2)) return E_INVALIDARG;
    using Clock = std::chrono::steady_clock;
    static thread_local Clock::time_point next{};
    const auto period = std::chrono::nanoseconds(1000000000 / 30);
    const auto now = Clock::now();
    if (next > now) std::this_thread::sleep_until(next);
    else if (now - next > period) next = now;
    next += period;
    std::vector<uint8_t> frame;
    const bool valid = read_frame(frame);
    for (uint32_t row = 0; row < height + height / 2; ++row) {
        BYTE* dest = target + static_cast<size_t>(row) * pitch;
        if (valid) memcpy(dest, frame.data() + static_cast<size_t>(row) * width, width);
        else memset(dest, row < height ? 16 : 128, width);
    }
    return S_OK;
}
}
