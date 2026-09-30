/* 여러 화면이 같이 쓰는 부품: 등급 배지, 거래 줄, 기록 카드, 소리로 듣기, 오류 안내. */
import { h, icon, picto, toast } from "./ui.js";
import { formatWon, formatTime, formatDate, formatWhen, parseTs, nf, sentence } from "./format.js";
import { LEVEL, CHANNEL_KO, CHANNEL_ICON, SIGNAL_ICON, SIGNAL_KO, signalLabel } from "./labels.js";
import { isConsentError, ApiError } from "./api.js";
import * as speech from "./speech.js";

export function levelBadge(level) {
  const lv = LEVEL[level] || LEVEL.none;
  return h("span", { class: `badge ${lv.cls}` }, icon(lv.icon), h("span", { text: lv.text }));
}

/** 거래 한 줄(토스 목록 모양). onOpen이 있으면 눌러서 자세히 보기. */
export function txnRow(item, onOpen) {
  const t = item.txn;
  const out = t.direction === "out";
  const d = parseTs(t.ts);
  const tone = item.level === "high" ? "red" : item.level === "caution" ? "orange" : out ? "" : "blue";
  const tags = [];
  if (item.level !== "none") tags.push(levelBadge(item.level));
  for (const code of item.signals || []) tags.push(h("span", { class: "tag" }, icon(SIGNAL_ICON[code] || "warning"), h("span", { text: signalLabel(item, code) })));
  if ((item.reasons || []).some((r) => String(r.code).startsWith("anomaly:")) && !(item.signals || []).length && item.level !== "none") {
    tags.push(h("span", { class: "tag" }, icon("sparkle"), h("span", { text: "평소와 달라요 (AI)" })));
  }
  if (item.practice) tags.push(h("span", { class: "tag", text: "보내기 연습" }));
  if (t.label && t.label !== "normal") tags.push(h("span", { class: "tag", text: `연습용 정답: ${SIGNAL_KO[t.label] || t.label}` }));
  const body = [
    h("span", { class: `row-icon ${tone}`.trim() }, icon(CHANNEL_ICON[t.channel] || "money")),
    h("span", { class: "row-main" },
      h("span", { class: "row-title", text: t.counterparty || "(이름 없음)" }),
      h("span", { class: "row-sub", text: `${d ? formatTime(d) : ""} · ${CHANNEL_KO[t.channel] || t.channel}` })),
    h("span", { class: "row-end" },
      h("span", { class: `row-amount${out ? "" : " in"}`, text: `${out ? "-" : "+"}${nf.format(t.amount)}원` }),
      h("span", { class: "row-sub", text: formatWon(t.amount) })),
    // 표시(등급·이유)는 이름·금액 아래 한 줄을 통째로 쓴다(좁은 화면에서 금액 칸에 밀려 한두 글자씩 끊기지 않게)
    tags.length ? h("span", { class: "row-tags full" }, tags) : null,
  ];
  const reasons = (item.signals || []).map((code) => signalLabel(item, code));
  const label = [t.counterparty || "이름 없음", d ? formatTime(d) : "", CHANNEL_KO[t.channel] || t.channel,
    `${out ? "나감" : "들어옴"} ${formatWon(t.amount)}`, LEVEL[item.level] ? LEVEL[item.level].text : "",
    ...reasons, item.practice ? "보내기 연습" : ""].filter(Boolean).join(", ");
  return onOpen
    ? h("button", { type: "button", class: "row wrap", "aria-label": label, onclick: () => onOpen(item) }, body)
    : h("div", { class: "row wrap" }, body);
}

export function dateHead(ts) {
  const d = parseTs(ts);
  return h("div", { class: "date-head", text: d ? formatDate(d) : "" });
}

/** 소리로 듣기 버튼. 기기에 한국어 음성이 없으면 null(버튼을 만들지 않음). */
export function speakButton(getText, { label = "소리로 듣기", cls = "btn block" } = {}) {
  if (!speech.available()) return null;
  return h("button", {
    type: "button", class: cls,
    onclick: () => { if (!speech.speak(typeof getText === "function" ? getText() : getText)) toast("지금은 소리로 읽을 수 없어요."); },
  }, icon("speaker"), h("span", { text: label }));
}

/** 기록 카드(알림 화면·홈): 이미 끝난 거래라 과거형, 선택지 없음. */
export function alertCard(item) {
  const c = item.card;
  const t = item.txn;
  const lv = LEVEL[c.level] || LEVEL.caution;
  return h("article", { class: `card pause level-${c.level}`, "aria-label": `${lv.text}: ${c.title}` },
    h("div", { class: "alert-head" },
      h("span", { class: `row-icon ${c.level === "high" ? "red" : "orange"}` }, picto((c.pictograms || [])[0] || lv.icon, "ic") || icon(lv.icon)),
      levelBadge(c.level)),
    h("h3", { text: c.title }),
    h("p", { class: "muted", text: `${formatWhen(t.ts)} · ${t.counterparty || "(이름 없음)"} · ${formatWon(t.amount)}` }),
    h("ul", { class: "pause-lines", style: "margin:.9rem 0 0" }, c.lines.map((line) => h("li", { text: line }))),
    c.question ? h("p", { class: "muted", style: "margin-top:.6rem", text: c.question }) : null,
    speakButton(() => [lv.text, c.speak_text].map(sentence).join(" "), { cls: "btn sm", label: "소리로 듣기" }));
}

/** 오류 안내 상자. 동의 오류면 '동의 켜러 가기' 버튼을 붙인다. */
export function errorNotice(err, go) {
  const msg = err instanceof ApiError || (err && err.message) ? err.message : String(err);
  return h("div", { class: "notice red", role: "alert" }, icon("warning"),
    h("div", null, h("p", { text: msg }),
      isConsentError(err) && go
        ? h("button", { type: "button", class: "btn sm weak", style: "margin-top:.6rem", onclick: () => go("more/consent") }, icon("toggle"), h("span", { text: "동의 켜러 가기" }))
        : null));
}

export function practicePill() {
  return h("span", { class: "practice-pill" }, icon("warning"), h("span", { text: "연습 화면 · 실제로 돈이 나가지 않아요" }));
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
  const a = h("a", { href: url, download: filename, style: "display:none" });
  document.body.append(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 4000);
  return Promise.resolve("saved");
}

export { formatWon, formatWhen };
