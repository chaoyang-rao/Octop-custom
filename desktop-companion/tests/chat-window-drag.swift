import AppKit
import WebKit

@main
struct ChatWindowDragCheck {
    @MainActor static func main() {
        _ = NSApplication.shared
        for width in [350.0, 456.0, 800.0] {
            let web = GlassChatWebView(frame: NSRect(x: 0, y: 0, width: width, height: 684))
            let container = ChatWindowContentView(content:web)
            func point(_ x: Double, _ fromTop: Double) -> NSPoint {
                NSPoint(x: x, y: container.bounds.height - fromTop)
            }
            precondition(container.hitTest(point(140, 50)) is ChatWindowDragHandle,
                         "Title must receive native window dragging")
            precondition(!(container.hitTest(point(width - 37, 50)) is ChatWindowDragHandle), "Settings must remain a WebKit control")
            precondition(!(container.hitTest(point(140, 200)) is ChatWindowDragHandle), "Messages must retain selection and scrolling")
            precondition(!(container.hitTest(point(140, 600)) is ChatWindowDragHandle), "Composer must retain normal editing")
            precondition(container.hitTest(point(-1, 50)) == nil, "Outside points must not initiate window dragging")
            container.setFrameSize(NSSize(width:width + 100,height:784))
            precondition(container.hitTest(NSPoint(x:140,y:734)) is ChatWindowDragHandle, "Drag region must follow window resizing")
            precondition(!(container.hitTest(NSPoint(x:width + 63,y:734)) is ChatWindowDragHandle), "Resized settings button must remain clickable")
            let window = NSWindow(contentRect:NSRect(x:300,y:300,width:width + 100,height:784),styleMask:[.titled,.fullSizeContentView],backing:.buffered,defer:false)
            window.contentView = container
            let handle = container.hitTest(NSPoint(x:140,y:734)) as! ChatWindowDragHandle
            func event(_ type: NSEvent.EventType, _ point: NSPoint) -> NSEvent {
                NSEvent.mouseEvent(with:type,location:point,modifierFlags:[],timestamp:0,windowNumber:window.windowNumber,context:nil,eventNumber:0,clickCount:1,pressure:1)!
            }
            let before = window.frame
            handle.mouseDown(with:event(.leftMouseDown,NSPoint(x:140,y:734)))
            handle.mouseDragged(with:event(.leftMouseDragged,NSPoint(x:70,y:714)))
            precondition(abs(window.frame.minX - before.minX + 70) < 0.001 && abs(window.frame.minY - before.minY + 20) < 0.001,
                         "Title dragging must move the window by the pointer delta")
            precondition(window.frame.size == before.size, "Dragging must not resize the chat")
            handle.mouseUp(with:event(.leftMouseUp,NSPoint(x:140,y:734)))
            let released = window.frame
            handle.mouseDragged(with:event(.leftMouseDragged,NSPoint(x:20,y:614)))
            precondition(window.frame == released, "Released mouse must stop moving the window")
        }
        print("chat_title_drag_routing_and_web_controls=passed")
    }
}
