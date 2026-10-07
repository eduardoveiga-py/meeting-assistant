// SPDX-License-Identifier: GPL-2.0-or-later
#include "binding_policy.hpp"
#include <cstdlib>
#include <iostream>

int main() {
    using namespace ma_jwl;
    Identity wanted{70, 110, 71, 111, 100, 101, -1920, 0, 0, 1080, L"ApplicationFrameWindow", "test"};
    Observed good{70, 110, 71, 111, 100, 101, -1920, 0, 0, 1080, L"ApplicationFrameWindow",
                  true, true, false, false, true, true, true, true};
    auto check = [](bool result) { if (!result) { std::cerr << "Binding policy failed\n"; std::exit(1); } };
    check(matches(wanted, good));
    // The title is intentionally absent from both identities. A second window
    // with the same PID, class and title must still fail the HWND comparison.
    auto other = good; other.hwnd = 72; check(!matches(wanted, other));
    other = good; other.created++; check(!matches(wanted, other)); // PID/handle reuse
    other = good; other.jwl_created++; check(!matches(wanted, other));
    other = good; other.jwl_process = false; check(!matches(wanted, other)); // Zoom
    other = good; other.related = false; check(!matches(wanted, other)); // unrelated UWP child
    other = good; other.non_primary = false; check(!matches(wanted, other));
    other = good; other.covers_hall = false; check(!matches(wanted, other));
    other = good; other.cloaked = true; check(!matches(wanted, other));
    other = good; other.minimized = true; check(!matches(wanted, other));
    other = good; other.right = 1; check(!matches(wanted, other)); // display changed
    wanted.session.clear(); check(!matches(wanted, good));
    std::cout << "Exact HWND, process generations, UWP identity and hall role verified\n";
}
