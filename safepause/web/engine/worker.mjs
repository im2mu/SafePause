/* SafePause 앱 안 AI 엔진(웹 워커). 안드로이드 앱에서만 쓴다.
 * - Pyodide(웹어셈블리 파이썬)와 numpy·scipy·scikit-learn을 APK 안 파일에서 읽는다(인터넷 없음).
 * - 파이썬 패키지 safepause(PC판과 같은 코드)를 풀고, 저장 폴더 /spdata를 IndexedDB(IDBFS)에 연결한다.
 * - 요청은 한 번에 하나씩 처리한다(파이썬은 단일 스레드). 동의·지우기는 줄 앞쪽(우선 요청끼리는 온 순서대로), 떠난 화면의 조회는 취소.
 *   저장을 바꾸는 요청 뒤에는 IDBFS에 반영한다.
 * 단계: basic(가벼운 요청) → full(AI 분석). AI가 필요한 요청은 full까지 기다린다.
 * 실패(FE-03): 파이썬을 켜지 못하면 error(fatal: true)로 모든 요청을 막는다. AI 부분(numpy·scikit-learn)만 못 켜면
 *   error(fatal: false)로 알리고, 동의 끄기·모두 지우기 같은 기본 요청(BASIC)은 계속 처리한다(AI가 필요한 요청만 503).
 */
import { loadPyodide } from "../pyodide/pyodide.mjs";

// AI 분석 없이 처리하는 가벼운 요청(동의·조력자·상담하는 곳·알림 기록·지우기). 담은 거래·돈 흐름 분석은 거래 분석이 필요해 넣지 않는다
const BASIC = new Set([
  "GET /api/health", "GET /api/consent", "PUT /api/consent", "GET /api/helpers", "PUT /api/helpers",
  "GET /api/counselors", "PUT /api/counselors",
  "GET /api/notices", "POST /api/notices/record", "POST /api/notices/remove", "POST /api/wipe",
  // 내가 한 거예요 표시·확인 기록 지우기: 저장만 바꾸고 분석은 하지 않는다(tests/test_v03_fixplan.py 가벼운 경로 시험)
  "POST /api/reviews", "POST /api/reviews/remove", "POST /api/transactions/remove-checked",
]);

const stage = (s, message, detail = "", fatal = false) => self.postMessage({ type: "stage", stage: s, message, detail, fatal });

let py = null;
let bridge = null;
let fullReady = null;       // Promise: AI 패키지까지 준비

function syncfs(populate) {
  return new Promise((resolve, reject) => py.FS.syncfs(populate, (err) => (err ? reject(err) : resolve())));
}

async function boot() {
  const t0 = performance.now();
  stage("loading", "AI 엔진을 준비하고 있어요", "파이썬 불러오는 중");
  py = await loadPyodide({ indexURL: new URL("../pyodide/", import.meta.url).href, fullStdLib: false });
  py.FS.mkdirTree("/spdata");
  py.FS.mount(py.FS.filesystems.IDBFS, {}, "/spdata");
  await syncfs(true);
  await py.loadPackage(["pydantic"], { messageCallback: () => {}, errorCallback: () => {} });   // 입력 검사(작음)
  const zip = await (await fetch(new URL("../py/safepause.zip", import.meta.url))).arrayBuffer();
  py.unpackArchive(zip, "zip", { extractDir: "/home/pyodide/app" });
  py.runPython("import sys; sys.path.insert(0, '/home/pyodide/app')");
  bridge = py.pyimport("safepause.api.bridge");
  bridge.init("/spdata/store");
  stage("basic", "기본 기능을 쓸 수 있어요", `${Math.round(performance.now() - t0)}ms`);

  fullReady = (async () => {
    stage("basic", "AI 분석 준비 중이에요", "numpy·scikit-learn 불러오는 중");
    await py.loadPackage(["numpy", "scipy", "scikit-learn"], { messageCallback: () => {}, errorCallback: () => {} });
    bridge.warm();
    stage("full", "AI 분석까지 준비됐어요", `${Math.round(performance.now() - t0)}ms`);
  })();
  // AI 부분만 실패: 기본 요청은 계속 받는다(fatal false)
  fullReady.catch((e) => stage("error", "AI 분석 부분을 켜지 못했어요", String(e && e.message || e), false));
}

const booted = boot().catch((e) => {
  stage("error", "AI 엔진을 켜지 못했어요", String(e && e.message || e), true);
  throw e;
});

function routeKey(method, path) {
  return `${method.toUpperCase()} ${path.split("?")[0]}`;
}

// 동의 끄기·모두 지우기(즉시 철회, S37)는 기다리는 줄의 앞쪽에 넣는다.
// 파이썬은 한 번에 하나만 돌므로 이미 돌고 있는 계산(예: 성능 확인)은 끝나야 하지만, 줄에 쌓인 다른 요청보다 먼저 처리된다.
// 우선 요청끼리는 온 순서대로(FIFO) 처리한다(FE-05: 동의를 켰다 끄면 마지막 선택인 끄기가 남아야 한다).
const PRIORITY = new Set(["PUT /api/consent", "POST /api/wipe"]);
const queue = [];
let running = false;

async function run(msg) {
  const key = routeKey(msg.method, msg.path);
  let raw;   // undefined → 파이썬 None (JS null은 None이 아닌 jsnull로 넘어간다)
  if (msg.bytes) raw = py.toPy(msg.bytes);
  try {
    const out = bridge.handle(msg.method, msg.path, JSON.stringify(msg.body ?? null), raw);
    const res = JSON.parse(out);
    if (msg.method !== "GET") {
      try { await syncfs(false); } catch (e) {
        return { status: 500, body: { detail: "이 휴대폰에 저장하지 못했어요. 저장 공간이 넉넉한지 확인해 주세요." } };
      }
    }
    return res;
  } catch (e) {
    return { status: 500, body: { detail: "처리하다 문제가 생겼어요. 다시 해 주세요.", error: String(e && e.message || e).slice(0, 500), route: key } };
  } finally {
    if (raw && typeof raw.destroy === "function") raw.destroy();
  }
}

function reply(msg, res) {
  self.postMessage({ type: "response", id: msg.id, status: res.status, body: res.body });
}

async function pump() {
  if (running) return;
  const msg = queue.shift();
  if (!msg) return;
  running = true;
  try {
    reply(msg, await run(msg));
  } catch (e) {
    reply(msg, { status: 500, body: { detail: "처리하다 문제가 생겼어요. 다시 해 주세요." } });
  } finally {
    running = false;
    pump();
  }
}

function enqueue(msg) {
  if (PRIORITY.has(routeKey(msg.method, msg.path))) {
    msg.priority = true;
    let i = 0;
    while (i < queue.length && queue[i].priority) i += 1;   // 앞서 온 우선 요청 바로 뒤
    queue.splice(i, 0, msg);
  } else {
    queue.push(msg);
  }
  pump();
}

async function accept(msg) {
  try {
    await booted;
  } catch (e) {
    reply(msg, { status: 503, body: { detail: "AI 엔진을 켜지 못했어요. 앱을 닫았다가 다시 열어 주세요." } });
    return;
  }
  if (!BASIC.has(routeKey(msg.method, msg.path))) {
    // AI가 필요한 요청은 줄 밖에서 준비를 기다린다(그동안 동의·조력자 같은 가벼운 요청은 바로 처리됨)
    try { await fullReady; } catch (e) {
      reply(msg, { status: 503, body: { detail: "AI 분석 부분을 켜지 못했어요. 앱을 닫았다가 다시 열어 주세요." } });
      return;
    }
  }
  if (msg.cancelled) { reply(msg, { status: 499, body: { detail: "화면을 떠나 요청을 취소했어요." } }); return; }
  enqueue(msg);
}

const waiting = new Set();   // AI 준비를 기다리는 요청(아직 줄에 넣지 않음)

self.onmessage = (e) => {
  const msg = e.data || {};
  if (msg.type === "cancel-reads") {
    for (let i = queue.length - 1; i >= 0; i -= 1) {
      if (queue[i].method === "GET") {
        const [m] = queue.splice(i, 1);
        reply(m, { status: 499, body: { detail: "화면을 떠나 요청을 취소했어요." } });
      }
    }
    for (const m of waiting) if (m.method === "GET") m.cancelled = true;
    return;
  }
  if (msg.type !== "request") return;
  waiting.add(msg);
  accept(msg).finally(() => waiting.delete(msg));
};
