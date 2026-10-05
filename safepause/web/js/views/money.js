/* 돈 보내기(보내기 탭의 첫 탭, #/send): 받는 사람·금액을 적고 → 보내기 전 확인 카드 → 본인이 정하면 내 은행 앱을 연다.
 * - SafePause는 돈을 옮기지 않는다. 보내기는 본인이 고른 은행 앱에서 한다(은행 이름·로고는 앱에 넣지 않음, bankapp.js).
 * - 확인: POST /api/safepause/check(아무것도 저장하지 않음) → 카드가 있으면 안전 정지 카드, 없으면(걱정 없음) 결과만 보인다.
 *   걱정 없음이면 decide를 부르지 않는다(본인이 고르지 않은 결정은 기록하지 않음, 수정 계획 1-A).
 *   거래 살펴보기 동의가 꺼져 있으면 확인하지 않은 결과를 보인다(보내는 길은 그대로 열어 둠).
 * - 카드 규칙(v0.2와 같음, tests/test_static_ui.py가 확인):
 *   등급 배지 → 그림 → 제목 → 줄 → 질문 → 조력자 안내 → 오류·닫기 → 소리로 듣기 → 선택지 3개(서버 순서·문구 그대로).
 *   닫을 수 없다(dismissible false). 처음 초점은 제목(#card-title). Esc·뒤로 가기는 닫지 않고 안 보낼래요로 초점만 옮긴다.
 *   대화상자 이름은 등급 + 제목(aria-labelledby card-level card-title). 세 선택지는 같은 모양이다(한쪽으로 이끌지 않음).
 *   칸이 넉넉하면 본문·선택지를 나누고(선택지가 늘 보임), 좁으면 카드 전체를 한 번에 스크롤한다(본문이 0px로 접히지 않게, fitLayout).
 *   나눈 본문이 넘치면 아래쪽을 흐리게 하고 아래로 더 있어요 표시를 둔다(질문·소리로 듣기가 본문 끝에 있음을 알게, L7).
 * - 결정: POST /api/safepause/decide → 결과 시트.
 *   그래도 보낼래요 → 계좌 이체면 내 은행 앱에서 보내 주세요 + [내 은행 앱 열기]·필수 문장, 가게·휴대폰 결제면 결과 글만(RF-7)
 *   안 보낼래요 → 보내지 않았어요 + [알림 보내기로 문자·메일 보내기](조력자에게 직접 알리는 길, RF-3)
 *   조력자에게 물어볼래요 → 물어볼 사람 고르기 → [문자로 물어보기]·[메일로 물어보기](알림 보내기에 조력자·글을 미리 채움)
 *   조력자 설정대로 적어 둔 기록은 보낸 것이 아니다: 보냈다는 약속을 쓰지 않고, 직접 보내는 버튼을 함께 둔다(C1·J4).
 * - 금액은 80만·1억 2천만처럼 적어도 바르게 읽고(parseKoreanAmount), 정확한 원 하나를 보인다(amountPreview). 0·한도는 그 자리에서 알린다.
 */
import { h, icon, picto, fill, setText, openSheet, busy, announce, toast, comingSoonSheet } from "../ui.js";
import { nf, formatWon, moneyText, amountPreview, parseKoreanAmount, sentence, deviceWord } from "../format.js";
import { LEVEL, DECISION_ICON, EXAMPLES, PAY_CHANNELS, COUNSELING_TITLE, AI_TEXT } from "../labels.js";
import { levelBadge, speakButton, menuRow, noVoiceNote } from "../components.js";
import { capabilities } from "../native.js";
import { STALE, isConsentError } from "../api.js";
import * as speech from "../speech.js";
import { bankAppActions, getBankApp, pickBankApp, bankAppUnavailable } from "./bankapp.js";

const MAX_AMOUNT = 10000000000;   // api PendingIn.amount 한도(100억 원)
const MIN_TRAIN = 30;             // api constants.MIN_TRAIN: 거래가 이보다 적으면 AI 없이 약속(규칙)만 쓴다
const TIMES = [
  { value: "", label: "지금" },
  { value: "15:00", label: "오후 3시" },
  { value: "23:00", label: "밤 11시", icon: "sig-night" },
  { value: "02:00", label: "새벽 2시", icon: "sig-night" },
];
const QUICK_ADD = [10000, 50000, 100000, 500000];
const NO_CHECK = { spellcheck: "false", autocapitalize: "off", autocorrect: "off", autocomplete: "off" };
const MUST = "SafePause는 돈을 보내지 않아요. 보내기는 내 은행 앱에서 해요.";
const AMOUNT_HINT = "숫자로 적어 주세요. 예: 800000 또는 80만";
const TOO_BIG = "금액이 너무 커요(100억 원까지).";
const NO_WORRY = "걱정되는 점이 없어요.";
const TO_NOTIFY = "알림 보내기로 문자·메일 보내기";
// 버튼 글의 가운뎃점 낱말(문자·메일)은 줄을 바꾸지 않는 조각으로 넣는다(문자 / ·메일로 끊기지 않게). 글 자체는 그대로다
function keepDot(text) {
  return h("span", null, String(text).split(/(\S*·\S*)/).filter(Boolean).map((part) => (part.includes("·") ? h("span", { class: "nowrap", text: part }) : part)));
}
// 결과 제목(거래 방법에 맞춰). 서버 decide의 message와 같은 글이다(easy_card.ChannelWords self_do·not_done).
// 서버 응답이 없는 경우(걱정 없음·동의 꺼짐)에는 이 표를 쓴다. 조력자에게 물어볼래요는 서버 글을 쓴다
const SEND_TITLE = { transfer: "내 은행 앱에서 보내 주세요.", card: "결제는 직접 해 주세요.", micropay: "결제는 직접 해 주세요." };
const STOP_TITLE = { transfer: "보내지 않았어요.", card: "결제하지 않았어요.", micropay: "결제하지 않았어요." };
// 요약 칸 이름: 계좌 이체는 받는 사람·보낼 시각, 가게·휴대폰 결제는 받는 곳·결제 시각(RF-7)
const SUM_WORDS = {
  transfer: { to: "받는 사람", time: "보낼 시각" },
  card: { to: "받는 곳", time: "결제 시각" },
  micropay: { to: "받는 곳", time: "결제 시각" },
};
// 계좌 연결해서 바로 보내기(준비 중): 오픈뱅킹 출금 이체 순서. 마이데이터는 조회 전용이라 쓰지 않는다(C4·IA-4)
const SOON_STEPS = [
  { title: "계좌 연결", sub: "오픈뱅킹으로 내 계좌를 연결해요." },
  { title: "출금 동의", sub: "이 앱에서 내 계좌의 돈을 보내도 된다고 동의해요." },
  { title: "받는 사람과 금액 적기" },   // 받는 사람·금액은 가운뎃점 묶음이라 큰 글씨에서 받는 / 사람·금액 적기로 갈렸다
  { title: "보내기 전 확인 카드", sub: "걱정되는 점을 다시 물어봐요." },
  { title: "이체 인증", sub: "은행이 정한 본인\u00a0인증과 한도를 거쳐요." },   // 본인 인증(한 말)은 줄을 바꾸지 않는 빈칸으로
  { title: "보내기 완료" },
];

// 확인한 거래: 알림 보내기가 저장된 거래에서 그 거래를 못 찾을 때(안 보낼래요·물어볼래요는 거래 이력에 적지 않음) 쓴다.
// 이 창의 기억(메모리) + 이 탭의 sessionStorage(새로 고쳐도 남고, 탭을 닫으면 사라짐). 모두 지우기·거래 살펴보기 끄기 때는
// clearChecked로 둘 다 지운다(consent.js). 메모리 항목은 세대(epoch)가 바뀌면 버린다(IA-1).
// 주소에는 거래 id(live-…)만 남긴다: 받는 사람 칸에 적은 계좌번호 같은 글이 주소·방문 기록에 남지 않게(⑰).
// sessionStorage에는 받는 사람 이름·금액·방법·시각·등급·신호·돈 받는 조력자 id만 둔다(계좌번호 칸 값은 넣지 않음).
// 시각(ts)을 함께 되살려 새로 고친 뒤에도 받는 사람 추천·미리 체크가 처음과 같다(⑯: 시각이 없으면 서버가 지금 시각으로 다시 판단했다)
const checked = new Map();
const CHECKED_KEY = "safepause.checked";
const CHECKED_MAX = 5;
function readChecked() {
  try {
    const v = JSON.parse(window.sessionStorage.getItem(CHECKED_KEY) || "[]");
    return Array.isArray(v) ? v.filter((x) => x && typeof x === "object" && typeof x.id === "string") : [];
  } catch (e) { return []; }
}
function writeChecked(list) {
  try {
    if (list.length) window.sessionStorage.setItem(CHECKED_KEY, JSON.stringify(list));
    else window.sessionStorage.removeItem(CHECKED_KEY);
  } catch (e) { /* 저장 못 하면(사생활 보호 창 등) 이 창의 기억만 쓴다 */ }
}
/** sessionStorage에 적어 둔 확인 거래를 항목(_item 모양)으로. */
function fromStored(s, epoch) {
  const channel = ["transfer", "card", "micropay"].includes(s.channel) ? s.channel : "transfer";
  return {
    txn: { id: s.id, counterparty: String(s.to || "").slice(0, 40), amount: Math.min(10000000000, Math.max(0, Math.round(Number(s.amount) || 0))),
      channel, ts: /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(String(s.ts || "")) ? String(s.ts) : "", direction: "out" },
    level: ["none", "caution", "high"].includes(s.level) ? s.level : "none",
    signals: Array.isArray(s.signals) ? s.signals.map(String).slice(0, 10) : [],
    reasons: Array.isArray(s.reasons) ? s.reasons.filter((x) => x && typeof x.code === "string").slice(0, 10) : [],
    practice: true, flagged: false, unsaved: s.unsaved !== false,
    conflict_ids: Array.isArray(s.conflicts) ? s.conflicts.map(String).slice(0, 10) : [],
    epoch,
  };
}
/** 돈 보내기에서 확인한 거래의 항목(_item 모양) 또는 null. epoch를 주면 그 세대에 기억한 것만 돌려준다. notify.js가 쓴다. */
export function checkedItem(id, epoch) {
  const key = String(id || "");
  const it = checked.get(key);
  if (it) {
    if (epoch !== undefined && it.epoch !== epoch) { checked.delete(key); return null; }
    return it;
  }
  const s = readChecked().find((x) => x.id === key);   // 새로 고친 뒤: 이 탭에 적어 둔 것
  if (!s) return null;
  const item = fromStored(s, epoch);
  checked.set(key, item);
  return item;
}
/** 확인 거래 기억을 모두 지운다(이 창 + 이 탭의 sessionStorage). 모두 지우기·거래 살펴보기 끄기 때 부른다. */
export function clearChecked() { checked.clear(); writeChecked([]); }
function remember(r, epoch, cands) {
  const p = r && r.pending;
  if (!p || !p.id) return;
  const a = r.assessment || {};
  const item = {
    txn: { ...p, direction: "out" }, level: a.level || "none",
    signals: (a.rule_hits || []).map((x) => x.code), reasons: a.reasons || [], practice: true, flagged: false,
    unsaved: !r.added_to_history,   // 거래 이력에 적지 않은 거래(알림 보내기는 이것을 pending으로 추천에 넘긴다, RF-1)
    // 이 거래에서 돈을 받는 조력자(추천을 못 받을 때도 체크를 풀고 경고하게)
    conflict_ids: (cands || []).filter((c) => c.conflict).map((c) => String(c.id)),
    epoch,
  };
  checked.set(String(p.id), item);
  const keep = {
    id: String(p.id), to: String(p.counterparty || "").slice(0, 40), amount: Number(p.amount) || 0, channel: p.channel || "transfer",
    ts: String(p.ts || ""), level: item.level, signals: item.signals,
    reasons: item.reasons.map((x) => ({ code: String(x.code), detail: x.detail && x.detail.newness_unknown ? { newness_unknown: true } : {} })),
    conflicts: item.conflict_ids, unsaved: item.unsaved,
  };
  writeChecked([...readChecked().filter((x) => x.id !== keep.id), keep].slice(-CHECKED_MAX));
}
// 서버 글 목록에서 빈 줄을 뺀다(서버 check·decide 글에는 연습이라는 말이 없다: tests/test_api_v03.py가 확인)
const clean = (lines) => (lines || []).map(String).filter(Boolean);

export default {
  title: "돈 보내기",
  async render(ctx) {
    const { main, go } = ctx;
    const toInput = h("input", { class: "input", id: "pay-to", type: "text", maxlength: "40", ...NO_CHECK, "aria-describedby": "pay-to-error pay-to-hint" });
    const toError = h("p", { class: "error-text", id: "pay-to-error", role: "alert", hidden: true });
    const payeeBox = h("div", { class: "mn-payees", hidden: true });
    const amountInput = h("input", { class: "input big", id: "pay-amount", type: "text", inputmode: "numeric", maxlength: "20", ...NO_CHECK, "aria-describedby": "pay-amount-easy" });
    const amountEasy = h("p", { class: "amount-easy", id: "pay-amount-easy", "aria-live": "polite" });
    const toIdInput = h("input", { class: "input", id: "pay-to-id", type: "text", maxlength: "60", ...NO_CHECK });
    const errorText = h("p", { class: "error-text", id: "pay-error", role: "alert", hidden: true });
    const checkBtn = h("button", { type: "submit", class: "btn primary big block" }, icon("shield"), h("span", { text: "보내기 전에 확인하기" }));
    const ctaBar = h("div", { class: "cta-bar" }, checkBtn);
    const channelSeg = segmented("pay-channel", PAY_CHANNELS, "transfer", "pay-channel-label");
    const timeSeg = segmented("pay-time", TIMES, "", "pay-time-label", () => paintMore());
    const moreSub = h("span", { class: "mn-more-sub" });
    const more = h("details", { class: "mn-more" },
      h("summary", null, h("span", { class: "mn-more-text" }, h("span", { class: "mn-more-title", text: "자세히" }), moreSub),
        icon("chevron-down", "mn-more-chev")),
      h("div", { class: "field" }, h("span", { class: "field-label", id: "pay-time-label", text: "보낼 시각" }), timeSeg.el,
        h("p", { class: "hint", text: "다른 시각을 고르면 그 시각에 보내는 것으로 보고 확인해요." })),
      h("div", { class: "field mn-last" }, h("label", { for: "pay-to-id", text: "계좌번호 (없으면 비워 두어요)" }), toIdInput));

    const form = h("form", { class: "card mn-form", novalidate: true, autocomplete: "off", "aria-label": "보낼 돈" },
      h("div", { class: "field" }, h("label", { for: "pay-to", text: "받는 사람 (또는 가게)" }), toInput, toError,
        h("p", { class: "hint", id: "pay-to-hint", text: "예: 엄마, 김*호, 새로 연 전자상가" }), payeeBox),
      h("div", { class: "field" }, h("label", { for: "pay-amount", text: "금액" }), amountInput, amountEasy,
        h("div", { class: "chips mn-add", role: "group", "aria-label": "금액 더하기" }, QUICK_ADD.map((n) => h("button", {
          type: "button", class: "chip", onclick: () => {
            const text = amountInput.value.trim();
            const cur = text ? parseKoreanAmount(text) : 0;
            if (!Number.isFinite(cur)) { formError(`먼저 금액을 고쳐 주세요. ${AMOUNT_HINT}`, amountInput); return; }
            setAmount(cur + n);
          },
        }, icon("plus"), h("span", { text: formatWon(n) }))),
        h("button", { type: "button", class: "chip", onclick: () => { amountInput.value = ""; updateEasy(); amountInput.focus(); } }, h("span", { text: "지우기" })))),
      h("div", { class: "field" }, h("span", { class: "field-label", id: "pay-channel-label", text: "어떻게 보내요?" }), channelSeg.el),
      more,
      errorText,
      ctaBar);

    // 화면 위 안내: 거래 수·동의에 따라 살펴보는 방법을 사실대로 쓴다(C13: 30건보다 적으면 약속(규칙)만, 동의가 꺼져 있으면 살펴보지 않음)
    const lead = h("p", { class: "page-sub mn-lead", text: "보내기 전에 받는 사람과 금액을 한 번 더 살펴봐요." });
    const bankRowSlot = h("div");
    // 필수 문장 안내는 폼 아래에 둔다(첫 화면에서 받는 사람 칸이 확인 버튼에 가리지 않게, L5·D7)
    fill(main,
      lead,
      form,
      h("div", { class: "notice blue mn-must" }, icon("shield"), h("div", null,
        h("p", { class: "strong", text: MUST }),
        h("p", { text: "계좌 이체는 확인이 끝나면 내가 고른 은행 앱을 열어 드려요." }))),
      h("h3", { class: "section-title", text: "보내는 방법" }),
      bankRowSlot,
      h("h3", { class: "section-title", text: "예시로 해 보기" }),
      h("div", { class: "card flat mn-examples" },
        h("p", { class: "muted", text: "누르면 예시 내용으로 칸을 채워요. 확인은 직접 눌러요." }),
        h("div", { class: "chips", role: "group", "aria-label": "예시" }, EXAMPLES.map((ex) => h("button", { type: "button", class: "chip", onclick: () => fillExample(ex) },
          icon("edit"), h("span", { text: ex.label }))))),
      noVoiceNote("muted mn-novoice"));

    paintBankRow();
    paintMore();
    amountInput.addEventListener("input", () => { amountInput.removeAttribute("aria-invalid"); updateEasy(); });
    toInput.addEventListener("input", () => { toInput.removeAttribute("aria-invalid"); toError.hidden = true; });
    form.addEventListener("submit", onCheck);

    let pending = null;      // 카드에서 고르기를 기다리는 거래(check 요청 + 정해진 시각·id)
    let lastCheck = null;
    let chosenTime = "";     // 자세히에서 고른 보낼 시각(지금이면 빈 글)

    // 확인 버튼은 화면 아래에 붙어 따라온다. 다만 첫 화면에서 받는 사람 칸을 가리면(큰 글씨·짧은 화면) 붙이지 않고 폼 끝에 둔다(L5)
    function fitCta() {
      if (!ctaBar.isConnected) return;
      const active = document.activeElement;
      if (active && form.contains(active) && active !== checkBtn && /^(INPUT|TEXTAREA)$/.test(active.tagName)) return;   // 자판이 열린 동안은 그대로
      ctaBar.classList.remove("free");
      const cs = window.getComputedStyle(ctaBar);
      if (cs.position !== "sticky") return;
      const stuckTop = window.innerHeight - (parseFloat(cs.bottom) || 0) - ctaBar.offsetHeight;
      const firstBottom = toInput.getBoundingClientRect().bottom + window.scrollY;
      ctaBar.classList.toggle("free", firstBottom > stuckTop - 4);
    }
    const onResize = () => fitCta();
    window.addEventListener("resize", onResize);
    ctx.onCleanup(() => window.removeEventListener("resize", onResize));
    window.requestAnimationFrame(fitCta);

    // 내 은행 앱 줄 + 계좌 연결해서 바로 보내기(준비 중)
    function paintBankRow() {
      const app = getBankApp();
      const why = bankAppUnavailable();
      fill(bankRowSlot, h("div", { class: "list" },
        menuRow({ icon: "bank", tone: "blue", title: "내 은행 앱", sub: why || (app ? app.label : "확인한 뒤 열 은행 앱을 골라 두세요."),
          onclick: async () => {
            if (why) { toast(why); return; }
            const picked = await pickBankApp();
            if (!ctx.alive()) return;
            paintBankRow();
            if (picked) toast(`내 은행 앱: ${picked.label}`);
            bankRowSlot.querySelector(".menu-row").focus();
          } }),
        menuRow({ icon: "link", title: "계좌 연결해서 바로 보내기", sub: "은행 앱을 열지 않고 여기서 보내요.", soon: true,
          onclick: () => comingSoonSheet({
            icon: "bank", title: "계좌 연결해서 바로 보내기",
            lines: ["계좌를 연결해(오픈뱅킹) 이 앱에서 바로 보내요.", "보내기 전에 받는 사람과 금액을 살펴보는 것은 그대로 해요."],
            steps: SOON_STEPS, action: "계좌 연결하기",
          }) })));
    }

    function paintMore() {
      const t = TIMES.find((x) => x.value === timeSeg.value()) || TIMES[0];
      const id = toIdInput.value.trim();
      // 이름과 값(시각 지금)은 묶어 둔다: 큰 글씨에서 값만 다음 줄에 홀로 남지 않게(보낼 / 시각 지금)
      fill(moreSub, "보낼 ", h("span", { class: "nowrap", text: `시각 ${t.label}` }), id ? " · 계좌번호 적음" : "");
    }
    toIdInput.addEventListener("input", paintMore);

    function setAmount(n) { amountInput.value = nf.format(Math.min(n, MAX_AMOUNT)); amountInput.removeAttribute("aria-invalid"); updateEasy(); }
    function isZero(text) { return text.replace(/[\s,원]/g, "") === "0"; }
    function updateEasy() {
      const text = amountInput.value.trim();
      const n = parseKoreanAmount(text);
      amountEasy.classList.remove("bad");
      if (!text) { amountEasy.textContent = ""; return; }
      let msg;
      if (isZero(text)) msg = "0보다 큰 금액을 적어 주세요.";
      else if (!Number.isFinite(n)) msg = AMOUNT_HINT;
      else if (n > MAX_AMOUNT) msg = TOO_BIG;
      if (msg) { amountEasy.classList.add("bad"); amountEasy.textContent = msg; return; }
      amountEasy.textContent = amountPreview(n);   // 정확한 원 단위 하나(반올림한 만 원 표기를 붙이지 않음, RF-4)
    }
    function fillExample(ex) {
      toInput.value = ex.to;
      setAmount(ex.amount);
      channelSeg.set(ex.channel);
      timeSeg.set(ex.time);
      toIdInput.value = "";
      paintMore();
      clearErrors();
      checkBtn.focus();
      checkBtn.scrollIntoView({ block: "nearest" });
      announce("예시로 칸을 채웠어요. 보내기 전에 확인하기를 눌러 보세요.");
    }
    function clearErrors() {
      errorText.hidden = true;
      toError.hidden = true;
      toInput.removeAttribute("aria-invalid");
      amountInput.removeAttribute("aria-invalid");
    }
    // 오류는 틀린 칸 바로 아래에 쓰고 그 칸에 초점을 둔다(받는 사람은 칸 아래, 금액은 금액 풀이 줄).
    // 서버 오류처럼 칸이 없는 오류는 확인 버튼 바로 위에 쓴다(2차 검증: 오류가 화면 밖에 있지 않게)
    function formError(message, el) {
      const box = el === toInput ? toError : el === amountInput ? amountEasy : errorText;
      setText(box, message);
      box.hidden = false;
      if (box === amountEasy) amountEasy.classList.add("bad");
      if (el) { el.setAttribute("aria-invalid", "true"); el.setAttribute("aria-errormessage", box.id); el.focus({ preventScroll: true }); }
      box.scrollIntoView({ block: "nearest" });   // 아래에 붙은 확인 버튼에 가리지 않게(scroll-margin, money.css)
    }

    // 화면 위 안내 문장(C13)과 최근에 보낸 사람(거래 살펴보기 동의가 있을 때만)을 함께 불러온다
    paintLead();
    try {
      const p = await ctx.req("GET", "/api/payees");
      const names = (p.items || []).slice(0, 6);
      if (names.length) {
        fill(payeeBox, h("p", { class: "mn-payees-title", id: "pay-recent", text: "최근에 보낸 사람" }),
          h("div", { class: "chips", role: "group", "aria-labelledby": "pay-recent" }, names.map((n) => h("button", { type: "button", class: "chip", onclick: () => {
            toInput.value = n; toInput.removeAttribute("aria-invalid"); amountInput.focus();
          } }, icon("sig-person"), h("span", { text: n })))));
        payeeBox.hidden = false;
      }
    } catch (e) { if (e === STALE) return; /* 동의가 없거나 아직 못 읽으면 목록 없이 쓴다 */ }

    async function paintLead() {
      try {
        const c = await ctx.req("GET", "/api/consent");
        if (!c || !c.monitoring) { setText(lead, "거래 살펴보기가 꺼져 있어서 지금은 살펴보지 않아요."); fitCta(); return; }
        const s = await ctx.req("GET", "/api/data/summary");
        const n = Number(s && s.count) || 0;
        setText(lead, n < MIN_TRAIN
          ? `보내기 전에 받는 사람과 금액을 약속(규칙)으로 한 번 더 살펴봐요. ${AI_TEXT.aiLearning}`
          : "보내기 전에 받는 사람과 금액을 약속(규칙)과 AI로 한 번 더 살펴봐요.");
        fitCta();
      } catch (e) { /* 못 읽으면 처음 문장 그대로 */ }
    }

    async function onCheck(e) {
      e.preventDefault();
      clearErrors();
      const to = toInput.value.trim();
      const amount = parseKoreanAmount(amountInput.value);
      if (!to) { formError("받는 사람을 적어 주세요.", toInput); return; }
      if (!amountInput.value.trim()) { formError("금액을 적어 주세요.", amountInput); return; }
      if (isZero(amountInput.value.trim())) { formError("0보다 큰 금액을 적어 주세요.", amountInput); return; }
      if (!Number.isFinite(amount) || amount <= 0) { formError(`금액을 고쳐 주세요. ${AMOUNT_HINT}`, amountInput); return; }
      if (amount > MAX_AMOUNT) { formError(TOO_BIG, amountInput); return; }
      const req = { to, amount, channel: channelSeg.value() || "transfer", to_id: toIdInput.value.trim() };
      const time = timeSeg.value();
      if (time) req.time = time;
      await busy(checkBtn, async () => {
        try {
          const r = await ctx.req("POST", "/api/safepause/check", req);
          pending = { id: r.pending.id, to: req.to, amount: req.amount, channel: req.channel, to_id: req.to_id, ts: r.pending.ts };
          lastCheck = r;
          chosenTime = req.time || "";
          if (r.card) openCard(r);
          else showNoWorry(req);   // 걱정 없음: 결정을 기록하지 않고 결과만(수정 계획 1-A)
        } catch (err) {
          if (err === STALE) return;
          if (isConsentError(err)) showUnchecked(req);
          else formError(sentence(err.message || "확인하지 못했어요. 다시 해 주세요."));
        }
      });
    }

    // ---- 안전 정지 카드 -------------------------------------------------------------
    function openCard(r) {
      const card = r.card;
      const lv = LEVEL[card.level] || LEVEL.caution;
      let sheetApi = null;
      let deciding = false;    // decide 요청 중(버튼은 disabled 대신 aria-disabled: 초점이 body로 빠지지 않게)
      const body = h("div", { class: "sheet-body" });
      const errorSlot = h("div", { class: "pause-error" });
      const foot = h("div", { class: "sheet-foot", role: "group", "aria-label": "고르기" });
      // 나눈 본문이 넘칠 때 아래로 더 있다는 표시(누르면 본문을 내린다). 읽는 순서를 흐리지 않게 화면 낭독에서는 숨긴다
      const below = h("button", { type: "button", class: "btn sm ghost mn-below", tabindex: "-1", "aria-hidden": "true",
        onclick: () => body.scrollBy({ top: Math.max(body.clientHeight * 0.7, 80), behavior: "smooth" }) },
      icon("chevron-down"), h("span", { text: "아래로 더 있어요" }));
      body.addEventListener("scroll", () => paintBelow(), { passive: true });

      const notes = (() => {
        const plan = r.notify_plan_preview;
        const out = [];
        if (plan && plan.note_to_person && ((plan.notices || []).length || (plan.excluded_conflict || []).length)) out.push(plan.note_to_person);
        out.push(askPreviewText(candidatesOf(r)));
        return clean(out);
      })();
      const speakText = () => {
        const choices = card.choices.map((c) => c.label).join(", ");
        return [lv.text, card.speak_text, ...notes, `고를 수 있어요. ${choices}.`].map(sentence).join(" ");
      };

      function showMain() {
        fill(body,
          h("div", { class: "pause-head" },
            h("span", { id: "card-level" }, levelBadge(card.level)),
            h("div", { class: "pictos", "aria-hidden": "true" }, (card.pictograms || []).map((p) => picto(p))),
            h("h2", { class: "pause-title focus-target", id: "card-title", tabindex: "-1", text: card.title })),
          h("ul", { class: "pause-lines", id: "card-lines" }, card.lines.map((line) => h("li", null, h("p", { text: line })))),
          h("p", { class: "pause-question", text: card.question }),
          notes.length ? h("div", { class: "helper-note" }, icon("users"), h("p", { text: notes.join(" ") })) : null,   // 같은 사람 이야기는 한 문단(⑥)
          errorSlot,
          speakButton(speakText, { cls: "btn block pause-speak", label: "소리로 듣기" }));
        // 선택지는 서버가 준 순서·문구 그대로. 세 선택지를 같은 모양으로 둔다(한쪽으로 이끌지 않음)
        fill(foot, below, card.choices.map((c) => h("button", {
          type: "button", class: "btn big block choice-btn", "data-decision": c.decision,
          onclick: () => { if (deciding) return; if (c.decision === "ask_helper") showAsk(); else choose(c.decision); },
        }, h("span", { class: "ci" }, icon(DECISION_ICON[c.decision] || "check")), h("span", { text: c.label }))));
        fitLayout();
      }

      // 칸이 넉넉할 때만 본문·선택지를 나눈다(선택지가 늘 아래에 보이게). 나눈 뒤 본문 칸(시트 높이 − 손잡이·위 여백 − 선택지 띠)이
      // 40%(최소 240px)·본문 최소 높이·'머리(제목 띠) + 글 네 줄'보다 작아지면 가로 화면·큰 글씨로 보고 카드 전체를 한 번에 스크롤한다
      // (본문이 0px로 접히거나, 선택지·손잡이가 시트 밖으로 잘리거나, 머리만 보이고 이유 글이 한두 줄만 보이지 않게, 2차 검증 C1·2026-10-03 검토).
      // 손잡이(::before)와 위 여백도 뺀다: 빼지 않으면 '손잡이 + 본문 최소 높이 + 띠'가 시트보다 길어져 셋째 선택지 아래와 손잡이가 잘렸다.
      // 재려고 split을 잠깐 붙이면 시트의 스크롤 범위가 줄어 읽던 자리가 깎이므로(창 크기가 바뀔 때마다 위로 튐) 읽던 자리를 되돌린다.
      // 아래로 더 있어요(mn-below)는 띠 위에 떠 있어 띠 높이에 들지 않는다(보였다 숨었다 해도 선택지가 밀리지 않게)
      function fitLayout() {
        const el = sheetApi && sheetApi.el;
        if (!el) return;
        const wasSplit = el.classList.contains("split");
        const sheetTop = el.scrollTop;
        const bodyTop = body.scrollTop;
        el.classList.add("split");
        const room = el.clientHeight;
        // 본문 위 자리(위 여백·손잡이): 시트 안쪽 위 끝에서 본문 위 끝까지(나누든 안 나누든 같다)
        const above = Math.max(0, body.getBoundingClientRect().top - el.getBoundingClientRect().top - el.clientTop + el.scrollTop);
        const bs = getComputedStyle(body);
        const bodyMin = parseFloat(bs.minHeight) || 0;
        const head = body.querySelector(".pause-head, .sheet-title");
        const lh = parseFloat(bs.lineHeight) || parseFloat(bs.fontSize) * 1.6;
        const readable = (head ? head.offsetHeight : 0) + 4 * lh;
        const fits = room >= 420 && room - above - foot.offsetHeight >= Math.max(room * 0.4, 240, bodyMin, readable);
        el.classList.toggle("split", fits);
        // 읽던 자리: 본문 스크롤과 시트 스크롤은 같은 글을 같은 화면 높이에 둔다(나눔이 바뀌어도 그 자리 그대로)
        if (fits) {
          el.scrollTop = 0;   // 나눈 카드는 본문만 스크롤한다(시트가 밀려 손잡이가 잘리지 않게)
          if (!wasSplit) body.scrollTop = sheetTop;
        } else {
          el.scrollTop = wasSplit ? bodyTop : sheetTop;
        }
        paintBelow();
      }
      function paintBelow() {
        const el = sheetApi && sheetApi.el;
        const more = Boolean(el && el.classList.contains("split") && body.scrollHeight - body.scrollTop - body.clientHeight > 8);
        below.hidden = !more;
        if (el) el.classList.toggle("has-more", more);
      }
      const onResize = () => fitLayout();
      window.addEventListener("resize", onResize);

      // 오류·닫기는 소리로 듣기·선택지 앞(카드 순서 규칙). 물어볼 사람 고르기 화면에도 같은 자리를 둔다(FE-02).
      // 닫으면 확인 버튼으로 돌아가 다시 할 수 있다
      function showError(err) {
        const msg = sentence(err.message || String(err));
        const box = h("div", { class: "notice red", role: "alert" }, icon("warning"), h("div", null,
          h("p", { text: `${msg} 닫기를 누르고 다시 해 볼 수 있어요.` }),
          h("button", { type: "button", class: "btn sm notice-action", onclick: () => { sheetApi.close(); checkBtn.focus(); } }, icon("close"), h("span", { text: "닫기" }))));
        fill(errorSlot, box);
        box.scrollIntoView({ block: "nearest" });
        box.querySelector("button").focus();
      }

      async function choose(decision, helperIds) {
        if (deciding) return;
        deciding = true;
        const buttons = [...foot.querySelectorAll("button"), ...body.querySelectorAll("button")];
        buttons.forEach((b) => { b.setAttribute("aria-disabled", "true"); });
        errorSlot.replaceChildren();
        try {
          await decide(decision, helperIds, sheetApi);
        } catch (err) {
          if (err === STALE) return;
          if (isConsentError(err)) { const p = pending; sheetApi.close(); if (p) showUnchecked(p); return; }
          showError(err);
        } finally {
          deciding = false;
          buttons.forEach((b) => { if (b.isConnected) b.removeAttribute("aria-disabled"); });
        }
      }

      // 조력자에게 물어볼래요 2단계: 물어볼 사람을 본인이 고른다(S37)
      function showAsk() {
        const cands = candidatesOf(r);
        errorSlot.replaceChildren();
        const back = h("button", { type: "button", class: "btn big block", onclick: () => {
          if (deciding) return;
          errorSlot.replaceChildren();
          showMain();
          foot.querySelector('[data-decision="ask_helper"]')?.focus();
        } }, icon("back"), h("span", { text: "돌아가기" }));
        if (!cands.some((c) => !c.conflict)) {
          const lines = askNobodyLines(cands);
          const orgs = (r.ask_helper_preview && r.ask_helper_preview.counseling_orgs) || [];
          fill(body,
            h("h2", { class: "sheet-title focus-target", id: "card-ask-title", tabindex: "-1", text: "물어볼 조력자가 없어요" }),
            h("p", { class: "sheet-sub", text: lines.join(" ") }),
            orgs.length ? h("div", { class: "notice blue" }, icon("building"), h("div", null, h("p", { class: "notice-lead", text: COUNSELING_TITLE }), h("ul", null, orgs.map((o) => h("li", { text: o }))))) : null,
            errorSlot,
            speakButton(() => ["물어볼 조력자가 없어요.", ...lines, ...(orgs.length ? [COUNSELING_TITLE, ...orgs] : [])].map(sentence).join(" ")));
          fill(foot, below,
            h("button", { type: "button", class: "btn primary big block mn-ask-go", onclick: () => choose("ask_helper", []) }, icon("building"), h("span", { text: "상담하는 곳에 알릴래요" })),
            back);
          fitLayout();
          body.scrollTop = 0;
          sheetApi.el.scrollTop = 0;   // 새 화면은 맨 위부터(나누지 않은 카드는 시트가 스크롤된다)
          body.querySelector("#card-ask-title").focus();
          return;
        }
        // 이름 줄 + (있으면) 아래 작은 줄 하나: 자동으로 함께 묻는 사람은 체크를 풀 수 없다는 것을 그 줄에서 한 번만 말한다(⑥)
        const who = (c) => (c.relation ? `${c.name} (${c.relation})` : c.name);
        const note = (c) => (c.conflict ? "돈을 받는 사람이라 이번에는 물어볼 수 없어요."
          : c.auto ? "조력자 설정대로 늘 함께 물어봐요." : c.active === false ? "자동으로 알리기는 꺼 두었어요." : "");
        const label = (c) => [who(c), note(c)].filter(Boolean).join(" · ");
        const boxes = cands.map((c) => h("input", { type: "checkbox", value: c.id, checked: !c.conflict && (c.default || c.auto), disabled: c.conflict || c.auto }));
        const err = h("p", { class: "error-text", role: "alert", hidden: true });
        const hints = ["체크한 사람에게 물어봐요.", "다음 화면에서 문자나 메일을 직접 보내요."];
        fill(body,
          h("h2", { class: "sheet-title focus-target", id: "card-ask-title", tabindex: "-1", text: "누구에게 물어볼까요?" }),
          h("p", { class: "sheet-sub", text: hints.join(" ") }),
          h("div", { class: "list mn-ask-list" }, cands.map((c, i) => h("label", { class: `check-row row${c.conflict ? " off" : ""}` }, boxes[i],
            h("span", { class: "row-icon" }, icon("users")),
            h("span", { class: "grow row-main" }, h("span", { class: "row-title", text: who(c) }), note(c) ? h("span", { class: "row-sub", text: note(c) }) : null)))),
          err,
          errorSlot,
          speakButton(() => ["누구에게 물어볼까요?", ...hints, ...cands.map((c) => label(c))].map(sentence).join(" ")));
        fill(foot, below,
          h("button", {
            type: "button", class: "btn primary big block mn-ask-go",
            onclick: () => {
              // 체크를 풀 수 없는 자동 알림 대상도 함께 보낸다(그 사람에게도 물어봄)
              const ids = boxes.filter((b) => b.checked).map((b) => b.value);
              if (!ids.length) { err.textContent = "물어볼 사람을 한 명 이상 골라 주세요."; err.hidden = false; return; }
              err.hidden = true;
              choose("ask_helper", ids);
            },
          }, icon("helper"), h("span", { text: "체크한 사람에게 물어볼래요" })),
          back);
        fitLayout();
        body.scrollTop = 0;
        sheetApi.el.scrollTop = 0;   // 새 화면은 맨 위부터(나누지 않은 카드는 시트가 스크롤된다)
        body.querySelector("#card-ask-title").focus();
      }

      sheetApi = openSheet(() => [body, foot], {
        className: `pause split level-${card.level}`, dismissible: false,
        label: `${lv.text}: ${card.title}`,
        initialFocus: "#card-title",
        onEscape: () => {
          const askTitle = body.querySelector("#card-ask-title");
          if (askTitle) { if (deciding) return; showMain(); body.querySelector("#card-title").focus(); return; }
          foot.querySelector('[data-decision="cancel"]')?.focus();
        },
        onClose: () => { speech.stop(); window.removeEventListener("resize", onResize); },
      });
      showMain();
      sheetApi.el.setAttribute("aria-labelledby", "card-level card-title");
      window.requestAnimationFrame(() => { body.querySelector("#card-title")?.focus(); paintBelow(); });
    }

    async function decide(decision, helperIds, sheetApi) {
      const payload = { pending, decision };
      if (decision === "ask_helper" && Array.isArray(helperIds)) payload.helper_ids = helperIds;
      const r = await ctx.req("POST", "/api/safepause/decide", payload);
      if (pending && r.pending) pending.id = r.pending.id;   // 서버가 새 id를 줬으면 그 id로 다시 시도
      remember(r, ctx.session.epoch, candidatesOf(lastCheck));
      if (sheetApi) sheetApi.close();
      showResult(r, decision, helperIds);
      return r;
    }

    /** 보낼 것 요약(받는 사람·금액·방법·시각·계좌번호): 은행 앱에 옮겨 적기 쉽게. 결제 방법이면 받는 곳·결제 시각. */
    function summary(p, time) {
      const ch = PAY_CHANNELS.find((c) => c.value === p.channel) || PAY_CHANNELS[0];
      const words = SUM_WORDS[ch.value] || SUM_WORDS.transfer;
      const t = TIMES.find((x) => x.value === time);
      const rows = [
        [words.to, p.to || p.counterparty || ""],
        ["금액", moneyText(p.amount)],
        ["방법", ch.label],
        time && t ? [words.time, t.label] : null,
        p.to_id ? ["계좌번호", p.to_id] : null,
      ].filter(Boolean);
      return fitSummary(h("dl", { class: "mn-summary" }, rows.map(([k, v]) => h("div", { class: "mn-sum-row" }, h("dt", { text: k }), h("dd", { text: v })))));
    }

    /**
     * 알림 보내기 주소(확인한 거래를 미리 고름). opts: {helpers, ask, channel, counselors}
     * 저장하지 않은 확인 거래도 주소에는 거래 id만 넣는다. 받는 사람 이름·금액·시각 등은 이 탭의 sessionStorage(remember)에
     * 있어 새로 고쳐도 알림 보내기가 그 거래와 돈 받은 조력자 경고를 다시 그린다(받는 사람 칸의 글이 주소에 남지 않게, ⑰).
     */
    function notifyRoute(txnId, { helpers = [], ask = false, channel = "", counselors = false } = {}) {
      const q = new URLSearchParams({ mode: "notify" });
      if (txnId) q.set("txn", txnId);
      if (helpers.length) q.set("helper", helpers.join(","));
      if (counselors) q.set("to", "counselors");
      if (ask) q.set("ask", "1");
      if (channel) q.set("channel", channel);
      return `send?${q.toString()}`;
    }

    function showResult(r, decision, helperIds) {
      const p = { ...pending, ...(r.pending || {}), to: (pending && pending.to) || (r.pending && r.pending.counterparty) || "" };
      const plan = r.notify_plan || {};
      const channel = p.channel || "transfer";
      const transfer = channel === "transfer";
      const kind = decision === "cancel" ? "stop" : decision === "ask_helper" ? "ask" : "send";
      const title = decision === "send" ? sentence(r.message || SEND_TITLE[channel] || SEND_TITLE.transfer)
        : decision === "cancel" ? sentence(r.message || STOP_TITLE[channel] || STOP_TITLE.transfer)
          : sentence(clean([r.result_title])[0] || "조력자에게 물어봐요");
      const txnId = r.pending && r.pending.id;
      const added = Boolean(r.added_to_history);
      const cands = candidatesOf(lastCheck);
      const askedIds = (helperIds || []).map(String);
      const asked = decision === "ask_helper" ? cands.filter((c) => askedIds.includes(String(c.id)) && !c.conflict) : [];
      const caps = capabilities();
      const askWays = [caps.sms ? { value: "sms", label: "문자로 물어보기", icon: "chat" } : null,
        caps.email ? { value: "email", label: "메일로 물어보기", icon: "mail" } : null].filter(Boolean);
      const wayWord = caps.sms && caps.email ? "문자나 메일을" : caps.sms ? "문자를" : "메일을";

      // 결과 글: 물어볼래요는 서버 글 + 아래 버튼으로 직접 묻는다는 안내. 보냈다고 약속하지 않는다(C1·J4).
      // 제목(조력자에게 물어봐요)을 되풀이하는 첫 줄은 받는 사람·금액만 남겨 다음 줄과 합친다(⑥)
      const lines = [];
      if (decision === "ask_helper") {
        lines.push(...askLines(clean(r.result_lines), title));
        if (asked.length && askWays.length) lines.push(`아래 버튼으로 ${namesText(asked.map((c) => c.name))}에게 ${wayWord} 보내 물어봐요.`);
      }
      // 조력자 설정대로 적어 둔 기록(보낸 것이 아님): 서버 안내 문장과 장소·직접 보내는 길을 한 문단으로(RF-3·RF-6·C1·⑥)
      const showCounseling = Boolean(plan.suggest_counseling && (plan.counseling_orgs || []).length);
      const notes = [];
      if (decision !== "ask_helper") {
        const note = plan.note_to_person && !(showCounseling && plan.note_to_person === COUNSELING_TITLE) ? clean([plan.note_to_person])[0] || "" : "";
        notes.push(...recordedNote(note, r.notices_recorded > 0));
      }
      const tsNote = added ? clean([r.ts_note || (lastCheck && lastCheck.ts_note) || ""])[0] || "" : "";
      const spoken = [title, ...lines];
      if (decision === "send" && transfer) spoken.push(MUST);
      spoken.push(...notes);
      if (showCounseling) spoken.push(COUNSELING_TITLE, `${plan.counseling_orgs.join(", ")}.`);
      if (tsNote) spoken.push(tsNote);

      openSheet((close) => {
        const done = () => { close(); resetForm(added); };
        const toNotify = (route) => { close(); resetForm(added); go(route); };
        // 결과의 알림 보내기 버튼: 물어볼래요는 문자·메일 따로, 물어볼 조력자가 없었으면 상담하는 곳, 그 밖은 조력자에게 직접 알리기
        let notifyBtns = null;
        if (decision === "ask_helper" && asked.length) {
          notifyBtns = (askWays.length ? askWays : [{ value: "", label: TO_NOTIFY, icon: "chat" }]).map((w, i) => h("button", {
            type: "button", class: `btn ${i === 0 ? "primary" : "weak"} big block result-main`,
            onclick: () => toNotify(notifyRoute(txnId, { helpers: asked.map((c) => String(c.id)), ask: true, channel: w.value })),
          }, icon(w.icon), keepDot(w.label)));
        } else if (decision === "ask_helper") {
          notifyBtns = h("button", { type: "button", class: "btn primary big block result-main",
            onclick: () => toNotify(notifyRoute(txnId, { counselors: true })) }, icon("chat"), keepDot(TO_NOTIFY));
        } else if (lastCheck && lastCheck.card) {
          notifyBtns = h("button", { type: "button", class: `btn ${decision === "cancel" ? "primary" : "weak"} big block result-main`,
            onclick: () => toNotify(notifyRoute(txnId)) }, icon("chat"), keepDot(TO_NOTIFY));
        }
        return [
          h("div", { class: `result-hero ${kind}` },
            h("div", { class: "big-icon" }, icon(kind === "stop" ? "stop" : kind === "ask" ? "helper" : transfer ? "bank" : "check")),
            h("h2", { class: "focus-target", tabindex: "-1", text: title })),
          lines.length ? h("div", { class: "result-lines" }, h("p", { text: lines.join(" ") })) : null,
          decision === "send" ? summary(p, chosenTime) : null,
          decision === "send" && transfer ? bankAppActions() : null,
          decision === "send" && transfer ? mustLine() : null,
          decision === "send" ? null : notifyBtns,
          notes.length || showCounseling || tsNote || (decision === "send" && notifyBtns) ? h("div", { class: "result-notes" },
            notes.length ? h("p", { class: "muted mn-notes", text: notes.join(" ") }) : null,
            decision === "send" ? notifyBtns : null,
            showCounseling ? h("div", { class: "notice blue" }, icon("building"), h("div", null, h("p", { class: "notice-lead", text: COUNSELING_TITLE }), h("ul", null, plan.counseling_orgs.map((o) => h("li", { text: o }))))) : null,
            // 내 거래에 적는 날짜 안내는 접어 둔다(결과의 핵심 문장 수를 줄임, ⑥). 소리로 듣기에는 그대로 들어간다
            tsNote ? h("details", { class: "mn-ts" }, h("summary", null, h("span", { class: "mn-ts-label" }, "내 거래에 ", h("span", { class: "nowrap" }, "적는 날짜", icon("chevron-down", "mn-ts-chev")))),
              h("p", { class: "muted", text: tsNote })) : null) : null,
          h("div", { class: "sheet-actions" },
            speakButton(() => spoken.map(sentence).join(" ")),
            h("button", { type: "button", class: "btn big block", text: decision === "send" ? "닫기" : "확인", onclick: done })),
        ];
      }, { label: title, className: "mn-result" });
      announce(title);
    }

    // 걱정 없음(카드 없음): 결정을 기록하지 않는다. 계좌 이체일 때만 내 은행 앱을 연다(수정 계획 1-A·RF-7)
    function showNoWorry(req) {
      const channel = req.channel || "transfer";
      const transfer = channel === "transfer";
      const next = SEND_TITLE[channel] || SEND_TITLE.transfer;
      const spoken = [NO_WORRY, next, ...(transfer ? [MUST] : [])];
      openSheet((close) => [
        h("div", { class: "result-hero ok" }, h("div", { class: "big-icon" }, icon("check-line")),
          h("h2", { class: "focus-target", tabindex: "-1", text: NO_WORRY })),
        h("div", { class: "result-lines" }, h("p", { text: next })),
        summary(req, req.time || ""),
        transfer ? bankAppActions() : null,
        transfer ? mustLine() : null,
        h("div", { class: "sheet-actions" },
          speakButton(() => spoken.map(sentence).join(" ")),
          h("button", { type: "button", class: "btn big block", text: "닫기", onclick: () => { close(); resetForm(false); } })),
      ], { label: NO_WORRY, className: "mn-result" });
      announce(NO_WORRY);
    }

    // 거래 살펴보기 동의가 꺼져 있으면 확인하지 않는다. 그래도 보내는 길은 그대로 열어 둔다
    function showUnchecked(req) {
      const channel = req.channel || "transfer";
      const transfer = channel === "transfer";
      const title = SEND_TITLE[channel] || SEND_TITLE.transfer;
      const lines = ["거래 살펴보기가 꺼져 있어서 SafePause는 확인하지 않았어요."];
      openSheet((close) => [
        h("div", { class: "result-hero" }, h("div", { class: "big-icon" }, icon(transfer ? "bank" : "check")),
          h("h2", { class: "focus-target", tabindex: "-1", text: title })),
        h("div", { class: "result-lines" }, h("p", { text: lines.join(" ") })),
        summary(req, req.time || ""),
        transfer ? bankAppActions() : null,
        transfer ? mustLine() : null,
        h("div", { class: "sheet-actions" },
          speakButton(() => [title, ...lines, ...(transfer ? [MUST] : [])].map(sentence).join(" ")),
          h("button", { type: "button", class: "btn weak big block", onclick: () => { close(); go("more/consent"); } }, icon("toggle"), h("span", { text: "동의 켜러 가기" })),
          h("button", { type: "button", class: "btn big block", text: "닫기", onclick: () => { close(); resetForm(false); } })),
      ], { label: title, className: "mn-result" });
      announce(title);
    }

    function resetForm(added) {
      form.reset();
      channelSeg.set("transfer");
      timeSeg.set("");
      paintMore();
      amountEasy.textContent = "";
      clearErrors();
      pending = null;
      lastCheck = null;
      chosenTime = "";
      paintBankRow();
      if (!document.activeElement || document.activeElement === document.body) checkBtn.focus({ preventScroll: true });
      if (added) toast("확인한 거래를 내 거래에 적어 두었어요.");
    }
  },
};

/**
 * 보낼 것 요약 줄 맞추기: 한 줄이라도 값이 이름 아래로 내려가면(큰 글씨·좁은 화면) 모든 줄을 두 줄(이름 / 값)로 둔다.
 * 넘칠 때만 줄을 나누면 받는 사람 김*호(한 줄)·금액 / 300,000원(두 줄)처럼 줄마다 모양이 번갈아 나왔다(2026-10-03 검토).
 * 칸 폭·글자 크기가 바뀌면 다음 틀에서 다시 잰다(charts.js와 같은 방법). 화면에서 떨어지면 그친다.
 */
function fitSummary(dl) {
  let frame = 0;
  let last = "";
  let shown = false;
  let ro = null;
  const stop = () => { if (ro) ro.disconnect(); else window.removeEventListener("resize", schedule); };
  const run = () => {
    frame = 0;
    if (!dl.isConnected) { if (shown) stop(); return; }   // 시트를 닫아 화면에서 떨어졌으면 그친다
    shown = true;
    const key = `${dl.clientWidth}|${getComputedStyle(dl).fontSize}`;
    if (!dl.clientWidth || key === last) return;
    last = key;
    dl.classList.remove("stacked");   // .stack은 차트 막대 이름이라 쓰지 않는다
    const wrapped = [...dl.querySelectorAll(".mn-sum-row")].some((row) => {
      const dt = row.querySelector("dt");
      const dd = row.querySelector("dd");
      return dt && dd && dd.offsetTop > dt.offsetTop + 2;
    });
    dl.classList.toggle("stacked", wrapped);
  };
  const schedule = () => { if (!frame) frame = window.requestAnimationFrame(run); };
  if (typeof window.ResizeObserver === "function") { ro = new ResizeObserver(schedule); ro.observe(dl); }
  else window.addEventListener("resize", schedule);
  schedule();
  return dl;
}

/** 결과의 필수 문장 한 줄(은행 앱 버튼 바로 아래). */
function mustLine() {
  return h("div", { class: "mn-must-line" }, icon("shield"), h("p", { text: MUST }));
}

/** 라디오 묶음(공용 .segmented). labelId는 묶음 이름 요소의 id. */
function segmented(name, options, value, labelId, onChange) {
  const inputs = [];
  const el = h("div", { class: `segmented seg-${name}`, role: "radiogroup", "aria-labelledby": labelId },
    options.map((o) => {
      const input = h("input", { type: "radio", name, value: o.value, checked: o.value === value, "aria-label": o.label,
        onchange: () => { if (typeof onChange === "function") onChange(o.value); } });
      inputs.push(input);
      return h("label", null, input, h("span", null, o.icon ? icon(o.icon) : null, h("span", { text: o.label })));
    }));
  return {
    el,
    value: () => (inputs.find((i) => i.checked) || {}).value || "",
    set: (v) => { for (const i of inputs) i.checked = i.value === v; },
  };
}

function candidatesOf(r) { return (r && r.ask_helper_preview && r.ask_helper_preview.candidates) || []; }

/**
 * 물어볼래요 결과 줄(서버 practice_result)에서 제목을 되풀이하는 첫 줄을 줄인다(⑥):
 * ["김*호에게 30만 원을 보내기 전에 조력자에게 물어봐요.", "아직 보내지 않았어요."] → ["김*호에게 30만 원을 아직 보내지 않았어요."]
 * 모양이 다르면 그대로 둔다.
 */
function askLines(lines, title) {
  const t = String(title || "").replace(/[.\s]+$/, "");
  const m = /^(.+)을 \S+ 전에 (.+?)\.?$/.exec(lines[0] || "");
  const n = /^아직 (.+?)\.?$/.exec(lines[1] || "");
  if (!m || !n || !t || m[2] !== t) return lines;
  return [`${m[1]}을 아직 ${n[1]}.`, ...lines.slice(2)];
}

/**
 * 조력자 설정대로 적어 둔 기록 안내(⑥): 서버 문장(이영희에게 알릴 수 있게 적어 두었어요.)과 장소 문장(… 적어 두기만 했어요.)이
 * 같은 말을 되풀이하지 않게 한 문장으로 합치고, 직접 보내는 길을 붙인다. 돌려주는 값: 문장 목록(한 문단으로 그린다).
 */
function recordedNote(note, recorded) {
  if (!recorded) return note ? [note] : [];
  const where = `${deviceWord()}에 적어 두기만 했어요.`;
  const merged = /알릴 수 있게 적어 두었어요\.$/.test(note) ? note.replace(/적어 두었어요\.$/, where) : "";
  return [...(merged ? [merged] : [note, where].filter(Boolean)), "문자나 메일은 알림 보내기에서 직접 보내요."];
}

function namesText(names) { return names.length <= 2 ? names.join(", ") : `${names[0]} 외 ${names.length - 1}명`; }

/**
 * 카드 안 조력자 안내: 조력자에게 물어볼래요를 누르면 누구에게 묻게 되는지. 버튼 이름 그대로 이어 쓴다
 * (조력자에게 물어보면 이영희에게 물어봐요는 같은 말을 되풀이하는 것처럼 읽혔다, 나중에 보기를 누르면과 같은 꼴).
 */
function askPreviewText(cands) {
  const selectable = cands.filter((c) => !c.conflict);
  const picked = selectable.filter((c) => c.default || c.auto).map((c) => c.name);
  const autoNames = selectable.filter((c) => c.auto).map((c) => c.name);   // 자동 알림 대상은 뺄 수 없음
  const others = selectable.filter((c) => !c.auto);
  if (!cands.length) return "물어볼 수 있는 조력자가 없어요. 조력자 화면에서 정할 수 있어요.";
  if (picked.length) {
    let more = "";
    if (others.length && !autoNames.length) more = " 다음 화면에서 바꿀 수 있어요.";
    else if (others.some((c) => c.default)) more = ` 다음 화면에서 ${namesText(autoNames)} 말고는 바꿀 수 있어요.`;
    else if (others.length) more = " 다음 화면에서 다른 사람을 더할 수 있어요.";
    return `조력자에게 물어볼래요를 누르면 ${namesText(picked)}에게 물어봐요.${more}`;
  }
  if (selectable.length) return "조력자에게 물어볼래요를 누르면 물어볼 사람을 다음 화면에서 골라요.";
  return "지금은 물어볼 수 있는 조력자가 없어요. 조력자가 돈을 받는 사람이에요.";
}

function askNobodyLines(cands) {
  if (!cands.length) return ["물어볼 수 있는 조력자가 없어요.", "조력자 화면에서 조력자를 정할 수 있어요.", "상담하는 곳에는 알릴 수 있어요."];
  return [`${namesText(cands.map((c) => c.name))}: 돈을 받는 사람이에요.`, "그래서 이번에는 물어볼 수 없어요.", "상담하는 곳에는 알릴 수 있어요."];
}
