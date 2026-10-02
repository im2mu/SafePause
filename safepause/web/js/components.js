/* 여러 화면이 같이 쓰는 부품: 등급 배지, 거래 줄, 담기 버튼, 메뉴 줄, 쉬운 말 카드, 소리로 듣기, 오류 안내. */
import { h, icon, picto, toast, setText, soonBadge } from "./ui.js";
import { formatWon, formatTime, formatDate, formatWhen, parseTs, nf, sentence, moneyText } from "./format.js";
import { LEVEL, CHANNEL_KO, CHANNEL_ICON, SIGNAL_ICON, signalLabel } from "./labels.js";
import { isConsentError, ApiError, STALE } from "./api.js";
import * as speech from "./speech.js";

export { soonBadge };

export function levelBadge(level) {
  const lv = LEVEL[level] || LEVEL.none;
  return h("span", { class: `badge ${lv.cls}` }, icon(lv.icon), h("span", { text: lv.text }));
}

/** 담은 거래 배지(알림 목록에 담은 거래). */
export function flaggedBadge() {
  return h("span", { class: "badge info" }, icon("bookmark-fill"), h("span", { text: "담음" }));
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
  return h("span", { class: `${cls} parts` }, parts.filter(Boolean).map((t) => h("span", { text: String(t).replace(/ /g, "\u00a0") })));
}

/** 날짜와 시각을 따로: ["2026년 6월 27일 (토)", "새벽 4시 41분"](subParts에서 날짜·시각 사이에서만 줄을 바꾸게). */
export function whenParts(ts) {
  const d = parseTs(ts);
  return d ? [formatDate(d), formatTime(d)] : [String(ts || "")];
}

/** 거래 한 줄(토스 목록 모양): 이름과 금액 한 줄 → 시각·방법 → 표시. onOpen이 있으면 눌러서 거래 시트를 연다. 금액은 한 번만 쓴다. */
export function txnRow(item, onOpen) {
  const t = item.txn;
  const out = t.direction === "out";
  const d = parseTs(t.ts);
  const tone = item.level === "high" ? "red" : item.level === "caution" ? "orange" : out ? "" : "blue";
  const signals = txnSignals(item);
  const tags = [];
  if (item.level && item.level !== "none") tags.push(levelBadge(item.level));
  for (const s of signals) tags.push(h("span", { class: "tag" }, icon(s.icon), h("span", { text: s.text })));
  if (item.flagged) tags.push(flaggedBadge());
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
    ...signals.map((s) => s.text), item.flagged ? "담음" : ""].filter(Boolean).join(", ");
  return onOpen
    ? h("button", { type: "button", class: "row txn-row", "aria-label": label, onclick: () => onOpen(item) }, body)
    : h("div", { class: "row txn-row" }, body);
}

export function dateHead(ts) {
  const d = parseTs(ts);
  return h("div", { class: "date-head", text: d ? formatDate(d) : "" });
}

/**
 * 알림 목록에 담기 ↔ 담기 취소 버튼(POST /api/flags, /api/flags/remove).
 * item: {txn: {id}, flagged}. opts: {cls, onChange(flagged, count)}.
 * 담으면 토스트 "알림 탭에 담았어요.", 빼면 "알림 목록에서 뺐어요."
 */
export function flagButton(ctx, item, { cls = "btn big block", onChange = null } = {}) {
  let flagged = Boolean(item.flagged);
  const ic = h("span", { class: "btn-ic" });
  const text = h("span");
  const btn = h("button", { type: "button", class: cls, "aria-pressed": "false" }, ic, text);
  function paint() {
    btn.setAttribute("aria-pressed", flagged ? "true" : "false");
    ic.replaceChildren(icon(flagged ? "bookmark-fill" : "bookmark"));
    text.textContent = flagged ? "담기 취소" : "알림 목록에 담기";
  }
  btn.addEventListener("click", async () => {
    if (btn.getAttribute("aria-busy") === "true") return;
    btn.setAttribute("aria-busy", "true");
    btn.disabled = true;
    const next = !flagged;
    try {
      const r = await ctx.req("POST", next ? "/api/flags" : "/api/flags/remove", { txn_id: item.txn.id });
      flagged = next;
      item.flagged = next;
      paint();
      toast(next ? "알림 탭에 담았어요." : "알림 목록에서 뺐어요.");
      if (typeof onChange === "function") onChange(next, r && r.count);
    } catch (e) {
      if (e !== STALE) toast(e && e.message ? e.message : "담지 못했어요. 다시 해 주세요.", "error");
    } finally {
      if (btn.isConnected) { btn.removeAttribute("aria-busy"); btn.disabled = false; }
    }
  });
  paint();
  return btn;
}

/**
 * 메뉴 한 줄(전체 탭·설정). {icon, tone, title, sub, href | onclick, soon, end}
 * soon이면 준비 중 배지를 붙인다(누르면 화면이 comingSoonSheet를 연다).
 */
export function menuRow({ icon: ic, tone = "", title, sub = "", href = null, onclick = null, soon = false, end = null }) {
  const inner = [
    h("span", { class: `row-icon ${tone}`.trim() }, icon(ic)),
    h("span", { class: "row-main" },
      h("span", { class: "row-title" }, h("span", { text: title }), soon ? soonBadge() : null),
      sub ? h("span", { class: "row-sub", text: sub }) : null),
    end || h("span", { class: "row-chev" }, icon("chevron")),
  ];
  if (href) return h("a", { class: "row menu-row", href }, inner);
  return h("button", { type: "button", class: "row menu-row", onclick }, inner);
}

/**
 * 소리로 듣기 ↔ 멈추기 토글 버튼. 기기에 한국어 음성이 없으면 null(버튼을 만들지 않음).
 * 누르면 읽고(aria-pressed=true, 글자 "멈추기"), 다시 누르면 멈춘다. 다른 버튼이 읽기 시작하거나
 * 다 읽으면 원래대로 돌아간다(한 번에 하나만 읽음).
 */
export function speakButton(getText, { label = "소리로 듣기", stopLabel = "멈추기", cls = "btn block" } = {}) {
  if (!speech.available()) return null;
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
    if (!speech.speak(t, { onEnd: () => paint(false) })) { toast("지금은 소리로 읽을 수 없어요."); return; }
    paint(true);
  });
  paint(false);
  return btn;
}

/**
 * 쉬운 말 카드(알림 탭·홈): 그림, 등급, 제목, 줄, 소리로 듣기.
 * opts.actions: 카드 아래에 더할 버튼들(예: [알리기]·[담기]).
 */
export function alertCard(item, { actions = null } = {}) {
  const c = item.card;
  const t = item.txn;
  const lv = LEVEL[c.level] || LEVEL.caution;
  const speak = speakButton(() => [lv.text, c.speak_text].map(sentence).join(" "), { cls: "btn sm" });
  return h("article", { class: `card alert-card level-${c.level}`, "aria-label": `${lv.text}: ${c.title}` },
    h("div", { class: "alert-head" },
      h("span", { class: `row-icon ${c.level === "high" ? "red" : "orange"}` }, picto((c.pictograms || [])[0] || lv.icon, "ic") || icon(lv.icon)),
      levelBadge(c.level),
      item.flagged ? flaggedBadge() : null),
    h("h3", { text: c.title }),
    subParts([...whenParts(t.ts), t.counterparty || "(이름 없음)", moneyText(t.amount)], "muted card-meta"),
    h("ul", { class: "pause-lines" }, c.lines.map((line) => h("li", { text: line }))),
    c.question ? h("p", { class: "muted card-question", text: c.question }) : null,
    speak || actions ? h("div", { class: "card-actions" }, speak, actions) : null);
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
