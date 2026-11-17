import AppKit

enum PetSpriteDrawing {
    static func headTransform(appearance: PetPeek, edge: PetEdgeDocking.Edge, in rect: NSRect) -> NSAffineTransform {
        let crop = appearance.normalizedCrop!
        let pivot = appearance.pivot?.count == 2 ? appearance.pivot! : [crop.midX,crop.midY]
        let x = rect.minX+(pivot[0]-crop.minX)/crop.width*rect.width
        let y = rect.minY+(crop.maxY-pivot[1])/crop.height*rect.height
        let offset = rect.width*appearance.headWidth/crop.width*(appearance.retraction ?? 0)
        let side = edge == .left || edge == .right
        let transform = NSAffineTransform()
        transform.translateX(by:x+(side ? offset : 0),yBy:y+(side ? 0 : -offset))
        transform.rotate(byDegrees:appearance.rotation ?? 0)
        transform.translateX(by:-x,yBy:-y)
        return transform
    }
    static func drawPeek(_ image: NSImage, appearance: PetPeek, edge: PetEdgeDocking.Edge, in rect: NSRect) {
        guard let crop = appearance.normalizedCrop else { return }
        let source = NSRect(x: image.size.width*crop.minX, y: image.size.height*(1-crop.maxY), width: image.size.width*crop.width, height: image.size.height*crop.height)
        NSGraphicsContext.saveGraphicsState()
        let transform = NSAffineTransform()
        transform.translateX(by: rect.midX, yBy: rect.midY)
        transform.scaleX(by: edge == .left || edge == .top ? -1 : 1, yBy: edge == .top ? -1 : 1)
        transform.translateX(by: -rect.midX, yBy: -rect.midY)
        transform.concat()
        let separateHands = (appearance.retraction ?? 0) > 0 || (appearance.rotation ?? 0) != 0
        NSGraphicsContext.saveGraphicsState()
        headTransform(appearance:appearance,edge:edge,in:rect).concat()
        if separateHands {
            let mask = NSBezierPath(rect:rect); mask.windingRule = .evenOdd
            for hand in appearance.hands {
                mask.appendOval(in:NSRect(x:rect.minX+(hand.minX-crop.minX)/crop.width*rect.width,
                    y:rect.minY+(crop.maxY-hand.maxY)/crop.height*rect.height,
                    width:hand.width/crop.width*rect.width,height:hand.height/crop.height*rect.height))
            }
            mask.addClip()
        }
        image.draw(in:rect,from:source,operation:.sourceOver,fraction:1,respectFlipped:true,hints:[.interpolation:NSImageInterpolation.high])
        NSGraphicsContext.restoreGraphicsState()
        if separateHands {
            for hand in appearance.hands {
                let target = NSRect(x:rect.minX+(hand.minX-crop.minX)/crop.width*rect.width,
                                    y:rect.minY+(crop.maxY-hand.maxY)/crop.height*rect.height,
                                    width:hand.width/crop.width*rect.width,height:hand.height/crop.height*rect.height)
                let pixels = NSRect(x:hand.minX*image.size.width,y:(1-hand.maxY)*image.size.height,width:hand.width*image.size.width,height:hand.height*image.size.height)
                NSGraphicsContext.saveGraphicsState(); NSBezierPath(ovalIn:target).addClip()
                image.draw(in:target,from:pixels,operation:.sourceOver,fraction:1,respectFlipped:true,hints:[.interpolation:NSImageInterpolation.high])
                NSGraphicsContext.restoreGraphicsState()
            }
        }
        NSGraphicsContext.restoreGraphicsState()
    }
    // Overlay coordinates are normalized from the sprite's top-left corner.
    static func patchRect(_ animation: PetAnimation, in rect: NSRect) -> NSRect? {
        guard animation.baseFrame != nil, let patch = animation.overlayRect,
              patch.count == 4, patch.allSatisfy({ $0.isFinite && $0 >= 0 }),
              patch[2] > 0, patch[3] > 0,
              patch[0] + patch[2] <= 1, patch[1] + patch[3] <= 1 else { return nil }
        return NSRect(x: rect.minX + rect.width * patch[0],
                      y: rect.minY + rect.height * (1 - patch[1] - patch[3]),
                      width: rect.width * patch[2], height: rect.height * patch[3])
    }

    static func draw(_ animation: PetAnimation, frame: String, images: [String: NSImage], in rect: NSRect, mirrorAboutX: CGFloat? = nil) {
        NSGraphicsContext.saveGraphicsState()
        defer { NSGraphicsContext.restoreGraphicsState() }
        if let pivot = mirrorAboutX {
            let transform = NSAffineTransform(); transform.translateX(by:pivot,yBy:0); transform.scaleX(by:-1,yBy:1); transform.translateX(by:-pivot,yBy:0); transform.concat()
        }
        func paint(_ name: String) {
            images[name]?.draw(in: rect, from: .zero, operation: .sourceOver, fraction: 1,
                               respectFlipped: true, hints: [.interpolation: NSImageInterpolation.high])
        }
        guard let base = animation.baseFrame, let patch = patchRect(animation, in: rect) else {
            paint(frame)
            return
        }
        paint(base)
        guard frame != base else { return }
        NSGraphicsContext.saveGraphicsState()
        NSBezierPath(rect: patch).addClip()
        paint(frame)
        NSGraphicsContext.restoreGraphicsState()
    }
}
