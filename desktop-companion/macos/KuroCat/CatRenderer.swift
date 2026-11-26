import Foundation
import CoreGraphics
import AppKit

enum CatHitZone {
    case none
    case head
    case body
    case permissionPill
}

enum CatRenderer {
    static let catBlack = NSColor(calibratedRed: 0.085, green: 0.085, blue: 0.095, alpha: 1.0)
    private static let blackOutlineWidth: CGFloat = 1.8
    private static let blackOutlineColor = NSColor(calibratedWhite: 1.0, alpha: 0.96)

    private static func rgb(_ hex: Int, _ alpha: CGFloat = 1) -> NSColor {
        NSColor(calibratedRed: CGFloat((hex >> 16) & 255) / 255,
                green: CGFloat((hex >> 8) & 255) / 255,
                blue: CGFloat(hex & 255) / 255, alpha: alpha)
    }

    private static func isClassicBlackRim(_ skin: SkinSpec) -> Bool {
        skin.id == "builtin:0" || (!skin.colorpoint && skin.palette.outline == nil && !skin.idleLegsTinted && skin.marks.isEmpty && skin.regions.isEmpty && skin.palette.body.luminance < 0.12)
    }

    private static func usesPatternedMuzzle(_ skin: SkinSpec) -> Bool {
        skin.palette.nose == nil && skin.palette.mouth == nil && skin.palette.belly != nil && !skin.marks.isEmpty && !skin.idleLegsTinted
    }

    private static func isMilkMark(_ mark: SkinMark) -> Bool {
        abs(mark.color.r - 242.0 / 255.0) < 0.01 && abs(mark.color.g - 238.0 / 255.0) < 0.01 && abs(mark.color.b - 228.0 / 255.0) < 0.01
    }

    static let permissionPillRect = CGRect(x: 92, y: 294, width: 176, height: 22)
    static let editRotateHandle = CGPoint(x: 180, y: 12)
    static let editCorners: [CGPoint] = [
        CGPoint(x: 10, y: 26),   // 0: top-left
        CGPoint(x: 350, y: 26),  // 1: top-right
        CGPoint(x: 10, y: 310),  // 2: bottom-left
        CGPoint(x: 350, y: 310)  // 3: bottom-right
    ]

    /// Maps a point in unflipped, unrotated 360x320 canvas coordinates into cat-local coordinates.
    static func canvasPointToCatSpace(_ p: CGPoint, flipped: Bool, rotationDeg: CGFloat) -> CGPoint {
        var x = p.x
        var y = p.y
        if abs(rotationDeg) > 0.05 {
            let rad = rotationDeg * .pi / 180.0
            let fitScale = 1.0 - abs(sin(rad)) * 0.14
            let dx = x - 180.0
            let dy = y - 160.0
            let c = cos(-rad), s = sin(-rad)
            x = 180.0 + (dx * c - dy * s) / fitScale
            y = 160.0 + (dx * s + dy * c) / fitScale
        }
        if flipped {
            x = CatPhysics.canvasSize.width - x
        }
        return CGPoint(x: x, y: y)
    }

    /// Edit-mode hit test in unflipped 360x320 canvas coordinates:
    /// 0..3 = corner resize handles, 20 = top rotation/direction handle, 12 = inside edit box, -1 = outside.
    static func hitTestEditOverlay(point p: CGPoint) -> Int {
        if hypot(p.x - editRotateHandle.x, p.y - editRotateHandle.y) <= 14.0 { return 20 }
        for (idx, c) in editCorners.enumerated() {
            if hypot(p.x - c.x, p.y - c.y) <= 18.0 { return idx }
        }
        if CGRect(x: 6, y: 22, width: 348, height: 292).contains(p) { return 12 }
        return -1
    }

    /// Base skeleton per SkinBuild; SkinShape multipliers are applied on top (all exact no-ops at 1).
    private struct Build {
        let headLift: CGFloat
        let cheekHalfW, crownCtrlW, crownBaseY, cheekY, cheekCtrlTopY, neckPinchX, neckCtrlY: CGFloat
        let hipHalfW, waistCtrlW, waistCtrlY, botOuterW, botInnerW, botHalfW: CGFloat
        let earFold, earLen, earInX, earInY, earOutX, earOutY, earTipX, earTipY, earTipSpread: CGFloat
        let tailWidth: CGFloat
        let hindLeftX, hindW, hindRightX, hindLeftY, hindLeftH, hindStaggerY, hindStaggerH: CGFloat
        let idleTopDY, idleTopX, idleBotX, shoulderX, limbStartW, limbEndW: CGFloat
        let sleekEyes: Bool
    }
    private static let standardBuild = Build(
        headLift: 0,
        cheekHalfW: 42.5, crownCtrlW: 26.0, crownBaseY: -30.0, cheekY: 5.0, cheekCtrlTopY: -14.0, neckPinchX: 2.5, neckCtrlY: 24.0,
        hipHalfW: 49.0, waistCtrlW: 51.5, waistCtrlY: -48.0, botOuterW: 47.0, botInnerW: 36.0, botHalfW: 24.0,
        earFold: 0.06, earLen: 32.0, earInX: 9.0, earInY: -16.0, earOutX: 35.0, earOutY: -5.0, earTipX: 24.5, earTipY: -20.0, earTipSpread: 3.8,
        tailWidth: 11.0,
        hindLeftX: -35.0, hindW: 17.0, hindRightX: 18.0, hindLeftY: 3.0, hindLeftH: 11.0, hindStaggerY: 4.5, hindStaggerH: 12.5,
        idleTopDY: 30, idleTopX: 18.0, idleBotX: 16.0, shoulderX: 20.0, limbStartW: 19.0, limbEndW: 13.5,
        sleekEyes: false)
    private static let sleekBuild = Build(
        headLift: -3.0,
        cheekHalfW: 42.5, crownCtrlW: 25.0, crownBaseY: -29.5, cheekY: 6.5, cheekCtrlTopY: -13.0, neckPinchX: 6.5, neckCtrlY: 27.5,
        hipHalfW: 44.5, waistCtrlW: 41.0, waistCtrlY: -50.0, botOuterW: 42.0, botInnerW: 32.0, botHalfW: 22.0,
        earFold: 0.14, earLen: 29.5, earInX: 10.0, earInY: -16.5, earOutX: 35.5, earOutY: -4.5, earTipX: 25.0, earTipY: -18.5, earTipSpread: 4.2,
        tailWidth: 9.5,
        hindLeftX: -31.0, hindW: 15.5, hindRightX: 15.5, hindLeftY: 3.5, hindLeftH: 12.0, hindStaggerY: 4.5, hindStaggerH: 12.5,
        idleTopDY: 31, idleTopX: 16.5, idleBotX: 15.0, shoulderX: 18.5, limbStartW: 17.0, limbEndW: 12.5,
        sleekEyes: true)
    private static func build(_ skin: SkinSpec) -> Build { skin.shape.build == .sleek ? sleekBuild : standardBuild }

    /// Scale v around c by k; returns v untouched when k == 1 so default shapes stay bit-identical.
    private static func around(_ v: CGFloat, _ c: CGFloat, _ k: CGFloat) -> CGFloat { k == 1 ? v : c + (v - c) * k }

    /// Hit test in 360x320 logical canvas coordinates for smart click-through & petting.
    static func hitTest(point p: CGPoint, physics: CatPhysics, showPermissionPill: Bool) -> CatHitZone {
        if showPermissionPill && permissionPillRect.insetBy(dx: -4, dy: -4).contains(p) {
            return .permissionPill
        }

        let skin = CatSettings.shared.activeSkin
        if skin.renderStyle == .douni {
            let loaf = max(0, min(1, physics.douniLoafBlend.value))
            let loafS = loaf * loaf * (3.0 - 2.0 * loaf)
            let scruff = max(0, min(1, physics.scruffDrag.value))
            if scruff > 0.25 {
                let d = hypot((p.x - 178) / 118, (p.y - 165) / 96)
                return d <= 1.0 ? .body : .none
            }
            // Continuously interpolate head hit zone from Video 2 desk seat -> Video 1 loaf so petting never drops or ping-pongs mid-morph!
            let hx = 248 + (162 - 248) * loafS
            let hy = 124 + (188 - 124) * loafS
            let hrx = 76 + (92 - 76) * loafS
            let hdx = (p.x - hx) / hrx
            let hdy = (p.y - hy) / 56
            if hdx * hdx + hdy * hdy <= 1.0 { return .head }
            if (loaf > 0.03 || physics.petHeadIntensity > 0.05) && loaf < 0.90 {
                let v2dx = (p.x - 248) / 76
                let v2dy = (p.y - 124) / 56
                if v2dx * v2dx + v2dy * v2dy <= 1.0 { return .head }
            }
            if loafS > 0.55 {
                let bdx = (p.x - 196) / 118
                let bdy = (p.y - 196) / 68
                return (bdx * bdx + bdy * bdy <= 1.0) ? .body : .none
            }
            if CGRect(x: 24, y: 120, width: 312, height: 158).contains(p) { return .body }
            return .none
        }

        let shape = skin.shape
        let cx = CatPhysics.seatAnchor.x + physics.bodyShiftX.value
        let breath = physics.breathingOffset
        let headLift: CGFloat = build(skin).headLift
        let headCenter = CGPoint(x: cx + physics.bodyTilt.value * 42, y: 124 + headLift + physics.headOffsetY.value + breath)

        // Head hit ellipse (strictly on the cat's head — never overlaps keyboard); follows head size + cheeks.
        let hdx = (p.x - headCenter.x) / (44.0 * shape.headScale * shape.cheekFullness)
        let hdy = (p.y - headCenter.y) / (38.0 * shape.headScale)
        if hdx * hdx + hdy * hdy <= 1.0 {
            return .head
        }

        // Torso + keyboard area hit check (follows body width)
        let bdx = (p.x - cx) / (58.0 * shape.bodyWidth)
        let bdy = (p.y - 196.0) / 56.0
        if bdx * bdx + bdy * bdy <= 1.0 {
            return .body
        }

        // Mini keyboard & mouse area (allows dragging by grabbing keyboard too)
        let kbRect = CGRect(x: 58, y: 232, width: 236, height: 64)
        if kbRect.contains(p) {
            return .body
        }

        return .none
    }

    /// Main 60fps draw routine in flipped 360x320 logical coordinate space.
    static func draw(in ctx: CGContext, physics: CatPhysics, showPermissionPill: Bool,
                     permissionPillText: String = "点击开启全局/游戏键盘监听 🔑",
                     isPreview: Bool = false) {
        ctx.saveGState()
        ctx.setAllowsAntialiasing(true)
        ctx.setShouldAntialias(true)

        let settings = CatSettings.shared
        if !isPreview && settings.obsCaptureMode == 2 {
            ctx.setFillColor(NSColor(calibratedRed: 0.0, green: 1.0, blue: 0.0, alpha: 1.0).cgColor)
            ctx.fill(CGRect(origin: .zero, size: CatPhysics.canvasSize))
        }
        let flipped = isPreview ? false : settings.flipHorizontal
        let rotationDeg: CGFloat = isPreview ? 0.0 : settings.rotationDeg
        let showEdit = !isPreview && settings.isEditMode
        let hasCanvasTransform = flipped || abs(rotationDeg) > 0.05
        if hasCanvasTransform {
            ctx.saveGState()
            if abs(rotationDeg) > 0.05 {
                let rad = rotationDeg * .pi / 180.0
                let fitScale = 1.0 - abs(sin(rad)) * 0.14
                ctx.translateBy(x: 180.0, y: 160.0)
                ctx.rotate(by: rad)
                ctx.scaleBy(x: fitScale, y: fitScale)
                ctx.translateBy(x: -180.0, y: -160.0)
            }
            if flipped {
                ctx.translateBy(x: CatPhysics.canvasSize.width, y: 0)
                ctx.scaleBy(x: -1, y: 1)
            }
        }
        let skin = settings.activeSkin
        let breath = physics.breathingOffset
        let scruff = max(0, min(1, physics.scruffDrag.value))
        let lie = max(0, min(1, physics.lieIntensity.value))
        let dizzy = max(0, min(1, physics.dizzyIntensity.value))
        let lieS = lie * lie * (3.0 - 2.0 * lie)
        // Dizzy has 2 stages: [0.12..0.50] upright stars + spiral eyes + wobble; [0.50..1.0] smooth sideways collapse onto keyboard!
        let dizzyFallRaw = max(0, min(1, (dizzy - 0.50) / 0.50))
        let dizzyFall = dizzyFallRaw * dizzyFallRaw * (3.0 - 2.0 * dizzyFallRaw)
        let preWobble = max(0, min(1, (dizzy - 0.12) / 0.38)) * (1.0 - dizzyFall)

        let seatX = CatPhysics.seatAnchor.x + physics.bodyShiftX.value
        let seatY = CatPhysics.seatAnchor.y - scruff * 22.0 + lieS * 10.0
        let kbSkin = settings.activeKeyboardSkin

        if skin.renderStyle == .douni {
            drawDouniScene(
                in: ctx,
                physics: physics,
                skin: skin,
                kbSkin: kbSkin,
                eyeTheme: settings.eyeTheme,
                flipped: flipped,
                marquee: settings.keyboardMarquee
            )
            if !physics.floatingKeycaps.isEmpty {
                drawFloatingKeycaps(in: ctx, physics: physics)
            }
            if hasCanvasTransform { ctx.restoreGState() }
            if showEdit {
                drawEditOverlay(in: ctx, isEnglish: settings.isEnglish, scale: settings.scale, rotationDeg: rotationDeg, flipped: flipped)
            }
            if showPermissionPill {
                drawPermissionPill(in: ctx, text: permissionPillText)
            }
            ctx.restoreGState()
            return
        }

        // Universal Scruff-Lifted Drag Pose (ALL non-Douni cat skins keep their own authentic KuroCat face/head/ears/markings in front,
        // with scruff-lifted arched neck/back, 4 dangling swinging paws, and limp drooping tail!)
        if scruff > 0.005 {
            let kbFade = max(0, min(1, 1.0 - scruff * 2.6))
            if kbFade > 0.01 {
                ctx.saveGState()
                ctx.setAlpha(kbFade)
                if physics.isTabletActive {
                    drawTablet(in: ctx, physics: physics, theme: settings.keyboardTheme, eyeTheme: settings.eyeTheme)
                    drawParkedStylus(in: ctx, theme: settings.keyboardTheme, eyeTheme: settings.eyeTheme)
                } else {
                    drawMouse(in: ctx, physics: physics, kbSkin: kbSkin)
                }
                drawKeyboard(in: ctx, physics: physics, kbSkin: kbSkin, eyeTheme: settings.eyeTheme, showLegends: settings.showKeyLegends, flipped: flipped, marquee: settings.keyboardMarquee)
                ctx.restoreGState()
            }
            drawNativeScruffDragCat(in: ctx, physics: physics, skin: skin, eyeTheme: settings.eyeTheme, lift: scruff)
            if !physics.floatingKeycaps.isEmpty {
                drawFloatingKeycaps(in: ctx, physics: physics)
            }
            if hasCanvasTransform { ctx.restoreGState() }
            if showEdit {
                drawEditOverlay(in: ctx, isEnglish: settings.isEnglish, scale: settings.scale, rotationDeg: rotationDeg, flipped: flipped)
            }
            if showPermissionPill {
                drawPermissionPill(in: ctx, text: permissionPillText)
            }
            ctx.restoreGState()
            return
        }

        // 1. Mini White Mouse OR Graphics Tablet (when drawing tablet/stylus is connected!)
        if physics.isTabletActive {
            drawTablet(in: ctx, physics: physics, theme: settings.keyboardTheme, eyeTheme: settings.eyeTheme)
            if !physics.leftPawOnMouse || scruff > 0.25 || dizzy > 0.35 || lie > 0.45 {
                drawParkedStylus(in: ctx, theme: settings.keyboardTheme, eyeTheme: settings.eyeTheme)
            }
        } else {
            drawMouse(in: ctx, physics: physics, kbSkin: kbSkin)
        }

        // 2. Mini Angled 65% Mechanical Keyboard + Dynamic Keycap Glow
        drawKeyboard(in: ctx, physics: physics, kbSkin: kbSkin, eyeTheme: settings.eyeTheme, showLegends: settings.showKeyLegends, flipped: flipped, marquee: settings.keyboardMarquee)

        // Rigid-body wobble (pre-dizzy) -> natural sideways collapse onto the keyboard (dizzy >= 0.5)
        let fallAngle: CGFloat = -dizzyFall * 1.46 + sin(physics.time * 9.5) * 0.16 * preWobble
        let fallShiftX: CGFloat = dizzyFall * 56.0
        let fallShiftY: CGFloat = dizzyFall * 20.0
        let baseHead = headPosition(physics, skin: skin)
        let localHeadCenter = CGPoint(x: baseHead.x - lieS * 4.0, y: baseHead.y + lieS * 60.0)
        let tailInFront = (physics.tailTyping.value >= 0.5) || (lieS >= 0.45)

        ctx.saveGState()
        if dizzy > 0.01 {
            ctx.translateBy(x: seatX + fallShiftX, y: seatY + fallShiftY)
            ctx.rotate(by: fallAngle)
            ctx.translateBy(x: -seatX, y: -seatY)
        }

        let showWhiteOutline = settings.whiteOutline
        // Pass 1: optional unified sticker-style outer white outline for ALL cat skins
        if showWhiteOutline {
            // Outline connected parts before any fills so the tail root has no white seam.
            drawTail(in: ctx, seatX: seatX, seatY: seatY, physics: physics, skin: skin, outlineOnly: true)
            drawEarsLayer(in: ctx, center: localHeadCenter, physics: physics, skin: skin, outlineOnly: true)
            drawUnifiedSilhouette(
                in: ctx,
                seatX: seatX,
                seatY: seatY,
                headCenter: localHeadCenter,
                breath: breath,
                physics: physics,
                skin: skin,
                outlineOnly: true
            )
        }

        if skin.renderStyle == .dazed {
            drawDazedSword(in: ctx, seatX: seatX, seatY: seatY, physics: physics)
        }

        if !tailInFront {
            drawTail(in: ctx, seatX: seatX, seatY: seatY, physics: physics, skin: skin)
        }

        // 4. 3D-Projected Ears (behind crown silhouette so seal-point ears emerge cleanly from cream skull!)
        drawEarsLayer(in: ctx, center: localHeadCenter, physics: physics, skin: skin)

        // 5. Unified C1-Continuous Head + Neck + Pear Torso Silhouette (+ regions, colour-point mask, marks)
        drawUnifiedSilhouette(
            in: ctx,
            seatX: seatX,
            seatY: seatY,
            headCenter: localHeadCenter,
            breath: breath,
            physics: physics,
            skin: skin
        )

        // 6. Hind Foot (3rd simultaneous key easter egg!)
        if physics.hindFootActive.value > 0.03 {
            drawHindFoot(in: ctx, seatX: seatX, seatY: seatY, physics: physics, skin: skin)
        }

        // 7. 2.5D Turning Head Features: Luminous Eyes & Whiskers (+ optional nose/mouth)
        drawHeadFeatures(in: ctx, center: localHeadCenter, physics: physics, eyeTheme: settings.eyeTheme, skin: skin)

        // 7b. Skin stickers anchored to head / neck / tail tip
        if !skin.decorations.isEmpty {
            drawDecorations(in: ctx, seatX: seatX, seatY: seatY, head: localHeadCenter, physics: physics, skin: skin)
        }

        // 8. Front Arms / Paws (over torso & keyboard/mouse with crisp separation outlines / colour-point socks!)
        drawFrontPaws(in: ctx, seatX: seatX, seatY: seatY, breath: breath, physics: physics, skin: skin)

        // 8b. Held Stylus gripped cleanly in the cat's paw when drawing on the graphics tablet!
        if physics.isTabletActive && physics.leftPawOnMouse && scruff <= 0.25 && dizzy <= 0.35 && lie <= 0.45 {
            drawHeldStylus(in: ctx, physics: physics, theme: settings.keyboardTheme, eyeTheme: settings.eyeTheme)
        }

        if tailInFront {
            drawTail(in: ctx, seatX: seatX, seatY: seatY, physics: physics, skin: skin)
        }

        ctx.restoreGState()

        // Upright orbiting golden dizzy stars floating right above the head (appear FIRST before falling!)
        if dizzy > 0.10 {
            let relX = localHeadCenter.x - seatX
            let relY = localHeadCenter.y - seatY
            let worldHeadX = seatX + fallShiftX + relX * cos(fallAngle) - relY * sin(fallAngle)
            let worldHeadY = seatY + fallShiftY + relX * sin(fallAngle) + relY * cos(fallAngle)
            let dAlpha = min(1.0, (dizzy - 0.10) / 0.22)
            let starLift: CGFloat = 42.0 + dizzyFall * 10.0
            ctx.saveGState()
            ctx.translateBy(x: worldHeadX, y: worldHeadY - starLift)
            for i in 0..<3 {
                let ang = physics.dizzyPhase * 0.85 + CGFloat(i) * (.pi * 2.0 / 3.0)
                let sx = cos(ang) * 26.0
                let sy = sin(ang) * 6.5
                let r: CGFloat = 4.4 * (0.75 + 0.25 * sin(ang))
                ctx.saveGState()
                ctx.translateBy(x: sx, y: sy)
                ctx.rotate(by: physics.dizzyPhase + CGFloat(i))
                ctx.setFillColor(NSColor(calibratedRed: 1.0, green: 0.86, blue: 0.22, alpha: 0.96 * dAlpha).cgColor)
                let star = CGMutablePath()
                for k in 0..<8 {
                    let rad = (k % 2 == 0) ? r : r * 0.42
                    let a = CGFloat(k) * .pi * 0.25
                    let pt = CGPoint(x: cos(a) * rad, y: sin(a) * rad)
                    if k == 0 { star.move(to: pt) } else { star.addLine(to: pt) }
                }
                star.closeSubpath()
                ctx.addPath(star)
                ctx.fillPath()
                ctx.restoreGState()
            }
            ctx.restoreGState()
        }

        // 8. Floating Mechanical Keycap Badges (keyboard + mouse clicks)
        if !physics.floatingKeycaps.isEmpty {
            drawFloatingKeycaps(in: ctx, physics: physics)
        }

        // 9. Subtle Petting Sparkles / Sleep Z
        drawSparkles(in: ctx, physics: physics, eyeTheme: settings.eyeTheme)

        if hasCanvasTransform {
            ctx.restoreGState()
        }

        // 10. Clean Transparent Resize & Rotation Edit Box (no blue tint, no flip/done buttons)
        if showEdit {
            drawEditOverlay(in: ctx, isEnglish: settings.isEnglish, scale: settings.scale, rotationDeg: rotationDeg, flipped: flipped)
        }

        // 11. Optional non-intrusive Permission Pill if global monitoring not yet granted
        if showPermissionPill {
            drawPermissionPill(in: ctx, text: permissionPillText)
        }

        ctx.restoreGState()
    }

    private static func drawEditOverlay(in ctx: CGContext, isEnglish: Bool, scale: CGFloat, rotationDeg: CGFloat = 0, flipped: Bool = false) {
        _ = isEnglish
        ctx.saveGState()
        let boxRect = CGRect(x: 10, y: 26, width: 340, height: 284)
        let boxPath = CGPath(roundedRect: boxRect, cornerWidth: 12, cornerHeight: 12, transform: nil)

        // Clean transparent dashed border ONLY (zero blue tint fill, zero cluttered pill buttons!)
        ctx.setStrokeColor(NSColor(calibratedRed: 0.20, green: 0.62, blue: 1.0, alpha: 0.90).cgColor)
        ctx.setLineWidth(1.6)
        ctx.setLineDash(phase: 0, lengths: [6, 4])
        ctx.addPath(boxPath)
        ctx.strokePath()
        ctx.setLineDash(phase: 0, lengths: [])

        // 4 corner resize handles
        for c in editCorners {
            let r: CGFloat = 6.0
            let hRect = CGRect(x: c.x - r, y: c.y - r, width: r * 2, height: r * 2)
            ctx.setFillColor(NSColor.white.cgColor)
            ctx.fillEllipse(in: hRect)
            ctx.setStrokeColor(NSColor(calibratedRed: 0.14, green: 0.52, blue: 0.96, alpha: 1.0).cgColor)
            ctx.setLineWidth(1.9)
            ctx.strokeEllipse(in: hRect)
        }

        // Top-center direction/rotation handle (drag to rotate freely, single-click to mirror-flip, double-click to reset 0°)
        let rh = editRotateHandle
        ctx.setStrokeColor(NSColor(calibratedRed: 0.14, green: 0.52, blue: 0.96, alpha: 0.92).cgColor)
        ctx.setLineWidth(1.6)
        ctx.move(to: CGPoint(x: rh.x, y: boxRect.minY))
        ctx.addLine(to: CGPoint(x: rh.x, y: rh.y + 7.5))
        ctx.strokePath()

        let rr: CGFloat = 8.0
        let rRect = CGRect(x: rh.x - rr, y: rh.y - rr, width: rr * 2, height: rr * 2)
        ctx.setFillColor(NSColor.white.cgColor)
        ctx.fillEllipse(in: rRect)
        ctx.setStrokeColor(NSColor(calibratedRed: 0.14, green: 0.52, blue: 0.96, alpha: 1.0).cgColor)
        ctx.setLineWidth(1.9)
        ctx.strokeEllipse(in: rRect)

        // Crisp circular rotation arrow inside handle
        ctx.setStrokeColor(NSColor(calibratedRed: 0.14, green: 0.52, blue: 0.96, alpha: 1.0).cgColor)
        ctx.setLineWidth(1.4)
        ctx.setLineCap(.round)
        ctx.addArc(center: rh, radius: 4.1, startAngle: -.pi * 0.72, endAngle: .pi * 0.78, clockwise: false)
        ctx.strokePath()
        let ax = rh.x + cos(-.pi * 0.72) * 4.1
        let ay = rh.y + sin(-.pi * 0.72) * 4.1
        ctx.move(to: CGPoint(x: ax - 2.4, y: ay + 0.5))
        ctx.addLine(to: CGPoint(x: ax + 0.3, y: ay - 0.3))
        ctx.addLine(to: CGPoint(x: ax + 0.8, y: ay + 2.4))
        ctx.strokePath()

        // Compact bottom readout badge (scale + optional angle / flip marker)
        var statusStr = String(format: "%.0f%%", scale * 100)
        let roundedDeg = Int(rotationDeg.rounded())
        if roundedDeg != 0 { statusStr += " · \(roundedDeg)°" }
        if flipped { statusStr += " · ⇄" }
        let sAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 9.5, weight: .semibold),
            .foregroundColor: NSColor.white
        ]
        let sns = NSAttributedString(string: statusStr, attributes: sAttrs)
        let ssz = sns.size()
        let pill = CGRect(x: 180 - (ssz.width + 12) * 0.5, y: 298 - (ssz.height + 4) * 0.5, width: ssz.width + 12, height: ssz.height + 4)
        ctx.setFillColor(NSColor(calibratedRed: 0.12, green: 0.13, blue: 0.16, alpha: 0.82).cgColor)
        ctx.addPath(CGPath(roundedRect: pill, cornerWidth: 6, cornerHeight: 6, transform: nil))
        ctx.fillPath()
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: ctx, flipped: true)
        sns.draw(at: CGPoint(x: pill.midX - ssz.width * 0.5, y: pill.midY - ssz.height * 0.5))
        NSGraphicsContext.restoreGraphicsState()

        ctx.restoreGState()
    }

    static func headPosition(_ physics: CatPhysics, coat: CatCoatTheme) -> CGPoint {
        headPosition(physics, skin: SkinSpec.builtIn(coat))
    }

    static func headPosition(_ physics: CatPhysics, skin: SkinSpec) -> CGPoint {
        let headLift: CGFloat = build(skin).headLift
        let scruff = max(0, min(1, physics.scruffDrag.value))
        return CGPoint(
            x: CatPhysics.seatAnchor.x + physics.bodyShiftX.value + physics.bodyTilt.value * 36 + physics.headYaw.value * 7.5,
            y: 126 + headLift + physics.headOffsetY.value + physics.headPitch.value * 4.8 + physics.breathingOffset * 1.1 - scruff * 22.0
        )
    }

    // MARK: - Mini White Mouse

    private static func drawMouse(in ctx: CGContext, physics: CatPhysics, kbSkin: KeyboardSkinSpec) {
        let center = CGPoint(
            x: CatPhysics.mouseBaseCenter.x + physics.mouseOffset.point.x,
            y: CatPhysics.mouseBaseCenter.y + physics.mouseOffset.point.y
        )
        let pressShift = max(physics.mousePressLeft.value, physics.mousePressRight.value) * 1.6

        ctx.saveGState()
        ctx.translateBy(x: center.x, y: center.y + pressShift)
        ctx.rotate(by: 0.22) // angled naturally for the cat's right paw (facing the cat!)

        // Soft underside shadow
        ctx.saveGState()
        ctx.setFillColor(NSColor(calibratedWhite: 0.0, alpha: 0.24).cgColor)
        ctx.fillEllipse(in: CGRect(x: -13.5, y: -13.5 + 4.0, width: 27, height: 31))
        ctx.restoreGState()

        let bodyRect = CGRect(x: -13.5, y: -16.5, width: 27, height: 33)
        let bodyColor = kbSkin.mouseBody.ns
        let borderColor = kbSkin.mouseBorder.ns
        let wheelColor = kbSkin.wheel.ns

        // Mouse body (palm-rest dome toward cat at top, click buttons & scroll wheel away from cat at bottom!)
        ctx.setFillColor(bodyColor.cgColor)
        ctx.fillEllipse(in: bodyRect)

        // Subtle click flash highlight (cat-facing: left button = inner right side, right button = outer left side!)
        if physics.mousePressLeft.value > 0.05 {
            ctx.saveGState()
            ctx.addEllipse(in: bodyRect)
            ctx.clip()
            ctx.setFillColor(NSColor(calibratedRed: 0.79, green: 0.95, blue: 0.25, alpha: 0.38 * physics.mousePressLeft.value).cgColor)
            ctx.fill(CGRect(x: 0, y: 0, width: 14, height: 17))
            ctx.restoreGState()
        }
        if physics.mousePressRight.value > 0.05 {
            ctx.saveGState()
            ctx.addEllipse(in: bodyRect)
            ctx.clip()
            ctx.setFillColor(NSColor(calibratedRed: 0.79, green: 0.95, blue: 0.25, alpha: 0.38 * physics.mousePressRight.value).cgColor)
            ctx.fill(CGRect(x: -14, y: 0, width: 14, height: 17))
            ctx.restoreGState()
        }

        // Button split seam pointing forward (bottom, away from cat!)
        ctx.setStrokeColor(borderColor.withAlphaComponent(0.32).cgColor)
        ctx.setLineWidth(1.05)
        ctx.move(to: CGPoint(x: 0, y: 16))
        ctx.addLine(to: CGPoint(x: 0, y: 1.5))
        ctx.strokePath()

        // Signature amber scroll wheel on the front (bottom) half facing away from cat
        let wheelRect = CGRect(x: -1.9, y: 2.5, width: 3.8, height: 8.5)
        let wheelPath = CGPath(roundedRect: wheelRect, cornerWidth: 1.9, cornerHeight: 1.9, transform: nil)
        ctx.setFillColor(wheelColor.cgColor)
        ctx.addPath(wheelPath)
        ctx.fillPath()

        // Outer crisp outline
        ctx.setStrokeColor(borderColor.cgColor)
        ctx.setLineWidth(1.7)
        ctx.strokeEllipse(in: bodyRect)

        ctx.restoreGState()
    }

    // MARK: - Mini 2.5D Graphics Tablet & Stylus (数位板与触控笔)

    private static func drawTablet(in ctx: CGContext, physics: CatPhysics, theme: KeyboardTheme, eyeTheme: EyeColorTheme) {
        let tl = CatPhysics.tabletQuadPoint(u: 0, v: 0)
        let tr = CatPhysics.tabletQuadPoint(u: 1, v: 0)
        let bl = CatPhysics.tabletQuadPoint(u: 0, v: 1)
        let br = CatPhysics.tabletQuadPoint(u: 1, v: 1)
        let depth: CGFloat = 3.6

        let baseColor: NSColor
        let bodyColor: NSColor
        let padColor: NSColor
        let keyColor: NSColor
        let accentColor: NSColor
        switch theme {
        case .classicMilk:
            baseColor = NSColor(calibratedRed: 0.10, green: 0.10, blue: 0.12, alpha: 1.0)
            bodyColor = NSColor(calibratedRed: 0.17, green: 0.18, blue: 0.21, alpha: 1.0)
            padColor  = NSColor(calibratedRed: 0.23, green: 0.24, blue: 0.28, alpha: 1.0)
            keyColor  = NSColor(calibratedRed: 0.30, green: 0.32, blue: 0.37, alpha: 1.0)
            accentColor = NSColor(calibratedRed: 0.96, green: 0.69, blue: 0.16, alpha: 1.0)
        case .midnightHacker:
            baseColor = NSColor(calibratedRed: 0.05, green: 0.05, blue: 0.07, alpha: 1.0)
            bodyColor = NSColor(calibratedRed: 0.11, green: 0.12, blue: 0.15, alpha: 1.0)
            padColor  = NSColor(calibratedRed: 0.16, green: 0.17, blue: 0.21, alpha: 1.0)
            keyColor  = NSColor(calibratedRed: 0.24, green: 0.25, blue: 0.30, alpha: 1.0)
            accentColor = NSColor(calibratedRed: 0.78, green: 0.95, blue: 0.25, alpha: 1.0)
        case .retroCream:
            baseColor = NSColor(calibratedRed: 0.22, green: 0.21, blue: 0.19, alpha: 1.0)
            bodyColor = NSColor(calibratedRed: 0.33, green: 0.31, blue: 0.28, alpha: 1.0)
            padColor  = NSColor(calibratedRed: 0.42, green: 0.39, blue: 0.35, alpha: 1.0)
            keyColor  = NSColor(calibratedRed: 0.54, green: 0.50, blue: 0.45, alpha: 1.0)
            accentColor = NSColor(calibratedRed: 0.88, green: 0.42, blue: 0.24, alpha: 1.0)
        }

        // Ambient drop shadow beneath tablet
        ctx.saveGState()
        let shadowPath = roundedQuadPath(
            tl: CGPoint(x: tl.x, y: tl.y + depth + 2.0),
            tr: CGPoint(x: tr.x, y: tr.y + depth + 2.0),
            br: CGPoint(x: br.x, y: br.y + depth + 2.6),
            bl: CGPoint(x: bl.x, y: bl.y + depth + 2.6),
            radius: 5.5
        )
        ctx.setFillColor(NSColor(calibratedWhite: 0, alpha: 0.22).cgColor)
        ctx.addPath(shadowPath)
        ctx.fillPath()
        ctx.restoreGState()

        // 3D lower slab lip
        let lowerPath = roundedQuadPath(
            tl: CGPoint(x: tl.x, y: tl.y + depth),
            tr: CGPoint(x: tr.x, y: tr.y + depth),
            br: CGPoint(x: br.x, y: br.y + depth),
            bl: CGPoint(x: bl.x, y: bl.y + depth),
            radius: 5.0
        )
        ctx.setFillColor(baseColor.cgColor)
        ctx.addPath(lowerPath)
        ctx.fillPath()

        // Main slate tablet deck
        let topPath = roundedQuadPath(tl: tl, tr: tr, br: br, bl: bl, radius: 4.5)
        ctx.setFillColor(bodyColor.cgColor)
        ctx.addPath(topPath)
        ctx.fillPath()

        // Crisp subtle bezel rim
        ctx.setStrokeColor(NSColor(calibratedWhite: 1.0, alpha: 0.14).cgColor)
        ctx.setLineWidth(0.9)
        ctx.addPath(topPath)
        ctx.strokePath()

        // Active drawing surface recessed pad
        let pTL = CatPhysics.tabletQuadPoint(u: 0.21, v: 0.11)
        let pTR = CatPhysics.tabletQuadPoint(u: 0.94, v: 0.11)
        let pBR = CatPhysics.tabletQuadPoint(u: 0.94, v: 0.89)
        let pBL = CatPhysics.tabletQuadPoint(u: 0.21, v: 0.89)
        let padPath = roundedQuadPath(tl: pTL, tr: pTR, br: pBR, bl: pBL, radius: 2.6)
        ctx.setFillColor(padColor.cgColor)
        ctx.addPath(padPath)
        ctx.fillPath()

        // Minimalist active-area corner L-brackets ([ ])
        ctx.saveGState()
        ctx.setStrokeColor(NSColor(calibratedWhite: 1.0, alpha: 0.34).cgColor)
        ctx.setLineWidth(0.95)
        ctx.setLineCap(.round)
        let corners: [(CGFloat, CGFloat, CGFloat, CGFloat)] = [
            (0.24, 0.15,  0.07,  0.11),
            (0.91, 0.15, -0.07,  0.11),
            (0.24, 0.85,  0.07, -0.11),
            (0.91, 0.85, -0.07, -0.11)
        ]
        for (cu, cv, du, dv) in corners {
            let c = CatPhysics.tabletQuadPoint(u: cu, v: cv)
            let h = CatPhysics.tabletQuadPoint(u: cu + du, v: cv)
            let v = CatPhysics.tabletQuadPoint(u: cu, v: cv + dv)
            ctx.move(to: h); ctx.addLine(to: c); ctx.addLine(to: v)
        }
        ctx.strokePath()
        ctx.restoreGState()

        // 4 miniature ExpressKeys along outer-left bezel + status LED
        let ledPt = CatPhysics.tabletQuadPoint(u: 0.105, v: 0.14)
        let ledCol = physics.tabletPenPress.value > 0.15 ? eyeTheme.primaryColor : accentColor
        drawRadialGlow(in: ctx, center: ledPt, radius: 4.5, color: ledCol.withAlphaComponent(0.55))
        ctx.setFillColor(ledCol.cgColor)
        ctx.fillEllipse(in: CGRect(x: ledPt.x - 1.35, y: ledPt.y - 1.35, width: 2.7, height: 2.7))

        for kv: CGFloat in [0.28, 0.44, 0.60, 0.76] {
            let kTL = CatPhysics.tabletQuadPoint(u: 0.06, v: kv - 0.05)
            let kTR = CatPhysics.tabletQuadPoint(u: 0.15, v: kv - 0.05)
            let kBR = CatPhysics.tabletQuadPoint(u: 0.15, v: kv + 0.05)
            let kBL = CatPhysics.tabletQuadPoint(u: 0.06, v: kv + 0.05)
            let kp = roundedQuadPath(tl: kTL, tr: kTR, br: kBR, bl: kBL, radius: 1.2)
            ctx.setFillColor(keyColor.cgColor)
            ctx.addPath(kp)
            ctx.fillPath()
        }

        // Live fading glowing ink trail on the active drawing surface!
        if physics.tabletTrail.count >= 2 {
            ctx.saveGState()
            ctx.addPath(padPath)
            ctx.clip()
            ctx.setLineCap(.round)
            ctx.setLineJoin(.round)
            let inkCol = eyeTheme.primaryColor
            for i in 1..<physics.tabletTrail.count {
                let a = physics.tabletTrail[i - 1]
                let b = physics.tabletTrail[i]
                if hypot(b.point.x - a.point.x, b.point.y - a.point.y) > 22.0 { continue }
                let life = max(0.0, 1.0 - b.age / 0.72)
                if life <= 0.01 { continue }
                ctx.setStrokeColor(inkCol.withAlphaComponent(life * 0.88).cgColor)
                ctx.setLineWidth(1.2 + life * 1.4)
                ctx.move(to: a.point)
                ctx.addLine(to: b.point)
                ctx.strokePath()
            }
            ctx.restoreGState()
        }

        // Subtle glowing nib contact halo when drawing on the pad
        if physics.leftPawOnMouse && physics.tabletPenPress.value > 0.08 {
            let nib = physics.tabletNib.point
            drawRadialGlow(
                in: ctx,
                center: nib,
                radius: 7.5 + physics.tabletPenPress.value * 4.0,
                color: eyeTheme.primaryColor.withAlphaComponent(0.45 * physics.tabletPenPress.value)
            )
        }
    }

    /// Draws a sleek stylus oriented along +X from tip (0,0) to rounded cap (len,0).
    private static func drawStylusBody(in ctx: CGContext, length: CGFloat, theme: KeyboardTheme, eyeTheme: EyeColorTheme, pressed: CGFloat) {
        let barrelCol: NSColor
        let gripCol: NSColor
        let ringCol: NSColor
        switch theme {
        case .classicMilk:
            barrelCol = NSColor(calibratedRed: 0.18, green: 0.19, blue: 0.23, alpha: 1.0)
            gripCol   = NSColor(calibratedRed: 0.28, green: 0.30, blue: 0.35, alpha: 1.0)
            ringCol   = NSColor(calibratedRed: 0.96, green: 0.69, blue: 0.16, alpha: 1.0)
        case .midnightHacker:
            barrelCol = NSColor(calibratedRed: 0.13, green: 0.14, blue: 0.17, alpha: 1.0)
            gripCol   = NSColor(calibratedRed: 0.22, green: 0.24, blue: 0.29, alpha: 1.0)
            ringCol   = NSColor(calibratedRed: 0.78, green: 0.95, blue: 0.25, alpha: 1.0)
        case .retroCream:
            barrelCol = NSColor(calibratedRed: 0.28, green: 0.26, blue: 0.24, alpha: 1.0)
            gripCol   = NSColor(calibratedRed: 0.42, green: 0.39, blue: 0.35, alpha: 1.0)
            ringCol   = NSColor(calibratedRed: 0.88, green: 0.42, blue: 0.24, alpha: 1.0)
        }

        // Tapered pen silhouette (nib at x=0 -> tapered cone x=7 -> ergonomic barrel -> rounded eraser cap at x=length)
        let penPath = CGMutablePath()
        penPath.move(to: CGPoint(x: 0.0, y: 0.0))
        penPath.addLine(to: CGPoint(x: 7.5, y: -2.4))
        penPath.addLine(to: CGPoint(x: length - 3.0, y: -2.6))
        penPath.addQuadCurve(to: CGPoint(x: length, y: 0.0), control: CGPoint(x: length, y: -2.4))
        penPath.addQuadCurve(to: CGPoint(x: length - 3.0, y: 2.6), control: CGPoint(x: length, y: 2.4))
        penPath.addLine(to: CGPoint(x: 7.5, y: 2.4))
        penPath.closeSubpath()

        // Crisp subtle bright outer halo so stylus reads cleanly over dark fur/backgrounds
        ctx.saveGState()
        ctx.setStrokeColor(NSColor(calibratedWhite: 0.96, alpha: 0.80).cgColor)
        ctx.setLineWidth(1.6)
        ctx.setLineJoin(.round)
        ctx.addPath(penPath)
        ctx.strokePath()
        ctx.restoreGState()

        ctx.setFillColor(barrelCol.cgColor)
        ctx.addPath(penPath)
        ctx.fillPath()

        // Rubberized grip sleeve + dual side-button rocker
        ctx.saveGState()
        ctx.addPath(penPath)
        ctx.clip()
        ctx.setFillColor(gripCol.cgColor)
        ctx.fill(CGRect(x: 7.5, y: -3.0, width: 11.5, height: 6.0))
        // Signature metallic accent ring between grip & upper barrel
        ctx.setFillColor(ringCol.cgColor)
        ctx.fill(CGRect(x: 19.0, y: -3.0, width: 2.4, height: 6.0))
        // Fine light stylus nib tip (glows slightly in eye theme color when pressing down!)
        let nibCol = pressed > 0.15 ? eyeTheme.primaryColor : NSColor(calibratedWhite: 0.94, alpha: 1.0)
        ctx.setFillColor(nibCol.cgColor)
        ctx.fill(CGRect(x: -0.5, y: -1.5, width: 3.4, height: 3.0))
        // Subtle specular sheen along upper barrel
        ctx.setFillColor(NSColor(calibratedWhite: 1.0, alpha: 0.24).cgColor)
        ctx.fill(CGRect(x: 8.0, y: -1.9, width: length - 12.0, height: 1.1))
        ctx.restoreGState()

        // Side shortcut rocker button
        let btn = CGPath(roundedRect: CGRect(x: 11.0, y: -3.1, width: 6.0, height: 1.4), cornerWidth: 0.7, cornerHeight: 0.7, transform: nil)
        ctx.setFillColor(NSColor(calibratedWhite: 0.78, alpha: 0.90).cgColor)
        ctx.addPath(btn)
        ctx.fillPath()
    }

    private static func drawParkedStylus(in ctx: CGContext, theme: KeyboardTheme, eyeTheme: EyeColorTheme) {
        // Neatly parked horizontally along the top bezel of the graphics tablet while typing/sleeping
        let nib = CatPhysics.tabletQuadPoint(u: 0.88, v: -0.02)
        let tail = CatPhysics.tabletQuadPoint(u: 0.18, v: -0.02)
        let ang = atan2(tail.y - nib.y, tail.x - nib.x)
        let len = hypot(tail.x - nib.x, tail.y - nib.y)

        ctx.saveGState()
        // Subtle resting shadow
        ctx.saveGState()
        ctx.translateBy(x: nib.x, y: nib.y + 2.2)
        ctx.rotate(by: ang)
        ctx.setFillColor(NSColor(calibratedWhite: 0, alpha: 0.22).cgColor)
        ctx.fill(CGRect(x: 2, y: -2.0, width: len - 4, height: 4.5))
        ctx.restoreGState()

        ctx.translateBy(x: nib.x, y: nib.y)
        ctx.rotate(by: ang)
        drawStylusBody(in: ctx, length: len, theme: theme, eyeTheme: eyeTheme, pressed: 0)
        ctx.restoreGState()
    }

    private static func drawHeldStylus(in ctx: CGContext, physics: CatPhysics, theme: KeyboardTheme, eyeTheme: EyeColorTheme) {
        let lPos = physics.leftPaw.point
        let press = max(0, min(1, physics.tabletPenPress.value))
        // Nib rests right at the front-bottom tip of the paw touching the tablet surface;
        // shaft angles cleanly upward-left away from the cat's arm so it's 100% crisp and clear!
        let nib = CGPoint(x: lPos.x - 5.5, y: lPos.y + 7.0 + press * 1.4)
        let angle: CGFloat = -2.18 + physics.tabletPenTilt.value

        ctx.saveGState()
        ctx.translateBy(x: nib.x, y: nib.y)
        ctx.rotate(by: angle)
        drawStylusBody(in: ctx, length: 35.0, theme: theme, eyeTheme: eyeTheme, pressed: press)
        ctx.restoreGState()
    }

    // MARK: - Mini Angled 65% Mechanical Keyboard (facing the cat!)

    private struct KeyboardBitmap {
        let image: CGImage
        let bounds: CGRect

        init?(bounds: CGRect, scale: CGSize, draw: (CGContext) -> Void) {
            let pixels = CGRect(x: bounds.minX * scale.width, y: bounds.minY * scale.height,
                                width: bounds.width * scale.width, height: bounds.height * scale.height).integral
            guard let ctx = CGContext(data: nil, width: Int(pixels.width), height: Int(pixels.height),
                                      bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
            ctx.translateBy(x: -pixels.minX, y: pixels.maxY)
            ctx.scaleBy(x: scale.width, y: -scale.height)
            ctx.setAllowsAntialiasing(true)
            ctx.setShouldAntialias(true)
            draw(ctx)
            guard let image = ctx.makeImage() else { return nil }
            self.image = image
            self.bounds = CGRect(x: pixels.minX / scale.width, y: pixels.minY / scale.height,
                                 width: pixels.width / scale.width, height: pixels.height / scale.height)
        }

        func draw(in ctx: CGContext) {
            ctx.saveGState()
            ctx.translateBy(x: bounds.minX, y: bounds.maxY)
            ctx.scaleBy(x: 1, y: -1)
            ctx.draw(image, in: CGRect(origin: .zero, size: bounds.size))
            ctx.restoreGState()
        }
    }

    private struct KeyboardStyle: Equatable {
        let kbSkin: KeyboardSkinSpec
        let showLegends: Bool
        let flipped: Bool
        let scale: CGSize
    }

    private struct KeyboardArtwork {
        let style: KeyboardStyle
        let chassis: KeyboardBitmap?
        let idle: KeyboardBitmap?
        let keys: [KeyboardKeyArtwork]
        let deckPath: CGPath
        let deckStart: CGPoint
        let deckEnd: CGPoint
    }

    private struct KeyboardKeyArtwork {
        let key: PhysicalKey
        let center: CGPoint
        let path: CGPath
        let fill: NSColor
        let border: CGColor
        let legend: KeyboardBitmap?
        let resting: KeyboardBitmap?
    }

    // Keep only the currently displayed keyboard. Retina scale can change when the window moves screens.
    private static var keyboardArtwork: KeyboardArtwork?

    private static func drawKeyboard(
        in ctx: CGContext,
        physics: CatPhysics,
        kbSkin: KeyboardSkinSpec,
        eyeTheme: EyeColorTheme,
        showLegends: Bool,
        flipped: Bool,
        marquee: Bool
    ) {
        let transform = ctx.userSpaceToDeviceSpaceTransform
        // Round up in quarter steps so dragging a resize handle does not rebuild the cache every tick.
        func rasterScale(_ value: CGFloat) -> CGFloat { min(4, max(1, (value * 4).rounded(.up) / 4)) }
        let scale = CGSize(width: rasterScale(hypot(transform.a, transform.b)),
                           height: rasterScale(hypot(transform.c, transform.d)))
        let style = KeyboardStyle(kbSkin: kbSkin, showLegends: showLegends, flipped: flipped, scale: scale)
        if keyboardArtwork?.style != style {
            keyboardArtwork = makeKeyboardArtwork(style: style)
        }
        guard let artwork = keyboardArtwork else { return }

        let glowBaseColor = eyeTheme.glowColor
        if !marquee, physics.keyGlow.isEmpty, let idle = artwork.idle {
            idle.draw(in: ctx)
        } else {
            artwork.chassis?.draw(in: ctx)
            let phase = physics.marqueePhase.truncatingRemainder(dividingBy: 1)
            let backlight = marquee
                ? KeyboardMarquee(phase: phase, color: hsvColor(hue: phase + 0.52, saturation: 0.55, value: 1),
                                  start: artwork.deckStart, end: artwork.deckEnd)
                : nil
            if let backlight { drawMarquee(backlight, in: ctx, clippedTo: artwork.deckPath) }
            for key in artwork.keys {
                drawKeyboardKey(key, in: ctx, glow: physics.keyGlow[key.key] ?? 0,
                                glowColor: glowBaseColor, backlight: backlight)
            }
        }

        // Signature soft chartreuse backlit glow halos on active keys!
        for (key, glow) in physics.keyGlow where glow > 0.05 {
            let center = KeyboardLayout.canvasPoint(for: key)
            drawRadialGlow(in: ctx, center: center, radius: 17.0 + glow * 6.0,
                           color: glowBaseColor.withAlphaComponent(0.36 * glow))
        }
    }

    private static func makeKeyboardArtwork(style: KeyboardStyle) -> KeyboardArtwork {
        let tl = KeyboardLayout.screenQuadPoint(su: -0.012, sv: -0.04)
        let tr = KeyboardLayout.screenQuadPoint(su: 1.012, sv: -0.04)
        let bl = KeyboardLayout.screenQuadPoint(su: -0.016, sv: 1.04)
        let br = KeyboardLayout.screenQuadPoint(su: 1.016, sv: 1.04)

        let caseDepth: CGFloat = 4.5

        let shadowPath = roundedQuadPath(
            tl: CGPoint(x: tl.x, y: tl.y + caseDepth + 2),
            tr: CGPoint(x: tr.x, y: tr.y + caseDepth + 2),
            br: CGPoint(x: br.x, y: br.y + caseDepth + 3),
            bl: CGPoint(x: bl.x, y: bl.y + caseDepth + 3),
            radius: 6
        )

        // Dark 3D chassis lower lip (built-in or imported .kurokb / keyboard.json skin!)
        let kb = style.kbSkin
        let baseColor = kb.base.ns
        let deckColor = kb.deck.ns
        let keyColor = kb.key.ns
        let keyBorderColor = kb.keyBorder.ns
        let accentColor = kb.accent.ns

        let lowerChassis = roundedQuadPath(
            tl: CGPoint(x: tl.x, y: tl.y + caseDepth),
            tr: CGPoint(x: tr.x, y: tr.y + caseDepth),
            br: CGPoint(x: br.x, y: br.y + caseDepth),
            bl: CGPoint(x: bl.x, y: bl.y + caseDepth),
            radius: 5.5
        )
        let topChassis = roundedQuadPath(tl: tl, tr: tr, br: br, bl: bl, radius: 5.0)
        let bounds = shadowPath.boundingBoxOfPath.union(lowerChassis.boundingBoxOfPath)
            .union(topChassis.boundingBoxOfPath).insetBy(dx: -2, dy: -2)
        let chassis = KeyboardBitmap(bounds: bounds, scale: style.scale) { ctx in
            ctx.setFillColor(NSColor(calibratedWhite: 0, alpha: 0.22).cgColor)
            ctx.addPath(shadowPath)
            ctx.fillPath()
            ctx.setFillColor(baseColor.cgColor)
            ctx.addPath(lowerChassis)
            ctx.fillPath()
            ctx.setFillColor(deckColor.cgColor)
            ctx.addPath(topChassis)
            ctx.fillPath()
        }

        // Individual keycaps — tight clean mechanical spacing matching the reference video
        let padU: CGFloat = 0.0028
        let padV: CGFloat = 0.014
        let border = keyBorderColor.cgColor

        let keys = KeyboardLayout.keycaps.map { cap in
            // 180° rotated to face the cat: su = 1 - u, sv = 1 - v
            let su0 = (1.0 - (cap.xUnits + cap.widthUnits)) + padU
            let su1 = (1.0 - cap.xUnits) - padU
            let sv0 = (1.0 - CGFloat(cap.row + 1) / 5.0) + padV
            let sv1 = (1.0 - CGFloat(cap.row) / 5.0) - padV

            let kTL = KeyboardLayout.screenQuadPoint(su: su0, sv: sv0)
            let kTR = KeyboardLayout.screenQuadPoint(su: su1, sv: sv0)
            let kBR = KeyboardLayout.screenQuadPoint(su: su1, sv: sv1)
            let kBL = KeyboardLayout.screenQuadPoint(su: su0, sv: sv1)

            let kPath = roundedQuadPath(tl: kTL, tr: kTR, br: kBR, bl: kBL, radius: 1.6)
            let center = CGPoint(x: (kTL.x + kTR.x + kBR.x + kBL.x) * 0.25,
                                 y: (kTL.y + kTR.y + kBR.y + kBL.y) * 0.25)
            let fill = cap.isAmberAccent ? accentColor : keyColor
            let keyBounds = kPath.boundingBoxOfPath.insetBy(dx: -2, dy: -2)
            var legendBitmap: KeyboardBitmap?
            if style.showLegends {
                let isSpace = cap.key == .space
                let legend = isSpace ? "space" : keycapLegend(cap.key)
                if !legend.isEmpty {
                    var labelCenter = center
                    if isSpace {
                        // The spacebar sits right under the cat: its legs hide the middle, and an
                        // unlabeled visible end looked like an odd blank patch beside the cat.
                        // Label the end that stays visible instead.
                        labelCenter = KeyboardLayout.screenQuadPoint(su: su0 + (su1 - su0) * 0.82, sv: (sv0 + sv1) * 0.5)
                    }
                    let textColor: NSColor
                    if cap.isAmberAccent {
                        textColor = kb.accent.luminance >= 0.45
                            ? NSColor(calibratedRed: 0.14, green: 0.14, blue: 0.16, alpha: 0.82)
                            : NSColor(calibratedRed: 0.96, green: 0.96, blue: 0.98, alpha: 0.90)
                    } else if kb.darkText {
                        textColor = NSColor(calibratedRed: 0.14, green: 0.14, blue: 0.16, alpha: 0.78)
                    } else {
                        textColor = NSColor(calibratedRed: 0.88, green: 0.90, blue: 0.92, alpha: 0.82)
                    }
                    let fontSize: CGFloat = legend.count <= 1 ? 5.2 : 4.2
                    let attrs: [NSAttributedString.Key: Any] = [
                        .font: NSFont.systemFont(ofSize: fontSize, weight: .semibold),
                        .foregroundColor: textColor
                    ]
                    let str = NSAttributedString(string: legend, attributes: attrs)
                    let size = str.size()
                    let textRect = CGRect(x: -size.width * 0.5, y: -size.height * 0.5,
                                          width: size.width, height: size.height)
                    // Keyboard faces the cat (180°), so legends read upright from the cat's seat.
                    var transform = CGAffineTransform(translationX: labelCenter.x, y: labelCenter.y).rotated(by: .pi + 0.052)
                    if style.flipped { transform = transform.scaledBy(x: -1, y: 1) }
                    legendBitmap = KeyboardBitmap(bounds: textRect.applying(transform).insetBy(dx: -2, dy: -2),
                                                  scale: style.scale) { ctx in
                        ctx.concatenate(transform)
                        NSGraphicsContext.saveGraphicsState()
                        NSGraphicsContext.current = NSGraphicsContext(cgContext: ctx, flipped: true)
                        str.draw(at: textRect.origin)
                        NSGraphicsContext.restoreGraphicsState()
                    }
                }
            }
            let restingBounds = legendBitmap.map { keyBounds.union($0.bounds) } ?? keyBounds
            let resting = KeyboardBitmap(bounds: restingBounds, scale: style.scale) { ctx in
                drawKeycap(in: ctx, path: kPath, fill: fill.cgColor, border: border)
                legendBitmap?.draw(in: ctx)
            }
            return KeyboardKeyArtwork(key: cap.key, center: center, path: kPath, fill: fill, border: border,
                                      legend: legendBitmap, resting: resting)
        }

        let idle = KeyboardBitmap(bounds: bounds, scale: style.scale) { ctx in
            chassis?.draw(in: ctx)
            for key in keys {
                drawKeyboardKey(key, in: ctx, glow: 0, glowColor: accentColor)
            }
        }
        return KeyboardArtwork(style: style, chassis: chassis, idle: idle, keys: keys,
                               deckPath: topChassis, deckStart: tl, deckEnd: br)
    }

    private static func drawKeyboardKey(_ key: KeyboardKeyArtwork, in ctx: CGContext, glow: CGFloat,
                                        glowColor: NSColor, backlight: KeyboardMarquee? = nil) {
        if backlight == nil, glow == 0, let resting = key.resting {
            resting.draw(in: ctx)
            return
        }

        let pressDepth = glow * 1.9
        let center = CGPoint(x: key.center.x, y: key.center.y + pressDepth)
        let illumination = backlight?.illumination(at: center) ?? 0
        var color = key.fill
        if let backlight, illumination > 0.015 {
            let lit = blendColor(backlight.color, .white, t: illumination * illumination * 0.5)
            color = blendColor(color, lit, t: illumination * 0.88)
        }
        if glow > 0.02 {
            color = blendColor(color, glowColor, t: glow * 0.55)
        }

        ctx.saveGState()
        ctx.translateBy(x: 0, y: pressDepth)
        if let backlight, illumination > 0.10 {
            let border = backlight.color.withAlphaComponent(illumination * 215.0 / 255.0).cgColor
            drawKeycap(in: ctx, path: key.path, fill: color.cgColor, border: border, borderWidth: 1.0)
        } else {
            drawKeycap(in: ctx, path: key.path, fill: color.cgColor, border: key.border)
        }
        if let backlight, illumination > 0.45 {
            ctx.saveGState()
            ctx.translateBy(x: key.center.x, y: key.center.y)
            ctx.scaleBy(x: 15.0, y: 10.5)
            let bloom = (illumination - 0.45) / 0.55
            drawRadialGlow(in: ctx, center: .zero, radius: 1.0,
                           color: backlight.color.withAlphaComponent(bloom * 135.0 / 255.0))
            ctx.restoreGState()
        }
        key.legend?.draw(in: ctx)
        ctx.restoreGState()
    }

    private static func drawKeycap(in ctx: CGContext, path: CGPath, fill: CGColor, border: CGColor,
                                   borderWidth: CGFloat = 0.65) {
        ctx.setFillColor(fill)
        ctx.setStrokeColor(border)
        ctx.setLineWidth(borderWidth)
        ctx.addPath(path)
        ctx.drawPath(using: .fillStroke)
    }

    private struct KeyboardMarquee {
        let phase: CGFloat
        let color: NSColor
        let start: CGPoint
        let end: CGPoint
        let dx: CGFloat
        let dy: CGFloat
        let lengthSquared: CGFloat

        init(phase: CGFloat, color: NSColor, start: CGPoint, end: CGPoint) {
            self.phase = phase
            self.color = color
            self.start = start
            self.end = end
            dx = end.x - start.x
            dy = end.y - start.y
            lengthSquared = dx * dx + dy * dy
        }

        func illumination(at center: CGPoint) -> CGFloat {
            let t = ((center.x - start.x) * dx + (center.y - start.y) * dy) / lengthSquared
            return wave(at: max(0, min(1, t)))
        }

        func wave(at t: CGFloat) -> CGFloat {
            let distance = phase - t
            return exp(-(distance < 0 ? distance + 1 : distance) / 0.125)
        }
    }

    private static func drawMarquee(_ light: KeyboardMarquee, in ctx: CGContext, clippedTo deck: CGPath) {
        ctx.saveGState()
        ctx.addPath(deck)
        ctx.clip()
        let stops = (0..<24).map { CGFloat($0) / 23 }
        let colors = stops.map { stop in
            light.color.withAlphaComponent(light.wave(at: stop) * 200.0 / 255.0).cgColor
        }
        if let band = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: colors as CFArray, locations: stops) {
            ctx.drawLinearGradient(band, start: light.start, end: light.end,
                                   options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
        }
        let head = CGPoint(x: light.start.x + light.dx * light.phase, y: light.start.y + light.dy * light.phase)
        drawRadialGlow(in: ctx, center: head, radius: 44.0,
                       color: NSColor(calibratedRed: 240.0 / 255, green: 252.0 / 255, blue: 1, alpha: 150.0 / 255))
        ctx.restoreGState()
    }

    // MARK: - Skin part mapping helpers

    /// Head-local point -> canvas, on the skin's head surface (dome / plane) or flat skull space.
    private static func headPoint(_ p: CGPoint, skull: Bool, skin: SkinSpec, head: CGPoint, physics: CatPhysics, whiteSurface: Bool = false) -> CGPoint {
        let radius = max(0, 1 - pow(p.x / 46, 2) - pow(p.y / 40, 2))
        let surface = whiteSurface ? radius * radius * (3 - 2 * radius) : sqrt(radius)
        let depth: CGFloat = skin.headSurface == .dome ? 29.6 * surface : 27.5
        var projected = skull ? p : projectHead3D(x: p.x, y: p.y, z: depth,
                                                  yawRad: physics.headYaw.value * 0.50,
                                                  pitchRad: physics.headPitch.value * 0.36).pt
        let hs = skin.shape.headScale
        projected.x *= hs; projected.y *= hs
        let c = cos(physics.headTilt.value), s = sin(physics.headTilt.value)
        return CGPoint(x: head.x + projected.x*c - projected.y*s,
                       y: head.y + projected.x*s + projected.y*c)
    }
    private static func bodyPoint(_ p: CGPoint, skin: SkinSpec, seatX: CGFloat, seatY: CGFloat, physics: CatPhysics) -> CGPoint {
        let bw = skin.shape.bodyWidth
        let lie = max(0, min(1, physics.lieIntensity.value))
        let lieS = lie * lie * (3.0 - 2.0 * lie)
        let sy = physics.bodySquash.value * (1.0 - lieS * 0.42)
        let sx = (1 + (1 - physics.bodySquash.value) * 0.55) * (1.0 + lieS * 0.03)
        let c = cos(physics.bodyTilt.value), s = sin(physics.bodyTilt.value)
        return CGPoint(x: seatX + p.x*bw*sx*c - p.y*sy*s,
                       y: seatY + p.x*bw*sx*s + p.y*sy*c)
    }
    private static func polyline(_ points: [CGPoint], closed: Bool, map: (CGPoint) -> CGPoint) -> CGMutablePath {
        let path = CGMutablePath()
        for (i, point) in points.enumerated() {
            let p = map(point)
            if i == 0 { path.move(to: p) } else { path.addLine(to: p) }
        }
        if closed { path.closeSubpath() }
        return path
    }
    /// Strokes get round caps, except tail-space strokes (bands around the tail) which are cut flat.
    private static func drawMark(in ctx: CGContext, _ mark: SkinMark, cap: CGLineCap = .round, map: (CGPoint) -> CGPoint) {
        ctx.saveGState()
        let path = polyline(mark.points, closed: !mark.stroke, map: map)
        let color = mark.color.ns
        if !mark.stroke {
            path.closeSubpath(); ctx.setFillColor(color.cgColor); ctx.addPath(path); ctx.fillPath()
        } else {
            ctx.setStrokeColor(color.cgColor); ctx.setLineWidth(mark.width)
            ctx.setLineCap(cap); ctx.setLineJoin(.round); ctx.addPath(path); ctx.strokePath()
        }
        ctx.restoreGState()
    }
    private static func drawRegion(in ctx: CGContext, _ region: SkinRegion, map: (CGPoint) -> CGPoint) {
        ctx.setFillColor(region.fill.ns.cgColor)
        ctx.addPath(polyline(region.flat, closed: true, map: map))
        ctx.fillPath()
    }

    // MARK: - Tail

    private struct TailCurve {
        let root: CGPoint, c1: CGPoint, c2: CGPoint, tip: CGPoint, thickness: CGFloat
        /// Tail space: x = 0 (root) .. 100 (tip) along the curve, y = offset along the left-hand normal.
        func at(_ p: CGPoint) -> CGPoint {
            let t = max(0, min(1, p.x / 100))
            let u = 1-t
            let q = CGPoint(x: u*u*u*root.x + 3*u*u*t*c1.x + 3*u*t*t*c2.x + t*t*t*tip.x,
                            y: u*u*u*root.y + 3*u*u*t*c1.y + 3*u*t*t*c2.y + t*t*t*tip.y)
            let dx = 3*u*u*(c1.x-root.x)+6*u*t*(c2.x-c1.x)+3*t*t*(tip.x-c2.x)
            let dy = 3*u*u*(c1.y-root.y)+6*u*t*(c2.y-c1.y)+3*t*t*(tip.y-c2.y)
            let length = max(0.001, hypot(dx,dy)), n = p.y * thickness
            return CGPoint(x: q.x + -dy/length*n, y: q.y + dx/length*n)
        }
    }

    static func tailCurve(_ physics: CatPhysics)
        -> (root: CGPoint, control1: CGPoint, control2: CGPoint, tip: CGPoint) {
        let seatX = CatPhysics.seatAnchor.x + physics.bodyShiftX.value
        let scruff = max(0, min(1, physics.scruffDrag.value))
        let lie = max(0, min(1, physics.lieIntensity.value))
        let lieS = lie * lie * (3.0 - 2.0 * lie)
        let seatY = CatPhysics.seatAnchor.y - scruff * 22.0 + lieS * 10.0
        let c = tailCurve(seatX: seatX, seatY: seatY, physics: physics, skin: CatSettings.shared.activeSkin)
        return (c.root, c.c1, c.c2, c.tip)
    }

    private static func tailCurve(seatX: CGFloat, seatY: CGFloat, physics: CatPhysics, skin: SkinSpec) -> TailCurve {
        let p = physics.tailPhase
        let hunt = max(0, min(1, physics.huntIntensity.value))
        let agility = max(0, min(1, physics.tailAgility.value))
        let lie = max(0, min(1, physics.lieIntensity.value))
        let lieS = lie * lie * (3.0 - 2.0 * lie)
        let wag1 = sin(p) * (8.0 + hunt * 5.5 + agility * 4.0)
        let wag2 = cos(p * 1.3) * (6.0 + hunt * 4.5 + agility * 3.5)
        // Tail drops lower & swishes tautly when stalking/hunting!
        let huntDrop = hunt * 14.0
        let bw = skin.shape.bodyWidth, tl = skin.shape.tailLength
        let shift: CGFloat = bw == 1 ? 0 : 34 * bw - 34   // tail root stays on the (wider/narrower) hip

        // Signature low sweep out to the right, then playful upward curl at the tip!
        let baseRoot = CGPoint(x: seatX + 34 + shift, y: seatY - 6)
        let reach = max(0, min(1, physics.tailTyping.value))
        let target = physics.tailTip.point
        let flickScale = (1.0 - reach) * (1.0 - lieS)
        let fx = physics.tailFlick.point.x * flickScale
        let fy = physics.tailFlick.point.y * flickScale
        let curl = physics.tailCurl.value * flickScale
        var baseC1 = CGPoint(x: seatX + 64 + shift + 12 * reach + fx * 0.25, y: seatY + 2 + wag1 * 0.35 + huntDrop * 0.4 - 18 * reach + fy * 0.22 + curl * 0.35)
        var idleC2 = CGPoint(x: seatX + 66 + wag2 * 0.4 + shift + fx * 0.65 - curl * 0.45, y: seatY - 26 + wag1 * 0.7 + huntDrop + fy * 0.60 - curl * 0.55)
        var idleTip = CGPoint(x: seatX + 91 + wag2 * 0.5 + shift + fx, y: seatY - 30 + wag1 * 0.85 + huntDrop + fy)
        if tl != 1 {
            baseC1 = CGPoint(x: around(baseC1.x, baseRoot.x, tl), y: around(baseC1.y, baseRoot.y, tl))
            idleC2 = CGPoint(x: around(idleC2.x, baseRoot.x, tl), y: around(idleC2.y, baseRoot.y, tl))
            idleTip = CGPoint(x: around(idleTip.x, baseRoot.x, tl), y: around(idleTip.y, baseRoot.y, tl))
        }
        let baseC2 = CGPoint(x: idleC2.x + (target.x + 24 - idleC2.x) * reach, y: idleC2.y + (target.y - 30 - idleC2.y) * reach)
        let baseTip = CGPoint(x: idleTip.x + (target.x - idleTip.x) * reach, y: idleTip.y + (target.y - idleTip.y) * reach)

        // When curling up to sleep, tail sweeps smoothly around the front to wrap cozily around the cat ball!
        let sleepWag = sin(p * 0.6) * 2.0
        let wrapRoot = CGPoint(x: seatX + 40 + shift, y: seatY - 2)
        let wrapC1 = CGPoint(x: seatX + 54 + shift, y: seatY + 13)
        let wrapC2 = CGPoint(x: seatX + 14, y: seatY + 17)
        let wrapTip = CGPoint(x: seatX - 28, y: seatY + 8 + sleepWag)

        let root = CGPoint(x: baseRoot.x + (wrapRoot.x - baseRoot.x) * lieS, y: baseRoot.y + (wrapRoot.y - baseRoot.y) * lieS)
        let c1 = CGPoint(x: baseC1.x + (wrapC1.x - baseC1.x) * lieS, y: baseC1.y + (wrapC1.y - baseC1.y) * lieS)
        let c2 = CGPoint(x: baseC2.x + (wrapC2.x - baseC2.x) * lieS, y: baseC2.y + (wrapC2.y - baseC2.y) * lieS)
        let tip = CGPoint(x: baseTip.x + (wrapTip.x - baseTip.x) * lieS, y: baseTip.y + (wrapTip.y - baseTip.y) * lieS)
        return TailCurve(root: root, c1: c1, c2: c2, tip: tip, thickness: skin.shape.tailThickness)
    }

    // MARK: - Monster Hunter Dazed Cat Special Renderer (renderStyle == .dazed)

    private static func dazedColor(_ hex: Int, alpha: CGFloat = 1.0) -> CGColor {
        let r = CGFloat((hex >> 16) & 0xFF) / 255.0
        let g = CGFloat((hex >> 8) & 0xFF) / 255.0
        let b = CGFloat(hex & 0xFF) / 255.0
        return NSColor(calibratedRed: r, green: g, blue: b, alpha: alpha).cgColor
    }

    private static func drawDazedPaw(in ctx: CGContext, rect: CGRect) {
        ctx.saveGState()
        let path = CGPath(ellipseIn: rect, transform: nil)
        ctx.addPath(path)
        ctx.clip()
        let cs = CGColorSpaceCreateDeviceRGB()
        if let grad = CGGradient(colorsSpace: cs, colors: [dazedColor(0xFFF1CD), dazedColor(0xCCAC7F)] as CFArray, locations: [0, 1]) {
            ctx.drawLinearGradient(grad, start: CGPoint(x: rect.midX, y: rect.minY), end: CGPoint(x: rect.midX, y: rect.maxY), options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
        }
        ctx.restoreGState()
        ctx.saveGState()
        ctx.setStrokeColor(dazedColor(0x7E634A, alpha: 170.0 / 255.0))
        ctx.setLineWidth(0.9)
        ctx.strokeEllipse(in: rect)
        ctx.restoreGState()
    }

    private static func drawDazedSword(in ctx: CGContext, seatX: CGFloat, seatY: CGFloat, physics: CatPhysics) {
        ctx.saveGState()
        ctx.translateBy(x: seatX, y: seatY + (1.0 - physics.bodySquash.value) * 36.0)
        ctx.rotate(by: physics.bodyTilt.value)

        let blade = CGMutablePath()
        blade.move(to: CGPoint(x: 38.0, y: -96.0))
        blade.addCurve(to: CGPoint(x: -65.0, y: -38.0), control1: CGPoint(x: 7.0, y: -61.0), control2: CGPoint(x: -31.0, y: -33.0))
        blade.addCurve(to: CGPoint(x: -37.0, y: -25.0), control1: CGPoint(x: -62.0, y: -24.0), control2: CGPoint(x: -51.0, y: -21.0))
        blade.addCurve(to: CGPoint(x: 50.0, y: -84.0), control1: CGPoint(x: -5.0, y: -33.0), control2: CGPoint(x: 27.0, y: -60.0))
        blade.closeSubpath()

        let cs = CGColorSpaceCreateDeviceRGB()
        ctx.saveGState()
        ctx.addPath(blade)
        ctx.clip()
        if let steel = CGGradient(colorsSpace: cs, colors: [dazedColor(0x8395B0), dazedColor(0xDDE7F2)] as CFArray, locations: [0, 1]) {
            ctx.drawLinearGradient(steel, start: CGPoint(x: -46.0, y: -51.0), end: CGPoint(x: -29.0, y: -22.0), options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
        }
        ctx.restoreGState()

        ctx.setStrokeColor(dazedColor(0x232638))
        ctx.setLineWidth(3.6)
        ctx.setLineJoin(.round)
        ctx.addPath(blade)
        ctx.strokePath()

        ctx.setStrokeColor(dazedColor(0xF3F7FB))
        ctx.setLineWidth(2.1)
        ctx.setLineCap(.round)
        ctx.move(to: CGPoint(x: -59.0, y: -33.5))
        ctx.addCurve(to: CGPoint(x: 43.0, y: -87.0), control1: CGPoint(x: -34.0, y: -24.0), control2: CGPoint(x: 12.0, y: -53.0))
        ctx.strokePath()

        ctx.translateBy(x: 44.0, y: -90.0)
        ctx.rotate(by: 44.0 * .pi / 180.0)

        let grip = CGPath(roundedRect: CGRect(x: -7.5, y: -32.0, width: 15.0, height: 32.0), cornerWidth: 3.6, cornerHeight: 3.6, transform: nil)
        ctx.setFillColor(dazedColor(0x58617D))
        ctx.addPath(grip)
        ctx.fillPath()
        ctx.saveGState()
        ctx.addPath(grip)
        ctx.clip()
        ctx.setFillColor(dazedColor(0xB5BED0))
        for y in [-27.0, -19.0, -11.0] as [CGFloat] {
            let band = CGMutablePath()
            band.move(to: CGPoint(x: -7.5, y: y - 2.0))
            band.addLine(to: CGPoint(x: 7.5, y: y + 1.0))
            band.addLine(to: CGPoint(x: 7.5, y: y + 4.3))
            band.addLine(to: CGPoint(x: -7.5, y: y + 1.3))
            band.closeSubpath()
            ctx.addPath(band)
            ctx.fillPath()
        }
        ctx.restoreGState()
        ctx.setStrokeColor(dazedColor(0x232638))
        ctx.setLineWidth(3.6)
        ctx.addPath(grip)
        ctx.strokePath()

        let guardPath = CGPath(roundedRect: CGRect(x: -13.5, y: -3.8, width: 27.0, height: 7.6), cornerWidth: 2.5, cornerHeight: 2.5, transform: nil)
        ctx.setFillColor(dazedColor(0xE2C58B))
        ctx.addPath(guardPath)
        ctx.fillPath()
        ctx.setStrokeColor(dazedColor(0x232638))
        ctx.setLineWidth(3.6)
        ctx.addPath(guardPath)
        ctx.strokePath()

        ctx.restoreGState()
    }

    private static func drawDazedEar(in ctx: CGContext, sign: CGFloat, yawRad: CGFloat, pitchRad: CGFloat, fold: CGFloat, twitch: CGFloat) {
        let foldAngle = sign * fold * 0.34 + twitch
        let tipDx = sin(foldAngle) * 37.0
        let tipDy = (1.0 - cos(foldAngle)) * 37.0
        func proj(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat) -> CGPoint {
            projectHead3D(x: sign * x + tipDx * w, y: y + tipDy * w, z: -3.0 * w, yawRad: yawRad, pitchRad: pitchRad).pt
        }
        let innerBase = proj(5.0, -25.0, 0.0)
        let tip = proj(40.0, -63.0, 1.0)
        let outerBase = proj(42.5, -5.0, 0.0)
        let ear = CGMutablePath()
        ear.move(to: innerBase)
        ear.addCurve(to: tip, control1: proj(13.0, -46.0, 0.30), control2: proj(31.0, -62.0, 0.90))
        ear.addCurve(to: outerBase, control1: proj(54.0, -66.0, 0.95), control2: proj(57.0, -34.0, 0.40))
        ear.closeSubpath()

        ctx.saveGState()
        ctx.addPath(ear)
        ctx.clip()
        let cs = CGColorSpaceCreateDeviceRGB()
        if let grad = CGGradient(colorsSpace: cs, colors: [dazedColor(0x777FBD), dazedColor(0x4D5892)] as CFArray, locations: [0, 1]) {
            ctx.drawLinearGradient(grad, start: tip, end: outerBase, options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
        }
        ctx.restoreGState()
    }

    private static func drawDazedSilhouette(in ctx: CGContext, seatX: CGFloat, seatY: CGFloat, head: CGPoint, physics: CatPhysics) {
        let cs = CGColorSpaceCreateDeviceRGB()
        ctx.saveGState()
        ctx.translateBy(x: seatX, y: seatY)
        ctx.rotate(by: physics.bodyTilt.value)
        let squash = physics.bodySquash.value
        ctx.scaleBy(x: 1.0 + (1.0 - squash) * 0.55, y: squash)

        drawDazedPaw(in: ctx, rect: CGRect(x: -34.0, y: -2.0, width: 19.0, height: 18.0))
        if physics.hindFootActive.value < 0.35 {
            drawDazedPaw(in: ctx, rect: CGRect(x: 15.0, y: -2.0, width: 19.0, height: 18.0))
        }

        let belly = CGMutablePath()
        belly.move(to: CGPoint(x: -42.0, y: -19.0))
        belly.addCurve(to: CGPoint(x: 0.0, y: 11.5), control1: CGPoint(x: -46.0, y: -5.0), control2: CGPoint(x: -41.0, y: 11.5))
        belly.addCurve(to: CGPoint(x: 42.0, y: -19.0), control1: CGPoint(x: 41.0, y: 11.5), control2: CGPoint(x: 46.0, y: -5.0))
        belly.closeSubpath()
        ctx.saveGState()
        ctx.addPath(belly)
        ctx.clip()
        if let g = CGGradient(colorsSpace: cs, colors: [dazedColor(0xF4DFB8), dazedColor(0xC8A77A)] as CFArray, locations: [0, 1]) {
            ctx.drawLinearGradient(g, start: CGPoint(x: 0.0, y: -16.0), end: CGPoint(x: 0.0, y: 12.0), options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
        }
        ctx.restoreGState()

        let tunic = CGMutablePath()
        tunic.move(to: CGPoint(x: -21.0, y: -65.0))
        tunic.addCurve(to: CGPoint(x: -44.0, y: -17.0), control1: CGPoint(x: -34.0, y: -56.0), control2: CGPoint(x: -44.0, y: -35.0))
        tunic.addCurve(to: CGPoint(x: 44.0, y: -17.0), control1: CGPoint(x: -37.0, y: -2.0), control2: CGPoint(x: 37.0, y: -2.0))
        tunic.addCurve(to: CGPoint(x: 21.0, y: -65.0), control1: CGPoint(x: 44.0, y: -35.0), control2: CGPoint(x: 34.0, y: -56.0))
        tunic.closeSubpath()
        ctx.saveGState()
        ctx.addPath(tunic)
        ctx.clip()
        if let g = CGGradient(colorsSpace: cs, colors: [dazedColor(0x555F9B), dazedColor(0x252E58)] as CFArray, locations: [0, 1]) {
            ctx.drawLinearGradient(g, start: CGPoint(x: -16.0, y: -65.0), end: CGPoint(x: 12.0, y: -5.0), options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
        }
        ctx.restoreGState()

        ctx.setStrokeColor(dazedColor(0x7C86BC, alpha: 155.0 / 255.0))
        ctx.setLineWidth(1.1)
        ctx.move(to: CGPoint(x: -39.0, y: -15.0))
        ctx.addCurve(to: CGPoint(x: 39.0, y: -15.0), control1: CGPoint(x: -28.0, y: -6.0), control2: CGPoint(x: 28.0, y: -6.0))
        ctx.strokePath()
        ctx.restoreGState()

        ctx.saveGState()
        ctx.translateBy(x: head.x, y: head.y)
        ctx.rotate(by: physics.headTilt.value)
        let hood = CGMutablePath()
        hood.move(to: CGPoint(x: 0.0, y: -33.0))
        hood.addCurve(to: CGPoint(x: 48.0, y: 9.0), control1: CGPoint(x: 28.0, y: -35.0), control2: CGPoint(x: 48.0, y: -16.0))
        hood.addCurve(to: CGPoint(x: 0.0, y: 41.0), control1: CGPoint(x: 48.0, y: 32.0), control2: CGPoint(x: 25.0, y: 41.0))
        hood.addCurve(to: CGPoint(x: -48.0, y: 9.0), control1: CGPoint(x: -25.0, y: 41.0), control2: CGPoint(x: -48.0, y: 32.0))
        hood.addCurve(to: CGPoint(x: 0.0, y: -33.0), control1: CGPoint(x: -48.0, y: -16.0), control2: CGPoint(x: -28.0, y: -35.0))
        hood.closeSubpath()
        ctx.addPath(hood)
        ctx.clip()
        if let g = CGGradient(colorsSpace: cs, colors: [dazedColor(0x6871B4), dazedColor(0x2F386D)] as CFArray, locations: [0, 1]) {
            ctx.drawLinearGradient(g, start: CGPoint(x: -16.0, y: -35.0), end: CGPoint(x: 15.0, y: 42.0), options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
        }
        ctx.restoreGState()
    }

    private static func drawDazedFace(in ctx: CGContext, physics: CatPhysics, eyeTheme: EyeColorTheme, yawRad: CGFloat, pitchRad: CGFloat, scruffStartle: CGFloat, scruffWide: CGFloat) {
        let cs = CGColorSpaceCreateDeviceRGB()
        let face = projectHead3D(x: 0.0, y: 4.0, z: 22.0, yawRad: yawRad * 0.72, pitchRad: pitchRad * 0.78).pt
        ctx.saveGState()
        ctx.translateBy(x: face.x, y: face.y)
        ctx.scaleBy(x: cos(yawRad), y: cos(pitchRad))

        let opening = CGMutablePath()
        opening.move(to: CGPoint(x: 0.0, y: -22.0))
        opening.addCurve(to: CGPoint(x: 32.0, y: 8.0), control1: CGPoint(x: 17.0, y: -23.0), control2: CGPoint(x: 32.0, y: -9.0))
        opening.addCurve(to: CGPoint(x: 0.0, y: 27.5), control1: CGPoint(x: 32.0, y: 22.0), control2: CGPoint(x: 17.0, y: 27.5))
        opening.addCurve(to: CGPoint(x: -32.0, y: 8.0), control1: CGPoint(x: -17.0, y: 27.5), control2: CGPoint(x: -32.0, y: 22.0))
        opening.addCurve(to: CGPoint(x: 0.0, y: -22.0), control1: CGPoint(x: -32.0, y: -9.0), control2: CGPoint(x: -17.0, y: -23.0))
        opening.closeSubpath()

        ctx.saveGState()
        ctx.addPath(opening)
        ctx.clip()
        if let g = CGGradient(colorsSpace: cs, colors: [dazedColor(0xFFF4D4), dazedColor(0xDDBF91)] as CFArray, locations: [0, 1]) {
            ctx.drawLinearGradient(g, start: CGPoint(x: -7.0, y: -23.0), end: CGPoint(x: 8.0, y: 29.0), options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
        }
        ctx.restoreGState()

        ctx.setStrokeColor(dazedColor(0x34355D))
        ctx.setLineWidth(1.9)
        ctx.addPath(opening)
        ctx.strokePath()

        // Soft colorpoint muzzle
        ctx.saveGState()
        ctx.translateBy(x: 0.0, y: 11.0)
        ctx.scaleBy(x: 1.0, y: 34.0 / 42.0)
        if let g = CGGradient(colorsSpace: cs, colors: [
            dazedColor(0x8D5B44, alpha: 220.0 / 255.0),
            dazedColor(0x8D5B44, alpha: 155.0 / 255.0),
            dazedColor(0x8D5B44, alpha: 5.0 / 255.0),
            dazedColor(0x8D5B44, alpha: 0.0)
        ] as CFArray, locations: [0.0, 0.62, 0.83, 1.0]) {
            ctx.drawRadialGradient(g, startCenter: .zero, startRadius: 0, endCenter: .zero, endRadius: 21.0, options: [])
        }
        ctx.restoreGState()

        ctx.setFillColor(dazedColor(0xCF8173, alpha: 94.0 / 255.0))
        ctx.fillEllipse(in: CGRect(x: -23.0, y: 10.0, width: 9.0, height: 4.0))
        ctx.fillEllipse(in: CGRect(x: 14.0, y: 10.0, width: 9.0, height: 4.0))

        let ink = dazedColor(0x282333)
        ctx.setStrokeColor(ink)
        ctx.setLineWidth(1.7)
        ctx.setLineCap(.round)
        ctx.setLineJoin(.round)
        ctx.move(to: CGPoint(x: -6.5, y: 12.0))
        ctx.addCurve(to: CGPoint(x: 0.0, y: 13.4), control1: CGPoint(x: -5.9, y: 17.0), control2: CGPoint(x: -1.8, y: 17.5))
        ctx.addCurve(to: CGPoint(x: 6.5, y: 12.0), control1: CGPoint(x: 1.8, y: 17.5), control2: CGPoint(x: 5.9, y: 17.0))
        ctx.strokePath()

        ctx.setFillColor(ink)
        ctx.fillEllipse(in: CGRect(x: -1.9, y: 10.1, width: 3.8, height: 2.8))

        let happy = physics.isHappyClosedEyes
        let squint = physics.isBlissfulSquint
        if happy || squint {
            for x in [-11.8, 11.8] as [CGFloat] {
                ctx.move(to: CGPoint(x: x - 7.2, y: 2.0))
                ctx.addQuadCurve(to: CGPoint(x: x + 7.2, y: 2.0), control: CGPoint(x: x, y: happy ? 7.0 : 4.0))
                ctx.strokePath()
            }
            ctx.restoreGState()
            return
        }

        let open = 1.0 - max(0.0, min(1.0, max(physics.effectiveEyeClosure, scruffStartle * 0.44)))
        if open <= 0.025 {
            ctx.restoreGState()
            return
        }
        let hunt = max(0.0, min(1.0, max(physics.huntIntensity.value, scruffWide * 0.94)))
        let gaze = physics.eyeGaze.point
        let gazeX = max(-1.0, min(1.0, gaze.x)) * (1.35 - hunt * 0.65)
        let gazeY = max(-1.0, min(1.0, gaze.y)) * (1.1 - hunt * 0.55)
        let radius = 8.5 + hunt * 1.0
        let pupilRadius = 6.25 + hunt * 1.35
        let irisCol = eyeTheme.primaryColor.blended(withFraction: 0.80, of: NSColor(calibratedRed: 1.0, green: 248.0/255.0, blue: 229.0/255.0, alpha: 1.0))?.cgColor ?? dazedColor(0xFFF8E5)

        for x in [-11.8, 11.8] as [CGFloat] {
            ctx.saveGState()
            ctx.translateBy(x: x, y: 1.0)
            ctx.scaleBy(x: 1.0, y: open)
            ctx.setFillColor(ink)
            ctx.fillEllipse(in: CGRect(x: -radius, y: -radius, width: radius * 2, height: radius * 2))
            let ir = radius - 1.25
            ctx.setFillColor(irisCol)
            ctx.fillEllipse(in: CGRect(x: -ir, y: -ir, width: ir * 2, height: ir * 2))
            ctx.setFillColor(dazedColor(0x191825))
            ctx.fillEllipse(in: CGRect(x: gazeX - pupilRadius, y: gazeY - pupilRadius, width: pupilRadius * 2, height: pupilRadius * 2))
            if hunt > 0.25 {
                let shine = 1.1 + hunt * 0.6
                ctx.setFillColor(dazedColor(0xFFF9EA))
                ctx.fillEllipse(in: CGRect(x: gazeX - 3.4 - shine, y: gazeY - 4.2 - shine, width: shine * 2, height: shine * 2))
            }
            ctx.restoreGState()
        }
        ctx.restoreGState()
    }

    private static func drawDazedArm(in ctx: CGContext, arm: CGPath, left: [CGPoint], right: [CGPoint], paw: CGRect) {
        ctx.saveGState()
        ctx.setFillColor(dazedColor(0x465189))
        ctx.addPath(arm)
        ctx.fillPath()

        let sleeveLength: CGFloat = 15.0
        var distance: CGFloat = 0.0
        for i in 1..<left.count {
            let dx = (left[i].x + right[i].x - left[i - 1].x - right[i - 1].x) * 0.5
            let dy = (left[i].y + right[i].y - left[i - 1].y - right[i - 1].y) * 0.5
            let segment = hypot(dx, dy)
            if distance + segment < sleeveLength && i < left.count - 1 {
                distance += segment
                continue
            }
            let t = max(0.0, min(1.0, (sleeveLength - distance) / max(segment, 0.001)))
            func interp(_ a: CGPoint, _ b: CGPoint, _ f: CGFloat) -> CGPoint {
                CGPoint(x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f)
            }
            func offsetAlong(_ pt: CGPoint, _ off: CGFloat) -> CGPoint {
                let sc = off / max(segment, 0.001)
                return CGPoint(x: pt.x + dx * sc, y: pt.y + dy * sc)
            }
            let leftCuff = interp(left[i - 1], left[i], t)
            let rightCuff = interp(right[i - 1], right[i], t)
            let leftLip = interp(rightCuff, leftCuff, 1.23)
            let rightLip = interp(leftCuff, rightCuff, 1.23)
            let leftFront = offsetAlong(leftLip, 4.0)
            let rightFront = offsetAlong(rightLip, 4.0)

            let flare = CGMutablePath()
            flare.move(to: offsetAlong(leftCuff, -8.0))
            flare.addLine(to: leftLip)
            flare.addCurve(to: rightLip, control1: leftFront, control2: rightFront)
            flare.addLine(to: offsetAlong(rightCuff, -8.0))
            flare.closeSubpath()
            ctx.setFillColor(dazedColor(0x465189))
            ctx.addPath(flare)
            ctx.fillPath()

            let opening = CGMutablePath()
            opening.move(to: leftLip)
            opening.addCurve(to: rightLip, control1: leftFront, control2: rightFront)
            opening.addCurve(to: leftLip, control1: offsetAlong(rightLip, -3.5), control2: offsetAlong(leftLip, -3.5))
            opening.closeSubpath()
            ctx.setFillColor(dazedColor(0x252D54))
            ctx.addPath(opening)
            ctx.fillPath()

            let forearm = CGMutablePath()
            forearm.move(to: leftCuff)
            for k in i..<left.count { forearm.addLine(to: left[k]) }
            for k in stride(from: right.count - 1, through: i, by: -1) { forearm.addLine(to: right[k]) }
            forearm.addLine(to: rightCuff)
            forearm.closeSubpath()
            ctx.setFillColor(dazedColor(0xE3C99F))
            ctx.addPath(forearm)
            ctx.fillPath()

            drawDazedPaw(in: ctx, rect: paw)

            ctx.setStrokeColor(dazedColor(0x8790C8))
            ctx.setLineWidth(1.25)
            ctx.setLineCap(.round)
            ctx.move(to: leftLip)
            ctx.addCurve(to: rightLip, control1: leftFront, control2: rightFront)
            ctx.strokePath()
            break
        }
        ctx.restoreGState()
    }

    private static func drawTail(in ctx: CGContext, seatX: CGFloat, seatY: CGFloat, physics: CatPhysics, skin: SkinSpec, outlineOnly: Bool = false) {
        let curve = tailCurve(seatX: seatX, seatY: seatY, physics: physics, skin: skin)
        let width = (skin.renderStyle == .dazed) ? 13.0 : (build(skin).tailWidth * skin.shape.tailThickness)
        let lie = max(0, min(1, physics.lieIntensity.value))
        let lieS = lie * lie * (3.0 - 2.0 * lie)

        ctx.saveGState()
        if outlineOnly {
            ctx.setStrokeColor(blackOutlineColor.cgColor)
            ctx.setLineWidth(width + blackOutlineWidth * 2.0)
            ctx.setLineCap(.round)
            ctx.setLineJoin(.round)
            ctx.move(to: curve.root)
            ctx.addCurve(to: curve.tip, control1: curve.c1, control2: curve.c2)
            ctx.strokePath()
            ctx.restoreGState()
            return
        }
        ctx.setStrokeColor(skin.palette.tail.ns.cgColor)
        ctx.setLineWidth(width)
        ctx.setLineCap(.round)
        ctx.setLineJoin(.round)
        ctx.move(to: curve.root)
        ctx.addCurve(to: curve.tip, control1: curve.c1, control2: curve.c2)
        let tailLine = ctx.path
        ctx.strokePath()
        // Crisp upper separation rim on wrapped sleeping tail so it stands out cleanly against the curled torso!
        if lieS > 0.35 {
            let rAlpha = min(1.0, (lieS - 0.35) / 0.45) * 0.72
            ctx.saveGState()
            ctx.setStrokeColor(skin.palette.crease.withAlpha(rAlpha).cgColor)
            ctx.setLineWidth(1.45)
            ctx.setLineCap(.round)
            ctx.move(to: CGPoint(x: curve.root.x - 4, y: curve.root.y - 3))
            ctx.addCurve(
                to: CGPoint(x: curve.tip.x + 2, y: curve.tip.y - 4.5),
                control1: CGPoint(x: curve.c1.x - 6, y: curve.c1.y - 5.5),
                control2: CGPoint(x: curve.c2.x, y: curve.c2.y - 5.5)
            )
            ctx.strokePath()
            ctx.restoreGState()
        }
        if skin.hasPartArt(.tail) || skin.palette.tailTip != nil, let line = tailLine {
            // Everything below lands only on the tail's own pixels.
            ctx.saveGState()
            ctx.addPath(line.copy(strokingWithWidth: width, lineCap: .round, lineJoin: .round, miterLimit: 10))
            ctx.clip()
            let map: (CGPoint) -> CGPoint = { curve.at($0) }
            for region in skin.regions where region.space == .tail { drawRegion(in: ctx, region, map: map) }
            if let tipColor = skin.palette.tailTip {
                // Last 22% of the tail: de Casteljau split at t = 0.78, stroked with the tail width.
                let t: CGFloat = 0.78, u = 1 - t
                func lerp(_ a: CGPoint, _ b: CGPoint) -> CGPoint { CGPoint(x: u*a.x + t*b.x, y: u*a.y + t*b.y) }
                let a = lerp(curve.root, curve.c1), b = lerp(curve.c1, curve.c2), q = lerp(curve.c2, curve.tip)
                let d = lerp(a, b), e = lerp(b, q), s = lerp(d, e)
                ctx.setStrokeColor(tipColor.ns.cgColor)
                ctx.setLineWidth(width + 2)
                ctx.setLineCap(.round)
                ctx.move(to: s)
                ctx.addCurve(to: curve.tip, control1: e, control2: q)
                ctx.strokePath()
            }
            for mark in skin.marks where mark.space == .tail { drawMark(in: ctx, mark, cap: .butt, map: map) }
            ctx.restoreGState()
        }
        ctx.restoreGState()
    }

    // MARK: - Unified C1-Continuous Cat Silhouette (Crown -> Cheeks -> Plush Neck -> Pear Hips)

    private static func drawUnifiedSilhouette(
        in ctx: CGContext,
        seatX: CGFloat,
        seatY: CGFloat,
        headCenter: CGPoint,
        breath: CGFloat,
        physics: CatPhysics,
        skin: SkinSpec,
        outlineOnly: Bool = false
    ) {
        if skin.renderStyle == .dazed {
            if !outlineOnly { drawDazedSilhouette(in: ctx, seatX: seatX, seatY: seatY, head: headCenter, physics: physics) }
            return
        }
        let bd = build(skin)
        let pal = skin.palette
        let yaw = physics.headYaw.value
        let pitch = physics.headPitch.value
        let hTilt = physics.headTilt.value
        let bTilt = physics.bodyTilt.value
        let hs = skin.shape.headScale, bw = skin.shape.bodyWidth

        let cH = cos(hTilt), sH = sin(hTilt)
        func H(_ lx: CGFloat, _ ly: CGFloat) -> CGPoint {
            let x = lx * hs, y = ly * hs
            return CGPoint(
                x: headCenter.x + x * cH - y * sH,
                y: headCenter.y + x * sH + y * cH
            )
        }

        let cB = cos(bTilt), sB = sin(bTilt)
        let lie = max(0, min(1, physics.lieIntensity.value))
        let lieS = lie * lie * (3.0 - 2.0 * lie)
        let sy = physics.bodySquash.value * (1.0 - lieS * 0.42)
        let sx = (1.0 + (1.0 - physics.bodySquash.value) * 0.55) * (1.0 + lieS * 0.03)
        func B(_ lx: CGFloat, _ ly: CGFloat) -> CGPoint {
            let rx = lx * bw * sx
            let ry = ly * sy
            return CGPoint(
                x: seatX + rx * cB - ry * sB,
                y: seatY + rx * sB + ry * cB
            )
        }

        let cheekShift = yaw * 3.0
        let crownDrop = pitch * 2.0
        let cheekHalfW: CGFloat = bd.cheekHalfW * skin.shape.cheekFullness
        let crownCtrlW: CGFloat = bd.crownCtrlW
        let crownBaseY: CGFloat = bd.crownBaseY
        let cheekY: CGFloat = bd.cheekY
        let neckPinchX: CGFloat = bd.neckPinchX
        let neckCtrlY: CGFloat = bd.neckCtrlY
        let hipHalfW: CGFloat = bd.hipHalfW
        let waistCtrlW: CGFloat = bd.waistCtrlW
        let waistCtrlY: CGFloat = bd.waistCtrlY
        let botOuterW: CGFloat = bd.botOuterW
        let botInnerW: CGFloat = bd.botInnerW
        let botHalfW: CGFloat = bd.botHalfW
        let leftCheekX: CGFloat = -cheekHalfW + cheekShift * 0.4
        let rightCheekX: CGFloat = cheekHalfW + cheekShift * 0.4

        // ONE single tangent-continuous closed cubic Bezier path — mathematically impossible to form any ledge or protrusion!
        let crown  = H(cheekShift * 0.2, crownBaseY + crownDrop)
        let rCheek = H(rightCheekX, cheekY)
        let rHip   = B(hipHalfW, -14)
        let rBot   = B(botHalfW, 12)
        let lBot   = B(-botHalfW, 12)
        let lHip   = B(-hipHalfW, -14)
        let lCheek = H(leftCheekX, cheekY)

        let cheekCtrlTopY: CGFloat = bd.cheekCtrlTopY
        let nw = skin.shape.neckWidth
        let neckCenter = cheekShift * 0.4
        let rNeckX = neckCenter + (rightCheekX - neckPinchX - neckCenter) * nw
        let lNeckX = neckCenter + (leftCheekX + neckPinchX - neckCenter) * nw
        let neckWaistW = waistCtrlW * (1.0 + (nw - 1.0) * 0.32)
        let path = CGMutablePath()
        path.move(to: crown)
        path.addCurve(to: rCheek, control1: H(crownCtrlW + cheekShift * 0.3, crownBaseY + crownDrop), control2: H(rightCheekX + 1.5, cheekCtrlTopY))
        path.addCurve(to: rHip,   control1: H(rNeckX, neckCtrlY), control2: B(neckWaistW, waistCtrlY + breath * 0.5))
        path.addCurve(to: rBot,   control1: B(botOuterW, 5), control2: B(botInnerW, 12))
        path.addLine(to: lBot)
        path.addCurve(to: lHip,   control1: B(-botInnerW, 12), control2: B(-botOuterW, 5))
        path.addCurve(to: lCheek, control1: B(-neckWaistW, waistCtrlY + breath * 0.5), control2: H(lNeckX, neckCtrlY))
        path.addCurve(to: crown,  control1: H(leftCheekX - 1.5, cheekCtrlTopY), control2: H(-crownCtrlW + cheekShift * 0.3, crownBaseY + crownDrop))
        path.closeSubpath()

        let stagger = skin.shape.pawStagger
        let hindW: CGFloat = bd.hindW
        let leftHindX: CGFloat = bw == 1 ? bd.hindLeftX : (bd.hindLeftX + hindW * 0.5) * bw - hindW * 0.5
        let rightHindX: CGFloat = bw == 1 ? bd.hindRightX : (bd.hindRightX + hindW * 0.5) * bw - hindW * 0.5
        let leftHindY: CGFloat = bd.hindLeftY
        let leftHindH: CGFloat = bd.hindLeftH
        let rightHindY: CGFloat = bd.hindLeftY + (bd.hindStaggerY - bd.hindLeftY) * stagger
        let rightHindH: CGFloat = bd.hindLeftH + (bd.hindStaggerH - bd.hindLeftH) * stagger
        let rightTucked = physics.hindFootActive.value < 0.35

        if outlineOnly {
            ctx.saveGState()
            ctx.setStrokeColor(blackOutlineColor.cgColor)
            ctx.setLineWidth(blackOutlineWidth * 2.0)
            ctx.setLineJoin(.round)
            ctx.setLineCap(.round)
            ctx.addPath(path)
            ctx.strokePath()
            ctx.translateBy(x: seatX, y: seatY)
            ctx.rotate(by: bTilt)
            ctx.scaleBy(x: sx, y: sy)
            ctx.strokeEllipse(in: CGRect(x: leftHindX, y: leftHindY, width: hindW, height: leftHindH))
            if rightTucked {
                ctx.strokeEllipse(in: CGRect(x: rightHindX, y: rightHindY, width: hindW, height: rightHindH))
            }
            ctx.restoreGState()
            return
        }

        let partSpaces: [SkinSpace] = [.head, .skull, .body]
        let hasRegions = skin.regions.contains { partSpaces.contains($0.space) }
        let hasMarks = skin.marks.contains { partSpaces.contains($0.space) }
        let headMap: (CGPoint) -> CGPoint = { Self.headPoint($0, skull: false, skin: skin, head: headCenter, physics: physics) }
        let headWhiteMap: (CGPoint) -> CGPoint = { Self.headPoint($0, skull: false, skin: skin, head: headCenter, physics: physics, whiteSurface: true) }
        let skullMap: (CGPoint) -> CGPoint = { Self.headPoint($0, skull: true, skin: skin, head: headCenter, physics: physics) }
        let bodyMap: (CGPoint) -> CGPoint = { Self.bodyPoint($0, skin: skin, seatX: seatX, seatY: seatY, physics: physics) }

        ctx.saveGState()
        if pal.bodyShade == nil {
            ctx.setFillColor(pal.body.ns.cgColor)
            ctx.addPath(path)
            ctx.fillPath()
            if skin.headSurface == .dome && pal.body != pal.earOuter && !skin.colorpoint && !skin.marks.isEmpty && !skin.idleLegsTinted {
                // Overlap the matching fur colors at the ear/crown join so the
                // white torso underpaint cannot leave an antialiased seam.
                let join = CGMutablePath()
                join.move(to: lCheek)
                join.addCurve(to: crown, control1: H(leftCheekX - 1.5, cheekCtrlTopY), control2: H(-crownCtrlW + cheekShift * 0.3, crownBaseY + crownDrop))
                join.addCurve(to: rCheek, control1: H(crownCtrlW + cheekShift * 0.3, crownBaseY + crownDrop), control2: H(rightCheekX + 1.5, cheekCtrlTopY))
                ctx.setStrokeColor(pal.earOuter.ns.cgColor); ctx.setLineWidth(1.0); ctx.setLineCap(.round)
                ctx.addPath(join); ctx.strokePath()
            }
        }
        if pal.bodyShade != nil || skin.colorpoint || hasRegions || hasMarks {
            ctx.saveGState(); ctx.addPath(path); ctx.clip()
            let cs = CGColorSpaceCreateDeviceRGB()

            if let shade = pal.bodyShade {
                // Warm oat-milk cream gradient + soft toasted back shading
                let bodyColors = [pal.body.ns.cgColor, shade.ns.cgColor] as CFArray
                if let grad = CGGradient(colorsSpace: cs, colors: bodyColors, locations: [0.15, 1.0]) {
                    ctx.drawLinearGradient(
                        grad,
                        start: CGPoint(x: seatX, y: headCenter.y - 34),
                        end: CGPoint(x: seatX, y: seatY + 18),
                        options: [.drawsBeforeStartLocation, .drawsAfterEndLocation]
                    )
                }
            }

            // Curve regions: head/skull above the jaw line, body below it.
            for region in skin.regions where partSpaces.contains(region.space) {
                ctx.saveGState()
                let side = SkinSpec.jawSide(head: region.space != .body, cheekFullness: skin.shape.cheekFullness)
                ctx.addPath(polyline(side, closed: true, map: headMap))
                ctx.clip()
                drawRegion(in: ctx, region, map: region.space == .body ? bodyMap : (region.space == .skull ? skullMap : headMap))
                ctx.restoreGState()
            }

            if let point = pal.points {
                let mid = pal.pointsMid ?? point
                let yawRad = yaw * 0.50
                let pitchRad = pitch * 0.36
                ctx.saveGState()
                ctx.translateBy(x: headCenter.x, y: headCenter.y)
                ctx.rotate(by: hTilt)
                if hs != 1 { ctx.scaleBy(x: hs, y: hs) }

                // 2.5D Rotating Seal-Point "挖煤" Face Mask (layered soft mocha halo + velvety seal-brown muzzle!)
                let maskCenter = projectHead3D(x: 0, y: 3.0, z: 27.0, yawRad: yawRad, pitchRad: pitchRad).pt
                let maskScaleX = max(0.76, cos(yawRad * 0.7))
                let maskScaleY = max(0.82, cos(pitchRad * 0.7))

                // Layer 1: Soft wide eye-and-cheek mocha mask halo (startRadius: 0 so there is NEVER a center hole!)
                ctx.saveGState()
                ctx.translateBy(x: maskCenter.x, y: maskCenter.y)
                ctx.scaleBy(x: maskScaleX * 1.24, y: maskScaleY * 0.88)
                let maskColors = [
                    point.ns.cgColor,
                    point.withAlpha(0.92).cgColor,
                    mid.withAlpha(0.62).cgColor,
                    mid.withAlpha(0.0).cgColor
                ] as CFArray
                if let maskGrad = CGGradient(colorsSpace: cs, colors: maskColors, locations: [0.0, 0.42, 0.74, 1.0]) {
                    ctx.drawRadialGradient(
                        maskGrad,
                        startCenter: .zero, startRadius: 0,
                        endCenter: .zero, endRadius: 31.5,
                        options: [.drawsBeforeStartLocation]
                    )
                }
                ctx.restoreGState()

                // Layer 2: Soft warm cocoa muzzle depth below eyes
                let muzzleCenter = projectHead3D(x: 0, y: 7.5, z: 28.0, yawRad: yawRad, pitchRad: pitchRad).pt
                ctx.saveGState()
                ctx.translateBy(x: muzzleCenter.x, y: muzzleCenter.y)
                ctx.scaleBy(x: maskScaleX * 1.04, y: maskScaleY * 0.76)
                let muzzleColors = [
                    point.ns.cgColor,
                    point.withAlpha(0.85).cgColor,
                    point.withAlpha(0.0).cgColor
                ] as CFArray
                if let muzGrad = CGGradient(colorsSpace: cs, colors: muzzleColors, locations: [0.0, 0.50, 1.0]) {
                    ctx.drawRadialGradient(
                        muzGrad,
                        startCenter: .zero, startRadius: 0,
                        endCenter: .zero, endRadius: 19.5,
                        options: [.drawsBeforeStartLocation]
                    )
                }
                ctx.restoreGState()
                ctx.restoreGState()
            }

            let overlap = min(1, abs(yaw) * max(0, pitch))
            let coverage = overlap * overlap * (3 - 2 * overlap)
            let bib = skin.marks.first { $0.space == .head && !$0.stroke && isMilkMark($0) && $0.points.contains { abs($0.x) > 46 } }
            for mark in skin.marks {
                if mark.clipToBib && coverage == 0 { continue }
                switch mark.space {
                case .body:
                    drawMark(in: ctx, mark, map: bodyMap)
                case .skull:
                    drawMark(in: ctx, mark, map: skullMap)
                case .head:
                    let useWhite = skin.headSurface == .dome && isMilkMark(mark)
                    if mark.clipToBib, let bib = bib {
                        ctx.saveGState()
                        ctx.addPath(polyline(bib.points, closed: true, map: useWhite ? headWhiteMap : headMap))
                        ctx.clip()
                        let clipMap: (CGPoint) -> CGPoint = { pt in
                            var local = pt
                            let lowerRim = min(1, max(0, (pt.y - 20) / 6))
                            local.x *= 1 - 0.5 * lowerRim * (1 - coverage)
                            if pt.y > 20 { local.y = 20 + (pt.y - 20) * (0.75 + 0.25 * coverage) }
                            return (useWhite ? headWhiteMap : headMap)(local)
                        }
                        drawMark(in: ctx, mark, map: clipMap)
                        ctx.restoreGState()
                    } else {
                        drawMark(in: ctx, mark, map: useWhite ? headWhiteMap : headMap)
                    }
                default: break
                }
            }
            ctx.restoreGState()
        }
        ctx.restoreGState()

        // Ultra-soft plush rim (the Siamese cream body; never a harsh dark outline)
        if let outline = pal.outline {
            ctx.saveGState()
            ctx.setStrokeColor(outline.ns.cgColor)
            ctx.setLineWidth(1.0)
            ctx.addPath(path)
            ctx.strokePath()
            ctx.restoreGState()
        }

        // Tucked hind paws peeking softly along bottom edge
        ctx.saveGState()
        ctx.translateBy(x: seatX, y: seatY)
        ctx.rotate(by: bTilt)
        ctx.scaleBy(x: sx, y: sy)
        ctx.setFillColor(pal.paws.ns.cgColor)

        ctx.fillEllipse(in: CGRect(x: leftHindX, y: leftHindY, width: hindW, height: leftHindH))
        if rightTucked {
            ctx.fillEllipse(in: CGRect(x: rightHindX, y: rightHindY, width: hindW, height: rightHindH))
        }

        // Subtle bottom rim highlights on tucked haunches
        let rimColor = skin.colorpoint
            ? pal.body.withAlpha(0.55)
            : (isClassicBlackRim(skin) ? blackOutlineColor.withAlphaComponent(0.0) : pal.crease.withAlpha(0.58))
        ctx.setStrokeColor(rimColor.cgColor)
        ctx.setLineWidth(1.3)
        ctx.setLineCap(.round)
        ctx.addArc(center: CGPoint(x: leftHindX + hindW * 0.5, y: leftHindY + leftHindH * 0.5), radius: 7.5, startAngle: 0.25, endAngle: .pi - 0.25, clockwise: false)
        ctx.strokePath()
        if rightTucked {
            ctx.addArc(center: CGPoint(x: rightHindX + hindW * 0.5, y: rightHindY + rightHindH * 0.5), radius: 7.5, startAngle: 0.25, endAngle: .pi - 0.25, clockwise: false)
            ctx.strokePath()
        }
        if let pads = pal.pawPads {
            ctx.setFillColor(pads.ns.cgColor)
            for side in 0..<(rightTucked ? 2 : 1) {
                let cx = (side == 1 ? rightHindX : leftHindX) + hindW * 0.5
                let cy = side == 1 ? rightHindY + rightHindH * 0.5 : leftHindY + leftHindH * 0.5
                ctx.fillEllipse(in: CGRect(x: cx - 2.7, y: cy + 1.6 - 1.9, width: 5.4, height: 3.8))
                for tx: CGFloat in [-3.4, 0, 3.4] {
                    let ty = cy - 1.7 - (tx == 0 ? 0.8 : 0)
                    ctx.fillEllipse(in: CGRect(x: cx + tx - 1.25, y: ty - 1.1, width: 2.5, height: 2.2))
                }
            }
        }
        ctx.restoreGState()
    }

    private static func coatMarkPoint(_ p: CGPoint, headSurface: Bool, skull: Bool, coat: CatCoatTheme, seatX: CGFloat, seatY: CGFloat,
                                      head: CGPoint, physics: CatPhysics, whiteSurface: Bool = false) -> CGPoint {
        let skin = SkinSpec.builtIn(coat)
        if headSurface {
            return headPoint(p, skull: skull, skin: skin, head: head, physics: physics, whiteSurface: whiteSurface)
        }
        return bodyPoint(p, skin: skin, seatX: seatX, seatY: seatY, physics: physics)
    }
    // MARK: - 3rd Key Hind Foot Easter Egg

    private static func drawHindFoot(in ctx: CGContext, seatX: CGFloat, seatY: CGFloat, physics: CatPhysics, skin: SkinSpec) {
        let hip = CGPoint(x: seatX + 26 * skin.shape.bodyWidth, y: seatY + 2)
        let target = physics.hindFoot.point
        let mid = CGPoint(
            x: (hip.x + target.x) * 0.5 + 10,
            y: (hip.y + target.y) * 0.5 - 8
        )

        drawLimb(
            in: ctx,
            start: hip,
            control: mid,
            end: target,
            startWidth: 15.0,
            endWidth: 12.0,
            outlineOnLeftSide: true,
            outlineAlpha: 0.85 * physics.hindFootActive.value,
            skin: skin
        )
    }

    // MARK: - 2.5D Spherical Head Projection Helper

    /// Projects a 3D point on the cat's head ellipsoid rotated by (yawRad, pitchRad)
    /// into 2D head-local coordinates — creating true Live2D-style 2.5D head turning!
    private static func projectHead3D(
        x: CGFloat, y: CGFloat, z: CGFloat,
        yawRad: CGFloat, pitchRad: CGFloat
    ) -> (pt: CGPoint, z: CGFloat) {
        // 1. Yaw around Y axis (positive yaw = turning right toward viewer's right)
        let cy = cos(yawRad)
        let sy = sin(yawRad)
        let x1 = x * cy + z * sy
        let z1 = -x * sy + z * cy

        // 2. Pitch around X axis (positive pitch = nodding down)
        let cp = cos(pitchRad)
        let sp = sin(pitchRad)
        let y2 = y * cp + z1 * sp
        let z2 = -y * sp + z1 * cp

        return (CGPoint(x: x1, y: y2), z2)
    }

    // MARK: - 2.5D Ears Layer (drawn behind unified silhouette so seal-point ears emerge organically!)

    private static func drawEarsLayer(
        in ctx: CGContext,
        center: CGPoint,
        physics: CatPhysics,
        skin: SkinSpec,
        outlineOnly: Bool = false
    ) {
        ctx.saveGState()
        ctx.translateBy(x: center.x, y: center.y)
        ctx.rotate(by: physics.headTilt.value)
        if skin.shape.headScale != 1 { ctx.scaleBy(x: skin.shape.headScale, y: skin.shape.headScale) }

        let yawRad = physics.headYaw.value * 0.50
        let pitchRad = physics.headPitch.value * 0.36
        let fold = physics.earFold.value
        let twitch = physics.earTwitch.value * 0.045

        drawEar3D(in: ctx, isLeft: true, yawRad: yawRad, pitchRad: pitchRad, fold: fold, twitch: twitch, skin: skin, outlineOnly: outlineOnly)
        drawEar3D(in: ctx, isLeft: false, yawRad: yawRad, pitchRad: pitchRad, fold: fold, twitch: -twitch, skin: skin, outlineOnly: outlineOnly)

        ctx.restoreGState()
    }

    // MARK: - 2.5D Head Features (Luminous Eyes & Whiskers)

    private static func drawHeadFeatures(
        in ctx: CGContext,
        center: CGPoint,
        physics: CatPhysics,
        eyeTheme: EyeColorTheme,
        skin: SkinSpec,
        scruffStartle: CGFloat = 0,
        scruffWide: CGFloat = 0
    ) {
        ctx.saveGState()
        ctx.translateBy(x: center.x, y: center.y)
        ctx.rotate(by: physics.headTilt.value)
        if skin.shape.headScale != 1 { ctx.scaleBy(x: skin.shape.headScale, y: skin.shape.headScale) }

        let yaw = physics.headYaw.value      // -1 (left) .. +1 (right)
        let pitch = physics.headPitch.value  // -1 (up)   .. +1 (down)
        let yawRad = yaw * 0.50              // ~±28.5° authentic head turn
        let pitchRad = pitch * 0.36          // ~±20.5° authentic head nod

        if skin.renderStyle == .dazed {
            drawDazedFace(in: ctx, physics: physics, eyeTheme: eyeTheme, yawRad: yawRad, pitchRad: pitchRad, scruffStartle: scruffStartle, scruffWide: scruffWide)
            ctx.restoreGState()
            return
        }

        // 1. 3D-Projected Eyes with authentic spherical foreshortening & parallax!
        drawEye3D(in: ctx, isLeft: true, yawRad: yawRad, pitchRad: pitchRad, physics: physics, eyeTheme: eyeTheme, skin: skin, scruffStartle: scruffStartle, scruffWide: scruffWide)
        drawEye3D(in: ctx, isLeft: false, yawRad: yawRad, pitchRad: pitchRad, physics: physics, eyeTheme: eyeTheme, skin: skin, scruffStartle: scruffStartle, scruffWide: scruffWide)

        // 1b. Optional little kitty nose + delicate `:3` mouth hint (小豆泥 charm on the Siamese!)
        if skin.palette.nose != nil || skin.palette.mouth != nil {
            ctx.saveGState()
            if let noseColor = skin.palette.nose {
                let nose = projectHead3D(x: 0, y: 8.2, z: 29.0, yawRad: yawRad, pitchRad: pitchRad).pt
                // Tiny warm dark-rose-espresso triangle nose
                let nPath = CGMutablePath()
                nPath.move(to: CGPoint(x: nose.x - 2.3, y: nose.y - 1.1))
                nPath.addQuadCurve(to: CGPoint(x: nose.x + 2.3, y: nose.y - 1.1), control: CGPoint(x: nose.x, y: nose.y - 1.6))
                nPath.addQuadCurve(to: CGPoint(x: nose.x, y: nose.y + 1.5), control: CGPoint(x: nose.x + 1.8, y: nose.y + 0.6))
                nPath.addQuadCurve(to: CGPoint(x: nose.x - 2.3, y: nose.y - 1.1), control: CGPoint(x: nose.x - 1.8, y: nose.y + 0.6))
                nPath.closeSubpath()
                ctx.setFillColor(noseColor.ns.cgColor)
                ctx.addPath(nPath)
                ctx.fillPath()
            }
            if let mouthColor = skin.palette.mouth, physics.yawnAmount < 0.15 {
                let mouthL = projectHead3D(x: -4.2, y: 12.2, z: 28.4, yawRad: yawRad, pitchRad: pitchRad).pt
                let mouthM = projectHead3D(x: 0, y: 11.2, z: 28.8, yawRad: yawRad, pitchRad: pitchRad).pt
                let mouthR = projectHead3D(x: 4.2, y: 12.2, z: 28.4, yawRad: yawRad, pitchRad: pitchRad).pt
                // Delicate light-mocha `ω` kitty mouth (hidden while mouth is open yawning)
                ctx.setStrokeColor(mouthColor.ns.cgColor)
                ctx.setLineWidth(1.05)
                ctx.setLineCap(.round)
                ctx.move(to: mouthL)
                ctx.addQuadCurve(to: mouthM, control: CGPoint(x: (mouthL.x + mouthM.x) * 0.5, y: mouthL.y + 1.6))
                ctx.addQuadCurve(to: mouthR, control: CGPoint(x: (mouthM.x + mouthR.x) * 0.5, y: mouthR.y + 1.6))
                ctx.strokePath()
            }
            ctx.restoreGState()
        }

        if usesPatternedMuzzle(skin) { drawPatternedMuzzle(in: ctx, yawRad: yawRad, pitchRad: pitchRad) }
        if physics.yawnAmount > 0.03 {
            drawYawnMouth(in: ctx, yawRad: yawRad, pitchRad: pitchRad, yawn: physics.yawnAmount, skin: skin)
        }

        // 2. 3D-Projected Whiskers (outer-side whiskers poke out past silhouette when turning!)
        drawWhiskers3D(in: ctx, yawRad: yawRad, pitchRad: pitchRad, physics: physics, skin: skin)

        // 3. Expressive emotion badges: Anger vein (💢) & Dizzy orbiting stars (✦) & Scruff pinch!
        let anger = max(0, min(1, physics.angerIntensity.value))
        if anger > 0.25 {
            let aAlpha = min(1.0, (anger - 0.25) / 0.35)
            let pulse = 1.0 + sin(physics.time * 14.0) * 0.10
            let pt = projectHead3D(x: 28.0, y: -22.0, z: 24.0, yawRad: yawRad, pitchRad: pitchRad).pt
            ctx.saveGState()
            ctx.translateBy(x: pt.x, y: pt.y)
            ctx.scaleBy(x: pulse, y: pulse)
            ctx.setStrokeColor(NSColor(calibratedRed: 0.96, green: 0.22, blue: 0.28, alpha: 0.95 * aAlpha).cgColor)
            ctx.setLineWidth(2.0)
            ctx.setLineCap(.round)
            // Classic 4-corner anime anger vein mark
            let d: CGFloat = 2.4, r: CGFloat = 6.2
            for (sx, sy): (CGFloat, CGFloat) in [(-1,-1), (1,-1), (-1,1), (1,1)] {
                ctx.move(to: CGPoint(x: sx * r, y: sy * d))
                ctx.addQuadCurve(to: CGPoint(x: sx * d, y: sy * r), control: CGPoint(x: sx * d, y: sy * d))
            }
            ctx.strokePath()
            ctx.restoreGState()
        }

        ctx.restoreGState()
    }

    private static func drawYawnMouth(in ctx: CGContext, yawRad: CGFloat, pitchRad: CGFloat, yawn: CGFloat, skin: SkinSpec) {
        let y = max(0, min(1, yawn))
        let center = projectHead3D(x: 0, y: 16.2 + y * 2.2, z: 30.2, yawRad: yawRad, pitchRad: pitchRad).pt
        let rx = 3.2 + y * 5.8
        let ry = 1.6 + y * 7.4

        ctx.saveGState()
        ctx.translateBy(x: center.x, y: center.y)

        let mouth = CGMutablePath()
        mouth.move(to: CGPoint(x: 0, y: -ry * 0.92))
        mouth.addCurve(to: CGPoint(x: rx, y: ry * 0.08), control1: CGPoint(x: rx * 0.68, y: -ry * 0.92), control2: CGPoint(x: rx * 1.05, y: -ry * 0.42))
        mouth.addCurve(to: CGPoint(x: 0, y: ry), control1: CGPoint(x: rx * 0.95, y: ry * 0.72), control2: CGPoint(x: rx * 0.50, y: ry))
        mouth.addCurve(to: CGPoint(x: -rx, y: ry * 0.08), control1: CGPoint(x: -rx * 0.50, y: ry), control2: CGPoint(x: -rx * 0.95, y: ry * 0.72))
        mouth.addCurve(to: CGPoint(x: 0, y: -ry * 0.92), control1: CGPoint(x: -rx * 1.05, y: -ry * 0.42), control2: CGPoint(x: -rx * 0.68, y: -ry * 0.92))
        mouth.closeSubpath()

        ctx.setFillColor(NSColor(calibratedRed: 0.78, green: 0.19, blue: 0.25, alpha: 0.98).cgColor)
        ctx.addPath(mouth)
        ctx.fillPath()

        ctx.saveGState()
        ctx.addPath(mouth)
        ctx.clip()

        ctx.setFillColor(NSColor(calibratedRed: 0.55, green: 0.10, blue: 0.16, alpha: 0.55).cgColor)
        ctx.fillEllipse(in: CGRect(x: -rx * 0.65, y: -ry * 0.72, width: rx * 1.30, height: ry * 0.92))

        if y > 0.22 {
            let tAlpha = min(1.0, (y - 0.22) / 0.35)
            ctx.setFillColor(NSColor(calibratedRed: 0.95, green: 0.48, blue: 0.55, alpha: 0.92 * tAlpha).cgColor)
            let tongue = CGMutablePath()
            tongue.move(to: CGPoint(x: -rx * 0.62, y: ry * 0.55))
            tongue.addQuadCurve(to: CGPoint(x: 0, y: ry * 0.36), control: CGPoint(x: -rx * 0.32, y: ry * 0.16))
            tongue.addQuadCurve(to: CGPoint(x: rx * 0.62, y: ry * 0.55), control: CGPoint(x: rx * 0.32, y: ry * 0.16))
            tongue.addQuadCurve(to: CGPoint(x: -rx * 0.62, y: ry * 0.55), control: CGPoint(x: 0, y: ry * 1.25))
            tongue.closeSubpath()
            ctx.addPath(tongue)
            ctx.fillPath()
        }

        if y > 0.28 {
            let fScale = min(1.0, (y - 0.28) / 0.32)
            ctx.setFillColor(NSColor(calibratedRed: 1.0, green: 0.99, blue: 0.96, alpha: 0.98).cgColor)
            let upperBaseY = -ry * 0.80
            let upperLen = (2.6 + y * 2.2) * fScale
            let upperHalfW = (1.15 + y * 0.55) * fScale
            for sign: CGFloat in [-1, 1] {
                let fx = sign * rx * 0.46
                let fang = CGMutablePath()
                fang.move(to: CGPoint(x: fx - upperHalfW, y: upperBaseY - 0.8))
                fang.addLine(to: CGPoint(x: fx + upperHalfW, y: upperBaseY - 0.8))
                fang.addQuadCurve(to: CGPoint(x: fx - sign * 0.25, y: upperBaseY + upperLen), control: CGPoint(x: fx + upperHalfW * 0.45, y: upperBaseY + upperLen * 0.62))
                fang.addQuadCurve(to: CGPoint(x: fx - upperHalfW, y: upperBaseY - 0.8), control: CGPoint(x: fx - upperHalfW * 0.45, y: upperBaseY + upperLen * 0.62))
                fang.closeSubpath()
                ctx.addPath(fang)
                ctx.fillPath()
            }
            let lowerBaseY = ry * 0.84
            let lowerLen = (1.6 + y * 1.3) * fScale
            let lowerHalfW = (0.85 + y * 0.35) * fScale
            for sign: CGFloat in [-1, 1] {
                let fx = sign * rx * 0.36
                let fang = CGMutablePath()
                fang.move(to: CGPoint(x: fx - lowerHalfW, y: lowerBaseY + 0.8))
                fang.addLine(to: CGPoint(x: fx + lowerHalfW, y: lowerBaseY + 0.8))
                fang.addQuadCurve(to: CGPoint(x: fx - sign * 0.15, y: lowerBaseY - lowerLen), control: CGPoint(x: fx + lowerHalfW * 0.4, y: lowerBaseY - lowerLen * 0.55))
                fang.addQuadCurve(to: CGPoint(x: fx - lowerHalfW, y: lowerBaseY + 0.8), control: CGPoint(x: fx - lowerHalfW * 0.4, y: lowerBaseY - lowerLen * 0.55))
                fang.closeSubpath()
                ctx.addPath(fang)
                ctx.fillPath()
            }
        }
        ctx.restoreGState()

        let rimColor: NSColor = (skin.palette.body.luminance < 0.25 || skin.colorpoint)
            ? NSColor(calibratedRed: 0.42, green: 0.08, blue: 0.12, alpha: 0.85)
            : NSColor(calibratedRed: 0.56, green: 0.22, blue: 0.26, alpha: 0.72)
        ctx.setStrokeColor(rimColor.cgColor)
        ctx.setLineWidth(1.0)
        ctx.addPath(mouth)
        ctx.strokePath()

        ctx.restoreGState()
    }

    // Small opaque nose and soft mouth on the existing white muzzle, below whiskers.
    // All control points share the head's yaw/pitch projection; the caller applies roll.
    private static func drawPatternedMuzzle(in ctx: CGContext, yawRad: CGFloat, pitchRad: CGFloat) {
        let local: [CGPoint] = [CGPoint(x: -2.9, y: 8.5), CGPoint(x: -1.8, y: 8.1), CGPoint(x: 1.8, y: 8.1), CGPoint(x: 2.9, y: 8.5), CGPoint(x: 3.2, y: 8.9), CGPoint(x: 0.8, y: 12.1), CGPoint(x: 0, y: 12.3), CGPoint(x: -0.8, y: 12.1), CGPoint(x: -3.2, y: 8.9), CGPoint(x: -2.9, y: 8.5), CGPoint(x: -5.9, y: 14.4), CGPoint(x: -4.7, y: 18), CGPoint(x: -1.4, y: 18), CGPoint(x: 0, y: 14.3), CGPoint(x: 1.4, y: 18), CGPoint(x: 4.7, y: 18), CGPoint(x: 5.9, y: 14.4), CGPoint(x: 0, y: 12.0)]
        let p = local.map { projectHead3D(x: $0.x, y: $0.y, z: 30, yawRad: yawRad, pitchRad: pitchRad).pt }
        ctx.saveGState()
        let nose = CGMutablePath()
        nose.move(to: p[0])
        nose.addCurve(to: p[3], control1: p[1], control2: p[2])
        nose.addCurve(to: p[6], control1: p[4], control2: p[5])
        nose.addCurve(to: p[9], control1: p[7], control2: p[8])
        nose.closeSubpath()
        ctx.setFillColor(rgb(0xD98F9B).cgColor)
        ctx.addPath(nose); ctx.fillPath()
        ctx.setStrokeColor(rgb(0x8B8C86, 0.78).cgColor)
        ctx.setLineWidth(1.15); ctx.setLineCap(.round); ctx.setLineJoin(.round)
        ctx.move(to: p[17]); ctx.addLine(to: p[13])
        ctx.move(to: p[10]); ctx.addCurve(to: p[13], control1: p[11], control2: p[12])
        ctx.addCurve(to: p[16], control1: p[14], control2: p[15]); ctx.strokePath()
        ctx.restoreGState()
    }

    private static func drawEar3D(
        in ctx: CGContext,
        isLeft: Bool,
        yawRad: CGFloat,
        pitchRad: CGFloat,
        fold: CGFloat,
        twitch: CGFloat,
        skin: SkinSpec,
        outlineOnly: Bool = false
    ) {
        if skin.renderStyle == .dazed {
            if !outlineOnly { drawDazedEar(in: ctx, sign: isLeft ? -1.0 : 1.0, yawRad: yawRad, pitchRad: pitchRad, fold: fold, twitch: twitch) }
            return
        }
        let bd = build(skin)
        let sign: CGFloat = isLeft ? -1.0 : 1.0
        let foldAngle = sign * (bd.earFold + fold * 0.34) + twitch
        let earLen: CGFloat = bd.earLen

        let tipDx = sin(foldAngle) * earLen
        let tipDy = -cos(foldAngle) * earLen

        // Bases anchored comfortably inside the upper skull contour so they merge seamlessly at every yaw/pitch!
        var innerBase3D = projectHead3D(x: sign * bd.earInX, y: bd.earInY, z: 0.0, yawRad: yawRad, pitchRad: pitchRad).pt
        var outerBase3D = projectHead3D(x: sign * bd.earOutX, y: bd.earOutY, z: -2.0, yawRad: yawRad, pitchRad: pitchRad).pt
        var tip3D       = projectHead3D(x: sign * bd.earTipX + tipDx, y: bd.earTipY + tipDy, z: -3.0, yawRad: yawRad, pitchRad: pitchRad).pt
        let es = skin.shape.earSize
        if es != 1 { // grow / shrink around the middle of the ear base
            let m = CGPoint(x: (innerBase3D.x + outerBase3D.x) * 0.5, y: (innerBase3D.y + outerBase3D.y) * 0.5)
            innerBase3D = CGPoint(x: around(innerBase3D.x, m.x, es), y: around(innerBase3D.y, m.y, es))
            outerBase3D = CGPoint(x: around(outerBase3D.x, m.x, es), y: around(outerBase3D.y, m.y, es))
            tip3D = CGPoint(x: around(tip3D.x, m.x, es), y: around(tip3D.y, m.y, es))
        }
        let ebw = skin.shape.earBaseWidth
        if ebw != 1 {
            let m = CGPoint(x: (innerBase3D.x + outerBase3D.x) * 0.5, y: (innerBase3D.y + outerBase3D.y) * 0.5)
            innerBase3D = CGPoint(x: around(innerBase3D.x, m.x, ebw), y: around(innerBase3D.y, m.y, ebw))
            outerBase3D = CGPoint(x: around(outerBase3D.x, m.x, ebw), y: around(outerBase3D.y, m.y, ebw))
        }

        // Soft plush rounded-tip feline ear
        let ep = skin.shape.earPointiness
        let tipSpread: CGFloat = bd.earTipSpread / ep
        let tipLeft  = CGPoint(x: tip3D.x - sign * tipSpread, y: tip3D.y + 2.8)
        let tipRight = CGPoint(x: tip3D.x + sign * tipSpread, y: tip3D.y + 3.2)

        let ear = CGMutablePath()
        ear.move(to: innerBase3D)
        ear.addQuadCurve(
            to: tipLeft,
            control: CGPoint(x: (innerBase3D.x + tipLeft.x) * 0.5 - sign * 1.5, y: (innerBase3D.y + tipLeft.y) * 0.5 - 2.0)
        )
        ear.addQuadCurve(to: tipRight, control: CGPoint(x: tip3D.x, y: tip3D.y - 2.2 * ep))
        ear.addQuadCurve(
            to: outerBase3D,
            control: CGPoint(x: (outerBase3D.x + tipRight.x) * 0.5 + sign * 2.5, y: (outerBase3D.y + tipRight.y) * 0.5 - 2.0)
        )
        ear.closeSubpath()

        ctx.saveGState()
        if outlineOnly {
            ctx.setStrokeColor(blackOutlineColor.cgColor)
            ctx.setLineWidth(blackOutlineWidth * 2.0)
            ctx.setLineJoin(.round)
            ctx.setLineCap(.round)
            ctx.addPath(ear)
            ctx.strokePath()
            ctx.restoreGState()
            return
        }
        ctx.setFillColor(skin.palette.earOuter.ns.cgColor)
        ctx.addPath(ear)
        ctx.fillPath()

        // Optional inner ear hollow (warm dusty cocoa on the Siamese)
        if let innerColor = skin.palette.earInner {
            let inI = CGPoint(x: innerBase3D.x + (tip3D.x - innerBase3D.x) * 0.24 + sign * 3.0,
                              y: innerBase3D.y + (tip3D.y - innerBase3D.y) * 0.16)
            let outI = CGPoint(x: outerBase3D.x + (tip3D.x - outerBase3D.x) * 0.20 - sign * 3.8,
                               y: outerBase3D.y + (tip3D.y - outerBase3D.y) * 0.18)
            let tipI = CGPoint(x: (innerBase3D.x + outerBase3D.x) * 0.16 + tip3D.x * 0.68,
                               y: (innerBase3D.y + outerBase3D.y) * 0.14 + tip3D.y * 0.72 + 2.5)
            let inner = CGMutablePath()
            inner.move(to: inI)
            inner.addQuadCurve(to: tipI, control: CGPoint(x: (inI.x + tipI.x) * 0.5 - sign * 0.8, y: (inI.y + tipI.y) * 0.5))
            inner.addQuadCurve(to: outI, control: CGPoint(x: (outI.x + tipI.x) * 0.5 + sign * 1.2, y: (outI.y + tipI.y) * 0.5))
            inner.closeSubpath()
            ctx.setFillColor(innerColor.ns.cgColor)
            ctx.addPath(inner)
            ctx.fillPath()
        }

        let space: SkinSpace = isLeft ? .leftEar : .rightEar
        if skin.hasPartArt(space) {
            // Ear space: (-50,0) inner base, (50,0) outer base, (0,-100) tip; mirrored per ear.
            let m = CGPoint(x: (innerBase3D.x + outerBase3D.x) * 0.5, y: (innerBase3D.y + outerBase3D.y) * 0.5)
            let inB = innerBase3D, outB = outerBase3D, tipP = tip3D
            let map: (CGPoint) -> CGPoint = { p in
                let u = p.x / 100, v = -p.y / 100
                return CGPoint(x: m.x + u * (outB.x - inB.x) + v * (tipP.x - m.x), y: m.y + u * (outB.y - inB.y) + v * (tipP.y - m.y))
            }
            ctx.saveGState()
            ctx.addPath(ear)
            ctx.clip()
            for region in skin.regions where region.space == space { drawRegion(in: ctx, region, map: map) }
            for mark in skin.marks where mark.space == space { drawMark(in: ctx, mark, map: map) }
            ctx.restoreGState()
        }
        ctx.restoreGState()
    }

    private static func drawEye3D(
        in ctx: CGContext,
        isLeft: Bool,
        yawRad: CGFloat,
        pitchRad: CGFloat,
        physics: CatPhysics,
        eyeTheme: EyeColorTheme,
        skin: SkinSpec,
        scruffStartle: CGFloat = 0,
        scruffWide: CGFloat = 0
    ) {
        let sign: CGFloat = isLeft ? -1.0 : 1.0
        let customIris = skin.palette.iris   // a skin's iris overrides the eye-colour menu
        let eyeColor = customIris?.ns ?? eyeTheme.primaryColor
        let siameseBlue = customIris == nil && eyeTheme == .siameseBlue

        // Eye sits on the front surface of the 3D head sphere at (±17.5, -2.0, +28.0)
        let proj = projectHead3D(x: sign * 17.2, y: -2.0, z: 27.5, yawRad: yawRad, pitchRad: pitchRad)

        // Authentic spherical foreshortening: the eye turning away toward the edge narrows horizontally!
        let eyeNormalAngle = yawRad + sign * 0.34
        let foreshortenX = max(0.64, min(1.06, cos(eyeNormalAngle) / cos(0.34)))
        let foreshortenY = max(0.78, min(1.03, cos(pitchRad * 0.85)))

        ctx.saveGState()
        ctx.translateBy(x: proj.pt.x, y: proj.pt.y)
        ctx.scaleBy(x: foreshortenX, y: foreshortenY)

        // Mode 0: Dizzy spinning spiral eyes (@ @) — appear AFTER initial golden stars warning (>0.28)!
        let dizzy = max(0, min(1, physics.dizzyIntensity.value))
        if dizzy > 0.28 {
            ctx.setFillColor(NSColor(calibratedRed: 0.98, green: 0.98, blue: 0.96, alpha: 0.95).cgColor)
            ctx.fillEllipse(in: CGRect(x: -11.5, y: -11.0, width: 23.0, height: 22.0))
            ctx.setStrokeColor(NSColor(calibratedRed: 0.14, green: 0.14, blue: 0.18, alpha: 0.95).cgColor)
            ctx.setLineWidth(1.85)
            ctx.setLineCap(.round)
            let spiral = CGMutablePath()
            let spin = physics.dizzyPhase * (isLeft ? 1.0 : -1.0)
            for step in 0...42 {
                let t = CGFloat(step) / 42.0
                let theta = spin + t * .pi * 5.2
                let rad = 1.0 + t * 8.6
                let px = cos(theta) * rad
                let py = sin(theta) * rad
                if step == 0 { spiral.move(to: CGPoint(x: px, y: py)) }
                else { spiral.addLine(to: CGPoint(x: px, y: py)) }
            }
            ctx.addPath(spiral)
            ctx.strokePath()
            ctx.restoreGState()
            return
        }

        let bodyLuma = 0.299 * skin.palette.body.r + 0.587 * skin.palette.body.g + 0.114 * skin.palette.body.b
        let pointsLuma: CGFloat = skin.palette.points.map { 0.299 * $0.r + 0.587 * $0.g + 0.114 * $0.b } ?? 1.0
        let outlineLuma: CGFloat = skin.palette.outline.map { 0.299 * $0.r + 0.587 * $0.g + 0.114 * $0.b } ?? 1.0
        let isDarkEyeArea = bodyLuma < 0.28 || (skin.colorpoint && pointsLuma < 0.38)
        let closedLidColor: CGColor = {
            if isDarkEyeArea { return eyeColor.cgColor }
            if let out = skin.palette.outline, outlineLuma < 0.42 {
                return out.ns.withAlphaComponent(0.90).cgColor
            }
            return NSColor(calibratedRed: 60.0 / 255.0, green: 50.0 / 255.0, blue: 44.0 / 255.0, alpha: 0.88).cgColor
        }()

        // Mode 1: Happy closed curved line eyes (petting head!)
        if physics.isHappyClosedEyes {
            ctx.setStrokeColor(closedLidColor)
            ctx.setLineWidth(2.6)
            ctx.setLineCap(.round)
            ctx.move(to: CGPoint(x: -11.5, y: 1.0))
            ctx.addQuadCurve(
                to: CGPoint(x: 11.5, y: 1.0),
                control: CGPoint(x: sign * 1.5, y: 3.4)
            )
            ctx.strokePath()
            ctx.restoreGState()
            return
        }

        // Mode 1b: Peaceful closed sleeping eyelids on light-faced cats so eyes never vanish into light fur!
        if !isDarkEyeArea && physics.sleepiness > 0.62 && scruffStartle < 0.15 {
            ctx.setStrokeColor(closedLidColor)
            ctx.setLineWidth(2.5)
            ctx.setLineCap(.round)
            ctx.move(to: CGPoint(x: -10.5, y: 0.4))
            ctx.addQuadCurve(
                to: CGPoint(x: 10.5, y: 0.4),
                control: CGPoint(x: 0, y: 5.2)
            )
            ctx.strokePath()
            ctx.restoreGState()
            return
        }

        // Mode 2: Blissful half-squint glowing lime slits (petting back/body!)
        if physics.isBlissfulSquint {
            ctx.setFillColor(eyeColor.cgColor)
            let slit = CGMutablePath()
            slit.move(to: CGPoint(x: -11.5, y: -0.5))
            slit.addQuadCurve(to: CGPoint(x: 11.5, y: -0.5), control: CGPoint(x: 0, y: 0.6))
            slit.addQuadCurve(to: CGPoint(x: -11.5, y: -0.5), control: CGPoint(x: 0, y: 4.8))
            slit.closeSubpath()
            ctx.addPath(slit)
            ctx.fillPath()
            if !isDarkEyeArea {
                ctx.setStrokeColor(closedLidColor)
                ctx.setLineWidth(1.6)
                ctx.setLineCap(.round)
                ctx.move(to: CGPoint(x: -11.2, y: -0.5))
                ctx.addQuadCurve(to: CGPoint(x: 11.2, y: -0.5), control: CGPoint(x: 0, y: 0.6))
                ctx.strokePath()
            }
            ctx.restoreGState()
            return
        }

        let hunt = max(0, min(1, max(physics.huntIntensity.value, scruffWide * 0.94)))

        // Subtle feline eye angle (straightens slightly when wide-eyed hunting!)
        ctx.rotate(by: sign * (0.06 * (1.0 - hunt * 0.6)))

        // Eyes grow rounder & slightly larger in full hunting focus!
        let isSiameseEye = build(skin).sleekEyes && siameseBlue
        let rx: CGFloat = (isSiameseEye ? 11.4 + hunt * 1.3 : 12.0 + hunt * 1.1)
        let ry: CGFloat = (isSiameseEye ? 9.8 + hunt * 2.0 : 10.8 + hunt * 1.8)
        let eyeRect = CGRect(x: -rx, y: -ry, width: rx * 2, height: ry * 2)

        // Clip to the visible opening before painting any iris/pupil pixels.
        // Painting a lid over an antialiased oval leaves a colored fringe.
        ctx.saveGState()
        ctx.addEllipse(in: eyeRect)
        ctx.clip()

        let closure = max(0, min(1, max(physics.effectiveEyeClosure, scruffStartle * 0.44)))
        if closure >= 1 {
            ctx.restoreGState()
            ctx.restoreGState()
            return
        }
        if closure > 0 {
            ctx.clip(to: CGRect(x: -rx - 2, y: -ry + 2 * ry * closure,
                                width: 2 * rx + 4, height: 2 * ry * (1 - closure)))
        }
        // Angry furrowed V-brow slant clipped cleanly inside the eye so every skin's real forehead fur (including Siamese mask!) shows through seamlessly!
        let anger = max(0, min(1, physics.angerIntensity.value))
        if anger > 0.15 {
            let angryCut = CGMutablePath()
            let drop = 7.5 * anger
            angryCut.move(to: CGPoint(x: sign * (rx + 4), y: -ry + 1.5))
            angryCut.addLine(to: CGPoint(x: -sign * (rx + 4), y: -ry + 2.5 + drop))
            angryCut.addLine(to: CGPoint(x: -sign * (rx + 4), y: ry + 4))
            angryCut.addLine(to: CGPoint(x: sign * (rx + 4), y: ry + 4))
            angryCut.closeSubpath()
            ctx.addPath(angryCut)
            ctx.clip()
        }

        // Luminous iris (flat-art translucent pale crystal ice-blue top-to-bottom wash for Siamese!)
        ctx.setFillColor(eyeColor.cgColor)
        ctx.fill(eyeRect)
        if siameseBlue {
            let cs = CGColorSpaceCreateDeviceRGB()
            let irisCols = [
                NSColor(calibratedRed: 0.56, green: 0.77, blue: 0.90, alpha: 1.0).cgColor,  // #8FC4E6 soft cool upper iris
                NSColor(calibratedRed: 0.71, green: 0.87, blue: 0.96, alpha: 1.0).cgColor,  // #B5DEF5 airy pale sky blue
                NSColor(calibratedRed: 0.86, green: 0.945, blue: 0.99, alpha: 1.0).cgColor  // #DBF1FC clear luminous lower iris
            ] as CFArray
            if let irisGrad = CGGradient(colorsSpace: cs, colors: irisCols, locations: [0.0, 0.55, 1.0]) {
                ctx.drawLinearGradient(
                    irisGrad,
                    start: CGPoint(x: 0, y: -ry),
                    end: CGPoint(x: 0, y: ry),
                    options: [.drawsBeforeStartLocation, .drawsAfterEndLocation]
                )
            }
        }

        // Pupil morphs smoothly from vertical almond slit -> HUGE round black boba pupil when hunting!
        let gaze = physics.eyeGaze.point
        let px = gaze.x * (4.2 - hunt * 1.2)
        let py = gaze.y * (3.6 - hunt * 1.0)
        let pScale = physics.pupilScale.value
        let normalW: CGFloat = 5.0 * pScale
        let normalH: CGFloat = 13.5 * min(1.12, pScale)
        let huntDiameter: CGFloat = 18.8 // huge round boba pupil leaving an electric chartreuse ring!
        let pupilW = normalW + (huntDiameter - normalW) * hunt
        let pupilH = normalH + (huntDiameter - normalH) * hunt
        let pupilRect = CGRect(x: px - pupilW * 0.5, y: py - pupilH * 0.5, width: pupilW, height: pupilH)
        // Photo-sampled hazel: #DAB257 outside, a narrow #8D9180 ring by the pupil.
        // Paint inside the existing lid clip and follow the animated pupil position/size.
        if customIris == nil && eyeTheme == .referenceHazel {
            for i in 0...24 {
                let t = CGFloat(i) / 24
                let mix = t * t * (3 - 2 * t)
                ctx.setFillColor(NSColor(calibratedRed: (218 - 77 * mix)/255,
                    green: (178 - 33 * mix)/255, blue: (87 + 41 * mix)/255, alpha: 1).cgColor)
                let rim = (1 - t) * 2.2
                ctx.fillEllipse(in: pupilRect.insetBy(dx: -rim, dy: -rim))
            }
        }
        ctx.setFillColor(catBlack.cgColor)
        ctx.fillEllipse(in: pupilRect)

        // Tiny crisp white specular sparkle dot (subtle catchlight on translucent Siamese blue eyes + hunting boba sparkle!)
        if hunt > 0.25 {
            let glintAlpha = min(1.0, (hunt - 0.25) / 0.55) * 0.92
            ctx.setFillColor(NSColor(calibratedWhite: 1.0, alpha: glintAlpha).cgColor)
            let glintR: CGFloat = 2.1 + hunt * 0.9
            ctx.fillEllipse(in: CGRect(
                x: px - pupilW * 0.22 - glintR * 0.5,
                y: py - pupilH * 0.22 - glintR * 0.5,
                width: glintR * 2,
                height: glintR * 2
            ))
            // Second crisp lower specular dot when scruff-lifted aloft for extra watery pleading appeal
            if scruffWide > 0.25 {
                let sAlpha = min(1.0, (scruffWide - 0.25) / 0.45) * 0.88
                ctx.setFillColor(NSColor(calibratedWhite: 1.0, alpha: sAlpha).cgColor)
                let sr: CGFloat = 1.45
                ctx.fillEllipse(in: CGRect(x: px + pupilW * 0.16 - sr, y: py + pupilH * 0.18 - sr, width: sr * 2, height: sr * 2))
            }
        } else if siameseBlue {
            ctx.setFillColor(NSColor(calibratedWhite: 1.0, alpha: 0.86).cgColor)
            let glintR: CGFloat = 1.65
            ctx.fillEllipse(in: CGRect(
                x: px - 2.9 - glintR,
                y: py - 3.6 - glintR,
                width: glintR * 2,
                height: glintR * 2
            ))
        }

        ctx.restoreGState()
        ctx.restoreGState()
    }

    private static func drawWhiskers3D(
        in ctx: CGContext,
        yawRad: CGFloat,
        pitchRad: CGFloat,
        physics: CatPhysics,
        skin: SkinSpec
    ) {
        let wiggle = sin(physics.time * 4.5) * (max(physics.petHeadIntensity, physics.petBodyIntensity) * 1.2)
        ctx.saveGState()
        ctx.setStrokeColor(skin.palette.whiskers.ns.cgColor)
        ctx.setLineWidth(1.0)
        ctx.setLineCap(.round)

        // 3D cheek whiskers — when turning left, left whiskers naturally poke past silhouette
        // while right whiskers sweep inward across the cheek (exact Xiaohongshu effect!)
        for sign in [-1.0, 1.0] as [CGFloat] {
            let rows: [(CGFloat, CGFloat, CGFloat)] = [
                (10.5, 36.5, 8.8 + wiggle),
                (14.2, 37.8, 14.2 + wiggle * 0.5),
                (18.0, 35.5, 19.6 - wiggle * 0.4)
            ]
            for (y0, xEnd, yEnd) in rows {
                let p0 = projectHead3D(x: sign * 24.0, y: y0, z: 23.0, yawRad: yawRad, pitchRad: pitchRad).pt
                let p2 = projectHead3D(x: sign * xEnd, y: yEnd, z: 14.0, yawRad: yawRad, pitchRad: pitchRad).pt
                let ctrl = CGPoint(x: (p0.x + p2.x) * 0.5, y: (p0.y + p2.y) * 0.5 - 0.8)
                ctx.move(to: p0)
                ctx.addQuadCurve(to: p2, control: ctrl)
            }
        }
        ctx.strokePath()
        ctx.restoreGState()
    }

    // MARK: - Decorations (anchored PNG stickers)

    private static func drawDecorations(in ctx: CGContext, seatX: CGFloat, seatY: CGFloat, head: CGPoint, physics: CatPhysics, skin: SkinSpec,
                                        neckOverride: CGPoint? = nil, tailTipOverride: CGPoint? = nil) {
        let yawRad = physics.headYaw.value * 0.50, pitchRad = physics.headPitch.value * 0.36
        for deco in skin.decorations {
            var at = CGPoint.zero
            var rot: CGFloat = 0, kx: CGFloat = 1, ky: CGFloat = 1
            switch deco.anchor {
            case .headTop, .face:
                let baseY: CGFloat = deco.anchor == .headTop ? -30 : 4
                at = headPoint(CGPoint(x: deco.offsetX, y: baseY + deco.offsetY), skull: false, skin: skin, head: head, physics: physics)
                rot = physics.headTilt.value
                kx = max(0.55, cos(yawRad)) * skin.shape.headScale
                ky = max(0.70, cos(pitchRad)) * skin.shape.headScale
            case .neck:
                if let n = neckOverride {
                    at = CGPoint(x: n.x + deco.offsetX, y: n.y + deco.offsetY)
                    rot = 0
                } else {
                    at = bodyPoint(CGPoint(x: deco.offsetX, y: -64 + deco.offsetY), skin: skin, seatX: seatX, seatY: seatY, physics: physics)
                    rot = physics.bodyTilt.value
                }
            case .tailTip:
                if let t = tailTipOverride {
                    at = CGPoint(x: t.x + deco.offsetX, y: t.y + deco.offsetY)
                } else {
                    let curve = tailCurve(seatX: seatX, seatY: seatY, physics: physics, skin: skin)
                    at = CGPoint(x: curve.tip.x + deco.offsetX, y: curve.tip.y + deco.offsetY)
                }
            }
            let scale = 0.5 * deco.scale   // stickers are authored at 2x: 1 image px = 0.5 canvas units
            let w = CGFloat(deco.image.width), h = CGFloat(deco.image.height)
            ctx.saveGState()
            ctx.translateBy(x: at.x, y: at.y)
            ctx.rotate(by: rot + deco.rotation * .pi / 180)
            ctx.scaleBy(x: scale * kx, y: scale * ky)
            // The canvas is flipped (y down); flip locally so the PNG is upright.
            ctx.translateBy(x: 0, y: h * 0.5)
            ctx.scaleBy(x: 1, y: -1)
            ctx.interpolationQuality = .high
            ctx.draw(deco.image, in: CGRect(x: -w * 0.5, y: 0, width: w, height: h))
            ctx.restoreGState()
        }
    }

    // MARK: - Front Paws (Idle Sitting & Dynamic Reaching with Signature Outlines / Colour-point Socks)

    private static func drawFrontPaws(
        in ctx: CGContext,
        seatX: CGFloat,
        seatY: CGFloat,
        breath: CGFloat,
        physics: CatPhysics,
        skin: SkinSpec
    ) {
        let lPos = physics.leftPaw.point
        let rPos = physics.rightPaw.point

        let lDist = hypot(lPos.x - CatPhysics.leftPawRest.x, lPos.y - CatPhysics.leftPawRest.y)
        let rDist = hypot(rPos.x - CatPhysics.rightPawRest.x, rPos.y - CatPhysics.rightPawRest.y)

        // Attach to the transformed chest, below the moving face rather than its white blaze.
        let bd = build(skin)
        let bw = skin.shape.bodyWidth
        let headLift: CGFloat = bd.headLift
        let lie = max(0, min(1, physics.lieIntensity.value))
        let lieS = lie * lie * (3.0 - 2.0 * lie)
        // When curling into a cozy sleeping ball, tuck front legs neatly inward underneath the chin (揣手手)!
        let idleTopY: CGFloat = (seatY - bd.idleTopDY) + lieS * 24.0
        let idleTopX: CGFloat = bd.idleTopX * bw - lieS * 5.0
        let idleBotX: CGFloat = bd.idleBotX * bw - lieS * 4.5
        let idleBotY: CGFloat = seatY + 12.0 - lieS * 4.0
        let shX: CGFloat = bd.shoulderX * bw
        let approved = !skin.colorpoint && skin.palette.belly != nil && skin.palette.belly == skin.palette.legs && !skin.idleLegsTinted && !skin.marks.isEmpty
        let shoulderDepth: CGFloat = approved ? 43 : 58
        let faceClearance: CGFloat = approved ? 52 : 42
        func shoulder(_ x: CGFloat) -> CGPoint {
            let sy = physics.bodySquash.value * (1.0 - lieS * 0.42)
            let sx = (1.0 + (1.0 - physics.bodySquash.value) * 0.55) * (1.0 + lieS * 0.03)
            let c = cos(physics.bodyTilt.value), s = sin(physics.bodyTilt.value)
            let faceBottom = 126 + headLift + physics.headOffsetY.value + physics.headPitch.value * 4.8 + breath * 1.1 + faceClearance
            return CGPoint(x: seatX + x*sx*c + shoulderDepth*sy*s,
                           y: max(seatY + x*sx*s - shoulderDepth*sy*c, faceBottom))
        }
        let leftShoulder = shoulder(-shX)
        let rightShoulder = shoulder(shX)

        // Left arm
        if lDist < 6.0 && !physics.leftPawOnMouse && !physics.leftPawTyping {
            if lieS < 0.78 {
                drawIdleFrontLeg(in: ctx, top: CGPoint(x: seatX - idleTopX, y: idleTopY), bottom: CGPoint(x: seatX - idleBotX, y: idleBotY), isLeft: true, skin: skin)
            }
        } else {
            let mid = CGPoint(
                x: (leftShoulder.x + lPos.x) * 0.5 - (physics.leftPawOnMouse ? 8 : 4),
                y: (leftShoulder.y + lPos.y) * 0.5 - 6
            )
            drawLimb(
                in: ctx,
                start: leftShoulder,
                control: mid,
                end: lPos,
                startWidth: bd.limbStartW,
                endWidth: bd.limbEndW,
                outlineOnLeftSide: false,
                outlineAlpha: 0.78,
                skin: skin,
                frontPaw: true
            )
        }

        // Right arm
        if rDist < 6.0 && !physics.rightPawTyping {
            if lieS < 0.78 {
                drawIdleFrontLeg(in: ctx, top: CGPoint(x: seatX + idleTopX, y: idleTopY), bottom: CGPoint(x: seatX + idleBotX, y: idleBotY), isLeft: false, skin: skin)
            }
        } else {
            let mid = CGPoint(
                x: (rightShoulder.x + rPos.x) * 0.5 + 4,
                y: (rightShoulder.y + rPos.y) * 0.5 - 6
            )
            drawLimb(
                in: ctx,
                start: rightShoulder,
                control: mid,
                end: rPos,
                startWidth: bd.limbStartW,
                endWidth: bd.limbEndW,
                outlineOnLeftSide: true,
                outlineAlpha: 0.78,
                skin: skin,
                frontPaw: true
            )
        }
    }

    /// Signature tucked sitting front legs (black with mint lines OR colour-point cream-to-chocolate socks!)
    private static func drawIdleFrontLeg(in ctx: CGContext, top: CGPoint, bottom: CGPoint, isLeft: Bool, skin: SkinSpec) {
        if skin.renderStyle == .dazed {
            let sign: CGFloat = isLeft ? -1.0 : 1.0
            let shoulder = CGPoint(x: top.x + sign * 4.0, y: top.y - 10.0)
            let elbow = CGPoint(x: top.x + sign * 11.0, y: top.y + 1.0)
            let paw = CGPoint(x: top.x + sign * 10.0, y: top.y + 15.0)
            drawLimb(in: ctx, start: shoulder, control: elbow, end: paw, startWidth: 19.0, endWidth: 14.0, outlineOnLeftSide: !isLeft, outlineAlpha: 0.78, skin: skin, frontPaw: true)
            return
        }
        let pal = skin.palette
        let sign: CGFloat = isLeft ? -1.0 : 1.0
        ctx.saveGState()

        if let point = pal.points {
            // Creamy upper leg dipping smoothly into adorable seal-point chocolate socks resting on the keyboard!
            let mid = pal.pointsMid ?? point
            let legRect = CGRect(x: bottom.x - 7.5, y: top.y, width: 15.0, height: bottom.y - top.y + 5.0)
            let legPath = CGPath(roundedRect: legRect, cornerWidth: 6.5, cornerHeight: 6.5, transform: nil)
            ctx.saveGState()
            ctx.addPath(legPath)
            ctx.clip()
            let cs = CGColorSpaceCreateDeviceRGB()
            let colors = [
                pal.body.withAlpha(0.0).cgColor,
                mid.withAlpha(0.75).cgColor,
                point.ns.cgColor
            ] as CFArray
            if let grad = CGGradient(colorsSpace: cs, colors: colors, locations: [0.05, 0.50, 0.82]) {
                ctx.drawLinearGradient(
                    grad,
                    start: CGPoint(x: top.x, y: top.y),
                    end: CGPoint(x: bottom.x, y: bottom.y + 5.0),
                    options: []
                )
            }
            ctx.restoreGState()
        } else {
            // Smooth shoulder-fade leg fill so palette.legs shows cleanly on idle sitting legs too
            // ("idleLegs": "legs"; the built-in coats use "chest" and keep their approved look)
            let legShape = CGMutablePath()
            legShape.move(to: CGPoint(x: top.x + sign * 8.5, y: top.y))
            legShape.addQuadCurve(
                to: CGPoint(x: bottom.x + sign * 7.5, y: bottom.y - 1),
                control: CGPoint(x: top.x + sign * 9.5, y: (top.y + bottom.y) * 0.5)
            )
            legShape.addQuadCurve(
                to: CGPoint(x: bottom.x + sign * 0.8, y: bottom.y + 5.2),
                control: CGPoint(x: bottom.x + sign * 7.0, y: bottom.y + 5.2)
            )
            legShape.addQuadCurve(
                to: CGPoint(x: bottom.x - sign * 6.0, y: bottom.y - 1),
                control: CGPoint(x: bottom.x - sign * 6.2, y: bottom.y + 5.2)
            )
            legShape.addQuadCurve(
                to: CGPoint(x: top.x - sign * 7.0, y: top.y + 4),
                control: CGPoint(x: top.x - sign * 6.5, y: (top.y + bottom.y) * 0.5)
            )
            legShape.closeSubpath()
            if skin.idleLegsTinted {
            ctx.saveGState()
            ctx.addPath(legShape)
            ctx.clip()
            let cs = CGColorSpaceCreateDeviceRGB()
            let legCols = [pal.legs.withAlpha(0.0).cgColor, pal.legs.ns.cgColor, pal.legs.ns.cgColor] as CFArray
            if let legGrad = CGGradient(colorsSpace: cs, colors: legCols, locations: [0.04, 0.32, 1.0]) {
                ctx.drawLinearGradient(
                    legGrad,
                    start: CGPoint(x: top.x, y: top.y),
                    end: CGPoint(x: bottom.x, y: bottom.y + 5.0),
                    options: [.drawsAfterEndLocation]
                )
            }
            ctx.restoreGState()
            }

            let armSpace: SkinSpace = isLeft ? .leftArm : .rightArm
            if skin.hasPartArt(armSpace) {
                let map: (CGPoint) -> CGPoint = { p in
                    let t = max(0, min(1, p.x / 100.0))
                    let cx = top.x + (bottom.x - top.x) * t
                    let cy = top.y + (bottom.y - top.y) * t
                    let hw: CGFloat = 8.0 - 1.2 * t
                    return CGPoint(x: cx + sign * (p.y / 10.0) * hw, y: cy)
                }
                ctx.saveGState()
                ctx.addPath(legShape)
                ctx.clip()
                for region in skin.regions where region.space == armSpace { drawRegion(in: ctx, region, map: map) }
                for mark in skin.marks where mark.space == armSpace { drawMark(in: ctx, mark, map: map) }
                ctx.restoreGState()
            }

            let cuff = CGRect(x: bottom.x - 7.5, y: bottom.y - 13, width: 15, height: 18)
            let cuffPath = CGPath(roundedRect: cuff, cornerWidth: 6.5, cornerHeight: 6.5, transform: nil)
            if CatSettings.shared.whiteOutline {
                ctx.saveGState()
                ctx.setStrokeColor(blackOutlineColor.cgColor)
                ctx.setLineWidth(blackOutlineWidth * 1.8)
                ctx.setLineCap(.round)
                ctx.addArc(center: CGPoint(x: bottom.x, y: bottom.y - 1.5), radius: 7.2, startAngle: 0.15, endAngle: .pi - 0.15, clockwise: false)
                ctx.strokePath()
                ctx.restoreGState()
            }
            ctx.setFillColor(pal.paws.ns.cgColor)
            ctx.addPath(cuffPath)
            ctx.fillPath()
        }
        let lineColor = isClassicBlackRim(skin) ? blackOutlineColor.withAlphaComponent(0.75) : pal.crease.ns
        ctx.setStrokeColor(lineColor.cgColor)
        ctx.setLineWidth(1.45)
        ctx.setLineCap(.round)

        // Outer separation crease
        ctx.move(to: CGPoint(x: top.x + sign * 8.5, y: top.y))
        ctx.addQuadCurve(
            to: CGPoint(x: bottom.x + sign * 7.5, y: bottom.y - 1),
            control: CGPoint(x: top.x + sign * 9.5, y: (top.y + bottom.y) * 0.5)
        )
        // Inner separation crease
        ctx.move(to: CGPoint(x: top.x - sign * 7.0, y: top.y + 4))
        ctx.addQuadCurve(
            to: CGPoint(x: bottom.x - sign * 6.0, y: bottom.y - 1),
            control: CGPoint(x: top.x - sign * 6.5, y: (top.y + bottom.y) * 0.5)
        )
        ctx.strokePath()
        ctx.restoreGState()
    }

    /// Smooth tapered limb + plump rounded paw (solid legs, white socks OR colour-point cream-to-espresso socks!)
    private static func drawLimb(
        in ctx: CGContext,
        start: CGPoint,
        control: CGPoint,
        end: CGPoint,
        startWidth: CGFloat,
        endWidth: CGFloat,
        outlineOnLeftSide: Bool,
        outlineAlpha: CGFloat,
        skin: SkinSpec,
        frontPaw: Bool = false
    ) {
        let pal = skin.palette
        let steps = 14
        var leftEdge: [CGPoint] = []
        var rightEdge: [CGPoint] = []

        for i in 0...steps {
            let t = CGFloat(i) / CGFloat(steps)
            let p = quadPoint(start, control, end, t: t)
            let tan = quadTangent(start, control, end, t: t)
            let len = max(0.001, hypot(tan.x, tan.y))
            let nx = -tan.y / len
            let ny = tan.x / len
            let halfW = (startWidth + (endWidth - startWidth) * t) * 0.5
            leftEdge.append(CGPoint(x: p.x + nx * halfW, y: p.y + ny * halfW))
            rightEdge.append(CGPoint(x: p.x - nx * halfW, y: p.y - ny * halfW))
        }

        let limbPath = CGMutablePath()
        limbPath.move(to: leftEdge[0])
        for pt in leftEdge.dropFirst() { limbPath.addLine(to: pt) }
        for pt in rightEdge.reversed() { limbPath.addLine(to: pt) }
        let tangent = quadTangent(start, control, end, t: 0)
        let length = max(0.001, hypot(tangent.x, tangent.y))
        limbPath.addQuadCurve(to: leftEdge[0], control: CGPoint(
            x: start.x - tangent.x/length*startWidth*0.5,
            y: start.y - tangent.y/length*startWidth*0.5))
        limbPath.closeSubpath()

        let pawR = endWidth * 0.58
        let pawRect = CGRect(x: end.x - pawR, y: end.y - pawR * 0.85, width: pawR * 2, height: pawR * 1.7)
        let lineColor = pal.outline ?? pal.crease

        if skin.renderStyle == .dazed {
            let dazedPawRect = pawRect.insetBy(dx: -pawR * 0.28, dy: -pawR * 0.46)
            if frontPaw {
                drawDazedArm(in: ctx, arm: limbPath, left: leftEdge, right: rightEdge, paw: dazedPawRect)
            } else {
                ctx.saveGState()
                ctx.setFillColor(dazedColor(0xE3C99F))
                ctx.addPath(limbPath)
                ctx.fillPath()
                drawDazedPaw(in: ctx, rect: dazedPawRect)
                ctx.restoreGState()
            }
            return
        }

        ctx.saveGState()
        // Optional sticker-style crisp white outer rim on reaching arms & hind foot for ALL skins
        if CatSettings.shared.whiteOutline {
            ctx.setStrokeColor(blackOutlineColor.cgColor)
            ctx.setLineWidth(blackOutlineWidth * 2.0)
            ctx.setLineCap(.round)
            ctx.setLineJoin(.round)
            let rimStartIdx = isClassicBlackRim(skin) ? 2 : 4
            if leftEdge.count > rimStartIdx + 1 {
                ctx.move(to: leftEdge[rimStartIdx])
                for idx in (rimStartIdx + 1)..<leftEdge.count { ctx.addLine(to: leftEdge[idx]) }
                ctx.strokePath()
            }
            if rightEdge.count > rimStartIdx + 1 {
                ctx.move(to: rightEdge[rimStartIdx])
                for idx in (rimStartIdx + 1)..<rightEdge.count { ctx.addLine(to: rightEdge[idx]) }
                ctx.strokePath()
            }
            ctx.strokeEllipse(in: pawRect)
        }
        if let point = pal.points {
            // Colour-point chocolate-dipped socks gradient along the limb!
            // Starts transparent at shoulder (0.0) so it melts 100% seamlessly into the creamy chest!
            let mid = pal.pointsMid ?? point
            ctx.saveGState()
            ctx.addPath(limbPath)
            ctx.clip()
            let cs = CGColorSpaceCreateDeviceRGB()
            let colors = [
                pal.body.withAlpha(0.0).cgColor,
                pal.body.ns.cgColor,
                mid.ns.cgColor,
                point.ns.cgColor
            ] as CFArray
            if let grad = CGGradient(colorsSpace: cs, colors: colors, locations: [0.0, 0.16, 0.48, 0.78]) {
                ctx.drawLinearGradient(grad, start: start, end: end, options: [.drawsAfterEndLocation])
            }
            ctx.restoreGState()

            // Solid rich espresso-chocolate rounded paw tip (no winding-rule overlap artifacts!)
            ctx.setFillColor(pal.paws.ns.cgColor)
            ctx.fillEllipse(in: pawRect)

            // Clean outer edge outline on the arm (fading in below shoulder) so it reads crisply over light backgrounds
            ctx.setStrokeColor(lineColor.withAlpha(0.72).cgColor)
            ctx.setLineWidth(1.25)
            ctx.setLineCap(.round)
            ctx.setLineJoin(.round)
            let outerEdge = outlineOnLeftSide ? rightEdge : leftEdge
            if outerEdge.count > 4 {
                ctx.move(to: outerEdge[3])
                for idx in 4..<(outerEdge.count - 1) { ctx.addLine(to: outerEdge[idx]) }
                ctx.strokePath()
            }
        } else {
            let limbBaseCol = frontPaw ? pal.legs : (pal.hindLeg ?? pal.legs)
            let limbPawCol = frontPaw ? pal.paws : (pal.hindPaw ?? pal.paws)
            ctx.setFillColor(limbBaseCol.ns.cgColor)
            ctx.addPath(limbPath)
            if frontPaw, let chest = pal.belly, chest != limbBaseCol {
                // White chest fading into the leg colour along the first 30% of the arm.
                ctx.saveGState(); ctx.clip()
                let colors = [chest.ns.cgColor, limbBaseCol.ns.cgColor] as CFArray
                if let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: colors, locations: [0, 0.30]) {
                    ctx.drawLinearGradient(gradient, start: start, end: end,
                                           options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
                }
                ctx.restoreGState()
            } else { ctx.fillPath() }
            let isLeftArm = frontPaw && !outlineOnLeftSide
            let limbSpace: SkinSpace = frontPaw ? (isLeftArm ? .leftArm : .rightArm) : .hindLeg
            if skin.hasPartArt(limbSpace) {
                let sideSign: CGFloat = isLeftArm ? 1.0 : -1.0
                let map: (CGPoint) -> CGPoint = { pt in
                    let t = max(0, min(1, pt.x / 100.0))
                    let p = quadPoint(start, control, end, t: t)
                    let tan = quadTangent(start, control, end, t: t)
                    let len = max(0.001, hypot(tan.x, tan.y))
                    let nx = -tan.y / len, ny = tan.x / len
                    let halfW = (startWidth + (endWidth - startWidth) * t) * 0.5
                    let off = sideSign * (pt.y / 10.0) * halfW
                    return CGPoint(x: p.x + nx * off, y: p.y + ny * off)
                }
                ctx.saveGState()
                ctx.addPath(limbPath)
                ctx.clip()
                for region in skin.regions where region.space == limbSpace { drawRegion(in: ctx, region, map: map) }
                for mark in skin.marks where mark.space == limbSpace { drawMark(in: ctx, mark, map: map) }
                ctx.restoreGState()
            }
            if limbPawCol == limbBaseCol { ctx.setFillColor(limbPawCol.ns.cgColor); ctx.fillEllipse(in: pawRect) }
            else {
                let cuff = CGMutablePath()
                let first = Int(CGFloat(steps) * 0.72)
                cuff.move(to: leftEdge[first])
                for pt in leftEdge.dropFirst(first + 1) { cuff.addLine(to: pt) }
                for pt in rightEdge.dropFirst(first).reversed() { cuff.addLine(to: pt) }
                cuff.closeSubpath()
                ctx.setFillColor(limbPawCol.ns.cgColor); ctx.addPath(cuff); ctx.fillPath()
                ctx.fillEllipse(in: pawRect)
            }
        }

        // Crisp separation stroke along upper-to-mid arm where it crosses the torso
        let highlightEdge = outlineOnLeftSide ? leftEdge : rightEdge
        if highlightEdge.count > 6 && !isClassicBlackRim(skin) {
            let strokeColor = skin.colorpoint
                ? lineColor.withAlpha(outlineAlpha * 0.78)
                : pal.crease.withAlpha(outlineAlpha * 0.9)
            ctx.setStrokeColor(strokeColor.cgColor)
            ctx.setLineWidth(1.35)
            ctx.setLineCap(.round)
            ctx.setLineJoin(.round)
            let startIdx = 2
            let endIdx = Int(CGFloat(highlightEdge.count - 1) * 0.68)
            ctx.move(to: highlightEdge[startIdx])
            for idx in (startIdx + 1)...endIdx {
                ctx.addLine(to: highlightEdge[idx])
            }
            ctx.strokePath()
        }
        ctx.restoreGState()
    }

    // MARK: - Floating Mechanical Keycap Popups

    private static func drawFloatingKeycaps(in ctx: CGContext, physics: CatPhysics) {
        for badge in physics.floatingKeycaps {
            let progress = badge.age / badge.lifetime
            // Spring pop-in scale (starts crisp and readable immediately!)
            let scale: CGFloat
            if badge.age < 0.09 {
                let t = badge.age / 0.09
                scale = 0.72 + 0.38 * sin(t * .pi * 0.65)
            } else if badge.age < 0.18 {
                let t = (badge.age - 0.09) / 0.09
                scale = 1.10 - 0.10 * t
            } else {
                scale = 1.0
            }

            let alpha: CGFloat = progress < 0.62 ? 1.0 : max(0, 1.0 - (progress - 0.62) / 0.38)

            let charCount = badge.label.count
            let fontSize: CGFloat = charCount <= 1 ? 11.5 : 10.0
            let font = NSFont.systemFont(ofSize: fontSize, weight: .bold)
            let attrs: [NSAttributedString.Key: Any] = [
                .font: font,
                .foregroundColor: NSColor(calibratedRed: 0.12, green: 0.12, blue: 0.14, alpha: 1.0)
            ]
            let attrStr = NSAttributedString(string: badge.label, attributes: attrs)
            let strSize = attrStr.size()
            let w: CGFloat = max(23, ceil(strSize.width) + 12)
            let h: CGFloat = 22

            ctx.saveGState()
            ctx.setAlpha(alpha)
            ctx.translateBy(x: badge.position.x, y: badge.position.y)
            ctx.rotate(by: badge.rotation)
            ctx.scaleBy(x: CatSettings.shared.flipHorizontal ? -scale : scale, y: scale)

            // 3D bottom keycap edge / shadow
            let baseRect = CGRect(x: -w * 0.5, y: -h * 0.5 + 2.5, width: w, height: h)
            let basePath = CGPath(roundedRect: baseRect, cornerWidth: 5.5, cornerHeight: 5.5, transform: nil)
            ctx.setFillColor(NSColor(calibratedRed: 0.15, green: 0.15, blue: 0.17, alpha: 0.95).cgColor)
            ctx.addPath(basePath)
            ctx.fillPath()

            // Crisp white mechanical keycap top face
            let faceRect = CGRect(x: -w * 0.5, y: -h * 0.5, width: w, height: h)
            let facePath = CGPath(roundedRect: faceRect, cornerWidth: 5.2, cornerHeight: 5.2, transform: nil)
            ctx.setFillColor(NSColor(calibratedRed: 0.975, green: 0.972, blue: 0.952, alpha: 1.0).cgColor)
            ctx.addPath(facePath)
            ctx.fillPath()

            ctx.setStrokeColor(NSColor(calibratedRed: 0.16, green: 0.16, blue: 0.18, alpha: 1.0).cgColor)
            ctx.setLineWidth(1.45)
            ctx.addPath(facePath)
            ctx.strokePath()

            // Centered bold key label
            let drawPt = CGPoint(x: -strSize.width * 0.5, y: -strSize.height * 0.5 - 0.5)
            NSGraphicsContext.saveGraphicsState()
            let nsCtx = NSGraphicsContext(cgContext: ctx, flipped: true)
            NSGraphicsContext.current = nsCtx
            attrStr.draw(at: drawPt)
            NSGraphicsContext.restoreGraphicsState()

            ctx.restoreGState()
        }
    }

    // MARK: - Subtle Petting Sparkles & Sleep Z

    private static func drawSparkles(in ctx: CGContext, physics: CatPhysics, eyeTheme: EyeColorTheme) {
        for sp in physics.sparkles {
            let p = sp.age / sp.lifetime
            let alpha = sin(min(1.0, p) * .pi)
            ctx.saveGState()
            ctx.setAlpha(alpha * 0.85)
            if sp.isSleepZ {
                let attrs: [NSAttributedString.Key: Any] = [
                    .font: NSFont.systemFont(ofSize: 11 + p * 3, weight: .bold),
                    .foregroundColor: eyeTheme.primaryColor
                ]
                NSGraphicsContext.saveGraphicsState()
                NSGraphicsContext.current = NSGraphicsContext(cgContext: ctx, flipped: true)
                NSAttributedString(string: "z", attributes: attrs).draw(at: sp.position)
                NSGraphicsContext.restoreGraphicsState()
            } else {
                // Tiny glowing chartreuse 4-point star
                let r: CGFloat = 3.5 + p * 1.5
                ctx.translateBy(x: sp.position.x, y: sp.position.y)
                ctx.setFillColor(eyeTheme.primaryColor.cgColor)
                let star = CGMutablePath()
                star.move(to: CGPoint(x: 0, y: -r))
                star.addQuadCurve(to: CGPoint(x: r, y: 0), control: CGPoint(x: 0.8, y: -0.8))
                star.addQuadCurve(to: CGPoint(x: 0, y: r), control: CGPoint(x: 0.8, y: 0.8))
                star.addQuadCurve(to: CGPoint(x: -r, y: 0), control: CGPoint(x: -0.8, y: 0.8))
                star.addQuadCurve(to: CGPoint(x: 0, y: -r), control: CGPoint(x: -0.8, y: -0.8))
                star.closeSubpath()
                ctx.addPath(star)
                ctx.fillPath()
            }
            ctx.restoreGState()
        }
    }

    // MARK: - Non-Intrusive Permission Pill

    private static func drawPermissionPill(in ctx: CGContext, text: String) {
        let r = permissionPillRect
        let path = CGPath(roundedRect: r, cornerWidth: 11, cornerHeight: 11, transform: nil)

        ctx.saveGState()
        ctx.setFillColor(NSColor(calibratedRed: 0.11, green: 0.11, blue: 0.13, alpha: 0.90).cgColor)
        ctx.addPath(path)
        ctx.fillPath()

        ctx.setStrokeColor(NSColor(calibratedRed: 0.79, green: 0.95, blue: 0.25, alpha: 0.90).cgColor)
        ctx.setLineWidth(1.2)
        ctx.addPath(path)
        ctx.strokePath()

        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 10.5, weight: .semibold),
            .foregroundColor: NSColor(calibratedRed: 0.95, green: 0.97, blue: 0.90, alpha: 1.0)
        ]
        let str = NSAttributedString(string: text, attributes: attrs)
        let sz = str.size()
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: ctx, flipped: true)
        str.draw(at: CGPoint(x: r.midX - sz.width * 0.5, y: r.midY - sz.height * 0.5 - 0.5))
        NSGraphicsContext.restoreGraphicsState()

        ctx.restoreGState()
    }

    // MARK: - Geometry & Color Helpers

    private static func keycapLegend(_ key: PhysicalKey) -> String {
        switch key {
        case .escape: return "ESC"
        case .tab: return "⇥"
        case .capsLock: return "⇪"
        case .leftShift, .rightShift: return "⇧"
        case .leftControl, .rightControl: return "⌃"
        case .leftOption, .rightOption: return "⌥"
        case .leftCommand, .rightCommand: return "⌘"
        case .backspace: return "⌫"
        case .enter: return "↵"
        case .space: return ""
        default: return key.badgeLabel
        }
    }

    private static func quadPoint(_ p0: CGPoint, _ p1: CGPoint, _ p2: CGPoint, t: CGFloat) -> CGPoint {
        let mt = 1 - t
        return CGPoint(
            x: mt * mt * p0.x + 2 * mt * t * p1.x + t * t * p2.x,
            y: mt * mt * p0.y + 2 * mt * t * p1.y + t * t * p2.y
        )
    }

    private static func quadTangent(_ p0: CGPoint, _ p1: CGPoint, _ p2: CGPoint, t: CGFloat) -> CGPoint {
        let mt = 1 - t
        return CGPoint(
            x: 2 * mt * (p1.x - p0.x) + 2 * t * (p2.x - p1.x),
            y: 2 * mt * (p1.y - p0.y) + 2 * t * (p2.y - p1.y)
        )
    }

    private static func roundedQuadPath(
        tl: CGPoint, tr: CGPoint, br: CGPoint, bl: CGPoint, radius: CGFloat
    ) -> CGPath {
        let p = CGMutablePath()
        let midTop = CGPoint(x: (tl.x + tr.x) * 0.5, y: (tl.y + tr.y) * 0.5)
        p.move(to: midTop)
        p.addArc(tangent1End: tr, tangent2End: br, radius: radius)
        p.addArc(tangent1End: br, tangent2End: bl, radius: radius)
        p.addArc(tangent1End: bl, tangent2End: tl, radius: radius)
        p.addArc(tangent1End: tl, tangent2End: tr, radius: radius)
        p.closeSubpath()
        return p
    }

    /// HSV → RGB, used by the keyboard marquee for its one-hue-cycle-per-sweep backlight.
    private static func hsvColor(hue h: CGFloat, saturation s: CGFloat, value v: CGFloat) -> NSColor {
        var hue = h.truncatingRemainder(dividingBy: 1.0)
        if hue < 0 { hue += 1 }
        let c = v * s
        let x = c * (1 - abs((hue * 6.0).truncatingRemainder(dividingBy: 2.0) - 1))
        let m = v - c
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0
        switch Int(hue * 6.0) % 6 {
        case 0: r = c; g = x
        case 1: r = x; g = c
        case 2: g = c; b = x
        case 3: g = x; b = c
        case 4: r = x; b = c
        default: r = c; b = x
        }
        return NSColor(calibratedRed: r + m, green: g + m, blue: b + m, alpha: 1.0)
    }

    private static func blendColor(_ a: NSColor, _ b: NSColor, t: CGFloat) -> NSColor {
        let ca = a.usingColorSpace(.deviceRGB) ?? a
        let cb = b.usingColorSpace(.deviceRGB) ?? b
        let clamped = max(0, min(1, t))
        return NSColor(
            calibratedRed: ca.redComponent + (cb.redComponent - ca.redComponent) * clamped,
            green: ca.greenComponent + (cb.greenComponent - ca.greenComponent) * clamped,
            blue: ca.blueComponent + (cb.blueComponent - ca.blueComponent) * clamped,
            alpha: ca.alphaComponent + (cb.alphaComponent - ca.alphaComponent) * clamped
        )
    }

    private static func drawRadialGlow(in ctx: CGContext, center: CGPoint, radius: CGFloat, color: NSColor) {
        let cs = CGColorSpaceCreateDeviceRGB()
        let colors = [color.cgColor, color.withAlphaComponent(0.0).cgColor] as CFArray
        let locs: [CGFloat] = [0.0, 1.0]
        if let grad = CGGradient(colorsSpace: cs, colors: colors, locations: locs) {
            ctx.saveGState()
            ctx.drawRadialGradient(
                grad,
                startCenter: center, startRadius: 0,
                endCenter: center, endRadius: radius,
                options: []
            )
            ctx.restoreGState()
        }
    }

    // MARK: - Pixel-Traced Xiao Douni (Video 1 & Video 2) & Universal Video 1 Drag Renderer

    private static let douniInkColor   = NSColor(calibratedRed: 0.149, green: 0.118, blue: 0.094, alpha: 1.0) // #261E18
    private static let douniCreamColor = NSColor(calibratedRed: 0.965, green: 0.937, blue: 0.902, alpha: 1.0) // #F6EFE6
    private static let douniTaupeColor = NSColor(calibratedRed: 0.659, green: 0.576, blue: 0.482, alpha: 1.0) // #A8937B
    private static let douniIceIris    = NSColor(calibratedRed: 0.847, green: 0.937, blue: 0.918, alpha: 1.0) // #D8EFEA
    private static let douniV2Sclera   = NSColor(calibratedRed: 0.918, green: 0.922, blue: 0.906, alpha: 1.0) // #EAEBE7

    private static func lerp(_ a: CGFloat, _ b: CGFloat, _ t: CGFloat) -> CGFloat {
        a + (b - a) * t
    }

    private static func lerpPt(_ a: CGPoint, _ b: CGPoint, _ t: CGFloat) -> CGPoint {
        CGPoint(x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t)
    }

    private static func smoothstep(_ edge0: CGFloat, _ edge1: CGFloat, _ x: CGFloat) -> CGFloat {
        let t = max(0, min(1, (x - edge0) / max(0.0001, edge1 - edge0)))
        return t * t * (3.0 - 2.0 * t)
    }

    /// Super-rounded marshmallow oval head matching Video 1 & Video 2's flat-topped, chubby-cheeked silhouette.
    private static func douniMochiOvalPath(cx: CGFloat, cy: CGFloat, rx: CGFloat, ry: CGFloat,
                                           kx: CGFloat = 0.63, ky: CGFloat = 0.60) -> CGPath {
        let p = CGMutablePath()
        let top = CGPoint(x: cx, y: cy - ry)
        let right = CGPoint(x: cx + rx, y: cy)
        let bot = CGPoint(x: cx, y: cy + ry)
        let left = CGPoint(x: cx - rx, y: cy)
        p.move(to: top)
        p.addCurve(to: right,
                   control1: CGPoint(x: cx + rx * kx, y: cy - ry),
                   control2: CGPoint(x: cx + rx, y: cy - ry * ky))
        p.addCurve(to: bot,
                   control1: CGPoint(x: cx + rx, y: cy + ry * ky),
                   control2: CGPoint(x: cx + rx * kx, y: cy + ry))
        p.addCurve(to: left,
                   control1: CGPoint(x: cx - rx * kx, y: cy + ry),
                   control2: CGPoint(x: cx - rx, y: cy + ry * ky))
        p.addCurve(to: top,
                   control1: CGPoint(x: cx - rx, y: cy - ry * ky),
                   control2: CGPoint(x: cx - rx * kx, y: cy - ry))
        p.closeSubpath()
        return p
    }

    /// Top-level Xiao Douni scene router inside KuroCat's 360x320 canvas.
    private static func drawDouniScene(
        in ctx: CGContext,
        physics: CatPhysics,
        skin: SkinSpec,
        kbSkin: KeyboardSkinSpec,
        eyeTheme: EyeColorTheme,
        flipped: Bool,
        marquee: Bool
    ) {
        let scruff = max(0, min(1, physics.scruffDrag.value))
        let scruffS = smoothstep(0.0, 1.0, scruff)
        let loafRaw = max(0, min(1, physics.douniLoafBlend.value))
        let loafS = smoothstep(0.0, 1.0, loafRaw)

        if scruff > 0.02 {
            let deskFade = 1.0 - smoothstep(0.0, 0.48, scruffS)
            if deskFade > 0.01 && loafS < 0.85 {
                ctx.saveGState()
                ctx.setAlpha(deskFade * (1.0 - loafS))
                ctx.translateBy(x: 0, y: scruffS * 28.0)
                drawDouniV2InCanvas(in: ctx, physics: physics, skin: skin, kbSkin: kbSkin, eyeTheme: eyeTheme, marquee: marquee)
                ctx.restoreGState()
            }
            if deskFade > 0.01 && loafS > 0.02 {
                ctx.saveGState()
                ctx.setAlpha(deskFade * loafS)
                ctx.translateBy(x: 0, y: scruffS * 20.0)
                drawDouniV1LoafInCanvas(in: ctx, physics: physics, skin: skin, loafMorph: 1.0)
                ctx.restoreGState()
            }
            // Smoothly lift out of her resting seat instead of snapping into place!
            ctx.saveGState()
            ctx.translateBy(x: (1.0 - scruffS) * 40.0 * (1.0 - loafS), y: (1.0 - scruffS) * 30.0)
            drawVideo1DragCatInCanvas(in: ctx, physics: physics, skin: skin, eyeTheme: eyeTheme, lift: scruff)
            ctx.restoreGState()
            return
        }

        // Smooth Disney choreographed morph between Video 2 Desk Scene and Video 1 Mochi Loaf!
        if loafS < 0.99 {
            drawDouniV2InCanvas(
                in: ctx,
                physics: physics,
                skin: skin,
                kbSkin: kbSkin,
                eyeTheme: eyeTheme,
                marquee: marquee,
                loafMorph: loafS
            )
        }

        if loafS > 0.01 {
            drawDouniV1LoafInCanvas(in: ctx, physics: physics, skin: skin, loafMorph: loafS)
        }
    }

    /// Maps Video 1 Rest/Pet/Sleep (1000x750) cleanly into 360x320 canvas with Disney pop-squish align-and-settle morph (zero double ghosting!).
    private static func drawDouniV1LoafInCanvas(
        in ctx: CGContext,
        physics: CatPhysics,
        skin: SkinSpec,
        loafMorph: CGFloat = 1.0
    ) {
        let m = max(0, min(1, loafMorph))
        // Tight swap window [0.36..0.56] right when V2 cat has already glided & squished into Loaf's exact spot!
        let alpha = smoothstep(0.36, 0.56, m)
        guard alpha > 0.01 else { return }
        // Arrival slide finishes by m = 0.62, then playful mochi bounce-settle overshoots flat and rebounds to 1.0!
        let arrive = smoothstep(0.30, 0.64, m)
        let settlePhase = max(0, min(1, (m - 0.52) / 0.48))
        let bounce = sin(settlePhase * .pi) * 0.08 * (1.0 - settlePhase * 0.35)
        ctx.saveGState()
        ctx.setAlpha(alpha)
        let scale: CGFloat = 0.345
        let tx: CGFloat = 20.0 + physics.bodyShiftX.value + (1.0 - arrive) * 26.0
        let ty: CGFloat = 46.0 - (1.0 - arrive) * 14.0
        let pivotX: CGFloat = tx + 440 * scale
        let pivotY: CGFloat = ty + 616 * scale
        let sx: CGFloat = 0.94 + 0.06 * arrive + bounce
        let sy: CGFloat = 1.08 - 0.08 * arrive - bounce * 1.15
        ctx.translateBy(x: pivotX, y: pivotY)
        ctx.scaleBy(x: sx, y: sy)
        ctx.translateBy(x: -pivotX, y: -pivotY)
        ctx.translateBy(x: tx, y: ty)
        ctx.scaleBy(x: scale, y: scale)
        drawDouniV1LoafInSpace(in: ctx, physics: physics, skin: skin, showStatusAccents: true)
        ctx.restoreGState()
    }

    /// Maps Universal Video 1 Drag (1000x750) cleanly into 360x320 canvas for ALL cat skins.
    private static func drawVideo1DragCatInCanvas(
        in ctx: CGContext,
        physics: CatPhysics,
        skin: SkinSpec,
        eyeTheme: EyeColorTheme,
        lift: CGFloat
    ) {
        let liftS = smoothstep(0.0, 1.0, lift)
        // Video 1 timing: brief half-lidded startled face on pickup (< 0.17s) AND landing release, then wide watery eyes!
        let startleTarget: CGFloat
        if physics.isScruffDragging {
            if physics.scruffHoldTime < 0.14 {
                startleTarget = 1.0
            } else {
                startleTarget = max(0, 1.0 - (physics.scruffHoldTime - 0.14) / 0.07)
            }
        } else {
            startleTarget = (physics.scruffDropTimer > 0.01) ? min(1.0, physics.scruffDropTimer / 0.12) : 1.0
        }
        let swing = max(-0.32, min(0.32, physics.scruffSwing.value * 0.38)) + sin(physics.time * 4.6) * 0.055 * (1.0 - startleTarget)

        ctx.saveGState()
        ctx.setAlpha(smoothstep(0.0, 0.22, lift))
        // Generous headroom at top so ears are NEVER clipped when lifted high
        let scale: CGFloat = 0.330
        let tx: CGFloat = 24.0 + physics.bodyShiftX.value - physics.scruffSwing.value * 14.0
        let ty: CGFloat = 68.0 - liftS * 22.0 + physics.scruffSwingY.value * 8.0 + sin(physics.time * 3.8) * 2.5 * (1.0 - startleTarget)
        ctx.translateBy(x: tx, y: ty)
        ctx.scaleBy(x: scale, y: scale)
        drawVideo1DragInSpace(in: ctx, physics: physics, skin: skin, eyeTheme: eyeTheme, startle: startleTarget, swing: swing)
        ctx.restoreGState()
    }

    /// Maps Video 2 Typing/Idle/Mouse/Tablet scene (832x720) cleanly into 360x320 canvas.
    private static func drawDouniV2InCanvas(
        in ctx: CGContext,
        physics: CatPhysics,
        skin: SkinSpec,
        kbSkin: KeyboardSkinSpec,
        eyeTheme: EyeColorTheme,
        marquee: Bool,
        loafMorph: CGFloat = 0
    ) {
        ctx.saveGState()
        let scale: CGFloat = 0.405
        let tx: CGFloat = 14.0 + physics.bodyShiftX.value
        let ty: CGFloat = 22.0
        ctx.translateBy(x: tx, y: ty)
        ctx.scaleBy(x: scale, y: scale)
        drawDouniV2InSpace(
            in: ctx,
            physics: physics,
            skin: skin,
            kbSkin: kbSkin,
            eyeTheme: eyeTheme,
            marquee: marquee,
            showMouse: true,
            poseOverride: nil,
            loafMorph: loafMorph
        )
        ctx.restoreGState()
    }

    // MARK: - V1Space (1000 x 750) Pixel-Exact Video 1 Rest / Pet / Sleep Loaf

    /// Draws Xiao Douni's exact Video 1 Frame 1 flat mochi pancake loaf in 1000x750 coordinates.
    static func drawDouniV1LoafInSpace(
        in ctx: CGContext,
        physics: CatPhysics,
        skin: SkinSpec,
        showStatusAccents: Bool = true
    ) {
        let ink = skin.palette.outline?.ns ?? douniInkColor
        let cream = skin.palette.body.ns
        let taupe = (skin.palette.points ?? skin.palette.paws).ns
        let lw: CGFloat = 13.2

        let isPet = showStatusAccents && (physics.petHeadIntensity > 0.12 || physics.petBodyIntensity > 0.22)
        let isSleep = showStatusAccents && physics.sleepiness > 0.45 && !isPet
        let petAmt = isPet ? max(physics.petHeadIntensity, physics.petBodyIntensity) : 0
        let breathWave = showStatusAccents ? sin(physics.time * (isSleep ? 1.7 : 2.3)) : 0
        let squishY: CGFloat = 1.0 - petAmt * 0.065 + breathWave * (isSleep ? 0.028 : 0.015)
        let squishX: CGFloat = 1.0 + petAmt * 0.032 - breathWave * (isSleep ? 0.014 : 0.008)
        let purrShiftX: CGFloat = isPet ? sin(physics.time * 13.0) * 4.5 * petAmt : 0

        ctx.saveGState()
        // Anchor breathing/petting squish cleanly to the flat bottom resting line (y = 616)
        ctx.translateBy(x: 440 + purrShiftX, y: 616)
        ctx.scaleBy(x: squishX, y: squishY)
        ctx.translateBy(x: -440, y: -616)
        ctx.setLineCap(.round)
        ctx.setLineJoin(.round)

        // 1. Far back paw peeking right (x=778..896, y=476..598)
        let backPaw = CGMutablePath()
        backPaw.move(to: CGPoint(x: 786, y: 492))
        backPaw.addCurve(to: CGPoint(x: 896, y: 554),
                         control1: CGPoint(x: 852, y: 472),
                         control2: CGPoint(x: 898, y: 506))
        backPaw.addCurve(to: CGPoint(x: 830, y: 598),
                         control1: CGPoint(x: 894, y: 590),
                         control2: CGPoint(x: 866, y: 602))
        backPaw.addCurve(to: CGPoint(x: 778, y: 576),
                         control1: CGPoint(x: 802, y: 596),
                         control2: CGPoint(x: 784, y: 588))
        backPaw.closeSubpath()

        // 2. Cream loaf back dome behind head (x=338..842, y=274..596)
        let backDome = CGMutablePath()
        backDome.move(to: CGPoint(x: 338, y: 318))
        backDome.addCurve(to: CGPoint(x: 562, y: 274),
                          control1: CGPoint(x: 400, y: 282),
                          control2: CGPoint(x: 486, y: 272))
        backDome.addCurve(to: CGPoint(x: 838, y: 492),
                          control1: CGPoint(x: 702, y: 278),
                          control2: CGPoint(x: 836, y: 368))
        backDome.addCurve(to: CGPoint(x: 708, y: 594),
                          control1: CGPoint(x: 840, y: 562),
                          control2: CGPoint(x: 790, y: 594))
        backDome.addLine(to: CGPoint(x: 340, y: 590))
        backDome.closeSubpath()

        // 3. Left front paw peeking out under left cheek (x=8..156, y=476..600)
        let leftPaw = CGMutablePath()
        leftPaw.move(to: CGPoint(x: 118, y: 478))
        leftPaw.addCurve(to: CGPoint(x: 8, y: 554),
                         control1: CGPoint(x: 54, y: 474),
                         control2: CGPoint(x: 8, y: 506))
        leftPaw.addCurve(to: CGPoint(x: 86, y: 598),
                         control1: CGPoint(x: 8, y: 590),
                         control2: CGPoint(x: 38, y: 600))
        leftPaw.addLine(to: CGPoint(x: 158, y: 594))
        leftPaw.closeSubpath()

        // 8 (path prebuilt for Pass 0 white sticker rim). Right front paw IN FRONT of lower-right cheek
        let rightPaw = CGMutablePath()
        rightPaw.move(to: CGPoint(x: 542, y: 586))
        rightPaw.addCurve(to: CGPoint(x: 632, y: 508),
                          control1: CGPoint(x: 540, y: 534),
                          control2: CGPoint(x: 576, y: 506))
        rightPaw.addCurve(to: CGPoint(x: 724, y: 588),
                          control1: CGPoint(x: 688, y: 508),
                          control2: CGPoint(x: 724, y: 538))
        rightPaw.addCurve(to: CGPoint(x: 632, y: 635),
                          control1: CGPoint(x: 724, y: 626),
                          control2: CGPoint(x: 682, y: 636))
        rightPaw.addCurve(to: CGPoint(x: 542, y: 586),
                          control1: CGPoint(x: 578, y: 634),
                          control2: CGPoint(x: 544, y: 622))
        rightPaw.closeSubpath()

        // Pass 0: optional crisp sticker-style white outer silhouette rim behind the entire loaf
        if CatSettings.shared.whiteOutline {
            let loafHeadRim = v1UnifiedHeadWithEarsPath(headCX: 380, headCY: 472, headRX: 292, headRY: 144, earTipY: 165, shiftX: 0)
            ctx.saveGState()
            ctx.setStrokeColor(blackOutlineColor.cgColor)
            ctx.setLineWidth(lw + 10.6)
            for p in [backPaw, backDome, leftPaw, loafHeadRim, rightPaw] {
                ctx.addPath(p)
                ctx.strokePath()
            }
            ctx.restoreGState()
        }

        ctx.setFillColor(taupe.cgColor)
        ctx.addPath(backPaw)
        ctx.fillPath()
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw)
        ctx.addPath(backPaw)
        ctx.strokePath()
        // Back paw toe ticks
        ctx.setLineWidth(lw * 0.88)
        ctx.move(to: CGPoint(x: 844, y: 574)); ctx.addLine(to: CGPoint(x: 855, y: 594))
        ctx.move(to: CGPoint(x: 872, y: 562)); ctx.addLine(to: CGPoint(x: 884, y: 580))
        ctx.strokePath()

        ctx.setFillColor(cream.cgColor)
        ctx.addPath(backDome)
        ctx.fillPath()
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw)
        ctx.addPath(backDome)
        ctx.strokePath()

        ctx.setFillColor(taupe.cgColor)
        ctx.addPath(leftPaw)
        ctx.fillPath()
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw)
        ctx.addPath(leftPaw)
        ctx.strokePath()
        // Left paw 2 vertical toe ticks
        ctx.setLineWidth(lw * 0.90)
        ctx.move(to: CGPoint(x: 50, y: 564)); ctx.addLine(to: CGPoint(x: 50, y: 596))
        ctx.move(to: CGPoint(x: 90, y: 562)); ctx.addLine(to: CGPoint(x: 90, y: 596))
        ctx.strokePath()

        // 4–6. Unified Seamless Head + Ears Silhouette (ONE continuous closed outline — zero seam or floating gap!)
        drawV1UnifiedHeadAndEars(
            in: ctx,
            headCX: 380,
            headCY: 472,
            headRX: 292,
            headRY: 144,
            earTipY: 165,
            shiftX: 0,
            cream: cream,
            taupe: taupe,
            ink: ink,
            lw: lw,
            muzzleCenter: CGPoint(x: 376, y: 474),
            muzzleRX: 98,
            muzzleRY: 78,
            petBlushAlpha: isPet ? 0.34 * petAmt : 0
        )

        // 7. Bold dark curved closed-eye lines (︶ ︶)
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw * 1.10)
        ctx.move(to: CGPoint(x: 174, y: 452))
        ctx.addQuadCurve(to: CGPoint(x: 334, y: 488), control: CGPoint(x: 264, y: 453))
        ctx.move(to: CGPoint(x: 410, y: 490))
        ctx.addQuadCurve(to: CGPoint(x: 576, y: 462), control: CGPoint(x: 486, y: 456))
        ctx.strokePath()

        // 8. Right front paw IN FRONT of lower-right cheek (x=540..724, y=506..636)
        ctx.setFillColor(taupe.cgColor)
        ctx.addPath(rightPaw)
        ctx.fillPath()
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw)
        ctx.addPath(rightPaw)
        ctx.strokePath()
        // Right paw 2 vertical toe ticks
        ctx.setLineWidth(lw * 0.90)
        ctx.move(to: CGPoint(x: 591, y: 596)); ctx.addLine(to: CGPoint(x: 591, y: 632))
        ctx.move(to: CGPoint(x: 636, y: 598)); ctx.addLine(to: CGPoint(x: 636, y: 633))
        ctx.strokePath()

        // 9. Whiskers (upper-left \ \ and right shoulder / /)
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw * 0.95)
        ctx.move(to: CGPoint(x: 69, y: 259)); ctx.addLine(to: CGPoint(x: 110, y: 326))
        ctx.move(to: CGPoint(x: 46, y: 307)); ctx.addLine(to: CGPoint(x: 89, y: 341))
        ctx.move(to: CGPoint(x: 614, y: 318)); ctx.addLine(to: CGPoint(x: 636, y: 286))
        ctx.move(to: CGPoint(x: 642, y: 328)); ctx.addLine(to: CGPoint(x: 665, y: 298))
        ctx.strokePath()

        ctx.restoreGState()

        // 10. Optional comic petting heart or sleeping Zzz floating cleanly above the loaf
        if isPet {
            let phase = (physics.time * 1.4).truncatingRemainder(dividingBy: 1.0)
            let hy = 152 - phase * 62
            let hx = 684 + sin(physics.time * 3.2) * 16
            let alpha = min(1.0, (1.0 - phase) * 1.6) * min(1.0, petAmt * 1.4)
            drawComicHeart(in: ctx, center: CGPoint(x: hx, y: hy), size: 32, alpha: alpha, ink: ink)
        } else if isSleep {
            for i in 0..<2 {
                let p = (physics.time * 0.45 + CGFloat(i) * 0.5).truncatingRemainder(dividingBy: 1.0)
                let zx = 668 + p * 74 + sin(p * 5.0) * 12
                let zy = 218 - p * 112
                let alpha = sin(p * .pi) * min(1.0, physics.sleepiness * 1.3)
                let sz: CGFloat = 24 + p * 18
                drawComicZ(in: ctx, center: CGPoint(x: zx, y: zy), size: sz, alpha: alpha, ink: ink)
            }
        }
    }

    // MARK: - V1Space (1000 x 750) Universal Video 1 Lifted / Startled Drag Pose (ALL SKINS!)

    /// Draws the exact Video 1 3/4 arched-back lifted drag pose in 1000x750 coordinates.
    /// `startle`: 1.0 = exact v1_05 half-lidded startle/touchdown; 0.0 = exact v1_06 wide watery eyes + 4 dangling legs + limp tail.
    static func drawVideo1DragInSpace(
        in ctx: CGContext,
        physics: CatPhysics,
        skin: SkinSpec,
        eyeTheme: EyeColorTheme,
        startle: CGFloat,
        swing: CGFloat
    ) {
        let s = max(0, min(1, startle))
        let isDouni = (skin.renderStyle == .douni)
        let isBlackRim = isClassicBlackRim(skin)

        let bodyColor = isDouni ? douniCreamColor : skin.palette.body.ns
        let earOuterColor = isDouni ? douniTaupeColor : skin.palette.earOuter.ns
        let earInnerColor: NSColor? = isDouni ? nil : skin.palette.earInner?.ns
        let pointColor = isDouni ? douniTaupeColor : (skin.palette.points ?? skin.palette.earOuter).ns
        let legColor: NSColor = isDouni ? douniTaupeColor : skin.palette.paws.ns
        let tailColor: NSColor = isDouni ? douniTaupeColor : skin.palette.tail.ns
        let inkColor: NSColor = isDouni
            ? (skin.palette.outline?.ns ?? douniInkColor)
            : (isBlackRim ? NSColor(calibratedWhite: 0.04, alpha: 1.0)
               : (skin.colorpoint ? NSColor(calibratedRed: 0.27, green: 0.21, blue: 0.17, alpha: 1.0)
                  : (skin.palette.outline?.ns ?? NSColor(calibratedRed: 0.16, green: 0.14, blue: 0.12, alpha: 1.0))))
        let toeInkColor: NSColor = isBlackRim ? NSColor(calibratedWhite: 0.85, alpha: 0.34) : inkColor
        let lw: CGFloat = isDouni ? 13.5 : (isBlackRim ? 7.5 : 10.2)
        let whiteRimW: CGFloat = lw + 11.0

        // Interpolated head coordinates: v1_06 (s=0) <-> v1_05 (s=1)
        let headCX = lerp(400, 380, s)
        let headCY = lerp(236, 333, s)
        let headRX: CGFloat = 292
        let headRY = lerp(148, 149, s)
        let headTopY = headCY - headRY // v1_06: 88, v1_05: 184
        let earShiftX = headCX - 380   // v1_06: +20, v1_05: 0
        let earTipY = headTopY - 164   // Full unclipped tall ears! (matches v1_05 exact ear height 164!)

        // Build key paths once so Classic Black can cleanly stroke a unified outer white rim first
        let headPath = v1UnifiedHeadWithEarsPath(headCX: headCX, headCY: headCY, headRX: headRX, headRY: headRY, earTipY: earTipY, shiftX: earShiftX)
        let backPath = v1DragBackPath(startle: s)
        let (tailFill, tailStroke) = v1DragTailPaths(startle: s, swing: swing)
        let (backLeftFill, backLeftStroke) = v1DragBackLeftLegPaths(startle: s, swing: swing)
        let (backRightFill, backRightStroke) = v1DragBackRightLegPaths(startle: s, swing: swing)
        let (frontLeftFill, frontLeftStroke) = v1DragFrontLeftLegPaths(startle: s, swing: swing)
        let (frontRightFill, frontRightStroke) = v1DragFrontRightLegPaths(startle: s, swing: swing)

        ctx.saveGState()
        ctx.setLineCap(.round)
        ctx.setLineJoin(.round)

        // Pass 0 (ALL skins, when whiteOutline is enabled): crisp sticker-style outer white silhouette rim
        if CatSettings.shared.whiteOutline {
            ctx.setStrokeColor(blackOutlineColor.cgColor)
            ctx.setLineWidth(whiteRimW)
            var rimPaths: [CGPath] = [backLeftStroke, backRightStroke, backPath, frontLeftStroke, frontRightStroke, headPath]
            if s < 0.45 { rimPaths.insert(tailStroke, at: 0) }
            for p in rimPaths {
                ctx.addPath(p)
                ctx.strokePath()
            }
        }

        // 1. Limp hanging tail behind right hip (fades behind back during startle/touchdown s -> 1)
        if s < 0.85 {
            ctx.saveGState()
            ctx.setAlpha(1.0 - smoothstep(0.45, 0.85, s))
            ctx.setFillColor(tailColor.cgColor)
            ctx.addPath(tailFill)
            ctx.fillPath()
            if isDouni || skin.colorpoint {
                ctx.saveGState()
                ctx.addPath(tailFill)
                ctx.clip()
                drawVerticalFurGradient(in: ctx, topY: 225, botY: 325, topColor: bodyColor, botColor: tailColor)
                ctx.restoreGState()
            }
            ctx.setStrokeColor(inkColor.cgColor)
            ctx.setLineWidth(lw)
            ctx.addPath(tailStroke)
            ctx.strokePath()
            ctx.restoreGState()
        }

        // 2. Back-left inner leg peeking under belly
        let blToes: [(CGPoint, CGPoint)] = s > 0.85
            ? [(CGPoint(x: lerp(576, 338, s), y: lerp(456, 578, s)), CGPoint(x: lerp(574, 332, s), y: lerp(472, 598, s))),
               (CGPoint(x: lerp(594, 360, s), y: lerp(458, 580, s)), CGPoint(x: lerp(592, 354, s), y: lerp(472, 600, s)))]
            : []
        drawV1Limb(in: ctx, fillPath: backLeftFill, strokePath: backLeftStroke, topColor: bodyColor, pawColor: legColor,
                   gradientTopY: lerp(404, 515, s), gradientBotY: lerp(440, 560, s),
                   useGradient: isDouni || skin.colorpoint, ink: inkColor, toeInk: toeInkColor, lw: lw,
                   toes: blToes)

        // 3. Arched back & torso dome
        ctx.setFillColor(bodyColor.cgColor)
        ctx.addPath(backPath)
        ctx.fillPath()
        if !isDouni {
            ctx.saveGState()
            ctx.addPath(backPath)
            ctx.clip()
            drawV1SkinBackMarkings(in: ctx, skin: skin, startle: s)
            ctx.restoreGState()
        }
        ctx.setStrokeColor(inkColor.cgColor)
        ctx.setLineWidth(lw)
        ctx.addPath(backPath)
        ctx.strokePath()

        // 4. Back-right chubby hind leg (open top seam merges cleanly into rump!)
        let brToes: [(CGPoint, CGPoint)] = {
            let p0 = v1RotatePoint(CGPoint(x: lerp(684, 808, s), y: lerp(452, 574, s)), around: CGPoint(x: lerp(710, 810, s), y: lerp(345, 470, s)), angle: swing * (1 - s))
            let p1 = v1RotatePoint(CGPoint(x: lerp(682, 818, s), y: lerp(485, 600, s)), around: CGPoint(x: lerp(710, 810, s), y: lerp(345, 470, s)), angle: swing * (1 - s))
            let p2 = v1RotatePoint(CGPoint(x: lerp(712, 838, s), y: lerp(455, 566, s)), around: CGPoint(x: lerp(710, 810, s), y: lerp(345, 470, s)), angle: swing * (1 - s))
            let p3 = v1RotatePoint(CGPoint(x: lerp(710, 850, s), y: lerp(486, 592, s)), around: CGPoint(x: lerp(710, 810, s), y: lerp(345, 470, s)), angle: swing * (1 - s))
            return [(p0, p1), (p2, p3)]
        }()
        drawV1Limb(in: ctx, fillPath: backRightFill, strokePath: backRightStroke, topColor: bodyColor, pawColor: legColor,
                   gradientTopY: lerp(330, 468, s), gradientBotY: lerp(405, 540, s),
                   useGradient: isDouni || skin.colorpoint, ink: inkColor, toeInk: toeInkColor, lw: lw, toes: brToes)

        // 5. Front-left & Front-right dangling legs (open top seam merges cleanly into chest!)
        let flPivot = CGPoint(x: lerp(276, 198, s), y: lerp(352, 430, s))
        let flToes: [(CGPoint, CGPoint)] = [
            (v1RotatePoint(CGPoint(x: lerp(272, 108, s), y: lerp(516, 566, s)), around: flPivot, angle: swing * (1 - s)),
             v1RotatePoint(CGPoint(x: lerp(272, 102, s), y: lerp(552, 598, s)), around: flPivot, angle: swing * (1 - s))),
            (v1RotatePoint(CGPoint(x: lerp(304, 146, s), y: lerp(514, 570, s)), around: flPivot, angle: swing * (1 - s)),
             v1RotatePoint(CGPoint(x: lerp(304, 142, s), y: lerp(548, 601, s)), around: flPivot, angle: swing * (1 - s)))
        ]
        drawV1Limb(in: ctx, fillPath: frontLeftFill, strokePath: frontLeftStroke, topColor: bodyColor, pawColor: legColor,
                   gradientTopY: lerp(354, 432, s), gradientBotY: lerp(420, 498, s),
                   useGradient: isDouni || skin.colorpoint, ink: inkColor, toeInk: toeInkColor, lw: lw, toes: flToes)

        let frPivot = CGPoint(x: lerp(514, 586, s), y: lerp(362, 442, s))
        let frToes: [(CGPoint, CGPoint)] = [
            (v1RotatePoint(CGPoint(x: lerp(478, 598, s), y: lerp(532, 592, s)), around: frPivot, angle: swing * (1 - s)),
             v1RotatePoint(CGPoint(x: lerp(478, 598, s), y: lerp(568, 626, s)), around: frPivot, angle: swing * (1 - s))),
            (v1RotatePoint(CGPoint(x: lerp(510, 636, s), y: lerp(534, 590, s)), around: frPivot, angle: swing * (1 - s)),
             v1RotatePoint(CGPoint(x: lerp(510, 638, s), y: lerp(568, 624, s)), around: frPivot, angle: swing * (1 - s)))
        ]
        drawV1Limb(in: ctx, fillPath: frontRightFill, strokePath: frontRightStroke, topColor: bodyColor, pawColor: legColor,
                   gradientTopY: lerp(366, 448, s), gradientBotY: lerp(436, 516, s),
                   useGradient: isDouni || skin.colorpoint, ink: inkColor, toeInk: toeInkColor, lw: lw, toes: frToes)

        // 6–7. Unified Seamless Head + Ears Silhouette (for Douni: ONE continuous unbroken head+ears outline!)
        if isDouni {
            drawV1UnifiedHeadAndEars(
                in: ctx,
                headCX: headCX,
                headCY: headCY,
                headRX: headRX,
                headRY: headRY,
                earTipY: earTipY,
                shiftX: earShiftX,
                cream: bodyColor,
                taupe: pointColor,
                ink: inkColor,
                lw: lw,
                muzzleCenter: CGPoint(x: headCX - 8, y: headCY + lerp(-12, 0, s)),
                muzzleRX: 88,
                muzzleRY: 78,
                petBlushAlpha: 0
            )
        } else {
            drawV1DouniEar(in: ctx, isLeft: true, baseY: headTopY + 8, tipY: earTipY, shiftX: earShiftX,
                           fill: earOuterColor, ink: inkColor, lw: lw, drawTufts: false, innerFill: earInnerColor)
            drawV1DouniEar(in: ctx, isLeft: false, baseY: headTopY + 8, tipY: earTipY, shiftX: earShiftX,
                           fill: earOuterColor, ink: inkColor, lw: lw, drawTufts: false, innerFill: earInnerColor)
            ctx.setFillColor(bodyColor.cgColor)
            ctx.addPath(headPath)
            ctx.fillPath()
            ctx.saveGState()
            ctx.addPath(headPath)
            ctx.clip()
            drawV1SkinHeadMarkings(in: ctx, skin: skin, headCX: headCX, headCY: headCY, headRX: headRX, headRY: headRY)
            ctx.restoreGState()
            ctx.setStrokeColor(inkColor.cgColor)
            ctx.setLineWidth(lw)
            ctx.addPath(headPath)
            ctx.strokePath()
        }

        // 8. Huge Watery Anime Boba Eyes (v1_06 full wide open <-> v1_05 flat half-lidded!)
        let irisColor: NSColor = isDouni
            ? douniIceIris
            : blendColor(skin.palette.iris?.ns ?? eyeTheme.primaryColor, .white, t: 0.28)
        let leftEyeCenter  = CGPoint(x: lerp(273, 268, s), y: lerp(223, 324, s))
        let rightEyeCenter = CGPoint(x: lerp(510, 501, s), y: lerp(222, 324, s))
        let eyeRX: CGFloat = lerp(87, 89, s)
        let eyeRY: CGFloat = lerp(91, 84, s)
        drawV1WateryEye(in: ctx, center: leftEyeCenter, rx: eyeRX, ry: eyeRY, isLeft: true,
                        iris: irisColor, ink: inkColor, lw: lw, startle: s, isBlackRim: isBlackRim)
        drawV1WateryEye(in: ctx, center: rightEyeCenter, rx: eyeRX + 2, ry: eyeRY, isLeft: false,
                        iris: irisColor, ink: inkColor, lw: lw, startle: s, isBlackRim: isBlackRim)

        // Optional cute tiny nose/mouth on patterned non-Douni cats (e.g. OrangeWhite / Calico / Shorthair)
        if !isDouni && !isBlackRim && !skin.colorpoint {
            let noseC = (skin.palette.nose?.ns ?? NSColor(calibratedRed: 0.90, green: 0.56, blue: 0.58, alpha: 0.92))
            ctx.setFillColor(noseC.cgColor)
            let ny = headCY + lerp(44, 52, s)
            ctx.fillEllipse(in: CGRect(x: headCX - 14, y: ny - 9, width: 28, height: 18))
        }

        // 9. Whiskers on upper-left (just like v1_05 & v1_06!)
        ctx.setStrokeColor(isBlackRim ? NSColor(calibratedWhite: 0.92, alpha: 0.90).cgColor : inkColor.cgColor)
        ctx.setLineWidth(lw * 0.92)
        if s < 0.5 {
            ctx.move(to: CGPoint(x: 84, y: 18)); ctx.addLine(to: CGPoint(x: 132, y: 92))
            ctx.move(to: CGPoint(x: 62, y: 74)); ctx.addLine(to: CGPoint(x: 108, y: 108))
        } else {
            ctx.move(to: CGPoint(x: 56, y: 168)); ctx.addLine(to: CGPoint(x: 118, y: 184))
            ctx.move(to: CGPoint(x: 62, y: 222)); ctx.addLine(to: CGPoint(x: 106, y: 214))
        }
        ctx.strokePath()

        ctx.restoreGState()
    }

    // MARK: - V1Space Geometry & Sub-Helpers

    private static func v1RotatePoint(_ pt: CGPoint, around pivot: CGPoint, angle: CGFloat) -> CGPoint {
        let dx = pt.x - pivot.x, dy = pt.y - pivot.y
        let c = cos(angle), s = sin(angle)
        return CGPoint(x: pivot.x + dx * c - dy * s, y: pivot.y + dx * s + dy * c)
    }

    /// ONE continuous closed path pixel-traced directly from Video 1's original head + ears contour (maxErr ~ 1.2px on 1000x750!).
    private static func v1UnifiedHeadWithEarsPath(
        headCX: CGFloat,
        headCY: CGFloat,
        headRX: CGFloat,
        headRY: CGFloat,
        earTipY: CGFloat,
        shiftX: CGFloat
    ) -> CGPath {
        let headTopY    = headCY - headRY
        let leftEarOut  = CGPoint(x: headCX - headRX * 0.709, y: headCY - headRY * 0.903)
        let leftEarTip  = CGPoint(x: 284 + shiftX, y: earTipY)
        let leftEarIn   = CGPoint(x: 339 + shiftX, y: headTopY)
        let rightEarIn  = CGPoint(x: 399 + shiftX, y: headTopY)
        let rightEarTip = CGPoint(x: 460 + shiftX, y: earTipY)
        let rightEarOut = CGPoint(x: headCX + headRX * 0.640, y: headCY - headRY * 0.945)
        let cheekY      = headCY - headRY * 0.021
        let rightCheek  = CGPoint(x: headCX + headRX * 1.000, y: cheekY)
        let chin        = CGPoint(x: headCX, y: headCY + headRY * 1.007)
        let leftCheek   = CGPoint(x: headCX - headRX * 1.002, y: cheekY)

        let p = CGMutablePath()
        p.move(to: leftEarOut)
        // Left ear outer -> tip -> inner (directly traced to v1_01 ink centerline)
        p.addCurve(to: leftEarTip,
                   control1: CGPoint(x: 202 + shiftX, y: lerp(leftEarOut.y, earTipY, 0.345)),
                   control2: CGPoint(x: 214 + shiftX, y: lerp(leftEarOut.y, earTipY, 0.853)))
        p.addCurve(to: leftEarIn,
                   control1: CGPoint(x: 350 + shiftX, y: lerp(leftEarIn.y, earTipY, 0.897)),
                   control2: CGPoint(x: 329 + shiftX, y: lerp(leftEarIn.y, earTipY, 0.320)))
        // Smooth crown bridge between ears
        p.addQuadCurve(to: rightEarIn, control: CGPoint(x: 369 + shiftX, y: headTopY - 1))
        // Right ear inner -> tip -> outer
        p.addCurve(to: rightEarTip,
                   control1: CGPoint(x: 416 + shiftX, y: lerp(rightEarIn.y, earTipY, 0.308)),
                   control2: CGPoint(x: 403 + shiftX, y: lerp(rightEarIn.y, earTipY, 0.856)))
        p.addCurve(to: rightEarOut,
                   control1: CGPoint(x: 529 + shiftX, y: lerp(rightEarOut.y, earTipY, 0.876)),
                   control2: CGPoint(x: 539 + shiftX, y: lerp(rightEarOut.y, earTipY, 0.344)))
        // Full soft plump mochi cheeks directly traced from Video 1 ink centerline (ZERO flat diagonal slopes or corner kinks!)
        p.addCurve(to: rightCheek,
                   control1: CGPoint(x: headCX + headRX * 0.838, y: headCY - headRY * 0.818),
                   control2: CGPoint(x: headCX + headRX * 1.020, y: headCY - headRY * 0.470))
        p.addCurve(to: chin,
                   control1: CGPoint(x: headCX + headRX * 0.976, y: headCY + headRY * 0.924),
                   control2: CGPoint(x: headCX + headRX * 0.352, y: headCY + headRY * 1.054))
        p.addCurve(to: leftCheek,
                   control1: CGPoint(x: headCX - headRX * 0.346, y: headCY + headRY * 1.009),
                   control2: CGPoint(x: headCX - headRX * 0.972, y: headCY + headRY * 0.927))
        p.addCurve(to: leftEarOut,
                   control1: CGPoint(x: headCX - headRX * 1.014, y: headCY - headRY * 0.419),
                   control2: CGPoint(x: headCX - headRX * 0.866, y: headCY - headRY * 0.720))
        p.closeSubpath()
        return p
    }

    private static func drawV1UnifiedHeadAndEars(
        in ctx: CGContext,
        headCX: CGFloat,
        headCY: CGFloat,
        headRX: CGFloat,
        headRY: CGFloat,
        earTipY: CGFloat,
        shiftX: CGFloat,
        cream: NSColor,
        taupe: NSColor,
        ink: NSColor,
        lw: CGFloat,
        muzzleCenter: CGPoint,
        muzzleRX: CGFloat,
        muzzleRY: CGFloat,
        petBlushAlpha: CGFloat
    ) {
        let headTopY = headCY - headRY
        let unified = v1UnifiedHeadWithEarsPath(headCX: headCX, headCY: headCY, headRX: headRX, headRY: headRY, earTipY: earTipY, shiftX: shiftX)

        // 1. Cream base fill across unified head+ears
        ctx.setFillColor(cream.cgColor)
        ctx.addPath(unified)
        ctx.fillPath()

        // 2. Clipped interior shading: soft vertical ear-to-forehead taupe gradients + muzzle + optional blush
        ctx.saveGState()
        ctx.addPath(unified)
        ctx.clip()

        let cs = CGColorSpaceCreateDeviceRGB()
        let earCols = [taupe.cgColor, taupe.cgColor, cream.withAlphaComponent(0.0).cgColor] as CFArray
        if let earGrad = CGGradient(colorsSpace: cs, colors: earCols, locations: [0.0, 0.78, 1.0]) {
            // Left ear clip band (keeps crown bridge pure cream!)
            ctx.saveGState()
            ctx.clip(to: CGRect(x: 145 + shiftX, y: earTipY - 12, width: 205, height: (headTopY + 34) - (earTipY - 12)))
            ctx.drawLinearGradient(earGrad,
                                   start: CGPoint(x: 260 + shiftX, y: earTipY),
                                   end: CGPoint(x: 260 + shiftX, y: headTopY + 28),
                                   options: [.drawsBeforeStartLocation])
            ctx.restoreGState()
            // Right ear clip band
            ctx.saveGState()
            ctx.clip(to: CGRect(x: 390 + shiftX, y: earTipY - 12, width: 205, height: (headTopY + 34) - (earTipY - 12)))
            ctx.drawLinearGradient(earGrad,
                                   start: CGPoint(x: 470 + shiftX, y: earTipY),
                                   end: CGPoint(x: 470 + shiftX, y: headTopY + 28),
                                   options: [.drawsBeforeStartLocation])
            ctx.restoreGState()
        }

        // Soft milk-tea muzzle circle
        drawSoftTaupePatch(in: ctx, center: muzzleCenter, rx: muzzleRX, ry: muzzleRY, color: taupe, solidStop: 0.78)

        if petBlushAlpha > 0.01 {
            let blush = NSColor(calibratedRed: 1.0, green: 0.56, blue: 0.60, alpha: petBlushAlpha)
            ctx.setFillColor(blush.cgColor)
            ctx.fillEllipse(in: CGRect(x: 158 + shiftX, y: headCY + 14, width: 74, height: 34))
            ctx.fillEllipse(in: CGRect(x: 514 + shiftX, y: headCY + 14, width: 74, height: 34))
        }
        ctx.restoreGState()

        // 3. Single unbroken bold ink contour around the fused head + ears!
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw)
        ctx.setLineJoin(.round)
        ctx.setLineCap(.round)
        ctx.addPath(unified)
        ctx.strokePath()

        // 4. Signature 3-stroke inner ear tufts (|||) cleanly anchored inside the fused ears
        drawV1EarTufts(in: ctx, isLeft: true, baseY: headTopY + 12, shiftX: shiftX, ink: ink, lw: lw)
        drawV1EarTufts(in: ctx, isLeft: false, baseY: headTopY + 12, shiftX: shiftX, ink: ink, lw: lw)
    }

    private static func v1EarOpenCGPath(isLeft: Bool, baseY: CGFloat, tipY: CGFloat, shiftX: CGFloat) -> CGPath {
        let p = CGMutablePath()
        if isLeft {
            p.move(to: CGPoint(x: 171 + shiftX, y: baseY + 14))
            p.addCurve(to: CGPoint(x: 278 + shiftX, y: tipY),
                       control1: CGPoint(x: 204 + shiftX, y: lerp(baseY, tipY, 0.56)),
                       control2: CGPoint(x: 242 + shiftX, y: tipY))
            p.addCurve(to: CGPoint(x: 342 + shiftX, y: baseY + 4),
                       control1: CGPoint(x: 318 + shiftX, y: tipY),
                       control2: CGPoint(x: 338 + shiftX, y: lerp(baseY, tipY, 0.48)))
        } else {
            p.move(to: CGPoint(x: 398 + shiftX, y: baseY + 4))
            p.addCurve(to: CGPoint(x: 455 + shiftX, y: tipY),
                       control1: CGPoint(x: 402 + shiftX, y: lerp(baseY, tipY, 0.48)),
                       control2: CGPoint(x: 420 + shiftX, y: tipY))
            p.addCurve(to: CGPoint(x: 568 + shiftX, y: baseY + 14),
                       control1: CGPoint(x: 496 + shiftX, y: tipY),
                       control2: CGPoint(x: 536 + shiftX, y: lerp(baseY, tipY, 0.56)))
        }
        return p
    }

    private static func v1EarCGPath(isLeft: Bool, baseY: CGFloat, tipY: CGFloat, shiftX: CGFloat) -> CGPath {
        let m = v1EarOpenCGPath(isLeft: isLeft, baseY: baseY, tipY: tipY, shiftX: shiftX).mutableCopy()!
        m.closeSubpath()
        return m
    }

    /// Soft vertical gradient covering ONLY the head-crown ink line right under each ear so taupe merges naturally into cream.
    private static func drawV1EarBaseBlend(in ctx: CGContext, isLeft: Bool, baseY: CGFloat, shiftX: CGFloat, cream: NSColor, earFill: NSColor) {
        let rect = isLeft
            ? CGRect(x: 182 + shiftX, y: baseY - 14, width: 154, height: 28)
            : CGRect(x: 403 + shiftX, y: baseY - 14, width: 155, height: 28)
        ctx.saveGState()
        ctx.clip(to: rect)
        drawVerticalFurGradient(in: ctx, topY: baseY - 14, botY: baseY + 12, topColor: earFill, botColor: cream)
        ctx.restoreGState()
    }

    private static func drawV1EarTufts(in ctx: CGContext, isLeft: Bool, baseY: CGFloat, shiftX: CGFloat, ink: NSColor, lw: CGFloat) {
        ctx.saveGState()
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw * 0.85)
        ctx.setLineCap(.round)
        if isLeft {
            ctx.move(to: CGPoint(x: 256 + shiftX, y: baseY - 6)); ctx.addLine(to: CGPoint(x: 248 + shiftX, y: baseY - 34))
            ctx.move(to: CGPoint(x: 282 + shiftX, y: baseY - 7)); ctx.addLine(to: CGPoint(x: 274 + shiftX, y: baseY - 48))
            ctx.move(to: CGPoint(x: 306 + shiftX, y: baseY - 6)); ctx.addLine(to: CGPoint(x: 300 + shiftX, y: baseY - 66))
        } else {
            ctx.move(to: CGPoint(x: 434 + shiftX, y: baseY - 6)); ctx.addLine(to: CGPoint(x: 441 + shiftX, y: baseY - 66))
            ctx.move(to: CGPoint(x: 460 + shiftX, y: baseY - 7)); ctx.addLine(to: CGPoint(x: 469 + shiftX, y: baseY - 48))
            ctx.move(to: CGPoint(x: 486 + shiftX, y: baseY - 6)); ctx.addLine(to: CGPoint(x: 500 + shiftX, y: baseY - 34))
        }
        ctx.strokePath()
        ctx.restoreGState()
    }

    private static func drawV1DouniEar(
        in ctx: CGContext,
        isLeft: Bool,
        baseY: CGFloat,
        tipY: CGFloat,
        shiftX: CGFloat,
        fill: NSColor,
        ink: NSColor,
        lw: CGFloat,
        drawTufts: Bool,
        innerFill: NSColor?
    ) {
        let path = v1EarCGPath(isLeft: isLeft, baseY: baseY, tipY: tipY, shiftX: shiftX)
        ctx.setFillColor(fill.cgColor)
        ctx.addPath(path)
        ctx.fillPath()
        if let inner = innerFill {
            ctx.saveGState()
            ctx.addPath(path)
            ctx.clip()
            let ip = CGMutablePath()
            if isLeft {
                ip.move(to: CGPoint(x: 212 + shiftX, y: baseY + 6))
                ip.addQuadCurve(to: CGPoint(x: 274 + shiftX, y: tipY + 42), control: CGPoint(x: 234 + shiftX, y: lerp(baseY, tipY, 0.45)))
                ip.addQuadCurve(to: CGPoint(x: 320 + shiftX, y: baseY + 6), control: CGPoint(x: 312 + shiftX, y: lerp(baseY, tipY, 0.40)))
            } else {
                ip.move(to: CGPoint(x: 420 + shiftX, y: baseY + 6))
                ip.addQuadCurve(to: CGPoint(x: 458 + shiftX, y: tipY + 42), control: CGPoint(x: 428 + shiftX, y: lerp(baseY, tipY, 0.40)))
                ip.addQuadCurve(to: CGPoint(x: 528 + shiftX, y: baseY + 6), control: CGPoint(x: 504 + shiftX, y: lerp(baseY, tipY, 0.45)))
            }
            ip.closeSubpath()
            ctx.setFillColor(inner.cgColor)
            ctx.addPath(ip)
            ctx.fillPath()
            ctx.restoreGState()
        }
        // Stroke only outer + inner sides (open at bottom so ear merges smoothly into skull!)
        let openPath = v1EarOpenCGPath(isLeft: isLeft, baseY: baseY, tipY: tipY, shiftX: shiftX)
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw)
        ctx.addPath(openPath)
        ctx.strokePath()
        if drawTufts {
            drawV1EarTufts(in: ctx, isLeft: isLeft, baseY: baseY, shiftX: shiftX, ink: ink, lw: lw)
        }
    }

    private static func drawSoftTaupePatch(in ctx: CGContext, center: CGPoint, rx: CGFloat, ry: CGFloat, color: NSColor, solidStop: CGFloat = 0.72) {
        let cs = CGColorSpaceCreateDeviceRGB()
        let cols = [
            color.cgColor,
            color.withAlphaComponent(0.96).cgColor,
            color.withAlphaComponent(0.0).cgColor
        ] as CFArray
        if let grad = CGGradient(colorsSpace: cs, colors: cols, locations: [0.0, solidStop, 1.0]) {
            ctx.saveGState()
            ctx.translateBy(x: center.x, y: center.y)
            ctx.scaleBy(x: rx, y: ry)
            ctx.drawRadialGradient(grad, startCenter: .zero, startRadius: 0, endCenter: .zero, endRadius: 1.0, options: [.drawsBeforeStartLocation])
            ctx.restoreGState()
        }
    }

    private static func drawVerticalFurGradient(in ctx: CGContext, topY: CGFloat, botY: CGFloat, topColor: NSColor, botColor: NSColor) {
        let cs = CGColorSpaceCreateDeviceRGB()
        let cols = [topColor.cgColor, botColor.cgColor] as CFArray
        if let grad = CGGradient(colorsSpace: cs, colors: cols, locations: [0.0, 1.0]) {
            ctx.drawLinearGradient(grad, start: CGPoint(x: 0, y: topY), end: CGPoint(x: 0, y: botY), options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
        }
    }

    private static func drawV1Limb(
        in ctx: CGContext,
        fillPath: CGPath,
        strokePath: CGPath,
        topColor: NSColor,
        pawColor: NSColor,
        gradientTopY: CGFloat,
        gradientBotY: CGFloat,
        useGradient: Bool,
        ink: NSColor,
        toeInk: NSColor,
        lw: CGFloat,
        toes: [(CGPoint, CGPoint)]
    ) {
        ctx.saveGState()
        ctx.addPath(fillPath)
        ctx.clip()
        if useGradient {
            drawVerticalFurGradient(in: ctx, topY: gradientTopY, botY: gradientBotY, topColor: topColor, botColor: pawColor)
        } else {
            ctx.setFillColor(pawColor.cgColor)
            ctx.fill(fillPath.boundingBoxOfPath.insetBy(dx: -4, dy: -4))
        }
        ctx.restoreGState()
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw)
        ctx.addPath(strokePath)
        ctx.strokePath()
        if !toes.isEmpty {
            ctx.setStrokeColor(toeInk.cgColor)
            ctx.setLineWidth(lw * 0.88)
            for (a, b) in toes {
                ctx.move(to: a); ctx.addLine(to: b)
            }
            ctx.strokePath()
        }
    }

    private static func v1DragBackPath(startle s: CGFloat) -> CGPath {
        let p = CGMutablePath()
        p.move(to: CGPoint(x: lerp(346, 352, s), y: lerp(88, 178, s)))
        p.addCurve(to: CGPoint(x: lerp(548, 580, s), y: lerp(-6, 124, s)),
                   control1: CGPoint(x: lerp(418, 420, s), y: lerp(14, 134, s)),
                   control2: CGPoint(x: lerp(488, 514, s), y: lerp(-10, 120, s)))
        p.addCurve(to: CGPoint(x: lerp(765, 836, s), y: lerp(236, 442, s)),
                   control1: CGPoint(x: lerp(672, 744, s), y: lerp(6, 172, s)),
                   control2: CGPoint(x: lerp(768, 838, s), y: lerp(112, 304, s)))
        p.addCurve(to: CGPoint(x: lerp(624, 720, s), y: lerp(414, 540, s)),
                   control1: CGPoint(x: lerp(764, 834, s), y: lerp(348, 526, s)),
                   control2: CGPoint(x: lerp(708, 782, s), y: lerp(412, 542, s)))
        p.addCurve(to: CGPoint(x: lerp(282, 276, s), y: lerp(388, 524, s)),
                   control1: CGPoint(x: lerp(512, 558, s), y: lerp(418, 536, s)),
                   control2: CGPoint(x: lerp(378, 362, s), y: lerp(404, 528, s)))
        p.closeSubpath()
        return p
    }

    private static func v1DragTailPaths(startle s: CGFloat, swing: CGFloat) -> (CGPath, CGPath) {
        let pivot = CGPoint(x: 754, y: 222)
        let ang = swing * 1.18 * (1 - s)
        func pt(_ x: CGFloat, _ y: CGFloat) -> CGPoint { v1RotatePoint(CGPoint(x: x, y: y), around: pivot, angle: ang) }
        let open = CGMutablePath()
        open.move(to: pt(726, 224))
        open.addCurve(to: pt(724, 520), control1: pt(730, 326), control2: pt(722, 444))
        open.addCurve(to: pt(764, 566), control1: pt(726, 554), control2: pt(744, 568))
        open.addCurve(to: pt(804, 504), control1: pt(790, 564), control2: pt(804, 540))
        open.addCurve(to: pt(766, 212), control1: pt(806, 390), control2: pt(796, 286))
        let closed = open.mutableCopy()!
        closed.closeSubpath()
        return (closed, open)
    }

    private static func v1DragBackLeftLegPaths(startle s: CGFloat, swing: CGFloat) -> (CGPath, CGPath) {
        let pivot = CGPoint(x: lerp(590, 368, s), y: lerp(404, 524, s))
        let ang = swing * 0.9 * (1 - s)
        func lp(_ a: CGPoint, _ b: CGPoint) -> CGPoint { v1RotatePoint(lerpPt(a, b, s), around: pivot, angle: ang) }
        let open = CGMutablePath()
        open.move(to: lp(CGPoint(x: 568, y: 404), CGPoint(x: 318, y: 524)))
        open.addCurve(to: lp(CGPoint(x: 586, y: 474), CGPoint(x: 350, y: 602)),
                      control1: lp(CGPoint(x: 564, y: 446), CGPoint(x: 304, y: 576)),
                      control2: lp(CGPoint(x: 572, y: 472), CGPoint(x: 318, y: 602)))
        open.addCurve(to: lp(CGPoint(x: 616, y: 404), CGPoint(x: 434, y: 526)),
                      control1: lp(CGPoint(x: 606, y: 476), CGPoint(x: 398, y: 600)),
                      control2: lp(CGPoint(x: 616, y: 448), CGPoint(x: 428, y: 564)))
        let closed = open.mutableCopy()!
        closed.closeSubpath()
        return (closed, open)
    }

    private static func v1DragBackRightLegPaths(startle s: CGFloat, swing: CGFloat) -> (CGPath, CGPath) {
        let pivot = CGPoint(x: lerp(710, 810, s), y: lerp(345, 470, s))
        let ang = swing * 1.0 * (1 - s)
        func lp(_ a: CGPoint, _ b: CGPoint) -> CGPoint { v1RotatePoint(lerpPt(a, b, s), around: pivot, angle: ang) }
        let open = CGMutablePath()
        open.move(to: lp(CGPoint(x: 654, y: 398), CGPoint(x: 758, y: 526)))
        open.addCurve(to: lp(CGPoint(x: 706, y: 489), CGPoint(x: 822, y: 601)),
                      control1: lp(CGPoint(x: 642, y: 454), CGPoint(x: 760, y: 582)),
                      control2: lp(CGPoint(x: 668, y: 490), CGPoint(x: 786, y: 602)))
        open.addCurve(to: lp(CGPoint(x: 774, y: 332), CGPoint(x: 876, y: 534)),
                      control1: lp(CGPoint(x: 756, y: 486), CGPoint(x: 870, y: 598)),
                      control2: lp(CGPoint(x: 780, y: 424), CGPoint(x: 882, y: 568)))
        open.addCurve(to: lp(CGPoint(x: 756, y: 298), CGPoint(x: 836, y: 468)),
                      control1: lp(CGPoint(x: 770, y: 312), CGPoint(x: 866, y: 492)),
                      control2: lp(CGPoint(x: 762, y: 302), CGPoint(x: 848, y: 474)))
        let closed = open.mutableCopy()!
        closed.closeSubpath()
        return (closed, open)
    }

    private static func v1DragFrontLeftLegPaths(startle s: CGFloat, swing: CGFloat) -> (CGPath, CGPath) {
        let pivot = CGPoint(x: lerp(276, 198, s), y: lerp(352, 430, s))
        let ang = swing * 1.05 * (1 - s)
        func lp(_ a: CGPoint, _ b: CGPoint) -> CGPoint { v1RotatePoint(lerpPt(a, b, s), around: pivot, angle: ang) }
        let open = CGMutablePath()
        open.move(to: lp(CGPoint(x: 208, y: 356), CGPoint(x: 146, y: 428)))
        open.addCurve(to: lp(CGPoint(x: 288, y: 554), CGPoint(x: 138, y: 601)),
                      control1: lp(CGPoint(x: 204, y: 472), CGPoint(x: 66, y: 520)),
                      control2: lp(CGPoint(x: 222, y: 554), CGPoint(x: 74, y: 602)))
        open.addCurve(to: lp(CGPoint(x: 348, y: 376), CGPoint(x: 282, y: 484)),
                      control1: lp(CGPoint(x: 356, y: 554), CGPoint(x: 226, y: 600)),
                      control2: lp(CGPoint(x: 358, y: 478), CGPoint(x: 274, y: 544)))
        let closed = open.mutableCopy()!
        closed.closeSubpath()
        return (closed, open)
    }

    private static func v1DragFrontRightLegPaths(startle s: CGFloat, swing: CGFloat) -> (CGPath, CGPath) {
        let pivot = CGPoint(x: lerp(514, 586, s), y: lerp(362, 442, s))
        let ang = swing * 1.05 * (1 - s)
        func lp(_ a: CGPoint, _ b: CGPoint) -> CGPoint { v1RotatePoint(lerpPt(a, b, s), around: pivot, angle: ang) }
        let open = CGMutablePath()
        open.move(to: lp(CGPoint(x: 458, y: 382), CGPoint(x: 498, y: 472)))
        open.addCurve(to: lp(CGPoint(x: 498, y: 571), CGPoint(x: 616, y: 626)),
                      control1: lp(CGPoint(x: 454, y: 472), CGPoint(x: 494, y: 590)),
                      control2: lp(CGPoint(x: 432, y: 570), CGPoint(x: 558, y: 628)))
        open.addCurve(to: lp(CGPoint(x: 578, y: 372), CGPoint(x: 656, y: 448)),
                      control1: lp(CGPoint(x: 564, y: 570), CGPoint(x: 696, y: 622)),
                      control2: lp(CGPoint(x: 586, y: 482), CGPoint(x: 690, y: 536)))
        let closed = open.mutableCopy()!
        closed.closeSubpath()
        return (closed, open)
    }

    private static func drawV1WateryEye(
        in ctx: CGContext,
        center: CGPoint,
        rx: CGFloat,
        ry: CGFloat,
        isLeft: Bool,
        iris: NSColor,
        ink: NSColor,
        lw: CGFloat,
        startle s: CGFloat,
        isBlackRim: Bool
    ) {
        let eyeRect = CGRect(x: center.x - rx, y: center.y - ry, width: rx * 2, height: ry * 2)
        // Flat horizontal upper eyelid descends across eye when startled (s=1 -> exact y=304 on v1_05!)
        let lidY = center.y - ry - 6 + s * (ry * 0.80)

        ctx.saveGState()
        if s > 0.02 {
            ctx.clip(to: CGRect(x: center.x - rx - 14, y: lidY, width: rx * 2 + 28, height: ry * 2 + 28))
        }

        // 1. Watery iris fill
        ctx.setFillColor(iris.cgColor)
        ctx.fillEllipse(in: eyeRect)

        // 2. Giant glossy black pupil shifted slightly upward so luminous iris forms a thick bottom/outer crescent
        ctx.saveGState()
        ctx.addEllipse(in: eyeRect)
        ctx.clip()
        let pRX = rx * 0.86
        let pRY = ry * 0.81
        let pCenter = CGPoint(x: center.x + (isLeft ? 4 : -2), y: center.y - ry * 0.14 + s * 10)
        ctx.setFillColor(NSColor.black.cgColor)
        ctx.fillEllipse(in: CGRect(x: pCenter.x - pRX, y: pCenter.y - pRY, width: pRX * 2, height: pRY * 2))

        // 3. Two crisp pure-white Video 1 catchlights (large upper round oval + small lower sparkle)
        ctx.setFillColor(NSColor.white.cgColor)
        let bigDX: CGFloat = isLeft ? 19 : -21
        let bigDY: CGFloat = lerp(-34, -4, s)
        let bigRX: CGFloat = isLeft ? 26 : 28
        let bigRY: CGFloat = isLeft ? 21 : 22
        ctx.fillEllipse(in: CGRect(x: center.x + bigDX - bigRX, y: center.y + bigDY - bigRY, width: bigRX * 2, height: bigRY * 2))

        let smDX: CGFloat = isLeft ? 28 : -8
        let smDY: CGFloat = lerp(24, 34, s)
        let smR: CGFloat = 11
        ctx.fillEllipse(in: CGRect(x: center.x + smDX - smR, y: center.y + smDY - smR, width: smR * 2, height: smR * 2))
        ctx.restoreGState()

        // 4. Outer eye border stroke
        ctx.setStrokeColor(isBlackRim ? NSColor(calibratedWhite: 0.16, alpha: 1.0).cgColor : ink.cgColor)
        ctx.setLineWidth(lw * 0.94)
        ctx.strokeEllipse(in: eyeRect)
        ctx.restoreGState()

        // Crisp deadpan flat horizontal upper eyelid line when startled (v1_05!)
        if s > 0.04 {
            let dy = lidY - center.y
            let ratio = max(-0.98, min(0.98, dy / ry))
            let halfSpan = rx * sqrt(max(0.04, 1.0 - ratio * ratio)) + 3
            ctx.saveGState()
            ctx.setStrokeColor(isBlackRim ? NSColor(calibratedWhite: 0.90, alpha: 0.92).cgColor : ink.cgColor)
            ctx.setLineWidth(lw * 0.96)
            ctx.setLineCap(.round)
            ctx.move(to: CGPoint(x: center.x - halfSpan, y: lidY))
            ctx.addLine(to: CGPoint(x: center.x + halfSpan, y: lidY))
            ctx.strokePath()
            ctx.restoreGState()
        }
    }

    /// Projects non-Douni skins' coat patches, Siamese masks, tuxedo bibs, and stripes onto the V1 oval head.
    private static func drawV1SkinHeadMarkings(
        in ctx: CGContext,
        skin: SkinSpec,
        headCX: CGFloat,
        headCY: CGFloat,
        headRX: CGFloat,
        headRY: CGFloat
    ) {
        if skin.colorpoint {
            let seal = (skin.palette.points ?? skin.palette.earOuter).ns
            drawSoftTaupePatch(in: ctx, center: CGPoint(x: headCX, y: headCY + 4), rx: headRX * 0.56, ry: headRY * 0.64, color: seal)
            return
        }
        // Project head/skull bezier regions cleanly into V1 oval head coordinates (part space: roughly x in [-46..46], y in [-34..34])
        let sx = headRX / 44.0
        let sy = headRY / 33.0
        for region in skin.regions where (region.space == .head || region.space == .skull) && region.flat.count >= 3 {
            let p = CGMutablePath()
            for (idx, pt) in region.flat.enumerated() {
                let mapped = CGPoint(x: headCX + pt.x * sx, y: headCY + pt.y * sy)
                if idx == 0 { p.move(to: mapped) } else { p.addLine(to: mapped) }
            }
            p.closeSubpath()
            ctx.setFillColor(region.fill.ns.cgColor)
            ctx.addPath(p)
            ctx.fillPath()
        }
        // Head markings (orange cap / calico patches / tabby stripes / white muzzle)
        for mark in skin.marks where (mark.space == .head || mark.space == .skull) && mark.points.count >= 2 {
            let p = CGMutablePath()
            for (idx, pt) in mark.points.enumerated() {
                let mapped = CGPoint(x: headCX + pt.x * sx, y: headCY + pt.y * sy)
                if idx == 0 { p.move(to: mapped) } else { p.addLine(to: mapped) }
            }
            if mark.stroke {
                ctx.setStrokeColor(mark.color.ns.cgColor)
                ctx.setLineWidth(max(4.0, mark.width * sy))
                ctx.addPath(p)
                ctx.strokePath()
            } else {
                p.closeSubpath()
                ctx.setFillColor(mark.color.ns.cgColor)
                ctx.addPath(p)
                ctx.fillPath()
            }
        }
    }

    private static func drawV1SkinBackMarkings(in ctx: CGContext, skin: SkinSpec, startle s: CGFloat) {
        let bx: CGFloat = lerp(560, 590, s)
        let by: CGFloat = lerp(220, 330, s)
        let sx: CGFloat = 3.6
        let sy: CGFloat = 2.6
        for region in skin.regions where region.space == .body && region.flat.count >= 3 {
            let p = CGMutablePath()
            for (idx, pt) in region.flat.enumerated() {
                let mapped = CGPoint(x: bx + pt.x * sx, y: by + (pt.y + 42) * sy)
                if idx == 0 { p.move(to: mapped) } else { p.addLine(to: mapped) }
            }
            p.closeSubpath()
            ctx.setFillColor(region.fill.ns.cgColor)
            ctx.addPath(p)
            ctx.fillPath()
        }
        for mark in skin.marks where mark.space == .body && mark.points.count >= 2 {
            let p = CGMutablePath()
            for (idx, pt) in mark.points.enumerated() {
                let mapped = CGPoint(x: bx + pt.x * sx, y: by + (pt.y + 42) * sy)
                if idx == 0 { p.move(to: mapped) } else { p.addLine(to: mapped) }
            }
            if mark.stroke {
                ctx.setStrokeColor(mark.color.ns.cgColor)
                ctx.setLineWidth(max(5.0, mark.width * sy))
                ctx.addPath(p)
                ctx.strokePath()
            } else {
                p.closeSubpath()
                ctx.setFillColor(mark.color.ns.cgColor)
                ctx.addPath(p)
                ctx.fillPath()
            }
        }
        if let belly = skin.palette.belly {
            ctx.setFillColor(belly.ns.withAlphaComponent(0.92).cgColor)
            ctx.fillEllipse(in: CGRect(x: bx - 170, y: by + lerp(110, 130, s), width: 290, height: 110))
        }
    }

    private static func drawComicHeart(in ctx: CGContext, center: CGPoint, size: CGFloat, alpha: CGFloat, ink: NSColor) {
        guard alpha > 0.02 else { return }
        ctx.saveGState()
        ctx.setAlpha(alpha)
        ctx.translateBy(x: center.x, y: center.y)
        let p = CGMutablePath()
        p.move(to: CGPoint(x: 0, y: size * 0.65))
        p.addCurve(to: CGPoint(x: -size, y: -size * 0.15),
                   control1: CGPoint(x: -size * 0.65, y: size * 0.35),
                   control2: CGPoint(x: -size, y: size * 0.15))
        p.addCurve(to: CGPoint(x: 0, y: -size * 0.38),
                   control1: CGPoint(x: -size, y: -size * 0.78),
                   control2: CGPoint(x: -size * 0.25, y: -size * 0.82))
        p.addCurve(to: CGPoint(x: size, y: -size * 0.15),
                   control1: CGPoint(x: size * 0.25, y: -size * 0.82),
                   control2: CGPoint(x: size, y: -size * 0.78))
        p.addCurve(to: CGPoint(x: 0, y: size * 0.65),
                   control1: CGPoint(x: size, y: size * 0.15),
                   control2: CGPoint(x: size * 0.65, y: size * 0.35))
        p.closeSubpath()
        ctx.setFillColor(NSColor(calibratedRed: 1.0, green: 0.44, blue: 0.56, alpha: 1.0).cgColor)
        ctx.addPath(p)
        ctx.fillPath()
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(6.5)
        ctx.addPath(p)
        ctx.strokePath()
        ctx.restoreGState()
    }

    private static func drawComicZ(in ctx: CGContext, center: CGPoint, size: CGFloat, alpha: CGFloat, ink: NSColor) {
        guard alpha > 0.02 else { return }
        ctx.saveGState()
        ctx.setAlpha(alpha)
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(7.5)
        ctx.setLineCap(.round)
        ctx.setLineJoin(.round)
        let r = size * 0.55
        ctx.move(to: CGPoint(x: center.x - r, y: center.y - r))
        ctx.addLine(to: CGPoint(x: center.x + r, y: center.y - r))
        ctx.addLine(to: CGPoint(x: center.x - r, y: center.y + r))
        ctx.addLine(to: CGPoint(x: center.x + r, y: center.y + r))
        ctx.strokePath()
        ctx.restoreGState()
    }

    // MARK: - V2Space (832 x 720) Pixel-Exact Video 2 Typing / Idle / Mouse Scene

    /// Draws Xiao Douni's exact Video 2 scene (cat + angled wired hand-drawn keyboard + companion comic mouse/tablet) in 832x720 space.
    /// `poseOverride`: `(leftPose, rightPose, mouseBlend)` where pose ∈ [-1 (slam), 0 (ready), +1 (high)].
    static func drawDouniV2InSpace(
        in ctx: CGContext,
        physics: CatPhysics,
        skin: SkinSpec,
        kbSkin: KeyboardSkinSpec,
        eyeTheme: EyeColorTheme,
        marquee: Bool,
        showMouse: Bool = true,
        poseOverride: (leftPose: CGFloat, rightPose: CGFloat, mouseBlend: CGFloat)? = nil,
        loafMorph: CGFloat = 0
    ) {
        let ink = skin.palette.outline?.ns ?? douniInkColor
        let cream = skin.palette.body.ns
        let taupe = (skin.palette.points ?? skin.palette.paws).ns
        let catLW: CGFloat = 10.8
        let kbLW: CGFloat = 12.6
        let morph = max(0, min(1, loafMorph))

        // Direct independent signed arm poses: -1 = slam down on exact key, 0 = ready (v2_01), +1 = flung high (v2_04/v2_05).
        // Never cancels out to 0 during fast rollover typing or rapid alternation!
        let leftPose: CGFloat
        let rightPose: CGFloat
        let mouseBlend: CGFloat
        if let ov = poseOverride {
            leftPose = ov.leftPose
            rightPose = ov.rightPose
            mouseBlend = ov.mouseBlend
        } else {
            leftPose = max(-1.08, min(1.08, physics.douniLeftRaise.value))
            rightPose = max(-1.08, min(1.08, physics.douniRightRaise.value))
            mouseBlend = max(0, min(1, physics.douniMouseBlend.value))
        }

        let hunt: CGFloat = (poseOverride != nil) ? 0 : max(0, min(1, physics.huntIntensity.value))
        let dizzy: CGFloat = (poseOverride != nil) ? 0 : max(0, min(1, physics.dizzyIntensity.value))
        let anger: CGFloat = (poseOverride != nil) ? 0 : max(0, min(1, physics.angerIntensity.value))
        let isTablet: Bool = (poseOverride == nil) && physics.isTabletActive

        // Disney 12-Principles Typing Secondary Action + Hunting Crouch + Dizzy Wobble + Furious Tremble
        let impY = max(-0.4, min(1.3, physics.kbImpactY.value))
        let impT = max(-0.9, min(0.9, physics.kbImpactTilt.value))
        let dizzyWobble: CGFloat = sin(physics.time * 9.5) * 0.14 * dizzy
        let angerShakeX: CGFloat = anger > 0.08 ? sin(physics.time * 42.0) * 3.2 * anger : 0
        let headTiltRad: CGFloat = -rightPose * 0.010 + leftPose * 0.012 + physics.headTilt.value * 0.08 + impT * 0.014 + dizzyWobble
        let headBobY: CGFloat = abs(leftPose - rightPose) * 2.5 + physics.breathingOffset * 1.4 + impY * 5.2
            + hunt * 16.0 + anger * 5.0 + abs(sin(physics.time * 4.8)) * 9.0 * dizzy
        let headSquashY: CGFloat = 1.0 - max(0, impY) * 0.028 - hunt * 0.062 - anger * 0.022
        let headSquashX: CGFloat = 1.0 + max(0, impY) * 0.014 + hunt * 0.045 + anger * 0.018
        let earLagX: CGFloat = (poseOverride != nil) ? 0 : max(-9, min(9, physics.earTwitch.value * 2.8))
        let earFlare: CGFloat = hunt * 9.0 - anger * 10.0

        // Keyboard colors: Video 2 authentic retro grey by default (`builtin:0`), or synced with custom `.kurokb` skin!
        let useDefaultRetroGrey = (kbSkin.id == "builtin:0")
        let kbDeckColor = useDefaultRetroGrey ? NSColor(calibratedRed: 0.725, green: 0.733, blue: 0.733, alpha: 1.0) : kbSkin.deck.ns
        let kbBevelColor = useDefaultRetroGrey ? NSColor(calibratedRed: 0.608, green: 0.616, blue: 0.612, alpha: 1.0) : kbSkin.base.ns
        let kbKeyColor = useDefaultRetroGrey ? NSColor(calibratedRed: 0.698, green: 0.706, blue: 0.702, alpha: 1.0) : kbSkin.key.ns
        let kbAccentColor = useDefaultRetroGrey ? NSColor(calibratedRed: 0.658, green: 0.666, blue: 0.662, alpha: 1.0) : kbSkin.accent.ns
        let mouseBodyColor = useDefaultRetroGrey ? NSColor(calibratedRed: 0.745, green: 0.753, blue: 0.753, alpha: 1.0) : kbSkin.mouseBody.ns
        let mouseWheelColor = useDefaultRetroGrey ? NSColor(calibratedRed: 0.36, green: 0.35, blue: 0.34, alpha: 1.0) : kbSkin.wheel.ns
        let baseGlow = useDefaultRetroGrey ? NSColor(calibratedRed: 1.0, green: 0.84, blue: 0.24, alpha: 1.0) : eyeTheme.glowColor
        // Shift keycap glow fiery orange-red when fast-typing anger kicks in!
        let glowBaseColor = anger > 0.05
            ? blendColor(baseGlow, NSColor(calibratedRed: 1.0, green: 0.34, blue: 0.14, alpha: 1.0), t: min(0.88, anger * 0.88))
            : baseGlow

        // Choreographed Disney Pop-Squish Morph:
        // Phase 1 (0..0.44): Desk gear glides down & fades; V2 cat stays opaque while gliding down-left, squishing wide & closing eyes!
        // Phase 2 (0.36..0.56): Tight aligned cross-swap right into V1 Loaf at the same spot (ZERO muddy double ghosting!)
        let gearAlpha = 1.0 - smoothstep(0.0, 0.42, morph)
        let gearDropY = smoothstep(0.0, 0.46, morph) * 86.0
        let catAlpha = 1.0 - smoothstep(0.36, 0.56, morph)
        let catGlide = smoothstep(0.0, 0.54, morph)
        let catMorphX = -catGlide * 185.0
        let catMorphY = catGlide * 145.0
        let catMorphSX = 1.0 + catGlide * 0.22
        let catMorphSY = 1.0 - catGlide * 0.28

        // Compute mouse / tablet nib position in V2Space
        let mouseCenter = CGPoint(
            x: 168 + physics.mouseOffset.point.x * 5.2,
            y: 286 + physics.mouseOffset.point.y * 4.5
        )
        let mousePress = max(physics.mousePressLeft.value, physics.mousePressRight.value)
        let nibUV = douniTabletUV(from: physics.tabletNib.point)
        let v2Nib = v2TabletPoint(u: nibUV.u, v: nibUV.v)
        let tabletPress = max(0, min(1, physics.tabletPenPress.value))

        ctx.saveGState()
        ctx.setLineCap(.round)
        ctx.setLineJoin(.round)

        // 1. Companion hand-drawn comic Mouse OR Graphics Tablet (upper-left beside keyboard — zero overlap!)
        if showMouse && gearAlpha > 0.01 {
            ctx.saveGState()
            if morph > 0.005 {
                ctx.setAlpha(gearAlpha)
                ctx.translateBy(x: 0, y: gearDropY)
            }
            if isTablet {
                drawDouniComicTablet(
                    in: ctx,
                    physics: physics,
                    deckColor: kbDeckColor,
                    bevelColor: kbBevelColor,
                    padColor: kbKeyColor,
                    accentColor: kbAccentColor,
                    glowColor: glowBaseColor,
                    eyeColor: eyeTheme.primaryColor,
                    ink: ink,
                    lw: catLW,
                    showParkedStylus: mouseBlend < 0.18
                )
            } else {
                drawDouniComicMouse(
                    in: ctx,
                    center: mouseCenter,
                    pressLeft: physics.mousePressLeft.value,
                    pressRight: physics.mousePressRight.value,
                    bodyColor: mouseBodyColor,
                    bevelColor: kbBevelColor,
                    wheelColor: mouseWheelColor,
                    glowColor: glowBaseColor,
                    ink: ink,
                    lw: catLW
                )
            }
            ctx.restoreGState()
        }

        // 2. Video 2 Cat Back/Torso, Soft Rounded Unified Head+Ears & Expressive Boba Eyes (behind angled keyboard!)
        if catAlpha > 0.01 {
            ctx.saveGState()
            if morph > 0.005 {
                ctx.setAlpha(catAlpha)
                ctx.translateBy(x: 582 + catMorphX, y: 340 + catMorphY)
                ctx.scaleBy(x: catMorphSX, y: catMorphSY)
                ctx.translateBy(x: -582, y: -340)
            }
            ctx.translateBy(x: 582 + angerShakeX, y: 340 + headBobY)
            ctx.rotate(by: headTiltRad)
            ctx.scaleBy(x: headSquashX, y: headSquashY)
            ctx.translateBy(x: -582, y: -340)

            // Pass 0: optional crisp sticker-style outer white silhouette rim behind V2 Douni body + head/ears
            if CatSettings.shared.whiteOutline {
                ctx.saveGState()
                ctx.setStrokeColor(blackOutlineColor.cgColor)
                ctx.setLineWidth(catLW + 9.2)
                ctx.move(to: CGPoint(x: 716, y: 326))
                ctx.addCurve(to: CGPoint(x: 762, y: 444),
                             control1: CGPoint(x: 742, y: 356),
                             control2: CGPoint(x: 758, y: 400))
                ctx.strokePath()
                ctx.addPath(v2UnifiedHeadStrokePath(earLagX: earLagX, earFlare: earFlare))
                ctx.strokePath()
                ctx.restoreGState()
            }

            // 2a. Right shoulder / back descending smoothly behind keyboard top-right edge (x=688..762, y=324..444)
            let bodyPath = CGMutablePath()
            bodyPath.move(to: CGPoint(x: 416, y: 316))
            bodyPath.addLine(to: CGPoint(x: 718, y: 326))
            bodyPath.addCurve(to: CGPoint(x: 762, y: 444),
                              control1: CGPoint(x: 742, y: 358),
                              control2: CGPoint(x: 758, y: 402))
            bodyPath.addLine(to: CGPoint(x: 416, y: 422))
            bodyPath.closeSubpath()
            ctx.setFillColor(cream.cgColor)
            ctx.addPath(bodyPath)
            ctx.fillPath()
            ctx.setStrokeColor(ink.cgColor)
            ctx.setLineWidth(catLW)
            ctx.move(to: CGPoint(x: 716, y: 326))
            ctx.addCurve(to: CGPoint(x: 762, y: 444),
                         control1: CGPoint(x: 742, y: 356),
                         control2: CGPoint(x: 758, y: 400))
            ctx.strokePath()

            // 2b. Whiskers directly traced from Video 2 reference temples (top-left \ \ and top-right / /)
            let wTwitch = hunt > 0.15 ? sin(physics.time * 30.0) * 3.5 * hunt : 0
            ctx.setStrokeColor(ink.cgColor)
            ctx.setLineWidth(catLW * 0.90)
            ctx.move(to: CGPoint(x: 420, y: 168 + wTwitch)); ctx.addLine(to: CGPoint(x: 446, y: 194))
            ctx.move(to: CGPoint(x: 444, y: 146 - wTwitch)); ctx.addLine(to: CGPoint(x: 462, y: 178))
            ctx.move(to: CGPoint(x: 728, y: 206)); ctx.addLine(to: CGPoint(x: 754, y: 174 + wTwitch))
            ctx.move(to: CGPoint(x: 740, y: 224)); ctx.addLine(to: CGPoint(x: 772, y: 208 - wTwitch))
            ctx.strokePath()

            // 2c. ONE Continuous Soft Plump Oval Head + Both Ears Path (zero boxy corners, zero seams!)
            drawV2UnifiedHeadAndEars(
                in: ctx,
                earLagX: earLagX,
                earFlare: earFlare,
                cream: cream,
                taupe: taupe,
                ink: ink,
                lw: catLW,
                angerBlush: anger
            )

            // 2d. Expressive circular boba eyes (normal / hunting starry dilated / dizzy spinning spirals / angry slanted V-brows)
            let gazeX = (poseOverride != nil) ? 0 : physics.eyeGaze.x.value
            let gazeY = (poseOverride != nil) ? 0 : physics.eyeGaze.y.value
            let baseBlink = (poseOverride != nil) ? 0 : physics.blinkProgress
            let blink = max(baseBlink, smoothstep(0.04, 0.44, morph))
            drawV2BobaEye(
                in: ctx,
                center: CGPoint(x: 518, y: 262),
                r: 47.5,
                isLeft: true,
                gazeX: gazeX,
                gazeY: gazeY,
                blink: blink,
                hunt: hunt,
                dizzy: dizzy,
                dizzyPhase: physics.dizzyPhase,
                anger: anger,
                cream: cream,
                ink: ink,
                lw: catLW
            )
            drawV2BobaEye(
                in: ctx,
                center: CGPoint(x: 652, y: 274),
                r: 46.5,
                isLeft: false,
                gazeX: gazeX,
                gazeY: gazeY,
                blink: blink,
                hunt: hunt,
                dizzy: dizzy,
                dizzyPhase: physics.dizzyPhase,
                anger: anger,
                cream: cream,
                ink: ink,
                lw: catLW
            )

            // 2e. Expressive Comic Emotion Accents: Pulsing Red Anger Vein (💢), Alert Hunter Ticks, Orbiting Dizzy Stars!
            if anger > 0.14 {
                let aAlpha = smoothstep(0.14, 0.55, anger)
                let pulse = (1.0 + sin(physics.time * 16.0) * 0.12) * 0.90
                drawDouniAngerVein(in: ctx, center: CGPoint(x: 682, y: 198), scale: pulse, alpha: aAlpha)
            }
            if hunt > 0.35 && dizzy < 0.15 {
                let hAlpha = smoothstep(0.35, 0.78, hunt)
                ctx.saveGState()
                ctx.setAlpha(hAlpha)
                ctx.setStrokeColor(ink.cgColor)
                ctx.setLineWidth(catLW * 0.68)
                // Crisp comic alert excitement sparks beside left ear
                ctx.move(to: CGPoint(x: 472, y: 112)); ctx.addLine(to: CGPoint(x: 454, y: 92))
                ctx.move(to: CGPoint(x: 454, y: 138)); ctx.addLine(to: CGPoint(x: 432, y: 130))
                ctx.strokePath()
                ctx.restoreGState()
            }
            if dizzy > 0.08 {
                drawDouniDizzyStars(in: ctx, center: CGPoint(x: 590, y: 74), phase: physics.dizzyPhase, dizzy: dizzy, ink: ink)
            }

            ctx.restoreGState()
        }

        // 3. Video 2 Hand-Drawn Angled Wired Keyboard with Disney Squash & Stretch, Micro-Shake, Vivid Glowing Keys & Spark Burst!
        if gearAlpha > 0.01 {
            ctx.saveGState()
            if morph > 0.005 {
                ctx.setAlpha(gearAlpha)
                ctx.translateBy(x: 0, y: gearDropY)
            }
            let kbShakeActive = (poseOverride == nil)
            drawDouniV2Keyboard(
                in: ctx,
                physics: physics,
                deckColor: kbDeckColor,
                bevelColor: kbBevelColor,
                keyColor: kbKeyColor,
                accentColor: kbAccentColor,
                glowColor: glowBaseColor,
                marquee: marquee,
                ink: ink,
                lw: kbLW,
                impactY: kbShakeActive ? impY : 0,
                impactTilt: kbShakeActive ? impT : 0
            )
            ctx.restoreGState()
        }

        // 4–5. Chubby Milk-Tea Arms (slapping exact keys / hovering ready / gripping mouse or comic stylus!)
        if catAlpha > 0.01 {
            ctx.saveGState()
            if morph > 0.005 {
                ctx.setAlpha(catAlpha)
                ctx.translateBy(x: 582 + catMorphX, y: 340 + catMorphY)
                ctx.scaleBy(x: catMorphSX, y: catMorphSY)
                ctx.translateBy(x: -582, y: -340)
            }

            // Subtle eager predator paw-tremble when hunting!
            let huntTremble: CGFloat = (hunt > 0.18 && abs(leftPose) < 0.25 && abs(rightPose) < 0.25)
                ? sin(physics.time * 32.0) * 0.08 * hunt : 0
            let effectiveLeftPose = leftPose * (1.0 - morph * 0.85) + huntTremble
            let effectiveRightPose = rightPose * (1.0 - morph * 0.85) - huntTremble
            let effectiveMouseBlend = (showMouse ? mouseBlend : 0) * (1.0 - morph)

            // Left Arm (Cat's Right Arm) — slams DEAD-CENTER onto exact pressed left-half keycap, OR glides onto mouse / grips stylus!
            let lVel = (poseOverride != nil) ? 0 : physics.douniLeftRaise.velocity
            let lTarget: CGPoint? = (poseOverride != nil) ? nil : CGPoint(
                x: physics.douniLeftKeyTarget.point.x + impT * 10.0,
                y: physics.douniLeftKeyTarget.point.y + impY * 8.5
            )
            let leftToolTarget: CGPoint = isTablet
                ? CGPoint(x: v2Nib.x + 14, y: v2Nib.y - 12 + tabletPress * 5.0)
                : CGPoint(x: mouseCenter.x + 8, y: mouseCenter.y - 2 + mousePress * 8)

            drawV2LeftArm(
                in: ctx,
                pose: effectiveLeftPose,
                mouseBlend: effectiveMouseBlend,
                mouseTarget: leftToolTarget,
                slamTarget: lTarget,
                cream: cream,
                taupe: taupe,
                ink: ink,
                lw: catLW,
                swingVelocity: lVel
            )

            // Held Hand-Drawn Comic Stylus gripped right at Douni's left paw when using Graphics Tablet!
            if showMouse && isTablet && effectiveMouseBlend > 0.18 {
                let penAlpha = smoothstep(0.18, 0.42, effectiveMouseBlend)
                ctx.saveGState()
                ctx.setAlpha(penAlpha * catAlpha)
                let nibDrawPt = CGPoint(x: v2Nib.x, y: v2Nib.y + tabletPress * 4.0)
                let penAngle: CGFloat = -2.14 + physics.tabletPenTilt.value
                ctx.translateBy(x: nibDrawPt.x, y: nibDrawPt.y)
                ctx.rotate(by: penAngle)
                drawDouniComicStylus(
                    in: ctx,
                    length: 124.0,
                    accentColor: glowBaseColor,
                    eyeColor: eyeTheme.primaryColor,
                    ink: ink,
                    lw: catLW,
                    pressed: tabletPress
                )
                ctx.restoreGState()
            }

            // Right Arm (Cat's Left Arm) — slams DEAD-CENTER onto exact pressed right-half/spacebar keycap, or flings high across face!
            let rVel = (poseOverride != nil) ? 0 : physics.douniRightRaise.velocity
            let rTarget: CGPoint? = (poseOverride != nil) ? nil : CGPoint(
                x: physics.douniRightKeyTarget.point.x + impT * 10.0,
                y: physics.douniRightKeyTarget.point.y + impY * 8.5
            )
            drawV2RightArm(
                in: ctx,
                pose: effectiveRightPose,
                slamTarget: rTarget,
                cream: cream,
                taupe: taupe,
                ink: ink,
                lw: catLW,
                swingVelocity: rVel
            )

            ctx.restoreGState()
        }

        ctx.restoreGState()
    }

    /// Builds the unified outer contour path pixel-traced directly from Video 2's original head + ears (maxErr ~ 0.8px on 832x720!).
    private static func v2UnifiedHeadStrokePath(earLagX: CGFloat, earFlare: CGFloat = 0) -> CGPath {
        let dxL = earLagX - earFlare
        let dxR = earLagX + earFlare
        let dyPin = max(0, -earFlare) * 0.9
        let neckLeft    = CGPoint(x: 576.0, y: 365.0)
        let leftCheek   = CGPoint(x: 421.0, y: 275.0)
        let leftEarOut  = CGPoint(x: 483.5, y: 180.0)
        let leftEarTip  = CGPoint(x: 573.0 + dxL, y: 62.0 + dyPin)
        let leftEarIn   = CGPoint(x: 596.0, y: 174.0)
        let rightEarIn  = CGPoint(x: 618.0, y: 178.0)
        let rightEarTip = CGPoint(x: 679.5 + dxR, y: 76.0 + dyPin)
        let rightEarOut = CGPoint(x: 714.0, y: 196.0)
        let rightCheek  = CGPoint(x: 757.0, y: 280.0)
        let neckRight   = CGPoint(x: 722.0, y: 350.0)

        let strokePath = CGMutablePath()
        strokePath.move(to: neckLeft)
        strokePath.addCurve(to: leftCheek,
                            control1: CGPoint(x: 520.3, y: 369.5),
                            control2: CGPoint(x: 416.7, y: 351.4))
        strokePath.addCurve(to: leftEarOut,
                            control1: CGPoint(x: 423.2, y: 235.2),
                            control2: CGPoint(x: 442.5, y: 192.8))
        strokePath.addCurve(to: leftEarTip,
                            control1: CGPoint(x: 519.3, y: 147.1),
                            control2: CGPoint(x: 529.2 + dxL * 0.6, y: 90.3 + dyPin * 0.6))
        strokePath.addCurve(to: leftEarIn,
                            control1: CGPoint(x: 596.8 + dxL * 0.4, y: 94.0 + dyPin * 0.5),
                            control2: CGPoint(x: 592.7, y: 136.4))
        strokePath.addQuadCurve(to: rightEarIn, control: CGPoint(x: 607.0, y: 176.0))
        strokePath.addCurve(to: rightEarTip,
                            control1: CGPoint(x: 640.1, y: 146.2),
                            control2: CGPoint(x: 642.6 + dxR * 0.6, y: 97.9 + dyPin * 0.6))
        strokePath.addCurve(to: rightEarOut,
                            control1: CGPoint(x: 717.7 + dxR * 0.4, y: 102.3 + dyPin * 0.5),
                            control2: CGPoint(x: 709.7, y: 155.8))
        strokePath.addCurve(to: rightCheek,
                            control1: CGPoint(x: 738.0, y: 217.2),
                            control2: CGPoint(x: 757.4, y: 246.8))
        strokePath.addCurve(to: neckRight,
                            control1: CGPoint(x: 756.3, y: 307.2),
                            control2: CGPoint(x: 745.0, y: 334.2))
        return strokePath
    }

    /// ONE continuous unified path fusing Video 2's pixel-traced head + both close-set pointed ears.
    private static func drawV2UnifiedHeadAndEars(
        in ctx: CGContext,
        earLagX: CGFloat,
        earFlare: CGFloat = 0,
        cream: NSColor,
        taupe: NSColor,
        ink: NSColor,
        lw: CGFloat,
        angerBlush: CGFloat = 0
    ) {
        let chin        = CGPoint(x: 589.0, y: 366.0)
        let neckLeft    = CGPoint(x: 576.0, y: 365.0)

        let strokePath = v2UnifiedHeadStrokePath(earLagX: earLagX, earFlare: earFlare)

        // Closed fill path bridges cleanly across the cream neck seam
        let fillPath = strokePath.mutableCopy()!
        fillPath.addQuadCurve(to: chin, control: CGPoint(x: 660, y: 366))
        fillPath.addLine(to: neckLeft)
        fillPath.closeSubpath()

        // 1. Cream base fill across unified head+ears
        ctx.setFillColor(cream.cgColor)
        ctx.addPath(fillPath)
        ctx.fillPath()

        // 2. Clipped ear gradients + nose-bridge taupe smudge + optional furious rosy blush!
        ctx.saveGState()
        ctx.addPath(fillPath)
        ctx.clip()
        let cs = CGColorSpaceCreateDeviceRGB()
        let earCols = [taupe.cgColor, taupe.cgColor, cream.withAlphaComponent(0.0).cgColor] as CFArray
        if let earGrad = CGGradient(colorsSpace: cs, colors: earCols, locations: [0.0, 0.72, 1.0]) {
            ctx.saveGState()
            ctx.clip(to: CGRect(x: 472, y: 52, width: 130, height: 158))
            ctx.drawLinearGradient(earGrad, start: CGPoint(x: 545, y: 62), end: CGPoint(x: 545, y: 204), options: [.drawsBeforeStartLocation])
            ctx.restoreGState()
            ctx.saveGState()
            ctx.clip(to: CGRect(x: 612, y: 64, width: 118, height: 158))
            ctx.drawLinearGradient(earGrad, start: CGPoint(x: 672, y: 76), end: CGPoint(x: 672, y: 214), options: [.drawsBeforeStartLocation])
            ctx.restoreGState()
        }
        drawSoftTaupePatch(in: ctx, center: CGPoint(x: 586, y: 270), rx: 52, ry: 48, color: taupe, solidStop: 0.72)
        if angerBlush > 0.08 {
            let bCol = NSColor(calibratedRed: 1.0, green: 0.44, blue: 0.48, alpha: min(0.42, angerBlush * 0.42))
            ctx.setFillColor(bCol.cgColor)
            ctx.fillEllipse(in: CGRect(x: 432, y: 294, width: 56, height: 30))
            ctx.fillEllipse(in: CGRect(x: 680, y: 304, width: 56, height: 30))
        }
        ctx.restoreGState()

        // 3. Single unbroken bold ink contour around the soft fused head + ears!
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw)
        ctx.setLineJoin(.round)
        ctx.setLineCap(.round)
        ctx.addPath(strokePath)
        ctx.strokePath()

        // 4. Inner ear tufts (|||) cleanly anchored inside fused ears
        drawV2EarTufts(in: ctx, isLeft: true, ink: ink, lw: lw)
        drawV2EarTufts(in: ctx, isLeft: false, ink: ink, lw: lw)
    }

    // MARK: - V2Space Sub-Helpers

    private static func drawV2DouniEar(in ctx: CGContext, isLeft: Bool, fill: NSColor, cream: NSColor, ink: NSColor, lw: CGFloat) {
        let p = CGMutablePath()
        if isLeft {
            p.move(to: CGPoint(x: 470, y: 184))
            p.addCurve(to: CGPoint(x: 571, y: 61),
                       control1: CGPoint(x: 492, y: 122),
                       control2: CGPoint(x: 542, y: 63))
            p.addCurve(to: CGPoint(x: 584, y: 180),
                       control1: CGPoint(x: 584, y: 62),
                       control2: CGPoint(x: 588, y: 126))
        } else {
            p.move(to: CGPoint(x: 610, y: 186))
            p.addCurve(to: CGPoint(x: 682, y: 74),
                       control1: CGPoint(x: 626, y: 128),
                       control2: CGPoint(x: 660, y: 74))
            p.addCurve(to: CGPoint(x: 714, y: 198),
                       control1: CGPoint(x: 702, y: 76),
                       control2: CGPoint(x: 714, y: 138))
        }
        p.closeSubpath()
        ctx.saveGState()
        ctx.addPath(p)
        ctx.clip()
        drawVerticalFurGradient(in: ctx, topY: isLeft ? 75 : 88, botY: isLeft ? 186 : 198, topColor: fill, botColor: blendColor(fill, cream, t: 0.30))
        ctx.restoreGState()

        // Stroke outer + inner sides cleanly
        let sPath = CGMutablePath()
        if isLeft {
            sPath.move(to: CGPoint(x: 470, y: 184))
            sPath.addCurve(to: CGPoint(x: 571, y: 61), control1: CGPoint(x: 492, y: 122), control2: CGPoint(x: 542, y: 63))
            sPath.addCurve(to: CGPoint(x: 584, y: 180), control1: CGPoint(x: 584, y: 62), control2: CGPoint(x: 588, y: 126))
        } else {
            sPath.move(to: CGPoint(x: 610, y: 186))
            sPath.addCurve(to: CGPoint(x: 682, y: 74), control1: CGPoint(x: 626, y: 128), control2: CGPoint(x: 660, y: 74))
            sPath.addCurve(to: CGPoint(x: 714, y: 198), control1: CGPoint(x: 702, y: 76), control2: CGPoint(x: 714, y: 138))
        }
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw)
        ctx.addPath(sPath)
        ctx.strokePath()
    }

    private static func drawV2EarTufts(in ctx: CGContext, isLeft: Bool, ink: NSColor, lw: CGFloat) {
        ctx.saveGState()
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw * 0.72)
        ctx.setLineCap(.round)
        if isLeft {
            ctx.move(to: CGPoint(x: 550, y: 176)); ctx.addLine(to: CGPoint(x: 544, y: 158))
            ctx.move(to: CGPoint(x: 564, y: 176)); ctx.addLine(to: CGPoint(x: 558, y: 146))
            ctx.move(to: CGPoint(x: 578, y: 175)); ctx.addLine(to: CGPoint(x: 572, y: 134))
        } else {
            ctx.move(to: CGPoint(x: 632, y: 182)); ctx.addLine(to: CGPoint(x: 644, y: 144))
            ctx.move(to: CGPoint(x: 646, y: 184)); ctx.addLine(to: CGPoint(x: 660, y: 158))
            ctx.move(to: CGPoint(x: 660, y: 186)); ctx.addLine(to: CGPoint(x: 674, y: 172))
        }
        ctx.strokePath()
        ctx.restoreGState()
    }

    private static func drawV2BobaEye(
        in ctx: CGContext,
        center: CGPoint,
        r: CGFloat,
        isLeft: Bool,
        gazeX: CGFloat,
        gazeY: CGFloat,
        blink: CGFloat,
        hunt: CGFloat,
        dizzy: CGFloat,
        dizzyPhase: CGFloat,
        anger: CGFloat,
        cream: NSColor,
        ink: NSColor,
        lw: CGFloat
    ) {
        if blink > 0.72 && dizzy < 0.25 {
            ctx.saveGState()
            ctx.setStrokeColor(ink.cgColor)
            ctx.setLineWidth(lw * 1.05)
            ctx.setLineCap(.round)
            ctx.move(to: CGPoint(x: center.x - r * 0.88, y: center.y + 4))
            ctx.addQuadCurve(to: CGPoint(x: center.x + r * 0.88, y: center.y + 4),
                             control: CGPoint(x: center.x, y: center.y + 14))
            ctx.strokePath()
            ctx.restoreGState()
            return
        }
        let openScaleY = dizzy > 0.28 ? 1.0 : max(0.18, 1.0 - blink * 0.85)
        ctx.saveGState()
        ctx.translateBy(x: center.x, y: center.y)
        ctx.scaleBy(x: 1.0, y: openScaleY)
        let rect = CGRect(x: -r, y: -r, width: r * 2, height: r * 2)

        // 1. Soft pale off-white sclera disc
        ctx.setFillColor(douniV2Sclera.cgColor)
        ctx.fillEllipse(in: rect)

        // 2. Eye interior: either Dizzy Spinning Comic Spiral (@ @) OR Video 2 Boba Pupil (+ Hunting Starry Glints!)
        ctx.saveGState()
        ctx.addEllipse(in: rect)
        ctx.clip()
        if dizzy > 0.28 {
            // Bold hand-drawn Archimedean spiral spinning oppositely per eye!
            let dir: CGFloat = isLeft ? 1.0 : -1.0
            let phase = dizzyPhase * dir
            let sp = CGMutablePath()
            let steps = 44
            let maxTheta: CGFloat = .pi * 4.4
            let maxR: CGFloat = r * 0.78
            for i in 0...steps {
                let t = CGFloat(i) / CGFloat(steps)
                let theta = t * maxTheta + phase
                let rad = t * maxR
                let pt = CGPoint(x: cos(theta) * rad, y: sin(theta) * rad)
                if i == 0 { sp.move(to: pt) } else { sp.addLine(to: pt) }
            }
            ctx.setStrokeColor(ink.cgColor)
            ctx.setLineWidth(lw * 0.72)
            ctx.setLineCap(.round)
            ctx.setLineJoin(.round)
            ctx.addPath(sp)
            ctx.strokePath()
        } else {
            // Giant pure-black circular pupil: default shifted down-left toward keyboard; unlocks & dilates huge during hunting!
            let pr = r * (0.80 + hunt * 0.11)
            let baseX = lerp(-5.5, 0.0, hunt)
            let baseY = lerp(7.5, 0.0, hunt)
            let px = baseX + gazeX * (7.5 + hunt * 10.5)
            let py = baseY + gazeY * (5.5 + hunt * 8.5)
            ctx.setFillColor(NSColor.black.cgColor)
            ctx.fillEllipse(in: CGRect(x: px - pr, y: py - pr, width: pr * 2, height: pr * 2))

            // Sparkling starry hunter catchlights when stalking a fast cursor!
            if hunt > 0.12 {
                let ha = smoothstep(0.12, 0.65, hunt)
                ctx.setFillColor(NSColor.white.withAlphaComponent(ha).cgColor)
                // Crisp 4-point comic star glint upper-left
                let sx = px - pr * 0.34, sy = py - pr * 0.32
                let sr: CGFloat = r * (0.28 + hunt * 0.08)
                let star = CGMutablePath()
                star.move(to: CGPoint(x: sx, y: sy - sr))
                star.addQuadCurve(to: CGPoint(x: sx + sr, y: sy), control: CGPoint(x: sx + sr * 0.18, y: sy - sr * 0.18))
                star.addQuadCurve(to: CGPoint(x: sx, y: sy + sr), control: CGPoint(x: sx + sr * 0.18, y: sy + sr * 0.18))
                star.addQuadCurve(to: CGPoint(x: sx - sr, y: sy), control: CGPoint(x: sx - sr * 0.18, y: sy + sr * 0.18))
                star.addQuadCurve(to: CGPoint(x: sx, y: sy - sr), control: CGPoint(x: sx - sr * 0.18, y: sy - sr * 0.18))
                star.closeSubpath()
                ctx.addPath(star)
                ctx.fillPath()
                // Secondary bright pinpoint lower-right
                let dotR: CGFloat = r * 0.12
                ctx.fillEllipse(in: CGRect(x: px + pr * 0.28 - dotR, y: py + pr * 0.26 - dotR, width: dotR * 2, height: dotR * 2))
            } else if anger > 0.18 {
                // Tiny fierce comic highlight glint when angry-typing
                let fa = smoothstep(0.18, 0.60, anger)
                ctx.setFillColor(NSColor.white.withAlphaComponent(0.85 * fa).cgColor)
                let dotR: CGFloat = r * 0.11
                ctx.fillEllipse(in: CGRect(x: px + (isLeft ? -11 : 11) - dotR, y: py + 6 - dotR, width: dotR * 2, height: dotR * 2))
            }
        }
        ctx.restoreGState()

        // 3. Bold ink border around eye circle
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw * 0.94)
        ctx.strokeEllipse(in: rect)

        // 4. Cleanly clipped comic slanted upper eyelid + bold ink V-brow when angry (ZERO floating brown blocks!)
        if anger > 0.06 && dizzy < 0.25 {
            let a = smoothstep(0.06, 0.72, anger)
            let tiltAngle: CGFloat = (isLeft ? 1.0 : -1.0) * (0.32 * a)
            let lidY: CGFloat = -r + a * (r * 0.62)
            ctx.saveGState()
            ctx.rotate(by: tiltAngle)
            // Mask upper eye slice cleanly with cream fur so the eye genuinely slants fiercely!
            ctx.setFillColor(cream.cgColor)
            ctx.fill(CGRect(x: -r - 16, y: -r - 22, width: r * 2 + 32, height: (lidY - (-r - 22))))
            // Bold hand-drawn curved ink angry brow line right along the slanted eyelid rim
            let span: CGFloat = r * 1.12
            let outerLift: CGFloat = -6.0 * a
            let pL = CGPoint(x: -span, y: lidY + (isLeft ? outerLift : 2.0))
            let pR = CGPoint(x:  span, y: lidY + (isLeft ? 2.0 : outerLift))
            ctx.setStrokeColor(ink.cgColor)
            ctx.setLineWidth(lw * 1.12)
            ctx.setLineCap(.round)
            ctx.move(to: pL)
            ctx.addQuadCurve(to: pR, control: CGPoint(x: 0, y: lidY + 4.0 * a))
            ctx.strokePath()
            ctx.restoreGState()
        }

        ctx.restoreGState()
    }

    /// Bold comic red anger vein (`💢`) matching Video 2's chunky hand-drawn marker aesthetic.
    private static func drawDouniAngerVein(in ctx: CGContext, center: CGPoint, scale: CGFloat, alpha: CGFloat) {
        guard alpha > 0.02 else { return }
        ctx.saveGState()
        ctx.setAlpha(alpha)
        ctx.translateBy(x: center.x, y: center.y)
        ctx.scaleBy(x: scale, y: scale)
        ctx.setStrokeColor(NSColor(calibratedRed: 0.94, green: 0.22, blue: 0.28, alpha: 1.0).cgColor)
        ctx.setLineWidth(8.6)
        ctx.setLineCap(.round)
        ctx.setLineJoin(.round)
        let d: CGFloat = 9.0, r: CGFloat = 24.0
        for (sx, sy): (CGFloat, CGFloat) in [(-1, -1), (1, -1), (-1, 1), (1, 1)] {
            ctx.move(to: CGPoint(x: sx * r, y: sy * d))
            ctx.addQuadCurve(to: CGPoint(x: sx * d, y: sy * r), control: CGPoint(x: sx * d, y: sy * d))
        }
        ctx.strokePath()
        ctx.restoreGState()
    }

    /// 3 orbiting golden hand-drawn comic stars above Xiao Douni's ears when dizzy!
    private static func drawDouniDizzyStars(in ctx: CGContext, center: CGPoint, phase: CGFloat, dizzy: CGFloat, ink: NSColor) {
        let a = smoothstep(0.08, 0.40, dizzy)
        guard a > 0.01 else { return }
        let rx: CGFloat = 136.0, ry: CGFloat = 32.0
        ctx.saveGState()
        ctx.setAlpha(a)
        for i in 0..<3 {
            let ang = phase * 0.72 + CGFloat(i) * (.pi * 2.0 / 3.0)
            let sx = center.x + cos(ang) * rx
            let sy = center.y + sin(ang) * ry
            let sz: CGFloat = 20.0 + sin(ang) * 4.5
            let star = CGMutablePath()
            for k in 0..<8 {
                let ka = CGFloat(k) * (.pi / 4.0) + phase * 0.4
                let rad = (k % 2 == 0) ? sz : sz * 0.42
                let pt = CGPoint(x: sx + cos(ka) * rad, y: sy + sin(ka) * rad)
                if k == 0 { star.move(to: pt) } else { star.addLine(to: pt) }
            }
            star.closeSubpath()
            ctx.setFillColor(NSColor(calibratedRed: 1.0, green: 0.84, blue: 0.24, alpha: 1.0).cgColor)
            ctx.addPath(star)
            ctx.fillPath()
            ctx.setStrokeColor(ink.cgColor)
            ctx.setLineWidth(6.5)
            ctx.setLineJoin(.round)
            ctx.addPath(star)
            ctx.strokePath()
        }
        ctx.restoreGState()
    }

    /// Bilinear interpolation on Xiao Douni's upper-left hand-drawn comic Graphics Tablet in V2Space (`832x720`).
    private static func v2TabletPoint(u: CGFloat, v: CGFloat) -> CGPoint {
        let tl = CGPoint(x: 84, y: 184)
        let tr = CGPoint(x: 268, y: 222)
        let br = CGPoint(x: 192, y: 316)
        let bl = CGPoint(x: 14, y: 274)
        let topX = tl.x + (tr.x - tl.x) * u
        let topY = tl.y + (tr.y - tl.y) * u
        let botX = bl.x + (br.x - bl.x) * u
        let botY = bl.y + (br.y - bl.y) * u
        return CGPoint(x: topX + (botX - topX) * v, y: topY + (botY - topY) * v)
    }

    /// Maps standard 360x320 canvas tablet coordinates (`tabletNib` & `tabletTrail`) into normalized `(u, v)` on Douni's comic tablet!
    private static func douniTabletUV(from canvasPt: CGPoint) -> (u: CGFloat, v: CGFloat) {
        let dx = canvasPt.x - 18.0
        let dy = canvasPt.y - 235.0
        let det: CGFloat = 76.0 * 49.0 - (-5.0) * 5.0
        let u = max(0.06, min(0.94, (dx * 49.0 + dy * 5.0) / det))
        let v = max(0.06, min(0.94, (-dx * 5.0 + dy * 76.0) / det))
        return (u, v)
    }

    /// Bilinear interpolation on Video 2's angled keyboard top surface (`u` left→right, `v` top→bottom).
    private static func v2KbPoint(u: CGFloat, v: CGFloat) -> CGPoint {
        KeyboardLayout.v2KbPoint(u: u, v: v)
    }

    private static func drawDouniV2Keyboard(
        in ctx: CGContext,
        physics: CatPhysics,
        deckColor: NSColor,
        bevelColor: NSColor,
        keyColor: NSColor,
        accentColor: NSColor,
        glowColor: NSColor,
        marquee: Bool,
        ink: NSColor,
        lw: CGFloat,
        impactY: CGFloat = 0,
        impactTilt: CGFloat = 0
    ) {
        let tl = v2KbPoint(u: 0, v: 0)
        let tr = v2KbPoint(u: 1, v: 0)
        let br = v2KbPoint(u: 1, v: 1)
        let bl = v2KbPoint(u: 0, v: 1)
        let depth: CGFloat = 28.0

        // Disney 12-Principles Follow-Through on USB cord (whips & jiggles softly with keyboard impact!)
        let cordWhipX = impactTilt * 24.0
        let cordWhipY = impactY * 12.0
        ctx.saveGState()
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw * 1.05)
        ctx.setLineCap(.round)
        ctx.move(to: CGPoint(x: 268 + impactTilt * 8.0, y: 522 + impactY * 8.0))
        ctx.addCurve(to: CGPoint(x: 224 + cordWhipX * 0.7, y: 598 + cordWhipY * 0.6),
                     control1: CGPoint(x: 220 + cordWhipX * 0.4, y: 536 + cordWhipY * 0.5),
                     control2: CGPoint(x: 218 + cordWhipX * 0.9, y: 572 + cordWhipY * 0.8))
        ctx.addCurve(to: CGPoint(x: 132 + cordWhipX * 0.35, y: 646 + cordWhipY * 0.25),
                     control1: CGPoint(x: 230 + cordWhipX * 0.6, y: 632 + cordWhipY * 0.4),
                     control2: CGPoint(x: 186 + cordWhipX * 0.3, y: 648))
        ctx.strokePath()
        ctx.restoreGState()

        // Disney Squash & Stretch + Micro-Vibration transform on the whole keyboard chassis!
        ctx.saveGState()
        let kbPivot = CGPoint(x: 410, y: 584)
        let sx = 1.0 + max(0, impactY) * 0.026
        let sy = 1.0 - max(0, impactY) * 0.052
        ctx.translateBy(x: kbPivot.x + impactTilt * 11.0, y: kbPivot.y + impactY * 9.5)
        ctx.rotate(by: impactTilt * 0.024)
        ctx.scaleBy(x: sx, y: sy)
        ctx.translateBy(x: -kbPivot.x, y: -kbPivot.y)

        // 2. 3D Underside bevel hull
        let bevelPath = roundedQuadPath(
            tl: CGPoint(x: tl.x, y: tl.y + depth * 0.45),
            tr: CGPoint(x: tr.x, y: tr.y + depth),
            br: CGPoint(x: br.x, y: br.y + depth),
            bl: CGPoint(x: bl.x, y: bl.y + depth * 0.85),
            radius: 28
        )
        ctx.setFillColor(bevelColor.cgColor)
        ctx.addPath(bevelPath)
        ctx.fillPath()
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw)
        ctx.addPath(bevelPath)
        ctx.strokePath()

        // 3. Top deck hull
        let topPath = roundedQuadPath(tl: tl, tr: tr, br: br, bl: bl, radius: 28)
        ctx.setFillColor(deckColor.cgColor)
        ctx.addPath(topPath)
        ctx.fillPath()
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw)
        ctx.addPath(topPath)
        ctx.strokePath()

        // 4. Left smooth rectangular pad (u=0.06..0.28, v=0.14..0.84)
        let padPath = roundedQuadPath(
            tl: v2KbPoint(u: 0.06, v: 0.14),
            tr: v2KbPoint(u: 0.28, v: 0.14),
            br: v2KbPoint(u: 0.28, v: 0.84),
            bl: v2KbPoint(u: 0.06, v: 0.84),
            radius: 14
        )
        ctx.setFillColor(keyColor.cgColor)
        ctx.addPath(padPath)
        ctx.fillPath()
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw * 0.82)
        ctx.addPath(padPath)
        ctx.strokePath()

        // 5. Right keycap well (u=0.31..0.95, v=0.11..0.87) — 4 rows x 8 cols with vivid Disney backlit glow & press travel!
        let wellU0: CGFloat = 0.31, wellU1: CGFloat = 0.95
        let wellV0: CGFloat = 0.11, wellV1: CGFloat = 0.87
        let wellPath = roundedQuadPath(
            tl: v2KbPoint(u: wellU0, v: wellV0),
            tr: v2KbPoint(u: wellU1, v: wellV0),
            br: v2KbPoint(u: wellU1, v: wellV1),
            bl: v2KbPoint(u: wellU0, v: wellV1),
            radius: 16
        )
        ctx.saveGState()
        ctx.setFillColor(keyColor.cgColor)
        ctx.addPath(wellPath)
        ctx.fillPath()
        ctx.addPath(wellPath)
        ctx.clip()

        // Optional RGB marquee wash across keycap well
        if marquee {
            let phase = physics.marqueePhase.truncatingRemainder(dividingBy: 1.0)
            let mCol = hsvColor(hue: phase + 0.52, saturation: 0.58, value: 1.0)
            let cs = CGColorSpaceCreateDeviceRGB()
            let gCols = [mCol.withAlphaComponent(0.32).cgColor, glowColor.withAlphaComponent(0.18).cgColor] as CFArray
            if let grad = CGGradient(colorsSpace: cs, colors: gCols, locations: [0, 1]) {
                ctx.drawLinearGradient(grad, start: v2KbPoint(u: wellU0, v: 0.5), end: v2KbPoint(u: wellU1, v: 0.5), options: [])
            }
        }

        // Map live pressed keys in `physics.keyGlow` onto Video 2's 4x8 keycap grid using exact shared cell mapper!
        var cellGlow = Array(repeating: Array(repeating: CGFloat(0), count: 8), count: 4)
        var sparkCenter: CGPoint? = nil
        for (k, g) in physics.keyGlow where g > 0.03 {
            let info = KeyboardLayout.v2KeyCellInfo(for: k)
            cellGlow[info.row][info.col] = max(cellGlow[info.row][info.col], g)
            if k == physics.kbSparkKey {
                sparkCenter = info.center
            }
        }

        // Fill accent corner keys & VIVIDLY glowing depressed active keys + record bloom centers!
        let rows = 4, cols = 8
        var glowBlooms: [(CGPoint, CGFloat)] = []
        for r in 0..<rows {
            let rv0 = lerp(wellV0, wellV1, CGFloat(r) / CGFloat(rows))
            let rv1 = lerp(wellV0, wellV1, CGFloat(r + 1) / CGFloat(rows))
            for c in 0..<cols {
                if r == 3 && c > 2 && c <= 5 { continue }
                let cEnd = (r == 3 && c == 2) ? 6 : (c + 1)
                let cu0 = lerp(wellU0, wellU1, CGFloat(c) / CGFloat(cols))
                let cu1 = lerp(wellU0, wellU1, CGFloat(cEnd) / CGFloat(cols))
                var g = cellGlow[r][c]
                if r == 3 && c == 2 {
                    for sc in 2..<6 { g = max(g, cellGlow[3][sc]) }
                }
                let isAccent = (r == 0 && c == 0) || (r == 2 && c == 7)
                if isAccent || g > 0.03 {
                    let pTL = v2KbPoint(u: cu0, v: rv0)
                    let pTR = v2KbPoint(u: cu1, v: rv0)
                    let pBR = v2KbPoint(u: cu1, v: rv1)
                    let pBL = v2KbPoint(u: cu0, v: rv1)
                    let kQuad = CGMutablePath()
                    kQuad.move(to: pTL); kQuad.addLine(to: pTR); kQuad.addLine(to: pBR); kQuad.addLine(to: pBL); kQuad.closeSubpath()
                    if g > 0.03 {
                        // Saturated bright glow + crisp hot luminous inner core so active keys POP unmistakably!
                        let vivid = blendColor(glowColor, NSColor(calibratedRed: 1.0, green: 0.96, blue: 0.72, alpha: 1.0), t: min(0.55, g * 0.55))
                        let fill = blendColor(isAccent ? accentColor : keyColor, vivid, t: min(1.0, 0.45 + g * 0.55))
                        ctx.setFillColor(fill.cgColor)
                        ctx.addPath(kQuad)
                        ctx.fillPath()
                        // Subtle inner top press shadow (physical key depression cue!)
                        let pInL = lerpPt(pTL, pBL, 0.24)
                        let pInR = lerpPt(pTR, pBR, 0.24)
                        let dep = CGMutablePath()
                        dep.move(to: pTL); dep.addLine(to: pTR); dep.addLine(to: pInR); dep.addLine(to: pInL); dep.closeSubpath()
                        ctx.setFillColor(NSColor(calibratedWhite: 0, alpha: 0.16 * g).cgColor)
                        ctx.addPath(dep)
                        ctx.fillPath()
                        let ctr = CGPoint(x: (pTL.x + pTR.x + pBR.x + pBL.x) * 0.25, y: (pTL.y + pTR.y + pBR.y + pBL.y) * 0.25)
                        glowBlooms.append((ctr, g))
                    } else {
                        ctx.setFillColor(accentColor.cgColor)
                        ctx.addPath(kQuad)
                        ctx.fillPath()
                    }
                }
            }
        }

        // Crisp hand-drawn grid lines inside keycap well (subtle lighter charcoal on dark .kurokb themes so keys stay sharp!)
        let keyIsDark = (keyColor.usingColorSpace(.deviceRGB)?.brightnessComponent ?? 0.5) < 0.28
        let gridInk = keyIsDark ? NSColor(calibratedRed: 0.34, green: 0.36, blue: 0.41, alpha: 0.92) : ink
        ctx.setStrokeColor(gridInk.cgColor)
        ctx.setLineWidth(lw * 0.78)
        for r in 1..<rows {
            let rv = lerp(wellV0, wellV1, CGFloat(r) / CGFloat(rows))
            ctx.move(to: v2KbPoint(u: wellU0, v: rv))
            ctx.addLine(to: v2KbPoint(u: wellU1, v: rv))
        }
        for c in 1..<cols {
            let cu = lerp(wellU0, wellU1, CGFloat(c) / CGFloat(cols))
            let stopV = (c >= 3 && c <= 5) ? lerp(wellV0, wellV1, 3.0 / 4.0) : wellV1
            ctx.move(to: v2KbPoint(u: cu, v: wellV0))
            ctx.addLine(to: v2KbPoint(u: cu, v: stopV))
        }
        ctx.strokePath()
        ctx.restoreGState()

        // Bold outer border of keycap well
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw * 0.84)
        ctx.addPath(wellPath)
        ctx.strokePath()

        // Soft radiant backlit bloom halos spilling cleanly over each active keycap!
        for (ctr, g) in glowBlooms {
            drawRadialGlow(in: ctx, center: ctr, radius: 56.0 + g * 18.0, color: glowColor.withAlphaComponent(0.62 * g))
        }

        // Disney impact comic spark ticks (\ | /) popping crisply for 0.14s on slap contact!
        if physics.kbSparkTimer > 0.005, let sc = sparkCenter {
            let t = max(0, min(1, physics.kbSparkTimer / 0.14))
            let spread: CGFloat = 14.0 + (1.0 - t) * 26.0
            let len: CGFloat = 14.0 * t + 6.0
            ctx.saveGState()
            ctx.setAlpha(min(1.0, t * 1.4))
            ctx.setLineCap(.round)
            for ang in [-2.35, -1.55, -0.75] as [CGFloat] {
                let p0 = CGPoint(x: sc.x + cos(ang) * spread, y: sc.y + sin(ang) * spread - 6)
                let p1 = CGPoint(x: sc.x + cos(ang) * (spread + len), y: sc.y + sin(ang) * (spread + len) - 6)
                ctx.setStrokeColor(ink.cgColor)
                ctx.setLineWidth(9.5)
                ctx.move(to: p0); ctx.addLine(to: p1); ctx.strokePath()
                ctx.setStrokeColor(glowColor.cgColor)
                ctx.setLineWidth(4.5)
                ctx.move(to: p0); ctx.addLine(to: p1); ctx.strokePath()
            }
            ctx.restoreGState()
        }

        ctx.restoreGState() // end keyboard squash/shake transform
    }

    private static func drawDouniComicMouse(
        in ctx: CGContext,
        center: CGPoint,
        pressLeft: CGFloat,
        pressRight: CGFloat,
        bodyColor: NSColor,
        bevelColor: NSColor,
        wheelColor: NSColor,
        glowColor: NSColor,
        ink: NSColor,
        lw: CGFloat
    ) {
        let pressShift = max(pressLeft, pressRight) * 5.0
        ctx.saveGState()
        // Cute short wavy comic mouse cord trailing up-left
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw * 0.88)
        ctx.setLineCap(.round)
        ctx.move(to: CGPoint(x: center.x - 42, y: center.y - 10 + pressShift))
        ctx.addCurve(to: CGPoint(x: center.x - 102, y: center.y - 16),
                     control1: CGPoint(x: center.x - 66, y: center.y - 36),
                     control2: CGPoint(x: center.x - 86, y: center.y - 42))
        ctx.strokePath()

        ctx.translateBy(x: center.x, y: center.y + pressShift)
        ctx.rotate(by: -0.34) // aligns naturally with Video 2 keyboard's left perspective edge!

        let rx: CGFloat = 46, ry: CGFloat = 33
        // 3D comic bottom lip
        let lipRect = CGRect(x: -rx, y: -ry + 10, width: rx * 2, height: ry * 2)
        ctx.setFillColor(bevelColor.cgColor)
        ctx.fillEllipse(in: lipRect)
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw)
        ctx.strokeEllipse(in: lipRect)

        // Top mouse shell
        let topRect = CGRect(x: -rx, y: -ry, width: rx * 2, height: ry * 2)
        ctx.setFillColor(bodyColor.cgColor)
        ctx.fillEllipse(in: topRect)

        // Left / right button click highlights (cat-facing: buttons are on left/front half away from cat's right palm!)
        if pressLeft > 0.04 || pressRight > 0.04 {
            ctx.saveGState()
            ctx.addEllipse(in: topRect)
            ctx.clip()
            if pressLeft > 0.04 {
                ctx.setFillColor(glowColor.withAlphaComponent(0.55 * pressLeft).cgColor)
                ctx.fill(CGRect(x: -rx, y: 0, width: rx * 0.96, height: ry))
            }
            if pressRight > 0.04 {
                ctx.setFillColor(glowColor.withAlphaComponent(0.55 * pressRight).cgColor)
                ctx.fill(CGRect(x: -rx, y: -ry, width: rx * 0.96, height: ry))
            }
            ctx.restoreGState()
        }

        // Button seam & scroll wheel
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw * 0.72)
        ctx.move(to: CGPoint(x: -4, y: -ry + 4))
        ctx.addQuadCurve(to: CGPoint(x: -4, y: ry - 4), control: CGPoint(x: 4, y: 0))
        ctx.move(to: CGPoint(x: -rx + 5, y: 0))
        ctx.addLine(to: CGPoint(x: -4, y: 0))
        ctx.strokePath()

        // Scroll wheel pill
        let wheelRect = CGRect(x: -29, y: -5.5, width: 17, height: 11)
        let wheelPath = CGPath(roundedRect: wheelRect, cornerWidth: 5, cornerHeight: 5, transform: nil)
        ctx.setFillColor(wheelColor.cgColor)
        ctx.addPath(wheelPath)
        ctx.fillPath()
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw * 0.62)
        ctx.addPath(wheelPath)
        ctx.strokePath()

        // Outer comic shell outline
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw)
        ctx.strokeEllipse(in: topRect)
        ctx.restoreGState()
    }

    /// Hand-drawn chunky comic Graphics Tablet in Video 2's bold-ink aesthetic (with live glowing stroke trail & parked stylus!).
    private static func drawDouniComicTablet(
        in ctx: CGContext,
        physics: CatPhysics,
        deckColor: NSColor,
        bevelColor: NSColor,
        padColor: NSColor,
        accentColor: NSColor,
        glowColor: NSColor,
        eyeColor: NSColor,
        ink: NSColor,
        lw: CGFloat,
        showParkedStylus: Bool
    ) {
        let tl = v2TabletPoint(u: 0, v: 0)
        let tr = v2TabletPoint(u: 1, v: 0)
        let br = v2TabletPoint(u: 1, v: 1)
        let bl = v2TabletPoint(u: 0, v: 1)
        let depth: CGFloat = 16.0

        ctx.saveGState()
        ctx.setLineCap(.round)
        ctx.setLineJoin(.round)

        // 1. Short wavy comic USB cord trailing up-left from tablet top edge
        let cordStart = v2TabletPoint(u: 0.36, v: 0.0)
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw * 0.85)
        ctx.move(to: cordStart)
        ctx.addCurve(to: CGPoint(x: cordStart.x - 74, y: cordStart.y - 42),
                     control1: CGPoint(x: cordStart.x - 16, y: cordStart.y - 42),
                     control2: CGPoint(x: cordStart.x - 50, y: cordStart.y - 54))
        ctx.strokePath()

        // 2. 3D Underside bevel lip
        let bevelPath = roundedQuadPath(
            tl: CGPoint(x: tl.x, y: tl.y + depth * 0.45),
            tr: CGPoint(x: tr.x, y: tr.y + depth),
            br: CGPoint(x: br.x, y: br.y + depth),
            bl: CGPoint(x: bl.x, y: bl.y + depth * 0.85),
            radius: 18
        )
        ctx.setFillColor(bevelColor.cgColor)
        ctx.addPath(bevelPath)
        ctx.fillPath()
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw)
        ctx.addPath(bevelPath)
        ctx.strokePath()

        // 3. Top tablet hull
        let topPath = roundedQuadPath(tl: tl, tr: tr, br: br, bl: bl, radius: 18)
        ctx.setFillColor(deckColor.cgColor)
        ctx.addPath(topPath)
        ctx.fillPath()
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw)
        ctx.addPath(topPath)
        ctx.strokePath()

        // 4. Recessed active drawing surface pad (u = 0.23..0.93, v = 0.12..0.88)
        let padPath = roundedQuadPath(
            tl: v2TabletPoint(u: 0.23, v: 0.12),
            tr: v2TabletPoint(u: 0.93, v: 0.12),
            br: v2TabletPoint(u: 0.93, v: 0.88),
            bl: v2TabletPoint(u: 0.23, v: 0.88),
            radius: 12
        )
        ctx.setFillColor(padColor.cgColor)
        ctx.addPath(padPath)
        ctx.fillPath()

        // Active-area corner L-brackets ([ ]) & live glowing ink stroke trail clipped inside pad!
        ctx.saveGState()
        ctx.addPath(padPath)
        ctx.clip()

        let padIsDark = (padColor.usingColorSpace(.deviceRGB)?.brightnessComponent ?? 0.5) < 0.30
        let bracketCol = padIsDark
            ? NSColor(calibratedWhite: 0.86, alpha: 0.48)
            : ink.withAlphaComponent(0.45)
        ctx.setStrokeColor(bracketCol.cgColor)
        ctx.setLineWidth(lw * 0.45)
        let corners: [(CGFloat, CGFloat, CGFloat, CGFloat)] = [
            (0.28, 0.20,  0.09,  0.14),
            (0.88, 0.20, -0.09,  0.14),
            (0.28, 0.80,  0.09, -0.14),
            (0.88, 0.80, -0.09, -0.14)
        ]
        for (cu, cv, du, dv) in corners {
            let c = v2TabletPoint(u: cu, v: cv)
            let h = v2TabletPoint(u: cu + du, v: cv)
            let v = v2TabletPoint(u: cu, v: cv + dv)
            ctx.move(to: h); ctx.addLine(to: c); ctx.addLine(to: v)
        }
        ctx.strokePath()

        // Live fading comic ink trail mapped 1:1 from physics.tabletTrail!
        if physics.tabletTrail.count >= 2 {
            let trailCol = eyeColor
            for i in 1..<physics.tabletTrail.count {
                let a = physics.tabletTrail[i - 1]
                let b = physics.tabletTrail[i]
                if hypot(b.point.x - a.point.x, b.point.y - a.point.y) > 22.0 { continue }
                let life = max(0.0, 1.0 - b.age / 0.72)
                if life <= 0.01 { continue }
                let uvA = douniTabletUV(from: a.point)
                let uvB = douniTabletUV(from: b.point)
                let pA = v2TabletPoint(u: uvA.u, v: uvA.v)
                let pB = v2TabletPoint(u: uvB.u, v: uvB.v)
                ctx.setStrokeColor(trailCol.withAlphaComponent(life * 0.92).cgColor)
                ctx.setLineWidth(4.5 + life * 5.0)
                ctx.move(to: pA)
                ctx.addLine(to: pB)
                ctx.strokePath()
            }
        }

        // Glowing nib contact halo when drawing
        if !showParkedStylus && physics.tabletPenPress.value > 0.08 {
            let uv = douniTabletUV(from: physics.tabletNib.point)
            let nib = v2TabletPoint(u: uv.u, v: uv.v)
            drawRadialGlow(
                in: ctx,
                center: nib,
                radius: 24.0 + physics.tabletPenPress.value * 14.0,
                color: eyeColor.withAlphaComponent(0.55 * physics.tabletPenPress.value)
            )
        }
        ctx.restoreGState()

        // Bold ink border around recessed pad
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw * 0.72)
        ctx.addPath(padPath)
        ctx.strokePath()

        // 5. Left bezel ExpressKeys (3 chunky comic pills) + glowing status LED dot
        let ledPt = v2TabletPoint(u: 0.125, v: 0.20)
        let ledCol = physics.tabletPenPress.value > 0.12 ? eyeColor : glowColor
        drawRadialGlow(in: ctx, center: ledPt, radius: 14.0, color: ledCol.withAlphaComponent(0.65))
        ctx.setFillColor(ledCol.cgColor)
        ctx.fillEllipse(in: CGRect(x: ledPt.x - 5.5, y: ledPt.y - 5.5, width: 11.0, height: 11.0))
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw * 0.42)
        ctx.strokeEllipse(in: CGRect(x: ledPt.x - 5.5, y: ledPt.y - 5.5, width: 11.0, height: 11.0))

        for kv: CGFloat in [0.40, 0.58, 0.76] {
            let kp = roundedQuadPath(
                tl: v2TabletPoint(u: 0.07, v: kv - 0.06),
                tr: v2TabletPoint(u: 0.175, v: kv - 0.06),
                br: v2TabletPoint(u: 0.175, v: kv + 0.06),
                bl: v2TabletPoint(u: 0.07, v: kv + 0.06),
                radius: 4.5
            )
            ctx.setFillColor(accentColor.cgColor)
            ctx.addPath(kp)
            ctx.fillPath()
            ctx.setStrokeColor(ink.cgColor)
            ctx.setLineWidth(lw * 0.48)
            ctx.addPath(kp)
            ctx.strokePath()
        }

        // 6. Parked hand-drawn comic stylus resting along top bezel when cat is typing/idle!
        if showParkedStylus {
            let nib = v2TabletPoint(u: 0.88, v: -0.06)
            let tail = v2TabletPoint(u: 0.14, v: -0.06)
            let ang = atan2(tail.y - nib.y, tail.x - nib.x)
            let len = hypot(tail.x - nib.x, tail.y - nib.y)
            ctx.saveGState()
            ctx.translateBy(x: nib.x, y: nib.y)
            ctx.rotate(by: ang)
            drawDouniComicStylus(in: ctx, length: len, accentColor: glowColor, eyeColor: eyeColor, ink: ink, lw: lw, pressed: 0)
            ctx.restoreGState()
        }

        ctx.restoreGState()
    }

    /// Chunky hand-drawn comic stylus oriented along +X from nib `(0,0)` to rounded eraser cap `(length,0)`.
    private static func drawDouniComicStylus(
        in ctx: CGContext,
        length: CGFloat,
        accentColor: NSColor,
        eyeColor: NSColor,
        ink: NSColor,
        lw: CGFloat,
        pressed: CGFloat
    ) {
        let halfW: CGFloat = 10.5
        let coneX: CGFloat = 26.0
        let pen = CGMutablePath()
        pen.move(to: CGPoint(x: 0, y: 0))
        pen.addLine(to: CGPoint(x: coneX, y: -halfW))
        pen.addLine(to: CGPoint(x: length - 12, y: -halfW))
        pen.addQuadCurve(to: CGPoint(x: length, y: 0), control: CGPoint(x: length, y: -halfW))
        pen.addQuadCurve(to: CGPoint(x: length - 12, y: halfW), control: CGPoint(x: length, y: halfW))
        pen.addLine(to: CGPoint(x: coneX, y: halfW))
        pen.closeSubpath()

        let barrelCol = NSColor(calibratedRed: 0.25, green: 0.24, blue: 0.25, alpha: 1.0)
        let gripCol   = NSColor(calibratedRed: 0.36, green: 0.35, blue: 0.37, alpha: 1.0)

        // Base fill
        ctx.setFillColor(barrelCol.cgColor)
        ctx.addPath(pen)
        ctx.fillPath()

        // Clipped grip sleeve, warm accent collar ring, glowing nib tip & comic specular streak!
        ctx.saveGState()
        ctx.addPath(pen)
        ctx.clip()
        ctx.setFillColor(gripCol.cgColor)
        ctx.fill(CGRect(x: coneX, y: -halfW - 2, width: 34, height: (halfW + 2) * 2))
        ctx.setFillColor(accentColor.cgColor)
        ctx.fill(CGRect(x: coneX + 34, y: -halfW - 2, width: 10, height: (halfW + 2) * 2))
        let nibCol = pressed > 0.12 ? eyeColor : NSColor(calibratedWhite: 0.94, alpha: 1.0)
        ctx.setFillColor(nibCol.cgColor)
        ctx.fill(CGRect(x: -2, y: -halfW, width: 14, height: halfW * 2))
        ctx.setFillColor(NSColor(calibratedWhite: 1.0, alpha: 0.26).cgColor)
        ctx.fill(CGRect(x: coneX + 2, y: -halfW + 2.5, width: length - coneX - 18, height: 3.5))
        ctx.restoreGState()

        // Bold Video 2 comic ink outline around stylus
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw * 0.72)
        ctx.setLineJoin(.round)
        ctx.setLineCap(.round)
        ctx.addPath(pen)
        ctx.strokePath()

        // Cute comic side button pill on upper barrel
        let btn = CGPath(roundedRect: CGRect(x: coneX + 8, y: -halfW - 3.5, width: 18, height: 5.5), cornerWidth: 2.5, cornerHeight: 2.5, transform: nil)
        ctx.setFillColor(NSColor(calibratedWhite: 0.84, alpha: 1.0).cgColor)
        ctx.addPath(btn)
        ctx.fillPath()
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw * 0.45)
        ctx.addPath(btn)
        ctx.strokePath()
    }

    private struct V2ArmShape {
        var shTop, shBot, tip, topC1, topC2, botC1, botC2: CGPoint
        var toe1A, toe1B, toe2A, toe2B: CGPoint
    }

    /// Builds a guaranteed constant-volume chubby Video-2 mitten arm from `shoulder` to exact key center `keyPoint`
    /// at ANY angle (horizontal, diagonal, or straight vertical) so the forearm NEVER pinches thin!
    private static func v2ChubbySlamArm(shoulder: CGPoint, keyPoint: CGPoint, archSign: CGFloat) -> V2ArmShape {
        let target = CGPoint(x: keyPoint.x, y: keyPoint.y - 4)
        let dx = target.x - shoulder.x
        let dy = target.y - shoulder.y
        let dist = max(56.0, hypot(dx, dy))
        let ux = dx / dist, uy = dy / dist
        // Choose perpendicular normal `n` pointing generally UP/LEFT for top edge and DOWN/RIGHT for bottom edge
        var nx = -uy, ny = ux
        if ny > 0 { nx = -nx; ny = -ny } // ensure (nx, ny) points toward the top/outer side of the arm!

        let rS: CGFloat = 34.0 // full chubby 68px shoulder width
        let rP: CGFloat = 33.0 // full chubby 66px rounded paw mitten width
        let archLift: CGFloat = 14.0 * abs(ux) // soft upward comic arch when reaching sideways

        let shTop = CGPoint(x: shoulder.x + nx * rS, y: shoulder.y + ny * rS)
        let shBot = CGPoint(x: shoulder.x - nx * rS, y: shoulder.y - ny * rS)
        let tip   = CGPoint(x: target.x + ux * 16.0, y: target.y + uy * 16.0)

        let topC1 = CGPoint(x: lerp(shTop.x, target.x + nx * rP, 0.42), y: lerp(shTop.y, target.y + ny * rP, 0.42) - archLift)
        let topC2 = CGPoint(x: target.x + nx * (rP * 1.15) + ux * 8.0, y: target.y + ny * (rP * 1.15) + uy * 8.0)
        let botC1 = CGPoint(x: target.x - nx * (rP * 1.15) + ux * 8.0, y: target.y - ny * (rP * 1.15) + uy * 8.0)
        let botC2 = CGPoint(x: lerp(shBot.x, target.x - nx * rP, 0.42), y: lerp(shBot.y, target.y - ny * rP, 0.42) - archLift * 0.4)

        // 2 crisp toe ticks cleanly centered on the rounded taupe paw pad pointing forward onto the keycap!
        let tBase = CGPoint(x: target.x - ux * 10.0, y: target.y - uy * 10.0)
        let tLen: CGFloat = 24.0
        let toe1A = CGPoint(x: tBase.x + nx * 10.0, y: tBase.y + ny * 10.0)
        let toe1B = CGPoint(x: toe1A.x + ux * tLen, y: toe1A.y + uy * tLen)
        let toe2A = CGPoint(x: tBase.x - nx * 12.0, y: tBase.y - ny * 12.0)
        let toe2B = CGPoint(x: toe2A.x + ux * tLen, y: toe2A.y + uy * tLen)

        return V2ArmShape(
            shTop: shTop, shBot: shBot, tip: tip,
            topC1: topC1, topC2: topC2, botC1: botC1, botC2: botC2,
            toe1A: toe1A, toe1B: toe1B, toe2A: toe2A, toe2B: toe2B
        )
    }

    /// Draws Video 2's chunky curved Left Arm (cat's right arm) across Pose A (0), Pose B (-1 slam onto exact key), Pose C (+1 high), and Mouse reach.
    private static func drawV2LeftArm(
        in ctx: CGContext,
        pose: CGFloat,
        mouseBlend: CGFloat,
        mouseTarget: CGPoint,
        slamTarget: CGPoint? = nil,
        cream: NSColor,
        taupe: NSColor,
        ink: NSColor,
        lw: CGFloat,
        swingVelocity: CGFloat = 0
    ) {
        typealias ArmShape = V2ArmShape
        let poseA = ArmShape( // v2_01 ready
            shTop: CGPoint(x: 416, y: 312), shBot: CGPoint(x: 416, y: 374),
            tip:   CGPoint(x: 242, y: 346),
            topC1: CGPoint(x: 344, y: 288), topC2: CGPoint(x: 260, y: 298),
            botC1: CGPoint(x: 242, y: 392), botC2: CGPoint(x: 332, y: 386),
            toe1A: CGPoint(x: 256, y: 356), toe1B: CGPoint(x: 258, y: 380),
            toe2A: CGPoint(x: 278, y: 360), toe2B: CGPoint(x: 280, y: 384)
        )
        let poseB: ArmShape
        if let pt = slamTarget {
            // Volume-preserving chubby Video-2 mitten aimed DEAD-CENTER on exact pressed key `pt` at ANY angle (zero pinch!)
            poseB = v2ChubbySlamArm(shoulder: CGPoint(x: 426, y: 350), keyPoint: pt, archSign: -1)
        } else {
            poseB = ArmShape( // Exact v2_04 pixel-overlap reference pose
                shTop: CGPoint(x: 422, y: 326), shBot: CGPoint(x: 432, y: 392),
                tip:   CGPoint(x: 274, y: 412),
                topC1: CGPoint(x: 348, y: 318), topC2: CGPoint(x: 284, y: 356),
                botC1: CGPoint(x: 272, y: 454), botC2: CGPoint(x: 348, y: 434),
                toe1A: CGPoint(x: 288, y: 414), toe1B: CGPoint(x: 292, y: 440),
                toe2A: CGPoint(x: 310, y: 416), toe2B: CGPoint(x: 314, y: 442)
            )
        }
        let poseC = ArmShape( // v2_05 flung high up-left into the air!
            shTop: CGPoint(x: 422, y: 262), shBot: CGPoint(x: 434, y: 336),
            tip:   CGPoint(x: 258, y: 248),
            topC1: CGPoint(x: 360, y: 222), topC2: CGPoint(x: 286, y: 204),
            botC1: CGPoint(x: 254, y: 298), botC2: CGPoint(x: 352, y: 312),
            toe1A: CGPoint(x: 274, y: 246), toe1B: CGPoint(x: 274, y: 278),
            toe2A: CGPoint(x: 296, y: 254), toe2B: CGPoint(x: 296, y: 286)
        )
        let poseM = ArmShape( // Gliding smoothly onto left-side hand-drawn mouse
            shTop: CGPoint(x: 414, y: 298), shBot: CGPoint(x: 414, y: 356),
            tip:   CGPoint(x: mouseTarget.x - 16, y: mouseTarget.y - 2),
            topC1: CGPoint(x: 330, y: 274), topC2: CGPoint(x: mouseTarget.x + 28, y: mouseTarget.y - 36),
            botC1: CGPoint(x: mouseTarget.x - 12, y: mouseTarget.y + 38), botC2: CGPoint(x: 312, y: 358),
            toe1A: CGPoint(x: mouseTarget.x - 2, y: mouseTarget.y + 6), toe1B: CGPoint(x: mouseTarget.x - 2, y: mouseTarget.y + 28),
            toe2A: CGPoint(x: mouseTarget.x + 18, y: mouseTarget.y + 8), toe2B: CGPoint(x: mouseTarget.x + 18, y: mouseTarget.y + 30)
        )

        func blendShape(_ a: ArmShape, _ b: ArmShape, _ t: CGFloat) -> ArmShape {
            ArmShape(
                shTop: lerpPt(a.shTop, b.shTop, t), shBot: lerpPt(a.shBot, b.shBot, t),
                tip: lerpPt(a.tip, b.tip, t),
                topC1: lerpPt(a.topC1, b.topC1, t), topC2: lerpPt(a.topC2, b.topC2, t),
                botC1: lerpPt(a.botC1, b.botC1, t), botC2: lerpPt(a.botC2, b.botC2, t),
                toe1A: lerpPt(a.toe1A, b.toe1A, t), toe1B: lerpPt(a.toe1B, b.toe1B, t),
                toe2A: lerpPt(a.toe2A, b.toe2A, t), toe2B: lerpPt(a.toe2B, b.toe2B, t)
            )
        }

        let typingShape: ArmShape = pose >= 0
            ? blendShape(poseA, poseC, min(1.05, pose))
            : blendShape(poseA, poseB, min(1.05, -pose))
        let sh = mouseBlend > 0.01 ? blendShape(typingShape, poseM, mouseBlend) : typingShape

        let fillPath = CGMutablePath()
        fillPath.move(to: sh.shTop)
        fillPath.addCurve(to: sh.tip, control1: sh.topC1, control2: sh.topC2)
        fillPath.addCurve(to: sh.shBot, control1: sh.botC1, control2: sh.botC2)
        fillPath.closeSubpath()

        let strokePath = CGMutablePath()
        strokePath.move(to: sh.shTop)
        strokePath.addCurve(to: sh.tip, control1: sh.topC1, control2: sh.topC2)
        strokePath.addCurve(to: sh.shBot, control1: sh.botC1, control2: sh.botC2)

        // Outer white sticker rim around the protruding paw
        if CatSettings.shared.whiteOutline {
            ctx.saveGState()
            ctx.setStrokeColor(blackOutlineColor.cgColor)
            ctx.setLineWidth(lw + 9.0)
            ctx.addPath(strokePath)
            ctx.strokePath()
            ctx.restoreGState()
        }

        // Smooth cream-to-taupe paw gradient (tip taupe -> shoulder cream, matching Video 2!)
        ctx.saveGState()
        ctx.addPath(fillPath)
        ctx.clip()
        let cs = CGColorSpaceCreateDeviceRGB()
        let cols = [taupe.cgColor, taupe.cgColor, cream.cgColor] as CFArray
        if let grad = CGGradient(colorsSpace: cs, colors: cols, locations: [0.0, 0.42, 0.80]) {
            let start = sh.tip
            let end = CGPoint(x: (sh.shTop.x + sh.shBot.x) * 0.5, y: (sh.shTop.y + sh.shBot.y) * 0.5)
            ctx.drawLinearGradient(grad, start: start, end: end, options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
        }
        ctx.restoreGState()

        // Crisp open comic outline (no hard seam across the shoulder!)
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw)
        ctx.addPath(strokePath)
        ctx.strokePath()

        // 2 curved vertical toe ticks
        ctx.setLineWidth(lw * 0.88)
        ctx.move(to: sh.toe1A); ctx.addLine(to: sh.toe1B)
        ctx.move(to: sh.toe2A); ctx.addLine(to: sh.toe2B)
        ctx.strokePath()

        // Disney Principle #7 (Arcs): crisp subtle motion-arc smear lines when whipping fast!
        let spd = abs(swingVelocity)
        if spd > 4.2 && mouseBlend < 0.2 {
            let a = min(0.45, (spd - 4.2) / 10.0)
            let dir: CGFloat = swingVelocity > 0 ? 1 : -1
            ctx.saveGState()
            ctx.setStrokeColor(ink.withAlphaComponent(a).cgColor)
            ctx.setLineWidth(lw * 0.55)
            ctx.move(to: CGPoint(x: sh.tip.x - 16, y: sh.tip.y + dir * 22))
            ctx.addQuadCurve(to: CGPoint(x: sh.tip.x + 14, y: sh.tip.y + dir * 68),
                             control: CGPoint(x: sh.tip.x - 24, y: sh.tip.y + dir * 48))
            ctx.move(to: CGPoint(x: sh.tip.x + 6, y: sh.tip.y + dir * 28))
            ctx.addQuadCurve(to: CGPoint(x: sh.tip.x + 34, y: sh.tip.y + dir * 64),
                             control: CGPoint(x: sh.tip.x + 2, y: sh.tip.y + dir * 50))
            ctx.strokePath()
            ctx.restoreGState()
        }
    }

    /// Draws Video 2's chunky curved Right Arm (cat's left arm) across Pose A (0), Pose B (+1 high across face!), Pose C (-1 slam onto exact key).
    private static func drawV2RightArm(
        in ctx: CGContext,
        pose: CGFloat,
        slamTarget: CGPoint? = nil,
        cream: NSColor,
        taupe: NSColor,
        ink: NSColor,
        lw: CGFloat,
        swingVelocity: CGFloat = 0
    ) {
        typealias ArmShape = V2ArmShape
        let poseA = ArmShape( // v2_01 resting horizontally across upper keys under chin
            shTop: CGPoint(x: 616, y: 344), shBot: CGPoint(x: 618, y: 406),
            tip:   CGPoint(x: 410, y: 368),
            topC1: CGPoint(x: 544, y: 306), topC2: CGPoint(x: 432, y: 306),
            botC1: CGPoint(x: 406, y: 414), botC2: CGPoint(x: 522, y: 414),
            toe1A: CGPoint(x: 426, y: 374), toe1B: CGPoint(x: 426, y: 402),
            toe2A: CGPoint(x: 452, y: 378), toe2B: CGPoint(x: 452, y: 404)
        )
        let poseB = ArmShape( // v2_04 flung HIGH up-left right across the lower face & left eye!
            shTop: CGPoint(x: 626, y: 344), shBot: CGPoint(x: 608, y: 382),
            tip:   CGPoint(x: 422, y: 294),
            topC1: CGPoint(x: 564, y: 278), topC2: CGPoint(x: 458, y: 226),
            botC1: CGPoint(x: 416, y: 344), botC2: CGPoint(x: 518, y: 350),
            toe1A: CGPoint(x: 440, y: 296), toe1B: CGPoint(x: 442, y: 332),
            toe2A: CGPoint(x: 464, y: 306), toe2B: CGPoint(x: 466, y: 338)
        )
        let poseC: ArmShape
        if let pt = slamTarget {
            // Volume-preserving chubby Video-2 mitten aimed DEAD-CENTER on exact pressed key `pt` across Space & right keys (Q/W/A/S/D/E)!
            poseC = v2ChubbySlamArm(shoulder: CGPoint(x: 604, y: 372), keyPoint: pt, archSign: 1)
        } else {
            poseC = ArmShape( // Exact v2_05 pixel-overlap reference pose
                shTop: CGPoint(x: 586, y: 346), shBot: CGPoint(x: 608, y: 404),
                tip:   CGPoint(x: 406, y: 414),
                topC1: CGPoint(x: 498, y: 344), topC2: CGPoint(x: 422, y: 356),
                botC1: CGPoint(x: 404, y: 464), botC2: CGPoint(x: 500, y: 446),
                toe1A: CGPoint(x: 420, y: 422), toe1B: CGPoint(x: 420, y: 452),
                toe2A: CGPoint(x: 446, y: 426), toe2B: CGPoint(x: 446, y: 454)
            )
        }

        func blendShape(_ a: ArmShape, _ b: ArmShape, _ t: CGFloat) -> ArmShape {
            ArmShape(
                shTop: lerpPt(a.shTop, b.shTop, t), shBot: lerpPt(a.shBot, b.shBot, t),
                tip: lerpPt(a.tip, b.tip, t),
                topC1: lerpPt(a.topC1, b.topC1, t), topC2: lerpPt(a.topC2, b.topC2, t),
                botC1: lerpPt(a.botC1, b.botC1, t), botC2: lerpPt(a.botC2, b.botC2, t),
                toe1A: lerpPt(a.toe1A, b.toe1A, t), toe1B: lerpPt(a.toe1B, b.toe1B, t),
                toe2A: lerpPt(a.toe2A, b.toe2A, t), toe2B: lerpPt(a.toe2B, b.toe2B, t)
            )
        }

        let sh: ArmShape = pose >= 0
            ? blendShape(poseA, poseB, min(1.05, pose))
            : blendShape(poseA, poseC, min(1.05, -pose))

        // In Pose B (right arm sweeps up across lower face), softly mask out the lower chin line directly behind the arm!
        if pose > 0.35 {
            ctx.saveGState()
            ctx.setFillColor(cream.cgColor)
            ctx.setAlpha(smoothstep(0.35, 0.85, pose))
            ctx.fill(CGRect(x: 446, y: 332, width: 164, height: 32))
            ctx.restoreGState()
        }

        let fillPath = CGMutablePath()
        fillPath.move(to: sh.shTop)
        fillPath.addCurve(to: sh.tip, control1: sh.topC1, control2: sh.topC2)
        fillPath.addCurve(to: sh.shBot, control1: sh.botC1, control2: sh.botC2)
        fillPath.closeSubpath()

        let strokePath = CGMutablePath()
        strokePath.move(to: sh.shTop)
        strokePath.addCurve(to: sh.tip, control1: sh.topC1, control2: sh.topC2)
        strokePath.addCurve(to: sh.shBot, control1: sh.botC1, control2: sh.botC2)

        // Outer white sticker rim around the protruding paw
        if CatSettings.shared.whiteOutline {
            ctx.saveGState()
            ctx.setStrokeColor(blackOutlineColor.cgColor)
            ctx.setLineWidth(lw + 8.4)
            ctx.addPath(strokePath)
            ctx.strokePath()
            ctx.restoreGState()
        }

        ctx.saveGState()
        ctx.addPath(fillPath)
        ctx.clip()
        let cs = CGColorSpaceCreateDeviceRGB()
        let cols = [taupe.cgColor, taupe.cgColor, cream.cgColor] as CFArray
        if let grad = CGGradient(colorsSpace: cs, colors: cols, locations: [0.0, 0.45, 0.84]) {
            let start = sh.tip
            let end = CGPoint(x: (sh.shTop.x + sh.shBot.x) * 0.5, y: (sh.shTop.y + sh.shBot.y) * 0.5)
            ctx.drawLinearGradient(grad, start: start, end: end, options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
        }
        ctx.restoreGState()

        // Crisp open comic outline (merges seamlessly into cream chest on right!)
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(lw)
        ctx.addPath(strokePath)
        ctx.strokePath()

        // 2 curved vertical toe ticks
        ctx.setLineWidth(lw * 0.88)
        ctx.move(to: sh.toe1A); ctx.addLine(to: sh.toe1B)
        ctx.move(to: sh.toe2A); ctx.addLine(to: sh.toe2B)
        ctx.strokePath()

        // Disney Principle #7 (Arcs): subtle speed-arc lines trailing fast arm slam/windup!
        let spd = abs(swingVelocity)
        if spd > 4.2 {
            let a = min(0.45, (spd - 4.2) / 10.0)
            let dir: CGFloat = swingVelocity > 0 ? 1 : -1
            ctx.saveGState()
            ctx.setStrokeColor(ink.withAlphaComponent(a).cgColor)
            ctx.setLineWidth(lw * 0.55)
            ctx.move(to: CGPoint(x: sh.tip.x - 14, y: sh.tip.y + dir * 24))
            ctx.addQuadCurve(to: CGPoint(x: sh.tip.x + 12, y: sh.tip.y + dir * 68),
                             control: CGPoint(x: sh.tip.x - 20, y: sh.tip.y + dir * 48))
            ctx.strokePath()
            ctx.restoreGState()
        }
    }

    // MARK: - Universal Native-Face Scruff-Lifted Drag Pose (ALL Non-Douni Skins!)

    /// Lifts ANY standard or custom `.kurocat` cat by the scruff of its neck:
    /// keeps the cat's OWN authentic KuroCat face, head shape, 3D ears, markings, whiskers, nose/mouth, eyes & decorations
    /// cleanly in front, while its neck & back arch behind as if held by the scruff, 4 seamlessly attached chubby paws
    /// Universal Front-Facing Long-Cat Scruff-Lifted Drag Pose:
    /// 1:1 front-view body & arm mapping so every built-in, custom .kurocat, calico, tuxedo, vest, and Paint Studio skin
    /// preserves its exact color blocks with zero side-view scramble!
    static func drawNativeScruffDragCat(
        in ctx: CGContext,
        physics: CatPhysics,
        skin: SkinSpec,
        eyeTheme: EyeColorTheme,
        lift: CGFloat
    ) {
        let liftS = smoothstep(0.0, 1.0, lift)
        let startle: CGFloat
        if physics.isScruffDragging {
            if physics.scruffHoldTime < 0.14 {
                startle = 1.0
            } else {
                startle = max(0, 1.0 - (physics.scruffHoldTime - 0.14) / 0.08)
            }
        } else {
            startle = (physics.scruffDropTimer > 0.01) ? min(1.0, physics.scruffDropTimer / 0.12) : 1.0
        }

        // Lively 2D drag inertia: limbs, lower torso & tail trail behind fast motion and rebound softly!
        let swingH = max(-1.0, min(1.0, physics.scruffSwing.value))
        let swingY = max(-0.92, min(0.92, physics.scruffSwingY.value))
        let tailSwing = max(-1.25, min(1.25, physics.scruffTailSwing.value))
        let idleSway = sin(physics.time * 4.2) * 0.045 * (1.0 - startle)
        let limbSwing = max(-0.82, min(0.82, swingH * 0.85)) * (1.0 - startle * 0.45) + idleSway
        let upBillow = max(0, -swingY)

        let pal = skin.palette
        let bd = build(skin)
        let hs = skin.shape.headScale
        let bw = skin.shape.bodyWidth
        let nw = skin.shape.neckWidth
        let isDazed = (skin.renderStyle == .dazed)
        let isBlackRim = isClassicBlackRim(skin)
        let limbInk = isBlackRim
            ? NSColor(calibratedWhite: 0.94, alpha: 0.28)
            : (pal.outline?.ns ?? NSColor(calibratedRed: 0.18, green: 0.15, blue: 0.12, alpha: 0.26))

        // Build- & shape-adaptive long-cat proportions: sleek stretches into a slim liquid noodle;
        // chubby hangs rounder with a plush pear-shaped tummy and stubbier paws.
        let isSleek = (skin.shape.build == .sleek)
        let plump = max(-0.35, min(0.38, (bw - 1.0) + (isSleek ? -0.15 : 0.0)))
        let limbWScale = max(0.72, min(1.30, (bd.limbStartW / 19.0) * (1.0 + plump * 0.62)))
        let limbLenScale = max(0.84, min(1.18, 1.0 - plump * 0.28 + (isSleek ? 0.07 : 0.0)))

        let baseShiftX = physics.bodyShiftX.value + swingH * 10.0
        let liftY = -liftS * 12.0 + sin(physics.time * 3.8) * 2.0 * (1.0 - startle) + swingY * 5.0
        let headCenter = CGPoint(
            x: 180.0 + baseShiftX,
            y: lerp(94.0, 108.0, startle) + liftY + (hs - 1.0) * 6.0
        )

        let cheekHalfW = bd.cheekHalfW * skin.shape.cheekFullness * hs
        let crownY = bd.crownBaseY * hs
        let cheekY = bd.cheekY * hs
        let chinY = 33.0 * hs

        // Soft lifted scruff fur gather right between the ears (gentle rounded pinch — never pointy, never overlaps ears!)
        let scruffTuftH = lerp(6.2, 3.8, startle) * hs
        let scruffPinch = CGPoint(x: headCenter.x, y: headCenter.y + crownY - scruffTuftH)

        // Stretched hanging torso dimensions & soft spinal lag curve
        let torsoLen = lerp(124.0 - plump * 18.0 + (isSleek ? 10.0 : 0.0), 104.0 - plump * 12.0, startle) * (1.0 + swingY * 0.08)
        let torsoBottomY = headCenter.y + torsoLen
        let hipLagX = (swingH * 22.0 + idleSway * 16.0) * (1.0 - startle * 0.35)

        let neckHalfW = max(18.0 * hs, (cheekHalfW - bd.neckPinchX * hs) * nw)
        let waistHalfW = bd.waistCtrlW * bw * lerp(0.84 + plump * 0.24, 0.92 + plump * 0.20, startle)
        let hipHalfW = bd.hipHalfW * bw * lerp(0.95 + plump * 0.26, 1.00 + plump * 0.20, startle)
        let bottomDip: CGFloat = 12.0 + max(0.0, plump) * 14.0
        let rumpCenterX = headCenter.x + hipLagX

        func rot(_ pt: CGPoint, around pivot: CGPoint, angle: CGFloat) -> CGPoint {
            let dx = pt.x - pivot.x, dy = pt.y - pivot.y
            let c = cos(angle), s = sin(angle)
            return CGPoint(x: pivot.x + dx * c - dy * s, y: pivot.y + dx * s + dy * c)
        }

        // 1. Unified front-facing long-cat silhouette: subtle lifted scruff tuft between ears + native cheeks + seamless stretched torso
        let longCatPath = CGMutablePath()
        do {
            let tuftBaseX = min(12.5 * hs, cheekHalfW * 0.31)
            let rCheekX = headCenter.x + cheekHalfW
            let lCheekX = headCenter.x - cheekHalfW
            let cheekPosY = headCenter.y + cheekY
            let neckCtrlY = headCenter.y + bd.neckCtrlY * hs
            let waistY = headCenter.y + torsoLen * 0.48
            let hipY = torsoBottomY - 14.0
            let waistCenterX = headCenter.x + hipLagX * 0.34
            let botHalf = hipHalfW * 0.62

            longCatPath.move(to: scruffPinch)
            longCatPath.addCurve(
                to: CGPoint(x: headCenter.x + tuftBaseX, y: headCenter.y + crownY + 0.5 * hs),
                control1: CGPoint(x: headCenter.x + tuftBaseX * 0.56, y: scruffPinch.y + scruffTuftH * 0.06),
                control2: CGPoint(x: headCenter.x + tuftBaseX * 0.80, y: headCenter.y + crownY - scruffTuftH * 0.14)
            )
            longCatPath.addCurve(
                to: CGPoint(x: rCheekX, y: cheekPosY),
                control1: CGPoint(x: headCenter.x + bd.crownCtrlW * hs, y: headCenter.y + crownY),
                control2: CGPoint(x: rCheekX + 1.5 * hs, y: headCenter.y + bd.cheekCtrlTopY * hs)
            )
            longCatPath.addCurve(
                to: CGPoint(x: rumpCenterX + hipHalfW, y: hipY),
                control1: CGPoint(x: headCenter.x + neckHalfW, y: neckCtrlY),
                control2: CGPoint(x: waistCenterX + waistHalfW, y: waistY)
            )
            longCatPath.addCurve(
                to: CGPoint(x: rumpCenterX, y: torsoBottomY + bottomDip),
                control1: CGPoint(x: rumpCenterX + hipHalfW * 0.96, y: torsoBottomY + bottomDip * 0.55),
                control2: CGPoint(x: rumpCenterX + botHalf, y: torsoBottomY + bottomDip)
            )
            longCatPath.addCurve(
                to: CGPoint(x: rumpCenterX - hipHalfW, y: hipY),
                control1: CGPoint(x: rumpCenterX - botHalf, y: torsoBottomY + bottomDip),
                control2: CGPoint(x: rumpCenterX - hipHalfW * 0.96, y: torsoBottomY + bottomDip * 0.55)
            )
            longCatPath.addCurve(
                to: CGPoint(x: lCheekX, y: cheekPosY),
                control1: CGPoint(x: waistCenterX - waistHalfW, y: waistY),
                control2: CGPoint(x: headCenter.x - neckHalfW, y: neckCtrlY)
            )
            longCatPath.addCurve(
                to: CGPoint(x: headCenter.x - tuftBaseX, y: headCenter.y + crownY + 0.5 * hs),
                control1: CGPoint(x: lCheekX - 1.5 * hs, y: headCenter.y + bd.cheekCtrlTopY * hs),
                control2: CGPoint(x: headCenter.x - bd.crownCtrlW * hs, y: headCenter.y + crownY)
            )
            longCatPath.addCurve(
                to: scruffPinch,
                control1: CGPoint(x: headCenter.x - tuftBaseX * 0.80, y: headCenter.y + crownY - scruffTuftH * 0.14),
                control2: CGPoint(x: headCenter.x - tuftBaseX * 0.56, y: scruffPinch.y + scruffTuftH * 0.06)
            )
            longCatPath.closeSubpath()
        }

        // Exact 1:1 front-view body mapping: seated body y in [-98..+12] stretches smoothly along the hanging torso
        // and follows both body width envelope & spinal sway so every calico/tuxedo/vest/brush pattern bends cleanly!
        let dragBodyMap: (CGPoint) -> CGPoint = { pt in
            let u = (pt.y + 98.0) / 110.0
            let uC = max(0.0, min(1.15, u))
            let ySpan = (torsoBottomY + bottomDip * 0.78) - headCenter.y
            let mappedY = headCenter.y + u * ySpan
            let baseRefW = max(1.0, bd.hipHalfW * bw)
            let targetW = lerp(waistHalfW / max(1.0, bd.waistCtrlW * bw), hipHalfW / baseRefW, smoothstep(0.35, 0.95, uC))
            let wScale = lerp(1.0, targetW, smoothstep(0.18, 0.55, uC))
            let swayX = hipLagX * uC * uC
            return CGPoint(x: headCenter.x + pt.x * bw * wScale + swayX, y: mappedY)
        }

        // 2. Dangling limp tail emerging from lower-right behind the hip with graceful outward separation from right hind paw
        let tailPivot = CGPoint(x: rumpCenterX + hipHalfW * 0.60, y: torsoBottomY - 16.0)
        let tailLen: CGFloat = 76.0 * skin.shape.tailLength * (1.0 + swingY * 0.14)
        let tailW: CGFloat = max(8.0, (isDazed ? 13.0 : bd.tailWidth * skin.shape.tailThickness) * 1.08)
        let rawTailAng = (tailSwing * (1.0 - startle * 0.25) + idleSway * 1.5) * 0.85
        let tailAng = max(-1.05, min(0.75, rawTailAng))
        let baseC1 = CGPoint(x: tailPivot.x + 26 + upBillow * 10, y: tailPivot.y + tailLen * 0.22 - upBillow * 10)
        let baseC2 = CGPoint(x: tailPivot.x + 36 + upBillow * 18, y: tailPivot.y + tailLen * 0.64 - upBillow * 26)
        let baseTip = CGPoint(x: tailPivot.x + 24 + upBillow * 24, y: tailPivot.y + tailLen - upBillow * 40)
        let tailC1 = rot(baseC1, around: tailPivot, angle: tailAng * 0.45)
        let tailC2 = rot(baseC2, around: tailPivot, angle: tailAng * 0.92)
        let tailTip = rot(baseTip, around: tailPivot, angle: tailAng * 1.26)
        let tailCurvePath = CGMutablePath()
        tailCurvePath.move(to: tailPivot)
        tailCurvePath.addCurve(to: tailTip, control1: tailC1, control2: tailC2)

        // 3. Four symmetric front-facing dangling limbs:
        //    - Front arms root snugly along the outer shoulder slopes and drape softly downward/slightly inward,
        //      leaving the central chest 100% unobstructed for vests/bibs/calico/brush art!
        //    - Hind legs emerge cleanly from the lower rounded belly hem with soft natural splay.
        struct DragLimb {
            let root, tip: CGPoint
            let startW, endW: CGFloat
            let bendX: CGFloat
            let armSpace: SkinSpace?
            let isBehindBody: Bool
        }
        func makeLimb(
            rootA: CGPoint, tipA: CGPoint,
            rootB: CGPoint, tipB: CGPoint,
            w0: CGFloat, w1: CGFloat,
            bendX: CGFloat, swingScale: CGFloat, splayDir: CGFloat,
            armSpace: SkinSpace? = nil,
            isBehindBody: Bool = false
        ) -> DragLimb {
            let r = lerpPt(rootA, rootB, startle)
            let baseTip = lerpPt(tipA, tipB, startle)
            let lenFactor: CGFloat = (1.0 + swingY * 0.16) * limbLenScale
            let stretched = CGPoint(
                x: r.x + (baseTip.x - r.x) * lenFactor,
                y: r.y + (baseTip.y - r.y) * lenFactor - upBillow * 6.0
            )
            let ang = limbSwing * swingScale + upBillow * 0.20 * splayDir
            let t = rot(stretched, around: r, angle: ang)
            let dynBendX = bendX + limbSwing * 11.0 * swingScale
            return DragLimb(root: r, tip: t, startW: w0 * limbWScale, endW: w1 * limbWScale, bendX: dynBendX, armSpace: armSpace, isBehindBody: isBehindBody)
        }

        let shoulderY = headCenter.y + 42.0 * hs
        // Tuck front-arm roots cleanly INSIDE the torso silhouette so shoulders NEVER bulge outside the body!
        let shoulderInX = max(12.0 * hs, min(neckHalfW * 0.72, waistHalfW * 0.56))
        let armLen: CGFloat = 56.0
        let frontLeftLimb = makeLimb(
            rootA: CGPoint(x: headCenter.x - shoulderInX + hipLagX * 0.16, y: shoulderY),
            tipA: CGPoint(x: headCenter.x - shoulderInX + 1.5 + hipLagX * 0.30, y: shoulderY + armLen),
            rootB: CGPoint(x: headCenter.x - shoulderInX + hipLagX * 0.12, y: shoulderY + 3.0),
            tipB: CGPoint(x: headCenter.x - shoulderInX - 4.0 + hipLagX * 0.22, y: shoulderY + armLen * 0.84),
            w0: 13.6, w1: 12.4, bendX: -1.5, swingScale: 0.42, splayDir: -0.65, armSpace: .leftArm
        )
        let frontRightLimb = makeLimb(
            rootA: CGPoint(x: headCenter.x + shoulderInX + hipLagX * 0.16, y: shoulderY),
            tipA: CGPoint(x: headCenter.x + shoulderInX - 1.5 + hipLagX * 0.30, y: shoulderY + armLen),
            rootB: CGPoint(x: headCenter.x + shoulderInX + hipLagX * 0.12, y: shoulderY + 3.0),
            tipB: CGPoint(x: headCenter.x + shoulderInX + 4.0 + hipLagX * 0.22, y: shoulderY + armLen * 0.84),
            w0: 13.6, w1: 12.4, bendX: 1.5, swingScale: 0.42, splayDir: 0.65, armSpace: .rightArm
        )

        let hindRootX = max(13.0, hipHalfW * 0.42)
        let hindRootY = torsoBottomY + bottomDip * 0.20 - 12.0
        let hindLen: CGFloat = 46.0
        let backLeftLimb = makeLimb(
            rootA: CGPoint(x: rumpCenterX - hindRootX, y: hindRootY),
            tipA: CGPoint(x: rumpCenterX - hindRootX - 2.5, y: hindRootY + hindLen),
            rootB: CGPoint(x: rumpCenterX - hindRootX - 1.0, y: hindRootY - 3.0),
            tipB: CGPoint(x: rumpCenterX - hindRootX - 7.5, y: hindRootY + hindLen * 0.80),
            w0: 15.2, w1: 12.8, bendX: -1.5, swingScale: 0.68, splayDir: -0.65, armSpace: .hindLeg, isBehindBody: true
        )
        let backRightLimb = makeLimb(
            rootA: CGPoint(x: rumpCenterX + hindRootX, y: hindRootY),
            tipA: CGPoint(x: rumpCenterX + hindRootX + 2.5, y: hindRootY + hindLen),
            rootB: CGPoint(x: rumpCenterX + hindRootX + 1.0, y: hindRootY - 3.0),
            tipB: CGPoint(x: rumpCenterX + hindRootX + 7.5, y: hindRootY + hindLen * 0.80),
            w0: 15.2, w1: 12.8, bendX: 1.5, swingScale: 0.68, splayDir: 0.65, armSpace: .hindLeg, isBehindBody: true
        )

        struct LimbGeo {
            let ux, uy, nx, ny, r0, r1: CGFloat
            let p0L, p0R, p1L, p1R, midL, midR, pawC1, pawC2: CGPoint
            let fill, rim, ink: CGPath
        }
        func limbGeo(_ limb: DragLimb) -> LimbGeo {
            let dx = limb.tip.x - limb.root.x, dy = limb.tip.y - limb.root.y
            let len = max(1, hypot(dx, dy))
            let ux = dx / len, uy = dy / len
            let nx = -uy, ny = ux
            let r0 = limb.startW * 0.5, r1 = limb.endW * 0.5
            let p0L = CGPoint(x: limb.root.x + nx * r0, y: limb.root.y + ny * r0)
            let p0R = CGPoint(x: limb.root.x - nx * r0, y: limb.root.y - ny * r0)
            let p1L = CGPoint(x: limb.tip.x + nx * r1, y: limb.tip.y + ny * r1)
            let p1R = CGPoint(x: limb.tip.x - nx * r1, y: limb.tip.y - ny * r1)
            let midL = CGPoint(x: (p0L.x + p1L.x) * 0.5 + limb.bendX * 0.5 + nx * 1.2, y: (p0L.y + p1L.y) * 0.5 + ny * 1.2)
            let midR = CGPoint(x: (p0R.x + p1R.x) * 0.5 + limb.bendX * 0.5 - nx * 1.2, y: (p0R.y + p1R.y) * 0.5 - ny * 1.2)
            let pawC1 = CGPoint(x: p1L.x + ux * r1 * 1.25, y: p1L.y + uy * r1 * 1.25)
            let pawC2 = CGPoint(x: p1R.x + ux * r1 * 1.25, y: p1R.y + uy * r1 * 1.25)

            let rim = CGMutablePath()
            rim.move(to: p0L)
            rim.addQuadCurve(to: p1L, control: midL)
            rim.addCurve(to: p1R, control1: pawC1, control2: pawC2)
            rim.addQuadCurve(to: p0R, control: midR)

            let closed = rim.mutableCopy()!
            closed.addCurve(
                to: p0L,
                control1: CGPoint(x: p0R.x - ux * r0 * 0.85, y: p0R.y - uy * r0 * 0.85),
                control2: CGPoint(x: p0L.x - ux * r0 * 0.85, y: p0L.y - uy * r0 * 0.85)
            )
            closed.closeSubpath()

            let t0: CGFloat = 0.24
            let omt = 1.0 - t0
            let s0L = CGPoint(
                x: omt * omt * p0L.x + 2 * omt * t0 * midL.x + t0 * t0 * p1L.x,
                y: omt * omt * p0L.y + 2 * omt * t0 * midL.y + t0 * t0 * p1L.y
            )
            let scL = CGPoint(x: omt * midL.x + t0 * p1L.x, y: omt * midL.y + t0 * p1L.y)
            let s0R = CGPoint(
                x: omt * omt * p0R.x + 2 * omt * t0 * midR.x + t0 * t0 * p1R.x,
                y: omt * omt * p0R.y + 2 * omt * t0 * midR.y + t0 * t0 * p1R.y
            )
            let scR = CGPoint(x: omt * midR.x + t0 * p1R.x, y: omt * midR.y + t0 * p1R.y)
            let ink = CGMutablePath()
            ink.move(to: s0L)
            ink.addQuadCurve(to: p1L, control: scL)
            ink.addCurve(to: p1R, control1: pawC1, control2: pawC2)
            ink.addQuadCurve(to: s0R, control: scR)

            return LimbGeo(ux: ux, uy: uy, nx: nx, ny: ny, r0: r0, r1: r1,
                           p0L: p0L, p0R: p0R, p1L: p1L, p1R: p1R, midL: midL, midR: midR,
                           pawC1: pawC1, pawC2: pawC2, fill: closed, rim: rim, ink: ink)
        }

        func drawDragLimb(_ limb: DragLimb) {
            let g = limbGeo(limb)
            if isDazed, limb.armSpace != nil {
                // Authentic Monster Hunter Palico wide indigo sleeve + cream paw on front arms!
                var leftEdge: [CGPoint] = []
                var rightEdge: [CGPoint] = []
                for i in 0...8 {
                    let t = CGFloat(i) / 8.0, omt = 1.0 - t
                    leftEdge.append(CGPoint(
                        x: omt * omt * g.p0L.x + 2 * omt * t * g.midL.x + t * t * g.p1L.x,
                        y: omt * omt * g.p0L.y + 2 * omt * t * g.midL.y + t * t * g.p1L.y
                    ))
                    rightEdge.append(CGPoint(
                        x: omt * omt * g.p0R.x + 2 * omt * t * g.midR.x + t * t * g.p1R.x,
                        y: omt * omt * g.p0R.y + 2 * omt * t * g.midR.y + t * t * g.p1R.y
                    ))
                }
                let pawRect = CGRect(x: limb.tip.x - g.r1, y: limb.tip.y - g.r1 * 0.4, width: g.r1 * 2, height: g.r1 * 1.8)
                drawDazedArm(in: ctx, arm: g.fill, left: leftEdge, right: rightEdge, paw: pawRect)
                return
            }

            ctx.saveGState()
            ctx.addPath(g.fill)
            ctx.clip()
            let cs = CGColorSpaceCreateDeviceRGB()
            if isDazed {
                let cols = [dazedColor(0xE3C99F), dazedColor(0xC8A77A)] as CFArray
                if let grad = CGGradient(colorsSpace: cs, colors: cols, locations: [0.0, 1.0]) {
                    ctx.drawLinearGradient(grad, start: limb.root, end: limb.tip, options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
                }
            } else if skin.colorpoint {
                let mid = pal.pointsMid ?? pal.legs
                let cols = [pal.body.ns.cgColor, pal.body.ns.cgColor, mid.ns.cgColor, pal.paws.ns.cgColor] as CFArray
                if let grad = CGGradient(colorsSpace: cs, colors: cols, locations: [0.0, 0.20, 0.54, 0.88]) {
                    ctx.drawLinearGradient(grad, start: limb.root, end: limb.tip, options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
                }
            } else if !limb.isBehindBody && pal.legs != pal.body {
                let cols = [pal.body.ns.cgColor, pal.body.ns.cgColor, pal.legs.ns.cgColor, pal.paws.ns.cgColor] as CFArray
                if let grad = CGGradient(colorsSpace: cs, colors: cols, locations: [0.0, 0.14, 0.42, 0.82]) {
                    ctx.drawLinearGradient(grad, start: limb.root, end: limb.tip, options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
                }
            } else {
                let legCol = limb.isBehindBody ? (pal.hindLeg ?? pal.legs) : pal.legs
                let pawCol = limb.isBehindBody ? (pal.hindPaw ?? pal.paws) : pal.paws
                let cols = [legCol.ns.cgColor, pawCol.ns.cgColor] as CFArray
                if let grad = CGGradient(colorsSpace: cs, colors: cols, locations: [0.22, 0.75]) {
                    ctx.drawLinearGradient(grad, start: limb.root, end: limb.tip, options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
                }
            }

            // Map custom leftArm / rightArm / hindLeg regions & marks directly onto the dangling limbs!
            if let armSpace = limb.armSpace, skin.hasPartArt(armSpace) {
                let sign: CGFloat = (armSpace == .leftArm) ? -1.0 : ((armSpace == .hindLeg && limb.bendX < 0) ? -1.0 : 1.0)
                let armMap: (CGPoint) -> CGPoint = { p in
                    let t = max(0.0, min(1.0, p.x / 100.0))
                    let omt = 1.0 - t
                    let lx = omt * omt * g.p0L.x + 2 * omt * t * g.midL.x + t * t * g.p1L.x
                    let ly = omt * omt * g.p0L.y + 2 * omt * t * g.midL.y + t * t * g.p1L.y
                    let rx = omt * omt * g.p0R.x + 2 * omt * t * g.midR.x + t * t * g.p1R.x
                    let ry = omt * omt * g.p0R.y + 2 * omt * t * g.midR.y + t * t * g.p1R.y
                    let cx = (lx + rx) * 0.5, cy = (ly + ry) * 0.5
                    let hx = (rx - lx) * 0.5, hy = (ry - ly) * 0.5
                    let u = sign * (p.y / 10.0)
                    return CGPoint(x: cx + hx * u, y: cy + hy * u)
                }
                for region in skin.regions where region.space == armSpace { drawRegion(in: ctx, region, map: armMap) }
                for mark in skin.marks where mark.space == armSpace { drawMark(in: ctx, mark, map: armMap) }
            }
            ctx.restoreGState()

            // Trimmed open contour + 2 cute toe ticks
            ctx.saveGState()
            ctx.setStrokeColor(limbInk.cgColor)
            ctx.setLineWidth(isBlackRim ? 1.15 : 1.2)
            ctx.setLineCap(.round)
            ctx.setLineJoin(.round)
            ctx.addPath(g.ink)
            ctx.strokePath()
            for side in [-1.0, 1.0] as [CGFloat] {
                let a = CGPoint(x: limb.tip.x + g.nx * side * 2.5 + g.ux * 1.6, y: limb.tip.y + g.ny * side * 2.5 + g.uy * 1.6)
                let b = CGPoint(x: limb.tip.x + g.nx * side * 2.5 + g.ux * (limb.endW * 0.44), y: limb.tip.y + g.ny * side * 2.5 + g.uy * (limb.endW * 0.44))
                ctx.move(to: a); ctx.addLine(to: b)
            }
            ctx.strokePath()
            ctx.restoreGState()
        }

        ctx.saveGState()
        ctx.setAlpha(smoothstep(0.0, 0.22, lift))
        ctx.setLineCap(.round)
        ctx.setLineJoin(.round)

        // Gentle pendulum rotation anchored right at the lifted scruff pinch point between the ears!
        let bodyPendulum = max(-0.17, min(0.17, swingH * 0.16))
        if abs(bodyPendulum) > 0.001 {
            ctx.translateBy(x: scruffPinch.x, y: scruffPinch.y)
            ctx.rotate(by: bodyPendulum)
            ctx.translateBy(x: -scruffPinch.x, y: -scruffPinch.y)
        }

        // Pass 0 (ALL skins, when whiteOutline is enabled): unified sticker-style outer white silhouette rim painted FIRST
        if CatSettings.shared.whiteOutline {
            let extraOutlineW: CGFloat = (pal.outline != nil) ? 2.0 : 0.0
            let whiteRimW = blackOutlineWidth * 2.0 + extraOutlineW
            ctx.saveGState()
            ctx.setStrokeColor(blackOutlineColor.cgColor)
            ctx.setLineWidth(tailW + whiteRimW)
            ctx.addPath(tailCurvePath)
            ctx.strokePath()
            ctx.setLineWidth(whiteRimW)
            for l in [backLeftLimb, backRightLimb, frontLeftLimb, frontRightLimb] {
                ctx.addPath(limbGeo(l).rim)
                ctx.strokePath()
            }
            drawEarsLayer(in: ctx, center: headCenter, physics: physics, skin: skin, outlineOnly: true)
            ctx.addPath(longCatPath)
            ctx.strokePath()
            ctx.restoreGState()
        }

        // Optional skin-defined dark outer outline (drawn inside the white sticker border)
        if let customOutline = pal.outline, !isDazed {
            ctx.saveGState()
            ctx.setStrokeColor(customOutline.ns.cgColor)
            ctx.setLineWidth(tailW + 2.4)
            ctx.addPath(tailCurvePath)
            ctx.strokePath()
            ctx.setLineWidth(2.4)
            for l in [backLeftLimb, backRightLimb, frontLeftLimb, frontRightLimb] {
                ctx.addPath(limbGeo(l).rim)
                ctx.strokePath()
            }
            ctx.addPath(longCatPath)
            ctx.strokePath()
            ctx.restoreGState()
        }

        // 1. Limp drooping/whipping tail behind the lower body
        ctx.saveGState()
        ctx.setLineCap(.round)
        ctx.setStrokeColor(isDazed ? dazedColor(0x283157) : pal.tail.ns.cgColor)
        ctx.setLineWidth(tailW)
        ctx.addPath(tailCurvePath)
        ctx.strokePath()
        if let stripes = pal.stripes, !isBlackRim && !skin.colorpoint && !isDazed {
            func evalTailPt(_ t: CGFloat) -> CGPoint {
                let u = 1.0 - t
                return CGPoint(
                    x: u*u*u*tailPivot.x + 3*u*u*t*tailC1.x + 3*u*t*t*tailC2.x + t*t*t*tailTip.x,
                    y: u*u*u*tailPivot.y + 3*u*u*t*tailC1.y + 3*u*t*t*tailC2.y + t*t*t*tailTip.y
                )
            }
            ctx.setStrokeColor(stripes.ns.withAlphaComponent(0.42).cgColor)
            ctx.setLineWidth(tailW * 0.88)
            ctx.setLineCap(.butt)
            for t0 in [0.24, 0.50, 0.74] as [CGFloat] {
                ctx.move(to: evalTailPt(t0))
                ctx.addLine(to: evalTailPt(t0 + 0.09))
                ctx.strokePath()
            }
            ctx.setLineCap(.round)
        }
        if !isDazed, let tipColor = pal.tailTip {
            ctx.setStrokeColor(tipColor.ns.cgColor)
            ctx.setLineWidth(tailW * 0.92)
            ctx.move(to: lerpPt(tailC2, tailTip, 0.35))
            ctx.addLine(to: tailTip)
            ctx.strokePath()
        }
        if !isBlackRim && pal.outline == nil {
            ctx.setStrokeColor(NSColor(calibratedWhite: 0, alpha: 0.16).cgColor)
            ctx.setLineWidth(1.0)
            let strokedTail = tailCurvePath.copy(strokingWithWidth: tailW, lineCap: .round, lineJoin: .round, miterLimit: 2)
            ctx.addPath(strokedTail)
            ctx.strokePath()
        }
        ctx.restoreGState()

        // 2. Dangling hind legs emerging from the lower belly hem
        drawDragLimb(backLeftLimb)
        drawDragLimb(backRightLimb)

        // 3. Native 3D Ears tucked cleanly behind the head crown (seamless ear bases just like seated mode!)
        drawEarsLayer(in: ctx, center: headCenter, physics: physics, skin: skin)

        // 4. Unified Front-Facing Long-Cat Head + Subtle Scruff Pinch + Stretched Torso
        let headMap: (CGPoint) -> CGPoint = { Self.headPoint($0, skull: false, skin: skin, head: headCenter, physics: physics) }
        let headWhiteMap: (CGPoint) -> CGPoint = { Self.headPoint($0, skull: false, skin: skin, head: headCenter, physics: physics, whiteSurface: true) }
        let skullMap: (CGPoint) -> CGPoint = { Self.headPoint($0, skull: true, skin: skin, head: headCenter, physics: physics) }

        if isDazed {
            // Authentic stretched Monster Hunter Palico hood + indigo tunic + cream lower tummy
            let cs = CGColorSpaceCreateDeviceRGB()
            ctx.saveGState()
            ctx.addPath(longCatPath)
            ctx.clip()
            let bellyCols = [dazedColor(0xF4DFB8), dazedColor(0xC8A77A)] as CFArray
            if let grad = CGGradient(colorsSpace: cs, colors: bellyCols, locations: [0.0, 1.0]) {
                ctx.drawLinearGradient(grad, start: CGPoint(x: headCenter.x, y: headCenter.y + 30),
                                       end: CGPoint(x: rumpCenterX, y: torsoBottomY + bottomDip),
                                       options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
            }
            let tunicBotY = headCenter.y + torsoLen * 0.74
            let tunic = CGMutablePath()
            tunic.move(to: CGPoint(x: headCenter.x - cheekHalfW * 1.4, y: headCenter.y))
            tunic.addLine(to: CGPoint(x: headCenter.x + cheekHalfW * 1.4, y: headCenter.y))
            tunic.addLine(to: CGPoint(x: rumpCenterX + hipHalfW * 1.2, y: tunicBotY))
            tunic.addCurve(to: CGPoint(x: rumpCenterX - hipHalfW * 1.2, y: tunicBotY),
                           control1: CGPoint(x: rumpCenterX + hipHalfW * 0.5, y: tunicBotY + 14),
                           control2: CGPoint(x: rumpCenterX - hipHalfW * 0.5, y: tunicBotY + 14))
            tunic.closeSubpath()
            ctx.saveGState()
            ctx.addPath(tunic)
            ctx.clip()
            let clothCols = [dazedColor(0x555F9B), dazedColor(0x252E58)] as CFArray
            if let grad = CGGradient(colorsSpace: cs, colors: clothCols, locations: [0.0, 1.0]) {
                ctx.drawLinearGradient(grad, start: CGPoint(x: headCenter.x - 16, y: headCenter.y + 20),
                                       end: CGPoint(x: rumpCenterX + 12, y: tunicBotY + 10),
                                       options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
            }
            ctx.restoreGState()
            ctx.setStrokeColor(NSColor(calibratedRed: 124/255, green: 134/255, blue: 188/255, alpha: 0.65).cgColor)
            ctx.setLineWidth(1.3)
            ctx.move(to: CGPoint(x: rumpCenterX - hipHalfW, y: tunicBotY - 1))
            ctx.addCurve(to: CGPoint(x: rumpCenterX + hipHalfW, y: tunicBotY - 1),
                         control1: CGPoint(x: rumpCenterX - hipHalfW * 0.45, y: tunicBotY + 11),
                         control2: CGPoint(x: rumpCenterX + hipHalfW * 0.45, y: tunicBotY + 11))
            ctx.strokePath()
            ctx.restoreGState()

            // Full fluffy Palico hood around head (outside narrow torso clip, matching seated drawDazedSilhouette!)
            ctx.saveGState()
            ctx.translateBy(x: headCenter.x, y: headCenter.y)
            ctx.rotate(by: physics.headTilt.value)
            let hood = CGMutablePath()
            hood.move(to: CGPoint(x: 0.0, y: -33.0 - scruffTuftH))
            hood.addCurve(to: CGPoint(x: 48.0, y: 9.0), control1: CGPoint(x: 28.0, y: -35.0), control2: CGPoint(x: 48.0, y: -16.0))
            hood.addCurve(to: CGPoint(x: 0.0, y: 41.0), control1: CGPoint(x: 48.0, y: 32.0), control2: CGPoint(x: 25.0, y: 41.0))
            hood.addCurve(to: CGPoint(x: -48.0, y: 9.0), control1: CGPoint(x: -25.0, y: 41.0), control2: CGPoint(x: -48.0, y: 32.0))
            hood.addCurve(to: CGPoint(x: 0.0, y: -33.0 - scruffTuftH), control1: CGPoint(x: -48.0, y: -16.0), control2: CGPoint(x: -28.0, y: -35.0))
            hood.closeSubpath()
            ctx.addPath(hood)
            ctx.clip()
            let hoodCols = [dazedColor(0x6871B4), dazedColor(0x2F386D)] as CFArray
            if let grad = CGGradient(colorsSpace: cs, colors: hoodCols, locations: [0.0, 1.0]) {
                ctx.drawLinearGradient(grad, start: CGPoint(x: -16, y: -38), end: CGPoint(x: 15, y: 42),
                                       options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
            }
            ctx.restoreGState()
        } else {
            ctx.saveGState()
            ctx.setFillColor(pal.body.ns.cgColor)
            ctx.addPath(longCatPath)
            ctx.fillPath()
            ctx.addPath(longCatPath)
            ctx.clip()

            let cs = CGColorSpaceCreateDeviceRGB()
            if let shade = pal.bodyShade {
                let cols = [pal.body.ns.cgColor, shade.ns.cgColor] as CFArray
                if let grad = CGGradient(colorsSpace: cs, colors: cols, locations: [0.15, 1.0]) {
                    ctx.drawLinearGradient(grad, start: CGPoint(x: headCenter.x, y: headCenter.y - 36),
                                           end: CGPoint(x: rumpCenterX, y: torsoBottomY + bottomDip),
                                           options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
                }
            }

            // Curve regions with EXACT seated jaw-line clipping — 100% faithful to every custom skin!
            for region in skin.regions where region.space == .head || region.space == .skull || region.space == .body {
                ctx.saveGState()
                let side = SkinSpec.jawSide(head: region.space != .body, cheekFullness: skin.shape.cheekFullness)
                ctx.addPath(polyline(side, closed: true, map: headMap))
                ctx.clip()
                let map: (CGPoint) -> CGPoint = (region.space == .body) ? dragBodyMap : (region.space == .skull ? skullMap : headMap)
                drawRegion(in: ctx, region, map: map)
                ctx.restoreGState()
            }

            // 2.5D Colorpoint face mask (Siamese / Ragdoll)
            if let point = pal.points {
                let mid = pal.pointsMid ?? point
                ctx.saveGState()
                ctx.translateBy(x: headCenter.x, y: headCenter.y + 3.0)
                ctx.scaleBy(x: 1.22 * hs, y: 0.88 * hs)
                let maskCols = [point.ns.cgColor, point.withAlpha(0.92).cgColor, mid.withAlpha(0.62).cgColor, mid.withAlpha(0.0).cgColor] as CFArray
                if let g = CGGradient(colorsSpace: cs, colors: maskCols, locations: [0.0, 0.42, 0.74, 1.0]) {
                    ctx.drawRadialGradient(g, startCenter: .zero, startRadius: 0, endCenter: .zero, endRadius: 31.0, options: [.drawsBeforeStartLocation])
                }
                ctx.restoreGState()
            }

            // Marks: body marks first, then skull/head marks on top (exact seated draw order!)
            for mark in skin.marks where mark.space == .body {
                drawMark(in: ctx, mark, map: dragBodyMap)
            }
            for mark in skin.marks where mark.space == .head || mark.space == .skull {
                let map: (CGPoint) -> CGPoint = mark.space == .skull ? skullMap : (isMilkMark(mark) ? headWhiteMap : headMap)
                drawMark(in: ctx, mark, map: map)
            }
            ctx.restoreGState()

            if !isBlackRim {
                ctx.saveGState()
                ctx.setStrokeColor(pal.outline?.ns.cgColor ?? NSColor(calibratedRed: 0.18, green: 0.15, blue: 0.12, alpha: 0.22).cgColor)
                ctx.setLineWidth(pal.outline != nil ? 1.5 : 1.05)
                ctx.addPath(longCatPath)
                ctx.strokePath()
                ctx.restoreGState()
            }

            // Subtle soft chin shadow curve (gentle depth cue without cutting a hard ring through solid coats)
            ctx.saveGState()
            ctx.setStrokeColor(isBlackRim
                ? NSColor(calibratedWhite: 1.0, alpha: 0.16).cgColor
                : (pal.outline?.ns.withAlphaComponent(0.45).cgColor ?? NSColor(calibratedRed: 0.18, green: 0.15, blue: 0.12, alpha: 0.16).cgColor))
            ctx.setLineWidth(isBlackRim ? 1.05 : 1.0)
            ctx.move(to: CGPoint(x: headCenter.x - cheekHalfW * 0.56, y: headCenter.y + chinY - 2.5 * hs))
            ctx.addQuadCurve(to: CGPoint(x: headCenter.x + cheekHalfW * 0.56, y: headCenter.y + chinY - 2.5 * hs),
                             control: CGPoint(x: headCenter.x, y: headCenter.y + chinY + 3.5 * hs))
            ctx.strokePath()
            ctx.restoreGState()
        }

        // 5. Native KuroCat Face Features (normal authentic almond eyes — no round bug-eyes!)
        drawHeadFeatures(
            in: ctx,
            center: headCenter,
            physics: physics,
            eyeTheme: eyeTheme,
            skin: skin,
            scruffStartle: 0,
            scruffWide: 0
        )

        // 6. Dangling front arms hanging along the outer shoulder slopes (leaving central chest/belly 100% unobstructed!)
        drawDragLimb(frontLeftLimb)
        drawDragLimb(frontRightLimb)

        // 7. Skin stickers / decorations stay anchored cleanly to the lifted cat's head, neck, and whipping tail tip!
        if !skin.decorations.isEmpty {
            let dragNeck = CGPoint(x: headCenter.x + hipLagX * 0.08, y: headCenter.y + 36.0 * hs)
            drawDecorations(in: ctx, seatX: rumpCenterX, seatY: torsoBottomY, head: headCenter, physics: physics, skin: skin,
                            neckOverride: dragNeck, tailTipOverride: tailTip)
        }

        ctx.restoreGState()
    }
}
