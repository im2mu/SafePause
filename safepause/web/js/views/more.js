/* 전체: 설정·보호자용·심사용 메뉴. 당사자 화면(홈·거래·보내기·알림)과 나눠 전문 용어는 여기 안쪽에만 둔다(리뷰 L5). */
import { h, icon, fill } from "../ui.js";
import { MODE } from "../api.js";

const GROUPS = [
  { head: "나를 지키는 설정", items: [
    { href: "#/more/consent", icon: "toggle", title: "동의", sub: "무엇을 해도 되는지 내가 정해요", tone: "blue" },
    { href: "#/more/helpers", icon: "users", title: "조력자", sub: "누구에게, 언제 알릴지 정해요", tone: "blue" },
    { href: "#/more/notices", icon: "bell", title: "조력자 알림 기록", sub: "알림은 기록만 해요", tone: "" },
  ] },
  { head: "내 데이터", items: [
    { href: "#/more/data", icon: "database", title: "내 데이터", sub: "내보내기 · 모두 지우기", tone: "" },
  ] },
  { head: "보호자·심사용", items: [
    { href: "#/more/eval", icon: "chart", title: "AI 성능 확인", sub: "합성 데이터로 얼마나 찾는지", tone: "" },
    { href: "#/more/about", icon: "info", title: "AI와 데이터 설명", sub: "모델·학습 데이터 요약·만든 방법", tone: "" },
  ] },
];

export default {
  title: "전체",
  tab: "more",
  async render(ctx) {
    fill(ctx.main,
      h("h2", { class: "page-title", tabindex: "-1", text: "전체" }),
      GROUPS.map((g) => [
        h("h3", { class: "section-title", text: g.head }),
        h("div", { class: "list" }, g.items.map((it) => h("a", { class: "row", href: it.href },
          h("span", { class: `row-icon ${it.tone}`.trim() }, icon(it.icon)),
          h("span", { class: "row-main" }, h("span", { class: "row-title", text: it.title }), h("span", { class: "row-sub", text: it.sub })),
          h("span", { class: "row-chev" }, icon("chevron"))))),
      ]),
      h("div", { class: "notice", style: "margin-top:1rem" }, icon("lock"), h("div", null,
        h("strong", { text: "모든 일은 이 기기 안에서만 해요." }),
        h("p", { text: MODE === "engine"
          ? "이 앱은 인터넷 권한이 없어요. 거래가 기기 밖으로 나가지 않아요."
          : "SafePause는 이 컴퓨터 안(127.0.0.1)에서만 열려요. 거래가 밖으로 나가지 않아요." }))),
      h("p", { class: "muted center", style: "margin:1.5rem 0 .5rem", text: "SafePause 안전 정지 v0.2.0 · 연습용 시제품(Pre-R&D)" }));
  },
};
