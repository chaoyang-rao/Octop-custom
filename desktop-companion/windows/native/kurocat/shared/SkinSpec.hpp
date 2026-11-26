// KuroCat skin model + strict `.kurocat` (formatVersion 1) parser, shared by Windows and Linux.
// The format is documented in docs/skin-format.md; Sources/SkinSpec.swift mirrors this file for macOS.
// Header-only, C++17, no third-party dependencies, locale-independent number parsing.
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <memory>
#include <string>
#include <vector>
#include "CoatPatterns.hpp"

struct SkinColor {
    double r = 0, g = 0, b = 0, a = 1;
    bool set = false;
    static SkinColor rgba(double r, double g, double b, double a = 1.0) { return {r, g, b, a, true}; }
    static SkinColor hex(unsigned int rgb, double a = 1.0) {
        return {((rgb >> 16) & 255) / 255.0, ((rgb >> 8) & 255) / 255.0, (rgb & 255) / 255.0, a, true};
    }
    bool sameAs(const SkinColor& o) const { return set == o.set && r == o.r && g == o.g && b == o.b && a == o.a; }
    double luminance() const { return 0.2126 * r + 0.7152 * g + 0.0722 * b; }
};

// Part coordinate spaces (see docs/skin-format.md for the diagram).
enum class SkinSpace : int { Head = 0, Skull, Body, Tail, LeftEar, RightEar, LeftArm, RightArm, HindLeg };
enum class SkinBuild : int { Standard = 0, Sleek };
enum class SkinHeadSurface : int { Dome = 0, Plane };
enum class SkinAnchorPoint : int { HeadTop = 0, Face, Neck, TailTip };
enum class SkinRenderStyle : int { Standard = 0, Douni, Dazed };
enum class SkinTypingStyle : int { Standard = 0, Douni };

struct SkinPoint { float x = 0, y = 0; };
// One pen-tool anchor; in/out are absolute handle positions in the same part space.
struct SkinBezierAnchor { float x = 0, y = 0, inX = 0, inY = 0, outX = 0, outY = 0; };

struct SkinRegion {
    SkinSpace space = SkinSpace::Body;
    SkinColor fill;                       // alpha already multiplied in
    std::vector<SkinBezierAnchor> anchors; // closed path, >= 2 anchors
    // Flattened closed polyline in part space (16 segments per cubic), filled in by the parser.
    std::vector<SkinPoint> flat;
};

struct SkinMark {
    SkinSpace space = SkinSpace::Body;
    bool stroke = false;
    float width = 0;
    SkinColor color;
    std::vector<SkinPoint> points;
    bool clipToBib = false;
};

struct SkinShape {
    SkinBuild build = SkinBuild::Standard;
    float bodyWidth = 1, headScale = 1, earSize = 1, earBaseWidth = 1, earPointiness = 1;
    float tailLength = 1, tailThickness = 1, cheekFullness = 1, neckWidth = 1, pawStagger = 1;
};

struct SkinDecoration {
    std::vector<uint8_t> png;
    int pixelWidth = 0, pixelHeight = 0;
    SkinAnchorPoint anchor = SkinAnchorPoint::HeadTop;
    float offsetX = 0, offsetY = 0, scale = 1, rotation = 0; // rotation in degrees
    mutable std::shared_ptr<void> nativeImage; // decoded platform image cache (cairo surface / GDI+ bitmap)
};

struct SkinPalette {
    SkinColor body, bodyShade, belly, legs, paws, hindLeg, hindPaw, pawPads, earOuter, earInner, nose, mouth, iris,
              tail, tailTip, stripes, whiskers, crease, outline, points, pointsMid;
};

struct SkinSpec {
    std::string id;     // "builtin:<n>" or the content hash of an imported file
    std::string name, author;
    bool builtIn = false;
    SkinPalette palette;
    std::vector<SkinRegion> regions;
    std::vector<SkinMark> marks;
    SkinShape shape;
    SkinHeadSurface headSurface = SkinHeadSurface::Dome;
    SkinRenderStyle renderStyle = SkinRenderStyle::Standard;
    SkinTypingStyle typingStyle = SkinTypingStyle::Standard;
    // "idleLegs": "legs" (default) tints the sitting front legs with palette.legs, fading in from the
    // shoulder; "chest" leaves them chest-coloured (only paws + creases), as the built-in coats are drawn.
    bool idleLegsTinted = true;
    std::vector<SkinDecoration> decorations;
    std::vector<uint8_t> preview;

    bool colorpoint() const { return palette.points.set; }
    bool hasPartArt(SkinSpace s) const {
        for (const auto& r : regions) if (r.space == s) return true;
        for (const auto& m : marks) if (m.space == s) return true;
        return false;
    }

    // Static limits of formatVersion 1.
    static constexpr size_t MaxFileBytes = 2 * 1024 * 1024;
    static constexpr int FormatVersion = 1;

    static bool parse(const std::string& bytes, SkinSpec& out, std::string& error);
    static bool loadFile(const std::string& path, SkinSpec& out, std::string& error);
    static std::string contentId(const std::string& bytes);
};

// ---------------------------------------------------------------------------------------------
namespace skinjson {

struct Value {
    enum Type { JNull, JBool, JNumber, JString, JArray, JObject } type = JNull;
    bool b = false;
    double n = 0;
    std::string s;
    std::vector<Value> items;       // Array items or Object values
    std::vector<std::string> keys;  // Object keys (same order as items)
    const Value* get(const char* key) const {
        if (type != JObject) return nullptr;
        for (size_t i = keys.size(); i-- > 0;) if (keys[i] == key) return &items[i]; // duplicate keys: last wins
        return nullptr;
    }
};

class Parser {
public:
    Parser(const std::string& text) : begin_(text.data()), p_(text.data()), end_(text.data() + text.size()) {}
    bool parseDocument(Value& out, std::string& error) {
        if (end_ - p_ >= 3 && (uint8_t)p_[0] == 0xEF && (uint8_t)p_[1] == 0xBB && (uint8_t)p_[2] == 0xBF) p_ += 3; // UTF-8 BOM
        skipWs();
        if (!parseValue(out, 0)) { error = error_; return false; }
        skipWs();
        if (p_ != end_) { fail("JSON 结尾有多余内容"); error = error_; return false; }
        return true;
    }

private:
    const char* begin_;
    const char* p_;
    const char* end_;
    std::string error_;

    bool fail(const char* what) {
        if (error_.empty()) error_ = std::string("不是有效的 JSON：") + what + "（第 " + std::to_string(p_ - begin_ + 1) + " 字节附近）";
        return false;
    }
    void skipWs() { while (p_ < end_ && (*p_ == ' ' || *p_ == '\t' || *p_ == '\n' || *p_ == '\r')) ++p_; }
    bool literal(const char* word) {
        size_t n = std::strlen(word);
        if ((size_t)(end_ - p_) < n || std::memcmp(p_, word, n) != 0) return fail("无法识别的值");
        p_ += n;
        return true;
    }
    bool parseValue(Value& v, int depth) {
        if (depth > 24) return fail("嵌套层级过深");
        if (p_ >= end_) return fail("内容意外结束");
        char c = *p_;
        if (c == '{') return parseObject(v, depth);
        if (c == '[') return parseArray(v, depth);
        if (c == '"') { v.type = Value::JString; return parseString(v.s); }
        if (c == 't') { v.type = Value::JBool; v.b = true; return literal("true"); }
        if (c == 'f') { v.type = Value::JBool; v.b = false; return literal("false"); }
        if (c == 'n') { v.type = Value::JNull; return literal("null"); }
        if (c == '-' || (c >= '0' && c <= '9')) { v.type = Value::JNumber; return parseNumber(v.n); }
        return fail("无法识别的值");
    }
    bool parseObject(Value& v, int depth) {
        v.type = Value::JObject;
        ++p_; skipWs();
        if (p_ < end_ && *p_ == '}') { ++p_; return true; }
        while (true) {
            skipWs();
            if (p_ >= end_ || *p_ != '"') return fail("对象的键必须是字符串");
            std::string key;
            if (!parseString(key)) return false;
            skipWs();
            if (p_ >= end_ || *p_ != ':') return fail("缺少冒号");
            ++p_; skipWs();
            v.keys.push_back(std::move(key));
            v.items.emplace_back();
            if (!parseValue(v.items.back(), depth + 1)) return false;
            skipWs();
            if (p_ < end_ && *p_ == ',') { ++p_; continue; }
            if (p_ < end_ && *p_ == '}') { ++p_; return true; }
            return fail("对象缺少逗号或右花括号");
        }
    }
    bool parseArray(Value& v, int depth) {
        v.type = Value::JArray;
        ++p_; skipWs();
        if (p_ < end_ && *p_ == ']') { ++p_; return true; }
        while (true) {
            skipWs();
            v.items.emplace_back();
            if (!parseValue(v.items.back(), depth + 1)) return false;
            skipWs();
            if (p_ < end_ && *p_ == ',') { ++p_; continue; }
            if (p_ < end_ && *p_ == ']') { ++p_; return true; }
            return fail("数组缺少逗号或右方括号");
        }
    }
    static void putUtf8(std::string& s, uint32_t cp) {
        if (cp < 0x80) s += (char)cp;
        else if (cp < 0x800) { s += (char)(0xC0 | (cp >> 6)); s += (char)(0x80 | (cp & 63)); }
        else if (cp < 0x10000) { s += (char)(0xE0 | (cp >> 12)); s += (char)(0x80 | ((cp >> 6) & 63)); s += (char)(0x80 | (cp & 63)); }
        else { s += (char)(0xF0 | (cp >> 18)); s += (char)(0x80 | ((cp >> 12) & 63)); s += (char)(0x80 | ((cp >> 6) & 63)); s += (char)(0x80 | (cp & 63)); }
    }
    bool hex4(uint32_t& out) {
        if (end_ - p_ < 4) return fail("\\u 转义不完整");
        out = 0;
        for (int i = 0; i < 4; ++i) {
            char c = *p_++;
            out <<= 4;
            if (c >= '0' && c <= '9') out |= (uint32_t)(c - '0');
            else if (c >= 'a' && c <= 'f') out |= (uint32_t)(c - 'a' + 10);
            else if (c >= 'A' && c <= 'F') out |= (uint32_t)(c - 'A' + 10);
            else return fail("\\u 转义含非十六进制字符");
        }
        return true;
    }
    bool parseString(std::string& s) {
        ++p_; // opening quote
        while (true) {
            if (p_ >= end_) return fail("字符串没有结束引号");
            unsigned char c = (unsigned char)*p_++;
            if (c == '"') break;
            if (c < 0x20) return fail("字符串里有未转义的控制字符");
            if (c != '\\') {
                if (c < 0x80) { s += (char)c; continue; }
                // Validate one UTF-8 sequence.
                int extra = (c >= 0xF0 && c <= 0xF4) ? 3 : (c >= 0xE0) ? 2 : (c >= 0xC2 && c <= 0xDF) ? 1 : -1;
                if (extra < 0 || end_ - p_ < extra) return fail("字符串不是有效的 UTF-8");
                s += (char)c;
                for (int i = 0; i < extra; ++i) {
                    unsigned char d = (unsigned char)*p_++;
                    if ((d & 0xC0) != 0x80) return fail("字符串不是有效的 UTF-8");
                    s += (char)d;
                }
                continue;
            }
            if (p_ >= end_) return fail("转义不完整");
            char e = *p_++;
            switch (e) {
                case '"': s += '"'; break;
                case '\\': s += '\\'; break;
                case '/': s += '/'; break;
                case 'b': s += '\b'; break;
                case 'f': s += '\f'; break;
                case 'n': s += '\n'; break;
                case 'r': s += '\r'; break;
                case 't': s += '\t'; break;
                case 'u': {
                    uint32_t cp;
                    if (!hex4(cp)) return false;
                    if (cp >= 0xD800 && cp <= 0xDBFF) {
                        uint32_t lo;
                        if (end_ - p_ < 2 || p_[0] != '\\' || p_[1] != 'u') return fail("UTF-16 代理对不完整");
                        p_ += 2;
                        if (!hex4(lo) || lo < 0xDC00 || lo > 0xDFFF) return fail("UTF-16 代理对无效");
                        cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                    } else if (cp >= 0xDC00 && cp <= 0xDFFF) return fail("UTF-16 代理对无效");
                    putUtf8(s, cp);
                    break;
                }
                default: return fail("未知的转义字符");
            }
        }
        return true;
    }
    bool parseNumber(double& out) {
        const char* start = p_;
        bool neg = false;
        if (*p_ == '-') { neg = true; ++p_; }
        if (p_ >= end_ || !(*p_ >= '0' && *p_ <= '9')) return fail("数字格式错误");
        long double mant = 0;
        int digits = 0, exp10 = 0;
        if (*p_ == '0') { ++p_; }
        else while (p_ < end_ && *p_ >= '0' && *p_ <= '9') {
            if (digits < 19) { mant = mant * 10 + (*p_ - '0'); ++digits; } else ++exp10;
            ++p_;
        }
        if (p_ < end_ && *p_ == '.') {
            ++p_;
            if (p_ >= end_ || !(*p_ >= '0' && *p_ <= '9')) return fail("数字格式错误");
            while (p_ < end_ && *p_ >= '0' && *p_ <= '9') {
                if (digits < 19) { mant = mant * 10 + (*p_ - '0'); ++digits; --exp10; }
                ++p_;
            }
        }
        if (p_ < end_ && (*p_ == 'e' || *p_ == 'E')) {
            ++p_;
            bool eneg = false;
            if (p_ < end_ && (*p_ == '+' || *p_ == '-')) { eneg = (*p_ == '-'); ++p_; }
            if (p_ >= end_ || !(*p_ >= '0' && *p_ <= '9')) return fail("数字格式错误");
            int e = 0;
            while (p_ < end_ && *p_ >= '0' && *p_ <= '9') { if (e < 10000) e = e * 10 + (*p_ - '0'); ++p_; }
            exp10 += eneg ? -e : e;
        }
        if (p_ - start > 64) return fail("数字过长");
        long double v = mant;
        if (mant != 0) v = (exp10 > 400) ? HUGE_VALL : (exp10 < -400 ? 0.0L : mant * std::pow(10.0L, (long double)exp10));
        out = (double)(neg ? -v : v);
        if (!std::isfinite(out)) return fail("数字超出范围");
        return true;
    }
};

inline bool base64Decode(const std::string& in, std::vector<uint8_t>& out) {
    size_t start = 0;
    const char* prefix = "data:image/png;base64,";
    if (in.compare(0, std::strlen(prefix), prefix) == 0) start = std::strlen(prefix);
    uint32_t acc = 0;
    int bits = 0, pad = 0;
    out.clear();
    out.reserve(in.size() * 3 / 4);
    for (size_t i = start; i < in.size(); ++i) {
        char c = in[i];
        int v;
        if (c >= 'A' && c <= 'Z') v = c - 'A';
        else if (c >= 'a' && c <= 'z') v = c - 'a' + 26;
        else if (c >= '0' && c <= '9') v = c - '0' + 52;
        else if (c == '+') v = 62;
        else if (c == '/') v = 63;
        else if (c == '=') { ++pad; continue; }
        else if (c == ' ' || c == '\n' || c == '\r' || c == '\t') continue;
        else return false;
        if (pad) return false; // data after padding
        acc = (acc << 6) | (uint32_t)v;
        bits += 6;
        if (bits >= 8) { bits -= 8; out.push_back((uint8_t)((acc >> bits) & 0xFF)); }
    }
    return pad <= 2;
}

// Checks the PNG signature + IHDR and returns its pixel size.
inline bool pngSize(const std::vector<uint8_t>& png, int& w, int& h) {
    static const uint8_t sig[8] = {0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A};
    if (png.size() < 33 || std::memcmp(png.data(), sig, 8) != 0 || std::memcmp(png.data() + 12, "IHDR", 4) != 0) return false;
    auto be32 = [&](size_t o) { return (uint32_t)png[o] << 24 | (uint32_t)png[o + 1] << 16 | (uint32_t)png[o + 2] << 8 | (uint32_t)png[o + 3]; };
    uint32_t pw = be32(16), ph = be32(20);
    if (pw == 0 || ph == 0 || pw > 4096 || ph > 4096) return false;
    w = (int)pw; h = (int)ph;
    return true;
}

} // namespace skinjson

// ---------------------------------------------------------------------------------------------
namespace skinparse {
using skinjson::Value;

struct Ctx {
    std::string error;
    bool fail(const std::string& msg) { if (error.empty()) error = msg; return false; }
};

inline float clampf(double v, double lo, double hi) { return (float)std::min(hi, std::max(lo, v)); }

inline bool number(Ctx& c, const Value* v, const std::string& field, double lo, double hi, float& out) {
    if (!v || v->type == Value::JNull) return true; // keep default
    if (v->type != Value::JNumber) return c.fail(field + " 必须是数字");
    out = clampf(v->n, lo, hi);
    return true;
}

inline bool color(Ctx& c, const Value* v, const std::string& field, SkinColor& out) {
    if (!v || v->type == Value::JNull) return true;
    if (v->type != Value::JString) return c.fail(field + " 必须是 \"#RRGGBB\" 或 \"#RRGGBBAA\" 颜色字符串");
    const std::string& s = v->s;
    if ((s.size() != 7 && s.size() != 9) || s[0] != '#') return c.fail(field + " 颜色格式应为 #RRGGBB 或 #RRGGBBAA，现在是 \"" + s.substr(0, 16) + "\"");
    unsigned int vals[4] = {0, 0, 0, 255};
    for (size_t i = 1; i < s.size(); ++i) {
        char ch = s[i];
        int d = (ch >= '0' && ch <= '9') ? ch - '0' : (ch >= 'a' && ch <= 'f') ? ch - 'a' + 10 : (ch >= 'A' && ch <= 'F') ? ch - 'A' + 10 : -1;
        if (d < 0) return c.fail(field + " 颜色里有非十六进制字符：\"" + s + "\"");
        size_t k = (i - 1) / 2;
        if ((i - 1) % 2 == 0) vals[k] = 0;
        vals[k] = vals[k] * 16 + (unsigned)d;
    }
    out = SkinColor::rgba(vals[0] / 255.0, vals[1] / 255.0, vals[2] / 255.0, vals[3] / 255.0);
    return true;
}

// Returns false only when the field is missing/not a string; sets recognized=false for unknown future spaces
// so newer Workshop skins remain forward-compatible instead of failing import.
inline bool space(Ctx& c, const Value* v, const std::string& field, SkinSpace& out, bool& recognized) {
    static const char* names[] = {"head", "skull", "body", "tail", "leftEar", "rightEar", "leftArm", "rightArm", "hindLeg"};
    if (!v || v->type != Value::JString || v->s.empty()) return c.fail(field + " 缺失：必须是 head / skull / body / tail / leftEar / rightEar / leftArm / rightArm / hindLeg 之一");
    for (int i = 0; i < 9; ++i) if (v->s == names[i]) { out = (SkinSpace)i; recognized = true; return true; }
    recognized = false;
    return true;
}

inline std::string trimmedUtf8(const std::string& s, size_t maxChars) {
    size_t a = s.find_first_not_of(" \t\r\n"), b = s.find_last_not_of(" \t\r\n");
    if (a == std::string::npos) return "";
    std::string t = s.substr(a, b - a + 1), out;
    size_t chars = 0;
    for (size_t i = 0; i < t.size() && chars < maxChars;) {
        unsigned char ch = (unsigned char)t[i];
        size_t len = ch < 0x80 ? 1 : ch < 0xE0 ? 2 : ch < 0xF0 ? 3 : 4;
        if (ch < 0x20) { ++i; continue; } // drop control characters (newlines etc.)
        out.append(t, i, len); i += len; ++chars;
    }
    return out;
}

inline SkinPoint cubic(const SkinBezierAnchor& a, const SkinBezierAnchor& b, float t) {
    float u = 1 - t;
    return {u * u * u * a.x + 3 * u * u * t * a.outX + 3 * u * t * t * b.inX + t * t * t * b.x,
            u * u * u * a.y + 3 * u * u * t * a.outY + 3 * u * t * t * b.inY + t * t * t * b.y};
}

} // namespace skinparse

inline bool SkinSpec::parse(const std::string& bytes, SkinSpec& out, std::string& error) {
    using namespace skinparse;
    using skinjson::Value;
    Ctx c;
    if (bytes.size() > MaxFileBytes) { error = "皮肤文件超过 2 MB 上限"; return false; }
    if (bytes.empty()) { error = "皮肤文件是空的"; return false; }
    Value root;
    {
        skinjson::Parser parser(bytes);
        if (!parser.parseDocument(root, error)) return false;
    }
    if (root.type != Value::JObject) { error = "皮肤文件最外层必须是 JSON 对象 { … }"; return false; }

    const Value* ver = root.get("formatVersion");
    if (!ver) { error = "缺少 formatVersion，这不是 KuroCat 皮肤文件"; return false; }
    if (ver->type != Value::JNumber || ver->n != std::floor(ver->n)) { error = "formatVersion 必须是整数"; return false; }
    if (ver->n > FormatVersion) { error = "这个皮肤使用了更新的格式（formatVersion " + std::to_string((long long)ver->n) + "），请先升级 KuroCat"; return false; }
    if (ver->n < 1) { error = "formatVersion 无效"; return false; }

    SkinSpec s;
    const Value* name = root.get("name");
    if (!name || name->type != Value::JString) { error = "缺少皮肤名称 name"; return false; }
    s.name = trimmedUtf8(name->s, 40);
    if (s.name.empty()) { error = "皮肤名称 name 不能为空"; return false; }
    if (const Value* author = root.get("author")) {
        if (author->type == Value::JString) s.author = trimmedUtf8(author->s, 40);
        else if (author->type != Value::JNull) { error = "author 必须是字符串"; return false; }
    }

    // Palette
    const Value* pal = root.get("palette");
    if (!pal || pal->type != Value::JObject) { error = "缺少调色板 palette"; return false; }
    struct Slot { const char* key; SkinColor SkinPalette::*member; };
    static const Slot slots[] = {
        {"body", &SkinPalette::body}, {"bodyShade", &SkinPalette::bodyShade}, {"belly", &SkinPalette::belly},
        {"legs", &SkinPalette::legs}, {"paws", &SkinPalette::paws}, {"hindLeg", &SkinPalette::hindLeg},
        {"hindPaw", &SkinPalette::hindPaw}, {"pawPads", &SkinPalette::pawPads},
        {"earOuter", &SkinPalette::earOuter}, {"earInner", &SkinPalette::earInner}, {"nose", &SkinPalette::nose},
        {"mouth", &SkinPalette::mouth}, {"iris", &SkinPalette::iris}, {"tail", &SkinPalette::tail},
        {"tailTip", &SkinPalette::tailTip}, {"stripes", &SkinPalette::stripes}, {"whiskers", &SkinPalette::whiskers},
        {"crease", &SkinPalette::crease}, {"outline", &SkinPalette::outline}, {"points", &SkinPalette::points},
        {"pointsMid", &SkinPalette::pointsMid},
    };
    for (const Slot& slot : slots)
        if (!color(c, pal->get(slot.key), std::string("palette.") + slot.key, s.palette.*slot.member)) { error = c.error; return false; }
    if (!s.palette.body.set) { error = "调色板缺少主体颜色 palette.body"; return false; }
    // Defaults derived from the base colours (documented in docs/skin-format.md).
    SkinPalette& p = s.palette;
    if (!p.legs.set) p.legs = p.body;
    if (!p.paws.set) p.paws = p.points.set ? p.points : p.legs;
    if (!p.earOuter.set) p.earOuter = p.points.set ? p.points : p.legs;
    if (!p.tail.set) p.tail = p.earOuter;
    if (p.points.set && !p.pointsMid.set) {
        p.pointsMid = SkinColor::rgba((p.points.r + p.body.r) * 0.5, (p.points.g + p.body.g) * 0.5, (p.points.b + p.body.b) * 0.5, 1);
    }
    bool darkBody = p.body.luminance() < 0.45;
    if (!p.whiskers.set) p.whiskers = darkBody ? SkinColor::rgba(0.88, 0.90, 0.92, 0.68) : SkinColor::hex(0x8D8170, 0.68);
    if (!p.crease.set) p.crease = darkBody ? SkinColor::rgba(0.82, 0.92, 0.89, 0.76) : SkinColor::hex(0x8B8171, 0.60);

    // Shape
    if (const Value* sh = root.get("shape")) {
        if (sh->type != Value::JObject) { error = "shape 必须是对象"; return false; }
        if (const Value* b = sh->get("build")) {
            if (b->type != Value::JString || (b->s != "standard" && b->s != "sleek")) { error = "shape.build 必须是 \"standard\" 或 \"sleek\""; return false; }
            s.shape.build = b->s == "sleek" ? SkinBuild::Sleek : SkinBuild::Standard;
        }
        SkinShape& h = s.shape;
        if (!number(c, sh->get("bodyWidth"), "shape.bodyWidth", 0.85, 1.35, h.bodyWidth) ||
            !number(c, sh->get("headScale"), "shape.headScale", 0.90, 1.15, h.headScale) ||
            !number(c, sh->get("earSize"), "shape.earSize", 0.80, 1.25, h.earSize) ||
            !number(c, sh->get("earBaseWidth"), "shape.earBaseWidth", 0.65, 1.40, h.earBaseWidth) ||
            !number(c, sh->get("earPointiness"), "shape.earPointiness", 0.50, 1.50, h.earPointiness) ||
            !number(c, sh->get("tailLength"), "shape.tailLength", 0.70, 1.30, h.tailLength) ||
            !number(c, sh->get("tailThickness"), "shape.tailThickness", 0.70, 1.50, h.tailThickness) ||
            !number(c, sh->get("cheekFullness"), "shape.cheekFullness", 0.85, 1.25, h.cheekFullness) ||
            !number(c, sh->get("neckWidth"), "shape.neckWidth", 0.65, 1.40, h.neckWidth) ||
            !number(c, sh->get("pawStagger"), "shape.pawStagger", 0.0, 1.0, h.pawStagger)) { error = c.error; return false; }
    }
    if (const Value* hs = root.get("headSurface")) {
        if (hs->type != Value::JString || (hs->s != "dome" && hs->s != "plane")) { error = "headSurface 必须是 \"dome\" 或 \"plane\""; return false; }
        s.headSurface = hs->s == "plane" ? SkinHeadSurface::Plane : SkinHeadSurface::Dome;
    }

    if (const Value* il = root.get("idleLegs")) {
        if (il->type != Value::JString || (il->s != "legs" && il->s != "chest")) { error = "idleLegs 必须是 \"legs\" 或 \"chest\""; return false; }
        s.idleLegsTinted = il->s == "legs";
    }
    if (const Value* rs = root.get("renderStyle"); rs && rs->type == Value::JString) {
        if (rs->s == "douni") s.renderStyle = SkinRenderStyle::Douni;
        else if (rs->s == "dazed") s.renderStyle = SkinRenderStyle::Dazed;
    }
    if (const Value* ts = root.get("typingStyle"); ts && ts->type == Value::JString) {
        if (ts->s == "douni") s.typingStyle = SkinTypingStyle::Douni;
    }

    // Regions (pen-tool curve areas)
    if (const Value* regs = root.get("regions")) {
        if (regs->type != Value::JArray) { error = "regions 必须是数组"; return false; }
        if (regs->items.size() > 64) { error = "regions 最多 64 个分区"; return false; }
        for (size_t i = 0; i < regs->items.size(); ++i) {
            const Value& r = regs->items[i];
            std::string f = "regions[" + std::to_string(i) + "]";
            if (r.type != Value::JObject) { error = f + " 必须是对象"; return false; }
            SkinRegion reg;
            bool knownSpace = false;
            if (!space(c, r.get("space"), f + ".space", reg.space, knownSpace)) { error = c.error; return false; }
            if (!knownSpace) continue;
            const Value* fill = r.get("fill");
            if (!fill || fill->type == Value::JNull) { error = f + ".fill 缺失"; return false; }
            if (!color(c, fill, f + ".fill", reg.fill)) { error = c.error; return false; }
            float alpha = 1;
            if (!number(c, r.get("alpha"), f + ".alpha", 0, 1, alpha)) { error = c.error; return false; }
            reg.fill.a *= alpha;
            const Value* anchors = r.get("anchors");
            if (!anchors || anchors->type != Value::JArray) { error = f + ".anchors 必须是锚点数组"; return false; }
            if (anchors->items.size() < 2 || anchors->items.size() > 128) { error = f + ".anchors 需要 2–128 个锚点"; return false; }
            for (size_t k = 0; k < anchors->items.size(); ++k) {
                const Value& a = anchors->items[k];
                std::string af = f + ".anchors[" + std::to_string(k) + "]";
                if (a.type != Value::JObject) { error = af + " 必须是 {x, y, inX, inY, outX, outY} 对象"; return false; }
                const Value* x = a.get("x");
                const Value* y = a.get("y");
                if (!x || !y) { error = af + " 缺少 x / y"; return false; }
                SkinBezierAnchor an;
                if (!number(c, x, af + ".x", -400, 400, an.x) || !number(c, y, af + ".y", -400, 400, an.y)) { error = c.error; return false; }
                an.inX = an.outX = an.x; an.inY = an.outY = an.y; // missing handles = sharp corner
                if (!number(c, a.get("inX"), af + ".inX", -400, 400, an.inX) || !number(c, a.get("inY"), af + ".inY", -400, 400, an.inY) ||
                    !number(c, a.get("outX"), af + ".outX", -400, 400, an.outX) || !number(c, a.get("outY"), af + ".outY", -400, 400, an.outY)) { error = c.error; return false; }
                reg.anchors.push_back(an);
            }
            for (size_t k = 0; k < reg.anchors.size(); ++k) {
                const SkinBezierAnchor& a = reg.anchors[k];
                const SkinBezierAnchor& b = reg.anchors[(k + 1) % reg.anchors.size()];
                for (int t = 0; t < 16; ++t) reg.flat.push_back(cubic(a, b, t / 16.0f));
            }
            s.regions.push_back(std::move(reg));
        }
    }

    // Marks (polygons / strokes, same model as the built-in CoatMark artwork)
    if (const Value* marks = root.get("marks")) {
        if (marks->type != Value::JArray) { error = "marks 必须是数组"; return false; }
        if (marks->items.size() > 256) { error = "marks 最多 256 条"; return false; }
        for (size_t i = 0; i < marks->items.size(); ++i) {
            const Value& m = marks->items[i];
            std::string f = "marks[" + std::to_string(i) + "]";
            if (m.type != Value::JObject) { error = f + " 必须是对象"; return false; }
            SkinMark mark;
            bool knownSpace = false;
            if (!space(c, m.get("space"), f + ".space", mark.space, knownSpace)) { error = c.error; return false; }
            if (!knownSpace) continue;
            const Value* kind = m.get("kind");
            if (!kind || kind->type != Value::JString || (kind->s != "polygon" && kind->s != "stroke")) { error = f + ".kind 必须是 \"polygon\" 或 \"stroke\""; return false; }
            mark.stroke = kind->s == "stroke";
            if (!color(c, m.get("color"), f + ".color", mark.color)) { error = c.error; return false; }
            if (!mark.color.set) {
                if (!s.palette.stripes.set) { error = f + ".color 缺失，且调色板没有 stripes 可作默认色"; return false; }
                mark.color = s.palette.stripes;
            }
            float alpha = 1;
            if (!number(c, m.get("alpha"), f + ".alpha", 0, 1, alpha)) { error = c.error; return false; }
            mark.color.a *= alpha;
            mark.width = mark.stroke ? 2.0f : 0.0f;
            if (mark.stroke && !number(c, m.get("width"), f + ".width", 0.2, 24, mark.width)) { error = c.error; return false; }
            const Value* pts = m.get("points");
            if (!pts || pts->type != Value::JArray) { error = f + ".points 必须是 [[x, y], …] 数组"; return false; }
            size_t minPts = mark.stroke ? 2 : 3;
            if (pts->items.size() < minPts || pts->items.size() > 512) { error = f + ".points 需要 " + std::to_string(minPts) + "–512 个点"; return false; }
            for (size_t k = 0; k < pts->items.size(); ++k) {
                const Value& pt = pts->items[k];
                if (pt.type != Value::JArray || pt.items.size() != 2 || pt.items[0].type != Value::JNumber || pt.items[1].type != Value::JNumber) {
                    error = f + ".points[" + std::to_string(k) + "] 必须是 [x, y]"; return false;
                }
                mark.points.push_back({clampf(pt.items[0].n, -400, 400), clampf(pt.items[1].n, -400, 400)});
            }
            if (const Value* cb = m.get("clipToBib")) mark.clipToBib = (cb->type == Value::JBool && cb->b);
            s.marks.push_back(std::move(mark));
        }
    }

    // Decorations (anchored PNG stickers)
    if (const Value* decos = root.get("decorations")) {
        if (decos->type != Value::JArray) { error = "decorations 必须是数组"; return false; }
        if (decos->items.size() > 8) { error = "decorations 最多 8 个贴纸"; return false; }
        for (size_t i = 0; i < decos->items.size(); ++i) {
            const Value& d = decos->items[i];
            std::string f = "decorations[" + std::to_string(i) + "]";
            if (d.type != Value::JObject) { error = f + " 必须是对象"; return false; }
            SkinDecoration deco;
            const Value* png = d.get("png");
            if (!png || png->type != Value::JString || !skinjson::base64Decode(png->s, deco.png)) { error = f + ".png 必须是 base64 编码的 PNG"; return false; }
            if (deco.png.size() > 1024 * 1024) { error = f + ".png 超过 1 MB"; return false; }
            if (!skinjson::pngSize(deco.png, deco.pixelWidth, deco.pixelHeight) || deco.pixelWidth > 1024 || deco.pixelHeight > 1024) {
                error = f + ".png 不是有效的 PNG（或尺寸超过 1024×1024）"; return false;
            }
            const Value* anchor = d.get("anchor");
            static const char* anchors[] = {"headTop", "face", "neck", "tailTip"};
            if (!anchor || anchor->type != Value::JString || anchor->s.empty()) {
                error = f + ".anchor 必须是 headTop / face / neck / tailTip 之一"; return false;
            }
            bool ok = false;
            for (int k = 0; k < 4; ++k) if (anchor->s == anchors[k]) { deco.anchor = (SkinAnchorPoint)k; ok = true; }
            if (!ok) continue;
            if (!number(c, d.get("offsetX"), f + ".offsetX", -120, 120, deco.offsetX) || !number(c, d.get("offsetY"), f + ".offsetY", -120, 120, deco.offsetY) ||
                !number(c, d.get("scale"), f + ".scale", 0.05, 4, deco.scale) || !number(c, d.get("rotation"), f + ".rotation", -180, 180, deco.rotation)) { error = c.error; return false; }
            s.decorations.push_back(std::move(deco));
        }
    }

    if (const Value* prev = root.get("preview")) {
        if (prev->type == Value::JString) {
            int w = 0, h = 0;
            if (!skinjson::base64Decode(prev->s, s.preview) || !skinjson::pngSize(s.preview, w, h) || s.preview.size() > 512 * 1024) {
                error = "preview 必须是不超过 512 KB 的 base64 PNG"; return false;
            }
        } else if (prev->type != Value::JNull) { error = "preview 必须是 base64 PNG 字符串"; return false; }
    }

    s.id = contentId(bytes);
    out = std::move(s);
    return true;
}

inline bool SkinSpec::loadFile(const std::string& path, SkinSpec& out, std::string& error) {
    FILE* f = std::fopen(path.c_str(), "rb");
    if (!f) { error = "无法打开文件"; return false; }
    std::string bytes;
    char buf[65536];
    size_t n;
    while ((n = std::fread(buf, 1, sizeof buf, f)) > 0) {
        bytes.append(buf, n);
        if (bytes.size() > MaxFileBytes) { std::fclose(f); error = "皮肤文件超过 2 MB 上限"; return false; }
    }
    std::fclose(f);
    return parse(bytes, out, error);
}

// Stable id for an imported file: FNV-1a 64 of its bytes (also its file name in the skins folder).
inline std::string SkinSpec::contentId(const std::string& bytes) {
    uint64_t h = 1469598103934665603ULL;
    for (unsigned char ch : bytes) { h ^= ch; h *= 1099511628211ULL; }
    char out[17];
    std::snprintf(out, sizeof out, "%016llx", (unsigned long long)h);
    return out;
}

// Head/body split used to clip regions (docs/skin-format.md §2.3): the jaw line runs from under one
// cheek (±44·cheekFullness, 8) down to the chin (0, 34) in head space; head + skull regions are drawn
// on the side above it, body regions below it. The polygon is in head space (projected like head marks).
inline std::vector<SkinPoint> skinJawSide(bool headSide, float cheekFullness) {
    float c = cheekFullness, edgeY = headSide ? -400.0f : 400.0f;
    std::vector<SkinPoint> pts = {{-400, edgeY}, {400, edgeY}, {400, 8}};
    auto cubicTo = [&](SkinPoint p0, SkinPoint p1, SkinPoint p2, SkinPoint p3) {
        for (int i = 1; i <= 16; ++i) {
            float t = i / 16.0f, u = 1 - t;
            pts.push_back({u*u*u*p0.x + 3*u*u*t*p1.x + 3*u*t*t*p2.x + t*t*t*p3.x,
                           u*u*u*p0.y + 3*u*u*t*p1.y + 3*u*t*t*p2.y + t*t*t*p3.y});
        }
    };
    pts.push_back({44 * c, 8});
    cubicTo({44 * c, 8}, {44 * c, 22}, {24 * c, 34}, {0, 34});
    cubicTo({0, 34}, {-24 * c, 34}, {-44 * c, 22}, {-44 * c, 8});
    pts.push_back({-400, 8});
    return pts;
}

// Built-in coats share the generated CoatMark artwork; converts it into SkinSpec marks.
inline std::vector<SkinMark> skinMarksFromCoat(const std::vector<CoatMark>& coat) {
    std::vector<SkinMark> out;
    for (const CoatMark& m : coat) {
        SkinMark s;
        s.space = m.skull ? SkinSpace::Skull : (m.head ? SkinSpace::Head : SkinSpace::Body);
        s.stroke = m.width != 0;
        s.width = m.width;
        s.color = SkinColor::hex(m.rgb, m.alpha);
        s.clipToBib = m.clipToBib;
        for (const CoatPoint& p : m.points) s.points.push_back({p.x, p.y});
        out.push_back(std::move(s));
    }
    return out;
}
