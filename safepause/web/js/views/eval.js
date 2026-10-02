/* AI 성능 확인(보호자·심사용). 전문 용어(주의·고위험·fused 등)는 이 화면 표에만 쓴다.
 * ① 제출 보고서 수치(검증 세트 seed 21~40, 앱에 함께 넣은 원자료) ② 직접 다시 계산 ③ 내 거래로 확인. */
import { h, icon, fill, busy, announce, skeleton } from "../ui.js";
import { nf, percent, num, formatWon } from "../format.js";
import { errorNotice, learnedText } from "../components.js";
import { MODE_KO, SIGNAL_KO } from "../labels.js";
import { STALE, MODE } from "../api.js";

export default {
  title: "AI 성능 확인",
  back: "more",
  tab: "more",
  async render(ctx) {
    const { main, go } = ctx;
    const refSlot = h("div", null, skeleton(1));
    const runOut = h("div", { "aria-live": "polite" });
    const mineOut = h("div", { "aria-live": "polite" });
    const seeds = h("select", { class: "input", id: "eval-seeds" },
      [["1", "1번 (빠름)"], ["3", "3번"], ["5", "5번"], ["10", "10번 (느림)"]].map(([v, t]) => h("option", { value: v, text: t, selected: v === "3" })));
    const modeBoxes = Object.keys(MODE_KO).map((m) => h("input", { type: "checkbox", name: "eval-mode", value: m, checked: m === "fused" }));
    fill(main,
      h("h2", { class: "page-title", tabindex: "-1", text: "AI 성능 확인" }),
      h("div", { class: "notice orange" }, icon("warning"), h("div", null,
        h("strong", { text: "합성 데이터 기준, 실제 피해 데이터 검증 아님" }),
        h("p", { text: "가상의 거래에 걱정되는 거래를 섞어서, SafePause가 얼마나 찾는지 확인해요." }))),
      h("h3", { class: "section-title", text: "제출 보고서 수치 (검증 세트)" }),
      refSlot,
      h("h3", { class: "section-title", text: "직접 다시 계산해 보기" }),
      h("div", { class: "card" },
        h("div", { class: "field" }, h("label", { for: "eval-seeds", text: "반복 횟수 (seed 수, 인물 3명씩)" }), seeds),
        h("fieldset", { class: "field form-group" }, h("legend", { class: "field-label", text: "어떤 방식으로 확인할까요?" }),
          modeBoxes.map((b) => h("label", { class: "check-row" }, b, h("span", { class: "grow", text: `${MODE_KO[b.value]} (${b.value})` })))),
        MODE === "engine" ? h("p", { class: "hint", text: "휴대폰에서는 1번에 10초쯤, 10번이면 1~2분 걸려요." }) : null,
        h("button", { type: "button", class: "btn primary big block", onclick: (e) => busy(e.currentTarget, run) }, icon("chart"), h("span", { text: "확인 시작" }))),
      runOut,
      h("h3", { class: "section-title", text: "내 거래로 확인" }),
      h("div", { class: "card" },
        h("p", { text: "저장된 거래를 모두 평소 거래로 보고, 알림이 얼마나 나오는지 세어요. 잘못 알리는 정도를 어림하는 방법이에요." }),
        h("button", { type: "button", class: "btn weak big block eval-mine", onclick: (e) => busy(e.currentTarget, mine) }, icon("list"), h("span", { text: "내 거래로 확인" }))),
      mineOut);

    // ① 제출 보고서 수치: 앱에 넣은 원자료 파일(web/data/eval_reference.json)
    try {
      const res = await fetch("data/eval_reference.json", { cache: "no-store" });
      const ref = await res.json();
      if (!ctx.alive()) return;
      const std = ref.sets.standard.modes, sub = ref.sets.subtle.modes;
      const H3 = ["rules", "fused", "anomaly"].map((m) => MODE_KO[m]);
      fill(refSlot,
        h("div", { class: "table-wrap" }, h("table", null,
          h("caption", { text: "표준 시나리오 300개 (인물 3 × seed 20)" }),
          h("thead", null, h("tr", null, h("th", { text: "지표" }), ["rules", "fused", "anomaly"].map((m) => h("th", { text: MODE_KO[m] })))),
          h("tbody", null,
            trow("거래별 고위험 재현율", ["rules", "fused", "anomaly"].map((m) => percent(std[m].txn_high_recall)), H3),
            trow("정상 거래 고위험률", ["rules", "fused", "anomaly"].map((m) => percent(std[m].normal_high_rate, 2)), H3),
            trow("정상 거래 알림률(주의 이상)", ["rules", "fused", "anomaly"].map((m) => percent(std[m].normal_alert_rate, 2)), H3),
            trow("대조군 월 알림(건)", ["rules", "fused", "anomaly"].map((m) => num(std[m].control_monthly_alerts)), H3),
            trow("첫 알림 전 평균 유출", ["rules", "fused", "anomaly"].map((m) => formatWon(std[m].amount_before_first_alert_mean)), H3)))),
        h("div", { class: "table-wrap" }, h("table", null,
          h("caption", { text: "경계 변형 300개 (결과 확인 전에 정의)" }),
          h("thead", null, h("tr", null, h("th", { text: "지표" }), ["rules", "fused", "anomaly"].map((m) => h("th", { text: MODE_KO[m] })))),
          h("tbody", null,
            trow("시나리오 고위험 탐지율", ["rules", "fused", "anomaly"].map((m) => percent(sub[m].scenario_high)), H3),
            trow("시나리오 주의 이상 탐지율", ["rules", "fused", "anomaly"].map((m) => percent(sub[m].scenario_caution)), H3),
            trow("정상 거래 고위험률", ["rules", "fused", "anomaly"].map((m) => percent(sub[m].normal_high_rate, 2)), H3),
            trow("정상 거래 알림률(주의 이상)", ["rules", "fused", "anomaly"].map((m) => percent(sub[m].normal_alert_rate, 2)), H3)))),
        h("p", { class: "muted eval-note", text: `seed ${ref.seeds} 검증 세트(룰 보완에 쓰지 않은 세트). ${ref.note}` }),
        h("p", { class: "muted eval-note", text: "이 앱 안의 AI 엔진은 PC판과 같은 코드예요. 아래 직접 다시 계산해 보기는 seed 1부터 계산해서 값이 달라요." }));
    } catch (e) {
      fill(refSlot, h("div", { class: "notice" }, icon("info"), h("p", { text: "보고서 수치 파일을 읽지 못했어요." })));
    }

    async function run() {
      const modes = modeBoxes.filter((b) => b.checked).map((b) => b.value);
      if (!modes.length) { fill(runOut, h("p", { class: "error-text", role: "alert", text: "방식을 하나 이상 골라 주세요." })); return; }
      fill(runOut, h("div", { class: "engine-bar", role: "status" }, h("span", { class: "spinner", "aria-hidden": "true" }), h("span", { text: "계산하고 있어요…" })));
      try {
        const r = await ctx.req("POST", "/api/eval/run", { seeds: parseInt(seeds.value, 10) || 3, modes });
        const ms = r.modes.filter((m) => r.results[m]);
        const res = ms.map((m) => r.results[m]);
        const first = res[0] || {};
        const pick = (fn) => res.map((x) => { try { return fn(x); } catch (e) { return "-"; } });
        const HM = ms.map((m) => MODE_KO[m] || m);
        const codes = Object.keys(first.scenario_recall || {});
        fill(runOut,
          h("p", { class: "muted eval-note", text: `인물 ${r.personas.length}명 × seed ${r.seeds.length}개 = 사례 ${first.n_cases ?? "-"}개. 앞 ${first.baseline_days ?? "-"}일로 배우고 뒤 ${first.eval_days ?? "-"}일을 확인했어요. (${r.elapsed_sec}초)` }),
          h("div", { class: "table-wrap" }, h("table", null, h("caption", { text: "요약" }),
            h("thead", null, h("tr", null, h("th", { text: "지표" }), ms.map((m) => h("th", { text: MODE_KO[m] || m })))),
            h("tbody", null,
              trow("시나리오 찾음 (주의 이상)", pick((x) => `${percent(x.overall.recall_caution)} (${x.overall.caution}/${x.overall.n})`), HM),
              trow("시나리오 찾음 (고위험)", pick((x) => `${percent(x.overall.recall_high)} (${x.overall.high}/${x.overall.n})`), HM),
              trow("평소 거래를 잘못 알림 (주의 이상 비율)", pick((x) => percent(x.normal.alert_rate)), HM),
              trow("평소 거래가 고위험이 됨 (조력자 알림 대상)", pick((x) => percent(x.normal.high_rate)), HM),
              trow("걱정 거래 없는 대조군: 한 달 평균 알림 (건)", pick((x) => (x.control ? num(x.control.monthly_alerts) : "-")), HM),
              trow("걱정 거래 없는 대조군: 한 달 평균 고위험 (건)", pick((x) => (x.control ? num(x.control.monthly_high) : "-")), HM)))),
          codes.length ? h("div", { class: "table-wrap" }, h("table", null, h("caption", { text: "걱정 거래 종류별 찾음 (주의 이상 / 고위험)" }),
            h("thead", null, h("tr", null, h("th", { text: "종류" }), ms.map((m) => h("th", { text: MODE_KO[m] || m })))),
            h("tbody", null, codes.map((code) => trow(SIGNAL_KO[code] || code,
              pick((x) => { const s = x.scenario_recall[code]; return `${percent(s.recall_caution)} / ${percent(s.recall_high)}`; }), HM))))) : null,
          h("p", { class: "muted eval-note", text: `모델: ${[...new Set(res.flatMap((x) => x.model_versions || []))].join(", ") || "-"}` }),
          h("p", { class: "eval-note" }, h("strong", { text: r.note })));
        announce("성능 확인을 마쳤어요.");
      } catch (e) {
        if (e === STALE) return;
        fill(runOut, errorNotice(e, go));
      }
    }

    async function mine() {
      fill(mineOut, h("div", { class: "engine-bar", role: "status" }, h("span", { class: "spinner", "aria-hidden": "true" }), h("span", { text: "계산하고 있어요…" })));
      try {
        const r = await ctx.req("POST", "/api/eval/file");
        const bySignal = Object.entries(r.by_signal || {}).map(([code, n]) => `${SIGNAL_KO[code] || code} ${n}건`).join(", ");
        fill(mineOut,
          h("div", { class: "table-wrap" }, h("table", null, h("caption", { text: "내 거래로 확인한 결과" }),
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
  return h("tr", null, h("th", { scope: "row", text: label }),
    values.map((v, i) => h("td", { class: "num", "data-label": heads[i] || "", text: v })));
}
