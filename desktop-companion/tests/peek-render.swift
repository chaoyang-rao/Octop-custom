import AppKit

@main
struct PeekRender {
    static func main() throws {
        let args = CommandLine.arguments
        guard args.count == 3 else { fatalError("Pass the approved frame directory and output directory") }
        let root = URL(fileURLWithPath: args[1]), output = URL(fileURLWithPath: args[2])
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        let manifest = try JSONDecoder().decode(PetManifest.self, from: Data(contentsOf: root.appendingPathComponent("pet.json")))
        for edge in PetEdgeDocking.Edge.allCases {
            guard let appearance = manifest.peek?[edge == .left || edge == .right ? "right" : "bottom"], let image = NSImage(contentsOf: root.appendingPathComponent(appearance.frame)) else { fatalError("Missing dedicated peek pose") }
            let size = appearance.size(for: 240, referenceHeadWidth: manifest.registration?.headWidth ?? 0.52)
            let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(ceil(size.width)), pixelsHigh: Int(ceil(size.height)), bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
            PetSpriteDrawing.drawPeek(image, appearance: appearance, edge: edge, in: NSRect(origin: .zero, size: size))
            NSGraphicsContext.restoreGraphicsState()
            precondition((bitmap.colorAt(x: bitmap.pixelsWide/2, y: bitmap.pixelsHigh/2)?.alphaComponent ?? 0) > 0.8)
            try bitmap.representation(using: .png, properties: [:])!.write(to: output.appendingPathComponent("peek-"+edge.rawValue+".png"))
        }
        PetEdgeDocking.selfTest()
        print("dedicated_peek_poses_and_edge_geometry=passed")
    }
}
