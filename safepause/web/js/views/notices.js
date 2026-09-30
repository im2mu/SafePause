/* 조력자 알림 기록: 알림은 기록만 한다(문자·메일을 보내지 않음). */
import { h, icon, fill, skeleton, emptyState } from "../ui.js";
import { formatWhen } from "../format.js";
import { errorNotice } from "../components.js";
import { LEVEL } from "../labels.js";
import { STALE, MODE } from "../api.js";

export default {
  title: "조력자 알림 기록",
  back: "more",
  tab: "more",
  async render(ctx) {
    const { main, go } = ctx;
    const note = h("p", { class: "page-sub", text: MODE === "engine"
      ? "알림은 기록만 해요. 이 기기에 적어 두고, 문자나 메일은 보내지 않아요."
      : "알림은 기록만 해요. 이 컴퓨터에 적어 두고, 문자나 메일은 보내지 않아요." });
    const slot = h("div", null, skeleton(2));
    fill(main, h("h2", { class: "page-title", tabindex: "-1", text: "조력자 알림 기록" }), note, slot);
    try {
      const d = await ctx.req("GET", "/api/notices");
      if (d.delivery_note && MODE !== "engine") note.textContent = d.delivery_note;
      fill(slot, d.items.length
        ? h("div", { class: "list" }, d.items.slice(0, 100).map((n) => h("div", { class: "row" },
          h("span", { class: `row-icon ${n.level === "high" ? "red" : "orange"}` }, icon("bell")),
          h("span", { class: "row-main" },
            h("span", { class: "row-title", text: `${n.helper_name} · ${(LEVEL[n.level] || LEVEL.none).text}` }),
            h("span", { class: "row-sub", text: formatWhen(n.created_at) }),
            h("span", { class: "row-sub", text: n.message })))))
        : emptyState("bell", "아직 알림 기록이 없어요", "조력자에게 알릴 일이 생기면 여기에 적어요."));
    } catch (e) {
      if (e === STALE) return;
      fill(slot, errorNotice(e, go));
    }
  },
};
