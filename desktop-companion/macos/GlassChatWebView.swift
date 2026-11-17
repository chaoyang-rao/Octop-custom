import AppKit
import WebKit

final class GlassChatWebView: WKWebView {
    override var isOpaque: Bool { false }
}

final class ChatWindowContentView: NSView {
    init(content: NSView) {
        super.init(frame: content.frame)
        content.frame = bounds
        content.autoresizingMask = [.width, .height]
        addSubview(content)
        // Match the web topbar (34pt top inset + 38pt button + 12pt bottom).
        // Leave the trailing settings button and its padding to WebKit.
        let handle = ChatWindowDragHandle(frame: NSRect(x: 0, y: bounds.height - 84, width: max(0, bounds.width - 70), height: 84))
        handle.autoresizingMask = [.width, .minYMargin]
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
