import Foundation
import CoreGraphics
import AppKit

// MARK: - Themes & Settings

enum KeyboardTheme: String, CaseIterable {
    case classicMilk = "经典奶白暖黄 (原版)"
    case midnightHacker = "暗夜极客黑"
    case retroCream = "复古奶油灰"
}

enum CatCoatTheme: String, CaseIterable {
    case classicBlack = "经典小黑猫 (原版)"
    case siamese = "挖煤暹罗猫"
    case shorthair = "美短（银虎斑加白）"
    case orangeWhite = "橘白猫"
}

enum EyeColorTheme: String, CaseIterable {
    case neonChartreuse = "经典荧光黄绿 (原版)"
    case siameseBlue = "暹罗宝石蓝 (暹罗标配)"
    case warmAmber = "琥珀金瞳"
    case iceCyan = "冰晶浅蓝"
    case softAmber = "柔和琥珀"
    case referenceHazel = "淡金青绿"

    static func saved(_ raw: String) -> Self {
        raw == "淡金青绿（参考图）" ? .referenceHazel : (Self(rawValue: raw) ?? .neonChartreuse)
    }

    var primaryColor: NSColor {
        switch self {
        case .neonChartreuse: return NSColor(calibratedRed: 0.79, green: 0.95, blue: 0.25, alpha: 1.0) // #C9F240
        case .siameseBlue:    return NSColor(calibratedRed: 0.69, green: 0.855, blue: 0.95, alpha: 1.0) // #B0DAF2 通透浅淡冰蓝
        case .warmAmber:      return NSColor(calibratedRed: 0.98, green: 0.76, blue: 0.22, alpha: 1.0)
        case .iceCyan:        return NSColor(calibratedRed: 0.45, green: 0.92, blue: 0.96, alpha: 1.0)
        case .referenceHazel: return NSColor(calibratedRed: 218.0/255, green: 178.0/255, blue: 87.0/255, alpha: 1)
        case .softAmber: return NSColor(calibratedRed: 217.0/255, green: 173.0/255, blue: 85.0/255, alpha: 1)
        }
    }

    var glowColor: NSColor {
        switch self {
        case .neonChartreuse: return NSColor(calibratedRed: 0.77, green: 0.95, blue: 0.24, alpha: 0.85)
        case .siameseBlue:    return NSColor(calibratedRed: 0.68, green: 0.85, blue: 0.95, alpha: 0.80)
        case .warmAmber:      return NSColor(calibratedRed: 0.98, green: 0.74, blue: 0.20, alpha: 0.85)
        case .iceCyan:        return NSColor(calibratedRed: 0.42, green: 0.90, blue: 0.98, alpha: 0.85)
        case .referenceHazel: return NSColor(calibratedRed: 218.0/255, green: 178.0/255, blue: 87.0/255, alpha: 0.85)
        case .softAmber: return NSColor(calibratedRed: 217.0/255, green: 173.0/255, blue: 85.0/255, alpha: 0.85)
        }
    }
}

final class CatSettings {
    static let shared = CatSettings()

    var showKeyBadges: Bool {
        didSet { UserDefaults.standard.set(showKeyBadges, forKey: "KuroCat.ShowKeyBadges") }
    }
    var showMouseBadges: Bool {
        didSet { UserDefaults.standard.set(showMouseBadges, forKey: "KuroCat.ShowMouseBadges") }
    }
    var showKeyLegends: Bool {
        didSet { UserDefaults.standard.set(showKeyLegends, forKey: "KuroCat.ShowKeyLegends") }
    }
    var footEasterEgg: Bool {
        didSet { UserDefaults.standard.set(footEasterEgg, forKey: "KuroCat.FootEasterEgg") }
    }
    var tailEasterEgg: Bool {
        didSet { UserDefaults.standard.set(tailEasterEgg, forKey: "KuroCat.TailEasterEgg") }
    }
    var keyboardMarquee: Bool {
        didSet { UserDefaults.standard.set(keyboardMarquee, forKey: "KuroCat.KeyboardMarquee") }
    }
    /// 0 = normal desktop overlay, 1 = OBS transparent window capture, 2 = OBS green screen (#00FF00)
    var obsCaptureMode: Int {
        didSet { UserDefaults.standard.set(obsCaptureMode, forKey: "KuroCat.OBSCaptureMode") }
    }
    /// When true in OBS mode, hide cat behind desktop/offscreen while OBS still captures live frames
    var obsHideDesktop: Bool {
        didSet { UserDefaults.standard.set(obsHideDesktop, forKey: "KuroCat.OBSHideDesktop") }
    }
    /// Automatically hide the pet when another app enters fullscreen
    var autoHideFullscreen: Bool {
        didSet { UserDefaults.standard.set(autoHideFullscreen, forKey: "KuroCat.AutoHideFullscreen") }
    }
    /// 0 = Auto-detect graphics tablet/stylus, 1 = Always show tablet, 2 = Always show mouse
    var tabletMode: Int {
        didSet { UserDefaults.standard.set(tabletMode, forKey: "KuroCat.TabletMode") }
    }
    var flipHorizontal: Bool {
        didSet { UserDefaults.standard.set(flipHorizontal, forKey: "KuroCat.FlipHorizontal") }
    }
    /// Rotation angle in degrees [-180, 180], persisted across restarts
    var rotationDeg: CGFloat {
        didSet { UserDefaults.standard.set(Double(rotationDeg), forKey: "KuroCat.RotationDeg") }
    }
    /// Sticker-style crisp white outer outline around the cat (optional in Settings)
    var whiteOutline: Bool {
        didSet { UserDefaults.standard.set(whiteOutline, forKey: "KuroCat.WhiteOutline") }
    }
    /// Fast-typing angry expression toggle (optional in Settings)
    var enableAnger: Bool {
        didSet { UserDefaults.standard.set(enableAnger, forKey: "KuroCat.EnableAnger") }
    }
    /// Scruff-lifted drag animation toggle (optional in Settings; when off, dragging keeps seated pose)
    var enableDragAnimation: Bool {
        didSet { UserDefaults.standard.set(enableDragAnimation, forKey: "KuroCat.EnableDragAnimation") }
    }
    /// "zh" or "en"
    var language: String {
        didSet { UserDefaults.standard.set(language, forKey: "KuroCat.Language") }
    }
    var isEnglish: Bool { language == "en" }
    /// Runtime-only interactive resize & flip bounding box (toggled via double-click or menu)
    var isEditMode: Bool = false
    var petInteraction: Bool {
        didSet { UserDefaults.standard.set(petInteraction, forKey: "KuroCat.PetInteraction") }
    }
    var fullClickThrough: Bool {
        didSet { UserDefaults.standard.set(fullClickThrough, forKey: "KuroCat.FullClickThrough") }
    }
    var fullScreenOverlay: Bool {
        didSet { UserDefaults.standard.set(fullScreenOverlay, forKey: "KuroCat.FullScreenOverlay") }
    }
    var scale: CGFloat {
        didSet { UserDefaults.standard.set(Double(scale), forKey: "KuroCat.Scale") }
    }
    var coatTheme: CatCoatTheme {
        didSet { UserDefaults.standard.set(coatTheme.rawValue, forKey: "KuroCat.CoatTheme") }
    }
    var keyboardTheme: KeyboardTheme {
        didSet { UserDefaults.standard.set(keyboardTheme.rawValue, forKey: "KuroCat.KeyboardTheme") }
    }
    var eyeTheme: EyeColorTheme {
        didSet { UserDefaults.standard.set(eyeTheme.rawValue, forKey: "KuroCat.EyeTheme") }
    }
    /// Content id of the imported .kurocat skin in use; empty = the built-in coatTheme.
    var customSkin: String {
        didSet { UserDefaults.standard.set(customSkin, forKey: "KuroCat.CustomSkin") }
    }
    /// The skin the renderer draws: the imported one while its file still exists, else the built-in coat.
    var activeSkin: SkinSpec {
        SkinLibrary.shared.skin(id: customSkin) ?? SkinSpec.builtIn(coatTheme)
    }
    /// Content id of the imported .kurokb / keyboard.json skin in use; empty = the built-in keyboardTheme.
    var customKeyboard: String {
        didSet { UserDefaults.standard.set(customKeyboard, forKey: "KuroCat.CustomKeyboard") }
    }
    /// The keyboard/mouse skin the renderer draws: the imported one while its file still exists, else built-in.
    var activeKeyboardSkin: KeyboardSkinSpec {
        KeyboardSkinLibrary.shared.skin(id: customKeyboard) ?? KeyboardSkinSpec.builtIn(keyboardTheme)
    }

    private init() {
        let d = UserDefaults.standard
        showKeyBadges = d.object(forKey: "KuroCat.ShowKeyBadges") as? Bool ?? true
        showMouseBadges = d.object(forKey: "KuroCat.ShowMouseBadges") as? Bool ?? true
        showKeyLegends = d.object(forKey: "KuroCat.ShowKeyLegends") as? Bool ?? true
        footEasterEgg = d.object(forKey: "KuroCat.FootEasterEgg") as? Bool ?? true
        tailEasterEgg = d.object(forKey: "KuroCat.TailEasterEgg") as? Bool ?? true
        keyboardMarquee = d.object(forKey: "KuroCat.KeyboardMarquee") as? Bool ?? true
        obsCaptureMode = d.object(forKey: "KuroCat.OBSCaptureMode") as? Int ?? 0
        obsHideDesktop = d.object(forKey: "KuroCat.OBSHideDesktop") as? Bool ?? false
        autoHideFullscreen = d.object(forKey: "KuroCat.AutoHideFullscreen") as? Bool ?? false
        tabletMode = d.object(forKey: "KuroCat.TabletMode") as? Int ?? 0
        flipHorizontal = d.object(forKey: "KuroCat.FlipHorizontal") as? Bool ?? false
        rotationDeg = CGFloat(d.object(forKey: "KuroCat.RotationDeg") as? Double ?? 0.0)
        whiteOutline = d.object(forKey: "KuroCat.WhiteOutline") as? Bool ?? true
        enableAnger = d.object(forKey: "KuroCat.EnableAnger") as? Bool ?? true
        enableDragAnimation = d.object(forKey: "KuroCat.EnableDragAnimation") as? Bool ?? true
        language = d.string(forKey: "KuroCat.Language") ?? "zh"
        petInteraction = d.object(forKey: "KuroCat.PetInteraction") as? Bool ?? true
        fullClickThrough = d.object(forKey: "KuroCat.FullClickThrough") as? Bool ?? false
        fullScreenOverlay = d.object(forKey: "KuroCat.FullScreenOverlay") as? Bool ?? true
        let savedScale = d.double(forKey: "KuroCat.Scale")
        scale = savedScale > 0.3 ? CGFloat(savedScale) : 1.0
        coatTheme = CatCoatTheme(rawValue: d.string(forKey: "KuroCat.CoatTheme") ?? "") ?? .classicBlack
        keyboardTheme = KeyboardTheme(rawValue: d.string(forKey: "KuroCat.KeyboardTheme") ?? "") ?? .classicMilk
        let savedEye = d.string(forKey: "KuroCat.EyeTheme") ?? ""
        eyeTheme = EyeColorTheme.saved(savedEye)
        customSkin = d.string(forKey: "KuroCat.CustomSkin") ?? ""
        customKeyboard = d.string(forKey: "KuroCat.CustomKeyboard") ?? ""
    }
}

// MARK: - Spring Primitives

struct Spring1D {
    var value: CGFloat
    var velocity: CGFloat = 0
    var target: CGFloat

    init(_ initial: CGFloat) {
        self.value = initial
        self.target = initial
    }

    mutating func step(dt: CGFloat, stiffness: CGFloat = 260, damping: CGFloat = 22) {
        let force = (target - value) * stiffness
        let damp = velocity * damping
        velocity += (force - damp) * dt
        value += velocity * dt
    }
}

struct Spring2D {
    var x: Spring1D
    var y: Spring1D

    init(_ pt: CGPoint) {
        self.x = Spring1D(pt.x)
        self.y = Spring1D(pt.y)
    }

    var point: CGPoint { CGPoint(x: x.value, y: y.value) }
    var target: CGPoint {
        get { CGPoint(x: x.target, y: y.target) }
        set { x.target = newValue.x; y.target = newValue.y }
    }

    mutating func step(dt: CGFloat, stiffness: CGFloat = 340, damping: CGFloat = 25) {
        x.step(dt: dt, stiffness: stiffness, damping: damping)
        y.step(dt: dt, stiffness: stiffness, damping: damping)
    }
}

// MARK: - Particles

struct FloatingKeycap {
    let id: Int
    let label: String
    var position: CGPoint
    var velocity: CGPoint
    var age: CGFloat = 0
    let lifetime: CGFloat = 1.25
    var rotation: CGFloat
}

struct PurrSparkle {
    var position: CGPoint
    var velocity: CGPoint
    var age: CGFloat = 0
    let lifetime: CGFloat = 0.9
    let isSleepZ: Bool
}

struct ScriptedFrameInput {
    var now: CFTimeInterval
    var activeKeys: Set<PhysicalKey>
    var orderedKeys: [PhysicalKey]
    var mouseScreenPos: CGPoint
    var mouseVelocity: CGVector
    var leftMouseDown: Bool
    var rightMouseDown: Bool
    var lastMouseMoveTime: CFTimeInterval
    var lastMouseClickTime: CFTimeInterval
    var lastKeyActivityTime: CFTimeInterval
}

// MARK: - Cat Physics & Procedural Animation State

final class CatPhysics {
    // Logical canvas dimensions
    static let canvasSize = CGSize(width: 360, height: 320)

    // Rest positions
    static let seatAnchor = CGPoint(x: 184, y: 226)
    static let leftPawRest = CGPoint(x: 164, y: 235)
    static let rightPawRest = CGPoint(x: 204, y: 235)
    static let hindFootRest = CGPoint(x: 214, y: 234)
    static let mouseBaseCenter = CGPoint(x: 78, y: 258)

    // Springs
    var leftPaw = Spring2D(leftPawRest)
    var rightPaw = Spring2D(rightPawRest)
    var hindFoot = Spring2D(hindFootRest)
    var hindFootActive = Spring1D(0) // 0 = tucked, 1 = kicking 3rd key
    var tailTip = Spring2D(CGPoint(x: 275, y: 196))
    var tailTyping = Spring1D(0)
    var tailFlick = Spring2D(.zero)
    var tailCurl = Spring1D(0)
    var tailAgility = Spring1D(0)
    private var tailFlickHold: CGFloat = 0
    private var tailFlickCooldown: CGFloat = 0
    // Keyboard marquee: normalized position (0..1) of the light head, plus its speed boost.
    var marqueePhase: CGFloat = 0
    var marqueeBoost = Spring1D(0)

    var bodyShiftX = Spring1D(0)
    var bodyTilt = Spring1D(0)       // radians
    var bodySquash = Spring1D(1.0)
    var headTilt = Spring1D(0)       // radians (roll)
    var headYaw = Spring1D(0)        // -1 (turn left) ... +1 (turn right)
    var headPitch = Spring1D(0)      // -1 (look up)   ... +1 (look down)
    var headOffsetY = Spring1D(0)
    var earFold = Spring1D(0)        // 0 = alert, 1 = relaxed petting ears
    var earTwitch = Spring1D(0)

    var eyeGaze = Spring2D(.zero)    // normalized [-1..1, -1..1]
    var pupilScale = Spring1D(1.0)
    var huntIntensity = Spring1D(0)  // 0 = normal slit pupils, 1 = full hunting crouch + big round boba pupils!
    var scruffDrag = Spring1D(0)      // 0 = seated, 1 = picked up by neck scruff
    var scruffSwing = Spring1D(0)     // horizontal pendulum sway while dragged (+ = trails left when dragged right)
    var scruffSwingY = Spring1D(0)    // vertical inertia while dragged (+ = stretches down when lifted up, - = floats up when dropped)
    var scruffTailSwing = Spring1D(0) // looser secondary tail whip/billow while dragged
    var lieIntensity = Spring1D(0)    // 0 = sitting, 1 = lying cozily on keyboard while idle
    var angerIntensity = Spring1D(0)  // 0 = calm, 1 = angry from very fast typing
    var dizzyIntensity = Spring1D(0)  // 0 = clear, 1 = dizzy spiral eyes + slumped beside keyboard
    /// True while the cat lies down or sits up; a cat lying still (asleep) is not changing.
    var isChangingLie: Bool {
        abs(lieIntensity.target - lieIntensity.value) > 0.02 || abs(lieIntensity.velocity) > 0.02
    }
    private(set) var dizzyPhase: CGFloat = 0
    private(set) var isScruffDragging = false
    private var scruffDragDx: CGFloat = 0
    private var scruffDragDy: CGFloat = 0
    private var scruffDragAccumX: CGFloat = 0
    private var scruffDragAccumY: CGFloat = 0
    private var fastMouseDuration: CGFloat = 0
    private var dizzyTimer: CGFloat = 0
    private var fastTypeAccum: CGFloat = 0
    private var angerBurstTimer: CGFloat = 0
    private var angerCooldown: CGFloat = 0
    var mouseOffset = Spring2D(.zero)
    var mousePressLeft = Spring1D(0)
    var mousePressRight = Spring1D(0)

    // Graphics Tablet & Stylus state (auto-activates when a tablet/pen is connected or forced on!)
    static func tabletQuadPoint(u: CGFloat, v: CGFloat) -> CGPoint {
        let tl = CGPoint(x: 18, y: 235), tr = CGPoint(x: 94, y: 240)
        let bl = CGPoint(x: 13, y: 284), br = CGPoint(x: 91, y: 289)
        let topX = tl.x + (tr.x - tl.x) * u
        let topY = tl.y + (tr.y - tl.y) * u
        let botX = bl.x + (br.x - bl.x) * u
        let botY = bl.y + (br.y - bl.y) * u
        return CGPoint(x: topX + (botX - topX) * v, y: topY + (botY - topY) * v)
    }

    struct TabletStrokePoint {
        var point: CGPoint
        var age: CGFloat
    }

    private(set) var isTabletActive = false
    var tabletNib = Spring2D(CGPoint(x: 60, y: 261))
    var tabletPenPress = Spring1D(0)
    var tabletPenTilt = Spring1D(0)
    var tabletTrail: [TabletStrokePoint] = []

    // Paw mode flags (for crisp outline & posture rendering)
    private(set) var leftPawOnMouse = false
    private(set) var leftPawTyping = false
    private(set) var rightPawTyping = false

    // Keycap glow & press depths
    var keyGlow: [PhysicalKey: CGFloat] = [:]
    var floatingKeycaps: [FloatingKeycap] = []
    var sparkles: [PurrSparkle] = []
    private var nextBadgeID = 1
    private var badgeCascadeIndex = 0
    private var lastBadgeTime: CFTimeInterval = 0

    // Time & blink
    private(set) var time: CGFloat = 0
    private(set) var tailPhase: CGFloat = 0
    private var nextBlinkTime: CGFloat = 3.2
    private(set) var blinkProgress: CGFloat = 0 // 0 = open, 1 = closed
    private(set) var isBlinking = false
    private var blinkTimer: CGFloat = 0

    // Petting state
    private(set) var petHeadIntensity: CGFloat = 0  // 0..1 -> happy closed lime lines
    private(set) var petBodyIntensity: CGFloat = 0  // 0..1 -> blissful half-squint
    private(set) var totalPetSessions: Int = UserDefaults.standard.integer(forKey: "KuroCat.PetCount")
    private var petStrokeAccumulator: CGFloat = 0
    private var lastPetTime: CFTimeInterval = 0
    private var isCurrentlyPetting = false
    private var petCursorCanvasPos: CGPoint = .zero
    private var petSparkleCooldown: CGFloat = 0

    // Sleepy idle state
    private(set) var sleepiness: CGFloat = 0 // 0 = awake, 1 = napping
    private(set) var yawnAmount: CGFloat = 0 // 0 = closed, 1 = peak wide yawn before sleep
    private var yawnTimer: CGFloat = 0
    private(set) var isYawning = false
    private var hasYawnedThisIdle = false
    private var sleepZCooldown: CGFloat = 0

    // Recent key memory so fast single taps linger visibly (~140ms)
    private var recentLeftKey: (key: PhysicalKey, time: CFTimeInterval)?
    private var recentRightKey: (key: PhysicalKey, time: CFTimeInterval)?
    private var lastTypedPoint: CGPoint?

    // Video-2 Xiao Douni independent signed slap arm springs (-1 = slammed on key, 0 = ready, +1 = high windup)
    var douniSlapSide: Int = 0
    var douniSlapTimer: CGFloat = 0
    var douniLastLeftKeyTime: CFTimeInterval = -10
    var douniLastRightKeyTime: CFTimeInterval = -10
    var douniLeftRaise = Spring1D(0)
    var douniRightRaise = Spring1D(0)
    var douniLeftKeyTarget = Spring2D(CGPoint(x: 318, y: 422))
    var douniRightKeyTarget = Spring2D(CGPoint(x: 512, y: 462))
    var douniMouseBlend = Spring1D(0)
    var douniLoafBlend = Spring1D(0)
    var scruffHoldTime: CGFloat = 0
    var scruffDropTimer: CGFloat = 0
    // Disney 12-principles tactile keyboard impact recoil, tilt shudder & keycap spark burst
    var kbImpactY = Spring1D(0)
    var kbImpactTilt = Spring1D(0)
    var kbSparkTimer: CGFloat = 0
    var kbSparkKey: PhysicalKey? = nil

    // Computed eye closure (0 = wide open, 0.55 = half squint, 1 = fully closed)
    var effectiveEyeClosure: CGFloat {
        let petClose = max(petHeadIntensity * 1.0, petBodyIntensity * 0.62)
        let sleepClose = max(sleepiness * 0.92, yawnAmount * 0.96)
        return min(1.0, max(blinkProgress, max(petClose, sleepClose)))
    }

    var breathingOffset: CGFloat { sin(time * 2.1) * 1.6 }

    /// True when eyes should draw the signature glowing lime horizontal closed-eye lines
    var isHappyClosedEyes: Bool {
        petHeadIntensity > 0.45
    }

    var isBlissfulSquint: Bool {
        petBodyIntensity > 0.35 && !isHappyClosedEyes
    }

    // MARK: - Input Hooks

    func triggerKeyDown(_ key: PhysicalKey, at timestamp: CFTimeInterval? = nil) {
        let now = timestamp ?? CACurrentMediaTime()
        let vk = key.visualKey
        keyGlow[vk] = 1.0

        let pt = KeyboardLayout.canvasPoint(for: vk)
        lastTypedPoint = pt

        // Snap memory to the appropriate paw with lively bounce velocity
        let active = InputEngine.shared.activeKeys
        let leftHeld = active.contains { $0.prefersLeftPaw }
        let rightHeld = active.contains { !$0.prefersLeftPaw }

        if key.prefersLeftPaw {
            recentLeftKey = (vk, now)
            leftPaw.y.velocity -= 180
        } else if !rightHeld || !leftHeld {
            recentRightKey = (vk, now)
            rightPaw.y.velocity -= 180
        } else {
            recentRightKey = (vk, now)
            rightPaw.y.velocity -= 180
        }

        // Expressive micro-reactions
        if CatSettings.shared.activeSkin.typingStyle == .douni {
            let keyPt = KeyboardLayout.v2KeyCellCenter(for: vk)
            let useLeft = vk.prefersLeftPaw
            douniSlapSide = useLeft ? 0 : 1
            douniSlapTimer = 0.28
            douniMouseBlend.target = 0
            if douniMouseBlend.value > 0.05 {
                douniMouseBlend.velocity = min(douniMouseBlend.velocity, -14.0)
            }
            douniLoafBlend.target = 0
            let angerBoost: CGFloat = 1.0 + max(0, min(1, angerIntensity.value)) * 0.35
            if useLeft {
                let chordOther = (now - douniLastRightKeyTime) < 0.035
                douniLastLeftKeyTime = now
                douniLeftKeyTarget.target = keyPt
                // Independent signed spring (-1 = slam on keycap, +1 = flung high):
                // On rapid same-side repeat, visibly pop up (+0.50) then whip down so EVERY keystroke re-slaps cleanly!
                if douniLeftRaise.value < -0.15 {
                    douniLeftRaise.value = 0.50
                    douniLeftRaise.velocity = -15.5 * angerBoost
                } else {
                    douniLeftRaise.velocity = -22.0 * angerBoost
                }
                douniLeftRaise.target = -1.0
                if !chordOther {
                    douniRightRaise.target = 1.02
                    douniRightRaise.velocity = max(douniRightRaise.velocity + 6.0, 17.0 * angerBoost)
                }
                leftPaw.y.velocity += 220
            } else {
                let chordOther = (now - douniLastLeftKeyTime) < 0.035
                douniLastRightKeyTime = now
                douniRightKeyTarget.target = keyPt
                if douniRightRaise.value < -0.15 {
                    douniRightRaise.value = 0.50
                    douniRightRaise.velocity = -15.5 * angerBoost
                } else {
                    douniRightRaise.velocity = -22.0 * angerBoost
                }
                douniRightRaise.target = -1.0
                if !chordOther {
                    douniLeftRaise.target = 1.02
                    douniLeftRaise.velocity = max(douniLeftRaise.velocity + 6.0, 17.0 * angerBoost)
                }
                rightPaw.y.velocity += 220
            }
            // Disney Squash & Stretch + Impact Recoil + Secondary Action on keyboard, cord & ears!
            kbImpactY.velocity += 24.0 * angerBoost
            kbImpactTilt.velocity += (useLeft ? -10.5 : 10.5) * angerBoost
            kbSparkTimer = 0.14
            kbSparkKey = vk
            bodySquash.velocity -= 2.2
            headOffsetY.velocity += 44
            earTwitch.velocity += (useLeft ? -6.5 : 6.5)
            headTilt.velocity += (useLeft ? -2.8 : 2.8)
            pupilScale.target = 1.24
        } else {
            bodySquash.velocity -= 1.3
            earTwitch.velocity += (key.prefersLeftPaw ? -3.8 : 3.8)
            headTilt.velocity += (key.prefersLeftPaw ? -1.4 : 1.4)
            pupilScale.target = 1.16
        }

        // Wake up immediately
        sleepiness = 0

        // Spawn floating keycap badge
        if CatSettings.shared.showKeyBadges {
            spawnFloatingKeycap(label: key.badgeLabel, near: pt, now: now)
        }
    }

    func triggerMouseClick(button: Int, isDown: Bool) {
        sleepiness = 0
        if isDown {
            let now = CACurrentMediaTime()
            if CatSettings.shared.activeSkin.renderStyle == .douni {
                douniSlapTimer = 0
                douniLeftRaise.target = 0
                douniRightRaise.target = 0
                douniLoafBlend.target = 0
                douniMouseBlend.target = 1.0
            }
            if button == 0 {
                mousePressLeft.target = 1.0
                leftPaw.y.velocity += 130
            } else {
                mousePressRight.target = 1.0
                leftPaw.y.velocity += 110
            }
            pupilScale.target = 1.12
            earTwitch.velocity -= 2.2
            if CatSettings.shared.showMouseBadges {
                let en = CatSettings.shared.isEnglish
                let label = button == 0 ? (en ? "LMB" : "左键") : (button == 1 ? (en ? "RMB" : "右键") : (en ? "MMB" : "中键"))
                let pt = CGPoint(
                    x: CatPhysics.mouseBaseCenter.x + mouseOffset.point.x,
                    y: CatPhysics.mouseBaseCenter.y + mouseOffset.point.y - 6
                )
                spawnFloatingKeycap(label: label, near: pt, now: now)
            }
        } else {
            if button == 0 { mousePressLeft.target = 0 }
            else { mousePressRight.target = 0 }
        }
    }

    /// Called by OverlayWindow when the user drags the cat window (triggers scruff-pickup posture when enabled!).
    func setDragging(_ dragging: Bool, dragDx: CGFloat = 0, dragDy: CGFloat = 0) {
        let effectiveDragging = dragging && CatSettings.shared.enableDragAnimation
        let wasDragging = isScruffDragging
        isScruffDragging = effectiveDragging
        if effectiveDragging {
            if !wasDragging {
                scruffHoldTime = 0
                scruffDropTimer = 0
                scruffDragAccumX = 0
                scruffDragAccumY = 0
            }
            scruffDragAccumX += dragDx
            scruffDragAccumY += dragDy
            sleepiness = 0
            dizzyTimer = 0
            fastMouseDuration = 0
        } else {
            scruffDragDx = 0
            scruffDragDy = 0
            scruffDragAccumX = 0
            scruffDragAccumY = 0
            if wasDragging {
                scruffDropTimer = 0.16
                // Cute soft squash bounce when set back down (Video 1 drop settle!)
                bodySquash.velocity -= 2.4
                headOffsetY.velocity += 78
            }
        }
    }

    /// Called by the overlay window when cursor hovers near the cat's tail: whips away flexibly!
    func updateTailHover(canvasPoint cp: CGPoint?) {
        guard let cp, tailTyping.value < 0.25 else { return }
        let seatX = CatPhysics.seatAnchor.x + bodyShiftX.value
        let seatY = CatPhysics.seatAnchor.y
        let hunt = max(0, min(1, huntIntensity.value))
        let agility = max(0, min(1, tailAgility.value))
        let wag1 = sin(tailPhase) * (8.0 + hunt * 5.5 + agility * 4.0)
        let wag2 = cos(tailPhase * 1.3) * (6.0 + hunt * 4.5 + agility * 3.5)
        let huntDrop = hunt * 14.0
        let fx = tailFlick.point.x
        let fy = tailFlick.point.y
        let curl = tailCurl.value

        let root = CGPoint(x: seatX + 34, y: seatY - 6)
        let c1 = CGPoint(x: seatX + 64 + fx * 0.25, y: seatY + 2 + wag1 * 0.35 + huntDrop * 0.4 + fy * 0.22 + curl * 0.35)
        let c2 = CGPoint(x: seatX + 66 + wag2 * 0.4 + fx * 0.65 - curl * 0.45, y: seatY - 26 + wag1 * 0.7 + huntDrop + fy * 0.60 - curl * 0.55)
        let tip = CGPoint(x: seatX + 91 + wag2 * 0.5 + fx, y: seatY - 30 + wag1 * 0.85 + huntDrop + fy)

        var bestDist: CGFloat = .greatestFiniteMagnitude
        var bestPt = tip
        for t: CGFloat in [0.35, 0.58, 0.80, 1.0] {
            let u = 1 - t
            let pt = CGPoint(
                x: u*u*u*root.x + 3*u*u*t*c1.x + 3*u*t*t*c2.x + t*t*t*tip.x,
                y: u*u*u*root.y + 3*u*u*t*c1.y + 3*u*t*t*c2.y + t*t*t*tip.y
            )
            let d = hypot(pt.x - cp.x, pt.y - cp.y)
            if d < bestDist {
                bestDist = d
                bestPt = pt
            }
        }

        if bestDist < 24.0 {
            var ax = bestPt.x - cp.x
            var ay = bestPt.y - cp.y
            let len = hypot(ax, ay)
            if len < 1.0 {
                ax = 0.35
                ay = -0.94
            } else {
                ax /= len
                ay /= len
            }
            let targetX = max(-24.0, min(36.0, ax * 32.0 + (ax >= 0 ? 6.0 : -4.0)))
            let targetY = max(-44.0, min(38.0, ay * 40.0 + (ay < 0 ? -8.0 : 6.0)))
            tailFlick.target = CGPoint(x: targetX, y: targetY)
            tailCurl.target = ay >= 0 ? -18.0 : 20.0
            if tailFlickCooldown <= 0 {
                tailFlick.x.velocity += ax * 240.0
                tailFlick.y.velocity += ay * 280.0
                tailCurl.velocity += (ay >= 0 ? -150.0 : 170.0)
                earTwitch.velocity += 1.4
                tailFlickCooldown = 0.16
            }
            tailFlickHold = 0.30
            tailAgility.target = 1.0
            sleepiness = max(0, sleepiness - 0.15)
        }
    }

    /// Called by the overlay window when cursor strokes across the cat's head or body.
    func registerPetStroke(canvasPoint: CGPoint, delta: CGFloat, isHead: Bool, at timestamp: CFTimeInterval? = nil) {
        guard CatSettings.shared.petInteraction else { return }
        let now = timestamp ?? CACurrentMediaTime()
        lastPetTime = now
        petCursorCanvasPos = canvasPoint
        sleepiness = 0

        let energy = min(delta / 26.0, 0.35)
        if isHead {
            petHeadIntensity = min(1.0, petHeadIntensity + energy + 0.08)
            petBodyIntensity = max(petBodyIntensity, petHeadIntensity * 0.6)
        } else {
            petBodyIntensity = min(1.0, petBodyIntensity + energy + 0.07)
        }

        petStrokeAccumulator += delta
        if !isCurrentlyPetting && petStrokeAccumulator > 45 {
            isCurrentlyPetting = true
            totalPetSessions += 1
            UserDefaults.standard.set(totalPetSessions, forKey: "KuroCat.PetCount")
            UserDefaults.standard.synchronize()
        }

        // Gentle nuzzle toward cursor
        let dx = (canvasPoint.x - CatPhysics.seatAnchor.x) / 60.0
        headTilt.target = max(-0.18, min(0.18, dx * 0.16))
        headOffsetY.velocity += 18
    }

    private func spawnFloatingKeycap(label: String, near pt: CGPoint, now: CFTimeInterval) {
        if now - lastBadgeTime < 0.38 {
            badgeCascadeIndex = (badgeCascadeIndex + 1) % 6
        } else {
            badgeCascadeIndex = 0
        }
        lastBadgeTime = now

        // Spread fast bursts gracefully so they stay readable like "F O J F E A"
        let spreadOffsets: [CGFloat] = [-10, 14, -22, 26, 2, 36]
        let dx = spreadOffsets[badgeCascadeIndex] + CGFloat.random(in: -3...3)
        let startX = max(55, min(315, pt.x + dx * 0.45))
        let startY = pt.y - 26 - CGFloat(badgeCascadeIndex % 2) * 8

        let badge = FloatingKeycap(
            id: nextBadgeID,
            label: label,
            position: CGPoint(x: startX, y: startY),
            velocity: CGPoint(x: dx * 0.65, y: -36 - CGFloat.random(in: 0...14)),
            rotation: CGFloat.random(in: -0.07...0.07)
        )
        nextBadgeID += 1
        floatingKeycaps.append(badge)
        if floatingKeycaps.count > 16 {
            floatingKeycaps.removeFirst(floatingKeycaps.count - 16)
        }
    }

    // MARK: - 60 FPS Simulation Step

    func step(dt rawDt: CGFloat, windowFrameInScreen: CGRect, scripted: ScriptedFrameInput? = nil) {
        let dt = min(rawDt, 1.0 / 25.0)
        time += dt

        let engine = InputEngine.shared
        if scripted == nil {
            engine.pollMouse(dt: dt)
        }

        let now = scripted?.now ?? CACurrentMediaTime()
        let activeKeys = scripted?.activeKeys ?? engine.activeKeys
        let orderedKeys = scripted?.orderedKeys ?? engine.pressedOrder
        let curMouseVel = scripted?.mouseVelocity ?? engine.mouseVelocity
        let curMouseLoc = scripted?.mouseScreenPos ?? engine.lastMouseLocation
        let curLeftMouse = scripted?.leftMouseDown ?? engine.leftMouseDown
        let curRightMouse = scripted?.rightMouseDown ?? engine.rightMouseDown
        let curLastMouseMove = scripted?.lastMouseMoveTime ?? engine.lastMouseMoveTime
        let curLastMouseClick = scripted?.lastMouseClickTime ?? engine.lastMouseClickTime
        let curLastKeyTime = scripted?.lastKeyActivityTime ?? engine.lastKeyActivityTime

        // 1. Decay petting intensity gracefully when hand stops moving
        if now - lastPetTime > 0.28 {
            petHeadIntensity = max(0, petHeadIntensity - dt * 1.4)
            petBodyIntensity = max(0, petBodyIntensity - dt * 1.2)
            if petHeadIntensity < 0.05 && petBodyIntensity < 0.05 {
                isCurrentlyPetting = false
                petStrokeAccumulator = 0
            }
        } else if (petHeadIntensity > 0.55 || petBodyIntensity > 0.55) {
            petSparkleCooldown -= dt
            if petSparkleCooldown <= 0 {
                petSparkleCooldown = 0.42
                let sx = CatPhysics.seatAnchor.x + CGFloat.random(in: -44...44)
                let sy = 88 + CGFloat.random(in: -14...18)
                sparkles.append(PurrSparkle(
                    position: CGPoint(x: sx, y: sy),
                    velocity: CGPoint(x: CGFloat.random(in: -10...10), y: -24),
                    isSleepZ: false
                ))
            }
        }

        // 2. Sleepy idle detection (+ cute yawn right before drifting off to sleep!)
        let lastAnyActivity = max(curLastKeyTime, max(curLastMouseMove, lastPetTime))
        let idleSeconds = lastAnyActivity > 0 ? (now - lastAnyActivity) : 0
        if activeKeys.isEmpty && idleSeconds > 42 && !isYawning && !hasYawnedThisIdle {
            isYawning = true
            hasYawnedThisIdle = true
            yawnTimer = 0
        }
        if !activeKeys.isEmpty || idleSeconds < 5 {
            isYawning = false
            hasYawnedThisIdle = false
            yawnAmount = max(0, yawnAmount - dt * 6.0)
        } else if isYawning {
            yawnTimer += dt
            if yawnTimer < 0.65 {
                let u = yawnTimer / 0.65
                yawnAmount = u * u * (3 - 2 * u)
            } else if yawnTimer < 1.55 {
                yawnAmount = 1.0
            } else if yawnTimer < 2.35 {
                let u = (2.35 - yawnTimer) / 0.80
                yawnAmount = u * u * (3 - 2 * u)
            } else {
                yawnAmount = 0
                isYawning = false
            }
        } else {
            yawnAmount = max(0, yawnAmount - dt * 4.0)
        }
        if activeKeys.isEmpty && idleSeconds > 45 {
            let targetSleep = min(1.0, CGFloat((idleSeconds - 45) / 35.0))
            sleepiness += (targetSleep - sleepiness) * dt * 1.5
            if sleepiness > 0.8 {
                sleepZCooldown -= dt
                if sleepZCooldown <= 0 {
                    sleepZCooldown = 2.6
                    sparkles.append(PurrSparkle(
                        position: CGPoint(x: CatPhysics.seatAnchor.x + 42, y: 100),
                        velocity: CGPoint(x: 12, y: -18),
                        isSleepZ: true
                    ))
                }
            }
        } else {
            sleepiness = max(0, sleepiness - dt * 5.0)
        }

        // 2b. Fast Mouse Movement -> Hunting / Stalking Mode (dilated round boba pupils + low crouch!)
        // Sustained > 10s of rapid mouse shaking -> Dizzy spiral eyes & slump beside keyboard!
        let mouseSpeed = hypot(curMouseVel.dx, curMouseVel.dy)
        if !isScruffDragging && dizzyTimer <= 0 && mouseSpeed > 1500 && petHeadIntensity < 0.25 && petBodyIntensity < 0.25 {
            // Only rapid mouse shaking/flicking triggers hunting dilation (ignore casual movement)
            let boost = min(1.0, (mouseSpeed - 1500) / 1800.0)
            huntIntensity.target = min(1.0, huntIntensity.target + (0.40 + boost * 1.25) * dt)
            sleepiness = 0
        } else {
            // Calm down quickly once cursor stops darting
            huntIntensity.target = max(0.0, huntIntensity.target - dt * 1.15)
        }
        huntIntensity.step(dt: dt, stiffness: 85, damping: 16)
        let hunt = max(0, min(1, huntIntensity.value))

        if !isScruffDragging && dizzyTimer <= 0 && hunt > 0.42 {
            fastMouseDuration += dt
            if fastMouseDuration >= 10.0 {
                dizzyTimer = 6.0
                fastMouseDuration = 0
                huntIntensity.target = 0
                sleepiness = 0
            }
        } else if dizzyTimer <= 0 {
            fastMouseDuration = max(0, fastMouseDuration - dt * 1.5)
        }
        if dizzyTimer > 0 {
            dizzyTimer = max(0, dizzyTimer - dt)
            dizzyIntensity.target = 1.0
            dizzyPhase += dt * 7.5
        } else if fastMouseDuration > 6.8 {
            // Stage 2 (6.8s -> 10.0s): Pre-dizzy warning — stars appear first, then spiral eyes & upright wobble!
            let pre = min(1.0, (fastMouseDuration - 6.8) / 3.2)
            dizzyIntensity.target = pre * 0.48
            dizzyPhase += dt * 7.5
        } else {
            dizzyIntensity.target = 0.0
        }
        dizzyIntensity.step(dt: dt, stiffness: 75, damping: 14)
        let dizzy = max(0, min(1, dizzyIntensity.value))

        // 2c. Scruff-drag pickup, idle lie-on-keyboard, and episodic low-frequency fast-typing anger
        if !CatSettings.shared.enableDragAnimation && isScruffDragging {
            isScruffDragging = false
        }
        if isScruffDragging {
            scruffHoldTime += dt
            scruffDropTimer = 0
            let frameScale = (1.0 / 60.0) / max(dt, 1.0 / 120.0)
            let instDx = scruffDragAccumX * frameScale
            let instDy = scruffDragAccumY * frameScale
            scruffDragAccumX = 0
            scruffDragAccumY = 0
            scruffDragDx = scruffDragDx * 0.52 + instDx * 0.85
            scruffDragDy = scruffDragDy * 0.52 + instDy * 0.85
        } else {
            scruffDropTimer = max(0, scruffDropTimer - dt)
            if scruffDrag.value < 0.02 { scruffHoldTime = 0 }
            scruffDragDx *= 0.80
            scruffDragDy *= 0.80
        }
        scruffDrag.target = isScruffDragging ? 1.0 : 0.0
        // Positive scruffSwing when dragged right (+dx) rotates dangling tips left (trailing behind motion)
        scruffSwing.target = isScruffDragging ? 0.92 * tanh(scruffDragDx / 18.0) : 0.0
        // Positive scruffSwingY when dragged up (-dy) stretches limbs/tail down; negative when dragged down floats them up
        scruffSwingY.target = isScruffDragging ? 0.78 * tanh(-scruffDragDy / 18.0) : 0.0
        scruffTailSwing.target = isScruffDragging ? 1.22 * tanh(scruffDragDx / 16.0) : 0.0
        scruffDrag.step(dt: dt, stiffness: 190, damping: 17)
        scruffSwing.step(dt: dt, stiffness: 92, damping: 7.4)
        scruffSwingY.step(dt: dt, stiffness: 108, damping: 8.4)
        scruffTailSwing.step(dt: dt, stiffness: 58, damping: 5.2)
        let scruff = max(0, min(1, scruffDrag.value))

        lieIntensity.target = (!isScruffDragging && dizzyTimer <= 0 && sleepiness > 0.65)
            ? min(1.0, (sleepiness - 0.65) / 0.30) : 0.0
        lieIntensity.step(dt: dt, stiffness: 55, damping: 14)
        let lie = max(0, min(1, lieIntensity.value))

        // Low-frequency episodic anger: ~3.2s of brisk typing (>= 260 KPM) triggers a brief ~4.2s grumpy burst,
        // followed by a ~28s cooldown so fast typists get occasional cute anger without staying angry non-stop!
        let kpm = CGFloat(engine.currentKPM)
        if !CatSettings.shared.enableAnger || isScruffDragging || dizzyTimer > 0 {
            fastTypeAccum = 0
            angerBurstTimer = 0
            angerCooldown = max(0, angerCooldown - dt)
            angerIntensity.target = 0.0
        } else if angerBurstTimer > 0 {
            let sootheMul: CGFloat = (petHeadIntensity > 0.25 || petBodyIntensity > 0.25 || kpm < 80) ? 2.6 : 1.0
            angerBurstTimer = max(0, angerBurstTimer - dt * sootheMul)
            angerIntensity.target = min(1.0, angerBurstTimer / 0.7)
        } else {
            if angerCooldown > 0 {
                angerCooldown = max(0, angerCooldown - dt)
                fastTypeAccum = max(0, fastTypeAccum - dt * 1.2)
            } else if kpm >= 260 {
                let speedFactor = min(1.8, 0.75 + (kpm - 260.0) / 220.0)
                fastTypeAccum += dt * speedFactor
                if fastTypeAccum >= 3.2 {
                    angerBurstTimer = 4.2
                    angerCooldown = 28.0 + CGFloat(Int(time * 13) % 9) - 4.0 // 24..32s cooldown
                    fastTypeAccum = 0
                }
            } else {
                fastTypeAccum = max(0, fastTypeAccum - dt * 0.9)
            }
            angerIntensity.target = 0.0
        }
        angerIntensity.step(dt: dt, stiffness: 70, damping: 14)
        let anger = max(0, min(1, angerIntensity.value))

        // 3. Determine limb targets (Left Paw, Right Paw, 3rd-Key Hind Foot!)
        let tapHoldWindow: CFTimeInterval = 0.14
        let mouseRecent = (now - curLastMouseMove < 2.2) || curLeftMouse || curRightMouse
        let mouseActivelyUsed = (now - curLastMouseMove < 0.75) || curLeftMouse || curRightMouse

        // Partition active keys
        var leftCandidates: [PhysicalKey] = []
        var rightCandidates: [PhysicalKey] = []
        for k in orderedKeys {
            if k.prefersLeftPaw { leftCandidates.append(k) }
            else { rightCandidates.append(k) }
        }

        var leftKey: PhysicalKey? = leftCandidates.last
        var rightKey: PhysicalKey? = rightCandidates.last
        var footKey: PhysicalKey? = nil

        // If 2+ keys are pressed on the same side, let the free paw help —
        // UNLESS viewer-left paw (cat's right hand) is actively driving the mouse!
        if leftKey == nil && rightCandidates.count >= 2 && !mouseActivelyUsed {
            let sorted = rightCandidates.sorted {
                KeyboardLayout.canvasPoint(for: $0).x < KeyboardLayout.canvasPoint(for: $1).x
            }
            leftKey = sorted.first
            rightKey = sorted.last
        } else if rightKey == nil && leftCandidates.count >= 2 {
            let sorted = leftCandidates.sorted {
                KeyboardLayout.canvasPoint(for: $0).x < KeyboardLayout.canvasPoint(for: $1).x
            }
            leftKey = sorted.first
            rightKey = sorted.last
        }

        // 3+ simultaneous keys (or 2+ keys while other hand is busy on the mouse!) -> HIND FOOT EASTER EGG!!
        if CatSettings.shared.footEasterEgg {
            if orderedKeys.count >= 3 {
                footKey = orderedKeys.first { $0 != leftKey && $0 != rightKey }
            } else if mouseActivelyUsed && leftKey == nil && rightCandidates.count >= 2 {
                footKey = rightCandidates.first { $0 != rightKey }
            }
        }

        // Keep quick taps visible for a tiny snappy window
        if leftKey == nil, let rec = recentLeftKey, now - rec.time < tapHoldWindow {
            leftKey = rec.key
        }
        if rightKey == nil, let rec = recentRightKey, now - rec.time < tapHoldWindow {
            rightKey = rec.key
        }

        // Subtle mini-mouse movement driven by global cursor velocity
        let targetMouseDx = max(-5.5, min(5.5, curMouseVel.dx * 0.0045))
        let targetMouseDy = max(-4.5, min(4.5, -curMouseVel.dy * 0.0045))
        mouseOffset.target = CGPoint(x: targetMouseDx, y: targetMouseDy)
        mouseOffset.step(dt: dt, stiffness: 120, damping: 16)
        mousePressLeft.step(dt: dt, stiffness: 400, damping: 24)
        mousePressRight.step(dt: dt, stiffness: 400, damping: 24)

        let liveMouseCenter = CGPoint(
            x: CatPhysics.mouseBaseCenter.x + mouseOffset.point.x,
            y: CatPhysics.mouseBaseCenter.y + mouseOffset.point.y
        )

        // Graphics Tablet & Stylus mode (auto-switches when tablet/pen connected!)
        let tMode = CatSettings.shared.tabletMode
        isTabletActive = (tMode == 1) || (tMode == 0 && engine.isTabletConnected)
        if isTabletActive {
            let screenFrame = (NSScreen.screens.first { $0.frame.contains(curMouseLoc) } ?? NSScreen.main)?.frame
                ?? CGRect(x: 0, y: 0, width: 1440, height: 900)
            let nx = max(0, min(1, (curMouseLoc.x - screenFrame.minX) / max(1, screenFrame.width)))
            let ny = max(0, min(1, 1.0 - (curMouseLoc.y - screenFrame.minY) / max(1, screenFrame.height)))
            tabletNib.target = CatPhysics.tabletQuadPoint(u: 0.25 + nx * 0.64, v: 0.16 + ny * 0.68)
            tabletNib.step(dt: dt, stiffness: 240, damping: 20)
            let penDown = curLeftMouse || engine.penPressure > 0.02
            tabletPenPress.target = penDown ? max(0.65, min(1.0, engine.penPressure > 0.02 ? engine.penPressure : 0.85)) : 0.0
            tabletPenPress.step(dt: dt, stiffness: 360, damping: 22)
            tabletPenTilt.target = max(-0.22, min(0.22, curMouseVel.dx * 0.00018))
            tabletPenTilt.step(dt: dt, stiffness: 120, damping: 14)
        } else {
            tabletPenPress.target = 0
            tabletPenPress.step(dt: dt, stiffness: 300, damping: 22)
        }
        for i in stride(from: tabletTrail.count - 1, through: 0, by: -1) {
            tabletTrail[i].age += dt
            if tabletTrail[i].age >= 0.72 { tabletTrail.remove(at: i) }
        }

        let isDouniTyping = CatSettings.shared.activeSkin.typingStyle == .douni
        let isDouniSkin = CatSettings.shared.activeSkin.renderStyle == .douni
        if isDouniTyping {
            douniSlapTimer = max(0, douniSlapTimer - dt)
            let leftHeldNow = activeKeys.contains { $0.prefersLeftPaw }
            let rightHeldNow = activeKeys.contains { !$0.prefersLeftPaw }
            if douniSlapTimer <= 0.08 {
                if !leftHeldNow {
                    douniLeftRaise.target = 0
                } else if douniLeftRaise.target > 0.2 {
                    douniLeftRaise.target = -0.85
                }
                if !rightHeldNow {
                    douniRightRaise.target = 0
                } else if douniRightRaise.target > 0.2 {
                    douniRightRaise.target = -0.85
                }
            }
            douniLeftRaise.step(dt: dt, stiffness: 680, damping: 25)
            douniRightRaise.step(dt: dt, stiffness: 680, damping: 25)
            douniLeftKeyTarget.step(dt: dt, stiffness: 820, damping: 28)
            douniRightKeyTarget.step(dt: dt, stiffness: 820, damping: 28)
            kbImpactY.target = 0
            kbImpactTilt.target = 0
            kbImpactY.step(dt: dt, stiffness: 560, damping: 16)
            kbImpactTilt.step(dt: dt, stiffness: 500, damping: 14)
            kbSparkTimer = max(0, kbSparkTimer - dt)
        } else {
            douniSlapTimer = 0
            douniLeftRaise.target = 0
            douniRightRaise.target = 0
            kbImpactY.value = 0; kbImpactTilt.value = 0; kbSparkTimer = 0
        }
        if isDouniSkin {
            // Deliberate petting threshold (avoids abrupt hijacking on 1px cursor brush or fast hunting whip!) + silky Disney ease spring
            let wantsLoaf = !isScruffDragging && scruff < 0.08 && dizzy < 0.15 && hunt < 0.22
                && (petHeadIntensity > 0.30 || isCurrentlyPetting || petBodyIntensity > 0.35 || sleepiness > 0.48)
            douniLoafBlend.target = wantsLoaf ? 1.0 : 0.0
            douniLoafBlend.step(dt: dt, stiffness: 52, damping: 13.5)
            let typingNow = (douniSlapTimer > 0.04 || !activeKeys.isEmpty)
            let tabletUsed = isTabletActive && (engine.isPenInProximity || curLeftMouse || mouseActivelyUsed)
            let wantsMouse = !isScruffDragging && !wantsLoaf && !typingNow && (mouseActivelyUsed || tabletUsed)
            douniMouseBlend.target = wantsMouse ? 1.0 : 0.0
            douniMouseBlend.step(dt: dt, stiffness: wantsMouse ? 280 : 460, damping: wantsMouse ? 22 : 28)
            // Keep tablet ink trail alive for Xiao Douni when drawing on the hand-drawn comic tablet!
            if isTabletActive && wantsMouse && (curLeftMouse || engine.penPressure > 0.02) {
                let nib = tabletNib.point
                let last = tabletTrail.last?.point
                if last == nil || hypot(nib.x - last!.x, nib.y - last!.y) >= 1.8 {
                    tabletTrail.append(TabletStrokePoint(point: nib, age: 0))
                    if tabletTrail.count > 28 { tabletTrail.removeFirst() }
                }
            }
        } else {
            douniLoafBlend.value = 0; douniLoafBlend.target = 0
            douniMouseBlend.value = 0; douniMouseBlend.target = 0
        }
        let douniActive = isDouniTyping && (douniSlapTimer > 0.01 || !activeKeys.isEmpty) && scruff <= 0.25 && dizzy <= 0.35 && lie <= 0.45

        // Left paw target (Video 1 chubby mid-air dangling mittens during scruff / Video 2 Douni slap / normal typing)
        if scruff > 0.24 {
            let scruffS = scruff * scruff * (3.0 - 2.0 * scruff)
            let liftSeatY = CatPhysics.seatAnchor.y - scruffS * 44.0
            let sway = scruffSwing.value * 24.0 + sin(time * 7.6) * 3.0
            let bob = cos(time * 7.6) * 2.2
            leftPaw.target = CGPoint(x: CatPhysics.seatAnchor.x + bodyShiftX.value - 20 + sway, y: liftSeatY + 24 + bob)
            leftPawTyping = true
            leftPawOnMouse = false
        } else if dizzy > 0.35 {
            // Relaxed paws staying natural inside the toppled cat frame
            leftPaw.target = CatPhysics.leftPawRest
            leftPawTyping = false
            leftPawOnMouse = false
        } else if douniActive {
            let raise = max(0, min(1.18, douniLeftRaise.value))
            let sx = CatPhysics.seatAnchor.x + bodyShiftX.value
            let downPt = leftKey.map { KeyboardLayout.canvasPoint(for: $0) } ?? CGPoint(x: sx - 44, y: 246)
            let highPt = CGPoint(x: sx - 84, y: 156) // High windup beside left cheek (Video 2!)
            leftPaw.target = CGPoint(x: downPt.x + (highPt.x - downPt.x) * raise, y: downPt.y + (highPt.y - downPt.y) * raise)
            leftPawTyping = true
            leftPawOnMouse = false
        } else if let lk = leftKey {
            leftPaw.target = KeyboardLayout.canvasPoint(for: lk)
            leftPawTyping = true
            leftPawOnMouse = false
        } else if (mouseRecent || (isTabletActive && engine.isPenInProximity)) && sleepiness < 0.3 {
            if isTabletActive {
                let nib = tabletNib.point
                leftPaw.target = CGPoint(x: nib.x + 6, y: nib.y - 7)
                if curLeftMouse || engine.penPressure > 0.02 {
                    let last = tabletTrail.last?.point
                    if last == nil || hypot(nib.x - last!.x, nib.y - last!.y) >= 1.8 {
                        tabletTrail.append(TabletStrokePoint(point: nib, age: 0))
                        if tabletTrail.count > 28 { tabletTrail.removeFirst() }
                    }
                }
            } else {
                leftPaw.target = CGPoint(x: liveMouseCenter.x + 2, y: liveMouseCenter.y - 3)
            }
            leftPawTyping = false
            leftPawOnMouse = true
        } else {
            // Keep paws tucked neatly in rest position when curling into a sleeping cat ball!
            leftPaw.target = CatPhysics.leftPawRest
            leftPawTyping = false
            leftPawOnMouse = false
        }

        // Right paw target
        if scruff > 0.24 {
            let scruffS = scruff * scruff * (3.0 - 2.0 * scruff)
            let liftSeatY = CatPhysics.seatAnchor.y - scruffS * 44.0
            let sway = scruffSwing.value * 24.0 + sin(time * 7.6 + 2.1) * 3.0
            let bob = cos(time * 7.6 + 2.1) * 2.2
            rightPaw.target = CGPoint(x: CatPhysics.seatAnchor.x + bodyShiftX.value + 16 + sway, y: liftSeatY + 24 + bob)
            rightPawTyping = true
        } else if dizzy > 0.35 {
            rightPaw.target = CatPhysics.rightPawRest
            rightPawTyping = false
        } else if douniActive {
            let raise = max(0, min(1.18, douniRightRaise.value))
            let sx = CatPhysics.seatAnchor.x + bodyShiftX.value
            let downPt = rightKey.map { KeyboardLayout.canvasPoint(for: $0) } ?? CGPoint(x: sx + 22, y: 246)
            let highPt = CGPoint(x: sx - 8, y: 158) // High windup curled right across the cheek/face (Video 2!)
            rightPaw.target = CGPoint(x: downPt.x + (highPt.x - downPt.x) * raise, y: downPt.y + (highPt.y - downPt.y) * raise)
            rightPawTyping = true
        } else if let rk = rightKey {
            rightPaw.target = KeyboardLayout.canvasPoint(for: rk)
            rightPawTyping = true
        } else {
            rightPaw.target = CatPhysics.rightPawRest
            rightPawTyping = false
        }

        // Hind foot target (3rd simultaneous key!)
        if let fk = footKey {
            hindFoot.target = KeyboardLayout.canvasPoint(for: fk)
            hindFootActive.target = 1.0
        } else {
            hindFoot.target = CatPhysics.hindFootRest
            hindFootActive.target = 0.0
        }

        // Held physical keys determine the mode; repeats and mouse buttons do not count.
        // When both foot & tail are enabled: 3rd key -> hind foot, 4th key -> tail.
        // When tail-only mode is selected (!footEasterEgg && tailEasterEgg): 3+ keys (or 2+ keys while mouse is active) -> tail!
        let tailOnlyTrigger = !CatSettings.shared.footEasterEgg && (orderedKeys.count >= 3 || (mouseActivelyUsed && leftKey == nil && rightCandidates.count >= 2))
        let tailActiveNow = CatSettings.shared.tailEasterEgg && (activeKeys.count >= 4 || tailOnlyTrigger)
        tailTyping.target = tailActiveNow ? 1 : 0
        tailTyping.step(dt: dt, stiffness: 180, damping: 24)
        // Marquee chase across the keyboard deck: steady sweep, faster while many keys are held.
        if CatSettings.shared.keyboardMarquee {
            marqueeBoost.target = max(0, min(1, (CGFloat(activeKeys.count) - 2) / 5))
            marqueeBoost.step(dt: dt, stiffness: 90, damping: 20)
            marqueePhase = (marqueePhase + dt * (0.42 + 0.40 * marqueeBoost.value)).truncatingRemainder(dividingBy: 1.0)
        }
        let tailKey = orderedKeys.first { $0 != leftKey && $0 != rightKey && $0 != footKey }
        var tip = tailTyping.target > 0 ? tailKey.map { KeyboardLayout.canvasPoint(for: $0) } ?? CGPoint(x: 275, y: 196) : CGPoint(x: 275, y: 196)
        tip.y -= tailTyping.target * (1 + sin(time * 18)) * 3
        tailTip.target = tip
        tailTip.step(dt: dt, stiffness: 280, damping: 26)

        tailFlickHold = max(0, tailFlickHold - dt)
        tailFlickCooldown = max(0, tailFlickCooldown - dt)
        if tailFlickHold <= 0 {
            tailFlick.target = .zero
            tailCurl.target = 0
            tailAgility.target = 0
        }
        tailFlick.step(dt: dt, stiffness: 150, damping: 12)
        tailCurl.step(dt: dt, stiffness: 135, damping: 10.5)
        tailAgility.step(dt: dt, stiffness: 40, damping: 10)

        leftPaw.step(dt: dt, stiffness: 360, damping: 24)
        rightPaw.step(dt: dt, stiffness: 360, damping: 24)
        hindFoot.step(dt: dt, stiffness: 320, damping: 22)
        hindFootActive.step(dt: dt, stiffness: 260, damping: 22)

        // 4. Expressive body lean, squash, head & ears
        var targetShiftX: CGFloat = 0
        var targetBodyTilt: CGFloat = 0
        if leftPawOnMouse && !rightPawTyping {
            targetShiftX = -10
            targetBodyTilt = -0.075
        } else if leftPawOnMouse && rightPawTyping {
            targetShiftX = -3
            targetBodyTilt = (rightPaw.point.x - 196) * 0.0008
        } else if leftPawTyping || rightPawTyping {
            let avgX = ((leftPawTyping ? leftPaw.point.x : 184) + (rightPawTyping ? rightPaw.point.x : 184)) * 0.5
            targetShiftX = (avgX - 184) * 0.14
            targetBodyTilt = (avgX - 184) * 0.0011
        }
        bodyShiftX.target = max(-16, min(16, targetShiftX))
        bodyTilt.target = max(-0.12, min(0.12, targetBodyTilt)) + scruffSwing.value * scruff
        // Keep body sleek & natural during lie/dizzy (zero fat distortion; renderer handles smooth rigid fall & forward sprawl!)
        bodySquash.target = 1.0 - hunt * 0.11 + scruff * 0.16

        headOffsetY.target = ((leftPawTyping || rightPawTyping) ? 3.5 : (sleepiness * 5.0 + hunt * 10.5))
            - scruff * 10.0
        earFold.target = max(petHeadIntensity * 0.7, petBodyIntensity * 0.45) + sleepiness * 0.25 - hunt * 0.18
            + scruff * 0.35 + anger * 0.45 + dizzy * 0.35
        earTwitch.target = 0

        bodyShiftX.step(dt: dt, stiffness: 140, damping: 18)
        bodyTilt.step(dt: dt, stiffness: 140, damping: 18)
        bodySquash.step(dt: dt, stiffness: 280, damping: 18)
        headOffsetY.step(dt: dt, stiffness: 180, damping: 19)
        earFold.step(dt: dt, stiffness: 120, damping: 16)
        earTwitch.step(dt: dt, stiffness: 320, damping: 16)

        // 5. 2.5D Head Turning (Yaw + Pitch) + Eye Tracking!
        // Head smoothly turns in pseudo-3D toward the mouse cursor (or subtly nods down toward keys while typing).
        let typingRecently = !activeKeys.isEmpty || (now - curLastKeyTime < 0.65)
        let mouseMovedRecently = (now - curLastMouseMove < 1.2)
        let eyeOriginCanvas = CGPoint(x: CatPhysics.seatAnchor.x + bodyShiftX.value, y: 124 + headOffsetY.value)

        // Compute normalized vector from cat head to real macOS screen cursor
        let scale = max(0.2, windowFrameInScreen.width / CatPhysics.canvasSize.width)
        let headScreenX = windowFrameInScreen.minX + eyeOriginCanvas.x * scale
        let headScreenY = windowFrameInScreen.maxY - eyeOriginCanvas.y * scale
        let cursor = curMouseLoc
        let curDx = (cursor.x - headScreenX) / 290.0
        let curDy = -(cursor.y - headScreenY) / 260.0
        let curMag = hypot(curDx, curDy)
        let clampedCur = min(1.0, curMag)
        let cursorNX = curMag > 0.001 ? (curDx / curMag) * clampedCur : 0
        let cursorNY = curMag > 0.001 ? (curDy / curMag) * clampedCur : 0

        let lookTargetX: CGFloat
        let lookTargetY: CGFloat
        if typingRecently && !mouseMovedRecently, let keyPt = lastTypedPoint {
            let kdx = max(-0.85, min(0.85, (keyPt.x - eyeOriginCanvas.x) / 95.0))
            let kdy = max(-0.3, min(0.92, (keyPt.y - eyeOriginCanvas.y) / 125.0))
            lookTargetX = kdx
            lookTargetY = kdy
        } else if typingRecently && mouseMovedRecently, let keyPt = lastTypedPoint {
            // Blend mouse & typing naturally when gaming with mouse + keyboard!
            let kdx = max(-0.85, min(0.85, (keyPt.x - eyeOriginCanvas.x) / 95.0))
            lookTargetX = cursorNX * 0.72 + kdx * 0.28
            lookTargetY = cursorNY * 0.72 + 0.25
        } else {
            lookTargetX = cursorNX
            lookTargetY = cursorNY
        }

        // Head turns smoothly in 2.5D (yaw & pitch) — locks on faster during hunting mode!
        if sleepiness > 0.45 {
            headYaw.target = 0
            headPitch.target = 0.45 * sleepiness
        } else {
            headYaw.target = max(-1.0, min(1.0, lookTargetX))
            headPitch.target = max(-1.0, min(1.0, lookTargetY))
        }
        let headStiff: CGFloat = 88 + hunt * 75
        let headDamp: CGFloat = 14.5 + hunt * 4.5
        headYaw.step(dt: dt, stiffness: headStiff, damping: headDamp)
        headPitch.step(dt: dt, stiffness: headStiff, damping: headDamp)

        // Subtle natural head roll coupled to head turning (curious tilt / locked-on hunt!)
        if now - lastPetTime > 0.28 {
            headTilt.target = bodyTilt.target * 0.45 + headYaw.value * (0.11 + hunt * 0.05) - headYaw.value * headPitch.value * 0.04 + lie * 0.12
        }
        headTilt.step(dt: dt, stiffness: 130, damping: 16)

        // Eyes lead slightly ahead of the 2.5D head turn
        eyeGaze.target = CGPoint(x: lookTargetX * 0.88, y: lookTargetY * 0.85)
        eyeGaze.step(dt: dt, stiffness: 210 + hunt * 80, damping: 21)

        // Pupil dilation
        if hindFootActive.value > 0.3 {
            pupilScale.target = 1.24
        } else if now - curLastKeyTime > 0.45 && now - curLastMouseClick > 0.45 {
            pupilScale.target = 1.0
        }
        pupilScale.step(dt: dt, stiffness: 150, damping: 18)

        // 6. Blinking (cats lock eyes without blinking during hunting mode!)
        if isBlinking {
            blinkTimer += dt
            let blinkDuration: CGFloat = 0.14
            if blinkTimer >= blinkDuration {
                isBlinking = false
                blinkProgress = 0
                nextBlinkTime = time + CGFloat.random(in: 2.6...5.6)
            } else {
                let p = blinkTimer / blinkDuration
                blinkProgress = sin(p * .pi)
            }
        } else if time >= nextBlinkTime && sleepiness < 0.5 && petHeadIntensity < 0.3 && hunt < 0.35 {
            isBlinking = true
            blinkTimer = 0
        }

        // 7. Tail wag speed reacts organically to energy / petting / hunting tension!
        let kpmBoost = min(2.4, CGFloat(engine.currentKPM) / 160.0)
        let petBoost = max(petHeadIntensity, petBodyIntensity) * 1.4
        let huntBoost = hunt * 2.8
        let agilityBoost = max(0, min(1, tailAgility.value)) * 3.2
        let angerBoost = anger * 3.5
        let tailSpeed: CGFloat = 1.85 + kpmBoost + petBoost + huntBoost + agilityBoost + angerBoost - sleepiness * 1.1
        tailPhase += dt * tailSpeed

        // 8. Update per-keycap glows
        let visualActive = Set(activeKeys.map { $0.visualKey })
        for (k, v) in keyGlow {
            if visualActive.contains(k) {
                keyGlow[k] = 1.0
            } else {
                let next = v - dt * 4.5
                if next <= 0.01 { keyGlow.removeValue(forKey: k) }
                else { keyGlow[k] = next }
            }
        }
        for vk in visualActive {
            keyGlow[vk] = 1.0
        }

        // 9. Update floating keycaps
        for i in floatingKeycaps.indices.reversed() {
            floatingKeycaps[i].age += dt
            floatingKeycaps[i].position.x += floatingKeycaps[i].velocity.x * dt
            floatingKeycaps[i].position.y += floatingKeycaps[i].velocity.y * dt
            floatingKeycaps[i].velocity.x *= (1.0 - dt * 2.4)
            floatingKeycaps[i].velocity.y *= (1.0 - dt * 1.6)
            if floatingKeycaps[i].age >= floatingKeycaps[i].lifetime {
                floatingKeycaps.remove(at: i)
            }
        }

        // 10. Update purr / sleep particles
        for i in sparkles.indices.reversed() {
            sparkles[i].age += dt
            sparkles[i].position.x += sparkles[i].velocity.x * dt
            sparkles[i].position.y += sparkles[i].velocity.y * dt
            if sparkles[i].age >= sparkles[i].lifetime {
                sparkles.remove(at: i)
            }
        }
    }
}

// MARK: - Skins (.kurocat, formatVersion 1)
// Mirrors shared/SkinSpec.hpp (Windows/Linux); the format is documented in docs/skin-format.md.
// Kept in this file because build.sh compiles an explicit list of Swift sources.

struct SkinColor: Equatable {
    var r: CGFloat, g: CGFloat, b: CGFloat, a: CGFloat

    static func rgba(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat, _ a: CGFloat = 1) -> SkinColor {
        SkinColor(r: r, g: g, b: b, a: a)
    }
    /// Same arithmetic as CatRenderer's old `rgb(_:_:)` helper, so built-ins keep identical components.
    static func hex(_ rgb: Int, _ a: CGFloat = 1) -> SkinColor {
        SkinColor(r: CGFloat((rgb >> 16) & 255)/255, g: CGFloat((rgb >> 8) & 255)/255, b: CGFloat(rgb & 255)/255, a: a)
    }
    var ns: NSColor { NSColor(calibratedRed: r, green: g, blue: b, alpha: a) }
    func withAlpha(_ alpha: CGFloat) -> NSColor { NSColor(calibratedRed: r, green: g, blue: b, alpha: alpha) }
    var luminance: CGFloat { 0.2126 * r + 0.7152 * g + 0.0722 * b }
}

/// Part coordinate spaces (see docs/skin-format.md for the diagram).
enum SkinSpace: String { case head, skull, body, tail, leftEar, rightEar, leftArm, rightArm, hindLeg }
enum SkinBuild: String { case standard, sleek }
enum SkinHeadSurface: String { case dome, plane }
enum SkinAnchorPoint: String { case headTop, face, neck, tailTip }
enum SkinRenderStyle: String { case standard, douni, dazed }
enum SkinTypingStyle: String { case standard, douni }

/// One pen-tool anchor; in/out are absolute handle positions in the same part space.
struct SkinBezierAnchor { var x, y, inX, inY, outX, outY: CGFloat }

struct SkinRegion {
    var space: SkinSpace
    var fill: SkinColor                  // alpha already multiplied in
    var anchors: [SkinBezierAnchor]      // closed path, >= 2 anchors
    var flat: [CGPoint]                  // 16 segments per cubic, in part space
}

struct SkinMark {
    var space: SkinSpace
    var stroke: Bool
    var width: CGFloat
    var color: SkinColor
    var points: [CGPoint]
    var clipToBib: Bool = false
}

struct SkinShape {
    var build: SkinBuild = .standard
    var bodyWidth: CGFloat = 1, headScale: CGFloat = 1, earSize: CGFloat = 1, earBaseWidth: CGFloat = 1, earPointiness: CGFloat = 1
    var tailLength: CGFloat = 1, tailThickness: CGFloat = 1, cheekFullness: CGFloat = 1, neckWidth: CGFloat = 1, pawStagger: CGFloat = 1
}

struct SkinDecoration {
    var image: CGImage
    var anchor: SkinAnchorPoint
    var offsetX: CGFloat = 0, offsetY: CGFloat = 0, scale: CGFloat = 1, rotation: CGFloat = 0 // degrees
}

struct SkinPalette {
    var body = SkinColor.rgba(0, 0, 0)
    var bodyShade: SkinColor?, belly: SkinColor?
    var legs = SkinColor.rgba(0, 0, 0), paws = SkinColor.rgba(0, 0, 0)
    var hindLeg: SkinColor?, hindPaw: SkinColor?
    var pawPads: SkinColor?
    var earOuter = SkinColor.rgba(0, 0, 0)
    var earInner: SkinColor?, nose: SkinColor?, mouth: SkinColor?, iris: SkinColor?
    var tail = SkinColor.rgba(0, 0, 0)
    var tailTip: SkinColor?, stripes: SkinColor?
    var whiskers = SkinColor.rgba(0, 0, 0), crease = SkinColor.rgba(0, 0, 0)
    var outline: SkinColor?, points: SkinColor?, pointsMid: SkinColor?
}

struct SkinError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

struct SkinSpec {
    var id = ""            // "builtin:<n>" or the content hash of an imported file
    var name = ""
    var author = ""
    var builtIn = false
    var palette = SkinPalette()
    var regions: [SkinRegion] = []
    var marks: [SkinMark] = []
    var shape = SkinShape()
    var headSurface: SkinHeadSurface = .dome
    var renderStyle: SkinRenderStyle = .standard
    var typingStyle: SkinTypingStyle = .standard
    /// "idleLegs": "legs" (default) tints the sitting front legs with palette.legs; "chest" keeps them
    /// chest-coloured like the built-in coats.
    var idleLegsTinted = true
    var decorations: [SkinDecoration] = []
    var preview: Data?

    static let maxFileBytes = 2 * 1024 * 1024
    static let formatVersion = 1

    var colorpoint: Bool { palette.points != nil }
    func hasPartArt(_ space: SkinSpace) -> Bool {
        regions.contains { $0.space == space } || marks.contains { $0.space == space }
    }

    // MARK: Built-in coats (exact colours of the pre-SkinSpec CoreGraphics renderer)

    static func builtIn(_ coat: CatCoatTheme) -> SkinSpec { builtIns[coat] ?? builtIns[.classicBlack]! }

    private static let builtIns: [CatCoatTheme: SkinSpec] = {
        let black = SkinColor.rgba(0.085, 0.085, 0.095)
        let milk = SkinColor.hex(0xF2EEE4)
        func tailRings(_ rgb: Int) -> [SkinMark] {
            [50, 78].map { x in SkinMark(space: .tail, stroke: true, width: 3.5, color: .hex(rgb, 0.50),
                                         points: [CGPoint(x: x, y: 8), CGPoint(x: x, y: -8)]) }
        }
        var k = SkinSpec(id: "builtin:0", name: "经典小黑猫", builtIn: true)
        k.palette.body = black; k.palette.legs = black; k.palette.paws = black; k.palette.earOuter = black; k.palette.tail = black
        k.palette.whiskers = .rgba(0.88, 0.90, 0.92, 0.68); k.palette.crease = .rgba(0.82, 0.92, 0.89, 0.76)

        var s = SkinSpec(id: "builtin:1", name: "挖煤暹罗猫", builtIn: true)
        s.shape.build = .sleek
        let point = SkinColor.rgba(0.208, 0.149, 0.122)
        s.palette.body = .rgba(0.965, 0.937, 0.894)
        s.palette.bodyShade = .rgba(0.918, 0.859, 0.784)
        s.palette.points = point; s.palette.paws = point; s.palette.earOuter = point; s.palette.tail = point; s.palette.legs = point
        s.palette.pointsMid = .rgba(0.416, 0.314, 0.255)
        s.palette.earInner = .rgba(0.365, 0.275, 0.228)
        s.palette.outline = .rgba(0.68, 0.59, 0.50, 0.42)
        s.palette.crease = .rgba(0.553, 0.471, 0.404, 0.54)
        s.palette.whiskers = .rgba(0.478, 0.388, 0.325, 0.62)
        s.palette.nose = .rgba(0.14, 0.09, 0.08, 0.95)
        s.palette.mouth = .rgba(0.78, 0.66, 0.56, 0.55)

        var h = SkinSpec(id: "builtin:2", name: "美短（银虎斑加白）", builtIn: true)
        let silver = SkinColor.hex(0xC2C5C1)
        h.palette.body = silver; h.palette.legs = milk; h.palette.earOuter = silver; h.palette.tail = silver
        h.palette.belly = milk; h.palette.paws = milk; h.palette.stripes = .hex(0x55595A)
        h.palette.whiskers = .hex(0x8D8170, 0.68); h.palette.crease = .hex(0x8B8171, 0.60)
        h.headSurface = .plane; h.shape.pawStagger = 0
        h.marks = CoatPatterns.shorthair.map(SkinSpec.skinMark) + tailRings(0x55595A)

        var o = SkinSpec(id: "builtin:3", name: "橘白猫", builtIn: true)
        let ginger = SkinColor.hex(0xD8AA73)
        o.palette.body = milk; o.palette.legs = milk; o.palette.earOuter = ginger; o.palette.tail = ginger
        o.palette.belly = milk; o.palette.paws = milk; o.palette.stripes = .hex(0xA57543)
        o.palette.whiskers = .hex(0x8D8170, 0.68); o.palette.crease = .hex(0x8B8171, 0.60)
        o.headSurface = .dome; o.shape.pawStagger = 0
        o.marks = CoatPatterns.orangeWhite.map(SkinSpec.skinMark) + tailRings(0xA57543)
        k.idleLegsTinted = false; s.idleLegsTinted = false; h.idleLegsTinted = false; o.idleLegsTinted = false
        return [.classicBlack: k, .siamese: s, .shorthair: h, .orangeWhite: o]
    }()

    private static func skinMark(_ m: CoatMark) -> SkinMark {
        SkinMark(space: m.skull ? .skull : (m.head ? .head : .body), stroke: m.width != 0, width: m.width,
                 color: .hex(m.rgb, m.alpha), points: m.points, clipToBib: m.clipToBib)
    }

    // MARK: Jaw line used to split head and body regions (docs/skin-format.md §2.3)

    static func jawSide(head headSide: Bool, cheekFullness c: CGFloat) -> [CGPoint] {
        let edgeY: CGFloat = headSide ? -400 : 400
        var pts = [CGPoint(x: -400, y: edgeY), CGPoint(x: 400, y: edgeY), CGPoint(x: 400, y: 8)]
        func cubicTo(_ p0: CGPoint, _ p1: CGPoint, _ p2: CGPoint, _ p3: CGPoint) {
            for i in 1...16 {
                let t = CGFloat(i) / 16, u = 1 - t
                pts.append(CGPoint(x: u*u*u*p0.x + 3*u*u*t*p1.x + 3*u*t*t*p2.x + t*t*t*p3.x,
                                   y: u*u*u*p0.y + 3*u*u*t*p1.y + 3*u*t*t*p2.y + t*t*t*p3.y))
            }
        }
        pts.append(CGPoint(x: 44 * c, y: 8))
        cubicTo(CGPoint(x: 44 * c, y: 8), CGPoint(x: 44 * c, y: 22), CGPoint(x: 24 * c, y: 34), CGPoint(x: 0, y: 34))
        cubicTo(CGPoint(x: 0, y: 34), CGPoint(x: -24 * c, y: 34), CGPoint(x: -44 * c, y: 22), CGPoint(x: -44 * c, y: 8))
        pts.append(CGPoint(x: -400, y: 8))
        return pts
    }

    // MARK: Parsing

    /// FNV-1a 64 of the file bytes; also the file name inside the skins folder.
    static func contentId(_ data: Data) -> String {
        var h: UInt64 = 1469598103934665603
        for byte in data { h ^= UInt64(byte); h = h &* 1099511628211 }
        return String(format: "%016llx", h)
    }

    static func load(contentsOf url: URL) throws -> SkinSpec {
        let attrs = try? FileManager.default.attributesOfItem(atPath: url.path)
        if let size = attrs?[.size] as? NSNumber, size.intValue > maxFileBytes { throw SkinError(message: "皮肤文件超过 2 MB 上限") }
        guard let data = try? Data(contentsOf: url) else { throw SkinError(message: "无法打开这个文件") }
        return try parse(data)
    }

    static func parse(_ data: Data) throws -> SkinSpec {
        func fail(_ message: String) -> SkinError { SkinError(message: message) }
        if data.count > maxFileBytes { throw fail("皮肤文件超过 2 MB 上限") }
        if data.isEmpty { throw fail("皮肤文件是空的") }
        let rootAny: Any
        do { rootAny = try JSONSerialization.jsonObject(with: data, options: []) }
        catch { throw fail("不是有效的 JSON（请检查逗号、引号和括号）") }
        guard let root = rootAny as? [String: Any] else { throw fail("皮肤文件最外层必须是 JSON 对象 { … }") }

        func isBool(_ v: Any) -> Bool { (v as? NSNumber).map { CFGetTypeID($0) == CFBooleanGetTypeID() } ?? false }
        func numberValue(_ v: Any) -> Double? { isBool(v) ? nil : (v as? NSNumber)?.doubleValue }
        func isNull(_ v: Any?) -> Bool { v == nil || v is NSNull }
        func number(_ v: Any?, _ field: String, _ lo: Double, _ hi: Double, _ def: CGFloat) throws -> CGFloat {
            if isNull(v) { return def }
            guard let n = numberValue(v!), n.isFinite else { throw fail("\(field) 必须是数字") }
            return CGFloat(min(hi, max(lo, n)))
        }
        func color(_ v: Any?, _ field: String) throws -> SkinColor? {
            if isNull(v) { return nil }
            guard let s = v as? String else { throw fail("\(field) 必须是 \"#RRGGBB\" 或 \"#RRGGBBAA\" 颜色字符串") }
            let chars = Array(s.utf8)
            guard (chars.count == 7 || chars.count == 9), chars[0] == UInt8(ascii: "#") else {
                throw fail("\(field) 颜色格式应为 #RRGGBB 或 #RRGGBBAA，现在是 \"\(String(s.prefix(16)))\"")
            }
            var vals: [Int] = [0, 0, 0, 255]
            for i in 1..<chars.count {
                let c = chars[i]
                let d: Int
                switch c {
                case UInt8(ascii: "0")...UInt8(ascii: "9"): d = Int(c) - 48
                case UInt8(ascii: "a")...UInt8(ascii: "f"): d = Int(c) - 87
                case UInt8(ascii: "A")...UInt8(ascii: "F"): d = Int(c) - 55
                default: throw fail("\(field) 颜色里有非十六进制字符：\"\(s)\"")
                }
                let k = (i - 1) / 2
                if (i - 1) % 2 == 0 { vals[k] = 0 }
                vals[k] = vals[k] * 16 + d
            }
            return .rgba(CGFloat(vals[0]) / 255, CGFloat(vals[1]) / 255, CGFloat(vals[2]) / 255, CGFloat(vals[3]) / 255)
        }
        /// Returns nil for unrecognized future space names so newer Workshop skins remain forward-compatible.
        func space(_ v: Any?, _ field: String) throws -> SkinSpace? {
            guard let s = v as? String, !s.isEmpty else {
                throw fail("\(field) 缺失：必须是 head / skull / body / tail / leftEar / rightEar / leftArm / rightArm / hindLeg 之一")
            }
            return SkinSpace(rawValue: s)
        }
        func trimmed(_ s: String, _ maxChars: Int) -> String {
            let t = s.trimmingCharacters(in: .whitespacesAndNewlines).unicodeScalars.filter { $0.value >= 0x20 }
            return String(String.UnicodeScalarView(t.prefix(maxChars)))
        }

        guard let ver = root["formatVersion"] else { throw fail("缺少 formatVersion，这不是 KuroCat 皮肤文件") }
        guard let vn = numberValue(ver), vn == vn.rounded() else { throw fail("formatVersion 必须是整数") }
        if vn > Double(formatVersion) { throw fail("这个皮肤使用了更新的格式（formatVersion \(Int(vn))），请先升级 KuroCat") }
        if vn < 1 { throw fail("formatVersion 无效") }

        var spec = SkinSpec()
        guard let name = root["name"] as? String else { throw fail("缺少皮肤名称 name") }
        spec.name = trimmed(name, 40)
        if spec.name.isEmpty { throw fail("皮肤名称 name 不能为空") }
        if let author = root["author"], !isNull(author) {
            guard let a = author as? String else { throw fail("author 必须是字符串") }
            spec.author = trimmed(a, 40)
        }

        // Palette
        guard let pal = root["palette"] as? [String: Any] else { throw fail("缺少调色板 palette") }
        func pc(_ key: String) throws -> SkinColor? { try color(pal[key], "palette.\(key)") }
        let body = try pc("body"), bodyShade = try pc("bodyShade"), belly = try pc("belly"), legs = try pc("legs")
        let paws = try pc("paws"), pawPads = try pc("pawPads"), earOuter = try pc("earOuter"), earInner = try pc("earInner")
        let hindLeg = try pc("hindLeg"), hindPaw = try pc("hindPaw")
        let nose = try pc("nose"), mouth = try pc("mouth"), iris = try pc("iris"), tail = try pc("tail")
        let tailTip = try pc("tailTip"), stripes = try pc("stripes"), whiskers = try pc("whiskers"), crease = try pc("crease")
        let outline = try pc("outline"), points = try pc("points"), pointsMid = try pc("pointsMid")
        guard let bodyColor = body else { throw fail("调色板缺少主体颜色 palette.body") }
        var p = SkinPalette()
        p.body = bodyColor; p.bodyShade = bodyShade; p.belly = belly
        p.legs = legs ?? bodyColor
        p.paws = paws ?? points ?? p.legs
        p.hindLeg = hindLeg
        p.hindPaw = hindPaw
        p.pawPads = pawPads
        p.earOuter = earOuter ?? points ?? p.legs
        p.earInner = earInner; p.nose = nose; p.mouth = mouth; p.iris = iris
        p.tail = tail ?? p.earOuter
        p.tailTip = tailTip; p.stripes = stripes; p.outline = outline; p.points = points
        if let pt = points { p.pointsMid = pointsMid ?? .rgba((pt.r + bodyColor.r) * 0.5, (pt.g + bodyColor.g) * 0.5, (pt.b + bodyColor.b) * 0.5) }
        let darkBody = bodyColor.luminance < 0.45
        p.whiskers = whiskers ?? (darkBody ? .rgba(0.88, 0.90, 0.92, 0.68) : .hex(0x8D8170, 0.68))
        p.crease = crease ?? (darkBody ? .rgba(0.82, 0.92, 0.89, 0.76) : .hex(0x8B8171, 0.60))
        spec.palette = p

        // Shape
        if let shAny = root["shape"], !isNull(shAny) {
            guard let sh = shAny as? [String: Any] else { throw fail("shape 必须是对象") }
            if let b = sh["build"], !isNull(b) {
                guard let bs = b as? String, let build = SkinBuild(rawValue: bs) else { throw fail("shape.build 必须是 \"standard\" 或 \"sleek\"") }
                spec.shape.build = build
            }
            spec.shape.bodyWidth = try number(sh["bodyWidth"], "shape.bodyWidth", 0.85, 1.35, 1)
            spec.shape.headScale = try number(sh["headScale"], "shape.headScale", 0.90, 1.15, 1)
            spec.shape.earSize = try number(sh["earSize"], "shape.earSize", 0.80, 1.25, 1)
            spec.shape.earBaseWidth = try number(sh["earBaseWidth"], "shape.earBaseWidth", 0.65, 1.40, 1)
            spec.shape.earPointiness = try number(sh["earPointiness"], "shape.earPointiness", 0.50, 1.50, 1)
            spec.shape.tailLength = try number(sh["tailLength"], "shape.tailLength", 0.70, 1.30, 1)
            spec.shape.tailThickness = try number(sh["tailThickness"], "shape.tailThickness", 0.70, 1.50, 1)
            spec.shape.cheekFullness = try number(sh["cheekFullness"], "shape.cheekFullness", 0.85, 1.25, 1)
            spec.shape.neckWidth = try number(sh["neckWidth"], "shape.neckWidth", 0.65, 1.40, 1)
            spec.shape.pawStagger = try number(sh["pawStagger"], "shape.pawStagger", 0, 1, 1)
        }
        if let hs = root["headSurface"], !isNull(hs) {
            guard let hss = hs as? String, let surface = SkinHeadSurface(rawValue: hss) else { throw fail("headSurface 必须是 \"dome\" 或 \"plane\"") }
            spec.headSurface = surface
        }

        if let il = root["idleLegs"], !isNull(il) {
            guard let ils = il as? String, ils == "legs" || ils == "chest" else { throw fail("idleLegs 必须是 \"legs\" 或 \"chest\"") }
            spec.idleLegsTinted = ils == "legs"
        }
        if let rs = root["renderStyle"] as? String, let style = SkinRenderStyle(rawValue: rs) {
            spec.renderStyle = style
        }
        if let ts = root["typingStyle"] as? String, let style = SkinTypingStyle(rawValue: ts) {
            spec.typingStyle = style
        }

        // Regions (pen-tool curve areas)
        if let regsAny = root["regions"], !isNull(regsAny) {
            guard let regs = regsAny as? [Any] else { throw fail("regions 必须是数组") }
            if regs.count > 64 { throw fail("regions 最多 64 个分区") }
            for (i, rAny) in regs.enumerated() {
                let f = "regions[\(i)]"
                guard let r = rAny as? [String: Any] else { throw fail("\(f) 必须是对象") }
                guard let sp = try space(r["space"], "\(f).space") else { continue }
                guard let parsedFill = try color(r["fill"], "\(f).fill") else { throw fail("\(f).fill 缺失") }
                var fill = parsedFill
                fill.a *= try number(r["alpha"], "\(f).alpha", 0, 1, 1)
                guard let anchorsAny = r["anchors"] as? [Any] else { throw fail("\(f).anchors 必须是锚点数组") }
                if anchorsAny.count < 2 || anchorsAny.count > 128 { throw fail("\(f).anchors 需要 2–128 个锚点") }
                var anchors: [SkinBezierAnchor] = []
                for (k, aAny) in anchorsAny.enumerated() {
                    let af = "\(f).anchors[\(k)]"
                    guard let a = aAny as? [String: Any] else { throw fail("\(af) 必须是 {x, y, inX, inY, outX, outY} 对象") }
                    if isNull(a["x"]) || isNull(a["y"]) { throw fail("\(af) 缺少 x / y") }
                    let x = try number(a["x"], "\(af).x", -400, 400, 0)
                    let y = try number(a["y"], "\(af).y", -400, 400, 0)
                    let inX = try number(a["inX"], "\(af).inX", -400, 400, x)
                    let inY = try number(a["inY"], "\(af).inY", -400, 400, y)
                    let outX = try number(a["outX"], "\(af).outX", -400, 400, x)
                    let outY = try number(a["outY"], "\(af).outY", -400, 400, y)
                    anchors.append(SkinBezierAnchor(x: x, y: y, inX: inX, inY: inY, outX: outX, outY: outY))
                }
                var flat: [CGPoint] = []
                for k in 0..<anchors.count {
                    let a = anchors[k], b = anchors[(k + 1) % anchors.count]
                    for step in 0..<16 {
                        let t = CGFloat(step) / 16, u = 1 - t
                        flat.append(CGPoint(x: u*u*u*a.x + 3*u*u*t*a.outX + 3*u*t*t*b.inX + t*t*t*b.x,
                                            y: u*u*u*a.y + 3*u*u*t*a.outY + 3*u*t*t*b.inY + t*t*t*b.y))
                    }
                }
                spec.regions.append(SkinRegion(space: sp, fill: fill, anchors: anchors, flat: flat))
            }
        }

        // Marks (polygons / strokes, same model as the built-in CoatMark artwork)
        if let marksAny = root["marks"], !isNull(marksAny) {
            guard let marks = marksAny as? [Any] else { throw fail("marks 必须是数组") }
            if marks.count > 256 { throw fail("marks 最多 256 条") }
            for (i, mAny) in marks.enumerated() {
                let f = "marks[\(i)]"
                guard let m = mAny as? [String: Any] else { throw fail("\(f) 必须是对象") }
                guard let sp = try space(m["space"], "\(f).space") else { continue }
                guard let kind = m["kind"] as? String, kind == "polygon" || kind == "stroke" else { throw fail("\(f).kind 必须是 \"polygon\" 或 \"stroke\"") }
                let stroke = kind == "stroke"
                let parsedColor = try color(m["color"], "\(f).color")
                guard var c = parsedColor ?? p.stripes else { throw fail("\(f).color 缺失，且调色板没有 stripes 可作默认色") }
                c.a *= try number(m["alpha"], "\(f).alpha", 0, 1, 1)
                var width: CGFloat = 0
                if stroke { width = try number(m["width"], "\(f).width", 0.2, 24, 2) }
                guard let ptsAny = m["points"] as? [Any] else { throw fail("\(f).points 必须是 [[x, y], …] 数组") }
                let minPts = stroke ? 2 : 3
                if ptsAny.count < minPts || ptsAny.count > 512 { throw fail("\(f).points 需要 \(minPts)–512 个点") }
                var pts: [CGPoint] = []
                for (k, ptAny) in ptsAny.enumerated() {
                    guard let pair = ptAny as? [Any], pair.count == 2, let x = numberValue(pair[0]), let y = numberValue(pair[1]), x.isFinite, y.isFinite else {
                        throw fail("\(f).points[\(k)] 必须是 [x, y]")
                    }
                    pts.append(CGPoint(x: min(400, max(-400, x)), y: min(400, max(-400, y))))
                }
                let clipToBib = (m["clipToBib"] as? Bool) == true
                spec.marks.append(SkinMark(space: sp, stroke: stroke, width: width, color: c, points: pts, clipToBib: clipToBib))
            }
        }

        // Decorations (anchored PNG stickers)
        if let decosAny = root["decorations"], !isNull(decosAny) {
            guard let decos = decosAny as? [Any] else { throw fail("decorations 必须是数组") }
            if decos.count > 8 { throw fail("decorations 最多 8 个贴纸") }
            for (i, dAny) in decos.enumerated() {
                let f = "decorations[\(i)]"
                guard let d = dAny as? [String: Any] else { throw fail("\(f) 必须是对象") }
                guard let b64 = d["png"] as? String, let png = decodeBase64PNG(b64) else { throw fail("\(f).png 必须是 base64 编码的 PNG") }
                if png.count > 1024 * 1024 { throw fail("\(f).png 超过 1 MB") }
                guard let size = pngSize(png), size.0 <= 1024, size.1 <= 1024,
                      let provider = CGDataProvider(data: png as CFData),
                      let image = CGImage(pngDataProviderSource: provider, decode: nil, shouldInterpolate: true, intent: .defaultIntent) else {
                    throw fail("\(f).png 不是有效的 PNG（或尺寸超过 1024×1024）")
                }
                guard let anchorName = d["anchor"] as? String, !anchorName.isEmpty else {
                    throw fail("\(f).anchor 必须是 headTop / face / neck / tailTip 之一")
                }
                guard let anchor = SkinAnchorPoint(rawValue: anchorName) else { continue }
                let offsetX = try number(d["offsetX"], "\(f).offsetX", -120, 120, 0)
                let offsetY = try number(d["offsetY"], "\(f).offsetY", -120, 120, 0)
                let scale = try number(d["scale"], "\(f).scale", 0.05, 4, 1)
                let rotation = try number(d["rotation"], "\(f).rotation", -180, 180, 0)
                spec.decorations.append(SkinDecoration(image: image, anchor: anchor, offsetX: offsetX, offsetY: offsetY,
                                                       scale: scale, rotation: rotation))
            }
        }

        if let prev = root["preview"], !isNull(prev) {
            guard let s = prev as? String, let png = decodeBase64PNG(s), pngSize(png) != nil, png.count <= 512 * 1024 else {
                throw fail("preview 必须是不超过 512 KB 的 base64 PNG")
            }
            spec.preview = png
        }

        spec.id = contentId(data)
        return spec
    }

    private static func decodeBase64PNG(_ s: String) -> Data? {
        let prefix = "data:image/png;base64,"
        let body = s.hasPrefix(prefix) ? String(s.dropFirst(prefix.count)) : s
        return Data(base64Encoded: body, options: .ignoreUnknownCharacters)
    }

    private static func pngSize(_ png: Data) -> (Int, Int)? {
        let bytes = [UInt8](png.prefix(24))
        let sig: [UInt8] = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]
        guard bytes.count >= 24, Array(bytes[0..<8]) == sig, Array(bytes[12..<16]) == Array("IHDR".utf8) else { return nil }
        func be32(_ o: Int) -> Int { Int(bytes[o]) << 24 | Int(bytes[o + 1]) << 16 | Int(bytes[o + 2]) << 8 | Int(bytes[o + 3]) }
        let w = be32(16), h = be32(20)
        return (w > 0 && h > 0 && w <= 4096 && h <= 4096) ? (w, h) : nil
    }
}

// MARK: - Imported skins (~/Library/Application Support/KuroCat/skins/<content-hash>.kurocat)

final class SkinLibrary {
    static let shared = SkinLibrary()
    private(set) var skins: [SkinSpec] = []   // sorted by name

    private init() { reload() }

    static var directory: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support")
        return base.appendingPathComponent("KuroCat/skins", isDirectory: true)
    }

    func reload() {
        let fm = FileManager.default
        let files = (try? fm.contentsOfDirectory(at: Self.directory, includingPropertiesForKeys: nil)) ?? []
        skins = files.filter { $0.pathExtension == "kurocat" }
            .compactMap { try? SkinSpec.load(contentsOf: $0) }
            .sorted { $0.name < $1.name }
    }

    func skin(id: String) -> SkinSpec? {
        id.isEmpty ? nil : skins.first { $0.id == id }
    }

    /// Validates `url`, copies it into the skins folder and returns the new skin's id.
    func importFile(_ url: URL) throws -> String {
        let attrs = try? FileManager.default.attributesOfItem(atPath: url.path)
        if let size = attrs?[.size] as? NSNumber, size.intValue > SkinSpec.maxFileBytes { throw SkinError(message: "皮肤文件超过 2 MB 上限") }
        guard let data = try? Data(contentsOf: url) else { throw SkinError(message: "无法打开这个文件") }
        let spec = try SkinSpec.parse(data)
        do {
            try FileManager.default.createDirectory(at: Self.directory, withIntermediateDirectories: true)
            try data.write(to: Self.directory.appendingPathComponent("\(spec.id).kurocat"), options: .atomic)
        } catch {
            throw SkinError(message: "保存皮肤失败：无法写入 \(Self.directory.path)")
        }
        reload()
        return spec.id
    }

    @discardableResult
    func remove(id: String) -> Bool {
        guard id.count == 16, id.allSatisfy({ "0123456789abcdef".contains($0) }) else { return false }
        let ok = (try? FileManager.default.removeItem(at: Self.directory.appendingPathComponent("\(id).kurocat"))) != nil
        reload()
        return ok
    }
}

// MARK: - Custom Keyboard & Mouse Skins (.kurokb / keyboard.json)

struct KeyboardSkinSpec: Equatable {
    var id = ""
    var name = ""
    var author = ""
    var builtIn = false
    var mouseBody = SkinColor.rgba(0.955, 0.950, 0.925)
    var mouseBorder = SkinColor.rgba(0.14, 0.14, 0.16)
    var wheel = SkinColor.rgba(0.96, 0.69, 0.16)
    var base = SkinColor.rgba(0.10, 0.10, 0.12)
    var deck = SkinColor.rgba(0.14, 0.14, 0.16)
    var key = SkinColor.rgba(0.968, 0.964, 0.942)
    var keyBorder = SkinColor.rgba(0.78, 0.77, 0.74, 0.75)
    var accent = SkinColor.rgba(0.97, 0.70, 0.16)
    var darkText = true

    static let maxFileBytes = 256 * 1024
    static let formatVersion = 1

    static func builtIn(_ theme: KeyboardTheme) -> KeyboardSkinSpec {
        switch theme {
        case .classicMilk:
            return KeyboardSkinSpec(
                id: "builtin:0", name: theme.rawValue, author: "KuroCat", builtIn: true,
                mouseBody: .rgba(0.955, 0.950, 0.925),
                mouseBorder: .rgba(0.14, 0.14, 0.16),
                wheel: .rgba(0.96, 0.69, 0.16),
                base: .rgba(0.10, 0.10, 0.12),
                deck: .rgba(0.14, 0.14, 0.16),
                key: .rgba(0.968, 0.964, 0.942),
                keyBorder: .rgba(0.78, 0.77, 0.74, 0.75),
                accent: .rgba(0.97, 0.70, 0.16),
                darkText: true
            )
        case .midnightHacker:
            return KeyboardSkinSpec(
                id: "builtin:1", name: theme.rawValue, author: "KuroCat", builtIn: true,
                mouseBody: .rgba(0.20, 0.21, 0.24),
                mouseBorder: .rgba(0.08, 0.08, 0.10),
                wheel: .rgba(0.77, 0.94, 0.25),
                base: .rgba(0.06, 0.06, 0.08),
                deck: .rgba(0.10, 0.11, 0.13),
                key: .rgba(0.21, 0.22, 0.25),
                keyBorder: .rgba(0.11, 0.11, 0.13, 0.95),
                accent: .rgba(0.77, 0.94, 0.25),
                darkText: false
            )
        case .retroCream:
            return KeyboardSkinSpec(
                id: "builtin:2", name: theme.rawValue, author: "KuroCat", builtIn: true,
                mouseBody: .rgba(0.90, 0.88, 0.82),
                mouseBorder: .rgba(0.28, 0.26, 0.24),
                wheel: .rgba(0.88, 0.42, 0.24),
                base: .rgba(0.25, 0.24, 0.22),
                deck: .rgba(0.38, 0.36, 0.33),
                key: .rgba(0.90, 0.88, 0.82),
                keyBorder: .rgba(0.68, 0.65, 0.60, 0.85),
                accent: .rgba(0.88, 0.42, 0.24),
                darkText: true
            )
        }
    }

    static func load(contentsOf url: URL) throws -> KeyboardSkinSpec {
        let attrs = try? FileManager.default.attributesOfItem(atPath: url.path)
        if let size = attrs?[.size] as? NSNumber, size.intValue > maxFileBytes {
            throw SkinError(message: "键盘皮肤文件超过 256 KB 上限")
        }
        guard let data = try? Data(contentsOf: url) else { throw SkinError(message: "无法打开这个键盘皮肤文件") }
        return try parse(data)
    }

    static func parse(_ data: Data) throws -> KeyboardSkinSpec {
        func fail(_ message: String) -> SkinError { SkinError(message: message) }
        if data.count > maxFileBytes { throw fail("键盘皮肤文件超过 256 KB 上限") }
        if data.isEmpty { throw fail("键盘皮肤文件是空的") }
        let rootAny: Any
        do { rootAny = try JSONSerialization.jsonObject(with: data, options: []) }
        catch { throw fail("不是有效的 JSON（请检查逗号、引号和括号）") }
        guard let root = rootAny as? [String: Any] else { throw fail("键盘皮肤最外层必须是 JSON 对象 { … }") }

        func isNull(_ v: Any?) -> Bool { v == nil || v is NSNull }
        func color(_ v: Any?, _ field: String) throws -> SkinColor? {
            if isNull(v) { return nil }
            guard let s = v as? String else { throw fail("\(field) 必须是 \"#RRGGBB\" 或 \"#RRGGBBAA\" 颜色字符串") }
            let chars = Array(s.utf8)
            guard (chars.count == 7 || chars.count == 9), chars[0] == UInt8(ascii: "#") else {
                throw fail("\(field) 颜色格式应为 #RRGGBB 或 #RRGGBBAA")
            }
            var vals = [0, 0, 0, 255]
            for i in 1..<chars.count {
                let c = chars[i]
                let d: Int
                switch c {
                case UInt8(ascii: "0")...UInt8(ascii: "9"): d = Int(c) - 48
                case UInt8(ascii: "a")...UInt8(ascii: "f"): d = Int(c) - 87
                case UInt8(ascii: "A")...UInt8(ascii: "F"): d = Int(c) - 55
                default: throw fail("\(field) 颜色里有非十六进制字符")
                }
                let k = (i - 1) / 2
                if (i - 1) % 2 == 0 { vals[k] = 0 }
                vals[k] = vals[k] * 16 + d
            }
            return .rgba(CGFloat(vals[0]) / 255, CGFloat(vals[1]) / 255, CGFloat(vals[2]) / 255, CGFloat(vals[3]) / 255)
        }
        func trimmed(_ s: String, _ maxChars: Int) -> String {
            let t = s.trimmingCharacters(in: .whitespacesAndNewlines).unicodeScalars.filter { $0.value >= 0x20 }
            return String(String.UnicodeScalarView(t.prefix(maxChars)))
        }

        if let ver = root["formatVersion"], !isNull(ver) {
            guard let vn = (ver as? NSNumber)?.doubleValue, vn == vn.rounded() else { throw fail("formatVersion 必须是整数") }
            if vn > Double(formatVersion) { throw fail("这个键盘皮肤使用了更新的格式，请先升级 KuroCat") }
            if vn < 1 { throw fail("formatVersion 无效") }
        }
        guard let nameRaw = root["name"] as? String else { throw fail("缺少键盘皮肤名称 name") }
        let name = trimmed(nameRaw, 40)
        if name.isEmpty { throw fail("键盘皮肤名称 name 不能为空") }
        var author = ""
        if let aRaw = root["author"] as? String { author = trimmed(aRaw, 40) }

        guard let cols = root["colors"] as? [String: Any] else { throw fail("缺少键盘配色对象 colors") }
        guard let key = try color(cols["key"], "colors.key") else { throw fail("缺少键帽颜色 colors.key") }
        let deck = try color(cols["deck"], "colors.deck") ?? .rgba(0.14, 0.14, 0.16)
        let base = try color(cols["base"], "colors.base") ?? .rgba(deck.r * 0.72, deck.g * 0.72, deck.b * 0.72)
        let keyBorder = try color(cols["keyBorder"], "colors.keyBorder") ?? .rgba(deck.r, deck.g, deck.b, 0.78)
        let accent = try color(cols["accent"], "colors.accent") ?? .rgba(0.97, 0.70, 0.16)
        let mouseBody = try color(cols["mouseBody"], "colors.mouseBody") ?? key
        let mouseBorder = try color(cols["mouseBorder"], "colors.mouseBorder") ?? base
        let wheel = try color(cols["wheel"], "colors.wheel") ?? accent
        let darkText = (cols["darkText"] as? Bool) ?? (key.luminance >= 0.45)

        return KeyboardSkinSpec(
            id: SkinSpec.contentId(data), name: name, author: author, builtIn: false,
            mouseBody: mouseBody, mouseBorder: mouseBorder, wheel: wheel,
            base: base, deck: deck, key: key, keyBorder: keyBorder, accent: accent,
            darkText: darkText
        )
    }

    /// Quick sniffer to distinguish a keyboard JSON from a cat `.kurocat` JSON when dropping `.json` files.
    static func looksLikeKeyboardJSON(_ url: URL) -> Bool {
        let ext = url.pathExtension.lowercased()
        if ext == "kurokb" { return true }
        guard ext == "json",
              let data = try? Data(contentsOf: url),
              data.count <= maxFileBytes,
              let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              obj["colors"] is [String: Any] else { return false }
        return true
    }
}

final class KeyboardSkinLibrary {
    static let shared = KeyboardSkinLibrary()
    private(set) var skins: [KeyboardSkinSpec] = []

    private init() { reload() }

    static var directory: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support")
        return base.appendingPathComponent("KuroCat/keyboards", isDirectory: true)
    }

    func reload() {
        let fm = FileManager.default
        let files = (try? fm.contentsOfDirectory(at: Self.directory, includingPropertiesForKeys: nil)) ?? []
        skins = files.filter { ["kurokb", "json"].contains($0.pathExtension.lowercased()) }
            .compactMap { try? KeyboardSkinSpec.load(contentsOf: $0) }
            .sorted { $0.name < $1.name }
    }

    func skin(id: String) -> KeyboardSkinSpec? {
        id.isEmpty ? nil : skins.first { $0.id == id }
    }

    func importFile(_ url: URL) throws -> String {
        let attrs = try? FileManager.default.attributesOfItem(atPath: url.path)
        if let size = attrs?[.size] as? NSNumber, size.intValue > KeyboardSkinSpec.maxFileBytes {
            throw SkinError(message: "键盘皮肤文件超过 256 KB 上限")
        }
        guard let data = try? Data(contentsOf: url) else { throw SkinError(message: "无法打开这个文件") }
        let spec = try KeyboardSkinSpec.parse(data)
        do {
            try FileManager.default.createDirectory(at: Self.directory, withIntermediateDirectories: true)
            try data.write(to: Self.directory.appendingPathComponent("\(spec.id).kurokb"), options: .atomic)
        } catch {
            throw SkinError(message: "保存键盘皮肤失败：无法写入 \(Self.directory.path)")
        }
        reload()
        return spec.id
    }

    @discardableResult
    func remove(id: String) -> Bool {
        guard id.count == 16, id.allSatisfy({ "0123456789abcdef".contains($0) }) else { return false }
        let ok = (try? FileManager.default.removeItem(at: Self.directory.appendingPathComponent("\(id).kurokb"))) != nil
        reload()
        return ok
    }
}
