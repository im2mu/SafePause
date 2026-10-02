/* 결과 내보내기(조력자·기관용): 한 장 요약(글 파일), 현장 검증용 요약 파일, 분석 결과 표 파일.
 * 앱은 시스템 저장 창, PC는 내려받기로 저장한다(components.saveFile). 번호·메일 원본은 파일에 넣지 않는다(서버).
 * 한 장 요약(AUG-10)은 이미 있는 API(거래 수·돈 흐름·보낸 알림)를 모아 화면에서 만든다.
 * 이름·계좌번호·연락처는 넣지 않고 수와 합계만 담는다. 저장하기 전에 담길 글을 시트에서 먼저 보여 준다.
 * 조력자용 보고서(PDF)·매달 요약 보내기는 정식 버전 기능이라 준비 중 안내만 연다(AUG-15). */
import { h, icon, fill, busy, toast, announce, comingSoonSheet, openSheet } from "../ui.js";
import { errorNotice, saveFile, menuRow } from "../components.js";
import { deviceWord, moneyText, formatMonth, parseTs, percent, nf, bandLabel, keepUnits } from "../format.js";
import { SIGNALS, SIGNAL_KO, CHANNEL_KO, NOTICE_CHANNEL_KO } from "../labels.js";
import { STALE } from "../api.js";

const FILES = [
  { icon: "file", type: "JSON", title: "현장 검증용 요약 파일", path: "/api/export/validation",
    lines: ["이름·계좌·금액·날짜 없이 거래 수와 알림 수만 담아요.", "시범 사용 결과를 모을 때 본인이 동의하고 직접 전달해요."] },
  { icon: "download", type: "CSV", title: "분석 결과 표 파일", path: "/api/export/results",
    lines: ["거래마다 판단 결과를 담아요.", "받는 사람 이름이 들어 있어서 나만 봐요."] },
];

export default {
  title: "결과 내보내기",
  back: "more",
  tab: "more",
  async render(ctx) {
    const { main, go } = ctx;
    const out = h("div", { "aria-live": "polite" });
    const sumOut = h("div", { "aria-live": "polite" });
    fill(main,
      h("h2", { class: "page-title", tabindex: "-1", text: "결과 내보내기" }),
      h("p", { class: "page-sub", text: `조력자나 기관에 보여 줄 파일이에요. 파일은 ${deviceWord()}에 저장해요.` }),

      h("article", { class: "card export-card summary-card", "aria-label": "한 장 요약" },
        h("div", { class: "export-top" },
          h("span", { class: "row-icon blue" }, icon("doc")),
          h("div", { class: "export-main" },
            h("b", { class: "export-title", text: "조력자·기관용 한 장 요약" }),
            h("span", { class: "export-type", text: "글 파일(.txt)" }))),
        h("p", { class: "muted", text: "돈 흐름과 걱정되는 거래 수를 한\u00a0장으로 정리해요. 상담하는 곳에 갈 때 보여 주거나 인쇄할 수 있어요. 이름·계좌번호·연락처는 넣지 않아요." }),
        h("button", { type: "button", class: "btn primary block export-btn", onclick: (e) => busy(e.currentTarget, makeSummary) },
          icon("doc"), h("span", { text: "요약 만들기" }))),
      sumOut,

      h("div", { class: "export-list" }, FILES.map((f) => fileCard(f))),
      out,
      h("h3", { class: "section-title", text: "정식 버전에서 더할 것" }),
      h("div", { class: "list" },
        menuRow({ icon: "doc", title: "조력자용 보고서(PDF)", soon: true, onclick: () => comingSoonSheet({
          icon: "doc", title: "조력자용 보고서(PDF)",
          lines: [["한 달 동안의 돈 흐름과 걱정되는 거래를 그림과 표로 정리해요.", "인쇄하거나 상담하는 곳에 보여 줄 수 있어요."],
            ["지금은 위의 한 장 요약을 글 파일로 저장할 수 있어요."]],
          action: "만들기" }) }),
        menuRow({ icon: "calendar", title: "매달 요약 보내기", sub: "조력자·상담하는 곳에 매달 요약을 보내요.", soon: true, onclick: () => comingSoonSheet({
          icon: "calendar", title: "매달 요약 보내기",
          lines: ["매달 정한 날에 돈 흐름 요약을 조력자나 상담하는 곳에 보내요.", "보낼 사람과 담을 내용은 내가 정해요."],
          steps: [
            { title: "받는 사람 고르기", sub: "조력자나 상담하는 곳에서 골라요." },
            { title: "보낼 날 정하기", options: ["매달 1일", "매달 15일"] },
            { title: "보낼 내용 고르기", options: ["나간 돈", "걱정되는 거래 수", "보낸 알림 수"] },
          ],
          action: "켜기" }) })));

    function fileCard(f) {
      return h("article", { class: "card export-card", "aria-label": f.title },
        h("div", { class: "export-top" },
          h("span", { class: "row-icon blue" }, icon(f.icon)),
          h("div", { class: "export-main" },
            h("b", { class: "export-title", text: f.title }),
            h("span", { class: "export-type", text: `${f.type} 파일` }))),
        h("p", { class: "muted", text: f.lines.join(" ") }),
        h("button", { type: "button", class: "btn weak block export-btn", onclick: (e) => busy(e.currentTarget, () => save(f)) },
          icon("download"), h("span", { text: "파일로 저장하기" })));
    }

    async function save(f) {
      try {
        const r = await ctx.req("GET", f.path);
        const st = await saveFile(r.filename, r.mime, r.text);
        report(st);
        if (r.note) fill(out, h("div", { class: "notice orange" }, icon("info"), h("p", { text: r.note })));
        else out.replaceChildren();
      } catch (err) {
        if (err === STALE) return;
        fill(out, errorNotice(err, go));
      }
    }

    // 한 장 요약: 모은 값으로 글을 만들고, 시트에서 담길 글을 보여 준 뒤 저장한다
    async function makeSummary() {
      try {
        const [data, txns, ins, notices] = await Promise.all([
          ctx.req("GET", "/api/data/summary"),
          ctx.req("GET", "/api/transactions?level=caution"),
          ctx.req("GET", "/api/insights"),
          ctx.req("GET", "/api/notices"),
        ]);
        sumOut.replaceChildren();
        const doc = buildSummary({ data, txns, ins, notices, now: new Date() });
        openSummarySheet(doc);
      } catch (err) {
        if (err === STALE) return;
        fill(sumOut, errorNotice(err, go));
      }
    }

    function openSummarySheet(doc) {
      openSheet((close) => [
        h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: "한 장 요약" }),
        h("p", { class: "sheet-sub", text: "아래 글이 파일에 담겨요. 이름·계좌번호·연락처는 넣지 않았어요." }),
        h("div", { class: "summary-preview" }, doc.sections.map((sec) => h("section", { class: "summary-sec" },
          h("h3", { text: sec.title }),
          h("ul", null, sec.lines.map((t) => h("li", null, h("p", { text: keepUnits(t) }))))))),
        h("div", { class: "sheet-actions" },
          h("button", { type: "button", class: "btn primary big block", onclick: (e) => busy(e.currentTarget, async () => {
            const st = await saveFile(doc.filename, "text/plain", doc.text);
            report(st);
            if (st === "saved") close();
          }) }, icon("download"), h("span", { text: "파일로 저장하기" })),
          h("button", { type: "button", class: "btn big block", text: "닫기", onclick: () => close() })),
      ], { label: "한 장 요약" });
    }
  },
};

function report(st) {
  const msg = st === "saved" ? "저장했어요." : st === "cancelled" ? "저장하지 않았어요." : "저장하지 못했어요.";
  toast(msg, st === "error" ? "error" : "");
  announce(msg);
}

const pad = (n) => String(n).padStart(2, "0");
const count = (n) => `${nf.format(n || 0)}건`;
const ymd = (d) => `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일`;

/**
 * 한 장 요약 글. 이름·계좌번호·연락처·메모·글 내용은 넣지 않는다(수·합계·달·결제 방법·시간대만).
 * 보내기 전 확인으로 적은 거래(practice)는 실제로 보냈는지 몰라 걱정되는 거래 수에서 뺀다(돈 흐름 분석과 같음).
 */
export function buildSummary({ data, txns, ins, notices, now }) {
  const items = (txns.items || []).filter((x) => !x.practice);
  const level = (lv) => items.filter((x) => x.level === lv);
  const high = level("high"), caution = level("caution");
  const reviewed = items.filter((x) => x.reviewed).length;
  const notified = items.filter((x) => x.notified_at).length;
  const aiOnly = items.filter((x) => x.ai && x.ai.only_ai).length;
  const bySignal = SIGNALS.map((code) => [code, items.filter((x) => (x.signals || []).includes(code)).length]).filter(([, n]) => n);

  const first = parseTs(data.first_ts), last = parseTs(data.last_ts);
  const sections = [];
  sections.push({ title: "SafePause 한 장 요약", lines: [
    `만든 날: ${ymd(now)}`,
    first && last
      ? `살펴본 거래: ${ymd(first)}부터 ${first.getFullYear() === last.getFullYear() ? ymd(last).replace(/^\d+년 /, "") : ymd(last)}까지 ${count(data.count)}`
      : `살펴본 거래: ${count(data.count)}`,
  ] });
  sections.push({ title: "걱정되는 거래", lines: [
    `꼭 확인할 거래: ${count(high.length)}`,
    `확인할 거래: ${count(caution.length)}`,
    ...(reviewed ? [`이 가운데 내가 한 거래라고 표시한 것: ${count(reviewed)}`] : []),
    ...(aiOnly ? [`AI만 먼저 찾은 거래: ${count(aiOnly)}`] : []),
    ...(notified ? [`조력자나 상담하는 곳에 알린 거래: ${count(notified)}`] : []),
  ] });
  if (bySignal.length) {
    sections.push({ title: "걱정되는 거래의 종류", lines: [
      ...bySignal.map(([code, n]) => `${SIGNAL_KO[code]}: ${count(n)}`),
      "한 거래에 여러 종류가 겹칠 수 있어요.",
    ] });
  }

  const tm = ins.this_month;
  if (tm) {
    const lines = [`나간 돈: ${moneyText(tm.out_total)} (${count(tm.out_count)})`, `들어온 돈: ${moneyText(tm.in_total)}`];
    const cmp = ins.compare;
    if (cmp && Number.isFinite(cmp.prev_same_period_out)) {
      const diff = tm.out_total - cmp.prev_same_period_out;
      const period = cmp.days ? `지난달 같은 기간(1~${cmp.days}일)` : "지난달 같은 기간";
      lines.push(diff === 0 ? `${period}과 나간 돈이 같아요.`
        : `${period}보다 ${moneyText(Math.abs(diff))} ${diff > 0 ? "더 나갔어요." : "덜 나갔어요."}`);
    }
    sections.push({ title: `${formatMonth(tm.month, true)} 돈 흐름`, lines });
  }
  if ((ins.months || []).length) {
    sections.push({ title: "달마다 나간 돈", lines: ins.months.map((m) => {
      const f = (m.flagged && (m.flagged.high || 0) + (m.flagged.caution || 0)) || 0;
      return `${formatMonth(m.month, true)}: ${moneyText(m.out_total)} (${count(m.out_count)}, 걱정되는 거래 ${count(f)})`;
    }) });
  }
  if ((ins.channels || []).length) {
    sections.push({ title: `${tm ? formatMonth(tm.month) : "이번 달"}에 어디에 썼나요`, lines: ins.channels.map((c) =>
      `${CHANNEL_KO[c.channel] || "그 밖"}: ${moneyText(c.out_total)} (${percent(c.share, 0)})`) });
  }
  const bands = (ins.time_bands || []).filter((b) => b.flagged);
  if (bands.length) {
    sections.push({ title: "걱정되는 거래가 있었던 때", lines: bands.map((b) => `${bandLabel(b.band, { range: true })}: ${count(b.flagged)}`) });
  }
  const recs = notices.items || [];
  const manual = recs.filter((r) => r.kind === "manual");
  const byChannel = Object.keys(NOTICE_CHANNEL_KO).map((ch) => [ch, manual.filter((r) => r.channel === ch).length]).filter(([, n]) => n);
  sections.push({ title: "알림", lines: [
    `알림 보내기 기록: ${count(manual.length)}${byChannel.length ? ` (${byChannel.map(([ch, n]) => `${NOTICE_CHANNEL_KO[ch]} ${n}`).join(" · ")})` : ""}`,
    `적어 둔 기록(아직 안 보냄): ${count(recs.length - manual.length)}`,
    "알림 보내기 기록은 앱을 연 기록이에요. 실제로 보냈는지는 문자·메일 앱에서 확인해야 해요.",
  ] });
  sections.push({ title: "읽을 때 알아 둘 것", lines: [
    "걱정되는 거래는 SafePause가 한 번 더 살펴보라고 고른 거래예요.",
    "실제로 문제가 있었는지는 본인과 함께 확인해 주세요.",
    "이 요약에는 이름·계좌번호·연락처를 넣지 않았어요.",
  ] });

  const text = sections.map((s) => [`[${s.title}]`, ...s.lines].join("\n")).join("\n\n") + "\n";
  const filename = `safepause-summary-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}.txt`;
  return { sections, text, filename };
}
