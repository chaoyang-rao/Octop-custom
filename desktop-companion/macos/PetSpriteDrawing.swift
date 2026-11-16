import AppKit

enum PetSpriteDrawing {
    // Overlay coordinates are normalized from the sprite's top-left corner.
    static func patchRect(_ animation: PetAnimation, in rect: NSRect) -> NSRect? {
        guard animation.baseFrame != nil, let patch = animation.overlayRect,
              patch.count == 4, patch.allSatisfy({ $0.isFinite && $0 >= 0 }),
              patch[2] > 0, patch[3] > 0,
              patch[0] + patch[2] <= 1, patch[1] + patch[3] <= 1 else { return nil }
        return NSRect(x: rect.minX + rect.width * patch[0],
                      y: rect.minY + rect.height * (1 - patch[1] - patch[3]),
                      width: rect.width * patch[2], height: rect.height * patch[3])
    }

    static func draw(_ animation: PetAnimation, frame: String, images: [String: NSImage], in rect: NSRect) {
        func paint(_ name: String) {
            images[name]?.draw(in: rect, from: .zero, operation: .sourceOver, fraction: 1,
                               respectFlipped: true, hints: [.interpolation: NSImageInterpolation.high])
        }
        guard let base = animation.baseFrame, let patch = patchRect(animation, in: rect) else {
            paint(frame)
            return
        }
        paint(base)
        guard frame != base else { return }
        NSGraphicsContext.saveGraphicsState()
        NSBezierPath(rect: patch).addClip()
        paint(frame)
        NSGraphicsContext.restoreGraphicsState()
    }
}
