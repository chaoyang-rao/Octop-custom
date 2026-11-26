// Octop owns process/window/auth lifecycle; the pinned KuroCat headers own motion.
// Input is consumed locally. Only rendered pixels and aggregate status leave this process.
#include <windows.h>
#include <gdiplus.h>
#include <io.h>
#include <fcntl.h>
#include <atomic>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <thread>
#include "kurocat/windows/src/CatRenderer.hpp"

constexpr UINT CommandMessage = WM_APP + 7;
constexpr int MaxPixels = 1024;
struct Bridge;
static Bridge* active = nullptr;
static std::atomic<bool> running{true};

static bool packet(unsigned char type, const std::vector<unsigned char>& bytes) {
    uint32_t count = static_cast<uint32_t>(bytes.size() + 1);
    return fwrite(&count, 4, 1, stdout) == 1 && fwrite(&type, 1, 1, stdout) == 1
        && fwrite(bytes.data(), 1, bytes.size(), stdout) == bytes.size() && fflush(stdout) == 0;
}
static void event(const std::string& text) {
    if (!packet(2, std::vector<unsigned char>(text.begin(), text.end()))) running = false;
}
static void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }

struct Bridge {
    InputEngine input;
    CatPhysics physics;
    CatSettings settings;
    HWND window = nullptr;
    RECT frame{400, 200, 558, 358};
    int width = 158, height = 158;
    float dpi = 1;
    bool paused = false, dirty = true;
    std::string state = "idle";
    Pt previousHover{};
    bool hasHover = false;
    uint64_t frames = 0;

    Bridge() {
        settings.flipHorizontal = false;
        input.onKeyDown = [this](PhysicalKey key) { if (!paused) physics.triggerKeyDown(key, settings); };
        input.onMouseClick = [this](int button, bool down) { if (!paused) physics.triggerMouseClick(button, down, settings); };
    }
    RECT canvasFrame() const {
        const float margin = 3 * dpi;
        const float fit = std::max(0.01f, std::min((width - margin * 2) / 360.0f, (height - margin * 2) / 320.0f));
        const float sx = float(frame.right - frame.left) / width, sy = float(frame.bottom - frame.top) / height;
        LONG x = frame.left + LONG((width - fit * 360) * 0.5f * sx);
        LONG y = frame.top + LONG((height - fit * 320) * 0.5f * sy);
        return RECT{x, y, x + LONG(fit * 360 * sx), y + LONG(fit * 320 * sy)};
    }
    std::unique_ptr<Gdiplus::Bitmap> bitmap() const {
        auto image = std::make_unique<Gdiplus::Bitmap>(width, height, PixelFormat32bppPARGB);
        Gdiplus::Graphics g(image.get());
        g.SetCompositingMode(Gdiplus::CompositingModeSourceCopy);
        g.Clear(Gdiplus::Color(0, 0, 0, 0));
        g.SetCompositingMode(Gdiplus::CompositingModeSourceOver);
        const float margin = 3 * dpi;
        const float fit = std::max(0.01f, std::min((width - margin * 2) / 360.0f, (height - margin * 2) / 320.0f));
        g.TranslateTransform((width - fit * 360) / 2, (height - fit * 320) / 2);
        g.ScaleTransform(fit, fit);
        CatRenderer::draw(g, physics, settings, builtInSkin(CatCoatTheme::ClassicBlack));
        if (state != "idle") {
            Gdiplus::SolidBrush brush(state == "error" ? Gdiplus::Color(255, 235, 70, 70)
                : state == "success" ? Gdiplus::Color(255, 70, 190, 100) : Gdiplus::Color(255, 65, 140, 240));
            g.FillEllipse(&brush, 310.0f, 290.0f, 6.0f, 6.0f);
        }
        return image;
    }
    std::vector<unsigned char> pixels(Gdiplus::Bitmap& image) const {
        Gdiplus::BitmapData data{};
        Gdiplus::Rect rect(0, 0, width, height);
        require(image.LockBits(&rect, Gdiplus::ImageLockModeRead, PixelFormat32bppPARGB, &data) == Gdiplus::Ok, "bitmap_lock");
        std::vector<unsigned char> rgba(size_t(width) * height * 4);
        for (int y = 0; y < height; ++y) {
            const auto* row = static_cast<const unsigned char*>(data.Scan0) + y * data.Stride;
            for (int x = 0; x < width; ++x) {
                const auto* b = row + x * 4; auto* out = rgba.data() + (size_t(y) * width + x) * 4;
                const unsigned int a = b[3];
                out[0] = a ? static_cast<unsigned char>(std::min(255u, unsigned(b[2]) * 255 / a)) : 0;
                out[1] = a ? static_cast<unsigned char>(std::min(255u, unsigned(b[1]) * 255 / a)) : 0;
                out[2] = a ? static_cast<unsigned char>(std::min(255u, unsigned(b[0]) * 255 / a)) : 0;
                out[3] = static_cast<unsigned char>(a);
            }
        }
        image.UnlockBits(&data);
        return rgba;
    }
    void render() {
        auto image = bitmap(); auto rgba = pixels(*image);
        std::vector<unsigned char> body(8 + rgba.size());
        const uint32_t w = width, h = height;
        memcpy(body.data(), &w, 4); memcpy(body.data() + 4, &h, 4);
        memcpy(body.data() + 8, rgba.data(), rgba.size());
        if (!packet(1, body)) running = false;
        ++frames; dirty = false;
    }
    void stats() const {
        event("{\"type\":\"stats\",\"keyboardEvents\":" + std::to_string(input.totalKeystrokesToday)
            + ",\"frames\":" + std::to_string(frames) + ",\"held\":" + std::to_string(input.activeKeys.size()) + "}");
    }
    void command(const std::string& line) {
        std::istringstream value(line); std::string op; value >> op;
        if (op == "quit") { running = false; return; }
        if (op == "frame") {
            int x, y, w, h, pw, ph; float scale;
            if (!(value >> x >> y >> w >> h >> pw >> ph >> scale) || w < 1 || h < 1 || w > 8192 || h > 8192
                || pw < 32 || ph < 32 || pw > MaxPixels || ph > MaxPixels || !std::isfinite(scale) || scale < 0.5f || scale > 4) return;
            frame = RECT{x, y, x + w, y + h}; width = pw; height = ph; dpi = scale; dirty = true;
        } else if (op == "pause") {
            int flag; if (!(value >> flag)) return; paused = flag != 0;
            if (paused) { input.resetAllState(); physics.setDragging(false); } dirty = true;
        } else if (op == "drag") {
            int flag; float dx, dy;
            if (value >> flag >> dx >> dy) physics.setDragging(settings.enableDragAnimation && !paused && flag, dx, dy);
        } else if (op == "hover") {
            Pt point; if (!(value >> point.x >> point.y) || paused) return;
            if (point.x < 0 || point.y < 0) { hasHover = false; return; }
            const auto zone = CatRenderer::hitTest(point, physics, builtInSkin(CatCoatTheme::ClassicBlack));
            physics.updateTailHover(&point);
            if (zone == CatHitZone::Head || zone == CatHitZone::Body) {
                if (hasHover) {
                    float distance = std::hypot(point.x - previousHover.x, point.y - previousHover.y);
                    if (distance > 1.2f && distance < 80) physics.registerPetStroke(point, distance, zone == CatHitZone::Head, settings);
                }
                previousHover = point; hasHover = true;
            } else hasHover = false;
        } else if (op == "motion") {
            std::string name; int flag; if (!(value >> name >> flag)) return;
            bool enabled = flag != 0;
            if (name == "petInteraction") settings.petInteraction = enabled;
            else if (name == "footEasterEgg") settings.footEasterEgg = enabled;
            else if (name == "tailEasterEgg") settings.tailEasterEgg = enabled;
            else if (name == "keyboardMarquee") settings.keyboardMarquee = enabled;
            else if (name == "enableAnger") settings.enableAnger = enabled;
            else if (name == "enableDragAnimation") { settings.enableDragAnimation = enabled; if (!enabled) physics.setDragging(false); }
            dirty = true;
        } else if (op == "state") {
            value >> state; dirty = true;
        } else if (op == "stats") stats();
    }
};

static LRESULT CALLBACK sinkProc(HWND window, UINT message, WPARAM wParam, LPARAM lParam) {
    if (message == WM_INPUT && active) active->input.handleRawInput(lParam);
    if (message == CommandMessage) {
        std::unique_ptr<std::string> line(reinterpret_cast<std::string*>(lParam));
        if (active && line) active->command(*line);
        return 0;
    }
    if (message == WM_CLOSE || message == WM_DESTROY) { running = false; return 0; }
    return DefWindowProcW(window, message, wParam, lParam);
}
static HWND createSink(Bridge& app) {
    WNDCLASSW type{}; type.lpfnWndProc = sinkProc; type.hInstance = GetModuleHandleW(nullptr); type.lpszClassName = L"DoraKuroCatInputSink";
    RegisterClassW(&type); active = &app;
    HWND window = CreateWindowExW(0, type.lpszClassName, L"Dora KuroCat Input", 0, 0, 0, 0, 0, HWND_MESSAGE, nullptr, type.hInstance, nullptr);
    require(window != nullptr, "input_window"); app.window = window; return window;
}
static void pump() {
    MSG message{};
    for (int n = 0; n < 200 && PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE); ++n) {
        if (message.message == WM_QUIT) { running = false; break; }
        TranslateMessage(&message); DispatchMessageW(&message);
    }
}
static CLSID pngEncoder() {
    UINT count = 0, size = 0; Gdiplus::GetImageEncodersSize(&count, &size);
    std::vector<unsigned char> bytes(size); auto* encoders = reinterpret_cast<Gdiplus::ImageCodecInfo*>(bytes.data());
    Gdiplus::GetImageEncoders(count, size, encoders);
    for (UINT n = 0; n < count; ++n) if (wcscmp(encoders[n].MimeType, L"image/png") == 0) return encoders[n].Clsid;
    throw std::runtime_error("png_encoder");
}
static int verify(const std::filesystem::path& output) {
    std::filesystem::create_directories(output); Bridge app; app.width = 720; app.height = 640; app.dpi = 1;
    app.frame = RECT{400, 200, 760, 520}; POINT old{}; GetCursorPos(&old);
    const auto encoder = pngEncoder();
    auto save = [&](const wchar_t* name) { auto image = app.bitmap(); require(image->Save((output / name).c_str(), &encoder, nullptr) == Gdiplus::Ok, "png_save"); };
    auto step = [&](int count) { for (int n = 0; n < count; ++n) app.physics.step(1.0f / 60, app.frame, app.input, app.settings); };
    SetCursorPos(584, 324); app.input.lastKeyActivityTime = -10; step(90); save(L"idle.png");
    auto pixels = app.pixels(*app.bitmap()); size_t opaque = 0, green = 0;
    for (size_t n = 0; n < pixels.size(); n += 4) { opaque += pixels[n + 3] > 20; green += pixels[n + 1] > 180 && pixels[n] > 100 && pixels[n + 2] < 130; }
    require(opaque > 15000 && green > 100 && opaque < pixels.size() / 4, "cat_pixels");
    require(!app.settings.flipHorizontal, "layout_mirrored");
    const POINT directions[] = {{100, 324}, {1000, 324}, {584, 30}, {584, 750}};
    const wchar_t* names[] = {L"look-left.png", L"look-right.png", L"look-up.png", L"look-down.png"};
    for (int n = 0; n < 4; ++n) {
        SetCursorPos(directions[n].x, directions[n].y); step(90);
        float direction = n < 2 ? app.physics.headYaw.value : app.physics.headPitch.value;
        require(direction * (n % 2 ? 1 : -1) > 0.05f, "pointer_direction"); save(names[n]);
    }
    app.input.activeKeys = {PhysicalKey::A, PhysicalKey::S, PhysicalKey::D, PhysicalKey::F};
    app.input.pressedOrder = {PhysicalKey::A, PhysicalKey::S, PhysicalKey::D, PhysicalKey::F}; step(90);
    require(app.physics.hindFootActive.value > 0.5f && app.physics.tailTyping.value > 0.5f, "multi_key_limbs"); save(L"combo.png");
    app.input.activeKeys.clear(); app.input.pressedOrder.clear(); step(180);
    require(app.physics.hindFootActive.value < 0.1f && app.physics.tailTyping.value < 0.1f, "key_release");
    app.physics.triggerMouseClick(0, true, app.settings); step(60); require(app.physics.mousePressLeft.value > 0.8f, "mouse_press"); save(L"mouse.png");
    app.physics.triggerMouseClick(0, false, app.settings); step(60); require(app.physics.mousePressLeft.value < 0.1f, "mouse_release");
    app.physics.registerPetStroke({184, 126}, 24, true, app.settings); require(app.physics.petHeadIntensity > 0.1f, "petting"); save(L"petting.png");
    app.physics.sleepiness = 1; require(app.physics.effectiveEyeClosure() > 0.8f, "sleep_pose"); save(L"sleep.png");
    app.physics.triggerKeyDown(PhysicalKey::A, app.settings); require(app.physics.sleepiness == 0, "wake");
    app.physics.setDragging(true, 8, -4); step(90); require(app.physics.scruffDrag.value > 0.5f, "drag_lift"); save(L"drag.png");
    app.physics.setDragging(false); step(180); require(app.physics.scruffDrag.value < 0.1f, "drag_release");
    SetCursorPos(old.x, old.y);
    std::cout << "{\"native_kurocat\":true,\"motion_scenarios\":14,\"direction_cases\":4,\"transparent_rgba\":true,\"physical_keyboard_tested\":false}\n";
    return 0;
}
static int inputProbe(const std::filesystem::path& output) {
    Bridge app; HWND sink = createSink(app); require(app.input.registerRawInput(sink), "raw_input_register"); app.input.installKeyboardHook();
    require(app.input.kbHook_ != nullptr, "keyboard_hook");
    HWND edit = CreateWindowW(L"EDIT", L"Dora isolated input probe", WS_OVERLAPPEDWINDOW | WS_VISIBLE, 20, 20, 250, 120, nullptr, nullptr, GetModuleHandleW(nullptr), nullptr);
    SetForegroundWindow(edit); SetFocus(edit);
    for (WORD key : {WORD('A'), WORD('S'), WORD('D'), WORD('F')}) {
        INPUT value{}; value.type = INPUT_KEYBOARD; value.ki.wVk = key;
        require(SendInput(1, &value, sizeof(value)) == 1, "key_down_inject");
        for (int n = 0; n < 8; ++n) { pump(); app.input.pollMouse(0.016f); Sleep(10); }
        value.ki.dwFlags = KEYEVENTF_KEYUP; SendInput(1, &value, sizeof(value));
        for (int n = 0; n < 8; ++n) { pump(); app.input.pollMouse(0.016f); Sleep(10); }
    }
    require(app.input.totalKeystrokesToday >= 4 && app.input.activeKeys.empty(), "system_input_callbacks");
    app.input.uninstallKeyboardHook(); DestroyWindow(edit); DestroyWindow(sink);
    std::ofstream(output) << "{\"raw_input_registered\":true,\"synthetic_system_keyboard\":true,\"release_cleared_keys\":true,\"physical_keyboard_tested\":false}\n";
    return 0;
}
int wmain(int argc, wchar_t** argv) {
    ULONG_PTR graphics = 0; Gdiplus::GdiplusStartupInput startup;
    if (Gdiplus::GdiplusStartup(&graphics, &startup, nullptr) != Gdiplus::Ok) return 2;
    try {
        if (argc == 3 && wcscmp(argv[1], L"--verify") == 0) { int code = verify(argv[2]); Gdiplus::GdiplusShutdown(graphics); return code; }
        if (argc == 3 && wcscmp(argv[1], L"--input-probe") == 0) { int code = inputProbe(argv[2]); Gdiplus::GdiplusShutdown(graphics); return code; }
        _setmode(_fileno(stdout), _O_BINARY);
        Bridge app; HWND sink = createSink(app); app.input.registerRawInput(sink); app.input.installKeyboardHook();
        event(std::string("{\"type\":\"ready\",\"rawInput\":") + (app.input.isRawInputRegistered ? "true" : "false")
            + ",\"keyboardHook\":" + (app.input.kbHook_ ? "true" : "false") + "}");
        std::thread([sink] {
            std::string line;
            while (std::getline(std::cin, line)) {
                if (line.size() > 1024) continue;
                auto* value = new std::string(line);
                if (!PostMessageW(sink, CommandMessage, 0, reinterpret_cast<LPARAM>(value))) delete value;
            }
            PostMessageW(sink, WM_CLOSE, 0, 0);
        }).detach();
        double previous = nowSeconds(), presented = -1, reported = -1;
        while (running) {
            pump(); double now = nowSeconds();
            if (now - previous >= 0.015) {
                if (!app.paused) app.physics.step(float(now - previous), app.canvasFrame(), app.input, app.settings);
                previous = now;
                const bool busy = !app.input.activeKeys.empty() || now - app.input.lastMouseMoveTime < 0.8 || app.physics.petHeadIntensity > 0.02 || app.physics.isScruffDragging_;
                if (app.dirty || (!app.paused && now - presented > (busy ? 1.0 / 30 : 0.1))) { app.render(); presented = now; }
                if (now - reported > 1) { app.stats(); reported = now; }
            }
            MsgWaitForMultipleObjectsEx(0, nullptr, 5, QS_ALLINPUT, MWMO_INPUTAVAILABLE);
        }
        app.input.uninstallKeyboardHook(); app.input.resetAllState(); DestroyWindow(sink); active = nullptr;
        Gdiplus::GdiplusShutdown(graphics); return 0;
    } catch (const std::exception& e) { std::cerr << "Dora native pet: " << e.what() << '\n'; Gdiplus::GdiplusShutdown(graphics); return 1; }
}
