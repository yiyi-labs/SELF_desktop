#include <spatial/spatial_recon_interface.h>
#include <syscap_ndk.h>
#include <dlfcn.h>
#include <iostream>
#include "vendor/json.hpp"

// Diagnostic only: no camera, reconstruction session, images or network calls.
// A shell-process load failure is not proof that the app namespace cannot load it.
int main() {
    using Json = nlohmann::json;
    Json caps = Json::object();
    for (const auto* cap : {"SystemCapability.Graphics.SpatialRecon",
                           "SystemCapability.Graphics.SpatialRender",
                           "SystemCapability.Graphics.SpatialEdit"}) {
        caps[cap] = canIUse(cap);
    }
    Json recon{{"libraryLoaded", false}, {"isSupportCalled", false},
               {"isSupportStatus", nullptr}, {"gsSupportedByQuery", nullptr},
               {"allSelfApi26Symbols", false}, {"symbols", Json::object()}};
    dlerror();
    void* library = dlopen("libspatial_recon_ndk.z.so", RTLD_NOW | RTLD_LOCAL);
    recon["libraryLoaded"] = library != nullptr;
    if (!library) {
        const char* error = dlerror();
        recon["loadError"] = error ? error : "Unknown loader error";
    } else {
        bool complete = true;
        for (const auto* symbol : {"HMS_SpatialRecon_IsSupport", "HMS_SpatialRecon_CreateSession",
                "HMS_SpatialRecon_DestroySession", "HMS_SpatialRecon_PushFrame",
                "HMS_SpatialRecon_PushARFrame", "HMS_SpatialRecon_StartSession",
                "HMS_SpatialRecon_GetProgress", "HMS_SpatialRecon_RegisterNGCallbackFunc",
                "HMS_SpatialRecon_SaveResultToFile", "HMS_SpatialRecon_SetRunningMode",
                "HMS_SpatialRecon_PauseSession", "HMS_SpatialRecon_ResumeSession"}) {
            const bool present = dlsym(library, symbol) != nullptr;
            recon["symbols"][symbol] = present;
            complete = complete && present;
        }
        recon["allSelfApi26Symbols"] = complete;
        const auto support = reinterpret_cast<decltype(&HMS_SpatialRecon_IsSupport)>(
            dlsym(library, "HMS_SpatialRecon_IsSupport"));
        if (support) {
            const int result = support(SPATIAL_RECON_MODEL_TYPE_GS);
            recon["isSupportCalled"] = true;
            recon["isSupportStatus"] = result;
            recon["gsSupportedByQuery"] = result == SPATIAL_RECON_STATUS_SUCCESS;
        }
        dlclose(library);
    }
    Json report{{"probe", "commercial-sdk-capabilities"}, {"executionContext", "hdc-shell"},
                {"declaredCapabilities", caps}, {"reconstruction", recon},
                {"renderingExecuted", false}, {"editingExecuted", false},
                {"reconstructionExecuted", false}, {"personalReconstructionValidated", false}};
    std::cout << "SELF_SPATIAL_CAPABILITY=" << report.dump() << std::endl;
    return 0; // Successful diagnosis does not mean a capability is supported.
}
