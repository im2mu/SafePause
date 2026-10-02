/* 소리로 듣기. 기기 안 한국어 음성만 쓴다(읽을 글에 받는 사람·금액이 있어 온라인 음성으로 보내지 않음).
 * - 안드로이드 앱: 기기 TTS(SafePauseNative.speak). 다 읽거나 멈추면 앱이 window.__safepauseSpeechDone()을 부른다.
 * - PC 브라우저: Web Speech API의 localService 한국어 음성(끝나면 onend).
 * 상태 관리: 한 번에 하나만 읽는다. 새로 읽기 시작하거나 stop()하면 앞의 것은 끝난 것으로 보고 onEnd를 부른다.
 * 음성 준비 상태(D10): voiceStatus() = "ready"(쓸 수 있음) | "pending"(아직 준비 중) | "none"(이 기기에 없음으로 확정).
 *  - html[data-voice]에 같은 값을 적는다. CSS가 준비 전에는 소리로 듣기 버튼(.speak-btn)을 숨기고,
 *    음성 없음 안내(.voice-note)는 없음으로 확정됐을 때만 보인다. 그래서 음성 목록이 늦게 와도 화면이 맞게 바뀐다.
 *  - 쓸 음성이 없다고 확정되면 소리로 듣기 버튼을 만들지 않는다(components.speakButton이 null).
 */
import { deviceWord } from "./format.js";

const native = window.SafePauseNative;
const webSpeech = !native && "speechSynthesis" in window && typeof window.SpeechSynthesisUtterance === "function";
const WEB_WAIT_MS = 3000;        // 브라우저 음성 목록을 기다리는 시간(그 뒤에도 없으면 없음으로 본다)
let koVoice = null;
let settled = !native && !webSpeech;   // 더 기다리지 않음(있거나 없음이 정해짐)
const listeners = new Set();

function publish() {
  const st = voiceStatus();
  try { document.documentElement.dataset.voice = st; } catch (e) { /* 문서가 없으면 건너뜀 */ }
  for (const fn of listeners) { try { fn(st === "ready"); } catch (e) { /* 화면 쪽 오류는 무시 */ } }
}

function pickVoice() {
  if (!webSpeech) return;
  let voices = [];
  try { voices = window.speechSynthesis.getVoices() || []; } catch (e) { voices = []; }
  koVoice = voices.find((v) => v.localService === true && /^ko/i.test(v.lang || "")) || null;
  if (koVoice) settled = true;
  publish();
}

if (webSpeech) {
  pickVoice();
  if (typeof window.speechSynthesis.addEventListener === "function") window.speechSynthesis.addEventListener("voiceschanged", pickVoice);
  else window.speechSynthesis.onvoiceschanged = pickVoice;
  window.setTimeout(() => { if (!settled) { settled = true; publish(); } }, WEB_WAIT_MS);
}

let nativePoll = 0;
if (native) {
  // TTS 엔진 준비는 비동기다: 준비되면(또는 10초를 기다려도 안 되면) 한 번 알린다
  const check = () => {
    let s = "none";
    try { s = native.ttsStatus(); } catch (e) { s = "none"; }
    if (s === "pending" && nativePoll < 40) { nativePoll += 1; window.setTimeout(check, 250); return; }
    settled = true;
    publish();
  };
  window.setTimeout(check, 250);
}
publish();

export function available() {
  if (native) { try { return native.ttsStatus() === "ready"; } catch (e) { return false; } }
  return Boolean(webSpeech && koVoice);
}

/** "ready" | "pending" | "none". pending은 음성 목록·TTS 엔진이 아직 준비 중이라는 뜻이다. */
export function voiceStatus() {
  if (available()) return "ready";
  return settled ? "none" : "pending";
}

/** 준비 상태가 바뀔 때 fn(available)을 부른다. 돌려주는 함수를 부르면 구독을 끝낸다. */
export function onAvailability(fn) { listeners.add(fn); return () => listeners.delete(fn); }

// ---- 지금 읽는 것 -------------------------------------------------------------------
let current = null;          // {onEnd, utterance?, timer?}
// 앱은 지금 발화의 끝남만 알린다(새 발화에 밀린 옛 발화는 알리지 않음). 다만 멈추기의 알림은 화면이 이미
// 원래대로 돌린 뒤에 늦게 오므로, 그 알림이 바로 다음 발화를 끝내지 않게 한 번 건너뛴다
let skipDone = 0;
let skipTimer = 0;
// 옛 앱(끝남 알림이 없는 브리지)은 글 길이로 끝날 때를 어림한다
const nativeDone = Boolean(native && typeof native.capabilities === "function");

function finish(entry) {
  if (!entry || current !== entry) return;
  current = null;
  if (entry.timer) window.clearTimeout(entry.timer);
  if (typeof entry.onEnd === "function") { try { entry.onEnd(); } catch (e) { /* 화면 쪽 오류는 무시 */ } }
}

function expectLateDone() {
  if (!native || !nativeDone) return;
  skipDone += 1;
  window.clearTimeout(skipTimer);
  skipTimer = window.setTimeout(() => { skipDone = 0; }, 2000);   // 알림이 오지 않았으면 셈을 버린다
}

// 안드로이드 UtteranceProgressListener(onDone·onError·onStop)가 UI 스레드에서 부른다
window.__safepauseSpeechDone = () => {
  if (skipDone > 0) { skipDone -= 1; return; }
  finish(current);
};

/** 지금 읽고 있으면 true. */
export function isSpeaking() { return current !== null; }

/**
 * 글을 읽는다. 읽던 것이 있으면 멈추고(그 onEnd를 부름) 새로 읽는다.
 * opts.onEnd: 다 읽었거나, 멈췄거나, 다른 글을 읽기 시작했을 때 한 번 불린다.
 * 돌려주는 값: 읽기를 시작했으면 true(음성이 없거나 글이 비면 false, onEnd는 불리지 않음).
 */
export function speak(text, opts = {}) {
  const t = String(text || "").trim();
  if (!t || !available()) return false;
  if (current) finish(current);
  const entry = { onEnd: opts.onEnd };
  if (native) {
    let ok = false;
    try { ok = native.speak(t); } catch (e) { ok = false; }
    if (!ok) return false;
    current = entry;
    if (!nativeDone) entry.timer = window.setTimeout(() => finish(entry), 1500 + t.length * 160);
    return true;
  }
  const synth = window.speechSynthesis;
  synth.cancel();
  const u = new SpeechSynthesisUtterance(t);
  u.voice = koVoice;
  u.lang = koVoice.lang;
  u.rate = 0.9;
  entry.utterance = u;
  u.onend = () => finish(entry);
  u.onerror = () => finish(entry);
  current = entry;
  synth.speak(u);
  return true;
}

/** 읽기를 멈춘다(읽던 것의 onEnd를 부름). 화면을 옮길 때도 불린다. */
export function stop() {
  const entry = current;
  if (entry) expectLateDone();
  try {
    if (native) native.stopSpeaking();
    else if (webSpeech) window.speechSynthesis.cancel();
  } catch (e) { /* 무시 */ }
  finish(entry);
}

/** 음성이 없을 때의 안내(장소 말은 deviceWord). 화면은 components.noVoiceNote()를 쓰면 준비 상태에 맞춰 보이고 숨는다. */
export function noVoiceNote() {
  return `${deviceWord()}에 한국어 음성이 없어서 소리로 듣기 버튼을 숨겼어요. 인터넷으로 글을 보내는 음성은 쓰지 않아요.`;
}
// 옛 이름(문자열). 처음 불러올 때 장소 말을 정한다(앱·휴대폰 브라우저는 이 휴대폰, PC는 이 컴퓨터)
export const NO_VOICE_NOTE = noVoiceNote();
