#pragma once
#include "GltfAssetLoader.h"
#include "vendor/json.hpp"
namespace self {
std::vector<uint8_t> visibleSelection(const Asset&,const std::vector<uint8_t>& editable,
 const nlohmann::json& polygon,const std::array<float,16>& mvp,float yaw,float pitch,float distance,float panX,float panY);
}
