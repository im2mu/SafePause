/* SafePause 앱 안 AI 엔진(웹 워커). 안드로이드 앱에서만 쓴다.
 * - Pyodide(웹어셈블리 파이썬)와 numpy·scipy·scikit-learn을 APK 안 파일에서 읽는다(인터넷 없음).
 * - 파이썬 패키지 safepause(PC판과 같은 코드)를 풀고, 저장 폴더 /spdata를 IndexedDB(IDBFS)에 연결한다.
 * - 요청은 한 번에 하나씩 처리한다(파이썬은 단일 스레드). 저장을 바꾸는 요청 뒤에는 IDBFS에 반영한다.
 * 단계: basic(가벼운 요청) → full(AI 분석). AI가 필요한 요청은 full까지 기다린다.
 */
import { loadPyodide } from "../pyodide/pyodide.mjs";

const BASIC = new Set([
  "GET /api/health", "GET /api/consent", "PUT /api/consent", "GET /api/helpers", "PUT /api/helpers",
  "GET /api/notices", "GET /api/decisions", "POST /api/wipe",
]);

const stage = (s, message, detail = "") => self.postMessage({ type: "stage", stage: s, message, detail });

let py = null;
let bridge = null;
let fullReady = null;       // Promise: AI 패키지까지 준비
let chain = Promise.resolve();

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
  fullReady.catch((e) => stage("error", "AI 분석 부분을 켜지 못했어요", String(e && e.message || e)));
}

const booted = boot().catch((e) => {
  stage("error", "AI 엔진을 켜지 못했어요", String(e && e.message || e));
  throw e;
});

function routeKey(method, path) {
  return `${method.toUpperCase()} ${path.split("?")[0]}`;
}

async function handle(msg) {
  try {
    await booted;
  } catch (e) {
    return { status: 503, body: { detail: "AI 엔진을 켜지 못했어요. 앱을 닫았다가 다시 열어 주세요." } };
  }
  const key = routeKey(msg.method, msg.path);
  if (!BASIC.has(key)) {
    try { await fullReady; } catch (e) {
      return { status: 503, body: { detail: "AI 분석 부분을 켜지 못했어요. 앱을 닫았다가 다시 열어 주세요." } };
    }
  }
  let raw = null;
  if (msg.bytes) raw = py.toPy(msg.bytes);
  try {
    const out = bridge.handle(msg.method, msg.path, JSON.stringify(msg.body ?? null), raw);
    const res = JSON.parse(out);
    if (msg.method !== "GET") {
      try { await syncfs(false); } catch (e) {
        return { status: 500, body: { detail: "기기에 저장하지 못했어요. 저장 공간이 넉넉한지 확인해 주세요." } };
      }
    }
    return res;
  } catch (e) {
    return { status: 500, body: { detail: "처리하다 문제가 생겼어요. 다시 해 주세요.", error: String(e && e.message || e).slice(0, 500) } };
  } finally {
    if (raw && typeof raw.destroy === "function") raw.destroy();
  }
}

self.onmessage = (e) => {
  const msg = e.data || {};
  if (msg.type !== "request") return;
  // 요청을 한 줄로 세운다(동시에 두 요청이 저장 파일을 건드리지 않게)
  chain = chain
    .then(() => handle(msg))
    .catch(() => ({ status: 500, body: { detail: "처리하다 문제가 생겼어요. 다시 해 주세요." } }))
    .then((res) => { self.postMessage({ type: "response", id: msg.id, status: res.status, body: res.body }); });
};
