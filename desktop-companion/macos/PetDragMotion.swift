import Foundation

struct PetDragMotion {
    enum Phase: Equatable { case rest, takeoff, flying, landing }
    private(set) var phase: Phase = .rest
    private var startedAt: TimeInterval = 0

    mutating func begin(at now: TimeInterval) { phase = .takeoff; startedAt = now }
    mutating func release(at now: TimeInterval) { phase = .landing; startedAt = now }
    mutating func advance(at now: TimeInterval) {
        if phase == .takeoff && now - startedAt >= 0.32 { phase = .flying; startedAt = now }
        else if phase == .landing && now - startedAt >= 0.36 { phase = .rest }
    }
    func presentation(activity: String) -> String {
        switch phase {
        case .rest: return activity
        case .takeoff: return "takeoff"
        case .flying: return "dragging"
        case .landing: return "landing"
        }
    }
    func lift(at now: TimeInterval, reducedMotion: Bool) -> Double {
        if reducedMotion { return 0 }
        let elapsed = max(0, now - startedAt)
        switch phase {
        case .rest: return 0
        case .takeoff: return 0.7 * sin(min(1, elapsed / 0.32) * .pi / 2)
        case .flying: return 0.65 + 0.2 * sin(elapsed * 6)
        case .landing: return 0.85 * exp(-12 * elapsed) * cos(elapsed * 19)
        }
    }
}
