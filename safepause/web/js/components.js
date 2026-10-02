/* 여러 화면이 같이 쓰는 부품: 등급·상태 배지, 거래 줄, 담기·내가 한 거예요 버튼, 메뉴 줄, 쉬운 말 카드,
 * 왜 걱정되나요(약속(규칙) + AI), 소리로 듣기, 오류 안내.
 * 아이콘은 모두 선 아이콘(ui.icon, 24 viewBox 굵기 2)이다. 큰 픽토그램(ui.picto)은 돈 보내기 확인 카드 본문에만 쓴다(D4). */
import { h, icon, toast, setText, soonBadge } from "./ui.js";
import { formatWon, formatTime, formatDate, formatWhen, parseTs, nf, sentence, moneyText, keepUnits } from "./format.js";
import { LEVEL, CHANNEL_KO, CHANNEL_ICON, SIGNAL_ICON, signalLabel, FLAG_TEXT, REVIEW_TEXT, NOTIFIED_TEXT, AI_TEXT } from "./labels.js";
import { isConsentError, ApiError, STALE } from "./api.js";
import * as speech from "./speech.js";

export { soonBadge };

export function levelBadge(level) {
  const lv = LEVEL[level] || LEVEL.none;
  return h("span", { class: `badge ${lv.cls}` }, icon(lv.icon), h("span", { text: lv.text }));
}

/** 담은 거래 배지(알림 목록에 담은 거래). 글은 FLAG_TEXT.badge(담음). */
export function flaggedBadge() {
  return h("span", { class: "badge info" }, icon("bookmark-fill"), h("span", { text: FLAG_TEXT.badge }));
}

/** 담은 거래면 담음 배지, 아니면 null. */
export function flagBadge(item) {
  return item && item.flagged ? flaggedBadge() : null;
}

/** 내가 한 거예요로 표시한 거래(item.reviewed)면 내가 확인함 배지, 아니면 null. */
export function reviewBadge(item) {
  if (!item || !item.reviewed) return null;
  return h("span", { class: "badge ok-line" }, icon("user-check"), h("span", { text: REVIEW_TEXT.badge }));
}

/** 직접 보낸 알림에 든 거래(item.notified_at)면 알렸어요(10월 3일) 배지, 아니면 null. */
export function notifiedBadge(item) {
  if (!item || !item.notified_at) return null;
  const d = parseTs(item.notified_at);
  const when = d ? `(${d.getMonth() + 1}월 ${d.getDate()}일)` : "";
  return h("span", { class: "badge grey" }, icon("send"), h("span", { text: `${NOTIFIED_TEXT}${when}` }));
}

/** 보내기 전 확인(돈 보내기 화면)으로 확인하고 내 거래 끝에 적은 거래의 배지. */
export const CHECKED_TEXT = "보내기 전 확인";
export function checkedBadge() {
  return h("span", { class: "tag" }, icon("shield"), h("span", { text: CHECKED_TEXT }));
}

/** 거래 금액 한 번만: 나간 돈 "-50,000원", 들어온 돈 "+50,000원". */
export function txnAmount(t) {
  return moneyText(t.amount, t.direction === "out" ? "-" : "+");
}

/** 거래 표시 이름(명사형 신호) 목록: [{code, icon, text}]. AI만 평소와 다르다고 본 거래는 "평소와 다른 거래". */
export function txnSignals(item) {
  const names = (item.signals || []).map((code) => ({ code, icon: SIGNAL_ICON[code] || "warning", text: signalLabel(item, code) }));
  if (!names.length && item.level && item.level !== "none" && (item.reasons || []).some((r) => String(r.code).startsWith("anomaly:"))) {
    names.push({ code: "anomaly", icon: "sparkle", text: "평소와 다른 거래" });
  }
  return names;
}

/**
 * 목록 줄의 작은 글(시각 · 방법 등). 조각마다 줄을 바꾸지 않고, 줄이 바뀌면 줄 앞의 가운뎃점은 보이지 않는다
 * ("저녁 8시 47분 ·" 다음 줄 "카드 결제"처럼 점이 끝에 매달리거나 "카드 / 결제"로 끊기지 않게).
 */
export function subParts(parts, cls = "row-sub") {
  // 조각 안 빈칸은 줄을 바꾸지 않는 빈칸으로(조각이 칸보다 길 때만 CSS가 안에서 줄을 바꾼다)
  return h("span", { class: `${cls} parts` }, parts.filter(Boolean).map((t) => h("span", { text: String(t).replace(/ /g, " ") })));
}

/** 날짜와 시각을 따로: ["2026년 6월 27일 (토)", "새벽 4시 41분"](subParts에서 날짜·시각 사이에서만 줄을 바꾸게). */
export function whenParts(ts) {
  const d = parseTs(ts);
  return d ? [formatDate(d), formatTime(d)] : [String(ts || "")];
}

/** 거래 줄·카드에 붙는 상태 표시(등급 + 명사형 신호 + 담음 + 내가 확인함 + 알렸어요 + 보내기 전 확인). */
function statusTags(item, signals) {
  const tags = [];
  if (item.level && item.level !== "none") tags.push(levelBadge(item.level));
  for (const s of signals) tags.push(h("span", { class: "tag" }, icon(s.icon), h("span", { text: s.text })));
  tags.push(flagBadge(item), reviewBadge(item), notifiedBadge(item));
  if (item.practice) tags.push(checkedBadge());
  return tags.filter(Boolean);
}

/** 거래 한 줄(토스 목록 모양): 이름과 금액 한 줄 → 시각·방법 → 표시. onOpen이 있으면 눌러서 거래 시트를 연다. 금액은 한 번만 쓴다. */
export function txnRow(item, onOpen) {
  const t = item.txn;
  const out = t.direction === "out";
  const d = parseTs(t.ts);
  const tone = item.level === "high" ? "red" : item.level === "caution" ? "orange" : out ? "" : "blue";
  const signals = txnSignals(item);
  const tags = statusTags(item, signals);
  const body = [
    h("span", { class: `row-icon ${tone}`.trim() }, icon(CHANNEL_ICON[t.channel] || "cash")),
    h("span", { class: "row-main" },
      // 이름과 금액은 한 줄(자리가 모자라면 금액이 다음 줄 오른쪽으로), 시각·방법은 그 아래 줄을 넓게 쓴다
      h("span", { class: "txn-top" },
        h("span", { class: "row-title", text: t.counterparty || "(이름 없음)" }),
        h("span", { class: `row-amount${out ? "" : " in"}`, text: txnAmount(t) })),
      subParts([d ? formatTime(d) : "", CHANNEL_KO[t.channel] || t.channel]),
      tags.length ? h("span", { class: "row-tags" }, tags) : null),
  ];
  const label = [t.counterparty || "이름 없음", d ? formatTime(d) : "", CHANNEL_KO[t.channel] || t.channel,
    `${out ? "나감" : "들어옴"} ${moneyText(t.amount)}`, item.level && item.level !== "none" && LEVEL[item.level] ? LEVEL[item.level].text : "",
    ...signals.map((s) => s.text), item.flagged ? FLAG_TEXT.badge : "", item.reviewed ? REVIEW_TEXT.badge : "",
    item.notified_at ? NOTIFIED_TEXT : "", item.practice ? CHECKED_TEXT : ""].filter(Boolean).join(", ");
  return onOpen
    ? h("button", { type: "button", class: "row txn-row", "aria-label": label, onclick: () => onOpen(item) }, body)
    : h("div", { class: "row txn-row" }, body);
}

export function dateHead(ts) {
  const d = parseTs(ts);
  return h("div", { class: "date-head", text: d ? formatDate(d) : "" });
}

/**
 * 누르면 서버에 바꾸고 글을 바꾸는 켜고 끄기 버튼(담기·내가 한 거예요가 같이 쓴다).
 * 하는 동안 disabled를 쓰지 않는다(초점이 body로 빠지지 않게, FE-04): aria-disabled·aria-busy로 두 번 누름만 막는다.
 */
function toggleButton(ctx, { on, cls, iconOn, iconOff, textOn, textOff, request, toastOn, toastOff, failText, onDone }) {
  let state = Boolean(on);
  const ic = h("span", { class: "btn-ic" });
  const text = h("span");
  const btn = h("button", { type: "button", class: cls, "aria-pressed": "false" }, ic, text);
  function paint() {
    btn.setAttribute("aria-pressed", state ? "true" : "false");
    ic.replaceChildren(icon(state ? iconOn : iconOff));
    text.textContent = state ? textOn : textOff;
  }
  btn.addEventListener("click", async () => {
    if (btn.getAttribute("aria-busy") === "true") return;
    btn.setAttribute("aria-busy", "true");
    btn.setAttribute("aria-disabled", "true");
    const next = !state;
    try {
      const r = await request(next);
      state = next;
      paint();
      toast(next ? toastOn : toastOff);
      if (typeof onDone === "function") onDone(next, r && r.count);
    } catch (e) {
      if (e !== STALE) toast(e && e.message ? e.message : failText, "error");
    } finally {
      btn.removeAttribute("aria-busy");
      btn.removeAttribute("aria-disabled");
    }
  });
  paint();
  return btn;
}

/**
 * 알림 목록에 담기 ↔ 담기 취소 버튼(POST /api/flags, /api/flags/remove). 글은 FLAG_TEXT.
 * item: {txn: {id}, flagged}. opts: {cls, onChange(flagged, count)}.
 * 담으면 토스트 "알림 탭에 담았어요.", 빼면 "담은 거래에서 뺐어요." `item.flagged`도 바꾼다.
 * 작은 버튼(알림 카드)은 cls만 바꾼다: flagButton(ctx, item, {cls: "btn sm"}).
 */
export function flagButton(ctx, item, { cls = "btn big block", onChange = null } = {}) {
  return toggleButton(ctx, {
    on: item.flagged, cls, iconOn: "bookmark-fill", iconOff: "bookmark", textOn: FLAG_TEXT.undo, textOff: FLAG_TEXT.button,
    toastOn: FLAG_TEXT.toast, toastOff: FLAG_TEXT.removed, failText: "담지 못했어요. 다시 해 주세요.",
    request: (next) => ctx.req("POST", next ? "/api/flags" : "/api/flags/remove", { txn_id: item.txn.id }),
    onDone: (next, count) => { item.flagged = next; if (typeof onChange === "function") onChange(next, count); },
  });
}

/**
 * 내가 한 거예요 ↔ 확인 취소 버튼(POST /api/reviews, /api/reviews/remove). 글은 REVIEW_TEXT.
 * 탐지 등급은 그대로이고, 걱정되는 거래 수에서만 뺀다(수정 계획 1-C). `item.reviewed`도 바꾼다.
 */
export function reviewButton(ctx, item, { cls = "btn big block", onChange = null } = {}) {
  return toggleButton(ctx, {
    on: item.reviewed, cls, iconOn: "user-check", iconOff: "check", textOn: REVIEW_TEXT.undo, textOff: REVIEW_TEXT.button,
    toastOn: REVIEW_TEXT.toast, toastOff: REVIEW_TEXT.removedToast, failText: "표시하지 못했어요. 다시 해 주세요.",
    request: (next) => ctx.req("POST", next ? "/api/reviews" : "/api/reviews/remove", { txn_id: item.txn.id }),
    onDone: (next, count) => { item.reviewed = next; if (typeof onChange === "function") onChange(next, count); },
  });
}

/**
 * 메뉴 한 줄(전체 탭·설정). {icon, tone, title, sub, href | onclick, soon, end}
 * soon이면 준비 중 배지를 제목 바로 아래 고정 줄(.menu-soon)에 붙인다(L15: 제목 길이에 따라 어떤 줄은 옆, 어떤 줄은
 * 다음 줄로 배지가 들쭉날쭉하지 않게. 오른쪽 끝에 두면 360폭에서 제목 칸이 6글자로 줄어 제목이 두 줄로 꺾인다).
 * 누르면 화면이 comingSoonSheet를 연다.
 */
export function menuRow({ icon: ic, tone = "", title, sub = "", href = null, onclick = null, soon = false, end = null }) {
  const inner = [
    h("span", { class: `row-icon ${tone}`.trim() }, icon(ic)),
    h("span", { class: "row-main" },
      h("span", { class: "row-title" }, h("span", { text: title })),
      soon ? h("span", { class: "menu-soon" }, soonBadge()) : null,
      sub ? h("span", { class: "row-sub", text: sub }) : null),
    end || h("span", { class: "row-chev" }, icon("chevron")),
  ];
  if (href) return h("a", { class: `row menu-row${soon ? " is-soon" : ""}`, href }, inner);
  return h("button", { type: "button", class: `row menu-row${soon ? " is-soon" : ""}`, onclick }, inner);
}

// ---- 소리로 듣기 -----------------------------------------------------------------
// 지금 읽고 있는 버튼. 그 버튼이 화면에서 떨어지거나(패널을 다시 그림·시트를 닫음·탭을 바꿈) 숨겨지면 읽기를 멈춘다(D1·FE-09).
let speaking = null;
const speakWatch = typeof MutationObserver === "function" ? new MutationObserver(() => {
  if (speaking && (!speaking.isConnected || speaking.closest("[hidden]"))) speech.stop();
}) : null;

function watchSpeaking(btn) {
  speaking = btn;
  if (speakWatch) speakWatch.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden"] });
}

function unwatchSpeaking(btn) {
  if (speaking !== btn) return;
  speaking = null;
  if (speakWatch) speakWatch.disconnect();
}

/**
 * 소리로 듣기 ↔ 멈추기 토글 버튼. 이 기기에 한국어 음성이 없다고 확정되면 null(버튼을 만들지 않음).
 * 누르면 읽고(aria-pressed=true, 글자 "멈추기"), 다시 누르면 멈춘다. 다른 버튼이 읽기 시작하거나
 * 다 읽으면 원래대로 돌아간다(한 번에 하나만 읽음).
 * - 버튼이 화면에서 떨어지거나 숨겨지면(같은 화면 안 탭 바꾸기·패널 다시 그리기·시트 닫기) 읽기를 멈춘다. 화면 쪽은 stop을 부르지 않아도 된다.
 * - 음성이 아직 준비 중이면 버튼을 만들어 두고 CSS(html[data-voice])가 숨긴다. 준비되면 저절로 보인다(D10).
 */
export function speakButton(getText, { label = "소리로 듣기", stopLabel = "멈추기", cls = "btn block" } = {}) {
  if (speech.voiceStatus() === "none") return null;
  const ic = h("span", { class: "btn-ic" });
  const text = h("span");
  const btn = h("button", { type: "button", class: `${cls} speak-btn`, "aria-pressed": "false" }, ic, text);
  function paint(on) {
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    ic.replaceChildren(icon(on ? "stop-circle" : "speaker"));
    text.textContent = on ? stopLabel : label;
  }
  btn.addEventListener("click", () => {
    if (btn.getAttribute("aria-pressed") === "true") { speech.stop(); return; }   // onEnd가 원래대로 돌린다
    const t = typeof getText === "function" ? getText() : getText;
    if (!speech.speak(t, { onEnd: () => { unwatchSpeaking(btn); paint(false); } })) { toast("지금은 소리로 읽을 수 없어요."); return; }
    paint(true);
    watchSpeaking(btn);
  });
  paint(false);
  return btn;
}

/**
 * 음성 없음 안내 문장. 음성이 없다고 확정됐을 때만 보이고(CSS html[data-voice="none"]), 준비 중·준비됨이면 숨는다.
 * 화면은 speech.available()로 미리 고르지 않고 이것을 그대로 넣는다.
 */
export function noVoiceNote(cls = "muted") {
  return h("p", { class: `${cls} voice-note`.trim(), text: speech.noVoiceNote() });
}

/**
 * 쉬운 말 카드(알림 탭·홈): 그림, 등급, 제목, 줄, 소리로 듣기.
 * - 머리 그림은 신호 선 아이콘(SIGNAL_ICON, 내 거래 표시와 같은 그림)이다. 신호가 없으면 AI(sparkle) 또는 등급 아이콘.
 * - 카드 줄이 이미 같은 금액을 말하면 머리 줄에 금액을 또 쓰지 않는다(C10).
 * opts.actions: 카드 아래에 더할 버튼들(예: [알리기]·[담기]·[자세히]).
 */
export function alertCard(item, { actions = null } = {}) {
  const c = item.card;
  const t = item.txn;
  const lv = LEVEL[c.level] || LEVEL.caution;
  const signals = txnSignals({ ...item, level: item.level || c.level });
  const headIcon = signals.length ? signals[0].icon : lv.icon;
  const lines = c.lines || [];
  const said = t.amount ? lines.some((line) => String(line).includes(formatWon(t.amount))) : false;
  const speak = speakButton(() => [lv.text, c.speak_text].map(sentence).join(" "), { cls: "btn sm" });
  return h("article", { class: `card alert-card level-${c.level}`, "aria-label": `${lv.text}: ${c.title}` },
    h("div", { class: "alert-head" },
      h("span", { class: `row-icon ${c.level === "high" ? "red" : "orange"}` }, icon(headIcon)),
      levelBadge(c.level),
      flagBadge(item), reviewBadge(item), notifiedBadge(item)),
    h("h3", { text: keepUnits(c.title) }),
    subParts([...whenParts(t.ts), t.counterparty || "(이름 없음)", said ? "" : moneyText(t.amount)], "muted card-meta"),
    // 카드 줄은 문장마다 한 줄(li 안 p), 숫자와 단위(168만 원)·시각은 줄 끝에서 떨어지지 않게(keepUnits, 보이는 글만)
    h("ul", { class: "pause-lines" }, lines.map((line) => h("li", null, h("p", { text: keepUnits(line) })))),
    c.question ? h("p", { class: "muted card-question", text: keepUnits(c.question) }) : null,
    speak || actions ? h("div", { class: "card-actions" }, speak, actions) : null);
}

/** 평소 내 거래와 다른 정도(percentile 0~100, 클수록 다름) → "상위 3%". 절반보다 덜 다르면 null. */
function topText(percentile) {
  const p = Number(percentile);
  if (!Number.isFinite(p) || p < 50) return null;
  return `상위 ${Math.max(1, Math.ceil(100 - p))}%`;
}

/**
 * 왜 걱정되나요(수정 계획 1-D): 두 갈래를 돌려준다.
 *  - 약속(규칙)으로 본 것: 명사형 신호 목록(없으면 걸린 것이 없다고 씀)
 *  - AI가 본 것(item.ai가 있을 때만): 평소 내 거래와 다른 정도(상위 N%) + 평소와 가장 다른 점 한 줄.
 *    모델이 아직 없으면(거래 30건 미만) 배우는 중이라고 쓴다. AI만 먼저 찾은 거래는 그렇다고 쓴다.
 *    top_feature는 평균과 가장 다른 특징 한 가지일 뿐이라 AI가 판단한 이유(기여도)라고 쓰지 않는다.
 * item.ai: {fitted, percentile(0~100|null), top_feature(쉬운 말 한 줄|null), only_ai}
 * opts.heading: 제목 단계(기본 3: 시트 제목 h2 아래). 묶음 제목은 그 다음 단계.
 */
export function aiExplain(item, { heading = 3 } = {}) {
  const hTag = `h${Math.min(Math.max(heading, 2), 5)}`;
  const subTag = `h${Math.min(Math.max(heading, 2), 5) + 1}`;
  const rules = txnSignals(item || {}).filter((s) => s.code !== "anomaly");
  const ai = item && item.ai && typeof item.ai === "object" ? item.ai : null;
  const ruleBlock = h("div", { class: "ae-group" },
    h(subTag, { class: "ae-title" }, icon("list"), h("span", { text: AI_TEXT.rules })),
    rules.length
      ? h("ul", { class: "ae-list" }, rules.map((s) => h("li", null, icon(s.icon), h("span", { text: s.text }))))
      : h("p", { class: "muted", text: AI_TEXT.rulesNone }));
  let aiBlock = null;
  if (ai) {
    const body = [];
    if (!ai.fitted) {
      body.push(h("p", { class: "muted", text: AI_TEXT.aiLearning }));
    } else {
      const top = topText(ai.percentile);
      if (top) body.push(h("p", { class: "ae-diff" }, h("span", { text: AI_TEXT.diffLabel }), h("b", { class: "ae-diff-value", text: top })));
      else if (ai.percentile !== null && ai.percentile !== undefined) body.push(h("p", { text: "평소 내 거래와 비슷한 편이에요." }));
      if (ai.top_feature) body.push(h("p", { text: keepUnits(sentence(ai.top_feature)) }));
      if (ai.only_ai) body.push(h("p", { class: "ae-only" }, icon("sparkle"), h("span", { text: AI_TEXT.aiOnly })));
      if (!body.length) body.push(h("p", { class: "muted", text: AI_TEXT.aiNone }));
    }
    aiBlock = h("div", { class: "ae-group ae-ai" },
      h(subTag, { class: "ae-title" }, icon("sparkle"), h("span", { text: AI_TEXT.ai })), body);
  }
  return h("section", { class: "ai-explain" }, h(hTag, { class: "ae-head", text: AI_TEXT.title }), ruleBlock, aiBlock);
}

/** 오류 안내 상자. 동의 오류면 '동의 켜러 가기' 버튼을 붙인다. */
export function errorNotice(err, go) {
  const msg = err instanceof ApiError || (err && err.message) ? err.message : String(err);
  return h("div", { class: "notice red", role: "alert" }, icon("warning"),
    h("div", null, h("p", { text: msg }),
      isConsentError(err) && go
        ? h("button", { type: "button", class: "btn sm weak notice-action", onclick: () => go("more/consent") }, icon("toggle"), h("span", { text: "동의 켜러 가기" }))
        : null));
}

export function learnedText(span, rows) {
  if (Number.isInteger(rows) && rows > 0 && rows < span) {
    return `AI는 앞쪽 거래 ${nf.format(span)}건 가운데 ${nf.format(rows)}건으로 평소 모습을 배웠어요. `
      + `맨 앞 ${nf.format(span - rows)}건은 비교할 평소가 없어서 뺐어요.`;
  }
  return `AI는 앞쪽 거래 ${nf.format(span)}건으로 평소 모습을 배웠어요.`;
}

/** 파일로 저장: 안드로이드는 시스템 저장 창, PC 브라우저는 내려받기. */
export function saveFile(filename, mime, text) {
  const native = window.SafePauseNative;
  if (native && typeof native.saveFile === "function") {
    const bytes = new TextEncoder().encode(text);
    let bin = "";
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    const token = `s${Date.now()}`;
    return new Promise((resolve) => {
      window.__safepauseSaveDone = (tk, status) => { if (tk === token) resolve(status); };
      if (!native.saveFile(token, filename, mime, btoa(bin))) resolve("error");
    });
  }
  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: filename, hidden: true });
  document.body.append(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 4000);
  return Promise.resolve("saved");
}

export { formatWon, formatWhen, setText };
