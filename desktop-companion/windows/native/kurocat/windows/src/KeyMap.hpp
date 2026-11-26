#pragma once
#define NOMINMAX
#include <windows.h>
#include <string>
#include <vector>
#include <unordered_map>
#include <algorithm>
#include <cmath>

struct Pt {
    float x = 0.0f;
    float y = 0.0f;
};

enum class PhysicalKey {
    Escape, K1, K2, K3, K4, K5, K6, K7, K8, K9, K0, Minus, Equal, Backspace,
    Tab, Q, W, E, R, T, Y, U, I, O, P, LeftBracket, RightBracket, Backslash,
    CapsLock, A, S, D, F, G, H, J, K, L, Semicolon, Quote, Enter,
    LeftShift, Z, X, C, V, B, N, M, Comma, Period, Slash, RightShift, ArrowUp,
    LeftControl, LeftOption, LeftCommand, Space, RightCommand, RightOption, Fn, ArrowLeft, ArrowDown, ArrowRight,
    Grave, RightControl, ForwardDelete,
    F1, F2, F3, F4, F5, F6, F7, F8, F9, F10, F11, F12,
    None
};

inline std::wstring keyBadgeLabel(PhysicalKey k) {
    switch (k) {
        case PhysicalKey::Escape: return L"ESC";
        case PhysicalKey::Grave: return L"~";
        case PhysicalKey::K1: return L"1"; case PhysicalKey::K2: return L"2";
        case PhysicalKey::K3: return L"3"; case PhysicalKey::K4: return L"4";
        case PhysicalKey::K5: return L"5"; case PhysicalKey::K6: return L"6";
        case PhysicalKey::K7: return L"7"; case PhysicalKey::K8: return L"8";
        case PhysicalKey::K9: return L"9"; case PhysicalKey::K0: return L"0";
        case PhysicalKey::Minus: return L"-"; case PhysicalKey::Equal: return L"=";
        case PhysicalKey::Backspace: return L"BK";
        case PhysicalKey::ForwardDelete: return L"DEL";
        case PhysicalKey::Tab: return L"TAB";
        case PhysicalKey::Q: return L"Q"; case PhysicalKey::W: return L"W";
        case PhysicalKey::E: return L"E"; case PhysicalKey::R: return L"R";
        case PhysicalKey::T: return L"T"; case PhysicalKey::Y: return L"Y";
        case PhysicalKey::U: return L"U"; case PhysicalKey::I: return L"I";
        case PhysicalKey::O: return L"O"; case PhysicalKey::P: return L"P";
        case PhysicalKey::LeftBracket: return L"["; case PhysicalKey::RightBracket: return L"]";
        case PhysicalKey::Backslash: return L"\\";
        case PhysicalKey::CapsLock: return L"CAP";
        case PhysicalKey::A: return L"A"; case PhysicalKey::S: return L"S";
        case PhysicalKey::D: return L"D"; case PhysicalKey::F: return L"F";
        case PhysicalKey::G: return L"G"; case PhysicalKey::H: return L"H";
        case PhysicalKey::J: return L"J"; case PhysicalKey::K: return L"K";
        case PhysicalKey::L: return L"L";
        case PhysicalKey::Semicolon: return L";"; case PhysicalKey::Quote: return L"'";
        case PhysicalKey::Enter: return L"\u21B5";
        case PhysicalKey::LeftShift:
        case PhysicalKey::RightShift: return L"\u21E7";
        case PhysicalKey::Z: return L"Z"; case PhysicalKey::X: return L"X";
        case PhysicalKey::C: return L"C"; case PhysicalKey::V: return L"V";
        case PhysicalKey::B: return L"B"; case PhysicalKey::N: return L"N";
        case PhysicalKey::M: return L"M";
        case PhysicalKey::Comma: return L","; case PhysicalKey::Period: return L".";
        case PhysicalKey::Slash: return L"/";
        case PhysicalKey::LeftControl:
        case PhysicalKey::RightControl: return L"CTL";
        case PhysicalKey::LeftOption:
        case PhysicalKey::RightOption: return L"ALT";
        case PhysicalKey::LeftCommand:
        case PhysicalKey::RightCommand: return L"WIN";
        case PhysicalKey::Space: return L"\u2423";
        case PhysicalKey::Fn: return L"Fn";
        case PhysicalKey::ArrowUp: return L"\u2191";
        case PhysicalKey::ArrowDown: return L"\u2193";
        case PhysicalKey::ArrowLeft: return L"\u2190";
        case PhysicalKey::ArrowRight: return L"\u2192";
        case PhysicalKey::F1: return L"F1"; case PhysicalKey::F2: return L"F2";
        case PhysicalKey::F3: return L"F3"; case PhysicalKey::F4: return L"F4";
        case PhysicalKey::F5: return L"F5"; case PhysicalKey::F6: return L"F6";
        case PhysicalKey::F7: return L"F7"; case PhysicalKey::F8: return L"F8";
        case PhysicalKey::F9: return L"F9"; case PhysicalKey::F10: return L"F10";
        case PhysicalKey::F11: return L"F11"; case PhysicalKey::F12: return L"F12";
        default: return L"";
    }
}

inline PhysicalKey visualKeyOf(PhysicalKey k) {
    switch (k) {
        case PhysicalKey::Grave: return PhysicalKey::Escape;
        case PhysicalKey::ForwardDelete: return PhysicalKey::Backspace;
        case PhysicalKey::RightControl: return PhysicalKey::RightOption;
        case PhysicalKey::F1: return PhysicalKey::K1;
        case PhysicalKey::F2: return PhysicalKey::K2;
        case PhysicalKey::F3: return PhysicalKey::K3;
        case PhysicalKey::F4: return PhysicalKey::K4;
        case PhysicalKey::F5: return PhysicalKey::K5;
        case PhysicalKey::F6: return PhysicalKey::K6;
        case PhysicalKey::F7: return PhysicalKey::K7;
        case PhysicalKey::F8: return PhysicalKey::K8;
        case PhysicalKey::F9: return PhysicalKey::K9;
        case PhysicalKey::F10: return PhysicalKey::K0;
        case PhysicalKey::F11: return PhysicalKey::Minus;
        case PhysicalKey::F12: return PhysicalKey::Equal;
        default: return k;
    }
}

/// Viewer-left paw = cat's RIGHT hand (mouse + right side of keyboard).
/// Viewer-right paw = cat's LEFT hand (WASD, Q-T, A-G, Z-B, Space, Esc, Shift).
inline bool prefersViewerLeftPaw(PhysicalKey k) {
    switch (visualKeyOf(k)) {
        case PhysicalKey::Escape: case PhysicalKey::K1: case PhysicalKey::K2:
        case PhysicalKey::K3: case PhysicalKey::K4: case PhysicalKey::K5: case PhysicalKey::K6:
        case PhysicalKey::Tab: case PhysicalKey::Q: case PhysicalKey::W:
        case PhysicalKey::E: case PhysicalKey::R: case PhysicalKey::T:
        case PhysicalKey::CapsLock: case PhysicalKey::A: case PhysicalKey::S:
        case PhysicalKey::D: case PhysicalKey::F: case PhysicalKey::G:
        case PhysicalKey::LeftShift: case PhysicalKey::Z: case PhysicalKey::X:
        case PhysicalKey::C: case PhysicalKey::V: case PhysicalKey::B:
        case PhysicalKey::LeftControl: case PhysicalKey::LeftOption: case PhysicalKey::LeftCommand:
        case PhysicalKey::Space:
            return false;
        default:
            return true;
    }
}

/// Map Windows Raw Input hardware scancode + E0 flag (+ VKey fallback) -> PhysicalKey.
/// Scancodes are completely independent of IME state and work inside DirectX/Vulkan games!
inline PhysicalKey mapRawInputKey(USHORT makeCode, USHORT flags, USHORT vkey) {
    bool isE0 = (flags & RI_KEY_E0) != 0;

    if (isE0) {
        switch (makeCode) {
            case 0x1C: return PhysicalKey::Enter;        // Numpad Enter
            case 0x1D: return PhysicalKey::RightControl;
            case 0x35: return PhysicalKey::Slash;
            case 0x38: return PhysicalKey::RightOption;  // Right Alt
            case 0x48: return PhysicalKey::ArrowUp;
            case 0x4B: return PhysicalKey::ArrowLeft;
            case 0x4D: return PhysicalKey::ArrowRight;
            case 0x50: return PhysicalKey::ArrowDown;
            case 0x53: return PhysicalKey::ForwardDelete;
            case 0x5B: return PhysicalKey::LeftCommand;  // Left Win
            case 0x5C: return PhysicalKey::RightCommand; // Right Win
            default: break;
        }
    } else {
        switch (makeCode) {
            case 0x01: return PhysicalKey::Escape;
            case 0x02: return PhysicalKey::K1;
            case 0x03: return PhysicalKey::K2;
            case 0x04: return PhysicalKey::K3;
            case 0x05: return PhysicalKey::K4;
            case 0x06: return PhysicalKey::K5;
            case 0x07: return PhysicalKey::K6;
            case 0x08: return PhysicalKey::K7;
            case 0x09: return PhysicalKey::K8;
            case 0x0A: return PhysicalKey::K9;
            case 0x0B: return PhysicalKey::K0;
            case 0x0C: return PhysicalKey::Minus;
            case 0x0D: return PhysicalKey::Equal;
            case 0x0E: return PhysicalKey::Backspace;
            case 0x0F: return PhysicalKey::Tab;
            case 0x10: return PhysicalKey::Q;
            case 0x11: return PhysicalKey::W;
            case 0x12: return PhysicalKey::E;
            case 0x13: return PhysicalKey::R;
            case 0x14: return PhysicalKey::T;
            case 0x15: return PhysicalKey::Y;
            case 0x16: return PhysicalKey::U;
            case 0x17: return PhysicalKey::I;
            case 0x18: return PhysicalKey::O;
            case 0x19: return PhysicalKey::P;
            case 0x1A: return PhysicalKey::LeftBracket;
            case 0x1B: return PhysicalKey::RightBracket;
            case 0x1C: return PhysicalKey::Enter;
            case 0x1D: return PhysicalKey::LeftControl;
            case 0x1E: return PhysicalKey::A;
            case 0x1F: return PhysicalKey::S;
            case 0x20: return PhysicalKey::D;
            case 0x21: return PhysicalKey::F;
            case 0x22: return PhysicalKey::G;
            case 0x23: return PhysicalKey::H;
            case 0x24: return PhysicalKey::J;
            case 0x25: return PhysicalKey::K;
            case 0x26: return PhysicalKey::L;
            case 0x27: return PhysicalKey::Semicolon;
            case 0x28: return PhysicalKey::Quote;
            case 0x29: return PhysicalKey::Grave;
            case 0x2A: return PhysicalKey::LeftShift;
            case 0x2B: return PhysicalKey::Backslash;
            case 0x2C: return PhysicalKey::Z;
            case 0x2D: return PhysicalKey::X;
            case 0x2E: return PhysicalKey::C;
            case 0x2F: return PhysicalKey::V;
            case 0x30: return PhysicalKey::B;
            case 0x31: return PhysicalKey::N;
            case 0x32: return PhysicalKey::M;
            case 0x33: return PhysicalKey::Comma;
            case 0x34: return PhysicalKey::Period;
            case 0x35: return PhysicalKey::Slash;
            case 0x36: return PhysicalKey::RightShift;
            case 0x38: return PhysicalKey::LeftOption;   // Left Alt
            case 0x39: return PhysicalKey::Space;
            case 0x3A: return PhysicalKey::CapsLock;
            case 0x3B: return PhysicalKey::F1;
            case 0x3C: return PhysicalKey::F2;
            case 0x3D: return PhysicalKey::F3;
            case 0x3E: return PhysicalKey::F4;
            case 0x3F: return PhysicalKey::F5;
            case 0x40: return PhysicalKey::F6;
            case 0x41: return PhysicalKey::F7;
            case 0x42: return PhysicalKey::F8;
            case 0x43: return PhysicalKey::F9;
            case 0x44: return PhysicalKey::F10;
            case 0x57: return PhysicalKey::F11;
            case 0x58: return PhysicalKey::F12;
            // Numpad digits
            case 0x47: return PhysicalKey::K7;
            case 0x48: return PhysicalKey::K8;
            case 0x49: return PhysicalKey::K9;
            case 0x4B: return PhysicalKey::K4;
            case 0x4C: return PhysicalKey::K5;
            case 0x4D: return PhysicalKey::K6;
            case 0x4F: return PhysicalKey::K1;
            case 0x50: return PhysicalKey::K2;
            case 0x51: return PhysicalKey::K3;
            case 0x52: return PhysicalKey::K0;
            case 0x53: return PhysicalKey::Period;
            default: break;
        }
    }

    // Virtual key fallback
    if (vkey >= 'A' && vkey <= 'Z') {
        static const PhysicalKey letters[26] = {
            PhysicalKey::A, PhysicalKey::B, PhysicalKey::C, PhysicalKey::D, PhysicalKey::E,
            PhysicalKey::F, PhysicalKey::G, PhysicalKey::H, PhysicalKey::I, PhysicalKey::J,
            PhysicalKey::K, PhysicalKey::L, PhysicalKey::M, PhysicalKey::N, PhysicalKey::O,
            PhysicalKey::P, PhysicalKey::Q, PhysicalKey::R, PhysicalKey::S, PhysicalKey::T,
            PhysicalKey::U, PhysicalKey::V, PhysicalKey::W, PhysicalKey::X, PhysicalKey::Y, PhysicalKey::Z
        };
        return letters[vkey - 'A'];
    }
    if (vkey == VK_SPACE) return PhysicalKey::Space;
    if (vkey == VK_RETURN) return PhysicalKey::Enter;
    if (vkey == VK_BACK) return PhysicalKey::Backspace;
    if (vkey == VK_ESCAPE) return PhysicalKey::Escape;
    if (vkey == VK_UP) return PhysicalKey::ArrowUp;
    if (vkey == VK_DOWN) return PhysicalKey::ArrowDown;
    if (vkey == VK_LEFT) return PhysicalKey::ArrowLeft;
    if (vkey == VK_RIGHT) return PhysicalKey::ArrowRight;
    return PhysicalKey::None;
}

struct VisualKeycap {
    PhysicalKey key;
    int row;
    float xUnits;
    float widthUnits;
    bool isAmberAccent;

    Pt normalizedCenter() const {
        return { xUnits + widthUnits * 0.5f, (row + 0.5f) / 5.0f };
    }
};

class KeyboardLayout {
public:
    static const std::vector<VisualKeycap>& keycaps() {
        static const std::vector<VisualKeycap> caps = build();
        return caps;
    }

    static Pt screenQuadPoint(float su, float sv) {
        const Pt topLeft     = { 109.0f, 238.0f };
        const Pt topRight    = { 281.0f, 247.0f };
        const Pt bottomLeft  = { 103.0f, 282.0f };
        const Pt bottomRight = { 286.0f, 292.0f };

        float topX = topLeft.x + (topRight.x - topLeft.x) * su;
        float topY = topLeft.y + (topRight.y - topLeft.y) * su;
        float botX = bottomLeft.x + (bottomRight.x - bottomLeft.x) * su;
        float botY = bottomLeft.y + (bottomRight.y - bottomLeft.y) * su;
        return { topX + (botX - topX) * sv, topY + (botY - topY) * sv };
    }

    /// 180° rotated to face the cat: Spacebar closest to cat (top), amber Enter left, amber Esc bottom-right!
    static Pt canvasPoint(float u, float v) {
        return screenQuadPoint(1.0f - u, 1.0f - v);
    }

    static Pt canvasPointForKey(PhysicalKey key) {
        PhysicalKey vk = visualKeyOf(key);
        const auto& map = lookup();
        auto it = map.find(vk);
        if (it != map.end()) {
            Pt c = it->second.normalizedCenter();
            return canvasPoint(c.x, c.y);
        }
        return canvasPoint(0.5f, 0.5f);
    }

    struct V2KeyCellInfo {
        int row = 1;
        int col = 3;
        Pt center = { 0.0f, 0.0f };
    };

    /// Bilinear interpolation on Xiao Douni Video 2's angled hand-drawn keyboard surface (`u` left->right, `v` top->bottom in 832x720 V2Space).
    static Pt v2KbPoint(float u, float v) {
        const Pt tl = { 242.0f, 336.0f };
        const Pt tr = { 782.0f, 446.0f };
        const Pt br = { 584.0f, 586.0f };
        const Pt bl = {  28.0f, 440.0f };
        float topX = tl.x + (tr.x - tl.x) * u;
        float topY = tl.y + (tr.y - tl.y) * u;
        float botX = bl.x + (br.x - bl.x) * u;
        float botY = bl.y + (br.y - bl.y) * u;
        return { topX + (botX - topX) * v, topY + (botY - topY) * v };
    }

    /// Single source of truth mapping any PhysicalKey -> exact Video 2 keyboard cell `(row, col)` and V2Space center point.
    static V2KeyCellInfo v2KeyCellInfo(PhysicalKey key) {
        constexpr float wellU0 = 0.31f, wellU1 = 0.95f;
        constexpr float wellV0 = 0.11f, wellV1 = 0.87f;
        PhysicalKey vk = visualKeyOf(key);
        if (vk == PhysicalKey::Space) {
            float su = wellU0 + (wellU1 - wellU0) * (4.0f / 8.0f);
            float sv = wellV0 + (wellV1 - wellV0) * (3.5f / 4.0f);
            return { 3, 2, v2KbPoint(su, sv) };
        }
        const auto& map = lookup();
        auto it = map.find(vk);
        if (it == map.end()) {
            float su = wellU0 + (wellU1 - wellU0) * (3.5f / 8.0f);
            float sv = wellV0 + (wellV1 - wellV0) * (1.5f / 4.0f);
            return { 1, 3, v2KbPoint(su, sv) };
        }
        const VisualKeycap& cap = it->second;
        float normU = std::clamp(1.0f - (cap.xUnits + cap.widthUnits * 0.5f), 0.0f, 1.0f);
        int col = std::clamp((int)(normU * 7.99f), 0, 7);
        int row = std::clamp(cap.row >= 3 ? 3 : cap.row, 0, 3);
        if (row == 3 && col >= 2 && col <= 5) {
            row = 2;
        }
        float su = wellU0 + (wellU1 - wellU0) * (((float)col + 0.5f) / 8.0f);
        float sv = wellV0 + (wellV1 - wellV0) * (((float)row + 0.5f) / 4.0f);
        return { row, col, v2KbPoint(su, sv) };
    }

    static Pt v2KeyCellCenter(PhysicalKey key) {
        return v2KeyCellInfo(key).center;
    }

private:
    static std::vector<VisualKeycap> build() {
        struct Entry { PhysicalKey k; float w; bool amber; };
        const std::vector<std::vector<Entry>> rows = {
            // Row 0 (Esc amber -> bottom-right when facing cat)
            {
                {PhysicalKey::Escape, 1.0f, true}, {PhysicalKey::K1, 1.0f, false}, {PhysicalKey::K2, 1.0f, false},
                {PhysicalKey::K3, 1.0f, false}, {PhysicalKey::K4, 1.0f, false}, {PhysicalKey::K5, 1.0f, false},
                {PhysicalKey::K6, 1.0f, false}, {PhysicalKey::K7, 1.0f, false}, {PhysicalKey::K8, 1.0f, false},
                {PhysicalKey::K9, 1.0f, false}, {PhysicalKey::K0, 1.0f, false}, {PhysicalKey::Minus, 1.0f, false},
                {PhysicalKey::Equal, 1.0f, false}, {PhysicalKey::Backspace, 2.0f, false}
            },
            // Row 1
            {
                {PhysicalKey::Tab, 1.5f, false}, {PhysicalKey::Q, 1.0f, false}, {PhysicalKey::W, 1.0f, false},
                {PhysicalKey::E, 1.0f, false}, {PhysicalKey::R, 1.0f, false}, {PhysicalKey::T, 1.0f, false},
                {PhysicalKey::Y, 1.0f, false}, {PhysicalKey::U, 1.0f, false}, {PhysicalKey::I, 1.0f, false},
                {PhysicalKey::O, 1.0f, false}, {PhysicalKey::P, 1.0f, false}, {PhysicalKey::LeftBracket, 1.0f, false},
                {PhysicalKey::RightBracket, 1.0f, false}, {PhysicalKey::Backslash, 1.5f, false}
            },
            // Row 2 (Enter amber -> middle-left when facing cat)
            {
                {PhysicalKey::CapsLock, 1.75f, false}, {PhysicalKey::A, 1.0f, false}, {PhysicalKey::S, 1.0f, false},
                {PhysicalKey::D, 1.0f, false}, {PhysicalKey::F, 1.0f, false}, {PhysicalKey::G, 1.0f, false},
                {PhysicalKey::H, 1.0f, false}, {PhysicalKey::J, 1.0f, false}, {PhysicalKey::K, 1.0f, false},
                {PhysicalKey::L, 1.0f, false}, {PhysicalKey::Semicolon, 1.0f, false}, {PhysicalKey::Quote, 1.0f, false},
                {PhysicalKey::Enter, 2.25f, true}
            },
            // Row 3
            {
                {PhysicalKey::LeftShift, 2.25f, false}, {PhysicalKey::Z, 1.0f, false}, {PhysicalKey::X, 1.0f, false},
                {PhysicalKey::C, 1.0f, false}, {PhysicalKey::V, 1.0f, false}, {PhysicalKey::B, 1.0f, false},
                {PhysicalKey::N, 1.0f, false}, {PhysicalKey::M, 1.0f, false}, {PhysicalKey::Comma, 1.0f, false},
                {PhysicalKey::Period, 1.0f, false}, {PhysicalKey::Slash, 1.0f, false},
                {PhysicalKey::RightShift, 1.75f, false}, {PhysicalKey::ArrowUp, 1.0f, false}
            },
            // Row 4 (Spacebar -> top row closest to cat)
            {
                {PhysicalKey::LeftControl, 1.25f, false}, {PhysicalKey::LeftOption, 1.25f, false},
                {PhysicalKey::LeftCommand, 1.25f, false}, {PhysicalKey::Space, 6.25f, false},
                {PhysicalKey::RightCommand, 1.0f, false}, {PhysicalKey::RightOption, 1.0f, false},
                {PhysicalKey::ArrowLeft, 1.0f, false}, {PhysicalKey::ArrowDown, 1.0f, false},
                {PhysicalKey::ArrowRight, 1.0f, false}
            }
        };

        std::vector<VisualKeycap> out;
        constexpr float totalUnits = 15.0f;
        for (int r = 0; r < (int)rows.size(); ++r) {
            float cursor = 0.0f;
            for (const auto& e : rows[r]) {
                out.push_back({ e.k, r, cursor / totalUnits, e.w / totalUnits, e.amber });
                cursor += e.w;
            }
        }
        return out;
    }

    static const std::unordered_map<PhysicalKey, VisualKeycap>& lookup() {
        static const auto map = [] {
            std::unordered_map<PhysicalKey, VisualKeycap> m;
            for (const auto& c : keycaps()) m[c.key] = c;
            return m;
        }();
        return map;
    }
};
