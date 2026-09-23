#pragma once
#include "GltfAssetLoader.h"
#include "ProductScene.h"
#include "vendor/json.hpp"
#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <native_window/external_window.h>
#include <native_vsync/native_vsync.h>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <future>
#include <deque>
#include <functional>
#include <atomic>
#include <map>
namespace self {
using Json=nlohmann::json;
struct Result {Json data=Json::object();std::vector<uint8_t> bytes;std::vector<Image> images;};
class RendererSession {
 public:
 RendererSession();~RendererSession();
 std::future<Result> submit(Json request,std::vector<uint8_t> bytes={});
 Result process(Json request,std::vector<uint8_t> bytes); // Called on the N-API worker, never the UI thread.
 void attach(OHNativeWindow* window);void detach();void resize(int width,int height);
 void silenceEvents();
 std::function<void(const Json&)> event;
 private:
 struct Job {std::function<Result()> run;std::promise<Result> promise;};
 std::future<Result> enqueue(std::function<Result()> run);
 void loop();Result execute(const Json&,const std::vector<uint8_t>&);
 void initialize(OHNativeWindow*);void clearGL();void upload();void draw(bool original=false,int width=0,int height=0);void schedule();
 void animateCommit(const Image& previous);void drawTransition();
 Image readFrame(int width,int height,bool original=false);Result probe();
 std::vector<uint8_t> select(const Json& polygon);void prepare(const Json&);
 std::array<float,16> matrix(int width,int height) const;
 static void vsyncCallback(long long,void*);
 std::thread thread_;std::mutex mutex_;std::condition_variable wake_;std::deque<std::shared_ptr<Job>> jobs_;bool stopping_=false,tick_=false;
 OH_NativeVSync* vsync_=nullptr;bool scheduled_=false,dirty_=false,foreground_=true,orbit_=false;double orbitPhase_=0;float orbitYaw_=0,orbitPitch_=0;
 EGLDisplay display_=EGL_NO_DISPLAY;EGLContext context_=EGL_NO_CONTEXT;EGLSurface surface_=EGL_NO_SURFACE;OHNativeWindow* window_=nullptr;
 GLuint program_=0,backgroundProgram_=0,vao_=0,vbo_=0,ebo_=0,texture_=0,maskArray_=0,protection_=0,annotation_=0;
 GLuint transitionProgram_=0,transitionTexture_=0;bool transitioning_=false;double transitionStart_=0;uint64_t transitionFrames_=0;
 std::array<float,3> paletteWeights_{{1,0,0}};
 bool viewReset_=false;float viewResetElapsed_=0;std::array<float,5> viewResetFrom_{};
 bool motion_=false;int palette_=0;float phase_=0;long long lastAnimatedDraw_=0,nextAnimatedDraw_=0;
 int width_=1,height_=1,auditMode_=0;uint64_t generation_=0,frameCount_=0;std::vector<double> frameTimes_,frameIntervals_;long long lastPresented_=0;
 Asset asset_;std::map<std::string,std::vector<uint8_t>> masks_;Json operations_=Json::array(),anchors_=Json::array();std::string protectId_,protectRule_,tool_="NAVIGATE";
 ProductScene product_;bool productMode_=false;
 std::map<std::string,std::vector<uint8_t>> featherMasks_;std::array<std::string,16> uploadedMasks_{};std::string uploadedProtection_="__uninitialized";
 float yaw_=0,pitch_=0,distance_=16,panX_=0,panY_=0;bool hasAsset_=false;Json lastInfo_;
};
}
