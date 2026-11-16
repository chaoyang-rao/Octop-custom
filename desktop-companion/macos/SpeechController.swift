import AppKit
import AVFoundation
import Speech

@MainActor
final class SpeechController: NSObject, AVSpeechSynthesizerDelegate {
    var onEvent: (@MainActor ([String: Any]) -> Void)?
    private let synthesizer = AVSpeechSynthesizer()
    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "zh-CN"))
    private var recording = false
    private var requested = false
    private var recognitionId = UUID()
    private var spoken: AVSpeechUtterance?
    var isSpeaking: Bool { spoken != nil }
    var isListening: Bool { recording }

    override init() { super.init(); synthesizer.delegate = self }

    func start() async throws {
        stopRecognition(notify: false)
        stopSpeaking()
        let generation = UUID()
        recognitionId = generation
        requested = true
        let microphone = await withCheckedContinuation { (continuation: CheckedContinuation<Bool, Never>) in
            AVCaptureDevice.requestAccess(for: .audio) { continuation.resume(returning: $0) }
        }
        guard requested && recognitionId == generation else { return }
        guard microphone else {
            requested = false
            throw CompanionError.unavailable("请在系统设置的“隐私与安全性 → 麦克风”中允许哆啦。")
        }
        let authorization = await withCheckedContinuation { (continuation: CheckedContinuation<SFSpeechRecognizerAuthorizationStatus, Never>) in
            SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
        }
        guard requested && recognitionId == generation else { return }
        guard authorization == .authorized else {
            requested = false
            throw CompanionError.unavailable("请在系统设置的“隐私与安全性 → 语音识别”中允许哆啦。")
        }
        guard let recognizer, recognizer.isAvailable else {
            requested = false
            throw CompanionError.unavailable("系统语音识别暂不可用，请检查网络后重试。")
        }
        let audioRequest = SFSpeechAudioBufferRecognitionRequest()
        audioRequest.shouldReportPartialResults = true
        request = audioRequest
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0 else {
            requested = false
            throw CompanionError.unavailable("没有找到可用麦克风。")
        }
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in audioRequest.append(buffer) }
        recording = true
        task = recognizer.recognitionTask(with: audioRequest) { [weak self] result, error in
            DispatchQueue.main.async {
                guard let self, self.recognitionId == generation else { return }
                if let result { self.onEvent?(["type": "voice", "text": result.bestTranscription.formattedString]) }
                if result?.isFinal == true { self.finish() }
                else if error != nil && self.requested {
                    self.finish()
                    self.onEvent?(["type": "voice", "error": "语音识别中断，已识别的文字保留在输入框，请检查网络后重试。"])
                }
            }
        }
        engine.prepare()
        do { try engine.start() }
        catch { stopRecognition(); throw CompanionError.unavailable("麦克风无法启动，请检查是否被其他设备占用。") }
        onEvent?(["type": "voice", "data": "started"])
    }

    func finish(notify: Bool = true) {
        requested = false
        if recording { engine.stop(); engine.inputNode.removeTap(onBus: 0); recording = false }
        request?.endAudio(); task?.finish()
        if notify { onEvent?(["type": "voice", "data": "stopped"]) }
    }
    func stopRecognition(notify: Bool = true) {
        recognitionId = UUID()
        finish(notify: notify)
        task?.cancel(); task = nil; request = nil
    }
    func speak(_ text: String) {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        stopRecognition(); stopSpeaking()
        let utterance = AVSpeechUtterance(string: String(text.prefix(8000)))
        utterance.voice = AVSpeechSynthesisVoice(language: "zh-CN")
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate * 0.92
        spoken = utterance
        synthesizer.speak(utterance)
    }
    func stopSpeaking() {
        spoken = nil
        synthesizer.stopSpeaking(at: .immediate)
        onEvent?(["type": "speech", "data": "stopped"])
    }
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didStart utterance: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard let self, self.spoken === utterance else { return }
            self.onEvent?(["type": "speech", "data": "started"])
        }
    }
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard let self, self.spoken === utterance else { return }
            self.spoken = nil; self.onEvent?(["type": "speech", "data": "stopped"])
        }
    }
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard let self, self.spoken === utterance else { return }
            self.spoken = nil; self.onEvent?(["type": "speech", "data": "stopped"])
        }
    }
}
