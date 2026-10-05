/* 내 거래: 요약(저장된 거래·기간·등급 비율), 거래 불러오기(은행·카드·휴대폰 결제 연결은 준비 중, 파일 올리기, 연습용 거래),
 * 찾기(이름 검색·기간)와 걸러 보기(전체·걱정되는 것·꼭 확인할 것·담은 거래), 날짜별 목록,
 * 거래 시트(왜 걱정되나요·알림 목록에 담기·내가 한 거예요·조력자·상담하는 곳에 알리기·확인 기록 지우기).
 * 주소 뒤 open=upload|sample|bank|card|phone이면 그 시트를 바로 연다(views/connect.js·홈 바로가기가 보냄).
 * 주소 뒤 q=이름·period=1m|3m이면 그대로 걸러 본다(홈 많이 보낸 곳 TOP 3가 보냄, J9·AUG-09).
 *
 * 목록 읽기
 *  - 찾기가 없으면 서버에서 50건씩 읽는다(/api/transactions?level&limit&offset).
 *  - 이름·기간으로 찾을 때는 전체 거래(level=all, limit=0)를 한 번 읽어 이 화면에서 거르고 50건씩 보인다.
 *    걸러 보기 칩의 수도 찾은 거래 안에서 센다. 담기·내가 한 거예요·지우기·불러오기 뒤에는 다시 읽는다.
 *  - 더 보기가 실패해도 이미 보인 거래는 그대로 두고, 그 자리에 오류와 다시 불러오기만 보인다(FE-01).
 *  - 거래 살펴보기가 꺼져 있으면 목록을 부르지 않고 알림 탭과 같은 안내를 보인다(C15).
 */
import { h, icon, fill, openSheet, confirmSheet, busy, toast, announce, skeleton, emptyState, soonBadge, SOON_TEXT } from "../ui.js";
import { nf, formatWhen, dayKey, parseTs, deviceWord, sentence, keepUnits, moneyText } from "../format.js";
import {
  txnRow, dateHead, levelBadge, flagBadge, reviewBadge, notifiedBadge, checkedBadge, txnSignals, txnDetailHead,
  flagButton, reviewButton, aiExplain, errorNotice, speakButton,
} from "../components.js";
import { PERSONAS, CHANNEL_KO, LEVEL, REVIEW_TEXT } from "../labels.js";
import { STALE, UPLOAD_PATH, MAX_UPLOAD_BYTES, isConsentError } from "../api.js";
import * as apiModule from "../api.js";
import { openBankConnect, openCardConnect, openPhonePayConnect } from "./connect.js";

const PAGE = 50;
// 연습용 거래 기본 번호: 파이썬 api/constants.py DEFAULT_SAMPLE_SEED와 같게(AI만 먼저 찾은 거래가 있는 조합, J3)
const SAMPLE_SEED = 10;
// 이어 붙여 올리기(AUG-03)는 api.js가 file.mode를 서버에 넘길 때만 고를 수 있게 한다(넘기지 못하면 모두 바뀌므로)
const CAN_APPEND = Array.isArray(apiModule.UPLOAD_MODES) && apiModule.UPLOAD_MODES.includes("append");

const FILTERS = [
  { value: "all", label: "전체" },
  { value: "caution", label: "걱정되는 것" },
  { value: "high", label: "꼭 확인할 것" },
  { value: "flagged", label: "담은 거래" },
];
// 기간: 저장된 마지막 거래 날부터 거꾸로 센다(연습용 거래는 지난 날짜라서). 보이는 날짜 범위를 늘 함께 적는다
const PERIODS = [
  { value: "all", label: "전체", aria: "전체 기간", months: 0 },
  { value: "1m", label: "1개월", aria: "최근 1개월", months: 1 },
  { value: "3m", label: "3개월", aria: "최근 3개월", months: 3 },
];
// 고른 보기에 거래가 없을 때
const EMPTY = {
  all: ["저장된 거래가 없어요", "위의 거래 불러오기에서 시작해 보세요."],
  caution: ["걱정되는 거래가 없어요", "다른 보기를 골라 보세요."],
  high: ["꼭 확인할 거래가 없어요", "다른 보기를 골라 보세요."],
  flagged: ["담은 거래가 없어요", "거래를 누르면 알림 목록에 담을 수 있어요."],
};
const EMPTY_FOUND = ["찾는 거래가 없어요", "이름이나 기간을 바꿔 보세요."];

// 거래 시트의 쉬운 설명 한 줄(신호 이름은 labels.js의 명사형, 여기는 무슨 일이 있었는지)
const SIGNAL_EASY = {
  night_repeat_transfer: "밤늦게 돈을 여러 번 보냈어요.",
  payee_surge: "한 사람에게 돈을 자주 보냈어요.",
  micropay_surge: "휴대폰으로 결제를 많이 했어요.",
  new_merchant_high_value: "처음 간 가게에 큰 돈을 냈어요.",
  multi_line_telecom: "휴대폰 요금이 여러 개 나왔어요.",
};
// 이력이 짧아 처음인지 알 수 없을 때(labels.SIGNAL_KO_NEUTRAL과 맞춤)
const SIGNAL_EASY_NEUTRAL = { new_merchant_high_value: "가게에 큰 돈을 냈어요." };

// 파일 올리기: 지금 읽을 수 있는 파일과 정식 버전에서 열 파일(AUG-02: 엑셀은 첫 시트를 읽는다. .xls는 옛 엑셀(BIFF8)과
// 은행·카드사가 내려주는 확장자만 .xls인 HTML 표를 모두 읽는다: safepause/data/xls.py·htmltable.py, 2026-10-03)
const EXT_NOW = [".csv", ".txt", ".xls", ".xlsx"];
const EXT_SOON = [".pdf", ".jpg", ".png"];
const EXT_OK = new Set(["csv", "txt", "tsv", "xls", "xlsx"]);
const ACCEPT = [".csv", ".txt", ".xls", ".xlsx", "text/csv", "text/plain", "text/comma-separated-values", "text/tab-separated-values",
  "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"].join(",");

function easyLine(item, code) {
  const r = (item.reasons || []).find((x) => x.code === code);
  if (r && r.detail && r.detail.newness_unknown && SIGNAL_EASY_NEUTRAL[code]) return SIGNAL_EASY_NEUTRAL[code];
  return SIGNAL_EASY[code] || "";
}

/**
 * 왜 걱정되나요(components.aiExplain) + 약속(규칙) 신호마다 쉬운 설명 한 줄(설계서 6.2: 명사형 + 쉬운 말 한 줄).
 * aiExplain의 신호 목록(li) 순서는 txnSignals(규칙)와 같다. 모양이 다르면 설명 없이 그대로 둔다.
 */
function whyBlock(item) {
  const section = aiExplain(item);
  const rules = txnSignals(item).filter((s) => s.code !== "anomaly");
  const lis = Array.from(section.querySelectorAll(".ae-list > li"));
  if (lis.length !== rules.length) return section;
  rules.forEach((s, i) => {
    const easy = easyLine(item, s.code);
    const label = lis[i].querySelector(":scope > span");
    if (!easy || !label) return;
    lis[i].classList.add("tx-ae-li");
    const main = h("span", { class: "tx-ae-main" });
    label.replaceWith(main);
    main.append(label, h("p", { class: "muted tx-ae-easy", text: easy }));
  });
  return section;
}

/** "2026년 3월 2일 ~ 6월 29일"(해가 바뀌면 뒤에도 해를 쓴다). 날짜(Date)나 시각 글을 받는다. */
function periodText(first, last) {
  const a = first instanceof Date ? first : parseTs(first);
  const b = last instanceof Date ? last : parseTs(last);
  if (!a || !b) return "";
  const day = (d, withYear) => (withYear ? `${d.getFullYear()}년 ` : "") + `${d.getMonth() + 1}월 ${d.getDate()}일`;
  if (a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()) return day(a, true);
  return `${day(a, true)} ~ ${day(b, a.getFullYear() !== b.getFullYear())}`;
}

/** 마지막 거래 날 기준 최근 n개월의 첫날(0시). 3월 31일의 1개월 전은 3월 1일부터(2월 28일 다음 날). */
function periodStart(lastTs, months) {
  const last = parseTs(lastTs);
  if (!last || !months) return null;
  const y = last.getFullYear();
  const m = last.getMonth() - months;
  const dim = new Date(y, m + 1, 0).getDate();
  return new Date(y, m, Math.min(last.getDate(), dim) + 1);
}

/** 이름 비교: 빈칸을 빼고 소문자로("김 호"도 "김호"를 찾게). */
function norm(text) {
  return String(text || "").toLowerCase().replace(/\s+/g, "");
}

/** 요약 카드 맨 아래 한 줄: AI가 몇 건으로 배웠는지(자세한 숫자는 AI와 데이터 설명·성능 확인 화면) */
function modelText(model) {
  if (!model || !model.fitted) return "거래가 30건보다 적어서 AI 없이 약속(규칙)으로만 살펴봐요.";
  const rows = Number.isInteger(model.train_rows) && model.train_rows > 0 ? model.train_rows : model.train_count;
  return `AI가 거래 ${nf.format(rows)}건을 보고 내 평소 모습을 배웠어요.`;
}

/** 불러온 뒤 한 줄 요약(AUG-07·J3): 꼭 확인할 거래·확인할 거래 수와 AI만 찾은 거래 수. levels가 없으면 빈 목록. */
function levelLines(r, prefix = "") {
  const lv = r && r.levels;
  if (!lv) return [];
  const high = lv.high || 0;
  const caution = lv.caution || 0;
  const found = [high ? `꼭 확인할 거래 ${nf.format(high)}건` : "", caution ? `확인할 거래 ${nf.format(caution)}건` : ""].filter(Boolean);
  const lines = [found.length ? `${prefix}${found.join(", ")}이 있어요.` : `${prefix}걱정되는 거래는 없어요.`];
  if (Number.isInteger(r.ai_only) && r.ai_only > 0) lines.push(`그 가운데 AI만 찾은 거래가 ${nf.format(r.ai_only)}건이에요.`);
  return lines;
}

function fileExt(name) {
  const m = /\.([A-Za-z0-9]{1,6})$/.exec(String(name || ""));
  return m ? m[1].toLowerCase() : "";
}

function sizeText(bytes) {
  if (bytes < 1024) return `${nf.format(bytes)}B`;
  if (bytes < 1024 * 1024) return `${nf.format(Math.round(bytes / 1024))}KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}

export default {
  title: "내 거래",
  tab: "txns",
  async render(ctx) {
    const { main, go } = ctx;
    const summarySlot = h("div", null, skeleton(1));
    const statusSlot = h("div", { role: "status" });
    const listSlot = h("div", { class: "list tx-list", id: "txns-list", "aria-label": "거래 목록" });
    const moreStatus = h("div", { class: "tx-more-status" });   // 더 보기가 실패했을 때 오류·다시 불러오기(FE-01)
    const moreBtn = h("button", { type: "button", class: "btn block tx-more", hidden: true });
    const rowsById = new Map();   // 거래 id → 목록 줄(담기 뒤 그 줄만 다시 그림)
    const counts = { all: null, caution: null, high: null, flagged: null };
    let filter = "all";
    let period = PERIODS.some((p) => p.value === ctx.params.get("period")) ? ctx.params.get("period") : "all";
    let query = (ctx.params.get("q") || "").slice(0, 40);
    let offset = 0;
    let lastKey = "";
    let loadSeq = 0;
    let stored = null;      // /api/data/summary
    let levels = null;      // /api/transactions의 summary·model
    let reviewedCount = 0;  // 내가 한 거예요로 표시한 거래 수
    let monitoring = null;  // 거래 살펴보기 동의(null: 아직 모름)
    let fullCache = null;   // 찾기용 전체 거래(level=all, limit=0)
    const searching = () => Boolean(norm(query)) || period !== "all";

    // ---- 찾기: 이름 검색 + 기간 ----
    const searchInput = h("input", {
      class: "input tx-search-input", id: "txns-q", type: "search", enterkeyhint: "search", autocomplete: "off",
      spellcheck: "false", autocorrect: "off", autocapitalize: "off", maxlength: "40", value: query,
      placeholder: "이름 검색", "aria-controls": "txns-list",
    });
    const clearBtn = h("button", {
      type: "button", class: "icon-btn tx-search-clear", "aria-label": "찾는 이름 지우기", hidden: !query,
      onclick: () => { searchInput.value = ""; setQuery("", true); searchInput.focus(); },
    }, icon("close"));
    let typing = 0;
    searchInput.addEventListener("input", () => {
      clearBtn.hidden = !searchInput.value;
      window.clearTimeout(typing);
      typing = window.setTimeout(() => setQuery(searchInput.value, true), 350);
    });
    searchInput.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      window.clearTimeout(typing);
      setQuery(searchInput.value, true);
    });
    ctx.onCleanup(() => window.clearTimeout(typing));
    const searchBox = h("div", { class: "tx-search", role: "search" },
      h("label", { class: "field-label", for: "txns-q", text: "받는 사람·가게 이름으로 찾기" }),
      h("div", { class: "tx-search-row" }, searchInput, clearBtn));

    function setQuery(value, speak = false) {
      const next = String(value || "").slice(0, 40);
      if (next.trim() === query.trim()) return;
      query = next;
      clearBtn.hidden = !query;
      syncParams();
      loadList(true, speak);
    }

    function syncParams() {
      ctx.replaceParams({ q: query.trim() || null, period: period === "all" ? null : period });
    }

    const periodEls = PERIODS.map((p) => h("button", {
      type: "button", class: "chip", "aria-pressed": p.value === period ? "true" : "false", "data-period": p.value,
      "aria-controls": "txns-list", "aria-label": p.aria, text: p.label,
      onclick: () => {
        if (p.value === period) return;
        period = p.value;
        for (const b of periodEls) b.setAttribute("aria-pressed", b.dataset.period === period ? "true" : "false");
        syncParams();
        loadList(true, true);
      },
    }));
    const periodBox = h("div", { class: "tx-period" },
      h("span", { class: "field-label", id: "txns-period-label", text: "기간" }),
      h("div", { class: "chips tx-period-chips", role: "group", "aria-labelledby": "txns-period-label" }, periodEls));

    // ---- 걸러 보기 칩 ----
    const chipEls = FILTERS.map((f) => {
      const count = h("span", { class: "chip-count", hidden: true });
      const btn = h("button", {
        type: "button", class: "chip", "aria-pressed": f.value === filter ? "true" : "false", "data-v": f.value,
        "aria-controls": "txns-list", onclick: () => choose(f.value),
      }, h("span", { text: f.label }), count);
      return { f, btn, count };
    });
    const chips = h("div", { class: "chips tx-chips", role: "group", "aria-label": "거래 걸러 보기" }, chipEls.map((c) => c.btn));
    const filterNote = h("div", { class: "tx-filter-note", hidden: true });
    // 찾기(이름·기간)는 카드 하나로 묶고, 걸러 보기 칩은 그 아래에 둔다(두 칩 묶음이 섞여 보이지 않게)
    const finder = h("div", { class: "tx-finder" },
      h("section", { class: "card tx-find-card", "aria-label": "거래 찾기" }, searchBox, periodBox), chips, filterNote);

    function paintChips() {
      for (const { f, btn, count } of chipEls) {
        const n = counts[f.value];
        count.hidden = n === null;
        count.textContent = n === null ? "" : nf.format(n);
        btn.setAttribute("aria-label", n === null ? f.label : `${f.label} ${nf.format(n)}건`);
        btn.setAttribute("aria-pressed", f.value === filter ? "true" : "false");
      }
    }

    function choose(v) {
      if (v === filter) return;
      filter = v;
      paintChips();
      loadList(true, true);
    }

    function resetFind() {
      window.clearTimeout(typing);
      query = "";
      searchInput.value = "";
      clearBtn.hidden = true;
      period = "all";
      for (const b of periodEls) b.setAttribute("aria-pressed", b.dataset.period === "all" ? "true" : "false");
      filter = "all";   // 모두 보기: 걸러 보기도 전체로
      paintChips();
      syncParams();
      loadList(true, true);
      searchInput.focus();   // 누른 버튼이 사라지므로 찾는 칸으로
    }

    /** 찾는 중이면 무엇으로 걸렀는지·몇 건인지 한 줄씩 + 모두 보기. */
    function paintFilterNote(d) {
      if (!searching() || !d.count) { filterNote.hidden = true; filterNote.replaceChildren(); return; }
      const lines = [];
      if (d.range) lines.push(`${keepUnits(periodText(d.range.start, d.range.end))} 거래만 보여요.`);
      if (norm(query)) lines.push(`이름에 ${query.trim()} 글자가 든 거래만 보여요.`);
      lines.push(`모두 ${nf.format(d.matched)}건이에요.`);
      fill(filterNote, h("p", { text: lines.join(" ") }),
        h("button", { type: "button", class: "btn sm weak tx-find-reset", onclick: resetFind }, icon("refresh"), h("span", { text: "모두 보기" })));
      filterNote.hidden = false;
    }

    // ---- 거래 불러오기: 은행·카드·휴대폰 결제 연결(준비 중), 파일 올리기, 연습용 거래 ----
    const connectOpts = { onUpload: openUpload, onSample: openSample };
    const tile = ({ ic, title, sub, soon, onclick, wide }) => h("button", { type: "button", class: `tx-tile${wide ? " wide" : ""}`, onclick },
      h("span", { class: "tx-tile-icon", "aria-hidden": "true" }, icon(ic)),
      h("span", { class: "tx-tile-text" },
        h("span", { class: "tx-tile-title", text: title }),
        soon ? h("span", { class: "tx-tile-sub" }, soonBadge()) : h("span", { class: "tx-tile-sub", text: sub })));
    const importGrid = h("div", { class: "tx-import" },
      tile({ ic: "bank", title: "은행 거래내역 불러오기", soon: true, onclick: () => openBankConnect(ctx, connectOpts) }),
      tile({ ic: "card", title: "카드 결제내역 불러오기", soon: true, onclick: () => openCardConnect(ctx, connectOpts) }),
      tile({ ic: "sig-phone-pay", title: "휴대폰 결제내역 불러오기", soon: true, onclick: () => openPhonePayConnect(ctx, connectOpts) }),
      tile({ ic: "upload", title: "파일 올리기", sub: EXT_NOW.join(" "), onclick: openUpload }),
      tile({ ic: "sparkle", title: "연습용 거래 불러오기", sub: "가상의 거래로 미리 살펴봐요", onclick: openSample, wide: true }));

    const listTitle = h("h3", { class: "section-title", tabindex: "-1", text: "거래 목록" });
    fill(main,
      h("h2", { class: "page-title", tabindex: "-1", text: "내 거래" }),
      summarySlot,
      h("h3", { class: "section-title", text: "거래 불러오기" }),
      importGrid,
      listTitle, finder, statusSlot, listSlot, moreStatus, moreBtn);
    moreBtn.addEventListener("click", () => loadList(false));

    // ---- 요약 카드: 저장된 거래 N건, 기간, 등급 비율(뱅크샐러드 톤) ----
    function paintSummary() {
      if (!stored) return;
      if (!stored.count) {
        fill(summarySlot, h("section", { class: "card tx-summary", "aria-label": "저장된 거래 요약" },
          h("div", { class: "kpi" },
            h("span", { class: "kpi-label", text: "저장된 거래" }),
            h("b", { class: "kpi-value", text: "0건" })),
          h("p", { class: "tx-period", text: "거래를 불러오면 여기에 모아서 보여 줘요." })));
        return;
      }
      const parts = [];
      if (levels && monitoring !== false) {
        const s = levels.summary;
        const rows = ["none", "caution", "high"].map((lv) => ({ lv, n: s[lv] || 0 }));
        parts.push(
          h("div", { class: "stack tx-levels", "aria-hidden": "true" },
            rows.filter((r) => r.n > 0).map((r) => h("i", { class: `lv-${r.lv}`, style: `flex:${r.n}` }))),
          h("ul", { class: "legend tx-legend", "aria-label": "등급별 거래 수" }, rows.map((r) => h("li", { class: `lv-${r.lv}` },
            h("span", { class: "swatch", "aria-hidden": "true" }),
            h("span", { class: "grow", text: LEVEL[r.lv].text }),
            h("b", { text: `${nf.format(r.n)}건` })))),
          reviewedCount ? h("p", { class: "tx-reviewed", text: `내가 한 거래로 표시한 거래가 ${nf.format(reviewedCount)}건 있어요.` }) : null,
          h("div", { class: "tx-model" }, icon("sparkle"), h("p", { text: modelText(levels.model) })));
      }
      fill(summarySlot, h("section", { class: "card tx-summary", "aria-label": "저장된 거래 요약" },
        h("div", { class: "kpi" },
          h("span", { class: "kpi-label", text: "저장된 거래" }),
          h("b", { class: "kpi-value", text: `${nf.format(stored.count)}건` })),
        h("p", { class: "tx-period", "data-nosplit": true, text: keepUnits(periodText(stored.first_ts, stored.last_ts)) }),
        parts));
    }

    async function loadSummary() {
      try {
        stored = await ctx.req("GET", "/api/data/summary");
        paintSummary();
        return stored;
      } catch (e) {
        if (e !== STALE) fill(summarySlot, errorNotice(e, go));
        return null;
      }
    }

    // ---- 거래 살펴보기가 꺼져 있을 때(알림 탭과 같은 안내, C15) ----
    function showConsentOff() {
      monitoring = false;
      finder.hidden = true;
      listTitle.hidden = false;
      moreBtn.hidden = true;
      moreStatus.replaceChildren();
      listSlot.replaceChildren();
      listSlot.hidden = true;
      counts.all = counts.caution = counts.high = counts.flagged = null;
      paintChips();
      paintSummary();
      fill(statusSlot, h("div", { class: "empty tx-off" }, icon("toggle"),
        h("b", { text: "거래 살펴보기가 꺼져 있어요" }),
        h("p", { text: "거래 살펴보기를 켜면 거래 목록을 볼 수 있어요." }),
        h("button", { type: "button", class: "btn weak", onclick: () => go("more/consent") }, icon("toggle"), h("span", { text: "동의 켜러 가기" }))));
    }

    async function checkConsent() {
      try {
        const c = await ctx.req("GET", "/api/consent");
        ctx.session.consent = c;
        monitoring = Boolean(c.monitoring);
      } catch (e) {
        if (e === STALE) throw e;
        monitoring = null;   // 모르면 목록을 불러 보고, 동의 오류면 그때 안내한다
      }
      return monitoring;
    }

    // ---- 목록 ----
    function addRow(item) {
      const key = dayKey(item.txn.ts);
      if (key !== lastKey) { listSlot.append(dateHead(item.txn.ts)); lastKey = key; }
      const row = txnRow(item, openDetail);
      rowsById.set(item.txn.id, row);
      listSlot.append(row);
      return row;
    }

    /** 찾기용: 전체 거래를 한 번 읽어 이 화면에서 거른다. 응답 모양은 /api/transactions와 같고 range·localCounts를 더한다. */
    async function findPage(off) {
      if (!fullCache) fullCache = await ctx.req("GET", "/api/transactions?level=all&limit=0");
      const d = fullCache;
      const items = d.items || [];
      const p = PERIODS.find((x) => x.value === period) || PERIODS[0];
      const lastTs = items.length ? items[0].txn.ts : "";   // 최근 거래부터
      const start = periodStart(lastTs, p.months);
      const q = norm(query);
      const base = items.filter((it) => (!q || norm(it.txn.counterparty).includes(q))
        && (!start || (parseTs(it.txn.ts) || 0) >= start));
      const by = {
        all: base,
        caution: base.filter((it) => it.level === "caution" || it.level === "high"),
        high: base.filter((it) => it.level === "high"),
        flagged: base.filter((it) => it.flagged),
      };
      const pick = by[filter] || base;
      return {
        ...d, matched: pick.length, items: pick.slice(off, off + PAGE),
        range: start ? { start, end: parseTs(lastTs) } : null,
        localCounts: { all: by.all.length, caution: by.caution.length, high: by.high.length, flagged: by.flagged.length },
      };
    }

    async function loadList(reset, speak = false) {
      const seq = ++loadSeq;   // 보기를 빨리 바꾸면 늦게 온 옛 응답을 버린다(리뷰 M3)
      const active = document.activeElement;
      const moreFocused = active === moreBtn || Boolean(active && moreStatus.contains(active));
      if (monitoring === false) { showConsentOff(); return; }
      if (reset) {
        offset = 0; lastKey = ""; rowsById.clear();
        listSlot.hidden = false;
        listSlot.setAttribute("aria-busy", "true");
        listSlot.replaceChildren(skeleton(3));
        moreBtn.hidden = true;
      }
      moreStatus.replaceChildren();
      try {
        const d = searching()
          ? await findPage(offset)
          : await ctx.req("GET", `/api/transactions?level=${filter}&limit=${PAGE}&offset=${offset}`);
        if (seq !== loadSeq) return;
        // 성공하면 보기·오류 상태를 늘 되돌린다(더 보기 실패 뒤 다시 불러오기도, FE-01)
        listSlot.hidden = false;
        statusSlot.replaceChildren();
        if (reset) {
          listSlot.replaceChildren();
          const s = d.summary || {};
          if (d.localCounts) Object.assign(counts, d.localCounts);
          else {
            counts.all = d.count;
            counts.caution = (s.caution || 0) + (s.high || 0);
            counts.high = s.high || 0;
            counts.flagged = d.flagged_count || 0;
          }
          paintChips();
          levels = { summary: s, model: d.model };
          reviewedCount = d.reviewed_count || 0;
          monitoring = true;
          paintSummary();
          // 거래가 하나도 없으면 찾기·걸러 보기를 숨기고 빈 안내만
          finder.hidden = !d.count;
          listTitle.hidden = !d.count;
          paintFilterNote(d);
          if (!d.items.length) {
            const [title, text] = !d.count ? EMPTY.all : searching() ? EMPTY_FOUND : EMPTY[filter];
            listSlot.append(emptyState(filter === "flagged" ? "bookmark" : "list", title, text));
          }
          if (speak) announce(d.matched ? `${nf.format(d.matched)}건이 있어요.` : (searching() ? EMPTY_FOUND[0] : EMPTY[filter][0]));
        }
        let firstNew = null;
        for (const item of d.items) {
          const row = addRow(item);
          if (!firstNew) firstNew = row;
        }
        offset += d.items.length;
        const left = d.matched - offset;
        moreBtn.hidden = left <= 0;
        moreBtn.textContent = `더 보기 (${nf.format(Math.max(left, 0))}건 남음)`;
        // 더 보기(또는 다시 불러오기)에 초점이 있었는데 그 버튼이 사라졌으면 새로 보인 첫 거래로 옮긴다
        if (!reset && moreFocused && (moreBtn.hidden || !document.activeElement || document.activeElement === document.body) && firstNew) firstNew.focus();
      } catch (e) {
        if (e === STALE || seq !== loadSeq) return;
        if (isConsentError(e)) { showConsentOff(); return; }
        const retry = h("button", { type: "button", class: "btn block tx-retry", onclick: () => loadList(reset) },
          icon("refresh"), h("span", { text: "다시 불러오기" }));
        if (!reset) {
          // 더 보기만 실패: 이미 보인 거래는 그대로 두고 그 아래에 오류와 다시 불러오기(FE-01)
          moreBtn.hidden = true;
          fill(moreStatus, errorNotice(e, go), retry);
          if (moreFocused) retry.focus();
          return;
        }
        listSlot.replaceChildren();
        listSlot.hidden = true;
        moreBtn.hidden = true;
        fill(statusSlot, errorNotice(e, go), retry);
      } finally {
        if (seq === loadSeq) listSlot.removeAttribute("aria-busy");
      }
    }

    /** 담기·내가 한 거예요·지우기·불러오기처럼 거래 상태가 바뀐 뒤: 찾기용 전체 목록을 버린다(다음에 다시 읽음). */
    function changedData() {
      fullCache = null;
    }

    // ---- 거래 시트: 상대·시각·방법·금액(한 번, components.txnDetailHead), 왜 걱정되나요, 담기·내가 한 거예요·알리기·확인 기록 지우기 ----
    /** 목록의 그 줄만 다시 그린다(배지). 그 줄에 초점이 있었으면 새 줄로 옮긴다. */
    function repaintRow(item) {
      const old = rowsById.get(item.txn.id);
      if (!old || !old.isConnected) return null;
      const hadFocus = document.activeElement === old;
      const fresh = txnRow(item, openDetail);
      old.replaceWith(fresh);
      rowsById.set(item.txn.id, fresh);
      if (hadFocus) fresh.focus();
      return fresh;
    }

    function openDetail(item) {
      const t = item.txn;
      const out = t.direction === "out";
      const concern = Boolean(item.level && item.level !== "none");
      let sheetOpen = true;
      let changed = false;
      let flagRemoved = false;   // 담은 거래 보기에서 담기를 취소함(닫은 뒤 목록을 다시 읽음)
      // 이름 옆 배지(등급·담음·내가 확인함·알렸어요·보내기 전 확인): 바꾸면 배지만 다시 그린다(제목의 초점은 그대로)
      const badges = h("span", { class: "tx-badges" });
      const paintHead = () => fill(badges, levelBadge(item.level), flagBadge(item), reviewBadge(item), notifiedBadge(item),
        item.practice ? checkedBadge() : null);
      paintHead();

      /** 담기·내가 한 거예요 응답 뒤: 시트가 닫혀 있어도 목록 줄을 바로 고친다(FE-10). */
      function afterToggle() {
        changed = true;
        changedData();
        paintHead();
        if (filter === "flagged" && !item.flagged) flagRemoved = true;
        if (sheetOpen) { repaintRow(item); return; }
        // 응답 전에 시트를 닫았음: 그 줄만 고치거나(담은 거래 보기에서 뺐으면) 목록을 다시 읽는다
        if (!ctx.alive()) return;
        if (flagRemoved) { loadList(true); return; }
        repaintRow(item);
      }

      const flag = flagButton(ctx, item, {
        cls: `btn${item.flagged ? "" : " primary"} big block`,
        onChange: (on, count) => {
          flag.classList.toggle("primary", !on);
          if (!searching()) counts.flagged = Number.isInteger(count) ? count : Math.max(0, (counts.flagged || 0) + (on ? 1 : -1));
          else counts.flagged = Math.max(0, (counts.flagged || 0) + (on ? 1 : -1));
          paintChips();
          afterToggle();
        },
      });
      // 내가 한 거예요(J1·AUG-01): 걱정되는 거래(또는 이미 표시한 거래)에만. 등급은 그대로, 걱정되는 거래 수에서만 뺀다
      const reviewNote = h("p", { class: "hint tx-review-note", text: REVIEW_TEXT.note, hidden: !item.reviewed });
      const review = concern || item.reviewed ? reviewButton(ctx, item, {
        cls: "btn weak big block",
        onChange: (on) => {
          reviewNote.hidden = !on;
          reviewedCount = Math.max(0, reviewedCount + (on ? 1 : -1));
          paintSummary();
          afterToggle();
        },
      }) : null;
      // 보내기 전 확인으로 적은 기록(live id)만 지울 수 있다(수정 계획 1-A, POST /api/transactions/remove-checked)
      const removeChecked = (close) => h("button", {
        type: "button", class: "btn danger-weak big block tx-remove-checked",
        onclick: (e) => busy(e.currentTarget, async () => {
          const ok = await confirmSheet({
            title: "이 확인 기록을 지울까요?",
            lines: ["보내기 전 확인으로 내 거래에 적은 기록만 지워요."],
            confirmText: "지울래요", cancelText: "아니요", danger: true,
          });
          if (!ok || !ctx.alive()) return;
          try {
            await ctx.req("POST", "/api/transactions/remove-checked", { txn_id: t.id });
          } catch (e2) {
            if (e2 !== STALE) toast(e2 && e2.message ? e2.message : "지우지 못했어요. 다시 해 주세요.", "error");
            return;
          }
          changed = false;   // 목록을 통째로 다시 읽는다
          close();
          toast("확인 기록을 지웠어요.");
          changedData();
          await loadSummary();
          await loadList(true);
          if (ctx.alive()) window.requestAnimationFrame(() => { if (listTitle.isConnected && !listTitle.hidden) listTitle.focus(); });
        }),
      }, icon("trash"), h("span", { text: "이 확인 기록 지우기" }));

      // 거래 시트도 소리로 듣는다(AUG-08): 누구·언제·어떻게·얼마, 등급과 걸린 약속, AI가 본 점(음성이 없으면 버튼 없음)
      const speakText = () => {
        const lines = [t.counterparty || "이름 없음", formatWhen(t.ts), CHANNEL_KO[t.channel] || "",
          `${out ? "나간 돈" : "들어온 돈"} ${moneyText(t.amount)}`];
        if (concern) {
          lines.push((LEVEL[item.level] || {}).text || "", ...txnSignals(item).map((sg) => sg.text));
          if (item.ai && item.ai.top_feature) lines.push(item.ai.top_feature);
        }
        if (item.reviewed) lines.push(REVIEW_TEXT.badge);
        return lines.filter(Boolean).map(sentence).join(" ");
      };
      openSheet((close) => [
        txnDetailHead(item, badges),
        // 왜 걱정되나요: 약속(규칙)으로 본 것 + AI가 본 것(J2). 괜찮은 거래에는 두지 않는다
        concern ? whyBlock(item) : null,
        concern && item.ai ? h("button", {
          type: "button", class: "btn sm ghost tx-ai-link", onclick: () => { close(); go("more/about"); },
        }, icon("help"), h("span", { text: "AI는 어떻게 살펴보나요?" })) : null,
        h("div", { class: "sheet-actions" },
          speakButton(speakText, { cls: "btn weak big block tx-speak" }),
          flag,
          review,
          review ? reviewNote : null,
          h("button", {
            type: "button", class: "btn weak big block",
            onclick: () => { close(); go(`send?txn=${encodeURIComponent(t.id)}`); },
          }, icon("send"), h("span", { text: "조력자·상담하는 곳에 알리기" })),
          item.practice ? removeChecked(close) : null,
          h("button", { type: "button", class: "btn big block", text: "닫기", onclick: () => close() })),
      ], {
        label: "거래 자세히",
        className: "tx-sheet",
        onClose: () => {
          sheetOpen = false;
          if (!changed || !ctx.alive()) return;
          // 담은 거래 보기에서 뺐으면 목록을 다시 읽고, 아니면 바꿔 그린 그 줄로 초점을 돌려준다
          if (flagRemoved) {
            loadList(true);
            const activeChip = chipEls.find((c) => c.f.value === filter);
            if (activeChip) window.requestAnimationFrame(() => activeChip.btn.focus());
            return;
          }
          const fresh = rowsById.get(t.id);
          if (fresh && fresh.isConnected) window.requestAnimationFrame(() => { if (fresh.isConnected) fresh.focus(); });
        },
      });
    }

    // ---- 거래를 바꾸기 전 확인(리뷰 M8). 건수를 못 읽으면 건너뛰지 않고 바뀔 수 있다고 묻는다(2차 검증) ----
    async function storedCount() {
      try {
        return (await ctx.req("GET", "/api/data/summary")).count;
      } catch (e) {
        if (e === STALE) throw e;
        return null;
      }
    }
    function clearsText() {
      return [counts.flagged ? "알림 목록에 담은 거래도 비워져요." : "",
        reviewedCount ? "내가 한 거래로 표시한 것도 비워져요." : ""].filter(Boolean).join(" ");
    }
    async function confirmReplace(count) {
      if (count === 0) return true;
      return confirmSheet({
        title: "지금 거래가 바뀌어요",
        // 한 문단에 넣으면 문장마다 한 줄로 나뉜다(줄 사이가 벌어지지 않게)
        lines: [[
          count === null ? "저장된 거래가 있으면 지워지고 새 거래로 바뀌어요." : `저장된 거래 ${nf.format(count)}건은 지워지고 새 거래로 바뀌어요.`,
          clearsText(),
          "계속할까요?",
        ].filter(Boolean).join(" ")],
        confirmText: "네, 바꿀래요", cancelText: "아니요",
      });
    }

    /**
     * 파일을 어떻게 넣을지 고른다(AUG-03): 이어 붙이기(같은 거래는 한 번만, 담은 거래·내가 확인한 표시 그대로) / 모두 바꾸기.
     * 저장된 거래가 없으면 묻지 않고 바꾸기. 돌려주는 값: "append" | "replace" | null(그만두기).
     */
    function chooseUploadMode(count) {
      if (count === 0) return Promise.resolve("replace");
      if (!CAN_APPEND) return confirmReplace(count).then((ok) => (ok ? "replace" : null));
      return new Promise((resolve) => {
        let result = null;
        const pickBtn = (mode, text, cls) => h("button", {
          type: "button", class: `btn big block ${cls}`.trim(), text, "data-mode": mode,
          onclick: () => { result = mode; closeIt(); },
        });
        let closeIt = () => {};
        openSheet((close) => {
          closeIt = close;
          return [
            h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: "새 파일을 어떻게 넣을까요?" }),
            h("p", { class: "sheet-sub", text: count === null ? "저장된 거래가 있을 수 있어요." : `저장된 거래가 ${nf.format(count)}건 있어요.` }),
            h("ul", { class: "tx-modes" },
              h("li", null, h("b", { text: "이어 붙이기" }),
                h("p", { text: "저장된 거래 뒤에 새 거래를 붙여요. 시각·금액·상대가 같은 거래는 한 번만 둬요. 담은 거래도 그대로예요." })),
              h("li", null, h("b", { text: "모두 바꾸기" }),
                h("p", { text: ["저장된 거래를 지우고 새 거래로 바꿔요.", clearsText()].filter(Boolean).join(" ") }))),
            h("div", { class: "sheet-actions" },
              pickBtn("append", "이어 붙이기", "primary"),
              pickBtn("replace", "모두 바꾸기", ""),
              h("button", { type: "button", class: "btn big block ghost", "data-cancel": "1", text: "그만두기", onclick: () => close() })),
          ];
        }, { label: "새 파일을 어떻게 넣을까요?", onClose: () => resolve(result) });
      });
    }

    async function afterReplace() {
      changedData();
      await loadSummary();
      if (monitoring === null) await checkConsent().catch(() => null);
      await loadList(true);
    }

    // ---- 연습용 거래 불러오기 ----
    function openSample() {
      // 고르기 상자(select)는 큰 글씨에서 고른 이름이 잘려(가상 근로) 누구인지 알 수 없었다: 이름이 다 보이는 라디오 묶음으로
      const persona = h("div", { class: "segmented seg-persona", role: "radiogroup", "aria-labelledby": "sample-persona-label" },
        PERSONAS.map((p, i) => h("label", null, h("input", { type: "radio", name: "sample-persona", value: p.value, checked: i === 0 }), h("span", { text: p.label }))));
      const personaValue = () => (persona.querySelector("input:checked") || {}).value || PERSONAS[0].value;
      const seed = h("input", { class: "input", id: "sample-seed", type: "number", inputmode: "numeric", min: "0", max: "1000000", value: String(SAMPLE_SEED),
        "aria-describedby": "sample-seed-hint" });
      const mix = h("input", { type: "checkbox", id: "sample-mix", checked: true });
      const err = h("p", { class: "error-text", role: "alert", hidden: true });
      openSheet((close) => [
        h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: "연습용 거래 불러오기" }),
        // 뜻 단위가 갈리지 않게 줄을 바꾸지 않는 빈칸(\u00a0, 6글자까지)으로 잇는다: 알려 주는지·미리 살펴봐요, 같은 거래가(같은 번호면 같은 / 거래가).
        // 미리 볼 수 있어요는 미리 살펴봐요로 줄였다: 볼 수 있어요가 낱말 묶음(span.bind)이라 그 앞 빈칸을 \u00a0로 두어도 크롬은 묶음 앞에서
        // 줄을 바꿔 미리 / 볼 수 있어요로 갈렸다
        h("p", { class: "sheet-sub", text: "진짜 사람의 거래가 아니에요. AI가 어떻게 알려\u00a0주는지 미리\u00a0살펴봐요." }),
        h("div", { class: "field" }, h("span", { class: "field-label", id: "sample-persona-label", text: "누구의 거래인가요? (가상 인물)" }), persona),
        h("div", { class: "field" }, h("label", { for: "sample-seed", text: "번호" }), seed,
          h("p", { class: "hint", id: "sample-seed-hint", text: "같은 번호면 같은\u00a0거래가 나와요." })),
        h("label", { class: "check-row" }, mix, h("span", { class: "grow", text: "걱정되는 거래 섞기" })),
        err,
        h("div", { class: "sheet-actions" },
          h("button", {
            type: "button", class: "btn primary big block",
            onclick: (e) => busy(e.currentTarget, async () => {
              const n = parseInt(seed.value || String(SAMPLE_SEED), 10);
              const body = { persona: personaValue(), seed: Number.isFinite(n) && n >= 0 ? Math.min(n, 1000000) : SAMPLE_SEED, scenarios: mix.checked };
              let count;
              try { count = await storedCount(); } catch (e2) { return; }
              if (!(await confirmReplace(count)) || !ctx.alive()) return;
              try {
                const r = await ctx.req("POST", "/api/data/sample", body);
                // 섞은 수(정답 표시 수)는 AI가 찾은 수와 달라 헷갈리므로 쓰지 않는다. 대신 실제로 찾은 수를 알린다(J3·AUG-07)
                const msg = [`${r.persona_name} 거래 ${nf.format(r.count)}건을 불러왔어요.`, ...levelLines(r)].join(" ");
                close();
                toast(msg);
                announce(msg);
                await afterReplace();
              } catch (e2) {
                if (e2 === STALE) return;
                err.textContent = e2.message; err.hidden = false;
              }
            }),
          }, icon("check"), h("span", { text: "불러오기" })),
          h("button", { type: "button", class: "btn big block", text: "닫기", onclick: () => close() })),
      ], { label: "연습용 거래 불러오기" });
    }

    // ---- 파일 올리기: 지금은 .csv .txt .xls .xlsx, .pdf .jpg .png는 준비 중 ----
    function openUpload() {
      const file = h("input", { class: "sr-only", id: "upload-file", type: "file", tabindex: "-1", "aria-hidden": "true", accept: ACCEPT });
      const chosen = h("p", { class: "hint tx-chosen", id: "upload-chosen", "data-nosplit": true, text: "아직 고르지 않았어요." });
      const report = h("div", { "aria-live": "polite" });
      const pick = h("button", { type: "button", class: "btn weak big block", "aria-describedby": "upload-chosen", onclick: () => file.click() },
        icon("file"), h("span", { text: "파일 고르기" }));
      const badFile = (f) => {
        const ext = fileExt(f.name);
        if (!ext || EXT_OK.has(ext)) return "";
        return `.${ext} 파일은 아직 올릴 수 없어요. .csv, .txt, .xls, .xlsx 파일을 골라 주세요.`;
      };
      file.addEventListener("change", () => {
        const f = file.files && file.files[0];
        chosen.textContent = f ? `고른 파일: ${f.name} (${sizeText(f.size)})` : "아직 고르지 않았어요.";
        const bad = f ? badFile(f) : "";
        if (bad) fill(report, h("p", { class: "error-text", role: "alert", text: bad }));
        else report.replaceChildren();
      });
      const extChip = (ext, on) => h("li", { class: `tx-ext${on ? "" : " off"}`, "aria-disabled": on ? null : "true" },
        on ? icon("check-line") : null, h("span", { text: ext }));

      /** 올린 결과(AUG-07): 읽은 수 → 이어 붙인 수 → 걱정되는 거래 요약 + 알림에서 보기 → 안내(문장마다 한 줄). */
      function showResult(r, close) {
        const rep = r.report || {};
        const appended = r.mode === "append";
        const lines = [`${nf.format(rep.loaded || 0)}건을 읽었어요.`];
        if (rep.skipped) lines.push(`못 읽은 줄은 ${nf.format(rep.skipped)}개예요.`);
        if (appended) lines.push(r.added ? `새 거래 ${nf.format(r.added)}건을 저장된 거래 뒤에 붙였어요.` : "새로 붙인 거래는 없어요.");
        const summary = levelLines(r, appended ? "지금 저장된 거래에는 " : "");
        const lv = r.levels || {};
        const concern = (lv.high || 0) + (lv.caution || 0);
        const warnings = (rep.warnings || []).map((w) => sentence(String(w)));
        fill(report, h("div", { class: "notice green tx-result" }, icon("check"), h("div", { class: "tx-result-main" },
          h("p", { text: keepUnits(lines.join(" ")) }),
          summary.length ? h("p", { class: "tx-result-sum", text: keepUnits(summary.join(" ")) }) : null,
          warnings.length ? h("ul", null, warnings.map((w) => h("li", null, h("p", { text: w })))) : null,   // 안내도 한 문장 한 줄
          concern ? h("button", {
            type: "button", class: "btn sm weak notice-action tx-to-alerts", onclick: () => { close(); go("alerts"); },
          }, icon("bell"), h("span", { text: "알림에서 보기" })) : null)));
        // 결과 상자(aria-live)가 읽어 주므로 토스트·announce를 따로 띄우지 않는다(같은 글을 두 번 읽지 않게)
      }

      openSheet((close) => [
        h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: "거래내역 파일 올리기" }),
        h("p", { class: "sheet-sub", text: `은행 앱에서 내려받은 거래내역 파일을 올려요. 파일은 ${deviceWord()} 밖으로 나가지 않아요.` }),
        h("section", { class: "tx-exts-box", "aria-label": "올릴 수 있는 파일" },
          h("h3", { class: "tx-ext-title", text: "지금 올릴 수 있는 파일" }),
          h("ul", { class: "tx-exts" }, EXT_NOW.map((x) => extChip(x, true))),
          h("h3", { class: "tx-ext-title" }, h("span", { text: "곧 올릴 수 있는 파일" }), soonBadge()),
          h("ul", { class: "tx-exts" }, EXT_SOON.map((x) => extChip(x, false))),
          h("p", { class: "muted", text: SOON_TEXT })),
        // 올릴 수 있는 확장자(.xls .xlsx)는 바로 위 목록에 있으므로 안내 글에서는 엑셀 파일이라고만 쓴다(긴 덩어리 파일(.xls·.xlsx)은이
        // 큰 글씨에서 통째로 다음 줄로 넘어가 엑셀 / 파일(.xls· / .xlsx)은처럼 갈렸다). 엑셀 파일·첫 번째 시트만·올려 주세요는 줄을 바꾸지 않는 빈칸으로 잇고,
        // 첫 번째 시트만 읽어요.는 한 덩어리(span.keep-word: 한 줄에 들면 통째로 옮기고, 칸보다 길 때만 안에서 줄을 바꾼다)로 둔다
        // (읽어요.만 다음 줄에 홀로 남거나 첫 번째 / 시트만으로 갈리지 않게). 문장마다 한 줄(span.sent), 문장 사이 빈칸은 span 끝에
        h("div", { class: "notice" }, icon("info"),
          h("p", null,
            h("span", { class: "sent", text: "은행 파일 모양은 따로 확인하지 못했어요. " }),
            h("span", { class: "sent" }, "엑셀\u00a0파일은 ", h("span", { class: "keep-word", text: "첫 번째\u00a0시트만 읽어요." }), " "),
            h("span", { class: "sent", text: "암호가 걸린 엑셀\u00a0파일은 엑셀에서 암호를 넣어 연 뒤 CSV로 저장해 올려\u00a0주세요." }))),
        h("div", { class: "field" }, pick, file, chosen),
        report,
        h("div", { class: "sheet-actions" },
          h("button", {
            type: "button", class: "btn primary big block",
            onclick: (e) => busy(e.currentTarget, async () => {
              const f = file.files && file.files[0];
              if (!f) { fill(report, h("p", { class: "error-text", role: "alert", text: "먼저 파일을 골라 주세요." })); return; }
              const bad = badFile(f);
              if (bad) { fill(report, h("p", { class: "error-text", role: "alert", text: bad })); return; }
              if (f.size > MAX_UPLOAD_BYTES) { fill(report, h("p", { class: "error-text", role: "alert", text: "파일이 너무 커요. 5MB까지 올릴 수 있어요." })); return; }
              let count;
              try { count = await storedCount(); } catch (e2) { return; }
              const mode = await chooseUploadMode(count);
              if (!mode || !ctx.alive()) return;
              fill(report, h("p", { class: "muted", text: "읽는 중이에요." }));
              try {
                // 열 이름은 서버가 스스로 찾는다(직접 알려 주기는 v0.3에서 뺐다). mode: replace(모두 바꾸기) | append(이어 붙이기)
                const r = await ctx.req("POST", UPLOAD_PATH, undefined, { blob: f, name: f.name, mapping: "", mode });
                showResult(r, close);
                await afterReplace();
              } catch (e2) {
                if (e2 === STALE) return;
                fill(report, errorNotice(e2, (p) => { close(); go(p); }));
              }
            }),
          }, icon("upload"), h("span", { text: "올리기" })),
          h("button", { type: "button", class: "btn big block", text: "닫기", onclick: () => close() })),
      ], { label: "파일 올리기" });
    }

    // 다른 화면에서 시트를 바로 열어 달라고 왔으면(주소 open=…) 연 뒤 주소에서 지운다(새로 고침에 다시 열리지 않게)
    const OPENERS = {
      upload: openUpload, sample: openSample,
      bank: () => openBankConnect(ctx, connectOpts), card: () => openCardConnect(ctx, connectOpts),
      phone: () => openPhonePayConnect(ctx, connectOpts),
    };
    const open = ctx.params.get("open");
    if (open) {
      syncParams();   // open만 지우고 찾는 이름·기간은 그대로 둔다
      if (OPENERS[open]) window.requestAnimationFrame(() => { if (ctx.alive()) OPENERS[open](); });
    }

    paintChips();
    const [, on] = await Promise.all([loadSummary(), checkConsent().catch((e) => (e === STALE ? STALE : null))]);
    if (on === STALE || !ctx.alive()) return;
    await loadList(true);
  },
};
