/* 알림: 걱정했던 거래(기록 카드)와 보내기 연습에서 내가 고른 것. */
import { h, icon, fill, skeleton, emptyState } from "../ui.js";
import { nf, formatWhen } from "../format.js";
import { alertCard, errorNotice } from "../components.js";
import { LEVEL, DECISION_KO, DECISION_ICON, ASK_NOBODY_KO } from "../labels.js";
import { STALE } from "../api.js";

export default {
  title: "알림",
  tab: "alerts",
  async render(ctx) {
    const { main, go } = ctx;
    let tab = "cards";
    const slot = h("div", null, skeleton(2));
    const chips = h("div", { class: "chips", role: "group", "aria-label": "보기" },
      [["cards", "걱정했던 거래"], ["decisions", "내가 고른 것"]].map(([v, t]) => h("button", {
        type: "button", class: "chip", "aria-pressed": v === tab ? "true" : "false", "data-v": v,
        onclick: () => { tab = v; for (const c of chips.children) c.setAttribute("aria-pressed", c.dataset.v === v ? "true" : "false"); load(); },
      }, h("span", { text: t }))));
    fill(main, h("h2", { class: "page-title", tabindex: "-1", text: "알림" }),
      h("p", { class: "page-sub", text: "SafePause가 걱정했던 거래와, 내가 고른 것을 모아 봐요." }), chips, slot);
    let seq = 0;

    async function load() {
      const my = ++seq;
      slot.replaceChildren(skeleton(2));
      try {
        if (tab === "cards") {
          const d = await ctx.req("GET", "/api/cards?limit=30");
          if (my !== seq) return;
          fill(slot,
            h("p", { class: "muted", style: "margin:0 .25rem .75rem", text: d.total ? `걱정했던 거래 ${nf.format(d.total)}건 가운데 최근 ${d.items.length}건이에요.` : "" }),
            d.items.length ? d.items.map(alertCard) : emptyState("bell", "걱정했던 거래가 없어요", "걱정되는 거래가 있으면 여기에 모여요."));
        } else {
          const d = await ctx.req("GET", "/api/decisions");
          if (my !== seq) return;
          const text = (x) => (x.decision === "ask_helper" && x.asked === 0 ? ASK_NOBODY_KO : (DECISION_KO[x.decision] || x.decision));
          fill(slot, d.items.length
            ? h("div", { class: "list" }, d.items.slice(0, 100).map((x) => h("div", { class: "row" },
              h("span", { class: `row-icon ${x.decision === "cancel" ? "red" : x.decision === "ask_helper" ? "blue" : ""}`.trim() }, icon(DECISION_ICON[x.decision] || "check")),
              h("span", { class: "row-main" }, h("span", { class: "row-title", text: text(x) }),
                h("span", { class: "row-sub", text: `${(LEVEL[x.level] || LEVEL.none).text} · ${formatWhen(x.at)}` })))))
            : emptyState("check", "아직 고른 것이 없어요", "보내기 연습에서 고른 것을 기록해요."));
        }
      } catch (e) {
        if (e === STALE || my !== seq) return;
        fill(slot, errorNotice(e, go));
      }
    }
    await load();
  },
};
