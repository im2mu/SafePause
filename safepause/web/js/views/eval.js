/* AI 성능 확인(조력자·기관용). 전문 용어(주의·고위험·fused·seed 등)는 이 화면에만 쓰고, 결론 줄(J11)은 쉬운 말로 쓴다.
 * ① 제출 보고서 수치(검증 세트 seed 21~40, 앱에 함께 넣은 원자료 data/eval_reference.json) + 표 위 결론(표와 같은 수치로 만든 글)
 * ② 보고서 수치 다시 계산: 보고서와 같은 설정(인물 3명 × seed 21~40, 세 방식)으로 표준 시나리오 → 경계 변형을 차례로 계산하고
 *    ①의 기준값과 지표마다 견준다(POST /api/eval/run {seeds: 20, seed_start: 21, intensity, modes}).
 *    응답 report_set이 참이고 intensity가 맞을 때만 견주고, 값은 반올림하지 않고 === 로 견준다
 *    (키 짝은 tests/test_eval_run_api.py REFERENCE_PATHS와 같다).
 * ③ 직접 골라 계산해 보기(seed 1부터, 즉석) ④ 내 거래로 확인. 표 칸 안 설명도 문장마다 한 줄(C6).
 * 계산하는 동안에는 계산 버튼 셋을 잠그고(aria-disabled), 화면을 떠나면 늦게 온 결과를 버린다
 * (ctx.req → STALE, 다음 세트는 보내지 않음, 시계는 onCleanup에서 멈춤).
 */
import { h, icon, fill, append, setText, busy, announce, skeleton, splitSentences } from "../ui.js";
import { nf, percent, num, formatWon, moneyText, keepUnits } from "../format.js";
import { errorNotice, learnedText } from "../components.js";
import { MODE_KO, SIGNAL_KO } from "../labels.js";
import { STALE, MODE } from "../api.js";

const MODES3 = ["rules", "fused", "anomaly"];
const INTENSITY_KO = { standard: "표준 시나리오", subtle: "경계 변형" };
// 제출 보고서 검증 세트: 인물 3명 × seed 21~40(safepause/api/constants.py REPORT_SEED_START·REPORT_SEEDS)
const REPORT_RUN = { seeds: 20, seed_start: 21 };
const REPORT_SETS = ["standard", "subtle"];
// 걸리는 시간 안내(C14: 잰 값만 쓴다). 백엔드 담당이 seed 20개·세 방식으로 잰 값(2026-10-03, scratchpad/evalapi):
// PC 서버 표준 10.78초·경계 변형 10.14초, 앱 안 AI 엔진(데스크톱 Chrome의 Pyodide) 24.72초·21.44초. 휴대폰은 재지 않았다
const TIME_HINT = MODE === "engine"
  ? "앱 안 AI 엔진은 시험용 컴퓨터에서 한 세트에 21~25초, 두 세트에 46초쯤 걸렸어요. 휴대폰에서는 아직 재 보지 않았고, 더 오래 걸릴 수 있어요."
  : "시험용 컴퓨터에서는 한 세트에 10~11초, 두 세트에 21초쯤 걸렸어요. 컴퓨터마다 걸리는 시간이 달라요.";
// 엔진은 요청을 한 줄로 처리한다: 화면을 떠나도 이미 보낸 계산은 끝까지 돈다
const LEAVE_NOTE = MODE === "engine"
  ? "계산하는 동안 다른 화면으로 가면 결과를 버려요. 시작한 계산은 끝까지 이어져서, 그동안 다른 화면이 늦게 열릴 수 있어요."
  : "계산하는 동안 다른 화면으로 가면 결과를 버려요.";
const SETTING_ERROR = "보고서와 같은 설정(seed 21~40)으로 계산하지 못했어요. SafePause를 최신 버전으로 바꾼 뒤 다시 해 주세요.";

// eval_reference.json 키 → 응답 results[방식] 안 자리(tests/test_eval_run_api.py REFERENCE_PATHS와 같은 짝)
const REF_PATHS = {
  scenario_caution: ["overall", "recall_caution"],
  scenario_high: ["overall", "recall_high"],
  scenario_caution_n: ["overall", "caution"],
  scenario_high_n: ["overall", "high"],
  scenario_n: ["overall", "n"],
  txn_high_recall: ["confusion", "high", "recall"],
  txn_caution_recall: ["confusion", "caution", "recall"],
  normal_alert_rate: ["normal", "alert_rate"],
  normal_high_rate: ["normal", "high_rate"],
  control_monthly_alerts: ["control", "monthly_alerts"],
  control_monthly_high: ["control", "monthly_high"],
  amount_before_first_alert_mean: ["overall", "amount_before_first_alert_mean"],
};
const SCEN_FIELDS = ["caution", "high", "n"];
// 견준 표의 줄: 한 줄에서 키 여러 개를 함께 견준다(탐지율은 비율 + 찾은 수 + 전체 수). show는 끊기지 않는 조각 목록
const CHECK_ROWS = [
  { label: "시나리오 주의 이상 탐지율", keys: ["scenario_caution", "scenario_caution_n", "scenario_n"], show: ([r, c, n]) => [percent(r), `(${c}/${n})`] },
  { label: "시나리오 고위험 탐지율", keys: ["scenario_high", "scenario_high_n", "scenario_n"], show: ([r, c, n]) => [percent(r), `(${c}/${n})`] },
  { label: "거래별 주의 이상 재현율", keys: ["txn_caution_recall"], show: ([v]) => [percent(v)] },
  { label: "거래별 고위험 재현율", keys: ["txn_high_recall"], show: ([v]) => [percent(v)] },
  { label: "정상 거래 알림률 (주의 이상)", keys: ["normal_alert_rate"], show: ([v]) => [percent(v, 2)] },
  { label: "정상 거래 고위험률", keys: ["normal_high_rate"], show: ([v]) => [percent(v, 2)] },
  { label: "대조군 월평균 알림 건수", keys: ["control_monthly_alerts"], show: ([v]) => [num(v)] },
  { label: "대조군 월평균 고위험 건수", keys: ["control_monthly_high"], show: ([v]) => [num(v)] },
  { label: "첫 알림 전 평균 유출", keys: ["amount_before_first_alert_mean"], show: ([v]) => [moneyText(v)] },
];

export default {
  title: "AI 성능 확인",
  back: "more",
  tab: "more",
  async render(ctx) {
    const { main, go } = ctx;
    const refSlot = h("div", null, skeleton(1));
    const reOut = h("div");                         // 진행 단계·결과(바뀌는 때는 announce로 알린다)
    const runOut = h("div", { "aria-live": "polite" });
    const mineOut = h("div", { "aria-live": "polite" });
    let ref = null;                                 // 보고서 기준값(eval_reference.json)
    let running = false;                            // 계산 하나가 도는 동안 계산 버튼 셋을 잠근다
    let tick = 0;
    ctx.onCleanup(() => window.clearInterval(tick));

    const seeds = h("select", { class: "input", id: "eval-seeds" },
      [["1", "1번 (빠름)"], ["3", "3번"], ["5", "5번"], ["10", "10번"], ["20", "20번 (느림)"]].map(([v, t]) => h("option", { value: v, text: t, selected: v === "3" })));
    const intensity = h("select", { class: "input", id: "eval-intensity" },
      Object.entries(INTENSITY_KO).map(([v, t]) => h("option", { value: v, text: t, selected: v === "standard" })));
    const modeBoxes = Object.keys(MODE_KO).map((m) => h("input", { type: "checkbox", name: "eval-mode", value: m, checked: m === "fused" }));
    const reBtn = h("button", { type: "button", class: "btn primary big block ev-re-btn", onclick: (e) => exclusive(e.currentTarget, recompute) },
      icon("refresh"), h("span", { text: "보고서 수치 다시 계산" }));
    const runBtn = h("button", { type: "button", class: "btn weak big block", onclick: (e) => exclusive(e.currentTarget, run) },
      icon("chart"), h("span", { text: "계산 시작" }));
    const mineBtn = h("button", { type: "button", class: "btn weak big block eval-mine", onclick: (e) => exclusive(e.currentTarget, mine) },
      icon("list"), h("span", { text: "내 거래로 확인" }));
    const lockable = [reBtn, runBtn, mineBtn];

    fill(main,
      h("h2", { class: "page-title", tabindex: "-1", text: "AI 성능 확인" }),
      h("div", { class: "notice orange" }, icon("warning"), h("div", null,
        h("strong", { text: "합성 데이터 기준, 실제 피해 데이터 검증 아님" }),
        h("p", { text: "가상의 거래에 걱정되는 거래를 섞어서, SafePause가 얼마나 찾는지 확인해요." }))),
      h("h3", { class: "section-title", text: "제출 보고서 수치 (검증 세트)" }),
      refSlot,
      h("h3", { class: "section-title", text: "보고서 수치 다시 계산 (seed 21~40)" }),
      h("div", { class: "card" },
        h("p", { text: "보고서와 같은 설정으로 표준 시나리오와 경계 변형을 차례로 계산해요. 설정은 인물 3명 × seed 21~40, 세 가지 방식이에요. 끝나면 위 표의 보고서 수치와 지표마다 견줘요." }),
        h("p", { class: "hint", text: TIME_HINT }),
        reBtn),
      reOut,
      h("h3", { class: "section-title", text: "직접 골라 계산해 보기 (seed 1부터)" }),
      h("div", { class: "card" },
        h("p", { class: "ev-intro", text: "보고서 수치 다시 계산은 보고서와 같은 가상 거래로 계산해서 같은 값이 나오는지 봐요. 여기서는 seed 1부터 고른 횟수만큼 다른 가상 거래로 계산해요. 그래서 값이 위 표와 달라요." }),
        h("div", { class: "field" }, h("label", { for: "eval-seeds", text: "반복 횟수 (seed 수, 인물 3명씩)" }), seeds),
        h("div", { class: "field" }, h("label", { for: "eval-intensity", text: "시나리오 종류" }), intensity),
        h("fieldset", { class: "field form-group" }, h("legend", { class: "field-label", text: "어떤 방식으로 확인할까요?" }),
          modeBoxes.map((b) => h("label", { class: "check-row" }, b, h("span", { class: "grow", text: `${MODE_KO[b.value]} (${b.value})` })))),
        h("p", { class: "hint", text: "횟수가 많을수록 오래 걸리고, 적을수록 값이 더 흔들려요. 20번에 세 방식을 모두 고르면 보고서 수치 다시 계산의 한 세트와 같은 양이에요." }),
        runBtn),
      runOut,
      h("h3", { class: "section-title", text: "내 거래로 확인" }),
      h("div", { class: "card" },
        h("p", { text: "저장된 거래를 모두 평소 거래로 보고, 알림이 얼마나 나오는지 세어요. 잘못 알리는 정도를 어림하는 방법이에요." }),
        mineBtn),
      mineOut);

    /** 계산은 한 번에 하나만: 누른 버튼은 busy(돌림표), 나머지 계산 버튼은 꺼진 모양으로 잠근다(초점이 빠지지 않게 disabled는 쓰지 않음). */
    async function exclusive(btn, fn) {
      if (running) return;
      running = true;
      for (const b of lockable) if (b !== btn) b.setAttribute("aria-disabled", "true");
      try { await busy(btn, fn); } finally {
        running = false;
        for (const b of lockable) if (b !== btn) b.removeAttribute("aria-disabled");
      }
    }

    // ① 제출 보고서 수치: 앱에 넣은 원자료 파일(web/data/eval_reference.json)
    async function loadRef() {
      if (ref) return ref;
      const res = await fetch("data/eval_reference.json", { cache: "no-store" });
      if (!res.ok) throw new Error("보고서 수치 파일을 읽지 못했어요.");
      ref = await res.json();
      return ref;
    }
    try {
      const data = await loadRef();
      if (!ctx.alive()) return;
      const std = data.sets.standard.modes, sub = data.sets.subtle.modes;
      const H3 = MODES3.map((m) => MODE_KO[m]);
      fill(refSlot,
        conclusion(std, sub),
        h("div", { class: "table-wrap ev-wrap" }, h("table", null,
          h("caption", { text: "표준 시나리오 300개 (인물 3 × seed 20)" }),
          h("thead", null, h("tr", null, h("th", { text: "지표" }), MODES3.map((m) => h("th", { text: MODE_KO[m] })))),
          h("tbody", null,
            trow("거래별 고위험 재현율", MODES3.map((m) => percent(std[m].txn_high_recall)), H3),
            trow("정상 거래 고위험률", MODES3.map((m) => percent(std[m].normal_high_rate, 2)), H3),
            trow("정상 거래 알림률 (주의 이상)", MODES3.map((m) => percent(std[m].normal_alert_rate, 2)), H3),
            trow("대조군 월평균 알림 건수", MODES3.map((m) => num(std[m].control_monthly_alerts)), H3),
            // 표의 금액은 moneyText(R21). 결론 문장은 쉬운 말 금액(formatWon)
            trow("첫 알림 전 평균 유출", MODES3.map((m) => moneyText(std[m].amount_before_first_alert_mean)), H3)))),
        h("div", { class: "table-wrap ev-wrap" }, h("table", null,
          h("caption", { text: "경계 변형 300개 (결과 확인 전에 정의)" }),
          h("thead", null, h("tr", null, h("th", { text: "지표" }), MODES3.map((m) => h("th", { text: MODE_KO[m] })))),
          h("tbody", null,
            trow("시나리오 고위험 탐지율", MODES3.map((m) => percent(sub[m].scenario_high)), H3),
            trow("시나리오 주의 이상 탐지율", MODES3.map((m) => percent(sub[m].scenario_caution)), H3),
            trow("정상 거래 고위험률", MODES3.map((m) => percent(sub[m].normal_high_rate, 2)), H3),
            trow("정상 거래 알림률 (주의 이상)", MODES3.map((m) => percent(sub[m].normal_alert_rate, 2)), H3)))),
        breakPaths(h("p", { class: "muted eval-note", text: `seed ${data.seeds} 검증 세트(룰 보완에 쓰지 않은 세트). ${data.note}` })),
        // PC 프로그램 안에서 PC판과 같다고 말하지 않는다(C8). 같은 값이 나오는지는 아래 다시 계산으로 직접 본다
        MODE === "engine" ? h("p", { class: "muted eval-note", text: "이 앱 안의 AI 엔진은 PC판과 같은 코드예요." }) : null);
    } catch (e) {
      if (!ctx.alive()) return;
      fill(refSlot, h("div", { class: "notice" }, icon("info"), h("p", { text: "보고서 수치 파일을 읽지 못했어요." })));
    }

    // ② 보고서 수치 다시 계산: 표준 → 경계 변형을 차례로 계산하고 보고서 기준값과 견준다
    async function recompute() {
      let want;
      try {
        want = await loadRef();
      } catch (e) {
        if (!ctx.alive()) return;
        fill(reOut, errorNotice(new Error("보고서 수치 파일을 읽지 못해서 견줄 수 없어요."), go));
        return;
      }
      if (!ctx.alive()) return;
      const steps = progressView([
        `${INTENSITY_KO.standard} ${scenarioCount(want, "standard")}개 계산`,
        `${INTENSITY_KO.subtle} ${scenarioCount(want, "subtle")}개 계산`,
        "보고서 수치와 견주기",
      ]);
      const leave = h("p", { class: "hint ev-leave", text: LEAVE_NOTE });
      fill(reOut, h("div", { class: "ev-progress" }, steps.el, steps.clock, leave));
      announce("보고서 수치 다시 계산을 시작했어요.");
      const t0 = performance.now();
      window.clearInterval(tick);
      tick = window.setInterval(() => setText(steps.clock, `지난 시간 ${Math.floor((performance.now() - t0) / 1000)}초`), 1000);
      const stop = () => { window.clearInterval(tick); tick = 0; };
      const got = {};
      let i = 0;
      try {
        for (; i < REPORT_SETS.length; i += 1) {
          if (!ctx.alive()) { stop(); return; }   // 떠난 뒤에는 다음 세트를 보내지 않는다
          const key = REPORT_SETS[i];
          steps.set(i, "run");
          const s0 = performance.now();
          const r = await ctx.req("POST", "/api/eval/run", { ...REPORT_RUN, intensity: key, modes: MODES3 });
          if (!r || r.report_set !== true || r.intensity !== key) throw new Error(SETTING_ERROR);
          got[key] = r;
          steps.set(i, "done", seconds(performance.now() - s0));
          announce(`${INTENSITY_KO[key]} 계산을 마쳤어요.`);
        }
        steps.set(i, "run");
        const cmps = REPORT_SETS.map((key) => ({ key, r: got[key], want: want.sets[key], map: compareSet(want.sets[key], got[key]) }));
        steps.set(i, "done");
        stop();
        setText(steps.clock, `모두 ${seconds(performance.now() - t0)} 걸렸어요.`);
        leave.remove();
        const total = cmps.reduce((s, c) => s + c.map.size, 0);
        const diffs = cmps.reduce((s, c) => s + [...c.map.values()].filter((x) => !x.same).length, 0);
        append(reOut, [verdict(total, diffs), cmps.map((c) => setTables(c)), envNote(got.standard)]);
        announce(diffs ? `다시 계산을 마쳤어요. 보고서 수치와 다른 값이 ${diffs}개 있어요.` : "다시 계산을 마쳤어요. 보고서 수치와 모두 같아요.");
      } catch (e) {
        stop();
        if (e === STALE || !ctx.alive()) return;
        steps.set(i, "fail");
        setText(steps.clock, `${seconds(performance.now() - t0)} 만에 멈췄어요.`);
        leave.remove();
        append(reOut, errorNotice(e, go));
      }
    }

    // ③ 직접 골라 계산해 보기(seed 1부터)
    async function run() {
      const modes = modeBoxes.filter((b) => b.checked).map((b) => b.value);
      if (!modes.length) { fill(runOut, h("p", { class: "error-text", role: "alert", text: "방식을 하나 이상 골라 주세요." })); return; }
      fill(runOut, h("div", { class: "engine-bar", role: "status" }, h("span", { class: "spinner", "aria-hidden": "true" }), h("span", { text: "계산하고 있어요…" })));
      try {
        const r = await ctx.req("POST", "/api/eval/run", { seeds: parseInt(seeds.value, 10) || 3, intensity: intensity.value, modes });
        const ms = r.modes.filter((m) => r.results[m]);
        const res = ms.map((m) => r.results[m]);
        const first = res[0] || {};
        const pick = (fn) => res.map((x) => { try { return fn(x); } catch (e) { return "-"; } });
        const HM = ms.map((m) => MODE_KO[m] || m);
        const codes = Object.keys(first.scenario_recall || {});
        const s0 = r.seed_start ?? r.seeds[0], s1 = r.seed_end ?? r.seeds[r.seeds.length - 1];
        fill(runOut,
          h("p", { class: "muted eval-note", text: `${INTENSITY_KO[r.intensity] || INTENSITY_KO.standard} · 인물 ${r.personas.length}명 × seed ${s0 === s1 ? s0 : `${s0}~${s1}`} = 사례 ${first.n_cases ?? "-"}개. 앞 ${first.baseline_days ?? "-"}일로 배우고 뒤 ${first.eval_days ?? "-"}일을 확인했어요. 계산에 ${r.elapsed_sec}초 걸렸어요.` }),
          h("div", { class: "table-wrap ev-wrap" }, h("table", null, h("caption", { text: "요약" }),
            h("thead", null, h("tr", null, h("th", { text: "지표" }), ms.map((m) => h("th", { text: MODE_KO[m] || m })))),
            h("tbody", null,
              trow("시나리오 찾음 (주의 이상)", pick((x) => [percent(x.overall.recall_caution), `(${x.overall.caution}/${x.overall.n})`]), HM),
              trow("시나리오 찾음 (고위험)", pick((x) => [percent(x.overall.recall_high), `(${x.overall.high}/${x.overall.n})`]), HM),
              trow("평소 거래를 잘못 알림 (주의 이상 비율)", pick((x) => percent(x.normal.alert_rate)), HM),
              trow("평소 거래가 고위험이 됨 (조력자 알림 대상)", pick((x) => percent(x.normal.high_rate)), HM),
              trow("걱정 거래 없는 대조군: 한 달 평균 알림 (건)", pick((x) => (x.control ? num(x.control.monthly_alerts) : "-")), HM),
              trow("걱정 거래 없는 대조군: 한 달 평균 고위험 (건)", pick((x) => (x.control ? num(x.control.monthly_high) : "-")), HM)))),
          codes.length ? h("div", { class: "table-wrap ev-wrap" }, h("table", null, h("caption", { text: "걱정 거래 종류별 찾음 (주의 이상 / 고위험)" }),
            h("thead", null, h("tr", null, h("th", { text: "종류" }), ms.map((m) => h("th", { text: MODE_KO[m] || m })))),
            h("tbody", null, codes.map((code) => trow(SIGNAL_KO[code] || code,
              pick((x) => { const s = x.scenario_recall[code]; return [percent(s.recall_caution), `/ ${percent(s.recall_high)}`]; }), HM))))) : null,
          h("p", { class: "muted eval-note", text: `모델: ${[...new Set(res.flatMap((x) => x.model_versions || []))].join(", ") || "-"}` }),
          h("p", { class: "eval-note" }, h("strong", { text: r.note })));
        announce("성능 확인을 마쳤어요.");
      } catch (e) {
        if (e === STALE) return;
        fill(runOut, errorNotice(e, go));
      }
    }

    // ④ 내 거래로 확인
    async function mine() {
      fill(mineOut, h("div", { class: "engine-bar", role: "status" }, h("span", { class: "spinner", "aria-hidden": "true" }), h("span", { text: "계산하고 있어요…" })));
      try {
        const r = await ctx.req("POST", "/api/eval/file");
        const bySignal = Object.entries(r.by_signal || {}).map(([code, n]) => `${SIGNAL_KO[code] || code} ${n}건`).join(", ");
        fill(mineOut,
          h("div", { class: "table-wrap ev-wrap" }, h("table", null, h("caption", { text: "내 거래로 확인한 결과" }),
            h("tbody", null,
              trow("저장된 거래", [`${nf.format(r.n_total)}건`]),
              trow("AI가 평소 모습을 배운 구간 (앞쪽)", [learnedText(r.n_baseline, r.n_train_rows)]),
              trow("확인한 거래 (뒤쪽)", [`${nf.format(r.n_eval)}건 · ${r.eval_days}일`]),
              trow("알림 (주의 이상)", [`${r.alerts}건 (${percent(r.alert_rate)})`]),
              trow("고위험 (조력자 알림 대상)", [`${r.high}건 (${percent(r.high_rate)})`]),
              trow("한 달 평균 알림", [r.monthly_alerts === null || r.monthly_alerts === undefined ? "기간이 짧아 계산하지 않았어요" : `${num(r.monthly_alerts)}건`]),
              trow("알림 이유 (규칙)", [bySignal || "없음"]),
              trow("AI만 알린 것", [`${r.anomaly_only}건`])))),
          r.labeled_note ? h("div", { class: "notice orange" }, icon("info"), h("p", { text: r.labeled_note })) : null,
          h("p", { class: "eval-note" }, h("strong", { text: r.note })));
      } catch (e) {
        if (e === STALE) return;
        fill(mineOut, errorNotice(e, go));
      }
    }
  },
};

function trow(label, values, heads = []) {
  // heads: 좁은 화면에서 값 앞에 붙일 칸 이름(표를 카드 모양으로 바꿀 때)
  // 조각 목록인 값(["63.0%", "(189/300)"])은 조각 사이에서만 줄을 바꾼다(큰 글씨 좁은 칸에서 넘치지 않게)
  // 두 문장 이상인 값(learnedText 등)은 문장마다 한 줄(p 안 span.sent, C6)
  return h("tr", null, h("th", { scope: "row", text: label }),
    values.map((v, i) => {
      const head = heads[i] || "";
      if (Array.isArray(v)) return h("td", { class: "num ev-cell", "data-label": head }, pieces(v));
      return splitSentences(String(v)).length > 1
        ? h("td", { class: "num long", "data-label": head }, h("p", { text: v }))
        : h("td", { class: "num", "data-label": head, text: v });
    }));
}

/** 파일 이름·경로(docs/eval/eval_results_holdout.json)는 / 와 _ 뒤에서 줄을 바꿀 수 있게 wbr을 넣는다
 * (좁은 화면·큰 글씨에서 낱말 가운데가 아무 데서나 잘리지 않게, textContent는 그대로). */
function breakPaths(el) {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const nodes = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) if (/[/_]/.test(n.nodeValue)) nodes.push(n);
  for (const n of nodes) {
    const parts = n.nodeValue.split(/(?<=[/_])/);
    n.replaceWith(...parts.flatMap((t, i) => (i < parts.length - 1 ? [t, document.createElement("wbr")] : [t])));
  }
  return el;
}

/** 끊기지 않는 조각들(조각 사이 빈칸에서만 줄바꿈). */
function pieces(parts, cls = "ev-out") {
  const out = h("span", { class: cls });
  parts.forEach((p, i) => append(out, [i ? " " : null, h("span", { class: "nowrap", text: p })]));
  return out;
}

// ---- 보고서 수치 다시 계산: 진행 단계·견주기·표 ------------------------------------------
const STEP_STATE = { wait: "기다려요", run: "계산하고 있어요", done: "마쳤어요", fail: "못 했어요" };

/** 진행 단계 목록(번호 순서) + 지난 시간. set(i, wait|run|done|fail, 덧붙일 말). */
function progressView(titles) {
  const items = titles.map((title) => {
    const ic = h("span", { class: "ev-step-ic", "aria-hidden": "true" });
    const state = h("span", { class: "ev-step-state" });
    const li = h("li", { class: "ev-step" }, ic, h("span", { class: "ev-step-main" }, h("span", { class: "ev-step-title", text: title }), " ", state));
    return { li, ic, state };
  });
  const set = (i, kind, extra = "") => {
    const it = items[i];
    if (!it) return;
    it.li.className = `ev-step ${kind}`;
    if (kind === "run") it.li.setAttribute("aria-current", "step"); else it.li.removeAttribute("aria-current");
    it.state.textContent = extra ? `${STEP_STATE[kind]} · ${extra}` : STEP_STATE[kind];
    fill(it.ic, kind === "run" ? h("span", { class: "ev-spin" }) : kind === "done" ? icon("check") : kind === "fail" ? icon("warning") : h("span", { class: "ev-dot" }));
  };
  items.forEach((_, i) => set(i, "wait"));
  return {
    el: h("ol", { class: "ev-steps", "aria-label": "계산 단계" }, items.map((x) => x.li)),
    clock: h("p", { class: "muted ev-clock", text: "지난 시간 0초" }),
    set,
  };
}

function seconds(ms) {
  return `${(ms / 1000).toFixed(1)}초`;
}

function scenarioCount(want, key) {
  const n = want.sets[key] && want.sets[key].modes.rules && want.sets[key].modes.rules.scenario_n;
  return n ? nf.format(n) : "";
}

function at(obj, path) {
  let v = obj;
  for (const k of path) {
    if (v === null || v === undefined || typeof v !== "object") return undefined;
    v = v[k];
  }
  return v;
}

/**
 * 한 세트(표준 또는 경계 변형)의 모든 기준값을 견준다. 돌려주는 값: Map(`${방식}|${키}` → {got, want, same}).
 * 키: REF_PATHS 12개 + 종류별(by.<code>.caution|high|n) + n_cases. 반올림하지 않고 === 로 견준다(PC·앱 엔진 모두 같은 값, 백엔드 시험).
 */
function compareSet(wantSet, r) {
  const out = new Map();
  for (const m of MODES3) {
    const res = r && r.results ? r.results[m] : undefined;
    const want = (wantSet.modes || {})[m] || {};
    const put = (key, got, w) => out.set(`${m}|${key}`, { got, want: w, same: w !== undefined && got === w });
    for (const [key, path] of Object.entries(REF_PATHS)) put(key, at(res, path), want[key]);
    for (const [code, v] of Object.entries(want.by_scenario || {})) {
      for (const f of SCEN_FIELDS) put(`by.${code}.${f}`, at(res, ["scenario_recall", code, f]), v[f]);
    }
    put("n_cases", at(res, ["n_cases"]), wantSet.n_cases);
  }
  return out;
}

const missing = (v) => v === null || v === undefined || (typeof v === "number" && Number.isNaN(v));

/** 표 칸: 같으면 값, 다르면 계산한 값과 보고서 값을 함께(보이는 값이 같으면 반올림 전 값으로). */
function cmpCell(row, mode, map) {
  const items = row.keys.map((k) => map.get(`${mode}|${k}`) || { same: false });
  const same = items.every((x) => x.same);
  const vals = (side) => items.map((x) => x[side]);
  const show = (vs) => (vs.some(missing) ? ["값 없음"] : row.show(vs));
  const label = MODE_KO[mode];
  if (same) return h("td", { class: "num ev-cell", "data-label": label }, pieces(show(vals("got"))));
  let a = show(vals("got")), b = show(vals("want"));
  if (a.join(" ") === b.join(" ")) { a = vals("got").map(String); b = vals("want").map(String); }
  return h("td", { class: "num ev-cell diff", "data-label": label },
    h("span", { class: "ev-pair" }, pieces(["계산", ...a], "ev-got"), " ", pieces(["보고서", ...b], "ev-want")));
}

function mark(same) {
  return h("span", { class: `ev-mark ${same ? "same" : "diff"}` },
    icon(same ? "check" : "warning"), h("span", { text: same ? "보고서 수치와 같아요" : "보고서 수치와 달라요" }));
}

function cmpRow(row, map) {
  const same = MODES3.every((m) => row.keys.every((k) => (map.get(`${m}|${k}`) || {}).same));
  return h("tr", { class: same ? "ev-same" : "ev-diff" },
    h("th", { scope: "row" }, h("span", { class: "ev-label", text: row.label }), " ", mark(same)),
    MODES3.map((m) => cmpCell(row, m, map)));
}

function headRow(first) {
  return h("thead", null, h("tr", null, h("th", { text: first }), MODES3.map((m) => h("th", { text: MODE_KO[m] }))));
}

/** 한 세트의 견준 표: 지표 9줄(키 12개) + 접어 둔 종류별 찾은 수·사례 수. 다른 값이 있으면 펼쳐 둔다. */
function setTables({ key, r, want, map }) {
  const name = INTENSITY_KO[key];
  const scenRows = Object.keys((want.modes.rules || {}).by_scenario || {}).map((code) => ({
    label: SIGNAL_KO[code] || code,
    keys: SCEN_FIELDS.map((f) => `by.${code}.${f}`),
    show: ([c, hi, n]) => [`${c} / ${hi} / ${n}`],
  }));
  scenRows.push({ label: `사례 수 (인물 3 × seed ${REPORT_RUN.seeds})`, keys: ["n_cases"], show: ([n]) => [nf.format(n)] });
  const scenSame = scenRows.every((row) => MODES3.every((m) => row.keys.every((k) => (map.get(`${m}|${k}`) || {}).same)));
  const scenCount = scenRows.reduce((s, row) => s + row.keys.length * MODES3.length, 0);
  return [
    h("div", { class: "table-wrap ev-wrap ev-table" }, h("table", null,
      h("caption", { text: `${name} 다시 계산 (seed ${r.seed_start}~${r.seed_end})` }),
      headRow("지표"),
      h("tbody", null, CHECK_ROWS.map((row) => cmpRow(row, map))))),
    h("details", { class: "ev-more", open: !scenSame },
      h("summary", null,
        h("span", { class: "ev-more-text" },
          h("span", { class: "ev-more-title", text: `${name}: 걱정 거래 종류별 찾은 수 (값 ${scenCount}개)` }),
          " ", mark(scenSame)),
        icon("chevron-down")),
      h("div", { class: "table-wrap ev-wrap" }, h("table", { "aria-label": `${name} 종류별 찾은 사례 수 (주의 이상 / 고위험 / 전체)` },
        h("caption", { text: "주의 이상 / 고위험 / 전체" }),
        headRow("종류"),
        h("tbody", null, scenRows.map((row) => cmpRow(row, map)))))),
  ];
}

/** 결론 한 줄(J11, 쉬운 말): 모두 같은지, 다르면 몇 개인지. */
function verdict(total, diffs) {
  return diffs === 0
    ? h("div", { class: "notice green ev-verdict" }, icon("check"),
      h("p", { class: "lead-strong", text: `다시 계산한 값이 보고서 수치와 모두 같아요. 표준 시나리오와 경계 변형에서 값 ${nf.format(total)}개를 견줬어요.` }))
    : h("div", { class: "notice red ev-verdict" }, icon("warning"),
      h("p", { class: "lead-strong", text: `다시 계산한 값 ${nf.format(total)}개 가운데 ${nf.format(diffs)}개가 보고서 수치와 달라요. 다른 값은 아래 표에 계산한 값과 보고서 값을 함께 적었어요.` }));
}

/** 계산한 환경(프로그램 버전): 다른 값이 나왔을 때 견줄 단서. */
function envNote(r) {
  const res = r && r.results ? r.results.fused || Object.values(r.results)[0] : null;
  const env = res && res.environment;
  if (!env || typeof env !== "object") return null;
  const items = Object.entries(env).map(([k, v]) => `${k} ${v}`);
  // 한 문장이라 나누지 않는다. 이름과 버전(scikit-learn 1.9.1)은 끊지 않고 가운뎃점 뒤에서만 줄을 바꾼다
  return items.length ? h("p", { class: "muted eval-note" }, "계산 환경: ", items.map((t, i) => [i ? " · " : null, h("span", { class: "nowrap", text: t })])) : null;
}

// 화면 글에서 숫자와 단위·조사가 줄 끝에서 떨어지지 않게(6만 7천 원, 78.5%로)
function tight(t) {
  return keepUnits(t).replace(/%(?=[가-힣])/g, "%⁠");
}

/**
 * 표 위 결론(J11): 규칙만 → 규칙 + AI로 바뀐 점을 표와 같은 수치로 쓴다(합성 데이터 기준). 방향(늘어요·줄어요)은 값에서 정한다.
 */
function conclusion(std, sub) {
  const r = std.rules, f = std.fused;
  const dir = (a, b, up, down) => (b > a ? up : b < a ? down : "같아요");
  const lines = [
    `걱정되는 거래를 꼭 확인으로 알린 비율이 ${percent(r.txn_high_recall)}에서 ${percent(f.txn_high_recall)}로 ${dir(r.txn_high_recall, f.txn_high_recall, "늘어요.", "줄어요.")}`,
    `첫 알림 전에 나간 돈은 평균 ${formatWon(r.amount_before_first_alert_mean)}에서 ${formatWon(f.amount_before_first_alert_mean)}으로 ${dir(r.amount_before_first_alert_mean, f.amount_before_first_alert_mean, "늘어요.", "줄어요.")}`,
    `평소 거래를 잘못 알린 비율도 ${percent(r.normal_alert_rate, 2)}에서 ${percent(f.normal_alert_rate, 2)}로 ${dir(r.normal_alert_rate, f.normal_alert_rate, "조금 늘어요.", "줄어요.")}`,
  ];
  if (sub && sub.rules && sub.fused) {
    lines.push(`알아차리기 어려운 경계 변형에서는 꼭 확인으로 찾은 사례가 ${percent(sub.rules.scenario_high, 0)}에서 ${percent(sub.fused.scenario_high, 0)}로 ${dir(sub.rules.scenario_high, sub.fused.scenario_high, "늘어요.", "줄어요.")}`);
  }
  const more = f.txn_high_recall > r.txn_high_recall, noisier = f.normal_alert_rate > r.normal_alert_rate;
  const lead = more && noisier ? "AI를 더하면 꼭 확인할 일을 더 많이 찾지만, 괜찮은 거래 알림도 조금 늘어요."
    : more ? "AI를 더하면 꼭 확인할 일을 더 많이 찾아요." : "AI를 더해도 꼭 확인할 일을 더 찾지는 못했어요.";
  return h("section", { class: "card eval-conclusion", "aria-label": "결론" },
    h("h4", { class: "eval-conclusion-title", text: "규칙만 쓸 때와 AI를 더할 때" }),
    h("p", { class: "strong", text: lead }),
    h("ul", { class: "about-bullets" }, lines.map((t) => h("li", null, h("p", { text: tight(t) })))),
    h("p", { class: "muted", text: "표준 시나리오 300개 기준이에요. 합성 데이터라서 실제 피해 데이터로 확인한 값이 아니에요." }));
}
