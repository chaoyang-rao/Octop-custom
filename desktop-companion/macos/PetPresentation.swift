import Foundation
import CoreGraphics

struct PetFacing {
    private(set) var right = true
    mutating func update(frame: NSRect, area: NSRect) {
        if frame.midX < area.midX-16 { right = true }
        else if frame.midX > area.midX+16 { right = false }
    }
}

enum CompanionWindowPlacement {
    static func chat(size: NSSize, pet: NSRect, area: NSRect) -> NSRect {
        let width = min(size.width,area.width-24), height = min(size.height,area.height-24), gap: CGFloat = 16
        let y = max(area.minY+12,min(area.maxY-height-12,pet.midY-height*0.45))
        let left = NSRect(x:pet.minX-gap-width,y:y,width:width,height:height)
        let right = NSRect(x:pet.maxX+gap,y:y,width:width,height:height)
        let candidates = pet.midX >= area.midX ? [left,right] : [right,left]
        for frame in candidates where area.contains(frame) && !frame.intersects(pet.insetBy(dx:-8,dy:-8)) { return frame }
        let x = max(area.minX+12,min(area.maxX-width-12,candidates[0].minX))
        return NSRect(x:x,y:y,width:width,height:height)
    }
    static func selfTest() {
        let area = NSRect(x:0,y:25,width:1512,height:930), size = NSSize(width:456,height:706)
        for x in [0.0,700.0,1433.0] {
            let pet = NSRect(x:x,y:259,width:79,height:79)
            let frame = chat(size:size,pet:pet,area:area)
            precondition(area.contains(frame) && !frame.intersects(pet))
        }
        var facing = PetFacing()
        facing.update(frame:NSRect(x:30,y:200,width:79,height:79),area:area); precondition(facing.right)
        facing.update(frame:NSRect(x:1400,y:200,width:79,height:79),area:area); precondition(!facing.right)
        facing.update(frame:NSRect(x:10,y:200,width:79,height:79),area:area); precondition(facing.right)
    }
}
