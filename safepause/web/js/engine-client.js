/* 안드로이드 앱 전용: 앱 안 파이썬 엔진(Pyodide)을 웹 워커에서 돌리고 요청을 주고받는다.
 * 준비 단계: loading → basic(동의·조력자·상담하는 곳·알림 기록 등 가벼운 요청 가능) → full(AI 분석까지 가능) / error.
 * 화면은 기본 단계부터 쓸 수 있고, AI가 필요한 요청은 워커 안에서 full 단계가 될 때까지 기다린다.
 * PC(로컬 서버)에서는 이 모듈을 쓰지 않는다(워커를 만들지 않음).
 */
const listeners = new Set();
let worker = null;
let seq = 0;
const pending = new Map();
const status = { stage: "idle", message: "", detail: "" };

function emit() { for (const fn of listeners) { try { fn({ ...status }); } catch (e) { /* 화면 쪽 오류는 무시 */ } } }

function start() {
  if (worker) return;
  status.stage = "loading";
  status.message = "AI 엔진을 준비하고 있어요";
  emit();
  worker = new Worker(new URL("../engine/worker.mjs", import.meta.url), { type: "module" });
  worker.onmessage = (e) => {
    const m = e.data || {};
    if (m.type === "stage") {
      status.stage = m.stage;
      status.message = m.message || "";
      status.detail = m.detail || "";
      emit();
      return;
    }
    if (m.type === "response") {
      const p = pending.get(m.id);
      if (!p) return;
      pending.delete(m.id);
      p.resolve({ status: m.status, body: m.body });
    }
  };
  worker.onerror = (e) => {
    status.stage = "error";
    status.message = "AI 엔진을 켜지 못했어요";
    status.detail = (e && e.message) || "";
    emit();
    for (const [, p] of pending) p.resolve({ status: 503, body: { detail: "AI 엔진을 켜지 못했어요. 앱을 닫았다가 다시 열어 주세요." } });
    pending.clear();
  };
}

export const engine = {
  start,
  /** 아직 시작하지 않은 조회(GET)를 워커 줄에서 뺀다(저장·동의 같은 쓰기는 빼지 않음). */
  cancelQueuedReads() { if (worker) worker.postMessage({ type: "cancel-reads" }); },
  get status() { return { ...status }; },
  subscribe(fn) { listeners.add(fn); fn({ ...status }); return () => listeners.delete(fn); },
  request({ method, path, body, bytes }) {
    start();
    if (status.stage === "error") {
      return Promise.resolve({ status: 503, body: { detail: "AI 엔진을 켜지 못했어요. 앱을 닫았다가 다시 열어 주세요." } });
    }
    const id = ++seq;
    return new Promise((resolve) => {
      pending.set(id, { resolve });
      const msg = { type: "request", id, method, path, body: body === undefined ? null : body, bytes: bytes || null };
      worker.postMessage(msg, bytes ? [bytes.buffer] : []);
    });
  },
};
