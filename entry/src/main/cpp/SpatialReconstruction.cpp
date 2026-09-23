#include "SpatialReconstruction.h"
#include <dlfcn.h>
#include <cmath>
#include <climits>
#include <filesystem>
#include <map>
#include <limits>
#include <stdexcept>
#include <sys/statvfs.h>

namespace self {
namespace {
using Json = nlohmann::json;
// Opaque monotonic cookies, never object addresses. Late callbacks cannot refer to a new job.
struct CallbackRegistry {
    std::mutex mutex;
    std::map<uintptr_t, std::function<void(int)>> callbacks;
    uintptr_t next = 1;
};
CallbackRegistry& registry() {
    // Survives static destruction if an SDK destroy fails during process teardown.
    static auto* value = new CallbackRegistry; return *value;
}
void check(bool value, const std::string& message) { if (!value) throw std::runtime_error(message); }
int64_t timestamp(const Json& j) {
    // JS doubles cannot represent all nanosecond timestamps. Require an integer decimal string.
    const auto s = j.at("timestampNs").get<std::string>();
    check(!s.empty() && s.size() <= 19 && s.find_first_not_of("0123456789") == std::string::npos, "Invalid timestampNs");
    size_t used = 0; auto n = std::stoll(s, &used); check(n > 0 && used == s.size(), "Invalid timestampNs"); return n;
}
float number(const Json& j, const char* name) {
    check(j.contains(name) && j[name].is_number(), std::string("Missing calibrated ") + name);
    float f = j[name].get<float>(); check(std::isfinite(f), std::string("Invalid ") + name); return f;
}
template<size_t N> void array(const Json& j, const char* key, float (&out)[N]) {
    const auto& a = j.at(key); check(a.is_array() && a.size() == N, std::string("Invalid ") + key);
    for (size_t i = 0; i < N; ++i) { check(a[i].is_number(), "Non-numeric calibration"); out[i] = a[i].get<float>(); check(std::isfinite(out[i]), "Non-finite calibration"); }
}
void storage(const std::string& path, size_t minimum) {
    struct statvfs s{}; check(statvfs(path.c_str(), &s) == 0, "Cannot inspect reconstruction storage");
    check(static_cast<uint64_t>(s.f_bavail) * s.f_frsize >= minimum, "Insufficient storage; quality was not reduced");
}
}

bool SpatialReconApi::complete() const { return support && create && destroy && push && pushAR && start && progress && callback && save && mode && pause && resume; }
SpatialReconApi SpatialReconApi::load() {
    SpatialReconApi a;
    // Keep the optional runtime loaded for the process lifetime: SDK callbacks can be asynchronous.
    static void* library = dlopen("libspatial_recon_ndk.z.so", RTLD_NOW | RTLD_LOCAL);
    a.loaded = library != nullptr; if (!library) return a;
#define RESOLVE(field, symbol) a.field = reinterpret_cast<decltype(a.field)>(dlsym(library, #symbol))
    RESOLVE(support, HMS_SpatialRecon_IsSupport); RESOLVE(create, HMS_SpatialRecon_CreateSession);
    RESOLVE(destroy, HMS_SpatialRecon_DestroySession); RESOLVE(push, HMS_SpatialRecon_PushFrame);
    RESOLVE(pushAR, HMS_SpatialRecon_PushARFrame); RESOLVE(start, HMS_SpatialRecon_StartSession);
    RESOLVE(progress, HMS_SpatialRecon_GetProgress); RESOLVE(callback, HMS_SpatialRecon_RegisterNGCallbackFunc);
    RESOLVE(save, HMS_SpatialRecon_SaveResultToFile); RESOLVE(mode, HMS_SpatialRecon_SetRunningMode);
    RESOLVE(pause, HMS_SpatialRecon_PauseSession); RESOLVE(resume, HMS_SpatialRecon_ResumeSession);
#undef RESOLVE
    return a;
}
SpatialReconstruction::SpatialReconstruction(SpatialReconApi api) : api_(api) {}
SpatialReconstruction::~SpatialReconstruction() {
    try { release(); } catch (...) {
        // Do not free memory still potentially borrowed by a failed SDK destroy.
        // This exceptional quarantine lasts until process exit and does not fake successful cleanup.
        (void)new std::vector<std::vector<uint8_t>>(std::move(frames_));
        (void)new std::vector<std::unique_ptr<HMS_SpatialRecon_DataFrame>>(std::move(frameDescriptors_));
        (void)write_.release(); (void)writePath_.release();
    }
}
Json SpatialReconstruction::probe() const {
    const int code = api_.complete() ? api_.support(SPATIAL_RECON_MODEL_TYPE_GS) : -1;
    return {{"libraryLoaded", api_.loaded}, {"api26Symbols", api_.complete()}, {"status", code}, {"available", code == 0},
        {"nativeSessionImplemented", true}, {"captureIntegrated", false}, {"gsAcceptanceVerified", false}, {"pipelineImplemented", false},
        {"qualityPolicy", "preserve-source-no-decimation-no-early-success"},
        {"message", code == 0 ? "设备支持空间重建；原生任务已实现，AR采集与个人模型验收尚未接通。" : "当前设备未通过空间重建能力检查；不会用示例面容代替你的建模结果。"}};
}
void SpatialReconstruction::ok(HMS_SpatialReconStatus s, const char* action) {
    if (s != SPATIAL_RECON_STATUS_SUCCESS) throw std::runtime_error(std::string(action) + " failed (" + std::to_string(s) + ")");
}
void SpatialReconstruction::require(State state, const char* action) const { check(state_ == state, std::string("Invalid reconstruction stage for ") + action); }
void SpatialReconstruction::completed(HMS_SpatialReconStatus status, void* data) {
    const uintptr_t id = reinterpret_cast<uintptr_t>(data);
    auto& r = registry(); std::lock_guard<std::mutex> lock(r.mutex);
    auto it = r.callbacks.find(id); if (it == r.callbacks.end()) return;
    it->second(status); r.callbacks.erase(it);
}
void SpatialReconstruction::clearCompletion() {
    if (callbackId_) { auto& r = registry(); std::lock_guard<std::mutex> lock(r.mutex); r.callbacks.erase(callbackId_); }
    callbackId_ = 0; completion_.reset();
}
void SpatialReconstruction::registerCompletion() {
    clearCompletion(); completion_ = std::make_shared<Completion>();
    {
        auto& r = registry(); std::lock_guard<std::mutex> lock(r.mutex);
        check(r.next != std::numeric_limits<uintptr_t>::max(), "Callback generation exhausted");
        callbackId_ = r.next++;
        std::weak_ptr<Completion> weak = completion_;
        r.callbacks.emplace(callbackId_, [weak](int result) { if (auto state = weak.lock()) state->result.store(result, std::memory_order_release); });
    }
    try { ok(api_.callback(session_, completed, reinterpret_cast<void*>(callbackId_)), "Register completion"); }
    catch (...) { clearCompletion(); throw; }
}
void SpatialReconstruction::refresh() {
    if (!session_) return;
    if (state_ == State::Building || state_ == State::Paused || state_ == State::Saving) {
        float p = 0; HMS_SpatialReconStage stage = SPATIAL_RECON_STAGE_UNKNOWN;
        auto s = api_.progress(session_, &p, &stage);
        if (s == SPATIAL_RECON_STATUS_SUCCESS || s == SPATIAL_RECON_STATUS_STAGE_BUILDING) {
            if (std::isfinite(p) && p >= 0 && p <= 1) progress_ = p;
            sdkStage_ = stage;
        }
    }
    if (!completion_) return;
    const int result = completion_->result.load(std::memory_order_acquire); if (result < 0) return;
    clearCompletion();
    if (result != 0) { state_ = State::Failed; error_ = "SDK completion failed (" + std::to_string(result) + ")"; return; }
    if (state_ == State::Building || state_ == State::Paused) state_ = State::Reconstructed;
    else if (state_ == State::Saving) {
        // SDK success is not geometric/visual validation. Preserve the original work until acceptance.
        std::error_code ec; auto size = std::filesystem::file_size(outputPath_, ec);
        if (ec || size == 0) { state_ = State::Failed; error_ = "SDK save returned success without a nonempty model"; }
        else state_ = State::Saved;
    }
}
void SpatialReconstruction::release() {
    clearCompletion();
    // Retain buffers if destruction fails: SDK may still hold their pointers.
    if (session_) {
        const auto result = api_.destroy(session_);
        if (result != SPATIAL_RECON_STATUS_SUCCESS) { state_ = State::Failed; error_ = "Destroy failed; resources retained (" + std::to_string(result) + ")"; throw std::runtime_error(error_); }
        session_ = nullptr;
    }
    write_.reset(); writePath_.reset();
    frameDescriptors_.clear(); frames_.clear(); bytes_ = frameCount_ = 0; width_ = height_ = 0; timestamp_ = 0;
    state_ = State::Idle; progress_ = 0; sdkStage_ = SPATIAL_RECON_STAGE_UNKNOWN;
    jobId_.clear(); error_.clear(); workPath_.clear(); outputPath_.clear(); inputKind_.clear();
}
Json SpatialReconstruction::status() const {
    static const char* names[] = {"idle", "capturing", "building", "paused", "reconstructed", "saving", "saved-unverified", "failed"};
    return {{"jobId", jobId_}, {"state", names[static_cast<int>(state_)]}, {"sdkStage", sdkStage_}, {"progress", progress_},
        {"frames", frameCount_}, {"retainedRgbBytes", bytes_}, {"width", width_}, {"height", height_},
        {"error", error_}, {"modelPath", state_ == State::Saved ? outputPath_ : ""}, {"acceptedForPortrait", false},
        {"qualityReduced", false}};
}
void SpatialReconstruction::push(const Json& j, std::vector<uint8_t> rgb) {
    require(State::Capturing, "push frame"); check(inputKind_.empty() || inputKind_ == "rgb", "Cannot mix AR and calibrated RGB frames");
    check(j.value("tracking", false), "Tracking unavailable; reacquire before capture");
    check(j.value("poseSource", "") == "ar-engine", "Synthetic/landmark poses are not reconstruction input");
    HMS_SpatialRecon_DataFrame frame{};
    check(j.at("width").is_number_integer() && j.at("height").is_number_integer(), "Integer image dimensions required");
    frame.imageWidth = j.at("width").get<int>(); frame.imageHeight = j.at("height").get<int>();
    check(frame.imageWidth > 0 && frame.imageHeight > 0, "Invalid image dimensions");
    const uint64_t size = uint64_t(frame.imageWidth) * frame.imageHeight * 3;
    check(size == rgb.size(), "RGB length mismatch");
    check(!width_ || (frame.imageWidth == width_ && frame.imageHeight == height_), "Capture resolution changed; restart without rescaling");
    check(size <= memoryBudget_ && bytes_ <= memoryBudget_ - size, "Memory budget reached; quality was not reduced");
    frame.timestamp = timestamp(j); check(frame.timestamp > timestamp_, "Duplicate or out-of-order frame");
    frame.focalX = number(j, "focalX"); frame.focalY = number(j, "focalY");
    frame.principalX = number(j, "principalX"); frame.principalY = number(j, "principalY");
    check(frame.focalX > 0 && frame.focalY > 0 && frame.principalX >= 0 && frame.principalX < frame.imageWidth && frame.principalY >= 0 && frame.principalY < frame.imageHeight, "Invalid calibrated intrinsics");
    array(j, "distortion", frame.distortionCoef); array(j, "position", frame.position); array(j, "rotation", frame.rotation);
    float norm = 0; for (float f : frame.rotation) norm += f * f;
    check(std::abs(norm - 1.0f) <= 0.001f, "Non-unit camera quaternion; calibration was not silently changed");
    storage(workPath_, size);
    frames_.push_back(std::move(rgb)); frame.imageData = frames_.back().data();
    frameDescriptors_.push_back(std::make_unique<HMS_SpatialRecon_DataFrame>(frame));
    const auto result = api_.push(session_, frameDescriptors_.back().get());
    if (result != SPATIAL_RECON_STATUS_SUCCESS) {
        // A rejected frame is not a completed capture; fail the job and keep ownership until destroy.
        bytes_ += size; state_ = State::Failed; error_ = "Push frame failed (" + std::to_string(result) + ")"; throw std::runtime_error(error_);
    }
    bytes_ += size; ++frameCount_; timestamp_ = frame.timestamp; width_ = frame.imageWidth; height_ = frame.imageHeight; inputKind_ = "rgb";
}
void SpatialReconstruction::pushARFrame(AREngine_ARSession* ar, AREngine_ARFrame* frame, int64_t time, bool tracking) {
    std::lock_guard<std::mutex> lock(mutex_); require(State::Capturing, "push AR frame");
    check(ar && frame && tracking && time > timestamp_, "Invalid/non-tracking/out-of-order AR frame");
    check(inputKind_.empty() || inputKind_ == "ar", "Cannot mix input coordinate systems");
    const auto result = api_.pushAR(session_, ar, frame);
    if (result != SPATIAL_RECON_STATUS_SUCCESS) { state_ = State::Failed; error_ = "Push AR frame failed (" + std::to_string(result) + ")"; throw std::runtime_error(error_); }
    ++frameCount_; timestamp_ = time; inputKind_ = "ar";
}
Json SpatialReconstruction::execute(const Json& j, std::vector<uint8_t> rgb) {
    std::lock_guard<std::mutex> lock(mutex_); const auto op = j.at("op").get<std::string>();
    if (op == "probe") return probe();
    if (op == "close" && state_ == State::Idle) return status();
    if (op == "create") {
        require(State::Idle, "create"); check(api_.complete(), "API26 SpatialRecon runtime unavailable");
        ok(api_.support(SPATIAL_RECON_MODEL_TYPE_GS), "Device support");
        const auto root = j.at("root").get<std::string>(); const auto id = j.at("jobId").get<std::string>();
        check(!id.empty() && id.size() <= 80 && id.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-") == std::string::npos, "Invalid job ID");
        check(!root.empty() && root.front() == '/' && root.find("/../") == std::string::npos, "Invalid app files directory");
        auto canonical = std::filesystem::canonical(root); check(canonical == std::filesystem::path(root), "Root must be canonical without symlinks");
        const auto base = canonical / "self-reconstruction";
        if (!std::filesystem::exists(base)) std::filesystem::create_directory(base);
        check(!std::filesystem::is_symlink(base) && std::filesystem::is_directory(base), "Invalid job storage");
        const auto work = base / id; check(!std::filesystem::exists(work), "Job already exists; refusing to overwrite a capture");
        const int64_t budget = j.at("memoryBudgetBytes").get<int64_t>();
        check(budget > 0 && budget <= 1024LL * 1024 * 1024, "Invalid explicit memory budget");
        storage(base.string(), 64 * 1024 * 1024); std::filesystem::create_directory(work);
        jobId_ = id; workPath_ = work.string(); memoryBudget_ = budget;
        HMS_SpatialRecon_Session* session = nullptr;
        const auto result = api_.create(SPATIAL_RECON_MODEL_TYPE_GS, work.c_str(), &session);
        if (result != SPATIAL_RECON_STATUS_SUCCESS || !session) {
            session_ = session; state_ = State::Failed;
            throw std::runtime_error("Create reconstruction failed (" + std::to_string(result) + ")");
        }
        session_ = session; state_ = State::Capturing;
    } else {
        check(!jobId_.empty() && j.value("jobId", "") == jobId_, "Stale reconstruction job"); refresh();
        if (op == "push") push(j, std::move(rgb));
        else if (op == "start") {
            require(State::Capturing, "start"); check(frameCount_ >= 2, "Multiple calibrated views required");
            registerCompletion(); state_ = State::Building; progress_ = 0;
            const auto result = api_.start(session_, nullptr, nullptr);
            if (result != SPATIAL_RECON_STATUS_SUCCESS) { clearCompletion(); state_ = State::Failed; error_ = "Start failed (" + std::to_string(result) + ")"; throw std::runtime_error(error_); }
        } else if (op == "save") {
            require(State::Reconstructed, "save"); storage(workPath_, 64 * 1024 * 1024);
            outputPath_ = workPath_ + "/original.ply"; check(!std::filesystem::exists(outputPath_), "Output already exists");
            write_ = std::make_unique<HMS_SpatialRecon_ModelWriteInfo>(); writePath_ = std::make_unique<std::string>(outputPath_);
            write_->modelFile = writePath_->c_str(); write_->modelFormat = SPATIAL_RECON_OUTPUT_FORMAT_PLY;
            registerCompletion(); state_ = State::Saving; progress_ = 0;
            const auto result = api_.save(session_, write_.get(), nullptr);
            if (result != SPATIAL_RECON_STATUS_SUCCESS) { clearCompletion(); state_ = State::Failed; error_ = "Save failed (" + std::to_string(result) + ")"; throw std::runtime_error(error_); }
        } else if (op == "pause") { require(State::Building, "pause"); ok(api_.pause(session_), "Pause"); state_ = State::Paused; }
        else if (op == "resume") { require(State::Paused, "resume"); ok(api_.resume(session_), "Resume"); state_ = State::Building; }
        else if (op == "foreground") {
            check(state_ == State::Building || state_ == State::Paused, "Running mode only applies during reconstruction");
            ok(api_.mode(session_, j.at("value").get<bool>() ? SPATIAL_RECON_RUNNING_FOREGROUND_MODE : SPATIAL_RECON_RUNNING_BACKGROUND_MODE), "Set running mode");
        } else if (op == "cancel" || op == "close") release();
        else check(op == "status", "Unknown reconstruction operation");
    }
    refresh(); return status();
}
Json reconstructionProcess(const Json& j, std::vector<uint8_t> rgb) {
    static SpatialReconstruction session; return session.execute(j, std::move(rgb));
}
}
