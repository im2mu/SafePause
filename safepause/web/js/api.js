/* SafePause API 호출. 화면 코드는 전달 방식을 모른다.
 * - PC(Windows exe): 같은 컴퓨터의 로컬 서버(127.0.0.1)에 fetch. 세션 토큰을 머리글로 붙인다.
 * - 안드로이드 앱: 앱 안 파이썬 엔진(Pyodide, 웹 워커)에 메시지로 보낸다(인터넷 없음).
 * 두 방식 모두 같은 경로·같은 JSON을 쓰고, 파이썬 쪽은 같은 서비스 계층(safepause.api)이 처리한다.
 */
import { engine } from "./engine-client.js";

/** 화면을 떠났거나 데이터가 지워진 뒤 늦게 온 응답(화면은 조용히 버린다). */
export const STALE = Symbol("stale");

export class ApiError extends Error {
  constructor(status, message, extra = {}) {
    super(message);
    this.status = status;
    this.extra = extra;
  }
}

export const CONSENT_REQUIRED = 403;
export function isConsentError(err) { return err instanceof ApiError && err.status === CONSENT_REQUIRED && /동의/.test(err.message); }

// ---- PC: 로컬 서버 토큰 ----------------------------------------------------------
// 서버가 브라우저를 열 때 주소 뒤(#k=…)에 준 일회성 토큰. 주소창에서는 바로 지운다(화면 공유·기록에 남지 않게).
const TOKEN_KEY = "safepause.k";
function takeToken() {
  let token = "";
  const m = /(?:^|[#&])k=([A-Za-z0-9_-]{16,128})/.exec(location.hash || "");
  if (m) {
    token = m[1];
    try { sessionStorage.setItem(TOKEN_KEY, token); } catch (e) { /* 저장 못 해도 이번 창에서는 씀 */ }
    const rest = location.hash.replace(/(?:^|[#&])k=[A-Za-z0-9_-]+/, "").replace(/^#&?/, "#");
    history.replaceState(null, "", location.pathname + location.search + (rest === "#" ? "" : rest));
  } else {
    try { token = sessionStorage.getItem(TOKEN_KEY) || ""; } catch (e) { token = ""; }
  }
  return token;
}

export const MODE = window.SafePauseNative || window.__SAFEPAUSE_ENGINE__ ? "engine" : "http";
const token = MODE === "http" ? takeToken() : "";

const TIMEOUT_MS = 120000;

async function viaHttp(method, path, body, file) {
  const headers = { Accept: "application/json", "X-SafePause": token || "1" };
  const opts = { method, headers, cache: "no-store", credentials: "same-origin" };
  if (file) {
    const form = new FormData();
    form.append("file", file.blob, file.name || "upload.csv");
    if (file.mapping) form.append("mapping", file.mapping);
    opts.body = form;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  opts.signal = ctrl.signal;
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    const timedOut = e && e.name === "AbortError";
    throw new ApiError(0, timedOut
      ? "응답이 너무 오래 걸려요. 잠시 뒤 다시 해 주세요."
      : "SafePause 프로그램에 연결할 수 없어요. 프로그램 창이 켜져 있는지 확인해 주세요.");
  } finally {
    window.clearTimeout(timer);
  }
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok) {
    const detail = data && typeof data.detail === "string" ? data.detail : `문제가 생겼어요 (${res.status}).`;
    throw new ApiError(res.status, detail, data || {});
  }
  return data;
}

async function viaEngine(method, path, body, file) {
  let payload = body;
  let bytes = null;
  if (file) {
    bytes = new Uint8Array(await file.blob.arrayBuffer());
    payload = { mapping: file.mapping || "" };
  }
  const r = await engine.request({ method, path, body: payload, bytes });
  if (r.status >= 400) {
    const detail = r.body && typeof r.body.detail === "string" ? r.body.detail : `문제가 생겼어요 (${r.status}).`;
    throw new ApiError(r.status, detail, r.body || {});
  }
  return r.body;
}

/** api("GET", "/api/consent") / api("PUT", "/api/consent", {...}) / api("POST", UPLOAD, undefined, {blob, name, mapping}) */
export function api(method, path, body, file) {
  return MODE === "engine" ? viaEngine(method, path, body, file) : viaHttp(method, path, body, file);
}

export const UPLOAD_PATH = "/api/data/upload";
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
