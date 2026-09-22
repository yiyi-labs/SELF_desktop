#pragma once
#include "GltfAssetLoader.h"
#include <GLES3/gl3.h>
#include <array>
namespace self {
// Separate display-only scene. Never reads/writes facial masks, plans or bills.
class ProductScene {
 public:
 void load(const Asset& asset,bool lid);
 void clear();
 void view(float yaw,float pitch);
 void open(bool open,bool motion,int direction);
 void stop();
 void draw(int width,int height);
 bool animating() const{return animating_;}
 bool ready() const{return parts_[0].count&&parts_[1].count;}
 float progress() const{return progress_;}
 uint64_t animationFrames() const{return animationFrames_;}
 private:
 struct Part {GLuint vao=0,vbo=0,ibo=0,texture=0;GLsizei count=0;};
 std::array<Part,2> parts_{};
 GLuint program_=0,sampler_=0;
 float yaw_=0,pitch_=-.14f,progress_=0,from_=0,target_=0;
 float minY_=0,maxY_=0,radius_=1;
 double started_=0;
 bool animating_=false;
 int direction_=1;
 uint64_t animationFrames_=0;
};
}
