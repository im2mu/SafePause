/* 보내기 연습 → 안전 정지 카드 → (조력자에게 물어보기) → 결과.
 *
 * 지키는 규칙(v0.1 계약·리뷰):
 * - 어떤 경우에도 막지 않는다. 카드가 없으면(괜찮아요) 바로 '보냈어요'. 동의가 꺼져 있으면 확인하지 않은 결과를 보여 준다.
 * - 카드 구성 순서: 등급 배지 → 그림 → 제목 → 줄 → 질문 → 조력자 안내 → 오류·닫기 → 소리로 듣기 → 선택지 3개(서버 순서·문구) → 연습 안내.
 * - 카드가 열리면 초점은 제목(선택지에 바로 두지 않음). Esc·뒤로 가기는 닫지 않고 '안 보낼래요'로 초점만 옮긴다.
 * - 대화상자 이름에 등급을 넣는다(리뷰 M4). 선택지는 카드 아래에 붙어 늘 보인다(리뷰 M7).
 * - 금액은 '80만 원'처럼 적어도 바르게 읽는다(리뷰 H2).
 */
import { h, icon, picto, fill, openSheet, busy, announce, toast } from "../ui.js";
import { nf, formatWon, formatWhen, parseKoreanAmount, sentence } from "../format.js";
import { LEVEL, DECISION_ICON, DONE_KO, EXAMPLES, COUNSELING_TITLE, PRACTICE_NOTE } from "../labels.js";
import { levelBadge, speakButton, practicePill } from "../components.js";
import { STALE, isConsentError } from "../api.js";
import * as speech from "../speech.js";

const MAX_AMOUNT = 10000000000;
const CHANNELS = [
  { value: "transfer", label: "계좌로 보내기", icon: "person" },
  { value: "card", label: "가게에서 결제", icon: "store" },
  { value: "micropay", label: "휴대폰 결제", icon: "phone" },
];
const TIMES = [
  { value: "", label: "지금 시각" },
  { value: "15:00", label: "오후 3시" },
  { value: "23:00", label: "밤 11시", icon: "moon" },
  { value: "02:00", label: "새벽 2시", icon: "moon" },
];
const QUICK_ADD = [10000, 50000, 100000, 500000];

export default {
  title: "보내기 연습",
  tab: "send",
  async render(ctx) {
    const { main, go } = ctx;
    const noCheck = { spellcheck: "false", autocapitalize: "off", autocorrect: "off", autocomplete: "off" };
    const toInput = h("input", { class: "input", id: "pay-to", type: "text", maxlength: "40", list: "payee-list", ...noCheck, "aria-describedby": "pay-to-hint" });
    const payeeList = h("datalist", { id: "payee-list" });
    const payeeChips = h("div", { class: "chips", "aria-label": "최근에 보낸 사람" });
    const amountInput = h("input", { class: "input big", id: "pay-amount", type: "text", inputmode: "numeric", maxlength: "20", ...noCheck, "aria-describedby": "pay-amount-easy" });
    const amountEasy = h("p", { class: "amount-easy", id: "pay-amount-easy", "aria-live": "polite" });
    const toIdInput = h("input", { class: "input", id: "pay-to-id", type: "text", maxlength: "60", ...noCheck });
    const errorText = h("p", { class: "error-text", role: "alert", hidden: true });
    const payBtn = h("button", { type: "submit", class: "btn primary big block" }, icon("send"), h("span", { text: "보내기" }));
    const channelSeg = segmented("channel", CHANNELS, "transfer", "어떻게 보내요?");
    const timeSeg = segmented("time", TIMES, "", "언제 보내요? (연습)");

    const form = h("form", { novalidate: true, autocomplete: "off" },
      h("div", { class: "field" }, h("label", { for: "pay-to", text: "받는 사람 (또는 가게)" }), toInput, payeeList,
        h("p", { class: "hint", id: "pay-to-hint", text: "예: 엄마, 김*호, 새로 연 전자상가" }), payeeChips),
      h("div", { class: "field" }, h("label", { for: "pay-amount", text: "금액" }), amountInput, amountEasy,
        h("div", { class: "chips", "aria-label": "금액 더하기" }, QUICK_ADD.map((n) => h("button", {
          type: "button", class: "chip", onclick: () => { const cur = parseKoreanAmount(amountInput.value); setAmount((Number.isFinite(cur) ? cur : 0) + n); },
        }, icon("plus"), h("span", { text: formatWon(n) }))),
          h("button", { type: "button", class: "chip", onclick: () => { amountInput.value = ""; updateEasy(); amountInput.focus(); } }, h("span", { text: "지우기" })))),
      h("div", { class: "field" }, h("span", { class: "field-label", id: "channel-label", text: "어떻게 보내요?" }), channelSeg.el),
      h("div", { class: "field" }, h("span", { class: "field-label", id: "time-label", text: "언제 보내요? (연습)" }), timeSeg.el),
      h("details", { class: "field" }, h("summary", { class: "field-label", text: "계좌번호 적기 (없으면 그냥 두어요)" }),
        h("label", { for: "pay-to-id", class: "sr-only", text: "계좌번호" }), toIdInput),
      errorText,
      h("div", { class: "cta-bar" }, payBtn));

    fill(main,
      h("h2", { class: "page-title", tabindex: "-1", text: "돈 보내기 연습" }),
      h("p", { class: "page-sub" }, practicePill()),
      h("div", { class: "notice blue" }, icon("shield"), h("div", null,
        h("p", null, h("strong", { text: "SafePause는 막지 않아요." })),
        h("p", { text: "걱정되면 한 번 더 물어볼 뿐이에요. 결정은 내가 해요." }))),
      h("h3", { class: "section-title", style: "margin-top:.5rem", text: "예시로 해 보기" }),
      h("div", { class: "chips" }, EXAMPLES.map((ex) => h("button", { type: "button", class: "chip", onclick: () => fillExample(ex) }, h("span", { text: ex.label })))),
      h("div", { class: "card" }, form),
      speech.available() ? null : h("p", { class: "muted", style: "margin:.5rem .25rem", text: speech.NO_VOICE_NOTE }));

    amountInput.addEventListener("input", updateEasy);
    form.addEventListener("submit", onPay);

    let pending = null;      // 카드에서 고르기를 기다리는 거래(check 요청 + 정해진 시각·id)
    let lastCheck = null;

    function setAmount(n) { amountInput.value = nf.format(Math.min(n, MAX_AMOUNT)); updateEasy(); }
    function updateEasy() {
      const n = parseKoreanAmount(amountInput.value);
      amountEasy.textContent = amountInput.value.trim() ? (Number.isFinite(n) ? `= ${formatWon(n)}` : "숫자로 적어 주세요. 예: 800000 또는 80만") : "";
    }
    function fillExample(ex) {
      toInput.value = ex.to;
      setAmount(ex.amount);
      channelSeg.set(ex.channel);
      timeSeg.set(ex.time);
      toIdInput.value = "";
      errorText.hidden = true;
      payBtn.focus();
      announce("칸을 채웠어요. 보내기를 눌러 보세요.");
    }
    function formError(message, el) {
      errorText.textContent = message;
      errorText.hidden = false;
      if (el) { el.setAttribute("aria-invalid", "true"); el.focus(); }
    }

    // 최근에 보낸 사람(동의가 있을 때만)
    try {
      const p = await ctx.req("GET", "/api/payees");
      fill(payeeList, p.items.map((n) => h("option", { value: n })));
      fill(payeeChips, p.items.slice(0, 6).map((n) => h("button", { type: "button", class: "chip", onclick: () => { toInput.value = n; amountInput.focus(); } }, icon("person"), h("span", { text: n }))));
    } catch (e) { if (e === STALE) return; /* 동의가 없으면 목록 없이 쓴다 */ }

    async function onPay(e) {
      e.preventDefault();
      errorText.hidden = true;
      toInput.removeAttribute("aria-invalid");
      amountInput.removeAttribute("aria-invalid");
      const to = toInput.value.trim();
      const amount = parseKoreanAmount(amountInput.value);
      if (!to) { formError("받는 사람을 적어 주세요.", toInput); return; }
      if (!Number.isFinite(amount) || amount <= 0) { formError("금액을 숫자로 적어 주세요. 예: 800000 또는 80만", amountInput); return; }
      if (amount > MAX_AMOUNT) { formError("금액이 너무 커요.", amountInput); return; }
      const req = { to, amount, channel: channelSeg.value() || "transfer", to_id: toIdInput.value.trim() };
      const time = timeSeg.value();
      if (time) req.time = time;
      await busy(payBtn, async () => {
        try {
          const r = await ctx.req("POST", "/api/safepause/check", req);
          pending = { id: r.pending.id, to: req.to, amount: req.amount, channel: req.channel, to_id: req.to_id, ts: r.pending.ts };
          lastCheck = r;
          if (r.card) openCard(r);
          else await decide("send", null, null);   // 걱정 없음 → 바로 '보냈어요'
        } catch (err) {
          if (err === STALE) return;
          if (isConsentError(err)) showUnchecked(req);
          else formError(err.message);
        }
      });
    }

    // ---- 안전 정지 카드 -------------------------------------------------------------
    function openCard(r) {
      const card = r.card;
      const lv = LEVEL[card.level] || LEVEL.caution;
      let sheetApi = null;
      const body = h("div", { class: "sheet-body" });
      const foot = h("div", { class: "sheet-foot", role: "group", "aria-label": "고르기" });

      function helperNote() {
        const plan = r.notify_plan_preview;
        const notes = [];
        if (plan && plan.note_to_person && (plan.notices.length || plan.excluded_conflict.length)) notes.push(plan.note_to_person);
        notes.push(askPreviewText(candidatesOf(r)));
        return notes;
      }
      const notes = helperNote();
      const speakText = () => {
        const choices = card.choices.map((c) => c.label).join(", ");
        return `${lv.text}. ${card.speak_text} ${notes.join(" ")} 고를 수 있어요. ${choices}.`;
      };

      function showMain() {
        fill(body,
          h("div", { class: "pause-head" },
            h("span", { id: "card-level" }, levelBadge(card.level)),
            h("div", { class: "pictos", "aria-hidden": "true" }, (card.pictograms || []).map((p) => picto(p))),
            h("h2", { class: "pause-title focus-target", id: "card-title", tabindex: "-1", text: card.title })),
          h("ul", { class: "pause-lines", id: "card-lines" }, card.lines.map((line) => h("li", { text: line }))),
          h("p", { class: "pause-question", text: card.question }),
          h("div", { class: "helper-note" }, icon("helper"), h("div", null, notes.map((t) => h("p", { text: t })))),
          speakButton(speakText, { cls: "btn block", label: "소리로 듣기" }),
          h("p", { class: "muted center", style: "margin-top:.75rem", text: PRACTICE_NOTE }));
        fill(foot, card.choices.map((c) => h("button", {
          type: "button", class: "btn big block choice-btn", "data-decision": c.decision,   // 세 선택지를 같은 모양으로(한쪽으로 이끌지 않음, S38)
          onclick: () => (c.decision === "ask_helper" ? showAsk() : choose(c.decision)),
        }, h("span", { class: "ci" }, icon(DECISION_ICON[c.decision] === "money" ? "send" : DECISION_ICON[c.decision] || "check")), h("span", { text: c.label }))));
      }

      function showError(err) {
        const msg = sentence(err.message || String(err));
        const box = h("div", { class: "notice red", role: "alert" }, icon("warning"), h("div", null,
          h("p", { text: `${msg} '닫기'를 누르고 다시 해 볼 수 있어요.` }),
          h("button", { type: "button", class: "btn sm", style: "margin-top:.5rem", onclick: () => { sheetApi.close(); payBtn.focus(); } }, h("span", { text: "닫기" }))));
        body.append(box);
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

      // '조력자에게 물어볼래요' 2단계: 물어볼 사람을 당사자가 고른다(S37)
      function showAsk() {
        const cands = candidatesOf(r);
        const back = h("button", { type: "button", class: "btn big block", onclick: () => { showMain(); foot.querySelector('[data-decision="ask_helper"]')?.focus(); } }, icon("back"), h("span", { text: "돌아가기" }));
        if (!cands.some((c) => !c.conflict)) {
          const lines = [...askNobodyLines(cands), "다른 것을 골라 주세요."];
          const orgs = (r.ask_helper_preview && r.ask_helper_preview.counseling_orgs) || [];
          fill(body,
            h("h2", { class: "sheet-title focus-target", id: "card-ask-title", tabindex: "-1", text: "물어볼 조력자가 없어요" }),
            lines.map((t) => h("p", { class: "sheet-sub", text: t })),
            orgs.length ? h("div", { class: "notice blue" }, icon("users"), h("div", null, h("p", { text: COUNSELING_TITLE }), h("ul", null, orgs.map((o) => h("li", { text: o }))))) : null,
            speakButton(() => ["물어볼 조력자가 없어요.", ...lines, ...(orgs.length ? [COUNSELING_TITLE, ...orgs] : [])].join(" ")));
          fill(foot, back);
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
        const hints = ["체크한 사람에게 물어봐요. 문자나 메일은 보내지 않아요."];
        if (auto.length) hints.push(`${namesText(auto.map((c) => c.name))}에게는 조력자 설정대로 알려요. 그래서 체크를 풀 수 없어요.`);
        fill(body,
          h("h2", { class: "sheet-title focus-target", id: "card-ask-title", tabindex: "-1", text: "누구에게 물어볼까요?" }),
          hints.map((t) => h("p", { class: "sheet-sub", text: t })),
          h("div", { class: "list" }, cands.map((c, i) => h("label", { class: "check-row row" }, boxes[i], h("span", { class: "row-icon" }, icon("users")), h("span", { class: "grow", text: label(c) })))),
          err,
          speakButton(() => ["누구에게 물어볼까요?", ...hints, ...cands.map((c) => `${label(c)}.`)].join(" ")));
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
        onClose: () => speech.stop(),
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
      if (sheetApi) sheetApi.close();
      showResult(r);
      return r;
    }

    function showResult(r) {
      const t = r.pending;
      const plan = r.notify_plan || {};
      const title = r.result_title || r.message;
      const lines = [...(r.result_lines || []), `연습 시각: ${formatWhen(t.ts)}`];
      const tsNote = r.ts_note || (lastCheck && lastCheck.ts_note) || "";
      if (tsNote) lines.push(tsNote);
      const showCounseling = Boolean(plan.suggest_counseling && (plan.counseling_orgs || []).length);
      if (plan.note_to_person && !(showCounseling && plan.note_to_person === COUNSELING_TITLE)) lines.push(plan.note_to_person);
      const spoken = [title, ...lines];
      const recorded = r.notices_recorded > 0 ? `${r.delivery_note} (기록 ${r.notices_recorded}건)` : "";
      if (recorded) spoken.push(recorded);
      if (showCounseling) spoken.push(COUNSELING_TITLE, `${plan.counseling_orgs.join(", ")}.`);
      spoken.push(r.practice_note);
      const kind = r.decision === "cancel" ? "stop" : r.decision === "ask_helper" ? "ask" : "";
      openSheet((close) => [
        h("div", { class: `result-hero ${kind}`.trim() },
          h("div", { class: "big-icon" }, icon(r.decision === "cancel" ? "stop" : r.decision === "ask_helper" ? "helper" : "check")),
          h("h2", { class: "focus-target", tabindex: "-1", text: title })),
        h("div", { class: "result-lines" }, lines.map((line) => h("p", { text: line }))),
        recorded ? h("p", { class: "muted", text: recorded }) : null,
        showCounseling ? h("div", { class: "notice blue" }, icon("users"), h("div", null, h("p", { text: COUNSELING_TITLE }), h("ul", null, plan.counseling_orgs.map((o) => h("li", { text: o }))))) : null,
        h("p", null, h("strong", { text: r.practice_note })),
        h("div", { class: "sheet-actions" },
          speakButton(() => spoken.map(sentence).join(" ")),
          h("button", { type: "button", class: "btn primary big block", text: "확인", onclick: () => { close(); resetForm(); } })),
      ], { label: title });
      announce(title);
    }

    function showUnchecked(req) {
      // 동의가 없으면 살펴보지 않는다. 그래도 막지 않는다.
      const done = DONE_KO[req.channel] || "보냈어요";
      const lines = [`${formatWon(req.amount)}을 ${done}.`, "거래 살펴보기가 꺼져 있어서 SafePause는 확인하지 않았어요."];
      openSheet((close) => [
        h("div", { class: "result-hero" }, h("div", { class: "big-icon" }, icon("check")),
          h("h2", { class: "focus-target", tabindex: "-1", text: `${done} (연습)` })),
        h("div", { class: "result-lines" }, lines.map((t) => h("p", { text: t }))),
        h("p", null, h("strong", { text: PRACTICE_NOTE })),
        h("div", { class: "sheet-actions" },
          speakButton(() => [`${done} (연습).`, ...lines, PRACTICE_NOTE].join(" ")),
          h("button", { type: "button", class: "btn weak big block", onclick: () => { close(); go("more/consent"); } }, icon("toggle"), h("span", { text: "동의 켜러 가기" })),
          h("button", { type: "button", class: "btn big block", text: "확인", onclick: () => { close(); resetForm(); } })),
      ], { label: `${done} (연습)` });
    }

    function resetForm() {
      form.reset();
      channelSeg.set("transfer");
      timeSeg.set("");
      amountEasy.textContent = "";
      pending = null;
      lastCheck = null;
      toast("연습 결과를 알림 화면에 적어 두었어요.");
    }
  },
};

function segmented(name, options, value, label) {
  const inputs = [];
  const el = h("div", { class: "segmented", role: "radiogroup", "aria-label": label },
    options.map((o) => {
      const input = h("input", { type: "radio", name, value: o.value, checked: o.value === value, "aria-label": o.label });
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

function askPreviewText(cands) {
  const selectable = cands.filter((c) => !c.conflict);
  const picked = selectable.filter((c) => c.default || c.auto).map((c) => c.name);
  const autoNames = selectable.filter((c) => c.auto).map((c) => c.name);   // 자동 알림 대상은 뺄 수 없음
  const others = selectable.filter((c) => !c.auto);
  if (!cands.length) return "물어볼 수 있는 조력자가 없어요. '조력자' 화면에서 정할 수 있어요.";
  if (picked.length) {
    let more = "";
    if (others.length && !autoNames.length) more = " 다음 화면에서 바꿀 수 있어요.";
    else if (others.some((c) => c.default)) more = ` 다음 화면에서 ${namesText(autoNames)} 말고는 바꿀 수 있어요.`;
    else if (others.length) more = " 다음 화면에서 다른 사람을 더할 수 있어요.";
    return `'조력자에게 물어볼래요'를 고르면 ${namesText(picked)}에게 물어봐요.${more}`;
  }
  if (selectable.length) return "'조력자에게 물어볼래요'를 고르면, 물어볼 사람을 다음 화면에서 골라요.";
  return "지금은 물어볼 수 있는 조력자가 없어요. 조력자가 돈을 받는 사람이에요.";
}

function askNobodyLines(cands) {
  if (!cands.length) return ["물어볼 수 있는 조력자가 없어요.", "'조력자' 화면에서 조력자를 정할 수 있어요."];
  return [`${namesText(cands.map((c) => c.name))}: 돈을 받는 사람이에요.`, "그래서 이번에는 물어볼 수 없어요."];
}
