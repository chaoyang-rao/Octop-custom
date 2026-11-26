// Shared custom keyboard/mouse skin format (.kurokb / keyboard.json, v1) for Windows and Linux.
// Reuses skinjson::Parser and SkinColor from SkinSpec.hpp.
#pragma once
#include "SkinSpec.hpp"
#include <cstdio>
#include <string>

struct KeyboardSkinSpec {
    std::string id;        // "builtin:0..2" or 16-hex FNV-1a content hash
    std::string name;
    std::string author;
    bool builtIn = false;

    SkinColor mouseBody;
    SkinColor mouseBorder;
    SkinColor wheel;
    SkinColor base;
    SkinColor deck;
    SkinColor key;
    SkinColor keyBorder;
    SkinColor accent;
    bool darkText = true;

    static constexpr size_t MaxFileBytes = 256 * 1024;
    static constexpr int FormatVersion = 1;

    static KeyboardSkinSpec builtInTheme(int themeIdx) {
        KeyboardSkinSpec s;
        s.builtIn = true;
        if (themeIdx == 1) {
            s.id = "builtin:1";
            s.name = "暗夜极客黑";
            s.mouseBody   = SkinColor::rgba(0.20f, 0.21f, 0.24f);
            s.mouseBorder = SkinColor::rgba(0.08f, 0.08f, 0.10f);
            s.wheel       = SkinColor::rgba(0.77f, 0.94f, 0.25f);
            s.base        = SkinColor::rgba(0.06f, 0.06f, 0.08f);
            s.deck        = SkinColor::rgba(0.10f, 0.11f, 0.13f);
            s.key         = SkinColor::rgba(0.21f, 0.22f, 0.25f);
            s.keyBorder   = SkinColor::rgba(0.11f, 0.11f, 0.13f, 0.95f);
            s.accent      = SkinColor::rgba(0.77f, 0.94f, 0.25f);
            s.darkText    = false;
        } else if (themeIdx == 2) {
            s.id = "builtin:2";
            s.name = "复古奶油灰";
            s.mouseBody   = SkinColor::rgba(0.90f, 0.88f, 0.82f);
            s.mouseBorder = SkinColor::rgba(0.28f, 0.26f, 0.24f);
            s.wheel       = SkinColor::rgba(0.88f, 0.42f, 0.24f);
            s.base        = SkinColor::rgba(0.25f, 0.24f, 0.22f);
            s.deck        = SkinColor::rgba(0.38f, 0.36f, 0.33f);
            s.key         = SkinColor::rgba(0.90f, 0.88f, 0.82f);
            s.keyBorder   = SkinColor::rgba(0.68f, 0.65f, 0.60f, 0.85f);
            s.accent      = SkinColor::rgba(0.88f, 0.42f, 0.24f);
            s.darkText    = true;
        } else {
            s.id = "builtin:0";
            s.name = "经典奶白暖黄 (原版)";
            s.mouseBody   = SkinColor::rgba(0.955f, 0.950f, 0.925f);
            s.mouseBorder = SkinColor::rgba(0.14f, 0.14f, 0.16f);
            s.wheel       = SkinColor::rgba(0.96f, 0.69f, 0.16f);
            s.base        = SkinColor::rgba(0.10f, 0.10f, 0.12f);
            s.deck        = SkinColor::rgba(0.14f, 0.14f, 0.16f);
            s.key         = SkinColor::rgba(0.968f, 0.964f, 0.942f);
            s.keyBorder   = SkinColor::rgba(0.78f, 0.77f, 0.74f, 0.75f);
            s.accent      = SkinColor::rgba(0.97f, 0.70f, 0.16f);
            s.darkText    = true;
        }
        return s;
    }

    static bool parse(const std::string& bytes, KeyboardSkinSpec& out, std::string& error) {
        using namespace skinjson;
        if (bytes.size() > MaxFileBytes) { error = "键盘皮肤文件超过 256 KB 上限"; return false; }
        if (bytes.empty()) { error = "键盘皮肤文件是空的"; return false; }
        Value root;
        Parser parser(bytes);
        if (!parser.parseDocument(root, error)) return false;
        if (root.type != Value::JObject) { error = "键盘皮肤文件最外层必须是 JSON 对象 { … }"; return false; }

        if (const Value* ver = root.get("formatVersion")) {
            if (ver->type != Value::JNumber || ver->n != std::floor(ver->n)) { error = "formatVersion 必须是整数"; return false; }
            if (ver->n > FormatVersion) { error = "这个键盘皮肤使用了更新的格式，请先升级 KuroCat"; return false; }
            if (ver->n < 1) { error = "formatVersion 无效"; return false; }
        }

        const Value* cols = root.get("colors");
        if (!cols || cols->type != Value::JObject) { error = "缺少键盘配色对象 colors"; return false; }

        auto trim = [](const std::string& s, size_t maxBytes) {
            size_t a = 0, b = s.size();
            while (a < b && (unsigned char)s[a] <= ' ') ++a;
            while (b > a && (unsigned char)s[b - 1] <= ' ') --b;
            std::string r;
            for (size_t i = a; i < b && r.size() < maxBytes; ++i)
                if ((unsigned char)s[i] >= 0x20) r.push_back(s[i]);
            return r;
        };

        KeyboardSkinSpec s;
        if (const Value* name = root.get("name"); name && name->type == Value::JString) {
            s.name = trim(name->s, 96);
        }
        if (s.name.empty()) { error = "缺少键盘皮肤名称 name"; return false; }
        if (const Value* author = root.get("author"); author && author->type == Value::JString) {
            s.author = trim(author->s, 96);
        }

        auto parseHex = [&](const Value* v, const std::string& field, SkinColor& dst) -> bool {
            if (!v || v->type == Value::JNull) return true;
            if (v->type != Value::JString) { error = field + " 必须是 \"#RRGGBB\" 或 \"#RRGGBBAA\" 颜色字符串"; return false; }
            const std::string& h = v->s;
            if ((h.size() != 7 && h.size() != 9) || h[0] != '#') {
                error = field + " 颜色格式应为 #RRGGBB 或 #RRGGBBAA";
                return false;
            }
            auto hex = [](char ch) -> int {
                if (ch >= '0' && ch <= '9') return ch - '0';
                if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
                if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
                return -1;
            };
            int c[4] = {0, 0, 0, 255};
            for (size_t i = 0; i < (h.size() - 1) / 2; ++i) {
                int hi = hex(h[1 + i * 2]), lo = hex(h[2 + i * 2]);
                if (hi < 0 || lo < 0) { error = field + " 颜色里有非十六进制字符"; return false; }
                c[i] = hi * 16 + lo;
            }
            dst = SkinColor::rgba(c[0] / 255.0f, c[1] / 255.0f, c[2] / 255.0f, c[3] / 255.0f);
            return true;
        };

        SkinColor base, deck, key, keyBorder, accent, mouseBody, mouseBorder, wheel;
        if (!parseHex(cols->get("base"), "colors.base", base) ||
            !parseHex(cols->get("deck"), "colors.deck", deck) ||
            !parseHex(cols->get("key"), "colors.key", key) ||
            !parseHex(cols->get("keyBorder"), "colors.keyBorder", keyBorder) ||
            !parseHex(cols->get("accent"), "colors.accent", accent) ||
            !parseHex(cols->get("mouseBody"), "colors.mouseBody", mouseBody) ||
            !parseHex(cols->get("mouseBorder"), "colors.mouseBorder", mouseBorder) ||
            !parseHex(cols->get("wheel"), "colors.wheel", wheel)) {
            return false;
        }
        if (!key.set) { error = "缺少键帽颜色 colors.key"; return false; }

        s.key         = key;
        s.deck        = deck.set ? deck : SkinColor::rgba(0.14f, 0.14f, 0.16f);
        s.base        = base.set ? base : SkinColor::rgba(s.deck.r * 0.72f, s.deck.g * 0.72f, s.deck.b * 0.72f);
        s.keyBorder   = keyBorder.set ? keyBorder : SkinColor::rgba(s.deck.r, s.deck.g, s.deck.b, 0.78f);
        s.accent      = accent.set ? accent : SkinColor::rgba(0.97f, 0.70f, 0.16f);
        s.mouseBody   = mouseBody.set ? mouseBody : s.key;
        s.mouseBorder = mouseBorder.set ? mouseBorder : s.base;
        s.wheel       = wheel.set ? wheel : s.accent;
        if (const Value* dt = cols->get("darkText"); dt && dt->type == Value::JBool) {
            s.darkText = dt->b;
        } else {
            s.darkText = s.key.luminance() >= 0.45f;
        }

        s.id = SkinSpec::contentId(bytes);
        out = std::move(s);
        return true;
    }

    static bool loadFile(const std::string& path, KeyboardSkinSpec& out, std::string& error) {
        FILE* f = std::fopen(path.c_str(), "rb");
        if (!f) { error = "无法打开文件"; return false; }
        std::string bytes;
        char buf[32768];
        size_t n;
        while ((n = std::fread(buf, 1, sizeof buf, f)) > 0) {
            bytes.append(buf, n);
            if (bytes.size() > MaxFileBytes) { std::fclose(f); error = "键盘皮肤文件超过 256 KB 上限"; return false; }
        }
        std::fclose(f);
        return parse(bytes, out, error);
    }
};
