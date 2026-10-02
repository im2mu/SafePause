/* 전체: 나를 지키는 설정·거래 연결·앱 설정·내 계정·데이터·조력자·기관용·도움말·정보.
 * 정식 버전 기능은 준비 중 배지와 안내 시트로 자리만 둔다(동작하는 척하지 않음, R6·수정 계획 1-F).
 * 전문 용어는 조력자·기관용 화면(eval·about) 안쪽에만 둔다(리뷰 L5).
 * 준비 중 안내 시트(SOON)는 앱 설정·첫 실행도 같이 쓴다(openSoon, 한 곳에서만 정의, AUG-14). */
import { h, icon, fill, setText, openSheet, comingSoonSheet, getPref } from "../ui.js";
import { menuRow, subParts } from "../components.js";
import { deviceWord } from "../format.js";
import { MODE, STALE } from "../api.js";
import { engine } from "../engine-client.js";
import { openBankConnect, openCardConnect, openPhonePayConnect } from "./connect.js";
import { getBankApp } from "./bankapp.js";

const APP_VERSION = "0.3.0";
export const FONT_KO = { m: "보통", l: "크게", xl: "아주 크게" };
export const THEME_KO = { auto: "자동", light: "밝게", dark: "어둡게" };
const CONSENT_KEYS = ["monitoring", "helper_alerts", "counseling_referral"];

// 준비 중 기능 안내(정식 버전에서 열림). 함수는 열 때 장소 말(deviceWord)을 다시 고른다
const SOON = {
  phoneAlert: () => ({ icon: "bell", title: "휴대폰 알림 받기",
    lines: ["꼭 확인할 거래가 생기면 휴대폰 알림으로 알려 줘요.", "알림을 누르면 그 거래 카드가 바로 열려요.",
      "알림을 받으려면 휴대폰 알림 권한이 필요할 수 있어요."],
    steps: [
      { title: "알림 받을 때", options: ["꼭 확인할 때만", "확인할 때도"] },
      { title: "조용한 시간", sub: "이 시간에는 알림 소리를 내지 않아요.", options: ["밤 10시~아침 7시", "끄기"] },
      { title: "다시 알려 주기", sub: "나중에 보기를 누르면 정한 때에 다시 알려 줘요.", options: ["1시간 뒤", "내일 아침"] },
    ], action: "켜기" }),
  appLock: () => ({ icon: "lock", title: "앱 잠금",
    lines: ["앱을 열 때 잠금을 풀어야 열려요.", "지문이나 비밀번호로 열 수 있어요."], action: "켜기" }),
  account: () => ({ icon: "user-check", title: "내 계정",
    lines: ["정식 버전에서는 내 계정으로 로그인해요.", `지금은 계정 없이 ${deviceWord()} 안에서만 써요.`],
    list: [
      { icon: "user-check", title: "로그인", sub: "휴대폰으로 내가 맞는지 확인하고 들어가요." },
      { icon: "back", title: "로그아웃", sub: `${deviceWord()}에서 내 계정을 빼요.` },
      { icon: "trash", title: "회원 탈퇴", sub: "계정과 계정에 저장한 것을 지워요." },
    ], action: "로그인" }),
  transfer: () => ({ icon: "refresh", title: "백업·되살리기",
    lines: ["휴대폰이나 컴퓨터를 바꿔도 조력자·상담하는 곳·동의를 이어서 쓸 수 있게 해요.",
      "지금은 SafePause가 따로 백업하지 않아요.", "바꾼 뒤에는 조력자·상담하는 곳·동의를 새로 정해 주세요."],
    steps: [
      { title: "백업 파일 만들기", sub: "암호를 걸어 파일로 저장해요." },
      { title: "새 휴대폰에서 불러오기", sub: "같은 암호로 파일을 열어 되살려요." },
      { title: "옮긴 내용 확인하기", sub: "조력자·상담하는 곳·동의가 맞는지 봐요." },
    ], action: "백업 파일 만들기" }),
  helperApp: () => ({ icon: "link", title: "조력자 앱 연결",
    lines: ["조력자 휴대폰의 SafePause와 연결해요.", "내가 허락한 알림만 조력자에게 가요."],
    steps: [
      { title: "조력자 초대하기", sub: "연결 번호를 조력자에게 보내요." },
      { title: "조력자가 받기", sub: "조력자 휴대폰에서 연결을 받아요." },
      { title: "보낼 알림 고르기", options: ["꼭 확인할 때만", "확인할 때도"] },
    ], action: "연결하기" }),
  support: () => ({ icon: "headset", title: "고객센터",
    lines: ["궁금한 것을 묻거나 문제를 알릴 수 있어요.", "전화와 채팅으로 상담해요."] }),
  terms: () => ({ icon: "doc", title: "이용약관",
    lines: ["SafePause를 쓸 때 지킬 약속을 적은 글이에요.", "정식 버전에서는 처음 시작할 때 읽고 동의해요."] }),
  collect: () => ({ icon: "shield", title: "개인정보 수집·이용 동의",
    lines: ["거래내역처럼 내 돈에 관한 정보를 무엇에 쓰고 언제 지우는지 적은 글이에요.", "정식 버전에서는 처음 시작할 때 읽고 동의해요."] }),
  privacy: () => ({ icon: "shield", title: "개인정보 처리방침",
    lines: ["어떤 정보를 어디에 저장하고 언제 지우는지 적은 글이에요.", "정식 버전에서는 처음 시작할 때 읽고 동의해요."] }),
};

/**
 * 준비 중 안내 시트를 연다. key: phoneAlert·appLock·account·transfer·helperApp·support·terms·collect·privacy.
 * opts.go가 있으면 개인정보 처리방침 시트에 지금 볼 수 있는 곳(AI와 데이터 설명) 버튼을 붙인다.
 */
export function openSoon(key, { go = null } = {}) {
  const { list, ...s } = SOON[key]();
  const parts = [];
  if (list) parts.push(() => soonList(list));
  if (key === "privacy" && go) {
    parts.push((close) => h("div", { class: "soon-now" },
      h("p", { class: "soon-now-title", text: "지금은 AI와 데이터 설명에서 볼 수 있어요." }),
      h("button", { type: "button", class: "btn weak block", onclick: () => { close(); go("more/about"); } },
        icon("info"), h("span", { text: "AI와 데이터 설명 보기" }))));
  }
  return comingSoonSheet({ ...s, extra: parts.length ? (close) => parts.map((p) => p(close)) : null });
}

// 정식 버전에서 할 수 있는 일(순서가 아닌 묶음): 번호 대신 그림을 붙인 비활성 줄
function soonList(items) {
  return h("ul", { class: "soon-steps soon-plain", "aria-label": "정식 버전에서 할 수 있는 일" }, items.map((it) =>
    h("li", { class: "soon-step", "aria-disabled": "true" },
      h("span", { class: "soon-step-no", "aria-hidden": "true" }, icon(it.icon)),
      h("div", { class: "soon-step-main" }, h("b", { text: it.title }), it.sub ? h("p", { class: "muted", text: it.sub }) : null))));
}

export default {
  title: "전체",
  tab: "more",
  async render(ctx) {
    const { main } = ctx;
    // 오른쪽 값(동의 켜짐 수·조력자 수 등). 불러오기 전에는 비워 둔다
    const val = { consent: valueSlot(), helpers: valueSlot(), counselors: valueSlot() };
    const soon = (key) => () => openSoon(key, { go: ctx.go });
    const bankApp = getBankApp();

    fill(main,
      h("h2", { class: "page-title", tabindex: "-1", text: "전체" }),

      group("나를 지키는 설정",
        valueRow({ icon: "toggle", tone: "blue", title: "동의", href: "#/more/consent", value: val.consent }),
        valueRow({ icon: "users", tone: "blue", title: "조력자", href: "#/more/helpers", value: val.helpers }),
        valueRow({ icon: "building", tone: "blue", title: "상담하는 곳", href: "#/more/counselors", value: val.counselors })),

      group("거래 연결",
        menuRow({ icon: "bank", title: "은행 계좌 연결", soon: true, onclick: () => openBankConnect(ctx) }),
        menuRow({ icon: "card", title: "카드 연결", soon: true, onclick: () => openCardConnect(ctx) }),
        menuRow({ icon: "sig-phone-pay", title: "휴대폰 결제 연결", soon: true, onclick: () => openPhonePayConnect(ctx) }),
        menuRow({ icon: "upload", title: "파일로 거래 불러오기", onclick: () => ctx.go("txns?open=upload") })),

      // 앱 설정 화면 하나로 들어간다(IA-8). 내 은행 앱은 이름을 따로 보여 바로 찾게 한다
      group("앱 설정",
        withParts(menuRow({ icon: "settings", title: "앱 설정", href: "#/more/settings" }),
          [`글자 크기 ${FONT_KO[getPref("font")]}`, `화면 모드 ${THEME_KO[getPref("theme")]}`, "휴대폰 알림", "앱 잠금"]),
        valueRow({ icon: "bank", title: "내 은행 앱", href: "#/more/settings?part=bank",
          value: valueSlot(bankApp ? bankApp.label : "없음") })),

      group("내 계정·데이터",
        withParts(menuRow({ icon: "user-check", title: "내 계정", soon: true, onclick: soon("account") }), ["로그인", "로그아웃", "회원 탈퇴"]),
        menuRow({ icon: "refresh", title: "백업·되살리기", sub: "휴대폰을 바꿔도 내 설정을 이어서 써요.", soon: true, onclick: soon("transfer") })),

      group("조력자·기관용",
        menuRow({ icon: "chart", title: "AI 성능 확인", href: "#/more/eval" }),
        menuRow({ icon: "download", title: "결과 내보내기", href: "#/more/export" }),
        menuRow({ icon: "link", title: "조력자 앱 연결", soon: true, onclick: soon("helperApp") })),

      group("도움말·정보",
        menuRow({ icon: "help", title: "사용법 안내", href: "#/more/guide" }),
        menuRow({ icon: "headset", title: "고객센터", soon: true, onclick: soon("support") }),
        menuRow({ icon: "doc", title: "이용약관", soon: true, onclick: soon("terms") }),
        menuRow({ icon: "shield", title: "개인정보 처리방침", soon: true, onclick: soon("privacy") }),
        menuRow({ icon: "info", title: "AI와 데이터 설명", href: "#/more/about" }),
        valueRow({ icon: "code", title: "버전 정보", onclick: () => openVersion(ctx), value: valueSlot(APP_VERSION) })),

      // 분석은 안에서만 한다. 알림 보내기에서 내가 보내는 글은 문자·메일 앱으로 넘어간다(C10: 모든 일이라고 하지 않음)
      h("div", { class: "notice more-local" }, icon("lock"), h("div", null,
        h("strong", { text: `분석은 모두 ${deviceWord()} 안에서만 해요.` }),
        h("p", { text: MODE === "engine"
          ? "이 앱은 인터넷 권한이 없어요. 알림 보내기에서 내가 보내는 글만 문자·메일 앱으로 넘어가요."
          : "알림 보내기에서 내가 보내는 글만 문자·메일 앱으로 넘어가요." }))),
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

// 메뉴 줄 아래 작은 글을 조각으로(조각 안에서는 줄을 바꾸지 않음: 글자 크기 보통 · 화면 모드 자동)
function withParts(row, parts) {
  row.querySelector(".row-main").append(subParts(parts));
  return row;
}

function group(head, ...rows) {
  return [h("h3", { class: "section-title", text: head }), h("div", { class: "list" }, rows)];
}

function valueSlot(text = "") {
  return h("span", { class: "menu-val", text });
}

// 이름 + 오른쪽 값 메뉴 줄. 큰 글씨로 자리가 모자라면 값이 이름 아래 줄로 내려간다(한 글자씩 끊기지 않게)
function valueRow({ icon: ic, tone = "", title, sub = "", href = null, onclick = null, value }) {
  const inner = [
    h("span", { class: `row-icon ${tone}`.trim() }, icon(ic)),
    h("span", { class: "row-main with-val" }, h("span", { class: "row-title", text: title }), value,
      sub ? h("span", { class: "row-sub", text: sub }) : null),
    h("span", { class: "row-chev" }, icon("chevron")),
  ];
  return href ? h("a", { class: "row menu-row", href }, inner) : h("button", { type: "button", class: "row menu-row", onclick }, inner);
}

// 버전 정보: 앱 버전·실행 방식·AI 엔진 상태(앱은 엔진 준비 단계를 따라 바뀐다)
function openVersion(ctx) {
  const ver = h("dd", { class: "tnum", text: APP_VERSION });
  const state = h("dd", { text: MODE === "engine" ? engineText(engine.status) : "확인하고 있어요" });
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
  if (MODE === "engine") unsub = engine.subscribe((s) => setText(state, engineText(s)));
  ctx.req("GET", "/api/health").then((r) => {
    if (r && r.version) setText(ver, r.version);
    if (MODE !== "engine") setText(state, r && r.status === "ok" ? "준비됐어요" : "확인하지 못했어요");
  }).catch((e) => {
    if (e !== STALE && MODE !== "engine") setText(state, "연결하지 못했어요");
  });
}

// AI 부분만 못 켰으면(fatal 아님) 기본 기능은 쓸 수 있다(FE-03)
function engineText(status) {
  const stage = status && status.stage;
  if (stage === "full") return "준비됐어요";
  if (stage === "basic") return "AI 분석을 켜고 있어요";
  if (stage === "error") return status.fatal === false ? "AI 분석만 켜지 못했어요" : "켜지 못했어요";
  return "켜고 있어요";
}
