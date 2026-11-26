#pragma once
#include "CatPhysics.hpp"
#include <objidl.h>
#include <gdiplus.h>
#include <initializer_list>
#include <utility>

// Paint materials only. CatRenderer supplies the same paths, caps and silhouettes
// as the black coat. Coordinates in the coat design are in the native 360x320 canvas.
namespace tabby {
using namespace Gdiplus;
inline Color dark() {
    return Color(64, 54, 43);
}
inline Color brown() {
    return Color(103, 86, 66);
}
inline Color oat() {
    return Color(202, 180, 149);
}
inline Color milk() {
    return Color(239, 231, 213);
}
inline Color line(BYTE alpha) {
    return Color(alpha, 104, 85, 65);
}

template <class Paint, class Apply> void material(RectF box, Color base, Paint paint, Apply apply) {
    constexpr float density = 2.f;
    float x = std::floor(box.X) - 2, y = std::floor(box.Y) - 2;
    int w = int(std::ceil((box.GetRight() - x + 2) * density)),
        h = int(std::ceil((box.GetBottom() - y + 2) * density));
    Bitmap bitmap(w, h, PixelFormat32bppPARGB);
    {
        Graphics ink(&bitmap);
        ink.Clear(base);
        ink.SetSmoothingMode(SmoothingModeAntiAlias);
        ink.SetPixelOffsetMode(PixelOffsetModeHighQuality);
        Matrix worldToPaint(density, 0, 0, density, -x * density, -y * density);
        ink.SetTransform(&worldToPaint);
        paint(ink);
    }
    TextureBrush fur(&bitmap, WrapModeClamp);
    Matrix paintToWorld(1.f / density, 0, 0, 1.f / density, x, y);
    fur.SetTransform(&paintToWorld);
    apply(fur);
}

struct Cubic {
    float ax, ay, bx, by, x, y;
};

template <class Map>
void markPath(GraphicsPath &spot, Map map, PointF origin, std::initializer_list<Cubic> segments) {
    PointF start = map(origin.X, origin.Y);
    for (const auto &s : segments) {
        PointF end = map(s.x, s.y);
        spot.AddBezier(start, map(s.ax, s.ay), map(s.bx, s.by), end);
        start = end;
    }
    spot.CloseFigure();
}

template <class Map, class Fill>
void shape(Graphics &g, Map map, Fill &paint, PointF origin, std::initializer_list<Cubic> segments) {
    GraphicsPath spot;
    markPath(spot, map, origin, segments);
    g.FillPath(&paint, &spot);
}

template <class Map>
void softShape(Graphics &g, Map map, Color color, PointF center, float feather, PointF origin,
               std::initializer_list<Cubic> segments) {
    GraphicsPath spot;
    markPath(spot, map, origin, segments);
    PathGradientBrush wash(&spot);
    wash.SetCenterPoint(map(center.X, center.Y));
    Color clear(0, color.GetR(), color.GetG(), color.GetB());
    Color half(130, color.GetR(), color.GetG(), color.GetB());
    Color stops[] = {clear, half, color, color};
    REAL pos[] = {0.f, feather * .48f, feather, 1.f};
    wash.SetInterpolationColors(stops, pos, 4);
    g.FillPath(&wash, &spot);
}

inline float smooth(float t) {
    t = std::clamp(t, 0.f, 1.f);
    return t * t * (3.f - 2.f * t);
}

template <class Face, class Body>
void drawBody(Graphics &target, GraphicsPath &silhouette, Face face, Body body, const CatPhysics &physics) {
    RectF bounds;
    silhouette.GetBounds(&bounds);
    material(
        bounds, oat(),
        [&](Graphics &ink) {
            auto map = [&](float x, float y) {
                // Blend coordinates through the throat so the muzzle and bib share a continuous field.
                float t = smooth((y - 12.f) / 45.f);
                PointF h = face(x, y), b = body(x, y - 100.f);
                return PointF(h.X + (b.X - h.X) * t, h.Y + (b.Y - h.Y) * t);
            };
            LinearGradientBrush ground(PointF(bounds.X - 3, bounds.Y), PointF(bounds.GetRight() + 3, bounds.Y),
                                       brown(), oat());
            Color colors[] = {Color(131, 115, 96), Color(169, 148, 121), Color(201, 176, 143),
                              Color(183, 160, 129), Color(143, 124, 103)};
            REAL stops[] = {0.f, .20f, .48f, .73f, 1.f};
            ground.SetInterpolationColors(colors, stops, 5);
            ink.FillRectangle(&ground, bounds.X - 2, bounds.Y - 2, bounds.Width + 4, bounds.Height + 4);

            SolidBrush stripe(dark()), secondary(Color(117, 99, 78)), lighter(Color(213, 191, 157));
            // The stripes enter from the flanks. Their forked tips fall short of the white bib.
            for (float sign : {-1.f, 1.f}) {
                auto flank = [&](float x, float y) { return map(sign * x, y + (sign < 0 ? 1.8f : 0.f)); };
                shape(ink, flank, secondary, {53, 22},
                      {{42, 26, 36, 31, 27, 34}, {35, 34, 42, 32, 51, 29}, {55, 27, 56, 24, 53, 22}});
                shape(ink, flank, stripe, {56, 31},
                      {{44, 30, 35, 42, 22, 43},
                       {27, 45, 34, 44, 38, 42},
                       {35, 46, 32, 47, 29, 49},
                       {40, 48, 46, 42, 56, 39},
                       {58, 36, 58, 34, 56, 31}});
                shape(ink, flank, stripe, {56, 49},
                      {{44, 47, 35, 60, 19, 60},
                       {27, 63, 35, 61, 41, 58},
                       {46, 56, 50, 57, 55, 55},
                       {57, 53, 57, 51, 56, 49}});
                shape(ink, flank, secondary, {54, 62},
                      {{43, 62, 37, 72, 27, 74}, {37, 74, 44, 71, 53, 67}, {54, 66, 54, 63, 54, 62}});
                shape(ink, flank, stripe, {55, 72},
                      {{44, 70, 37, 84, 23, 86},
                       {32, 87, 38, 85, 40, 83},
                       {39, 85, 37, 87, 35, 89},
                       {45, 86, 50, 82, 55, 81},
                       {56, 77, 56, 74, 55, 72}});
                shape(ink, flank, secondary, {53, 90},
                      {{46, 88, 39, 98, 30, 100}, {37, 100, 45, 97, 52, 96}, {53, 93, 53, 92, 53, 90}});
            }

            // Feather-shaped patches overlap vertically without outlining the jaw.
            softShape(ink, map, Color(230, 211, 183), {0, 47}, .42f, {-25, 6},
                      {{-19, 6, -11, 11, -6, 12},
                       {-2, 13, 1, 13, 8, 11},
                       {14, 9, 19, 7, 24, 6},
                       {25, 18, 21, 25, 20, 37},
                       {22, 48, 21, 54, 17, 63},
                       {17, 76, 12, 91, 3, 106},
                       {-4, 106, -12, 94, -15, 78},
                       {-19, 68, -22, 55, -21, 45},
                       {-18, 30, -26, 22, -25, 6}});
            softShape(ink, map, Color(243, 234, 215), {0, 47}, .40f, {-22, 8},
                      {{-18, 8, -11, 9, -7, 13},
                       {-4, 15, 0, 15, 4, 13},
                       {10, 9, 16, 8, 22, 8},
                       {22, 15, 18, 19, 16, 24},
                       {17, 24, 18, 23, 19, 23},
                       {19, 28, 16, 33, 17, 38},
                       {17, 43, 19, 48, 18, 53},
                       {16, 51, 16, 50, 15, 50},
                       {17, 63, 12, 70, 12, 76},
                       {11, 74, 10, 73, 10, 73},
                       {12, 84, 6, 94, 2, 99},
                       {-3, 91, -7, 86, -7, 78},
                       {-9, 82, -10, 82, -10, 82},
                       {-13, 76, -13, 67, -15, 61},
                       {-16, 63, -17, 64, -17, 64},
                       {-20, 54, -16, 45, -17, 38},
                       {-16, 31, -20, 26, -21, 23},
                       {-19, 23, -18, 24, -17, 24},
                       {-20, 20, -23, 14, -22, 8}});

            // Forehead markings split around the lighter nose bridge. Each cheek sweeps backwards
            // from the outer eye and tapers; the two sides never join under the chin.
            for (float sign : {-1.f, 1.f}) {
                auto f = [&](float x, float y) { return face(sign * x, y + (sign < 0 ? -.55f : 0.f)); };
                shape(ink, f, lighter, {1, -26},
                      {{4, -22, 6, -18, 6, -12},
                       {8, -16, 9, -23, 11, -27},
                       {9, -31, 6, -32, 4, -32},
                       {3, -30, 2, -28, 1, -26}});
                shape(ink, f, stripe, {11, -35},
                      {{11, -30, 8, -27, 6, -24},
                       {4, -21, 4, -17, 3, -14},
                       {1, -16, 1, -21, 2, -24},
                       {4, -27, 6, -27, 7, -31},
                       {8, -33, 8, -34, 8, -36},
                       {9, -36, 10, -36, 11, -35}});
                shape(ink, f, secondary, {1, -34},
                      {{4, -31, 4, -28, 3, -25},
                       {2, -23, 1, -22, 1, -20},
                       {0, -23, 0, -27, 0, -29},
                       {0, -31, 0, -33, 1, -34}});
                shape(ink, f, secondary, {18, -34},
                      {{16, -27, 11, -22, 9, -15},
                       {14, -18, 17, -23, 21, -27},
                       {24, -29, 26, -29, 27, -31},
                       {25, -33, 21, -34, 18, -34}});
                shape(ink, f, stripe, {44, -14},
                      {{36, -14, 32, -9, 27, -7},
                       {31, -5, 35, -7, 38, -9},
                       {40, -10, 42, -10, 45, -10},
                       {45, -12, 45, -13, 44, -14}});
                shape(ink, f, stripe, {47, 0},
                      {{40, -1, 37, 5, 31, 7},
                       {28, 9, 26, 9, 24, 9},
                       {27, 12, 32, 11, 35, 9},
                       {34, 11, 32, 13, 30, 14},
                       {36, 13, 40, 7, 46, 7},
                       {48, 4, 48, 2, 47, 0}});
                shape(ink, f, secondary, {45, 12},
                      {{38, 12, 34, 20, 25, 20}, {32, 23, 37, 19, 44, 17}, {46, 15, 46, 13, 45, 12}});
                softShape(
                    ink, f, Color(246, 236, 214), {10, 12}, .65f, {3, 9},
                    {{8, 6, 14, 7, 18, 7}, {21, 8, 23, 11, 21, 14}, {18, 18, 9, 20, 4, 18}, {2, 15, 2, 12, 3, 9}});
                SolidBrush ticking(Color(88, 119, 99, 77));
                for (Pt dot : {Pt{11.8f, 12.5f}, Pt{15.2f, 13.f}, Pt{13.7f, 15.2f}}) {
                    PointF at = f(dot.x, dot.y);
                    ink.FillEllipse(&ticking, at.X - .55f, at.Y - .4f, 1.1f, .8f);
                }
                shape(ink, f, lighter, {11, -13},
                      {{14, -17, 20, -19, 25, -17}, {21, -17, 16, -15, 13, -12}, {12, -12, 12, -12, 11, -13}});
            }

            // The black skin's resting front legs are contour lines on this silhouette. Put the
            // idle sock color inside this same fill so it cannot expand the cat's alpha mask.
            for (float sign : {-1.f, 1.f}) {
                bool left = sign < 0;
                Pt paw = left ? physics.leftPaw.point() : physics.rightPaw.point();
                Pt rest = left ? CatPhysics::LeftPawRest : CatPhysics::RightPawRest;
                if (std::hypot(paw.x - rest.x, paw.y - rest.y) >= 6.f ||
                    (left ? (physics.leftPawTyping || physics.leftPawOnMouse) : physics.rightPawTyping))
                    continue;
                auto leg = [&](float x, float y) {
                    return PointF(CatPhysics::SeatAnchor.x + physics.bodyShiftX.value + sign * (16.f + x),
                                  CatPhysics::SeatAnchor.y + y);
                };
                SolidBrush toe(milk()), band(brown());
                shape(ink, leg, band, {-6, -24},
                      {{-2, -23, 2, -21, 8, -22},
                       {7, -19, 4, -18, 0, -19},
                       {-2, -21, -4, -21, -6, -21},
                       {-6, -22, -6, -23, -6, -24}});
                shape(ink, leg, band, {-7, -11},
                      {{-3, -12, 3, -7, 8, -10},
                       {6, -5, 1, -6, -2, -7},
                       {-4, -9, -5, -9, -7, -9},
                       {-7, -10, -7, -11, -7, -11}});
                shape(ink, leg, toe, {-6, 4},
                      {{-3, 4, -3, 2, 0, 3},
                       {4, 4, 5, 2, 7, 3},
                       {8, 7, 8, 11, 6, 13},
                       {2, 15, -3, 14, -6, 12},
                       {-7, 9, -7, 6, -6, 4}});
            }
        },
        [&](TextureBrush &fur) { target.FillPath(&fur, &silhouette); });
}

inline void drawTail(Graphics &g, Pen &pen, PointF a, PointF b, PointF c, PointF d) {
    const auto x = std::minmax({a.X, b.X, c.X, d.X});
    const auto y = std::minmax({a.Y, b.Y, c.Y, d.Y});
    RectF box(x.first - 10, y.first - 10, x.second - x.first + 20, y.second - y.first + 20);
    material(
        box, Color(163, 143, 117),
        [&](Graphics &ink) {
            auto onTail = [&](float t, float across) {
                float h = 1 - t;
                float x = h * h * h * a.X + 3 * h * h * t * b.X + 3 * h * t * t * c.X + t * t * t * d.X;
                float y = h * h * h * a.Y + 3 * h * h * t * b.Y + 3 * h * t * t * c.Y + t * t * t * d.Y;
                float dx = h * h * (b.X - a.X) + 2 * h * t * (c.X - b.X) + t * t * (d.X - c.X);
                float dy = h * h * (b.Y - a.Y) + 2 * h * t * (c.Y - b.Y) + t * t * (d.Y - c.Y);
                float len = std::max(.01f, std::hypot(dx, dy));
                return PointF(x - dy * across / len, y + dx * across / len);
            };
            SolidBrush inkBand(dark());
            for (auto range : {std::pair<float, float>{.18f, .25f}, {.40f, .48f}, {.61f, .71f}, {.84f, 1.25f}}) {
                auto m = [&](float t, float across) {
                    return onTail(range.first + (range.second - range.first) * t, across);
                };
                shape(ink, m, inkBand, {0, -11},
                      {{.3f, -5, -.12f, 3, 0, 11},
                       {.4f, 11, .7f, 11, 1, 11},
                       {.85f, 4, 1.25f, -4, 1, -11},
                       {.65f, -11, .4f, -11, 0, -11}});
            }
        },
        [&](TextureBrush &fur) {
            pen.SetBrush(&fur);
            g.DrawBezier(&pen, a, b, c, d);
        });
}

// Use the native quadratic limb centerline for the direction and width of each band.
inline void drawLimb(Graphics &g, GraphicsPath &path, RectF paw, Pt a, Pt b, Pt c, float startW, float endW) {
    RectF bounds;
    path.GetBounds(&bounds);
    material(
        bounds, Color(174, 152, 123),
        [&](Graphics &ink) {
            auto map = [&](float side, float t) {
                float h = 1 - t;
                float x = h * h * a.x + 2 * h * t * b.x + t * t * c.x,
                      y = h * h * a.y + 2 * h * t * b.y + t * t * c.y;
                float dx = h * (b.x - a.x) + t * (c.x - b.x), dy = h * (b.y - a.y) + t * (c.y - b.y);
                float r = side * (startW * h + endW * t) / std::max(.01f, std::hypot(dx, dy));
                return PointF(x - dy * r, y + dx * r);
            };
            SolidBrush band(brown()), darkBand(dark()), toe(milk());
            auto ring = [&](float y, float thickness, SolidBrush &brush) {
                auto local = [&](float x, float v) { return map(x, y + v * thickness); };
                shape(ink, local, brush, {-.6f, 0},
                      {{-.1f, -.1f, .23f, .65f, .65f, .12f},
                       {.66f, .6f, .61f, .83f, .59f, 1.15f},
                       {.26f, 1.6f, -.2f, .58f, -.61f, .9f},
                       {-.66f, .6f, -.66f, .2f, -.6f, 0}});
            };
            ring(.26f, .09f, band);
            ring(.48f, .1f, darkBand);
            ring(.69f, .075f, band);
            shape(ink, map, toe, {-.8f, .88f},
                  {{-.3f, .9f, .1f, .84f, .8f, .89f},
                   {.85f, 1.1f, .8f, 1.2f, .8f, 1.3f},
                   {0, 1.3f, -.5f, 1.3f, -.8f, 1.3f},
                   {-.8f, 1.2f, -.8f, 1.05f, -.8f, .88f}});
        },
        [&](TextureBrush &fur) { g.FillPath(&fur, &path); });
    SolidBrush toes(milk());
    g.FillEllipse(&toes, paw);
}
} // namespace tabby
