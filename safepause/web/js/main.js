/* SafePause v0.3 화면 시작점: 앱 틀(머리글·아래 탭), 해시 라우터, 화면 수명 관리.
 *
 * 경로는 #/경로?이름=값 모양이다(예: #/send?txn=t123). ? 뒤는 ctx.params(URLSearchParams)로 화면에 넘긴다.
 * 화면(view)은 render(ctx)로 그리고, 떠날 때 ctx.onCleanup에 둔 정리 함수가 불린다(리스너·타이머 누수 방지).
 * 늦게 온 응답 막기(리뷰 H1·M3): ctx.req()는 요청을 보낸 뒤 ①다른 화면으로 옮겼거나 ②지우기·동의 끄기로
 * 데이터 세대(session.epoch)가 바뀌었으면 결과를 버린다(STALE). 즉시 철회한 뒤 옛 거래가 다시 그려지지 않는다.
 * 화면 파일은 처음 열 때 불러온다: 한 화면 파일에 문제가 있어도 다른 화면은 열린다.
 */
import { api, ApiError, MODE, isConsentError, STALE } from "./api.js";
import { engine } from "./engine-client.js";
import { $, h, fill, icon, toast, announce, closeTopSheet, closeAllSheets, applyPrefs, watchBundles } from "./ui.js";
import * as speech from "./speech.js";
import { hardProblem, wasmAllowed, layoutOk, showCompat } from "./compat.js";

// legacy.js에게: 모듈 묶음이 떴다(여기부터는 아래 시작 검사가 맡는다)
window.__SAFEPAUSE_STARTED__ = true;

applyPrefs();   // 글자 크기·화면 모드는 첫 화면을 그리기 전에 맞춘다

const ROUTES = {
  home: () => import("./views/home.js"),
  txns: () => import("./views/txns.js"),
  send: () => import("./views/send.js"),            // 보내기 탭 = 돈 보내기(?mode=money) | 알림 보내기(?mode=notify)
  alerts: () => import("./views/alerts.js"),
  more: () => import("./views/more.js"),
  "more/consent": () => import("./views/consent.js"),
  "more/helpers": () => import("./views/helpers.js"),
  "more/counselors": () => import("./views/counselors.js"),
  "more/settings": () => import("./views/settings.js"),
  "more/eval": () => import("./views/eval.js"),
  "more/export": () => import("./views/export.js"),
  "more/about": () => import("./views/about.js"),
  "more/guide": () => import("./views/guide.js"),      // 사용법 안내(첫 실행 소개를 다시 보기, 동의 단계 없음)
  onboarding: () => import("./views/onboarding.js"),
};

// 옛 경로(v0.2)는 새 자리로 옮긴다
const MOVED = { "more/data": "more/consent", "more/notices": "alerts?tab=sent" };

const NAV = [
  { tab: "home", label: "홈", icon: "home" },
  { tab: "txns", label: "내 거래", icon: "list" },
  { tab: "send", label: "보내기", icon: "send", primary: true },
  { tab: "alerts", label: "알림", icon: "bell" },
  { tab: "more", label: "전체", icon: "grid" },
];

export { STALE };

/** 앱 전체 상태. epoch는 지우기·거래 살펴보기 끄기 때 오른다. */
export const session = {
  epoch: 0,
  consent: null,
  unsaved: null,        // 저장하지 않은 입력이 있는 화면의 확인 함수(조력자 편집 등, 리뷰 M2)
  bumpEpoch() { this.epoch += 1; },
};

let current = null;      // {path, key, cleanup[], token, idx}
let navToken = 0;
let navIndex = history.state && typeof history.state.sp === "number" ? history.state.sp : 0;   // history.state.sp: 기록 안 위치(저장 안 한 입력 경고에서 계속 적기를 고르면 되돌리는 데 씀)
let restoring = false;

/** "send?txn=1" → {path: "send", query: "txn=1"} */
function splitRoute(route) {
  const s = String(route || "");
  const i = s.indexOf("?");
  const path = (i < 0 ? s : s.slice(0, i)).replace(/^\/+|\/+$/g, "") || "home";
  return { path, query: i < 0 ? "" : s.slice(i + 1) };
}

function currentRoute() {
  const m = /^#\/([a-z/-]*)(\?[^#]*)?/.exec(location.hash || "");
  if (!m) return "home";
  const path = (m[1] || "").replace(/\/$/, "") || "home";
  return m[2] && m[2].length > 1 ? `${path}${m[2]}` : path;
}

/** 화면 옮기기. go("send?txn=t1"), go("home", {replace: true}) */
export function go(route, { replace = false } = {}) {
  const target = `#/${route}`;
  if (location.hash === target) { render(route); return; }
  if (replace) { history.replaceState(null, "", target); render(route); } else { location.hash = target; }
}

function renderNav(activeTab) {
  const nav = $("#nav");
  if (!nav.querySelector(".nav-item")) {
    fill(nav,
      // 넓은 화면(왼쪽 메뉴)에서만 보이는 이름표
      h("div", { class: "nav-brand", "aria-hidden": "true" }, h("span", { class: "brand-mark" }, icon("logo")), h("span", { class: "brand-name", text: "SafePause" })),
      NAV.map((n) => h("a", {
        class: `nav-item${n.primary ? " primary-tab" : ""}`, href: `#/${n.tab}`, "data-tab": n.tab,
      }, icon(n.icon), h("span", { text: n.label }))));
  }
  for (const a of nav.querySelectorAll(".nav-item")) {
    if (a.dataset.tab === activeTab) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
}

/** 머리글. 홈(뿌리 화면)은 SafePause 로고, 하위 화면은 뒤로 + 제목. */
function setAppbar({ title, back, actions, root, brand }) {
  const bar = $("#appbar");
  bar.className = `appbar${back ? " has-back" : ""}${root ? " root" : ""}${brand ? " brand-bar" : ""}`;
  fill(bar,
    back ? h("button", { type: "button", class: "icon-btn", "aria-label": "뒤로", onclick: () => history.length > 1 ? history.back() : go(back) }, icon("back")) : null,
    brand
      ? h("h1", { class: "appbar-title brand", "aria-label": "SafePause" },
        h("span", { class: "brand-mark" }, icon("logo")), h("span", { class: "brand-name", text: "SafePause" }))
      : h("h1", { class: "appbar-title", text: title || "" }),
    actions && actions.length ? h("div", { class: "appbar-actions" }, actions) : null);
}

async function loadView(path) {
  const load = ROUTES[path];
  if (!load) return null;
  const mod = await load();
  return mod.default;
}

async function render(route) {
  const { path, query } = splitRoute(route);
  if (MOVED[path]) { go(MOVED[path], { replace: true }); return; }
  const key = query ? `${path}?${query}` : path;
  // 저장하지 않은 입력이 있으면 떠나기 전에 묻는다(같은 화면이라도 주소가 바뀌면 다시 그리므로 묻는다)
  if (current && current.key !== key && session.unsaved) {
    const ok = await session.unsaved();
    if (!ok) {
      // 뒤로 가기로 왔으면 앞으로, 링크로 왔으면 뒤로: 기록에 같은 주소가 두 번 남지 않게
      const st = history.state;
      restoring = true;
      if (st && typeof st.sp === "number" && st.sp < current.idx) history.forward();
      else history.back();
      window.setTimeout(() => { restoring = false; }, 400);
      return;
    }
    session.unsaved = null;
  }
  if (!ROUTES[path]) { go("home", { replace: true }); return; }

  if (current) for (const fn of current.cleanup.splice(0)) { try { fn(); } catch (e) { /* 정리 실패는 무시 */ } }
  closeAllSheets();
  speech.stop();
  const token = ++navToken;
  const cleanup = [];
  if (!(history.state && typeof history.state.sp === "number")) history.replaceState({ sp: ++navIndex }, "", location.hash);
  current = { path, key, cleanup, token, idx: history.state.sp };
  if (MODE === "engine") engine.cancelQueuedReads();   // 떠난 화면의 아직 시작하지 않은 조회는 워커에서 뺀다

  const main = $("#main");
  let view;
  try {
    view = await loadView(path);
  } catch (e) {
    if (navToken !== token) return;
    console.error("화면 파일을 불러오지 못했어요:", path, e);
    main.className = "main";
    fill(main, h("div", { class: "notice red", role: "alert" }, icon("warning"),
      h("p", { text: "화면을 불러오지 못했어요. 앱을 닫았다가 다시 열어 주세요." })));
    return;
  }
  if (navToken !== token) return;   // 불러오는 사이에 다른 화면으로 옮겼다

  const noNav = Boolean(view.noNav);
  const brand = !view.back && view.tab === "home";
  const root = Boolean(!view.back && view.tab && view.tab !== "home");
  $("#nav").hidden = noNav;
  $("#appbar").hidden = Boolean(view.noAppbar);
  main.className = `main${noNav ? " no-nav" : ""}`;
  renderNav(view.tab || "");
  // 탭 첫 화면(홈 빼고)은 본문 큰 제목이 있어 위쪽 제목을 숨긴다(두 번 보이지 않게). 하위 화면은 본문 제목을 숨긴다
  setAppbar({ title: view.title, back: view.back || null, root, brand });
  main.classList.toggle("sub", Boolean(view.back));
  main.replaceChildren();

  const ctx = {
    path, main, session,
    /** 주소의 ? 뒤 값. ctx.params.get("txn") */
    params: new URLSearchParams(query),
    alive: () => navToken === token,
    onCleanup: (fn) => cleanup.push(fn),
    setTitle: (title, actions) => setAppbar({ title, back: view.back || null, actions, root, brand }),
    go,
    /** 화면을 다시 그리지 않고 주소의 ? 뒤만 바꾼다(탭 고르기 등). ctx.replaceParams({tab: "sent"}), 빈 값은 뺀다 */
    replaceParams(values) {
      if (navToken !== token) return;   // 이미 떠난 화면
      const next = new URLSearchParams();
      for (const [k, v] of Object.entries(values || {})) if (v !== null && v !== undefined && v !== "") next.set(k, String(v));
      const q = next.toString();
      ctx.params = next;
      current.key = q ? `${path}?${q}` : path;
      history.replaceState(history.state, "", `#/${current.key}`);
    },
    /** 늦게 온 응답을 버리는 요청. 버릴 때는 STALE을 던진다(화면은 조용히 무시). */
    async req(method, p, body, file) {
      const epoch = session.epoch;
      const stale = () => navToken !== token || session.epoch !== epoch;
      let r;
      try {
        r = await api(method, p, body, file);
      } catch (e) {
        if (stale()) throw STALE;   // 화면을 떠나 취소된 조회(499)도 여기서 조용히 버린다
        throw e;
      }
      if (stale()) throw STALE;
      return r;
    },
  };
  let rendering;
  try {
    rendering = view.render(ctx);   // 화면 골격은 첫 await 전에 그려진다
  } catch (e) {
    rendering = Promise.reject(e);
  }
  // 초점·스크롤은 골격을 그린 직후 한 번만(데이터가 늦게 와도 입력 중인 칸의 초점을 빼앗지 않게, 2차 검증)
  if (navToken === token) {
    const heading = main.querySelector("h1, h2, .page-title");
    (heading && !view.noFocus ? heading : main).focus({ preventScroll: true });
    window.scrollTo(0, 0);
    announce(view.announce || view.title || "");
  }
  try {
    await rendering;
  } catch (e) {
    if (e === STALE || navToken !== token) return;
    if (!(e instanceof ApiError)) console.error(e);
    main.append(h("div", { class: "notice red", role: "alert" }, icon("warning"),
      h("p", { text: e instanceof ApiError ? e.message : "화면을 그리다 문제가 생겼어요. 다시 해 주세요." })));
  }
}

// ---- 엔진 준비 표시(안드로이드 앱) -------------------------------------------------
function engineSlot() {
  const slot = $("#engine-slot");
  if (MODE !== "engine") return;
  engine.start();
  engine.subscribe((s) => {
    if (s.stage === "full") { slot.replaceChildren(); return; }
    const err = s.stage === "error";
    // 한 문장 한 줄(C4): 띠 글은 p의 text로 넣어 문장마다 나눈다
    const lines = !err ? [`${s.message}.`, "처음에는 10초쯤 걸려요."]
      : s.fatal ? [`${s.message}.`, "앱을 닫았다가 다시 열어 주세요."]
        : [`${s.message}.`, "동의 바꾸기·조력자·모두 지우기는 지금도 쓸 수 있어요.", "AI 분석을 쓰려면 앱을 닫았다가 다시 열어 주세요."];
    fill(slot, h("div", { class: "main engine-wrap" },
      h("div", { class: `engine-bar${err ? " error" : ""}`, role: "status" },
        err ? icon("warning") : h("span", { class: "spinner", "aria-hidden": "true" }),
        h("p", { text: lines.join(" ") }))));
  });
}

// ---- 시작 ----------------------------------------------------------------------
async function boot() {
  // 앱 안 파이썬 엔진은 페이지 CSP 아래 웹어셈블리 컴파일이 돼야 돈다(화면 프로그램 97 이상)
  if (MODE === "engine" && !(await wasmAllowed())) { showCompat("wasm-csp"); return; }
  if (!layoutOk()) layoutTip();
  // 안드로이드 뒤로 가기: 열린 창을 먼저 닫는다(MainActivity.onBackPressed가 부름)
  window.__safepauseBack = () => closeTopSheet();
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("a[data-skip]");
    if (a) { e.preventDefault(); $("#main").focus(); }   // 리뷰 M1: 본문으로 바로 가기가 화면을 바꾸지 않게
  });
  // 휴대폰 자판이 열린 동안에만 아래 탭을 숨겨 입력 칸이 자판에 가리지 않게 한다(넓은 화면은 CSS에서 무시).
  // 자판은 창 높이가 줄어드는 것으로 안다: 뒤로 가기로 자판만 닫아도(입력 칸 초점은 남음) 탭이 다시 보인다
  const isTyping = (el) => el && el.matches && el.matches("input:not([type=checkbox]):not([type=radio]):not([type=file]), textarea, select");
  let fullH = window.innerHeight, lastW = window.innerWidth;
  const updateTyping = () => {
    if (window.innerWidth !== lastW) { lastW = window.innerWidth; fullH = window.innerHeight; }   // 화면 돌림
    fullH = Math.max(fullH, window.innerHeight);
    const keyboard = window.innerHeight < fullH * 0.8;
    document.body.classList.toggle("typing", keyboard && isTyping(document.activeElement));
  };
  window.addEventListener("resize", updateTyping);
  if (window.visualViewport) window.visualViewport.addEventListener("resize", updateTyping);
  document.addEventListener("focusin", updateTyping);
  document.addEventListener("focusout", () => window.setTimeout(updateTyping, 50));
  window.addEventListener("hashchange", () => {
    if (!/^#\//.test(location.hash)) return;   // #main 같은 문서 안 이동은 화면을 바꾸지 않는다
    if (restoring) return;
    render(currentRoute());
  });
  engineSlot();
  watchBundles();   // 칸보다 넓은 묶음은 풀어 화면 밖으로 넘치지 않게(ui.fitBundles)

  let route = currentRoute();
  if (splitRoute(route).path !== "onboarding") {
    try {
      const c = await api("GET", "/api/consent");
      session.consent = c;
      let skipped = false;
      try { skipped = sessionStorage.getItem("safepause.onboard.later") === "1"; } catch (e) { skipped = false; }
      if (!c.updated_at && !skipped) route = "onboarding";
    } catch (e) {
      if (e instanceof ApiError && e.status === 403 && !isConsentError(e)) {
        fill($("#main"), h("div", { class: "notice red", role: "alert" }, icon("lock"),
          h("div", null, h("strong", { text: "이 창은 SafePause 프로그램이 연 창이 아니에요." }),
            h("p", { text: "SafePause 프로그램 창에 나온 주소로 다시 열어 주세요." }))));
        return;
      }
    }
  }
  if (location.hash !== `#/${route}`) history.replaceState(null, "", `#/${route}`);
  await render(route);
  // 다른 화면 파일은 첫 화면을 그린 뒤 미리 불러 둔다(탭을 바로 옮길 수 있게, 실패는 그 화면을 열 때 알림)
  window.setTimeout(() => { for (const load of Object.values(ROUTES)) load().catch(() => {}); }, 800);
}

// 화면 프로그램이 오래돼 배치 일부가 어긋날 수 있을 때(97~110) 업데이트를 권한다. 이 창에서 한 번만
function layoutTip() {
  try {
    if (sessionStorage.getItem("safepause.layoutTip") === "1") return;
    sessionStorage.setItem("safepause.layoutTip", "1");
  } catch (e) { /* 저장을 못 해도 안내는 한다 */ }
  toast(MODE === "engine"
    ? "화면 일부가 어긋나 보일 수 있어요. Play 스토어에서 Android System WebView를 업데이트하면 바르게 보여요."
    : "화면 일부가 어긋나 보일 수 있어요. 브라우저를 업데이트하면 바르게 보여요.");
}

window.addEventListener("error", () => toast("문제가 생겼어요. 다시 해 주세요.", "error"));
const startProblem = hardProblem(MODE === "engine");
if (startProblem) showCompat(startProblem);
else boot();
