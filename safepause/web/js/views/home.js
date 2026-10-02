/* 홈: 지금 상태 + 기준 달 돈 흐름(큰 숫자·차트) + 바로가기.
 * - 기준 달은 저장된 마지막 거래가 있는 달이다(/api/insights). 연습용 거래는 지난 날짜라 이번 달이 아닐 수 있다.
 * - 상태 카드는 /api/transactions?limit=1의 요약 수를 쓴다. 돈 흐름은 /api/insights를 쓴다(둘은 따로 불러 한쪽이 실패해도 다른 쪽은 보인다).
 * - 거래 살펴보기가 꺼져 있거나 거래가 없으면 빈 상태 안내 + 버튼을 보인다.
 * - 차트는 js/charts.js(SVG)로 그리고, 차트마다 글로 된 요약(aria-label)과 숨긴 표를 둔다.
 */
import { h, icon, fill, setText, skeleton, emptyState } from "../ui.js";
import { nf, moneyText, formatWon, formatMonth, deviceWord, percent } from "../format.js";
import { errorNotice, speakButton } from "../components.js";
import { CHANNEL_KO, CHANNEL_CHART } from "../labels.js";
import { STALE, ApiError, isConsentError } from "../api.js";
import { columnChart, ratioBar, srTable, shortWon } from "../charts.js";

// 시간대 이름(format.formatTime의 새벽·오전·오후·저녁과 맞춤)
const BANDS = {
  dawn: { name: "새벽", hours: "0~6시" }, morning: { name: "오전", hours: "6~12시" },
  day: { name: "오후", hours: "12~18시" }, evening: { name: "저녁", hours: "18~24시" },
};

export default {
  title: "홈",
  tab: "home",
  announce: "SafePause 홈",
  async render(ctx) {
    const statusSlot = h("div", { "aria-busy": "true" }, skeleton(1));
    const flowSlot = h("div", { "aria-busy": "true" }, skeleton(3));
    fill(ctx.main, h("div", { class: "home" },
      h("h2", { class: "sr-only", tabindex: "-1", text: "홈" }),
      statusSlot,
      flowSlot,
      quickLinks()));
    const done = (slot, ...nodes) => { slot.removeAttribute("aria-busy"); fill(slot, ...nodes); };

    let consent;
    try {
      consent = await ctx.req("GET", "/api/consent");
      ctx.session.consent = consent;
    } catch (e) {
      if (e === STALE) return;
      done(statusSlot, loadError(ctx, e, "지금 상태를 불러오지 못했어요."));
      done(flowSlot);
      return;
    }
    if (!consent.monitoring) {
      done(statusSlot, offCard());
      done(flowSlot);
      return;
    }

    // 요약 수와 돈 흐름은 함께 부른다(앱에서는 AI 준비가 끝난 뒤 온다)
    const [tx, ins] = await Promise.allSettled([
      ctx.req("GET", "/api/transactions?level=all&limit=1"),
      ctx.req("GET", "/api/insights"),
    ]);
    if (tx.reason === STALE || ins.reason === STALE || !ctx.alive()) return;

    if (tx.status === "fulfilled") done(statusSlot, statusCard(tx.value));
    else done(statusSlot, loadError(ctx, tx.reason, "지금 상태를 불러오지 못했어요."));

    if (tx.status === "fulfilled" && !tx.value.count) { done(flowSlot, noTxnCard()); return; }
    if (ins.status === "rejected") { done(flowSlot, loadError(ctx, ins.reason, "돈 흐름을 불러오지 못했어요.")); return; }
    const data = ins.value || {};
    if (!data.this_month || !(data.months || []).length) { done(flowSlot, noTxnCard()); return; }
    done(flowSlot, flowSection(ctx, data));
  },
};

// ---- 상태 카드 -------------------------------------------------------------------
function statusDot(on) {
  return h("p", { class: `hero-status${on ? "" : " off"}` },
    h("span", { class: "dot", "aria-hidden": "true" }), h("span", { text: on ? "거래 살펴보기 켜짐" : "거래 살펴보기 꺼짐" }));
}

function statusCard(t) {
  const s = t.summary || {};
  const high = s.high || 0;
  const caution = s.caution || 0;
  let title;
  if (!t.count) title = h("h3", { id: "home-status-title", class: "hero-title", text: "아직 저장된 거래가 없어요" });
  else if (high || caution) {
    title = h("h3", { id: "home-status-title", class: "hero-title" },
      high ? "꼭 확인할 거래가 " : "확인할 거래가 ",
      h("span", { class: `home-num ${high ? "high" : "caution"}`, text: `${nf.format(high || caution)}건` }), " 있어요");
  } else title = h("h3", { id: "home-status-title", class: "hero-title", text: "걱정되는 거래가 없어요" });
  const note = !t.count
    ? "파일이나 연습용 거래로 불러올 수 있어요."
    : [`저장된 거래 ${nf.format(t.count)}건을 ${deviceWord()} 안에서 살펴봤어요.`,
      high && caution ? `확인할 거래도 ${nf.format(caution)}건 있어요.` : ""].filter(Boolean).join(" ");
  const flagged = t.flagged_count || 0;
  return h("section", { class: "card hero home-hero", "aria-labelledby": "home-status-title" },
    statusDot(true),
    title,
    h("p", { class: "hero-note", text: note }),
    !t.count
      ? h("a", { class: "btn weak block home-cta", href: "#/txns" }, icon("upload"), h("span", { text: "거래 불러오기" }))
      : high || caution
        ? h("a", { class: "btn primary block home-cta", href: "#/alerts" }, icon("bell"), h("span", { text: "걱정되는 거래 보기" }))
        : null,
    flagged
      ? h("a", { class: "home-hero-link", href: "#/alerts?tab=flags" },
        icon("bookmark-fill"), h("span", { class: "grow", text: "담은 거래" }),
        h("b", { text: `${nf.format(flagged)}건` }), icon("chevron"))
      : null);
}

function offCard() {
  return h("section", { class: "card hero home-hero", "aria-labelledby": "home-status-title" },
    statusDot(false),
    h("h3", { id: "home-status-title", class: "hero-title", text: "지금은 거래를 살펴보지 않아요" }),
    h("p", { class: "hero-note", text: `켜면 ${deviceWord()} 안에서만 살펴봐요. 언제든지 끌 수 있어요.` }),
    h("a", { class: "btn weak block home-cta", href: "#/more/consent" }, icon("toggle"), h("span", { text: "동의 켜러 가기" })));
}

function noTxnCard() {
  return h("section", { class: "card home-card home-empty", "aria-label": "돈 흐름" },
    emptyState("chart", "돈 흐름을 보여 드릴 거래가 없어요", "거래를 불러오면 달마다 나간 돈과 쓴 곳을 그림으로 보여 드려요."),
    h("a", { class: "btn block", href: "#/txns?open=sample" }, icon("sparkle"), h("span", { text: "연습용 거래로 해 보기" })));
}

function loadError(ctx, err, title) {
  if (isConsentError(err)) return errorNotice(err, ctx.go);
  // 서버가 준 쉬운 말이면 같이 보이고, 그 밖(찾을 수 없음 등)은 쉬운 말 한 줄만 보인다
  const detail = err instanceof ApiError && err.status !== 404 && /[가-힣]/.test(err.message) ? err.message : "잠시 뒤 다시 해 주세요.";
  return h("div", { class: "notice red home-error", role: "alert" }, icon("warning"),
    h("div", null,
      h("strong", { text: title }),
      h("p", { text: detail }),
      h("button", { type: "button", class: "btn sm weak notice-action", onclick: () => ctx.go("home", { replace: true }) },
        icon("refresh"), h("span", { text: "다시 불러오기" }))));
}

// ---- 돈 흐름 ---------------------------------------------------------------------
function monthKeyNow() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function concernOf(m) {
  const f = (m && m.flagged) || {};
  return (f.caution || 0) + (f.high || 0);
}

// 받침이 있으면 으로, 없거나 ㄹ 받침이면 로
function withRo(word) {
  const code = String(word).charCodeAt(String(word).length - 1) - 0xac00;
  if (code < 0 || code > 11171) return `${word}로`;
  const jong = code % 28;
  return jong === 0 || jong === 8 ? `${word}로` : `${word}으로`;
}

function flowSection(ctx, data) {
  const tm = data.this_month;
  const prev = data.prev_month;
  const isNow = tm.month === monthKeyNow();
  const mWord = isNow ? "이번 달" : formatMonth(tm.month);
  const prevWord = isNow || !prev ? "지난달" : formatMonth(prev.month);
  const asOf = /^(\d{4})-(\d{2})-(\d{2})/.exec(data.as_of || "");
  return h("section", { class: "home-flow", "aria-labelledby": "home-flow-title" },
    h("h3", { id: "home-flow-title", class: "section-title" },
      h("span", { text: `${mWord} 돈 흐름` }),
      asOf ? h("span", { class: "home-asof", text: `${+asOf[2]}월 ${+asOf[3]}일까지` }) : null),
    summaryCard(tm, prev, mWord, prevWord),
    monthsCard(ctx, data.months || []),
    channelsCard(ctx, data.channels || [], mWord),
    bandsCard(ctx, data.time_bands || [], mWord),
    payeesCard(data.top_payees || [], tm, mWord));
}

function deltaText(tm, prev, prevWord) {
  if (!prev) return { cls: "same", mark: "", text: "지난달 거래가 없어서 비교할 수 없어요." };
  const diff = (tm.out_total || 0) - (prev.out_total || 0);
  if (Math.abs(diff) < 1000) return { cls: "same", mark: "", text: `${prevWord}과 비슷하게 썼어요.` };
  return diff > 0
    ? { cls: "up", mark: "▲", text: `${prevWord}보다 ${formatWon(diff)} 더 썼어요.` }
    : { cls: "down", mark: "▼", text: `${prevWord}보다 ${formatWon(-diff)} 덜 썼어요.` };
}

function summaryCard(tm, prev, mWord, prevWord) {
  const d = deltaText(tm, prev, prevWord);
  const concern = concernOf(tm);
  const speakText = [`${mWord}에 ${moneyText(tm.out_total)}이 나갔어요.`, d.text,
    concern ? `걱정되는 거래가 ${nf.format(concern)}건 있었어요.` : "걱정되는 거래는 없었어요."].join(" ");
  const speak = speakButton(speakText, { cls: "btn sm" });
  return h("section", { class: "card home-card home-summary", "aria-labelledby": "home-sum-title" },
    h("h4", { id: "home-sum-title", class: "kpi-label", text: `${mWord}에 나간 돈` }),
    h("p", { class: "kpi-value home-big", "data-nosplit": true, text: moneyText(tm.out_total) }),
    h("p", { class: `delta ${d.cls} home-delta`, "data-nosplit": true },
      d.mark ? h("span", { class: "home-mark", "aria-hidden": "true", text: d.mark }) : null, h("span", { text: d.text })),
    h("ul", { class: "home-facts" },
      fact("cash", "들어온 돈", moneyText(tm.in_total)),
      fact("list", "나간 거래", `${nf.format(tm.out_count || 0)}건`),
      concern
        ? h("li", null, h("a", { class: "home-fact concern", href: "#/alerts" },
          h("span", { class: "home-fact-icon" }, icon("bell")), h("span", { class: "home-fact-label", text: "걱정되는 거래" }),
          h("b", { class: "home-fact-value", text: `${nf.format(concern)}건` }), h("span", { class: "row-chev" }, icon("chevron"))))
        : fact("check-line", "걱정되는 거래", "없어요")),
    speak ? h("div", { class: "home-speak" }, speak) : null);
}

function fact(ic, label, value) {
  return h("li", null, h("div", { class: "home-fact" },
    h("span", { class: "home-fact-icon" }, icon(ic)), h("span", { class: "home-fact-label", text: label }),
    h("b", { class: "home-fact-value", text: value })));
}

function monthReadout(m) {
  const c = concernOf(m);
  return `${formatMonth(m.month)}에 ${moneyText(m.out_total)}이 나갔어요. `
    + (c ? `걱정되는 거래가 ${nf.format(c)}건 있었어요.` : "걱정되는 거래는 없었어요.");
}

function monthsCard(ctx, months) {
  const head = h("h4", { id: "home-months-title", text: "달마다 나간 돈" });
  if (months.length < 2) {
    return h("section", { class: "card home-card", "aria-labelledby": "home-months-title" }, head,
      h("p", { class: "muted", text: "두 달 넘게 거래가 쌓이면 달마다 비교해서 보여 드려요." }));
  }
  const flaggedMonths = months.filter((m) => concernOf(m) > 0).map((m) => formatMonth(m.month));
  const items = months.map((m) => {
    const c = concernOf(m);
    return {
      label: formatMonth(m.month), value: m.out_total || 0, valueText: shortWon(m.out_total), flag: c > 0,
      aria: `${formatMonth(m.month, true)}, ${moneyText(m.out_total)} 나감${c ? `, 걱정되는 거래 ${nf.format(c)}건` : ""}`,
    };
  });
  const summary = `달마다 나간 돈 막대그림. ${months.map((m) => `${formatMonth(m.month)} ${formatWon(m.out_total)}`).join(", ")}.`
    + (flaggedMonths.length ? ` 걱정되는 거래가 있던 달은 ${flaggedMonths.join(", ")}이에요.` : "");
  const readout = h("p", { class: "chart-readout", "aria-live": "polite", text: monthReadout(months[months.length - 1]) });
  const chart = columnChart(items, {
    label: summary, tone: "c1", emphasis: "selected", values: "auto", selected: months.length - 1,
    onSelect: (i) => setText(readout, monthReadout(months[i])), onCleanup: ctx.onCleanup,
  });
  return h("section", { class: "card home-card", "aria-labelledby": "home-months-title" }, head,
    h("p", { class: "muted", text: "막대를 누르면 그달에 나간 돈을 보여 줘요." }),
    chart.el,
    flaggedMonths.length ? h("p", { class: "chart-key", "data-nosplit": true },
      h("span", { class: "chart-key-dot", "aria-hidden": "true" }), h("span", { text: "점이 있는 달은 걱정되는 거래가 있던 달이에요." })) : null,
    readout,
    srTable("달마다 나간 돈", ["달", "나간 돈", "걱정되는 거래"],
      months.map((m) => [formatMonth(m.month, true), moneyText(m.out_total), `${nf.format(concernOf(m))}건`])));
}

function channelsCard(ctx, channels, mWord) {
  const head = h("h4", { id: "home-where-title", text: `${mWord}에 어디에 썼나요` });
  if (!channels.length) {
    return h("section", { class: "card home-card", "aria-labelledby": "home-where-title" }, head,
      h("p", { class: "muted", text: `${mWord}에는 나간 돈이 없어요.` }));
  }
  const name = (c) => CHANNEL_KO[c.channel] || c.channel;
  const cls = (c) => `c${CHANNEL_CHART[c.channel] || 5}`;
  const top = channels[0];
  const bar = ratioBar(channels.map((c) => ({ label: name(c), share: c.share, cls: cls(c) })), {
    label: `결제 방법별 나간 돈 비율. ${channels.map((c) => `${name(c)} ${percent(c.share, 0)}`).join(", ")}.`,
    onCleanup: ctx.onCleanup,
  });
  return h("section", { class: "card home-card", "aria-labelledby": "home-where-title" }, head,
    h("p", { class: "home-insight", text: `${withRo(name(top))} 가장 많이 나갔어요.` }),
    bar.el,
    h("ul", { class: "legend home-legend", "aria-label": "결제 방법별 나간 돈" }, channels.map((c) => h("li", { class: cls(c) },
      h("span", { class: "swatch", "aria-hidden": "true" }),
      h("span", { class: "grow" }, h("span", { class: "home-legend-name", text: name(c) }),
        h("span", { class: "pct", text: `${percent(c.share, 0)} · ${nf.format(c.out_count || 0)}건` })),
      h("b", { class: "home-legend-money", text: moneyText(c.out_total) })))));
}

function bandsCard(ctx, bands, mWord) {
  const head = h("h4", { id: "home-when-title", text: "언제 걱정되는 거래가 있었나요" });
  const total = bands.reduce((s, b) => s + (b.flagged || 0), 0);
  if (!bands.length || !total) {
    return h("section", { class: "card home-card", "aria-labelledby": "home-when-title" }, head,
      h("div", { class: "home-ok" }, icon("check-line"), h("p", { text: `${mWord}에는 걱정되는 거래가 없었어요.` })));
  }
  const most = Math.max(...bands.map((b) => b.flagged || 0));
  const peaks = bands.filter((b) => (b.flagged || 0) === most).map((b) => `${(BANDS[b.band] || {}).name || b.band} ${(BANDS[b.band] || {}).hours || b.hours}`);
  const items = bands.map((b) => {
    const meta = BANDS[b.band] || { name: b.band, hours: b.hours };
    return {
      label: meta.name, sub: meta.hours, value: b.flagged || 0, valueText: `${nf.format(b.flagged || 0)}건`,
      aria: `${meta.name} ${meta.hours}, 걱정되는 거래 ${nf.format(b.flagged || 0)}건`,
    };
  });
  const chart = columnChart(items, {
    label: `시간대별 걱정되는 거래 막대그림. ${items.map((it) => `${it.label} ${it.sub} ${it.valueText}`).join(", ")}.`,
    tone: "flag", emphasis: "max", values: "all", onCleanup: ctx.onCleanup,
  });
  return h("section", { class: "card home-card", "aria-labelledby": "home-when-title" }, head,
    h("p", { class: "home-insight", text: `${peaks.join(", ")}에 가장 많았어요.` }),
    chart.el,
    srTable(`${mWord} 시간대별 걱정되는 거래`, ["시간대", "걱정되는 거래", "나간 거래"],
      bands.map((b) => {
        const meta = BANDS[b.band] || { name: b.band, hours: b.hours };
        return [`${meta.name} ${meta.hours}`, `${nf.format(b.flagged || 0)}건`, `${nf.format(b.out_count || 0)}건`];
      })));
}

function payeesCard(payees, tm, mWord) {
  const head = h("h4", { id: "home-top-title", text: "많이 보낸 곳 TOP 3" });
  if (!payees.length) {
    return h("section", { class: "card home-card", "aria-labelledby": "home-top-title" }, head,
      h("p", { class: "muted", text: `${mWord}에는 계좌 이체와 카드 결제로 나간 돈이 없어요.` }));
  }
  const whole = tm.out_total || 0;
  return h("section", { class: "card home-card", "aria-labelledby": "home-top-title" }, head,
    h("p", { class: "muted", text: `${mWord}에 계좌 이체와 카드 결제로 나간 돈이에요.` }),
    h("ol", { class: "home-top" }, payees.map((p, i) => {
      const share = whole ? p.out_total / whole : 0;
      return h("li", { class: "home-top-item" },
        h("span", { class: "home-rank", "aria-hidden": "true", text: String(i + 1) }),
        h("div", { class: "home-top-main" },
          h("div", { class: "home-top-line" },
            h("b", { class: "home-top-name" }, h("span", { class: "sr-only", text: `${i + 1}위, ` }), h("span", { text: p.name || "이름 없음" })),
            h("b", { class: "home-top-money", text: moneyText(p.out_total) })),
          h("div", { class: "hbar-track c1", "aria-hidden": "true" }, h("i", { style: `width:${Math.max(2, Math.round(share * 100))}%` })),
          h("p", { class: "home-top-sub", "data-nosplit": true },
            h("span", { text: `${nf.format(p.out_count || 0)}번 · 나간 돈의 ${percent(share, 0)}` }),
            p.flagged ? h("span", { class: "badge caution" }, icon("warning"), h("span", { text: `걱정되는 거래 ${nf.format(p.flagged)}건` })) : null)));
    })));
}

// ---- 바로가기 ---------------------------------------------------------------------
function quickLinks() {
  return h("section", { class: "home-quick", "aria-labelledby": "home-quick-title" },
    h("h3", { id: "home-quick-title", class: "section-title", text: "바로가기" }),
    h("div", { class: "quick" },
      quick("upload", "거래 불러오기", "파일·연결", "#/txns"),
      quick("send", "알림 보내기", "문자·메일로", "#/send"),
      quick("users", "조력자", "알릴 사람", "#/more/helpers"),
      quick("building", "상담하는 곳", "도움받을 곳", "#/more/counselors")));
}

function quick(ic, title, sub, href) {
  return h("a", { class: "quick-item", href }, h("span", { class: "qi-icon" }, icon(ic)), h("b", { text: title }), h("span", { text: sub }));
}
