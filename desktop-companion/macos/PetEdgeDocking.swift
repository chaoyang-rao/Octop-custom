import Foundation
import CoreGraphics

/// Edge geometry and hover timing are independent of windows and display I/O.
struct PetEdgeDocking {
    enum Edge: String, CaseIterable { case left, right, bottom, top }
    private(set) var edge: Edge?
    private(set) var collapsed = false
    private var hideAt: TimeInterval = 0

    mutating func dock(_ value: Edge, at now: TimeInterval) {
        edge = value; collapsed = false; hideAt = now + 1
    }
    mutating func undock() { edge = nil; collapsed = false }
    mutating func reveal(at now: TimeInterval) { collapsed = false; hideAt = now + 1.2 }
    mutating func tick(inside: Bool, nearPeek: Bool, at now: TimeInterval) {
        guard edge != nil else { return }
        if collapsed {
            if nearPeek { reveal(at: now) }
        } else if inside { hideAt = now + 1.2 }
        else if now >= hideAt { collapsed = true }
    }

    static func candidate(frame: NSRect, area: NSRect, display: NSRect, screens: [NSRect]) -> Edge? {
        let threshold = max(16, min(30, frame.width * 0.16))
        let distances: [(Edge, CGFloat)] = [(.left, abs(frame.minX-area.minX)), (.right, abs(frame.maxX-area.maxX)), (.bottom, abs(frame.minY-area.minY)), (.top, abs(frame.maxY-area.maxY))]
        return distances.filter { edge, distance in
            guard distance <= threshold else { return false }
            // Moving between adjacent monitors is a drag, not a hiding gesture.
            return !screens.contains { other in
                guard other != display else { return false }
                switch edge {
                case .left: return abs(other.maxX-display.minX) < 2 && other.minY < frame.midY && frame.midY < other.maxY
                case .right: return abs(other.minX-display.maxX) < 2 && other.minY < frame.midY && frame.midY < other.maxY
                case .bottom: return abs(other.maxY-display.minY) < 2 && other.minX < frame.midX && frame.midX < other.maxX
                case .top: return abs(other.minY-display.maxY) < 2 && other.minX < frame.midX && frame.midX < other.maxX
                }
            }
        }.min(by: { $0.1 < $1.1 })?.0
    }
    static func snap(_ frame: NSRect, edge: Edge, area: NSRect) -> NSRect {
        var value = frame
        switch edge {
        case .left: value.origin.x = area.minX
        case .right: value.origin.x = area.maxX-value.width
        case .bottom: value.origin.y = area.minY
        case .top: value.origin.y = area.maxY-value.height
        }
        value.origin.x = max(area.minX, min(area.maxX-value.width, value.minX))
        value.origin.y = max(area.minY, min(area.maxY-value.height, value.minY))
        return value
    }
    static func peekFrame(_ full: NSRect, edge: Edge, area: NSRect, size: NSSize? = nil, grip: CGFloat? = nil) -> NSRect {
        let size = size ?? NSSize(width: full.width*0.68, height: full.width*0.68)
        let grip = grip ?? (edge == .left || edge == .right ? 0.92 : 0.06)
        let small = NSRect(x: full.midX-size.width/2, y: full.midY-size.height/2, width: size.width, height: size.height)
        var value = snap(small, edge: edge, area: area)
        switch edge {
        case .left: value.origin.x = area.minX-size.width*(1-grip)
        case .right: value.origin.x = area.maxX-size.width*grip
        case .bottom: value.origin.y = area.minY-size.height*grip
        case .top: value.origin.y = area.maxY-size.height*(1-grip)
        }
        return value
    }
    static func selfTest() {
        let screen = NSRect(x: 0, y: 0, width: 1440, height: 900)
        let left = NSRect(x: 0, y: 300, width: 158, height: 158)
        precondition(candidate(frame: left, area: screen, display: screen, screens: [screen]) == .left)
        let adjacent = NSRect(x: -1440, y: 0, width: 1440, height: 900)
        precondition(candidate(frame: left, area: screen, display: screen, screens: [screen, adjacent]) == nil)
        let onLeftDisplay = NSRect(x: -1440, y: 300, width: 158, height: 158)
        precondition(candidate(frame: onLeftDisplay, area: adjacent, display: adjacent, screens: [screen, adjacent]) == .left)
        precondition(peekFrame(onLeftDisplay, edge: .left, area: adjacent).minX < adjacent.minX)
        for edge in Edge.allCases {
            let frame = peekFrame(left, edge: edge, area: screen)
            precondition(!screen.contains(frame) && frame.width < left.width)
            precondition(frame.intersection(screen).width >= frame.width*0.90)
            precondition(frame.intersection(screen).height >= frame.height*0.91)
        }
        precondition(peekFrame(left, edge: .right, area: screen).maxX > screen.maxX)
        var dock = PetEdgeDocking(); dock.dock(.left, at: 0)
        dock.tick(inside: false, nearPeek: false, at: 0.5); precondition(!dock.collapsed)
        dock.tick(inside: false, nearPeek: false, at: 1.1); precondition(dock.collapsed)
        dock.tick(inside: false, nearPeek: true, at: 1.2); precondition(!dock.collapsed)
        dock.tick(inside: true, nearPeek: false, at: 2); precondition(!dock.collapsed)
        dock.tick(inside: false, nearPeek: false, at: 3.3); precondition(dock.collapsed)
        dock.undock(); precondition(dock.edge == nil && !dock.collapsed)
    }
}
