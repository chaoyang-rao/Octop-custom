import AppKit

@main
struct BlinkRenderCheck {
    static func main() throws {
        let root = URL(fileURLWithPath: CommandLine.arguments[1])
        let output = URL(fileURLWithPath: CommandLine.arguments[2])
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        let manifest = try JSONDecoder().decode(PetManifest.self, from: Data(contentsOf: root.appendingPathComponent("pet.json")))
        let animation = manifest.animations["idle"]!
        var images: [String: NSImage] = [:]
        for name in Set(animation.frames) {
            images[name] = NSImage(contentsOf: root.appendingPathComponent(name))!
        }
        for size in [96, 158, 256, 512] {
            let rect = NSRect(x: 0, y: 0, width: size, height: size)
            let patch = PetSpriteDrawing.patchRect(animation, in: rect)!.insetBy(dx: -1, dy: -1)
            var first: NSBitmapImageRep?
            var changes = 0
            for (index, name) in Set(animation.frames).sorted().enumerated() {
                let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
                    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                    colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
                NSGraphicsContext.saveGraphicsState()
                NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
                PetSpriteDrawing.draw(animation, frame: name, images: images, in: rect)
                NSGraphicsContext.restoreGraphicsState()
                if let reference = first {
                    for y in 0..<size { for x in 0..<size {
                        let before = reference.colorAt(x: x, y: y)!
                        let after = bitmap.colorAt(x: x, y: y)!
                        if before != after {
                            precondition(patch.contains(NSPoint(x: Double(x) + 0.5, y: Double(size-y) - 0.5)), "Blink changed body pixels")
                            changes += 1
                        }
                    } }
                } else { first = bitmap }
                if size == 512 {
                    try bitmap.representation(using: .png, properties: [:])!.write(to: output.appendingPathComponent("blink-\(index).png"))
                }
            }
            precondition(changes > 0, "Blink did not animate the eyes")
            print("\(size)px: body unchanged; \(changes) eye pixels animated")
        }
    }
}
