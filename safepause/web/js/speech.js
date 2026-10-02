/* 소리로 듣기. 기기 안 한국어 음성만 쓴다(읽을 글에 받는 사람·금액이 있어 온라인 음성으로 보내지 않음).
 * - 안드로이드 앱: 기기 TTS(SafePauseNative.speak). 다 읽거나 멈추면 앱이 window.__safepauseSpeechDone()을 부른다.
 * - PC 브라우저: Web Speech API의 localService 한국어 음성(끝나면 onend).
 * 상태 관리: 한 번에 하나만 읽는다. 새로 읽기 시작하거나 stop()하면 앞의 것은 끝난 것으로 보고 onEnd를 부른다.
 * 쓸 음성이 없으면 소리로 듣기 버튼을 만들지 않는다(available() = false).
 */
const native = window.SafePauseNative;
const webSpeech = !native && "speechSynthesis" in window && typeof window.SpeechSynthesisUtterance === "function";
let koVoice = null;
const listeners = new Set();

function pickVoice() {
  if (!webSpeech) return;
  let voices = [];
  try { voices = window.speechSynthesis.getVoices() || []; } catch (e) { voices = []; }
  koVoice = voices.find((v) => v.localService === true && /^ko/i.test(v.lang || "")) || null;
  for (const fn of listeners) fn(available());
}

if (webSpeech) {
  pickVoice();
  if (typeof window.speechSynthesis.addEventListener === "function") window.speechSynthesis.addEventListener("voiceschanged", pickVoice);
  else window.speechSynthesis.onvoiceschanged = pickVoice;
}

let nativePoll = 0;
if (native) {
  // TTS 엔진 준비는 비동기다: 준비되면 한 번 알린다
  const check = () => {
    let s = "none";
    try { s = native.ttsStatus(); } catch (e) { s = "none"; }
    if (s === "pending" && nativePoll < 40) { nativePoll += 1; window.setTimeout(check, 250); return; }
    for (const fn of listeners) fn(available());
  };
  window.setTimeout(check, 250);
}

export function available() {
  if (native) { try { return native.ttsStatus() === "ready"; } catch (e) { return false; } }
  return Boolean(webSpeech && koVoice);
}

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

export const NO_VOICE_NOTE = "이 기기에 한국어 음성이 없어서 소리로 듣기 버튼을 숨겼어요. 인터넷으로 글을 보내는 음성은 쓰지 않아요.";
