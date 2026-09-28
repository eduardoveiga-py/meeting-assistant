#include "pixels.hpp"
#include <array>
#include <iostream>
int main() {
    const uint8_t src[] = {16,32,64,128,90,180};
    std::array<uint8_t, 8> out{};
    ma_compat::convert(src, out.data(), 2, 2, 2);
    if (out != std::array<uint8_t,8>{16,90,32,180,64,90,128,180}) return 1;
    ma_compat::convert(src, out.data(), 2, 2, 1);
    if (memcmp(out.data(), src, 6)) return 1;
    const uint8_t wide[] = {1,2,3,4,5,6,7,8,10,20,30,40};
    std::array<uint8_t, 12> planar{};
    ma_compat::convert(wide, planar.data(), 4, 2, 1);
    if (planar != std::array<uint8_t,12>{1,2,3,4,5,6,7,8,10,30,20,40}) return 1;
    std::cout << "NV12/I420/YUY2 planes and chroma OK\n";
}
