#pragma once
#define NOMINMAX
#include <windows.h>
#include <cmath>
#include <string>
#include <vector>
#include <unordered_map>
#include <random>
#include <algorithm>
#include "KeyMap.hpp"
#include "InputEngine.hpp"

enum class CatCoatTheme : int {
    ClassicBlack = 0,
    Siamese = 1,
    Shorthair = 2,
    OrangeWhite = 3,
    Dazed = 4,
    Tabby = 5
};

enum class KeyboardTheme : int {
    ClassicMilk = 0,
    MidnightHacker = 1,
    RetroCream = 2
};

enum class EyeColorTheme : int {
    NeonChartreuse = 0,
    SiameseBlue = 1,
    WarmAmber = 2,
    IceCyan = 3,
    SoftAmber = 4,
    ReferenceHazel = 5,
    OliveGold = 6
};

struct CatSettings {
    bool showKeyBadges = true;
    bool showMouseBadges = true;
    bool showKeyLegends = true;
    bool footEasterEgg = true;
    bool tailEasterEgg = true;
    bool keyboardMarquee = true;
    int obsCaptureMode = 0; // 0 = off, 1 = OBS transparent window capture, 2 = OBS green screen (#00FF00)
    bool obsHideDesktop = false;
    bool autoHideFullscreen = false;
    int tabletMode = 0; // 0 = auto-detect tablet/stylus, 1 = always tablet, 2 = always mouse
    bool flipHorizontal = false;
    float rotationDeg = 0.0f; // -180..180 degrees
    bool whiteOutline = true;
    bool enableAnger = true;
    bool enableDragAnimation = true;
    bool isEnglish = false;
    bool isEditMode = false; // runtime-only interactive resize & rotate box
    bool petInteraction = true;
    bool fullClickThrough = false;
    bool alwaysOnTop = true;
    bool runAsAdmin = false; // relaunch elevated so keys typed into admin-level apps/games are visible (UIPI)
    float scale = 1.0f;
    CatCoatTheme coatTheme = CatCoatTheme::ClassicBlack;
    KeyboardTheme keyboardTheme = KeyboardTheme::ClassicMilk;
    EyeColorTheme eyeTheme = EyeColorTheme::NeonChartreuse;
    // Content id (16 hex chars) of the imported .kurocat skin in use; empty = the built-in coatTheme.
    std::string customSkin;
    // Content id (16 hex chars) of the imported .kurokb / keyboard.json skin in use; empty = the built-in keyboardTheme.
    std::string customKeyboard;
    int posX = -99999;
    int posY = -99999;

    void loadFromRegistry() {
        HKEY hKey = nullptr;
        if (RegOpenKeyExW(HKEY_CURRENT_USER, L"Software\\KuroCat", 0, KEY_READ, &hKey) != ERROR_SUCCESS) return;
        auto readDword = [&](const wchar_t* name, DWORD defVal) -> DWORD {
            DWORD val = defVal, sz = sizeof(val);
            if (RegQueryValueExW(hKey, name, nullptr, nullptr, (LPBYTE)&val, &sz) == ERROR_SUCCESS) return val;
            return defVal;
        };
        showKeyBadges    = readDword(L"ShowKeyBadges", 1) != 0;
        showMouseBadges  = readDword(L"ShowMouseBadges", 1) != 0;
        showKeyLegends   = readDword(L"ShowKeyLegends", 1) != 0;
        footEasterEgg    = readDword(L"FootEasterEgg", 1) != 0;
        tailEasterEgg    = readDword(L"TailEasterEgg", 1) != 0;
        keyboardMarquee  = readDword(L"KeyboardMarquee", 1) != 0;
        obsCaptureMode   = std::clamp((int)readDword(L"OBSCaptureMode", 0), 0, 2);
        obsHideDesktop   = readDword(L"OBSHideDesktop", 0) != 0;
        autoHideFullscreen = readDword(L"AutoHideFullscreen", 0) != 0;
        tabletMode       = std::clamp((int)readDword(L"TabletMode", 0), 0, 2);
        flipHorizontal   = readDword(L"FlipHorizontal", 0) != 0;
        {
            int rotTenths = (int)readDword(L"RotationTenths", 0);
            rotationDeg = std::clamp((float)rotTenths / 10.0f, -180.0f, 180.0f);
        }
        whiteOutline     = readDword(L"WhiteOutline", 1) != 0;
        enableAnger      = readDword(L"EnableAnger", 1) != 0;
        enableDragAnimation = readDword(L"EnableDragAnimation", 1) != 0;
        isEnglish        = readDword(L"LanguageEnglish", 0) != 0;
        petInteraction   = readDword(L"PetInteraction", 1) != 0;
        fullClickThrough = readDword(L"FullClickThrough", 0) != 0;
        alwaysOnTop      = readDword(L"AlwaysOnTop", 1) != 0;
        runAsAdmin       = readDword(L"RunAsAdmin", 0) != 0;
        scale            = std::clamp((float)readDword(L"ScalePct", 100) / 100.0f, 0.45f, 2.50f);
        coatTheme        = (CatCoatTheme)std::clamp((int)readDword(L"CoatTheme", 0), 0, static_cast<int>(CatCoatTheme::Tabby));
        keyboardTheme    = (KeyboardTheme)std::clamp((int)readDword(L"KeyboardTheme", 0), 0, 2);
        eyeTheme         = (EyeColorTheme)std::clamp((int)readDword(L"EyeTheme", 0), 0, (int)EyeColorTheme::OliveGold);
        {
            wchar_t buf[32] = {0};
            DWORD type = 0, sz = sizeof(buf) - sizeof(wchar_t);
            customSkin.clear();
            if (RegQueryValueExW(hKey, L"CustomSkin", nullptr, &type, (LPBYTE)buf, &sz) == ERROR_SUCCESS && type == REG_SZ) {
                for (int i = 0; buf[i] && i < 16; ++i) {
                    wchar_t c = buf[i];
                    if (!((c >= L'0' && c <= L'9') || (c >= L'a' && c <= L'f'))) { customSkin.clear(); break; }
                    customSkin += (char)c;
                }
                if (customSkin.size() != 16) customSkin.clear();
            }
        }
        {
            wchar_t buf[32] = {0};
            DWORD type = 0, sz = sizeof(buf) - sizeof(wchar_t);
            customKeyboard.clear();
            if (RegQueryValueExW(hKey, L"CustomKeyboard", nullptr, &type, (LPBYTE)buf, &sz) == ERROR_SUCCESS && type == REG_SZ) {
                for (int i = 0; buf[i] && i < 16; ++i) {
                    wchar_t c = buf[i];
                    if (!((c >= L'0' && c <= L'9') || (c >= L'a' && c <= L'f'))) { customKeyboard.clear(); break; }
                    customKeyboard += (char)c;
                }
                if (customKeyboard.size() != 16) customKeyboard.clear();
            }
        }
        DWORD hasPos     = readDword(L"HasPos", 0);
        if (hasPos) {
            posX = (int)readDword(L"PosX", 0);
            posY = (int)readDword(L"PosY", 0);
        }
        RegCloseKey(hKey);
    }

    void saveToRegistry() const {
        HKEY hKey = nullptr;
        if (RegCreateKeyExW(HKEY_CURRENT_USER, L"Software\\KuroCat", 0, nullptr, 0, KEY_WRITE, nullptr, &hKey, nullptr) != ERROR_SUCCESS) return;
        auto writeDword = [&](const wchar_t* name, DWORD val) {
            RegSetValueExW(hKey, name, 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
        };
        writeDword(L"ShowKeyBadges", showKeyBadges ? 1 : 0);
        writeDword(L"ShowMouseBadges", showMouseBadges ? 1 : 0);
        writeDword(L"ShowKeyLegends", showKeyLegends ? 1 : 0);
        writeDword(L"FootEasterEgg", footEasterEgg ? 1 : 0);
        writeDword(L"TailEasterEgg", tailEasterEgg ? 1 : 0);
        writeDword(L"KeyboardMarquee", keyboardMarquee ? 1 : 0);
        writeDword(L"OBSCaptureMode", (DWORD)obsCaptureMode);
        writeDword(L"OBSHideDesktop", obsHideDesktop ? 1 : 0);
        writeDword(L"AutoHideFullscreen", autoHideFullscreen ? 1 : 0);
        writeDword(L"TabletMode", (DWORD)tabletMode);
        writeDword(L"FlipHorizontal", flipHorizontal ? 1 : 0);
        writeDword(L"RotationTenths", (DWORD)(int)std::lround(std::clamp(rotationDeg, -180.0f, 180.0f) * 10.0f));
        writeDword(L"WhiteOutline", whiteOutline ? 1 : 0);
        writeDword(L"EnableAnger", enableAnger ? 1 : 0);
        writeDword(L"EnableDragAnimation", enableDragAnimation ? 1 : 0);
        writeDword(L"LanguageEnglish", isEnglish ? 1 : 0);
        writeDword(L"PetInteraction", petInteraction ? 1 : 0);
        writeDword(L"FullClickThrough", fullClickThrough ? 1 : 0);
        writeDword(L"AlwaysOnTop", alwaysOnTop ? 1 : 0);
        writeDword(L"RunAsAdmin", runAsAdmin ? 1 : 0);
        writeDword(L"ScalePct", (DWORD)(scale * 100.0f + 0.5f));
        writeDword(L"CoatTheme", (DWORD)coatTheme);
        writeDword(L"KeyboardTheme", (DWORD)keyboardTheme);
        writeDword(L"EyeTheme", (DWORD)eyeTheme);
        {
            std::wstring id(customSkin.begin(), customSkin.end());
            RegSetValueExW(hKey, L"CustomSkin", 0, REG_SZ, (const BYTE*)id.c_str(), (DWORD)((id.size() + 1) * sizeof(wchar_t)));
        }
        {
            std::wstring id(customKeyboard.begin(), customKeyboard.end());
            RegSetValueExW(hKey, L"CustomKeyboard", 0, REG_SZ, (const BYTE*)id.c_str(), (DWORD)((id.size() + 1) * sizeof(wchar_t)));
        }
        if (posX != -99999 && posY != -99999) {
            writeDword(L"HasPos", 1);
            writeDword(L"PosX", (DWORD)posX);
            writeDword(L"PosY", (DWORD)posY);
        }
        RegCloseKey(hKey);
    }

    static std::string todayDateString() {
        SYSTEMTIME st = {};
        GetLocalTime(&st);
        char buf[16];
        std::snprintf(buf, sizeof(buf), "%04u-%02u-%02u", st.wYear, st.wMonth, st.wDay);
        return buf;
    }

    static void loadStatsFromRegistry(std::string& day, int& todayKeys, int& petCount) {
        day = todayDateString();
        todayKeys = 0;
        petCount = 0;
        HKEY hKey = nullptr;
        if (RegOpenKeyExW(HKEY_CURRENT_USER, L"Software\\KuroCat", 0, KEY_READ, &hKey) != ERROR_SUCCESS) return;
        DWORD val = 0, sz = sizeof(val);
        if (RegQueryValueExW(hKey, L"PetCount", nullptr, nullptr, (LPBYTE)&val, &sz) == ERROR_SUCCESS) {
            petCount = (int)val;
        }
        wchar_t dayBuf[32] = {0};
        DWORD type = 0, dsz = sizeof(dayBuf) - sizeof(wchar_t);
        std::string savedDay;
        if (RegQueryValueExW(hKey, L"StatsDay", nullptr, &type, (LPBYTE)dayBuf, &dsz) == ERROR_SUCCESS && type == REG_SZ) {
            for (int i = 0; dayBuf[i] && i < 16; ++i) savedDay += (char)dayBuf[i];
        }
        if (savedDay == day) {
            sz = sizeof(val);
            if (RegQueryValueExW(hKey, L"TodayKeys", nullptr, nullptr, (LPBYTE)&val, &sz) == ERROR_SUCCESS) {
                todayKeys = (int)val;
            }
        }
        RegCloseKey(hKey);
    }

    static void saveStatsToRegistry(const std::string& day, int todayKeys, int petCount) {
        HKEY hKey = nullptr;
        if (RegCreateKeyExW(HKEY_CURRENT_USER, L"Software\\KuroCat", 0, nullptr, 0, KEY_WRITE, nullptr, &hKey, nullptr) != ERROR_SUCCESS) return;
        DWORD kVal = (DWORD)std::max(0, todayKeys);
        DWORD pVal = (DWORD)std::max(0, petCount);
        RegSetValueExW(hKey, L"TodayKeys", 0, REG_DWORD, (const BYTE*)&kVal, sizeof(kVal));
        RegSetValueExW(hKey, L"PetCount", 0, REG_DWORD, (const BYTE*)&pVal, sizeof(pVal));
        std::wstring wday(day.begin(), day.end());
        RegSetValueExW(hKey, L"StatsDay", 0, REG_SZ, (const BYTE*)wday.c_str(), (DWORD)((wday.size() + 1) * sizeof(wchar_t)));
        RegCloseKey(hKey);
    }
};

struct Spring1D {
    float value = 0.0f;
    float velocity = 0.0f;
    float target = 0.0f;

    explicit Spring1D(float v = 0.0f) : value(v), velocity(0.0f), target(v) {}

    void step(float dt, float stiffness = 260.0f, float damping = 22.0f) {
        float force = (target - value) * stiffness;
        float damp = velocity * damping;
        velocity += (force - damp) * dt;
        value += velocity * dt;
    }
};

struct Spring2D {
    Spring1D x;
    Spring1D y;

    explicit Spring2D(Pt p = {0.0f, 0.0f}) : x(p.x), y(p.y) {}
    Pt point() const { return { x.value, y.value }; }
    void setTarget(Pt p) { x.target = p.x; y.target = p.y; }
    void step(float dt, float stiffness = 340.0f, float damping = 25.0f) {
        x.step(dt, stiffness, damping);
        y.step(dt, stiffness, damping);
    }
};

struct FloatingKeycap {
    std::wstring label;
    Pt position;
    Pt velocity;
    float age = 0.0f;
    float lifetime = 1.25f;
    float rotation = 0.0f;
};

struct PurrSparkle {
    Pt position;
    Pt velocity;
    float age = 0.0f;
    float lifetime = 0.9f;
    bool isSleepZ = false;
};

class CatPhysics {
public:
    static constexpr float CanvasWidth  = 360.0f;
    static constexpr float CanvasHeight = 320.0f;
    static constexpr Pt SeatAnchor      = { 184.0f, 226.0f };
    static constexpr Pt LeftPawRest     = { 164.0f, 235.0f };
    static constexpr Pt RightPawRest    = { 204.0f, 235.0f };
    static constexpr Pt HindFootRest    = { 214.0f, 234.0f };
    static constexpr Pt MouseBaseCenter = { 78.0f, 258.0f };

    Spring2D leftPaw{LeftPawRest};
    Spring2D rightPaw{RightPawRest};
    Spring2D hindFoot{HindFootRest};
    Spring1D hindFootActive{0.0f};
    Spring2D tailTip{{275.0f, 196.0f}};
    Spring1D tailTyping{0.0f};
    Spring2D tailFlick{{0.0f, 0.0f}};
    Spring1D tailCurl{0.0f};
    Spring1D tailAgility{0.0f};
    float tailFlickHold = 0.0f;
    float tailFlickCooldown = 0.0f;
    // Keyboard marquee: normalized position (0..1) of the light head, plus its speed boost.
    float marqueePhase = 0.0f;
    Spring1D marqueeBoost{0.0f};

    Spring1D bodyShiftX{0.0f};
    Spring1D bodyTilt{0.0f};
    Spring1D bodySquash{1.0f};
    Spring1D headTilt{0.0f};
    Spring1D headYaw{0.0f};
    Spring1D headPitch{0.0f};
    Spring1D headOffsetY{0.0f};
    Spring1D earFold{0.0f};
    Spring1D earTwitch{0.0f};

    Spring2D eyeGaze{{0.0f, 0.0f}};
    Spring1D pupilScale{1.0f};
    Spring1D huntIntensity{0.0f};
    Spring1D scruffDrag{0.0f};
    Spring1D scruffSwing{0.0f};
    Spring1D scruffSwingY{0.0f};
    Spring1D scruffTailSwing{0.0f};
    Spring1D lieIntensity{0.0f};
    Spring1D angerIntensity{0.0f};
    Spring1D dizzyIntensity{0.0f};
    float dizzyPhase = 0.0f;
    bool isScruffDragging_ = false;
    float scruffDragDx_ = 0.0f;
    float scruffDragDy_ = 0.0f;
    float scruffDragAccumX_ = 0.0f;
    float scruffDragAccumY_ = 0.0f;
    float fastMouseDuration_ = 0.0f;
    float dizzyTimer_ = 0.0f;
    float fastTypeAccum_ = 0.0f;
    float angerBurstTimer_ = 0.0f;
    float angerCooldown_ = 0.0f;
    Spring2D mouseOffset{{0.0f, 0.0f}};
    Spring1D mousePressLeft{0.0f};
    Spring1D mousePressRight{0.0f};

    static Pt tabletQuadPoint(float u, float v) {
        constexpr Pt tl = { 18.0f, 235.0f }, tr = { 94.0f, 240.0f };
        constexpr Pt bl = { 13.0f, 284.0f }, br = { 91.0f, 289.0f };
        float topX = tl.x + (tr.x - tl.x) * u, topY = tl.y + (tr.y - tl.y) * u;
        float botX = bl.x + (br.x - bl.x) * u, botY = bl.y + (br.y - bl.y) * u;
        return { topX + (botX - topX) * v, topY + (botY - topY) * v };
    }

    struct TabletStrokePoint { Pt point; float age = 0.0f; };
    bool isTabletActive = false;
    Spring2D tabletNib{{60.0f, 261.0f}};
    Spring1D tabletPenPress{0.0f};
    Spring1D tabletPenTilt{0.0f};
    std::vector<TabletStrokePoint> tabletTrail;

    bool leftPawOnMouse = false;
    bool leftPawTyping = false;
    bool rightPawTyping = false;

    // Video-2 Xiao Douni independent signed slap arm springs (-1 = slammed on key, 0 = ready, +1 = high windup)
    int douniSlapSide = 0;
    float douniSlapTimer = 0.0f;
    double douniLastLeftKeyTime = -10.0;
    double douniLastRightKeyTime = -10.0;
    Spring1D douniLeftRaise{0.0f};
    Spring1D douniRightRaise{0.0f};
    Spring2D douniLeftKeyTarget{{318.0f, 422.0f}};
    Spring2D douniRightKeyTarget{{512.0f, 462.0f}};
    Spring1D douniMouseBlend{0.0f};
    Spring1D douniLoafBlend{0.0f};
    float scruffHoldTime = 0.0f;
    float scruffDropTimer = 0.0f;
    // Disney 12-principles tactile keyboard impact recoil, tilt shudder & keycap spark burst
    Spring1D kbImpactY{0.0f};
    Spring1D kbImpactTilt{0.0f};
    float kbSparkTimer = 0.0f;
    PhysicalKey kbSparkKey = PhysicalKey::None;

    std::unordered_map<PhysicalKey, float> keyGlow;
    std::vector<FloatingKeycap> floatingKeycaps;
    std::vector<PurrSparkle> sparkles;

    float time = 0.0f;
    float tailPhase = 0.0f;

    float petHeadIntensity = 0.0f;
    float petBodyIntensity = 0.0f;
    int totalPetSessions = 0;
    float sleepiness = 0.0f;
    float yawnAmount = 0.0f;
    float yawnTimer_ = 0.0f;
    bool isYawning_ = false;
    bool hasYawnedThisIdle_ = false;

    float effectiveEyeClosure() const {
        float petClose = std::max(petHeadIntensity, petBodyIntensity * 0.62f);
        float sleepClose = std::max(sleepiness * 0.92f, yawnAmount * 0.96f);
        return std::min(1.0f, std::max(blinkProgress_, std::max(petClose, sleepClose)));
    }

    float blinkProgress() const { return blinkProgress_; }
    float breathingOffset() const { return std::sin(time * 2.1f) * 1.6f; }
    bool isHappyClosedEyes() const { return petHeadIntensity > 0.45f; }
    bool isBlissfulSquint() const { return petBodyIntensity > 0.35f && !isHappyClosedEyes(); }

    void triggerKeyDown(PhysicalKey key, const CatSettings& settings, bool douniTyping = false,
                        const std::unordered_set<PhysicalKey>* activeKeys = nullptr) {
        double now = nowSeconds();
        PhysicalKey vk = visualKeyOf(key);
        keyGlow[vk] = 1.0f;

        Pt pt = KeyboardLayout::canvasPointForKey(vk);
        hasLastTypedPoint_ = true;
        lastTypedPoint_ = pt;

        (void)activeKeys;

        if (prefersViewerLeftPaw(key)) {
            recentLeftKey_ = vk;
            recentLeftTime_ = now;
            leftPaw.y.velocity -= 180.0f;
        } else {
            recentRightKey_ = vk;
            recentRightTime_ = now;
            rightPaw.y.velocity -= 180.0f;
        }

        if (douniTyping) {
            Pt keyPt = KeyboardLayout::v2KeyCellCenter(vk);
            bool useLeft = prefersViewerLeftPaw(vk);
            douniSlapSide = useLeft ? 0 : 1;
            douniSlapTimer = 0.28f;
            douniMouseBlend.target = 0.0f;
            if (douniMouseBlend.value > 0.05f) {
                douniMouseBlend.velocity = std::min(douniMouseBlend.velocity, -14.0f);
            }
            douniLoafBlend.target = 0.0f;
            float angerBoost = 1.0f + std::clamp(angerIntensity.value, 0.0f, 1.0f) * 0.35f;
            if (useLeft) {
                bool chordOther = (now - douniLastRightKeyTime) < 0.035;
                douniLastLeftKeyTime = now;
                douniLeftKeyTarget.setTarget(keyPt);
                // Independent signed spring (-1 = slam on keycap, +1 = flung high):
                // On rapid same-side repeat, visibly pop up (+0.50) then whip down so EVERY keystroke re-slaps cleanly!
                if (douniLeftRaise.value < -0.15f) {
                    douniLeftRaise.value = 0.50f;
                    douniLeftRaise.velocity = -15.5f * angerBoost;
                } else {
                    douniLeftRaise.velocity = -22.0f * angerBoost;
                }
                douniLeftRaise.target = -1.0f;
                if (!chordOther) {
                    douniRightRaise.target = 1.02f;
                    douniRightRaise.velocity = std::max(douniRightRaise.velocity + 6.0f, 17.0f * angerBoost);
                }
                leftPaw.y.velocity += 220.0f;
            } else {
                bool chordOther = (now - douniLastLeftKeyTime) < 0.035;
                douniLastRightKeyTime = now;
                douniRightKeyTarget.setTarget(keyPt);
                if (douniRightRaise.value < -0.15f) {
                    douniRightRaise.value = 0.50f;
                    douniRightRaise.velocity = -15.5f * angerBoost;
                } else {
                    douniRightRaise.velocity = -22.0f * angerBoost;
                }
                douniRightRaise.target = -1.0f;
                if (!chordOther) {
                    douniLeftRaise.target = 1.02f;
                    douniLeftRaise.velocity = std::max(douniLeftRaise.velocity + 6.0f, 17.0f * angerBoost);
                }
                rightPaw.y.velocity += 220.0f;
            }
            // Disney Squash & Stretch + Impact Recoil + Secondary Action on keyboard, cord & ears!
            kbImpactY.velocity += 24.0f * angerBoost;
            kbImpactTilt.velocity += (useLeft ? -10.5f : 10.5f) * angerBoost;
            kbSparkTimer = 0.14f;
            kbSparkKey = vk;
            bodySquash.velocity -= 2.2f;
            headOffsetY.velocity += 44.0f;
            earTwitch.velocity += (useLeft ? -6.5f : 6.5f);
            headTilt.velocity += (useLeft ? -2.8f : 2.8f);
            pupilScale.target = 1.24f;
        } else {
            bodySquash.velocity -= 1.3f;
            earTwitch.velocity += (prefersViewerLeftPaw(key) ? -3.8f : 3.8f);
            headTilt.velocity += (prefersViewerLeftPaw(key) ? -1.4f : 1.4f);
            pupilScale.target = 1.16f;
        }
        sleepiness = 0.0f;

        if (settings.showKeyBadges) {
            spawnFloatingKeycap(keyBadgeLabel(key), pt, now);
        }
    }

    void triggerMouseClick(int button, bool isDown, const CatSettings& settings, bool douniSkin = false) {
        sleepiness = 0.0f;
        if (isDown) {
            double now = nowSeconds();
            if (douniSkin) {
                douniSlapTimer = 0.0f;
                douniLeftRaise.target = 0.0f;
                douniRightRaise.target = 0.0f;
                douniLoafBlend.target = 0.0f;
                douniMouseBlend.target = 1.0f;
            }
            if (button == 0) {
                mousePressLeft.target = 1.0f;
                leftPaw.y.velocity += 130.0f;
            } else {
                mousePressRight.target = 1.0f;
                leftPaw.y.velocity += 110.0f;
            }
            pupilScale.target = 1.12f;
            earTwitch.velocity -= 2.2f;
            if (settings.showMouseBadges) {
                std::wstring lbl = settings.isEnglish
                    ? (button == 0 ? L"LMB" : (button == 1 ? L"RMB" : L"MMB"))
                    : ((button == 0) ? L"\u5DE6\u952E" : (button == 1 ? L"\u53F3\u952E" : L"\u4E2D\u952E"));
                Pt pt = { MouseBaseCenter.x + mouseOffset.point().x, MouseBaseCenter.y + mouseOffset.point().y - 6.0f };
                spawnFloatingKeycap(lbl, pt, now);
            }
        } else {
            if (button == 0) mousePressLeft.target = 0.0f;
            else mousePressRight.target = 0.0f;
        }
    }

    void setDragging(bool dragging, float dragDx = 0.0f, float dragDy = 0.0f) {
        bool wasDragging = isScruffDragging_;
        isScruffDragging_ = dragging;
        if (dragging) {
            if (!wasDragging) {
                scruffHoldTime = 0.0f;
                scruffDropTimer = 0.0f;
                scruffDragAccumX_ = 0.0f;
                scruffDragAccumY_ = 0.0f;
            }
            scruffDragAccumX_ += dragDx;
            scruffDragAccumY_ += dragDy;
            sleepiness = 0.0f;
            dizzyTimer_ = 0.0f;
            fastMouseDuration_ = 0.0f;
        } else {
            scruffDragDx_ = 0.0f;
            scruffDragDy_ = 0.0f;
            scruffDragAccumX_ = 0.0f;
            scruffDragAccumY_ = 0.0f;
            if (wasDragging) {
                scruffDropTimer = 0.16f;
                // Cute soft squash bounce when set back down (Video 1 drop settle!)
                bodySquash.velocity -= 2.4f;
                headOffsetY.velocity += 78.0f;
            }
        }
    }

    void updateTailHover(const Pt* cp) {
        if (!cp || tailTyping.value >= 0.25f) return;
        float seatX = SeatAnchor.x + bodyShiftX.value;
        float seatY = SeatAnchor.y;
        float hunt = std::clamp(huntIntensity.value, 0.0f, 1.0f);
        float agility = std::clamp(tailAgility.value, 0.0f, 1.0f);
        float wag1 = std::sin(tailPhase) * (8.0f + hunt * 5.5f + agility * 4.0f);
        float wag2 = std::cos(tailPhase * 1.3f) * (6.0f + hunt * 4.5f + agility * 3.5f);
        float huntDrop = hunt * 14.0f;
        Pt flick = tailFlick.point();
        float curl = tailCurl.value;

        Pt root{seatX + 34.0f, seatY - 6.0f};
        Pt c1{seatX + 64.0f + flick.x * 0.25f, seatY + 2.0f + wag1 * 0.35f + huntDrop * 0.4f + flick.y * 0.22f + curl * 0.35f};
        Pt c2{seatX + 66.0f + wag2 * 0.4f + flick.x * 0.65f - curl * 0.45f, seatY - 26.0f + wag1 * 0.7f + huntDrop + flick.y * 0.60f - curl * 0.55f};
        Pt tip{seatX + 91.0f + wag2 * 0.5f + flick.x, seatY - 30.0f + wag1 * 0.85f + huntDrop + flick.y};

        float bestDist = 1e9f;
        Pt bestPt = tip;
        for (float t : {0.35f, 0.58f, 0.80f, 1.0f}) {
            float u = 1.0f - t;
            Pt pt{
                u*u*u*root.x + 3*u*u*t*c1.x + 3*u*t*t*c2.x + t*t*t*tip.x,
                u*u*u*root.y + 3*u*u*t*c1.y + 3*u*t*t*c2.y + t*t*t*tip.y
            };
            float d = std::hypot(pt.x - cp->x, pt.y - cp->y);
            if (d < bestDist) {
                bestDist = d;
                bestPt = pt;
            }
        }

        if (bestDist < 24.0f) {
            float ax = bestPt.x - cp->x;
            float ay = bestPt.y - cp->y;
            float len = std::hypot(ax, ay);
            if (len < 1.0f) { ax = 0.35f; ay = -0.94f; }
            else { ax /= len; ay /= len; }
            float tx = std::clamp(ax * 32.0f + (ax >= 0.0f ? 6.0f : -4.0f), -24.0f, 36.0f);
            float ty = std::clamp(ay * 40.0f + (ay < 0.0f ? -8.0f : 6.0f), -44.0f, 38.0f);
            tailFlick.setTarget({tx, ty});
            tailCurl.target = (ay >= 0.0f) ? -18.0f : 20.0f;
            if (tailFlickCooldown <= 0.0f) {
                tailFlick.x.velocity += ax * 240.0f;
                tailFlick.y.velocity += ay * 280.0f;
                tailCurl.velocity += (ay >= 0.0f) ? -150.0f : 170.0f;
                earTwitch.velocity += 1.4f;
                tailFlickCooldown = 0.16f;
            }
            tailFlickHold = 0.30f;
            tailAgility.target = 1.0f;
            sleepiness = std::max(0.0f, sleepiness - 0.15f);
        }
    }

    void registerPetStroke(Pt canvasPoint, float delta, bool isHead, const CatSettings& settings) {
        if (!settings.petInteraction) return;
        double now = nowSeconds();
        lastPetTime_ = now;
        sleepiness = 0.0f;

        float energy = std::min(delta / 26.0f, 0.35f);
        if (isHead) {
            petHeadIntensity = std::min(1.0f, petHeadIntensity + energy + 0.08f);
            petBodyIntensity = std::max(petBodyIntensity, petHeadIntensity * 0.6f);
        } else {
            petBodyIntensity = std::min(1.0f, petBodyIntensity + energy + 0.07f);
        }

        petStrokeAccum_ += delta;
        if (!isCurrentlyPetting_ && petStrokeAccum_ > 45.0f) {
            isCurrentlyPetting_ = true;
            totalPetSessions++;
        }

        float dx = (canvasPoint.x - SeatAnchor.x) / 60.0f;
        headTilt.target = std::clamp(dx * 0.16f, -0.18f, 0.18f);
        headOffsetY.velocity += 18.0f;
    }

    void step(float rawDt, const RECT& windowRect, InputEngine& engine, const CatSettings& settings,
              bool douniTyping = false, bool douniSkin = false) {
        float dt = std::min(rawDt, 1.0f / 25.0f);
        time += dt;
        engine.pollMouse(dt);

        double now = nowSeconds();
        const auto& activeKeys = engine.activeKeys;
        const auto& orderedKeys = engine.pressedOrder;

        // 1. Petting decay & sparkles
        if (now - lastPetTime_ > 0.28) {
            petHeadIntensity = std::max(0.0f, petHeadIntensity - dt * 1.4f);
            petBodyIntensity = std::max(0.0f, petBodyIntensity - dt * 1.2f);
            if (petHeadIntensity < 0.05f && petBodyIntensity < 0.05f) {
                isCurrentlyPetting_ = false;
                petStrokeAccum_ = 0.0f;
            }
        } else if (petHeadIntensity > 0.55f || petBodyIntensity > 0.55f) {
            petSparkleCooldown_ -= dt;
            if (petSparkleCooldown_ <= 0.0f) {
                petSparkleCooldown_ = 0.42f;
                sparkles.push_back({
                    { SeatAnchor.x + randRange(-44.0f, 44.0f), 88.0f + randRange(-14.0f, 18.0f) },
                    { randRange(-10.0f, 10.0f), -24.0f },
                    0.0f, 0.9f, false
                });
            }
        }

        // 2. Sleepy idle detection (+ cute yawn right before drifting off to sleep!)
        double lastAny = std::max(engine.lastKeyActivityTime, std::max(engine.lastMouseMoveTime, lastPetTime_));
        double idleSec = lastAny > 0.0 ? (now - lastAny) : 0.0;
        if (activeKeys.empty() && idleSec > 42.0 && !isYawning_ && !hasYawnedThisIdle_) {
            isYawning_ = true;
            hasYawnedThisIdle_ = true;
            yawnTimer_ = 0.0f;
        }
        if (!activeKeys.empty() || idleSec < 5.0) {
            isYawning_ = false;
            hasYawnedThisIdle_ = false;
            yawnAmount = std::max(0.0f, yawnAmount - dt * 6.0f);
        } else if (isYawning_) {
            yawnTimer_ += dt;
            if (yawnTimer_ < 0.65f) {
                float u = yawnTimer_ / 0.65f;
                yawnAmount = u * u * (3.0f - 2.0f * u);
            } else if (yawnTimer_ < 1.55f) {
                yawnAmount = 1.0f;
            } else if (yawnTimer_ < 2.35f) {
                float u = (2.35f - yawnTimer_) / 0.80f;
                yawnAmount = u * u * (3.0f - 2.0f * u);
            } else {
                yawnAmount = 0.0f;
                isYawning_ = false;
            }
        } else {
            yawnAmount = std::max(0.0f, yawnAmount - dt * 4.0f);
        }
        if (activeKeys.empty() && idleSec > 45.0) {
            float targetSleep = std::min(1.0f, (float)((idleSec - 45.0) / 35.0));
            sleepiness += (targetSleep - sleepiness) * dt * 1.5f;
            if (sleepiness > 0.8f) {
                sleepZCooldown_ -= dt;
                if (sleepZCooldown_ <= 0.0f) {
                    sleepZCooldown_ = 2.6f;
                    sparkles.push_back({ { SeatAnchor.x + 42.0f, 100.0f }, { 12.0f, -18.0f }, 0.0f, 1.1f, true });
                }
            }
        } else {
            sleepiness = std::max(0.0f, sleepiness - dt * 5.0f);
        }

        // 2b. Fast Mouse Movement -> Hunting Mode (big round boba pupils + low crouch!)
        // Sustained > 10s of rapid mouse shaking -> Dizzy spiral eyes & slump beside keyboard!
        float mouseSpeed = std::hypot(engine.mouseVelocity.x, engine.mouseVelocity.y);
        if (!isScruffDragging_ && dizzyTimer_ <= 0.0f && mouseSpeed > 1500.0f && petHeadIntensity < 0.25f && petBodyIntensity < 0.25f) {
            float boost = std::min(1.0f, (mouseSpeed - 1500.0f) / 1800.0f);
            huntIntensity.target = std::min(1.0f, huntIntensity.target + (0.40f + boost * 1.25f) * dt);
            sleepiness = 0.0f;
        } else {
            huntIntensity.target = std::max(0.0f, huntIntensity.target - dt * 1.15f);
        }
        huntIntensity.step(dt, 85.0f, 16.0f);
        float hunt = std::clamp(huntIntensity.value, 0.0f, 1.0f);

        if (!isScruffDragging_ && dizzyTimer_ <= 0.0f && hunt > 0.42f) {
            fastMouseDuration_ += dt;
            if (fastMouseDuration_ >= 10.0f) {
                dizzyTimer_ = 6.0f;
                fastMouseDuration_ = 0.0f;
                huntIntensity.target = 0.0f;
                sleepiness = 0.0f;
            }
        } else if (dizzyTimer_ <= 0.0f) {
            fastMouseDuration_ = std::max(0.0f, fastMouseDuration_ - dt * 1.5f);
        }
        if (dizzyTimer_ > 0.0f) {
            dizzyTimer_ = std::max(0.0f, dizzyTimer_ - dt);
            dizzyIntensity.target = 1.0f;
            dizzyPhase += dt * 7.5f;
        } else if (fastMouseDuration_ > 6.8f) {
            // Stage 2 (6.8s -> 10.0s): Pre-dizzy warning — stars appear first, then spiral eyes & upright wobble!
            float pre = std::min(1.0f, (fastMouseDuration_ - 6.8f) / 3.2f);
            dizzyIntensity.target = pre * 0.48f;
            dizzyPhase += dt * 7.5f;
        } else {
            dizzyIntensity.target = 0.0f;
        }
        dizzyIntensity.step(dt, 75.0f, 14.0f);
        float dizzy = std::clamp(dizzyIntensity.value, 0.0f, 1.0f);

        if (!settings.enableDragAnimation && isScruffDragging_) {
            isScruffDragging_ = false;
        }
        if (isScruffDragging_) {
            scruffHoldTime += dt;
            scruffDropTimer = 0.0f;
            float frameScale = (1.0f / 60.0f) / std::max(dt, 1.0f / 120.0f);
            float instDx = scruffDragAccumX_ * frameScale;
            float instDy = scruffDragAccumY_ * frameScale;
            scruffDragAccumX_ = 0.0f;
            scruffDragAccumY_ = 0.0f;
            scruffDragDx_ = scruffDragDx_ * 0.52f + instDx * 0.85f;
            scruffDragDy_ = scruffDragDy_ * 0.52f + instDy * 0.85f;
        } else {
            scruffDropTimer = std::max(0.0f, scruffDropTimer - dt);
            if (scruffDrag.value < 0.02f) scruffHoldTime = 0.0f;
            scruffDragDx_ *= 0.80f;
            scruffDragDy_ *= 0.80f;
        }
        scruffDrag.target = isScruffDragging_ ? 1.0f : 0.0f;
        scruffSwing.target = isScruffDragging_ ? 0.92f * std::tanh(scruffDragDx_ / 18.0f) : 0.0f;
        scruffSwingY.target = isScruffDragging_ ? 0.78f * std::tanh(-scruffDragDy_ / 18.0f) : 0.0f;
        scruffTailSwing.target = isScruffDragging_ ? 1.22f * std::tanh(scruffDragDx_ / 16.0f) : 0.0f;
        scruffDrag.step(dt, 190.0f, 17.0f);
        scruffSwing.step(dt, 92.0f, 7.4f);
        scruffSwingY.step(dt, 108.0f, 8.4f);
        scruffTailSwing.step(dt, 58.0f, 5.2f);
        float scruff = std::clamp(scruffDrag.value, 0.0f, 1.0f);

        lieIntensity.target = (!isScruffDragging_ && dizzyTimer_ <= 0.0f && sleepiness > 0.65f)
            ? std::min(1.0f, (sleepiness - 0.65f) / 0.30f) : 0.0f;
        lieIntensity.step(dt, 55.0f, 14.0f);
        float lie = std::clamp(lieIntensity.value, 0.0f, 1.0f);

        // Low-frequency episodic anger: ~3.2s of brisk typing (>= 260 KPM) triggers a brief ~4.2s grumpy burst,
        // followed by a ~28s cooldown so fast typists get occasional cute anger without staying angry non-stop!
        float kpmVal = (float)engine.currentKPM();
        if (!settings.enableAnger || isScruffDragging_ || dizzyTimer_ > 0.0f) {
            fastTypeAccum_ = 0.0f;
            angerBurstTimer_ = 0.0f;
            angerCooldown_ = std::max(0.0f, angerCooldown_ - dt);
            angerIntensity.target = 0.0f;
        } else if (angerBurstTimer_ > 0.0f) {
            float sootheMul = (petHeadIntensity > 0.25f || petBodyIntensity > 0.25f || kpmVal < 80.0f) ? 2.6f : 1.0f;
            angerBurstTimer_ = std::max(0.0f, angerBurstTimer_ - dt * sootheMul);
            angerIntensity.target = std::min(1.0f, angerBurstTimer_ / 0.7f);
        } else {
            if (angerCooldown_ > 0.0f) {
                angerCooldown_ = std::max(0.0f, angerCooldown_ - dt);
                fastTypeAccum_ = std::max(0.0f, fastTypeAccum_ - dt * 1.2f);
            } else if (kpmVal >= 260.0f) {
                float speedFactor = std::min(1.8f, 0.75f + (kpmVal - 260.0f) / 220.0f);
                fastTypeAccum_ += dt * speedFactor;
                if (fastTypeAccum_ >= 3.2f) {
                    angerBurstTimer_ = 4.2f;
                    angerCooldown_ = 28.0f + (float)(((int)(time * 13.0f)) % 9) - 4.0f;
                    fastTypeAccum_ = 0.0f;
                }
            } else {
                fastTypeAccum_ = std::max(0.0f, fastTypeAccum_ - dt * 0.9f);
            }
            angerIntensity.target = 0.0f;
        }
        angerIntensity.step(dt, 70.0f, 14.0f);
        float anger = std::clamp(angerIntensity.value, 0.0f, 1.0f);

        // 3. Limb assignment (Left Paw, Right Paw, 3-Key Hind Foot!)
        constexpr double tapHoldWindow = 0.14;
        bool mouseRecent = (now - engine.lastMouseMoveTime < 2.2) || engine.leftMouseDown || engine.rightMouseDown;
        bool mouseActivelyUsed = (now - engine.lastMouseMoveTime < 0.75) || engine.leftMouseDown || engine.rightMouseDown;

        std::vector<PhysicalKey> leftCands, rightCands;
        for (PhysicalKey k : orderedKeys) {
            if (prefersViewerLeftPaw(k)) leftCands.push_back(k);
            else rightCands.push_back(k);
        }

        PhysicalKey leftKey = leftCands.empty() ? PhysicalKey::None : leftCands.back();
        PhysicalKey rightKey = rightCands.empty() ? PhysicalKey::None : rightCands.back();
        PhysicalKey footKey = PhysicalKey::None;

        if (leftKey == PhysicalKey::None && rightCands.size() >= 2 && !mouseActivelyUsed) {
            auto sorted = rightCands;
            std::sort(sorted.begin(), sorted.end(), [](PhysicalKey a, PhysicalKey b) {
                return KeyboardLayout::canvasPointForKey(a).x < KeyboardLayout::canvasPointForKey(b).x;
            });
            leftKey = sorted.front();
            rightKey = sorted.back();
        } else if (rightKey == PhysicalKey::None && leftCands.size() >= 2) {
            auto sorted = leftCands;
            std::sort(sorted.begin(), sorted.end(), [](PhysicalKey a, PhysicalKey b) {
                return KeyboardLayout::canvasPointForKey(a).x < KeyboardLayout::canvasPointForKey(b).x;
            });
            leftKey = sorted.front();
            rightKey = sorted.back();
        }

        if (settings.footEasterEgg) {
            if (orderedKeys.size() >= 3) {
                for (PhysicalKey k : orderedKeys) {
                    if (k != leftKey && k != rightKey) { footKey = k; break; }
                }
            } else if (mouseActivelyUsed && leftKey == PhysicalKey::None && rightCands.size() >= 2) {
                for (PhysicalKey k : rightCands) {
                    if (k != rightKey) { footKey = k; break; }
                }
            }
        }

        if (leftKey == PhysicalKey::None && recentLeftKey_ != PhysicalKey::None && now - recentLeftTime_ < tapHoldWindow) {
            leftKey = recentLeftKey_;
        }
        if (rightKey == PhysicalKey::None && recentRightKey_ != PhysicalKey::None && now - recentRightTime_ < tapHoldWindow) {
            rightKey = recentRightKey_;
        }

        // Subtle mini-mouse movement
        mouseOffset.setTarget({
            std::clamp(engine.mouseVelocity.x * 0.0045f, -5.5f, 5.5f),
            std::clamp(engine.mouseVelocity.y * 0.0045f, -4.5f, 4.5f)
        });
        mouseOffset.step(dt, 120.0f, 16.0f);
        mousePressLeft.step(dt, 400.0f, 24.0f);
        mousePressRight.step(dt, 400.0f, 24.0f);

        Pt liveMouse = { MouseBaseCenter.x + mouseOffset.point().x, MouseBaseCenter.y + mouseOffset.point().y };

        isTabletActive = (settings.tabletMode == 1) || (settings.tabletMode == 0 && engine.isTabletConnected());
        if (isTabletActive) {
            RECT monRect = { 0, 0, GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN) };
            HMONITOR hm = MonitorFromPoint(engine.lastCursorPos, MONITOR_DEFAULTTONEAREST);
            MONITORINFO mi = {}; mi.cbSize = sizeof(mi);
            if (hm && GetMonitorInfoW(hm, &mi)) monRect = mi.rcMonitor;
            float mw = std::max(1.0f, (float)(monRect.right - monRect.left));
            float mh = std::max(1.0f, (float)(monRect.bottom - monRect.top));
            float nx = std::clamp((float)(engine.lastCursorPos.x - monRect.left) / mw, 0.0f, 1.0f);
            float ny = std::clamp((float)(engine.lastCursorPos.y - monRect.top) / mh, 0.0f, 1.0f);
            tabletNib.setTarget(tabletQuadPoint(0.25f + nx * 0.64f, 0.16f + ny * 0.68f));
            tabletNib.step(dt, 240.0f, 20.0f);
            tabletPenPress.target = engine.leftMouseDown ? 0.88f : 0.0f;
            tabletPenPress.step(dt, 360.0f, 22.0f);
            tabletPenTilt.target = std::clamp(engine.mouseVelocity.x * 0.00018f, -0.22f, 0.22f);
            tabletPenTilt.step(dt, 120.0f, 14.0f);
        } else {
            tabletPenPress.target = 0.0f;
            tabletPenPress.step(dt, 300.0f, 22.0f);
        }
        for (int i = (int)tabletTrail.size() - 1; i >= 0; --i) {
            tabletTrail[i].age += dt;
            if (tabletTrail[i].age >= 0.72f) tabletTrail.erase(tabletTrail.begin() + i);
        }

        if (douniTyping) {
            douniSlapTimer = std::max(0.0f, douniSlapTimer - dt);
            bool leftHeldNow = false;
            bool rightHeldNow = false;
            for (PhysicalKey k : activeKeys) {
                if (prefersViewerLeftPaw(k)) leftHeldNow = true;
                else rightHeldNow = true;
            }
            if (douniSlapTimer <= 0.08f) {
                if (!leftHeldNow) {
                    douniLeftRaise.target = 0.0f;
                } else if (douniLeftRaise.target > 0.2f) {
                    douniLeftRaise.target = -0.85f;
                }
                if (!rightHeldNow) {
                    douniRightRaise.target = 0.0f;
                } else if (douniRightRaise.target > 0.2f) {
                    douniRightRaise.target = -0.85f;
                }
            }
            douniLeftRaise.step(dt, 680.0f, 25.0f);
            douniRightRaise.step(dt, 680.0f, 25.0f);
            douniLeftKeyTarget.step(dt, 820.0f, 28.0f);
            douniRightKeyTarget.step(dt, 820.0f, 28.0f);
            kbImpactY.target = 0.0f;
            kbImpactTilt.target = 0.0f;
            kbImpactY.step(dt, 560.0f, 16.0f);
            kbImpactTilt.step(dt, 500.0f, 14.0f);
            kbSparkTimer = std::max(0.0f, kbSparkTimer - dt);
        } else {
            douniSlapTimer = 0.0f;
            douniLeftRaise.target = 0.0f;
            douniRightRaise.target = 0.0f;
            kbImpactY.value = 0.0f;
            kbImpactTilt.value = 0.0f;
            kbSparkTimer = 0.0f;
        }
        if (douniSkin) {
            // Deliberate petting threshold (avoids abrupt hijacking on 1px cursor brush or fast hunting whip!) + silky Disney ease spring
            bool wantsLoaf = !isScruffDragging_ && scruff < 0.08f && dizzy < 0.15f && hunt < 0.22f
                && (petHeadIntensity > 0.30f || isCurrentlyPetting_ || petBodyIntensity > 0.35f || sleepiness > 0.48f);
            douniLoafBlend.target = wantsLoaf ? 1.0f : 0.0f;
            douniLoafBlend.step(dt, 52.0f, 13.5f);
            bool typingNow = (douniSlapTimer > 0.04f || !activeKeys.empty());
            bool tabletUsed = isTabletActive && (engine.leftMouseDown || mouseActivelyUsed);
            bool wantsMouse = !isScruffDragging_ && !wantsLoaf && !typingNow && (mouseActivelyUsed || tabletUsed);
            douniMouseBlend.target = wantsMouse ? 1.0f : 0.0f;
            douniMouseBlend.step(dt, wantsMouse ? 280.0f : 460.0f, wantsMouse ? 22.0f : 28.0f);
            // Keep tablet ink trail alive for Xiao Douni when drawing on the hand-drawn comic tablet!
            if (isTabletActive && wantsMouse && engine.leftMouseDown) {
                Pt nib = tabletNib.point();
                if (tabletTrail.empty() || std::hypot(nib.x - tabletTrail.back().point.x, nib.y - tabletTrail.back().point.y) >= 1.8f) {
                    tabletTrail.push_back({ nib, 0.0f });
                    if (tabletTrail.size() > 28) tabletTrail.erase(tabletTrail.begin());
                }
            }
        } else {
            douniLoafBlend.value = 0.0f; douniLoafBlend.target = 0.0f;
            douniMouseBlend.value = 0.0f; douniMouseBlend.target = 0.0f;
        }
        bool douniActive = douniTyping && (douniSlapTimer > 0.01f || !activeKeys.empty()) && scruff <= 0.25f && dizzy <= 0.35f && lie <= 0.45f;

        if (scruff > 0.24f) {
            float scruffS = scruff * scruff * (3.0f - 2.0f * scruff);
            float liftSeatY = SeatAnchor.y - scruffS * 44.0f;
            float lSway = scruffSwing.value * 24.0f + std::sin(time * 7.6f) * 3.0f;
            float lBob  = std::cos(time * 7.6f) * 2.2f;
            float rSway = scruffSwing.value * 24.0f + std::sin(time * 7.6f + 2.1f) * 3.0f;
            float rBob  = std::cos(time * 7.6f + 2.1f) * 2.2f;
            leftPaw.setTarget({ SeatAnchor.x + bodyShiftX.value - 20.0f + lSway, liftSeatY + 24.0f + lBob });
            rightPaw.setTarget({ SeatAnchor.x + bodyShiftX.value + 16.0f + rSway, liftSeatY + 24.0f + rBob });
            hindFoot.setTarget(HindFootRest);
            hindFootActive.target = 0.0f;
            leftPawTyping = true;
            rightPawTyping = true;
            leftPawOnMouse = false;
        } else if (dizzy > 0.35f) {
            leftPaw.setTarget(LeftPawRest);
            rightPaw.setTarget(RightPawRest);
            hindFoot.setTarget(HindFootRest);
            hindFootActive.target = 0.0f;
            leftPawTyping = false;
            rightPawTyping = false;
            leftPawOnMouse = false;
        } else if (lie > 0.45f) {
            leftPaw.setTarget(LeftPawRest);
            rightPaw.setTarget(RightPawRest);
            hindFoot.setTarget(HindFootRest);
            hindFootActive.target = 0.0f;
            leftPawTyping = false;
            rightPawTyping = false;
            leftPawOnMouse = false;
        } else {
            if (douniActive) {
                float raise = std::clamp(douniLeftRaise.value, 0.0f, 1.18f);
                float sx = SeatAnchor.x + bodyShiftX.value;
                Pt downPt = (leftKey != PhysicalKey::None) ? KeyboardLayout::canvasPointForKey(leftKey) : Pt{ sx - 44.0f, 246.0f };
                Pt highPt = { sx - 84.0f, 156.0f }; // High windup beside left cheek (Video 2!)
                leftPaw.setTarget({ downPt.x + (highPt.x - downPt.x) * raise, downPt.y + (highPt.y - downPt.y) * raise });
                leftPawTyping = true;
                leftPawOnMouse = false;
            } else if (leftKey != PhysicalKey::None) {
                leftPaw.setTarget(KeyboardLayout::canvasPointForKey(leftKey));
                leftPawTyping = true;
                leftPawOnMouse = false;
            } else if (mouseRecent && sleepiness < 0.3f) {
                if (isTabletActive) {
                    Pt nib = tabletNib.point();
                    leftPaw.setTarget({ nib.x + 6.0f, nib.y - 7.0f });
                    if (engine.leftMouseDown) {
                        if (tabletTrail.empty() || std::hypot(nib.x - tabletTrail.back().point.x, nib.y - tabletTrail.back().point.y) >= 1.8f) {
                            tabletTrail.push_back({ nib, 0.0f });
                            if (tabletTrail.size() > 28) tabletTrail.erase(tabletTrail.begin());
                        }
                    }
                } else {
                    leftPaw.setTarget({ liveMouse.x + 2.0f, liveMouse.y - 3.0f });
                }
                leftPawTyping = false;
                leftPawOnMouse = true;
            } else {
                leftPaw.setTarget(LeftPawRest);
                leftPawTyping = false;
                leftPawOnMouse = false;
            }

            if (douniActive) {
                float raise = std::clamp(douniRightRaise.value, 0.0f, 1.18f);
                float sx = SeatAnchor.x + bodyShiftX.value;
                Pt downPt = (rightKey != PhysicalKey::None) ? KeyboardLayout::canvasPointForKey(rightKey) : Pt{ sx + 22.0f, 246.0f };
                Pt highPt = { sx - 8.0f, 158.0f }; // High windup curled right across the cheek/face (Video 2!)
                rightPaw.setTarget({ downPt.x + (highPt.x - downPt.x) * raise, downPt.y + (highPt.y - downPt.y) * raise });
                rightPawTyping = true;
            } else if (rightKey != PhysicalKey::None) {
                rightPaw.setTarget(KeyboardLayout::canvasPointForKey(rightKey));
                rightPawTyping = true;
            } else {
                rightPaw.setTarget(RightPawRest);
                rightPawTyping = false;
            }

            if (footKey != PhysicalKey::None) {
                hindFoot.setTarget(KeyboardLayout::canvasPointForKey(footKey));
                hindFootActive.target = 1.0f;
            } else {
                hindFoot.setTarget(HindFootRest);
                hindFootActive.target = 0.0f;
            }
        }

        // Count held physical keys, never key-repeat events or mouse buttons.
        // Tail-only mode (!footEasterEgg && tailEasterEgg): 3+ keys (or 2+ keys while mouse is active) -> tail!
        bool tailOnlyTrigger = !settings.footEasterEgg && (orderedKeys.size() >= 3 || (mouseActivelyUsed && leftKey == PhysicalKey::None && orderedKeys.size() >= 2 && rightKey != PhysicalKey::None));
        bool tailActiveNow = settings.tailEasterEgg && (activeKeys.size() >= 4 || tailOnlyTrigger);
        tailTyping.target = tailActiveNow ? 1.0f : 0.0f;
        tailTyping.step(dt, 180.0f, 24.0f);
        // Marquee chase across the keyboard deck: a steady sweep that speeds up while
        // several keys are held, so a chord visibly "fan out" the light.
        if (settings.keyboardMarquee) {
            marqueeBoost.target = std::clamp(((float)activeKeys.size() - 2.0f) / 5.0f, 0.0f, 1.0f);
            marqueeBoost.step(dt, 90.0f, 20.0f);
            marqueePhase = std::fmod(marqueePhase + dt * (0.42f + 0.40f * marqueeBoost.value), 1.0f);
        }
        PhysicalKey tailKey = PhysicalKey::None;
        if (tailTyping.target > 0.0f) {
            for (PhysicalKey k : orderedKeys) {
                if (k != leftKey && k != rightKey && k != footKey) { tailKey = k; break; }
            }
        }
        Pt tip = tailKey != PhysicalKey::None ? KeyboardLayout::canvasPointForKey(tailKey) : Pt{275.0f, 196.0f};
        tip.y -= tailTyping.target * (1.0f + std::sin(time * 18.0f)) * 3.0f;
        tailTip.setTarget(tip);
        tailTip.step(dt, 280.0f, 26.0f);

        tailFlickHold = std::max(0.0f, tailFlickHold - dt);
        tailFlickCooldown = std::max(0.0f, tailFlickCooldown - dt);
        if (tailFlickHold <= 0.0f) {
            tailFlick.setTarget({0.0f, 0.0f});
            tailCurl.target = 0.0f;
            tailAgility.target = 0.0f;
        }
        tailFlick.step(dt, 150.0f, 12.0f);
        tailCurl.step(dt, 135.0f, 10.5f);
        tailAgility.step(dt, 40.0f, 10.0f);

        leftPaw.step(dt, 360.0f, 24.0f);
        rightPaw.step(dt, 360.0f, 24.0f);
        hindFoot.step(dt, 320.0f, 22.0f);
        hindFootActive.step(dt, 260.0f, 22.0f);

        // 4. Body lean, squash & ear motion
        float targetShiftX = 0.0f, targetBodyTilt = 0.0f;
        if (leftPawOnMouse && !rightPawTyping) {
            targetShiftX = -10.0f;
            targetBodyTilt = -0.075f;
        } else if (leftPawOnMouse && rightPawTyping) {
            targetShiftX = -3.0f;
            targetBodyTilt = (rightPaw.point().x - 196.0f) * 0.0008f;
        } else if (leftPawTyping || rightPawTyping) {
            float avgX = ((leftPawTyping ? leftPaw.point().x : 184.0f) + (rightPawTyping ? rightPaw.point().x : 184.0f)) * 0.5f;
            targetShiftX = (avgX - 184.0f) * 0.14f;
            targetBodyTilt = (avgX - 184.0f) * 0.0011f;
        }
        bodyShiftX.target = std::clamp(targetShiftX, -16.0f, 16.0f);
        bodyTilt.target = std::clamp(targetBodyTilt, -0.12f, 0.12f) + scruffSwing.value * scruff;
        bodySquash.target = 1.0f - hunt * 0.11f + scruff * 0.16f;
        headOffsetY.target = ((leftPawTyping || rightPawTyping) ? 3.5f : (sleepiness * 5.0f + hunt * 10.5f))
            - scruff * 10.0f;
        earFold.target = std::max(petHeadIntensity * 0.7f, petBodyIntensity * 0.45f) + sleepiness * 0.25f - hunt * 0.18f
            + scruff * 0.35f + anger * 0.45f + dizzy * 0.35f;
        earTwitch.target = 0.0f;

        bodyShiftX.step(dt, 140.0f, 18.0f);
        bodyTilt.step(dt, 140.0f, 18.0f);
        bodySquash.step(dt, 280.0f, 18.0f);
        headOffsetY.step(dt, 180.0f, 19.0f);
        earFold.step(dt, 120.0f, 16.0f);
        earTwitch.step(dt, 320.0f, 16.0f);

        // 5. 2.5D Head Turning (Yaw + Pitch) & Eye Tracking (Windows screen Y is top-down!)
        bool typingRecently = !activeKeys.empty() || (now - engine.lastKeyActivityTime < 0.65);
        bool mouseMovedRecently = (now - engine.lastMouseMoveTime < 1.2);
        Pt eyeOrigin = { SeatAnchor.x + bodyShiftX.value, 124.0f + headOffsetY.value };

        float winW = std::max(1.0f, (float)(windowRect.right - windowRect.left));
        float winScale = std::max(0.2f, winW / CanvasWidth);
        float headScreenX = (float)windowRect.left + eyeOrigin.x * winScale;
        float headScreenY = (float)windowRect.top  + eyeOrigin.y * winScale;

        float curDx = ((float)engine.lastCursorPos.x - headScreenX) / 290.0f;
        float curDy = ((float)engine.lastCursorPos.y - headScreenY) / 260.0f;
        float curMag = std::hypot(curDx, curDy);
        float clampedCur = std::min(1.0f, curMag);
        float cursorNX = curMag > 0.001f ? (curDx / curMag) * clampedCur : 0.0f;
        float cursorNY = curMag > 0.001f ? (curDy / curMag) * clampedCur : 0.0f;

        float lookX = cursorNX, lookY = cursorNY;
        if (typingRecently && !mouseMovedRecently && hasLastTypedPoint_) {
            lookX = std::clamp((lastTypedPoint_.x - eyeOrigin.x) / 95.0f, -0.85f, 0.85f);
            lookY = std::clamp((lastTypedPoint_.y - eyeOrigin.y) / 125.0f, -0.3f, 0.92f);
        } else if (typingRecently && mouseMovedRecently && hasLastTypedPoint_) {
            float kdx = std::clamp((lastTypedPoint_.x - eyeOrigin.x) / 95.0f, -0.85f, 0.85f);
            lookX = cursorNX * 0.72f + kdx * 0.28f;
            lookY = cursorNY * 0.72f + 0.25f;
        }

        if (sleepiness > 0.45f) {
            headYaw.target = 0.0f;
            headPitch.target = 0.45f * sleepiness;
        } else {
            headYaw.target = std::clamp(lookX, -1.0f, 1.0f);
            headPitch.target = std::clamp(lookY, -1.0f, 1.0f);
        }
        float headStiff = 88.0f + hunt * 75.0f;
        float headDamp  = 14.5f + hunt * 4.5f;
        headYaw.step(dt, headStiff, headDamp);
        headPitch.step(dt, headStiff, headDamp);

        if (now - lastPetTime_ > 0.28) {
            headTilt.target = bodyTilt.target * 0.45f + headYaw.value * (0.11f + hunt * 0.05f) - headYaw.value * headPitch.value * 0.04f + lie * 0.12f;
        }
        headTilt.step(dt, 130.0f, 16.0f);

        eyeGaze.setTarget({ lookX * 0.88f, lookY * 0.85f });
        eyeGaze.step(dt, 210.0f + hunt * 80.0f, 21.0f);

        if (hindFootActive.value > 0.3f) {
            pupilScale.target = 1.24f;
        } else if (now - engine.lastKeyActivityTime > 0.45 && now - engine.lastMouseClickTime > 0.45) {
            pupilScale.target = 1.0f;
        }
        pupilScale.step(dt, 150.0f, 18.0f);

        // 6. Blinking (no blinking during locked-on hunting!)
        if (isBlinking_) {
            blinkTimer_ += dt;
            constexpr float blinkDur = 0.14f;
            if (blinkTimer_ >= blinkDur) {
                isBlinking_ = false;
                blinkProgress_ = 0.0f;
                nextBlinkTime_ = time + randRange(2.6f, 5.6f);
            } else {
                blinkProgress_ = std::sin((blinkTimer_ / blinkDur) * 3.14159265f);
            }
        } else if (time >= nextBlinkTime_ && sleepiness < 0.5f && petHeadIntensity < 0.3f && hunt < 0.35f) {
            isBlinking_ = true;
            blinkTimer_ = 0.0f;
        }

        // 7. Tail wag speed
        float kpmBoost = std::min(2.4f, (float)engine.currentKPM() / 160.0f);
        float petBoost = std::max(petHeadIntensity, petBodyIntensity) * 1.4f;
        float agilityBoost = std::clamp(tailAgility.value, 0.0f, 1.0f) * 3.2f;
        float tailSpeed = 1.85f + kpmBoost + petBoost + hunt * 2.8f + anger * 3.5f + agilityBoost - sleepiness * 1.1f;
        tailPhase += dt * tailSpeed;

        // 8. Keycap glow decay
        std::unordered_set<PhysicalKey> visualActive;
        for (PhysicalKey k : activeKeys) visualActive.insert(visualKeyOf(k));
        for (auto it = keyGlow.begin(); it != keyGlow.end(); ) {
            if (visualActive.count(it->first)) {
                it->second = 1.0f;
                ++it;
            } else {
                it->second -= dt * 4.5f;
                if (it->second <= 0.01f) it = keyGlow.erase(it);
                else ++it;
            }
        }
        for (PhysicalKey vk : visualActive) keyGlow[vk] = 1.0f;

        // 9. Floating keycaps
        for (int i = (int)floatingKeycaps.size() - 1; i >= 0; --i) {
            auto& b = floatingKeycaps[i];
            b.age += dt;
            b.position.x += b.velocity.x * dt;
            b.position.y += b.velocity.y * dt;
            b.velocity.x *= (1.0f - dt * 2.4f);
            b.velocity.y *= (1.0f - dt * 1.6f);
            if (b.age >= b.lifetime) floatingKeycaps.erase(floatingKeycaps.begin() + i);
        }

        // 10. Sparkles / Sleep Z
        for (int i = (int)sparkles.size() - 1; i >= 0; --i) {
            auto& sp = sparkles[i];
            sp.age += dt;
            sp.position.x += sp.velocity.x * dt;
            sp.position.y += sp.velocity.y * dt;
            if (sp.age >= sp.lifetime) sparkles.erase(sparkles.begin() + i);
        }
    }

private:
    float nextBlinkTime_ = 3.2f;
    float blinkProgress_ = 0.0f;
    bool isBlinking_ = false;
    float blinkTimer_ = 0.0f;

    float petStrokeAccum_ = 0.0f;
    double lastPetTime_ = 0.0;
    bool isCurrentlyPetting_ = false;
    float petSparkleCooldown_ = 0.0f;
    float sleepZCooldown_ = 0.0f;

    PhysicalKey recentLeftKey_ = PhysicalKey::None;
    double recentLeftTime_ = 0.0;
    PhysicalKey recentRightKey_ = PhysicalKey::None;
    double recentRightTime_ = 0.0;
    bool hasLastTypedPoint_ = false;
    Pt lastTypedPoint_ = { 184.0f, 260.0f };

    int badgeCascade_ = 0;
    double lastBadgeTime_ = 0.0;

    static float randRange(float a, float b) {
        static thread_local std::mt19937 rng{ std::random_device{}() };
        std::uniform_real_distribution<float> dist(a, b);
        return dist(rng);
    }

    void spawnFloatingKeycap(const std::wstring& label, Pt pt, double now) {
        if (label.empty()) return;
        if (now - lastBadgeTime_ < 0.38) badgeCascade_ = (badgeCascade_ + 1) % 6;
        else badgeCascade_ = 0;
        lastBadgeTime_ = now;

        static const float spread[6] = { -10.0f, 14.0f, -22.0f, 26.0f, 2.0f, 36.0f };
        float dx = spread[badgeCascade_] + randRange(-3.0f, 3.0f);
        float startX = std::clamp(pt.x + dx * 0.45f, 55.0f, 315.0f);
        float startY = pt.y - 26.0f - (float)(badgeCascade_ % 2) * 8.0f;

        floatingKeycaps.push_back({
            label,
            { startX, startY },
            { dx * 0.65f, -36.0f - randRange(0.0f, 14.0f) },
            0.0f, 1.25f, randRange(-0.07f, 0.07f)
        });
        if (floatingKeycaps.size() > 16) {
            floatingKeycaps.erase(floatingKeycaps.begin(), floatingKeycaps.begin() + (floatingKeycaps.size() - 16));
        }
    }
};
