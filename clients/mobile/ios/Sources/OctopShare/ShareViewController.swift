import Foundation
import SwiftUI
import UIKit
import UniformTypeIdentifiers

final class ShareViewController: UIViewController {
    private var host: UIHostingController<AnyView>?
    override func viewDidLoad() {
        super.viewDidLoad()
        Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                let draft = try await self.loadDraft()
                self.install(AnyView(ShareComposerView(original: draft) { [weak self] in self?.extensionContext?.completeRequest(returningItems: [], completionHandler: nil) }))
            } catch {
                self.install(AnyView(VStack(spacing: 20) {
                    Text(L("native_could_not_read_shared_content_10_files_10_mb_total")).padding()
                    Button(L("native_close")) { [weak self] in self?.extensionContext?.completeRequest(returningItems: [], completionHandler: nil) }
                }))
            }
        }
    }
    private func install(_ view: AnyView) {
        let controller = UIHostingController(rootView: view)
        addChild(controller); controller.view.translatesAutoresizingMaskIntoConstraints = false; self.view.addSubview(controller.view)
        NSLayoutConstraint.activate([controller.view.leadingAnchor.constraint(equalTo: self.view.leadingAnchor), controller.view.trailingAnchor.constraint(equalTo: self.view.trailingAnchor), controller.view.topAnchor.constraint(equalTo: self.view.topAnchor), controller.view.bottomAnchor.constraint(equalTo: self.view.bottomAnchor)])
        controller.didMove(toParent: self); host = controller
    }
    private func loadDraft() async throws -> SharedDraft {
        var text: [String] = [], files: [SharedFile] = []
        for item in (extensionContext?.inputItems as? [NSExtensionItem]) ?? [] {
            for provider in item.attachments ?? [] {
                if provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
                    if let url = try await loadItem(provider, type: UTType.fileURL.identifier) as? URL { files.append(try Self.file(url, name: provider.suggestedName)) }
                } else if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
                    if let value = try await loadItem(provider, type: UTType.url.identifier) as? URL { text.append(value.absoluteString) }
                } else if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
                    if let value = try await loadItem(provider, type: UTType.plainText.identifier) as? String { text.append(value) }
                } else if let type = provider.registeredTypeIdentifiers.first(where: { UTType($0)?.conforms(to: .data) == true }) {
                    let suggestedName = provider.suggestedName
                    let incoming: SharedFile = try await withCheckedThrowingContinuation { continuation in
                        provider.loadFileRepresentation(forTypeIdentifier: type) { url, error in
                            guard let url else { continuation.resume(throwing: error ?? ShareStore.Failure.invalid); return }
                            do { continuation.resume(returning: try Self.file(url, name: suggestedName, type: UTType(type))) }
                            catch { continuation.resume(throwing: error) }
                        }
                    }
                    files.append(incoming)
                }
                guard files.count <= 10, files.reduce(0, { $0 + $1.data.count }) <= 10 * 1024 * 1024 else { throw ShareStore.Failure.invalid }
            }
        }
        let joined = text.joined(separator: "\n")
        guard joined.count <= 32000, !joined.isEmpty || !files.isEmpty else { throw ShareStore.Failure.invalid }
        return SharedDraft(text: joined, files: files)
    }
    private func loadItem(_ provider: NSItemProvider, type: String) async throws -> NSSecureCoding {
        try await withCheckedThrowingContinuation { continuation in
            provider.loadItem(forTypeIdentifier: type, options: nil) { value, error in
                if let value { continuation.resume(returning: value) }
                else { continuation.resume(throwing: error ?? ShareStore.Failure.invalid) }
            }
        }
    }
    nonisolated private static func file(_ url: URL, name: String?, type: UTType? = nil) throws -> SharedFile {
        let permitted = url.startAccessingSecurityScopedResource(); defer { if permitted { url.stopAccessingSecurityScopedResource() } }
        let values = try url.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
        guard values.isRegularFile == true, (values.fileSize ?? Int.max) <= 10 * 1024 * 1024 else { throw ShareStore.Failure.invalid }
        let data = try Data(contentsOf: url, options: .mappedIfSafe), kind = type ?? UTType(filenameExtension: url.pathExtension) ?? .data
        var filename = name ?? url.lastPathComponent
        if URL(fileURLWithPath: filename).pathExtension.isEmpty, let ext = kind.preferredFilenameExtension { filename += "." + ext }
        return SharedFile(filename: URL(fileURLWithPath: filename).lastPathComponent, mime: kind.preferredMIMEType ?? "application/octet-stream", data: data)
    }
}
