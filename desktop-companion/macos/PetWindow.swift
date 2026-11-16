import AppKit

struct PetAnimation: Decodable { let frames: [String]; let frameDelay: Double }
struct PetManifest: Decodable { let name: String; let animations: [String: PetAnimation] }
final class PetPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}
final class PetView: NSView {
    var onOpen: (() -> Void)?
    var onMenu: ((NSEvent) -> Void)?
    var onMoved: (() -> Void)?
    var onScale: ((Double) -> Void)?
    var state = "idle" { didSet { index = 0; lastFrameAt = 0; needsDisplay = true } }
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
    private var resetAt: TimeInterval = 0
    init(root: URL) throws {
        manifest = try JSONDecoder().decode(PetManifest.self, from: Data(contentsOf: root.appendingPathComponent("pet.json")))
        var loaded: [String: NSImage] = [:], bitmap: [String: NSBitmapImageRep] = [:]
        for name in Set(manifest.animations.values.flatMap(\.frames)) {
            guard name == (name as NSString).lastPathComponent, name.hasSuffix(".png") else { throw CompanionError.invalidPath }
            let data = try Data(contentsOf: root.appendingPathComponent(name))
            guard let image = NSImage(data: data), let rep = NSBitmapImageRep(data: data) else { throw CompanionError.unavailable("宠物图片无法读取。") }
            loaded[name] = image; bitmap[name] = rep
        }
        images = loaded; bitmaps = bitmap
        super.init(frame: .zero)
        setAccessibilityElement(true); setAccessibilityRole(.button); setAccessibilityLabel("双击打开或收起哆啦对话；拖动可移动位置")
        toolTip = "双击打开或收起对话；拖动移动；⌥+滚动调整大小"
        timer = Timer.scheduledTimer(withTimeInterval: 0.08, repeats: true) { [weak self] _ in self?.tick() }
        RunLoop.main.add(timer!, forMode: .common)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
    override var isOpaque: Bool { false }
    override var acceptsFirstResponder: Bool { false }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    private var animation: PetAnimation { manifest.animations[state] ?? manifest.animations["idle"]! }
    private var frameName: String { animation.frames[index % animation.frames.count] }
    private var imageRect: NSRect { bounds.insetBy(dx: 3, dy: 3) }
    override func draw(_ dirtyRect: NSRect) {
        NSColor.clear.setFill(); dirtyRect.fill(using: .copy)
        images[frameName]?.draw(in: imageRect, from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: [.interpolation: NSImageInterpolation.high])
    }
    private func tick() {
        guard let window, window.isVisible else { return }
        let now = Date.timeIntervalSinceReferenceDate
        if resetAt > 0 && now >= resetAt { state = "idle"; resetAt = 0 }
        if !paused && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion && now - lastFrameAt >= animation.frameDelay / 1000 {
            index = (index + 1) % animation.frames.count; lastFrameAt = now; needsDisplay = true
        }
        if !dragged {
            let point = convert(window.convertPoint(fromScreen: NSEvent.mouseLocation), from: nil)
            window.ignoresMouseEvents = !opaque(at: point)
        }
    }
    private func opaque(at point: NSPoint) -> Bool {
        guard imageRect.contains(point), let bitmap = bitmaps[frameName] else { return false }
        let x = min(bitmap.pixelsWide - 1, max(0, Int((point.x - imageRect.minX) / imageRect.width * Double(bitmap.pixelsWide))))
        let y = min(bitmap.pixelsHigh - 1, max(0, bitmap.pixelsHigh - 1 - Int((point.y - imageRect.minY) / imageRect.height * Double(bitmap.pixelsHigh))))
        return (bitmap.colorAt(x: x, y: y)?.alphaComponent ?? 0) > 0.08
    }
    func setState(_ value: String) {
        guard manifest.animations[value] != nil else { return }
        state = value
        resetAt = ["success", "error"].contains(value) ? Date.timeIntervalSinceReferenceDate + 2.4 : 0
    }
    override func mouseDown(with event: NSEvent) { mouseStart = NSEvent.mouseLocation; windowStart = window?.frame.origin ?? .zero; dragged = false }
    override func mouseDragged(with event: NSEvent) {
        let cursor = NSEvent.mouseLocation
        if hypot(cursor.x - mouseStart.x, cursor.y - mouseStart.y) < 4 && !dragged { return }
        dragged = true; window?.ignoresMouseEvents = false; setState("dragging")
        let position = NSPoint(x: windowStart.x + cursor.x - mouseStart.x, y: windowStart.y + cursor.y - mouseStart.y)
        window?.setFrameOrigin(position)
    }
    override func mouseUp(with event: NSEvent) {
        if dragged { dragged = false; clampToScreen(); onMoved?(); setState("idle") }
        else if event.clickCount == 2 { onOpen?() }
    }
    override func rightMouseDown(with event: NSEvent) { onMenu?(event) }
    override func scrollWheel(with event: NSEvent) {
        guard event.modifierFlags.contains(.option) else { super.scrollWheel(with: event); return }
        let sensitivity = event.hasPreciseScrollingDeltas ? 0.006 : 0.055
        onScale?(exp(event.scrollingDeltaY * sensitivity))
    }
    override func accessibilityPerformPress() -> Bool { onOpen?(); return true }
    func clampToScreen() {
        guard let window else { return }
        guard let area = PetSizing.screenArea(for: window.frame, areas: NSScreen.screens.map(\.visibleFrame)) else { return }
        window.setFrameOrigin(NSPoint(x: max(area.minX, min(area.maxX - window.frame.width, window.frame.minX)), y: max(area.minY, min(area.maxY - window.frame.height, window.frame.minY))))
    }
}
