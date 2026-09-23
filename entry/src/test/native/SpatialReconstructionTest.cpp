#include "SpatialReconstruction.h"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <unistd.h>
#include <thread>
using namespace self;
using Json = nlohmann::json;
namespace {
struct Fake {
    HMS_SpatialReconNGCallbackFunc callback = nullptr;
    void* data = nullptr;
    int calls = 0, pushes = 0, destroys = 0, registrations = 0;
    int createCode = 0, pushCode = 0, startCode = 0, saveCode = 0, destroyCode = 0;
    bool writeFile = true;
    HMS_SpatialRecon_ModelWriteInfo* write = nullptr;
    HMS_SpatialRecon_DataFrame* lastFrame = nullptr;
    void finish(int code = 0) { auto fn = callback; auto ptr = data; callback = nullptr; data = nullptr; if (fn) fn(static_cast<HMS_SpatialReconStatus>(code), ptr); }
} fake;
HMS_SpatialReconStatus status(int n) { return static_cast<HMS_SpatialReconStatus>(n); }
SpatialReconApi api() {
    SpatialReconApi a; a.loaded = true;
    a.support = [](HMS_SpatialReconModelType) { return status(0); };
    a.create = [](HMS_SpatialReconModelType, const char*, HMS_SpatialRecon_Session** out) { ++fake.calls; if (!fake.createCode) *out = reinterpret_cast<HMS_SpatialRecon_Session*>(1); return status(fake.createCode); };
    a.destroy = [](HMS_SpatialRecon_Session*) { ++fake.destroys; return status(fake.destroyCode); };
    a.push = [](HMS_SpatialRecon_Session*, HMS_SpatialRecon_DataFrame* f) { ++fake.pushes; fake.lastFrame = f; return status(fake.pushCode); };
    a.pushAR = [](HMS_SpatialRecon_Session*, AREngine_ARSession*, AREngine_ARFrame*) { ++fake.pushes; return status(fake.pushCode); };
    a.callback = [](HMS_SpatialRecon_Session*, HMS_SpatialReconNGCallbackFunc fn, void* data) { ++fake.registrations; fake.callback = fn; fake.data = data; return status(0); };
    a.start = [](HMS_SpatialRecon_Session*, HMS_SpatialRecon_ModelWriteInfo* w, HMS_SpatialReconCallbackFunc) { if (w) throw std::runtime_error("Reconstruction and save must be separate"); return status(fake.startCode); };
    a.progress = [](HMS_SpatialRecon_Session*, float* p, HMS_SpatialReconStage* s) { *p = 1; *s = SPATIAL_RECON_STAGE_FINISHED; return status(0); };
    a.save = [](HMS_SpatialRecon_Session*, HMS_SpatialRecon_ModelWriteInfo* w, HMS_SpatialReconCallbackFunc) { fake.write = w; if (fake.writeFile) std::ofstream(w->modelFile) << "synthetic test output; not a reconstructed face"; return status(fake.saveCode); };
    a.mode = [](HMS_SpatialRecon_Session*, HMS_SpatialReconRunningMode) { return status(0); };
    a.pause = [](HMS_SpatialRecon_Session*) { return status(0); };
    a.resume = [](HMS_SpatialRecon_Session*) { return status(0); };
    return a;
}
void check(bool value, const char* why) { if (!value) throw std::runtime_error(why); }
template<class F> void rejects(F run) { bool failed = false; try { run(); } catch (const std::exception&) { failed = true; } check(failed, "Expected rejection"); }
Json command(const char* op, const std::string& id) { return {{"op", op}, {"jobId", id}}; }
Json frame(const std::string& id, int i) {
    return {{"op", "push"}, {"jobId", id}, {"width", 2}, {"height", 2}, {"focalX", 2.0}, {"focalY", 2.0}, {"principalX", 1.0}, {"principalY", 1.0},
        {"distortion", {0,0,0,0,0,0,0,0}}, {"position", {0.01*i,0,0}}, {"rotation", {0,0,0,1}}, {"timestampNs", std::to_string(9007199254740992LL+i)}, {"tracking", true}, {"poseSource", "ar-engine"}};
}
void create(SpatialReconstruction& r, const std::string& root, const std::string& id, int budget = 1024) {
    r.execute({{"op", "create"}, {"root", root}, {"jobId", id}, {"memoryBudgetBytes", budget}});
}
void feed(SpatialReconstruction& r, const std::string& id) { r.execute(frame(id,1), std::vector<uint8_t>(12,17)); r.execute(frame(id,2), std::vector<uint8_t>(12,29)); }
}
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const std::string root = std::filesystem::canonical(argv[1]).string();
    Json results = Json::array(); int failed = 0;
    auto test = [&](const char* name, auto run) { fake = {}; try { run(); results.push_back({{"name",name},{"passed",true}}); } catch(const std::exception& e) { ++failed; results.push_back({{"name",name},{"passed",false},{"error",e.what()}}); } };
    test("missing_runtime_rejects_without_success", [&] { SpatialReconstruction r(SpatialReconApi{}); auto p=r.probe(); check(!p["available"].get<bool>() && !p["pipelineImplemented"].get<bool>(), "Incorrect capability"); rejects([&]{create(r,root,"missing");}); });
    test("missing_api26_callback_is_not_compatible", [&] { auto a=api(); a.callback=nullptr; SpatialReconstruction r(a); check(!r.probe()["available"].get<bool>(), "Partial runtime accepted"); });
    test("start_requires_multiple_frames", [&] { SpatialReconstruction r(api()); create(r,root,"empty"); rejects([&]{r.execute(command("start","empty"));}); });
    test("frame_bytes_and_calibration_preserved", [&] { SpatialReconstruction r(api()); create(r,root,"preserve"); feed(r,"preserve"); check(fake.lastFrame->imageData[0]==29 && fake.lastFrame->focalX==2 && fake.lastFrame->timestamp==9007199254740994LL,"Source changed"); auto s=r.execute(command("status","preserve")); check(s["retainedRgbBytes"]==24 && !s["qualityReduced"].get<bool>(),"Budget/data mismatch"); });
    test("timestamp_precision_and_order", [&] { SpatialReconstruction r(api()); create(r,root,"time"); auto f=frame("time",1); r.execute(f,std::vector<uint8_t>(12)); rejects([&]{r.execute(f,std::vector<uint8_t>(12));}); f["timestampNs"]=42; rejects([&]{r.execute(f,std::vector<uint8_t>(12));}); check(fake.pushes==1,"Invalid frame reached SDK"); });
    test("no_synthetic_landmark_pose", [&] { SpatialReconstruction r(api()); create(r,root,"pose"); auto f=frame("pose",1); f["poseSource"]="face-keypoints"; rejects([&]{r.execute(f,std::vector<uint8_t>(12));}); f["poseSource"]="ar-engine"; f["rotation"]={0,0,0,2}; rejects([&]{r.execute(f,std::vector<uint8_t>(12));}); check(fake.pushes==0,"Bad pose submitted"); });
    test("lost_tracking_not_submitted", [&] { SpatialReconstruction r(api()); create(r,root,"tracking"); auto f=frame("tracking",1); f["tracking"]=false; rejects([&]{r.execute(f,std::vector<uint8_t>(12));}); check(fake.pushes==0,"Lost tracking submitted"); });
    test("memory_limit_never_downscales", [&] { SpatialReconstruction r(api()); create(r,root,"memory",12); r.execute(frame("memory",1),std::vector<uint8_t>(12)); rejects([&]{r.execute(frame("memory",2),std::vector<uint8_t>(12));}); check(fake.pushes==1 && fake.lastFrame->imageWidth==2,"Quality reduced"); });
    test("resolution_change_rejected", [&] { SpatialReconstruction r(api()); create(r,root,"resolution"); r.execute(frame("resolution",1),std::vector<uint8_t>(12)); auto f=frame("resolution",2); f["width"]=3; rejects([&]{r.execute(f,std::vector<uint8_t>(18));}); });
    test("progress_one_is_not_completion", [&] { SpatialReconstruction r(api()); create(r,root,"progress"); feed(r,"progress"); r.execute(command("start","progress")); auto s=r.execute(command("status","progress")); check(s["state"]=="building", "Progress incorrectly accepted"); rejects([&]{r.execute(command("save","progress"));}); });
    test("sdk_completion_and_save_are_separate", [&] { SpatialReconstruction r(api()); create(r,root,"phases"); feed(r,"phases"); r.execute(command("start","phases")); fake.finish(); check(r.execute(command("status","phases"))["state"]=="reconstructed","Completion missing"); r.execute(command("save","phases")); check(fake.registrations==2,"One-shot callback not re-registered"); check(fake.write->modelFormat==SPATIAL_RECON_OUTPUT_FORMAT_PLY,"Incorrect format"); fake.finish(); auto s=r.execute(command("status","phases")); check(s["state"]=="saved-unverified" && !s["acceptedForPortrait"].get<bool>(),"Unvalidated model accepted"); });
    test("callback_error_preserves_failure", [&] { SpatialReconstruction r(api()); create(r,root,"callback-error"); feed(r,"callback-error"); r.execute(command("start","callback-error")); fake.finish(1023700007); check(r.execute(command("status","callback-error"))["state"]=="failed","Error lost"); });
    test("missing_output_not_saved", [&] { SpatialReconstruction r(api()); create(r,root,"no-file"); feed(r,"no-file"); r.execute(command("start","no-file")); fake.finish(); fake.writeFile=false; r.execute(command("save","no-file")); fake.finish(); check(r.execute(command("status","no-file"))["state"]=="failed","Missing file accepted"); });
    test("late_callback_cannot_finish_new_job", [&] { SpatialReconstruction r(api()); create(r,root,"old"); feed(r,"old"); r.execute(command("start","old")); auto late=fake.callback; auto token=fake.data; r.execute(command("cancel","old")); create(r,root,"new"); feed(r,"new"); r.execute(command("start","new")); late(status(0),token); check(r.execute(command("status","new"))["state"]=="building","Late result crossed jobs"); fake.finish(); check(r.execute(command("status","new"))["state"]=="reconstructed","Current callback lost"); });
    test("stale_commands_rejected", [&] { SpatialReconstruction r(api()); create(r,root,"current"); rejects([&]{r.execute(command("cancel","stale"));}); check(r.execute(command("status","current"))["state"]=="capturing","Stale cancel applied"); });
    test("pause_resume_preserve_source", [&] { SpatialReconstruction r(api()); create(r,root,"pause"); feed(r,"pause"); r.execute(command("start","pause")); r.execute(command("pause","pause")); rejects([&]{r.execute(frame("pause",3),std::vector<uint8_t>(12));}); r.execute(command("resume","pause")); auto s=r.execute(command("status","pause")); check(s["state"]=="building" && s["frames"]==2,"Pause changed source"); });
    test("sdk_frame_limit_is_failure_not_truncation", [&] { SpatialReconstruction r(api()); create(r,root,"max"); fake.pushCode=1023700001; rejects([&]{r.execute(frame("max",1),std::vector<uint8_t>(12));}); check(r.execute(command("status","max"))["state"]=="failed","Truncated capture accepted"); rejects([&]{r.execute(command("start","max"));}); });
    test("job_paths_cannot_overwrite", [&] { SpatialReconstruction r(api()); rejects([&]{create(r,root,"../escape");}); create(r,root,"existing"); r.execute(command("close","existing")); rejects([&]{create(r,root,"existing");}); });
    test("creation_failure_can_release", [&] { SpatialReconstruction r(api()); fake.createCode=801; rejects([&]{create(r,root,"create-failed");}); check(r.execute(command("close","create-failed"))["state"]=="idle","Partial creation stuck"); });
    test("native_ar_input_does_not_copy_rgb", [&] { SpatialReconstruction r(api()); create(r,root,"ar"); r.pushARFrame(reinterpret_cast<AREngine_ARSession*>(1),reinterpret_cast<AREngine_ARFrame*>(2),1,true); auto s=r.execute(command("status","ar")); check(s["retainedRgbBytes"]==0 && s["frames"]==1,"AR input duplicated"); rejects([&]{r.execute(frame("ar",2),std::vector<uint8_t>(12));}); });
    test("destruction_failure_retains_borrowed_memory", [&] { SpatialReconstruction r(api()); create(r,root,"destroy"); feed(r,"destroy"); fake.destroyCode=1023700007; rejects([&]{r.execute(command("close","destroy"));}); check(fake.lastFrame->imageData[0]==29,"Borrowed memory released"); check(r.execute(command("status","destroy"))["state"]=="failed","Failed release hidden"); fake.destroyCode=0; check(r.execute(command("close","destroy"))["state"]=="idle","Release retry failed"); });
    test("callback_from_other_thread_is_safe", [&] { SpatialReconstruction r(api()); create(r,root,"thread"); feed(r,"thread"); r.execute(command("start","thread")); auto callback=fake.callback; auto cookie=fake.data; std::thread worker([=]{callback(status(0),cookie);}); worker.join(); check(r.execute(command("status","thread"))["state"]=="reconstructed","Callback lost across threads"); });
    test("invalid_intrinsics_never_reach_sdk", [&] { SpatialReconstruction r(api()); create(r,root,"intrinsics"); auto f=frame("intrinsics",1); f["focalX"]=0; rejects([&]{r.execute(f,std::vector<uint8_t>(12));}); f=frame("intrinsics",1); f["principalY"]=20; rejects([&]{r.execute(f,std::vector<uint8_t>(12));}); check(fake.pushes==0,"Invalid calibration submitted"); });
    // Real dynamic loading probe, separate from injected SDK behavior tests.
    SpatialReconstruction real;
    Json report{{"environment","HarmonyOS native executable"},{"contractTestsUseInjectedSdk",true},{"personalReconstructionValidated",false},
        {"runtimeProbe",real.probe()},{"tests",results},{"passed",results.size()-failed},{"failed",failed}};
    std::cout<<report.dump(2)<<std::endl; return failed ? 1 : 0;
}
