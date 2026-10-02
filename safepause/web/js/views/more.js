/* 전체: 나를 지키는 설정·거래 연결·앱 설정·보호자·심사용·도움말·정보.
 * 정식 버전 기능은 준비 중 배지와 안내 시트로 자리만 둔다(동작하는 척하지 않음, R6).
 * 전문 용어는 보호자·심사용 화면(eval·about) 안쪽에만 둔다(리뷰 L5). */
import { h, icon, fill, setText, openSheet, comingSoonSheet, getPref } from "../ui.js";
import { menuRow } from "../components.js";
import { deviceWord } from "../format.js";
import { MODE, STALE } from "../api.js";
import { engine } from "../engine-client.js";
import { openBankConnect, openCardConnect } from "./connect.js";

const APP_VERSION = "0.3.0";
const FONT_KO = { m: "보통", l: "크게", xl: "아주 크게" };
const THEME_KO = { auto: "자동", light: "밝게", dark: "어둡게" };
const CONSENT_KEYS = ["monitoring", "helper_alerts", "counseling_referral"];

// 준비 중 기능 안내(정식 버전에서 열림)
const SOON = {
  phoneAlert: { icon: "bell", title: "휴대폰 알림 받기",
    lines: ["꼭 확인할 거래가 생기면 휴대폰 알림으로 알려 줘요.", "알림을 누르면 그 거래 카드가 바로 열려요."], action: "켜기" },
  appLock: { icon: "lock", title: "앱 잠금",
    lines: ["앱을 열 때 잠금을 풀어야 열려요.", "지문이나 비밀번호로 열 수 있어요."], action: "켜기" },
  guardian: { icon: "link", title: "보호자 앱 연결",
    lines: ["보호자 휴대폰의 SafePause와 연결해요.", "내가 허락한 알림만 보호자에게 가요."],
    steps: [
      { title: "보호자 초대하기", sub: "연결 번호를 보호자에게 보내요." },
      { title: "보호자가 수락하기", sub: "보호자 휴대폰에서 연결을 받아요." },
      { title: "보낼 알림 고르기", options: ["꼭 확인할 때만", "확인할 때도"] },
    ], action: "연결하기" },
  guide: { icon: "help", title: "사용법 안내",
    lines: ["SafePause를 쓰는 방법을 그림과 함께 알려 줘요.", "화면마다 무엇을 하는지 차례로 볼 수 있어요."] },
  support: { icon: "headset", title: "고객센터",
    lines: ["궁금한 것을 묻거나 문제를 알릴 수 있어요.", "전화와 채팅으로 상담해요."] },
  terms: { icon: "doc", title: "이용약관",
    lines: ["SafePause를 쓸 때 지킬 약속을 적은 글이에요."] },
  privacy: { icon: "shield", title: "개인정보 처리방침",
    lines: ["어떤 정보를 어디에 저장하고 언제 지우는지 적은 글이에요."] },
};

export default {
  title: "전체",
  tab: "more",
  async render(ctx) {
    const { main } = ctx;
    // 오른쪽 값(동의 켜짐 수·조력자 수 등). 불러오기 전에는 비워 둔다
    const val = { consent: valueSlot(), helpers: valueSlot(), counselors: valueSlot() };
    const soon = (key) => () => {
      const s = SOON[key];
      const extra = key === "privacy" ? (close) => h("div", { class: "soon-now" },
        h("p", { class: "soon-now-title", text: "지금은 AI와 데이터 설명에서 볼 수 있어요." }),
        h("button", { type: "button", class: "btn weak block", onclick: () => { close(); ctx.go("more/about"); } },
          icon("info"), h("span", { text: "AI와 데이터 설명 보기" }))) : null;
      comingSoonSheet({ ...s, extra });
    };

    fill(main,
      h("h2", { class: "page-title", tabindex: "-1", text: "전체" }),

      group("나를 지키는 설정",
        valueRow({ icon: "toggle", tone: "blue", title: "동의", href: "#/more/consent", value: val.consent }),
        valueRow({ icon: "users", tone: "blue", title: "조력자", href: "#/more/helpers", value: val.helpers }),
        valueRow({ icon: "building", tone: "blue", title: "상담하는 곳", href: "#/more/counselors", value: val.counselors })),

      group("거래 연결",
        menuRow({ icon: "bank", title: "은행 계좌 연결", soon: true, onclick: () => openBankConnect(ctx) }),
        menuRow({ icon: "card", title: "카드 연결", soon: true, onclick: () => openCardConnect(ctx) }),
        menuRow({ icon: "upload", title: "파일로 거래 불러오기", onclick: () => ctx.go("txns?open=upload") })),

      group("앱 설정",
        valueRow({ icon: "text-size", title: "글자 크기", href: "#/more/settings", value: valueSlot(FONT_KO[getPref("font")]) }),
        valueRow({ icon: "moon-sun", title: "화면 모드", href: "#/more/settings", value: valueSlot(THEME_KO[getPref("theme")]) }),
        menuRow({ icon: "bell", title: "휴대폰 알림 받기", soon: true, onclick: soon("phoneAlert") }),
        menuRow({ icon: "lock", title: "앱 잠금", soon: true, onclick: soon("appLock") })),

      group("보호자·심사용",
        menuRow({ icon: "chart", title: "AI 성능 확인", href: "#/more/eval" }),
        menuRow({ icon: "download", title: "결과 내보내기", href: "#/more/export" }),
        menuRow({ icon: "link", title: "보호자 앱 연결", soon: true, onclick: soon("guardian") })),

      group("도움말·정보",
        menuRow({ icon: "help", title: "사용법 안내", soon: true, onclick: soon("guide") }),
        menuRow({ icon: "headset", title: "고객센터", soon: true, onclick: soon("support") }),
        menuRow({ icon: "doc", title: "이용약관", soon: true, onclick: soon("terms") }),
        menuRow({ icon: "shield", title: "개인정보 처리방침", soon: true, onclick: soon("privacy") }),
        menuRow({ icon: "info", title: "AI와 데이터 설명", href: "#/more/about" }),
        valueRow({ icon: "code", title: "버전 정보", onclick: () => openVersion(ctx), value: valueSlot(APP_VERSION) })),

      h("div", { class: "notice more-local" }, icon("lock"), h("div", null,
        h("strong", { text: `모든 일은 ${deviceWord()} 안에서만 해요.` }),
        h("p", { text: MODE === "engine"
          ? "이 앱은 인터넷 권한이 없어요. 거래가 밖으로 나가지 않아요."
          : "거래가 밖으로 나가지 않아요." }))),
      h("p", { class: "muted center more-foot", text: `SafePause ${APP_VERSION}` }));

    // 나를 지키는 설정의 지금 상태(실패해도 메뉴는 그대로 쓴다)
    const [consent, helpers, counselors] = await Promise.all([
      ctx.req("GET", "/api/consent").catch((e) => (e === STALE ? STALE : null)),
      ctx.req("GET", "/api/helpers").catch((e) => (e === STALE ? STALE : null)),
      ctx.req("GET", "/api/counselors").catch((e) => (e === STALE ? STALE : null)),
    ]);
    if (!ctx.alive() || [consent, helpers, counselors].includes(STALE)) return;
    if (consent) {
      const on = CONSENT_KEYS.filter((k) => consent[k]).length;
      setText(val.consent, on ? `${on}개 켜짐` : "모두 꺼짐");
    }
    if (Array.isArray(helpers)) setText(val.helpers, helpers.length ? `${helpers.length}명` : "없음");
    if (counselors && Array.isArray(counselors.items)) {
      const n = counselors.items.filter((c) => c.active !== false).length;
      setText(val.counselors, n ? `${n}곳` : "없음");
    }
  },
};

function group(head, ...rows) {
  return [h("h3", { class: "section-title", text: head }), h("div", { class: "list" }, rows)];
}

function valueSlot(text = "") {
  return h("span", { class: "menu-val", text });
}

// 이름 + 오른쪽 값 메뉴 줄. 큰 글씨로 자리가 모자라면 값이 이름 아래 줄로 내려간다(한 글자씩 끊기지 않게)
function valueRow({ icon: ic, tone = "", title, href = null, onclick = null, value }) {
  const inner = [
    h("span", { class: `row-icon ${tone}`.trim() }, icon(ic)),
    h("span", { class: "row-main with-val" }, h("span", { class: "row-title", text: title }), value),
    h("span", { class: "row-chev" }, icon("chevron")),
  ];
  return href ? h("a", { class: "row menu-row", href }, inner) : h("button", { type: "button", class: "row menu-row", onclick }, inner);
}

// 버전 정보: 앱 버전·실행 방식·AI 엔진 상태(앱은 엔진 준비 단계를 따라 바뀐다)
function openVersion(ctx) {
  const ver = h("dd", { class: "tnum", text: APP_VERSION });
  const state = h("dd", { text: MODE === "engine" ? engineText(engine.status.stage) : "확인하고 있어요" });
  let unsub = null;
  openSheet((close) => [
    h("div", { class: "sheet-head" }, h("span", { class: "soon-icon" }, icon("logo"))),
    h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: "버전 정보" }),
    h("dl", { class: "ver-list" },
      h("div", null, h("dt", { text: "앱 버전" }), ver),
      h("div", null, h("dt", { text: "실행 방식" }), h("dd", { text: MODE === "engine" ? "휴대폰 앱 안에서 실행" : "컴퓨터 프로그램으로 실행" })),
      h("div", null, h("dt", { text: "AI 엔진" }), state),
      h("div", null, h("dt", { text: "인터넷" }), h("dd", { text: "쓰지 않아요" }))),
    h("div", { class: "sheet-actions" }, h("button", { type: "button", class: "btn big block", text: "닫기", onclick: () => close() })),
  ], { label: "버전 정보", onClose: () => { if (unsub) unsub(); } });
  if (MODE === "engine") unsub = engine.subscribe((s) => setText(state, engineText(s.stage)));
  ctx.req("GET", "/api/health").then((r) => {
    if (r && r.version) setText(ver, r.version);
    if (MODE !== "engine") setText(state, r && r.status === "ok" ? "준비됐어요" : "확인하지 못했어요");
  }).catch((e) => {
    if (e !== STALE && MODE !== "engine") setText(state, "연결하지 못했어요");
  });
}

function engineText(stage) {
  if (stage === "full") return "준비됐어요";
  if (stage === "basic") return "AI 분석을 켜고 있어요";
  if (stage === "error") return "켜지 못했어요";
  return "켜고 있어요";
}
