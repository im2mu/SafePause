/* 홈: 지금 상태(동의·거래 수·걱정 거래 수), 큰 '보내기 전에 확인' 버튼, 바로 가기, 최근 알림 카드. */
import { h, icon, fill, skeleton } from "../ui.js";
import { nf } from "../format.js";
import { alertCard, errorNotice, practicePill } from "../components.js";
import { STALE, MODE } from "../api.js";

export default {
  title: "안전 정지",
  tab: "home",
  async render(ctx) {
    const { main, go } = ctx;
    const heroSlot = h("div", null, skeleton(1));
    const recentSlot = h("div");
    fill(main,
      h("h2", { class: "sr-only", tabindex: "-1", text: "홈" }),
      heroSlot,
      h("a", { class: "btn primary big block", href: "#/send", style: "margin:.25rem 0 .75rem" },
        icon("send"), h("span", { text: "돈 보내기 전에 확인하기" })),
      h("p", { class: "center muted", style: "margin-bottom:1rem" }, practicePill()),
      h("div", { class: "quick" },
        quick("list", "내 거래 불러오기", "파일이나 연습용 거래", "#/txns"),
        quick("users", "조력자", "누구에게 알릴지 정해요", "#/more/helpers"),
        quick("chart", "AI 성능 확인", "얼마나 잘 찾는지", "#/more/eval"),
        quick("shield", "동의·내 데이터", "켜고 끄기·지우기", "#/more/consent")),
      h("div", { class: "notice blue" }, icon("shield"),
        h("div", null, h("strong", { text: "SafePause는 막지 않아요." }),
          h("p", { text: "걱정되면 한 번 더 물어볼 뿐이에요. 결정은 내가 해요." }))),
      recentSlot);

    let consent = null;
    try {
      consent = await ctx.req("GET", "/api/consent");
      ctx.session.consent = consent;
    } catch (e) {
      if (e === STALE) return;
      fill(heroSlot, errorNotice(e, go));
      return;
    }
    if (!consent.monitoring) {
      fill(heroSlot, h("section", { class: "card hero" },
        h("p", { class: "hero-status off" }, h("span", { class: "dot", "aria-hidden": "true" }), h("span", { text: "거래 살펴보기 꺼짐" })),
        h("h2", { class: "hero-title", text: "지금은 거래를 살펴보지 않아요" }),
        h("p", { class: "hero-note", text: `켜면 ${MODE === "engine" ? "이 기기" : "이 컴퓨터"} 안에서만 살펴봐요. 언제든지 끌 수 있어요.` }),
        h("a", { class: "btn weak block", href: "#/more/consent", style: "margin-top:1rem" }, icon("toggle"), h("span", { text: "동의 켜러 가기" }))));
      return;
    }
    // 분석 결과(앱에서는 AI 엔진 준비가 끝나야 온다)
    try {
      const t = await ctx.req("GET", "/api/transactions?level=all&limit=1");
      const s = t.summary;
      fill(heroSlot, h("section", { class: "card hero" },
        h("p", { class: "hero-status" }, h("span", { class: "dot", "aria-hidden": "true" }), h("span", { text: "거래 살펴보기 켜짐" })),
        h("h2", { class: "hero-title", text: t.count
          ? (s.high ? `꼭 확인할 거래가 ${nf.format(s.high)}건 있어요` : s.caution ? `확인할 거래가 ${nf.format(s.caution)}건 있어요` : "걱정되는 거래가 없어요")
          : "아직 저장된 거래가 없어요" }),
        h("p", { class: "hero-note", text: t.count ? `저장된 거래 ${nf.format(t.count)}건을 ${MODE === "engine" ? "이 기기" : "이 컴퓨터"} 안에서 살펴봤어요.` : "내 거래를 불러오거나 연습용 거래로 해 볼 수 있어요." }),
        t.count ? h("div", { class: "stats" },
          stat("괜찮아요", s.none, "ok"), stat("확인해요", s.caution, "caution"), stat("꼭 확인해요", s.high, "high")) : null,
        t.count ? null : h("a", { class: "btn weak block", href: "#/txns", style: "margin-top:1rem" }, icon("upload"), h("span", { text: "거래 불러오기" }))));
      if (!t.count) return;
      const c = await ctx.req("GET", "/api/cards?limit=2");
      if (!c.items.length) return;
      fill(recentSlot,
        h("h2", { class: "section-title" }, h("span", { text: "최근 알림" }),
          h("a", { class: "link", href: "#/alerts" }, h("span", { text: "모두 보기" }), icon("chevron"))),
        c.items.map(alertCard));
    } catch (e) {
      if (e === STALE) return;
      fill(heroSlot, errorNotice(e, go));
    }
  },
};

function quick(ic, title, sub, href) {
  return h("a", { class: "quick-item", href }, h("span", { class: "qi-icon" }, icon(ic)), h("b", { text: title }), h("span", { text: sub }));
}

function stat(label, n, cls) {
  return h("div", { class: `stat ${cls}` }, h("b", { text: nf.format(n || 0) }), h("span", { text: label }));
}
