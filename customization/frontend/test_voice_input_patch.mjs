import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import { patchVoiceInputSource, patchVoiceLocaleSource, VOICE_ERROR_MESSAGES } from './voice-input-patch.mjs';

const require = createRequire(new URL('../../dashboard/package.json', import.meta.url));
const ts = require('typescript');
const base = new URL('../baselines/projects-v2/octop/dashboard/assets/', import.meta.url);
const original = fs.readFileSync(new URL('index.G9_xhF8C.projects-v2.js', base), 'utf8');
const patched = patchVoiceInputSource(original);
const from = patched.indexOf('const BROWSER_STT_TIMEOUT_MS=15e3;');
const to = patched.indexOf('function expertMentionToken(', from);
assert.ok(from > 0 && to > from);
const frozen = patched.slice(from, to) + ';globalThis.voiceHook=useVoiceInput;globalThis.errorKey=browserSttErrorKey;';
const canonical = ts.transpileModule(fs.readFileSync(new URL('../../dashboard/src/hooks/useVoiceInput.ts', import.meta.url), 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText;

function harness(kind, plan = {}) {
  const errors = [], infos = [], texts = [], order = [], recorders = [], recognizers = [];
  const timers = new Map();
  let nextTimer = 0, hooks = [], cursor = 0, transcriptions = 0;
  const active = { stt: plan.server ? 'configured-test-provider' : 'browser', tts: 'browser', stt_realtime: false };
  const stream = { getTracks: () => [track] };
  const track = { stopCount: 0, stop() { this.stopCount++; order.push('track-stopped'); } };
  class Recorder extends EventTarget {
    static isTypeSupported(type) { return type === 'audio/mp4'; }
    constructor(received, options = {}) {
      super();
      if (plan.constructorFailure) throw new Error('recorder unavailable');
      assert.equal(received, stream);
      this.options = options; this.state = 'inactive'; this.onstop = null; this.ondataavailable = null;
      recorders.push(this);
    }
    start() {
      if (plan.startFailure) throw new Error('recorder start failed');
      this.state = 'recording';
      this.ondataavailable?.({ data: new Blob(['first-'], { type: this.options.mimeType }) });
    }
    stop() {
      this.state = 'inactive';
      queueMicrotask(() => {
        order.push('final-data');
        this.ondataavailable?.({ data: new Blob(['last'], { type: this.options.mimeType }) });
        this.onstop?.(new Event('stop'));
        this.dispatchEvent(new Event('stop'));
      });
    }
  }
  class Recognition {
    constructor() { recognizers.push(this); }
    start() {
      if (plan.browserStartError) throw plan.browserStartError;
      queueMicrotask(() => {
        if (plan.browserError) {
          this.onerror?.({ error: plan.browserError });
          this.onend?.();
        } else if (plan.browserText) {
          this.onresult?.({ resultIndex: 0, results: [{ isFinal: true, length: 1, 0: { transcript: plan.browserText } }] });
          this.onend?.();
        }
      });
    }
    stop() { order.push('browser-stop'); }
  }
  const React = {
    useState(initial) {
      const slot = cursor++;
      if (!(slot in hooks)) hooks[slot] = initial;
      return [hooks[slot], value => { hooks[slot] = typeof value === 'function' ? value(hooks[slot]) : value; }];
    },
    useRef(value) {
      const slot = cursor++;
      if (!(slot in hooks)) hooks[slot] = { current: value };
      return hooks[slot];
    },
    useCallback(fn) { return fn; },
  };
  const message = { error: value => errors.push(value), info: value => infos.push(value) };
  const voiceApi = {
    async transcribe(blob, language) {
      transcriptions++;
      order.push('transcribe');
      assert.equal(track.stopCount, 1, 'microphone must already be stopped when upload starts');
      assert.equal(await blob.text(), 'first-last', 'the final asynchronous dataavailable event must be included');
      assert.equal(blob.type, 'audio/mp4');
      assert.equal(language, 'zh-CN');
      if (plan.serverFailure) throw new Error('provider failure contains fake_secret_for_test');
      return { text: '转写完成' };
    },
  };
  const context = {
    Blob, Event, EventTarget, Error, DOMException, queueMicrotask, console,
    navigator: { mediaDevices: { async getUserMedia() { if (plan.mediaFailure) throw new Error('media denied'); return stream; } } },
    MediaRecorder: Recorder,
    window: { MediaRecorder: Recorder, SpeechRecognition: Recognition,
      setTimeout(fn) { const id = ++nextTimer; timers.set(id, fn); return id; },
      clearTimeout(id) { timers.delete(id); } },
    reactExports: React,
    useTranslation: () => ({ t: key => key, i18n: { language: 'zh' } }),
    useVoiceConfig: () => ({ active }), cachedActiveVoice: () => active, fetchActiveVoice: async () => active,
    speechLocaleFromUi: () => 'zh-CN', message, voiceApi,
    getWsUrl: () => 'ws://test.invalid', getAuthToken: () => null,
    RealtimeSttClient: class {}, PcmFrameBuffer: class {}, downsampleToPcm16: () => new Int16Array(),
  };
  if (kind === 'canonical') {
    const mod = { exports: {} };
    Object.assign(context, { module: mod, exports: mod.exports,
      require(name) {
        if (name === 'react') return React;
        if (name === 'react-i18next') return { useTranslation: context.useTranslation };
        if (name.endsWith('/api/config')) return { getWsUrl: context.getWsUrl };
        if (name.endsWith('/api/modules/voice')) return { voiceApi };
        if (name.endsWith('/api/request')) return { getAuthToken: context.getAuthToken };
        if (name.endsWith('/utils/localePrefs')) return { speechLocaleFromUi: context.speechLocaleFromUi };
        if (name.endsWith('/utils/pcmCapture')) return { PcmFrameBuffer: context.PcmFrameBuffer, downsampleToPcm16: context.downsampleToPcm16 };
        if (name.endsWith('/utils/realtimeStt')) return { RealtimeSttClient: context.RealtimeSttClient };
        if (name === './useVoiceConfig') return { cachedActiveVoice: context.cachedActiveVoice, fetchActiveVoice: context.fetchActiveVoice, useVoiceConfig: context.useVoiceConfig };
        if (name === '@/utils/antdMessage') return { message };
        throw new Error('Unexpected voice test dependency: ' + name);
      },
    });
    vm.runInNewContext(canonical, context);
    context.voiceHook = mod.exports.useVoiceInput;
    context.errorKey = mod.exports.browserSttErrorKey;
  } else {
    vm.runInNewContext(frozen, context);
  }
  cursor = 0;
  const hook = context.voiceHook({ onText: value => texts.push(value) });
  return { hook, errors, infos, texts, order, track, timers, active, recorders, recognizers,
    get transcriptions() { return transcriptions; }, errorKey: context.errorKey,
    fireTimeout() { const timer = [...timers.values()][0]; assert.equal(typeof timer, 'function'); timer(); } };
}

const cases = [
  ['not-allowed', 'voice.sttPermissionDenied'],
  ['service-not-allowed', 'voice.sttServiceNotAllowed'],
  ['audio-capture', 'voice.sttAudioCaptureFailed'],
  ['language-not-supported', 'voice.sttLanguageUnsupported'],
  ['network', 'voice.sttNetworkFailed'],
  ['unknown-fake_secret_for_test', 'voice.sttFailed'],
];
let checks = 0;
for (const kind of ['canonical', 'frozen']) {
  for (const [event, expected] of cases) {
    const h = harness(kind, { browserError: event });
    await h.hook.start();
    assert.deepEqual(h.errors, [expected], `${kind}/${event}`);
    assert.equal(h.timers.size, 0);
    assert.ok(!JSON.stringify(h.errors).includes('fake_secret_for_test'));
    checks++;
  }
  for (const name of ['NotAllowedError', 'SecurityError']) {
    const h = harness(kind, { browserStartError: { name, message: 'fake_secret_for_test' } });
    await h.hook.start();
    assert.deepEqual(h.errors, ['voice.sttPermissionDenied']);
    checks++;
  }
  const timed = harness(kind);
  const pending = timed.hook.start();
  timed.fireTimeout();
  await pending;
  assert.deepEqual(timed.errors, ['voice.sttTimedOut']);
  assert.ok(timed.order.includes('browser-stop'));
  checks++;
  const text = harness(kind, { browserText: '这是语音测试' });
  await text.hook.start();
  assert.deepEqual(text.texts, ['这是语音测试']);
  assert.deepEqual(text.errors, []);
  checks++;
  const noSpeech = harness(kind, { browserError: 'no-speech' });
  await noSpeech.hook.start();
  assert.deepEqual(noSpeech.infos, ['voice.sttEmpty']);
  assert.deepEqual(noSpeech.errors, []);
  checks++;
  const recording = harness(kind, { server: true });
  await recording.hook.start();
  await recording.hook.stop();
  assert.equal(recording.track.stopCount, 1);
  assert.deepEqual(recording.order, ['final-data', 'track-stopped', 'transcribe']);
  assert.deepEqual(recording.texts, ['转写完成']);
  assert.equal(recording.transcriptions, 1);
  checks++;
  for (const failure of ['constructorFailure', 'startFailure', 'mediaFailure']) {
    const failed = harness(kind, { server: true, [failure]: true });
    await failed.hook.start();
    await failed.hook.stop();
    assert.equal(failed.track.stopCount, failure === 'mediaFailure' ? 0 : 1);
    assert.equal(failed.transcriptions, 0);
    assert.deepEqual(failed.errors, ['voice.micDenied']);
    checks++;
  }
  const required = harness(kind, { server: true });
  await required.hook.start(); required.active.stt = 'browser'; await required.hook.stop();
  assert.equal(required.track.stopCount, 1); assert.equal(required.transcriptions, 0);
  assert.deepEqual(required.errors, ['voice.sttProviderRequired']);
  checks++;
  const serverError = harness(kind, { server: true, serverFailure: true });
  await serverError.hook.start(); await serverError.hook.stop();
  assert.equal(serverError.track.stopCount, 1);
  assert.deepEqual(serverError.errors, ['voice.sttFailed']);
  checks++;
}

assert.throws(() => patchVoiceInputSource(''), /Expected one voice patch point/);
assert.throws(() => patchVoiceInputSource(patched), /Expected one voice patch point/);
assert.throws(() => patchVoiceInputSource(original + original), /Expected one voice patch point/);
assert.throws(() => patchVoiceInputSource(null), /must be a string/);
const main = fs.readFileSync(new URL('index.BsYGCvv_.projects-v2.js', base), 'utf8');
assert.equal(patchVoiceLocaleSource(main), main, 'unrelated main module stays byte-identical');
for (const [language, name] of [['zh', 'zh.D-7HvP3m.projects-v2.js'], ['en', 'en.CaWe8dRV.projects-v2.js']]) {
  const before = fs.readFileSync(new URL(name, base), 'utf8');
  const after = patchVoiceLocaleSource(before);
  const exportAt = after.lastIndexOf('export{');
  assert.ok(exportAt > 0);
  const ctx = {};
  vm.runInNewContext(after.slice(0, exportAt) + ';globalThis.voiceCopy=voice;', ctx);
  const source = JSON.parse(fs.readFileSync(new URL(`../../dashboard/src/locales/${language}.json`, import.meta.url), 'utf8')).voice;
  for (const [key, message] of Object.entries(VOICE_ERROR_MESSAGES[language])) {
    assert.equal(ctx.voiceCopy[key], message);
    assert.equal(source[key], message);
  }
  assert.throws(() => patchVoiceLocaleSource(after), /already patched/);
}
assert.throws(() => patchVoiceLocaleSource('const voice={sttFailed:"changed"};'), /Unsupported voice locale anchor/);
console.log(`PASS ${checks} canonical/frozen event and microphone lifecycle checks; bilingual locale parity, exact network fallback, patch guards and unrelated-main preservation.`);
