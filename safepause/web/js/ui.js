/* 화면 도우미: DOM 만들기, 아이콘, 토스트, 시트(대화상자), 알림 읽기.
 * - 서버·엔진이 준 글(받는 사람 이름 등)은 모두 textContent로 넣는다(HTML로 해석하지 않음 → XSS 차단).
 * - 시트는 열 때 배경을 inert로 만들고, 닫을 때 초점을 되돌린다. 열린 시트는 안드로이드 뒤로 가기로 닫힌다.
 */
import { PICTO, UI } from "./icons.js";

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/** h("div", {class, text, onclick, ...}, ...children) */
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") el.className = value;
      else if (key === "text") el.textContent = value;
      else if (key === "dataset") Object.assign(el.dataset, value);
      // CSP(style-src 'self')는 style 속성 문자열을 막는다. CSSOM(el.style)으로 넣으면 허용된다.
      else if (key === "style") el.style.cssText = String(value);
      else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
      else if (key === "value" && "value" in el) el.value = value;
      else if (key === "checked" || key === "disabled" || key === "selected") el[key] = Boolean(value);
      else el.setAttribute(key, value === true ? "" : String(value));
    }
  }
  append(el, children);
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

/** 화면용 선 아이콘(24x24). */
export function icon(name, cls = "") {
  const markup = UI[name] || PICTO[name];
  if (!markup) return h("span", { class: "ic", "aria-hidden": "true" });
  return UI[name] ? svgFrom(markup, "0 0 24 24", cls, "2") : svgFrom(markup, "0 0 64 64", cls, "4");
}

/** 쉬운 말 카드 픽토그램(64x64, v0.1 그림). */
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
export function toast(message, kind = "") {
  const root = $("#toast-root");
  if (!root) return;
  window.clearTimeout(toastTimer);
  fill(root, h("div", { class: `toast ${kind}`.trim(), role: kind === "error" ? "alert" : "status", text: message }));
  toastTimer = window.setTimeout(() => root.replaceChildren(), kind === "error" ? 5200 : 3200);
}

// ---- 시트(아래에서 올라오는 창; 넓은 화면은 가운데 창) -------------------------------
const openSheets = [];

function setInert(on) {
  for (const el of $$("#app > *:not(#sheet-root)")) {
    if (on) { el.setAttribute("inert", ""); el.setAttribute("aria-hidden", "true"); } else { el.removeAttribute("inert"); el.removeAttribute("aria-hidden"); }
  }
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
    if (returnFocus && returnFocus.isConnected && typeof returnFocus.focus === "function") returnFocus.focus();
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
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
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
  else if (typeof top.onEscape === "function") top.onEscape();   // 안전 정지 카드: 닫지 않고 '안 보낼래요'로 초점
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

/** 버튼을 잠시 '하는 중' 상태로. */
export async function busy(btn, fn) {
  if (!btn) return fn();
  if (btn.getAttribute("aria-busy") === "true") return undefined;   // 두 번 누름 방지
  btn.setAttribute("aria-busy", "true");
  btn.disabled = true;
  try { return await fn(); } finally {
    if (btn.isConnected) { btn.removeAttribute("aria-busy"); btn.disabled = false; }
  }
}

export function skeleton(n = 3) {
  return h("div", { "aria-hidden": "true" }, Array.from({ length: n }, () => h("div", { class: "skeleton sk-block" })));
}

export function emptyState(iconName, title, text) {
  return h("div", { class: "empty" }, icon(iconName), h("b", { text: title }), text ? h("p", { text }) : null);
}
