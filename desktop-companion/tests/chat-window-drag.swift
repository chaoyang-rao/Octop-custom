import AppKit
import WebKit

@main
struct ChatWindowDragCheck {
    @MainActor static func main() {
        _ = NSApplication.shared
        precondition(CompanionWindowLevels.pet.rawValue > CompanionWindowLevels.chat.rawValue,
                     "The pet must stay above the chat without moving the chat away")
        for width in [350.0, 456.0, 800.0] {
            let web = GlassChatWebView(frame: NSRect(x: 0, y: 0, width: width, height: 684))
            let container = ChatWindowContentView(content:web)
            func point(_ x: Double, _ fromTop: Double) -> NSPoint {
                NSPoint(x: x, y: container.bounds.height - fromTop)
            }
            precondition(container.hitTest(point(140, 18)) is ChatWindowDragHandle,
                         "Title must receive native window dragging")
            precondition(!(container.hitTest(point(width - 22, 18)) is ChatWindowDragHandle), "Settings must remain a WebKit control")
            precondition(!(container.hitTest(point(20, 18)) is ChatWindowDragHandle), "Native traffic lights must remain clickable")
            precondition(!(container.hitTest(point(140, 200)) is ChatWindowDragHandle), "Messages must retain selection and scrolling")
            precondition(!(container.hitTest(point(140, 600)) is ChatWindowDragHandle), "Composer must retain normal editing")
            precondition(container.hitTest(point(-1, 18)) == nil, "Outside points must not initiate window dragging")
            container.setFrameSize(NSSize(width:width + 100,height:784))
            precondition(container.hitTest(NSPoint(x:140,y:766)) is ChatWindowDragHandle, "Drag region must follow window resizing")
            precondition(!(container.hitTest(NSPoint(x:width + 78,y:766)) is ChatWindowDragHandle), "Resized settings button must remain clickable")
            let window = NSWindow(contentRect:NSRect(x:300,y:300,width:width + 100,height:784),styleMask:[.titled,.fullSizeContentView],backing:.buffered,defer:false)
            window.contentView = container
            let handle = container.hitTest(NSPoint(x:140,y:766)) as! ChatWindowDragHandle
            func event(_ type: NSEvent.EventType, _ point: NSPoint) -> NSEvent {
                NSEvent.mouseEvent(with:type,location:point,modifierFlags:[],timestamp:0,windowNumber:window.windowNumber,context:nil,eventNumber:0,clickCount:1,pressure:1)!
            }
            let before = window.frame
            handle.mouseDown(with:event(.leftMouseDown,NSPoint(x:140,y:766)))
            handle.mouseDragged(with:event(.leftMouseDragged,NSPoint(x:70,y:746)))
            precondition(abs(window.frame.minX - before.minX + 70) < 0.001 && abs(window.frame.minY - before.minY + 20) < 0.001,
                         "Title dragging must move the window by the pointer delta")
            precondition(window.frame.size == before.size, "Dragging must not resize the chat")
            handle.mouseUp(with:event(.leftMouseUp,NSPoint(x:140,y:766)))
            let released = window.frame
            handle.mouseDragged(with:event(.leftMouseDragged,NSPoint(x:20,y:614)))
            precondition(window.frame == released, "Released mouse must stop moving the window")
        }
        print("chat_title_drag_routing_and_web_controls=passed")
    }
}
