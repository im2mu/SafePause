/* 화면 도우미: DOM 만들기, 아이콘, 토스트, 시트(대화상자), 알림 읽기, 앱 설정(글자 크기·화면 모드).
 * - 서버·엔진이 준 글(받는 사람 이름 등)은 모두 textContent로 넣는다(HTML로 해석하지 않음 → XSS 차단).
 * - 시트는 열 때 배경을 inert로 만들고, 닫을 때 초점을 연 버튼으로 되돌린다(그 버튼이 없어졌으면 위 시트 제목·본문). 열린 시트는 안드로이드 뒤로 가기로 닫힌다.
 * - 시트 안의 소리로 듣기는 시트를 닫으면 멈춘다(components.speakButton이 버튼이 화면에서 떨어지는 것을 보고 멈춤).
 * - 설명 글(p)은 한 문장에 한 줄씩 보인다: h("p", {text})가 문장 끝에서 나눠 span.sent로 넣는다(data-nosplit이면 그대로).
 */
import { PICTO, UI } from "./icons.js";

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/** h("div", {class, text, onclick, ...}, ...children). p의 text는 문장마다 한 줄(span.sent)로 나눈다. */
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  let text;
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") el.className = value;
      else if (key === "text") text = value;
      else if (key === "dataset") Object.assign(el.dataset, value);
      // CSP(style-src 'self')는 style 속성 문자열을 막는다. CSSOM(el.style)으로 넣으면 허용된다.
      else if (key === "style") el.style.cssText = String(value);
      else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
      else if (key === "value" && "value" in el) el.value = value;
      else if (key === "checked" || key === "disabled" || key === "selected") el[key] = Boolean(value);
      else el.setAttribute(key, value === true ? "" : String(value));
    }
  }
  if (text !== undefined) setText(el, text);
  append(el, children);
  return el;
}

// 문장 끝: 한글·닫는 괄호 뒤의 . ? ! 또는 ? ! 다음의 빈칸(1.5만·v0.3.0 같은 숫자 속 점은 나누지 않음)
const SENT_SPLIT = /(?<=[가-힣)\]][.?!]|[?!])\s+(?=\S)/;

/** 글을 문장 단위로 나눈다. "A요. B요." → ["A요.", "B요."] */
export function splitSentences(text) {
  return String(text ?? "").split(SENT_SPLIT).filter((x) => x !== "");
}

/** 글을 넣는다. p(문단)는 문장마다 span.sent(한 줄)로 나눈다. data-nosplit이 있으면 나누지 않는다. */
export function setText(el, text) {
  const s = text === null || text === undefined ? "" : String(text);
  const parts = el.tagName === "P" && !el.hasAttribute("data-nosplit") ? splitSentences(s) : [];
  if (parts.length < 2) { el.textContent = s; return el; }
  // 문장 사이 빈칸은 span 끝에 남겨 둔다(복사·소리로 읽기에서 문장이 붙지 않게)
  el.replaceChildren(...parts.map((part, i) => {
    const sp = document.createElement("span");
    sp.className = "sent";
    sp.textContent = i < parts.length - 1 ? `${part} ` : part;
    return sp;
  }));
  return el;
}

export function append(el, children) {
  for (const child of [children].flat(Infinity)) {
    if (child === null || child === undefined || child === false || child === "") continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function fill(el, ...children) {
  el.replaceChildren();
  return append(el, children);
}

const SVG_NS = "http://www.w3.org/2000/svg";

function svgFrom(markup, viewBox, cls, stroke) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", viewBox);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", stroke);
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  if (cls) svg.setAttribute("class", cls);
  // 아이콘 문자열은 이 앱 소스(icons.js)의 고정 값뿐이다(외부 입력 아님)
  const doc = new DOMParser().parseFromString(`<svg xmlns="${SVG_NS}">${markup}</svg>`, "image/svg+xml");
  for (const node of Array.from(doc.documentElement.childNodes)) svg.append(document.importNode(node, true));
  return svg;
}

/**
 * 화면용 선 아이콘(24x24, 굵기 2). 이름이 UI에 없으면 빈 자리(span.ic)를 돌려준다.
 * check·warning·stop·person 같은 픽토그램 이름도 UI의 선 버전으로 그린다(D4: 선 아이콘 체계 하나).
 */
export function icon(name, cls = "") {
  const markup = UI[name];
  if (!markup) return h("span", { class: "ic", "aria-hidden": "true" });
  return svgFrom(markup, "0 0 24 24", cls, "2");
}

/** 쉬운 말 카드 픽토그램(64x64, v0.1 그림). 돈 보내기 확인 카드 본문의 큰 그림에만 쓴다. */
export function picto(name, cls = "picto") {
  const markup = PICTO[name];
  return markup ? svgFrom(markup, "0 0 64 64", cls, "4") : null;
}

// ---- 알림(스크린리더) -------------------------------------------------------
export function announce(message) {
  const el = $("#announcer");
  if (!el) return;
  el.textContent = "";
  window.setTimeout(() => { el.textContent = message; }, 60);
}

// ---- 토스트 -----------------------------------------------------------------
let toastTimer = 0;
/** 잠깐 보이는 알림 글. 문장이 여럿이면 한 문장에 한 줄(p → span.sent, C4). 문장 수만큼 조금 더 오래 보인다. */
export function toast(message, kind = "") {
  const root = $("#toast-root");
  if (!root) return;
  window.clearTimeout(toastTimer);
  const n = splitSentences(message).length;
  fill(root, h("div", { class: `toast ${kind}`.trim(), role: kind === "error" ? "alert" : "status" }, h("p", { text: message })));
  toastTimer = window.setTimeout(() => root.replaceChildren(), (kind === "error" ? 5200 : 3200) + Math.max(0, n - 1) * 1500);
}

// ---- 시트(아래에서 올라오는 창; 넓은 화면은 가운데 창) -------------------------------
const openSheets = [];

function setInert(on) {
  for (const el of $$("#app > *:not(#sheet-root)")) {
    if (on) { el.setAttribute("inert", ""); el.setAttribute("aria-hidden", "true"); } else { el.removeAttribute("inert"); el.removeAttribute("aria-hidden"); }
  }
}

/** 초점을 줄 수 있는 상태인지(붙어 있고, 꺼지지 않았고, 숨겨지지 않음). */
function focusable(el) {
  return Boolean(el && el !== document.body && el.isConnected && typeof el.focus === "function"
    && !el.disabled && !el.closest("[inert]") && !el.closest("[hidden]"));
}

/**
 * 시트를 닫은 뒤 초점을 돌려줄 곳(FE-04·FN-07): 연 버튼 → (그 버튼이 없어졌거나 꺼졌으면) 아직 열린 위 시트의 제목 → 본문.
 * 초점이 body로 빠지지 않게 한다.
 */
function restoreFocus(returnFocus) {
  if (focusable(returnFocus)) { returnFocus.focus(); return; }
  const top = openSheets[openSheets.length - 1];
  if (top) {
    const t = $(".focus-target", top.el) || top.el;
    t.focus({ preventScroll: true });
    return;
  }
  const main = $("#main");
  if (main) main.focus({ preventScroll: true });
}

/**
 * 시트를 연다. build(close)는 시트 안의 노드를 돌려준다.
 * opts: {label, dismissible(기본 true), className, onClose, initialFocus}
 * 돌려주는 값: {close, el}
 */
export function openSheet(build, opts = {}) {
  const root = $("#sheet-root");
  const returnFocus = document.activeElement;
  const dismissible = opts.dismissible !== false;
  const sheet = h("div", {
    class: `sheet ${opts.className || ""}`.trim(), role: "dialog", "aria-modal": "true",
    "aria-label": opts.label || null, tabindex: "-1",
  });
  const overlay = h("div", { class: "overlay" }, sheet);
  let closed = false;
  const entry = { close: () => close("api"), dismissible, el: sheet, onEscape: opts.onEscape };

  function close(reason = "api") {
    if (closed) return;
    closed = true;
    overlay.remove();
    const i = openSheets.indexOf(entry);
    if (i >= 0) openSheets.splice(i, 1);
    if (!openSheets.length) { setInert(false); document.body.style.overflow = ""; }
    document.removeEventListener("keydown", onKey, true);
    if (typeof opts.onClose === "function") opts.onClose(reason);
    // onClose가 다른 시트를 열었으면 그 시트가 초점을 가진다
    if (openSheets.length && openSheets[openSheets.length - 1].el.contains(document.activeElement)) return;
    restoreFocus(returnFocus);
  }

  function onKey(e) {
    if (openSheets[openSheets.length - 1] !== entry) return;
    if (e.key === "Escape") {
      e.preventDefault();
      if (dismissible) close("escape");
      else if (typeof opts.onEscape === "function") opts.onEscape();
      return;
    }
    if (e.key !== "Tab") return;
    const items = $$("button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex='-1'].focus-target", sheet)
      .filter((x) => x.offsetParent !== null || x === document.activeElement);
    if (!items.length) { e.preventDefault(); sheet.focus(); return; }
    const first = items[0], last = items[items.length - 1];
    // 초점이 시트 밖(body 등)에 있으면 시트 안으로 끌어온다(본문으로 바로 가기 링크로 나가지 않게, FE-04)
    if (!sheet.contains(document.activeElement)) { e.preventDefault(); (e.shiftKey ? last : first).focus(); return; }
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  overlay.addEventListener("click", (e) => { if (e.target === overlay && dismissible) close("scrim"); });
  append(sheet, build(close));
  root.append(overlay);
  openSheets.push(entry);
  setInert(true);
  document.body.style.overflow = "hidden";
  document.addEventListener("keydown", onKey, true);
  const target = (opts.initialFocus && $(opts.initialFocus, sheet)) || $(".focus-target", sheet) || sheet;
  window.requestAnimationFrame(() => target.focus());
  entry.close = () => close("api");
  return { close: () => close("api"), el: sheet };
}

/** 안드로이드 뒤로 가기: 맨 위 시트를 닫으면 true. */
export function closeTopSheet() {
  const top = openSheets[openSheets.length - 1];
  if (!top) return false;
  if (top.dismissible) top.close();
  else if (typeof top.onEscape === "function") top.onEscape();   // 닫을 수 없는 시트(저장 안 한 입력 등): 시트가 정한 동작
  return true;   // 닫을 수 없는 시트는 뒤로 가기로 앞 화면에 넘어가지 않게 삼킨다
}

export function closeAllSheets() {
  while (openSheets.length) openSheets[openSheets.length - 1].close();
}

/** 확인 창. 안전한 선택(취소)에 먼저 초점을 둔다. */
export function confirmSheet({ title, lines = [], confirmText, cancelText = "아니요", danger = false }) {
  return new Promise((resolve) => {
    let result = false;
    openSheet((close) => [
      h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: title }),
      lines.map((t) => h("p", { class: "sheet-sub", text: t })),
      h("div", { class: "sheet-actions" },
        h("button", { type: "button", class: `btn big block ${danger ? "danger" : "primary"}`, text: confirmText,
          onclick: () => { result = true; close(); } }),
        h("button", { type: "button", class: "btn big block", "data-cancel": "1", text: cancelText, onclick: () => close() })),
    ], { label: title, initialFocus: "[data-cancel]", onClose: () => resolve(result) });
  });
}

/**
 * 버튼을 잠시 하는 중 상태로(두 번 누름 방지). disabled를 쓰지 않는다: 누른 버튼이 꺼지면 초점이 body로 빠지고,
 * 그 안에서 연 확인 시트가 닫힐 때 초점을 돌려줄 곳이 없어진다(FE-04·FN-07). 대신 aria-busy·aria-disabled로 막는다.
 */
export async function busy(btn, fn) {
  if (!btn) return fn();
  if (btn.getAttribute("aria-busy") === "true") return undefined;   // 두 번 누름 방지
  btn.setAttribute("aria-busy", "true");
  btn.setAttribute("aria-disabled", "true");
  try { return await fn(); } finally {
    btn.removeAttribute("aria-busy");
    btn.removeAttribute("aria-disabled");
  }
}

export function skeleton(n = 3) {
  return h("div", { "aria-hidden": "true" }, Array.from({ length: n }, () => h("div", { class: "skeleton sk-block" })));
}

export function emptyState(iconName, title, text) {
  return h("div", { class: "empty" }, icon(iconName), h("b", { text: title }), text ? h("p", { text }) : null);
}

// ---- 준비 중 기능 --------------------------------------------------------------
/** 준비 중 기능에 늘 붙이는 문장. */
export const SOON_TEXT = "정식 버전에서 열려요.";

/** 준비 중 배지(목록·시트 제목 옆). */
export function soonBadge() {
  return h("span", { class: "soon", text: "준비 중" });
}

/**
 * 준비 중 기능 안내 시트. 동작하는 척하지 않고, 정식 버전에서 할 일을 비활성으로 보여 준다.
 * opts: {icon, title, lines[], steps?: [{title, sub?, options?: []}], action?: "연결하기", extra?: Node | (close) => Node}
 * - action이 있으면 "연결하기(준비 중)" 비활성 버튼을 둔다.
 * - extra는 지금 쓸 수 있는 다른 방법(버튼 등)을 넣는 자리다.
 * 돌려주는 값: openSheet와 같은 {close, el}
 */
export function comingSoonSheet({ icon: ic = "info", title, lines = [], steps = [], action = "", extra = null } = {}) {
  return openSheet((close) => [
    h("div", { class: "soon-head" }, h("span", { class: "soon-icon" }, icon(ic)), soonBadge()),
    h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: title }),
    lines.length ? h("div", { class: "soon-lines" }, lines.map((t) => h("p", { text: t }))) : null,
    steps.length ? h("ol", { class: "soon-steps", "aria-label": "정식 버전에서 하는 순서" }, steps.map((st, i) => h("li", { class: "soon-step", "aria-disabled": "true" },
      h("span", { class: "soon-step-no", "aria-hidden": "true", text: String(i + 1) }),
      h("div", { class: "soon-step-main" },
        h("b", { text: st.title }),
        st.sub ? h("p", { class: "muted", text: st.sub }) : null,
        st.options && st.options.length ? h("div", { class: "soon-options" }, st.options.map((o) => h("span", { class: "chip off", "aria-disabled": "true", text: o }))) : null)))) : null,
    h("div", { class: "notice" }, icon("info"), h("p", { text: SOON_TEXT })),
    typeof extra === "function" ? extra(close) : extra,
    h("div", { class: "sheet-actions" },
      action ? h("button", { type: "button", class: "btn primary big block", disabled: true, text: `${action}(준비 중)` }) : null,
      h("button", { type: "button", class: "btn big block", text: "닫기", onclick: () => close() })),
  ], { label: title });
}

// ---- 탭(segmented) -------------------------------------------------------------
/**
 * 한 줄 탭. items: [{value, label, icon?, count?}], onChange(value)는 탭을 바꿀 때 불린다.
 * opts: {label(탭 묶음 이름), controls(바뀌는 영역 id)}
 * 돌려주는 값: {el, set(value)}  (set은 onChange를 부르지 않는다)
 */
export function segTabs(items, active, onChange, { label = "보기", controls = null } = {}) {
  const el = h("div", { class: "seg-tabs", role: "tablist", "aria-label": label });
  const buttons = items.map((it) => h("button", {
    type: "button", class: "seg-tab", role: "tab", "data-v": it.value, "aria-controls": controls,
    onclick: () => choose(it.value, false),
  }, it.icon ? icon(it.icon) : null, h("span", { text: it.label }),
  it.count === undefined || it.count === null ? null : h("span", { class: "seg-count", text: String(it.count) })));
  append(el, buttons);
  el.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight" && e.key !== "Home" && e.key !== "End") return;
    const i = buttons.indexOf(document.activeElement);
    if (i < 0) return;
    e.preventDefault();
    const n = buttons.length;
    const next = e.key === "Home" ? 0 : e.key === "End" ? n - 1 : (i + (e.key === "ArrowRight" ? 1 : -1) + n) % n;
    choose(buttons[next].dataset.v, true);
  });
  function set(value) {
    for (const b of buttons) {
      const on = b.dataset.v === String(value);
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
    }
  }
  function choose(value, focus) {
    const changed = buttons.some((b) => b.dataset.v === String(value) && b.getAttribute("aria-selected") !== "true");
    set(value);
    if (focus) { const b = buttons.find((x) => x.dataset.v === String(value)); if (b) b.focus(); }
    if (changed && typeof onChange === "function") onChange(value);
  }
  set(active);
  return { el, set };
}

// ---- 앱 설정: 글자 크기·화면 모드(이 휴대폰·이 컴퓨터에만 저장) ---------------------------------
const PREFS = {
  font: { key: "safepause.font", values: ["m", "l", "xl"], fallback: "m" },        // 보통·크게·아주 크게
  theme: { key: "safepause.theme", values: ["auto", "light", "dark"], fallback: "auto" },   // 자동·밝게·어둡게
};
const THEME_BG = { light: "#f2f4f6", dark: "#101013" };

/** getPref("font") → "m"|"l"|"xl", getPref("theme") → "auto"|"light"|"dark". 못 읽으면 기본값. */
export function getPref(name) {
  const p = PREFS[name];
  if (!p) return null;
  let v = null;
  try { v = localStorage.getItem(p.key); } catch (e) { v = null; }
  return p.values.includes(v) ? v : p.fallback;
}

/** 설정을 저장하고 바로 적용한다. 저장을 못 해도(사생활 보호 창 등) 이번 화면에는 적용한다. */
export function setPref(name, value) {
  const p = PREFS[name];
  if (!p || !p.values.includes(value)) return false;
  try { localStorage.setItem(p.key, value); } catch (e) { /* 저장 못 해도 적용은 한다 */ }
  applyPrefs({ [name]: value });
  return true;
}

/** 시작할 때 main.js가 부른다. html[data-font]·html[data-theme]를 맞춘다. */
export function applyPrefs(over = {}) {
  const root = document.documentElement;
  const font = over.font || getPref("font");
  const theme = over.theme || getPref("theme");
  if (font === "m") delete root.dataset.font; else root.dataset.font = font;
  if (theme === "auto") delete root.dataset.theme; else root.dataset.theme = theme;
  for (const meta of $$('meta[name="theme-color"]')) {
    const darkMedia = /dark/.test(meta.getAttribute("media") || "");
    meta.setAttribute("content", theme === "auto" ? THEME_BG[darkMedia ? "dark" : "light"] : THEME_BG[theme]);
  }
  // 안드로이드 앱: 앱 설정의 밝게·어둡게가 기기 설정과 달라도 위아래 시스템 막대 색을 맞춘다(AND-04, 옛 APK에는 함수가 없음)
  try {
    const native = window.SafePauseNative;
    if (native && typeof native.setThemeMode === "function") native.setThemeMode(theme);
  } catch (e) { /* 막대 색만 못 맞춘다 */ }
}
