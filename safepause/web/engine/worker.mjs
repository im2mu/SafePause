/* SafePause 앱 안 AI 엔진(웹 워커). 안드로이드 앱에서만 쓴다.
 * - Pyodide(웹어셈블리 파이썬)와 numpy·scipy·scikit-learn을 APK 안 파일에서 읽는다(인터넷 없음).
 * - 파이썬 패키지 safepause(PC판과 같은 코드)를 풀고, 저장 폴더 /spdata를 IndexedDB(IDBFS)에 연결한다.
 * - 요청은 한 번에 하나씩 처리한다(파이썬은 단일 스레드). 동의·지우기는 줄 앞쪽(우선 요청끼리는 온 순서대로), 떠난 화면의 조회는 취소.
 *   저장을 바꾸는 요청 뒤에는 IDBFS에 반영한다.
 * 단계: basic(가벼운 요청) → full(AI 분석). AI가 필요한 요청은 full까지 기다린다.
 * 실패(FE-03): 파이썬을 켜지 못하면 error(fatal: true)로 모든 요청을 막는다. AI 부분(numpy·scikit-learn)만 못 켜면
 *   error(fatal: false)로 알리고, 동의 끄기·모두 지우기 같은 기본 요청(BASIC)은 계속 처리한다(AI가 필요한 요청만 503).
 * 준비 순서(서로 기다릴 까닭이 없는 일은 겹친다): 엔진 묶음(zip) 받기와 pydantic 싣기는 파이썬을 켜는 동안,
 *   AI 패키지 내려받기는 기본 준비(파이썬 모듈 불러오기)와 함께 한다.
 *   full 뒤 요청이 없는 동안에는 첫 분석이 쓰는 큰 모듈(scikit-learn 등)을 한 조각씩 미리 불러 둔다(요청이 늘 먼저).
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

const AI_PACKAGES = ["numpy", "scipy", "scikit-learn"];

async function boot() {
  const t0 = performance.now();
  stage("loading", "AI 엔진을 준비하고 있어요", "파이썬 불러오는 중");
  // 엔진 묶음(zip)은 파이썬을 불러오는 동안 받아 둔다. 받기 실패는 아래 await에서 그대로 난다(그 전에 '처리 안 된 거부'로 남지 않게)
  const zipBytes = fetch(new URL("../py/safepause.zip", import.meta.url)).then((r) => r.arrayBuffer());
  zipBytes.catch(() => {});
  // 입력 검사 패키지(pydantic, 작음)는 packages로 넘겨 파이썬을 켜는 동안 받는다(loadPyodide는 이것까지 실은 뒤 끝난다)
  py = await loadPyodide({ indexURL: new URL("../pyodide/", import.meta.url).href, packages: ["pydantic"], fullStdLib: false });
  py.FS.mkdirTree("/spdata");
  py.FS.mount(py.FS.filesystems.IDBFS, {}, "/spdata");
  await syncfs(true);
  py.unpackArchive(await zipBytes, "zip", { extractDir: "/home/pyodide/app" });
  py.runPython("import sys; sys.path.insert(0, '/home/pyodide/app')");
  // AI 패키지 내려받기를 지금 시작해 아래 모듈 불러오기(동기)와 겹친다. 내려받기 요청이 실제로 나가도록 한 번 양보한다.
  // 설치는 기본 준비가 끝난 뒤 이어진다(loadPyodide 바로 뒤에 시작하면 설치가 저장 폴더 읽기 사이에 끼어 basic이 늦어졌다)
  const loadErrors = [];
  const aiPackages = py.loadPackage(AI_PACKAGES, { messageCallback: () => {}, errorCallback: (m) => { loadErrors.push(String(m)); } });
  aiPackages.catch(() => {});   // 실패는 아래 fullReady에서 그대로 난다
  await new Promise((resolve) => setTimeout(resolve, 0));
  bridge = py.pyimport("safepause.api.bridge");
  bridge.init("/spdata/store");
  stage("basic", "기본 기능을 쓸 수 있어요", `${Math.round(performance.now() - t0)}ms`);

  fullReady = (async () => {
    stage("basic", "AI 분석 준비 중이에요", "numpy·scikit-learn 불러오는 중");
    await aiPackages;
    // loadPackage는 받기·무결성(SRI) 실패에도 예외 없이 끝나고 오류 알림만 보낸다: 실제로 실렸는지 확인해 AI 부분 실패로 알린다
    // (확인하지 않으면 '준비됐어요'를 띄운 뒤 첫 분석에서 import 오류가 난다)
    const missing = AI_PACKAGES.filter((n) => !(py.loadedPackages && py.loadedPackages[n]));
    if (missing.length) throw new Error(`AI 패키지를 싣지 못했어요: ${missing.join(", ")}${loadErrors.length ? ` (${loadErrors[0].slice(0, 200)})` : ""}`);
    bridge.warm();
    stage("full", "AI 분석까지 준비됐어요", `${Math.round(performance.now() - t0)}ms`);
    idleWarm = true;
    scheduleIdleWarm();
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

// 쉬는 동안 미리 불러오기(첫 분석 대기 줄이기): 줄이 비어 있고 처리 중인 요청이 없을 때만 bridge.warm_more()로
// 모듈을 하나씩 불러온다. 한 조각이 도는 동안 온 요청은 그 조각이 끝나면 먼저 처리되고, 다음 조각은 줄이 빈 뒤에 한다.
// 못 불러오면 그만둔다(분석 때 같은 오류가 그대로 난다).
const IDLE_WARM_GAP_MS = 30;   // 조각 사이 쉬는 틈: 그 사이 들어온 요청 메시지가 먼저 줄에 들어가게
let idleWarm = false;
let idleTimer = null;

function scheduleIdleWarm() {
  if (!idleWarm || idleTimer !== null) return;
  idleTimer = setTimeout(() => {
    idleTimer = null;
    if (!idleWarm || running || queue.length) return;   // 요청을 처리한 뒤 pump가 다시 부른다
    try {
      idleWarm = Boolean(bridge.warm_more());
    } catch (e) {
      idleWarm = false;
    }
    scheduleIdleWarm();
  }, IDLE_WARM_GAP_MS);
}

async function pump() {
  if (running) return;
  const msg = queue.shift();
  if (!msg) { scheduleIdleWarm(); return; }
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
