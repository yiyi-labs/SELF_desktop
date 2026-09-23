#pragma once
#include "vendor/json.hpp"
#include <vector>
#include <cstdint>
namespace self {
// CPU-only, device-local camera operations. Serialized independently of rendering.
nlohmann::json cameraProcess(const nlohmann::json& request, const std::vector<uint8_t>& rgba);
}
