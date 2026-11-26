import Foundation
import AppKit
import IOKit
import IOKit.hid
import ApplicationServices

enum InputEngineStatus: String {
    case fullHardware = "硬件级全状态监听中 (HID + EventTap)"
    case hidOnly = "硬件 HID 监听中 (游戏/打字全支持)"
    case eventTapOnly = "全局事件监听中 (EventTap)"
    case needsPermission = "需开启「输入监控」以全局监听键盘"
    case needsRestart = "已授权，键盘监听启动失败"

    var needsAttention: Bool {
        self == .needsPermission || self == .needsRestart
    }

    var permissionPillText: String {
        self == .needsRestart ? "监听启动失败，点击重启重试 ↻" : "点击开启全局/游戏键盘监听 🔑"
    }
}

/// Dual-layer full-state keyboard & mouse capture engine for macOS.
/// Layer 1: IOHIDManager (kernel HID — true NKRO, works in games, IME, modifiers, long holds).
/// Layer 2: CGEventTap (.listenOnly — catches trackpad taps, virtual/remapped keys, scroll).
/// Layer 3: Local NSEvent + mouseLocation (always active even before permissions).
final class InputEngine {
    static let shared = InputEngine()

    // Unified active state
    private var hidPressedKeys = Set<PhysicalKey>()
    private var tapPressedKeys = Set<PhysicalKey>()
    private(set) var activeKeys = Set<PhysicalKey>()
    private(set) var pressedOrder: [PhysicalKey] = []

    // Mouse & Graphics Tablet / Stylus state
    private(set) var leftMouseDown = false
    private(set) var rightMouseDown = false
    private(set) var otherMouseDown = false
    private(set) var lastMouseMoveTime: CFTimeInterval = 0
    private(set) var lastMouseClickTime: CFTimeInterval = 0
    private(set) var lastKeyActivityTime: CFTimeInterval = 0
    private(set) var lastMouseLocation: CGPoint = NSEvent.mouseLocation
    private(set) var mouseVelocity: CGVector = .zero
    private(set) var penPressure: CGFloat = 0.0
    private(set) var isPenInProximity = false
    private var tabletHardwareDevices = Set<UInt>()
    private var lastTabletEventTime: CFTimeInterval = 0
    private var lastRegularMouseEventTime: CFTimeInterval = 0
    private var tabletHIDManager: IOHIDManager?

    var isTabletConnected: Bool {
        if !tabletHardwareDevices.isEmpty { return true }
        guard lastTabletEventTime > 0 else { return false }
        let now = CACurrentMediaTime()
        let sincePen = now - lastTabletEventTime
        let timeout: CFTimeInterval = isPenInProximity ? 25.0 : 15.0
        if sincePen >= timeout { return false }
        // If no external tablet hardware is plugged in and regular mouse/trackpad input resumed, fall back cleanly to mouse
        if lastRegularMouseEventTime > lastTabletEventTime + 1.2 { return false }
        return true
    }

    // Stats
    private(set) var totalKeystrokesToday: Int = 0
    private var recentKeyTimes: [CFTimeInterval] = []
    private var statsDayString: String = ""

    // Engine handles
    private var hidManager: IOHIDManager?
    private var eventTap: CFMachPort?
    private var eventTapRunLoopSource: CFRunLoopSource?
    private var localMonitor: Any?
    private var permissionCheckTimer: Timer?
    private var workspaceObservers: [NSObjectProtocol] = []
    private var lastReconcileTime: CFTimeInterval = 0
    private var keyDownTimes: [PhysicalKey: CFTimeInterval] = [:]

    private static let keyToCGCodes: [PhysicalKey: [CGKeyCode]] = {
        var map: [PhysicalKey: [CGKeyCode]] = [:]
        for code: UInt16 in 0..<128 {
            if let key = PhysicalKey.fromCGKeyCode(code) {
                map[key, default: []].append(CGKeyCode(code))
            }
        }
        return map
    }()

    private(set) var isHIDActive = false
    private(set) var isTapActive = false

    // Callbacks
    var onKeyDown: ((PhysicalKey) -> Void)?
    var onKeyUp: ((PhysicalKey) -> Void)?
    var onMouseClick: ((Int, Bool) -> Void)?   // button (0=L,1=R,2=Other), isDown
    var onStatusChanged: ((InputEngineStatus) -> Void)?

    private var lastModifierFlags: CGEventFlags = []

    // The render and hit-test paths read status every frame. Refresh these
    // permissions at startup and in the existing watchdog instead.
    private var inputMonitoringAllowed = false
    private var keyboardMonitoringAllowed = false

    var status: InputEngineStatus {
        guard keyboardMonitoringAllowed else { return .needsPermission }
        if isHIDActive && isTapActive { return .fullHardware }
        if isHIDActive { return .hidOnly }
        if isTapActive { return .eventTapOnly }
        return .needsRestart
    }

    private func refreshPermissions() {
        inputMonitoringAllowed = CGPreflightListenEventAccess()
            || IOHIDCheckAccess(kIOHIDRequestTypeListenEvent) == kIOHIDAccessTypeGranted
        keyboardMonitoringAllowed = inputMonitoringAllowed || AXIsProcessTrusted()
    }

    var currentKPM: Int {
        let now = CACurrentMediaTime()
        let cutoff = now - 10.0
        let count = recentKeyTimes.filter { $0 >= cutoff }.count
        return count * 6
    }

    private init() {
        loadStats()
    }

    func start() {
        startLocalFallbackMonitor()
        startTabletHardwareMonitor()
        refreshPermissions()
        tryStartHID()
        tryStartEventTap()
        notifyStatus()

        let wsCenter = NSWorkspace.shared.notificationCenter
        let resetNames: [NSNotification.Name] = [
            NSWorkspace.willSleepNotification,
            NSWorkspace.screensDidSleepNotification,
            NSWorkspace.sessionDidResignActiveNotification
        ]
        for name in resetNames {
            let obs = wsCenter.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                self?.resetAllKeys()
            }
            workspaceObservers.append(obs)
        }

        // Periodically check if the user just granted Input Monitoring permission
        permissionCheckTimer?.invalidate()
        let timer = Timer(timeInterval: 1.5, repeats: true) { [weak self] _ in
            guard let self else { return }
            let prevStatus = self.status
            self.refreshPermissions()
            if !self.inputMonitoringAllowed && self.isHIDActive {
                self.stopHID()
            }
            if !self.keyboardMonitoringAllowed && self.isTapActive {
                self.stopEventTap()
            }
            if let tap = self.eventTap, !CFMachPortIsValid(tap) {
                self.stopEventTap()
            }
            if !self.isHIDActive && self.inputMonitoringAllowed {
                self.tryStartHID()
            }
            if !self.isTapActive && self.keyboardMonitoringAllowed {
                self.tryStartEventTap()
            } else if self.isTapActive, let tap = self.eventTap, !CGEvent.tapIsEnabled(tap: tap) {
                CGEvent.tapEnable(tap: tap, enable: true)
                if !CGEvent.tapIsEnabled(tap: tap) {
                    self.stopEventTap()
                }
            }
            if self.status != prevStatus {
                self.notifyStatus()
            }
        }
        RunLoop.main.add(timer, forMode: .common)
        permissionCheckTimer = timer
    }

    func stop() {
        permissionCheckTimer?.invalidate()
        permissionCheckTimer = nil
        let wsCenter = NSWorkspace.shared.notificationCenter
        for obs in workspaceObservers {
            wsCenter.removeObserver(obs)
        }
        workspaceObservers.removeAll()
        stopHID()
        stopTabletHardwareMonitor()
        stopEventTap()
        if let m = localMonitor {
            NSEvent.removeMonitor(m)
            localMonitor = nil
        }
    }

    /// Request macOS Input Monitoring permission and open System Settings directly.
    func requestPermissionsAndOpenSettings() {
        CGRequestListenEventAccess()
        IOHIDRequestAccess(kIOHIDRequestTypeListenEvent)
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent") {
            NSWorkspace.shared.open(url)
        }
    }

    func openAccessibilitySettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
            NSWorkspace.shared.open(url)
        }
    }

    /// Called at 60fps from the render loop to sample global cursor motion (requires zero permissions).
    func pollMouse(dt: CGFloat) {
        let loc = NSEvent.mouseLocation
        let dx = loc.x - lastMouseLocation.x
        let dy = loc.y - lastMouseLocation.y
        let dist = hypot(dx, dy)
        if dist > 0.4 {
            lastMouseMoveTime = CACurrentMediaTime()
            if dt > 0.001 {
                mouseVelocity = CGVector(dx: dx / dt, dy: dy / dt)
            }
        } else {
            mouseVelocity = CGVector(dx: mouseVelocity.dx * 0.82, dy: mouseVelocity.dy * 0.82)
        }
        lastMouseLocation = loc

        // Keep KPM sliding window clean
        let now = CACurrentMediaTime()
        if recentKeyTimes.count > 120 {
            recentKeyTimes.removeAll { now - $0 > 12.0 }
        }
        reconcileStuckKeys(now: now)
    }

    private func isKeyPhysicallyDown(_ key: PhysicalKey) -> Bool {
        if key == .fn {
            return CGEventSource.flagsState(.hidSystemState).contains(.maskSecondaryFn)
                && CGEventSource.flagsState(.combinedSessionState).contains(.maskSecondaryFn)
        }
        if key == .capsLock {
            return CGEventSource.keyState(.hidSystemState, key: 57)
                && CGEventSource.keyState(.combinedSessionState, key: 57)
        }
        guard let codes = Self.keyToCGCodes[key] else { return false }
        return codes.contains {
            CGEventSource.keyState(.hidSystemState, key: $0)
                && CGEventSource.keyState(.combinedSessionState, key: $0)
        }
    }

    private func reconcileStuckKeys(now: CFTimeInterval) {
        guard now - lastReconcileTime >= 0.20 else { return }
        lastReconcileTime = now

        // Always keep pressedOrder strictly synced with activeKeys (guards against stopHID/stopEventTap races).
        if pressedOrder.count != activeKeys.count {
            pressedOrder.removeAll { !activeKeys.contains($0) }
        }

        if !activeKeys.isEmpty {
            var stale: [PhysicalKey] = []
            for key in activeKeys {
                let heldFor = now - (keyDownTimes[key] ?? 0)
                // Check per-key (not global lastKeyActivityTime) so a stuck key releases
                // immediately even while the user keeps typing other keys!
                if heldFor > 0.25 && !isKeyPhysicallyDown(key) {
                    stale.append(key)
                }
            }
            if !stale.isEmpty {
                for key in stale {
                    hidPressedKeys.remove(key)
                    tapPressedKeys.remove(key)
                    keyDownTimes.removeValue(forKey: key)
                }
                recomputeUnifiedKeys()
                for key in stale {
                    onKeyUp?(key)
                }
            }
        }

        if (leftMouseDown || rightMouseDown || otherMouseDown) && (now - lastMouseClickTime > 0.35) {
            let buttons = NSEvent.pressedMouseButtons
            if leftMouseDown && (buttons & 1) == 0 { updateMouseButton(0, isDown: false) }
            if rightMouseDown && (buttons & 2) == 0 { updateMouseButton(1, isDown: false) }
            if otherMouseDown && (buttons & ~3) == 0 { updateMouseButton(2, isDown: false) }
        }
    }

    func resetAllKeys() {
        let prev = activeKeys
        hidPressedKeys.removeAll()
        tapPressedKeys.removeAll()
        keyDownTimes.removeAll()
        pressedOrder.removeAll()
        recomputeUnifiedKeys()
        for key in prev {
            onKeyUp?(key)
        }
        if leftMouseDown { updateMouseButton(0, isDown: false) }
        if rightMouseDown { updateMouseButton(1, isDown: false) }
        if otherMouseDown { updateMouseButton(2, isDown: false) }
    }

    // MARK: - Graphics Tablet / Stylus Detection (Strict External USB/BT HID + Verified Pen Events)

    private static let knownTabletVendorIDs: Set<Int> = [
        0x056A, // Wacom
        0x256C, // Huion / Gaomon
        0x28BD, // XP-Pen / UGEE / Xencelabs
        0x5543, // UC-Logic / UGEE
        0x2FEB, // Veikk
        0x2179, // Hanvon
        0x33F8, // Xencelabs
        0x2FBB  // Parblo
    ]

    private func isDrawingTabletDevice(_ device: IOHIDDevice) -> Bool {
        let vid = (IOHIDDeviceGetProperty(device, kIOHIDVendorIDKey as CFString) as? NSNumber)?.intValue ?? 0
        let usagePage = (IOHIDDeviceGetProperty(device, kIOHIDPrimaryUsagePageKey as CFString) as? NSNumber)?.intValue ?? 0
        let usage = (IOHIDDeviceGetProperty(device, kIOHIDPrimaryUsageKey as CFString) as? NSNumber)?.intValue ?? 0
        let builtIn = (IOHIDDeviceGetProperty(device, kIOHIDBuiltInKey as CFString) as? NSNumber)?.boolValue ?? false
        let transport = (IOHIDDeviceGetProperty(device, kIOHIDTransportKey as CFString) as? String ?? "").lowercased()
        let product = (IOHIDDeviceGetProperty(device, kIOHIDProductKey as CFString) as? String ?? "").lowercased()

        // 1. Reject built-in laptop hardware, Apple trackpads/mice (USB 0x05AC & Bluetooth 0x004C), and virtual/residual driver stubs
        if builtIn || vid == 0x05AC || vid == 0x004C || vid == 0x1B96 { return false }
        let isPhysicalExternal = transport == "usb" || transport == "bluetooth" || transport == "bluetoothlowenergy"
        if !isPhysicalExternal { return false }

        // 2. Reject touchpads, touchscreens, virtual displays, remotes, and plain mice/keyboards by product name
        let excludedKeywords = ["touchpad", "trackpad", "touchscreen", "touch screen", "virtual", "sidecar", "remote", "mouse", "keyboard"]
        for kw in excludedKeywords where product.contains(kw) { return false }

        // 3. Dedicated graphics tablet vendors: must expose a Digitizer (0x0D) or vendor-specific (>= 0xFF00) tablet interface
        if Self.knownTabletVendorIDs.contains(vid) {
            return usagePage == kHIDPage_Digitizer || usagePage >= 0xFF00
        }

        // 4. Other USB/BT vendors: require EXPLICIT Pen usage (0x02) — never generic Digitizer (0x01) / TouchScreen (0x04) / TouchPad (0x05)
        return usagePage == kHIDPage_Digitizer && usage == kHIDUsage_Dig_Pen
    }

    private func startTabletHardwareMonitor() {
        guard tabletHIDManager == nil else { return }
        let manager = IOHIDManagerCreate(kCFAllocatorDefault, IOOptionBits(kIOHIDOptionsTypeNone))
        var matches: [[String: Any]] = [
            [
                kIOHIDDeviceUsagePageKey as String: kHIDPage_Digitizer,
                kIOHIDDeviceUsageKey as String: kHIDUsage_Dig_Pen
            ]
        ]
        for vid in Self.knownTabletVendorIDs {
            matches.append([kIOHIDVendorIDKey as String: vid])
        }
        IOHIDManagerSetDeviceMatchingMultiple(manager, matches as CFArray)
        let context = Unmanaged.passUnretained(self).toOpaque()
        IOHIDManagerRegisterDeviceMatchingCallback(manager, { ctx, _, _, device in
            guard let ctx else { return }
            let engine = Unmanaged<InputEngine>.fromOpaque(ctx).takeUnretainedValue()
            if engine.isDrawingTabletDevice(device) {
                engine.tabletHardwareDevices.insert(UInt(bitPattern: Unmanaged.passUnretained(device).toOpaque()))
            }
        }, context)
        IOHIDManagerRegisterDeviceRemovalCallback(manager, { ctx, _, _, device in
            guard let ctx else { return }
            let engine = Unmanaged<InputEngine>.fromOpaque(ctx).takeUnretainedValue()
            engine.tabletHardwareDevices.remove(UInt(bitPattern: Unmanaged.passUnretained(device).toOpaque()))
        }, context)
        IOHIDManagerScheduleWithRunLoop(manager, CFRunLoopGetMain(), CFRunLoopMode.commonModes.rawValue)
        let res = IOHIDManagerOpen(manager, IOOptionBits(kIOHIDOptionsTypeNone))
        if res == kIOReturnSuccess {
            tabletHIDManager = manager
            if let set = IOHIDManagerCopyDevices(manager) as? Set<IOHIDDevice> {
                for dev in set where isDrawingTabletDevice(dev) {
                    tabletHardwareDevices.insert(UInt(bitPattern: Unmanaged.passUnretained(dev).toOpaque()))
                }
            }
        } else {
            IOHIDManagerUnscheduleFromRunLoop(manager, CFRunLoopGetMain(), CFRunLoopMode.commonModes.rawValue)
        }
    }

    private func stopTabletHardwareMonitor() {
        if let manager = tabletHIDManager {
            IOHIDManagerUnscheduleFromRunLoop(manager, CFRunLoopGetMain(), CFRunLoopMode.commonModes.rawValue)
            IOHIDManagerClose(manager, IOOptionBits(kIOHIDOptionsTypeNone))
            tabletHIDManager = nil
        }
        tabletHardwareDevices.removeAll()
    }

    private func checkTabletEvent(_ event: CGEvent) {
        let now = CACurrentMediaTime()
        let subtype = event.getIntegerValueField(.mouseEventSubtype)
        if subtype == 2 {
            // TabletProximity: only accept real Pen (1) or Eraser (3) entering proximity
            let entering = event.getIntegerValueField(.tabletProximityEventEnterProximity) != 0
            let devType = event.getIntegerValueField(.tabletProximityEventPointerType)
            if devType == 1 || devType == 3 {
                isPenInProximity = entering
                if entering {
                    lastTabletEventTime = now
                } else {
                    penPressure = 0.0
                }
            }
        } else if subtype == 1 {
            // TabletPoint: require confirmed pen proximity, real tablet deviceID, or non-zero pen pressure
            let devId = event.getIntegerValueField(.tabletEventDeviceID)
            let p = CGFloat(event.getDoubleValueField(.tabletEventPointPressure))
            if isPenInProximity || devId != 0 || p > 0.001 {
                lastTabletEventTime = now
                isPenInProximity = true
                if p > 0.001 { penPressure = p }
            }
        } else {
            // Regular mouse / trackpad event
            lastRegularMouseEventTime = now
            if tabletHardwareDevices.isEmpty {
                isPenInProximity = false
            }
        }
    }

    // MARK: - Layer 1: IOHIDManager (Raw Kernel HID — Best for Games + IME)

    private func tryStartHID() {
        guard !isHIDActive else { return }
        guard inputMonitoringAllowed else { return }

        let manager = IOHIDManagerCreate(kCFAllocatorDefault, IOOptionBits(kIOHIDOptionsTypeNone))

        let matches: [[String: Any]] = [
            [
                kIOHIDDeviceUsagePageKey as String: kHIDPage_GenericDesktop,
                kIOHIDDeviceUsageKey as String: kHIDUsage_GD_Keyboard
            ],
            [
                kIOHIDDeviceUsagePageKey as String: kHIDPage_GenericDesktop,
                kIOHIDDeviceUsageKey as String: kHIDUsage_GD_Keypad
            ],
            [
                kIOHIDDeviceUsagePageKey as String: kHIDPage_GenericDesktop,
                kIOHIDDeviceUsageKey as String: kHIDUsage_GD_Mouse
            ]
        ]

        IOHIDManagerSetDeviceMatchingMultiple(manager, matches as CFArray)

        let context = Unmanaged.passUnretained(self).toOpaque()
        IOHIDManagerRegisterInputValueCallback(manager, { ctx, _, _, value in
            guard let ctx else { return }
            let engine = Unmanaged<InputEngine>.fromOpaque(ctx).takeUnretainedValue()
            engine.handleHIDValue(value)
        }, context)

        IOHIDManagerScheduleWithRunLoop(manager, CFRunLoopGetMain(), CFRunLoopMode.commonModes.rawValue)
        let openResult = IOHIDManagerOpen(manager, IOOptionBits(kIOHIDOptionsTypeNone))
        if openResult == kIOReturnSuccess {
            self.hidManager = manager
            self.isHIDActive = true
        } else {
            IOHIDManagerUnscheduleFromRunLoop(manager, CFRunLoopGetMain(), CFRunLoopMode.commonModes.rawValue)
            self.isHIDActive = false
        }
    }

    private func stopHID() {
        if let manager = hidManager {
            IOHIDManagerUnscheduleFromRunLoop(manager, CFRunLoopGetMain(), CFRunLoopMode.commonModes.rawValue)
            IOHIDManagerClose(manager, IOOptionBits(kIOHIDOptionsTypeNone))
            hidManager = nil
        }
        isHIDActive = false
        hidPressedKeys.removeAll()
        recomputeUnifiedKeys()
    }

    private func handleHIDValue(_ value: IOHIDValue) {
        let element = IOHIDValueGetElement(value)
        let usagePage = IOHIDElementGetUsagePage(element)
        let usage = IOHIDElementGetUsage(element)
        let intVal = IOHIDValueGetIntegerValue(value)

        // Standard Keyboard / Keypad page (0x07)
        if usagePage == UInt32(kHIDPage_KeyboardOrKeypad) {
            // Filter out HID error/rollover pseudo-usages (0x00..0x03)
            guard usage >= 0x04 else { return }
            if let key = PhysicalKey.fromHIDUsage(usage) {
                setKeyState(key, isDown: intVal != 0, fromHID: true)
            }
            return
        }

        // Apple Built-in / Magic Keyboard Fn key (Apple Vendor Top Case page 0xFF, usage 0x03)
        if usagePage == 0xFF && usage == 0x03 {
            setKeyState(.fn, isDown: intVal != 0, fromHID: true)
            return
        }

        // Mouse buttons (Page 0x09)
        if usagePage == UInt32(kHIDPage_Button) {
            let isDown = intVal != 0
            if usage == 1 {
                updateMouseButton(0, isDown: isDown)
            } else if usage == 2 {
                updateMouseButton(1, isDown: isDown)
            } else if usage >= 3 && usage <= 8 {
                updateMouseButton(2, isDown: isDown)
            }
        }
    }

    // MARK: - Layer 2: CGEventTap (Listen-Only Companion for Trackpad, Virtual Keys & Scroll)

    private func tryStartEventTap() {
        guard !isTapActive else { return }
        // Only activate keyboard EventTap when macOS actually granted Input Monitoring or Accessibility;
        // otherwise listenOnly tap silently drops keyboard events while returning non-nil!
        guard keyboardMonitoringAllowed else { return }

        var mask: CGEventMask = 0
        let types: [CGEventType] = [
            .keyDown, .keyUp, .flagsChanged,
            .leftMouseDown, .leftMouseUp, .leftMouseDragged,
            .rightMouseDown, .rightMouseUp,
            .otherMouseDown, .otherMouseUp,
            .scrollWheel,
            .tabletPointer, .tabletProximity
        ]
        for t in types {
            mask |= (1 << t.rawValue)
        }

        let context = Unmanaged.passUnretained(self).toOpaque()
        guard let tap = CGEvent.tapCreate(
            tap: .cgSessionEventTap,
            place: .headInsertEventTap,
            options: .listenOnly,
            eventsOfInterest: mask,
            callback: { _, type, event, ctx in
                guard let ctx else { return Unmanaged.passUnretained(event) }
                let engine = Unmanaged<InputEngine>.fromOpaque(ctx).takeUnretainedValue()
                engine.handleCGEvent(type: type, event: event)
                return Unmanaged.passUnretained(event)
            },
            userInfo: context
        ) else {
            isTapActive = false
            return
        }

        let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetMain(), source, .commonModes)
        CGEvent.tapEnable(tap: tap, enable: true)

        self.eventTap = tap
        self.eventTapRunLoopSource = source
        self.isTapActive = true
    }

    private func stopEventTap() {
        if let tap = eventTap {
            CGEvent.tapEnable(tap: tap, enable: false)
        }
        if let source = eventTapRunLoopSource {
            CFRunLoopRemoveSource(CFRunLoopGetMain(), source, .commonModes)
        }
        if let tap = eventTap {
            CFMachPortInvalidate(tap)
        }
        eventTap = nil
        eventTapRunLoopSource = nil
        isTapActive = false
        tapPressedKeys.removeAll()
        recomputeUnifiedKeys()
    }

    private func handleCGEvent(type: CGEventType, event: CGEvent) {
        if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
            if let tap = eventTap {
                CGEvent.tapEnable(tap: tap, enable: true)
            }
            return
        }

        switch type {
        case .keyDown:
            // Ignore OS auto-repeat events so holding W in a game doesn't spam floating keycaps!
            let isRepeat = event.getIntegerValueField(.keyboardEventAutorepeat) != 0
            let keyCode = UInt16(event.getIntegerValueField(.keyboardEventKeycode))
            if let key = PhysicalKey.fromCGKeyCode(keyCode), !isRepeat {
                // On macOS (especially 13.x Chinese IME / auto-pairing editors), typing `(` or `（`
                // injects synthetic CGEvent keyDowns (e.g. `)`, `9`, `0`, Left Arrow) with NO keyUp.
                // When kernel HID is active and the key isn't physically down, treat it as a brief tap
                // instead of holding it in tapPressedKeys so the right paw never gets glued to the keyboard!
                if isHIDActive && !hidPressedKeys.contains(key) && !isKeyPhysicallyDown(key) {
                    setKeyState(key, isDown: true, fromHID: false)
                    setKeyState(key, isDown: false, fromHID: false)
                } else {
                    setKeyState(key, isDown: true, fromHID: false)
                }
            }
        case .keyUp:
            let keyCode = UInt16(event.getIntegerValueField(.keyboardEventKeycode))
            if let key = PhysicalKey.fromCGKeyCode(keyCode) {
                setKeyState(key, isDown: false, fromHID: false)
            }
        case .flagsChanged:
            let keyCode = UInt16(event.getIntegerValueField(.keyboardEventKeycode))
            let flags = event.flags
            if let key = PhysicalKey.fromCGKeyCode(keyCode) {
                if key == .capsLock {
                    // CapsLock's .maskAlphaShift is a lock toggle, not a physical hold.
                    // When HID is active it tracks exact physical press/release; otherwise
                    // treat flagsChanged as a brief tap so the paw never sticks on CapsLock.
                    if !isHIDActive {
                        setKeyState(.capsLock, isDown: true, fromHID: false)
                        setKeyState(.capsLock, isDown: false, fromHID: false)
                    }
                } else {
                    let isDown = isModifierKeyDown(key: key, flags: flags)
                    setKeyState(key, isDown: isDown, fromHID: false)
                }
            }
            // If all Shift/Control/Option/Command flags cleared, ensure neither side lingers in tapPressedKeys.
            if !flags.contains(.maskShift) {
                if tapPressedKeys.contains(.leftShift) { setKeyState(.leftShift, isDown: false, fromHID: false) }
                if tapPressedKeys.contains(.rightShift) { setKeyState(.rightShift, isDown: false, fromHID: false) }
            }
            if !flags.contains(.maskControl) {
                if tapPressedKeys.contains(.leftControl) { setKeyState(.leftControl, isDown: false, fromHID: false) }
                if tapPressedKeys.contains(.rightControl) { setKeyState(.rightControl, isDown: false, fromHID: false) }
            }
            if !flags.contains(.maskAlternate) {
                if tapPressedKeys.contains(.leftOption) { setKeyState(.leftOption, isDown: false, fromHID: false) }
                if tapPressedKeys.contains(.rightOption) { setKeyState(.rightOption, isDown: false, fromHID: false) }
            }
            if !flags.contains(.maskCommand) {
                if tapPressedKeys.contains(.leftCommand) { setKeyState(.leftCommand, isDown: false, fromHID: false) }
                if tapPressedKeys.contains(.rightCommand) { setKeyState(.rightCommand, isDown: false, fromHID: false) }
            }
            lastModifierFlags = flags
        case .leftMouseDown:
            checkTabletEvent(event)
            updateMouseButton(0, isDown: true)
        case .leftMouseUp:
            checkTabletEvent(event)
            penPressure = 0.0
            updateMouseButton(0, isDown: false)
        case .leftMouseDragged:
            checkTabletEvent(event)
            lastMouseMoveTime = CACurrentMediaTime()
        case .tabletPointer:
            let devId = event.getIntegerValueField(.tabletEventDeviceID)
            let p = CGFloat(event.getDoubleValueField(.tabletEventPointPressure))
            if isPenInProximity || devId != 0 || p > 0.001 {
                lastTabletEventTime = CACurrentMediaTime()
                isPenInProximity = true
                penPressure = p
                lastMouseMoveTime = CACurrentMediaTime()
            }
        case .tabletProximity:
            let entering = event.getIntegerValueField(.tabletProximityEventEnterProximity) != 0
            let devType = event.getIntegerValueField(.tabletProximityEventPointerType)
            if devType == 1 || devType == 3 {
                isPenInProximity = entering
                if entering {
                    lastTabletEventTime = CACurrentMediaTime()
                } else {
                    penPressure = 0.0
                }
            }
        case .rightMouseDown:
            checkTabletEvent(event)
            updateMouseButton(1, isDown: true)
        case .rightMouseUp:
            checkTabletEvent(event)
            updateMouseButton(1, isDown: false)
        case .otherMouseDown:
            updateMouseButton(2, isDown: true)
        case .otherMouseUp:
            updateMouseButton(2, isDown: false)
        case .scrollWheel:
            lastMouseMoveTime = CACurrentMediaTime()
        default:
            break
        }
    }

    private func isModifierKeyDown(key: PhysicalKey, flags: CGEventFlags) -> Bool {
        let raw = flags.rawValue
        switch key {
        case .leftShift:
            if !flags.contains(.maskShift) { return false }
            return (raw & 0x0006) != 0 ? (raw & 0x0002) != 0 : true
        case .rightShift:
            if !flags.contains(.maskShift) { return false }
            return (raw & 0x0006) != 0 ? (raw & 0x0004) != 0 : true
        case .leftControl:
            if !flags.contains(.maskControl) { return false }
            return (raw & 0x2001) != 0 ? (raw & 0x0001) != 0 : true
        case .rightControl:
            if !flags.contains(.maskControl) { return false }
            return (raw & 0x2001) != 0 ? (raw & 0x2000) != 0 : true
        case .leftOption:
            if !flags.contains(.maskAlternate) { return false }
            return (raw & 0x0060) != 0 ? (raw & 0x0020) != 0 : true
        case .rightOption:
            if !flags.contains(.maskAlternate) { return false }
            return (raw & 0x0060) != 0 ? (raw & 0x0040) != 0 : true
        case .leftCommand:
            if !flags.contains(.maskCommand) { return false }
            return (raw & 0x0018) != 0 ? (raw & 0x0008) != 0 : true
        case .rightCommand:
            if !flags.contains(.maskCommand) { return false }
            return (raw & 0x0018) != 0 ? (raw & 0x0010) != 0 : true
        case .capsLock: return flags.contains(.maskAlphaShift)
        case .fn: return flags.contains(.maskSecondaryFn)
        default: return false
        }
    }

    // MARK: - Layer 3: Local Window Monitor (Immediate testing before permissions)

    private func startLocalFallbackMonitor() {
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .keyUp, .flagsChanged]) { [weak self] event in
            guard let self else { return event }
            if !self.isHIDActive && !self.isTapActive {
                if event.type == .keyDown && !event.isARepeat {
                    if let key = PhysicalKey.fromCGKeyCode(event.keyCode) {
                        self.setKeyState(key, isDown: true, fromHID: false)
                    }
                } else if event.type == .keyUp {
                    if let key = PhysicalKey.fromCGKeyCode(event.keyCode) {
                        self.setKeyState(key, isDown: false, fromHID: false)
                    }
                } else if event.type == .flagsChanged {
                    if let key = PhysicalKey.fromCGKeyCode(event.keyCode) {
                        let cgFlags = CGEventFlags(rawValue: UInt64(event.modifierFlags.rawValue))
                        self.setKeyState(key, isDown: self.isModifierKeyDown(key: key, flags: cgFlags), fromHID: false)
                    }
                }
            }
            return event
        }
    }

    // MARK: - Unified Deduplicated State

    private func setKeyState(_ key: PhysicalKey, isDown: Bool, fromHID: Bool) {
        let wasActive = activeKeys.contains(key)

        if fromHID {
            if isDown {
                hidPressedKeys.insert(key)
            } else {
                hidPressedKeys.remove(key)
                // If HID explicitly says the physical key was released, clear any lingering tap state too
                tapPressedKeys.remove(key)
            }
        } else {
            if isDown {
                tapPressedKeys.insert(key)
            } else {
                tapPressedKeys.remove(key)
                if !isHIDActive || !isKeyPhysicallyDown(key) {
                    hidPressedKeys.remove(key)
                }
            }
        }

        recomputeUnifiedKeys()
        let isNowActive = activeKeys.contains(key)

        if !wasActive && isNowActive {
            let now = CACurrentMediaTime()
            lastKeyActivityTime = now
            keyDownTimes[key] = now
            recentKeyTimes.append(now)
            incrementTodayStats()
            pressedOrder.removeAll { $0 == key }
            pressedOrder.append(key)
            onKeyDown?(key)
        } else if wasActive && !isNowActive {
            keyDownTimes.removeValue(forKey: key)
            pressedOrder.removeAll { $0 == key }
            onKeyUp?(key)
        }
    }

    private func recomputeUnifiedKeys() {
        activeKeys = hidPressedKeys.union(tapPressedKeys)
        pressedOrder.removeAll { !activeKeys.contains($0) }
        for k in keyDownTimes.keys where !activeKeys.contains(k) {
            keyDownTimes.removeValue(forKey: k)
        }
    }

    private func updateMouseButton(_ button: Int, isDown: Bool) {
        let prev: Bool
        switch button {
        case 0:
            prev = leftMouseDown
            leftMouseDown = isDown
        case 1:
            prev = rightMouseDown
            rightMouseDown = isDown
        default:
            prev = otherMouseDown
            otherMouseDown = isDown
        }
        if prev != isDown {
            let now = CACurrentMediaTime()
            lastMouseMoveTime = now
            if isDown { lastMouseClickTime = now }
            onMouseClick?(button, isDown)
        }
    }

    private func notifyStatus() {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.onStatusChanged?(self.status)
        }
    }

    // MARK: - Daily Stats Persistence

    private func todayString() -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: Date())
    }

    private func loadStats() {
        let today = todayString()
        statsDayString = today
        let savedDay = UserDefaults.standard.string(forKey: "KuroCat.StatsDay") ?? ""
        if savedDay == today {
            totalKeystrokesToday = UserDefaults.standard.integer(forKey: "KuroCat.TodayKeys")
        } else {
            totalKeystrokesToday = 0
            UserDefaults.standard.set(today, forKey: "KuroCat.StatsDay")
            UserDefaults.standard.set(0, forKey: "KuroCat.TodayKeys")
        }
    }

    private func incrementTodayStats() {
        let today = todayString()
        if today != statsDayString {
            statsDayString = today
            totalKeystrokesToday = 0
            UserDefaults.standard.set(today, forKey: "KuroCat.StatsDay")
        }
        totalKeystrokesToday += 1
        if totalKeystrokesToday % 10 == 0 {
            UserDefaults.standard.set(totalKeystrokesToday, forKey: "KuroCat.TodayKeys")
        }
    }

    func flushStats() {
        UserDefaults.standard.set(statsDayString, forKey: "KuroCat.StatsDay")
        UserDefaults.standard.set(totalKeystrokesToday, forKey: "KuroCat.TodayKeys")
        UserDefaults.standard.synchronize()
    }
}
