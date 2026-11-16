import AppKit

enum PetSizing {
    static let defaultSide = 158.0
    static let minimumScale = 0.5
    static let maximumScale = 2.5

    static func boundedScale(_ scale: Double) -> Double {
        scale.isFinite ? min(maximumScale, max(minimumScale, scale)) : 1
    }
    static func restoredSide(_ saved: Double) -> Double {
        guard saved.isFinite, saved > 0 else { return defaultSide }
        return min(defaultSide * maximumScale, max(defaultSide * minimumScale, saved))
    }
    static func screenArea(for frame: NSRect, areas: [NSRect]) -> NSRect? {
        let center = NSPoint(x: frame.midX, y: frame.midY)
        if let containing = areas.first(where: { $0.contains(center) }) { return containing }
        return areas.max { first, second in
            let a = first.intersection(frame), b = second.intersection(frame)
            return (a.isNull ? 0 : a.width * a.height) < (b.isNull ? 0 : b.width * b.height)
        }
    }
    static func frame(resizing old: NSRect, scale: Double, within area: NSRect) -> NSRect {
        let side = min(CGFloat(defaultSide * boundedScale(scale)), max(1, min(area.width, area.height)))
        // Keep the bottom center (the character's feet) steady unless a screen
        // edge requires clamping. Continuous updates retain fractional values.
        let x = max(area.minX, min(area.maxX - side, old.midX - side / 2))
        let y = max(area.minY, min(area.maxY - side, old.minY))
        return NSRect(x: x, y: y, width: side, height: side)
    }
    static func selfTest() {
        let screen = NSRect(x: 0, y: 0, width: 1440, height: 900)
        let original = NSRect(x: 500, y: 40, width: 158, height: 158)
        let first = frame(resizing: original, scale: 1.013, within: screen)
        let second = frame(resizing: first, scale: 1.017, within: screen)
        precondition(abs(first.width - second.width) > 0 && abs(first.width - second.width) < 1)
        precondition(abs(second.midX - original.midX) < 0.0001 && second.minY == original.minY)
        let edge = frame(resizing: NSRect(x: 1300, y: 850, width: 120, height: 120), scale: 2.5, within: screen)
        precondition(screen.contains(edge))
        precondition(restoredSide(196) == 196 && restoredSide(120) == 120)
        precondition(boundedScale(.infinity) == 1 && boundedScale(-1) == minimumScale)
        let other = NSRect(x: -1440, y: 0, width: 1440, height: 900)
        precondition(screenArea(for: NSRect(x: -300, y: 40, width: 158, height: 158), areas: [screen, other]) == other)
    }
}
