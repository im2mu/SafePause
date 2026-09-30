/* SafePause v0.2 화면 시작점: 앱 틀(앱바·아래 탭), 해시 라우터, 화면 수명 관리.
 *
 * 화면(view)은 render(ctx)로 그리고, 떠날 때 ctx.onCleanup에 둔 정리 함수가 불린다(리스너·타이머 누수 방지).
 * 늦게 온 응답 막기(리뷰 H1·M3): ctx.req()는 요청을 보낸 뒤 ①다른 화면으로 옮겼거나 ②지우기·동의 끄기로
 * 데이터 세대(session.epoch)가 바뀌었으면 결과를 버린다(STALE). 즉시 철회한 뒤 옛 거래가 다시 그려지지 않는다.
 */
import { api, ApiError, MODE, isConsentError, STALE } from "./api.js";
import { engine } from "./engine-client.js";
import { $, h, fill, icon, toast, announce, closeTopSheet, closeAllSheets } from "./ui.js";
import * as speech from "./speech.js";

import home from "./views/home.js";
import txns from "./views/txns.js";
import send from "./views/send.js";
import alerts from "./views/alerts.js";
import more from "./views/more.js";
import consent from "./views/consent.js";
import helpers from "./views/helpers.js";
import notices from "./views/notices.js";
import evalView from "./views/eval.js";
import dataView from "./views/data.js";
import about from "./views/about.js";
import onboarding from "./views/onboarding.js";

const ROUTES = {
  home, txns, send, alerts, more,
  "more/consent": consent, "more/helpers": helpers, "more/notices": notices,
  "more/eval": evalView, "more/data": dataView, "more/about": about,
  onboarding,
};

const NAV = [
  { tab: "home", label: "홈", icon: "home" },
  { tab: "txns", label: "내 거래", icon: "list" },
  { tab: "send", label: "보내기", icon: "send", primary: true },
  { tab: "alerts", label: "알림", icon: "bell" },
  { tab: "more", label: "전체", icon: "grid" },
];

export { STALE };

/** 앱 전체 상태. epoch는 지우기·'거래 살펴보기' 끄기 때 오른다. */
export const session = {
  epoch: 0,
  consent: null,
  unsaved: null,        // 저장하지 않은 입력이 있는 화면의 확인 함수(조력자 편집 등, 리뷰 M2)
  bumpEpoch() { this.epoch += 1; },
};

let current = null;      // {path, cleanup[], token}
let navToken = 0;

function currentPath() {
  const m = /^#\/([a-z/-]*)/.exec(location.hash || "");
  return m && m[1] ? m[1].replace(/\/$/, "") : "home";
}

export function go(path, { replace = false } = {}) {
  const target = `#/${path}`;
  if (location.hash === target) { render(path); return; }
  if (replace) { history.replaceState(null, "", target); render(path); } else { location.hash = target; }
}

function renderNav(activeTab) {
  const nav = $("#nav");
  if (!nav.childElementCount) {
    fill(nav, NAV.map((n) => h("a", {
      class: `nav-item${n.primary ? " primary-tab" : ""}`, href: `#/${n.tab}`, "data-tab": n.tab,
    }, icon(n.icon), h("span", { text: n.label }))));
  }
  for (const a of nav.querySelectorAll(".nav-item")) {
    if (a.dataset.tab === activeTab) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
}

function setAppbar({ title, back, actions, root }) {
  const bar = $("#appbar");
  bar.className = `appbar${back ? " has-back" : ""}${root ? " root" : ""}`;
  fill(bar,
    back ? h("button", { type: "button", class: "icon-btn", "aria-label": "뒤로", onclick: () => history.length > 1 ? history.back() : go(back) }, icon("back")) : null,
    h("h1", { class: "appbar-title", text: title || "" }),
    actions && actions.length ? h("div", { class: "appbar-actions" }, actions) : null);
}

async function render(path) {
  // 저장하지 않은 입력이 있으면 떠나기 전에 묻는다
  if (current && current.path !== path && session.unsaved) {
    const ok = await session.unsaved();
    if (!ok) { history.replaceState(null, "", `#/${current.path}`); return; }
    session.unsaved = null;
  }
  const view = ROUTES[path] || null;
  if (!view) { go("home", { replace: true }); return; }

  if (current) for (const fn of current.cleanup.splice(0)) { try { fn(); } catch (e) { /* 정리 실패는 무시 */ } }
  closeAllSheets();
  speech.stop();
  const token = ++navToken;
  const cleanup = [];
  current = { path, cleanup, token };

  const main = $("#main");
  const noNav = Boolean(view.noNav);
  $("#nav").hidden = noNav;
  $("#appbar").hidden = Boolean(view.noAppbar);
  main.className = `main${noNav ? " no-nav" : ""}`;
  renderNav(view.tab || "");
  // 탭 첫 화면(홈 빼고)은 본문 큰 제목이 있어 위쪽 제목을 숨긴다(두 번 보이지 않게). 하위 화면은 본문 제목을 숨긴다
  setAppbar({ title: view.title, back: view.back || null, root: !view.back && view.tab && view.tab !== "home" });
  main.classList.toggle("sub", Boolean(view.back));
  main.replaceChildren();

  const ctx = {
    path, main, session,
    alive: () => navToken === token,
    onCleanup: (fn) => cleanup.push(fn),
    setTitle: (title, actions) => setAppbar({ title, back: view.back || null, actions, root: !view.back && view.tab && view.tab !== "home" }),
    go,
    /** 늦게 온 응답을 버리는 요청. 버릴 때는 STALE을 던진다(화면은 조용히 무시). */
    async req(method, p, body, file) {
      const epoch = session.epoch;
      const r = await api(method, p, body, file);
      if (navToken !== token || session.epoch !== epoch) throw STALE;
      return r;
    },
  };
  try {
    await view.render(ctx);
  } catch (e) {
    if (e === STALE) return;
    main.append(h("div", { class: "notice red", role: "alert" }, icon("warning"),
      h("div", { text: e instanceof ApiError ? e.message : "화면을 그리다 문제가 생겼어요. 다시 해 주세요." })));
  }
  if (navToken === token) {
    const heading = main.querySelector("h1, h2, .page-title");
    (heading && !view.noFocus ? heading : main).focus({ preventScroll: false });
    window.scrollTo(0, 0);
    announce(view.announce || view.title || "");
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
    fill(slot, h("div", { class: "main", style: "padding-bottom:0" },
      h("div", { class: `engine-bar${err ? " error" : ""}`, role: "status" },
        err ? icon("warning") : h("span", { class: "spinner", "aria-hidden": "true" }),
        h("span", { text: err ? `${s.message}. 앱을 닫았다가 다시 열어 주세요.` : `${s.message}… 처음에는 10초쯤 걸려요.` }))));
  });
}

// ---- 시작 ----------------------------------------------------------------------
async function boot() {
  // 안드로이드 뒤로 가기: 열린 창을 먼저 닫는다(MainActivity.onBackPressed가 부름)
  window.__safepauseBack = () => closeTopSheet();
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("a[data-skip]");
    if (a) { e.preventDefault(); $("#main").focus(); }   // 리뷰 M1: '본문으로 바로 가기'가 화면을 바꾸지 않게
  });
  window.addEventListener("hashchange", () => {
    if (!/^#\//.test(location.hash)) return;   // #main 같은 문서 안 이동은 화면을 바꾸지 않는다
    render(currentPath());
  });
  engineSlot();

  let path = currentPath();
  if (path !== "onboarding") {
    try {
      const c = await api("GET", "/api/consent");
      session.consent = c;
      let skipped = false;
      try { skipped = sessionStorage.getItem("safepause.onboard.later") === "1"; } catch (e) { skipped = false; }
      if (!c.updated_at && !skipped) path = "onboarding";
    } catch (e) {
      if (e instanceof ApiError && e.status === 403 && !isConsentError(e)) {
        fill($("#main"), h("div", { class: "notice red", role: "alert" }, icon("lock"),
          h("div", null, h("strong", { text: "이 창은 SafePause 프로그램이 연 창이 아니에요." }),
            h("p", { text: "SafePause 프로그램 창에 나온 주소로 다시 열어 주세요." }))));
        return;
      }
    }
  }
  if (location.hash !== `#/${path}`) history.replaceState(null, "", `#/${path}`);
  render(path);
}

window.addEventListener("error", () => toast("문제가 생겼어요. 다시 해 주세요.", "error"));
boot();
