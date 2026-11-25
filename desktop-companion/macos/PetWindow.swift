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
struct PetManifest: Decodable { let name: String; let animations: [String: PetAnimation]; let peek: [String: PetPeek]?; let registration: PetRegistration?; let renderer: String? }
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
    private(set) var state = "idle" { didSet { index = 0; lastFrameAt = 0; needsDisplay = true } }
    private var activity = "idle"
    private var dragMotion = PetDragMotion()
    var paused = false
    private let manifest: PetManifest
    private let images: [String: NSImage]
    private let bitmaps: [String: NSBitmapImageRep]
    private var timer: Timer?
    private var index = 0
    private var lastFrameAt: TimeInterval = 0
    private var mouseStart = NSPoint.zero
    private var windowStart = NSPoint.zero
    private var dragged = false
    private var pressed = false
    private var docking = PetEdgeDocking()
    private var facing = PetFacing()
    private var dockedFrame: NSRect?
    var edgeHiding = true { didSet { if !edgeHiding { expandForPlacement() } else { dockNearEdge() } } }
    var placementFrame: NSRect { dockedFrame ?? window?.frame ?? .zero }
    private var resetAt: TimeInterval = 0
    private var bongoCat: BongoCatRenderer?
    var isBongoCat: Bool { bongoCat != nil }
    var keyboardAllowed: Bool { bongoCat?.keyboardAllowed ?? false }
    func requestKeyboard() { bongoCat?.requestKeyboard() }
    func catAction(_ action: String) { bongoCat?.perform(action) }
    func stop() { timer?.invalidate(); bongoCat?.stop() }
    init(root: URL) throws {
        manifest = try JSONDecoder().decode(PetManifest.self, from: Data(contentsOf: root.appendingPathComponent("pet.json")))
        var loaded: [String: NSImage] = [:], bitmap: [String: NSBitmapImageRep] = [:]
        for peek in (manifest.peek ?? [:]).values { guard peek.normalizedCrop != nil else { throw CompanionError.invalidPath } }
        let frameNames = manifest.animations.values.flatMap { $0.frames + [$0.baseFrame].compactMap { $0 } } + (manifest.peek ?? [:]).values.map(\.frame)
        for name in Set(frameNames) {
            guard name == (name as NSString).lastPathComponent, name.hasSuffix(".png") else { throw CompanionError.invalidPath }
            let data = try Data(contentsOf: root.appendingPathComponent(name))
            guard let image = NSImage(data: data), let rep = NSBitmapImageRep(data: data) else { throw CompanionError.unavailable("宠物图片无法读取。") }
            loaded[name] = image; bitmap[name] = rep
        }
        images = loaded; bitmaps = bitmap
        super.init(frame: .zero)
        if manifest.renderer == "bongocat" {
            let renderer = BongoCatRenderer(root: root.appendingPathComponent("BongoCat"))
            bongoCat = renderer; addSubview(renderer.view)
        }
        setAccessibilityElement(true); setAccessibilityRole(.button); setAccessibilityLabel("双击打开或收起哆啦对话；拖动起飞，松手落地")
        toolTip = "双击打开或收起对话；拖动起飞，松手落地；⌥+滚动调整大小"
        timer = Timer.scheduledTimer(withTimeInterval: bongoCat == nil ? 0.08 : 1.0 / 30, repeats: true) { [weak self] _ in self?.tick() }
        RunLoop.main.add(timer!, forMode: .common)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
    override var isOpaque: Bool { false }
    override var acceptsFirstResponder: Bool { false }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    private var animation: PetAnimation {
        manifest.animations[state] ?? manifest.animations[state == "takeoff" ? "dragging" : "idle"]!
    }
    private var frameName: String { animation.frames[index % animation.frames.count] }
    private func peekAppearance(for edge: PetEdgeDocking.Edge) -> PetPeek? { manifest.peek?[edge == .left || edge == .right ? "right" : "bottom"] }
    private var imageRect: NSRect {
        let lift = dragMotion.lift(at: Date.timeIntervalSinceReferenceDate, reducedMotion: paused || NSWorkspace.shared.accessibilityDisplayShouldReduceMotion)
        let rect = manifest.registration?.rect(for: animation.baseFrame ?? frameName, in: bounds) ?? bounds.insetBy(dx: 3, dy: 3)
        return rect.offsetBy(dx: 0, dy: lift * min(2.5, bounds.height * 0.015))
    }
    override func draw(_ dirtyRect: NSRect) {
        NSColor.clear.setFill(); dirtyRect.fill(using: .copy)
        if docking.collapsed, let edge = docking.edge, let appearance = peekAppearance(for: edge), let image = images[appearance.frame] {
            PetSpriteDrawing.drawPeek(image, appearance: appearance, edge: edge, in: bounds)
        } else {
            let pivot = bounds.minX+(manifest.registration?.anchor?.first ?? 0.5)*bounds.width
            PetSpriteDrawing.draw(animation, frame: frameName, images: images, in: imageRect, mirrorAboutX:facing.right ? nil : pivot)
        }
    }
    private func tick() {
        guard let window else { return }
        if let bongoCat {
            bongoCat.view.frame = imageRect
            bongoCat.view.isHidden = docking.collapsed || !bongoCat.ready
            let area = PetSizing.screenArea(for: placementFrame, areas: NSScreen.screens.map(\.visibleFrame)) ?? window.frame
            bongoCat.update(activity: state, paused: paused || NSWorkspace.shared.accessibilityDisplayShouldReduceMotion,
                visible: window.isVisible && !docking.collapsed, mirrored: !facing.right, screen: area)
        }
        guard window.isVisible else { return }
        let now = Date.timeIntervalSinceReferenceDate
        if resetAt > 0 && now >= resetAt { activity = "idle"; resetAt = 0 }
        dragMotion.advance(at: now)
        updateFacing()
        refreshPresentation()
        if edgeHiding && !pressed && !dragged && dragMotion.phase == .rest, let full = dockedFrame {
            let previous = docking.collapsed
            docking.tick(inside: full.insetBy(dx: -12, dy: -12).contains(NSEvent.mouseLocation), nearPeek: window.frame.insetBy(dx: -8, dy: -8).contains(NSEvent.mouseLocation), at: now)
            if previous != docking.collapsed { applyDockPresentation() }
        }
        if dragMotion.phase != .rest && !paused && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion { needsDisplay = true }
        if !paused && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion && now - lastFrameAt >= animation.frameDelay / 1000 {
            index = ["takeoff", "landing"].contains(state) ? min(index + 1, animation.frames.count - 1) : (index + 1) % animation.frames.count
            lastFrameAt = now; needsDisplay = true
        }
        if !dragged && !pressed {
            let point = convert(window.convertPoint(fromScreen: NSEvent.mouseLocation), from: nil)
            window.ignoresMouseEvents = !opaque(at: point)
        }
    }
    private func opaque(at point: NSPoint) -> Bool {
        if docking.collapsed, let edge = docking.edge, let appearance = peekAppearance(for: edge), let crop = appearance.normalizedCrop, let bitmap = bitmaps[appearance.frame] {
            guard bounds.contains(point) else { return false }
            var u = point.x/bounds.width, v = 1-point.y/bounds.height
            if edge == .left || edge == .top { u = 1-u }
            if edge == .top { v = 1-v }
            if (appearance.retraction ?? 0) > 0 || (appearance.rotation ?? 0) != 0 {
                for hand in appearance.hands {
                    let x = crop.minX+u*crop.width, y = crop.minY+v*crop.height
                    if NSBezierPath(ovalIn: hand).contains(NSPoint(x:x,y:y)) {
                        let bx = min(bitmap.pixelsWide-1,max(0,Int(x*Double(bitmap.pixelsWide))))
                        let by = min(bitmap.pixelsHigh-1,max(0,Int(y*Double(bitmap.pixelsHigh))))
                        if (bitmap.colorAt(x:bx,y:by)?.alphaComponent ?? 0) > 0.08 { return true }
                    }
                }
                let transform = PetSpriteDrawing.headTransform(appearance:appearance,edge:edge,in:bounds); transform.invert()
                let original = transform.transform(NSPoint(x:u*bounds.width,y:(1-v)*bounds.height))
                u = original.x/bounds.width; v = 1-original.y/bounds.height
                if u < 0 || u > 1 || v < 0 || v > 1 { return false }
            }
            let x = min(bitmap.pixelsWide-1, max(0, Int((crop.minX+u*crop.width)*Double(bitmap.pixelsWide))))
            let y = min(bitmap.pixelsHigh-1, max(0, Int((crop.minY+v*crop.height)*Double(bitmap.pixelsHigh))))
            return (bitmap.colorAt(x: x, y: y)?.alphaComponent ?? 0) > 0.08
        }
        var sample = point
        if !facing.right { sample.x = 2*(bounds.minX+(manifest.registration?.anchor?.first ?? 0.5)*bounds.width)-sample.x }
        guard imageRect.contains(sample), let bitmap = bitmaps[animation.baseFrame ?? frameName] else { return false }
        let x = min(bitmap.pixelsWide - 1, max(0, Int((sample.x - imageRect.minX) / imageRect.width * Double(bitmap.pixelsWide))))
        let y = min(bitmap.pixelsHigh - 1, max(0, bitmap.pixelsHigh - 1 - Int((sample.y - imageRect.minY) / imageRect.height * Double(bitmap.pixelsHigh))))
        return (bitmap.colorAt(x: x, y: y)?.alphaComponent ?? 0) > 0.08
    }
    func setState(_ value: String) {
        guard manifest.animations[value] != nil else { return }
        activity = value
        resetAt = ["success", "error"].contains(value) ? Date.timeIntervalSinceReferenceDate + 2.4 : 0
        refreshPresentation()
    }
    private func refreshPresentation() {
        let next = dragMotion.presentation(activity: activity)
        if state != next { state = next }
    }
    override func mouseDown(with event: NSEvent) {
        pressed = true
        if docking.collapsed { docking.reveal(at: Date.timeIntervalSinceReferenceDate); applyDockPresentation() }
        mouseStart = NSEvent.mouseLocation; windowStart = window?.frame.origin ?? .zero; dragged = false
        window?.ignoresMouseEvents = false
    }
    override func mouseDragged(with event: NSEvent) {
        let cursor = NSEvent.mouseLocation
        if hypot(cursor.x - mouseStart.x, cursor.y - mouseStart.y) < 4 && !dragged { return }
        if !dragged { docking.undock(); dockedFrame = nil; dragMotion.begin(at: Date.timeIntervalSinceReferenceDate) }
        dragged = true; window?.ignoresMouseEvents = false; refreshPresentation()
        let position = NSPoint(x: windowStart.x + cursor.x - mouseStart.x, y: windowStart.y + cursor.y - mouseStart.y)
        window?.setFrameOrigin(position)
        updateFacing()
    }
    override func mouseUp(with event: NSEvent) {
        pressed = false
        if dragged {
            dragged = false; clampToScreen(); dockNearEdge(); onMoved?()
            dragMotion.release(at: Date.timeIntervalSinceReferenceDate); refreshPresentation()
        }
        else if event.clickCount == 2 { onOpen?() }
    }
    override func rightMouseDown(with event: NSEvent) { onMenu?(event) }
    override func scrollWheel(with event: NSEvent) {
        guard event.modifierFlags.contains(.option) else { super.scrollWheel(with: event); return }
        let sensitivity = event.hasPreciseScrollingDeltas ? 0.006 : 0.055
        onScale?(exp(event.scrollingDeltaY * sensitivity))
    }
    override func accessibilityPerformPress() -> Bool {
        if docking.collapsed { docking.reveal(at: Date.timeIntervalSinceReferenceDate); applyDockPresentation() }
        else { onOpen?() }
        return true
    }
    func clampToScreen() {
        expandForPlacement()
        guard let window else { return }
        guard let area = PetSizing.screenArea(for: window.frame, areas: NSScreen.screens.map(\.visibleFrame)) else { return }
        window.setFrameOrigin(NSPoint(x: max(area.minX, min(area.maxX - window.frame.width, window.frame.minX)), y: max(area.minY, min(area.maxY - window.frame.height, window.frame.minY))))
    }
    func expandForPlacement() {
        if let frame = dockedFrame { window?.setFrame(frame, display: true) }
        docking.undock(); dockedFrame = nil; needsDisplay = true
    }
    private func updateFacing() {
        guard let area = PetSizing.screenArea(for:placementFrame,areas:NSScreen.screens.map(\.visibleFrame)) else { return }
        let previous = facing.right; facing.update(frame:placementFrame,area:area)
        if previous != facing.right { needsDisplay = true }
    }
    func dockNearEdge() {
        guard edgeHiding, let window,
              let screen = NSScreen.screens.first(where: { $0.visibleFrame.contains(NSPoint(x: window.frame.midX, y: window.frame.midY)) }),
              let edge = PetEdgeDocking.candidate(frame: window.frame, area: screen.visibleFrame, display: screen.frame, screens: NSScreen.screens.map(\.frame)), peekAppearance(for: edge) != nil else { return }
        let frame = PetEdgeDocking.snap(window.frame, edge: edge, area: screen.visibleFrame)
        window.setFrame(frame, display: true); dockedFrame = frame
        docking.dock(edge, at: Date.timeIntervalSinceReferenceDate)
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
        guard let appearance = peekAppearance(for: edge) else { return }
        let reference = manifest.registration?.headWidth ?? 0.52
        let target = docking.collapsed ? PetEdgeDocking.peekFrame(full, edge: edge, area: area, size: appearance.size(for: full.width, referenceHeadWidth: reference), grip: appearance.grip) : full
        // Interpolating the window size scales the character between poses.
        window.setFrame(target, display: true)
        needsDisplay = true
    }
}
