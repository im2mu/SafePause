/* 결과 내보내기(보호자·심사용): 현장 검증용 요약 파일, 분석 결과 표 파일(옛 내 데이터 화면의 내보내기).
 * 앱은 시스템 저장 창, PC는 내려받기로 저장한다(components.saveFile). 번호·메일 원본은 파일에 넣지 않는다(서버). */
import { h, icon, fill, busy, toast, announce, comingSoonSheet } from "../ui.js";
import { errorNotice, saveFile, menuRow } from "../components.js";
import { deviceWord } from "../format.js";
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
    fill(main,
      h("h2", { class: "page-title", tabindex: "-1", text: "결과 내보내기" }),
      h("p", { class: "page-sub", text: `보호자와 심사하는 사람이 보는 파일이에요. 파일은 ${deviceWord()}에 저장해요.` }),
      h("div", { class: "export-list" }, FILES.map((f) => fileCard(f))),
      out,
      h("h3", { class: "section-title", text: "정식 버전에서 더할 것" }),
      h("div", { class: "list" },
        menuRow({ icon: "doc", title: "보호자용 보고서(PDF)", soon: true, onclick: () => comingSoonSheet({
          icon: "doc", title: "보호자용 보고서(PDF)",
          lines: ["한 달 동안의 돈 흐름과 걱정되는 거래를 한 장으로 정리해요.", "인쇄하거나 상담하는 곳에 보여 줄 수 있어요."],
          action: "만들기" }) })));

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
        const msg = st === "saved" ? "저장했어요." : st === "cancelled" ? "저장하지 않았어요." : "저장하지 못했어요.";
        toast(msg, st === "error" ? "error" : "");
        announce(msg);
        if (r.note) fill(out, h("div", { class: "notice orange" }, icon("info"), h("p", { text: r.note })));
        else out.replaceChildren();
      } catch (err) {
        if (err === STALE) return;
        fill(out, errorNotice(err, go));
      }
    }
  },
};
