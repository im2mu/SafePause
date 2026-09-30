/* 소리로 듣기. 기기 안 한국어 음성만 쓴다(읽을 글에 받는 사람·금액이 있어 온라인 음성으로 보내지 않음).
 * - 안드로이드 앱: 기기 TTS(SafePauseNative.speak). 네트워크가 필요한 음성은 앱이 고르지 않는다.
 * - PC 브라우저: Web Speech API의 localService 한국어 음성.
 * 쓸 음성이 없으면 '소리로 듣기' 버튼을 만들지 않는다(available() = false).
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
    const s = native.ttsStatus();
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

export function speak(text) {
  const t = String(text || "").trim();
  if (!t || !available()) return false;
  if (native) return native.speak(t);
  const synth = window.speechSynthesis;
  synth.cancel();
  const u = new SpeechSynthesisUtterance(t);
  u.voice = koVoice;
  u.lang = koVoice.lang;
  u.rate = 0.9;
  synth.speak(u);
  return true;
}

export function stop() {
  try {
    if (native) native.stopSpeaking();
    else if (webSpeech) window.speechSynthesis.cancel();
  } catch (e) { /* 무시 */ }
}

export const NO_VOICE_NOTE = "이 기기에 한국어 음성이 없어서 '소리로 듣기'를 숨겼어요. 인터넷으로 글을 보내는 음성은 쓰지 않아요.";
