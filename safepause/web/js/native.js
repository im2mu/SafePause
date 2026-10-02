/* 기기 기능 한곳 모음: 문자·메일·전화 앱 열기, 연락처에서 고르기, 내 은행 앱 열기, 글 복사, 접속 환경(앱·휴대폰·컴퓨터).
 * - 안드로이드 앱: SafePauseNative 브리지(openExternal·pickContact·listApps·openApp·capabilities). 새 권한 없이 시스템 창·앱만 연다.
 * - 브라우저: 메일·전화는 링크로 열고, 문자는 휴대폰 브라우저에서만 연다. 연락처는 브라우저가 지원할 때만 고른다.
 * 화면은 이 모듈만 부르고 브리지를 직접 부르지 않는다(옛 앱에 없는 함수는 false·null로 돌아온다).
 */
import { toast } from "./ui.js";

const bridge = () => window.SafePauseNative || null;
const ALLOWED = /^(sms|smsto|mailto|tel):/i;

/** 안드로이드 앱(또는 앱 묶음 화면)에서 열렸으면 true. */
export function isApp() {
  return Boolean(window.SafePauseNative || window.__SAFEPAUSE_ENGINE__);
}

/** 휴대폰(앱 또는 휴대폰 브라우저)이면 true. */
export function isMobile() {
  if (isApp()) return true;
  const ua = navigator.userAgent || "";
  if (/Android|iPhone|iPad|iPod|Mobile/i.test(ua)) return true;
  if (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1) return true;   // iPadOS는 맥처럼 알린다
  return Boolean(navigator.userAgentData && navigator.userAgentData.mobile);
}

function nativeCaps() {
  const n = bridge();
  if (!n || typeof n.capabilities !== "function") return {};
  try { return JSON.parse(n.capabilities()) || {}; } catch (e) { return {}; }
}

function browserContacts() {
  return Boolean(navigator.contacts && typeof navigator.contacts.select === "function" && "ContactsManager" in window);
}

/**
 * 이 휴대폰(또는 컴퓨터)에서 할 수 있는 일.
 * {app, mobile, sms, email, call, contacts, apps, tts}
 * - sms: 문자 앱을 열 수 있음(앱·휴대폰 브라우저). PC는 false.
 * - apps: 설치된 앱 목록에서 내 은행 앱을 고르고 열 수 있음(안드로이드 앱만, canListApps()와 같음).
 * - call: 전화 걸기 화면을 열 수 있음(앱·휴대폰 브라우저). PC는 false.
 * - contacts: 연락처에서 고르기를 쓸 수 있음(canPickContact()와 같음).
 * - tts: 기기 음성이 있음(실제 재생 가능 여부는 speech.available()).
 */
export function capabilities() {
  const n = bridge();
  const mobile = isMobile();
  if (n) {
    const c = nativeCaps();
    const external = Boolean(c.external) && typeof n.openExternal === "function";
    const has = (key) => external && (c[key] === undefined ? true : Boolean(c[key]));   // 그 일을 할 앱이 기기에 있는지
    return {
      app: true, mobile: true, sms: has("sms"), email: has("email"), call: has("dial"),
      contacts: Boolean(c.contacts) && typeof n.pickContact === "function",
      apps: canListApps(),
      tts: c.tts === undefined ? safeTts(n) : Boolean(c.tts),
    };
  }
  return {
    app: isApp(), mobile, sms: mobile, email: true, call: mobile,
    contacts: browserContacts(), apps: false, tts: "speechSynthesis" in window,
  };
}

function safeTts(n) {
  try { return typeof n.ttsStatus === "function" && n.ttsStatus() === "ready"; } catch (e) { return false; }
}

/**
 * 문자·메일·전화 앱을 연다. sms:·smsto:·mailto:·tel:만 받는다.
 * 앱은 브리지로 열고, 브라우저는 링크로 연다(PC에서 문자는 열 수 없어 false).
 * 돌려주는 값: 열기를 시작했으면 true, 못 열면 false(화면은 글 복사하기를 보인다).
 */
export function openExternal(uri) {
  const u = String(uri || "");
  if (!ALLOWED.test(u)) return false;
  const n = bridge();
  if (n) {
    if (typeof n.openExternal !== "function") return false;
    try { return Boolean(n.openExternal(u)); } catch (e) { return false; }
  }
  if (/^sms/i.test(u) && !isMobile()) return false;
  const a = document.createElement("a");
  a.href = u;
  a.rel = "noopener noreferrer";
  a.hidden = true;
  document.body.append(a);
  try { a.click(); } catch (e) { return false; } finally { a.remove(); }   // 못 열면 화면이 글 복사하기를 보인다
  return true;
}

// ---- 주소 만들기(받는 사람 여러 명, 글은 주소 안에 안전하게 넣는다) ----------------------
const digits = (v) => String(v || "").replace(/[^\d+]/g, "");

/** 문자 앱 주소. smsUri(["010-1234-5678"], "글") → "smsto:01012345678?body=..." */
export function smsUri(numbers, body = "") {
  const to = [].concat(numbers || []).map(digits).filter(Boolean).join(";");
  return `smsto:${to}${body ? `?body=${encodeURIComponent(body)}` : ""}`;
}

/** 메일 앱 주소. mailtoUri(["a@b.kr"], "제목", "글") */
export function mailtoUri(emails, subject = "", body = "") {
  const to = [].concat(emails || []).map((e) => String(e || "").trim()).filter(Boolean)
    .map((e) => e.replace(/[^\w.+@-]/g, (ch) => encodeURIComponent(ch))).join(",");
  const q = [subject ? `subject=${encodeURIComponent(subject)}` : "", body ? `body=${encodeURIComponent(body)}` : ""].filter(Boolean).join("&");
  return `mailto:${to}${q ? `?${q}` : ""}`;
}

/** 전화 걸기 화면 주소(전화를 걸지는 않고 번호만 채운다). */
export function telUri(number) {
  return `tel:${digits(number)}`;
}

// ---- 연락처에서 고르기 ---------------------------------------------------------------
// 한 번에 한 창만 연다(IA-5·AND-08): 창이 열려 있는 동안 다시 누르면 새 창을 열지 않고(앞 창의 결과를 지키고) 안내만 한다.
let pending = null;       // {kind, resolve, timer}: 연락처 창 결과를 기다리는 중
let lastPick = "none";    // 마지막 결과: ok | cancelled | busy | failed | unsupported
const PICK_WAIT_MS = 5 * 60 * 1000;   // 결과가 끝내 오지 않으면(앱이 창을 잃음) 이 시간 뒤 기다림을 푼다
export const PICK_TEXT = {
  busy: "연락처 창이 이미 열려 있어요. 그 창에서 골라 주세요.",
  failed: "연락처를 불러오지 못했어요. 직접 적어 주세요.",
};

function finishPick(value, reason) {
  const p = pending;
  pending = null;
  if (!p) return false;
  window.clearTimeout(p.timer);
  lastPick = reason;
  if (reason === "failed") toast(PICK_TEXT.failed, "error");
  p.resolve(value);
  return true;
}

window.__safepauseContactPicked = (raw) => {
  let r = raw;
  if (typeof r === "string") { try { r = JSON.parse(r); } catch (e) { r = null; } }
  if (!r) { finishPick(null, "failed"); return; }
  if (r.cancelled) { finishPick(null, "cancelled"); return; }
  if (r.error || !r.value) { finishPick(null, "failed"); return; }
  finishPick({ name: String(r.name || ""), value: String(r.value) }, "ok");
};

/** 연락처에서 고르기를 쓸 수 있으면 true(못 쓰면 화면은 버튼을 숨긴다). */
export function canPickContact() {
  const n = bridge();
  if (n) return capabilities().contacts;
  return browserContacts();
}

/** 마지막 pickContact의 결과: "ok" | "cancelled" | "busy" | "failed" | "unsupported" (null이 왜 왔는지 화면이 알 때 씀). */
export function lastPickResult() { return lastPick; }

/**
 * 휴대폰 연락처에서 한 사람의 번호(kind "phone") 또는 메일(kind "email")을 고른다.
 * 돌려주는 값: Promise<{name, value} | null>. 연락처 전체를 읽지 않는다.
 * - 취소하면 null(안내 없음).
 * - 창이 이미 열려 있으면 두 번째 호출은 새 창을 열지 않고 안내 토스트와 함께 null(앞 창의 결과는 앞 호출이 받는다).
 * - 못 열었거나 읽지 못했으면 안내 토스트와 함께 null. 이유는 lastPickResult()로 알 수 있다.
 */
export function pickContact(kind) {
  const k = kind === "email" ? "email" : "phone";
  const n = bridge();
  if (pending) {
    lastPick = "busy";
    toast(PICK_TEXT.busy);
    return Promise.resolve(null);
  }
  if (n && typeof n.pickContact === "function") {
    return new Promise((resolve) => {
      const entry = { kind: k, resolve, timer: 0 };
      pending = entry;
      entry.timer = window.setTimeout(() => { if (pending === entry) finishPick(null, "failed"); }, PICK_WAIT_MS);
      let started;
      try { started = n.pickContact(k); } catch (e) { started = false; }
      if (started === false && pending === entry) finishPick(null, "failed");
    });
  }
  if (!n && browserContacts()) {
    return new Promise((resolve) => {
      const entry = { kind: k, resolve, timer: 0 };
      pending = entry;
      navigator.contacts.select(["name", k === "email" ? "email" : "tel"], { multiple: false })
        .then((list) => {
          const c = list && list[0];
          if (!c) { finishPick(null, "cancelled"); return; }
          const values = (k === "email" ? c.email : c.tel) || [];
          if (!values[0]) { finishPick(null, "failed"); return; }
          finishPick({ name: String((c.name || [])[0] || ""), value: String(values[0]) }, "ok");
        })
        .catch(() => finishPick(null, "failed"));
    });
  }
  lastPick = "unsupported";
  return Promise.resolve(null);
}

// ---- 내 은행 앱(설치된 앱 목록에서 본인이 고른 앱을 연다) ------------------------------
// 안드로이드 패키지 이름 모양(com.example.app). 다른 글은 브리지에 넘기지 않는다
const PACKAGE_RE = /^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$/;
const MAX_APPS = 2000;

/** 설치된 앱 목록을 읽고 열 수 있으면 true(안드로이드 앱만). PC·휴대폰 브라우저·옛 앱은 false. */
export function canListApps() {
  const n = bridge();
  if (!n || typeof n.listApps !== "function" || typeof n.openApp !== "function") return false;
  const c = nativeCaps();
  return c.apps === undefined ? true : Boolean(c.apps);
}

/**
 * 홈 화면에 아이콘이 있는 앱 목록 [{package, label}](앱이 정한 순서 그대로). 은행 이름을 앱에 넣지 않고,
 * 본인이 이 목록에서 자기 은행 앱을 한 번 고른다. 못 읽으면 빈 목록.
 */
export function listApps() {
  if (!canListApps()) return [];
  let raw;
  try { raw = bridge().listApps(); } catch (e) { return []; }
  let list = raw;
  if (typeof raw === "string") { try { list = JSON.parse(raw); } catch (e) { return []; } }
  if (!Array.isArray(list)) return [];
  const seen = new Set();
  const out = [];
  for (const x of list) {
    const pkg = String((x && x.package) || "");
    // 앱 이름은 한 줄, 80글자까지(MainActivity.cleanLabel과 같은 한도, 글자 단위로 잘라 깨진 글자가 없게)
    const label = Array.from(String((x && x.label) || "").replace(/\s+/g, " ").trim()).slice(0, 80).join("");
    if (!PACKAGE_RE.test(pkg) || seen.has(pkg)) continue;
    seen.add(pkg);
    out.push({ package: pkg, label: label || pkg });
    if (out.length >= MAX_APPS) break;
  }
  return out;
}

/** 그 앱을 연다. 열기를 시작했으면 true, 앱이 없거나 못 열면 false. */
export function openApp(pkg) {
  const n = bridge();
  const p = String(pkg || "");
  if (!n || typeof n.openApp !== "function" || !PACKAGE_RE.test(p)) return false;
  try { return Boolean(n.openApp(p)); } catch (e) { return false; }
}

// ---- 글 복사 ---------------------------------------------------------------------
/** 글을 클립보드에 복사한다. Promise<boolean>. */
export async function copyText(text) {
  const t = String(text ?? "");
  try {
    if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(t); return true; }
  } catch (e) { /* 아래 옛 방식으로 */ }
  const back = document.activeElement;
  const ta = document.createElement("textarea");
  ta.value = t;
  ta.setAttribute("readonly", "");
  ta.className = "sr-only";
  document.body.append(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  ta.remove();
  if (back && typeof back.focus === "function") back.focus();
  return ok;
}
