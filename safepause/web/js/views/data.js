/* 내 데이터: 내보내기(선택 사항 '샘플 결과물'·현장 검증 요약)와 모두 지우기(즉시 철회권). */
import { h, icon, fill, busy, confirmSheet, toast, announce } from "../ui.js";
import { errorNotice, saveFile } from "../components.js";
import { STALE, MODE } from "../api.js";

export default {
  title: "내 데이터",
  back: "more",
  tab: "more",
  async render(ctx) {
    const { main, go } = ctx;
    const where = MODE === "engine" ? "이 기기" : "이 컴퓨터";
    const exportOut = h("div", { "aria-live": "polite" });
    const wipeOut = h("div", { "aria-live": "polite" });
    fill(main,
      h("h2", { class: "page-title", tabindex: "-1", text: "내 데이터" }),
      h("p", { class: "page-sub", text: `SafePause가 쓰는 데이터는 모두 ${where} 안에만 있어요.` }),

      h("h3", { class: "section-title", text: "내보내기" }),
      h("div", { class: "list" },
        exportRow("file", "현장 검증용 요약 파일", "이름·계좌·금액·날짜 없이 거래 수와 알림 수만 담아요. 시범 사용 결과를 모을 때 본인이 동의하고 직접 전달해요.", "/api/export/validation"),
        exportRow("download", "내 분석 결과 표 파일", "거래마다 판단 결과를 담아요. 받는 사람 이름이 들어 있어서 나만 봐요.", "/api/export/results")),
      exportOut,

      h("h3", { class: "section-title", text: "모두 지우기" }),
      h("div", { class: "card" },
        h("p", { text: `${where}에 저장한 것을 모두 지워요. 지우면 되돌릴 수 없어요.` }),
        h("ul", { style: "list-style:disc;padding-left:1.2rem;margin:.5rem 0 1rem;color:var(--text-2)" },
          ["동의한 것", "조력자", "거래", "내가 고른 것", "조력자 알림 기록"].map((t) => h("li", { text: t }))),
        h("button", { type: "button", class: "btn danger big block", onclick: (e) => busy(e.currentTarget, wipe) }, icon("trash"), h("span", { text: "모두 지우기" }))),
      wipeOut);

    function exportRow(ic, title, sub, path) {
      return h("button", {
        type: "button", class: "row",
        onclick: (e) => busy(e.currentTarget, async () => {
          try {
            const r = await ctx.req("GET", path);
            const status = await saveFile(r.filename, r.mime, r.text);
            if (status === "saved") toast("저장했어요.");
            else if (status === "cancelled") toast("저장하지 않았어요.");
            else toast("저장하지 못했어요.", "error");
            if (r.note) fill(exportOut, h("div", { class: "notice orange" }, icon("info"), h("p", { text: r.note })));
            else exportOut.replaceChildren();
          } catch (err) {
            if (err === STALE) return;
            fill(exportOut, errorNotice(err, go));
          }
        }),
      }, h("span", { class: "row-icon blue" }, icon(ic)),
      h("span", { class: "row-main" }, h("span", { class: "row-title", text: title }), h("span", { class: "row-sub", style: "white-space:normal", text: sub })),
      h("span", { class: "row-chev" }, icon("chevron")));
    }

    async function wipe() {
      const ok = await confirmSheet({
        title: "정말 모두 지울까요?", lines: ["되돌릴 수 없어요."], confirmText: "네, 지울래요", cancelText: "아니요", danger: true,
      });
      if (!ok) return;
      ctx.session.bumpEpoch();   // 지우는 즉시 옛 분석 응답을 버린다(리뷰 H1)
      try {
        const r = await ctx.req("POST", "/api/wipe");
        ctx.session.consent = null;
        try { sessionStorage.removeItem("safepause.onboard.later"); } catch (e) { /* 무시 */ }
        fill(wipeOut, h("div", { class: "notice green", role: "status" }, icon("check"), h("p", { text: r.message })));
        toast(r.message);
        announce(r.message);
      } catch (err) {
        if (err === STALE) return;
        fill(wipeOut, errorNotice(err, go));
      }
    }
  },
};
