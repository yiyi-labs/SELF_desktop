#include "CameraPipeline.h"
#include "vendor/libfacedetection/facedetectcnn.h"
#define H264E_MAX_THREADS 0
#include "vendor/minih264/minih264e.h"
#include "vendor/minimp4/minimp4.h"
#include <mutex>
#include <memory>
#include <chrono>
#include <cmath>
#include <unistd.h>
#include <sys/stat.h>
#include <stdexcept>
#include <algorithm>

namespace self {
namespace {
using Json = nlohmann::json;
std::mutex cameraMutex;
void check(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
uint8_t byte(int value) { return static_cast<uint8_t>(std::clamp(value, 0, 255)); }
struct Recording {
    FILE* file = nullptr;
    MP4E_mux_t* mux = nullptr;
    mp4_h26x_writer_t writer{};
    void* persistent = nullptr;
    void* scratch = nullptr;
    std::vector<uint8_t> yuv, pending;
    int width = 0, height = 0, frames = 0, stride = 0, chromaStride = 0;
    int64_t firstTime = 0, pendingTime = 0, duration = 0;
    ~Recording() { close(); }
    void close() {
        if (mux) { MP4E_close(mux); mux = nullptr; }
        mp4_h26x_write_close(&writer); writer = {};
        if (file) { fclose(file); file = nullptr; }
        free(persistent); persistent = nullptr; free(scratch); scratch = nullptr;
    }
    static int write(int64_t offset, const void* bytes, size_t size, void* token) {
        FILE* out = static_cast<FILE*>(token);
        return fseeko(out, offset, SEEK_SET) || fwrite(bytes, 1, size, out) != size;
    }
    void open(int fd, int w, int h) {
        check(w >= 64 && h >= 64 && w <= 1280 && h <= 1280 && !(w & 1) && !(h & 1), "Invalid video dimensions");
        struct stat stat{}; check(fstat(fd, &stat) == 0 && S_ISREG(stat.st_mode), "Video requires private regular file");
        width = w; height = h;
        H264E_create_param_t p{}; p.width = w; p.height = h; p.gop = 20;
        p.const_input_flag = 1; p.num_layers = 1; p.enableNEON = 1;
        int a = 0, b = 0; check(H264E_sizeof(&p, &a, &b) == 0, "Encoder configuration failed");
        check(posix_memalign(&persistent, 64, a) == 0 && posix_memalign(&scratch, 64, b) == 0, "Encoder allocation failed");
        check(H264E_init(static_cast<H264E_persist_t*>(persistent), &p) == 0, "Encoder initialization failed");
        int copy = dup(fd); check(copy >= 0, "Video descriptor failed");
        file = fdopen(copy, "wb"); if (!file) { ::close(copy); throw std::runtime_error("Video file failed"); }
        mux = MP4E_open(0, 0, file, write); check(mux != nullptr, "MP4 initialization failed");
        check(mp4_h26x_write_init(&writer, mux, w, h, 0) == 0, "MP4 video track failed");
        stride = (w + 15) & ~15; chromaStride = (w / 2 + 15) & ~15;
        yuv.resize(stride * h + chromaStride * h);
    }
    void flush(int64_t next) {
        if (pending.empty()) return;
        // Actual capture intervals, not an invented constant frame rate.
        int64_t ms = std::clamp<int64_t>(next - pendingTime, 1, 30000);
        check(mp4_h26x_write_nal(&writer, pending.data(), pending.size(), ms * 90) == 0, "MP4 sample write failed");
        duration += ms; pending.clear();
    }
    void frame(const std::vector<uint8_t>& rgba, int w, int h, int64_t now) {
        check(w == width && h == height, "Camera orientation changed during capture; start a new clip");
        if (frames) check(now > pendingTime && now - firstTime <= 32000, "Invalid capture timestamp");
        auto* y = yuv.data(); auto* u = y + stride * h; auto* v = u + chromaStride * h / 2;
        for (int row = 0; row < h; ++row) for (int col = 0; col < w; ++col) {
            const auto* p = &rgba[(row * w + col) * 4];
            y[row * stride + col] = byte(((66 * p[0] + 129 * p[1] + 25 * p[2] + 128) >> 8) + 16);
        }
        for (int row = 0; row < h; row += 2) for (int col = 0; col < w; col += 2) {
            int r = 0, g = 0, b = 0;
            for (int dy = 0; dy < 2; ++dy) for (int dx = 0; dx < 2; ++dx) {
                auto* p = &rgba[((row + dy) * w + col + dx) * 4]; r += p[0]; g += p[1]; b += p[2];
            }
            r /= 4; g /= 4; b /= 4;
            u[row / 2 * chromaStride + col / 2] = byte(((-38 * r - 74 * g + 112 * b + 128) >> 8) + 128);
            v[row / 2 * chromaStride + col / 2] = byte(((112 * r - 94 * g - 18 * b + 128) >> 8) + 128);
        }
        H264E_io_yuv_t in{{y, u, v}, {stride, chromaStride, chromaStride}};
        H264E_run_param_t p{}; p.encode_speed = H264E_SPEED_FASTEST;
        p.desired_frame_bytes = 60000; p.qp_min = 16; p.qp_max = 28;
        unsigned char* out = nullptr; int size = 0;
        check(H264E_encode(static_cast<H264E_persist_t*>(persistent), static_cast<H264E_scratch_t*>(scratch), &p, &in, &out, &size) == 0 && size > 0, "Video encoding failed");
        flush(now); pending.assign(out, out + size); pendingTime = now; if (!frames) firstTime = now; ++frames;
    }
    Json finish(int64_t now) {
        check(frames >= 2, "Capture too short; no video saved"); flush(now);
        int closeResult = MP4E_close(mux); mux = nullptr; check(closeResult == 0, "MP4 finalization failed");
        check(fflush(file) == 0 && fsync(fileno(file)) == 0, "Video save failed");
        Json result{{"frames", frames}, {"width", width}, {"height", height}, {"durationMs", duration}, {"fps", frames * 1000.0 / duration}};
        close(); return result;
    }
};
std::unique_ptr<Recording> recording;

Json detect(const std::vector<uint8_t>& rgba, int width, int height, int& rawFaces, int& peakScore) {
    // Preserve aspect ratio; bounded CPU inference. No identity embeddings or network.
    double factor = std::min(1.0, 400.0 / std::max(width, height));
    int w = std::max(32, int(width * factor)), h = std::max(32, int(height * factor));
    std::vector<uint8_t> bgr(w * h * 3);
    for (int y = 0; y < h; ++y) for (int x = 0; x < w; ++x) {
        auto* src = &rgba[(std::min(height - 1, y * height / h) * width + std::min(width - 1, x * width / w)) * 4];
        auto* dst = &bgr[(y * w + x) * 3]; dst[0] = src[2]; dst[1] = src[1]; dst[2] = src[0];
    }
    alignas(64) unsigned char buffer[FACEDETECTION_RESULT_BUFFER_SIZE]{};
    int* result = facedetect_cnn(buffer, bgr.data(), w, h, w * 3);
    Json faces = Json::array();
    rawFaces = result ? result[0] : 0;
    peakScore = 0;
    if (result) for (int i = 0; i < std::min(result[0], 32); ++i) {
        const short* p = reinterpret_cast<const short*>(buffer + 4) + i * FACEDETECTION_RESULT_STRIDE_SHORTS;
        peakScore = std::max(peakScore, int(p[0]));
        if (p[0] < 80 || p[3] < 20 || p[4] < 20) continue;
        Json landmarks = Json::array();
        for (int k = 0; k < 5; ++k) landmarks.push_back({{"x", double(p[5 + 2 * k]) / w}, {"y", double(p[6 + 2 * k]) / h}});
        faces.push_back({{"confidence", p[0] / 100.0}, {"x", double(p[1]) / w}, {"y", double(p[2]) / h}, {"width", double(p[3]) / w}, {"height", double(p[4]) / h}, {"landmarks", landmarks}});
    }
    return faces;
}
}
nlohmann::json cameraProcess(const Json& request, const std::vector<uint8_t>& rgba) {
    std::lock_guard<std::mutex> lock(cameraMutex);
    const auto op = request.at("op").get<std::string>();
    if (op == "cancel") { recording.reset(); return {{"cancelled", true}}; }
    if (op == "start") {
        check(!recording, "Already recording"); auto next = std::make_unique<Recording>();
        next->open(request.at("fd"), request.at("width"), request.at("height")); recording = std::move(next);
        return {{"started", true}};
    }
    if (op == "stop") {
        check(recording != nullptr, "Not recording");
        auto completed = std::move(recording); return completed->finish(request.at("timestamp"));
    }
    check(op == "frame", "Unknown camera operation");
    int w = request.at("width"), h = request.at("height");
    check(w >= 32 && h >= 32 && w <= 1280 && h <= 1280 && rgba.size() == size_t(w) * h * 4, "Invalid camera RGBA buffer");
    auto start = std::chrono::steady_clock::now();
    if (request.value("record", false)) { check(recording != nullptr, "Capture session ended"); recording->frame(rgba, w, h, request.at("timestamp")); }
    int rawFaces = 0, peakScore = 0;
    Json faces = request.value("detect", true) ? detect(rgba, w, h, rawFaces, peakScore) : Json::array();
    return {{"faces", faces}, {"rawFaces", rawFaces}, {"peakScore", peakScore}, {"processingMs", std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count()}, {"frames", recording ? recording->frames : 0}};
}
}

