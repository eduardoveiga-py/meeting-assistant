// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <cstdint>
#include <string>

namespace ma_jwl {
struct Identity {
    uint64_t hwnd = 0, created = 0, jwl_hwnd = 0, jwl_created = 0;
    uint32_t pid = 0, jwl_pid = 0;
    int left = 0, top = 0, right = 0, bottom = 0;
    std::wstring class_name;
    std::string session;
};
struct Observed {
    uint64_t hwnd = 0, created = 0, jwl_hwnd = 0, jwl_created = 0;
    uint32_t pid = 0, jwl_pid = 0;
    int left = 0, top = 0, right = 0, bottom = 0;
    std::wstring class_name;
    bool exists = false, visible = false, minimized = true, cloaked = true;
    bool non_primary = false, covers_hall = false, jwl_process = false, related = false;
};
inline bool matches(const Identity& expected, const Observed& actual) {
    return expected.hwnd && expected.pid && expected.created && expected.jwl_hwnd
        && expected.jwl_pid && expected.jwl_created && !expected.session.empty()
        && expected.right > expected.left && expected.bottom > expected.top
        && expected.hwnd == actual.hwnd && expected.pid == actual.pid
        && expected.created == actual.created && expected.jwl_hwnd == actual.jwl_hwnd
        && expected.jwl_pid == actual.jwl_pid && expected.jwl_created == actual.jwl_created
        && !expected.class_name.empty() && expected.class_name == actual.class_name
        && expected.left == actual.left && expected.top == actual.top
        && expected.right == actual.right && expected.bottom == actual.bottom
        && actual.exists && actual.visible && !actual.minimized && !actual.cloaked
        && actual.non_primary && actual.covers_hall && actual.jwl_process && actual.related;
}
}
