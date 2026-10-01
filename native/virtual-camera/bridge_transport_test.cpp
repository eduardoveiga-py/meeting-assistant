// Exercises actual Windows IPC with synthetic OBS callback data; no OBS installation.
#include "obs_bridge.cpp"
#include "pipe_client.hpp"
#include <iostream>
#include <stdexcept>

void check(bool condition) { if (!condition) throw std::runtime_error("transport check failed"); }
HANDLE connect(const wchar_t* path) {
    for (int i = 0; i < 30; ++i) {
        auto h = CreateFileW(path, GENERIC_READ | GENERIC_WRITE, 0, nullptr,
                             OPEN_EXISTING, FILE_FLAG_OVERLAPPED, nullptr);
        if (h != INVALID_HANDLE_VALUE) return h;
        Sleep(5);
    }
    throw std::runtime_error("pipe connection failed");
}
ma::Header exchange(HANDLE p, char command, std::vector<uint8_t>& frame) {
    ma::Header h{};
    check(ma::transfer(p, &command, 1, true));
    check(ma::transfer(p, &h, sizeof(h), false));
    check(h.signature == ma::magic && h.payload <= ma::bytes);
    frame.resize(h.payload);
    if (h.payload) check(ma::transfer(p, frame.data(), h.payload, false));
    char ack = 'A'; check(ma::transfer(p, &ack, 1, true));
    return h;
}
int main() {
    quit = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    auto f = make_pipe(ma::frames_pipe, true);
    auto p = make_pipe(ma::preview_pipe, false);
    auto c = make_pipe(ma::control_pipe, false);
    if (f == INVALID_HANDLE_VALUE || p == INVALID_HANDLE_VALUE || c == INVALID_HANDLE_VALUE) return 1;
    std::thread ft(serve, f, true, false), pt(serve, p, true, true), ct(serve, c, false, false);
    int result = 0;
    try {
        std::vector<uint8_t> data(ma::bytes, 128), received;
        memset(data.data(), 77, ma::width * ma::height);
        video_data input{};
        input.data[0] = data.data(); input.data[1] = data.data() + ma::width * ma::height;
        input.linesize[0] = input.linesize[1] = ma::width;
        input.timestamp = 1000000000; video(nullptr, &input);
        auto preview = connect(ma::preview_pipe);
        auto camera = connect(ma::frames_pipe);
        auto h = exchange(preview, 'F', received);
        check(h.flags == 3 && received == data);
        h = exchange(camera, 'F', received); check(h.flags == 0 && received.empty());
        auto control = connect(ma::control_pipe);
        h = exchange(control, 'S', received); CloseHandle(control); check(h.flags == 3);
        for (int i = 0; i < 12; ++i) {
            h = exchange(camera, 'F', received); check(h.flags == 3 && received == data);
            h = exchange(preview, 'F', received); check(h.flags == 3 && received == data);
        }
        control = connect(ma::control_pipe);
        h = exchange(control, 'T', received); CloseHandle(control); check(h.flags == 0);
        h = exchange(camera, 'F', received); check(h.flags == 0 && received.empty());
        h = exchange(preview, 'F', received); check(h.flags == 3 && received == data);
        { std::lock_guard<std::mutex> lock(frame_mutex); state.tick_ms = GetTickCount64() - 2000; }
        h = exchange(preview, 'F', received); check(h.flags == 1 && received.empty());
        CloseHandle(camera); CloseHandle(preview);
        std::cout << "PASS: simultaneous consumers, persistent connections, camera stop, stale rejection\n";
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; result = 1; }
    SetEvent(quit); ft.join(); pt.join(); ct.join(); CloseHandle(quit);
    return result;
}
