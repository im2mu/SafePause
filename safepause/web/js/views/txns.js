/* 내 거래: 거래 불러오기(연습용·파일), 보기 고르기(전체·확인해요·꼭 확인해요), 날짜별 목록, 거래 자세히. */
import { h, icon, fill, openSheet, confirmSheet, busy, toast, announce, skeleton, emptyState } from "../ui.js";
import { nf, formatDay, formatWon, formatWhen, dayKey, percent } from "../format.js";
import { txnRow, dateHead, levelBadge, errorNotice, learnedText } from "../components.js";
import { PERSONAS, SIGNAL_KO, CHANNEL_KO } from "../labels.js";
import { STALE, UPLOAD_PATH, MAX_UPLOAD_BYTES } from "../api.js";

const PAGE = 50;

export default {
  title: "내 거래",
  tab: "txns",
  async render(ctx) {
    const { main, go } = ctx;
    const summarySlot = h("div", null, skeleton(1));
    const statusSlot = h("div", { role: "status" });
    const listSlot = h("div", { class: "list" });
    const moreBtn = h("button", { type: "button", class: "btn block", hidden: true });
    let filter = "all";
    let offset = 0;
    let lastKey = "";
    let loadSeq = 0;

    const chips = h("div", { class: "chips", role: "group", "aria-label": "거래 보기" },
      [["all", "전체"], ["caution", "걱정되는 것"], ["high", "꼭 확인할 것"]].map(([v, t]) => h("button", {
        type: "button", class: "chip", "aria-pressed": v === filter ? "true" : "false", "data-v": v,
        onclick: () => {
          filter = v;
          for (const c of chips.children) c.setAttribute("aria-pressed", c.dataset.v === v ? "true" : "false");
          loadList(true);
        },
      }, h("span", { text: t }))));

    fill(main,
      h("h2", { class: "page-title", tabindex: "-1", text: "내 거래" }),
      summarySlot,
      h("div", { class: "btn-row", style: "margin-bottom:1rem" },
        h("button", { type: "button", class: "btn weak", onclick: openSample }, icon("sparkle"), h("span", { text: "연습용 거래" })),
        h("button", { type: "button", class: "btn weak", onclick: openUpload }, icon("upload"), h("span", { text: "파일 올리기" }))),
      chips, statusSlot, listSlot, moreBtn);
    moreBtn.addEventListener("click", () => loadList(false));

    async function loadSummary() {
      try {
        const s = await ctx.req("GET", "/api/data/summary");
        fill(summarySlot, h("section", { class: "card" },
          h("div", { class: "card-row" },
            h("span", { class: "row-icon blue" }, icon("database")),
            h("div", { class: "grow" },
              h("h3", { text: s.count ? `저장된 거래 ${nf.format(s.count)}건` : "저장된 거래가 없어요" }),
              h("p", { class: "muted", text: s.count ? `${formatDay(s.first_ts)} ~ ${formatDay(s.last_ts)}` : "연습용 거래를 불러오거나 파일을 올려 주세요." })))));
        return s;
      } catch (e) {
        if (e !== STALE) fill(summarySlot, errorNotice(e, go));
        return null;
      }
    }

    async function loadList(reset) {
      const seq = ++loadSeq;   // 보기를 빨리 바꾸면 늦게 온 옛 응답을 버린다(리뷰 M3)
      if (reset) { offset = 0; lastKey = ""; listSlot.replaceChildren(skeleton(3)); moreBtn.hidden = true; }
      try {
        const d = await ctx.req("GET", `/api/transactions?level=${filter}&limit=${PAGE}&offset=${offset}`);
        if (seq !== loadSeq) return;
        if (reset) {
          listSlot.replaceChildren();
          const s = d.summary;
          const model = d.model.fitted ? learnedText(d.model.train_count, d.model.train_rows) : "거래가 30건보다 적어서 AI 없이 약속(규칙)으로만 살펴봐요.";
          fill(statusSlot, h("p", { class: "muted", style: "margin:.25rem .25rem .75rem" },
            `괜찮아요 ${nf.format(s.none)} · 확인해요 ${nf.format(s.caution)} · 꼭 확인해요 ${nf.format(s.high)}. ${model}`));
          if (!d.items.length) {
            listSlot.append(emptyState("list", d.count ? "고른 보기에 맞는 거래가 없어요" : "저장된 거래가 없어요",
              d.count ? "다른 보기를 골라 보세요." : "위에서 연습용 거래를 불러오거나 파일을 올려 주세요."));
          }
        }
        for (const item of d.items) {
          const key = dayKey(item.txn.ts);
          if (key !== lastKey) { listSlot.append(dateHead(item.txn.ts)); lastKey = key; }
          listSlot.append(txnRow(item, openDetail));
        }
        offset += d.items.length;
        const left = d.matched - offset;
        moreBtn.hidden = left <= 0;
        moreBtn.textContent = `더 보기 (${nf.format(Math.max(left, 0))}건 남음)`;
      } catch (e) {
        if (e === STALE || seq !== loadSeq) return;
        listSlot.replaceChildren();
        statusSlot.replaceChildren();
        moreBtn.hidden = true;
        fill(statusSlot, errorNotice(e, go));
      }
    }

    function openDetail(item) {
      const t = item.txn;
      const out = t.direction === "out";
      openSheet((close) => [
        h("div", { class: "card-row", style: "margin-bottom:.75rem" }, levelBadge(item.level),
          item.practice ? h("span", { class: "tag", text: "보내기 연습" }) : null),
        h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: `${t.counterparty || "(이름 없음)"} · ${out ? "나감" : "들어옴"} ${formatWon(t.amount)}` }),
        h("p", { class: "sheet-sub", text: `${formatWhen(t.ts)} · ${CHANNEL_KO[t.channel] || t.channel} · ${nf.format(t.amount)}원` }),
        (item.signals || []).length ? h("div", { class: "list" }, h("div", { class: "list-head", text: "걸린 약속(규칙)" }),
          item.signals.map((code) => h("div", { class: "row" }, h("span", { class: "row-icon orange" }, icon("warning")),
            h("span", { class: "row-main" }, h("span", { class: "row-title", text: SIGNAL_KO[code] || code }))))) : null,
        h("div", { class: "notice" }, icon("sparkle"), h("div", null,
          h("strong", { text: `평소와 다른 정도: ${percent(item.anomaly_score, 0)}` }),
          h("p", { text: "AI가 내 평소 거래와 비교한 값이에요. 100%에 가까울수록 평소와 달라요." }),
          h("p", { text: "AI 혼자서는 '꼭 확인해요'를 정하지 않아요. 약속(규칙)에 걸린 거래만 한 단계 올려요." }))),
        t.label && t.label !== "normal" ? h("p", { class: "muted", text: `연습용 정답: ${SIGNAL_KO[t.label] || t.label} (가상 거래라 정답이 붙어 있어요)` }) : null,
        h("div", { class: "sheet-actions" }, h("button", { type: "button", class: "btn big block", text: "닫기", onclick: () => close() })),
      ], { label: "거래 자세히" });
    }

    // 저장된 거래를 통째로 바꾸기 전에 묻는다(리뷰 M8). 건수를 못 읽으면 건너뛰지 않고 '바뀔 수 있어요'로 묻는다(2차 검증)
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
        lines: [count === null ? "저장된 거래가 있으면 지워지고, 새 거래로 바뀌어요." : `저장된 거래 ${nf.format(count)}건은 지워지고, 새 거래로 바뀌어요.`, "계속할까요?"],
        confirmText: "네, 바꿀래요", cancelText: "아니요",
      });
    }

    function openSample() {
      const persona = h("select", { class: "input", id: "sample-persona" }, PERSONAS.map((p) => h("option", { value: p.value, text: p.label })));
      const seed = h("input", { class: "input", id: "sample-seed", type: "number", inputmode: "numeric", min: "0", max: "1000000", value: "1" });
      const mix = h("input", { type: "checkbox", id: "sample-mix", checked: true });
      const err = h("p", { class: "error-text", role: "alert", hidden: true });
      openSheet((close) => [
        h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: "연습용 거래 불러오기" }),
        h("p", { class: "sheet-sub", text: "가상의 사람 거래예요. 진짜 사람의 거래가 아니에요." }),
        h("div", { class: "field" }, h("label", { for: "sample-persona", text: "누구의 거래?" }), persona),
        h("div", { class: "field" }, h("label", { for: "sample-seed", text: "번호 (같은 번호면 같은 거래가 나와요)" }), seed),
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
                const mixed = Object.values(r.scenario_labels || {}).reduce((a, b) => a + b, 0);
                const msg = `${r.persona_name} 연습용 거래 ${nf.format(r.count)}건을 불러왔어요(진짜 거래가 아니에요).` + (r.scenarios ? ` 걱정되는 거래 ${mixed}건을 섞었어요.` : "");
                close();
                toast(msg);
                announce(msg);
                await loadSummary();
                await loadList(true);
              } catch (e2) {
                if (e2 === STALE) return;
                err.textContent = e2.message; err.hidden = false;
              }
            }),
          }, icon("check"), h("span", { text: "불러오기" })),
          h("button", { type: "button", class: "btn big block", text: "닫기", onclick: () => close() })),
      ], { label: "연습용 거래 불러오기" });
    }

    function openUpload() {
      const file = h("input", { class: "sr-only", id: "upload-file", type: "file", tabindex: "-1", accept: ".csv,text/csv,text/comma-separated-values,application/vnd.ms-excel" });
      const fileName = h("span", { class: "muted", text: "아직 고르지 않았어요" });
      file.addEventListener("change", () => { fileName.textContent = file.files && file.files[0] ? file.files[0].name : "아직 고르지 않았어요"; });
      const mapping = h("textarea", { class: "input", id: "upload-mapping", rows: "3", spellcheck: "false", autocapitalize: "off", autocorrect: "off",
        placeholder: '{"datetime": "거래일시", "out_amount": "출금액", "in_amount": "입금액", "counterparty": "내용"}' });
      const report = h("div", { "aria-live": "polite" });
      openSheet((close) => [
        h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: "내 거래내역 파일 올리기" }),
        h("p", { class: "sheet-sub", text: "은행 앱에서 내려받은 거래내역 파일을 올려요. 파일은 이 기기 밖으로 나가지 않아요." }),
        h("div", { class: "notice" }, icon("info"), h("div", null,
          h("p", { text: "은행 파일 모양은 따로 확인하지 못했어요." }),
          h("p", { text: "엑셀 파일이면 엑셀에서 '다른 이름으로 저장 → CSV UTF-8'로 저장한 뒤 올려 주세요(보호자·도우미)." }))),
        h("div", { class: "field" },
          h("span", { class: "field-label", text: "파일" }),
          h("label", { for: "upload-file", class: "btn weak block", role: "button", tabindex: "0",
            onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); file.click(); } } },
            icon("file"), h("span", { text: "파일 고르기" })),
          file, h("p", { class: "hint" }, fileName)),
        h("details", { class: "field" }, h("summary", { class: "field-label", text: "열 이름 직접 알려 주기 (보호자·도우미용)" }),
          h("p", { class: "hint", text: "파일의 열 이름을 알아보지 못할 때 적어 주세요." }), mapping),
        report,
        h("div", { class: "sheet-actions" },
          h("button", {
            type: "button", class: "btn primary big block",
            onclick: (e) => busy(e.currentTarget, async () => {
              const f = file.files && file.files[0];
              if (!f) { fill(report, h("p", { class: "error-text", role: "alert", text: "먼저 파일을 골라 주세요." })); return; }
              if (f.size > MAX_UPLOAD_BYTES) { fill(report, h("p", { class: "error-text", role: "alert", text: "파일이 너무 커요(5MB까지)." })); return; }
              let count;
              try { count = await storedCount(); } catch (e2) { return; }
              if (!(await confirmReplace(count)) || !ctx.alive()) return;
              fill(report, h("p", { class: "muted", text: "읽는 중이에요…" }));
              try {
                const r = await ctx.req("POST", UPLOAD_PATH, undefined, { blob: f, name: f.name, mapping: mapping.value.trim() });
                const rep = r.report;
                fill(report, h("div", { class: "notice green" }, icon("check"), h("div", null,
                  h("p", { text: `${nf.format(rep.loaded)}건을 읽었어요. 못 읽은 줄은 ${nf.format(rep.skipped)}개예요.` }),
                  rep.warnings && rep.warnings.length ? h("ul", null, rep.warnings.map((w) => h("li", { text: w }))) : null)));
                announce(`${rep.loaded}건을 읽었어요.`);
                await loadSummary();
                await loadList(true);
              } catch (e2) {
                if (e2 === STALE) return;
                fill(report, errorNotice(e2, (p) => { close(); go(p); }));
              }
            }),
          }, icon("upload"), h("span", { text: "올리기" })),
          h("button", { type: "button", class: "btn big block", text: "닫기", onclick: () => close() })),
      ], { label: "파일 올리기" });
    }

    await loadSummary();
    await loadList(true);
  },
};
