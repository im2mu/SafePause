/* 돈 보내기(보내기 탭의 첫 탭, #/send): 받는 사람·금액을 적고 → AI 확인 카드 → 본인이 정하면 내 은행 앱을 연다.
 * - SafePause는 돈을 옮기지 않는다. 보내기는 본인이 고른 은행 앱에서 한다(은행 이름·로고는 앱에 넣지 않음, bankapp.js).
 * - 확인: POST /api/safepause/check → 카드가 있으면 안전 정지 카드, 없으면(걱정 없음) 바로 결과.
 *   거래 살펴보기 동의가 꺼져 있으면 확인하지 않은 결과를 보인다(보내는 것을 막지 않음).
 * - 카드 규칙(v0.2와 같음, tests/test_static_ui.py가 확인):
 *   등급 배지 → 그림 → 제목 → 줄 → 질문 → 조력자 안내 → 오류·닫기 → 소리로 듣기 → 선택지 3개(서버 순서·문구 그대로).
 *   닫을 수 없다(dismissible false). 처음 초점은 제목(#card-title). Esc·뒤로 가기는 닫지 않고 안 보낼래요로 초점만 옮긴다.
 *   대화상자 이름은 등급 + 제목(aria-labelledby card-level card-title). 세 선택지는 같은 모양이다(한쪽으로 이끌지 않음).
 *   칸이 넉넉하면 본문·선택지를 나누고(선택지가 늘 보임), 좁으면 카드 전체를 한 번에 스크롤한다(본문이 0px로 접히지 않게, fitLayout).
 * - 결정: POST /api/safepause/decide → 결과 시트.
 *   그래도 보낼래요 → 내 은행 앱에서 보내 주세요 + [내 은행 앱 열기]·[다른 은행 앱 고르기]
 *   안 보낼래요 → 보내지 않았어요
 *   조력자에게 물어볼래요 → 물어볼 사람 고르기 → 결과에 [알림 보내기로 문자·메일 보내기](#/send?mode=notify&txn=확인한 거래)
 * - 금액은 80만·1억 2천만처럼 적어도 바르게 읽고(parseKoreanAmount), 정확한 원을 같이 보인다. 0·한도는 그 자리에서 알린다.
 */
import { h, icon, picto, fill, setText, openSheet, busy, announce, toast, comingSoonSheet } from "../ui.js";
import { nf, formatWon, moneyText, parseKoreanAmount, sentence } from "../format.js";
import { LEVEL, DECISION_ICON, EXAMPLES, PAY_CHANNELS, COUNSELING_TITLE } from "../labels.js";
import { levelBadge, speakButton, menuRow } from "../components.js";
import { STALE, isConsentError } from "../api.js";
import * as speech from "../speech.js";
import { bankAppActions, getBankApp, pickBankApp, bankAppUnavailable } from "./bankapp.js";

const MAX_AMOUNT = 10000000000;   // api PendingIn.amount 한도(100억 원)
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
// 결과 제목(거래 방법에 맞춰). 서버 decide의 message와 같은 글이다(easy_card.ChannelWords self_do·not_done).
// 결과에서는 서버 글을 먼저 쓰고, 서버 응답이 없는 경우(동의 꺼짐)에만 이 표를 쓴다. 조력자에게 물어볼래요는 서버 글을 쓴다
const SEND_TITLE = { transfer: "내 은행 앱에서 보내 주세요.", card: "결제는 직접 해 주세요.", micropay: "결제는 직접 해 주세요." };
const STOP_TITLE = { transfer: "보내지 않았어요.", card: "결제하지 않았어요.", micropay: "결제하지 않았어요." };
const SOON_STEPS = [
  { title: "계좌 연결", sub: "마이데이터로 내 계좌를 연결해요." },
  { title: "받는 사람·금액 적기" },
  { title: "AI 확인 카드", sub: "걱정되는 점이 있으면 한 번 더 물어봐요." },
  { title: "이체 인증", sub: "은행이 정한 본인 인증과 한도를 거쳐요." },
  { title: "보내기 완료" },
];

// 확인한 거래(이 창에서만 기억): 알림 보내기가 저장된 거래에서 그 거래를 못 찾을 때(물어볼래요는 거래 이력에 적지 않음) 쓴다
const checked = new Map();
/** 돈 보내기에서 확인한 거래의 항목(_item 모양) 또는 null. notify.js가 쓴다. */
export function checkedItem(id) { return checked.get(String(id || "")) || null; }
function remember(r) {
  const p = r && r.pending;
  if (!p || !p.id) return;
  const a = r.assessment || {};
  checked.set(String(p.id), {
    txn: { ...p, direction: "out" }, level: a.level || "none",
    signals: (a.rule_hits || []).map((x) => x.code), reasons: a.reasons || [], practice: true, flagged: false,
    unsaved: !r.added_to_history,   // 거래 이력에 적지 않은 거래(서버의 거래 id 요청에는 넣지 않는다)
  });
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
      h("div", { class: "cta-bar" }, checkBtn));

    const bankRowSlot = h("div");
    fill(main,
      h("p", { class: "page-sub", text: "보내기 전에 받는 사람과 금액을 AI가 한 번 더 살펴봐요." }),
      h("div", { class: "notice blue mn-must" }, icon("shield"), h("div", null,
        h("p", { class: "strong", text: MUST }),
        h("p", { text: "확인이 끝나면 내가 고른 은행 앱을 열어 드려요." }))),
      form,
      h("h3", { class: "section-title", text: "보내는 방법" }),
      bankRowSlot,
      h("h3", { class: "section-title" }, h("span", { text: "예시로 해 보기" }), h("span", { class: "tag mn-example-tag", text: "심사·시연용" })),
      h("div", { class: "card flat mn-examples" },
        h("p", { class: "muted", text: "누르면 예시 내용으로 칸을 채워요. 확인은 직접 눌러요." }),
        h("div", { class: "chips", role: "group", "aria-label": "예시" }, EXAMPLES.map((ex) => h("button", { type: "button", class: "chip", onclick: () => fillExample(ex) },
          icon("edit"), h("span", { text: ex.label }))))),
      speech.available() ? null : h("p", { class: "muted mn-novoice", text: speech.NO_VOICE_NOTE }));

    paintBankRow();
    paintMore();
    amountInput.addEventListener("input", () => { amountInput.removeAttribute("aria-invalid"); updateEasy(); });
    toInput.addEventListener("input", () => { toInput.removeAttribute("aria-invalid"); toError.hidden = true; });
    form.addEventListener("submit", onCheck);

    let pending = null;      // 카드에서 고르기를 기다리는 거래(check 요청 + 정해진 시각·id)
    let lastCheck = null;
    let chosenTime = "";     // 자세히에서 고른 보낼 시각(지금이면 빈 글)

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
            lines: ["내 계좌를 연결하면 은행 앱을 열지 않고 여기서 바로 보낼 수 있어요.", "보내기 전 AI 확인은 그대로 해요."],
            steps: SOON_STEPS, action: "계좌 연결하기",
          }) })));
    }

    function paintMore() {
      const t = TIMES.find((x) => x.value === timeSeg.value()) || TIMES[0];
      const id = toIdInput.value.trim();
      moreSub.textContent = [`보낼 시각 ${t.label}`, id ? "계좌번호 적음" : ""].filter(Boolean).join(" · ");
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
      amountEasy.textContent = `= ${formatWon(n)} (${moneyText(n)})`;
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

    // 최근에 보낸 사람(거래 살펴보기 동의가 있을 때만)
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
          else await decide("send", null, null);   // 걱정 없음 → 바로 결과
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
      const body = h("div", { class: "sheet-body" });
      const errorSlot = h("div", { class: "pause-error" });
      const foot = h("div", { class: "sheet-foot", role: "group", "aria-label": "고르기" });

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
          h("ul", { class: "pause-lines", id: "card-lines" }, card.lines.map((line) => h("li", { text: line }))),
          h("p", { class: "pause-question", text: card.question }),
          notes.length ? h("div", { class: "helper-note" }, icon("users"), h("div", null, notes.map((t) => h("p", { text: t })))) : null,
          errorSlot,
          speakButton(speakText, { cls: "btn block pause-speak", label: "소리로 듣기" }));
        // 선택지는 서버가 준 순서·문구 그대로. 세 선택지를 같은 모양으로 둔다(한쪽으로 이끌지 않음)
        fill(foot, card.choices.map((c) => h("button", {
          type: "button", class: "btn big block choice-btn", "data-decision": c.decision,
          onclick: () => (c.decision === "ask_helper" ? showAsk() : choose(c.decision)),
        }, h("span", { class: "ci" }, icon(DECISION_ICON[c.decision] || "check")), h("span", { text: c.label }))));
        fitLayout();
      }

      // 칸이 넉넉할 때만 본문·선택지를 나눈다(선택지가 늘 아래에 보이게). 나눈 뒤 본문 칸이 40%(최소 240px)보다 작아지면
      // 가로 화면·큰 글씨로 보고 카드 전체를 한 번에 스크롤한다(본문이 0px로 접히지 않게, 2차 검증 C1)
      function fitLayout() {
        const el = sheetApi && sheetApi.el;
        if (!el) return;
        el.classList.add("split");
        const room = el.clientHeight;
        const fits = room >= 420 && room - foot.scrollHeight >= Math.max(room * 0.4, 240);
        el.classList.toggle("split", fits);
      }
      const onResize = () => fitLayout();
      window.addEventListener("resize", onResize);

      // 오류·닫기는 소리로 듣기·선택지 앞(카드 순서 규칙). 닫으면 확인 버튼으로 돌아가 다시 할 수 있다
      function showError(err) {
        const msg = sentence(err.message || String(err));
        const box = h("div", { class: "notice red", role: "alert" }, icon("warning"), h("div", null,
          h("p", { text: `${msg} 닫기를 누르고 다시 해 볼 수 있어요.` }),
          h("button", { type: "button", class: "btn sm notice-action", onclick: () => { sheetApi.close(); checkBtn.focus(); } }, icon("close"), h("span", { text: "닫기" }))));
        fill(errorSlot, box);
        box.querySelector("button").focus();
      }

      async function choose(decision, helperIds) {
        const buttons = [...foot.querySelectorAll("button"), ...body.querySelectorAll("button")];
        buttons.forEach((b) => { b.disabled = true; });
        try {
          await decide(decision, helperIds, sheetApi);
        } catch (err) {
          if (err === STALE) return;
          if (isConsentError(err)) { const p = pending; sheetApi.close(); if (p) showUnchecked(p); return; }
          showError(err);
        } finally {
          buttons.forEach((b) => { if (b.isConnected) b.disabled = false; });
        }
      }

      // 조력자에게 물어볼래요 2단계: 물어볼 사람을 본인이 고른다(S37)
      function showAsk() {
        const cands = candidatesOf(r);
        const back = h("button", { type: "button", class: "btn big block", onclick: () => { showMain(); foot.querySelector('[data-decision="ask_helper"]')?.focus(); } }, icon("back"), h("span", { text: "돌아가기" }));
        if (!cands.some((c) => !c.conflict)) {
          const lines = askNobodyLines(cands);
          const orgs = (r.ask_helper_preview && r.ask_helper_preview.counseling_orgs) || [];
          fill(body,
            h("h2", { class: "sheet-title focus-target", id: "card-ask-title", tabindex: "-1", text: "물어볼 조력자가 없어요" }),
            lines.map((t) => h("p", { class: "sheet-sub", text: t })),
            orgs.length ? h("div", { class: "notice blue" }, icon("building"), h("div", null, h("p", { text: COUNSELING_TITLE }), h("ul", null, orgs.map((o) => h("li", { text: o }))))) : null,
            speakButton(() => ["물어볼 조력자가 없어요.", ...lines, ...(orgs.length ? [COUNSELING_TITLE, ...orgs] : [])].map(sentence).join(" ")));
          fill(foot,
            h("button", { type: "button", class: "btn primary big block", onclick: () => choose("ask_helper", []) }, icon("building"), h("span", { text: "상담하는 곳에 알릴래요" })),
            back);
          fitLayout();
          body.querySelector("#card-ask-title").focus();
          return;
        }
        const auto = cands.filter((c) => c.auto && !c.conflict);
        const why = card.level === "high" ? "꼭 확인할 일이라" : "확인할 일이라";
        const label = (c) => {
          if (c.conflict) return `${c.name} (돈을 받는 사람이라 이번에는 물어볼 수 없어요)`;
          const who = c.relation ? `${c.name} (${c.relation})` : c.name;
          if (c.auto) return `${who} · ${why} 조력자 설정대로 알려요`;
          return c.active === false ? `${who} · 자동으로 알리기는 꺼 두었어요` : who;
        };
        const boxes = cands.map((c) => h("input", { type: "checkbox", value: c.id, checked: !c.conflict && (c.default || c.auto), disabled: c.conflict || c.auto }));
        const err = h("p", { class: "error-text", role: "alert", hidden: true });
        const hints = ["체크한 사람에게 물어볼게요.", "다음 화면에서 문자나 메일을 보낼 수 있어요."];
        if (auto.length) hints.push(`${namesText(auto.map((c) => c.name))}에게는 조력자 설정대로 알려요. 그래서 체크를 풀 수 없어요.`);
        fill(body,
          h("h2", { class: "sheet-title focus-target", id: "card-ask-title", tabindex: "-1", text: "누구에게 물어볼까요?" }),
          h("p", { class: "sheet-sub", text: hints.join(" ") }),
          h("div", { class: "list mn-ask-list" }, cands.map((c, i) => h("label", { class: `check-row row${c.conflict ? " off" : ""}` }, boxes[i],
            h("span", { class: "row-icon" }, icon("users")), h("span", { class: "grow", text: label(c) })))),
          err,
          speakButton(() => ["누구에게 물어볼까요?", ...hints, ...cands.map((c) => label(c))].map(sentence).join(" ")));
        fill(foot,
          h("button", {
            type: "button", class: "btn primary big block",
            onclick: () => {
              // 체크를 풀 수 없는 자동 알림 대상도 함께 보낸다(그 사람도 물어보는 알림을 받음)
              const ids = boxes.filter((b) => b.checked).map((b) => b.value);
              if (!ids.length) { err.textContent = "물어볼 사람을 한 명 이상 골라 주세요."; err.hidden = false; return; }
              choose("ask_helper", ids);
            },
          }, icon("helper"), h("span", { text: "체크한 사람에게 물어볼래요" })),
          back);
        fitLayout();
        body.querySelector("#card-ask-title").focus();
      }

      sheetApi = openSheet(() => [body, foot], {
        className: `pause split level-${card.level}`, dismissible: false,
        label: `${lv.text}: ${card.title}`,
        initialFocus: "#card-title",
        onEscape: () => {
          const askTitle = body.querySelector("#card-ask-title");
          if (askTitle) { showMain(); body.querySelector("#card-title").focus(); return; }
          foot.querySelector('[data-decision="cancel"]')?.focus();
        },
        onClose: () => { speech.stop(); window.removeEventListener("resize", onResize); },
      });
      showMain();
      sheetApi.el.setAttribute("aria-labelledby", "card-level card-title");
      window.requestAnimationFrame(() => body.querySelector("#card-title")?.focus());
    }

    async function decide(decision, helperIds, sheetApi) {
      const payload = { pending, decision };
      if (decision === "ask_helper" && Array.isArray(helperIds)) payload.helper_ids = helperIds;
      const r = await ctx.req("POST", "/api/safepause/decide", payload);
      if (pending && r.pending) pending.id = r.pending.id;   // 서버가 새 id를 줬으면 그 id로 다시 시도
      remember(r);
      if (sheetApi) sheetApi.close();
      showResult(r, decision, helperIds);
      return r;
    }

    /** 보낼 것 요약(받는 사람·금액·방법·시각·계좌번호): 은행 앱에 옮겨 적기 쉽게. */
    function summary(p, time) {
      const ch = PAY_CHANNELS.find((c) => c.value === p.channel) || PAY_CHANNELS[0];
      const t = TIMES.find((x) => x.value === time);
      const rows = [
        ["받는 사람", p.to || p.counterparty || ""],
        ["금액", moneyText(p.amount)],
        ["방법", ch.label],
        time && t ? ["보낼 시각", t.label] : null,
        p.to_id ? ["계좌번호", p.to_id] : null,
      ].filter(Boolean);
      return h("dl", { class: "mn-summary" }, rows.map(([k, v]) => h("div", { class: "mn-sum-row" }, h("dt", { text: k }), h("dd", { text: v }))));
    }

    function showResult(r, decision, helperIds) {
      const p = { ...pending, ...(r.pending || {}), to: (pending && pending.to) || (r.pending && r.pending.counterparty) || "" };
      const plan = r.notify_plan || {};
      const channel = p.channel || "transfer";
      const kind = decision === "cancel" ? "stop" : decision === "ask_helper" ? "ask" : "send";
      const title = decision === "send" ? sentence(r.message || SEND_TITLE[channel] || SEND_TITLE.transfer)
        : decision === "cancel" ? sentence(r.message || STOP_TITLE[channel] || STOP_TITLE.transfer)
          : sentence(clean([r.result_title])[0] || "조력자에게 물어봐요");
      const lines = decision === "ask_helper" ? clean(r.result_lines) : [];
      // 날짜 안내는 거래 이력에 적었을 때만(보낼래요). 물어볼래요·안 보낼래요는 이력에 적지 않는다
      const tsNote = r.added_to_history ? clean([r.ts_note || (lastCheck && lastCheck.ts_note) || ""])[0] || "" : "";
      const showCounseling = Boolean(plan.suggest_counseling && (plan.counseling_orgs || []).length);
      if (decision !== "send" && plan.note_to_person && !(showCounseling && plan.note_to_person === COUNSELING_TITLE)) lines.push(...clean([plan.note_to_person]));
      // 조력자 알림은 이 기기에 기록만 한다(문자·메일은 알림 보내기에서 직접): 보낼래요 결과에서는 그렇게 풀어 쓴다
      const recorded = r.notices_recorded > 0
        ? (decision === "send" ? "조력자 설정대로 알림 기록을 남겼어요. 문자나 메일은 알림 보내기에서 보낼 수 있어요." : clean([r.delivery_note])[0] || "")
        : "";
      const noWorry = decision === "send" && !(lastCheck && lastCheck.card);   // 카드 없이 바로 온 결과(걱정 없음)
      const spoken = [title, ...(noWorry ? ["걱정되는 점이 없어요."] : []), ...lines];
      if (decision === "send") spoken.push(MUST);
      if (showCounseling) spoken.push(COUNSELING_TITLE, `${plan.counseling_orgs.join(", ")}.`);
      if (tsNote) spoken.push(tsNote);
      const txnId = r.pending && r.pending.id;
      const added = Boolean(r.added_to_history);

      openSheet((close) => {
        const done = () => { close(); resetForm(added); };
        const toNotify = () => {
          const q = new URLSearchParams({ mode: "notify" });
          if (txnId) q.append("txn", txnId);
          for (const id of helperIds || []) q.append("helper", id);
          if (decision === "ask_helper" && !(helperIds || []).length) q.set("to", "counselors");   // 물어볼 조력자가 없었음
          close();
          resetForm(false);
          go(`send?${q.toString()}`);
        };
        return [
          h("div", { class: `result-hero ${kind}` },
            h("div", { class: "big-icon" }, icon(kind === "stop" ? "stop" : kind === "ask" ? "helper" : decision === "send" && channel === "transfer" ? "bank" : "check")),
            h("h2", { class: "focus-target", tabindex: "-1", text: title }),
            noWorry ? h("p", { class: "result-ok" }, icon("check-line"), h("span", { text: "걱정되는 점이 없어요." })) : null),
          lines.length ? h("div", { class: "result-lines" }, lines.map((line) => h("p", { text: line }))) : null,
          decision === "send" ? summary(p, chosenTime) : null,
          decision === "send" ? bankAppActions() : null,
          decision === "send" ? mustLine() : null,
          decision === "ask_helper" ? h("button", { type: "button", class: "btn primary big block result-main", onclick: toNotify }, icon("chat"), h("span", { text: "알림 보내기로 문자·메일 보내기" })) : null,
          recorded || showCounseling || tsNote ? h("div", { class: "result-notes" },
            recorded ? h("p", { class: "muted", text: recorded }) : null,
            recorded && decision === "send" ? h("button", { type: "button", class: "btn sm weak", onclick: toNotify }, icon("chat"), h("span", { text: "알림 보내기" })) : null,
            showCounseling ? h("div", { class: "notice blue" }, icon("building"), h("div", null, h("p", { text: COUNSELING_TITLE }), h("ul", null, plan.counseling_orgs.map((o) => h("li", { text: o }))))) : null,
            tsNote ? h("p", { class: "muted", text: tsNote }) : null) : null,
          h("div", { class: "sheet-actions" },
            speakButton(() => spoken.map(sentence).join(" ")),
            h("button", { type: "button", class: "btn big block", text: decision === "send" ? "닫기" : "확인", onclick: done })),
        ];
      }, { label: title, className: "mn-result" });
      announce(title);
    }

    // 거래 살펴보기 동의가 꺼져 있으면 확인하지 않는다. 그래도 보내는 길은 그대로 열어 둔다
    function showUnchecked(req) {
      const title = SEND_TITLE[req.channel] || SEND_TITLE.transfer;
      const lines = ["거래 살펴보기가 꺼져 있어서 SafePause는 확인하지 않았어요."];
      openSheet((close) => [
        h("div", { class: "result-hero" }, h("div", { class: "big-icon" }, icon("bank")),
          h("h2", { class: "focus-target", tabindex: "-1", text: title })),
        h("div", { class: "result-lines" }, lines.map((t) => h("p", { text: t }))),
        summary(req, req.time || ""),
        bankAppActions(),
        mustLine(),
        h("div", { class: "sheet-actions" },
          speakButton(() => [title, ...lines, MUST].map(sentence).join(" ")),
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

/** 결과의 필수 문장 한 줄(은행 앱 버튼 바로 아래). */
function mustLine() {
  return h("div", { class: "mn-must-line" }, icon("shield"), h("p", { text: MUST }));
}

/** 라디오 묶음(공용 .segmented). labelId는 묶음 이름 요소의 id. */
function segmented(name, options, value, labelId, onChange) {
  const inputs = [];
  const el = h("div", { class: "segmented", role: "radiogroup", "aria-labelledby": labelId },
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

function namesText(names) { return names.length <= 2 ? names.join(", ") : `${names[0]} 외 ${names.length - 1}명`; }

/** 카드 안 조력자 안내: 조력자에게 물어보면 누구에게 묻게 되는지. */
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
    return `조력자에게 물어보면 ${namesText(picked)}에게 물어봐요.${more}`;
  }
  if (selectable.length) return "조력자에게 물어보면, 물어볼 사람을 다음 화면에서 골라요.";
  return "지금은 물어볼 수 있는 조력자가 없어요. 조력자가 돈을 받는 사람이에요.";
}

function askNobodyLines(cands) {
  if (!cands.length) return ["물어볼 수 있는 조력자가 없어요.", "조력자 화면에서 조력자를 정할 수 있어요.", "상담하는 곳에는 알릴 수 있어요."];
  return [`${namesText(cands.map((c) => c.name))}: 돈을 받는 사람이에요.`, "그래서 이번에는 물어볼 수 없어요.", "상담하는 곳에는 알릴 수 있어요."];
}
