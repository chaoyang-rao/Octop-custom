#pragma once
#define NOMINMAX
#include <windows.h>
#include <objidl.h>
#include <gdiplus.h>
#include <cmath>
#include <cstring>
#include <vector>
#include <algorithm>
#include "CatPhysics.hpp"
#include "TabbyCoat.hpp"
#include "../../shared/CoatPatterns.hpp"
#include "../../shared/SkinSpec.hpp"
#include "../../shared/KeyboardSkinSpec.hpp"

enum class CatHitZone {
    None,
    Head,
    Body
};

// The six built-in coats expressed as SkinSpecs, using the exact 8-bit colours the GDI+ renderer always
// used, so built-ins render exactly as before. (skins/*.kurocat are the portable templates of these coats.)
inline const SkinSpec& builtInSkin(CatCoatTheme coat) {
    static const std::vector<SkinSpec> skins = [] {
        auto c8 = [](int r, int g, int b, int a = 255) { return SkinColor::rgba(r / 255.0, g / 255.0, b / 255.0, a / 255.0); };
        const SkinColor black = c8(22, 22, 24);
        const SkinColor milk = c8(0xF2, 0xEE, 0xE4);
        auto tailRings = [&](int r, int g, int b) {
            std::vector<SkinMark> rings;
            for (float x : {50.0f, 78.0f}) {
                SkinMark m;
                m.space = SkinSpace::Tail; m.stroke = true; m.width = 3.5f; m.color = c8(r, g, b, 128);
                m.points = {{x, 8.0f}, {x, -8.0f}};
                rings.push_back(m);
            }
            return rings;
        };
        std::vector<SkinSpec> v(6);
        SkinSpec& k = v[0];
        k.id = "builtin:0"; k.name = "经典小黑猫"; k.builtIn = true;
        k.palette.body = k.palette.legs = k.palette.paws = k.palette.earOuter = k.palette.tail = black;
        k.palette.whiskers = c8(224, 230, 235, 174); k.palette.crease = c8(209, 235, 227, 194);

        SkinSpec& s = v[1];
        s.id = "builtin:1"; s.name = "挖煤暹罗猫"; s.builtIn = true; s.shape.build = SkinBuild::Sleek;
        const SkinColor point = c8(53, 38, 31);
        s.palette.body = c8(246, 239, 228);
        s.palette.bodyShade = c8(234, 219, 200);
        s.palette.points = s.palette.paws = s.palette.earOuter = s.palette.tail = s.palette.legs = point;
        s.palette.pointsMid = c8(106, 80, 65);
        s.palette.earInner = c8(93, 70, 58);
        s.palette.outline = c8(173, 150, 128, 107);
        s.palette.crease = c8(141, 120, 103, 138);
        s.palette.whiskers = c8(122, 99, 83, 158);
        s.palette.nose = c8(36, 23, 20, 242);
        s.palette.mouth = c8(199, 168, 143, 140);

        SkinSpec& h = v[2];
        h.id = "builtin:2"; h.name = "美短（银虎斑加白）"; h.builtIn = true;
        h.palette.body = h.palette.earOuter = h.palette.tail = c8(0xC2, 0xC5, 0xC1);
        h.palette.belly = h.palette.paws = h.palette.legs = milk;
        h.palette.stripes = c8(0x55, 0x59, 0x5A);
        h.palette.whiskers = c8(0x8D, 0x81, 0x70, 174); h.palette.crease = c8(0x8B, 0x81, 0x71, 153);
        h.headSurface = SkinHeadSurface::Plane; h.shape.pawStagger = 0;
        h.marks = skinMarksFromCoat(shorthairMarks());
        for (auto& m : tailRings(0x55, 0x59, 0x5A)) h.marks.push_back(m);

        SkinSpec& o = v[3];
        o.id = "builtin:3"; o.name = "橘白猫"; o.builtIn = true;
        o.palette.body = milk;
        o.palette.earOuter = o.palette.tail = c8(0xD8, 0xAA, 0x73);
        o.palette.belly = o.palette.paws = o.palette.legs = milk;
        o.palette.stripes = c8(0xA5, 0x75, 0x43);
        o.palette.whiskers = c8(0x8D, 0x81, 0x70, 174); o.palette.crease = c8(0x8B, 0x81, 0x71, 153);
        o.headSurface = SkinHeadSurface::Dome; o.shape.pawStagger = 0;
        o.marks = skinMarksFromCoat(orangeWhiteMarks());
        for (auto& m : tailRings(0xA5, 0x75, 0x43)) o.marks.push_back(m);

        SkinSpec& d = v[4];
        d.id = "builtin:4"; d.name = "呆猫"; d.builtIn = true;
        d.palette.body = c8(0x4E, 0x57, 0x92);
        d.palette.legs = c8(0xE3, 0xC9, 0x9F);
        d.palette.paws = c8(0xFF, 0xF1, 0xCD);
        d.palette.earOuter = c8(0x55, 0x5F, 0x9B);
        d.palette.tail = c8(0x28, 0x31, 0x57);
        d.palette.whiskers = c8(0x8D, 0x81, 0x70, 174); d.palette.crease = c8(0x7C, 0x86, 0xBC, 155);

        SkinSpec& t = v[5];
        t.id = "builtin:5"; t.name = "狸花猫"; t.builtIn = true;
        t.palette.body = c8(202, 180, 149);
        t.palette.legs = c8(174, 152, 123);
        t.palette.paws = c8(239, 231, 213);
        t.palette.earOuter = c8(103, 86, 66);
        t.palette.tail = c8(163, 143, 117);
        t.palette.whiskers = c8(104, 85, 65, 174); t.palette.crease = c8(104, 85, 65, 255);

        for (SkinSpec& b : v) b.idleLegsTinted = false;
        return v;
    }();
    int i = std::clamp((int)coat, 0, static_cast<int>(CatCoatTheme::Tabby));
    return skins[(size_t)i];
}

class CatRenderer {
public:
    static constexpr float RadToDeg = 57.2957795f;

    static Pt headPosition(const CatPhysics& physics, const SkinSpec& skin) {
        float breath = physics.breathingOffset();
        float scruff = std::clamp(physics.scruffDrag.value, 0.0f, 1.0f);
        return {
            CatPhysics::SeatAnchor.x + physics.bodyShiftX.value + physics.bodyTilt.value * 36.0f + physics.headYaw.value * 7.5f,
            126.0f + buildOf(skin).headLift + physics.headOffsetY.value + physics.headPitch.value * 4.8f + breath * 1.1f - scruff * 22.0f
        };
    }

    static CatHitZone hitTest(Pt p, const CatPhysics& physics, const SkinSpec& skin) {
        if (skin.renderStyle == SkinRenderStyle::Douni) {
            float loaf = std::clamp(physics.douniLoafBlend.value, 0.0f, 1.0f);
            float loafS = loaf * loaf * (3.0f - 2.0f * loaf);
            float scruff = std::clamp(physics.scruffDrag.value, 0.0f, 1.0f);
            if (scruff > 0.25f) {
                float d = std::hypot((p.x - 178.0f) / 118.0f, (p.y - 165.0f) / 96.0f);
                return d <= 1.0f ? CatHitZone::Body : CatHitZone::None;
            }
            // Continuously interpolate head hit zone from Video 2 desk seat -> Video 1 loaf so petting never drops or ping-pongs mid-morph!
            float hx = 248.0f + (162.0f - 248.0f) * loafS;
            float hy = 124.0f + (188.0f - 124.0f) * loafS;
            float hrx = 76.0f + (92.0f - 76.0f) * loafS;
            float hdx = (p.x - hx) / hrx;
            float hdy = (p.y - hy) / 56.0f;
            if (hdx * hdx + hdy * hdy <= 1.0f) return CatHitZone::Head;
            if ((loaf > 0.03f || physics.petHeadIntensity > 0.05f) && loaf < 0.90f) {
                float v2dx = (p.x - 248.0f) / 76.0f;
                float v2dy = (p.y - 124.0f) / 56.0f;
                if (v2dx * v2dx + v2dy * v2dy <= 1.0f) return CatHitZone::Head;
            }
            if (loafS > 0.55f) {
                float bdx = (p.x - 196.0f) / 118.0f;
                float bdy = (p.y - 196.0f) / 68.0f;
                return (bdx * bdx + bdy * bdy <= 1.0f) ? CatHitZone::Body : CatHitZone::None;
            }
            if (p.x >= 24.0f && p.x <= 336.0f && p.y >= 120.0f && p.y <= 278.0f) return CatHitZone::Body;
            return CatHitZone::None;
        }

        const SkinShape& shape = skin.shape;
        float cx = CatPhysics::SeatAnchor.x + physics.bodyShiftX.value;
        float breath = std::sin(physics.time * 2.1f) * 1.6f;
        Pt headCenter = { cx + physics.bodyTilt.value * 36.0f + physics.headYaw.value * 7.5f,
                          126.0f + buildOf(skin).headLift + physics.headOffsetY.value + physics.headPitch.value * 4.8f + breath * 1.1f };

        // Petting zones follow the reshaped head (size + cheeks) and body (width), plus Dazed Cat hood proportions.
        bool dazed = isDazed(skin);
        float hdx = (p.x - headCenter.x) / ((dazed ? 47.0f : 44.0f) * shape.headScale * shape.cheekFullness);
        float hdy = (p.y - headCenter.y - (dazed ? 3.0f : 0.0f)) / ((dazed ? 40.0f : 38.0f) * shape.headScale);
        if (hdx * hdx + hdy * hdy <= 1.0f) return CatHitZone::Head;

        float bdx = (p.x - cx) / (58.0f * shape.bodyWidth);
        float bdy = (p.y - 196.0f) / 56.0f;
        if (bdx * bdx + bdy * bdy <= 1.0f) return CatHitZone::Body;

        if (p.x >= 58.0f && p.x <= 294.0f && p.y >= 232.0f && p.y <= 296.0f) return CatHitZone::Body;
        return CatHitZone::None;
    }

    /// Maps a point in unflipped 360x320 canvas coordinates into cat-local coordinates
    /// by inverting the canvas rotation (+ anti-clipping fitScale) and optional horizontal flip.
    static Pt canvasPointToCatSpace(Pt p, bool flipped, float rotationDeg) {
        Pt pt = p;
        if (std::fabs(rotationDeg) > 0.01f) {
            constexpr float cx = CatPhysics::CanvasWidth * 0.5f;
            constexpr float cy = CatPhysics::CanvasHeight * 0.5f;
            float rad = rotationDeg * (3.14159265f / 180.0f);
            float fit = std::max(0.5f, 1.0f - std::fabs(std::sin(rad)) * 0.14f);
            float dx = (pt.x - cx) / fit;
            float dy = (pt.y - cy) / fit;
            float c = std::cos(-rad);
            float s = std::sin(-rad);
            pt = { cx + dx * c - dy * s, cy + dx * s + dy * c };
        }
        if (flipped) {
            pt.x = CatPhysics::CanvasWidth - pt.x;
        }
        return pt;
    }

    /// Edit-mode hit test in unflipped 360x320 canvas coordinates:
    /// 20 = top rotation handle, 0..3 = corner resize handles, 12 = inside edit box, -1 = outside.
    static int hitTestEditOverlay(Pt p) {
        if (std::hypot(p.x - 180.0f, p.y - 12.0f) <= 15.0f) return 20;
        constexpr Pt corners[4] = { {10.0f, 26.0f}, {350.0f, 26.0f}, {10.0f, 310.0f}, {350.0f, 310.0f} };
        for (int i = 0; i < 4; ++i) {
            if (std::hypot(p.x - corners[i].x, p.y - corners[i].y) <= 18.0f) return i;
        }
        if (p.x >= 6.0f && p.x <= 354.0f && p.y >= 22.0f && p.y <= 314.0f) return 12;
        return -1;
    }

    static void draw(Gdiplus::Graphics& g, const CatPhysics& physics, const CatSettings& settings, const SkinSpec& skin) {
        draw(g, physics, settings, skin, KeyboardSkinSpec::builtInTheme((int)settings.keyboardTheme));
    }

    static void draw(Gdiplus::Graphics& g, const CatPhysics& physics, const CatSettings& settings, const SkinSpec& skin, const KeyboardSkinSpec& kbSkin) {
        using namespace Gdiplus;
        whiteOutlineEnabled() = settings.whiteOutline;
        g.SetSmoothingMode(SmoothingModeAntiAlias);
        g.SetPixelOffsetMode(PixelOffsetModeHighQuality);
        g.SetTextRenderingHint(TextRenderingHintAntiAliasGridFit);

        GraphicsState flipState = g.Save();
        if (std::fabs(settings.rotationDeg) > 0.01f) {
            constexpr float cx = CatPhysics::CanvasWidth * 0.5f;
            constexpr float cy = CatPhysics::CanvasHeight * 0.5f;
            float rad = settings.rotationDeg * (3.14159265f / 180.0f);
            float fit = 1.0f - std::fabs(std::sin(rad)) * 0.14f;
            g.TranslateTransform(cx, cy);
            g.RotateTransform(settings.rotationDeg);
            g.ScaleTransform(fit, fit);
            g.TranslateTransform(-cx, -cy);
        }
        if (settings.flipHorizontal) {
            g.TranslateTransform(CatPhysics::CanvasWidth, 0.0f);
            g.ScaleTransform(-1.0f, 1.0f);
        }

        float breath = std::sin(physics.time * 2.1f) * 1.6f;
        float seatX = CatPhysics::SeatAnchor.x + physics.bodyShiftX.value;
        float scruff = std::clamp(physics.scruffDrag.value, 0.0f, 1.0f);
        float lie = std::clamp(physics.lieIntensity.value, 0.0f, 1.0f);
        float dizzy = std::clamp(physics.dizzyIntensity.value, 0.0f, 1.0f);
        float lieS = lie * lie * (3.0f - 2.0f * lie);
        float dizzyFallRaw = std::clamp((dizzy - 0.50f) / 0.50f, 0.0f, 1.0f);
        float dizzyFall = dizzyFallRaw * dizzyFallRaw * (3.0f - 2.0f * dizzyFallRaw);
        float preWobble = std::clamp((dizzy - 0.12f) / 0.38f, 0.0f, 1.0f) * (1.0f - dizzyFall);

        if (skin.renderStyle == SkinRenderStyle::Douni) {
            drawDouniScene(g, physics, skin, kbSkin, settings.eyeTheme, settings.keyboardMarquee);
            if (!physics.floatingKeycaps.empty()) {
                drawFloatingKeycaps(g, physics);
            }
            g.Restore(flipState);
            if (settings.isEditMode) {
                drawEditOverlay(g, settings.scale, settings.rotationDeg, settings.flipHorizontal);
            }
            return;
        }

        // Universal Scruff-Lifted Drag Pose (ALL non-Douni cat skins keep their own authentic KuroCat face/head/ears/markings in front,
        // with scruff-lifted arched neck/back, 4 dangling swinging paws, and limp drooping tail!)
        if (scruff > 0.005f) {
            float kbFade = std::clamp(1.0f - scruff * 2.6f, 0.0f, 1.0f);
            if (kbFade > 0.01f) {
                drawWithLayerAlpha(g, kbFade, [&](Graphics& lg) {
                    if (physics.isTabletActive) {
                        drawTablet(lg, physics, settings.keyboardTheme, settings.eyeTheme);
                        drawParkedStylus(lg, settings.keyboardTheme, settings.eyeTheme);
                    } else {
                        drawMouse(lg, physics, kbSkin);
                    }
                    drawKeyboard(lg, physics, kbSkin, settings.eyeTheme, settings.showKeyLegends, settings.keyboardMarquee);
                });
            }
            drawNativeScruffDragCat(g, physics, skin, settings.eyeTheme, scruff);
            if (!physics.floatingKeycaps.empty()) {
                drawFloatingKeycaps(g, physics);
            }
            g.Restore(flipState);
            if (settings.isEditMode) {
                drawEditOverlay(g, settings.scale, settings.rotationDeg, settings.flipHorizontal);
            }
            return;
        }

        float seatY = CatPhysics::SeatAnchor.y - scruff * 22.0f + lieS * 10.0f;
        float fallAngle = -dizzyFall * 1.46f + std::sin(physics.time * 9.5f) * 0.16f * preWobble;
        float fallShiftX = dizzyFall * 56.0f;
        float fallShiftY = dizzyFall * 20.0f;

        Pt headCenter = {
            seatX + physics.bodyTilt.value * 36.0f + physics.headYaw.value * 7.5f - lieS * 4.0f,
            126.0f + buildOf(skin).headLift + physics.headOffsetY.value + physics.headPitch.value * 4.8f + breath * 1.1f - scruff * 22.0f + lieS * 60.0f
        };

        // 1. Mini White Mouse OR Graphics Tablet (when drawing tablet/stylus is connected!)
        if (physics.isTabletActive) {
            drawTablet(g, physics, settings.keyboardTheme, settings.eyeTheme);
            if (!physics.leftPawOnMouse || scruff > 0.25f || dizzy > 0.35f || lie > 0.45f) {
                drawParkedStylus(g, settings.keyboardTheme, settings.eyeTheme);
            }
        } else {
            drawMouse(g, physics, kbSkin);
        }

        // 2. Mini 65% Mechanical Keyboard (facing cat) + Backlit Glow
        drawKeyboard(g, physics, kbSkin, settings.eyeTheme, settings.showKeyLegends, settings.keyboardMarquee);

        GraphicsState fallState = g.Save();
        if (dizzy > 0.01f) {
            g.TranslateTransform(seatX + fallShiftX, seatY + fallShiftY);
            g.RotateTransform(fallAngle * RadToDeg);
            g.TranslateTransform(-seatX, -seatY);
        }

        if (isDazed(skin)) drawDazedSword(g, seatX, seatY, physics);
        bool tailInFront = (physics.tailTyping.value >= 0.5f) || (lieS >= 0.45f);
        // Pass 1: unified sticker-style outer white outline for ALL cat skins (optional)
        if (whiteOutlineEnabled()) {
            // Outline connected parts first; fills cover the internal tail-root seam.
            drawTail(g, seatX, seatY, physics, skin, true);
            drawEarsLayer(g, headCenter, physics, skin, true);
            drawUnifiedSilhouette(g, seatX, seatY, headCenter, breath, physics, skin, true);
        }
        // 3. Tail (behind body unless 4-key tail typing or curled up asleep)
        if (!tailInFront) drawTail(g, seatX, seatY, physics, skin);

        // 4. 3D-Projected Ears (behind crown silhouette)
        drawEarsLayer(g, headCenter, physics, skin);

        // 5. Unified C1-Continuous Silhouette (+ regions, colour-point mask, marks)
        drawUnifiedSilhouette(g, seatX, seatY, headCenter, breath, physics, skin);

        // 6. Hind Foot (3rd simultaneous key easter egg!)
        if (physics.hindFootActive.value > 0.03f) {
            drawHindFoot(g, seatX, seatY, physics, skin);
        }

        // 7. 2.5D Eyes & Whiskers (+ optional nose/mouth, yawn, angry vein)
        drawHeadFeatures(g, headCenter, physics, settings.eyeTheme, skin);

        // 7b. Skin stickers anchored to head / neck / tail tip
        if (!skin.decorations.empty()) drawDecorations(g, seatX, seatY, headCenter, physics, skin);

        // 8. Front Paws (Idle Sitting & Dynamic Reaching)
        drawFrontPaws(g, seatX, seatY, breath, physics, skin);

        // 8b. Held Stylus gripped cleanly in the cat's paw when drawing on the graphics tablet!
        if (physics.isTabletActive && physics.leftPawOnMouse && scruff <= 0.25f && dizzy <= 0.35f && lie <= 0.45f) {
            drawHeldStylus(g, physics, settings.keyboardTheme, settings.eyeTheme);
        }

        if (tailInFront) {

            drawTail(g, seatX, seatY, physics, skin);
        }

        g.Restore(fallState);

        // Upright orbiting golden dizzy stars floating right above the head (appear FIRST before falling!)
        if (dizzy > 0.10f) {
            float relX = headCenter.x - seatX;
            float relY = headCenter.y - seatY;
            float worldHeadX = seatX + fallShiftX + relX * std::cos(fallAngle) - relY * std::sin(fallAngle);
            float worldHeadY = seatY + fallShiftY + relX * std::sin(fallAngle) + relY * std::cos(fallAngle);
            float dAlpha = std::min(1.0f, (dizzy - 0.10f) / 0.22f);
            float starLift = 42.0f + dizzyFall * 10.0f;
            GraphicsState ss = g.Save();
            g.TranslateTransform(worldHeadX, worldHeadY - starLift);
            SolidBrush sb(Color((BYTE)(245 * dAlpha), 255, 220, 56));
            for (int i = 0; i < 3; ++i) {
                float ang = physics.dizzyPhase * 0.85f + (float)i * (6.283185f / 3.0f);
                float sx = std::cos(ang) * 26.0f;
                float sy = std::sin(ang) * 6.5f;
                float r = 4.4f * (0.75f + 0.25f * std::sin(ang));
                PointF pts[8];
                float rot = physics.dizzyPhase + (float)i;
                for (int k = 0; k < 8; ++k) {
                    float rad = (k % 2 == 0) ? r : r * 0.42f;
                    float a = rot + (float)k * 0.785398f;
                    pts[k] = PointF(sx + std::cos(a) * rad, sy + std::sin(a) * rad);
                }
                g.FillPolygon(&sb, pts, 8);
            }
            g.Restore(ss);
        }

        // 9. Floating Keycap Badges (keyboard + mouse clicks)
        if (!physics.floatingKeycaps.empty()) {
            drawFloatingKeycaps(g, physics);
        }

        // 10. Subtle Petting Sparkles & Sleep Z
        drawSparkles(g, physics, settings.eyeTheme);

        g.Restore(flipState);

        if (settings.isEditMode) {
            drawEditOverlay(g, settings.scale, settings.rotationDeg, settings.flipHorizontal);
        }
    }

    static void drawEditOverlay(Gdiplus::Graphics& g, float scale, float rotationDeg, bool flipHorizontal) {
        using namespace Gdiplus;
        // Transparent interior (no light-blue background fill, no Flip/Done pill buttons)
        GraphicsPath boxPath;
        addRoundedRect(boxPath, 10.0f, 26.0f, 340.0f, 284.0f, 12.0f);

        Pen dashPen(Color(235, 51, 158, 255), 1.6f);
        REAL dashes[2] = { 4.5f, 3.0f };
        dashPen.SetDashPattern(dashes, 2);
        g.DrawPath(&dashPen, &boxPath);

        // Stem from top edge of edit box up to circular rotation handle
        Pen stemPen(Color(235, 51, 158, 255), 1.6f);
        stemPen.SetStartCap(LineCapRound); stemPen.SetEndCap(LineCapRound);
        g.DrawLine(&stemPen, 180.0f, 26.0f, 180.0f, 20.0f);

        constexpr Pt corners[4] = { {10.0f, 26.0f}, {350.0f, 26.0f}, {10.0f, 310.0f}, {350.0f, 310.0f} };
        SolidBrush whiteBrush(Color(255, 255, 255, 255));
        Pen handlePen(Color(255, 36, 133, 245), 2.0f);
        for (const auto& c : corners) {
            g.FillEllipse(&whiteBrush, c.x - 6.0f, c.y - 6.0f, 12.0f, 12.0f);
            g.DrawEllipse(&handlePen, c.x - 6.0f, c.y - 6.0f, 12.0f, 12.0f);
        }

        // Top-center rotation handle (drag = rotate, click = flip horizontal, double-click = reset 0 deg)
        constexpr float rx = 180.0f, ry = 12.0f, rr = 8.5f;
        g.FillEllipse(&whiteBrush, rx - rr, ry - rr, rr * 2.0f, rr * 2.0f);
        g.DrawEllipse(&handlePen, rx - rr, ry - rr, rr * 2.0f, rr * 2.0f);
        Pen arcPen(Color(255, 36, 133, 245), 1.45f);
        arcPen.SetStartCap(LineCapRound); arcPen.SetEndCap(LineCapRound);
        g.DrawArc(&arcPen, rx - 4.2f, ry - 4.2f, 8.4f, 8.4f, -35.0f, 275.0f);
        PointF arrowPts[3] = {
            PointF(rx + 2.0f, ry - 5.2f),
            PointF(rx + 4.4f, ry - 2.3f),
            PointF(rx + 1.0f, ry - 1.9f)
        };
        g.DrawLines(&arcPen, arrowPts, 3);

        // Compact bottom readout pill: "73%" or "73% · 25°" or "73% · ⇄"
        wchar_t buf[48] = {};
        int degInt = (int)std::lround(rotationDeg);
        if (degInt == -180) degInt = 180;
        if (degInt != 0 && flipHorizontal) {
            swprintf_s(buf, L"%.0f%% \u00B7 %d\u00B0 \u00B7 \u21C4", scale * 100.0f, degInt);
        } else if (degInt != 0) {
            swprintf_s(buf, L"%.0f%% \u00B7 %d\u00B0", scale * 100.0f, degInt);
        } else if (flipHorizontal) {
            swprintf_s(buf, L"%.0f%% \u00B7 \u21C4", scale * 100.0f);
        } else {
            swprintf_s(buf, L"%.0f%%", scale * 100.0f);
        }
        FontFamily ff(L"Segoe UI");
        Font spFont(&ff, 9.5f, FontStyleBold, UnitPixel);
        StringFormat sf;
        sf.SetAlignment(StringAlignmentCenter);
        sf.SetLineAlignment(StringAlignmentCenter);
        RectF meas;
        g.MeasureString(buf, -1, &spFont, PointF(0, 0), &meas);
        float pillW = std::max(44.0f, meas.Width + 14.0f);
        float pillX = 180.0f - pillW * 0.5f;
        GraphicsPath sp;
        addRoundedRect(sp, pillX, 290.0f, pillW, 16.0f, 6.0f);
        SolidBrush spBg(Color(210, 30, 33, 41));
        g.FillPath(&spBg, &sp);
        g.DrawString(buf, -1, &spFont, RectF(pillX, 290.0f, pillW, 16.0f), &sf, &whiteBrush);
    }

private:
    static bool& whiteOutlineEnabled() {
        static thread_local bool enabled = true;
        return enabled;
    }
    static Gdiplus::Color catBlack(BYTE a = 255)      { return Gdiplus::Color(a, 22, 22, 24); }
    static constexpr float BlackOutlineW = 1.8f;
    static Gdiplus::Color blackOutline(BYTE a = 245)  { return Gdiplus::Color(a, 255, 255, 255); }
    static Gdiplus::Color rgb(unsigned int hex, BYTE a = 255) { return Gdiplus::Color(a, (hex >> 16) & 255, (hex >> 8) & 255, hex & 255); }

    static bool isBuiltInCoat(const SkinSpec& skin, const char* builtinId) { return skin.builtIn && skin.id == builtinId; }
    static bool isClassicBlack(const SkinSpec& skin) { return isBuiltInCoat(skin, "builtin:0"); }
    static bool isSiamese(const SkinSpec& skin)      { return isBuiltInCoat(skin, "builtin:1"); }
    static bool isShorthair(const SkinSpec& skin)    { return isBuiltInCoat(skin, "builtin:2"); }
    static bool isOrangeWhite(const SkinSpec& skin)  { return isBuiltInCoat(skin, "builtin:3"); }
    static bool isDazed(const SkinSpec& skin)        { return skin.renderStyle == SkinRenderStyle::Dazed || isBuiltInCoat(skin, "builtin:4"); }
    static bool isTabby(const SkinSpec& skin)        { return isBuiltInCoat(skin, "builtin:5"); }
    static bool isPatternedBuiltIn(const SkinSpec& skin) { return isShorthair(skin) || isOrangeWhite(skin); }
    static bool isClassicBlackRim(const SkinSpec& skin) {
        return skin.id == "builtin:0" || (!skin.colorpoint() && !skin.palette.outline.set && !skin.idleLegsTinted && skin.marks.empty() && skin.regions.empty() && skin.palette.body.luminance() < 0.12);
    }
    static bool isMilkMark(const SkinMark& mark) {
        return std::fabs(mark.color.r - 242.0 / 255.0) < 0.01 &&
               std::fabs(mark.color.g - 238.0 / 255.0) < 0.01 &&
               std::fabs(mark.color.b - 228.0 / 255.0) < 0.01;
    }

    // Base skeleton per SkinBuild; SkinShape multipliers are applied on top (all exact no-ops at 1).
    struct Build {
        float headLift;
        float cheekHalfW, crownCtrlW, crownBaseY, cheekY, cheekCtrlTopY, neckPinchX, neckCtrlY;
        float hipHalfW, waistCtrlW, waistCtrlY, botOuterW, botInnerW, botHalfW;
        float earFold, earLen, earInX, earInY, earOutX, earOutY, earTipX, earTipY, earTipSpread;
        float tailWidth;
        float hindLeftX, hindW, hindRightX, hindLeftY, hindLeftH, hindStaggerY, hindStaggerH;
        float idleTopDY, idleTopX, idleBotX, shoulderX, limbStartW, limbEndW;
        bool sleekEyes;
    };
    static const Build& buildOf(const SkinSpec& skin) {
        static const Build standard = { 0.0f,
            42.5f, 26.0f, -30.0f, 5.0f, -14.0f, 2.5f, 24.0f,
            49.0f, 51.5f, -48.0f, 47.0f, 36.0f, 24.0f,
            0.06f, 32.0f, 9.0f, -16.0f, 35.0f, -5.0f, 24.5f, -20.0f, 3.8f,
            11.0f,
            -35.0f, 17.0f, 18.0f, 3.0f, 11.0f, 4.5f, 12.5f,
            30.0f, 18.0f, 16.0f, 20.0f, 19.0f, 13.5f,
            false };
        static const Build sleek = { -3.0f,
            42.5f, 25.0f, -29.5f, 6.5f, -13.0f, 6.5f, 27.5f,
            44.5f, 41.0f, -50.0f, 42.0f, 32.0f, 22.0f,
            0.14f, 29.5f, 10.0f, -16.5f, 35.5f, -4.5f, 25.0f, -18.5f, 4.2f,
            9.5f,
            -31.0f, 15.5f, 15.5f, 3.5f, 12.0f, 4.5f, 12.5f,
            31.0f, 16.5f, 15.0f, 18.5f, 17.0f, 12.5f,
            true };
        return skin.shape.build == SkinBuild::Sleek ? sleek : standard;
    }

    // Scale v around c by k; returns v untouched when k == 1 so default shapes stay bit-identical.
    static float around(float v, float c, float k) { return k == 1.0f ? v : c + (v - c) * k; }

    static BYTE byteOf(double v) { return (BYTE)std::lround(std::clamp(v, 0.0, 1.0) * 255.0); }
    static Gdiplus::Color col(const SkinColor& c) { return Gdiplus::Color(byteOf(c.a), byteOf(c.r), byteOf(c.g), byteOf(c.b)); }
    static Gdiplus::Color withAlpha(const SkinColor& c, BYTE a) { return Gdiplus::Color(a, byteOf(c.r), byteOf(c.g), byteOf(c.b)); }
    // Legacy crease strokes ask for an absolute alpha `a`: opaque-ish creases (like the black cat's mint,
    // alpha >= 0.75) use it as-is, translucent ones scale it by their own alpha (the patterned coats' 0.60)
    // — exactly what the pre-SkinSpec creaseColor(coat, a) produced.
    static Gdiplus::Color creaseWith(const SkinColor& c, BYTE a) { return withAlpha(c, c.a >= 0.75 ? a : (BYTE)(a * (float)c.a)); }

    // Head-local point -> canvas, on the skin's head surface (dome / plane) or flat skull space.
    static Gdiplus::PointF headPoint(SkinPoint p, bool skull, const SkinSpec& skin, Pt head, const CatPhysics& physics, bool whiteSurface = false) {
        float radius = std::max(0.0f, 1.0f - (p.x * p.x) / (46.0f * 46.0f) - (p.y * p.y) / (40.0f * 40.0f));
        float surface = whiteSurface ? (radius * radius * (3.0f - 2.0f * radius)) : std::sqrt(radius);
        float depth = skin.headSurface == SkinHeadSurface::Dome ? 29.6f * surface : 27.5f;
        Pt q = skull ? Pt{p.x,p.y} : projectHead3D(p.x,p.y,depth,physics.headYaw.value*0.50f,physics.headPitch.value*0.36f);
        float hs = skin.shape.headScale;
        q.x *= hs; q.y *= hs;
        float c = std::cos(physics.headTilt.value), s = std::sin(physics.headTilt.value);
        return {head.x + q.x*c - q.y*s, head.y + q.x*s + q.y*c};
    }
    static Gdiplus::PointF bodyPoint(SkinPoint p, const SkinSpec& skin, float seatX, float seatY, const CatPhysics& physics) {
        float bw = skin.shape.bodyWidth;
        float lie = std::clamp(physics.lieIntensity.value, 0.0f, 1.0f);
        float lieS = lie * lie * (3.0f - 2.0f * lie);
        float sy = physics.bodySquash.value * (1.0f - lieS * 0.42f);
        float sx = (1.0f + (1.0f - physics.bodySquash.value) * 0.55f) * (1.0f + lieS * 0.03f);
        float c = std::cos(physics.bodyTilt.value), s = std::sin(physics.bodyTilt.value);
        return {seatX+p.x*bw*sx*c-p.y*sy*s, seatY+p.x*bw*sx*s+p.y*sy*c};
    }
    static Gdiplus::PointF coatMarkPoint(CoatPoint p, bool headSurface, bool skull, CatCoatTheme coat, float seatX, float seatY, Pt head, const CatPhysics& physics, bool whiteSurface = false) {
        if (headSurface) {
            float radius = std::max(0.0f, 1.0f - p.x*p.x/(46.0f*46.0f) - p.y*p.y/(40.0f*40.0f));
            float surface = whiteSurface ? radius*radius*(3.0f - 2.0f*radius) : std::sqrt(radius);
            float depth = coat == CatCoatTheme::OrangeWhite ? 29.6f*surface : 27.5f;
            Pt q = skull ? Pt{p.x,p.y} : projectHead3D(p.x,p.y,depth,physics.headYaw.value*0.50f,physics.headPitch.value*0.36f);
            float c = std::cos(physics.headTilt.value), s = std::sin(physics.headTilt.value);
            return {head.x + q.x*c - q.y*s, head.y + q.x*s + q.y*c};
        }
        float lie = std::clamp(physics.lieIntensity.value, 0.0f, 1.0f);
        float lieS = lie * lie * (3.0f - 2.0f * lie);
        float sy = physics.bodySquash.value * (1.0f - lieS * 0.42f);
        float sx = (1.0f + (1.0f - physics.bodySquash.value) * 0.55f) * (1.0f + lieS * 0.03f);
        float c = std::cos(physics.bodyTilt.value), s = std::sin(physics.bodyTilt.value);
        return {seatX+p.x*sx*c-p.y*sy*s, seatY+p.x*sx*s+p.y*sy*c};
    }
    static void drawCoatMarks(Gdiplus::Graphics& g, float seatX, float seatY, Pt head, const CatPhysics& physics, CatCoatTheme coat) {
        using namespace Gdiplus;
        const auto& marks = coat == CatCoatTheme::Shorthair ? shorthairMarks() : orangeWhiteMarks();
        const CoatMark* bib = nullptr;
        for (const auto& mark : marks) if (mark.head && !mark.skull && mark.rgb == 0xF2EEE4) {
            for (const auto& p : mark.points) if (std::abs(p.x) > 46) { bib = &mark; break; }
            if (bib) break;
        }
        float overlap = std::min(1.0f, std::abs(physics.headYaw.value) * std::max(0.0f, physics.headPitch.value));
        float coverage = overlap * overlap * (3.0f - 2.0f * overlap);
        for (const auto& mark : marks) {
            if (mark.clipToBib && coverage == 0) continue;
            GraphicsState saved = g.Save();
            if (mark.clipToBib && bib) {
                std::vector<PointF> clipPoints;
                for (const auto& p : bib->points) clipPoints.push_back(coatMarkPoint(p, true, false, coat, seatX, seatY, head, physics, true));
                GraphicsPath clip; clip.AddPolygon(clipPoints.data(), (INT)clipPoints.size()); g.SetClip(&clip, CombineModeIntersect);
            }
            std::vector<PointF> points;
            for (auto p : mark.points) {
                if (mark.clipToBib) {
                    float rim = std::min(1.0f, std::max(0.0f, (p.y - 20.0f) / 6.0f));
                    p.x *= 1.0f - 0.5f * rim * (1.0f - coverage);
                    if (p.y > 20.0f) p.y = 20.0f + (p.y - 20.0f) * (0.75f + 0.25f * coverage);
                }
                points.push_back(coatMarkPoint(p, mark.head, mark.skull, coat, seatX, seatY, head, physics, mark.rgb == 0xF2EEE4));
            }
            GraphicsPath path;
            Color color = rgb(mark.rgb, (BYTE)(mark.alpha * 255));
            if (mark.width == 0) { path.AddPolygon(points.data(), (INT)points.size()); SolidBrush brush(color); g.FillPath(&brush, &path); }
            else { path.AddLines(points.data(), (INT)points.size()); Pen pen(color, mark.width); pen.SetStartCap(LineCapRound); pen.SetEndCap(LineCapRound); pen.SetLineJoin(LineJoinRound); g.DrawPath(&pen, &path); }
            g.Restore(saved);
        }
    }
    template <class Map>
    static std::vector<Gdiplus::PointF> mapPoints(const std::vector<SkinPoint>& pts, Map map) {
        std::vector<Gdiplus::PointF> out;
        out.reserve(pts.size());
        for (const SkinPoint& p : pts) out.push_back(map(p));
        return out;
    }
    // Strokes get round caps, except tail-space strokes (bands around the tail) which are cut flat.
    template <class Map>
    static void drawMark(Gdiplus::Graphics& g, const SkinMark& mark, Map map, bool roundCaps = true) {
        using namespace Gdiplus;
        std::vector<PointF> points = mapPoints(mark.points, map);
        GraphicsPath path;
        Color color = col(mark.color);
        if (!mark.stroke) { path.AddPolygon(points.data(), (INT)points.size()); SolidBrush brush(color); g.FillPath(&brush, &path); }
        else if (!roundCaps) {
            Pen pen(color, mark.width);
            if (points.size() == 2) g.DrawLine(&pen, points[0].X, points[0].Y, points[1].X, points[1].Y);
            else { pen.SetLineJoin(LineJoinRound); g.DrawLines(&pen, points.data(), (INT)points.size()); }
        }
        else { path.AddLines(points.data(), (INT)points.size()); Pen pen(color, mark.width); pen.SetStartCap(LineCapRound); pen.SetEndCap(LineCapRound); pen.SetLineJoin(LineJoinRound); g.DrawPath(&pen, &path); }
    }
    template <class Map>
    static void drawRegion(Gdiplus::Graphics& g, const SkinRegion& region, Map map) {
        using namespace Gdiplus;
        std::vector<PointF> points = mapPoints(region.flat, map);
        SolidBrush brush(col(region.fill));
        g.FillPolygon(&brush, points.data(), (INT)points.size(), FillModeWinding);
    }
    // The head (above) or body (below) side of the jaw line, following the head like head marks do.
    static void jawSide(Gdiplus::GraphicsPath& path, bool headSide, const SkinSpec& skin, Pt head, const CatPhysics& physics) {
        std::vector<Gdiplus::PointF> pts = mapPoints(skinJawSide(headSide, skin.shape.cheekFullness),
            [&](SkinPoint p) { return headPoint(p, false, skin, head, physics); });
        path.AddPolygon(pts.data(), (INT)pts.size());
    }

    static Gdiplus::Color eyePrimary(EyeColorTheme t, BYTE a = 255) {
        switch (t) {
            case EyeColorTheme::NeonChartreuse: return Gdiplus::Color(a, 201, 242, 64);
            case EyeColorTheme::SiameseBlue:    return Gdiplus::Color(a, 176, 218, 242);
            case EyeColorTheme::WarmAmber:      return Gdiplus::Color(a, 250, 194, 56);
            case EyeColorTheme::IceCyan:        return Gdiplus::Color(a, 115, 235, 245);
            case EyeColorTheme::ReferenceHazel: return Gdiplus::Color(a, 218, 178, 87);
            case EyeColorTheme::OliveGold:      return Gdiplus::Color(a, 191, 179, 102);
            case EyeColorTheme::SoftAmber: return Gdiplus::Color(a, 217, 173, 85);
        }
        return Gdiplus::Color(a, 201, 242, 64);
    }

    static Gdiplus::Color eyeGlow(EyeColorTheme t) {
        switch (t) {
            case EyeColorTheme::NeonChartreuse: return Gdiplus::Color(217, 196, 242, 61);
            case EyeColorTheme::SiameseBlue:    return Gdiplus::Color(204, 173, 217, 242);
            case EyeColorTheme::WarmAmber:      return Gdiplus::Color(217, 250, 189, 51);
            case EyeColorTheme::IceCyan:        return Gdiplus::Color(217, 107, 230, 250);
            case EyeColorTheme::ReferenceHazel: return Gdiplus::Color(217, 218, 178, 87);
            case EyeColorTheme::OliveGold:      return Gdiplus::Color(217, 191, 179, 102);
            case EyeColorTheme::SoftAmber:      return Gdiplus::Color(217, 217, 173, 85);
        }
        return Gdiplus::Color(217, 196, 242, 61);
    }

    static Gdiplus::Color blendColor(Gdiplus::Color a, Gdiplus::Color b, float t) {
        t = std::clamp(t, 0.0f, 1.0f);
        auto lerp = [t](BYTE x, BYTE y) -> BYTE { return (BYTE)std::clamp((int)(x + (y - x) * t + 0.5f), 0, 255); };
        return Gdiplus::Color(lerp(a.GetA(), b.GetA()), lerp(a.GetR(), b.GetR()), lerp(a.GetG(), b.GetG()), lerp(a.GetB(), b.GetB()));
    }

    // Hue wheel helper for the keyboard marquee (one full hue cycle per sweep).
    static Gdiplus::Color hsvColor(float h, float s, float v, BYTE a = 255) {
        h = h - std::floor(h);
        float c = v * s;
        float x = c * (1.0f - std::fabs(std::fmod(h * 6.0f, 2.0f) - 1.0f));
        float m = v - c;
        float r = 0.0f, g = 0.0f, b = 0.0f;
        switch ((int)(h * 6.0f) % 6) {
            case 0: r = c; g = x; break;
            case 1: r = x; g = c; break;
            case 2: g = c; b = x; break;
            case 3: g = x; b = c; break;
            case 4: r = x; b = c; break;
            default: r = c; b = x; break;
        }
        return Gdiplus::Color(a, (BYTE)((r + m) * 255.0f), (BYTE)((g + m) * 255.0f), (BYTE)((b + m) * 255.0f));
    }

    static void addRoundedRect(Gdiplus::GraphicsPath& p, float x, float y, float w, float h, float r) {
        float d = std::min(r * 2.0f, std::min(w, h));
        if (d <= 0.5f) {
            p.AddRectangle(Gdiplus::RectF(x, y, w, h));
            return;
        }
        p.AddArc(x, y, d, d, 180.0f, 90.0f);
        p.AddArc(x + w - d, y, d, d, 270.0f, 90.0f);
        p.AddArc(x + w - d, y + h - d, d, d, 0.0f, 90.0f);
        p.AddArc(x, y + h - d, d, d, 90.0f, 90.0f);
        p.CloseFigure();
    }

    static void addQuadPoly(Gdiplus::GraphicsPath& p, Pt tl, Pt tr, Pt br, Pt bl) {
        Gdiplus::PointF pts[4] = { {tl.x, tl.y}, {tr.x, tr.y}, {br.x, br.y}, {bl.x, bl.y} };
        p.AddPolygon(pts, 4);
    }

    static void addQuadBezier(Gdiplus::GraphicsPath& p, Pt p0, Pt ctrl, Pt p2) {
        // Convert quadratic Bezier (p0, ctrl, p2) -> exact cubic Bezier for GDI+
        Gdiplus::PointF c1(p0.x + (2.0f / 3.0f) * (ctrl.x - p0.x), p0.y + (2.0f / 3.0f) * (ctrl.y - p0.y));
        Gdiplus::PointF c2(p2.x + (2.0f / 3.0f) * (ctrl.x - p2.x), p2.y + (2.0f / 3.0f) * (ctrl.y - p2.y));
        p.AddBezier(Gdiplus::PointF(p0.x, p0.y), c1, c2, Gdiplus::PointF(p2.x, p2.y));
    }

    static Pt projectHead3D(float x, float y, float z, float yawRad, float pitchRad) {
        float cy = std::cos(yawRad), sy = std::sin(yawRad);
        float x1 = x * cy + z * sy;
        float z1 = -x * sy + z * cy;
        float cp = std::cos(pitchRad), sp = std::sin(pitchRad);
        float y2 = y * cp + z1 * sp;
        return { x1, y2 };
    }

    static Pt quadPoint(Pt p0, Pt p1, Pt p2, float t) {
        float mt = 1.0f - t;
        return { mt * mt * p0.x + 2.0f * mt * t * p1.x + t * t * p2.x,
                 mt * mt * p0.y + 2.0f * mt * t * p1.y + t * t * p2.y };
    }

    static Pt quadTangent(Pt p0, Pt p1, Pt p2, float t) {
        float mt = 1.0f - t;
        return { 2.0f * mt * (p1.x - p0.x) + 2.0f * t * (p2.x - p1.x),
                 2.0f * mt * (p1.y - p0.y) + 2.0f * t * (p2.y - p1.y) };
    }

    // MARK: - Mini White Mouse (180° facing the cat)

    static void drawMouse(Gdiplus::Graphics& g, const CatPhysics& physics, const KeyboardSkinSpec& kbSkin) {
        using namespace Gdiplus;
        Pt center = { CatPhysics::MouseBaseCenter.x + physics.mouseOffset.point().x,
                      CatPhysics::MouseBaseCenter.y + physics.mouseOffset.point().y };
        float pressShift = std::max(physics.mousePressLeft.value, physics.mousePressRight.value) * 1.6f;

        GraphicsState st = g.Save();
        g.TranslateTransform(center.x, center.y + pressShift);
        g.RotateTransform(0.22f * RadToDeg);

        SolidBrush shadowBrush(Color(60, 0, 0, 0));
        g.FillEllipse(&shadowBrush, -13.5f, -9.5f, 27.0f, 31.0f);

        Color bodyCol = col(kbSkin.mouseBody);
        Color borderCol = col(kbSkin.mouseBorder);
        Color wheelCol = col(kbSkin.wheel);

        SolidBrush bodyBrush(bodyCol);
        g.FillEllipse(&bodyBrush, -13.5f, -16.5f, 27.0f, 33.0f);

        if (physics.mousePressLeft.value > 0.05f || physics.mousePressRight.value > 0.05f) {
            GraphicsPath clipPath;
            clipPath.AddEllipse(-13.5f, -16.5f, 27.0f, 33.0f);
            GraphicsState cs = g.Save();
            g.SetClip(&clipPath);
            if (physics.mousePressLeft.value > 0.05f) {
                SolidBrush hb(Color((BYTE)(96 * physics.mousePressLeft.value), 201, 242, 64));
                g.FillRectangle(&hb, 0.0f, 0.0f, 14.0f, 17.0f);
            }
            if (physics.mousePressRight.value > 0.05f) {
                SolidBrush hb(Color((BYTE)(96 * physics.mousePressRight.value), 201, 242, 64));
                g.FillRectangle(&hb, -14.0f, 0.0f, 14.0f, 17.0f);
            }
            g.Restore(cs);
        }

        // Front button split seam pointing away from cat (bottom)
        Pen seamPen(Color(82, borderCol.GetR(), borderCol.GetG(), borderCol.GetB()), 1.05f);
        g.DrawLine(&seamPen, 0.0f, 16.0f, 0.0f, 1.5f);

        // Amber scroll wheel on front (bottom) half
        GraphicsPath wheelPath;
        addRoundedRect(wheelPath, -1.9f, 2.5f, 3.8f, 8.5f, 1.9f);
        SolidBrush wheelBrush(wheelCol);
        g.FillPath(&wheelBrush, &wheelPath);

        Pen borderPen(borderCol, 1.7f);
        g.DrawEllipse(&borderPen, -13.5f, -16.5f, 27.0f, 33.0f);
        g.Restore(st);
    }

    // MARK: - Mini 2.5D Graphics Tablet & Stylus

    static void drawTablet(Gdiplus::Graphics& g, const CatPhysics& physics, KeyboardTheme theme, EyeColorTheme eyeTheme) {
        using namespace Gdiplus;
        Pt tl = CatPhysics::tabletQuadPoint(0.0f, 0.0f);
        Pt tr = CatPhysics::tabletQuadPoint(1.0f, 0.0f);
        Pt bl = CatPhysics::tabletQuadPoint(0.0f, 1.0f);
        Pt br = CatPhysics::tabletQuadPoint(1.0f, 1.0f);
        constexpr float depth = 3.6f;

        Color baseCol, bodyCol, padCol, keyCol, accentCol;
        if (theme == KeyboardTheme::MidnightHacker) {
            baseCol = Color(255, 13, 13, 18); bodyCol = Color(255, 28, 31, 38);
            padCol = Color(255, 41, 43, 54); keyCol = Color(255, 61, 64, 77); accentCol = Color(255, 199, 242, 64);
        } else if (theme == KeyboardTheme::RetroCream) {
            baseCol = Color(255, 56, 54, 48); bodyCol = Color(255, 84, 79, 71);
            padCol = Color(255, 107, 99, 89); keyCol = Color(255, 138, 128, 115); accentCol = Color(255, 224, 107, 61);
        } else {
            baseCol = Color(255, 26, 26, 31); bodyCol = Color(255, 43, 46, 54);
            padCol = Color(255, 59, 61, 71); keyCol = Color(255, 77, 82, 94); accentCol = Color(255, 245, 176, 41);
        }

        // Drop shadow
        {
            GraphicsPath sp;
            addQuadPoly(sp, {tl.x, tl.y + depth + 2.0f}, {tr.x, tr.y + depth + 2.0f},
                            {br.x, br.y + depth + 2.6f}, {bl.x, bl.y + depth + 2.6f});
            SolidBrush sb(Color(56, 0, 0, 0));
            Pen spen(Color(56, 0, 0, 0), 3.0f); spen.SetLineJoin(LineJoinRound);
            g.FillPath(&sb, &sp); g.DrawPath(&spen, &sp);
        }
        // Lower 3D slab
        {
            GraphicsPath lp;
            addQuadPoly(lp, {tl.x, tl.y + depth}, {tr.x, tr.y + depth}, {br.x, br.y + depth}, {bl.x, bl.y + depth});
            SolidBrush bb(baseCol);
            Pen bp(baseCol, 2.5f); bp.SetLineJoin(LineJoinRound);
            g.FillPath(&bb, &lp); g.DrawPath(&bp, &lp);
        }
        // Top body
        GraphicsPath topPath;
        addQuadPoly(topPath, tl, tr, br, bl);
        {
            SolidBrush tb(bodyCol);
            Pen tp(bodyCol, 2.0f); tp.SetLineJoin(LineJoinRound);
            g.FillPath(&tb, &topPath); g.DrawPath(&tp, &topPath);
            Pen rim(Color(36, 255, 255, 255), 0.9f); rim.SetLineJoin(LineJoinRound);
            g.DrawPath(&rim, &topPath);
        }
        // Recessed active drawing pad
        Pt pTL = CatPhysics::tabletQuadPoint(0.21f, 0.11f);
        Pt pTR = CatPhysics::tabletQuadPoint(0.94f, 0.11f);
        Pt pBR = CatPhysics::tabletQuadPoint(0.94f, 0.89f);
        Pt pBL = CatPhysics::tabletQuadPoint(0.21f, 0.89f);
        GraphicsPath padPath;
        addQuadPoly(padPath, pTL, pTR, pBR, pBL);
        {
            SolidBrush pb(padCol);
            g.FillPath(&pb, &padPath);
        }
        // Corner L-brackets
        {
            Pen cp(Color(88, 255, 255, 255), 0.95f);
            cp.SetStartCap(LineCapRound); cp.SetEndCap(LineCapRound);
            const float corners[4][4] = {
                {0.24f, 0.15f,  0.07f,  0.11f},
                {0.91f, 0.15f, -0.07f,  0.11f},
                {0.24f, 0.85f,  0.07f, -0.11f},
                {0.91f, 0.85f, -0.07f, -0.11f}
            };
            for (const auto& c : corners) {
                Pt pt = CatPhysics::tabletQuadPoint(c[0], c[1]);
                Pt ph = CatPhysics::tabletQuadPoint(c[0] + c[2], c[1]);
                Pt pv = CatPhysics::tabletQuadPoint(c[0], c[1] + c[3]);
                g.DrawLine(&cp, ph.x, ph.y, pt.x, pt.y);
                g.DrawLine(&cp, pt.x, pt.y, pv.x, pv.y);
            }
        }
        // Status LED + 4 ExpressKeys
        Color eyeCol = eyePrimary(eyeTheme);
        Color ledCol = physics.tabletPenPress.value > 0.15f ? eyeCol : accentCol;
        Pt ledPt = CatPhysics::tabletQuadPoint(0.105f, 0.14f);
        {
            SolidBrush glow(Color(95, ledCol.GetR(), ledCol.GetG(), ledCol.GetB()));
            g.FillEllipse(&glow, ledPt.x - 3.6f, ledPt.y - 3.6f, 7.2f, 7.2f);
            SolidBrush lb(ledCol);
            g.FillEllipse(&lb, ledPt.x - 1.35f, ledPt.y - 1.35f, 2.7f, 2.7f);
        }
        {
            SolidBrush kb(keyCol);
            for (float kv : { 0.28f, 0.44f, 0.60f, 0.76f }) {
                GraphicsPath kp;
                addQuadPoly(kp,
                    CatPhysics::tabletQuadPoint(0.06f, kv - 0.05f),
                    CatPhysics::tabletQuadPoint(0.15f, kv - 0.05f),
                    CatPhysics::tabletQuadPoint(0.15f, kv + 0.05f),
                    CatPhysics::tabletQuadPoint(0.06f, kv + 0.05f));
                g.FillPath(&kb, &kp);
            }
        }
        // Live fading ink trail
        if (physics.tabletTrail.size() >= 2) {
            GraphicsState cs = g.Save();
            g.SetClip(&padPath, CombineModeIntersect);
            for (size_t i = 1; i < physics.tabletTrail.size(); ++i) {
                const auto& a = physics.tabletTrail[i - 1];
                const auto& b = physics.tabletTrail[i];
                if (std::hypot(b.point.x - a.point.x, b.point.y - a.point.y) > 22.0f) continue;
                float life = std::max(0.0f, 1.0f - b.age / 0.72f);
                if (life <= 0.01f) continue;
                Pen ink(Color((BYTE)(life * 224.0f), eyeCol.GetR(), eyeCol.GetG(), eyeCol.GetB()), 1.2f + life * 1.4f);
                ink.SetStartCap(LineCapRound); ink.SetEndCap(LineCapRound);
                g.DrawLine(&ink, a.point.x, a.point.y, b.point.x, b.point.y);
            }
            g.Restore(cs);
        }
        // Nib contact glow
        if (physics.leftPawOnMouse && physics.tabletPenPress.value > 0.08f) {
            Pt nib = physics.tabletNib.point();
            float r = 7.0f + physics.tabletPenPress.value * 3.5f;
            GraphicsPath gp;
            gp.AddEllipse(nib.x - r, nib.y - r, r * 2.0f, r * 2.0f);
            PathGradientBrush pgb(&gp);
            pgb.SetCenterColor(Color((BYTE)(115 * physics.tabletPenPress.value), eyeCol.GetR(), eyeCol.GetG(), eyeCol.GetB()));
            Color surr[1] = { Color(0, eyeCol.GetR(), eyeCol.GetG(), eyeCol.GetB()) };
            INT cnt = 1; pgb.SetSurroundColors(surr, &cnt);
            g.FillPath(&pgb, &gp);
        }
    }

    static void drawStylusBody(Gdiplus::Graphics& g, float len, KeyboardTheme theme, EyeColorTheme eyeTheme, float pressed) {
        using namespace Gdiplus;
        Color barrelCol, gripCol, ringCol;
        if (theme == KeyboardTheme::MidnightHacker) {
            barrelCol = Color(255, 33, 36, 43); gripCol = Color(255, 56, 61, 74); ringCol = Color(255, 199, 242, 64);
        } else if (theme == KeyboardTheme::RetroCream) {
            barrelCol = Color(255, 71, 66, 61); gripCol = Color(255, 107, 99, 89); ringCol = Color(255, 224, 107, 61);
        } else {
            barrelCol = Color(255, 46, 48, 59); gripCol = Color(255, 71, 77, 89); ringCol = Color(255, 245, 176, 41);
        }
        GraphicsPath penPath;
        penPath.AddLine(0.0f, 0.0f, 7.5f, -2.4f);
        penPath.AddLine(7.5f, -2.4f, len - 3.0f, -2.6f);
        addQuadBezier(penPath, { len - 3.0f, -2.6f }, { len, -2.4f }, { len, 0.0f });
        addQuadBezier(penPath, { len, 0.0f }, { len, 2.4f }, { len - 3.0f, 2.6f });
        penPath.AddLine(len - 3.0f, 2.6f, 7.5f, 2.4f);
        penPath.CloseFigure();

        Pen halo(Color(204, 245, 245, 245), 1.6f);
        halo.SetLineJoin(LineJoinRound);
        g.DrawPath(&halo, &penPath);
        SolidBrush bb(barrelCol);
        g.FillPath(&bb, &penPath);

        GraphicsState cs = g.Save();
        g.SetClip(&penPath, CombineModeIntersect);
        SolidBrush gb(gripCol);
        g.FillRectangle(&gb, 7.5f, -3.0f, 11.5f, 6.0f);
        SolidBrush rb(ringCol);
        g.FillRectangle(&rb, 19.0f, -3.0f, 2.4f, 6.0f);
        Color nibCol = pressed > 0.15f ? eyePrimary(eyeTheme) : Color(255, 240, 240, 240);
        SolidBrush nb(nibCol);
        g.FillRectangle(&nb, -0.5f, -1.5f, 3.4f, 3.0f);
        SolidBrush sh(Color(60, 255, 255, 255));
        g.FillRectangle(&sh, 8.0f, -1.9f, std::max(1.0f, len - 12.0f), 1.1f);
        g.Restore(cs);

        GraphicsPath btn;
        addRoundedRect(btn, 11.0f, -3.1f, 6.0f, 1.4f, 0.7f);
        SolidBrush btnB(Color(230, 199, 199, 199));
        g.FillPath(&btnB, &btn);
    }

    static void drawParkedStylus(Gdiplus::Graphics& g, KeyboardTheme theme, EyeColorTheme eyeTheme) {
        using namespace Gdiplus;
        Pt nib = CatPhysics::tabletQuadPoint(0.88f, -0.02f);
        Pt tail = CatPhysics::tabletQuadPoint(0.18f, -0.02f);
        float ang = std::atan2(tail.y - nib.y, tail.x - nib.x) * RadToDeg;
        float len = std::hypot(tail.x - nib.x, tail.y - nib.y);

        GraphicsState st = g.Save();
        g.TranslateTransform(nib.x, nib.y + 2.2f);
        g.RotateTransform(ang);
        SolidBrush sb(Color(56, 0, 0, 0));
        g.FillRectangle(&sb, 2.0f, -2.0f, len - 4.0f, 4.5f);
        g.Restore(st);

        st = g.Save();
        g.TranslateTransform(nib.x, nib.y);
        g.RotateTransform(ang);
        drawStylusBody(g, len, theme, eyeTheme, 0.0f);
        g.Restore(st);
    }

    static void drawHeldStylus(Gdiplus::Graphics& g, const CatPhysics& physics, KeyboardTheme theme, EyeColorTheme eyeTheme) {
        using namespace Gdiplus;
        Pt lPos = physics.leftPaw.point();
        float press = std::clamp(physics.tabletPenPress.value, 0.0f, 1.0f);
        Pt nib = { lPos.x - 5.5f, lPos.y + 7.0f + press * 1.4f };
        float angleDeg = (-2.18f + physics.tabletPenTilt.value) * RadToDeg;

        GraphicsState st = g.Save();
        g.TranslateTransform(nib.x, nib.y);
        g.RotateTransform(angleDeg);
        drawStylusBody(g, 35.0f, theme, eyeTheme, press);
        g.Restore(st);
    }

    // MARK: - Mini 65% Mechanical Keyboard (180° facing the cat)

    static std::wstring keycapLegend(PhysicalKey k) {
        switch (k) {
            case PhysicalKey::Escape: return L"ESC";
            case PhysicalKey::Tab: return L"\u21E5";
            case PhysicalKey::CapsLock: return L"\u21EA";
            case PhysicalKey::LeftShift:
            case PhysicalKey::RightShift: return L"\u21E7";
            case PhysicalKey::LeftControl:
            case PhysicalKey::RightControl: return L"Ctrl";
            case PhysicalKey::LeftOption:
            case PhysicalKey::RightOption: return L"Alt";
            case PhysicalKey::LeftCommand:
            case PhysicalKey::RightCommand: return L"Win";
            case PhysicalKey::Backspace: return L"\u232B";
            case PhysicalKey::Enter: return L"\u21B5";
            case PhysicalKey::Space: return L"";
            default: return keyBadgeLabel(k);
        }
    }

    static void drawKeyboard(Gdiplus::Graphics& g, const CatPhysics& physics, const KeyboardSkinSpec& kbSkin, EyeColorTheme eyeTheme, bool showLegends, bool marquee) {
        using namespace Gdiplus;
        Pt tl = KeyboardLayout::screenQuadPoint(-0.012f, -0.04f);
        Pt tr = KeyboardLayout::screenQuadPoint(1.012f, -0.04f);
        Pt bl = KeyboardLayout::screenQuadPoint(-0.016f, 1.04f);
        Pt br = KeyboardLayout::screenQuadPoint(1.016f, 1.04f);
        constexpr float depth = 4.5f;

        // Shadow
        {
            GraphicsPath sp;
            addQuadPoly(sp, {tl.x, tl.y + depth + 2}, {tr.x, tr.y + depth + 2},
                            {br.x, br.y + depth + 3}, {bl.x, bl.y + depth + 3});
            SolidBrush sb(Color(56, 0, 0, 0));
            g.FillPath(&sb, &sp);
        }

        Color baseCol = col(kbSkin.base);
        Color deckCol = col(kbSkin.deck);
        Color keyCol = col(kbSkin.key);
        Color borderCol = col(kbSkin.keyBorder);
        Color accentCol = col(kbSkin.accent);

        {
            GraphicsPath lp;
            addQuadPoly(lp, {tl.x, tl.y + depth}, {tr.x, tr.y + depth}, {br.x, br.y + depth}, {bl.x, bl.y + depth});
            SolidBrush bb(baseCol);
            Pen bp(baseCol, 2.5f); bp.SetLineJoin(LineJoinRound);
            g.FillPath(&bb, &lp);
            g.DrawPath(&bp, &lp);
        }
        GraphicsPath deckPath;
        addQuadPoly(deckPath, tl, tr, br, bl);
        {
            SolidBrush db(deckCol);
            Pen dp(deckCol, 2.0f); dp.SetLineJoin(LineJoinRound);
            g.FillPath(&db, &deckPath);
            g.DrawPath(&dp, &deckPath);
        }

        // MARK: - Marquee backlight
        // A comet of light sweeps diagonally under the keycaps: bright head, long fading tail.
        Color glowCol = eyePrimary(eyeTheme, 215);
        float mqHead = physics.marqueePhase - std::floor(physics.marqueePhase);
        // One full hue cycle per sweep, so the deck reads as RGB backlight rather than paint.
        Color mqCol = hsvColor(mqHead + 0.52f, 0.55f, 1.0f);
        auto mqWave = [mqHead, marquee](float t) {
            if (!marquee) return 0.0f;
            float d = mqHead - t;
            if (d < 0.0f) d += 1.0f;
            return std::exp(-d / 0.125f);
        };
        float bandDx = br.x - tl.x, bandDy = br.y - tl.y;
        float bandLen2 = bandDx * bandDx + bandDy * bandDy;
        if (marquee) {
            GraphicsState mqState = g.Save();
            g.SetClip(&deckPath);
            const int kN = 24;
            Color mqColors[kN];
            REAL mqPos[kN];
            for (int i = 0; i < kN; ++i) {
                float t = (float)i / (float)(kN - 1);
                mqPos[i] = t;
                mqColors[i] = Color((BYTE)std::clamp(mqWave(t) * 200.0f, 0.0f, 255.0f),
                                    mqCol.GetR(), mqCol.GetG(), mqCol.GetB());
            }
            LinearGradientBrush band(PointF(tl.x, tl.y), PointF(br.x, br.y), Color(0, 0, 0, 0), Color(0, 0, 0, 0));
            band.SetInterpolationColors(mqColors, mqPos, kN);
            g.FillPath(&band, &deckPath);

            // White-hot lamp at the head of the comet, clipped to the deck.
            Pt head = { tl.x + bandDx * mqHead, tl.y + bandDy * mqHead };
            float hr = 44.0f;
            GraphicsPath hp;
            hp.AddEllipse(head.x - hr, head.y - hr, hr * 2.0f, hr * 2.0f);
            PathGradientBrush hb(&hp);
            hb.SetCenterPoint(PointF(head.x, head.y));
            hb.SetCenterColor(Color(150, 240, 252, 255));
            Color hSurr[1] = { Color(0, mqCol.GetR(), mqCol.GetG(), mqCol.GetB()) };
            INT hCnt = 1;
            hb.SetSurroundColors(hSurr, &hCnt);
            g.FillPath(&hb, &hp);
            g.Restore(mqState);
        }

        constexpr float padU = 0.0028f;
        constexpr float padV = 0.014f;
        Pen keyBorderPen(borderCol, 0.65f);
        FontFamily kbFF(L"Segoe UI");
        StringFormat kbSF;
        kbSF.SetAlignment(StringAlignmentCenter);
        kbSF.SetLineAlignment(StringAlignmentCenter);

        for (const auto& cap : KeyboardLayout::keycaps()) {
            float glow = 0.0f;
            auto it = physics.keyGlow.find(cap.key);
            if (it != physics.keyGlow.end()) glow = it->second;

            // 180° rotated to face the cat
            float su0 = (1.0f - (cap.xUnits + cap.widthUnits)) + padU;
            float su1 = (1.0f - cap.xUnits) - padU;
            float sv0 = (1.0f - (cap.row + 1) / 5.0f) + padV;
            float sv1 = (1.0f - cap.row / 5.0f) - padV;

            float dy = glow * 1.9f;
            Pt kTL = KeyboardLayout::screenQuadPoint(su0, sv0); kTL.y += dy;
            Pt kTR = KeyboardLayout::screenQuadPoint(su1, sv0); kTR.y += dy;
            Pt kBR = KeyboardLayout::screenQuadPoint(su1, sv1); kBR.y += dy;
            Pt kBL = KeyboardLayout::screenQuadPoint(su0, sv1); kBL.y += dy;

            // Where this keycap sits along the marquee axis, and how bright the comet makes it.
            float kcx = (kTL.x + kTR.x + kBR.x + kBL.x) * 0.25f;
            float kcy = (kTL.y + kTR.y + kBR.y + kBL.y) * 0.25f;
            float kt = std::clamp(((kcx - tl.x) * bandDx + (kcy - tl.y) * bandDy) / bandLen2, 0.0f, 1.0f);
            float mq = mqWave(kt);

            GraphicsPath kp;
            addQuadPoly(kp, kTL, kTR, kBR, kBL);
            Color fill = cap.isAmberAccent ? accentCol : keyCol;
            if (mq > 0.015f) {
                // Head of the comet reads hot (near white), the trailing keys stay saturated.
                Color lit = blendColor(mqCol, Color(255, 255, 255, 255), mq * mq * 0.5f);
                fill = blendColor(fill, lit, std::clamp(mq * 0.88f, 0.0f, 0.9f));
            }
            if (glow > 0.02f) fill = blendColor(fill, glowCol, glow * 0.55f);

            SolidBrush kb(fill);
            g.FillPath(&kb, &kp);
            if (mq > 0.10f) {
                Pen litPen(Color((BYTE)std::clamp(mq * 215.0f, 0.0f, 215.0f),
                                 mqCol.GetR(), mqCol.GetG(), mqCol.GetB()), 1.0f);
                g.DrawPath(&litPen, &kp);
            } else {
                g.DrawPath(&keyBorderPen, &kp);
            }

            // Under-key bloom where the beam is hottest, so the light spills between caps.
            if (mq > 0.45f) {
                float bloom = (mq - 0.45f) / 0.55f;
                float br2 = 15.0f;
                GraphicsPath bp;
                bp.AddEllipse(kcx - br2, kcy - br2 * 0.7f, br2 * 2.0f, br2 * 1.4f);
                PathGradientBrush pb(&bp);
                pb.SetCenterPoint(PointF(kcx, kcy));
                pb.SetCenterColor(Color((BYTE)std::clamp(bloom * 135.0f, 0.0f, 135.0f),
                                        mqCol.GetR(), mqCol.GetG(), mqCol.GetB()));
                Color bSurr[1] = { Color(0, mqCol.GetR(), mqCol.GetG(), mqCol.GetB()) };
                INT bCnt = 1;
                pb.SetSurroundColors(bSurr, &bCnt);
                g.FillPath(&pb, &bp);
            }

            if (showLegends) {
                bool isSpace = (cap.key == PhysicalKey::Space);
                std::wstring legend = isSpace ? std::wstring(L"space") : keycapLegend(cap.key);
                if (!legend.empty()) {
                    float cx = (kTL.x + kTR.x + kBR.x + kBL.x) * 0.25f;
                    float cy = (kTL.y + kTR.y + kBR.y + kBL.y) * 0.25f;
                    if (isSpace) {
                        // The spacebar sits right under the cat: its legs hide the middle, and an
                        // unlabeled visible end looked like an odd blank patch beside the cat.
                        // Label the end that stays visible instead.
                        Pt sp = KeyboardLayout::screenQuadPoint(su0 + (su1 - su0) * 0.82f, (sv0 + sv1) * 0.5f);
                        cx = sp.x;
                        cy = sp.y + dy;
                    }
                    Color txtCol;
                    if (cap.isAmberAccent) {
                        txtCol = kbSkin.accent.luminance() >= 0.45
                            ? Color(209, 36, 36, 41)
                            : Color(230, 245, 245, 250);
                    } else if (kbSkin.darkText) {
                        txtCol = Color(199, 36, 36, 41);
                    } else {
                        txtCol = Color(209, 224, 230, 235);
                    }
                    SolidBrush tb(txtCol);
                    float fSz = legend.size() <= 1 ? 5.2f : 3.9f;
                    Font kf(&kbFF, fSz, FontStyleBold, UnitPixel);
                    GraphicsState ks = g.Save();
                    g.TranslateTransform(cx, cy);
                    // The keyboard is laid out 180° to face the cat, so the legends must be too
                    // (upside-down to the viewer, upright from the cat's seat). +3° follows the deck slope.
                    g.RotateTransform(180.0f + 3.0f);
                    g.DrawString(legend.c_str(), -1, &kf, RectF(-14.0f, -7.0f, 28.0f, 14.0f), &kbSF, &tb);
                    g.Restore(ks);
                }
            }
        }

        // Radiant backlit glow halos over pressed keys
        for (const auto& kv : physics.keyGlow) {
            if (kv.second <= 0.05f) continue;
            Pt c = KeyboardLayout::canvasPointForKey(kv.first);
            float r = 17.0f + kv.second * 6.0f;
            GraphicsPath gp;
            gp.AddEllipse(c.x - r, c.y - r, r * 2.0f, r * 2.0f);
            PathGradientBrush pgb(&gp);
            pgb.SetCenterColor(Color((BYTE)(92 * kv.second), glowCol.GetR(), glowCol.GetG(), glowCol.GetB()));
            Color surr[1] = { Color(0, glowCol.GetR(), glowCol.GetG(), glowCol.GetB()) };
            INT cnt = 1;
            pgb.SetSurroundColors(surr, &cnt);
            g.FillPath(&pgb, &gp);
        }
    }

    // MARK: - Tail

    struct TailCurve {
        Gdiplus::PointF root, c1, c2, tip;
        float thickness;
        // Tail space: x = 0 (root) .. 100 (tip) along the curve, y = offset along the left-hand normal.
        Gdiplus::PointF at(SkinPoint p) const {
            float t = std::clamp(p.x / 100.0f, 0.0f, 1.0f);
            float u=1-t;
            float x=u*u*u*root.X+3*u*u*t*c1.X+3*u*t*t*c2.X+t*t*t*tip.X;
            float y=u*u*u*root.Y+3*u*u*t*c1.Y+3*u*t*t*c2.Y+t*t*t*tip.Y;
            float dx=3*u*u*(c1.X-root.X)+6*u*t*(c2.X-c1.X)+3*t*t*(tip.X-c2.X);
            float dy=3*u*u*(c1.Y-root.Y)+6*u*t*(c2.Y-c1.Y)+3*t*t*(tip.Y-c2.Y);
            float len=std::max(0.001f,std::hypot(dx,dy)),n=p.y*thickness;
            return Gdiplus::PointF(x+-dy/len*n,y+dx/len*n);
        }
    };
    static TailCurve tailCurve(float seatX, float seatY, const CatPhysics& physics, const SkinSpec& skin) {
        using namespace Gdiplus;
        float p = physics.tailPhase;
        float hunt = std::clamp(physics.huntIntensity.value, 0.0f, 1.0f);
        float agility = std::clamp(physics.tailAgility.value, 0.0f, 1.0f);
        float wag1 = std::sin(p) * (8.0f + hunt * 5.5f + agility * 4.0f);
        float wag2 = std::cos(p * 1.3f) * (6.0f + hunt * 4.5f + agility * 3.5f);
        float huntDrop = hunt * 14.0f;
        float bw = skin.shape.bodyWidth, tl = skin.shape.tailLength;
        float shift = bw == 1.0f ? 0.0f : 34.0f * bw - 34.0f; // tail root stays on the (wider/narrower) hip

        float reach = std::clamp(physics.tailTyping.value, 0.0f, 1.0f);
        float lie = std::clamp(physics.lieIntensity.value, 0.0f, 1.0f);
        float lieS = lie * lie * (3.0f - 2.0f * lie);
        float flickScale = (1.0f - reach) * (1.0f - lieS);
        Pt flick = physics.tailFlick.point();
        float fx = flick.x * flickScale;
        float fy = flick.y * flickScale;
        float curl = physics.tailCurl.value * flickScale;

        TailCurve c;
        c.root = PointF(seatX + 34.0f + shift, seatY - 6.0f);
        c.c1 = PointF(seatX + 64.0f + shift + fx * 0.25f, seatY + 2.0f + wag1 * 0.35f + huntDrop * 0.4f + fy * 0.22f + curl * 0.35f);
        c.c2 = PointF(seatX + 66.0f + wag2 * 0.4f + shift + fx * 0.65f - curl * 0.45f, seatY - 26.0f + wag1 * 0.7f + huntDrop + fy * 0.60f - curl * 0.55f);
        c.tip = PointF(seatX + 91.0f + wag2 * 0.5f + shift + fx, seatY - 30.0f + wag1 * 0.85f + huntDrop + fy);
        for (PointF* q : {&c.c1, &c.c2, &c.tip}) { q->X = around(q->X, c.root.X, tl); q->Y = around(q->Y, c.root.Y, tl); }

        Pt target = physics.tailTip.point();
        c.c1.X += 12.0f * reach;
        c.c1.Y -= 18.0f * reach;
        c.c2.X += (target.x + 24.0f - c.c2.X) * reach;
        c.c2.Y += (target.y - 30.0f - c.c2.Y) * reach;
        c.tip.X += (target.x - c.tip.X) * reach;
        c.tip.Y += (target.y - c.tip.Y) * reach;

        // When curling up to sleep, tail sweeps smoothly around the front to wrap cozily around the cat ball!
        float sleepWag = std::sin(p * 0.6f) * 2.0f;
        c.root.X += (seatX + 40.0f + shift - c.root.X) * lieS;
        c.root.Y += (seatY - 2.0f - c.root.Y) * lieS;
        c.c1.X += (seatX + 54.0f + shift - c.c1.X) * lieS;
        c.c1.Y += (seatY + 13.0f - c.c1.Y) * lieS;
        c.c2.X += (seatX + 14.0f - c.c2.X) * lieS;
        c.c2.Y += (seatY + 17.0f - c.c2.Y) * lieS;
        c.tip.X += (seatX - 28.0f - c.tip.X) * lieS;
        c.tip.Y += (seatY + 8.0f + sleepWag - c.tip.Y) * lieS;

        c.thickness = skin.shape.tailThickness;
        return c;
    }

    static void drawTail(Gdiplus::Graphics& g, float seatX, float seatY, const CatPhysics& physics, const SkinSpec& skin, bool outlineOnly = false) {
        using namespace Gdiplus;
        TailCurve c = tailCurve(seatX, seatY, physics, skin);
        float width = isDazed(skin) ? 13.0f : (buildOf(skin).tailWidth * skin.shape.tailThickness);

        if (outlineOnly) {
            Pen outPen(blackOutline(), width + BlackOutlineW * 2.0f);
            outPen.SetStartCap(LineCapRound); outPen.SetEndCap(LineCapRound); outPen.SetLineJoin(LineJoinRound);
            g.DrawBezier(&outPen, c.root, c.c1, c.c2, c.tip);
            return;
        }

        Pen tailPen(col(skin.palette.tail), width);
        tailPen.SetStartCap(LineCapRound);
        tailPen.SetEndCap(LineCapRound);
        tailPen.SetLineJoin(LineJoinRound);
        if (isTabby(skin)) {
            tabby::drawTail(g, tailPen, c.root, c.c1, c.c2, c.tip);
            return;
        }
        g.DrawBezier(&tailPen, c.root, c.c1, c.c2, c.tip);

        float lie = std::clamp(physics.lieIntensity.value, 0.0f, 1.0f);
        float lieS = lie * lie * (3.0f - 2.0f * lie);
        if (lieS > 0.35f) {
            float rAlpha = std::min(1.0f, (lieS - 0.35f) / 0.45f) * 0.72f;
            Color rc = col(skin.palette.crease);
            Pen rimPen(Color((BYTE)(rc.GetA() * rAlpha), rc.GetR(), rc.GetG(), rc.GetB()), 1.45f);
            rimPen.SetStartCap(LineCapRound); rimPen.SetEndCap(LineCapRound);
            g.DrawBezier(&rimPen,
                PointF(c.root.X - 4.0f, c.root.Y - 3.0f),
                PointF(c.c1.X - 6.0f, c.c1.Y - 5.5f),
                PointF(c.c2.X, c.c2.Y - 5.5f),
                PointF(c.tip.X + 2.0f, c.tip.Y - 4.5f));
        }
        if (skin.hasPartArt(SkinSpace::Tail) || skin.palette.tailTip.set) {
            GraphicsState state = g.Save();
            GraphicsPath outline; outline.AddBezier(c.root,c.c1,c.c2,c.tip); outline.Widen(&tailPen);
            g.SetClip(&outline, CombineModeIntersect);
            auto map = [&](SkinPoint p) { return c.at(p); };
            for (const SkinRegion& r : skin.regions) if (r.space == SkinSpace::Tail) drawRegion(g, r, map);
            if (skin.palette.tailTip.set) {
                // Last 22% of the tail: de Casteljau split at t = 0.78, stroked with the tail width.
                const float t = 0.78f, u = 1 - t;
                PointF a(u*c.root.X+t*c.c1.X, u*c.root.Y+t*c.c1.Y), b(u*c.c1.X+t*c.c2.X, u*c.c1.Y+t*c.c2.Y), q(u*c.c2.X+t*c.tip.X, u*c.c2.Y+t*c.tip.Y);
                PointF d(u*a.X+t*b.X, u*a.Y+t*b.Y), e(u*b.X+t*q.X, u*b.Y+t*q.Y);
                PointF s(u*d.X+t*e.X, u*d.Y+t*e.Y);
                Pen tipPen(col(skin.palette.tailTip), width + 2.0f);
                tipPen.SetStartCap(LineCapRound); tipPen.SetEndCap(LineCapRound);
                g.DrawBezier(&tipPen, s, e, q, c.tip);
            }
            for (const SkinMark& m : skin.marks) if (m.space == SkinSpace::Tail) drawMark(g, m, map, false);
            g.Restore(state);
        }
    }

    // MARK: - 3D-Projected Ears

    static void drawEarsLayer(Gdiplus::Graphics& g, Pt center, const CatPhysics& physics, const SkinSpec& skin, bool outlineOnly = false) {
        using namespace Gdiplus;
        GraphicsState st = g.Save();
        g.TranslateTransform(center.x, center.y);
        g.RotateTransform(physics.headTilt.value * RadToDeg);
        if (skin.shape.headScale != 1.0f) g.ScaleTransform(skin.shape.headScale, skin.shape.headScale);

        float yawRad = physics.headYaw.value * 0.50f;
        float pitchRad = physics.headPitch.value * 0.36f;
        float fold = physics.earFold.value;
        float twitch = physics.earTwitch.value * 0.045f;

        drawEar3D(g, true, yawRad, pitchRad, fold, twitch, skin, outlineOnly);
        drawEar3D(g, false, yawRad, pitchRad, fold, -twitch, skin, outlineOnly);
        g.Restore(st);
    }

    static void drawEar3D(Gdiplus::Graphics& g, bool isLeft, float yawRad, float pitchRad, float fold, float twitch, const SkinSpec& skin, bool outlineOnly = false) {
        using namespace Gdiplus;
        const Build& bd = buildOf(skin);
        float sign = isLeft ? -1.0f : 1.0f;
        if (isDazed(skin)) {
            if (!outlineOnly) drawDazedEar(g, sign, yawRad, pitchRad, fold, twitch);
            return;
        }
        float foldAngle = sign * (bd.earFold + fold * 0.34f) + twitch;
        float earLen = bd.earLen;
        float tipDx = std::sin(foldAngle) * earLen;
        float tipDy = -std::cos(foldAngle) * earLen;

        Pt innerBase = projectHead3D(sign * bd.earInX, bd.earInY, 0.0f, yawRad, pitchRad);
        Pt outerBase = projectHead3D(sign * bd.earOutX, bd.earOutY, -2.0f, yawRad, pitchRad);
        Pt tip3D     = projectHead3D(sign * bd.earTipX + tipDx, bd.earTipY + tipDy, -3.0f, yawRad, pitchRad);
        float es = skin.shape.earSize;
        if (es != 1.0f) { // grow / shrink around the middle of the ear base
            Pt m = { (innerBase.x + outerBase.x) * 0.5f, (innerBase.y + outerBase.y) * 0.5f };
            innerBase = { around(innerBase.x, m.x, es), around(innerBase.y, m.y, es) };
            outerBase = { around(outerBase.x, m.x, es), around(outerBase.y, m.y, es) };
            tip3D = { around(tip3D.x, m.x, es), around(tip3D.y, m.y, es) };
        }
        float ebw = skin.shape.earBaseWidth;
        if (ebw != 1.0f) {
            Pt m = { (innerBase.x + outerBase.x) * 0.5f, (innerBase.y + outerBase.y) * 0.5f };
            innerBase = { around(innerBase.x, m.x, ebw), around(innerBase.y, m.y, ebw) };
            outerBase = { around(outerBase.x, m.x, ebw), around(outerBase.y, m.y, ebw) };
        }

        float ep = skin.shape.earPointiness;
        float tipSpread = bd.earTipSpread / ep;
        Pt tipL = { tip3D.x - sign * tipSpread, tip3D.y + 2.8f };
        Pt tipR = { tip3D.x + sign * tipSpread, tip3D.y + 3.2f };

        GraphicsPath ear;
        addQuadBezier(ear, innerBase, { (innerBase.x + tipL.x) * 0.5f - sign * 1.5f, (innerBase.y + tipL.y) * 0.5f - 2.0f }, tipL);
        addQuadBezier(ear, tipL, { tip3D.x, tip3D.y - 2.2f * ep }, tipR);
        addQuadBezier(ear, tipR, { (outerBase.x + tipR.x) * 0.5f + sign * 2.5f, (outerBase.y + tipR.y) * 0.5f - 2.0f }, outerBase);
        ear.CloseFigure();

        if (isTabby(skin)) {
            if (outlineOnly) return;
            LinearGradientBrush fur(PointF(tip3D.x, tip3D.y - 2), PointF(outerBase.x, outerBase.y + 2),
                                    tabby::dark(), tabby::oat());
            fur.SetWrapMode(WrapModeTileFlipXY);
            g.FillPath(&fur, &ear);
            auto earPoint = [&](float width, float height) {
                float x = innerBase.x + (outerBase.x - innerBase.x) * width;
                float y = innerBase.y + (outerBase.y - innerBase.y) * width;
                return PointF(x + (tip3D.x - x) * height, y + (tip3D.y - y) * height);
            };
            SolidBrush lining(Color(185, 151, 128));
            tabby::shape(g, earPoint, lining, {.29f, .1f},
                         {{.2f, .37f, .38f, .67f, .48f, .75f},
                          {.60f, .63f, .77f, .26f, .76f, .1f},
                          {.68f, .16f, .44f, .18f, .29f, .1f}});
            return;
        }
        if (outlineOnly) {
            Pen outPen(blackOutline(), BlackOutlineW * 2.0f);
            outPen.SetLineJoin(LineJoinRound); outPen.SetStartCap(LineCapRound); outPen.SetEndCap(LineCapRound);
            g.DrawPath(&outPen, &ear);
            return;
        }
        SolidBrush b(col(skin.palette.earOuter));
        g.FillPath(&b, &ear);

        if (skin.palette.earInner.set) {
            Pt inI  = { innerBase.x + (tip3D.x - innerBase.x) * 0.24f + sign * 3.0f, innerBase.y + (tip3D.y - innerBase.y) * 0.16f };
            Pt outI = { outerBase.x + (tip3D.x - outerBase.x) * 0.20f - sign * 3.8f, outerBase.y + (tip3D.y - outerBase.y) * 0.18f };
            Pt tipI = { (innerBase.x + outerBase.x) * 0.16f + tip3D.x * 0.68f, (innerBase.y + outerBase.y) * 0.14f + tip3D.y * 0.72f + 2.5f };
            GraphicsPath inner;
            addQuadBezier(inner, inI, { (inI.x + tipI.x) * 0.5f - sign * 0.8f, (inI.y + tipI.y) * 0.5f }, tipI);
            addQuadBezier(inner, tipI, { (outI.x + tipI.x) * 0.5f + sign * 1.2f, (outI.y + tipI.y) * 0.5f }, outI);
            inner.CloseFigure();
            SolidBrush ib(col(skin.palette.earInner));
            g.FillPath(&ib, &inner);
        }

        SkinSpace space = isLeft ? SkinSpace::LeftEar : SkinSpace::RightEar;
        if (skin.hasPartArt(space)) {
            // Ear space: (-50,0) inner base, (50,0) outer base, (0,-100) tip; mirrored per ear.
            Pt m = { (innerBase.x + outerBase.x) * 0.5f, (innerBase.y + outerBase.y) * 0.5f };
            auto map = [&](SkinPoint p) {
                float u = p.x / 100.0f, v = -p.y / 100.0f;
                return PointF(m.x + u * (outerBase.x - innerBase.x) + v * (tip3D.x - m.x), m.y + u * (outerBase.y - innerBase.y) + v * (tip3D.y - m.y));
            };
            GraphicsState cs = g.Save();
            g.SetClip(&ear, CombineModeIntersect);
            for (const SkinRegion& r : skin.regions) if (r.space == space) drawRegion(g, r, map);
            for (const SkinMark& mk : skin.marks) if (mk.space == space) drawMark(g, mk, map);
            g.Restore(cs);
        }
    }

    static void drawDazedEar(Gdiplus::Graphics& g, float sign, float yawRad, float pitchRad, float fold, float twitch) {
        using namespace Gdiplus;
        float foldAngle = sign * fold * 0.34f + twitch;
        float tipDx = std::sin(foldAngle) * 37.0f;
        float tipDy = (1.0f - std::cos(foldAngle)) * 37.0f;
        auto project = [&](float x, float y, float tipWeight) {
            Pt point = projectHead3D(sign * x + tipDx * tipWeight, y + tipDy * tipWeight, -3.0f * tipWeight, yawRad, pitchRad);
            return PointF(point.x, point.y);
        };

        PointF innerBase = project(5.0f, -25.0f, 0.0f);
        PointF tip = project(40.0f, -63.0f, 1.0f);
        PointF outerBase = project(42.5f, -5.0f, 0.0f);
        GraphicsPath ear;
        ear.AddBezier(innerBase, project(13.0f, -46.0f, 0.30f), project(31.0f, -62.0f, 0.90f), tip);
        ear.AddBezier(tip, project(54.0f, -66.0f, 0.95f), project(57.0f, -34.0f, 0.40f), outerBase);
        ear.CloseFigure();

        LinearGradientBrush fabric(tip, outerBase, rgb(0x777FBD), rgb(0x4D5892));
        fabric.SetWrapMode(WrapModeTileFlipXY);
        g.FillPath(&fabric, &ear);
    }

    // MARK: - Unified C1-Continuous Cat Silhouette (+ regions, colour-point mask, marks)

    static void drawUnifiedSilhouette(Gdiplus::Graphics& g, float seatX, float seatY, Pt headCenter, float breath, const CatPhysics& physics, const SkinSpec& skin, bool outlineOnly = false) {
        using namespace Gdiplus;
        if (isDazed(skin)) {
            if (!outlineOnly) drawDazedSilhouette(g, seatX, seatY, headCenter, physics);
            return;
        }
        const Build& bd = buildOf(skin);
        const SkinPalette& pal = skin.palette;
        float yaw = physics.headYaw.value;
        float pitch = physics.headPitch.value;
        float hTilt = physics.headTilt.value;
        float bTilt = physics.bodyTilt.value;
        float hs = skin.shape.headScale, bw = skin.shape.bodyWidth;

        float cH = std::cos(hTilt), sH = std::sin(hTilt);
        auto H = [&](float lx, float ly) -> PointF {
            lx *= hs; ly *= hs;
            return PointF(headCenter.x + lx * cH - ly * sH, headCenter.y + lx * sH + ly * cH);
        };

        float cB = std::cos(bTilt), sB = std::sin(bTilt);
        float lie = std::clamp(physics.lieIntensity.value, 0.0f, 1.0f);
        float lieS = lie * lie * (3.0f - 2.0f * lie);
        float sy = physics.bodySquash.value * (1.0f - lieS * 0.42f);
        float sx = (1.0f + (1.0f - physics.bodySquash.value) * 0.55f) * (1.0f + lieS * 0.03f);
        auto B = [&](float lx, float ly) -> PointF {
            float rx = lx * bw * sx, ry = ly * sy;
            return PointF(seatX + rx * cB - ry * sB, seatY + rx * sB + ry * cB);
        };

        float cheekShift = yaw * 3.0f;
        float crownDrop = pitch * 2.0f;
        float cheekHalfW = bd.cheekHalfW * skin.shape.cheekFullness;
        float crownCtrlW = bd.crownCtrlW;
        float crownBaseY = bd.crownBaseY;
        float cheekY = bd.cheekY;
        float cheekCtrlTopY = bd.cheekCtrlTopY;
        float neckPinchX = bd.neckPinchX;
        float neckCtrlY = bd.neckCtrlY;
        float hipHalfW = bd.hipHalfW;
        float waistCtrlW = bd.waistCtrlW;
        float waistCtrlY = bd.waistCtrlY;
        float botOuterW = bd.botOuterW;
        float botInnerW = bd.botInnerW;
        float botHalfW = bd.botHalfW;
        float leftCheekX = -cheekHalfW + cheekShift * 0.4f;
        float rightCheekX = cheekHalfW + cheekShift * 0.4f;

        PointF crown  = H(cheekShift * 0.2f, crownBaseY + crownDrop);
        PointF rCheek = H(rightCheekX, cheekY);
        PointF rHip   = B(hipHalfW, -14.0f);
        PointF rBot   = B(botHalfW, 12.0f);
        PointF lBot   = B(-botHalfW, 12.0f);
        PointF lHip   = B(-hipHalfW, -14.0f);
        PointF lCheek = H(leftCheekX, cheekY);

        float nw = skin.shape.neckWidth;
        float neckCenter = cheekShift * 0.4f;
        float rNeckX = neckCenter + (rightCheekX - neckPinchX - neckCenter) * nw;
        float lNeckX = neckCenter + (leftCheekX + neckPinchX - neckCenter) * nw;
        float neckWaistW = waistCtrlW * (1.0f + (nw - 1.0f) * 0.32f);

        GraphicsPath path;
        path.AddBezier(crown, H(crownCtrlW + cheekShift * 0.3f, crownBaseY + crownDrop), H(rightCheekX + 1.5f, cheekCtrlTopY), rCheek);
        path.AddBezier(rCheek, H(rNeckX, neckCtrlY), B(neckWaistW, waistCtrlY + breath * 0.5f), rHip);
        path.AddBezier(rHip, B(botOuterW, 5.0f), B(botInnerW, 12.0f), rBot);
        path.AddLine(rBot, lBot);
        path.AddBezier(lBot, B(-botInnerW, 12.0f), B(-botOuterW, 5.0f), lHip);
        path.AddBezier(lHip, B(-neckWaistW, waistCtrlY + breath * 0.5f), H(lNeckX, neckCtrlY), lCheek);
        path.AddBezier(lCheek, H(leftCheekX - 1.5f, cheekCtrlTopY), H(-crownCtrlW + cheekShift * 0.3f, crownBaseY + crownDrop), crown);
        path.CloseFigure();

        float stagger = skin.shape.pawStagger;
        float hindW = bd.hindW;
        float leftHindX = bw == 1.0f ? bd.hindLeftX : (bd.hindLeftX + hindW * 0.5f) * bw - hindW * 0.5f;
        float rightHindX = bw == 1.0f ? bd.hindRightX : (bd.hindRightX + hindW * 0.5f) * bw - hindW * 0.5f;
        float leftHindY = bd.hindLeftY;
        float leftHindH = bd.hindLeftH;
        float rightHindY = bd.hindLeftY + (bd.hindStaggerY - bd.hindLeftY) * stagger;
        float rightHindH = bd.hindLeftH + (bd.hindStaggerH - bd.hindLeftH) * stagger;
        bool rightTucked = physics.hindFootActive.value < 0.35f;

        if (outlineOnly) {
            Pen outPen(blackOutline(), BlackOutlineW * 2.0f);
            outPen.SetLineJoin(LineJoinRound); outPen.SetStartCap(LineCapRound); outPen.SetEndCap(LineCapRound);
            g.DrawPath(&outPen, &path);
            GraphicsState ps = g.Save();
            g.TranslateTransform(seatX, seatY);
            g.RotateTransform(bTilt * RadToDeg);
            g.ScaleTransform(sx, sy);
            g.DrawEllipse(&outPen, leftHindX, leftHindY, hindW, leftHindH);
            if (rightTucked) {
                g.DrawEllipse(&outPen, rightHindX, rightHindY, hindW, rightHindH);
            }
            g.Restore(ps);
            return;
        }

        if (isTabby(skin)) {
            auto face = [&](float x, float y) {
                float depth = std::clamp(29.f - .012f * x * x - .22f * std::abs(y + 2.f), 3.f, 28.f);
                Pt projected = projectHead3D(x, y, depth, yaw * .50f, pitch * .36f);
                return H(projected.x, projected.y);
            };
            tabby::drawBody(g, path, face, B, physics);
        } else if (isPatternedBuiltIn(skin)) {
            SolidBrush b(col(pal.body));
            g.FillPath(&b, &path);
            if (isOrangeWhite(skin)) {
                GraphicsPath join;
                join.AddBezier(lCheek, H(leftCheekX - 1.5f, cheekCtrlTopY), H(-crownCtrlW + cheekShift * 0.3f, crownBaseY + crownDrop), crown);
                join.AddBezier(crown, H(crownCtrlW + cheekShift * 0.3f, crownBaseY + crownDrop), H(rightCheekX + 1.5f, cheekCtrlTopY), rCheek);
                Pen fur(col(pal.earOuter), 1.0f); fur.SetStartCap(LineCapRound); fur.SetEndCap(LineCapRound);
                g.DrawPath(&fur, &join);
            }
            GraphicsState cs = g.Save();
            g.SetClip(&path, CombineModeIntersect);
            drawCoatMarks(g, seatX, seatY, headCenter, physics, isShorthair(skin) ? CatCoatTheme::Shorthair : CatCoatTheme::OrangeWhite);
            g.Restore(cs);
        } else {
            bool hasRegions = false, hasMarks = false;
            for (const SkinRegion& r : skin.regions) hasRegions |= r.space == SkinSpace::Head || r.space == SkinSpace::Skull || r.space == SkinSpace::Body;
            for (const SkinMark& m : skin.marks) hasMarks |= m.space == SkinSpace::Head || m.space == SkinSpace::Skull || m.space == SkinSpace::Body;
            auto headMap = [&](SkinPoint p) { return headPoint(p, false, skin, headCenter, physics); };
            auto skullMap = [&](SkinPoint p) { return headPoint(p, true, skin, headCenter, physics); };
            auto bodyMap = [&](SkinPoint p) { return bodyPoint(p, skin, seatX, seatY, physics); };

            if (!pal.bodyShade.set) {
                SolidBrush b(col(pal.body));
                g.FillPath(&b, &path);
            }
            if (pal.bodyShade.set || skin.colorpoint() || hasRegions || hasMarks) {
                GraphicsState cs = g.Save();
                g.SetClip(&path, CombineModeIntersect);

                if (pal.bodyShade.set) {
                    Color top = col(pal.body), bottom = col(pal.bodyShade);
                    LinearGradientBrush bodyGrad(PointF(seatX, headCenter.y - 54.0f), PointF(seatX, seatY + 38.0f), top, bottom);
                    bodyGrad.SetWrapMode(WrapModeTileFlipXY);
                    Color bodyCols[4] = { top, top, bottom, bottom };
                    REAL bodyPos[4] = { 0.0f, 0.22f, 0.80f, 1.0f };
                    bodyGrad.SetInterpolationColors(bodyCols, bodyPos, 4);
                    g.FillPath(&bodyGrad, &path);
                }

                // Curve regions: head/skull above the jaw line, body below it.
                for (const SkinRegion& r : skin.regions) {
                    if (r.space != SkinSpace::Head && r.space != SkinSpace::Skull && r.space != SkinSpace::Body) continue;
                    GraphicsState rs = g.Save();
                    GraphicsPath side;
                    jawSide(side, r.space != SkinSpace::Body, skin, headCenter, physics);
                    g.SetClip(&side, CombineModeIntersect);
                    if (r.space == SkinSpace::Body) drawRegion(g, r, bodyMap);
                    else if (r.space == SkinSpace::Skull) drawRegion(g, r, skullMap);
                    else drawRegion(g, r, headMap);
                    g.Restore(rs);
                }

                if (skin.colorpoint()) {
                    // 2.5D Rotating Seal-Point "挖煤" Face Mask!
                    const SkinColor& point = pal.points;
                    const SkinColor& mid = pal.pointsMid;
                    float yawRad = yaw * 0.50f;
                    float pitchRad = pitch * 0.36f;
                    Pt maskC = projectHead3D(0.0f, 3.0f, 27.0f, yawRad, pitchRad);
                    float maskSX = std::max(0.76f, std::cos(yawRad * 0.7f)) * 1.24f;
                    float maskSY = std::max(0.82f, std::cos(pitchRad * 0.7f)) * 0.88f;

                    GraphicsState ms = g.Save();
                    g.TranslateTransform(headCenter.x, headCenter.y);
                    g.RotateTransform(hTilt * RadToDeg);
                    if (hs != 1.0f) g.ScaleTransform(hs, hs);
                    g.TranslateTransform(maskC.x, maskC.y);
                    g.ScaleTransform(maskSX, maskSY);

                    GraphicsPath maskEllipse;
                    maskEllipse.AddEllipse(-31.5f, -31.5f, 63.0f, 63.0f);
                    PathGradientBrush maskBrush(&maskEllipse);
                    Color cols[4] = { withAlpha(mid, 0), withAlpha(mid, 158), withAlpha(point, 235), withAlpha(point, 255) };
                    REAL pos[4] = { 0.0f, 0.26f, 0.58f, 1.0f };
                    maskBrush.SetInterpolationColors(cols, pos, 4);
                    g.FillPath(&maskBrush, &maskEllipse);
                    g.Restore(ms);

                    Pt muzC = projectHead3D(0.0f, 7.5f, 28.0f, yawRad, pitchRad);
                    GraphicsState ms2 = g.Save();
                    g.TranslateTransform(headCenter.x, headCenter.y);
                    g.RotateTransform(hTilt * RadToDeg);
                    if (hs != 1.0f) g.ScaleTransform(hs, hs);
                    g.TranslateTransform(muzC.x, muzC.y);
                    g.ScaleTransform(std::max(0.76f, std::cos(yawRad * 0.7f)) * 1.04f, std::max(0.82f, std::cos(pitchRad * 0.7f)) * 0.76f);
                    GraphicsPath muzEllipse;
                    muzEllipse.AddEllipse(-19.5f, -19.5f, 39.0f, 39.0f);
                    PathGradientBrush muzBrush(&muzEllipse);
                    Color mCols[3] = { withAlpha(point, 0), withAlpha(point, 216), withAlpha(point, 255) };
                    REAL mPos[3] = { 0.0f, 0.50f, 1.0f };
                    muzBrush.SetInterpolationColors(mCols, mPos, 3);
                    g.FillPath(&muzBrush, &muzEllipse);
                    g.Restore(ms2);
                }

                for (const SkinMark& m : skin.marks) {
                    if (m.space == SkinSpace::Body) drawMark(g, m, bodyMap);
                    else if (m.space == SkinSpace::Skull) drawMark(g, m, skullMap);
                    else if (m.space == SkinSpace::Head) drawMark(g, m, headMap);
                }
                g.Restore(cs);
            }
            if (pal.outline.set) {
                // Ultra-soft plush rim (the Siamese cream body)
                Pen outPen(col(pal.outline), 1.0f);
                g.DrawPath(&outPen, &path);
            }
        }

        // Tucked hind paws at bottom
        GraphicsState ps = g.Save();
        g.TranslateTransform(seatX, seatY);
        g.RotateTransform(bTilt * RadToDeg);
        g.ScaleTransform(sx, sy);

        SolidBrush pawBrush(col(pal.paws));
        g.FillEllipse(&pawBrush, leftHindX, leftHindY, hindW, leftHindH);
        if (rightTucked) {
            g.FillEllipse(&pawBrush, rightHindX, rightHindY, hindW, rightHindH);
        }

        Pen rimPen(skin.colorpoint() ? withAlpha(pal.body, 140) : (isClassicBlack(skin) ? blackOutline(0) : creaseWith(pal.crease, 148)), 1.3f);
        rimPen.SetStartCap(LineCapRound); rimPen.SetEndCap(LineCapRound);
        g.DrawArc(&rimPen, leftHindX + hindW * 0.5f - 7.5f, leftHindY + leftHindH * 0.5f - 7.5f, 15.0f, 15.0f, 15.0f, 150.0f);
        if (rightTucked) {
            g.DrawArc(&rimPen, rightHindX + hindW * 0.5f - 7.5f, rightHindY + rightHindH * 0.5f - 7.5f, 15.0f, 15.0f, 15.0f, 150.0f);
        }
        if (pal.pawPads.set) {
            SolidBrush pad(col(pal.pawPads));
            for (int side = 0; side < (rightTucked ? 2 : 1); ++side) {
                float cx = (side ? rightHindX : leftHindX) + hindW * 0.5f;
                float cy = side ? rightHindY + rightHindH * 0.5f : leftHindY + leftHindH * 0.5f;
                g.FillEllipse(&pad, cx - 2.7f, cy + 1.6f - 1.9f, 5.4f, 3.8f);
                for (float tx : {-3.4f, 0.0f, 3.4f}) {
                    float ty = cy - 1.7f - (tx == 0.0f ? 0.8f : 0.0f);
                    g.FillEllipse(&pad, cx + tx - 1.25f, ty - 1.1f, 2.5f, 2.2f);
                }
            }
        }
        g.Restore(ps);
    }

    static void drawDazedPaw(Gdiplus::Graphics& g, Gdiplus::RectF bounds) {
        using namespace Gdiplus;
        LinearGradientBrush fur(bounds, rgb(0xFFF1CD), rgb(0xCCAC7F), LinearGradientModeVertical);
        fur.SetWrapMode(WrapModeTileFlipXY);
        g.FillEllipse(&fur, bounds);
        Pen edge(rgb(0x7E634A, 170), 0.9f);
        g.DrawEllipse(&edge, bounds);
    }

    static void drawDazedSword(Gdiplus::Graphics& g, float seatX, float seatY, const CatPhysics& physics) {
        using namespace Gdiplus;
        GraphicsState state = g.Save();
        g.TranslateTransform(seatX, seatY + (1.0f - physics.bodySquash.value) * 36.0f);
        g.RotateTransform(physics.bodyTilt.value * RadToDeg);

        GraphicsPath blade;
        blade.AddBezier(38.0f, -96.0f, 7.0f, -61.0f, -31.0f, -33.0f, -65.0f, -38.0f);
        blade.AddBezier(-65.0f, -38.0f, -62.0f, -24.0f, -51.0f, -21.0f, -37.0f, -25.0f);
        blade.AddBezier(-37.0f, -25.0f, -5.0f, -33.0f, 27.0f, -60.0f, 50.0f, -84.0f);
        blade.CloseFigure();
        LinearGradientBrush steel(PointF(-46.0f, -51.0f), PointF(-29.0f, -22.0f), rgb(0x8395B0), rgb(0xDDE7F2));
        steel.SetWrapMode(WrapModeTileFlipXY);
        Pen outline(rgb(0x232638), 3.6f);
        outline.SetLineJoin(LineJoinRound);
        g.FillPath(&steel, &blade);
        g.DrawPath(&outline, &blade);
        Pen bevel(rgb(0xF3F7FB), 2.1f);
        bevel.SetStartCap(LineCapRound);
        g.DrawBezier(&bevel, -59.0f, -33.5f, -34.0f, -24.0f, 12.0f, -53.0f, 43.0f, -87.0f);

        g.TranslateTransform(44.0f, -90.0f);
        g.RotateTransform(44.0f);
        GraphicsPath grip;
        addRoundedRect(grip, -7.5f, -32.0f, 15.0f, 32.0f, 3.6f);
        SolidBrush wrap(rgb(0x58617D));
        g.FillPath(&wrap, &grip);
        GraphicsPath bindings;
        SolidBrush tape(rgb(0xB5BED0));
        for (float y : {-27.0f, -19.0f, -11.0f}) {
            addQuadPoly(bindings, {-7.5f, y - 2.0f}, {7.5f, y + 1.0f}, {7.5f, y + 4.3f}, {-7.5f, y + 1.3f});
        }
        g.FillPath(&tape, &bindings);
        g.DrawPath(&outline, &grip);

        GraphicsPath guard;
        addRoundedRect(guard, -13.5f, -3.8f, 27.0f, 7.6f, 2.5f);
        SolidBrush brass(rgb(0xE2C58B));
        g.FillPath(&brass, &guard);
        g.DrawPath(&outline, &guard);
        g.Restore(state);
    }

    static void drawDazedSilhouette(Gdiplus::Graphics& g, float seatX, float seatY, Pt head, const CatPhysics& physics) {
        using namespace Gdiplus;
        GraphicsState body = g.Save();
        g.TranslateTransform(seatX, seatY);
        g.RotateTransform(physics.bodyTilt.value * RadToDeg);
        float squash = physics.bodySquash.value;
        g.ScaleTransform(1.0f + (1.0f - squash) * 0.55f, squash);

        drawDazedPaw(g, RectF(-34.0f, -2.0f, 19.0f, 18.0f));
        if (physics.hindFootActive.value < 0.35f) {
            drawDazedPaw(g, RectF(15.0f, -2.0f, 19.0f, 18.0f));
        }

        GraphicsPath belly;
        belly.AddBezier(-42.0f, -19.0f, -46.0f, -5.0f, -41.0f, 11.5f, 0.0f, 11.5f);
        belly.AddBezier(0.0f, 11.5f, 41.0f, 11.5f, 46.0f, -5.0f, 42.0f, -19.0f);
        belly.CloseFigure();
        LinearGradientBrush bellyFur(PointF(0.0f, -16.0f), PointF(0.0f, 12.0f), rgb(0xF4DFB8), rgb(0xC8A77A));
        bellyFur.SetWrapMode(WrapModeTileFlipXY);
        g.FillPath(&bellyFur, &belly);

        GraphicsPath tunic;
        tunic.AddBezier(-21.0f, -65.0f, -34.0f, -56.0f, -44.0f, -35.0f, -44.0f, -17.0f);
        tunic.AddBezier(-44.0f, -17.0f, -37.0f, -2.0f, 37.0f, -2.0f, 44.0f, -17.0f);
        tunic.AddBezier(44.0f, -17.0f, 44.0f, -35.0f, 34.0f, -56.0f, 21.0f, -65.0f);
        tunic.CloseFigure();
        LinearGradientBrush cloth(PointF(-16.0f, -65.0f), PointF(12.0f, -5.0f), rgb(0x555F9B), rgb(0x252E58));
        cloth.SetWrapMode(WrapModeTileFlipXY);
        g.FillPath(&cloth, &tunic);
        Pen hem(rgb(0x7C86BC, 155), 1.1f);
        g.DrawBezier(&hem, -39.0f, -15.0f, -28.0f, -6.0f, 28.0f, -6.0f, 39.0f, -15.0f);
        g.Restore(body);

        GraphicsState hoodState = g.Save();
        g.TranslateTransform(head.x, head.y);
        g.RotateTransform(physics.headTilt.value * RadToDeg);

        GraphicsPath hood;
        hood.AddBezier(0.0f, -33.0f, 28.0f, -35.0f, 48.0f, -16.0f, 48.0f, 9.0f);
        hood.AddBezier(48.0f, 9.0f, 48.0f, 32.0f, 25.0f, 41.0f, 0.0f, 41.0f);
        hood.AddBezier(0.0f, 41.0f, -25.0f, 41.0f, -48.0f, 32.0f, -48.0f, 9.0f);
        hood.AddBezier(-48.0f, 9.0f, -48.0f, -16.0f, -28.0f, -35.0f, 0.0f, -33.0f);
        hood.CloseFigure();
        LinearGradientBrush fabric(PointF(-16.0f, -35.0f), PointF(15.0f, 42.0f), rgb(0x6871B4), rgb(0x2F386D));
        fabric.SetWrapMode(WrapModeTileFlipXY);
        g.FillPath(&fabric, &hood);
        g.Restore(hoodState);
    }

    // MARK: - 3rd Key Hind Foot

    static void drawHindFoot(Gdiplus::Graphics& g, float seatX, float seatY, const CatPhysics& physics, const SkinSpec& skin) {
        Pt hip = { seatX + 26.0f * skin.shape.bodyWidth, seatY + 2.0f };
        Pt target = physics.hindFoot.point();
        Pt mid = { (hip.x + target.x) * 0.5f + 10.0f, (hip.y + target.y) * 0.5f - 8.0f };
        drawLimb(g, hip, mid, target, 15.0f, 12.0f, true, 0.85f * physics.hindFootActive.value, skin);
    }

    // MARK: - 2.5D Eyes & Whiskers

    static void drawHeadFeatures(Gdiplus::Graphics& g, Pt center, const CatPhysics& physics, EyeColorTheme eyeTheme, const SkinSpec& skin,
                                 float scruffStartle = 0.0f, float scruffWide = 0.0f) {
        using namespace Gdiplus;
        GraphicsState st = g.Save();
        g.TranslateTransform(center.x, center.y);
        g.RotateTransform(physics.headTilt.value * RadToDeg);
        if (skin.shape.headScale != 1.0f) g.ScaleTransform(skin.shape.headScale, skin.shape.headScale);

        float yawRad = physics.headYaw.value * 0.50f;
        float pitchRad = physics.headPitch.value * 0.36f;

        if (isDazed(skin)) {
            drawDazedFace(g, physics, eyeTheme, yawRad, pitchRad, skin, scruffStartle, scruffWide);
            g.Restore(st);
            return;
        }

        drawEye3D(g, true, yawRad, pitchRad, physics, eyeTheme, skin, scruffStartle, scruffWide);
        drawEye3D(g, false, yawRad, pitchRad, physics, eyeTheme, skin, scruffStartle, scruffWide);
        if (skin.palette.nose.set) {
            Pt nose = projectHead3D(0.0f, 8.2f, 29.0f, yawRad, pitchRad);
            GraphicsPath np;
            addQuadBezier(np, { nose.x - 2.3f, nose.y - 1.1f }, { nose.x, nose.y - 1.6f }, { nose.x + 2.3f, nose.y - 1.1f });
            addQuadBezier(np, { nose.x + 2.3f, nose.y - 1.1f }, { nose.x + 1.8f, nose.y + 0.6f }, { nose.x, nose.y + 1.5f });
            addQuadBezier(np, { nose.x, nose.y + 1.5f }, { nose.x - 1.8f, nose.y + 0.6f }, { nose.x - 2.3f, nose.y - 1.1f });
            np.CloseFigure();
            SolidBrush nb(col(skin.palette.nose));
            g.FillPath(&nb, &np);
        }
        if (skin.palette.mouth.set && physics.yawnAmount < 0.15f) {
            Pt mL   = projectHead3D(-4.2f, 12.2f, 28.4f, yawRad, pitchRad);
            Pt mM   = projectHead3D(0.0f, 11.2f, 28.8f, yawRad, pitchRad);
            Pt mR   = projectHead3D(4.2f, 12.2f, 28.4f, yawRad, pitchRad);
            GraphicsPath mp;
            addQuadBezier(mp, mL, { (mL.x + mM.x) * 0.5f, mL.y + 1.6f }, mM);
            addQuadBezier(mp, mM, { (mM.x + mR.x) * 0.5f, mR.y + 1.6f }, mR);
            Pen mpen(col(skin.palette.mouth), 1.05f);
            mpen.SetStartCap(LineCapRound); mpen.SetEndCap(LineCapRound);
            g.DrawPath(&mpen, &mp);
        }
        if (isPatternedBuiltIn(skin)) drawPatternedMuzzle(g, yawRad, pitchRad);
        if (physics.yawnAmount > 0.03f) {
            float yawn = std::clamp(physics.yawnAmount, 0.0f, 1.0f);
            Pt mouthCenter = projectHead3D(0.0f, 16.2f + yawn * 2.2f, 30.2f, yawRad, pitchRad);
            drawYawnMouth(g, mouthCenter, yawn, skin);
        }
        drawWhiskers3D(g, yawRad, pitchRad, physics, skin);

        float anger = std::clamp(physics.angerIntensity.value, 0.0f, 1.0f);
        if (anger > 0.25f) {
            float aAlpha = std::min(1.0f, (anger - 0.25f) / 0.35f);
            float pulse = 1.0f + std::sin(physics.time * 14.0f) * 0.10f;
            Pt pt = projectHead3D(28.0f, -22.0f, 24.0f, yawRad, pitchRad);
            GraphicsState as = g.Save();
            g.TranslateTransform(pt.x, pt.y);
            g.ScaleTransform(pulse, pulse);
            Pen ap(Color((BYTE)(242 * aAlpha), 245, 56, 72), 2.0f);
            ap.SetStartCap(LineCapRound); ap.SetEndCap(LineCapRound);
            float d = 2.4f, r = 6.2f;
            float dirs[4][2] = { {-1,-1}, {1,-1}, {-1,1}, {1,1} };
            for (auto& dir : dirs) {
                GraphicsPath vp;
                addQuadBezier(vp, { dir[0]*r, dir[1]*d }, { dir[0]*d, dir[1]*d }, { dir[0]*d, dir[1]*r });
                g.DrawPath(&ap, &vp);
            }
            g.Restore(as);
        }
        g.Restore(st);
    }

    static void drawDazedFace(Gdiplus::Graphics& g, const CatPhysics& physics, EyeColorTheme eyeTheme, float yawRad, float pitchRad, const SkinSpec& skin,
                              float scruffStartle = 0.0f, float scruffWide = 0.0f) {
        using namespace Gdiplus;
        Pt face = projectHead3D(0.0f, 4.0f, 22.0f, yawRad * 0.72f, pitchRad * 0.78f);
        g.TranslateTransform(face.x, face.y);
        g.ScaleTransform(std::cos(yawRad), std::cos(pitchRad));

        GraphicsPath opening;
        opening.AddBezier(0.0f, -22.0f, 17.0f, -23.0f, 32.0f, -9.0f, 32.0f, 8.0f);
        opening.AddBezier(32.0f, 8.0f, 32.0f, 22.0f, 17.0f, 27.5f, 0.0f, 27.5f);
        opening.AddBezier(0.0f, 27.5f, -17.0f, 27.5f, -32.0f, 22.0f, -32.0f, 8.0f);
        opening.AddBezier(-32.0f, 8.0f, -32.0f, -9.0f, -17.0f, -23.0f, 0.0f, -22.0f);
        opening.CloseFigure();
        LinearGradientBrush fur(PointF(-7.0f, -23.0f), PointF(8.0f, 29.0f), rgb(0xFFF4D4), rgb(0xDDBF91));
        fur.SetWrapMode(WrapModeTileFlipXY);
        g.FillPath(&fur, &opening);
        Pen binding(rgb(0x34355D), 1.9f);
        g.DrawPath(&binding, &opening);

        GraphicsPath colorPoint;
        colorPoint.AddEllipse(-21.0f, -8.0f, 42.0f, 34.0f);
        PathGradientBrush pointFur(&colorPoint);
        pointFur.SetCenterPoint(PointF(0.0f, 11.0f));
        Color tones[] = {rgb(0x8D5B44, 0), rgb(0x8D5B44, 5), rgb(0x8D5B44, 155), rgb(0x8D5B44, 220)};
        REAL stops[] = {0.0f, 0.17f, 0.38f, 1.0f};
        pointFur.SetInterpolationColors(tones, stops, 4);
        g.FillPath(&pointFur, &colorPoint);

        SolidBrush cheeks(rgb(0xCF8173, 94));
        g.FillEllipse(&cheeks, -23.0f, 10.0f, 9.0f, 4.0f);
        g.FillEllipse(&cheeks, 14.0f, 10.0f, 9.0f, 4.0f);

        Color ink = rgb(0x282333);
        Pen expression(ink, 1.7f);
        expression.SetStartCap(LineCapRound);
        expression.SetEndCap(LineCapRound);
        expression.SetLineJoin(LineJoinRound);
        if (physics.yawnAmount > 0.03f) {
            float yawn = std::clamp(physics.yawnAmount, 0.0f, 1.0f);
            GraphicsState mouthState = g.Save();
            // Keep the opening inside the hood and in the same plane as the rest of the face.
            g.TranslateTransform(0.0f, 17.5f + yawn * 2.0f);
            g.ScaleTransform(1.0f, 0.75f);
            drawYawnMouth(g, {0.0f, 0.0f}, yawn, skin);
            g.Restore(mouthState);
        } else {
            GraphicsPath mouth;
            mouth.AddBezier(-6.5f, 12.0f, -5.9f, 17.0f, -1.8f, 17.5f, 0.0f, 13.4f);
            mouth.AddBezier(0.0f, 13.4f, 1.8f, 17.5f, 5.9f, 17.0f, 6.5f, 12.0f);
            g.DrawPath(&expression, &mouth);
        }
        SolidBrush nose(ink);
        g.FillEllipse(&nose, -1.9f, 10.1f, 3.8f, 2.8f);

        bool happy = physics.isHappyClosedEyes();
        bool squint = physics.isBlissfulSquint();
        if (happy || squint) {
            for (float x : {-11.8f, 11.8f}) {
                GraphicsPath lid;
                addQuadBezier(lid, {x - 7.2f, 2.0f}, {x, happy ? 7.0f : 4.0f}, {x + 7.2f, 2.0f});
                g.DrawPath(&expression, &lid);
            }
            return;
        }

        float open = 1.0f - std::clamp(std::max(physics.effectiveEyeClosure(), scruffStartle * 0.44f), 0.0f, 1.0f);
        if (open <= 0.025f) return;
        float hunt = std::clamp(std::max(physics.huntIntensity.value, scruffWide * 0.94f), 0.0f, 1.0f);
        Pt gaze = physics.eyeGaze.point();
        float gazeX = std::clamp(gaze.x, -1.0f, 1.0f) * (1.35f - hunt * 0.65f);
        float gazeY = std::clamp(gaze.y, -1.0f, 1.0f) * (1.1f - hunt * 0.55f);
        float radius = 8.5f + hunt * 1.0f;
        float pupilRadius = 6.25f + hunt * 1.35f;
        SolidBrush eyeRim(ink);
        SolidBrush iris(blendColor(rgb(0xFFF8E5), eyePrimary(eyeTheme), 0.20f));
        SolidBrush pupil(rgb(0x191825));
        SolidBrush glint(rgb(0xFFF9EA));
        for (float x : {-11.8f, 11.8f}) {
            GraphicsState eye = g.Save();
            g.TranslateTransform(x, 1.0f);
            g.ScaleTransform(1.0f, open);
            g.FillEllipse(&eyeRim, -radius, -radius, 2.0f * radius, 2.0f * radius);
            float irisRadius = radius - 1.25f;
            g.FillEllipse(&iris, -irisRadius, -irisRadius, 2.0f * irisRadius, 2.0f * irisRadius);
            g.FillEllipse(&pupil, gazeX - pupilRadius, gazeY - pupilRadius, 2.0f * pupilRadius, 2.0f * pupilRadius);
            if (hunt > 0.25f) {
                float shine = 1.1f + hunt * 0.6f;
                g.FillEllipse(&glint, gazeX - 3.4f, gazeY - 4.2f, 2.0f * shine, 2.0f * shine);
                if (scruffWide > 0.25f) {
                    float sr = 1.1f;
                    g.FillEllipse(&glint, gazeX + 2.2f - sr, gazeY + 2.5f - sr, 2.0f * sr, 2.0f * sr);
                }
            }
            g.Restore(eye);
        }
    }

    static void drawYawnMouth(Gdiplus::Graphics& g, Pt center, float y, const SkinSpec& skin) {
        using namespace Gdiplus;
        float rx = 3.2f + y * 5.8f;
        float ry = 1.6f + y * 7.4f;

        GraphicsState st = g.Save();
        g.TranslateTransform(center.x, center.y);

        GraphicsPath mouth;
        mouth.AddBezier(0.0f, -ry * 0.92f, rx * 0.68f, -ry * 0.92f, rx * 1.05f, -ry * 0.42f, rx, ry * 0.08f);
        mouth.AddBezier(rx, ry * 0.08f, rx * 0.95f, ry * 0.72f, rx * 0.50f, ry, 0.0f, ry);
        mouth.AddBezier(0.0f, ry, -rx * 0.50f, ry, -rx * 0.95f, ry * 0.72f, -rx, ry * 0.08f);
        mouth.AddBezier(-rx, ry * 0.08f, -rx * 1.05f, -ry * 0.42f, -rx * 0.68f, -ry * 0.92f, 0.0f, -ry * 0.92f);
        mouth.CloseFigure();

        SolidBrush bgBrush(Color(250, 199, 48, 64));
        g.FillPath(&bgBrush, &mouth);

        GraphicsState cs = g.Save();
        g.SetClip(&mouth, CombineModeIntersect);

        SolidBrush shadowBrush(Color(140, 140, 26, 41));
        g.FillEllipse(&shadowBrush, -rx * 0.65f, -ry * 0.72f, rx * 1.30f, ry * 0.92f);

        if (y > 0.22f) {
            float tAlpha = std::min(1.0f, (y - 0.22f) / 0.35f);
            SolidBrush tongueBrush(Color((BYTE)(235 * tAlpha), 242, 122, 140));
            GraphicsPath tongue;
            addQuadBezier(tongue, { -rx * 0.62f, ry * 0.55f }, { -rx * 0.32f, ry * 0.16f }, { 0.0f, ry * 0.36f });
            addQuadBezier(tongue, { 0.0f, ry * 0.36f }, { rx * 0.32f, ry * 0.16f }, { rx * 0.62f, ry * 0.55f });
            addQuadBezier(tongue, { rx * 0.62f, ry * 0.55f }, { 0.0f, ry * 1.25f }, { -rx * 0.62f, ry * 0.55f });
            tongue.CloseFigure();
            g.FillPath(&tongueBrush, &tongue);
        }

        if (y > 0.28f) {
            float fScale = std::min(1.0f, (y - 0.28f) / 0.32f);
            SolidBrush fangBrush(Color(250, 255, 252, 245));
            float uBaseY = -ry * 0.80f;
            float uLen = (2.6f + y * 2.2f) * fScale;
            float uHW = (1.15f + y * 0.55f) * fScale;
            for (float sign : { -1.0f, 1.0f }) {
                float fx = sign * rx * 0.46f;
                PointF pts[3] = { { fx - uHW, uBaseY - 0.8f }, { fx + uHW, uBaseY - 0.8f }, { fx - sign * 0.25f, uBaseY + uLen } };
                g.FillPolygon(&fangBrush, pts, 3);
            }
            float lBaseY = ry * 0.84f;
            float lLen = (1.6f + y * 1.3f) * fScale;
            float lHW = (0.85f + y * 0.35f) * fScale;
            for (float sign : { -1.0f, 1.0f }) {
                float fx = sign * rx * 0.36f;
                PointF pts[3] = { { fx - lHW, lBaseY + 0.8f }, { fx + lHW, lBaseY + 0.8f }, { fx - sign * 0.15f, lBaseY - lLen } };
                g.FillPolygon(&fangBrush, pts, 3);
            }
        }
        g.Restore(cs);

        bool darkRim = skin.colorpoint() || (!isDazed(skin) && skin.palette.body.luminance() < 0.25);
        Pen rimPen(darkRim ? Color(216, 107, 20, 31) : Color(184, 143, 56, 66), 1.0f);
        g.DrawPath(&rimPen, &mouth);
        g.Restore(st);
    }

    static void drawPatternedMuzzle(Gdiplus::Graphics& g, float yawRad, float pitchRad) {
        using namespace Gdiplus;
        const Pt local[] = {{-2.90f, 8.50f}, {-1.80f, 8.10f}, {1.80f, 8.10f}, {2.90f, 8.50f}, {3.20f, 8.90f}, {0.80f, 12.10f}, {0.00f, 12.30f}, {-0.80f, 12.10f}, {-3.20f, 8.90f}, {-2.90f, 8.50f}, {-5.90f, 14.40f}, {-4.70f, 18.00f}, {-1.40f, 18.00f}, {0.00f, 14.30f}, {1.40f, 18.00f}, {4.70f, 18.00f}, {5.90f, 14.40f}, {0.00f, 12.00f}};
        Pt p[18];
        for (int i=0;i<18;++i) p[i]=projectHead3D(local[i].x,local[i].y,30.0f,yawRad,pitchRad);
        GraphicsPath nose;
        nose.AddBezier(p[0].x,p[0].y,p[1].x,p[1].y,p[2].x,p[2].y,p[3].x,p[3].y);
        nose.AddBezier(p[3].x,p[3].y,p[4].x,p[4].y,p[5].x,p[5].y,p[6].x,p[6].y);
        nose.AddBezier(p[6].x,p[6].y,p[7].x,p[7].y,p[8].x,p[8].y,p[9].x,p[9].y);
        nose.CloseFigure(); SolidBrush ink(Color(255,217,143,155)); g.FillPath(&ink,&nose);
        GraphicsPath mouth;
        mouth.AddLine(p[17].x,p[17].y,p[13].x,p[13].y); mouth.StartFigure();
        mouth.AddBezier(p[10].x,p[10].y,p[11].x,p[11].y,p[12].x,p[12].y,p[13].x,p[13].y);
        mouth.AddBezier(p[13].x,p[13].y,p[14].x,p[14].y,p[15].x,p[15].y,p[16].x,p[16].y);
        Pen pen(Color(199,139,140,134),1.15f); pen.SetStartCap(LineCapRound); pen.SetEndCap(LineCapRound); pen.SetLineJoin(LineJoinRound); g.DrawPath(&pen,&mouth);
    }

    static void drawEye3D(Gdiplus::Graphics& g, bool isLeft, float yawRad, float pitchRad, const CatPhysics& physics, EyeColorTheme eyeTheme, const SkinSpec& skin,
                          float scruffStartle = 0.0f, float scruffWide = 0.0f) {
        using namespace Gdiplus;
        float sign = isLeft ? -1.0f : 1.0f;
        bool customIris = skin.palette.iris.set; // a skin's iris overrides the eye-colour menu
        Color eyeCol = customIris ? col(skin.palette.iris) : eyePrimary(eyeTheme);
        Pt proj = projectHead3D(sign * 17.2f, -2.0f, 27.5f, yawRad, pitchRad);

        float eyeNormal = yawRad + sign * 0.34f;
        float foreX = std::clamp(std::cos(eyeNormal) / std::cos(0.34f), 0.64f, 1.06f);
        float foreY = std::clamp(std::cos(pitchRad * 0.85f), 0.78f, 1.03f);

        GraphicsState st = g.Save();
        g.TranslateTransform(proj.x, proj.y);
        g.ScaleTransform(foreX, foreY);

        // Mode 0: Dizzy spinning spiral eyes (@ @) after 10s of rapid mouse shaking
        float dizzy = std::clamp(physics.dizzyIntensity.value, 0.0f, 1.0f);
        if (dizzy > 0.28f) {
            SolidBrush bg(Color(242, 250, 250, 245));
            g.FillEllipse(&bg, -11.5f, -11.0f, 23.0f, 22.0f);
            Pen sp(Color(242, 36, 36, 46), 1.85f);
            sp.SetStartCap(LineCapRound); sp.SetEndCap(LineCapRound);
            PointF pts[43];
            float spin = physics.dizzyPhase * (isLeft ? 1.0f : -1.0f);
            for (int i = 0; i <= 42; ++i) {
                float t = (float)i / 42.0f;
                float theta = spin + t * 3.1415926f * 5.2f;
                float rad = 1.0f + t * 8.6f;
                pts[i] = PointF(std::cos(theta) * rad, std::sin(theta) * rad);
            }
            g.DrawLines(&sp, pts, 43);
            g.Restore(st);
            return;
        }

        auto colorLuma = [](const SkinColor& c) -> float {
            return 0.299f * c.r + 0.587f * c.g + 0.114f * c.b;
        };
        float bodyLuma = colorLuma(skin.palette.body);
        float pointsLuma = skin.palette.points.set ? colorLuma(skin.palette.points) : 1.0f;
        float outlineLuma = skin.palette.outline.set ? colorLuma(skin.palette.outline) : 1.0f;
        bool isDarkEyeArea = bodyLuma < 0.28f || (skin.colorpoint() && pointsLuma < 0.38f);
        Color closedLidCol = isTabby(skin)
            ? tabby::dark()
            : (isDarkEyeArea
                ? eyeCol
                : (skin.palette.outline.set && outlineLuma < 0.42f ? withAlpha(skin.palette.outline, 230) : Color(224, 60, 50, 44)));

        // Mode 1: Happy closed curved line eyes (petting head!)
        if (physics.isHappyClosedEyes()) {
            GraphicsPath hp;
            addQuadBezier(hp, {-11.5f, 1.0f}, {sign * 1.5f, 3.4f}, {11.5f, 1.0f});
            Pen p(closedLidCol, 2.6f);
            p.SetStartCap(LineCapRound); p.SetEndCap(LineCapRound);
            g.DrawPath(&p, &hp);
            g.Restore(st);
            return;
        }

        // Mode 1b: Peaceful closed sleeping eyelids on light-faced cats so eyes never vanish into light fur!
        if (!isDarkEyeArea && physics.sleepiness > 0.62f && scruffStartle < 0.15f) {
            GraphicsPath sp;
            addQuadBezier(sp, {-10.5f, 0.4f}, {0.0f, 5.2f}, {10.5f, 0.4f});
            Pen p(closedLidCol, 2.5f);
            p.SetStartCap(LineCapRound); p.SetEndCap(LineCapRound);
            g.DrawPath(&p, &sp);
            g.Restore(st);
            return;
        }

        // Mode 2: Blissful half-squint glowing slits (petting body!)
        if (physics.isBlissfulSquint()) {
            GraphicsPath sp;
            addQuadBezier(sp, {-11.5f, -0.5f}, {0.0f, 0.6f}, {11.5f, -0.5f});
            addQuadBezier(sp, {11.5f, -0.5f}, {0.0f, 4.8f}, {-11.5f, -0.5f});
            sp.CloseFigure();
            SolidBrush sb(isTabby(skin) ? tabby::dark() : eyeCol);
            g.FillPath(&sb, &sp);
            if (!isDarkEyeArea && !isTabby(skin)) {
                GraphicsPath rimP;
                addQuadBezier(rimP, {-11.2f, -0.5f}, {0.0f, 0.6f}, {11.2f, -0.5f});
                Pen rp(closedLidCol, 1.6f);
                rp.SetStartCap(LineCapRound); rp.SetEndCap(LineCapRound);
                g.DrawPath(&rp, &rimP);
            }
            g.Restore(st);
            return;
        }

        float hunt = std::clamp(std::max(physics.huntIntensity.value, scruffWide * 0.94f), 0.0f, 1.0f);
        g.RotateTransform(sign * (0.06f * (1.0f - hunt * 0.6f)) * RadToDeg);

        bool siameseBlue = !customIris && eyeTheme == EyeColorTheme::SiameseBlue;
        bool isSiameseEye = buildOf(skin).sleekEyes && siameseBlue;
        float rx = isSiameseEye ? (11.4f + hunt * 1.3f) : (12.0f + hunt * 1.1f);
        float ry = isSiameseEye ? (9.8f + hunt * 2.0f) : (10.8f + hunt * 1.8f);

        GraphicsPath eyeClip;
        eyeClip.AddEllipse(-rx, -ry, rx * 2.0f, ry * 2.0f);
        GraphicsState cs = g.Save();
        g.SetClip(&eyeClip, CombineModeIntersect);
        // Leave covered pixels untouched so the underlying face remains seamless.
        float closure = std::clamp(std::max(physics.effectiveEyeClosure(), scruffStartle * 0.44f), 0.0f, 1.0f);
        if (closure >= 1.0f) {
            g.Restore(cs);
            g.Restore(st);
            return;
        }
        RectF opening(-rx - 2.0f, -ry + 2.0f * ry * closure,
                      2.0f * rx + 4.0f, 2.0f * ry * (1.0f - closure));
        if (closure > 0.0f) g.SetClip(opening, CombineModeIntersect);

        // Angry furrowed V-brow slant clipped cleanly inside the eye opening
        // (avoids painting flat solid eyebrows across gradient fur like Siamese!)
        float anger = std::clamp(physics.angerIntensity.value, 0.0f, 1.0f);
        if (anger > 0.08f) {
            float drop = anger * 8.2f;
            GraphicsPath angryCut;
            PointF cutPts[4] = {
                PointF(-rx - 2.0f, -ry + (isLeft ? 1.0f : drop)),
                PointF( rx + 2.0f, -ry + (isLeft ? drop : 1.0f)),
                PointF( rx + 2.0f,  ry + 2.0f),
                PointF(-rx - 2.0f,  ry + 2.0f)
            };
            angryCut.AddPolygon(cutPts, 4);
            g.SetClip(&angryCut, CombineModeIntersect);
        }

        SolidBrush irisBrush(eyeCol);
        g.FillRectangle(&irisBrush, -rx - 1.0f, -ry - 1.0f, rx * 2.0f + 2.0f, ry * 2.0f + 2.0f);
        if (siameseBlue) {
            LinearGradientBrush irisGrad(PointF(0.0f, -ry - 1.0f), PointF(0.0f, ry + 1.0f), Color(255, 143, 196, 230), Color(255, 219, 241, 252));
            irisGrad.SetWrapMode(WrapModeTileFlipXY);
            Color iCols[3] = { Color(255, 143, 196, 230), Color(255, 181, 222, 245), Color(255, 219, 241, 252) };
            REAL iPos[3] = { 0.0f, 0.55f, 1.0f };
            irisGrad.SetInterpolationColors(iCols, iPos, 3);
            g.FillRectangle(&irisGrad, -rx - 1.0f, -ry - 1.0f, rx * 2.0f + 2.0f, ry * 2.0f + 2.0f);
        }

        if (!customIris && eyeTheme == EyeColorTheme::OliveGold) {
            LinearGradientBrush iris(PointF(0, -ry - 1), PointF(0, ry + 1),
                                     blendColor(eyeCol, tabby::brown(), .39f),
                                     blendColor(eyeCol, Color(250, 237, 189), .31f));
            g.FillRectangle(&iris, -rx - 1.f, -ry - 1.f, 2 * rx + 2, 2 * ry + 2);
            Pen eyeRim(tabby::dark(), 1.5f);
            g.DrawEllipse(&eyeRim, -rx + .4f, -ry + .4f, 2 * rx - .8f, 2 * ry - .8f);
        }

        // Pupil morphs smoothly from vertical slit -> HUGE round black boba pupil!
        Pt gaze = physics.eyeGaze.point();
        float px = gaze.x * (4.2f - hunt * 1.2f);
        float py = gaze.y * (3.6f - hunt * 1.0f);
        float pScale = physics.pupilScale.value;
        float normalW = 5.0f * pScale;
        float normalH = 13.5f * std::min(1.12f, pScale);
        float huntDiam = 18.8f;
        float pupilW = normalW + (huntDiam - normalW) * hunt;
        float pupilH = normalH + (huntDiam - normalH) * hunt;

        // Reference iris colors, blended only in a narrow ring around the moving pupil.
        if (!customIris && eyeTheme == EyeColorTheme::ReferenceHazel) {
            for (int i = 0; i <= 24; ++i) {
                float t = i / 24.0f, mix = t*t*(3-2*t), rim = (1-t)*2.2f;
                SolidBrush ring(Color(255, (BYTE)std::lround(218-77*mix),
                    (BYTE)std::lround(178-33*mix), (BYTE)std::lround(87+41*mix)));
                g.FillEllipse(&ring, px-pupilW*0.5f-rim, py-pupilH*0.5f-rim,
                    pupilW+2*rim, pupilH+2*rim);
            }
        }
        SolidBrush pupilBrush(catBlack());
        g.FillEllipse(&pupilBrush, px - pupilW * 0.5f, py - pupilH * 0.5f, pupilW, pupilH);

        // Tiny crisp white sparkle glint as boba hunting pupils dilate (and delicate catchlight on Siamese blue eyes!)
        if (hunt > 0.25f) {
            BYTE ga = (BYTE)(std::min(1.0f, (hunt - 0.25f) / 0.55f) * 235.0f);
            float gr = 2.1f + hunt * 0.9f;
            SolidBrush gb(Color(ga, 255, 255, 255));
            g.FillEllipse(&gb, px - pupilW * 0.22f - gr * 0.5f, py - pupilH * 0.22f - gr * 0.5f, gr * 2.0f, gr * 2.0f);
            // Second crisp lower specular dot when scruff-lifted aloft for extra watery pleading appeal
            if (scruffWide > 0.25f) {
                BYTE sAlpha = (BYTE)(std::min(1.0f, (scruffWide - 0.25f) / 0.45f) * 0.88f * 255.0f);
                SolidBrush sb2(Color(sAlpha, 255, 255, 255));
                float sr = 1.45f;
                g.FillEllipse(&sb2, px + pupilW * 0.16f - sr, py + pupilH * 0.18f - sr, sr * 2.0f, sr * 2.0f);
            }
        } else if (siameseBlue) {
            float gr = 1.65f;
            SolidBrush gb(Color(220, 255, 255, 255));
            g.FillEllipse(&gb, px - 2.9f - gr, py - 3.6f - gr, gr * 2.0f, gr * 2.0f);
        }

        g.Restore(cs);
        g.Restore(st);
    }

    static void drawWhiskers3D(Gdiplus::Graphics& g, float yawRad, float pitchRad, const CatPhysics& physics, const SkinSpec& skin) {
        using namespace Gdiplus;
        float wiggle = std::sin(physics.time * 4.5f) * (std::max(physics.petHeadIntensity, physics.petBodyIntensity) * 1.2f);
        Pen pen(col(skin.palette.whiskers), 1.05f);
        pen.SetStartCap(LineCapRound); pen.SetEndCap(LineCapRound);

        const float rows[3][3] = {
            { 10.5f, 36.5f, 8.8f + wiggle },
            { 14.2f, 37.8f, 14.2f + wiggle * 0.5f },
            { 18.0f, 35.5f, 19.6f - wiggle * 0.4f }
        };

        for (float sign : {-1.0f, 1.0f}) {
            for (int i = 0; i < 3; ++i) {
                Pt p0 = projectHead3D(sign * 24.0f, rows[i][0], 23.0f, yawRad, pitchRad);
                Pt p2 = projectHead3D(sign * rows[i][1], rows[i][2], 14.0f, yawRad, pitchRad);
                Pt ctrl = { (p0.x + p2.x) * 0.5f, (p0.y + p2.y) * 0.5f - 0.8f };
                GraphicsPath wp;
                addQuadBezier(wp, p0, ctrl, p2);
                g.DrawPath(&pen, &wp);
            }
        }
    }

    // MARK: - Decorations (anchored PNG stickers)

    // Minimal read-only IStream over the decoded PNG bytes (avoids linking shlwapi/ole32 just for this).
    class MemoryStream : public IStream {
    public:
        explicit MemoryStream(const std::vector<uint8_t>& bytes) : data_(bytes) {}
        HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void** out) override {
            static const GUID unknown = {0x00000000, 0x0000, 0x0000, {0xC0, 0, 0, 0, 0, 0, 0, 0x46}};
            static const GUID stream = {0x0000000c, 0x0000, 0x0000, {0xC0, 0, 0, 0, 0, 0, 0, 0x46}};
            static const GUID sequential = {0x0c733a30, 0x2a1c, 0x11ce, {0xad, 0xe5, 0x00, 0xaa, 0x00, 0x44, 0x77, 0x3d}};
            if (!out) return E_POINTER;
            if (std::memcmp(&riid, &unknown, sizeof(GUID)) == 0 || std::memcmp(&riid, &stream, sizeof(GUID)) == 0 ||
                std::memcmp(&riid, &sequential, sizeof(GUID)) == 0) { *out = this; AddRef(); return S_OK; }
            *out = nullptr;
            return E_NOINTERFACE;
        }
        ULONG STDMETHODCALLTYPE AddRef() override { return ++refs_; }
        ULONG STDMETHODCALLTYPE Release() override { ULONG r = --refs_; if (r == 0) delete this; return r; }
        HRESULT STDMETHODCALLTYPE Read(void* pv, ULONG cb, ULONG* read) override {
            size_t n = std::min<size_t>(cb, data_.size() - std::min(pos_, data_.size()));
            if (n) std::memcpy(pv, data_.data() + pos_, n);
            pos_ += n;
            if (read) *read = (ULONG)n;
            return n == cb ? S_OK : S_FALSE;
        }
        HRESULT STDMETHODCALLTYPE Write(const void*, ULONG, ULONG*) override { return STG_E_ACCESSDENIED; }
        HRESULT STDMETHODCALLTYPE Seek(LARGE_INTEGER move, DWORD origin, ULARGE_INTEGER* newPos) override {
            long long base = origin == STREAM_SEEK_SET ? 0 : origin == STREAM_SEEK_CUR ? (long long)pos_ : (long long)data_.size();
            long long p = base + move.QuadPart;
            if (p < 0) return STG_E_INVALIDFUNCTION;
            pos_ = (size_t)p;
            if (newPos) newPos->QuadPart = (ULONGLONG)pos_;
            return S_OK;
        }
        HRESULT STDMETHODCALLTYPE SetSize(ULARGE_INTEGER) override { return E_NOTIMPL; }
        HRESULT STDMETHODCALLTYPE CopyTo(IStream*, ULARGE_INTEGER, ULARGE_INTEGER*, ULARGE_INTEGER*) override { return E_NOTIMPL; }
        HRESULT STDMETHODCALLTYPE Commit(DWORD) override { return S_OK; }
        HRESULT STDMETHODCALLTYPE Revert() override { return E_NOTIMPL; }
        HRESULT STDMETHODCALLTYPE LockRegion(ULARGE_INTEGER, ULARGE_INTEGER, DWORD) override { return E_NOTIMPL; }
        HRESULT STDMETHODCALLTYPE UnlockRegion(ULARGE_INTEGER, ULARGE_INTEGER, DWORD) override { return E_NOTIMPL; }
        HRESULT STDMETHODCALLTYPE Stat(STATSTG* st, DWORD) override {
            if (!st) return E_POINTER;
            std::memset(st, 0, sizeof(STATSTG));
            st->type = STGTY_STREAM;
            st->cbSize.QuadPart = (ULONGLONG)data_.size();
            return S_OK;
        }
        HRESULT STDMETHODCALLTYPE Clone(IStream**) override { return E_NOTIMPL; }
    private:
        virtual ~MemoryStream() = default;
        const std::vector<uint8_t>& data_;
        size_t pos_ = 0;
        ULONG refs_ = 1;
    };

    static Gdiplus::Bitmap* decorationBitmap(const SkinDecoration& d) {
        using namespace Gdiplus;
        if (!d.nativeImage) {
            Bitmap* copy = nullptr;
            MemoryStream* stream = new MemoryStream(d.png);
            {
                Bitmap decoded(stream);
                if (decoded.GetLastStatus() == Ok && decoded.GetWidth() > 0) {
                    // Copy into a standalone 32bpp bitmap so nothing keeps referencing the stream.
                    copy = new Bitmap((INT)decoded.GetWidth(), (INT)decoded.GetHeight(), PixelFormat32bppPARGB);
                    Graphics cg(copy);
                    cg.DrawImage(&decoded, 0, 0, (INT)decoded.GetWidth(), (INT)decoded.GetHeight());
                }
            }
            stream->Release();
            // An undecodable PNG is remembered as an empty bitmap so it is not retried every frame.
            d.nativeImage = std::shared_ptr<void>(copy ? (void*)copy : (void*)new Bitmap(1, 1, PixelFormat32bppPARGB),
                                                  [](void* p) { delete (Bitmap*)p; });
            if (!copy) return nullptr;
        }
        Bitmap* bmp = (Bitmap*)d.nativeImage.get();
        return bmp->GetWidth() > 1 || d.pixelWidth == 1 ? bmp : nullptr;
    }

    static void drawDecorations(Gdiplus::Graphics& g, float seatX, float seatY, Pt head, const CatPhysics& physics, const SkinSpec& skin,
                                const Pt* neckOverride = nullptr, const Pt* tailTipOverride = nullptr) {
        using namespace Gdiplus;
        float yawRad = physics.headYaw.value * 0.50f, pitchRad = physics.headPitch.value * 0.36f;
        for (const SkinDecoration& d : skin.decorations) {
            Bitmap* img = decorationBitmap(d);
            if (!img) continue;
            PointF at;
            float rot = 0, kx = 1, ky = 1;
            switch (d.anchor) {
                case SkinAnchorPoint::HeadTop:
                case SkinAnchorPoint::Face: {
                    float baseY = d.anchor == SkinAnchorPoint::HeadTop ? -30.0f : 4.0f;
                    at = headPoint({d.offsetX, baseY + d.offsetY}, false, skin, head, physics);
                    rot = physics.headTilt.value;
                    kx = std::max(0.55f, std::cos(yawRad)) * skin.shape.headScale;
                    ky = std::max(0.70f, std::cos(pitchRad)) * skin.shape.headScale;
                    break;
                }
                case SkinAnchorPoint::Neck:
                    if (neckOverride) {
                        at = PointF(neckOverride->x + d.offsetX, neckOverride->y + d.offsetY);
                        rot = 0.0f;
                    } else {
                        at = bodyPoint({d.offsetX, -64.0f + d.offsetY}, skin, seatX, seatY, physics);
                        rot = physics.bodyTilt.value;
                    }
                    break;
                case SkinAnchorPoint::TailTip: {
                    if (tailTipOverride) {
                        at = PointF(tailTipOverride->x + d.offsetX, tailTipOverride->y + d.offsetY);
                    } else {
                        TailCurve c = tailCurve(seatX, seatY, physics, skin);
                        at = PointF(c.tip.X + d.offsetX, c.tip.Y + d.offsetY);
                    }
                    break;
                }
            }
            float scale = 0.5f * d.scale; // stickers are authored at 2x: 1 image px = 0.5 canvas units
            float w = (float)img->GetWidth(), h = (float)img->GetHeight();
            GraphicsState st = g.Save();
            g.TranslateTransform(at.X, at.Y);
            g.RotateTransform(rot * RadToDeg + d.rotation);
            g.ScaleTransform(scale * kx, scale * ky);
            g.SetInterpolationMode(InterpolationModeHighQualityBicubic);
            g.DrawImage(img, RectF(-w * 0.5f, -h * 0.5f, w, h));
            g.Restore(st);
        }
    }

    // MARK: - Front Paws

    static void drawFrontPaws(Gdiplus::Graphics& g, float seatX, float seatY, float breath, const CatPhysics& physics, const SkinSpec& skin) {
        Pt lPos = physics.leftPaw.point();
        Pt rPos = physics.rightPaw.point();

        float lDist = std::hypot(lPos.x - CatPhysics::LeftPawRest.x, lPos.y - CatPhysics::LeftPawRest.y);
        float rDist = std::hypot(rPos.x - CatPhysics::RightPawRest.x, rPos.y - CatPhysics::RightPawRest.y);

        const Build& bd = buildOf(skin);
        float bw = skin.shape.bodyWidth;
        float headLift = bd.headLift;
        float lie = std::clamp(physics.lieIntensity.value, 0.0f, 1.0f);
        float lieS = lie * lie * (3.0f - 2.0f * lie);
        float idleTopY = (seatY - bd.idleTopDY) + lieS * 24.0f;
        float idleTopX = bd.idleTopX * bw - lieS * 5.0f;
        float idleBotX = bd.idleBotX * bw - lieS * 4.5f;
        float idleBotY = seatY + 12.0f - lieS * 4.0f;
        float shX = bd.shoulderX * bw;
        float limbStartW = bd.limbStartW;
        float limbEndW = bd.limbEndW;

        const bool approved = !skin.palette.points.set && skin.palette.belly.set && skin.palette.belly.sameAs(skin.palette.legs) && !skin.idleLegsTinted && !skin.marks.empty();
        const float shoulderDepth = approved ? 43.0f : 58.0f, faceClearance = approved ? 52.0f : 42.0f;
        auto shoulder = [&](float x) -> Pt {
            float sy=physics.bodySquash.value*(1.0f-lieS*0.42f), sx=(1+(1-physics.bodySquash.value)*0.55f)*(1.0f+lieS*0.03f);
            float c=std::cos(physics.bodyTilt.value), s=std::sin(physics.bodyTilt.value);
            float floor=126+headLift+physics.headOffsetY.value+physics.headPitch.value*4.8f+breath*1.1f+faceClearance;
            return {seatX+x*sx*c+shoulderDepth*sy*s, std::max(seatY+x*sx*s-shoulderDepth*sy*c,floor)};
        };
        Pt leftShoulder=shoulder(-shX), rightShoulder=shoulder(shX);

        if (lDist < 6.0f && !physics.leftPawOnMouse && !physics.leftPawTyping) {
            if (lieS < 0.78f) drawIdleFrontLeg(g, { seatX - idleTopX, idleTopY }, { seatX - idleBotX, idleBotY }, true, skin);
        } else {
            Pt mid = { (leftShoulder.x + lPos.x) * 0.5f - (physics.leftPawOnMouse ? 8.0f : 4.0f),
                       (leftShoulder.y + lPos.y) * 0.5f - 6.0f };
            drawLimb(g, leftShoulder, mid, lPos, limbStartW, limbEndW, false, 0.78f, skin, true);
        }

        if (rDist < 6.0f && !physics.rightPawTyping) {
            if (lieS < 0.78f) drawIdleFrontLeg(g, { seatX + idleTopX, idleTopY }, { seatX + idleBotX, idleBotY }, false, skin);
        } else {
            Pt mid = { (rightShoulder.x + rPos.x) * 0.5f + 4.0f, (rightShoulder.y + rPos.y) * 0.5f - 6.0f };
            drawLimb(g, rightShoulder, mid, rPos, limbStartW, limbEndW, true, 0.78f, skin, true);
        }
    }

    static void drawIdleFrontLeg(Gdiplus::Graphics& g, Pt top, Pt bottom, bool isLeft, const SkinSpec& skin) {
        using namespace Gdiplus;
        const SkinPalette& pal = skin.palette;
        float sign = isLeft ? -1.0f : 1.0f;
        if (isDazed(skin)) {
            Pt shoulder = {top.x + sign * 4.0f, top.y - 10.0f};
            Pt elbow = {top.x + sign * 11.0f, top.y + 1.0f};
            Pt paw = {top.x + sign * 10.0f, top.y + 15.0f};
            drawLimb(g, shoulder, elbow, paw, 19.0f, 14.0f, !isLeft, 0.78f, skin, true);
            return;
        }

        if (skin.colorpoint()) {
            GraphicsPath lp;
            addRoundedRect(lp, bottom.x - 7.5f, top.y, 15.0f, bottom.y - top.y + 5.0f, 6.5f);
            float pad = 10.0f;
            float span = std::max(1.0f, (bottom.y + 5.0f) - top.y);
            float total = span + pad * 2.0f;
            LinearGradientBrush grad(PointF(bottom.x, top.y - pad), PointF(bottom.x, bottom.y + 5.0f + pad), withAlpha(pal.body, 0), withAlpha(pal.points, 255));
            grad.SetWrapMode(WrapModeTileFlipXY);
            Color cols[5] = { withAlpha(pal.body, 0), withAlpha(pal.body, 0), withAlpha(pal.pointsMid, 190), withAlpha(pal.points, 255), withAlpha(pal.points, 255) };
            REAL pos[5] = { 0.0f, pad / total, (pad + span * 0.50f) / total, (pad + span * 0.82f) / total, 1.0f };
            grad.SetInterpolationColors(cols, pos, 5);
            g.FillPath(&grad, &lp);
        } else {
            // Smooth shoulder-fade leg fill so palette.legs shows cleanly on idle sitting legs too
            // ("idleLegs": "legs"; the built-in coats use "chest" and keep their approved look)
            GraphicsPath legShape;
            addQuadBezier(legShape, { top.x + sign * 8.5f, top.y }, { top.x + sign * 9.5f, (top.y + bottom.y) * 0.5f }, { bottom.x + sign * 7.5f, bottom.y - 1.0f });
            addQuadBezier(legShape, { bottom.x + sign * 7.5f, bottom.y - 1.0f }, { bottom.x + sign * 7.0f, bottom.y + 5.2f }, { bottom.x + sign * 0.8f, bottom.y + 5.2f });
            addQuadBezier(legShape, { bottom.x + sign * 0.8f, bottom.y + 5.2f }, { bottom.x - sign * 6.2f, bottom.y + 5.2f }, { bottom.x - sign * 6.0f, bottom.y - 1.0f });
            addQuadBezier(legShape, { bottom.x - sign * 6.0f, bottom.y - 1.0f }, { top.x - sign * 6.5f, (top.y + bottom.y) * 0.5f }, { top.x - sign * 7.0f, top.y + 4.0f });
            legShape.CloseFigure();
            if (skin.idleLegsTinted) {
                float pad = 10.0f;
                float span = std::max(1.0f, (bottom.y + 5.0f) - top.y);
                float total = span + pad * 2.0f;
                LinearGradientBrush legGrad(PointF(bottom.x, top.y - pad), PointF(bottom.x, bottom.y + 5.0f + pad), withAlpha(pal.legs, 0), col(pal.legs));
                legGrad.SetWrapMode(WrapModeTileFlipXY);
                Color legCols[4] = { withAlpha(pal.legs, 0), withAlpha(pal.legs, 0), col(pal.legs), col(pal.legs) };
                REAL legPos[4] = { 0.0f, (pad + span * 0.04f) / total, (pad + span * 0.32f) / total, 1.0f };
                legGrad.SetInterpolationColors(legCols, legPos, 4);
                g.FillPath(&legGrad, &legShape);
            }

            SkinSpace armSpace = isLeft ? SkinSpace::LeftArm : SkinSpace::RightArm;
            if (skin.hasPartArt(armSpace)) {
                auto map = [&](SkinPoint p) {
                    float t = std::clamp(p.x / 100.0f, 0.0f, 1.0f);
                    float cx = top.x + (bottom.x - top.x) * t;
                    float cy = top.y + (bottom.y - top.y) * t;
                    float hw = 8.0f - 1.2f * t;
                    return PointF(cx + sign * (p.y / 10.0f) * hw, cy);
                };
                GraphicsState cs = g.Save();
                g.SetClip(&legShape, CombineModeIntersect);
                for (const SkinRegion& r : skin.regions) if (r.space == armSpace) drawRegion(g, r, map);
                for (const SkinMark& mk : skin.marks) if (mk.space == armSpace) drawMark(g, mk, map);
                g.Restore(cs);
            }

            if (whiteOutlineEnabled()) {
                Pen outPen(blackOutline(), BlackOutlineW * 1.8f);
                outPen.SetStartCap(LineCapRound); outPen.SetEndCap(LineCapRound);
                g.DrawArc(&outPen, bottom.x - 7.2f, bottom.y - 8.7f, 14.4f, 14.4f, 10.0f, 160.0f);
            }

            SolidBrush cuff(col(pal.paws));
            g.FillRectangle(&cuff, bottom.x-7.5f, bottom.y-13.0f, 15.0f, 13.0f);
            g.FillEllipse(&cuff, bottom.x-7.5f, bottom.y-5.0f, 15.0f, 10.0f);
        }
        Pen p(isClassicBlack(skin) ? blackOutline(190) : col(pal.crease), 1.45f);
        p.SetStartCap(LineCapRound); p.SetEndCap(LineCapRound);

        GraphicsPath p1;
        addQuadBezier(p1, { top.x + sign * 8.5f, top.y }, { top.x + sign * 9.5f, (top.y + bottom.y) * 0.5f }, { bottom.x + sign * 7.5f, bottom.y - 1.0f });
        g.DrawPath(&p, &p1);

        GraphicsPath p2;
        addQuadBezier(p2, { top.x - sign * 7.0f, top.y + 4.0f }, { top.x - sign * 6.5f, (top.y + bottom.y) * 0.5f }, { bottom.x - sign * 6.0f, bottom.y - 1.0f });
        g.DrawPath(&p, &p2);
    }

    static void drawDazedArm(Gdiplus::Graphics& g, Gdiplus::GraphicsPath& arm, const std::vector<Gdiplus::PointF>& left,
        const std::vector<Gdiplus::PointF>& right, Gdiplus::RectF paw) {
        using namespace Gdiplus;
        SolidBrush cloth(rgb(0x465189));
        g.FillPath(&cloth, &arm);

        constexpr float sleeveLength = 15.0f;
        float distance = 0.0f;
        for (size_t i = 1; i < left.size(); ++i) {
            float dx = (left[i].X + right[i].X - left[i - 1].X - right[i - 1].X) * 0.5f;
            float dy = (left[i].Y + right[i].Y - left[i - 1].Y - right[i - 1].Y) * 0.5f;
            float segment = std::hypot(dx, dy);
            // End the cuff at the same distance from the shoulder as the arm reaches.
            if (distance + segment < sleeveLength && i < left.size() - 1) {
                distance += segment;
                continue;
            }

            float t = std::clamp((sleeveLength - distance) / std::max(segment, 0.001f), 0.0f, 1.0f);
            auto interpolate = [](PointF from, PointF to, float fraction) {
                return PointF(from.X + (to.X - from.X) * fraction, from.Y + (to.Y - from.Y) * fraction);
            };
            PointF leftCuff = interpolate(left[i - 1], left[i], t);
            PointF rightCuff = interpolate(right[i - 1], right[i], t);
            PointF leftLip = interpolate(rightCuff, leftCuff, 1.23f);
            PointF rightLip = interpolate(leftCuff, rightCuff, 1.23f);
            auto offsetAlongArm = [dx, dy, segment](PointF point, float offset) {
                float scale = offset / std::max(segment, 0.001f);
                return PointF(point.X + dx * scale, point.Y + dy * scale);
            };
            PointF leftFront = offsetAlongArm(leftLip, 4.0f);
            PointF rightFront = offsetAlongArm(rightLip, 4.0f);
            GraphicsPath flare;
            flare.AddLine(offsetAlongArm(leftCuff, -8.0f), leftLip);
            flare.AddBezier(leftLip, leftFront, rightFront, rightLip);
            flare.AddLine(rightLip, offsetAlongArm(rightCuff, -8.0f));
            flare.CloseFigure();
            g.FillPath(&cloth, &flare);
            GraphicsPath opening;
            opening.AddBezier(leftLip, leftFront, rightFront, rightLip);
            opening.AddBezier(rightLip, offsetAlongArm(rightLip, -3.5f), offsetAlongArm(leftLip, -3.5f), leftLip);
            opening.CloseFigure();
            SolidBrush lining(rgb(0x252D54));
            g.FillPath(&lining, &opening);

            std::vector<PointF> forearm{leftCuff};
            forearm.insert(forearm.end(), left.begin() + i, left.end());
            for (size_t j = right.size(); j > i; --j) forearm.push_back(right[j - 1]);
            forearm.push_back(rightCuff);

            SolidBrush fur(rgb(0xE3C99F));
            g.FillPolygon(&fur, forearm.data(), static_cast<INT>(forearm.size()));
            drawDazedPaw(g, paw);
            Pen seam(rgb(0x8790C8), 1.25f);
            seam.SetStartCap(LineCapRound);
            seam.SetEndCap(LineCapRound);
            g.DrawBezier(&seam, leftLip, leftFront, rightFront, rightLip);
            break;
        }
    }

    static void drawLimb(Gdiplus::Graphics& g, Pt start, Pt ctrl, Pt end, float startW, float endW, bool outlineOnLeft,
        float outlineAlpha, const SkinSpec& skin, bool frontPaw = false) {
        using namespace Gdiplus;
        const SkinPalette& pal = skin.palette;
        constexpr int steps = 14;
        std::vector<PointF> leftEdge, rightEdge;
        leftEdge.reserve(steps + 1);
        rightEdge.reserve(steps + 1);

        for (int i = 0; i <= steps; ++i) {
            float t = (float)i / (float)steps;
            Pt p = quadPoint(start, ctrl, end, t);
            Pt tan = quadTangent(start, ctrl, end, t);
            float len = std::max(0.001f, std::hypot(tan.x, tan.y));
            float nx = -tan.y / len, ny = tan.x / len;
            float hw = (startW + (endW - startW) * t) * 0.5f;
            leftEdge.push_back(PointF(p.x + nx * hw, p.y + ny * hw));
            rightEdge.push_back(PointF(p.x - nx * hw, p.y - ny * hw));
        }

        std::vector<PointF> poly = leftEdge;
        for (int i = steps; i >= 0; --i) poly.push_back(rightEdge[i]);

        GraphicsPath limbPath;
        limbPath.AddLines(poly.data(), (INT)poly.size());
        Pt tangent=quadTangent(start,ctrl,end,0);
        float length=std::max(0.001f,std::hypot(tangent.x,tangent.y));
        Pt cap = {start.x - tangent.x / length * startW * 0.5f, start.y - tangent.y / length * startW * 0.5f};
        addQuadBezier(limbPath, {rightEdge[0].X,rightEdge[0].Y}, cap, {leftEdge[0].X,leftEdge[0].Y});
        limbPath.CloseFigure();

        float pawR = endW * 0.58f;
        RectF pawRect(end.x - pawR, end.y - pawR * 0.85f, pawR * 2.0f, pawR * 1.7f);
        const SkinColor& lineCol = pal.outline.set ? pal.outline : pal.crease;

        if (isDazed(skin)) {
            pawRect.Inflate(pawR * 0.28f, pawR * 0.46f);
            if (whiteOutlineEnabled()) {
                Pen outPen(blackOutline(), BlackOutlineW * 2.0f);
                outPen.SetStartCap(LineCapRound); outPen.SetEndCap(LineCapRound); outPen.SetLineJoin(LineJoinRound);
                if ((int)leftEdge.size() > 5) {
                    g.DrawLines(&outPen, leftEdge.data() + 4, (INT)leftEdge.size() - 4);
                    g.DrawLines(&outPen, rightEdge.data() + 4, (INT)rightEdge.size() - 4);
                }
                g.DrawEllipse(&outPen, pawRect);
            }
            if (frontPaw) {
                drawDazedArm(g, limbPath, leftEdge, rightEdge, pawRect);
            } else {
                SolidBrush fur(rgb(0xE3C99F));
                g.FillPath(&fur, &limbPath);
                drawDazedPaw(g, pawRect);
            }
            return;
        }

        if (whiteOutlineEnabled()) {
            Pen outPen(blackOutline(), BlackOutlineW * 2.0f);
            outPen.SetStartCap(LineCapRound); outPen.SetEndCap(LineCapRound); outPen.SetLineJoin(LineJoinRound);
            int rimStart = isClassicBlackRim(skin) ? 2 : 4;
            if ((int)leftEdge.size() > rimStart + 1) {
                g.DrawLines(&outPen, leftEdge.data() + rimStart, (INT)leftEdge.size() - rimStart);
                g.DrawLines(&outPen, rightEdge.data() + rimStart, (INT)rightEdge.size() - rimStart);
            }
            g.DrawEllipse(&outPen, pawRect);
        }
        if (isTabby(skin)) {
            tabby::drawLimb(g, limbPath, pawRect, start, ctrl, end, startW, endW);
        } else if (!skin.colorpoint()) {
            const SkinColor& limbBase = frontPaw ? pal.legs : (pal.hindLeg.set ? pal.hindLeg : pal.legs);
            const SkinColor& limbPaw = frontPaw ? pal.paws : (pal.hindPaw.set ? pal.hindPaw : pal.paws);
            Color legs = col(limbBase);
            SolidBrush b(legs);
            if (frontPaw && pal.belly.set && !pal.belly.sameAs(limbBase)) {
                // White chest fading into the leg colour along the first 30% of the arm.
                Color chest = col(pal.belly);
                LinearGradientBrush gradient(PointF(start.x,start.y),PointF(end.x,end.y),chest,legs);
                gradient.SetWrapMode(WrapModeTileFlipXY);
                Color colors[3]={chest,legs,legs};
                REAL positions[3]={0,0.30f,1};gradient.SetInterpolationColors(colors,positions,3);
                g.FillPath(&gradient,&limbPath);
            } else g.FillPath(&b, &limbPath);
            bool isLeftArm = frontPaw && !outlineOnLeft;
            SkinSpace limbSpace = frontPaw ? (isLeftArm ? SkinSpace::LeftArm : SkinSpace::RightArm) : SkinSpace::HindLeg;
            if (skin.hasPartArt(limbSpace)) {
                float sideSign = isLeftArm ? 1.0f : -1.0f;
                auto map = [&](SkinPoint pt) {
                    float t = std::clamp(pt.x / 100.0f, 0.0f, 1.0f);
                    Pt p = quadPoint(start, ctrl, end, t);
                    Pt tan = quadTangent(start, ctrl, end, t);
                    float len = std::max(0.001f, std::hypot(tan.x, tan.y));
                    float nx = -tan.y / len, ny = tan.x / len;
                    float hw = (startW + (endW - startW) * t) * 0.5f;
                    float off = sideSign * (pt.y / 10.0f) * hw;
                    return PointF(p.x + nx * off, p.y + ny * off);
                };
                GraphicsState cs = g.Save();
                g.SetClip(&limbPath, CombineModeIntersect);
                for (const SkinRegion& r : skin.regions) if (r.space == limbSpace) drawRegion(g, r, map);
                for (const SkinMark& mk : skin.marks) if (mk.space == limbSpace) drawMark(g, mk, map);
                g.Restore(cs);
            }
            if (limbPaw.sameAs(limbBase)) g.FillEllipse(&b, pawRect);
            else {
                std::vector<PointF> points; int first = (int)(steps*0.72f);
                for (int i=first; i<=steps; ++i) points.push_back(leftEdge[i]);
                for (int i=steps; i>=first; --i) points.push_back(rightEdge[i]);
                SolidBrush cuff(col(limbPaw));
                g.FillPolygon(&cuff, points.data(), (INT)points.size()); g.FillEllipse(&cuff, pawRect);
            }
        } else {
            // Pad gradient endpoints beyond limb geometry + use WrapModeTileFlipXY so GDI+
            // NEVER wraps t < 0 shoulder corners around to t = 1.0 dark espresso!
            float dx = end.x - start.x, dy = end.y - start.y;
            float span = std::hypot(dx, dy);
            float ux = (span > 1.0f) ? (dx / span) : 0.0f;
            float uy = (span > 1.0f) ? (dy / span) : 1.0f;
            span = std::max(1.0f, span);
            float padStart = startW + 18.0f;
            float padEnd = endW + 18.0f;
            float total = padStart + span + padEnd;

            PointF gStart(start.x - ux * padStart, start.y - uy * padStart);
            PointF gEnd(end.x + ux * padEnd, end.y + uy * padEnd);

            LinearGradientBrush grad(gStart, gEnd, withAlpha(pal.body, 0), withAlpha(pal.points, 255));
            grad.SetWrapMode(WrapModeTileFlipXY);
            Color cols[6] = {
                withAlpha(pal.body, 0),
                withAlpha(pal.body, 0),
                withAlpha(pal.body, 255),
                withAlpha(pal.pointsMid, 255),
                withAlpha(pal.points, 255),
                withAlpha(pal.points, 255)
            };
            REAL pos[6] = {
                0.0f,
                padStart / total,
                (padStart + span * 0.16f) / total,
                (padStart + span * 0.48f) / total,
                (padStart + span) / total,
                1.0f
            };
            grad.SetInterpolationColors(cols, pos, 6);
            g.FillPath(&grad, &limbPath);

            SolidBrush pawBrush(col(pal.paws));
            g.FillEllipse(&pawBrush, pawRect);

            const auto& outerEdge = outlineOnLeft ? rightEdge : leftEdge;
            Pen op(withAlpha(lineCol, 184), 1.25f);
            op.SetStartCap(LineCapRound); op.SetEndCap(LineCapRound); op.SetLineJoin(LineJoinRound);
            g.DrawLines(&op, outerEdge.data() + 3, (INT)outerEdge.size() - 4);
        }

        const auto& hiEdge = outlineOnLeft ? leftEdge : rightEdge;
        int startIdx = 2;
        int endIdx = (int)((hiEdge.size() - 1) * 0.68f);
        if (endIdx > startIdx && !isClassicBlack(skin)) {
            Color sc = skin.colorpoint()
                ? withAlpha(lineCol, (BYTE)(outlineAlpha * 199))
                : creaseWith(pal.crease, (BYTE)(outlineAlpha * 229));
            Pen hp(sc, 1.35f);
            hp.SetStartCap(LineCapRound); hp.SetEndCap(LineCapRound); hp.SetLineJoin(LineJoinRound);
            g.DrawLines(&hp, hiEdge.data() + startIdx, endIdx - startIdx + 1);
        }
    }

    // MARK: - Floating Mechanical Keycaps

    static void drawFloatingKeycaps(Gdiplus::Graphics& g, const CatPhysics& physics) {
        using namespace Gdiplus;
        FontFamily ff(L"Segoe UI");
        StringFormat sf;
        sf.SetAlignment(StringAlignmentCenter);
        sf.SetLineAlignment(StringAlignmentCenter);

        for (const auto& b : physics.floatingKeycaps) {
            float prog = b.age / b.lifetime;
            float scale = 1.0f;
            if (b.age < 0.09f) {
                scale = 0.72f + 0.38f * std::sin((b.age / 0.09f) * 3.14159f * 0.65f);
            } else if (b.age < 0.18f) {
                scale = 1.10f - 0.10f * ((b.age - 0.09f) / 0.09f);
            }

            float alphaF = prog < 0.62f ? 1.0f : std::max(0.0f, 1.0f - (prog - 0.62f) / 0.38f);
            BYTE a = (BYTE)(alphaF * 255.0f);
            if (a < 4) continue;

            size_t len = b.label.size();
            bool hasWide = !b.label.empty() && b.label[0] > 0x7F;
            float w = (len <= 1) ? 23.0f : (len == 2 ? (hasWide ? 34.0f : 30.0f) : 38.0f);
            float h = 22.0f;

            GraphicsState st = g.Save();
            g.TranslateTransform(b.position.x, b.position.y);
            g.RotateTransform(b.rotation * RadToDeg);
            g.ScaleTransform(scale, scale);

            GraphicsPath basePath;
            addRoundedRect(basePath, -w * 0.5f, -h * 0.5f + 2.5f, w, h, 5.5f);
            SolidBrush baseBrush(Color((BYTE)(alphaF * 242), 38, 38, 43));
            g.FillPath(&baseBrush, &basePath);

            GraphicsPath facePath;
            addRoundedRect(facePath, -w * 0.5f, -h * 0.5f, w, h, 5.2f);
            SolidBrush faceBrush(Color(a, 249, 248, 243));
            Pen facePen(Color(a, 41, 41, 46), 1.45f);
            g.FillPath(&faceBrush, &facePath);
            g.DrawPath(&facePen, &facePath);

            Font font(&ff, len <= 1 ? 11.0f : 9.2f, FontStyleBold, UnitPixel);
            SolidBrush txtBrush(Color(a, 31, 31, 36));
            g.DrawString(b.label.c_str(), -1, &font, RectF(-w * 0.5f, -h * 0.5f, w, h), &sf, &txtBrush);

            g.Restore(st);
        }
    }

    // MARK: - Petting Sparkles & Sleep Z

    static void drawSparkles(Gdiplus::Graphics& g, const CatPhysics& physics, EyeColorTheme eyeTheme) {
        using namespace Gdiplus;
        Color baseCol = eyePrimary(eyeTheme);
        FontFamily ff(L"Segoe UI");

        for (const auto& sp : physics.sparkles) {
            float p = std::min(1.0f, sp.age / sp.lifetime);
            BYTE a = (BYTE)(std::sin(p * 3.14159f) * 215.0f);
            if (a < 4) continue;

            Color c(a, baseCol.GetR(), baseCol.GetG(), baseCol.GetB());
            if (sp.isSleepZ) {
                Font f(&ff, 11.0f + p * 3.0f, FontStyleBold, UnitPixel);
                SolidBrush sb(c);
                g.DrawString(L"z", -1, &f, PointF(sp.position.x, sp.position.y), &sb);
            } else {
                float r = 3.5f + p * 1.5f;
                GraphicsState st = g.Save();
                g.TranslateTransform(sp.position.x, sp.position.y);
                GraphicsPath star;
                addQuadBezier(star, {0, -r}, {0.8f, -0.8f}, {r, 0});
                addQuadBezier(star, {r, 0}, {0.8f, 0.8f}, {0, r});
                addQuadBezier(star, {0, r}, {-0.8f, 0.8f}, {-r, 0});
                addQuadBezier(star, {-r, 0}, {-0.8f, -0.8f}, {0, -r});
                star.CloseFigure();
                SolidBrush sb(c);
                g.FillPath(&sb, &star);
                g.Restore(st);
            }
        }
    }

    // MARK: - Pixel-Traced Xiao Douni (Video 1 & Video 2) & Universal Scruff-Drag Renderer

    static void setRound(Gdiplus::Pen& p) {
        p.SetLineCap(Gdiplus::LineCapRound, Gdiplus::LineCapRound, Gdiplus::DashCapRound);
        p.SetLineJoin(Gdiplus::LineJoinRound);
    }

    static Gdiplus::Color scaleAlpha(Gdiplus::Color c, float factor) {
        BYTE a = (BYTE)std::clamp((int)std::lround((float)c.GetA() * std::clamp(factor, 0.0f, 1.0f)), 0, 255);
        return Gdiplus::Color(a, c.GetR(), c.GetG(), c.GetB());
    }

    static Gdiplus::Color withColorAlpha(Gdiplus::Color c, float alpha01) {
        BYTE a = (BYTE)std::clamp((int)std::lround(std::clamp(alpha01, 0.0f, 1.0f) * 255.0f), 0, 255);
        return Gdiplus::Color(a, c.GetR(), c.GetG(), c.GetB());
    }

    static float lerpF(float a, float b, float t) {
        return a + (b - a) * t;
    }

    static Pt lerpPt(Pt a, Pt b, float t) {
        return { a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t };
    }

    static float smoothstep(float edge0, float edge1, float x) {
        float t = std::clamp((x - edge0) / std::max(0.0001f, edge1 - edge0), 0.0f, 1.0f);
        return t * t * (3.0f - 2.0f * t);
    }

    static Gdiplus::Color douniInkColor()   { return Gdiplus::Color(255, 38, 30, 24); }    // #261E18
    static Gdiplus::Color douniCreamColor() { return Gdiplus::Color(255, 246, 239, 230); } // #F6EFE6
    static Gdiplus::Color douniTaupeColor() { return Gdiplus::Color(255, 168, 147, 123); } // #A8937B
    static Gdiplus::Color douniIceIris()    { return Gdiplus::Color(255, 216, 239, 234); } // #D8EFEA
    static Gdiplus::Color douniV2Sclera()   { return Gdiplus::Color(255, 234, 235, 231); } // #EAEBE7

    /// Draws a sub-layer in arbitrary logical rect `(x, y, w, h)` with uniform alpha compositing (no-op fast path when alpha >= 0.995).
    template <typename Fn>
    static void drawWithRectLayerAlpha(Gdiplus::Graphics& g, float x, float y, float w, float h, float alpha, Fn&& drawFn) {
        using namespace Gdiplus;
        if (alpha <= 0.005f) return;
        if (alpha >= 0.995f) {
            drawFn(g);
            return;
        }
        Matrix mat;
        g.GetTransform(&mat);
        REAL m[6] = {};
        mat.GetElements(m);
        float sx = std::hypot(m[0], m[1]);
        float sy = std::hypot(m[2], m[3]);
        float ss = std::clamp(std::max(sx, sy), 0.35f, 3.0f);
        int bw = std::max(1, (int)std::ceil(w * ss));
        int bh = std::max(1, (int)std::ceil(h * ss));

        Bitmap layer(bw, bh, PixelFormat32bppPARGB);
        if (layer.GetLastStatus() != Ok) {
            drawFn(g);
            return;
        }
        {
            Graphics lg(&layer);
            lg.Clear(Color(0, 0, 0, 0));
            lg.SetSmoothingMode(SmoothingModeAntiAlias);
            lg.SetPixelOffsetMode(PixelOffsetModeHighQuality);
            lg.SetTextRenderingHint(TextRenderingHintAntiAliasGridFit);
            lg.ScaleTransform((float)bw / w, (float)bh / h);
            lg.TranslateTransform(-x, -y);
            drawFn(lg);
        }
        ColorMatrix cm = { {
            { 1.0f, 0.0f, 0.0f, 0.0f,  0.0f },
            { 0.0f, 1.0f, 0.0f, 0.0f,  0.0f },
            { 0.0f, 0.0f, 1.0f, 0.0f,  0.0f },
            { 0.0f, 0.0f, 0.0f, alpha, 0.0f },
            { 0.0f, 0.0f, 0.0f, 0.0f,  1.0f }
        } };
        ImageAttributes ia;
        ia.SetColorMatrix(&cm, ColorMatrixFlagsDefault, ColorAdjustTypeBitmap);
        PointF dest[3] = {
            PointF(x, y),
            PointF(x + w, y),
            PointF(x, y + h)
        };
        g.DrawImage(&layer, dest, 3, 0.0f, 0.0f, (REAL)bw, (REAL)bh, UnitPixel, &ia);
    }

    /// Draws a sub-layer in logical 360x320 space with uniform alpha compositing (no-op fast path when alpha >= 0.995).
    template <typename Fn>
    static void drawWithLayerAlpha(Gdiplus::Graphics& g, float alpha, Fn&& drawFn) {
        drawWithRectLayerAlpha(g, 0.0f, 0.0f, CatPhysics::CanvasWidth, CatPhysics::CanvasHeight, alpha, std::forward<Fn>(drawFn));
    }

    /// Clamped linear gradient matching CoreGraphics [.drawsBeforeStartLocation, .drawsAfterEndLocation] without wrap artifacts.
    static void fillClampedLinearGradient(
        Gdiplus::Graphics& g,
        const Gdiplus::GraphicsPath* path,
        const Gdiplus::RectF* rect,
        Gdiplus::PointF p0,
        Gdiplus::PointF p1,
        const Gdiplus::Color* cols,
        const Gdiplus::REAL* locs,
        INT count
    ) {
        using namespace Gdiplus;
        if (count <= 0) return;
        float dx = p1.X - p0.X;
        float dy = p1.Y - p0.Y;
        float span = std::hypot(dx, dy);
        if (span < 1.0f || count == 1) {
            SolidBrush sb(cols[count - 1]);
            if (path) g.FillPath(&sb, path);
            else if (rect && rect->Width > 0.0f && rect->Height > 0.0f) g.FillRectangle(&sb, *rect);
            return;
        }
        float ux = dx / span, uy = dy / span;
        constexpr float pad = 1200.0f;
        float total = span + 2.0f * pad;
        PointF gStart(p0.X - ux * pad, p0.Y - uy * pad);
        PointF gEnd(p1.X + ux * pad, p1.Y + uy * pad);

        std::vector<Color> extCols((size_t)count + 2);
        std::vector<REAL> extPos((size_t)count + 2);
        extCols[0] = cols[0];
        extPos[0] = 0.0f;
        for (INT i = 0; i < count; ++i) {
            extCols[(size_t)i + 1] = cols[i];
            float lp = (pad + span * std::clamp((float)locs[i], 0.0f, 1.0f)) / total;
            extPos[(size_t)i + 1] = std::clamp(lp, extPos[(size_t)i], 1.0f);
        }
        extCols[(size_t)count + 1] = cols[count - 1];
        extPos[(size_t)count + 1] = 1.0f;

        LinearGradientBrush brush(gStart, gEnd, extCols.front(), extCols.back());
        brush.SetWrapMode(WrapModeTileFlipXY);
        brush.SetInterpolationColors(extCols.data(), extPos.data(), count + 2);
        if (path) g.FillPath(&brush, path);
        else if (rect && rect->Width > 0.0f && rect->Height > 0.0f) g.FillRectangle(&brush, *rect);
    }

    /// Rounded arbitrary quadrilateral path with exact circular-arc cubic Bezier corners (mirrors CGPath.addArc(tangent1End:tangent2End:radius:)).
    static void addRoundedQuadPath(Gdiplus::GraphicsPath& p, Pt tl, Pt tr, Pt br, Pt bl, float radius) {
        using namespace Gdiplus;
        const Pt v[4] = { tl, tr, br, bl };
        Pt a[4], b[4];
        PointF c1[4], c2[4];
        for (int i = 0; i < 4; ++i) {
            Pt prev = v[(i + 3) & 3];
            Pt cur  = v[i];
            Pt next = v[(i + 1) & 3];
            float d1x = prev.x - cur.x, d1y = prev.y - cur.y;
            float d2x = next.x - cur.x, d2y = next.y - cur.y;
            float l1 = std::max(0.001f, std::hypot(d1x, d1y));
            float l2 = std::max(0.001f, std::hypot(d2x, d2y));
            float u1x = d1x / l1, u1y = d1y / l1;
            float u2x = d2x / l2, u2y = d2y / l2;
            float dot = std::clamp(u1x * u2x + u1y * u2y, -0.999f, 0.999f);
            float halfTheta = 0.5f * std::acos(dot);
            float tanHalf = std::max(0.20f, std::tan(halfTheta));
            float t = std::min(radius / tanHalf, std::min(l1, l2) * 0.45f);
            float actualR = t * tanHalf;
            float sweep = 3.14159265f - 2.0f * halfTheta;
            float h = (4.0f / 3.0f) * std::tan(sweep * 0.25f) * actualR;
            a[i] = { cur.x + u1x * t, cur.y + u1y * t };
            b[i] = { cur.x + u2x * t, cur.y + u2y * t };
            c1[i] = PointF(a[i].x - u1x * h, a[i].y - u1y * h);
            c2[i] = PointF(b[i].x - u2x * h, b[i].y - u2y * h);
        }
        for (int i = 0; i < 4; ++i) {
            if (i > 0) p.AddLine(PointF(b[i - 1].x, b[i - 1].y), PointF(a[i].x, a[i].y));
            p.AddBezier(PointF(a[i].x, a[i].y), c1[i], c2[i], PointF(b[i].x, b[i].y));
        }
        p.CloseFigure();
    }

    static void drawRadialGlow(Gdiplus::Graphics& g, Pt center, float radius, Gdiplus::Color color) {
        using namespace Gdiplus;
        if (radius < 1.0f || color.GetA() == 0) return;
        GraphicsPath gp;
        gp.AddEllipse(center.x - radius, center.y - radius, radius * 2.0f, radius * 2.0f);
        PathGradientBrush pgb(&gp);
        pgb.SetCenterPoint(PointF(center.x, center.y));
        pgb.SetCenterColor(color);
        Color surr[1] = { Color(0, color.GetR(), color.GetG(), color.GetB()) };
        INT cnt = 1;
        pgb.SetSurroundColors(surr, &cnt);
        g.FillPath(&pgb, &gp);
    }

    /// Super-rounded marshmallow oval head matching Video 1 & Video 2's flat-topped, chubby-cheeked silhouette.
    static void addDouniMochiOvalPath(Gdiplus::GraphicsPath& p, float cx, float cy, float rx, float ry,
                                      float kx = 0.63f, float ky = 0.60f) {
        using namespace Gdiplus;
        PointF top(cx, cy - ry);
        PointF right(cx + rx, cy);
        PointF bot(cx, cy + ry);
        PointF left(cx - rx, cy);
        p.AddBezier(top,   PointF(cx + rx * kx, cy - ry), PointF(cx + rx, cy - ry * ky), right);
        p.AddBezier(right, PointF(cx + rx, cy + ry * ky), PointF(cx + rx * kx, cy + ry), bot);
        p.AddBezier(bot,   PointF(cx - rx * kx, cy + ry), PointF(cx - rx, cy + ry * ky), left);
        p.AddBezier(left,  PointF(cx - rx, cy - ry * ky), PointF(cx - rx * kx, cy - ry), top);
        p.CloseFigure();
    }

    struct V2PoseOverride {
        float leftPose = 0.0f;
        float rightPose = 0.0f;
        float mouseBlend = 0.0f;
    };

    /// Top-level Xiao Douni scene router inside KuroCat's 360x320 canvas.
    static void drawDouniScene(
        Gdiplus::Graphics& g,
        const CatPhysics& physics,
        const SkinSpec& skin,
        const KeyboardSkinSpec& kbSkin,
        EyeColorTheme eyeTheme,
        bool marquee
    ) {
        using namespace Gdiplus;
        float scruff = std::clamp(physics.scruffDrag.value, 0.0f, 1.0f);
        float scruffS = smoothstep(0.0f, 1.0f, scruff);
        float loafRaw = std::clamp(physics.douniLoafBlend.value, 0.0f, 1.0f);
        float loafS = smoothstep(0.0f, 1.0f, loafRaw);

        if (scruff > 0.02f) {
            float deskFade = 1.0f - smoothstep(0.0f, 0.48f, scruffS);
            if (deskFade > 0.01f && loafS < 0.85f) {
                drawWithLayerAlpha(g, deskFade * (1.0f - loafS), [&](Graphics& lg) {
                    GraphicsState s = lg.Save();
                    lg.TranslateTransform(0.0f, scruffS * 28.0f);
                    drawDouniV2InCanvas(lg, physics, skin, kbSkin, eyeTheme, marquee, 0.0f);
                    lg.Restore(s);
                });
            }
            if (deskFade > 0.01f && loafS > 0.02f) {
                drawWithLayerAlpha(g, deskFade * loafS, [&](Graphics& lg) {
                    GraphicsState s = lg.Save();
                    lg.TranslateTransform(0.0f, scruffS * 20.0f);
                    drawDouniV1LoafInCanvas(lg, physics, skin, 1.0f);
                    lg.Restore(s);
                });
            }
            // Smoothly lift out of her resting seat instead of snapping into place!
            GraphicsState ds = g.Save();
            g.TranslateTransform((1.0f - scruffS) * 40.0f * (1.0f - loafS), (1.0f - scruffS) * 30.0f);
            drawVideo1DragCatInCanvas(g, physics, skin, eyeTheme, scruff);
            g.Restore(ds);
            return;
        }

        // Smooth Disney choreographed morph between Video 2 Desk Scene and Video 1 Mochi Loaf!
        if (loafS < 0.99f) {
            drawDouniV2InCanvas(g, physics, skin, kbSkin, eyeTheme, marquee, loafS);
        }

        if (loafS > 0.01f) {
            drawDouniV1LoafInCanvas(g, physics, skin, loafS);
        }
    }

    /// Maps Video 1 Rest/Pet/Sleep (1000x750) cleanly into 360x320 canvas with Disney pop-squish align-and-settle morph (zero double ghosting!).
    static void drawDouniV1LoafInCanvas(
        Gdiplus::Graphics& g,
        const CatPhysics& physics,
        const SkinSpec& skin,
        float loafMorph = 1.0f
    ) {
        using namespace Gdiplus;
        float m = std::clamp(loafMorph, 0.0f, 1.0f);
        // Tight swap window [0.36..0.56] right when V2 cat has already glided & squished into Loaf's exact spot!
        float alpha = smoothstep(0.36f, 0.56f, m);
        if (alpha <= 0.01f) return;
        // Arrival slide finishes by m = 0.62, then playful mochi bounce-settle overshoots flat and rebounds to 1.0!
        float arrive = smoothstep(0.30f, 0.64f, m);
        float settlePhase = std::clamp((m - 0.52f) / 0.48f, 0.0f, 1.0f);
        float bounce = std::sin(settlePhase * 3.14159265f) * 0.08f * (1.0f - settlePhase * 0.35f);

        drawWithLayerAlpha(g, alpha, [&](Graphics& lg) {
            GraphicsState st = lg.Save();
            constexpr float scale = 0.345f;
            float tx = 20.0f + physics.bodyShiftX.value + (1.0f - arrive) * 26.0f;
            float ty = 46.0f - (1.0f - arrive) * 14.0f;
            float pivotX = tx + 440.0f * scale;
            float pivotY = ty + 616.0f * scale;
            float sx = 0.94f + 0.06f * arrive + bounce;
            float sy = 1.08f - 0.08f * arrive - bounce * 1.15f;
            lg.TranslateTransform(pivotX, pivotY);
            lg.ScaleTransform(sx, sy);
            lg.TranslateTransform(-pivotX, -pivotY);
            lg.TranslateTransform(tx, ty);
            lg.ScaleTransform(scale, scale);
            drawDouniV1LoafInSpace(lg, physics, skin, true);
            lg.Restore(st);
        });
    }

    /// Maps Universal Video 1 Drag (1000x750) cleanly into 360x320 canvas.
    static void drawVideo1DragCatInCanvas(
        Gdiplus::Graphics& g,
        const CatPhysics& physics,
        const SkinSpec& skin,
        EyeColorTheme eyeTheme,
        float lift
    ) {
        using namespace Gdiplus;
        float liftS = smoothstep(0.0f, 1.0f, lift);
        float startleTarget = 0.0f;
        if (physics.isScruffDragging_) {
            if (physics.scruffHoldTime < 0.14f) {
                startleTarget = 1.0f;
            } else {
                startleTarget = std::max(0.0f, 1.0f - (physics.scruffHoldTime - 0.14f) / 0.07f);
            }
        } else {
            startleTarget = (physics.scruffDropTimer > 0.01f) ? std::min(1.0f, physics.scruffDropTimer / 0.12f) : 1.0f;
        }
        float swing = std::clamp(physics.scruffSwing.value * 0.38f, -0.32f, 0.32f) + std::sin(physics.time * 4.6f) * 0.055f * (1.0f - startleTarget);

        drawWithLayerAlpha(g, smoothstep(0.0f, 0.22f, lift), [&](Graphics& lg) {
            GraphicsState st = lg.Save();
            constexpr float scale = 0.330f;
            float tx = 24.0f + physics.bodyShiftX.value - physics.scruffSwing.value * 14.0f;
            float ty = 68.0f - liftS * 22.0f + physics.scruffSwingY.value * 8.0f + std::sin(physics.time * 3.8f) * 2.5f * (1.0f - startleTarget);
            lg.TranslateTransform(tx, ty);
            lg.ScaleTransform(scale, scale);
            drawVideo1DragInSpace(lg, physics, skin, eyeTheme, startleTarget, swing);
            lg.Restore(st);
        });
    }

    /// Maps Video 2 Typing/Idle/Mouse/Tablet scene (832x720) cleanly into 360x320 canvas.
    static void drawDouniV2InCanvas(
        Gdiplus::Graphics& g,
        const CatPhysics& physics,
        const SkinSpec& skin,
        const KeyboardSkinSpec& kbSkin,
        EyeColorTheme eyeTheme,
        bool marquee,
        float loafMorph = 0.0f
    ) {
        using namespace Gdiplus;
        GraphicsState st = g.Save();
        constexpr float scale = 0.405f;
        float tx = 14.0f + physics.bodyShiftX.value;
        float ty = 22.0f;
        g.TranslateTransform(tx, ty);
        g.ScaleTransform(scale, scale);
        drawDouniV2InSpace(g, physics, skin, kbSkin, eyeTheme, marquee, true, nullptr, loafMorph);
        g.Restore(st);
    }

    // MARK: - V1Space (1000 x 750) Pixel-Exact Video 1 Rest / Pet / Sleep Loaf

    static void drawDouniV1LoafInSpace(
        Gdiplus::Graphics& g,
        const CatPhysics& physics,
        const SkinSpec& skin,
        bool showStatusAccents = true
    ) {
        using namespace Gdiplus;
        Color ink = skin.palette.outline.set ? col(skin.palette.outline) : douniInkColor();
        Color cream = col(skin.palette.body);
        Color taupe = skin.palette.points.set ? col(skin.palette.points) : col(skin.palette.paws);
        constexpr float lw = 13.2f;

        bool isPet = showStatusAccents && (physics.petHeadIntensity > 0.12f || physics.petBodyIntensity > 0.22f);
        bool isSleep = showStatusAccents && physics.sleepiness > 0.45f && !isPet;
        float petAmt = isPet ? std::max(physics.petHeadIntensity, physics.petBodyIntensity) : 0.0f;
        float breathWave = showStatusAccents ? std::sin(physics.time * (isSleep ? 1.7f : 2.3f)) : 0.0f;
        float squishY = 1.0f - petAmt * 0.065f + breathWave * (isSleep ? 0.028f : 0.015f);
        float squishX = 1.0f + petAmt * 0.032f - breathWave * (isSleep ? 0.014f : 0.008f);
        float purrShiftX = isPet ? std::sin(physics.time * 13.0f) * 4.5f * petAmt : 0.0f;

        GraphicsState st = g.Save();
        g.TranslateTransform(440.0f + purrShiftX, 616.0f);
        g.ScaleTransform(squishX, squishY);
        g.TranslateTransform(-440.0f, -616.0f);

        Pen inkPen(ink, lw);
        setRound(inkPen);
        SolidBrush taupeBrush(taupe);
        SolidBrush creamBrush(cream);

        // Prebuild loaf paths so Pass 0 paints a single unified white sticker outline behind the entire loaf
        GraphicsPath backPaw, backDome, leftPaw, rightPaw, loafHeadRim;
        backPaw.AddBezier(786.0f, 492.0f, 852.0f, 472.0f, 898.0f, 506.0f, 896.0f, 554.0f);
        backPaw.AddBezier(896.0f, 554.0f, 894.0f, 590.0f, 866.0f, 602.0f, 830.0f, 598.0f);
        backPaw.AddBezier(830.0f, 598.0f, 802.0f, 596.0f, 784.0f, 588.0f, 778.0f, 576.0f);
        backPaw.CloseFigure();

        backDome.AddBezier(338.0f, 318.0f, 400.0f, 282.0f, 486.0f, 272.0f, 562.0f, 274.0f);
        backDome.AddBezier(562.0f, 274.0f, 702.0f, 278.0f, 836.0f, 368.0f, 838.0f, 492.0f);
        backDome.AddBezier(838.0f, 492.0f, 840.0f, 562.0f, 790.0f, 594.0f, 708.0f, 594.0f);
        backDome.AddLine(708.0f, 594.0f, 340.0f, 590.0f);
        backDome.CloseFigure();

        leftPaw.AddBezier(118.0f, 478.0f, 54.0f, 474.0f, 8.0f, 506.0f, 8.0f, 554.0f);
        leftPaw.AddBezier(8.0f, 554.0f, 8.0f, 590.0f, 38.0f, 600.0f, 86.0f, 598.0f);
        leftPaw.AddLine(86.0f, 598.0f, 158.0f, 594.0f);
        leftPaw.CloseFigure();

        rightPaw.AddBezier(542.0f, 586.0f, 540.0f, 534.0f, 576.0f, 506.0f, 632.0f, 508.0f);
        rightPaw.AddBezier(632.0f, 508.0f, 688.0f, 508.0f, 724.0f, 538.0f, 724.0f, 588.0f);
        rightPaw.AddBezier(724.0f, 588.0f, 724.0f, 626.0f, 682.0f, 636.0f, 632.0f, 635.0f);
        rightPaw.AddBezier(632.0f, 635.0f, 578.0f, 634.0f, 544.0f, 622.0f, 542.0f, 586.0f);
        rightPaw.CloseFigure();

        addV1UnifiedHeadWithEarsPath(loafHeadRim, 380.0f, 472.0f, 292.0f, 144.0f, 165.0f, 0.0f);
        if (whiteOutlineEnabled()) {
            Pen rimPen(blackOutline(), lw + 10.6f);
            setRound(rimPen);
            g.DrawPath(&rimPen, &backPaw);
            g.DrawPath(&rimPen, &backDome);
            g.DrawPath(&rimPen, &leftPaw);
            g.DrawPath(&rimPen, &loafHeadRim);
            g.DrawPath(&rimPen, &rightPaw);
        }

        // 1. Far back paw peeking right
        {
            g.FillPath(&taupeBrush, &backPaw);
            g.DrawPath(&inkPen, &backPaw);
            Pen toePen(ink, lw * 0.88f);
            setRound(toePen);
            g.DrawLine(&toePen, 844.0f, 574.0f, 855.0f, 594.0f);
            g.DrawLine(&toePen, 872.0f, 562.0f, 884.0f, 580.0f);
        }

        // 2. Cream loaf back dome behind head
        {
            g.FillPath(&creamBrush, &backDome);
            g.DrawPath(&inkPen, &backDome);
        }

        // 3. Left front paw peeking out under left cheek
        {
            g.FillPath(&taupeBrush, &leftPaw);
            g.DrawPath(&inkPen, &leftPaw);
            Pen toePen(ink, lw * 0.90f);
            setRound(toePen);
            g.DrawLine(&toePen, 50.0f, 564.0f, 50.0f, 596.0f);
            g.DrawLine(&toePen, 90.0f, 562.0f, 90.0f, 596.0f);
        }

        // 4-6. Unified Seamless Head + Ears Silhouette (ONE continuous closed outline — zero seam or floating gap!)
        drawV1UnifiedHeadAndEars(
            g, 380.0f, 472.0f, 292.0f, 144.0f, 165.0f, 0.0f,
            cream, taupe, ink, lw,
            { 376.0f, 474.0f }, 98.0f, 78.0f,
            isPet ? 0.34f * petAmt : 0.0f
        );

        // 7. Bold dark curved closed-eye lines (︶ ︶)
        {
            Pen eyePen(ink, lw * 1.10f);
            setRound(eyePen);
            GraphicsPath lEye, rEye;
            addQuadBezier(lEye, { 174.0f, 452.0f }, { 264.0f, 453.0f }, { 334.0f, 488.0f });
            addQuadBezier(rEye, { 410.0f, 490.0f }, { 486.0f, 456.0f }, { 576.0f, 462.0f });
            g.DrawPath(&eyePen, &lEye);
            g.DrawPath(&eyePen, &rEye);
        }

        // 8. Right front paw IN FRONT of lower-right cheek
        {
            g.FillPath(&taupeBrush, &rightPaw);
            g.DrawPath(&inkPen, &rightPaw);
            Pen toePen(ink, lw * 0.90f);
            setRound(toePen);
            g.DrawLine(&toePen, 591.0f, 596.0f, 591.0f, 632.0f);
            g.DrawLine(&toePen, 636.0f, 598.0f, 636.0f, 633.0f);
        }

        // 9. Whiskers (upper-left \ \ and right shoulder / /)
        {
            Pen wPen(ink, lw * 0.95f);
            setRound(wPen);
            g.DrawLine(&wPen,  69.0f, 259.0f, 110.0f, 326.0f);
            g.DrawLine(&wPen,  46.0f, 307.0f,  89.0f, 341.0f);
            g.DrawLine(&wPen, 614.0f, 318.0f, 636.0f, 286.0f);
            g.DrawLine(&wPen, 642.0f, 328.0f, 665.0f, 298.0f);
        }

        g.Restore(st);

        // 10. Optional comic petting heart or sleeping Zzz floating cleanly above the loaf
        if (isPet) {
            float phase = std::fmod(physics.time * 1.4f, 1.0f);
            if (phase < 0.0f) phase += 1.0f;
            float hy = 152.0f - phase * 62.0f;
            float hx = 684.0f + std::sin(physics.time * 3.2f) * 16.0f;
            float alpha = std::min(1.0f, (1.0f - phase) * 1.6f) * std::min(1.0f, petAmt * 1.4f);
            drawComicHeart(g, { hx, hy }, 32.0f, alpha, ink);
        } else if (isSleep) {
            for (int i = 0; i < 2; ++i) {
                float p = std::fmod(physics.time * 0.45f + (float)i * 0.5f, 1.0f);
                if (p < 0.0f) p += 1.0f;
                float zx = 668.0f + p * 74.0f + std::sin(p * 5.0f) * 12.0f;
                float zy = 218.0f - p * 112.0f;
                float alpha = std::sin(p * 3.14159265f) * std::min(1.0f, physics.sleepiness * 1.3f);
                float sz = 24.0f + p * 18.0f;
                drawComicZ(g, { zx, zy }, sz, alpha, ink);
            }
        }
    }

    // MARK: - V1Space (1000 x 750) Video 1 Lifted / Startled Drag Pose

    static void drawVideo1DragInSpace(
        Gdiplus::Graphics& g,
        const CatPhysics& physics,
        const SkinSpec& skin,
        EyeColorTheme eyeTheme,
        float startle,
        float swing
    ) {
        using namespace Gdiplus;
        (void)physics;
        float s = std::clamp(startle, 0.0f, 1.0f);
        bool isDouni = (skin.renderStyle == SkinRenderStyle::Douni);
        bool isBlackRim = isClassicBlackRim(skin);

        Color bodyColor = isDouni ? douniCreamColor() : col(skin.palette.body);
        Color earOuterColor = isDouni ? douniTaupeColor() : col(skin.palette.earOuter);
        bool hasEarInner = !isDouni && skin.palette.earInner.set;
        Color earInnerColor = hasEarInner ? col(skin.palette.earInner) : Color(0, 0, 0, 0);
        Color pointColor = isDouni ? douniTaupeColor() : (skin.palette.points.set ? col(skin.palette.points) : col(skin.palette.earOuter));
        Color legColor = isDouni ? douniTaupeColor() : col(skin.palette.paws);
        Color tailColor = isDouni ? douniTaupeColor() : col(skin.palette.tail);
        Color inkColor = isDouni
            ? (skin.palette.outline.set ? col(skin.palette.outline) : douniInkColor())
            : (isBlackRim ? Color(255, 10, 10, 10)
               : (skin.colorpoint() ? Color(255, 69, 54, 43)
                  : (skin.palette.outline.set ? col(skin.palette.outline) : Color(255, 41, 36, 31))));
        Color toeInkColor = isBlackRim ? Color(87, 217, 217, 217) : inkColor;
        float lw = isDouni ? 13.5f : (isBlackRim ? 7.5f : 10.2f);
        float whiteRimW = lw + 11.0f;

        // Interpolated head coordinates: v1_06 (s=0) <-> v1_05 (s=1)
        float headCX = lerpF(400.0f, 380.0f, s);
        float headCY = lerpF(236.0f, 333.0f, s);
        constexpr float headRX = 292.0f;
        float headRY = lerpF(148.0f, 149.0f, s);
        float headTopY = headCY - headRY;
        float earShiftX = headCX - 380.0f;
        float earTipY = headTopY - 164.0f;

        GraphicsPath headPath, backPath;
        addV1UnifiedHeadWithEarsPath(headPath, headCX, headCY, headRX, headRY, earTipY, earShiftX);
        addV1DragBackPath(backPath, s);

        GraphicsPath tailFill, tailStroke;
        buildV1DragTailPaths(tailFill, tailStroke, s, swing);
        GraphicsPath backLeftFill, backLeftStroke;
        buildV1DragBackLeftLegPaths(backLeftFill, backLeftStroke, s, swing);
        GraphicsPath backRightFill, backRightStroke;
        buildV1DragBackRightLegPaths(backRightFill, backRightStroke, s, swing);
        GraphicsPath frontLeftFill, frontLeftStroke;
        buildV1DragFrontLeftLegPaths(frontLeftFill, frontLeftStroke, s, swing);
        GraphicsPath frontRightFill, frontRightStroke;
        buildV1DragFrontRightLegPaths(frontRightFill, frontRightStroke, s, swing);

        // Pass 0 (ALL skins): crisp sticker-style outer white silhouette rim (open paths prevent internal white dashes!)
        if (whiteOutlineEnabled()) {
            Pen rimPen(blackOutline(), whiteRimW);
            setRound(rimPen);
            if (s < 0.45f) g.DrawPath(&rimPen, &tailStroke);
            g.DrawPath(&rimPen, &backLeftStroke);
            g.DrawPath(&rimPen, &backRightStroke);
            g.DrawPath(&rimPen, &backPath);
            g.DrawPath(&rimPen, &frontLeftStroke);
            g.DrawPath(&rimPen, &frontRightStroke);
            g.DrawPath(&rimPen, &headPath);
        }

        // 1. Limp hanging tail behind right hip (fades behind back during startle/touchdown s -> 1)
        if (s < 0.85f) {
            float tailAlpha = 1.0f - smoothstep(0.45f, 0.85f, s);
            if (tailAlpha > 0.01f) {
                if (isDouni || skin.colorpoint()) {
                    Color cols[2] = { scaleAlpha(bodyColor, tailAlpha), scaleAlpha(tailColor, tailAlpha) };
                    REAL locs[2] = { 0.0f, 1.0f };
                    fillClampedLinearGradient(g, &tailFill, nullptr, PointF(0.0f, 225.0f), PointF(0.0f, 325.0f), cols, locs, 2);
                } else {
                    SolidBrush tb(scaleAlpha(tailColor, tailAlpha));
                    g.FillPath(&tb, &tailFill);
                }
                Pen tPen(scaleAlpha(inkColor, tailAlpha), lw);
                setRound(tPen);
                g.DrawPath(&tPen, &tailStroke);
            }
        }

        // 2. Back-left inner leg peeking under belly
        std::vector<std::pair<Pt, Pt>> blToes;
        if (s > 0.85f) {
            blToes.push_back({ { lerpF(576.0f, 338.0f, s), lerpF(456.0f, 578.0f, s) },
                               { lerpF(574.0f, 332.0f, s), lerpF(472.0f, 598.0f, s) } });
            blToes.push_back({ { lerpF(594.0f, 360.0f, s), lerpF(458.0f, 580.0f, s) },
                               { lerpF(592.0f, 354.0f, s), lerpF(472.0f, 600.0f, s) } });
        }
        drawV1Limb(g, backLeftFill, backLeftStroke, bodyColor, legColor,
                   lerpF(404.0f, 515.0f, s), lerpF(440.0f, 560.0f, s),
                   isDouni || skin.colorpoint(), inkColor, toeInkColor, lw, blToes);

        // 3. Arched back & torso dome
        {
            SolidBrush bb(bodyColor);
            g.FillPath(&bb, &backPath);
            if (!isDouni) {
                GraphicsState bs = g.Save();
                g.SetClip(&backPath, CombineModeIntersect);
                drawV1SkinBackMarkings(g, skin, s);
                g.Restore(bs);
            }
            Pen bp(inkColor, lw);
            setRound(bp);
            g.DrawPath(&bp, &backPath);
        }

        // 4. Back-right chubby hind leg (open top seam merges cleanly into rump!)
        {
            Pt brPivot = { lerpF(710.0f, 810.0f, s), lerpF(345.0f, 470.0f, s) };
            float brAng = swing * (1.0f - s);
            std::vector<std::pair<Pt, Pt>> brToes = {
                { v1RotatePoint({ lerpF(684.0f, 808.0f, s), lerpF(452.0f, 574.0f, s) }, brPivot, brAng),
                  v1RotatePoint({ lerpF(682.0f, 818.0f, s), lerpF(485.0f, 600.0f, s) }, brPivot, brAng) },
                { v1RotatePoint({ lerpF(712.0f, 838.0f, s), lerpF(455.0f, 566.0f, s) }, brPivot, brAng),
                  v1RotatePoint({ lerpF(710.0f, 850.0f, s), lerpF(486.0f, 592.0f, s) }, brPivot, brAng) }
            };
            drawV1Limb(g, backRightFill, backRightStroke, bodyColor, legColor,
                       lerpF(330.0f, 468.0f, s), lerpF(405.0f, 540.0f, s),
                       isDouni || skin.colorpoint(), inkColor, toeInkColor, lw, brToes);
        }

        // 5. Front-left & Front-right dangling legs (open top seam merges cleanly into chest!)
        {
            Pt flPivot = { lerpF(276.0f, 198.0f, s), lerpF(352.0f, 430.0f, s) };
            float flAng = swing * (1.0f - s);
            std::vector<std::pair<Pt, Pt>> flToes = {
                { v1RotatePoint({ lerpF(272.0f, 108.0f, s), lerpF(516.0f, 566.0f, s) }, flPivot, flAng),
                  v1RotatePoint({ lerpF(272.0f, 102.0f, s), lerpF(552.0f, 598.0f, s) }, flPivot, flAng) },
                { v1RotatePoint({ lerpF(304.0f, 146.0f, s), lerpF(514.0f, 570.0f, s) }, flPivot, flAng),
                  v1RotatePoint({ lerpF(304.0f, 142.0f, s), lerpF(548.0f, 601.0f, s) }, flPivot, flAng) }
            };
            drawV1Limb(g, frontLeftFill, frontLeftStroke, bodyColor, legColor,
                       lerpF(354.0f, 432.0f, s), lerpF(420.0f, 498.0f, s),
                       isDouni || skin.colorpoint(), inkColor, toeInkColor, lw, flToes);
        }
        {
            Pt frPivot = { lerpF(514.0f, 586.0f, s), lerpF(362.0f, 442.0f, s) };
            float frAng = swing * (1.0f - s);
            std::vector<std::pair<Pt, Pt>> frToes = {
                { v1RotatePoint({ lerpF(478.0f, 598.0f, s), lerpF(532.0f, 592.0f, s) }, frPivot, frAng),
                  v1RotatePoint({ lerpF(478.0f, 598.0f, s), lerpF(568.0f, 626.0f, s) }, frPivot, frAng) },
                { v1RotatePoint({ lerpF(510.0f, 636.0f, s), lerpF(534.0f, 590.0f, s) }, frPivot, frAng),
                  v1RotatePoint({ lerpF(510.0f, 638.0f, s), lerpF(568.0f, 624.0f, s) }, frPivot, frAng) }
            };
            drawV1Limb(g, frontRightFill, frontRightStroke, bodyColor, legColor,
                       lerpF(366.0f, 448.0f, s), lerpF(436.0f, 516.0f, s),
                       isDouni || skin.colorpoint(), inkColor, toeInkColor, lw, frToes);
        }

        // 6-7. Unified Seamless Head + Ears Silhouette
        if (isDouni) {
            drawV1UnifiedHeadAndEars(
                g, headCX, headCY, headRX, headRY, earTipY, earShiftX,
                bodyColor, pointColor, inkColor, lw,
                { headCX - 8.0f, headCY + lerpF(-12.0f, 0.0f, s) }, 88.0f, 78.0f, 0.0f
            );
        } else {
            drawV1DouniEar(g, true, headTopY + 8.0f, earTipY, earShiftX, earOuterColor, inkColor, lw, false, hasEarInner, earInnerColor);
            drawV1DouniEar(g, false, headTopY + 8.0f, earTipY, earShiftX, earOuterColor, inkColor, lw, false, hasEarInner, earInnerColor);
            SolidBrush hb(bodyColor);
            g.FillPath(&hb, &headPath);
            GraphicsState hs = g.Save();
            g.SetClip(&headPath, CombineModeIntersect);
            drawV1SkinHeadMarkings(g, skin, headCX, headCY, headRX, headRY);
            g.Restore(hs);
            Pen hp(inkColor, lw);
            setRound(hp);
            g.DrawPath(&hp, &headPath);
        }

        // 8. Huge Watery Anime Boba Eyes (v1_06 full wide open <-> v1_05 flat half-lidded!)
        Color irisColor = isDouni
            ? douniIceIris()
            : blendColor(skin.palette.iris.set ? col(skin.palette.iris) : eyePrimary(eyeTheme), Color(255, 255, 255, 255), 0.28f);
        Pt leftEyeCenter  = { lerpF(273.0f, 268.0f, s), lerpF(223.0f, 324.0f, s) };
        Pt rightEyeCenter = { lerpF(510.0f, 501.0f, s), lerpF(222.0f, 324.0f, s) };
        float eyeRX = lerpF(87.0f, 89.0f, s);
        float eyeRY = lerpF(91.0f, 84.0f, s);
        drawV1WateryEye(g, leftEyeCenter, eyeRX, eyeRY, true, irisColor, inkColor, lw, s, isBlackRim);
        drawV1WateryEye(g, rightEyeCenter, eyeRX + 2.0f, eyeRY, false, irisColor, inkColor, lw, s, isBlackRim);

        // Optional cute tiny nose on patterned non-Douni cats
        if (!isDouni && !isBlackRim && !skin.colorpoint()) {
            Color noseC = skin.palette.nose.set ? col(skin.palette.nose) : Color(235, 230, 143, 148);
            SolidBrush nb(noseC);
            float ny = headCY + lerpF(44.0f, 52.0f, s);
            g.FillEllipse(&nb, headCX - 14.0f, ny - 9.0f, 28.0f, 18.0f);
        }

        // 9. Whiskers on upper-left (just like v1_05 & v1_06!)
        {
            Pen wPen(isBlackRim ? Color(230, 235, 235, 235) : inkColor, lw * 0.92f);
            setRound(wPen);
            if (s < 0.5f) {
                g.DrawLine(&wPen, 84.0f,  18.0f, 132.0f,  92.0f);
                g.DrawLine(&wPen, 62.0f,  74.0f, 108.0f, 108.0f);
            } else {
                g.DrawLine(&wPen, 56.0f, 168.0f, 118.0f, 184.0f);
                g.DrawLine(&wPen, 62.0f, 222.0f, 106.0f, 214.0f);
            }
        }
    }

    // MARK: - V1Space Geometry & Sub-Helpers

    static Pt v1RotatePoint(Pt pt, Pt pivot, float angle) {
        float dx = pt.x - pivot.x, dy = pt.y - pivot.y;
        float c = std::cos(angle), s = std::sin(angle);
        return { pivot.x + dx * c - dy * s, pivot.y + dx * s + dy * c };
    }

    /// ONE continuous closed path pixel-traced directly from Video 1's original head + ears contour (maxErr ~ 1.2px on 1000x750!).
    static void addV1UnifiedHeadWithEarsPath(
        Gdiplus::GraphicsPath& p,
        float headCX, float headCY, float headRX, float headRY,
        float earTipY, float shiftX
    ) {
        using namespace Gdiplus;
        float headTopY = headCY - headRY;
        Pt leftEarOut  = { headCX - headRX * 0.709f, headCY - headRY * 0.903f };
        Pt leftEarTip  = { 284.0f + shiftX, earTipY };
        Pt leftEarIn   = { 339.0f + shiftX, headTopY };
        Pt rightEarIn  = { 399.0f + shiftX, headTopY };
        Pt rightEarTip = { 460.0f + shiftX, earTipY };
        Pt rightEarOut = { headCX + headRX * 0.640f, headCY - headRY * 0.945f };
        float cheekY   = headCY - headRY * 0.021f;
        Pt rightCheek  = { headCX + headRX * 1.000f, cheekY };
        Pt chin        = { headCX, headCY + headRY * 1.007f };
        Pt leftCheek   = { headCX - headRX * 1.002f, cheekY };

        // Left ear outer -> tip -> inner (directly traced to v1_01 ink centerline)
        p.AddBezier(PointF(leftEarOut.x, leftEarOut.y),
                    PointF(202.0f + shiftX, lerpF(leftEarOut.y, earTipY, 0.345f)),
                    PointF(214.0f + shiftX, lerpF(leftEarOut.y, earTipY, 0.853f)),
                    PointF(leftEarTip.x, leftEarTip.y));
        p.AddBezier(PointF(leftEarTip.x, leftEarTip.y),
                    PointF(350.0f + shiftX, lerpF(leftEarIn.y, earTipY, 0.897f)),
                    PointF(329.0f + shiftX, lerpF(leftEarIn.y, earTipY, 0.320f)),
                    PointF(leftEarIn.x, leftEarIn.y));
        // Smooth crown bridge between ears
        addQuadBezier(p, leftEarIn, { 369.0f + shiftX, headTopY - 1.0f }, rightEarIn);
        // Right ear inner -> tip -> outer
        p.AddBezier(PointF(rightEarIn.x, rightEarIn.y),
                    PointF(416.0f + shiftX, lerpF(rightEarIn.y, earTipY, 0.308f)),
                    PointF(403.0f + shiftX, lerpF(rightEarIn.y, earTipY, 0.856f)),
                    PointF(rightEarTip.x, rightEarTip.y));
        p.AddBezier(PointF(rightEarTip.x, rightEarTip.y),
                    PointF(529.0f + shiftX, lerpF(rightEarOut.y, earTipY, 0.876f)),
                    PointF(539.0f + shiftX, lerpF(rightEarOut.y, earTipY, 0.344f)),
                    PointF(rightEarOut.x, rightEarOut.y));
        // Full soft plump mochi cheeks directly traced from Video 1 ink centerline (ZERO flat diagonal slopes or corner kinks!)
        p.AddBezier(PointF(rightEarOut.x, rightEarOut.y),
                    PointF(headCX + headRX * 0.838f, headCY - headRY * 0.818f),
                    PointF(headCX + headRX * 1.020f, headCY - headRY * 0.470f),
                    PointF(rightCheek.x, rightCheek.y));
        p.AddBezier(PointF(rightCheek.x, rightCheek.y),
                    PointF(headCX + headRX * 0.976f, headCY + headRY * 0.924f),
                    PointF(headCX + headRX * 0.352f, headCY + headRY * 1.054f),
                    PointF(chin.x, chin.y));
        p.AddBezier(PointF(chin.x, chin.y),
                    PointF(headCX - headRX * 0.346f, headCY + headRY * 1.009f),
                    PointF(headCX - headRX * 0.972f, headCY + headRY * 0.927f),
                    PointF(leftCheek.x, leftCheek.y));
        p.AddBezier(PointF(leftCheek.x, leftCheek.y),
                    PointF(headCX - headRX * 1.014f, headCY - headRY * 0.419f),
                    PointF(headCX - headRX * 0.866f, headCY - headRY * 0.720f),
                    PointF(leftEarOut.x, leftEarOut.y));
        p.CloseFigure();
    }

    static void drawV1UnifiedHeadAndEars(
        Gdiplus::Graphics& g,
        float headCX, float headCY, float headRX, float headRY,
        float earTipY, float shiftX,
        Gdiplus::Color cream, Gdiplus::Color taupe, Gdiplus::Color ink, float lw,
        Pt muzzleCenter, float muzzleRX, float muzzleRY, float petBlushAlpha
    ) {
        using namespace Gdiplus;
        float headTopY = headCY - headRY;
        GraphicsPath unified;
        addV1UnifiedHeadWithEarsPath(unified, headCX, headCY, headRX, headRY, earTipY, shiftX);

        // 1. Cream base fill across unified head+ears
        SolidBrush creamBrush(cream);
        g.FillPath(&creamBrush, &unified);

        // 2. Clipped interior shading: soft vertical ear-to-forehead taupe gradients + muzzle + optional blush
        {
            GraphicsState cs = g.Save();
            g.SetClip(&unified, CombineModeIntersect);

            Color earCols[3] = { taupe, taupe, Color(0, cream.GetR(), cream.GetG(), cream.GetB()) };
            REAL earLocs[3] = { 0.0f, 0.78f, 1.0f };
            float bandH = std::max(1.0f, (headTopY + 34.0f) - (earTipY - 12.0f));
            RectF leftBand(145.0f + shiftX, earTipY - 12.0f, 205.0f, bandH);
            fillClampedLinearGradient(g, nullptr, &leftBand, PointF(260.0f + shiftX, earTipY), PointF(260.0f + shiftX, headTopY + 28.0f), earCols, earLocs, 3);
            RectF rightBand(390.0f + shiftX, earTipY - 12.0f, 205.0f, bandH);
            fillClampedLinearGradient(g, nullptr, &rightBand, PointF(470.0f + shiftX, earTipY), PointF(470.0f + shiftX, headTopY + 28.0f), earCols, earLocs, 3);

            drawSoftTaupePatch(g, muzzleCenter, muzzleRX, muzzleRY, taupe, 0.78f);

            if (petBlushAlpha > 0.01f) {
                SolidBrush blush(Color((BYTE)std::clamp((int)std::lround(petBlushAlpha * 255.0f), 0, 255), 255, 143, 153));
                g.FillEllipse(&blush, 158.0f + shiftX, headCY + 14.0f, 74.0f, 34.0f);
                g.FillEllipse(&blush, 514.0f + shiftX, headCY + 14.0f, 74.0f, 34.0f);
            }
            g.Restore(cs);
        }

        // 3. Single unbroken bold ink contour around the fused head + ears!
        Pen inkPen(ink, lw);
        setRound(inkPen);
        g.DrawPath(&inkPen, &unified);

        // 4. Signature 3-stroke inner ear tufts (|||) cleanly anchored inside the fused ears
        drawV1EarTufts(g, true, headTopY + 12.0f, shiftX, ink, lw);
        drawV1EarTufts(g, false, headTopY + 12.0f, shiftX, ink, lw);
    }

    static void addV1EarOpenPath(Gdiplus::GraphicsPath& p, bool isLeft, float baseY, float tipY, float shiftX) {
        using namespace Gdiplus;
        if (isLeft) {
            p.AddBezier(PointF(171.0f + shiftX, baseY + 14.0f),
                        PointF(204.0f + shiftX, lerpF(baseY, tipY, 0.56f)),
                        PointF(242.0f + shiftX, tipY),
                        PointF(278.0f + shiftX, tipY));
            p.AddBezier(PointF(278.0f + shiftX, tipY),
                        PointF(318.0f + shiftX, tipY),
                        PointF(338.0f + shiftX, lerpF(baseY, tipY, 0.48f)),
                        PointF(342.0f + shiftX, baseY + 4.0f));
        } else {
            p.AddBezier(PointF(398.0f + shiftX, baseY + 4.0f),
                        PointF(402.0f + shiftX, lerpF(baseY, tipY, 0.48f)),
                        PointF(420.0f + shiftX, tipY),
                        PointF(455.0f + shiftX, tipY));
            p.AddBezier(PointF(455.0f + shiftX, tipY),
                        PointF(496.0f + shiftX, tipY),
                        PointF(536.0f + shiftX, lerpF(baseY, tipY, 0.56f)),
                        PointF(568.0f + shiftX, baseY + 14.0f));
        }
    }

    static void drawV1EarTufts(Gdiplus::Graphics& g, bool isLeft, float baseY, float shiftX, Gdiplus::Color ink, float lw) {
        using namespace Gdiplus;
        Pen pen(ink, lw * 0.85f);
        setRound(pen);
        if (isLeft) {
            g.DrawLine(&pen, 256.0f + shiftX, baseY - 6.0f, 248.0f + shiftX, baseY - 34.0f);
            g.DrawLine(&pen, 282.0f + shiftX, baseY - 7.0f, 274.0f + shiftX, baseY - 48.0f);
            g.DrawLine(&pen, 306.0f + shiftX, baseY - 6.0f, 300.0f + shiftX, baseY - 66.0f);
        } else {
            g.DrawLine(&pen, 434.0f + shiftX, baseY - 6.0f, 441.0f + shiftX, baseY - 66.0f);
            g.DrawLine(&pen, 460.0f + shiftX, baseY - 7.0f, 469.0f + shiftX, baseY - 48.0f);
            g.DrawLine(&pen, 486.0f + shiftX, baseY - 6.0f, 500.0f + shiftX, baseY - 34.0f);
        }
    }

    static void drawV1DouniEar(
        Gdiplus::Graphics& g, bool isLeft, float baseY, float tipY, float shiftX,
        Gdiplus::Color fill, Gdiplus::Color ink, float lw, bool drawTufts,
        bool hasInnerFill, Gdiplus::Color innerFill
    ) {
        using namespace Gdiplus;
        GraphicsPath closedPath, openPath;
        addV1EarOpenPath(openPath, isLeft, baseY, tipY, shiftX);
        addV1EarOpenPath(closedPath, isLeft, baseY, tipY, shiftX);
        closedPath.CloseFigure();

        SolidBrush fb(fill);
        g.FillPath(&fb, &closedPath);
        if (hasInnerFill) {
            GraphicsState cs = g.Save();
            g.SetClip(&closedPath, CombineModeIntersect);
            GraphicsPath ip;
            if (isLeft) {
                addQuadBezier(ip, { 212.0f + shiftX, baseY + 6.0f }, { 234.0f + shiftX, lerpF(baseY, tipY, 0.45f) }, { 274.0f + shiftX, tipY + 42.0f });
                addQuadBezier(ip, { 274.0f + shiftX, tipY + 42.0f }, { 312.0f + shiftX, lerpF(baseY, tipY, 0.40f) }, { 320.0f + shiftX, baseY + 6.0f });
            } else {
                addQuadBezier(ip, { 420.0f + shiftX, baseY + 6.0f }, { 428.0f + shiftX, lerpF(baseY, tipY, 0.40f) }, { 458.0f + shiftX, tipY + 42.0f });
                addQuadBezier(ip, { 458.0f + shiftX, tipY + 42.0f }, { 504.0f + shiftX, lerpF(baseY, tipY, 0.45f) }, { 528.0f + shiftX, baseY + 6.0f });
            }
            ip.CloseFigure();
            SolidBrush ib(innerFill);
            g.FillPath(&ib, &ip);
            g.Restore(cs);
        }
        Pen pen(ink, lw);
        setRound(pen);
        g.DrawPath(&pen, &openPath);
        if (drawTufts) {
            drawV1EarTufts(g, isLeft, baseY, shiftX, ink, lw);
        }
    }

    static void drawSoftTaupePatch(Gdiplus::Graphics& g, Pt center, float rx, float ry, Gdiplus::Color color, float solidStop = 0.72f) {
        using namespace Gdiplus;
        rx = std::max(1.0f, rx);
        ry = std::max(1.0f, ry);
        GraphicsPath ep;
        ep.AddEllipse(center.x - rx, center.y - ry, rx * 2.0f, ry * 2.0f);
        PathGradientBrush pgb(&ep);
        pgb.SetCenterPoint(PointF(center.x, center.y));
        // GDI+ PathGradientBrush stops run outer edge (0.0) -> center (1.0)
        Color cols[3] = {
            Color(0, color.GetR(), color.GetG(), color.GetB()),
            scaleAlpha(color, 0.96f),
            color
        };
        REAL pos[3] = {
            0.0f,
            std::clamp(1.0f - solidStop, 0.02f, 0.98f),
            1.0f
        };
        pgb.SetInterpolationColors(cols, pos, 3);
        g.FillPath(&pgb, &ep);
    }

    static void drawV1Limb(
        Gdiplus::Graphics& g,
        const Gdiplus::GraphicsPath& fillPath,
        const Gdiplus::GraphicsPath& strokePath,
        Gdiplus::Color topColor,
        Gdiplus::Color pawColor,
        float gradientTopY,
        float gradientBotY,
        bool useGradient,
        Gdiplus::Color ink,
        Gdiplus::Color toeInk,
        float lw,
        const std::vector<std::pair<Pt, Pt>>& toes
    ) {
        using namespace Gdiplus;
        if (useGradient) {
            Color cols[2] = { topColor, pawColor };
            REAL locs[2] = { 0.0f, 1.0f };
            fillClampedLinearGradient(g, &fillPath, nullptr, PointF(0.0f, gradientTopY), PointF(0.0f, gradientBotY), cols, locs, 2);
        } else {
            SolidBrush pb(pawColor);
            g.FillPath(&pb, &fillPath);
        }
        Pen pen(ink, lw);
        setRound(pen);
        g.DrawPath(&pen, &strokePath);
        if (!toes.empty()) {
            Pen tPen(toeInk, lw * 0.88f);
            setRound(tPen);
            for (const auto& seg : toes) {
                g.DrawLine(&tPen, seg.first.x, seg.first.y, seg.second.x, seg.second.y);
            }
        }
    }

    static void addV1DragBackPath(Gdiplus::GraphicsPath& p, float s) {
        using namespace Gdiplus;
        PointF p0(lerpF(346.0f, 352.0f, s), lerpF( 88.0f, 178.0f, s));
        PointF p1(lerpF(548.0f, 580.0f, s), lerpF( -6.0f, 124.0f, s));
        PointF p2(lerpF(765.0f, 836.0f, s), lerpF(236.0f, 442.0f, s));
        PointF p3(lerpF(624.0f, 720.0f, s), lerpF(414.0f, 540.0f, s));
        PointF p4(lerpF(282.0f, 276.0f, s), lerpF(388.0f, 524.0f, s));
        p.AddBezier(p0, PointF(lerpF(418.0f, 420.0f, s), lerpF( 14.0f, 134.0f, s)), PointF(lerpF(488.0f, 514.0f, s), lerpF(-10.0f, 120.0f, s)), p1);
        p.AddBezier(p1, PointF(lerpF(672.0f, 744.0f, s), lerpF(  6.0f, 172.0f, s)), PointF(lerpF(768.0f, 838.0f, s), lerpF(112.0f, 304.0f, s)), p2);
        p.AddBezier(p2, PointF(lerpF(764.0f, 834.0f, s), lerpF(348.0f, 526.0f, s)), PointF(lerpF(708.0f, 782.0f, s), lerpF(412.0f, 542.0f, s)), p3);
        p.AddBezier(p3, PointF(lerpF(512.0f, 558.0f, s), lerpF(418.0f, 536.0f, s)), PointF(lerpF(378.0f, 362.0f, s), lerpF(404.0f, 528.0f, s)), p4);
        p.CloseFigure();
    }

    static void buildV1DragTailPaths(Gdiplus::GraphicsPath& closed, Gdiplus::GraphicsPath& open, float s, float swing) {
        using namespace Gdiplus;
        Pt pivot = { 754.0f, 222.0f };
        float ang = swing * 1.18f * (1.0f - s);
        auto pt = [&](float x, float y) -> PointF {
            Pt r = v1RotatePoint({ x, y }, pivot, ang);
            return PointF(r.x, r.y);
        };
        auto build = [&](GraphicsPath& gp) {
            gp.AddBezier(pt(726.0f, 224.0f), pt(730.0f, 326.0f), pt(722.0f, 444.0f), pt(724.0f, 520.0f));
            gp.AddBezier(pt(724.0f, 520.0f), pt(726.0f, 554.0f), pt(744.0f, 568.0f), pt(764.0f, 566.0f));
            gp.AddBezier(pt(764.0f, 566.0f), pt(790.0f, 564.0f), pt(804.0f, 540.0f), pt(804.0f, 504.0f));
            gp.AddBezier(pt(804.0f, 504.0f), pt(806.0f, 390.0f), pt(796.0f, 286.0f), pt(766.0f, 212.0f));
        };
        build(open);
        build(closed);
        closed.CloseFigure();
    }

    static void buildV1DragBackLeftLegPaths(Gdiplus::GraphicsPath& closed, Gdiplus::GraphicsPath& open, float s, float swing) {
        using namespace Gdiplus;
        Pt pivot = { lerpF(590.0f, 368.0f, s), lerpF(404.0f, 524.0f, s) };
        float ang = swing * 0.9f * (1.0f - s);
        auto lp = [&](Pt a, Pt b) -> PointF {
            Pt r = v1RotatePoint(lerpPt(a, b, s), pivot, ang);
            return PointF(r.x, r.y);
        };
        auto build = [&](GraphicsPath& gp) {
            PointF p0 = lp({ 568.0f, 404.0f }, { 318.0f, 524.0f });
            PointF p1 = lp({ 586.0f, 474.0f }, { 350.0f, 602.0f });
            PointF p2 = lp({ 616.0f, 404.0f }, { 434.0f, 526.0f });
            gp.AddBezier(p0, lp({ 564.0f, 446.0f }, { 304.0f, 576.0f }), lp({ 572.0f, 472.0f }, { 318.0f, 602.0f }), p1);
            gp.AddBezier(p1, lp({ 606.0f, 476.0f }, { 398.0f, 600.0f }), lp({ 616.0f, 448.0f }, { 428.0f, 564.0f }), p2);
        };
        build(open);
        build(closed);
        closed.CloseFigure();
    }

    static void buildV1DragBackRightLegPaths(Gdiplus::GraphicsPath& closed, Gdiplus::GraphicsPath& open, float s, float swing) {
        using namespace Gdiplus;
        Pt pivot = { lerpF(710.0f, 810.0f, s), lerpF(345.0f, 470.0f, s) };
        float ang = swing * 1.0f * (1.0f - s);
        auto lp = [&](Pt a, Pt b) -> PointF {
            Pt r = v1RotatePoint(lerpPt(a, b, s), pivot, ang);
            return PointF(r.x, r.y);
        };
        auto build = [&](GraphicsPath& gp) {
            PointF p0 = lp({ 654.0f, 398.0f }, { 758.0f, 526.0f });
            PointF p1 = lp({ 706.0f, 489.0f }, { 822.0f, 601.0f });
            PointF p2 = lp({ 774.0f, 332.0f }, { 876.0f, 534.0f });
            PointF p3 = lp({ 756.0f, 298.0f }, { 836.0f, 468.0f });
            gp.AddBezier(p0, lp({ 642.0f, 454.0f }, { 760.0f, 582.0f }), lp({ 668.0f, 490.0f }, { 786.0f, 602.0f }), p1);
            gp.AddBezier(p1, lp({ 756.0f, 486.0f }, { 870.0f, 598.0f }), lp({ 780.0f, 424.0f }, { 882.0f, 568.0f }), p2);
            gp.AddBezier(p2, lp({ 770.0f, 312.0f }, { 866.0f, 492.0f }), lp({ 762.0f, 302.0f }, { 848.0f, 474.0f }), p3);
        };
        build(open);
        build(closed);
        closed.CloseFigure();
    }

    static void buildV1DragFrontLeftLegPaths(Gdiplus::GraphicsPath& closed, Gdiplus::GraphicsPath& open, float s, float swing) {
        using namespace Gdiplus;
        Pt pivot = { lerpF(276.0f, 198.0f, s), lerpF(352.0f, 430.0f, s) };
        float ang = swing * 1.05f * (1.0f - s);
        auto lp = [&](Pt a, Pt b) -> PointF {
            Pt r = v1RotatePoint(lerpPt(a, b, s), pivot, ang);
            return PointF(r.x, r.y);
        };
        auto build = [&](GraphicsPath& gp) {
            PointF p0 = lp({ 208.0f, 356.0f }, { 146.0f, 428.0f });
            PointF p1 = lp({ 288.0f, 554.0f }, { 138.0f, 601.0f });
            PointF p2 = lp({ 348.0f, 376.0f }, { 282.0f, 484.0f });
            gp.AddBezier(p0, lp({ 204.0f, 472.0f }, {  66.0f, 520.0f }), lp({ 222.0f, 554.0f }, {  74.0f, 602.0f }), p1);
            gp.AddBezier(p1, lp({ 356.0f, 554.0f }, { 226.0f, 600.0f }), lp({ 358.0f, 478.0f }, { 274.0f, 544.0f }), p2);
        };
        build(open);
        build(closed);
        closed.CloseFigure();
    }

    static void buildV1DragFrontRightLegPaths(Gdiplus::GraphicsPath& closed, Gdiplus::GraphicsPath& open, float s, float swing) {
        using namespace Gdiplus;
        Pt pivot = { lerpF(514.0f, 586.0f, s), lerpF(362.0f, 442.0f, s) };
        float ang = swing * 1.05f * (1.0f - s);
        auto lp = [&](Pt a, Pt b) -> PointF {
            Pt r = v1RotatePoint(lerpPt(a, b, s), pivot, ang);
            return PointF(r.x, r.y);
        };
        auto build = [&](GraphicsPath& gp) {
            PointF p0 = lp({ 458.0f, 382.0f }, { 498.0f, 472.0f });
            PointF p1 = lp({ 498.0f, 571.0f }, { 616.0f, 626.0f });
            PointF p2 = lp({ 578.0f, 372.0f }, { 656.0f, 448.0f });
            gp.AddBezier(p0, lp({ 454.0f, 472.0f }, { 494.0f, 590.0f }), lp({ 432.0f, 570.0f }, { 558.0f, 628.0f }), p1);
            gp.AddBezier(p1, lp({ 564.0f, 570.0f }, { 696.0f, 622.0f }), lp({ 586.0f, 482.0f }, { 690.0f, 536.0f }), p2);
        };
        build(open);
        build(closed);
        closed.CloseFigure();
    }

    static void drawV1WateryEye(
        Gdiplus::Graphics& g, Pt center, float rx, float ry, bool isLeft,
        Gdiplus::Color iris, Gdiplus::Color ink, float lw, float s, bool isBlackRim
    ) {
        using namespace Gdiplus;
        RectF eyeRect(center.x - rx, center.y - ry, rx * 2.0f, ry * 2.0f);
        float lidY = center.y - ry - 6.0f + s * (ry * 0.80f);

        {
            GraphicsState st = g.Save();
            if (s > 0.02f) {
                g.SetClip(RectF(center.x - rx - 14.0f, lidY, rx * 2.0f + 28.0f, ry * 2.0f + 28.0f), CombineModeIntersect);
            }

            // 1. Watery iris fill
            SolidBrush irisBrush(iris);
            g.FillEllipse(&irisBrush, eyeRect);

            // 2. Giant glossy black pupil shifted slightly upward so luminous iris forms a thick bottom/outer crescent
            {
                GraphicsState ec = g.Save();
                GraphicsPath ep;
                ep.AddEllipse(eyeRect);
                g.SetClip(&ep, CombineModeIntersect);

                float pRX = rx * 0.86f;
                float pRY = ry * 0.81f;
                Pt pCenter = { center.x + (isLeft ? 4.0f : -2.0f), center.y - ry * 0.14f + s * 10.0f };
                SolidBrush blackBrush(Color(255, 0, 0, 0));
                g.FillEllipse(&blackBrush, pCenter.x - pRX, pCenter.y - pRY, pRX * 2.0f, pRY * 2.0f);

                // 3. Two crisp pure-white Video 1 catchlights (large upper round oval + small lower sparkle)
                SolidBrush whiteBrush(Color(255, 255, 255, 255));
                float bigDX = isLeft ? 19.0f : -21.0f;
                float bigDY = lerpF(-34.0f, -4.0f, s);
                float bigRX = isLeft ? 26.0f : 28.0f;
                float bigRY = isLeft ? 21.0f : 22.0f;
                g.FillEllipse(&whiteBrush, center.x + bigDX - bigRX, center.y + bigDY - bigRY, bigRX * 2.0f, bigRY * 2.0f);

                float smDX = isLeft ? 28.0f : -8.0f;
                float smDY = lerpF(24.0f, 34.0f, s);
                constexpr float smR = 11.0f;
                g.FillEllipse(&whiteBrush, center.x + smDX - smR, center.y + smDY - smR, smR * 2.0f, smR * 2.0f);
                g.Restore(ec);
            }

            // 4. Outer eye border stroke
            Pen borderPen(isBlackRim ? Color(255, 41, 41, 41) : ink, lw * 0.94f);
            setRound(borderPen);
            g.DrawEllipse(&borderPen, eyeRect);
            g.Restore(st);
        }

        // Crisp deadpan flat horizontal upper eyelid line when startled (v1_05!)
        if (s > 0.04f) {
            float dy = lidY - center.y;
            float ratio = std::clamp(dy / std::max(1.0f, ry), -0.98f, 0.98f);
            float halfSpan = rx * std::sqrt(std::max(0.04f, 1.0f - ratio * ratio)) + 3.0f;
            Pen lidPen(isBlackRim ? Color(235, 230, 230, 230) : ink, lw * 0.96f);
            setRound(lidPen);
            g.DrawLine(&lidPen, center.x - halfSpan, lidY, center.x + halfSpan, lidY);
        }
    }

    static void drawV1SkinHeadMarkings(
        Gdiplus::Graphics& g, const SkinSpec& skin,
        float headCX, float headCY, float headRX, float headRY
    ) {
        using namespace Gdiplus;
        if (skin.colorpoint()) {
            Color seal = skin.palette.points.set ? col(skin.palette.points) : col(skin.palette.earOuter);
            drawSoftTaupePatch(g, { headCX, headCY + 4.0f }, headRX * 0.56f, headRY * 0.64f, seal);
            return;
        }
        float sx = headRX / 44.0f;
        float sy = headRY / 33.0f;
        auto mapHead = [&](SkinPoint pt) -> PointF {
            return PointF(headCX + pt.x * sx, headCY + pt.y * sy);
        };
        for (const SkinRegion& region : skin.regions) {
            if ((region.space == SkinSpace::Head || region.space == SkinSpace::Skull) && region.flat.size() >= 3) {
                drawRegion(g, region, mapHead);
            }
        }
        for (const SkinMark& mark : skin.marks) {
            if ((mark.space == SkinSpace::Head || mark.space == SkinSpace::Skull) && mark.points.size() >= 2) {
                if (mark.stroke) {
                    std::vector<PointF> pts = mapPoints(mark.points, mapHead);
                    GraphicsPath p;
                    p.AddLines(pts.data(), (INT)pts.size());
                    Pen pen(col(mark.color), std::max(4.0f, mark.width * sy));
                    setRound(pen);
                    g.DrawPath(&pen, &p);
                } else {
                    drawMark(g, mark, mapHead);
                }
            }
        }
    }

    static void drawV1SkinBackMarkings(Gdiplus::Graphics& g, const SkinSpec& skin, float s) {
        using namespace Gdiplus;
        float bx = lerpF(560.0f, 590.0f, s);
        float by = lerpF(220.0f, 330.0f, s);
        constexpr float sx = 3.6f;
        constexpr float sy = 2.6f;
        auto mapBack = [&](SkinPoint pt) -> PointF {
            return PointF(bx + pt.x * sx, by + (pt.y + 42.0f) * sy);
        };
        for (const SkinRegion& region : skin.regions) {
            if (region.space == SkinSpace::Body && region.flat.size() >= 3) {
                drawRegion(g, region, mapBack);
            }
        }
        for (const SkinMark& mark : skin.marks) {
            if (mark.space == SkinSpace::Body && mark.points.size() >= 2) {
                if (mark.stroke) {
                    std::vector<PointF> pts = mapPoints(mark.points, mapBack);
                    GraphicsPath p;
                    p.AddLines(pts.data(), (INT)pts.size());
                    Pen pen(col(mark.color), std::max(5.0f, mark.width * sy));
                    setRound(pen);
                    g.DrawPath(&pen, &p);
                } else {
                    drawMark(g, mark, mapBack);
                }
            }
        }
        if (skin.palette.belly.set) {
            SolidBrush bb(withAlpha(skin.palette.belly, 235));
            g.FillEllipse(&bb, bx - 170.0f, by + lerpF(110.0f, 130.0f, s), 290.0f, 110.0f);
        }
    }

    static void drawComicHeart(Gdiplus::Graphics& g, Pt center, float size, float alpha, Gdiplus::Color ink) {
        using namespace Gdiplus;
        if (alpha <= 0.02f) return;
        GraphicsState st = g.Save();
        g.TranslateTransform(center.x, center.y);
        GraphicsPath p;
        p.AddBezier(0.0f, size * 0.65f, -size * 0.65f, size * 0.35f, -size, size * 0.15f, -size, -size * 0.15f);
        p.AddBezier(-size, -size * 0.15f, -size, -size * 0.78f, -size * 0.25f, -size * 0.82f, 0.0f, -size * 0.38f);
        p.AddBezier(0.0f, -size * 0.38f, size * 0.25f, -size * 0.82f, size, -size * 0.78f, size, -size * 0.15f);
        p.AddBezier(size, -size * 0.15f, size, size * 0.15f, size * 0.65f, size * 0.35f, 0.0f, size * 0.65f);
        p.CloseFigure();
        SolidBrush fb(withColorAlpha(Color(255, 255, 112, 143), alpha));
        g.FillPath(&fb, &p);
        Pen pen(scaleAlpha(ink, alpha), 6.5f);
        setRound(pen);
        g.DrawPath(&pen, &p);
        g.Restore(st);
    }

    static void drawComicZ(Gdiplus::Graphics& g, Pt center, float size, float alpha, Gdiplus::Color ink) {
        using namespace Gdiplus;
        if (alpha <= 0.02f) return;
        float r = size * 0.55f;
        PointF pts[4] = {
            PointF(center.x - r, center.y - r),
            PointF(center.x + r, center.y - r),
            PointF(center.x - r, center.y + r),
            PointF(center.x + r, center.y + r)
        };
        Pen pen(scaleAlpha(ink, alpha), 7.5f);
        setRound(pen);
        g.DrawLines(&pen, pts, 4);
    }

    // MARK: - V2Space (832 x 720) Pixel-Exact Video 2 Typing / Idle / Mouse Scene

    static void drawDouniV2InSpace(
        Gdiplus::Graphics& g,
        const CatPhysics& physics,
        const SkinSpec& skin,
        const KeyboardSkinSpec& kbSkin,
        EyeColorTheme eyeTheme,
        bool marquee,
        bool showMouse = true,
        const V2PoseOverride* poseOverride = nullptr,
        float loafMorph = 0.0f
    ) {
        using namespace Gdiplus;
        Color ink = skin.palette.outline.set ? col(skin.palette.outline) : douniInkColor();
        Color cream = col(skin.palette.body);
        Color taupe = skin.palette.points.set ? col(skin.palette.points) : col(skin.palette.paws);
        constexpr float catLW = 10.8f;
        constexpr float kbLW = 12.6f;
        float morph = std::clamp(loafMorph, 0.0f, 1.0f);

        // Direct independent signed arm poses: -1 = slam down on exact key, 0 = ready (v2_01), +1 = flung high (v2_04/v2_05).
        // Never cancels out to 0 during fast rollover typing or rapid alternation!
        float leftPose = 0.0f, rightPose = 0.0f, mouseBlend = 0.0f;
        if (poseOverride) {
            leftPose = poseOverride->leftPose;
            rightPose = poseOverride->rightPose;
            mouseBlend = poseOverride->mouseBlend;
        } else {
            leftPose = std::clamp(physics.douniLeftRaise.value, -1.08f, 1.08f);
            rightPose = std::clamp(physics.douniRightRaise.value, -1.08f, 1.08f);
            mouseBlend = std::clamp(physics.douniMouseBlend.value, 0.0f, 1.0f);
        }

        float hunt = poseOverride ? 0.0f : std::clamp(physics.huntIntensity.value, 0.0f, 1.0f);
        float dizzy = poseOverride ? 0.0f : std::clamp(physics.dizzyIntensity.value, 0.0f, 1.0f);
        float anger = poseOverride ? 0.0f : std::clamp(physics.angerIntensity.value, 0.0f, 1.0f);
        bool isTablet = (!poseOverride) && physics.isTabletActive;

        // Disney 12-Principles Typing Secondary Action + Hunting Crouch + Dizzy Wobble + Furious Tremble
        float impY = std::clamp(physics.kbImpactY.value, -0.4f, 1.3f);
        float impT = std::clamp(physics.kbImpactTilt.value, -0.9f, 0.9f);
        float dizzyWobble = std::sin(physics.time * 9.5f) * 0.14f * dizzy;
        float angerShakeX = (anger > 0.08f) ? std::sin(physics.time * 42.0f) * 3.2f * anger : 0.0f;
        float headTiltRad = -rightPose * 0.010f + leftPose * 0.012f + physics.headTilt.value * 0.08f + impT * 0.014f + dizzyWobble;
        float headBobY = std::fabs(leftPose - rightPose) * 2.5f + physics.breathingOffset() * 1.4f + impY * 5.2f
            + hunt * 16.0f + anger * 5.0f + std::fabs(std::sin(physics.time * 4.8f)) * 9.0f * dizzy;
        float headSquashY = 1.0f - std::max(0.0f, impY) * 0.028f - hunt * 0.062f - anger * 0.022f;
        float headSquashX = 1.0f + std::max(0.0f, impY) * 0.014f + hunt * 0.045f + anger * 0.018f;
        float earLagX = poseOverride ? 0.0f : std::clamp(physics.earTwitch.value * 2.8f, -9.0f, 9.0f);
        float earFlare = hunt * 9.0f - anger * 10.0f;

        // Keyboard colors: Video 2 authentic retro grey by default (`builtin:0`), or synced with custom `.kurokb` skin!
        bool useDefaultRetroGrey = (kbSkin.id == "builtin:0");
        Color kbDeckColor     = useDefaultRetroGrey ? Color(255, 185, 187, 187) : col(kbSkin.deck);
        Color kbBevelColor    = useDefaultRetroGrey ? Color(255, 155, 157, 156) : col(kbSkin.base);
        Color kbKeyColor      = useDefaultRetroGrey ? Color(255, 178, 180, 179) : col(kbSkin.key);
        Color kbAccentColor   = useDefaultRetroGrey ? Color(255, 168, 170, 169) : col(kbSkin.accent);
        Color mouseBodyColor  = useDefaultRetroGrey ? Color(255, 190, 192, 192) : col(kbSkin.mouseBody);
        Color mouseWheelColor = useDefaultRetroGrey ? Color(255,  92,  89,  87) : col(kbSkin.wheel);
        Color baseGlow        = useDefaultRetroGrey ? Color(255, 255, 214,  61) : eyeGlow(eyeTheme);
        // Shift keycap glow fiery orange-red when fast-typing anger kicks in!
        Color glowBaseColor   = (anger > 0.05f)
            ? blendColor(baseGlow, Color(255, 255, 87, 36), std::min(0.88f, anger * 0.88f))
            : baseGlow;

        // Choreographed Disney Pop-Squish Morph:
        // Phase 1 (0..0.44): Desk gear glides down & fades; V2 cat stays opaque while gliding down-left, squishing wide & closing eyes!
        // Phase 2 (0.36..0.56): Tight aligned cross-swap right into V1 Loaf at the same spot (ZERO muddy double ghosting!)
        float gearAlpha = 1.0f - smoothstep(0.0f, 0.42f, morph);
        float gearDropY = smoothstep(0.0f, 0.46f, morph) * 86.0f;
        float catAlpha = 1.0f - smoothstep(0.36f, 0.56f, morph);
        float catGlide = smoothstep(0.0f, 0.54f, morph);
        float catMorphX = -catGlide * 185.0f;
        float catMorphY = catGlide * 145.0f;
        float catMorphSX = 1.0f + catGlide * 0.22f;
        float catMorphSY = 1.0f - catGlide * 0.28f;

        // Compute mouse / tablet nib position in V2Space
        Pt mouseCenter = {
            168.0f + physics.mouseOffset.point().x * 5.2f,
            286.0f + physics.mouseOffset.point().y * 4.5f
        };
        float mousePress = std::max(physics.mousePressLeft.value, physics.mousePressRight.value);
        Pt nibUV = douniTabletUV(physics.tabletNib.point());
        Pt v2Nib = v2TabletPoint(nibUV.x, nibUV.y);
        float tabletPress = std::clamp(physics.tabletPenPress.value, 0.0f, 1.0f);

        // 1. Companion hand-drawn comic Mouse OR Graphics Tablet (upper-left beside keyboard — zero overlap!)
        if (showMouse && gearAlpha > 0.01f) {
            drawWithRectLayerAlpha(g, -80.0f, -40.0f, 980.0f, 780.0f, gearAlpha, [&](Graphics& lg) {
                GraphicsState gs = lg.Save();
                if (morph > 0.005f) {
                    lg.TranslateTransform(0.0f, gearDropY);
                }
                if (isTablet) {
                    drawDouniComicTablet(lg, physics, kbDeckColor, kbBevelColor, kbKeyColor, kbAccentColor,
                                         glowBaseColor, eyePrimary(eyeTheme), ink, catLW, mouseBlend < 0.18f);
                } else {
                    drawDouniComicMouse(lg, mouseCenter, physics.mousePressLeft.value, physics.mousePressRight.value,
                                        mouseBodyColor, kbBevelColor, mouseWheelColor, glowBaseColor, ink, catLW);
                }
                lg.Restore(gs);
            });
        }

        // 2. Video 2 Cat Back/Torso, Soft Rounded Unified Head+Ears & Expressive Boba Eyes (behind angled keyboard!)
        if (catAlpha > 0.01f) {
            drawWithRectLayerAlpha(g, -80.0f, -40.0f, 980.0f, 780.0f, catAlpha, [&](Graphics& lg) {
                GraphicsState hs = lg.Save();
                if (morph > 0.005f) {
                    lg.TranslateTransform(582.0f + catMorphX, 340.0f + catMorphY);
                    lg.ScaleTransform(catMorphSX, catMorphSY);
                    lg.TranslateTransform(-582.0f, -340.0f);
                }
                lg.TranslateTransform(582.0f + angerShakeX, 340.0f + headBobY);
                lg.RotateTransform(headTiltRad * RadToDeg);
                lg.ScaleTransform(headSquashX, headSquashY);
                lg.TranslateTransform(-582.0f, -340.0f);

                // Pass 0: crisp sticker-style outer white silhouette rim behind V2 Douni body + head/ears
                if (whiteOutlineEnabled()) {
                    Pen wr(blackOutline(), catLW + 9.2f);
                    setRound(wr);
                    lg.DrawBezier(&wr, PointF(716.0f, 326.0f), PointF(742.0f, 356.0f), PointF(758.0f, 400.0f), PointF(762.0f, 444.0f));
                    GraphicsPath headRim;
                    addV2UnifiedHeadOuterContour(headRim, earLagX, earFlare);
                    lg.DrawPath(&wr, &headRim);
                }

                // 2a. Right shoulder / back descending smoothly behind keyboard top-right edge (x=688..762, y=324..444)
                {
                    GraphicsPath bodyPath;
                    bodyPath.AddLine(416.0f, 316.0f, 718.0f, 326.0f);
                    bodyPath.AddBezier(718.0f, 326.0f, 742.0f, 358.0f, 758.0f, 402.0f, 762.0f, 444.0f);
                    bodyPath.AddLine(762.0f, 444.0f, 416.0f, 422.0f);
                    bodyPath.CloseFigure();
                    SolidBrush cb(cream);
                    lg.FillPath(&cb, &bodyPath);
                    Pen bp(ink, catLW);
                    setRound(bp);
                    lg.DrawBezier(&bp, PointF(716.0f, 326.0f), PointF(742.0f, 356.0f), PointF(758.0f, 400.0f), PointF(762.0f, 444.0f));
                }

                // 2b. Whiskers directly traced from Video 2 reference temples (top-left \ \ and top-right / /)
                {
                    float wTwitch = (hunt > 0.15f) ? std::sin(physics.time * 30.0f) * 3.5f * hunt : 0.0f;
                    Pen wp(ink, catLW * 0.90f);
                    setRound(wp);
                    lg.DrawLine(&wp, 420.0f, 168.0f + wTwitch, 446.0f, 194.0f);
                    lg.DrawLine(&wp, 444.0f, 146.0f - wTwitch, 462.0f, 178.0f);
                    lg.DrawLine(&wp, 728.0f, 206.0f, 754.0f, 174.0f + wTwitch);
                    lg.DrawLine(&wp, 740.0f, 224.0f, 772.0f, 208.0f - wTwitch);
                }

                // 2c. ONE Continuous Soft Plump Oval Head + Both Ears Path (zero boxy corners, zero seams!)
                drawV2UnifiedHeadAndEars(lg, earLagX, earFlare, cream, taupe, ink, catLW, anger);

                // 2d. Expressive circular boba eyes (normal / hunting starry dilated / dizzy spinning spirals / angry slanted V-brows)
                float gazeX = poseOverride ? 0.0f : physics.eyeGaze.x.value;
                float gazeY = poseOverride ? 0.0f : physics.eyeGaze.y.value;
                float baseBlink = poseOverride ? 0.0f : physics.blinkProgress();
                float blink = std::max(baseBlink, smoothstep(0.04f, 0.44f, morph));
                drawV2BobaEye(lg, { 518.0f, 262.0f }, 47.5f, true, gazeX, gazeY, blink,
                              hunt, dizzy, physics.dizzyPhase, anger, cream, ink, catLW);
                drawV2BobaEye(lg, { 652.0f, 274.0f }, 46.5f, false, gazeX, gazeY, blink,
                              hunt, dizzy, physics.dizzyPhase, anger, cream, ink, catLW);

                // 2e. Expressive Comic Emotion Accents: Pulsing Red Anger Vein, Alert Hunter Ticks, Orbiting Dizzy Stars!
                if (anger > 0.14f) {
                    float aAlpha = smoothstep(0.14f, 0.55f, anger);
                    float pulse = (1.0f + std::sin(physics.time * 16.0f) * 0.12f) * 0.90f;
                    drawDouniAngerVein(lg, { 682.0f, 198.0f }, pulse, aAlpha);
                }
                if (hunt > 0.35f && dizzy < 0.15f) {
                    float hAlpha = smoothstep(0.35f, 0.78f, hunt);
                    Pen hp(scaleAlpha(ink, hAlpha), catLW * 0.68f);
                    setRound(hp);
                    lg.DrawLine(&hp, 472.0f, 112.0f, 454.0f,  92.0f);
                    lg.DrawLine(&hp, 454.0f, 138.0f, 432.0f, 130.0f);
                }
                if (dizzy > 0.08f) {
                    drawDouniDizzyStars(lg, { 590.0f, 74.0f }, physics.dizzyPhase, dizzy, ink);
                }

                lg.Restore(hs);
            });
        }

        // 3. Video 2 Hand-Drawn Angled Wired Keyboard with Disney Squash & Stretch, Micro-Shake, Vivid Glowing Keys & Spark Burst!
        if (gearAlpha > 0.01f) {
            drawWithRectLayerAlpha(g, -80.0f, -40.0f, 980.0f, 780.0f, gearAlpha, [&](Graphics& lg) {
                GraphicsState gs = lg.Save();
                if (morph > 0.005f) {
                    lg.TranslateTransform(0.0f, gearDropY);
                }
                bool kbShakeActive = (poseOverride == nullptr);
                drawDouniV2Keyboard(lg, physics, kbDeckColor, kbBevelColor, kbKeyColor, kbAccentColor, glowBaseColor,
                                    marquee, ink, kbLW, kbShakeActive ? impY : 0.0f, kbShakeActive ? impT : 0.0f);
                lg.Restore(gs);
            });
        }

        // 4-5. Chubby Milk-Tea Arms (slapping exact keys / hovering ready / gripping mouse or comic stylus!)
        if (catAlpha > 0.01f) {
            drawWithRectLayerAlpha(g, -80.0f, -40.0f, 980.0f, 780.0f, catAlpha, [&](Graphics& lg) {
                GraphicsState as = lg.Save();
                if (morph > 0.005f) {
                    lg.TranslateTransform(582.0f + catMorphX, 340.0f + catMorphY);
                    lg.ScaleTransform(catMorphSX, catMorphSY);
                    lg.TranslateTransform(-582.0f, -340.0f);
                }

                // Subtle eager predator paw-tremble when hunting!
                float huntTremble = (hunt > 0.18f && std::fabs(leftPose) < 0.25f && std::fabs(rightPose) < 0.25f)
                    ? std::sin(physics.time * 32.0f) * 0.08f * hunt : 0.0f;
                float effectiveLeftPose = leftPose * (1.0f - morph * 0.85f) + huntTremble;
                float effectiveRightPose = rightPose * (1.0f - morph * 0.85f) - huntTremble;
                float effectiveMouseBlend = (showMouse ? mouseBlend : 0.0f) * (1.0f - morph);

                // Left Arm (Cat's Right Arm) — slams DEAD-CENTER onto exact pressed left-half keycap, OR glides onto mouse / grips stylus!
                float lVel = poseOverride ? 0.0f : physics.douniLeftRaise.velocity;
                Pt lTarget = {
                    physics.douniLeftKeyTarget.point().x + impT * 10.0f,
                    physics.douniLeftKeyTarget.point().y + impY * 8.5f
                };
                Pt leftToolTarget = isTablet
                    ? Pt{ v2Nib.x + 14.0f, v2Nib.y - 12.0f + tabletPress * 5.0f }
                    : Pt{ mouseCenter.x + 8.0f, mouseCenter.y - 2.0f + mousePress * 8.0f };

                drawV2LeftArm(lg, effectiveLeftPose, effectiveMouseBlend, leftToolTarget,
                              poseOverride ? nullptr : &lTarget,
                              cream, taupe, ink, catLW, lVel);

                // Held Hand-Drawn Comic Stylus gripped right at Douni's left paw when using Graphics Tablet!
                if (showMouse && isTablet && effectiveMouseBlend > 0.18f) {
                    float penAlpha = smoothstep(0.18f, 0.42f, effectiveMouseBlend);
                    GraphicsState ps = lg.Save();
                    Pt nibDrawPt = { v2Nib.x, v2Nib.y + tabletPress * 4.0f };
                    float penAngle = -2.14f + physics.tabletPenTilt.value;
                    lg.TranslateTransform(nibDrawPt.x, nibDrawPt.y);
                    lg.RotateTransform(penAngle * RadToDeg);
                    drawWithRectLayerAlpha(lg, -24.0f, -32.0f, 180.0f, 64.0f, penAlpha, [&](Graphics& pg) {
                        drawDouniComicStylus(pg, 124.0f, glowBaseColor, eyePrimary(eyeTheme), ink, catLW, tabletPress);
                    });
                    lg.Restore(ps);
                }

                // Right Arm (Cat's Left Arm) — slams DEAD-CENTER onto exact pressed right-half/spacebar keycap, or flings high across face!
                float rVel = poseOverride ? 0.0f : physics.douniRightRaise.velocity;
                Pt rTarget = {
                    physics.douniRightKeyTarget.point().x + impT * 10.0f,
                    physics.douniRightKeyTarget.point().y + impY * 8.5f
                };
                drawV2RightArm(lg, effectiveRightPose, poseOverride ? nullptr : &rTarget,
                               cream, taupe, ink, catLW, rVel);

                lg.Restore(as);
            });
        }
    }

    /// Builds the unified outer contour path pixel-traced directly from Video 2's original head + ears (maxErr ~ 0.8px on 832x720!).
    static void addV2UnifiedHeadOuterContour(Gdiplus::GraphicsPath& gp, float earLagX, float earFlare) {
        using namespace Gdiplus;
        float dxL = earLagX - earFlare;
        float dxR = earLagX + earFlare;
        float dyPin = std::max(0.0f, -earFlare) * 0.9f;
        Pt neckLeft    = { 576.0f, 365.0f };
        Pt leftCheek   = { 421.0f, 275.0f };
        Pt leftEarOut  = { 483.5f, 180.0f };
        Pt leftEarTip  = { 573.0f + dxL, 62.0f + dyPin };
        Pt leftEarIn   = { 596.0f, 174.0f };
        Pt rightEarIn  = { 618.0f, 178.0f };
        Pt rightEarTip = { 679.5f + dxR, 76.0f + dyPin };
        Pt rightEarOut = { 714.0f, 196.0f };
        Pt rightCheek  = { 757.0f, 280.0f };
        Pt neckRight   = { 722.0f, 350.0f };

        gp.AddBezier(PointF(neckLeft.x, neckLeft.y), PointF(520.3f, 369.5f), PointF(416.7f, 351.4f), PointF(leftCheek.x, leftCheek.y));
        gp.AddBezier(PointF(leftCheek.x, leftCheek.y), PointF(423.2f, 235.2f), PointF(442.5f, 192.8f), PointF(leftEarOut.x, leftEarOut.y));
        gp.AddBezier(PointF(leftEarOut.x, leftEarOut.y), PointF(519.3f, 147.1f), PointF(529.2f + dxL * 0.6f, 90.3f + dyPin * 0.6f), PointF(leftEarTip.x, leftEarTip.y));
        gp.AddBezier(PointF(leftEarTip.x, leftEarTip.y), PointF(596.8f + dxL * 0.4f, 94.0f + dyPin * 0.5f), PointF(592.7f, 136.4f), PointF(leftEarIn.x, leftEarIn.y));
        addQuadBezier(gp, leftEarIn, { 607.0f, 176.0f }, rightEarIn);
        gp.AddBezier(PointF(rightEarIn.x, rightEarIn.y), PointF(640.1f, 146.2f), PointF(642.6f + dxR * 0.6f, 97.9f + dyPin * 0.6f), PointF(rightEarTip.x, rightEarTip.y));
        gp.AddBezier(PointF(rightEarTip.x, rightEarTip.y), PointF(717.7f + dxR * 0.4f, 102.3f + dyPin * 0.5f), PointF(709.7f, 155.8f), PointF(rightEarOut.x, rightEarOut.y));
        gp.AddBezier(PointF(rightEarOut.x, rightEarOut.y), PointF(738.0f, 217.2f), PointF(757.4f, 246.8f), PointF(rightCheek.x, rightCheek.y));
        gp.AddBezier(PointF(rightCheek.x, rightCheek.y), PointF(756.3f, 307.2f), PointF(745.0f, 334.2f), PointF(neckRight.x, neckRight.y));
    }

    /// ONE continuous unified path fusing Video 2's pixel-traced head + both close-set pointed ears.
    static void drawV2UnifiedHeadAndEars(
        Gdiplus::Graphics& g, float earLagX, float earFlare,
        Gdiplus::Color cream, Gdiplus::Color taupe, Gdiplus::Color ink, float lw,
        float angerBlush = 0.0f
    ) {
        using namespace Gdiplus;
        Pt neckRight   = { 722.0f, 350.0f };
        Pt chin        = { 589.0f, 366.0f };
        Pt neckLeft    = { 576.0f, 365.0f };

        GraphicsPath strokePath, fillPath;
        addV2UnifiedHeadOuterContour(strokePath, earLagX, earFlare);
        addV2UnifiedHeadOuterContour(fillPath, earLagX, earFlare);
        addQuadBezier(fillPath, neckRight, { 660.0f, 366.0f }, chin);
        fillPath.AddLine(PointF(chin.x, chin.y), PointF(neckLeft.x, neckLeft.y));
        fillPath.CloseFigure();

        // 1. Cream base fill across unified head+ears
        SolidBrush creamBrush(cream);
        g.FillPath(&creamBrush, &fillPath);

        // 2. Clipped ear gradients + nose-bridge taupe smudge + optional furious rosy blush!
        {
            GraphicsState cs = g.Save();
            g.SetClip(&fillPath, CombineModeIntersect);
            Color earCols[3] = { taupe, taupe, Color(0, cream.GetR(), cream.GetG(), cream.GetB()) };
            REAL earLocs[3] = { 0.0f, 0.72f, 1.0f };
            RectF lBand(472.0f, 52.0f, 130.0f, 158.0f);
            fillClampedLinearGradient(g, nullptr, &lBand, PointF(545.0f, 62.0f), PointF(545.0f, 204.0f), earCols, earLocs, 3);
            RectF rBand(612.0f, 64.0f, 118.0f, 158.0f);
            fillClampedLinearGradient(g, nullptr, &rBand, PointF(672.0f, 76.0f), PointF(672.0f, 214.0f), earCols, earLocs, 3);
            drawSoftTaupePatch(g, { 586.0f, 270.0f }, 52.0f, 48.0f, taupe, 0.72f);
            if (angerBlush > 0.08f) {
                BYTE ba = (BYTE)std::clamp((int)std::lround(std::min(0.42f, angerBlush * 0.42f) * 255.0f), 0, 255);
                SolidBrush blushBrush(Color(ba, 255, 112, 122));
                g.FillEllipse(&blushBrush, 432.0f, 294.0f, 56.0f, 30.0f);
                g.FillEllipse(&blushBrush, 680.0f, 304.0f, 56.0f, 30.0f);
            }
            g.Restore(cs);
        }

        // 3. Single unbroken bold ink contour around the soft fused head + ears!
        Pen inkPen(ink, lw);
        setRound(inkPen);
        g.DrawPath(&inkPen, &strokePath);

        // 4. Inner ear tufts (|||) cleanly anchored inside fused ears
        drawV2EarTufts(g, true, ink, lw);
        drawV2EarTufts(g, false, ink, lw);
    }

    static void drawV2EarTufts(Gdiplus::Graphics& g, bool isLeft, Gdiplus::Color ink, float lw) {
        using namespace Gdiplus;
        Pen pen(ink, lw * 0.72f);
        setRound(pen);
        if (isLeft) {
            g.DrawLine(&pen, 550.0f, 176.0f, 544.0f, 158.0f);
            g.DrawLine(&pen, 564.0f, 176.0f, 558.0f, 146.0f);
            g.DrawLine(&pen, 578.0f, 175.0f, 572.0f, 134.0f);
        } else {
            g.DrawLine(&pen, 632.0f, 182.0f, 644.0f, 144.0f);
            g.DrawLine(&pen, 646.0f, 184.0f, 660.0f, 158.0f);
            g.DrawLine(&pen, 660.0f, 186.0f, 674.0f, 172.0f);
        }
    }

    static void drawV2BobaEye(
        Gdiplus::Graphics& g, Pt center, float r, bool isLeft, float gazeX, float gazeY,
        float blink, float hunt, float dizzy, float dizzyPhase, float anger,
        Gdiplus::Color cream, Gdiplus::Color ink, float lw
    ) {
        using namespace Gdiplus;
        if (blink > 0.72f && dizzy < 0.25f) {
            Pen pen(ink, lw * 1.05f);
            setRound(pen);
            GraphicsPath bp;
            addQuadBezier(bp, { center.x - r * 0.88f, center.y + 4.0f }, { center.x, center.y + 14.0f }, { center.x + r * 0.88f, center.y + 4.0f });
            g.DrawPath(&pen, &bp);
            return;
        }
        float openScaleY = (dizzy > 0.28f) ? 1.0f : std::max(0.18f, 1.0f - blink * 0.85f);
        GraphicsState st = g.Save();
        g.TranslateTransform(center.x, center.y);
        g.ScaleTransform(1.0f, openScaleY);
        RectF rect(-r, -r, r * 2.0f, r * 2.0f);

        // 1. Soft pale off-white sclera disc
        SolidBrush scleraBrush(douniV2Sclera());
        g.FillEllipse(&scleraBrush, rect);

        // 2. Eye interior: either Dizzy Spinning Comic Spiral (@ @) OR Video 2 Boba Pupil (+ Hunting Starry Glints!)
        {
            GraphicsState cs = g.Save();
            GraphicsPath ep;
            ep.AddEllipse(rect);
            g.SetClip(&ep, CombineModeIntersect);
            if (dizzy > 0.28f) {
                // Bold hand-drawn Archimedean spiral spinning oppositely per eye!
                float dir = isLeft ? 1.0f : -1.0f;
                float phase = dizzyPhase * dir;
                constexpr int steps = 44;
                constexpr float maxTheta = 3.14159265f * 4.4f;
                float maxR = r * 0.78f;
                PointF pts[steps + 1];
                for (int i = 0; i <= steps; ++i) {
                    float t = (float)i / (float)steps;
                    float theta = t * maxTheta + phase;
                    float rad = t * maxR;
                    pts[i] = PointF(std::cos(theta) * rad, std::sin(theta) * rad);
                }
                Pen spPen(ink, lw * 0.72f);
                setRound(spPen);
                g.DrawLines(&spPen, pts, steps + 1);
            } else {
                // Giant pure-black circular pupil: default shifted down-left toward keyboard; unlocks & dilates huge during hunting!
                float pr = r * (0.80f + hunt * 0.11f);
                float baseX = lerpF(-5.5f, 0.0f, hunt);
                float baseY = lerpF(7.5f, 0.0f, hunt);
                float px = baseX + gazeX * (7.5f + hunt * 10.5f);
                float py = baseY + gazeY * (5.5f + hunt * 8.5f);
                SolidBrush blackBrush(Color(255, 0, 0, 0));
                g.FillEllipse(&blackBrush, px - pr, py - pr, pr * 2.0f, pr * 2.0f);

                // Sparkling starry hunter catchlights when stalking a fast cursor!
                if (hunt > 0.12f) {
                    float ha = smoothstep(0.12f, 0.65f, hunt);
                    SolidBrush whiteBrush(withColorAlpha(Color(255, 255, 255, 255), ha));
                    float sx = px - pr * 0.34f, sy = py - pr * 0.32f;
                    float sr = r * (0.28f + hunt * 0.08f);
                    GraphicsPath star;
                    addQuadBezier(star, { sx, sy - sr }, { sx + sr * 0.18f, sy - sr * 0.18f }, { sx + sr, sy });
                    addQuadBezier(star, { sx + sr, sy }, { sx + sr * 0.18f, sy + sr * 0.18f }, { sx, sy + sr });
                    addQuadBezier(star, { sx, sy + sr }, { sx - sr * 0.18f, sy + sr * 0.18f }, { sx - sr, sy });
                    addQuadBezier(star, { sx - sr, sy }, { sx - sr * 0.18f, sy - sr * 0.18f }, { sx, sy - sr });
                    star.CloseFigure();
                    g.FillPath(&whiteBrush, &star);
                    float dotR = r * 0.12f;
                    g.FillEllipse(&whiteBrush, px + pr * 0.28f - dotR, py + pr * 0.26f - dotR, dotR * 2.0f, dotR * 2.0f);
                } else if (anger > 0.18f) {
                    // Tiny fierce comic highlight glint when angry-typing
                    float fa = smoothstep(0.18f, 0.60f, anger);
                    SolidBrush glintBrush(withColorAlpha(Color(255, 255, 255, 255), 0.85f * fa));
                    float dotR = r * 0.11f;
                    g.FillEllipse(&glintBrush, px + (isLeft ? -11.0f : 11.0f) - dotR, py + 6.0f - dotR, dotR * 2.0f, dotR * 2.0f);
                }
            }
            g.Restore(cs);
        }

        // 3. Bold ink border around eye circle
        Pen rimPen(ink, lw * 0.94f);
        setRound(rimPen);
        g.DrawEllipse(&rimPen, rect);

        // 4. Cleanly clipped comic slanted upper eyelid + bold ink V-brow when angry (ZERO floating brown blocks!)
        if (anger > 0.06f && dizzy < 0.25f) {
            float a = smoothstep(0.06f, 0.72f, anger);
            float tiltAngle = (isLeft ? 1.0f : -1.0f) * (0.32f * a);
            float lidY = -r + a * (r * 0.62f);
            GraphicsState as = g.Save();
            g.RotateTransform(tiltAngle * RadToDeg);
            float maskH = lidY - (-r - 22.0f);
            if (maskH > 0.5f) {
                SolidBrush creamBrush(cream);
                g.FillRectangle(&creamBrush, -r - 16.0f, -r - 22.0f, r * 2.0f + 32.0f, maskH);
            }
            float span = r * 1.12f;
            float outerLift = -6.0f * a;
            Pt pL = { -span, lidY + (isLeft ? outerLift : 2.0f) };
            Pt pR = {  span, lidY + (isLeft ? 2.0f : outerLift) };
            Pen browPen(ink, lw * 1.12f);
            setRound(browPen);
            GraphicsPath brow;
            addQuadBezier(brow, pL, { 0.0f, lidY + 4.0f * a }, pR);
            g.DrawPath(&browPen, &brow);
            g.Restore(as);
        }

        g.Restore(st);
    }

    /// Bold comic red anger vein matching Video 2's chunky hand-drawn marker aesthetic.
    static void drawDouniAngerVein(Gdiplus::Graphics& g, Pt center, float scale, float alpha) {
        using namespace Gdiplus;
        if (alpha <= 0.02f) return;
        GraphicsState st = g.Save();
        g.TranslateTransform(center.x, center.y);
        g.ScaleTransform(scale, scale);
        Pen pen(withColorAlpha(Color(255, 240, 56, 71), alpha), 8.6f);
        setRound(pen);
        constexpr float d = 9.0f, r = 24.0f;
        constexpr float signs[4][2] = { {-1.0f, -1.0f}, {1.0f, -1.0f}, {-1.0f, 1.0f}, {1.0f, 1.0f} };
        for (const auto& s : signs) {
            GraphicsPath gp;
            addQuadBezier(gp, { s[0] * r, s[1] * d }, { s[0] * d, s[1] * d }, { s[0] * d, s[1] * r });
            g.DrawPath(&pen, &gp);
        }
        g.Restore(st);
    }

    /// 3 orbiting golden hand-drawn comic stars above Xiao Douni's ears when dizzy!
    static void drawDouniDizzyStars(Gdiplus::Graphics& g, Pt center, float phase, float dizzy, Gdiplus::Color ink) {
        using namespace Gdiplus;
        float a = smoothstep(0.08f, 0.40f, dizzy);
        if (a <= 0.01f) return;
        constexpr float rx = 136.0f, ry = 32.0f;
        SolidBrush fillBrush(withColorAlpha(Color(255, 255, 214, 61), a));
        Pen strokePen(scaleAlpha(ink, a), 6.5f);
        setRound(strokePen);
        for (int i = 0; i < 3; ++i) {
            float ang = phase * 0.72f + (float)i * (3.14159265f * 2.0f / 3.0f);
            float sx = center.x + std::cos(ang) * rx;
            float sy = center.y + std::sin(ang) * ry;
            float sz = 20.0f + std::sin(ang) * 4.5f;
            PointF pts[8];
            for (int k = 0; k < 8; ++k) {
                float ka = (float)k * (3.14159265f / 4.0f) + phase * 0.4f;
                float rad = (k % 2 == 0) ? sz : sz * 0.42f;
                pts[k] = PointF(sx + std::cos(ka) * rad, sy + std::sin(ka) * rad);
            }
            GraphicsPath star;
            star.AddPolygon(pts, 8);
            g.FillPath(&fillBrush, &star);
            g.DrawPath(&strokePen, &star);
        }
    }

    /// Bilinear interpolation on Xiao Douni's upper-left hand-drawn comic Graphics Tablet in V2Space (`832x720`).
    static Pt v2TabletPoint(float u, float v) {
        constexpr Pt tl = {  84.0f, 184.0f };
        constexpr Pt tr = { 268.0f, 222.0f };
        constexpr Pt br = { 192.0f, 316.0f };
        constexpr Pt bl = {  14.0f, 274.0f };
        float topX = tl.x + (tr.x - tl.x) * u;
        float topY = tl.y + (tr.y - tl.y) * u;
        float botX = bl.x + (br.x - bl.x) * u;
        float botY = bl.y + (br.y - bl.y) * u;
        return { topX + (botX - topX) * v, topY + (botY - topY) * v };
    }

    /// Maps standard 360x320 canvas tablet coordinates (`tabletNib` & `tabletTrail`) into normalized `(u, v)` on Douni's comic tablet!
    static Pt douniTabletUV(Pt canvasPt) {
        float dx = canvasPt.x - 18.0f;
        float dy = canvasPt.y - 235.0f;
        constexpr float det = 76.0f * 49.0f - (-5.0f) * 5.0f;
        float u = std::clamp((dx * 49.0f + dy * 5.0f) / det, 0.06f, 0.94f);
        float v = std::clamp((-dx * 5.0f + dy * 76.0f) / det, 0.06f, 0.94f);
        return { u, v };
    }

    static void drawDouniV2Keyboard(
        Gdiplus::Graphics& g,
        const CatPhysics& physics,
        Gdiplus::Color deckColor,
        Gdiplus::Color bevelColor,
        Gdiplus::Color keyColor,
        Gdiplus::Color accentColor,
        Gdiplus::Color glowColor,
        bool marquee,
        Gdiplus::Color ink,
        float lw,
        float impactY = 0.0f,
        float impactTilt = 0.0f
    ) {
        using namespace Gdiplus;
        Pt tl = KeyboardLayout::v2KbPoint(0.0f, 0.0f);
        Pt tr = KeyboardLayout::v2KbPoint(1.0f, 0.0f);
        Pt br = KeyboardLayout::v2KbPoint(1.0f, 1.0f);
        Pt bl = KeyboardLayout::v2KbPoint(0.0f, 1.0f);
        constexpr float depth = 28.0f;

        // Disney 12-Principles Follow-Through on USB cord (whips & jiggles softly with keyboard impact!)
        {
            float cordWhipX = impactTilt * 24.0f;
            float cordWhipY = impactY * 12.0f;
            Pen cordPen(ink, lw * 1.05f);
            setRound(cordPen);
            GraphicsPath cord;
            cord.AddBezier(PointF(268.0f + impactTilt * 8.0f, 522.0f + impactY * 8.0f),
                           PointF(220.0f + cordWhipX * 0.4f, 536.0f + cordWhipY * 0.5f),
                           PointF(218.0f + cordWhipX * 0.9f, 572.0f + cordWhipY * 0.8f),
                           PointF(224.0f + cordWhipX * 0.7f, 598.0f + cordWhipY * 0.6f));
            cord.AddBezier(PointF(224.0f + cordWhipX * 0.7f, 598.0f + cordWhipY * 0.6f),
                           PointF(230.0f + cordWhipX * 0.6f, 632.0f + cordWhipY * 0.4f),
                           PointF(186.0f + cordWhipX * 0.3f, 648.0f),
                           PointF(132.0f + cordWhipX * 0.35f, 646.0f + cordWhipY * 0.25f));
            g.DrawPath(&cordPen, &cord);
        }

        // Disney Squash & Stretch + Micro-Vibration transform on the whole keyboard chassis!
        GraphicsState kbState = g.Save();
        constexpr float kbPivotX = 410.0f, kbPivotY = 584.0f;
        float sx = 1.0f + std::max(0.0f, impactY) * 0.026f;
        float sy = 1.0f - std::max(0.0f, impactY) * 0.052f;
        g.TranslateTransform(kbPivotX + impactTilt * 11.0f, kbPivotY + impactY * 9.5f);
        g.RotateTransform(impactTilt * 0.024f * RadToDeg);
        g.ScaleTransform(sx, sy);
        g.TranslateTransform(-kbPivotX, -kbPivotY);

        Pen kbPen(ink, lw);
        setRound(kbPen);

        // 2. 3D Underside bevel hull
        {
            GraphicsPath bevelPath;
            addRoundedQuadPath(bevelPath,
                               { tl.x, tl.y + depth * 0.45f },
                               { tr.x, tr.y + depth },
                               { br.x, br.y + depth },
                               { bl.x, bl.y + depth * 0.85f },
                               28.0f);
            SolidBrush bb(bevelColor);
            g.FillPath(&bb, &bevelPath);
            g.DrawPath(&kbPen, &bevelPath);
        }

        // 3. Top deck hull
        {
            GraphicsPath topPath;
            addRoundedQuadPath(topPath, tl, tr, br, bl, 28.0f);
            SolidBrush db(deckColor);
            g.FillPath(&db, &topPath);
            g.DrawPath(&kbPen, &topPath);
        }

        // 4. Left smooth rectangular pad (u=0.06..0.28, v=0.14..0.84)
        {
            GraphicsPath padPath;
            addRoundedQuadPath(padPath,
                               KeyboardLayout::v2KbPoint(0.06f, 0.14f),
                               KeyboardLayout::v2KbPoint(0.28f, 0.14f),
                               KeyboardLayout::v2KbPoint(0.28f, 0.84f),
                               KeyboardLayout::v2KbPoint(0.06f, 0.84f),
                               14.0f);
            SolidBrush kb(keyColor);
            g.FillPath(&kb, &padPath);
            Pen padPen(ink, lw * 0.82f);
            setRound(padPen);
            g.DrawPath(&padPen, &padPath);
        }

        // 5. Right keycap well (u=0.31..0.95, v=0.11..0.87) — 4 rows x 8 cols with vivid Disney backlit glow & press travel!
        constexpr float wellU0 = 0.31f, wellU1 = 0.95f;
        constexpr float wellV0 = 0.11f, wellV1 = 0.87f;
        GraphicsPath wellPath;
        addRoundedQuadPath(wellPath,
                           KeyboardLayout::v2KbPoint(wellU0, wellV0),
                           KeyboardLayout::v2KbPoint(wellU1, wellV0),
                           KeyboardLayout::v2KbPoint(wellU1, wellV1),
                           KeyboardLayout::v2KbPoint(wellU0, wellV1),
                           16.0f);

        std::vector<std::pair<Pt, float>> glowBlooms;
        bool hasSparkCenter = false;
        Pt sparkCenter = { 0.0f, 0.0f };

        {
            GraphicsState ws = g.Save();
            SolidBrush kb(keyColor);
            g.FillPath(&kb, &wellPath);
            g.SetClip(&wellPath, CombineModeIntersect);

            // Optional RGB marquee wash across keycap well
            if (marquee) {
                float phase = std::fmod(physics.marqueePhase, 1.0f);
                if (phase < 0.0f) phase += 1.0f;
                Color mCol = hsvColor(phase + 0.52f, 0.58f, 1.0f, 82);
                Color gCols[2] = { mCol, withColorAlpha(glowColor, 0.18f) };
                REAL gLocs[2] = { 0.0f, 1.0f };
                Pt gs = KeyboardLayout::v2KbPoint(wellU0, 0.5f);
                Pt ge = KeyboardLayout::v2KbPoint(wellU1, 0.5f);
                fillClampedLinearGradient(g, &wellPath, nullptr, PointF(gs.x, gs.y), PointF(ge.x, ge.y), gCols, gLocs, 2);
            }

            // Map live pressed keys in `physics.keyGlow` onto Video 2's 4x8 keycap grid using exact shared cell mapper!
            float cellGlow[4][8] = {};
            for (const auto& kv : physics.keyGlow) {
                if (kv.second <= 0.03f) continue;
                auto info = KeyboardLayout::v2KeyCellInfo(kv.first);
                cellGlow[info.row][info.col] = std::max(cellGlow[info.row][info.col], kv.second);
                if (kv.first == physics.kbSparkKey) {
                    hasSparkCenter = true;
                    sparkCenter = info.center;
                }
            }

            constexpr int rows = 4, cols = 8;
            for (int r = 0; r < rows; ++r) {
                float rv0 = lerpF(wellV0, wellV1, (float)r / (float)rows);
                float rv1 = lerpF(wellV0, wellV1, (float)(r + 1) / (float)rows);
                for (int c = 0; c < cols; ++c) {
                    if (r == 3 && c > 2 && c <= 5) continue;
                    int cEnd = (r == 3 && c == 2) ? 6 : (c + 1);
                    float cu0 = lerpF(wellU0, wellU1, (float)c / (float)cols);
                    float cu1 = lerpF(wellU0, wellU1, (float)cEnd / (float)cols);
                    float gl = cellGlow[r][c];
                    if (r == 3 && c == 2) {
                        for (int sc = 2; sc < 6; ++sc) gl = std::max(gl, cellGlow[3][sc]);
                    }
                    bool isAccent = (r == 0 && c == 0) || (r == 2 && c == 7);
                    if (isAccent || gl > 0.03f) {
                        Pt pTL = KeyboardLayout::v2KbPoint(cu0, rv0);
                        Pt pTR = KeyboardLayout::v2KbPoint(cu1, rv0);
                        Pt pBR = KeyboardLayout::v2KbPoint(cu1, rv1);
                        Pt pBL = KeyboardLayout::v2KbPoint(cu0, rv1);
                        PointF quad[4] = { { pTL.x, pTL.y }, { pTR.x, pTR.y }, { pBR.x, pBR.y }, { pBL.x, pBL.y } };
                        if (gl > 0.03f) {
                            Color vivid = blendColor(withColorAlpha(glowColor, 1.0f), Color(255, 255, 245, 184), std::min(0.55f, gl * 0.55f));
                            Color fill = blendColor(isAccent ? accentColor : keyColor, vivid, std::min(1.0f, 0.45f + gl * 0.55f));
                            SolidBrush fb(fill);
                            g.FillPolygon(&fb, quad, 4);

                            // Subtle inner top press shadow (physical key depression cue!)
                            Pt pInL = lerpPt(pTL, pBL, 0.24f);
                            Pt pInR = lerpPt(pTR, pBR, 0.24f);
                            PointF dep[4] = { { pTL.x, pTL.y }, { pTR.x, pTR.y }, { pInR.x, pInR.y }, { pInL.x, pInL.y } };
                            SolidBrush db(Color((BYTE)std::clamp((int)std::lround(41.0f * gl), 0, 255), 0, 0, 0));
                            g.FillPolygon(&db, dep, 4);

                            Pt ctr = { (pTL.x + pTR.x + pBR.x + pBL.x) * 0.25f, (pTL.y + pTR.y + pBR.y + pBL.y) * 0.25f };
                            glowBlooms.push_back({ ctr, gl });
                        } else {
                            SolidBrush ab(accentColor);
                            g.FillPolygon(&ab, quad, 4);
                        }
                    }
                }
            }

            // Crisp hand-drawn grid lines inside keycap well (subtle lighter charcoal on dark .kurokb themes!)
            float keyBright = (float)std::max({ keyColor.GetR(), keyColor.GetG(), keyColor.GetB() }) / 255.0f;
            Color gridInk = (keyBright < 0.28f) ? Color(235, 87, 92, 105) : ink;
            Pen gridPen(gridInk, lw * 0.78f);
            setRound(gridPen);
            for (int r = 1; r < rows; ++r) {
                float rv = lerpF(wellV0, wellV1, (float)r / (float)rows);
                Pt a = KeyboardLayout::v2KbPoint(wellU0, rv);
                Pt b = KeyboardLayout::v2KbPoint(wellU1, rv);
                g.DrawLine(&gridPen, a.x, a.y, b.x, b.y);
            }
            for (int c = 1; c < cols; ++c) {
                float cu = lerpF(wellU0, wellU1, (float)c / (float)cols);
                float stopV = (c >= 3 && c <= 5) ? lerpF(wellV0, wellV1, 3.0f / 4.0f) : wellV1;
                Pt a = KeyboardLayout::v2KbPoint(cu, wellV0);
                Pt b = KeyboardLayout::v2KbPoint(cu, stopV);
                g.DrawLine(&gridPen, a.x, a.y, b.x, b.y);
            }
            g.Restore(ws);
        }

        // Bold outer border of keycap well
        {
            Pen wellPen(ink, lw * 0.84f);
            setRound(wellPen);
            g.DrawPath(&wellPen, &wellPath);
        }

        // Soft radiant backlit bloom halos spilling cleanly over each active keycap!
        for (const auto& blm : glowBlooms) {
            drawRadialGlow(g, blm.first, 56.0f + blm.second * 18.0f, withColorAlpha(glowColor, 0.62f * blm.second));
        }

        // Disney impact comic spark ticks (\ | /) popping crisply for 0.14s on slap contact!
        if (physics.kbSparkTimer > 0.005f && hasSparkCenter) {
            float t = std::clamp(physics.kbSparkTimer / 0.14f, 0.0f, 1.0f);
            float spread = 14.0f + (1.0f - t) * 26.0f;
            float len = 14.0f * t + 6.0f;
            float sAlpha = std::min(1.0f, t * 1.4f);
            Pen outerSpark(scaleAlpha(ink, sAlpha), 9.5f);
            Pen innerSpark(scaleAlpha(withColorAlpha(glowColor, 1.0f), sAlpha), 4.5f);
            setRound(outerSpark);
            setRound(innerSpark);
            const float angles[3] = { -2.35f, -1.55f, -0.75f };
            for (float ang : angles) {
                float x0 = sparkCenter.x + std::cos(ang) * spread;
                float y0 = sparkCenter.y + std::sin(ang) * spread - 6.0f;
                float x1 = sparkCenter.x + std::cos(ang) * (spread + len);
                float y1 = sparkCenter.y + std::sin(ang) * (spread + len) - 6.0f;
                g.DrawLine(&outerSpark, x0, y0, x1, y1);
                g.DrawLine(&innerSpark, x0, y0, x1, y1);
            }
        }

        g.Restore(kbState);
    }

    static void drawDouniComicMouse(
        Gdiplus::Graphics& g,
        Pt center,
        float pressLeft,
        float pressRight,
        Gdiplus::Color bodyColor,
        Gdiplus::Color bevelColor,
        Gdiplus::Color wheelColor,
        Gdiplus::Color glowColor,
        Gdiplus::Color ink,
        float lw
    ) {
        using namespace Gdiplus;
        float pressShift = std::max(pressLeft, pressRight) * 5.0f;
        GraphicsState st = g.Save();

        // Cute short wavy comic mouse cord trailing up-left
        {
            Pen cordPen(ink, lw * 0.88f);
            setRound(cordPen);
            g.DrawBezier(&cordPen,
                         PointF(center.x - 42.0f, center.y - 10.0f + pressShift),
                         PointF(center.x - 66.0f, center.y - 36.0f),
                         PointF(center.x - 86.0f, center.y - 42.0f),
                         PointF(center.x - 102.0f, center.y - 16.0f));
        }

        g.TranslateTransform(center.x, center.y + pressShift);
        g.RotateTransform(-0.34f * RadToDeg);

        constexpr float rx = 46.0f, ry = 33.0f;
        Pen inkPen(ink, lw);
        setRound(inkPen);

        // 3D comic bottom lip
        RectF lipRect(-rx, -ry + 10.0f, rx * 2.0f, ry * 2.0f);
        SolidBrush bevelBrush(bevelColor);
        g.FillEllipse(&bevelBrush, lipRect);
        g.DrawEllipse(&inkPen, lipRect);

        // Top mouse shell
        RectF topRect(-rx, -ry, rx * 2.0f, ry * 2.0f);
        SolidBrush bodyBrush(bodyColor);
        g.FillEllipse(&bodyBrush, topRect);

        // Left / right button click highlights
        if (pressLeft > 0.04f || pressRight > 0.04f) {
            GraphicsState cs = g.Save();
            GraphicsPath ep;
            ep.AddEllipse(topRect);
            g.SetClip(&ep, CombineModeIntersect);
            if (pressLeft > 0.04f) {
                SolidBrush gb(withColorAlpha(glowColor, 0.55f * pressLeft));
                g.FillRectangle(&gb, -rx, 0.0f, rx * 0.96f, ry);
            }
            if (pressRight > 0.04f) {
                SolidBrush gb(withColorAlpha(glowColor, 0.55f * pressRight));
                g.FillRectangle(&gb, -rx, -ry, rx * 0.96f, ry);
            }
            g.Restore(cs);
        }

        // Button seam & scroll wheel
        {
            Pen seamPen(ink, lw * 0.72f);
            setRound(seamPen);
            GraphicsPath seam;
            addQuadBezier(seam, { -4.0f, -ry + 4.0f }, { 4.0f, 0.0f }, { -4.0f, ry - 4.0f });
            g.DrawPath(&seamPen, &seam);
            g.DrawLine(&seamPen, -rx + 5.0f, 0.0f, -4.0f, 0.0f);
        }

        // Scroll wheel pill
        {
            GraphicsPath wheelPath;
            addRoundedRect(wheelPath, -29.0f, -5.5f, 17.0f, 11.0f, 5.0f);
            SolidBrush wb(wheelColor);
            g.FillPath(&wb, &wheelPath);
            Pen wp(ink, lw * 0.62f);
            setRound(wp);
            g.DrawPath(&wp, &wheelPath);
        }

        // Outer comic shell outline
        g.DrawEllipse(&inkPen, topRect);
        g.Restore(st);
    }

    /// Hand-drawn chunky comic Graphics Tablet in Video 2's bold-ink aesthetic (with live glowing stroke trail & parked stylus!).
    static void drawDouniComicTablet(
        Gdiplus::Graphics& g,
        const CatPhysics& physics,
        Gdiplus::Color deckColor,
        Gdiplus::Color bevelColor,
        Gdiplus::Color padColor,
        Gdiplus::Color accentColor,
        Gdiplus::Color glowColor,
        Gdiplus::Color eyeColor,
        Gdiplus::Color ink,
        float lw,
        bool showParkedStylus
    ) {
        using namespace Gdiplus;
        Pt tl = v2TabletPoint(0.0f, 0.0f);
        Pt tr = v2TabletPoint(1.0f, 0.0f);
        Pt br = v2TabletPoint(1.0f, 1.0f);
        Pt bl = v2TabletPoint(0.0f, 1.0f);
        constexpr float depth = 16.0f;

        Pen inkPen(ink, lw);
        setRound(inkPen);

        // 1. Short wavy comic USB cord trailing up-left from tablet top edge
        {
            Pt cordStart = v2TabletPoint(0.36f, 0.0f);
            Pen cordPen(ink, lw * 0.85f);
            setRound(cordPen);
            g.DrawBezier(&cordPen,
                         PointF(cordStart.x, cordStart.y),
                         PointF(cordStart.x - 16.0f, cordStart.y - 42.0f),
                         PointF(cordStart.x - 50.0f, cordStart.y - 54.0f),
                         PointF(cordStart.x - 74.0f, cordStart.y - 42.0f));
        }

        // 2. 3D Underside bevel lip
        {
            GraphicsPath bevelPath;
            addRoundedQuadPath(bevelPath,
                               { tl.x, tl.y + depth * 0.45f },
                               { tr.x, tr.y + depth },
                               { br.x, br.y + depth },
                               { bl.x, bl.y + depth * 0.85f },
                               18.0f);
            SolidBrush bb(bevelColor);
            g.FillPath(&bb, &bevelPath);
            g.DrawPath(&inkPen, &bevelPath);
        }

        // 3. Top tablet hull
        {
            GraphicsPath topPath;
            addRoundedQuadPath(topPath, tl, tr, br, bl, 18.0f);
            SolidBrush db(deckColor);
            g.FillPath(&db, &topPath);
            g.DrawPath(&inkPen, &topPath);
        }

        // 4. Recessed active drawing surface pad (u = 0.23..0.93, v = 0.12..0.88)
        GraphicsPath padPath;
        addRoundedQuadPath(padPath,
                           v2TabletPoint(0.23f, 0.12f),
                           v2TabletPoint(0.93f, 0.12f),
                           v2TabletPoint(0.93f, 0.88f),
                           v2TabletPoint(0.23f, 0.88f),
                           12.0f);
        SolidBrush padBrush(padColor);
        g.FillPath(&padBrush, &padPath);

        // Active-area corner L-brackets ([ ]) & live glowing ink stroke trail clipped inside pad!
        {
            GraphicsState cs = g.Save();
            g.SetClip(&padPath, CombineModeIntersect);

            float padBright = (float)std::max({ padColor.GetR(), padColor.GetG(), padColor.GetB() }) / 255.0f;
            Color bracketCol = (padBright < 0.30f) ? Color(122, 219, 219, 219) : scaleAlpha(ink, 0.45f);
            Pen bracketPen(bracketCol, lw * 0.45f);
            setRound(bracketPen);
            constexpr float corners[4][4] = {
                { 0.28f, 0.20f,  0.09f,  0.14f },
                { 0.88f, 0.20f, -0.09f,  0.14f },
                { 0.28f, 0.80f,  0.09f, -0.14f },
                { 0.88f, 0.80f, -0.09f, -0.14f }
            };
            for (const auto& k : corners) {
                Pt c = v2TabletPoint(k[0], k[1]);
                Pt h = v2TabletPoint(k[0] + k[2], k[1]);
                Pt v = v2TabletPoint(k[0], k[1] + k[3]);
                PointF pts[3] = { PointF(h.x, h.y), PointF(c.x, c.y), PointF(v.x, v.y) };
                g.DrawLines(&bracketPen, pts, 3);
            }

            // Live fading comic ink trail mapped 1:1 from physics.tabletTrail!
            if (physics.tabletTrail.size() >= 2) {
                for (size_t i = 1; i < physics.tabletTrail.size(); ++i) {
                    const auto& a = physics.tabletTrail[i - 1];
                    const auto& b = physics.tabletTrail[i];
                    if (std::hypot(b.point.x - a.point.x, b.point.y - a.point.y) > 22.0f) continue;
                    float life = std::max(0.0f, 1.0f - b.age / 0.72f);
                    if (life <= 0.01f) continue;
                    Pt uvA = douniTabletUV(a.point);
                    Pt uvB = douniTabletUV(b.point);
                    Pt pA = v2TabletPoint(uvA.x, uvA.y);
                    Pt pB = v2TabletPoint(uvB.x, uvB.y);
                    Pen tp(withColorAlpha(eyeColor, life * 0.92f), 4.5f + life * 5.0f);
                    setRound(tp);
                    g.DrawLine(&tp, pA.x, pA.y, pB.x, pB.y);
                }
            }

            // Glowing nib contact halo when drawing
            if (!showParkedStylus && physics.tabletPenPress.value > 0.08f) {
                Pt uv = douniTabletUV(physics.tabletNib.point());
                Pt nib = v2TabletPoint(uv.x, uv.y);
                drawRadialGlow(g, nib, 24.0f + physics.tabletPenPress.value * 14.0f,
                               withColorAlpha(eyeColor, 0.55f * physics.tabletPenPress.value));
            }
            g.Restore(cs);
        }

        // Bold ink border around recessed pad
        {
            Pen padPen(ink, lw * 0.72f);
            setRound(padPen);
            g.DrawPath(&padPen, &padPath);
        }

        // 5. Left bezel ExpressKeys (3 chunky comic pills) + glowing status LED dot
        {
            Pt ledPt = v2TabletPoint(0.125f, 0.20f);
            Color ledCol = (physics.tabletPenPress.value > 0.12f) ? eyeColor : glowColor;
            drawRadialGlow(g, ledPt, 14.0f, withColorAlpha(ledCol, 0.65f));
            SolidBrush lb(ledCol);
            g.FillEllipse(&lb, ledPt.x - 5.5f, ledPt.y - 5.5f, 11.0f, 11.0f);
            Pen lp(ink, lw * 0.42f);
            setRound(lp);
            g.DrawEllipse(&lp, ledPt.x - 5.5f, ledPt.y - 5.5f, 11.0f, 11.0f);

            SolidBrush ab(accentColor);
            Pen kpPen(ink, lw * 0.48f);
            setRound(kpPen);
            constexpr float kvs[3] = { 0.40f, 0.58f, 0.76f };
            for (float kv : kvs) {
                GraphicsPath kp;
                addRoundedQuadPath(kp,
                                   v2TabletPoint(0.07f, kv - 0.06f),
                                   v2TabletPoint(0.175f, kv - 0.06f),
                                   v2TabletPoint(0.175f, kv + 0.06f),
                                   v2TabletPoint(0.07f, kv + 0.06f),
                                   4.5f);
                g.FillPath(&ab, &kp);
                g.DrawPath(&kpPen, &kp);
            }
        }

        // 6. Parked hand-drawn comic stylus resting along top bezel when cat is typing/idle!
        if (showParkedStylus) {
            Pt nib = v2TabletPoint(0.88f, -0.06f);
            Pt tail = v2TabletPoint(0.14f, -0.06f);
            float ang = std::atan2(tail.y - nib.y, tail.x - nib.x);
            float len = std::hypot(tail.x - nib.x, tail.y - nib.y);
            GraphicsState ps = g.Save();
            g.TranslateTransform(nib.x, nib.y);
            g.RotateTransform(ang * RadToDeg);
            drawDouniComicStylus(g, len, glowColor, eyeColor, ink, lw, 0.0f);
            g.Restore(ps);
        }
    }

    /// Chunky hand-drawn comic stylus oriented along +X from nib `(0,0)` to rounded eraser cap `(length,0)`.
    static void drawDouniComicStylus(
        Gdiplus::Graphics& g,
        float length,
        Gdiplus::Color accentColor,
        Gdiplus::Color eyeColor,
        Gdiplus::Color ink,
        float lw,
        float pressed
    ) {
        using namespace Gdiplus;
        constexpr float halfW = 10.5f;
        constexpr float coneX = 26.0f;
        float bodyEnd = std::max(coneX + 2.0f, length - 12.0f);

        GraphicsPath pen;
        pen.AddLine(0.0f, 0.0f, coneX, -halfW);
        pen.AddLine(coneX, -halfW, bodyEnd, -halfW);
        addQuadBezier(pen, { bodyEnd, -halfW }, { length, -halfW }, { length, 0.0f });
        addQuadBezier(pen, { length, 0.0f }, { length, halfW }, { bodyEnd, halfW });
        pen.AddLine(bodyEnd, halfW, coneX, halfW);
        pen.CloseFigure();

        Color barrelCol(255, 64, 61, 64);
        Color gripCol(255, 92, 89, 94);

        // Base fill
        SolidBrush barrelBrush(barrelCol);
        g.FillPath(&barrelBrush, &pen);

        // Clipped grip sleeve, warm accent collar ring, glowing nib tip & comic specular streak!
        {
            GraphicsState cs = g.Save();
            g.SetClip(&pen, CombineModeIntersect);
            SolidBrush gripBrush(gripCol);
            g.FillRectangle(&gripBrush, coneX, -halfW - 2.0f, 34.0f, (halfW + 2.0f) * 2.0f);
            SolidBrush accentBrush(accentColor);
            g.FillRectangle(&accentBrush, coneX + 34.0f, -halfW - 2.0f, 10.0f, (halfW + 2.0f) * 2.0f);
            SolidBrush nibBrush(pressed > 0.12f ? eyeColor : Color(255, 240, 240, 240));
            g.FillRectangle(&nibBrush, -2.0f, -halfW, 14.0f, halfW * 2.0f);
            SolidBrush specBrush(Color(66, 255, 255, 255));
            g.FillRectangle(&specBrush, coneX + 2.0f, -halfW + 2.5f, std::max(1.0f, length - coneX - 18.0f), 3.5f);
            g.Restore(cs);
        }

        // Bold Video 2 comic ink outline around stylus
        Pen inkPen(ink, lw * 0.72f);
        setRound(inkPen);
        g.DrawPath(&inkPen, &pen);

        // Cute comic side button pill on upper barrel
        GraphicsPath btn;
        addRoundedRect(btn, coneX + 8.0f, -halfW - 3.5f, 18.0f, 5.5f, 2.5f);
        SolidBrush btnBrush(Color(255, 214, 214, 214));
        g.FillPath(&btnBrush, &btn);
        Pen btnPen(ink, lw * 0.45f);
        setRound(btnPen);
        g.DrawPath(&btnPen, &btn);
    }

    struct V2ArmShape {
        Pt shTop, shBot, tip, topC1, topC2, botC1, botC2;
        Pt toe1A, toe1B, toe2A, toe2B;
    };

    static V2ArmShape blendV2ArmShape(const V2ArmShape& a, const V2ArmShape& b, float t) {
        return {
            lerpPt(a.shTop, b.shTop, t), lerpPt(a.shBot, b.shBot, t), lerpPt(a.tip, b.tip, t),
            lerpPt(a.topC1, b.topC1, t), lerpPt(a.topC2, b.topC2, t),
            lerpPt(a.botC1, b.botC1, t), lerpPt(a.botC2, b.botC2, t),
            lerpPt(a.toe1A, b.toe1A, t), lerpPt(a.toe1B, b.toe1B, t),
            lerpPt(a.toe2A, b.toe2A, t), lerpPt(a.toe2B, b.toe2B, t)
        };
    }

    /// Builds a guaranteed constant-volume chubby Video-2 mitten arm from `shoulder` to exact key center `keyPoint`.
    static V2ArmShape v2ChubbySlamArm(Pt shoulder, Pt keyPoint, float archSign) {
        (void)archSign;
        Pt target = { keyPoint.x, keyPoint.y - 4.0f };
        float dx = target.x - shoulder.x;
        float dy = target.y - shoulder.y;
        float dist = std::max(56.0f, std::hypot(dx, dy));
        float ux = dx / dist, uy = dy / dist;
        float nx = -uy, ny = ux;
        if (ny > 0.0f) { nx = -nx; ny = -ny; }

        constexpr float rS = 34.0f;
        constexpr float rP = 33.0f;
        float archLift = 14.0f * std::fabs(ux);

        Pt shTop = { shoulder.x + nx * rS, shoulder.y + ny * rS };
        Pt shBot = { shoulder.x - nx * rS, shoulder.y - ny * rS };
        Pt tip   = { target.x + ux * 16.0f, target.y + uy * 16.0f };

        Pt topC1 = { lerpF(shTop.x, target.x + nx * rP, 0.42f), lerpF(shTop.y, target.y + ny * rP, 0.42f) - archLift };
        Pt topC2 = { target.x + nx * (rP * 1.15f) + ux * 8.0f, target.y + ny * (rP * 1.15f) + uy * 8.0f };
        Pt botC1 = { target.x - nx * (rP * 1.15f) + ux * 8.0f, target.y - ny * (rP * 1.15f) + uy * 8.0f };
        Pt botC2 = { lerpF(shBot.x, target.x - nx * rP, 0.42f), lerpF(shBot.y, target.y - ny * rP, 0.42f) - archLift * 0.4f };

        Pt tBase = { target.x - ux * 10.0f, target.y - uy * 10.0f };
        constexpr float tLen = 24.0f;
        Pt toe1A = { tBase.x + nx * 10.0f, tBase.y + ny * 10.0f };
        Pt toe1B = { toe1A.x + ux * tLen, toe1A.y + uy * tLen };
        Pt toe2A = { tBase.x - nx * 12.0f, tBase.y - ny * 12.0f };
        Pt toe2B = { toe2A.x + ux * tLen, toe2A.y + uy * tLen };

        return { shTop, shBot, tip, topC1, topC2, botC1, botC2, toe1A, toe1B, toe2A, toe2B };
    }

    static void drawV2LeftArm(
        Gdiplus::Graphics& g, float pose, float mouseBlend, Pt mouseTarget,
        const Pt* slamTarget, Gdiplus::Color cream, Gdiplus::Color taupe, Gdiplus::Color ink,
        float lw, float swingVelocity = 0.0f
    ) {
        using namespace Gdiplus;
        const V2ArmShape poseA = {
            { 416.0f, 312.0f }, { 416.0f, 374.0f }, { 242.0f, 346.0f },
            { 344.0f, 288.0f }, { 260.0f, 298.0f }, { 242.0f, 392.0f }, { 332.0f, 386.0f },
            { 256.0f, 356.0f }, { 258.0f, 380.0f }, { 278.0f, 360.0f }, { 280.0f, 384.0f }
        };
        V2ArmShape poseB = slamTarget
            ? v2ChubbySlamArm({ 426.0f, 350.0f }, *slamTarget, -1.0f)
            : V2ArmShape{
                { 422.0f, 326.0f }, { 432.0f, 392.0f }, { 274.0f, 412.0f },
                { 348.0f, 318.0f }, { 284.0f, 356.0f }, { 272.0f, 454.0f }, { 348.0f, 434.0f },
                { 288.0f, 414.0f }, { 292.0f, 440.0f }, { 310.0f, 416.0f }, { 314.0f, 442.0f }
            };
        const V2ArmShape poseC = {
            { 422.0f, 262.0f }, { 434.0f, 336.0f }, { 258.0f, 248.0f },
            { 360.0f, 222.0f }, { 286.0f, 204.0f }, { 254.0f, 298.0f }, { 352.0f, 312.0f },
            { 274.0f, 246.0f }, { 274.0f, 278.0f }, { 296.0f, 254.0f }, { 296.0f, 286.0f }
        };
        const V2ArmShape poseM = {
            { 414.0f, 298.0f }, { 414.0f, 356.0f }, { mouseTarget.x - 16.0f, mouseTarget.y - 2.0f },
            { 330.0f, 274.0f }, { mouseTarget.x + 28.0f, mouseTarget.y - 36.0f },
            { mouseTarget.x - 12.0f, mouseTarget.y + 38.0f }, { 312.0f, 358.0f },
            { mouseTarget.x - 2.0f, mouseTarget.y + 6.0f }, { mouseTarget.x - 2.0f, mouseTarget.y + 28.0f },
            { mouseTarget.x + 18.0f, mouseTarget.y + 8.0f }, { mouseTarget.x + 18.0f, mouseTarget.y + 30.0f }
        };

        V2ArmShape typingShape = (pose >= 0.0f)
            ? blendV2ArmShape(poseA, poseC, std::min(1.05f, pose))
            : blendV2ArmShape(poseA, poseB, std::min(1.05f, -pose));
        V2ArmShape sh = (mouseBlend > 0.01f) ? blendV2ArmShape(typingShape, poseM, mouseBlend) : typingShape;

        GraphicsPath fillPath, strokePath;
        strokePath.AddBezier(PointF(sh.shTop.x, sh.shTop.y), PointF(sh.topC1.x, sh.topC1.y), PointF(sh.topC2.x, sh.topC2.y), PointF(sh.tip.x, sh.tip.y));
        strokePath.AddBezier(PointF(sh.tip.x, sh.tip.y), PointF(sh.botC1.x, sh.botC1.y), PointF(sh.botC2.x, sh.botC2.y), PointF(sh.shBot.x, sh.shBot.y));
        fillPath.AddBezier(PointF(sh.shTop.x, sh.shTop.y), PointF(sh.topC1.x, sh.topC1.y), PointF(sh.topC2.x, sh.topC2.y), PointF(sh.tip.x, sh.tip.y));
        fillPath.AddBezier(PointF(sh.tip.x, sh.tip.y), PointF(sh.botC1.x, sh.botC1.y), PointF(sh.botC2.x, sh.botC2.y), PointF(sh.shBot.x, sh.shBot.y));
        fillPath.CloseFigure();

        // Outer white sticker rim around the protruding paw
        if (whiteOutlineEnabled()) {
            Pen rimPen(blackOutline(), lw + 9.0f);
            setRound(rimPen);
            g.DrawPath(&rimPen, &strokePath);
        }

        // Smooth cream-to-taupe paw gradient (tip taupe -> shoulder cream, matching Video 2!)
        {
            Color cols[3] = { taupe, taupe, cream };
            REAL locs[3] = { 0.0f, 0.42f, 0.80f };
            PointF start(sh.tip.x, sh.tip.y);
            PointF end((sh.shTop.x + sh.shBot.x) * 0.5f, (sh.shTop.y + sh.shBot.y) * 0.5f);
            fillClampedLinearGradient(g, &fillPath, nullptr, start, end, cols, locs, 3);
        }

        // Crisp open comic outline (no hard seam across the shoulder!)
        Pen pen(ink, lw);
        setRound(pen);
        g.DrawPath(&pen, &strokePath);

        // 2 curved vertical toe ticks
        Pen toePen(ink, lw * 0.88f);
        setRound(toePen);
        g.DrawLine(&toePen, sh.toe1A.x, sh.toe1A.y, sh.toe1B.x, sh.toe1B.y);
        g.DrawLine(&toePen, sh.toe2A.x, sh.toe2A.y, sh.toe2B.x, sh.toe2B.y);

        // Disney Principle #7 (Arcs): crisp subtle motion-arc smear lines when whipping fast!
        float spd = std::fabs(swingVelocity);
        if (spd > 4.2f && mouseBlend < 0.2f) {
            float a = std::min(0.45f, (spd - 4.2f) / 10.0f);
            float dir = (swingVelocity > 0.0f) ? 1.0f : -1.0f;
            Pen arcPen(scaleAlpha(ink, a), lw * 0.55f);
            setRound(arcPen);
            GraphicsPath a1, a2;
            addQuadBezier(a1, { sh.tip.x - 16.0f, sh.tip.y + dir * 22.0f }, { sh.tip.x - 24.0f, sh.tip.y + dir * 48.0f }, { sh.tip.x + 14.0f, sh.tip.y + dir * 68.0f });
            addQuadBezier(a2, { sh.tip.x +  6.0f, sh.tip.y + dir * 28.0f }, { sh.tip.x +  2.0f, sh.tip.y + dir * 50.0f }, { sh.tip.x + 34.0f, sh.tip.y + dir * 64.0f });
            g.DrawPath(&arcPen, &a1);
            g.DrawPath(&arcPen, &a2);
        }
    }

    static void drawV2RightArm(
        Gdiplus::Graphics& g, float pose, const Pt* slamTarget,
        Gdiplus::Color cream, Gdiplus::Color taupe, Gdiplus::Color ink,
        float lw, float swingVelocity = 0.0f
    ) {
        using namespace Gdiplus;
        const V2ArmShape poseA = {
            { 616.0f, 344.0f }, { 618.0f, 406.0f }, { 410.0f, 368.0f },
            { 544.0f, 306.0f }, { 432.0f, 306.0f }, { 406.0f, 414.0f }, { 522.0f, 414.0f },
            { 426.0f, 374.0f }, { 426.0f, 402.0f }, { 452.0f, 378.0f }, { 452.0f, 404.0f }
        };
        const V2ArmShape poseB = {
            { 626.0f, 344.0f }, { 608.0f, 382.0f }, { 422.0f, 294.0f },
            { 564.0f, 278.0f }, { 458.0f, 226.0f }, { 416.0f, 344.0f }, { 518.0f, 350.0f },
            { 440.0f, 296.0f }, { 442.0f, 332.0f }, { 464.0f, 306.0f }, { 466.0f, 338.0f }
        };
        V2ArmShape poseC = slamTarget
            ? v2ChubbySlamArm({ 604.0f, 372.0f }, *slamTarget, 1.0f)
            : V2ArmShape{
                { 586.0f, 346.0f }, { 608.0f, 404.0f }, { 406.0f, 414.0f },
                { 498.0f, 344.0f }, { 422.0f, 356.0f }, { 404.0f, 464.0f }, { 500.0f, 446.0f },
                { 420.0f, 422.0f }, { 420.0f, 452.0f }, { 446.0f, 426.0f }, { 446.0f, 454.0f }
            };

        V2ArmShape sh = (pose >= 0.0f)
            ? blendV2ArmShape(poseA, poseB, std::min(1.05f, pose))
            : blendV2ArmShape(poseA, poseC, std::min(1.05f, -pose));

        // In Pose B (right arm sweeps up across lower face), softly mask out the lower chin line directly behind the arm!
        if (pose > 0.35f) {
            SolidBrush maskBrush(scaleAlpha(cream, smoothstep(0.35f, 0.85f, pose)));
            g.FillRectangle(&maskBrush, 446.0f, 332.0f, 164.0f, 32.0f);
        }

        GraphicsPath fillPath, strokePath;
        strokePath.AddBezier(PointF(sh.shTop.x, sh.shTop.y), PointF(sh.topC1.x, sh.topC1.y), PointF(sh.topC2.x, sh.topC2.y), PointF(sh.tip.x, sh.tip.y));
        strokePath.AddBezier(PointF(sh.tip.x, sh.tip.y), PointF(sh.botC1.x, sh.botC1.y), PointF(sh.botC2.x, sh.botC2.y), PointF(sh.shBot.x, sh.shBot.y));
        fillPath.AddBezier(PointF(sh.shTop.x, sh.shTop.y), PointF(sh.topC1.x, sh.topC1.y), PointF(sh.topC2.x, sh.topC2.y), PointF(sh.tip.x, sh.tip.y));
        fillPath.AddBezier(PointF(sh.tip.x, sh.tip.y), PointF(sh.botC1.x, sh.botC1.y), PointF(sh.botC2.x, sh.botC2.y), PointF(sh.shBot.x, sh.shBot.y));
        fillPath.CloseFigure();

        // Outer white sticker rim around the protruding paw
        if (whiteOutlineEnabled()) {
            Pen rimPen(blackOutline(), lw + 8.4f);
            setRound(rimPen);
            g.DrawPath(&rimPen, &strokePath);
        }

        {
            Color cols[3] = { taupe, taupe, cream };
            REAL locs[3] = { 0.0f, 0.45f, 0.84f };
            PointF start(sh.tip.x, sh.tip.y);
            PointF end((sh.shTop.x + sh.shBot.x) * 0.5f, (sh.shTop.y + sh.shBot.y) * 0.5f);
            fillClampedLinearGradient(g, &fillPath, nullptr, start, end, cols, locs, 3);
        }

        Pen pen(ink, lw);
        setRound(pen);
        g.DrawPath(&pen, &strokePath);

        Pen toePen(ink, lw * 0.88f);
        setRound(toePen);
        g.DrawLine(&toePen, sh.toe1A.x, sh.toe1A.y, sh.toe1B.x, sh.toe1B.y);
        g.DrawLine(&toePen, sh.toe2A.x, sh.toe2A.y, sh.toe2B.x, sh.toe2B.y);

        float spd = std::fabs(swingVelocity);
        if (spd > 4.2f) {
            float a = std::min(0.45f, (spd - 4.2f) / 10.0f);
            float dir = (swingVelocity > 0.0f) ? 1.0f : -1.0f;
            Pen arcPen(scaleAlpha(ink, a), lw * 0.55f);
            setRound(arcPen);
            GraphicsPath a1;
            addQuadBezier(a1, { sh.tip.x - 14.0f, sh.tip.y + dir * 24.0f }, { sh.tip.x - 20.0f, sh.tip.y + dir * 48.0f }, { sh.tip.x + 12.0f, sh.tip.y + dir * 68.0f });
            g.DrawPath(&arcPen, &a1);
        }
    }

    // MARK: - Universal Front-Facing Long-Cat Scruff-Lifted Drag Pose (ALL Non-Douni Skins!)

    static void drawNativeScruffDragCat(
        Gdiplus::Graphics& g,
        const CatPhysics& physics,
        const SkinSpec& skin,
        EyeColorTheme eyeTheme,
        float lift
    ) {
        using namespace Gdiplus;
        float liftS = smoothstep(0.0f, 1.0f, lift);
        float startle = 0.0f;
        if (physics.isScruffDragging_) {
            if (physics.scruffHoldTime < 0.14f) {
                startle = 1.0f;
            } else {
                startle = std::max(0.0f, 1.0f - (physics.scruffHoldTime - 0.14f) / 0.08f);
            }
        } else {
            startle = (physics.scruffDropTimer > 0.01f) ? std::min(1.0f, physics.scruffDropTimer / 0.12f) : 1.0f;
        }
        // Lively 2D drag inertia: limbs, lower torso & tail trail behind fast motion and rebound softly!
        float swingH = std::clamp(physics.scruffSwing.value, -1.0f, 1.0f);
        float swingY = std::clamp(physics.scruffSwingY.value, -0.92f, 0.92f);
        float tailSwing = std::clamp(physics.scruffTailSwing.value, -1.25f, 1.25f);
        float idleSway = std::sin(physics.time * 4.2f) * 0.045f * (1.0f - startle);
        float limbSwing = std::clamp(swingH * 0.85f, -0.82f, 0.82f) * (1.0f - startle * 0.45f) + idleSway;
        float upBillow = std::max(0.0f, -swingY);

        const SkinPalette& pal = skin.palette;
        const Build& bd = buildOf(skin);
        float hs = skin.shape.headScale;
        float bw = skin.shape.bodyWidth;
        float nw = skin.shape.neckWidth;
        bool isDazed = (skin.renderStyle == SkinRenderStyle::Dazed);
        bool isBlackRim = isClassicBlackRim(skin);
        Color limbInk = isBlackRim
            ? Color(72, 240, 240, 240)
            : (pal.outline.set ? col(pal.outline) : Color(66, 46, 38, 31));

        // Build- & shape-adaptive long-cat proportions: sleek stretches into a slim liquid noodle;
        // chubby hangs rounder with a plush pear-shaped tummy and stubbier paws.
        bool isSleek = (skin.shape.build == SkinBuild::Sleek);
        float plump = std::clamp((bw - 1.0f) + (isSleek ? -0.15f : 0.0f), -0.35f, 0.38f);
        float limbWScale = std::clamp((bd.limbStartW / 19.0f) * (1.0f + plump * 0.62f), 0.72f, 1.30f);
        float limbLenScale = std::clamp(1.0f - plump * 0.28f + (isSleek ? 0.07f : 0.0f), 0.84f, 1.18f);

        float baseShiftX = physics.bodyShiftX.value + swingH * 10.0f;
        float liftY = -liftS * 12.0f + std::sin(physics.time * 3.8f) * 2.0f * (1.0f - startle) + swingY * 5.0f;
        Pt headCenter = {
            180.0f + baseShiftX,
            lerpF(94.0f, 108.0f, startle) + liftY + (hs - 1.0f) * 6.0f
        };

        float cheekHalfW = bd.cheekHalfW * skin.shape.cheekFullness * hs;
        float crownY = bd.crownBaseY * hs;
        float cheekY = bd.cheekY * hs;
        float chinY = 33.0f * hs;

        // Soft lifted scruff fur gather right between the ears (gentle rounded pinch — never pointy, never overlaps ears!)
        float scruffTuftH = lerpF(6.2f, 3.8f, startle) * hs;
        Pt scruffPinch = { headCenter.x, headCenter.y + crownY - scruffTuftH };

        // Stretched hanging torso dimensions & soft spinal lag curve
        float torsoLen = lerpF(124.0f - plump * 18.0f + (isSleek ? 10.0f : 0.0f), 104.0f - plump * 12.0f, startle) * (1.0f + swingY * 0.08f);
        float torsoBottomY = headCenter.y + torsoLen;
        float hipLagX = (swingH * 22.0f + idleSway * 16.0f) * (1.0f - startle * 0.35f);

        float neckHalfW = std::max(18.0f * hs, (cheekHalfW - bd.neckPinchX * hs) * nw);
        float waistHalfW = bd.waistCtrlW * bw * lerpF(0.84f + plump * 0.24f, 0.92f + plump * 0.20f, startle);
        float hipHalfW = bd.hipHalfW * bw * lerpF(0.95f + plump * 0.26f, 1.00f + plump * 0.20f, startle);
        float bottomDip = 12.0f + std::max(0.0f, plump) * 14.0f;
        float rumpCenterX = headCenter.x + hipLagX;

        auto rot = [](Pt pt, Pt pivot, float angle) -> Pt {
            float dx = pt.x - pivot.x, dy = pt.y - pivot.y;
            float c = std::cos(angle), s = std::sin(angle);
            return { pivot.x + dx * c - dy * s, pivot.y + dx * s + dy * c };
        };

        // 1. Unified front-facing long-cat silhouette
        GraphicsPath longCatPath;
        {
            float tuftBaseX = std::min(12.5f * hs, cheekHalfW * 0.31f);
            float rCheekX = headCenter.x + cheekHalfW;
            float lCheekX = headCenter.x - cheekHalfW;
            float cheekPosY = headCenter.y + cheekY;
            float neckCtrlY = headCenter.y + bd.neckCtrlY * hs;
            float waistY = headCenter.y + torsoLen * 0.48f;
            float hipY = torsoBottomY - 14.0f;
            float waistCenterX = headCenter.x + hipLagX * 0.34f;
            float botHalf = hipHalfW * 0.62f;

            PointF pPinch(scruffPinch.x, scruffPinch.y);
            PointF pRBase(headCenter.x + tuftBaseX, headCenter.y + crownY + 0.5f * hs);
            PointF pRCheek(rCheekX, cheekPosY);
            PointF pRHip(rumpCenterX + hipHalfW, hipY);
            PointF pBot(rumpCenterX, torsoBottomY + bottomDip);
            PointF pLHip(rumpCenterX - hipHalfW, hipY);
            PointF pLCheek(lCheekX, cheekPosY);
            PointF pLBase(headCenter.x - tuftBaseX, headCenter.y + crownY + 0.5f * hs);

            longCatPath.AddBezier(pPinch, PointF(headCenter.x + tuftBaseX * 0.56f, scruffPinch.y + scruffTuftH * 0.06f), PointF(headCenter.x + tuftBaseX * 0.80f, headCenter.y + crownY - scruffTuftH * 0.14f), pRBase);
            longCatPath.AddBezier(pRBase, PointF(headCenter.x + bd.crownCtrlW * hs, headCenter.y + crownY), PointF(rCheekX + 1.5f * hs, headCenter.y + bd.cheekCtrlTopY * hs), pRCheek);
            longCatPath.AddBezier(pRCheek, PointF(headCenter.x + neckHalfW, neckCtrlY), PointF(waistCenterX + waistHalfW, waistY), pRHip);
            longCatPath.AddBezier(pRHip, PointF(rumpCenterX + hipHalfW * 0.96f, torsoBottomY + bottomDip * 0.55f), PointF(rumpCenterX + botHalf, torsoBottomY + bottomDip), pBot);
            longCatPath.AddBezier(pBot, PointF(rumpCenterX - botHalf, torsoBottomY + bottomDip), PointF(rumpCenterX - hipHalfW * 0.96f, torsoBottomY + bottomDip * 0.55f), pLHip);
            longCatPath.AddBezier(pLHip, PointF(waistCenterX - waistHalfW, waistY), PointF(headCenter.x - neckHalfW, neckCtrlY), pLCheek);
            longCatPath.AddBezier(pLCheek, PointF(lCheekX - 1.5f * hs, headCenter.y + bd.cheekCtrlTopY * hs), PointF(headCenter.x - bd.crownCtrlW * hs, headCenter.y + crownY), pLBase);
            longCatPath.AddBezier(pLBase, PointF(headCenter.x - tuftBaseX * 0.80f, headCenter.y + crownY - scruffTuftH * 0.14f), PointF(headCenter.x - tuftBaseX * 0.56f, scruffPinch.y + scruffTuftH * 0.06f), pPinch);
            longCatPath.CloseFigure();
        }

        auto dragBodyMap = [&](SkinPoint pt) -> PointF {
            float u = (pt.y + 98.0f) / 110.0f;
            float uC = std::clamp(u, 0.0f, 1.15f);
            float ySpan = (torsoBottomY + bottomDip * 0.78f) - headCenter.y;
            float mappedY = headCenter.y + u * ySpan;
            float baseRefW = std::max(1.0f, bd.hipHalfW * bw);
            float targetW = lerpF(waistHalfW / std::max(1.0f, bd.waistCtrlW * bw), hipHalfW / baseRefW, smoothstep(0.35f, 0.95f, uC));
            float wScale = lerpF(1.0f, targetW, smoothstep(0.18f, 0.55f, uC));
            float swayX = hipLagX * uC * uC;
            return PointF(headCenter.x + pt.x * bw * wScale + swayX, mappedY);
        };

        // 2. Dangling limp tail emerging from lower-right behind the hip
        Pt tailPivot = { rumpCenterX + hipHalfW * 0.60f, torsoBottomY - 16.0f };
        float tailLen = 76.0f * skin.shape.tailLength * (1.0f + swingY * 0.14f);
        float tailW = std::max(8.0f, (isDazed ? 13.0f : bd.tailWidth * skin.shape.tailThickness) * 1.08f);
        float rawTailAng = (tailSwing * (1.0f - startle * 0.25f) + idleSway * 1.5f) * 0.85f;
        float tailAng = std::clamp(rawTailAng, -1.05f, 0.75f);
        Pt tailRoot = tailPivot;
        Pt baseC1 = { tailPivot.x + 26.0f + upBillow * 10.0f, tailPivot.y + tailLen * 0.22f - upBillow * 10.0f };
        Pt baseC2 = { tailPivot.x + 36.0f + upBillow * 18.0f, tailPivot.y + tailLen * 0.64f - upBillow * 26.0f };
        Pt baseTip = { tailPivot.x + 24.0f + upBillow * 24.0f, tailPivot.y + tailLen - upBillow * 40.0f };
        Pt tailC1 = rot(baseC1, tailPivot, tailAng * 0.45f);
        Pt tailC2 = rot(baseC2, tailPivot, tailAng * 0.92f);
        Pt tailTip = rot(baseTip, tailPivot, tailAng * 1.26f);
        GraphicsPath tailCurvePath;
        tailCurvePath.AddBezier(PointF(tailRoot.x, tailRoot.y), PointF(tailC1.x, tailC1.y), PointF(tailC2.x, tailC2.y), PointF(tailTip.x, tailTip.y));

        // 3. Four symmetric front-facing dangling limbs
        struct DragLimb {
            Pt root, tip;
            float startW, endW, bendX;
            int armDir; // -1 = leftArm, +1 = rightArm, 0 = hind
            bool isBehindBody;
        };
        auto makeLimb = [&](Pt rootA, Pt tipA, Pt rootB, Pt tipB, float w0, float w1, float bendX, float swingScale, float splayDir, int armDir, bool isBehindBody) -> DragLimb {
            Pt r = lerpPt(rootA, rootB, startle);
            Pt baseTip = lerpPt(tipA, tipB, startle);
            float lenFactor = (1.0f + swingY * 0.16f) * limbLenScale;
            Pt stretched = {
                r.x + (baseTip.x - r.x) * lenFactor,
                r.y + (baseTip.y - r.y) * lenFactor - upBillow * 6.0f
            };
            float ang = limbSwing * swingScale + upBillow * 0.20f * splayDir;
            Pt t = rot(stretched, r, ang);
            float dynBendX = bendX + limbSwing * 11.0f * swingScale;
            return { r, t, w0 * limbWScale, w1 * limbWScale, dynBendX, armDir, isBehindBody };
        };

        float shoulderY = headCenter.y + 42.0f * hs;
        // Tuck front-arm roots cleanly INSIDE the torso silhouette so shoulders NEVER bulge outside the body!
        float shoulderInX = std::max(12.0f * hs, std::min(neckHalfW * 0.72f, waistHalfW * 0.56f));
        float armLen = 56.0f;
        DragLimb frontLeftLimb = makeLimb(
            { headCenter.x - shoulderInX + hipLagX * 0.16f, shoulderY },
            { headCenter.x - shoulderInX + 1.5f + hipLagX * 0.30f, shoulderY + armLen },
            { headCenter.x - shoulderInX + hipLagX * 0.12f, shoulderY + 3.0f },
            { headCenter.x - shoulderInX - 4.0f + hipLagX * 0.22f, shoulderY + armLen * 0.84f },
            13.6f, 12.4f, -1.5f, 0.42f, -0.65f, -1, false
        );
        DragLimb frontRightLimb = makeLimb(
            { headCenter.x + shoulderInX + hipLagX * 0.16f, shoulderY },
            { headCenter.x + shoulderInX - 1.5f + hipLagX * 0.30f, shoulderY + armLen },
            { headCenter.x + shoulderInX + hipLagX * 0.12f, shoulderY + 3.0f },
            { headCenter.x + shoulderInX + 4.0f + hipLagX * 0.22f, shoulderY + armLen * 0.84f },
            13.6f, 12.4f, 1.5f, 0.42f, 0.65f, 1, false
        );

        float hindRootX = std::max(13.0f, hipHalfW * 0.42f);
        float hindRootY = torsoBottomY + bottomDip * 0.20f - 12.0f;
        float hindLen = 46.0f;
        DragLimb backLeftLimb = makeLimb(
            { rumpCenterX - hindRootX, hindRootY },
            { rumpCenterX - hindRootX - 2.5f, hindRootY + hindLen },
            { rumpCenterX - hindRootX - 1.0f, hindRootY - 3.0f },
            { rumpCenterX - hindRootX - 7.5f, hindRootY + hindLen * 0.80f },
            15.2f, 12.8f, -1.5f, 0.68f, -0.65f, 0, true
        );
        DragLimb backRightLimb = makeLimb(
            { rumpCenterX + hindRootX, hindRootY },
            { rumpCenterX + hindRootX + 2.5f, hindRootY + hindLen },
            { rumpCenterX + hindRootX + 1.0f, hindRootY - 3.0f },
            { rumpCenterX + hindRootX + 7.5f, hindRootY + hindLen * 0.80f },
            15.2f, 12.8f, 1.5f, 0.68f, 0.65f, 0, true
        );

        struct LimbGeo {
            Pt p0L, p0R, p1L, p1R, midL, midR;
            float r1;
        };
        auto buildLimbPaths = [](const DragLimb& limb, GraphicsPath& closed, GraphicsPath& rim, GraphicsPath& ink) -> LimbGeo {
            float dx = limb.tip.x - limb.root.x, dy = limb.tip.y - limb.root.y;
            float len = std::max(1.0f, std::hypot(dx, dy));
            float ux = dx / len, uy = dy / len;
            float nx = -uy, ny = ux;
            float r0 = limb.startW * 0.5f, r1 = limb.endW * 0.5f;
            Pt p0L = { limb.root.x + nx * r0, limb.root.y + ny * r0 };
            Pt p0R = { limb.root.x - nx * r0, limb.root.y - ny * r0 };
            Pt p1L = { limb.tip.x + nx * r1, limb.tip.y + ny * r1 };
            Pt p1R = { limb.tip.x - nx * r1, limb.tip.y - ny * r1 };
            Pt midL = { (p0L.x + p1L.x) * 0.5f + limb.bendX * 0.5f + nx * 1.2f, (p0L.y + p1L.y) * 0.5f + ny * 1.2f };
            Pt midR = { (p0R.x + p1R.x) * 0.5f + limb.bendX * 0.5f - nx * 1.2f, (p0R.y + p1R.y) * 0.5f - ny * 1.2f };
            PointF pawC1(p1L.x + ux * r1 * 1.25f, p1L.y + uy * r1 * 1.25f);
            PointF pawC2(p1R.x + ux * r1 * 1.25f, p1R.y + uy * r1 * 1.25f);
            auto addRim = [&](GraphicsPath& gp) {
                addQuadBezier(gp, p0L, midL, p1L);
                gp.AddBezier(PointF(p1L.x, p1L.y), pawC1, pawC2, PointF(p1R.x, p1R.y));
                addQuadBezier(gp, p1R, midR, p0R);
            };
            addRim(rim);
            addRim(closed);
            closed.AddBezier(PointF(p0R.x, p0R.y),
                             PointF(p0R.x - ux * r0 * 0.85f, p0R.y - uy * r0 * 0.85f),
                             PointF(p0L.x - ux * r0 * 0.85f, p0L.y - uy * r0 * 0.85f),
                             PointF(p0L.x, p0L.y));
            closed.CloseFigure();

            constexpr float t0 = 0.24f;
            constexpr float omt = 1.0f - t0;
            Pt s0L = { omt * omt * p0L.x + 2.0f * omt * t0 * midL.x + t0 * t0 * p1L.x,
                       omt * omt * p0L.y + 2.0f * omt * t0 * midL.y + t0 * t0 * p1L.y };
            Pt scL = { omt * midL.x + t0 * p1L.x, omt * midL.y + t0 * p1L.y };
            Pt s0R = { omt * omt * p0R.x + 2.0f * omt * t0 * midR.x + t0 * t0 * p1R.x,
                       omt * omt * p0R.y + 2.0f * omt * t0 * midR.y + t0 * t0 * p1R.y };
            Pt scR = { omt * midR.x + t0 * p1R.x, omt * midR.y + t0 * p1R.y };
            addQuadBezier(ink, s0L, scL, p1L);
            ink.AddBezier(PointF(p1L.x, p1L.y), pawC1, pawC2, PointF(p1R.x, p1R.y));
            addQuadBezier(ink, p1R, scR, s0R);
            return { p0L, p0R, p1L, p1R, midL, midR, r1 };
        };

        drawWithLayerAlpha(g, smoothstep(0.0f, 0.22f, lift), [&](Graphics& lg) {
            GraphicsState pState = lg.Save();
            float bodyPendulum = std::clamp(swingH * 0.16f, -0.17f, 0.17f);
            if (std::fabs(bodyPendulum) > 0.001f) {
                lg.TranslateTransform(scruffPinch.x, scruffPinch.y);
                lg.RotateTransform(bodyPendulum * RadToDeg);
                lg.TranslateTransform(-scruffPinch.x, -scruffPinch.y);
            }

            auto drawDragLimb = [&](const DragLimb& limb) {
                GraphicsPath fillP, rimP, inkP;
                LimbGeo geo = buildLimbPaths(limb, fillP, rimP, inkP);
                if (isDazed && limb.armDir != 0) {
                    std::vector<PointF> leftEdge, rightEdge;
                    for (int i = 0; i <= 8; ++i) {
                        float t = (float)i / 8.0f, omt = 1.0f - t;
                        leftEdge.emplace_back(
                            omt * omt * geo.p0L.x + 2.0f * omt * t * geo.midL.x + t * t * geo.p1L.x,
                            omt * omt * geo.p0L.y + 2.0f * omt * t * geo.midL.y + t * t * geo.p1L.y);
                        rightEdge.emplace_back(
                            omt * omt * geo.p0R.x + 2.0f * omt * t * geo.midR.x + t * t * geo.p1R.x,
                            omt * omt * geo.p0R.y + 2.0f * omt * t * geo.midR.y + t * t * geo.p1R.y);
                    }
                    RectF pawRect(limb.tip.x - geo.r1, limb.tip.y - geo.r1 * 0.4f, geo.r1 * 2.0f, geo.r1 * 1.8f);
                    drawDazedArm(lg, fillP, leftEdge, rightEdge, pawRect);
                    return;
                }

                if (isDazed) {
                    Color cols[2] = { Color(255, 227, 201, 159), Color(255, 200, 167, 122) };
                    REAL locs[2] = { 0.0f, 1.0f };
                    fillClampedLinearGradient(lg, &fillP, nullptr, PointF(limb.root.x, limb.root.y), PointF(limb.tip.x, limb.tip.y), cols, locs, 2);
                } else if (skin.colorpoint()) {
                    const SkinColor& midC = pal.pointsMid.set ? pal.pointsMid : pal.legs;
                    Color cols[4] = { col(pal.body), col(pal.body), col(midC), col(pal.paws) };
                    REAL locs[4] = { 0.0f, 0.20f, 0.54f, 0.88f };
                    fillClampedLinearGradient(lg, &fillP, nullptr, PointF(limb.root.x, limb.root.y), PointF(limb.tip.x, limb.tip.y), cols, locs, 4);
                } else if (!limb.isBehindBody && !pal.legs.sameAs(pal.body)) {
                    Color cols[4] = { col(pal.body), col(pal.body), col(pal.legs), col(pal.paws) };
                    REAL locs[4] = { 0.0f, 0.14f, 0.42f, 0.82f };
                    fillClampedLinearGradient(lg, &fillP, nullptr, PointF(limb.root.x, limb.root.y), PointF(limb.tip.x, limb.tip.y), cols, locs, 4);
                } else {
                    const SkinColor& legC = limb.isBehindBody && pal.hindLeg.set ? pal.hindLeg : pal.legs;
                    const SkinColor& pawC = limb.isBehindBody && pal.hindPaw.set ? pal.hindPaw : pal.paws;
                    Color cols[2] = { col(legC), col(pawC) };
                    REAL locs[2] = { 0.22f, 0.75f };
                    fillClampedLinearGradient(lg, &fillP, nullptr, PointF(limb.root.x, limb.root.y), PointF(limb.tip.x, limb.tip.y), cols, locs, 2);
                }

                SkinSpace limbSpace = (limb.armDir < 0) ? SkinSpace::LeftArm : ((limb.armDir > 0) ? SkinSpace::RightArm : SkinSpace::HindLeg);
                if (skin.hasPartArt(limbSpace)) {
                    float sign = (limb.armDir != 0) ? (float)limb.armDir : ((limb.bendX < 0.0f) ? -1.0f : 1.0f);
                    auto armMap = [&](SkinPoint p) -> PointF {
                        float t = std::clamp(p.x / 100.0f, 0.0f, 1.0f);
                        float omt = 1.0f - t;
                        float lx = omt * omt * geo.p0L.x + 2.0f * omt * t * geo.midL.x + t * t * geo.p1L.x;
                        float ly = omt * omt * geo.p0L.y + 2.0f * omt * t * geo.midL.y + t * t * geo.p1L.y;
                        float rx = omt * omt * geo.p0R.x + 2.0f * omt * t * geo.midR.x + t * t * geo.p1R.x;
                        float ry = omt * omt * geo.p0R.y + 2.0f * omt * t * geo.midR.y + t * t * geo.p1R.y;
                        float cx = (lx + rx) * 0.5f, cy = (ly + ry) * 0.5f;
                        float hx = (rx - lx) * 0.5f, hy = (ry - ly) * 0.5f;
                        float u = sign * (p.y / 10.0f);
                        return PointF(cx + hx * u, cy + hy * u);
                    };
                    GraphicsState as = lg.Save();
                    lg.SetClip(&fillP, CombineModeIntersect);
                    for (const SkinRegion& region : skin.regions) if (region.space == limbSpace) drawRegion(lg, region, armMap);
                    for (const SkinMark& mark : skin.marks) if (mark.space == limbSpace) drawMark(lg, mark, armMap);
                    lg.Restore(as);
                }

                Pen limbPen(limbInk, isBlackRim ? 1.15f : 1.2f);
                setRound(limbPen);
                lg.DrawPath(&limbPen, &inkP);

                float dx = limb.tip.x - limb.root.x, dy = limb.tip.y - limb.root.y;
                float len = std::max(1.0f, std::hypot(dx, dy));
                float ux = dx / len, uy = dy / len;
                float nx = -uy, ny = ux;
                for (float side : { -1.0f, 1.0f }) {
                    float ax = limb.tip.x + nx * side * 2.5f + ux * 1.6f;
                    float ay = limb.tip.y + ny * side * 2.5f + uy * 1.6f;
                    float bx = limb.tip.x + nx * side * 2.5f + ux * (limb.endW * 0.44f);
                    float by = limb.tip.y + ny * side * 2.5f + uy * (limb.endW * 0.44f);
                    lg.DrawLine(&limbPen, ax, ay, bx, by);
                }
            };

            // Pass 0 (ALL skins): unified sticker-style outer white silhouette rim painted FIRST
            const DragLimb* limbs[4] = { &backLeftLimb, &backRightLimb, &frontLeftLimb, &frontRightLimb };
            if (whiteOutlineEnabled()) {
                float whiteRimW = BlackOutlineW * 2.0f + (pal.outline.set ? 2.0f : 0.0f);
                Pen tailRimPen(blackOutline(), tailW + whiteRimW);
                setRound(tailRimPen);
                lg.DrawPath(&tailRimPen, &tailCurvePath);

                Pen rimPen(blackOutline(), whiteRimW);
                setRound(rimPen);
                for (const DragLimb* l : limbs) {
                    GraphicsPath fp, rp, ip;
                    buildLimbPaths(*l, fp, rp, ip);
                    lg.DrawPath(&rimPen, &rp);
                }
                drawEarsLayer(lg, headCenter, physics, skin, true);
                lg.DrawPath(&rimPen, &longCatPath);
            }

            if (pal.outline.set && !isDazed) {
                Pen tailOutPen(col(pal.outline), tailW + 2.4f);
                setRound(tailOutPen);
                lg.DrawPath(&tailOutPen, &tailCurvePath);
                Pen outPen(col(pal.outline), 2.4f);
                setRound(outPen);
                for (const DragLimb* l : limbs) {
                    GraphicsPath fp, rp, ip;
                    buildLimbPaths(*l, fp, rp, ip);
                    lg.DrawPath(&outPen, &rp);
                }
                lg.DrawPath(&outPen, &longCatPath);
            }

            // 1. Limp drooping tail behind lower body
            {
                Pen tailPen(isDazed ? Color(255, 40, 49, 87) : col(pal.tail), tailW);
                setRound(tailPen);
                if (isTabby(skin) && !isDazed) {
                    tabby::drawTail(lg, tailPen, PointF(tailRoot.x, tailRoot.y), PointF(tailC1.x, tailC1.y), PointF(tailC2.x, tailC2.y), PointF(tailTip.x, tailTip.y));
                } else {
                    lg.DrawPath(&tailPen, &tailCurvePath);
                    if (pal.stripes.set && !isBlackRim && !skin.colorpoint() && !isDazed) {
                        auto evalTailPt = [&](float t) -> PointF {
                            float u = 1.0f - t;
                            return PointF(
                                u*u*u*tailRoot.x + 3*u*u*t*tailC1.x + 3*u*t*t*tailC2.x + t*t*t*tailTip.x,
                                u*u*u*tailRoot.y + 3*u*u*t*tailC1.y + 3*u*t*t*tailC2.y + t*t*t*tailTip.y
                            );
                        };
                        Pen ringPen(withAlpha(pal.stripes, 107), tailW * 0.88f);
                        ringPen.SetStartCap(LineCapFlat); ringPen.SetEndCap(LineCapFlat);
                        for (float t0 : { 0.24f, 0.50f, 0.74f }) {
                            lg.DrawLine(&ringPen, evalTailPt(t0), evalTailPt(t0 + 0.09f));
                        }
                    }
                    if (!isDazed && pal.tailTip.set) {
                        Pen tipPen(col(pal.tailTip), tailW * 0.92f);
                        setRound(tipPen);
                        Pt tStart = lerpPt(tailC2, tailTip, 0.35f);
                        lg.DrawLine(&tipPen, tStart.x, tStart.y, tailTip.x, tailTip.y);
                    }
                    if (!isBlackRim && !pal.outline.set) {
                        GraphicsPath strokedTail;
                        strokedTail.AddBezier(PointF(tailRoot.x, tailRoot.y), PointF(tailC1.x, tailC1.y), PointF(tailC2.x, tailC2.y), PointF(tailTip.x, tailTip.y));
                        strokedTail.Widen(&tailPen);
                        Pen subtlePen(Color(41, 0, 0, 0), 1.0f);
                        setRound(subtlePen);
                        lg.DrawPath(&subtlePen, &strokedTail);
                    }
                }
            }

            // 2. Dangling hind legs emerging from lower belly hem
            drawDragLimb(backLeftLimb);
            drawDragLimb(backRightLimb);

            // 3. Native 3D Ears tucked cleanly behind the head crown
            drawEarsLayer(lg, headCenter, physics, skin);

            // 4. Unified Front-Facing Long-Cat Head + Subtle Scruff Pinch + Stretched Torso
            auto headMap = [&](SkinPoint p) { return headPoint(p, false, skin, headCenter, physics, false); };
            auto headWhiteMap = [&](SkinPoint p) { return headPoint(p, false, skin, headCenter, physics, true); };
            auto skullMap = [&](SkinPoint p) { return headPoint(p, true, skin, headCenter, physics, false); };

            if (isDazed) {
                Color bellyCols[2] = { Color(255, 244, 223, 184), Color(255, 200, 167, 122) };
                REAL bLocs[2] = { 0.0f, 1.0f };
                fillClampedLinearGradient(lg, &longCatPath, nullptr, PointF(headCenter.x, headCenter.y + 30.0f), PointF(rumpCenterX, torsoBottomY + bottomDip), bellyCols, bLocs, 2);

                GraphicsState ds = lg.Save();
                lg.SetClip(&longCatPath, CombineModeIntersect);
                float tunicBotY = headCenter.y + torsoLen * 0.74f;
                GraphicsPath tunic;
                tunic.AddLine(PointF(headCenter.x - cheekHalfW * 1.4f, headCenter.y), PointF(headCenter.x + cheekHalfW * 1.4f, headCenter.y));
                tunic.AddLine(PointF(headCenter.x + cheekHalfW * 1.4f, headCenter.y), PointF(rumpCenterX + hipHalfW * 1.2f, tunicBotY));
                tunic.AddBezier(PointF(rumpCenterX + hipHalfW * 1.2f, tunicBotY), PointF(rumpCenterX + hipHalfW * 0.5f, tunicBotY + 14.0f), PointF(rumpCenterX - hipHalfW * 0.5f, tunicBotY + 14.0f), PointF(rumpCenterX - hipHalfW * 1.2f, tunicBotY));
                tunic.CloseFigure();
                Color clothCols[2] = { Color(255, 85, 95, 155), Color(255, 37, 46, 88) };
                REAL cLocs[2] = { 0.0f, 1.0f };
                fillClampedLinearGradient(lg, &tunic, nullptr, PointF(headCenter.x - 16.0f, headCenter.y + 20.0f), PointF(rumpCenterX + 12.0f, tunicBotY + 10.0f), clothCols, cLocs, 2);

                Pen hemPen(Color(166, 124, 134, 188), 1.3f);
                setRound(hemPen);
                lg.DrawBezier(&hemPen, PointF(rumpCenterX - hipHalfW, tunicBotY - 1.0f), PointF(rumpCenterX - hipHalfW * 0.45f, tunicBotY + 11.0f), PointF(rumpCenterX + hipHalfW * 0.45f, tunicBotY + 11.0f), PointF(rumpCenterX + hipHalfW, tunicBotY - 1.0f));
                lg.Restore(ds);

                GraphicsState hsSave = lg.Save();
                lg.TranslateTransform(headCenter.x, headCenter.y);
                lg.RotateTransform(physics.headTilt.value * RadToDeg);
                GraphicsPath hood;
                PointF hTop(0.0f, -33.0f - scruffTuftH);
                PointF hR(48.0f, 9.0f), hBot(0.0f, 41.0f), hL(-48.0f, 9.0f);
                hood.AddBezier(hTop, PointF(28.0f, -35.0f), PointF(48.0f, -16.0f), hR);
                hood.AddBezier(hR, PointF(48.0f, 32.0f), PointF(25.0f, 41.0f), hBot);
                hood.AddBezier(hBot, PointF(-25.0f, 41.0f), PointF(-48.0f, 32.0f), hL);
                hood.AddBezier(hL, PointF(-48.0f, -16.0f), PointF(-28.0f, -35.0f), hTop);
                hood.CloseFigure();
                Color hoodCols[2] = { Color(255, 104, 113, 180), Color(255, 47, 56, 109) };
                REAL hLocs[2] = { 0.0f, 1.0f };
                fillClampedLinearGradient(lg, &hood, nullptr, PointF(-16.0f, -38.0f), PointF(15.0f, 42.0f), hoodCols, hLocs, 2);
                lg.Restore(hsSave);
            } else {
                if (isTabby(skin)) {
                    auto tabbyFace = [&](float x, float y) -> PointF {
                        float depth = std::clamp(29.0f - 0.012f * x * x - 0.22f * std::fabs(y + 2.0f), 3.0f, 28.0f);
                        Pt projected = projectHead3D(x, y, depth, physics.headYaw.value * 0.50f, physics.headPitch.value * 0.36f);
                        float cH = std::cos(physics.headTilt.value), sH = std::sin(physics.headTilt.value);
                        float px = projected.x * hs, py = projected.y * hs;
                        return PointF(headCenter.x + px * cH - py * sH, headCenter.y + px * sH + py * cH);
                    };
                    auto tabbyBack = [&](float x, float y) -> PointF {
                        return dragBodyMap(SkinPoint{ x, y - 44.0f });
                    };
                    tabby::drawBody(lg, longCatPath, tabbyFace, tabbyBack, physics);
                } else {
                    SolidBrush hb(col(pal.body));
                    lg.FillPath(&hb, &longCatPath);
                    GraphicsState bcs = lg.Save();
                    lg.SetClip(&longCatPath, CombineModeIntersect);

                    if (pal.bodyShade.set) {
                        Color cols[2] = { col(pal.body), col(pal.bodyShade) };
                        REAL locs[2] = { 0.15f, 1.0f };
                        fillClampedLinearGradient(lg, &longCatPath, nullptr, PointF(headCenter.x, headCenter.y - 36.0f), PointF(rumpCenterX, torsoBottomY + bottomDip), cols, locs, 2);
                    }

                    for (const SkinRegion& region : skin.regions) {
                        if (region.space != SkinSpace::Head && region.space != SkinSpace::Skull && region.space != SkinSpace::Body) continue;
                        GraphicsState rs = lg.Save();
                        GraphicsPath side;
                        jawSide(side, region.space != SkinSpace::Body, skin, headCenter, physics);
                        lg.SetClip(&side, CombineModeIntersect);
                        if (region.space == SkinSpace::Body) drawRegion(lg, region, dragBodyMap);
                        else if (region.space == SkinSpace::Skull) drawRegion(lg, region, skullMap);
                        else drawRegion(lg, region, headMap);
                        lg.Restore(rs);
                    }

                    if (pal.points.set) {
                        const SkinColor& point = pal.points;
                        const SkinColor& mid = pal.pointsMid.set ? pal.pointsMid : pal.points;
                        GraphicsState ms = lg.Save();
                        lg.TranslateTransform(headCenter.x, headCenter.y + 3.0f);
                        lg.ScaleTransform(1.22f * hs, 0.88f * hs);
                        GraphicsPath maskEllipse;
                        maskEllipse.AddEllipse(-31.0f, -31.0f, 62.0f, 62.0f);
                        PathGradientBrush maskBrush(&maskEllipse);
                        Color mCols[4] = { withAlpha(mid, 0), withAlpha(mid, 158), withAlpha(point, 235), withAlpha(point, 255) };
                        REAL mPos[4] = { 0.0f, 0.26f, 0.58f, 1.0f };
                        maskBrush.SetInterpolationColors(mCols, mPos, 4);
                        lg.FillPath(&maskBrush, &maskEllipse);
                        lg.Restore(ms);
                    }

                    for (const SkinMark& mark : skin.marks) {
                        if (mark.space == SkinSpace::Body) drawMark(lg, mark, dragBodyMap);
                    }
                    for (const SkinMark& mark : skin.marks) {
                        if (mark.space == SkinSpace::Skull) drawMark(lg, mark, skullMap);
                        else if (mark.space == SkinSpace::Head) {
                            if (isMilkMark(mark)) drawMark(lg, mark, headWhiteMap);
                            else drawMark(lg, mark, headMap);
                        }
                    }
                    lg.Restore(bcs);
                }

                if (!isBlackRim) {
                    Pen bp(pal.outline.set ? col(pal.outline) : Color(56, 46, 38, 31), pal.outline.set ? 1.5f : 1.05f);
                    setRound(bp);
                    lg.DrawPath(&bp, &longCatPath);
                }

                // Subtle soft chin shadow curve
                Pen chinPen(isBlackRim
                    ? Color(41, 255, 255, 255)
                    : (pal.outline.set ? withAlpha(pal.outline, 115) : Color(41, 46, 38, 31)),
                    isBlackRim ? 1.05f : 1.0f);
                setRound(chinPen);
                GraphicsPath chinArc;
                addQuadBezier(chinArc,
                              { headCenter.x - cheekHalfW * 0.56f, headCenter.y + chinY - 2.5f * hs },
                              { headCenter.x, headCenter.y + chinY + 3.5f * hs },
                              { headCenter.x + cheekHalfW * 0.56f, headCenter.y + chinY - 2.5f * hs });
                lg.DrawPath(&chinPen, &chinArc);
            }

            // 5. Native KuroCat Face Features (normal authentic almond eyes — no round bug-eyes!)
            drawHeadFeatures(lg, headCenter, physics, eyeTheme, skin, 0.0f, 0.0f);

            // 6. Dangling front arms hanging along the outer shoulder slopes (leaving central chest/belly 100% unobstructed!)
            drawDragLimb(frontLeftLimb);
            drawDragLimb(frontRightLimb);

            // 7. Skin stickers / decorations stay anchored cleanly to the lifted cat's head, neck, and whipping tail tip!
            if (!skin.decorations.empty()) {
                Pt dragNeck = { headCenter.x + hipLagX * 0.08f, headCenter.y + 36.0f * hs };
                drawDecorations(lg, rumpCenterX, torsoBottomY, headCenter, physics, skin, &dragNeck, &tailTip);
            }
            lg.Restore(pState);
        });
    }
};
