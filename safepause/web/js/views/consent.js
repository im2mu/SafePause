/* 동의: 세 가지를 따로 켜고 끄며, 끄면 바로 멈춘다(S18·S37 즉시 철회).
 * '거래 살펴보기'를 끄면 화면 데이터 세대를 올려, 요청 중이던 옛 거래 목록이 다시 그려지지 않게 한다(리뷰 H1). */
import { h, icon, fill, toast, announce, skeleton } from "../ui.js";
import { formatWhen } from "../format.js";
import { errorNotice } from "../components.js";
import { STALE } from "../api.js";

const ITEMS = [
  { key: "monitoring", icon: "money", title: "거래 살펴보기",
    lines: ["내가 돈을 쓰고 보내는 것을 살펴봐요.", "살펴보는 일은 이 기기 안에서만 해요."] },
  { key: "helper_alerts", icon: "helper", title: "조력자에게 알리기",
    lines: ["위험이 클 때 내가 고른 조력자에게 알려요.", "누구에게, 언제 알릴지는 '조력자'에서 정해요.",
      "이 스위치를 꺼도 직접 물어볼 수 있어요.", "카드에서 '조력자에게 물어볼래요'를 고를 때예요."] },
  { key: "counseling_referral", icon: "person", title: "상담하는 곳 알려 주기",
    lines: ["상담하는 곳을 알려 줘요.", "지역발달장애인지원센터, 장애인권익옹호기관이에요.", "이럴 때 알려 줘요."],
    bullets: ["꼭 확인할 일이 30일 동안 3번 이상 생길 때", "알릴 조력자가 모두 돈을 받는 사람일 때"],
    after: ["보내지 않고 멈춘 것도 함께 세어요."] },
];

export default {
  title: "동의",
  back: "more",
  tab: "more",
  async render(ctx) {
    const { main, go } = ctx;
    const list = h("div", { class: "list" }, skeleton(1));
    const updated = h("p", { class: "muted", style: "margin:.25rem .25rem 1rem" });
    const givenBy = h("div", { class: "segmented", role: "radiogroup", "aria-label": "누가 동의했나요?" });
    const status = h("div", { role: "status" });
    fill(main,
      h("h2", { class: "page-title", tabindex: "-1", text: "동의: 내가 정해요" }),
      h("p", { class: "page-sub", text: "SafePause가 무엇을 해도 되는지 내가 정해요. 언제든지 끌 수 있어요. 끄면 바로 멈춰요." }),
      list, updated,
      h("h3", { class: "section-title", text: "누가 동의했나요?" }), givenBy, status);

    let consent = null;
    const switches = {};

    function render(c) {
      consent = c;
      ctx.session.consent = c;
      if (!list.querySelector(".switch-row")) {
        fill(list, ITEMS.map((it) => {
          const titleId = `c-${it.key}-title`, descId = `c-${it.key}-desc`;
          const sw = h("button", { type: "button", class: "switch", role: "switch", "aria-checked": "false", "aria-labelledby": titleId, "aria-describedby": descId,
            onclick: () => toggle(it, sw) });
          switches[it.key] = sw;
          return h("div", { class: "switch-row" },
            h("span", { class: "row-icon blue" }, icon(it.icon)),
            h("div", { class: "row-main" }, h("h3", { id: titleId, text: it.title }),
              h("div", { id: descId }, it.lines.map((t) => h("p", { text: t })),
                it.bullets ? h("ul", { style: "list-style:disc;padding-left:1.2rem;color:var(--text-3)" }, it.bullets.map((b) => h("li", { text: b }))) : null,
                (it.after || []).map((t) => h("p", { text: t })))),
            sw);
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

    async function reload() {
      try { render(await ctx.req("GET", "/api/consent")); } catch (e) { if (e !== STALE) fill(status, errorNotice(e, go)); }
    }
    await reload();
  },
};
