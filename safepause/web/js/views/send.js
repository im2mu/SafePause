/* 보내기 탭(경로 send): 위 탭 두 개, 돈 보내기 | 알림 보내기(?mode=money|notify).
 * - 기본은 돈 보내기(money.js). 주소에 txn·to가 있으면(알림 탭·내 거래의 알리기) 알림 보내기(notify.js)를 연다.
 * - 탭을 바꿀 때는 화면을 다시 부르지 않고 주소의 ? 뒤만 바꾼다(ctx.replaceParams: 뒤로 가기 기록이 늘지 않는다).
 *   돈 보내기는 ? 뒤가 비고(#/send), 알림 보내기는 mode=notify가 붙는다.
 * - 탭마다 작은 ctx를 따로 만든다. 탭을 바꾸면 앞 탭의 정리 함수가 불리고, 앞 탭에서 늦게 온 응답은 버린다(STALE).
 *   고친 글이 있는 탭(알림 보내기)을 떠날 때는 화면을 옮길 때처럼 먼저 묻는다(ctx.session.unsaved).
 * - 알림 보내기에서 고른 거래·받는 사람 주소 값은 돈 보내기 탭을 갔다 와도 그대로 돌려놓는다(RF-8). 다시 보내기(resend)는 한 번만 쓴다.
 */
import { h, fill, segTabs, announce } from "../ui.js";
import { errorNotice } from "../components.js";
import { STALE } from "../api.js";
import * as speech from "../speech.js";
import money from "./money.js";
import notify from "./notify.js";

const PANELS = { money, notify };
const TABS = [
  { value: "money", label: "돈 보내기", icon: "bank" },
  { value: "notify", label: "알림 보내기", icon: "chat" },
];
const labelOf = (mode) => (TABS.find((t) => t.value === mode) || TABS[0]).label;

/** 주소 뒤 값을 {이름: 값} 객체로(같은 이름이 여럿이면 쉼표로 잇는다: txn=a&txn=b → txn: "a,b"). */
function paramsObject(params) {
  const out = {};
  for (const [k, v] of params) out[k] = out[k] ? `${out[k]},${v}` : v;
  return out;
}

/** 주소 뒤 값으로 고를 탭: mode가 있으면 그것, 없으면 txn·to가 있을 때 알림 보내기, 그 밖은 돈 보내기. */
export function modeOf(params) {
  const m = params.get("mode");
  if (m === "money" || m === "notify") return m;
  return params.get("txn") || params.get("to") ? "notify" : "money";
}

export default {
  title: "보내기",
  tab: "send",
  async render(ctx) {
    let mode = modeOf(ctx.params);
    let busySwitch = false;
    let notifyParams = null;   // 돈 보내기로 옮기기 전 알림 보내기의 주소 값(돌아오면 그대로 쓴다)
    const panel = h("section", { id: "send-panel", class: "send-panel", role: "tabpanel", "aria-label": labelOf(mode) });
    const tabs = segTabs(TABS, mode, (v) => { switchTo(v); }, { label: "무엇을 보낼까요?", controls: "send-panel" });
    fill(ctx.main,
      h("h2", { class: "page-title", tabindex: "-1", text: "보내기" }),
      h("div", { class: "send-tabs" }, tabs.el),
      panel);

    // ---- 탭 하나의 수명: 정리 함수·늦은 응답 막기 ----
    let seq = 0;
    const cleanups = [];
    function stopPanel() {
      seq += 1;
      for (const fn of cleanups.splice(0)) { try { fn(); } catch (e) { /* 정리 실패는 무시 */ } }
    }
    ctx.onCleanup(stopPanel);

    async function show(params) {
      stopPanel();
      const my = seq;
      const alive = () => ctx.alive() && seq === my;
      const sub = {
        path: ctx.path, main: panel, session: ctx.session, params, go: ctx.go, setTitle: ctx.setTitle,
        alive,
        onCleanup: (fn) => { if (alive()) cleanups.push(fn); else { try { fn(); } catch (e) { /* 무시 */ } } },
        /** 이 탭의 ? 뒤 값만 바꾼다(탭 이름은 그대로 붙여 둔다). */
        replaceParams(values) {
          if (!alive()) return;
          ctx.replaceParams(mode === "notify" ? { mode: "notify", ...values } : { ...values });
          sub.params = new URLSearchParams(ctx.params);
        },
        /** 탭을 바꾼 뒤 늦게 온 응답도 버린다. */
        async req(method, path, body, file) {
          let r;
          try {
            r = await ctx.req(method, path, body, file);
          } catch (e) {
            if (e !== STALE && !alive()) throw STALE;
            throw e;
          }
          if (!alive()) throw STALE;
          return r;
        },
      };
      panel.setAttribute("aria-label", labelOf(mode));
      panel.replaceChildren();
      await PANELS[mode].render(sub);
    }

    async function switchTo(next) {
      if (next === mode || busySwitch) { tabs.set(mode); return; }
      if (ctx.session.unsaved) {
        busySwitch = true;
        let ok = false;
        try { ok = await ctx.session.unsaved(); } finally { busySwitch = false; }
        if (!ctx.alive()) return;
        if (!ok) { tabs.set(mode); return; }   // 계속 쓰기: 탭을 그대로 둔다
        ctx.session.unsaved = null;
      }
      if (mode === "notify") {
        notifyParams = paramsObject(ctx.params);
        delete notifyParams.mode;
        delete notifyParams.resend;
      }
      mode = next;
      tabs.set(mode);
      speech.stop();
      ctx.replaceParams(mode === "notify" ? { ...(notifyParams || {}), mode } : {});
      announce(`${labelOf(mode)} 화면이에요.`);
      try {
        await show(new URLSearchParams(ctx.params));
      } catch (e) {
        if (e === STALE || !ctx.alive()) return;
        console.error(e);
        panel.append(errorNotice(e && e.message ? e : new Error("화면을 그리다 문제가 생겼어요. 다시 해 주세요."), ctx.go));
      }
    }

    await show(ctx.params);
  },
};
