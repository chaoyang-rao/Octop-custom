/** Pure patches for the saved Octop 1.0.2 voice-input and locale chunks. */
export const VOICE_ERROR_MESSAGES = {
  "zh": {
    "sttPermissionDenied": "语音权限未允许。请检查浏览器权限；Mac 桌面端还需在系统设置中允许 Octop 的麦克风和语音识别权限。",
    "sttServiceNotAllowed": "当前环境未允许浏览器语音识别。Mac 请检查系统语音识别权限；也可在“语音服务”中选择其他识别服务。",
    "sttAudioCaptureFailed": "无法获取可用的麦克风音频，请检查麦克风连接和占用情况。",
    "sttLanguageUnsupported": "当前语音识别服务不支持所选语言，请切换语言或配置其他识别服务。",
    "sttTimedOut": "语音识别等待超时，请重试或在“语音服务”中选择其他识别服务。"
  },
  "en": {
    "sttPermissionDenied": "Speech permission was not granted. Check browser permissions; on Mac, also allow Octop to use Microphone and Speech Recognition in System Settings.",
    "sttServiceNotAllowed": "Browser speech recognition is not allowed in this environment. On Mac, check Speech Recognition permission, or choose another service in Voice settings.",
    "sttAudioCaptureFailed": "No microphone audio could be captured. Check the microphone connection and whether another application is using it.",
    "sttLanguageUnsupported": "The speech recognition service does not support the selected language. Change the language or configure another service.",
    "sttTimedOut": "Speech recognition timed out. Try again or choose another service in Voice settings."
  }
};

const HELPERS = 'function browserSttErrorKey(error){const text=error instanceof Error?error.message:"",name=typeof error==="object"&&error!==null&&"name"in error&&typeof error.name==="string"?error.name:"";if(name==="NotAllowedError"||name==="SecurityError")return"voice.sttPermissionDenied";switch(text){case"browser STT failed: not-allowed":return"voice.sttPermissionDenied";case"browser STT failed: service-not-allowed":return"voice.sttServiceNotAllowed";case"browser STT failed: audio-capture":return"voice.sttAudioCaptureFailed";case"browser STT failed: language-not-supported":return"voice.sttLanguageUnsupported";case"browser STT timed out":return"voice.sttTimedOut";case"browser STT network":return"voice.sttNetworkFailed";default:return"voice.sttFailed"}}function stopMediaStream(stream){stream&&stream.getTracks().forEach(track=>track.stop())}';

function once(source, before, after) {
  const count = source.split(before).length - 1;
  if (count !== 1) throw new Error(`Expected one voice patch point, found ${count}: ${before.slice(0, 100)}`);
  return source.replace(before, after);
}

export function patchVoiceInputSource(source) {
  if (typeof source !== 'string') throw new TypeError('Voice source must be a string');
  source = once(source, 'async function transcribeWithBrowser(language){', HELPERS + 'async function transcribeWithBrowser(language){');
  source = once(source,
    'settle(()=>reject(err instanceof Error?err:new Error("browser STT failed")))',
    'settle(()=>reject(err))');
  source = once(source,
    'await new Promise(resolve=>{recorder.onstop=()=>resolve(),recorder.stop()})',
    'await new Promise(resolve=>{recorder.addEventListener("stop",()=>resolve(),{once:!0}),recorder.stop()})');
  source = once(source,
    'catch(err){(err instanceof Error?err.message:"").includes("network")?message.error(t("voice.sttNetworkFailed")):message.error(t("voice.sttFailed"))}',
    'catch(err){message.error(t(browserSttErrorKey(err)))}');
  source = once(source,
    'try{const stream=await navigator.mediaDevices.getUserMedia({audio:!0}),mimeType=pickRecorderMimeType(),recorder=',
    'let stream=null;try{stream=await navigator.mediaDevices.getUserMedia({audio:!0});const mimeType=pickRecorderMimeType(),recorder=');
  source = once(source,
    'recorder.onstop=()=>{stream.getTracks().forEach(track2=>track2.stop())}',
    'recorder.onstop=()=>{stopMediaStream(stream)}');
  source = once(source,
    'catch{message.error(t("voice.micDenied"))}},[t,language,startRealtime,stopRealtime])',
    'catch{stopMediaStream(stream),mediaRecorderRef.current=null,chunksRef.current=[],setRecording(!1),message.error(t("voice.micDenied"))}},[t,language,startRealtime,stopRealtime])');
  return source;
}

export function patchVoiceLocaleSource(source) {
  if (typeof source !== 'string') throw new TypeError('Voice locale source must be a string');
  const anchors = [
    ['zh', 'sttFailed:"语音识别失败",'],
    ['en', 'sttFailed:"Speech recognition failed",'],
  ];
  const matches = anchors.filter(([, anchor]) => source.includes(anchor));
  if (!matches.length) {
    if (source.includes('sttFailed:')) throw new Error('Unsupported voice locale anchor');
    return source;
  }
  if (matches.length !== 1 || source.includes('sttPermissionDenied:')) throw new Error('Voice locale is ambiguous or already patched');
  const [language, anchor] = matches[0];
  const additions = Object.entries(VOICE_ERROR_MESSAGES[language]).map(([key, value]) => `${key}:${JSON.stringify(value)},`).join('');
  return once(source, anchor, anchor + additions);
}
