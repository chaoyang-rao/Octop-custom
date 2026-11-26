import AppKit

/// Deterministic input drives the real upstream physics and renderer, without
/// starting keyboard monitoring or the assistant engine.
enum KuroCatVerification {
    static func run(output: URL) throws {
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        let frame = NSRect(x: 400, y: 200, width: 360, height: 320)
        func input(keys: [PhysicalKey] = [], mouse: CGPoint = CGPoint(x: 580, y: 500),
                   velocity: CGVector = .zero, left: Bool = false, right: Bool = false,
                   lastActivity: Double = 100) -> ScriptedFrameInput {
            ScriptedFrameInput(now: 100, activeKeys: Set(keys), orderedKeys: keys,
                mouseScreenPos: mouse, mouseVelocity: velocity, leftMouseDown: left,
                rightMouseDown: right, lastMouseMoveTime: lastActivity,
                lastMouseClickTime: lastActivity, lastKeyActivityTime: lastActivity)
        }
        func advance(_ cat: KuroCatIntegration, _ value: ScriptedFrameInput, frames: Int = 90) {
            for _ in 0..<frames { cat.physics.step(dt: 1.0 / 60, windowFrameInScreen: frame, scripted: value) }
        }
        func save(_ cat: KuroCatIntegration, _ name: String) throws {
            guard let image = cat.image(), let data = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:]) else { throw CompanionError.unavailable("小黑猫预览无法绘制。") }
            try data.write(to: output.appendingPathComponent(name + ".png"))
        }
        let idle = KuroCatIntegration(); advance(idle, input()); try save(idle, "idle")
        precondition(!CatSettings.shared.flipHorizontal, "Original keyboard and mouse layout must remain unmirrored")
        precondition(PhysicalKey.fromCGKeyCode(0) == .a && PhysicalKey.fromHIDUsage(4) == .a)
        precondition(!PhysicalKey.a.prefersLeftPaw && PhysicalKey.p.prefersLeftPaw)
        precondition(idle.hitZone(.zero, in: frame) == .none)
        let center = KuroCatIntegration.canvasPoint(NSPoint(x: 180, y: 160), in: NSRect(x: 0, y: 0, width: 360, height: 320))
        precondition(abs(center.x - 180) < 0.001 && abs(center.y - 160) < 0.001)
        for side: CGFloat in [79, 158, 395] {
            let window = NSRect(x: -400, y: 200, width: side, height: side)
            let canvas = KuroCatIntegration.screenCanvasFrame(in: window)
            precondition(abs(canvas.midX - window.midX) < 0.001 && abs(canvas.midY - window.midY) < 0.001)
            precondition(abs(canvas.width / canvas.height - 360.0 / 320.0) < 0.001)
        }
        for (name, point, axis, sign) in [
            ("look-left", CGPoint(x: 100, y: 396), "x", -1.0),
            ("look-right", CGPoint(x: 1050, y: 396), "x", 1.0),
            ("look-up", CGPoint(x: 584, y: 950), "y", -1.0),
            ("look-down", CGPoint(x: 584, y: 20), "y", 1.0)
        ] {
            let cat = KuroCatIntegration()
            advance(cat, input(mouse: point))
            let direction = axis == "x" ? cat.physics.headYaw.value : cat.physics.headPitch.value
            precondition(direction * sign > 0.1, "Mouse following reversed: \(name)")
            try save(cat, name)
        }

        let typing = KuroCatIntegration()
        advance(typing, input(keys: [.a, .l], lastActivity: 0))
        precondition(hypot(typing.physics.rightPaw.point.x - idle.physics.rightPaw.point.x, typing.physics.rightPaw.point.y - idle.physics.rightPaw.point.y) > 5)
        try save(typing, "typing")
        advance(typing, input(lastActivity: 0), frames: 180)
        precondition(hypot(typing.physics.rightPaw.point.x - CatPhysics.rightPawRest.x, typing.physics.rightPaw.point.y - CatPhysics.rightPawRest.y) < 3)

        let mouse = KuroCatIntegration()
        mouse.physics.triggerMouseClick(button: 0, isDown: true)
        advance(mouse, input(left: true))
        precondition(mouse.physics.mousePressLeft.value > 0.8)
        try save(mouse, "mouse-click")
        mouse.physics.triggerMouseClick(button: 0, isDown: false)
        advance(mouse, input()); precondition(mouse.physics.mousePressLeft.value < 0.1)

        let hunt = KuroCatIntegration()
        advance(hunt, input(mouse: CGPoint(x: 900, y: 700), velocity: CGVector(dx: 4200, dy: 900)))
        precondition(hunt.physics.huntIntensity.value > 0.4)
        precondition(abs(hunt.physics.headYaw.value) > 0.1)
        try save(hunt, "hunting")

        let combo = KuroCatIntegration()
        advance(combo, input(keys: [.a, .s, .d], lastActivity: 0))
        if CatSettings.shared.footEasterEgg { precondition(combo.physics.hindFootActive.value > 0.5) }
        advance(combo, input(keys: [.a, .s, .d, .f], lastActivity: 0))
        if CatSettings.shared.tailEasterEgg { precondition(combo.physics.tailTyping.value > 0.5) }
        try save(combo, "combo")

        let pet = KuroCatIntegration()
        pet.physics.registerPetStroke(canvasPoint: CGPoint(x: 184, y: 126), delta: 24, isHead: true, at: 100)
        advance(pet, input(), frames: 8)
        if CatSettings.shared.petInteraction { precondition(pet.physics.petHeadIntensity > 0.1) }
        try save(pet, "petting")

        let sleep = KuroCatIntegration(); advance(sleep, input(lastActivity: 1), frames: 240)
        precondition(sleep.physics.sleepiness > 0.8); try save(sleep, "sleeping")
        sleep.physics.triggerKeyDown(.a); precondition(sleep.physics.sleepiness == 0)

        let drag = KuroCatIntegration(); drag.physics.setDragging(true, dragDx: 8, dragDy: -4)
        advance(drag, input())
        if CatSettings.shared.enableDragAnimation { precondition(drag.physics.scruffDrag.value > 0.5) }
        try save(drag, "dragging")
        drag.physics.setDragging(false); advance(drag, input(), frames: 180)
        precondition(drag.physics.scruffDrag.value < 0.1)
        let old = drag.physics.time; drag.paused = true; drag.step(dt: 0.03, frame: frame)
        precondition(drag.physics.time == old)
        print("{\"kurocat_motion\":\"passed\",\"scenarios\":[\"key-mapping\",\"typing-and-release\",\"mouse-click-and-release\",\"head-tracking\",\"hunting\",\"three-key-foot\",\"four-key-tail\",\"petting\",\"sleep-and-wake\",\"drag-and-release\",\"pause\",\"transparent-hit-test\",\"pointer-directions\",\"canvas-coordinate-scaling\"],\"monitor_started\":false,\"assistant_started\":false}")
    }
}
