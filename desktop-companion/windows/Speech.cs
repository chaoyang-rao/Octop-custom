using System;
using System.Globalization;
using System.Speech.Recognition;
using System.Speech.Synthesis;
using System.Web.Script.Serialization;
using System.Collections.Generic;
class Speech {
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    static readonly object Gate = new object();
    static SpeechRecognitionEngine Recognition;
    static string Transcript = "";
    static readonly SpeechSynthesizer Voice = new SpeechSynthesizer();
    static void Emit(string type, string text) { lock (Gate) Console.WriteLine(Json.Serialize(new { type = type, text = text })); }
    static void Main() {
        Voice.SpeakCompleted += (s, e) => Emit("speechEnded", "");
        foreach (var voice in Voice.GetInstalledVoices()) if (voice.Enabled && voice.VoiceInfo.Culture.TwoLetterISOLanguageName == "zh") { Voice.SelectVoice(voice.VoiceInfo.Name); break; }
        string line;
        while ((line = Console.ReadLine()) != null) {
            try {
                var value = Json.Deserialize<Dictionary<string, object>>(line);
                string op = (string)value["op"];
                if (op == "speak") { Voice.SpeakAsyncCancelAll(); Voice.SpeakAsync((string)value["text"]); }
                if (op == "stopSpeaking") Voice.SpeakAsyncCancelAll();
                if (op == "stopListening" && Recognition != null) { Recognition.RecognizeAsyncCancel(); }
                if (op == "startListening") {
                    if (Recognition == null) {
                        RecognizerInfo selected = null;
                        foreach (var info in SpeechRecognitionEngine.InstalledRecognizers()) if (info.Culture.TwoLetterISOLanguageName == "zh") { selected = info; break; }
                        if (selected == null) throw new InvalidOperationException("请先在 Windows 设置中安装中文语音识别语言包。");
                        Recognition = new SpeechRecognitionEngine(selected);
                        Recognition.LoadGrammar(new DictationGrammar());
                        Recognition.SpeechRecognized += (s, e) => { Transcript = (Transcript + " " + e.Result.Text).Trim(); Emit("recognized", Transcript); };
                        Recognition.RecognizeCompleted += (s, e) => Emit("listeningEnded", "");
                        Recognition.SetInputToDefaultAudioDevice();
                    }
                    Transcript = "";
                    Recognition.RecognizeAsync(RecognizeMode.Multiple);
                }
            } catch (Exception e) { Emit("speechError", e.Message); }
        }
        if (Recognition != null) Recognition.Dispose(); Voice.Dispose();
    }
}
