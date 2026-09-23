#pragma once
#include <spatial/spatial_recon_interface.h>
#include "vendor/json.hpp"
#include <atomic>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace self {
// All signatures come from the installed commercial SDK, not redeclared ABI guesses.
struct SpatialReconApi {
    decltype(&HMS_SpatialRecon_IsSupport) support = nullptr;
    decltype(&HMS_SpatialRecon_CreateSession) create = nullptr;
    decltype(&HMS_SpatialRecon_DestroySession) destroy = nullptr;
    decltype(&HMS_SpatialRecon_PushFrame) push = nullptr;
    decltype(&HMS_SpatialRecon_PushARFrame) pushAR = nullptr;
    decltype(&HMS_SpatialRecon_StartSession) start = nullptr;
    decltype(&HMS_SpatialRecon_GetProgress) progress = nullptr;
    decltype(&HMS_SpatialRecon_RegisterNGCallbackFunc) callback = nullptr;
    decltype(&HMS_SpatialRecon_SaveResultToFile) save = nullptr;
    decltype(&HMS_SpatialRecon_SetRunningMode) mode = nullptr;
    decltype(&HMS_SpatialRecon_PauseSession) pause = nullptr;
    decltype(&HMS_SpatialRecon_ResumeSession) resume = nullptr;
    bool loaded = false;
    bool complete() const;
    static SpatialReconApi load();
};

// One owner; serialized commands; callbacks never access this object or a JS environment.
// Completion of SDK reconstruction, file saving, and product acceptance are separate states.
class SpatialReconstruction {
public:
    explicit SpatialReconstruction(SpatialReconApi api = SpatialReconApi::load());
    ~SpatialReconstruction();
    SpatialReconstruction(const SpatialReconstruction&) = delete;
    SpatialReconstruction& operator=(const SpatialReconstruction&) = delete;
    nlohmann::json probe() const;
    nlohmann::json execute(const nlohmann::json&, std::vector<uint8_t> rgb = {});
    // Called synchronously by a native AR capture owner while the AR frame is valid.
    // No raw native handles are accepted from ArkTS.
    void pushARFrame(AREngine_ARSession*, AREngine_ARFrame*, int64_t timestampNs, bool tracking);
private:
    enum class State { Idle, Capturing, Building, Paused, Reconstructed, Saving, Saved, Failed };
    struct Completion { std::atomic<int> result{-1}; };
    static void completed(HMS_SpatialReconStatus, void*);
    void registerCompletion();
    void clearCompletion();
    void refresh();
    void release();
    void require(State, const char*) const;
    void ok(HMS_SpatialReconStatus, const char*);
    void push(const nlohmann::json&, std::vector<uint8_t>);
    nlohmann::json status() const;
    SpatialReconApi api_;
    mutable std::mutex mutex_;
    HMS_SpatialRecon_Session* session_ = nullptr;
    State state_ = State::Idle;
    std::string jobId_, workPath_, outputPath_, error_, inputKind_;
    std::unique_ptr<HMS_SpatialRecon_ModelWriteInfo> write_;
    std::unique_ptr<std::string> writePath_;
    std::shared_ptr<Completion> completion_;
    uintptr_t callbackId_ = 0;
    // RGB ownership is unspecified by PushFrame documentation: retain exact buffers until DestroySession.
    // Prefer PushARFrame in the eventual capture integration, subject to real-device lifetime validation.
    std::vector<std::vector<uint8_t>> frames_;
    std::vector<std::unique_ptr<HMS_SpatialRecon_DataFrame>> frameDescriptors_;
    size_t bytes_ = 0, frameCount_ = 0, memoryBudget_ = 0;
    int width_ = 0, height_ = 0;
    int64_t timestamp_ = 0;
    float progress_ = 0;
    HMS_SpatialReconStage sdkStage_ = SPATIAL_RECON_STAGE_UNKNOWN;
};

nlohmann::json reconstructionProcess(const nlohmann::json&, std::vector<uint8_t> rgb);
}
