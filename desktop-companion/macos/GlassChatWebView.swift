import AppKit
import WebKit

enum CompanionWindowLevels {
    static let chat = NSWindow.Level.floating
    static let pet = NSWindow.Level(rawValue: chat.rawValue + 1)
}

final class GlassChatWebView: WKWebView {
    override var isOpaque: Bool { false }
}

final class ChatWindowContentView: NSView {
    init(content: NSView) {
        super.init(frame: content.frame)
        content.frame = bounds
        content.autoresizingMask = [.width, .height]
        addSubview(content)
        // Only the brand drags. The expert picker starts at x=166 in styles.css.
        let handle = ChatWindowDragHandle(frame: NSRect(x: 80, y: bounds.height - 36, width: 86, height: 36))
        handle.autoresizingMask = [.minYMargin]
        addSubview(handle)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
}

final class ChatWindowDragHandle: NSView {
    private var grabPoint: NSPoint?
    override var mouseDownCanMoveWindow: Bool { false }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override func mouseDown(with event: NSEvent) {
        grabPoint = event.locationInWindow
    }
    override func mouseDragged(with event: NSEvent) {
        guard let window, let grabPoint else { return }
        let pointer = window.convertPoint(toScreen:event.locationInWindow)
        window.setFrameOrigin(NSPoint(x:pointer.x - grabPoint.x,y:pointer.y - grabPoint.y))
    }
    override func mouseUp(with event: NSEvent) {
        grabPoint = nil
    }
}
