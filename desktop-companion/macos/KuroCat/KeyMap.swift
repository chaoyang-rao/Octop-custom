import Foundation
import CoreGraphics

/// Canonical physical key identifier shared across IOHIDManager (raw USB HID)
/// and CGEventTap (virtual key codes), ensuring full-state NKRO tracking in both
/// normal typing (any IME) and games.
enum PhysicalKey: String, Hashable, CaseIterable {
    // Row 0: Number row
    case escape, k1, k2, k3, k4, k5, k6, k7, k8, k9, k0, minus, equal, backspace
    // Row 1: QWERTY
    case tab, q, w, e, r, t, y, u, i, o, p, leftBracket, rightBracket, backslash
    // Row 2: ASDF
    case capsLock, a, s, d, f, g, h, j, k, l, semicolon, quote, enter
    // Row 3: ZXCV
    case leftShift, z, x, c, v, b, n, m, comma, period, slash, rightShift, arrowUp
    // Row 4: Modifiers & Space
    case leftControl, leftOption, leftCommand, space, rightCommand, rightOption, fn, arrowLeft, arrowDown, arrowRight
    // Extra function / nav keys (mapped cleanly onto top/edge key positions)
    case grave, rightControl, forwardDelete
    case f1, f2, f3, f4, f5, f6, f7, f8, f9, f10, f11, f12

    /// Short, clean keycap badge label matching mechanical keycap aesthetics.
    var badgeLabel: String {
        switch self {
        case .escape: return "ESC"
        case .grave: return "~"
        case .k1: return "1"
        case .k2: return "2"
        case .k3: return "3"
        case .k4: return "4"
        case .k5: return "5"
        case .k6: return "6"
        case .k7: return "7"
        case .k8: return "8"
        case .k9: return "9"
        case .k0: return "0"
        case .minus: return "-"
        case .equal: return "="
        case .backspace: return "⌫"
        case .forwardDelete: return "⌦"
        case .tab: return "⇥"
        case .q: return "Q"
        case .w: return "W"
        case .e: return "E"
        case .r: return "R"
        case .t: return "T"
        case .y: return "Y"
        case .u: return "U"
        case .i: return "I"
        case .o: return "O"
        case .p: return "P"
        case .leftBracket: return "["
        case .rightBracket: return "]"
        case .backslash: return "\\"
        case .capsLock: return "⇪"
        case .a: return "A"
        case .s: return "S"
        case .d: return "D"
        case .f: return "F"
        case .g: return "G"
        case .h: return "H"
        case .j: return "J"
        case .k: return "K"
        case .l: return "L"
        case .semicolon: return ";"
        case .quote: return "'"
        case .enter: return "↵"
        case .leftShift, .rightShift: return "⇧"
        case .z: return "Z"
        case .x: return "X"
        case .c: return "C"
        case .v: return "V"
        case .b: return "B"
        case .n: return "N"
        case .m: return "M"
        case .comma: return ","
        case .period: return "."
        case .slash: return "/"
        case .leftControl, .rightControl: return "⌃"
        case .leftOption, .rightOption: return "⌥"
        case .leftCommand, .rightCommand: return "⌘"
        case .space: return "␣"
        case .fn: return "Fn"
        case .arrowUp: return "↑"
        case .arrowDown: return "↓"
        case .arrowLeft: return "←"
        case .arrowRight: return "→"
        case .f1: return "F1"
        case .f2: return "F2"
        case .f3: return "F3"
        case .f4: return "F4"
        case .f5: return "F5"
        case .f6: return "F6"
        case .f7: return "F7"
        case .f8: return "F8"
        case .f9: return "F9"
        case .f10: return "F10"
        case .f11: return "F11"
        case .f12: return "F12"
        }
    }

    /// Which visual keycap on our 65% mini keyboard lights up when this key is pressed.
    var visualKey: PhysicalKey {
        switch self {
        case .grave: return .escape
        case .forwardDelete: return .backspace
        case .rightControl: return .fn
        case .f1: return .k1
        case .f2: return .k2
        case .f3: return .k3
        case .f4: return .k4
        case .f5: return .k5
        case .f6: return .k6
        case .f7: return .k7
        case .f8: return .k8
        case .f9: return .k9
        case .f10: return .k0
        case .f11: return .minus
        case .f12: return .equal
        default: return self
        }
    }

    /// Preferred paw in viewer coordinates:
    /// Because the keyboard faces the cat (rotated 180° relative to the viewer),
    /// viewer-left paw = cat's RIGHT hand (mouse + Y-P, H-Enter, N-/, 6-Backspace, Arrows),
    /// viewer-right paw = cat's LEFT hand (WASD, Q-T, A-G, Z-B, Esc, 1-5, Tab, Caps, LShift).
    var prefersLeftPaw: Bool {
        switch self.visualKey {
        case .escape, .k1, .k2, .k3, .k4, .k5, .k6,
             .tab, .q, .w, .e, .r, .t,
             .capsLock, .a, .s, .d, .f, .g,
             .leftShift, .z, .x, .c, .v, .b,
             .leftControl, .leftOption, .leftCommand,
             .space:
            return false // viewer-right paw (cat's left hand — zero arm crossing in WASD + Mouse gaming!)
        default:
            return true  // viewer-left paw (cat's right hand — right half of keyboard + mouse!)
        }
    }

    /// Map USB HID Keyboard/Keypad Usage ID (Page 0x07) -> PhysicalKey
    static func fromHIDUsage(_ usage: UInt32) -> PhysicalKey? {
        switch usage {
        case 0x04: return .a
        case 0x05: return .b
        case 0x06: return .c
        case 0x07: return .d
        case 0x08: return .e
        case 0x09: return .f
        case 0x0A: return .g
        case 0x0B: return .h
        case 0x0C: return .i
        case 0x0D: return .j
        case 0x0E: return .k
        case 0x0F: return .l
        case 0x10: return .m
        case 0x11: return .n
        case 0x12: return .o
        case 0x13: return .p
        case 0x14: return .q
        case 0x15: return .r
        case 0x16: return .s
        case 0x17: return .t
        case 0x18: return .u
        case 0x19: return .v
        case 0x1A: return .w
        case 0x1B: return .x
        case 0x1C: return .y
        case 0x1D: return .z
        case 0x1E: return .k1
        case 0x1F: return .k2
        case 0x20: return .k3
        case 0x21: return .k4
        case 0x22: return .k5
        case 0x23: return .k6
        case 0x24: return .k7
        case 0x25: return .k8
        case 0x26: return .k9
        case 0x27: return .k0
        case 0x28: return .enter
        case 0x29: return .escape
        case 0x2A: return .backspace
        case 0x2B: return .tab
        case 0x2C: return .space
        case 0x2D: return .minus
        case 0x2E: return .equal
        case 0x2F: return .leftBracket
        case 0x30: return .rightBracket
        case 0x31: return .backslash
        case 0x33: return .semicolon
        case 0x34: return .quote
        case 0x35: return .grave
        case 0x36: return .comma
        case 0x37: return .period
        case 0x38: return .slash
        case 0x39: return .capsLock
        case 0x3A: return .f1
        case 0x3B: return .f2
        case 0x3C: return .f3
        case 0x3D: return .f4
        case 0x3E: return .f5
        case 0x3F: return .f6
        case 0x40: return .f7
        case 0x41: return .f8
        case 0x42: return .f9
        case 0x43: return .f10
        case 0x44: return .f11
        case 0x45: return .f12
        case 0x4C: return .forwardDelete
        case 0x4F: return .arrowRight
        case 0x50: return .arrowLeft
        case 0x51: return .arrowDown
        case 0x52: return .arrowUp
        // Numpad support (great for gaming & data entry)
        case 0x58: return .enter
        case 0x59: return .k1
        case 0x5A: return .k2
        case 0x5B: return .k3
        case 0x5C: return .k4
        case 0x5D: return .k5
        case 0x5E: return .k6
        case 0x5F: return .k7
        case 0x60: return .k8
        case 0x61: return .k9
        case 0x62: return .k0
        case 0x63: return .period
        // Modifiers
        case 0xE0: return .leftControl
        case 0xE1: return .leftShift
        case 0xE2: return .leftOption
        case 0xE3: return .leftCommand
        case 0xE4: return .rightControl
        case 0xE5: return .rightShift
        case 0xE6: return .rightOption
        case 0xE7: return .rightCommand
        default: return nil
        }
    }

    /// Map macOS virtual CGKeyCode -> PhysicalKey
    static func fromCGKeyCode(_ code: UInt16) -> PhysicalKey? {
        switch code {
        case 0: return .a
        case 1: return .s
        case 2: return .d
        case 3: return .f
        case 4: return .h
        case 5: return .g
        case 6: return .z
        case 7: return .x
        case 8: return .c
        case 9: return .v
        case 11: return .b
        case 12: return .q
        case 13: return .w
        case 14: return .e
        case 15: return .r
        case 16: return .y
        case 17: return .t
        case 18: return .k1
        case 19: return .k2
        case 20: return .k3
        case 21: return .k4
        case 22: return .k6
        case 23: return .k5
        case 24: return .equal
        case 25: return .k9
        case 26: return .k7
        case 27: return .minus
        case 28: return .k8
        case 29: return .k0
        case 30: return .rightBracket
        case 31: return .o
        case 32: return .u
        case 33: return .leftBracket
        case 34: return .i
        case 35: return .p
        case 36: return .enter
        case 37: return .l
        case 38: return .j
        case 39: return .quote
        case 40: return .k
        case 41: return .semicolon
        case 42: return .backslash
        case 43: return .comma
        case 44: return .slash
        case 45: return .n
        case 46: return .m
        case 47: return .period
        case 48: return .tab
        case 49: return .space
        case 50: return .grave
        case 51: return .backspace
        case 53: return .escape
        case 54: return .rightCommand
        case 55: return .leftCommand
        case 56: return .leftShift
        case 57: return .capsLock
        case 58: return .leftOption
        case 59: return .leftControl
        case 60: return .rightShift
        case 61: return .rightOption
        case 62: return .rightControl
        case 63: return .fn
        case 76: return .enter
        case 82: return .k0
        case 83: return .k1
        case 84: return .k2
        case 85: return .k3
        case 86: return .k4
        case 87: return .k5
        case 88: return .k6
        case 89: return .k7
        case 91: return .k8
        case 92: return .k9
        case 96: return .f5
        case 97: return .f6
        case 98: return .f7
        case 99: return .f3
        case 100: return .f8
        case 101: return .f9
        case 103: return .f11
        case 109: return .f10
        case 111: return .f12
        case 117: return .forwardDelete
        case 118: return .f4
        case 120: return .f2
        case 122: return .f1
        case 123: return .arrowLeft
        case 124: return .arrowRight
        case 125: return .arrowDown
        case 126: return .arrowUp
        default: return nil
        }
    }
}

/// Visual definition of a single keycap on the mini 65% mechanical keyboard.
struct VisualKeycap {
    let key: PhysicalKey
    let row: Int
    let xUnits: CGFloat      // start X in normalized [0..1] keyboard interior units
    let widthUnits: CGFloat  // width in normalized [0..1] units
    let isAmberAccent: Bool
    /// Normalized center (u in 0..1, v in 0..1) inside the keyboard key-well
    var normalizedCenter: CGPoint {
        let u = xUnits + widthUnits * 0.5
        let v = (CGFloat(row) + 0.5) / 5.0
        return CGPoint(x: u, y: v)
    }
}

/// Complete 65% mini mechanical keyboard layout facing the cat (180° rotated relative to viewer),
/// matching the reference video's Spacebar closest to the cat, amber Enter on left, and amber Esc at bottom-right!
enum KeyboardLayout {
    static let keycaps: [VisualKeycap] = {
        let rows: [[(PhysicalKey, CGFloat, Bool)]] = [
            // Row 0: 15.0u total (Esc is amber -> lands at bottom-right corner when facing cat!)
            [
                (.escape, 1.0, true), (.k1, 1.0, false), (.k2, 1.0, false), (.k3, 1.0, false),
                (.k4, 1.0, false), (.k5, 1.0, false), (.k6, 1.0, false), (.k7, 1.0, false),
                (.k8, 1.0, false), (.k9, 1.0, false), (.k0, 1.0, false), (.minus, 1.0, false),
                (.equal, 1.0, false), (.backspace, 2.0, false)
            ],
            // Row 1: 15.0u total
            [
                (.tab, 1.5, false), (.q, 1.0, false), (.w, 1.0, false), (.e, 1.0, false),
                (.r, 1.0, false), (.t, 1.0, false), (.y, 1.0, false), (.u, 1.0, false),
                (.i, 1.0, false), (.o, 1.0, false), (.p, 1.0, false), (.leftBracket, 1.0, false),
                (.rightBracket, 1.0, false), (.backslash, 1.5, false)
            ],
            // Row 2: 15.0u total (Enter is amber -> lands on middle-left edge when facing cat!)
            [
                (.capsLock, 1.75, false), (.a, 1.0, false), (.s, 1.0, false), (.d, 1.0, false),
                (.f, 1.0, false), (.g, 1.0, false), (.h, 1.0, false), (.j, 1.0, false),
                (.k, 1.0, false), (.l, 1.0, false), (.semicolon, 1.0, false), (.quote, 1.0, false),
                (.enter, 2.25, true)
            ],
            // Row 3: 15.0u total
            [
                (.leftShift, 2.25, false), (.z, 1.0, false), (.x, 1.0, false), (.c, 1.0, false),
                (.v, 1.0, false), (.b, 1.0, false), (.n, 1.0, false), (.m, 1.0, false),
                (.comma, 1.0, false), (.period, 1.0, false), (.slash, 1.0, false),
                (.rightShift, 1.75, false), (.arrowUp, 1.0, false)
            ],
            // Row 4: 15.0u total (Spacebar row -> lands on TOP row closest to the cat!)
            [
                (.leftControl, 1.25, false), (.leftOption, 1.25, false), (.leftCommand, 1.25, false),
                (.space, 6.25, false),
                (.rightCommand, 1.0, false), (.rightOption, 1.0, false),
                (.arrowLeft, 1.0, false), (.arrowDown, 1.0, false), (.arrowRight, 1.0, false)
            ]
        ]

        var result: [VisualKeycap] = []
        let totalUnits: CGFloat = 15.0
        for (rowIdx, row) in rows.enumerated() {
            var cursor: CGFloat = 0
            for (key, width, isAmber) in row {
                result.append(VisualKeycap(
                    key: key,
                    row: rowIdx,
                    xUnits: cursor / totalUnits,
                    widthUnits: width / totalUnits,
                    isAmberAccent: isAmber
                ))
                cursor += width
            }
        }
        return result
    }()

    static let lookup: [PhysicalKey: VisualKeycap] = {
        var dict: [PhysicalKey: VisualKeycap] = [:]
        for cap in keycaps {
            dict[cap.key] = cap
        }
        return dict
    }()

    /// Screen-space keyboard quad point (su in 0..1 left-to-right, sv in 0..1 top-to-bottom).
    static func screenQuadPoint(su: CGFloat, sv: CGFloat) -> CGPoint {
        let topLeft = CGPoint(x: 109, y: 238)
        let topRight = CGPoint(x: 281, y: 247)
        let bottomLeft = CGPoint(x: 103, y: 282)
        let bottomRight = CGPoint(x: 286, y: 292)

        let topX = topLeft.x + (topRight.x - topLeft.x) * su
        let topY = topLeft.y + (topRight.y - topLeft.y) * su
        let botX = bottomLeft.x + (bottomRight.x - bottomLeft.x) * su
        let botY = bottomLeft.y + (bottomRight.y - bottomLeft.y) * su

        return CGPoint(
            x: topX + (botX - topX) * sv,
            y: topY + (botY - topY) * sv
        )
    }

    /// Convert logical keyboard (u, v) into 360x320 canvas coordinates,
    /// rotated 180° so the keyboard faces the cat (Spacebar at top closest to cat, Esc at bottom-right!).
    static func canvasPoint(u: CGFloat, v: CGFloat) -> CGPoint {
        screenQuadPoint(su: 1.0 - u, sv: 1.0 - v)
    }

    static func canvasPoint(for key: PhysicalKey) -> CGPoint {
        let vk = key.visualKey
        if let cap = lookup[vk] {
            let c = cap.normalizedCenter
            return canvasPoint(u: c.x, v: c.y)
        }
        return canvasPoint(u: 0.5, v: 0.5)
    }

    /// Bilinear interpolation on Xiao Douni Video 2's angled hand-drawn keyboard surface (`u` left→right, `v` top→bottom in 832x720 V2Space).
    static func v2KbPoint(u: CGFloat, v: CGFloat) -> CGPoint {
        let tl = CGPoint(x: 242, y: 336)
        let tr = CGPoint(x: 782, y: 446)
        let br = CGPoint(x: 584, y: 586)
        let bl = CGPoint(x: 28, y: 440)
        let topX = tl.x + (tr.x - tl.x) * u
        let topY = tl.y + (tr.y - tl.y) * u
        let botX = bl.x + (br.x - bl.x) * u
        let botY = bl.y + (br.y - bl.y) * u
        return CGPoint(x: topX + (botX - topX) * v, y: topY + (botY - topY) * v)
    }

    /// Single source of truth mapping any PhysicalKey -> exact Video 2 keyboard cell `(row, col)` and V2Space center point.
    static func v2KeyCellInfo(for key: PhysicalKey) -> (row: Int, col: Int, center: CGPoint) {
        let wellU0: CGFloat = 0.31, wellU1: CGFloat = 0.95
        let wellV0: CGFloat = 0.11, wellV1: CGFloat = 0.87
        let vk = key.visualKey
        if vk == .space {
            let su = wellU0 + (wellU1 - wellU0) * (4.0 / 8.0)
            let sv = wellV0 + (wellV1 - wellV0) * (3.5 / 4.0)
            return (3, 2, v2KbPoint(u: su, v: sv))
        }
        guard let cap = lookup[vk] else {
            let su = wellU0 + (wellU1 - wellU0) * (3.5 / 8.0)
            let sv = wellV0 + (wellV1 - wellV0) * (1.5 / 4.0)
            return (1, 3, v2KbPoint(u: su, v: sv))
        }
        let normU = max(0, min(1, 1.0 - (cap.xUnits + cap.widthUnits * 0.5)))
        let col = max(0, min(7, Int(normU * 7.99)))
        var row = max(0, min(3, cap.row >= 3 ? 3 : cap.row))
        if row == 3 && col >= 2 && col <= 5 {
            row = 2
        }
        let su = wellU0 + (wellU1 - wellU0) * ((CGFloat(col) + 0.5) / 8.0)
        let sv = wellV0 + (wellV1 - wellV0) * ((CGFloat(row) + 0.5) / 4.0)
        return (row, col, v2KbPoint(u: su, v: sv))
    }

    static func v2KeyCellCenter(for key: PhysicalKey) -> CGPoint {
        v2KeyCellInfo(for: key).center
    }
}
