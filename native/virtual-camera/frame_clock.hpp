#pragma once
#include <cstdint>

namespace ma {
// OBS timestamps are nanoseconds. Keep the deadline anchored instead of adding
// the processing delay to every frame. One frame maximum after a stall.
class FrameClock {
    static constexpr uint64_t period = 1000000000ULL / 30;
    static constexpr uint64_t tolerance = 1000000ULL;
    uint64_t next = 0, previous = 0;
    bool initialized = false;
public:
    bool accept(uint64_t timestamp) {
        if (!initialized || timestamp < previous) {
            initialized = true;
            previous = timestamp;
            next = timestamp + period;
            return true;
        }
        previous = timestamp;
        if (timestamp + tolerance < next) return false;
        next += period;
        if (timestamp >= next) next = timestamp + period;
        return true;
    }
};
}
