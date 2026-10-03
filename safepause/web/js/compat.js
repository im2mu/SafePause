/**
 * 시작 검사: 이 화면 프로그램(웹뷰·브라우저)이 SafePause를 돌릴 수 있는지 본다. 근거는 docs/mobile.md 지원 범위.
 * - 화면: Element.replaceChildren(Chrome 86)이 없으면 화면을 그릴 수 없다.
 * - 앱 안 파이썬 엔진: 웹어셈블리 예외 처리(95)·참조 타입(96)·SIMD(91)를 작은 시험 모듈로 확인(validate는 CSP와 무관),
 *   페이지 CSP 아래 컴파일 허용('wasm-unsafe-eval', 97)은 빈 모듈 컴파일로 확인.
 * - 배치: color-mix(111)가 없으면 일부가 어긋나 보일 수 있어 업데이트를 권한다(막지는 않음).
 * 막을 때는 index.html의 #compat 안내를 보인다(legacy.js가 둔 함수, 없으면 여기서 직접).
 */
const HEAD = "00 61 73 6d 01 00 00 00 ";
const PROBES = {
  eh: HEAD + "01 04 01 60 00 00 03 02 01 00 0d 03 01 00 00 0a 09 01 07 00 06 40 07 00 0b 0b",   // 태그 + try/catch(95)
  ref: HEAD + "01 05 01 60 00 01 6f 03 02 01 00 0a 06 01 04 00 d0 6f 0b",                      // ref.null extern(96)
  simd: HEAD + "01 05 01 60 00 01 7b 03 02 01 00 0a 16 01 14 00 fd 0c" + " 00".repeat(16) + " 0b",   // v128.const(91)
};
const bytes = (s) => new Uint8Array(s.trim().split(/\s+/).map((x) => parseInt(x, 16)));

/** 시작을 막아야 하는 문제("ui"·"wasm"). 없으면 null. */
export function hardProblem(engineMode) {
  if (typeof Element.prototype.replaceChildren !== "function") return "ui";
  if (!engineMode) return null;   // PC(로컬 서버)는 엔진을 쓰지 않는다
  if (typeof WebAssembly !== "object" || typeof WebAssembly.validate !== "function") return "wasm";
  for (const k of Object.keys(PROBES)) {
    try {
      if (!WebAssembly.validate(bytes(PROBES[k]))) return "wasm";
    } catch (e) {
      return "wasm";
    }
  }
  return null;
}

/** 페이지 CSP 아래 웹어셈블리 컴파일이 되는가(97). */
export async function wasmAllowed() {
  try {
    await WebAssembly.compile(bytes(HEAD));
    return true;
  } catch (e) {
    return false;
  }
}

/** 배치 기능이 모두 있는가(111). */
export function layoutOk() {
  try {
    return CSS.supports("color", "color-mix(in srgb, red 50%, blue)");
  } catch (e) {
    return false;
  }
}

/** 막는 안내를 보인다. */
export function showCompat(reason) {
  if (typeof window.__safepauseShowCompat === "function") {
    window.__safepauseShowCompat(reason);
    return;
  }
  const box = document.getElementById("compat");
  if (!box) return;
  const app = Boolean(window.SafePauseNative || window.__SAFEPAUSE_ENGINE__);
  for (const el of box.querySelectorAll("[data-for]")) el.hidden = el.getAttribute("data-for") !== (app ? "app" : "pc");
  box.setAttribute("data-reason", reason);
  const root = document.getElementById("app");
  if (root) root.hidden = true;
  box.hidden = false;
}
