import AppKit

struct PetAnimation: Decodable {
    let frames: [String]
    let frameDelay: Double
    let baseFrame: String?
    let overlayRect: [Double]?
}
struct PetPeek: Decodable {
    let frame: String
    let crop: [Double]
    let grip: Double
    let headWidth: Double
    let retraction: Double?
    let gripRects: [[Double]]?
    let rotation: Double?
    let pivot: [Double]?
    var normalizedCrop: NSRect? {
        guard crop.count == 4, crop.allSatisfy({ $0.isFinite && $0 >= 0 }), crop[2] > 0, crop[3] > 0,
              crop[0]+crop[2] <= 1, crop[1]+crop[3] <= 1, grip > 0, grip < 1,
              headWidth.isFinite, headWidth > 0,
              (retraction ?? 0).isFinite, (retraction ?? 0) >= 0, (retraction ?? 0) <= 0.5 else { return nil }
        return NSRect(x: crop[0], y: crop[1], width: crop[2], height: crop[3])
    }
    var hands: [NSRect] { (gripRects ?? []).compactMap { value in
        guard value.count == 4, value.allSatisfy({$0.isFinite && $0 >= 0}), value[2] > 0, value[3] > 0, value[0]+value[2] <= 1, value[1]+value[3] <= 1 else { return nil }
        return NSRect(x:value[0],y:value[1],width:value[2],height:value[3])
    } }
    func size(for side: CGFloat, referenceHeadWidth: CGFloat = 0.52) -> NSSize {
        let crop = normalizedCrop!
        let scale = side*referenceHeadWidth/headWidth
        return NSSize(width: crop.width*scale, height: crop.height*scale)
    }
}
struct PetRegistration: Decodable {
    let headWidth: Double
    let frames: [String: [Double]]
    let anchor: [Double]?
    func rect(for frame: String, in bounds: NSRect) -> NSRect? {
        guard let value = frames[frame], value.count == 4, value.allSatisfy(\.isFinite), value[2] > 0, value[3] > 0 else { return nil }
        return NSRect(x:bounds.minX+value[0]*bounds.width, y:bounds.maxY-(value[1]+value[3])*bounds.height, width:value[2]*bounds.width, height:value[3]*bounds.height)
    }
}
struct PetManifest: Decodable { let name: String; let animations: [String: PetAnimation]; let peek: [String: PetPeek]?; let registration: PetRegistration? }
final class PetPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
    // The peek is deliberately partly outside the display. Normal placement is
    // clamped by PetView when a drag ends or the display arrangement changes.
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect { frameRect }
    override func accessibilityPerformRaise() -> Bool {
        orderFrontRegardless()
        return true
    }
}
final class PetView: NSView {
    var onOpen: (() -> Void)?
    var onMenu: ((NSEvent) -> Void)?
    var onMoved: (() -> Void)?
    var onScale: ((Double) -> Void)?
    private(set) var state = "idle"
    private let cat = KuroCatIntegration()
    private var timer: Timer?
    private var lastTick = CACurrentMediaTime()
    private var redrawTick = 0
    private var resetAt: TimeInterval = 0
    private var pressed = false
    private var dragged = false
    private var permissionPressed = false
    private var mouseStart = NSPoint.zero
    private var lastDragPoint = NSPoint.zero
    private var windowStart = NSPoint.zero
    private var docking = PetEdgeDocking()
    private var dockedFrame: NSRect?
    private var peekImage: NSImage?
    var paused = false { didSet { cat.paused = motionPaused; needsDisplay = true } }
    var edgeHiding = false { didSet { if !edgeHiding { expandForPlacement() } else { dockNearEdge() } } }
    var placementFrame: NSRect { dockedFrame ?? window?.frame ?? .zero }
    var keyboardAllowed: Bool { !cat.needsPermission }
    private var motionPaused: Bool { paused || NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }

    init() {
        super.init(frame: .zero)
        setAccessibilityElement(true); setAccessibilityRole(.button)
        setAccessibilityLabel("哆啦小黑猫，双击打开或收起对话，拖动移动，滑过猫头或身体可抚摸")
        toolTip = "双击打开或收起对话；拖动移动；滑过猫头可抚摸；⌥+滚动调整大小"
        cat.start()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 60, repeats: true) { [weak self] _ in self?.tick() }
        RunLoop.main.add(timer!, forMode: .common)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
    override var isOpaque: Bool { false }
    override var acceptsFirstResponder: Bool { false }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    func stop() { timer?.invalidate(); cat.stop() }
    func requestKeyboard() { cat.requestPermission() }

    override func draw(_ dirtyRect: NSRect) {
        NSColor.clear.setFill(); dirtyRect.fill(using: .copy)
        if docking.collapsed, let image = peekImage {
            NSGraphicsContext.saveGraphicsState()
            if docking.edge == .top {
                let transform = NSAffineTransform(); transform.translateX(by: bounds.midX, yBy: bounds.midY)
                transform.rotate(byDegrees: 180); transform.translateX(by: -bounds.midX, yBy: -bounds.midY); transform.concat()
            }
            image.draw(in: bounds, from: .zero, operation: .sourceOver, fraction: 1)
            NSGraphicsContext.restoreGraphicsState()
        } else if let context = NSGraphicsContext.current?.cgContext {
            cat.draw(in: context, bounds: bounds, permission: cat.needsPermission)
            if state != "idle" {
                let color: NSColor = state == "error" ? .systemRed : state == "success" ? .systemGreen : state == "listening" ? .systemOrange : .systemBlue
                color.setFill()
                NSBezierPath(ovalIn: NSRect(x: bounds.midX - 3, y: bounds.minY + 5, width: 6, height: 6)).fill()
            }
        }
    }
    private func tick() {
        let now = CACurrentMediaTime(), dt = CGFloat(min(0.04, now - lastTick)); lastTick = now
        guard let window, window.isVisible else { return }
        cat.paused = motionPaused
        if resetAt > 0 && now >= resetAt { state = "idle"; resetAt = 0; needsDisplay = true }
        if !docking.collapsed { cat.step(dt: dt, frame: placementFrame) }
        if edgeHiding && !pressed && !dragged, let full = dockedFrame {
            let previous = docking.collapsed
            docking.tick(inside: full.insetBy(dx: -12, dy: -12).contains(NSEvent.mouseLocation), nearPeek: window.frame.insetBy(dx: -8, dy: -8).contains(NSEvent.mouseLocation), at: now)
            if previous != docking.collapsed { applyDockPresentation() }
        }
        if !dragged && !pressed {
            let point = convert(window.convertPoint(fromScreen: NSEvent.mouseLocation), from: nil)
            let zone = cat.hitZone(point, in: bounds)
            if !docking.collapsed { cat.hover(bounds.contains(point) ? point : nil, in: bounds) }
            let through = CatSettings.shared.fullClickThrough && !NSEvent.modifierFlags.contains(.option)
            window.ignoresMouseEvents = docking.collapsed ? !bounds.contains(point) : (through ? zone != .permissionPill : zone == .none)
        }
        guard !motionPaused, !docking.collapsed else { return }
        let input = InputEngine.shared
        let active = dragged || !input.activeKeys.isEmpty || input.leftMouseDown || input.rightMouseDown
            || now - max(input.lastKeyActivityTime, input.lastMouseMoveTime) < 0.8
            || cat.physics.petHeadIntensity > 0.02 || cat.physics.huntIntensity.value > 0.02
        redrawTick += 1
        if redrawTick >= (active ? 1 : cat.physics.sleepiness > 0.95 ? 6 : 2) { redrawTick = 0; needsDisplay = true }
    }
    func setState(_ value: String) {
        guard ["idle", "walking", "listening", "thinking", "working", "speaking", "success", "error", "sleep"].contains(value) else { return }
        state = value
        resetAt = ["success", "error"].contains(value) ? CACurrentMediaTime() + 2.4 : 0
        needsDisplay = true
    }
    override func mouseDown(with event: NSEvent) {
        pressed = true
        if docking.collapsed { docking.reveal(at: CACurrentMediaTime()); applyDockPresentation() }
        let point = convert(event.locationInWindow, from: nil)
        permissionPressed = cat.hitZone(point, in: bounds) == .permissionPill
        mouseStart = NSEvent.mouseLocation; lastDragPoint = mouseStart
        windowStart = window?.frame.origin ?? .zero; dragged = false
        window?.ignoresMouseEvents = false
    }
    override func mouseDragged(with event: NSEvent) {
        guard !permissionPressed else { return }
        let cursor = NSEvent.mouseLocation
        if hypot(cursor.x - mouseStart.x, cursor.y - mouseStart.y) < 4 && !dragged { return }
        if !dragged { docking.undock(); dockedFrame = nil }
        dragged = true; window?.ignoresMouseEvents = false
        if !motionPaused { cat.physics.setDragging(true, dragDx: cursor.x - lastDragPoint.x, dragDy: lastDragPoint.y - cursor.y) }
        lastDragPoint = cursor
        window?.setFrameOrigin(NSPoint(x: windowStart.x + cursor.x - mouseStart.x, y: windowStart.y + cursor.y - mouseStart.y))
    }
    override func mouseUp(with event: NSEvent) {
        pressed = false
        if permissionPressed { permissionPressed = false; requestKeyboard(); return }
        if dragged {
            dragged = false; cat.physics.setDragging(false)
            clampToScreen(); dockNearEdge(); onMoved?()
        } else if event.clickCount == 2 { onOpen?() }
    }
    override func rightMouseDown(with event: NSEvent) { onMenu?(event) }
    override func scrollWheel(with event: NSEvent) {
        guard event.modifierFlags.contains(.option) else { super.scrollWheel(with: event); return }
        onScale?(exp(event.scrollingDeltaY * (event.hasPreciseScrollingDeltas ? 0.006 : 0.055)))
    }
    override func accessibilityPerformPress() -> Bool {
        if docking.collapsed { docking.reveal(at: CACurrentMediaTime()); applyDockPresentation() }
        else { onOpen?() }
        return true
    }
    func clampToScreen() {
        expandForPlacement()
        guard let window, let area = PetSizing.screenArea(for: window.frame, areas: NSScreen.screens.map(\.visibleFrame)) else { return }
        window.setFrameOrigin(NSPoint(x: max(area.minX, min(area.maxX - window.frame.width, window.frame.minX)), y: max(area.minY, min(area.maxY - window.frame.height, window.frame.minY))))
    }
    func expandForPlacement() {
        if let frame = dockedFrame { window?.setFrame(frame, display: true) }
        docking.undock(); dockedFrame = nil; needsDisplay = true
    }
    func dockNearEdge() {
        guard edgeHiding, let window,
            let screen = NSScreen.screens.first(where: { $0.visibleFrame.contains(NSPoint(x: window.frame.midX, y: window.frame.midY)) }),
            let edge = PetEdgeDocking.candidate(frame: window.frame, area: screen.visibleFrame, display: screen.frame, screens: NSScreen.screens.map(\.frame)) else { return }
        let frame = PetEdgeDocking.snap(window.frame, edge: edge, area: screen.visibleFrame)
        window.setFrame(frame, display: true); dockedFrame = frame; docking.dock(edge, at: CACurrentMediaTime())
    }
    func resize(to scale: Double) {
        let previous = placementFrame, edge = docking.edge
        guard let area = PetSizing.screenArea(for: previous, areas: NSScreen.screens.map(\.visibleFrame)) else { return }
        expandForPlacement()
        var frame = PetSizing.frame(resizing: previous, scale: scale, within: area)
        if let edge { frame = PetEdgeDocking.snap(frame, edge: edge, area: area) }
        window?.setFrame(frame, display: true); dockNearEdge()
    }
    private func applyDockPresentation() {
        guard let window, let full = dockedFrame, let edge = docking.edge,
            let area = PetSizing.screenArea(for: full, areas: NSScreen.screens.map(\.visibleFrame)) else { return }
        if docking.collapsed, let image = cat.image(), let head = image.cropping(to: CGRect(x: 230, y: 100, width: 285, height: 310)) {
            peekImage = NSImage(cgImage: head, size: NSSize(width: 142.5, height: 155))
        }
        window.setFrame(docking.collapsed ? PetEdgeDocking.peekFrame(full, edge: edge, area: area) : full, display: true)
        needsDisplay = true
    }
    deinit { stop() }
}
