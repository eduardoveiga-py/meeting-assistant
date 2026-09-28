// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <cstdint>
#include <cstring>
namespace ma_compat {
// Fixed NV12 source. No scaling or desktop capture; negotiated sizes are checked.
inline void convert(const uint8_t* src, uint8_t* dst, int w, int h, int format) {
    const int plane = w * h;
    if (format == 0) { memcpy(dst, src, plane * 3 / 2); return; }
    if (format == 1) { // I420
        memcpy(dst, src, plane);
        for (int i = 0; i < plane / 4; ++i) {
            dst[plane + i] = src[plane + 2 * i];
            dst[plane + plane / 4 + i] = src[plane + 2 * i + 1];
        }
    } else { // YUY2
        for (int y = 0; y < h; ++y) for (int x = 0; x < w; x += 2) {
            const int uv = plane + (y / 2) * w + x, out = (y * w + x) * 2;
            dst[out] = src[y * w + x]; dst[out + 1] = src[uv];
            dst[out + 2] = src[y * w + x + 1]; dst[out + 3] = src[uv + 1];
        }
    }
}
}
