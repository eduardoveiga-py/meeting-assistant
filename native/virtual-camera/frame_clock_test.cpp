#include "frame_clock.hpp"
#include <iostream>
#include <stdexcept>

void check(bool ok, const char* message) {
    if (!ok) throw std::runtime_error(message);
}
int count(uint64_t step, int frames) {
    ma::FrameClock clock;
    int accepted = 0;
    for (int i = 0; i < frames; ++i)
        accepted += clock.accept(1000000000ULL + static_cast<uint64_t>(i) * step);
    return accepted;
}
int main() {
    try {
        check(count(33333333, 3000) == 3000, "30 fps must not lose every other frame");
        check(count(16666667, 6000) == 3000, "60 fps must reduce to 30");
        check(count(33366667, 3000) >= 2997, "29.97 fps must remain smooth");
        check(count(41666667, 2400) == 2400, "24 fps must not lose source frames");
        ma::FrameClock clock;
        check(clock.accept(1000000000), "first frame");
        check(!clock.accept(1000000000), "duplicate timestamp");
        check(clock.accept(9000000000), "resume after stall");
        check(!clock.accept(9000000001), "no burst after stall");
        check(clock.accept(1000), "timestamp reset");
        std::cout << "Frame cadence: 24/29.97/30/60 fps, stall and reset OK\n";
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
