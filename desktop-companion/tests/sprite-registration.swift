import AppKit

@main
struct SpriteRegistrationCheck {
    static func main() throws {
        let root = URL(fileURLWithPath: CommandLine.arguments[1]), output = URL(fileURLWithPath: CommandLine.arguments[2])
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        let manifest = try JSONDecoder().decode(PetManifest.self, from: Data(contentsOf: root.appendingPathComponent("pet.json")))
        guard let registration = manifest.registration else { fatalError("Missing frame registration") }
        var images: [String:NSImage] = [:]
        for animation in manifest.animations.values {
            for name in animation.frames + [animation.baseFrame].compactMap({$0}) { images[name] = NSImage(contentsOf:root.appendingPathComponent(name))! }
        }
        var total = 0
        for mirrored in [false,true] {
            let folder = output.appendingPathComponent(mirrored ? "left-facing" : "right-facing")
            try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
            var checked = Set<String>()
            for animation in manifest.animations.values {
                for name in animation.frames where !checked.contains(name) {
                    checked.insert(name); total += 1
                    let bitmap = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:512,pixelsHigh:512,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
                    guard let rect = registration.rect(for:animation.baseFrame ?? name,in:NSRect(x:0,y:0,width:512,height:512)) else { fatalError("Unregistered frame") }
                    NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep:bitmap)
                    let pivot = (registration.anchor?.first ?? 0.5)*512
                    PetSpriteDrawing.draw(animation,frame:name,images:images,in:rect,mirrorAboutX:mirrored ? pivot : nil)
                    NSGraphicsContext.restoreGraphicsState()
                    try bitmap.representation(using:.png,properties:[:])!.write(to:folder.appendingPathComponent(name))
                }
            }
        }
        print("registered_direction_frames_rendered=\(total)")
    }
}
