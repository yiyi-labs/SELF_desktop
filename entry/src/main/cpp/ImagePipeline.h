#pragma once
#include <vector>
#include <cstdint>
namespace self {
struct Image { int width=0,height=0; std::vector<uint8_t> rgba; };
Image decodeImage(const std::vector<uint8_t>& data);
std::vector<uint8_t> encodePNG(const Image& image);
}
