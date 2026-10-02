/* 동의: 세 가지를 따로 켜고 끄며, 끄면 바로 멈춘다(S18·S37 즉시 철회). 맨 아래에 모두 지우기.
 * 거래 살펴보기를 끄거나 모두 지울 때는 화면 데이터 세대를 올려, 요청 중이던 옛 거래 목록이 다시 그려지지 않게 한다(리뷰 H1). */
import { h, icon, fill, toast, announce, skeleton, busy, confirmSheet } from "../ui.js";
import { formatWhen, deviceWord } from "../format.js";
import { errorNotice } from "../components.js";
import { STALE } from "../api.js";
import { clearBankApp } from "./bankapp.js";

const ITEMS = [
  { key: "monitoring", icon: "chart", title: "거래 살펴보기",
    lines: ["내 거래를 살펴보고 걱정되는 거래를 찾아요.", `살펴보는 일은 ${deviceWord()} 안에서만 해요.`] },
  { key: "helper_alerts", icon: "users", title: "조력자에게 알리기",
    lines: ["꼭 확인할 거래가 생기면 내가 고른 조력자에게 알려요.", "이 스위치를 꺼도 알림 보내기에서 직접 알릴 수 있어요."],
    link: { href: "#/more/helpers", icon: "users", text: "조력자 정하기" } },
  { key: "counseling_referral", icon: "building", title: "상담하는 곳에 알려 주기",
    lines: ["상담하는 곳에 알려 줘요.", "이럴 때 알려 줘요."],
    bullets: ["꼭 확인할 일이 30일 동안 3번 이상 생길 때", "알릴 조력자가 모두 돈을 받는 사람일 때"],
    link: { href: "#/more/counselors", icon: "building", text: "상담하는 곳 정하기" } },
];
// 모두 지우기에서 함께 지워지는 것
const WIPED = ["동의한 것", "조력자", "상담하는 곳", "거래", "담은 거래", "보낸 알림 기록", "내 은행 앱"];

export default {
  title: "동의",
  back: "more",
  tab: "more",
  async render(ctx) {
    const { main, go } = ctx;
    const list = h("div", { class: "list" }, skeleton(1));
    const updated = h("p", { class: "muted consent-updated" });
    const givenBy = h("div", { class: "segmented", role: "radiogroup", "aria-label": "누가 동의했나요?" });
    const status = h("div", { role: "status" });
    const wipeOut = h("div", { "aria-live": "polite" });
    fill(main,
      h("h2", { class: "page-title", tabindex: "-1", text: "동의" }),
      h("p", { class: "page-sub", text: "SafePause가 무엇을 해도 되는지 내가 정해요. 언제든지 끌 수 있어요. 끄면 바로 멈춰요." }),
      list, updated,
      h("h3", { class: "section-title", text: "누가 동의했나요?" }), givenBy, status,

      h("h3", { class: "section-title", text: "모두 지우기" }),
      h("div", { class: "card wipe-card" },
        h("p", { text: `${deviceWord()}에 저장한 것을 모두 지워요. 지우면 되돌릴 수 없어요.` }),
        h("ul", { class: "wipe-items", "aria-label": "함께 지워지는 것" }, WIPED.map((t) => h("li", { class: "tag", text: t }))),
        h("button", { type: "button", class: "btn danger-weak big block", onclick: (e) => busy(e.currentTarget, wipe) },
          icon("trash"), h("span", { text: "모두 지우기" }))),
      wipeOut);

    const switches = {};

    function render(c) {
      ctx.session.consent = c;
      if (!list.querySelector(".switch-row")) {
        fill(list, ITEMS.map((it) => {
          const titleId = `c-${it.key}-title`, descId = `c-${it.key}-desc`;
          const sw = h("button", { type: "button", class: "switch", role: "switch", "aria-checked": "false", "aria-labelledby": titleId, "aria-describedby": descId,
            onclick: () => toggle(it, sw) });
          switches[it.key] = sw;
          // 윗줄: 아이콘 · 이름 · 스위치, 아랫줄: 설명(좁은 화면에서도 스위치가 이름 옆에 남게)
          return h("div", { class: "switch-row consent-row" },
            h("div", { class: "consent-head" },
              h("span", { class: "row-icon blue" }, icon(it.icon)),
              h("h3", { id: titleId, text: it.title }),
              sw),
            h("div", { class: "consent-body" },
              h("div", { id: descId }, it.lines.map((t) => h("p", { text: t })),
                it.bullets ? h("ul", { class: "consent-bullets" }, it.bullets.map((b) => h("li", { text: b }))) : null),
              it.link ? h("a", { class: "btn sm weak consent-link", href: it.link.href }, icon(it.link.icon), h("span", { text: it.link.text })) : null));
        }));
        fill(givenBy, [["self", "나(본인)"], ["legal_representative", "법정대리인"]].map(([v, t]) => {
          const input = h("input", { type: "radio", name: "given_by", value: v, onchange: () => changeGivenBy(v) });
          return h("label", null, input, h("span", { text: t }));
        }));
      }
      for (const it of ITEMS) switches[it.key].setAttribute("aria-checked", c[it.key] ? "true" : "false");
      for (const r of givenBy.querySelectorAll("input")) r.checked = r.value === (c.given_by || "self");
      updated.textContent = c.updated_at ? `마지막으로 바꾼 때: ${formatWhen(c.updated_at)}` : "아직 아무것도 켜지 않았어요. 모두 꺼져 있어요.";
    }

    async function toggle(it, sw) {
      if (sw.getAttribute("aria-busy") === "true") return;
      const next = sw.getAttribute("aria-checked") !== "true";
      sw.setAttribute("aria-busy", "true");
      sw.setAttribute("aria-checked", next ? "true" : "false");   // 누르는 즉시 보여 준다(리뷰 L2)
      if (it.key === "monitoring" && !next) ctx.session.bumpEpoch();   // 끄는 즉시 옛 분석 응답을 버린다(리뷰 H1)
      try {
        render(await ctx.req("PUT", "/api/consent", { [it.key]: next }));
        status.replaceChildren();   // 앞서 난 오류 안내를 지운다
        const msg = next ? `${it.title}: 켰어요.` : `${it.title}: 껐어요. 바로 멈췄어요.`;
        toast(msg);
        announce(msg);
      } catch (e) {
        if (e === STALE) return;
        fill(status, errorNotice(e, go));
        await reload();   // 서버 값으로 되돌린다(리뷰 L1)
      } finally {
        sw.removeAttribute("aria-busy");
      }
    }

    async function changeGivenBy(value) {
      try {
        render(await ctx.req("PUT", "/api/consent", { given_by: value }));
        status.replaceChildren();
        toast(value === "self" ? "본인이 동의했어요." : "법정대리인이 동의했어요.");
      } catch (e) {
        if (e === STALE) return;
        fill(status, errorNotice(e, go));
        await reload();   // 저장되지 않은 선택이 남지 않게(리뷰 L1)
      }
    }

    // 모두 지우기(즉시 철회권): 확인 → 세대 올리기 → 지우기 → 꺼진 동의로 다시 그림
    async function wipe() {
      const ok = await confirmSheet({
        title: "정말 모두 지울까요?", lines: ["되돌릴 수 없어요."], confirmText: "네, 지울래요", cancelText: "아니요", danger: true,
      });
      if (!ok) return;
      ctx.session.bumpEpoch();   // 지우는 즉시 옛 분석 응답을 버린다(리뷰 H1)
      try {
        const r = await ctx.req("POST", "/api/wipe");
        ctx.session.consent = null;
        try { sessionStorage.removeItem("safepause.onboard.later"); } catch (e) { /* 무시 */ }
        clearBankApp();   // 이 기기에 기억한 내 은행 앱도 함께 잊는다
        fill(wipeOut, h("div", { class: "notice green", role: "status" }, icon("check"), h("p", { text: r.message })));
        toast(r.message);
        announce(r.message);
        await reload();   // 모두 꺼진 동의를 보인다
      } catch (err) {
        if (err === STALE) return;
        fill(wipeOut, errorNotice(err, go));
      }
    }

    async function reload() {
      try { render(await ctx.req("GET", "/api/consent")); } catch (e) { if (e !== STALE) fill(status, errorNotice(e, go)); }
    }
    await reload();
  },
};
