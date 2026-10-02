/* 내 거래: 요약(저장된 거래·기간·등급 비율), 거래 불러오기 4칸(은행·카드 연결은 준비 중, 파일 올리기, 연습용 거래),
 * 걸러 보기(전체·걱정되는 것·꼭 확인할 것·담은 거래), 날짜별 목록, 거래 시트(알림 목록에 담기·조력자·상담하는 곳에 알리기).
 * 주소 뒤 open=upload|sample|bank|card면 그 시트를 바로 연다(views/connect.js·홈 바로가기가 보냄). */
import { h, icon, fill, openSheet, confirmSheet, busy, toast, announce, skeleton, emptyState, soonBadge, SOON_TEXT } from "../ui.js";
import { nf, formatWhen, dayKey, parseTs, deviceWord } from "../format.js";
import { txnRow, dateHead, levelBadge, flaggedBadge, checkedBadge, txnAmount, txnSignals, flagButton, errorNotice } from "../components.js";
import { PERSONAS, CHANNEL_KO, LEVEL } from "../labels.js";
import { STALE, UPLOAD_PATH, MAX_UPLOAD_BYTES, isConsentError } from "../api.js";
import { openBankConnect, openCardConnect } from "./connect.js";

const PAGE = 50;

const FILTERS = [
  { value: "all", label: "전체" },
  { value: "caution", label: "걱정되는 것" },
  { value: "high", label: "꼭 확인할 것" },
  { value: "flagged", label: "담은 거래" },
];
// 고른 보기에 거래가 없을 때
const EMPTY = {
  all: ["저장된 거래가 없어요", "위의 거래 불러오기에서 시작해 보세요."],
  caution: ["걱정되는 거래가 없어요", "다른 보기를 골라 보세요."],
  high: ["꼭 확인할 거래가 없어요", "다른 보기를 골라 보세요."],
  flagged: ["담은 거래가 없어요", "거래를 누르면 알림 목록에 담을 수 있어요."],
};

// 거래 시트의 쉬운 설명 한 줄(신호 이름은 labels.js의 명사형, 여기는 무슨 일이 있었는지)
const SIGNAL_EASY = {
  night_repeat_transfer: "밤늦게 돈을 여러 번 보냈어요.",
  payee_surge: "한 사람에게 돈을 자주 보냈어요.",
  micropay_surge: "휴대폰으로 결제를 많이 했어요.",
  new_merchant_high_value: "처음 간 가게에 큰 돈을 냈어요.",
  multi_line_telecom: "휴대폰 요금이 여러 개 나왔어요.",
  anomaly: "AI가 보기에 내 평소 거래와 많이 달라요.",
};
// 이력이 짧아 처음인지 알 수 없을 때(labels.SIGNAL_KO_NEUTRAL과 맞춤)
const SIGNAL_EASY_NEUTRAL = { new_merchant_high_value: "가게에 큰 돈을 냈어요." };

// 파일 올리기: 지금 읽을 수 있는 파일과 정식 버전에서 열 파일
const EXT_NOW = [".csv", ".txt"];
const EXT_SOON = [".xlsx", ".pdf", ".jpg", ".png"];
const EXT_OK = new Set(["csv", "txt", "tsv"]);
const ACCEPT = ".csv,.txt,text/csv,text/plain,text/comma-separated-values,text/tab-separated-values,application/vnd.ms-excel";

function easyLine(item, code) {
  const r = (item.reasons || []).find((x) => x.code === code);
  if (r && r.detail && r.detail.newness_unknown && SIGNAL_EASY_NEUTRAL[code]) return SIGNAL_EASY_NEUTRAL[code];
  return SIGNAL_EASY[code] || "";
}

/** "2026년 3월 2일 ~ 6월 29일"(해가 바뀌면 뒤에도 해를 쓴다) */
function periodText(first, last) {
  const a = parseTs(first), b = parseTs(last);
  if (!a || !b) return "";
  const day = (d, withYear) => (withYear ? `${d.getFullYear()}년 ` : "") + `${d.getMonth() + 1}월 ${d.getDate()}일`;
  if (dayKey(first) === dayKey(last)) return day(a, true);
  return `${day(a, true)} ~ ${day(b, a.getFullYear() !== b.getFullYear())}`;
}

/** 요약 카드 맨 아래 한 줄: AI가 몇 건으로 배웠는지(자세한 숫자는 AI와 데이터 설명·성능 확인 화면) */
function modelText(model) {
  if (!model || !model.fitted) return "거래가 30건보다 적어서 AI 없이 약속(규칙)으로만 살펴봐요.";
  const rows = Number.isInteger(model.train_rows) && model.train_rows > 0 ? model.train_rows : model.train_count;
  return `AI가 거래 ${nf.format(rows)}건을 보고 내 평소 모습을 배웠어요.`;
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
    const moreBtn = h("button", { type: "button", class: "btn block tx-more", hidden: true });
    const rowsById = new Map();   // 거래 id → 목록 줄(담기 뒤 그 줄만 다시 그림)
    const counts = { all: null, caution: null, high: null, flagged: null };
    let filter = "all";
    let offset = 0;
    let lastKey = "";
    let loadSeq = 0;
    let stored = null;   // /api/data/summary
    let levels = null;   // /api/transactions의 summary·model

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

    // ---- 거래 불러오기 4칸 ----
    const connectOpts = { onUpload: openUpload, onSample: openSample };
    const tile = ({ ic, title, sub, soon, onclick }) => h("button", { type: "button", class: "tx-tile", onclick },
      h("span", { class: "tx-tile-icon", "aria-hidden": "true" }, icon(ic)),
      h("span", { class: "tx-tile-title", text: title }),
      soon ? h("span", { class: "tx-tile-sub" }, soonBadge()) : h("span", { class: "tx-tile-sub", text: sub }));
    const importGrid = h("div", { class: "tx-import" },
      tile({ ic: "bank", title: "은행 거래내역 불러오기", soon: true, onclick: () => openBankConnect(ctx, connectOpts) }),
      tile({ ic: "card", title: "카드 결제내역 불러오기", soon: true, onclick: () => openCardConnect(ctx, connectOpts) }),
      tile({ ic: "upload", title: "파일 올리기", sub: EXT_NOW.join(" "), onclick: openUpload }),
      tile({ ic: "sparkle", title: "연습용 거래 불러오기", sub: "가상의 거래", onclick: openSample }));

    const listTitle = h("h3", { class: "section-title", text: "거래 목록" });
    fill(main,
      h("h2", { class: "page-title", tabindex: "-1", text: "내 거래" }),
      summarySlot,
      h("h3", { class: "section-title", text: "거래 불러오기" }),
      importGrid,
      listTitle, chips, statusSlot, listSlot, moreBtn);
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
      if (levels) {
        const s = levels.summary;
        const rows = ["none", "caution", "high"].map((lv) => ({ lv, n: s[lv] || 0 }));
        parts.push(
          h("div", { class: "stack tx-levels", "aria-hidden": "true" },
            rows.filter((r) => r.n > 0).map((r) => h("i", { class: `lv-${r.lv}`, style: `flex:${r.n}` }))),
          h("ul", { class: "legend tx-legend", "aria-label": "등급별 거래 수" }, rows.map((r) => h("li", { class: `lv-${r.lv}` },
            h("span", { class: "swatch", "aria-hidden": "true" }),
            h("span", { class: "grow", text: LEVEL[r.lv].text }),
            h("b", { text: `${nf.format(r.n)}건` })))),
          h("div", { class: "tx-model" }, icon("sparkle"), h("p", { text: modelText(levels.model) })));
      }
      fill(summarySlot, h("section", { class: "card tx-summary", "aria-label": "저장된 거래 요약" },
        h("div", { class: "kpi" },
          h("span", { class: "kpi-label", text: "저장된 거래" }),
          h("b", { class: "kpi-value", text: `${nf.format(stored.count)}건` })),
        h("p", { class: "tx-period", "data-nosplit": true, text: periodText(stored.first_ts, stored.last_ts) }),
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

    // ---- 목록 ----
    function addRow(item) {
      const key = dayKey(item.txn.ts);
      if (key !== lastKey) { listSlot.append(dateHead(item.txn.ts)); lastKey = key; }
      const row = txnRow(item, openDetail);
      rowsById.set(item.txn.id, row);
      listSlot.append(row);
    }

    async function loadList(reset, speak = false) {
      const seq = ++loadSeq;   // 보기를 빨리 바꾸면 늦게 온 옛 응답을 버린다(리뷰 M3)
      if (reset) {
        offset = 0; lastKey = ""; rowsById.clear();
        listSlot.hidden = false;
        listSlot.setAttribute("aria-busy", "true");
        listSlot.replaceChildren(skeleton(3));
        moreBtn.hidden = true;
      }
      try {
        const d = await ctx.req("GET", `/api/transactions?level=${filter}&limit=${PAGE}&offset=${offset}`);
        if (seq !== loadSeq) return;
        if (reset) {
          listSlot.replaceChildren();
          statusSlot.replaceChildren();
          const s = d.summary;
          counts.all = d.count;
          counts.caution = (s.caution || 0) + (s.high || 0);
          counts.high = s.high || 0;
          counts.flagged = d.flagged_count || 0;
          paintChips();
          levels = { summary: s, model: d.model };
          paintSummary();
          // 거래가 하나도 없으면 칩·목록 제목을 숨기고 빈 안내만
          chips.hidden = !d.count;
          listTitle.hidden = !d.count;
          if (!d.items.length) {
            const [title, text] = d.count ? EMPTY[filter] : EMPTY.all;
            listSlot.append(emptyState(filter === "flagged" ? "bookmark" : "list", title, text));
          }
          if (speak) announce(d.matched ? `${nf.format(d.matched)}건이 있어요.` : EMPTY[filter][0]);
        }
        for (const item of d.items) addRow(item);
        offset += d.items.length;
        const left = d.matched - offset;
        moreBtn.hidden = left <= 0;
        moreBtn.textContent = `더 보기 (${nf.format(Math.max(left, 0))}건 남음)`;
      } catch (e) {
        if (e === STALE || seq !== loadSeq) return;
        listSlot.replaceChildren();
        listSlot.hidden = true;
        moreBtn.hidden = true;
        if (reset && isConsentError(e)) chips.hidden = true;   // 동의가 꺼져 있으면 걸러 볼 거래가 없다
        fill(statusSlot, errorNotice(e, go),
          isConsentError(e) ? null : h("button", { type: "button", class: "btn block tx-retry", onclick: () => loadList(reset) },
            icon("refresh"), h("span", { text: "다시 불러오기" })));
      } finally {
        if (seq === loadSeq) listSlot.removeAttribute("aria-busy");
      }
    }

    // ---- 거래 시트: 상대·시각·방법·금액(한 번), 등급·이유, 담기·알리기 ----
    function fact(label, value) {
      return h("div", { class: "tx-fact" }, h("dt", { text: label }), h("dd", { text: value }));
    }

    function openDetail(item) {
      const t = item.txn;
      const out = t.direction === "out";
      const signals = txnSignals(item);
      let changed = false;
      // 이름 옆 배지(등급·담음): 담기를 바꾸면 배지만 다시 그린다(제목의 초점은 그대로)
      const badges = h("span", { class: "tx-badges" });
      const paintHead = () => fill(badges, levelBadge(item.level), item.flagged ? flaggedBadge() : null, item.practice ? checkedBadge() : null);
      paintHead();
      const flag = flagButton(ctx, item, {
        cls: `btn${item.flagged ? "" : " primary"} big block`,
        onChange: (on, count) => {
          changed = true;
          flag.classList.toggle("primary", !on);
          paintHead();
          counts.flagged = Number.isInteger(count) ? count : Math.max(0, (counts.flagged || 0) + (on ? 1 : -1));
          paintChips();
        },
      });
      const tone = item.level === "high" ? "red" : "orange";
      openSheet((close) => [
        h("div", { class: "tx-head" },
          h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: t.counterparty || "이름 없음" }), badges),
        h("p", { class: `tx-amount${out ? "" : " in"}`, "data-nosplit": true, text: txnAmount(t) }),
        h("dl", { class: "tx-facts" },
          fact("언제", formatWhen(t.ts)),
          fact("어떻게", CHANNEL_KO[t.channel] || t.channel),
          t.memo ? fact("메모", t.memo) : null),
        signals.length ? h("section", { class: "sheet-section", "aria-label": "확인할 점" },
          h("h3", { class: "tx-sub-title", text: "왜 확인해요?" }),
          h("ul", { class: "tx-reasons" }, signals.map((s) => h("li", null,
            h("span", { class: `row-icon ${tone}` }, icon(s.icon)),
            h("div", { class: "tx-reason-main" },
              h("b", { text: s.text }),
              easyLine(item, s.code) ? h("p", { class: "muted", text: easyLine(item, s.code) }) : null))))) : null,
        h("div", { class: "sheet-actions" },
          flag,
          h("button", {
            type: "button", class: "btn weak big block",
            onclick: () => { close(); go(`send?txn=${encodeURIComponent(t.id)}`); },
          }, icon("send"), h("span", { text: "조력자·상담하는 곳에 알리기" })),
          h("button", { type: "button", class: "btn big block", text: "닫기", onclick: () => close() })),
      ], {
        label: "거래 자세히",
        onClose: () => {
          if (!changed || !ctx.alive()) return;
          // 담은 거래 보기에서 뺐으면 목록을 다시 읽고, 아니면 그 줄만 담음 표시를 바꿔 그린다
          if (filter === "flagged") {
            loadList(true);
            const active = chipEls.find((c) => c.f.value === filter);
            if (active) window.requestAnimationFrame(() => active.btn.focus());
            return;
          }
          const old = rowsById.get(t.id);
          if (!old || !old.isConnected) return;
          const fresh = txnRow(item, openDetail);
          old.replaceWith(fresh);
          rowsById.set(t.id, fresh);
          window.requestAnimationFrame(() => { if (fresh.isConnected) fresh.focus(); });
        },
      });
    }

    // ---- 거래를 통째로 바꾸기 전 확인(리뷰 M8). 건수를 못 읽으면 건너뛰지 않고 바뀔 수 있다고 묻는다(2차 검증) ----
    async function storedCount() {
      try {
        return (await ctx.req("GET", "/api/data/summary")).count;
      } catch (e) {
        if (e === STALE) throw e;
        return null;
      }
    }
    async function confirmReplace(count) {
      if (count === 0) return true;
      return confirmSheet({
        title: "지금 거래가 바뀌어요",
        // 한 문단에 넣으면 문장마다 한 줄로 나뉜다(줄 사이가 벌어지지 않게)
        lines: [[
          count === null ? "저장된 거래가 있으면 지워지고 새 거래로 바뀌어요." : `저장된 거래 ${nf.format(count)}건은 지워지고 새 거래로 바뀌어요.`,
          counts.flagged ? "알림 목록에 담은 거래도 비워져요." : "",
          "계속할까요?",
        ].filter(Boolean).join(" ")],
        confirmText: "네, 바꿀래요", cancelText: "아니요",
      });
    }

    async function afterReplace() {
      await loadSummary();
      await loadList(true);
    }

    // ---- 연습용 거래 불러오기 ----
    function openSample() {
      const persona = h("select", { class: "input", id: "sample-persona" }, PERSONAS.map((p) => h("option", { value: p.value, text: p.label })));
      const seed = h("input", { class: "input", id: "sample-seed", type: "number", inputmode: "numeric", min: "0", max: "1000000", value: "1",
        "aria-describedby": "sample-seed-hint" });
      const mix = h("input", { type: "checkbox", id: "sample-mix", checked: true });
      const err = h("p", { class: "error-text", role: "alert", hidden: true });
      openSheet((close) => [
        h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: "연습용 거래 불러오기" }),
        h("p", { class: "sheet-sub", text: "진짜 사람의 거래가 아니에요. AI가 어떻게 알려 주는지 미리 볼 수 있어요." }),
        h("div", { class: "field" }, h("label", { for: "sample-persona", text: "누구의 거래인가요?" }), persona),
        h("div", { class: "field" }, h("label", { for: "sample-seed", text: "번호" }), seed,
          h("p", { class: "hint", id: "sample-seed-hint", text: "같은 번호면 같은 거래가 나와요." })),
        h("label", { class: "check-row" }, mix, h("span", { class: "grow", text: "걱정되는 거래 섞기" })),
        err,
        h("div", { class: "sheet-actions" },
          h("button", {
            type: "button", class: "btn primary big block",
            onclick: (e) => busy(e.currentTarget, async () => {
              const n = parseInt(seed.value || "1", 10);
              const body = { persona: persona.value, seed: Number.isFinite(n) && n >= 0 ? Math.min(n, 1000000) : 1, scenarios: mix.checked };
              let count;
              try { count = await storedCount(); } catch (e2) { return; }
              if (!(await confirmReplace(count)) || !ctx.alive()) return;
              try {
                const r = await ctx.req("POST", "/api/data/sample", body);
                // 섞은 수(정답 표시 수)는 AI가 찾은 수와 달라 헷갈리므로 쓰지 않는다
                const msg = `${r.persona_name} 거래 ${nf.format(r.count)}건을 불러왔어요.` + (r.scenarios ? " 걱정되는 거래도 섞었어요." : "");
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

    // ---- 파일 올리기: 지금은 .csv .txt, .xlsx .pdf .jpg .png는 준비 중 ----
    function openUpload() {
      const file = h("input", { class: "sr-only", id: "upload-file", type: "file", tabindex: "-1", "aria-hidden": "true", accept: ACCEPT });
      const chosen = h("p", { class: "hint tx-chosen", id: "upload-chosen", "data-nosplit": true, text: "아직 고르지 않았어요." });
      const report = h("div", { "aria-live": "polite" });
      const pick = h("button", { type: "button", class: "btn weak big block", "aria-describedby": "upload-chosen", onclick: () => file.click() },
        icon("file"), h("span", { text: "파일 고르기" }));
      const badFile = (f) => {
        const ext = fileExt(f.name);
        if (!ext || EXT_OK.has(ext)) return "";
        if (ext === "xlsx" || ext === "xls") return "엑셀 파일은 아직 올릴 수 없어요. CSV UTF-8로 저장한 뒤 올려 주세요.";
        return `.${ext} 파일은 아직 올릴 수 없어요. .csv 또는 .txt 파일을 골라 주세요.`;
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
      openSheet((close) => [
        h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: "거래내역 파일 올리기" }),
        h("p", { class: "sheet-sub", text: `은행 앱에서 내려받은 거래내역 파일을 올려요. 파일은 ${deviceWord()} 밖으로 나가지 않아요.` }),
        h("section", { class: "tx-exts-box", "aria-label": "올릴 수 있는 파일" },
          h("h3", { class: "tx-ext-title", text: "지금 올릴 수 있는 파일" }),
          h("ul", { class: "tx-exts" }, EXT_NOW.map((x) => extChip(x, true))),
          h("h3", { class: "tx-ext-title" }, h("span", { text: "곧 올릴 수 있는 파일" }), soonBadge()),
          h("ul", { class: "tx-exts" }, EXT_SOON.map((x) => extChip(x, false))),
          h("p", { class: "muted", text: SOON_TEXT })),
        h("div", { class: "notice" }, icon("info"),
          h("p", { text: "은행 파일 모양은 따로 확인하지 못했어요. 엑셀 파일은 CSV UTF-8로 저장한 뒤 올려 주세요." })),
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
              if (!(await confirmReplace(count)) || !ctx.alive()) return;
              fill(report, h("p", { class: "muted", text: "읽는 중이에요." }));
              try {
                // 열 이름은 서버가 스스로 찾는다(직접 알려 주기는 v0.3에서 뺐다)
                const r = await ctx.req("POST", UPLOAD_PATH, undefined, { blob: f, name: f.name, mapping: "" });
                const rep = r.report;
                fill(report, h("div", { class: "notice green" }, icon("check"), h("div", null,
                  h("p", { text: `${nf.format(rep.loaded)}건을 읽었어요. 못 읽은 줄은 ${nf.format(rep.skipped)}개예요.` }),
                  rep.warnings && rep.warnings.length ? h("ul", null, rep.warnings.map((w) => h("li", null, h("p", { text: w })))) : null)));   // 안내도 한 문장 한 줄
                announce(`${nf.format(rep.loaded)}건을 읽었어요.`);
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
    };
    const open = ctx.params.get("open");
    if (open) {
      ctx.replaceParams({});
      if (OPENERS[open]) window.requestAnimationFrame(() => { if (ctx.alive()) OPENERS[open](); });
    }

    paintChips();
    await Promise.all([loadSummary(), loadList(true)]);
  },
};
