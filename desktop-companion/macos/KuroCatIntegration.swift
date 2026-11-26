import AppKit
import QuartzCore

/// Octop owns the window and assistant lifecycle; KuroCat owns drawing and motion.
final class KuroCatIntegration {
    let physics = CatPhysics()
    private(set) var running = false
    private var previousHover: CGPoint?
    var paused = false { didSet { if paused && !oldValue { InputEngine.shared.resetAllKeys() } } }
    var needsPermission: Bool { InputEngine.shared.status.needsAttention }

    init() {
        // Keep the original keyboard layout and the physics input coordinates
        // in the same orientation, including on the right half of the screen.
        if CatSettings.shared.flipHorizontal { CatSettings.shared.flipHorizontal = false }
    }

    func start() {
        guard !running else { return }
        running = true
        let input = InputEngine.shared
        input.onKeyDown = { [weak self] key in
            DispatchQueue.main.async { guard let self, !self.paused else { return }; self.physics.triggerKeyDown(key) }
        }
        input.onMouseClick = { [weak self] button, down in
            DispatchQueue.main.async { guard let self, !self.paused else { return }; self.physics.triggerMouseClick(button: button, isDown: down) }
        }
        input.start()
    }
    func stop() {
        guard running else { return }
        running = false
        let input = InputEngine.shared
        input.onKeyDown = nil; input.onKeyUp = nil; input.onMouseClick = nil
        input.resetAllKeys(); input.flushStats(); input.stop()
    }
    func requestPermission() { InputEngine.shared.requestPermissionsAndOpenSettings() }
    func step(dt: CGFloat, frame: NSRect) {
        guard !paused else { return }
        physics.step(dt: dt, windowFrameInScreen: Self.screenCanvasFrame(in: frame))
    }
    static func canvasRect(in bounds: NSRect) -> NSRect {
        let scale = max(0.001, min((bounds.width - 6) / 360, (bounds.height - 6) / 320))
        return NSRect(x: bounds.midX - scale * 180, y: bounds.midY - scale * 160, width: scale * 360, height: scale * 320)
    }
    static func canvasPoint(_ point: NSPoint, in bounds: NSRect) -> CGPoint {
        let rect = canvasRect(in: bounds)
        return CGPoint(x: (point.x - rect.minX) * 360 / rect.width, y: (rect.maxY - point.y) * 320 / rect.height)
    }
    static func screenCanvasFrame(in window: NSRect) -> NSRect {
        let canvas = canvasRect(in: NSRect(origin: .zero, size: window.size))
        return canvas.offsetBy(dx: window.minX, dy: window.minY)
    }
    func hitZone(_ point: NSPoint, in bounds: NSRect) -> CatHitZone {
        let canvas = Self.canvasPoint(point, in: bounds)
        let cat = CatRenderer.canvasPointToCatSpace(canvas, flipped: CatSettings.shared.flipHorizontal, rotationDeg: 0)
        return CatRenderer.hitTest(point: cat, physics: physics, showPermissionPill: needsPermission)
    }
    func hover(_ point: NSPoint?, in bounds: NSRect) {
        guard let point, !paused else { previousHover = nil; return }
        let canvas = Self.canvasPoint(point, in: bounds)
        let cat = CatRenderer.canvasPointToCatSpace(canvas, flipped: CatSettings.shared.flipHorizontal, rotationDeg: 0)
        physics.updateTailHover(canvasPoint: cat)
        let zone = hitZone(point, in: bounds)
        if zone == .head || zone == .body {
            if let previous = previousHover {
                let delta = hypot(cat.x - previous.x, cat.y - previous.y)
                if delta > 1.2 && delta < 80 { physics.registerPetStroke(canvasPoint: cat, delta: delta, isHead: zone == .head) }
            }
            previousHover = cat
        } else { previousHover = nil }
    }
    func draw(in context: CGContext, bounds: NSRect, permission: Bool) {
        let rect = Self.canvasRect(in: bounds)
        context.saveGState()
        context.translateBy(x: rect.minX, y: rect.maxY)
        context.scaleBy(x: rect.width / 360, y: -rect.height / 320)
        CatRenderer.draw(in: context, physics: physics, showPermissionPill: permission,
                         permissionPillText: InputEngine.shared.status.permissionPillText)
        context.restoreGState()
    }
    func image() -> CGImage? {
        guard let context = CGContext(data: nil, width: 720, height: 640, bitsPerComponent: 8, bytesPerRow: 720 * 4,
            space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
        context.scaleBy(x: 2, y: 2)
        draw(in: context, bounds: NSRect(x: -3, y: -3, width: 366, height: 326), permission: false)
        return context.makeImage()
    }
    deinit { stop() }
}
