#pragma once
#include "ImagePipeline.h"
#include <array>
namespace self {
struct Vertex {float x,y,z,nx,ny,nz,u,v;};
struct Asset {std::vector<Vertex> vertices;std::vector<uint32_t> indices;Image image;bool photo=false;};
Asset loadGLB(const std::vector<uint8_t>& bytes);
Asset photoAsset(const std::vector<uint8_t>& bytes);
}
