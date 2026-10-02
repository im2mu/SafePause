/* 사용법 안내(#/more/guide, 수정 계획 1-E J10): 첫 실행 1단계 소개를 다시 보여 주고(동의 단계 없음),
 * 불러오기 → 찾기 → 쉬운 말 카드 → 알리기 네 단계와 돈 보내기 전 확인을 그림과 함께 알려 준다.
 * 단계마다 그 화면으로 가는 버튼을 둔다. 동작을 약속하지 않고 지금 앱이 하는 일만 적는다. */
import { h, icon, fill } from "../ui.js";
import { menuRow } from "../components.js";
import { introNodes } from "./onboarding.js";

const STEPS = [
  { icon: "upload", title: "거래 불러오기",
    lines: ["내 거래에서 파일을 올리거나 연습용 거래를 불러와요.", "은행·카드 연결은 정식 버전에서 열려요."],
    link: { href: "#/txns", text: "내 거래로 가기" } },
  { icon: "sparkle", title: "걱정되는 거래 찾기",
    lines: ["약속(규칙) 다섯 가지와 내 평소 거래를 배운 AI가 함께 살펴봐요.", "거래가 30건보다 적으면 약속으로만 살펴봐요.",
      "동의 화면에서 거래 살펴보기를 켜야 살펴봐요."],
    link: { href: "#/more/about", text: "AI와 데이터 설명 보기" } },
  { icon: "bell", title: "쉬운 말 카드로 보기",
    lines: ["알림 탭에서 걱정되는 거래를 쉬운 말과 그림으로 보여 줘요.", "내가 한 거래라면 내가 한 거예요를 눌러 표시해요."],
    link: { href: "#/alerts", text: "알림으로 가기" } },
  { icon: "send", title: "조력자·상담하는 곳에 알리기",
    lines: ["알림 보내기에서 보낼 글을 만들고 문자·메일 앱을 열어요.", "보내기 버튼은 문자·메일 앱에서 직접 눌러요."],
    link: { href: "#/send?mode=notify", text: "알림 보내기로 가기" } },
];

export default {
  title: "사용법 안내",
  tab: "more",
  back: "more",
  async render(ctx) {
    fill(ctx.main,
      h("h2", { class: "page-title", tabindex: "-1", text: "사용법 안내" }),
      h("section", { class: "card guide-intro", "aria-label": "SafePause 소개" }, introNodes("h3")),

      h("h3", { class: "section-title", text: "이렇게 써요" }),
      h("ol", { class: "guide-steps" }, STEPS.map((st, i) => h("li", { class: "card guide-step" },
        h("div", { class: "guide-head" },
          h("span", { class: "guide-no", "aria-hidden": "true", text: String(i + 1) }),
          h("span", { class: "row-icon blue" }, icon(st.icon)),
          h("h4", { class: "guide-title", text: st.title })),
        h("div", { class: "guide-body" }, st.lines.map((t) => h("p", { text: t }))),
        h("a", { class: "btn sm weak guide-link", href: st.link.href }, h("span", { text: st.link.text }), icon("chevron"))))),

      h("h3", { class: "section-title", text: "돈 보내기 전에" }),
      h("div", { class: "card guide-step" },
        h("div", { class: "guide-head" },
          h("span", { class: "row-icon blue" }, icon("bank")),
          h("h4", { class: "guide-title", text: "받는 사람과 금액 먼저 살펴보기" })),
        h("div", { class: "guide-body" },
          h("p", { text: "보내기 탭의 돈 보내기에서 보내기 전에 한 번 더 살펴봐요." }),
          h("p", { text: "SafePause는 돈을 보내지 않아요. 보내기는 내 은행 앱에서 해요." })),
        h("a", { class: "btn sm weak guide-link", href: "#/send" }, h("span", { text: "돈 보내기로 가기" }), icon("chevron"))),

      h("h3", { class: "section-title", text: "처음에 정해 두면 좋아요" }),
      h("div", { class: "list" },
        menuRow({ icon: "toggle", tone: "blue", title: "동의", sub: "무엇을 해도 되는지 내가 정해요.", href: "#/more/consent" }),
        menuRow({ icon: "users", tone: "blue", title: "조력자", sub: "알릴 사람을 정해요.", href: "#/more/helpers" }),
        menuRow({ icon: "building", tone: "blue", title: "상담하는 곳", sub: "알릴 센터나 기관을 정해요.", href: "#/more/counselors" })));
  },
};
