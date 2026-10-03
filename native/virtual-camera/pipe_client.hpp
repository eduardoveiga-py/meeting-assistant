#pragma once
#include <windows.h>
#include <atomic>
#include <chrono>
#include <mutex>
#include <thread>
#include <utility>
#include <vector>
#include <cstring>
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
    std::atomic<bool> stopping{false};
    std::thread reader;
    std::mutex frame_mutex;
    std::vector<uint8_t> latest_frame;
    std::vector<uint8_t> scratch_frame;
    bool has_frame = false;

    static bool valid_header(const Header& h) {
        return h.signature == magic && h.version == 1 && h.size == sizeof(h)
            && h.w == width && h.h == height && (h.payload == bytes || h.payload == 0)
            && (h.flags & ~3u) == 0 && h.reserved == 0;
    }

    void run() {
        HANDLE pipe = INVALID_HANDLE_VALUE;
        const auto period = std::chrono::nanoseconds(1000000000 / 30);
        auto next = Clock::now();

        while (!stopping.load(std::memory_order_relaxed)) {
            if (pipe == INVALID_HANDLE_VALUE) {
                pipe = CreateFileW(frames_pipe, GENERIC_READ | GENERIC_WRITE, 0, nullptr,
                                   OPEN_EXISTING, FILE_FLAG_OVERLAPPED, nullptr);
                if (pipe == INVALID_HANDLE_VALUE) {
                    std::this_thread::sleep_for(std::chrono::milliseconds(50));
                    next = Clock::now();
                    continue;
                }
            }

            char command = 'F', ack = 'A';
            Header h{};
            bool ok = transfer(pipe, &command, 1, true)
                && transfer(pipe, &h, sizeof(h), false)
                && valid_header(h);
            bool is_fresh = ok && h.payload == bytes && h.flags == (enabled | ma::fresh);
            if (ok && h.payload) {
                if (scratch_frame.size() != bytes) scratch_frame.resize(bytes);
                ok = transfer(pipe, scratch_frame.data(), bytes, false);
            }
            if (ok) ok = transfer(pipe, &ack, 1, true) && ack == 'A';

            if (!ok) {
                CloseHandle(pipe);
                pipe = INVALID_HANDLE_VALUE;
                std::this_thread::sleep_for(std::chrono::milliseconds(25));
                next = Clock::now();
                continue;
            }

            {
                std::lock_guard<std::mutex> lock(frame_mutex);
                if (is_fresh) {
                    std::swap(latest_frame, scratch_frame);
                    has_frame = true;
                } else {
                    has_frame = false;
                }
            }

            next += period;
            const auto now = Clock::now();
            if (next < now) next = now;
            std::this_thread::sleep_until(next);
        }

        if (pipe != INVALID_HANDLE_VALUE) CloseHandle(pipe);
    }
public:
    ProgramReader() : latest_frame(bytes), scratch_frame(bytes) {}
    ProgramReader(const ProgramReader&) = delete;
    ProgramReader& operator=(const ProgramReader&) = delete;
    ~ProgramReader() { reset(); }
    void reset() {
        stopping.store(true, std::memory_order_relaxed);
        if (reader.joinable()) reader.join();
        stopping.store(false, std::memory_order_relaxed);
        std::lock_guard<std::mutex> lock(frame_mutex);
        has_frame = false;
    }
    void ensure_reader() {
        if (!reader.joinable()) reader = std::thread(&ProgramReader::run, this);
    }

    // Called under SimpleMediaStream's lock. The pipe reader runs independently so
    // Media Foundation never blocks on named-pipe I/O or frame pacing.
    HRESULT copy_frame(BYTE* target, DWORD length, LONG pitch) {
        if (!target || pitch < static_cast<LONG>(width)
            || length < static_cast<uint64_t>(pitch) * (height + height / 2)) return E_INVALIDARG;

        ensure_reader();
        std::lock_guard<std::mutex> lock(frame_mutex);
        const bool valid = has_frame;
        for (uint32_t row = 0; row < height + height / 2; ++row) {
            BYTE* dest = target + static_cast<size_t>(row) * pitch;
            if (valid) memcpy(dest, latest_frame.data() + static_cast<size_t>(row) * width, width);
            else memset(dest, row < height ? 16 : 128, width);
        }
        return S_OK;
    }
};
}
