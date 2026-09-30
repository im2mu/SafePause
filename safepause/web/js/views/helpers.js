/* 조력자: 내가 믿는 사람. 누구에게, 언제, 무엇을 알릴지 내가 정한다(S22·S37).
 * 한 사람씩 시트에서 고치고 '저장하기'를 누를 때만 저장한다. 저장하지 않은 입력이 있으면 닫기 전에 묻는다(리뷰 M2). */
import { h, icon, fill, openSheet, confirmSheet, busy, toast, announce, skeleton, emptyState } from "../ui.js";
import { errorNotice } from "../components.js";
import { SIGNALS, SIGNAL_KO, SIGNAL_ICON } from "../labels.js";
import { STALE } from "../api.js";

const RELATIONS = ["가족", "지역발달장애인지원센터 전담 인력", "친구", "이웃"];
const MAX_HELPERS = 10;

export default {
  title: "조력자",
  back: "more",
  tab: "more",
  async render(ctx) {
    const { main, go } = ctx;
    const consentNote = h("div");
    const listSlot = h("div", null, skeleton(2));
    const status = h("div", { role: "status" });
    const addBtn = h("button", { type: "button", class: "btn weak big block", onclick: () => edit(null) }, icon("plus"), h("span", { text: "조력자 더하기" }));
    fill(main,
      h("h2", { class: "page-title", tabindex: "-1", text: "조력자" }),
      h("p", { class: "page-sub", text: "조력자는 내가 믿는 사람이에요. 누구에게, 언제 알릴지 내가 정해요." }),
      consentNote,
      h("div", { class: "notice" }, icon("helper"), h("div", null,
        h("p", { text: "조력자가 돈을 받는 사람이면 그 조력자에게는 알리지 않아요. 다른 조력자에게만 알려요." }),
        h("p", { text: "알릴 조력자가 없을 때도 있어요. 그때는 상담하는 곳을 알려 줘요." }),
        h("p", { text: "'동의'에서 '상담하는 곳 알려 주기'를 켰을 때만이에요." }))),
      listSlot, addBtn, status);

    let helpers = [];

    function renderList() {
      addBtn.disabled = helpers.length >= MAX_HELPERS;
      if (!helpers.length) { fill(listSlot, emptyState("users", "아직 조력자가 없어요", "'조력자 더하기'를 눌러 주세요.")); return; }
      fill(listSlot, h("div", { class: "list" }, helpers.map((hp, i) => h("button", { type: "button", class: "row", onclick: () => edit(i) },
        h("span", { class: "row-icon blue" }, icon("person")),
        h("span", { class: "row-main" },
          h("span", { class: "row-title", text: hp.relation ? `${hp.name} (${hp.relation})` : hp.name }),
          h("span", { class: "row-sub", text: [hp.min_level === "caution" ? "확인할 때도 알려요" : "꼭 확인할 때만 알려요",
            hp.active === false ? "자동으로 알리기 꺼짐" : null, hp.contact || null].filter(Boolean).join(" · ") })),
        h("span", { class: "row-chev" }, icon("chevron"))))));
    }

    async function save(next) {
      const saved = await ctx.req("PUT", "/api/helpers", next);
      helpers = saved;
      renderList();
      return saved;
    }

    function edit(index) {
      const isNew = index === null;
      const hp = isNew ? { name: "", relation: "", contact: "", identifiers: [], min_level: "high", signal_scope: [], active: true } : helpers[index];
      const noCheck = { spellcheck: "false", autocapitalize: "off", autocorrect: "off", autocomplete: "off" };
      const name = h("input", { class: "input", id: "hp-name", type: "text", maxlength: "30", value: hp.name || "", ...noCheck });
      const relation = h("input", { class: "input", id: "hp-rel", type: "text", maxlength: "40", list: "hp-rel-list", value: hp.relation || "", ...noCheck });
      const contact = h("input", { class: "input", id: "hp-contact", type: "text", maxlength: "60", value: hp.contact || "", ...noCheck, "aria-describedby": "hp-contact-hint" });
      const ids = h("textarea", { class: "input", id: "hp-ids", rows: "2", maxlength: "600", ...noCheck, "aria-describedby": "hp-ids-hint" });
      ids.value = (hp.identifiers || []).join(", ");
      let idsTouched = !isNew;
      ids.addEventListener("input", () => { idsTouched = true; });
      name.addEventListener("input", () => { if (!idsTouched) ids.value = name.value.trim(); });   // 새 조력자: 이름을 계좌번호·이름 칸에도 채움
      const levelHigh = h("input", { type: "radio", name: "hp-level", value: "high", checked: hp.min_level !== "caution" });
      const levelCaution = h("input", { type: "radio", name: "hp-level", value: "caution", checked: hp.min_level === "caution" });
      const scope = new Set(hp.signal_scope || []);
      const allBox = h("input", { type: "checkbox", checked: scope.size === 0 });
      const sigBoxes = SIGNALS.map((code) => h("input", { type: "checkbox", value: code, checked: scope.has(code), disabled: scope.size === 0 }));
      allBox.addEventListener("change", () => sigBoxes.forEach((b) => { b.disabled = allBox.checked; if (allBox.checked) b.checked = false; }));
      const active = h("input", { type: "checkbox", checked: hp.active !== false, "aria-describedby": "hp-active-hint" });
      const err = h("p", { class: "error-text", role: "alert", hidden: true });
      let dirty = false;
      const markDirty = () => { dirty = true; };

      const sheet = openSheet((close) => {
        const form = h("form", { novalidate: true, oninput: markDirty, onchange: markDirty, onsubmit: (e) => e.preventDefault() },
          h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: isNew ? "새 조력자" : `조력자: ${hp.name}` }),
          h("div", { class: "field" }, h("label", { for: "hp-name", text: "이름" }), name),
          h("div", { class: "field" }, h("label", { for: "hp-rel", text: "관계" }), relation,
            h("datalist", { id: "hp-rel-list" }, RELATIONS.map((r) => h("option", { value: r })))),
          h("div", { class: "field" }, h("label", { for: "hp-contact", text: "연락처 (가려서 저장해요)" }), contact,
            h("p", { class: "hint", id: "hp-contact-hint", text: "전화번호는 가운데를, 메일은 앞 두 글자 뒤를 가려서 저장해요. 연락처로 보내는 것은 없어요." })),
          h("div", { class: "field" }, h("label", { for: "hp-ids", text: "이 사람의 계좌번호·이름 (쉼표나 줄바꿈으로 나눠요)" }), ids,
            h("p", { class: "hint", id: "hp-ids-hint", text: "받는 사람이 여기 적은 계좌번호나 이름과 같으면, 이번에는 이 조력자에게 알리지 않아요." })),
          h("fieldset", { class: "field", style: "border:0;padding:0;margin:0 0 1.1rem" },
            h("legend", { class: "field-label", text: "언제 알릴까요?" }),
            h("label", { class: "check-row" }, levelHigh, h("span", { class: "grow", text: "꼭 확인할 때만 (처음 설정)" })),
            h("label", { class: "check-row" }, levelCaution, h("span", { class: "grow", text: "확인할 때도" }))),
          h("fieldset", { class: "field", style: "border:0;padding:0;margin:0 0 1.1rem" },
            h("legend", { class: "field-label", text: "무엇을 알릴까요?" }),
            h("label", { class: "check-row" }, allBox, h("span", { class: "grow", text: "모든 것" })),
            SIGNALS.map((code, i) => h("label", { class: "check-row" }, sigBoxes[i], icon(SIGNAL_ICON[code]), h("span", { class: "grow", text: SIGNAL_KO[code] })))),
          h("label", { class: "check-row" }, active, h("span", { class: "grow", text: "이 조력자에게 자동으로 알리기" })),
          h("p", { class: "hint", id: "hp-active-hint", text: "끄면 자동으로는 알리지 않아요. 카드에서 '조력자에게 물어볼래요'로 고를 때만 알려요." }),
          err,
          h("div", { class: "sheet-actions" },
            h("button", {
              type: "button", class: "btn primary big block",
              onclick: (e) => busy(e.currentTarget, async () => {
                const nm = name.value.trim();
                if (!nm) { err.textContent = "이름을 적어 주세요."; err.hidden = false; name.focus(); return; }
                const all = allBox.checked;
                const sc = all ? [] : sigBoxes.filter((b) => b.checked).map((b) => b.value);
                if (!all && !sc.length) { err.textContent = "알릴 것을 하나 이상 골라 주세요."; err.hidden = false; allBox.focus(); return; }
                const item = {
                  id: hp.id || null, name: nm, relation: relation.value.trim(), contact: contact.value.trim(),
                  identifiers: ids.value.split(/[,\n]/).map((s) => s.trim()).filter(Boolean),
                  min_level: levelCaution.checked ? "caution" : "high", signal_scope: sc, active: active.checked,
                };
                const next = helpers.map((x) => ({ ...x }));
                if (isNew) next.push(item); else next[index] = item;
                try {
                  await save(next);
                  dirty = false;
                  ctx.session.unsaved = null;
                  close();
                  toast(`저장했어요. 조력자 ${helpers.length}명.`);
                  announce("조력자를 저장했어요.");
                } catch (e2) {
                  if (e2 === STALE) return;
                  err.textContent = e2.message; err.hidden = false;
                }
              }),
            }, icon("check"), h("span", { text: "저장하기" })),
            isNew ? null : h("button", {
              type: "button", class: "btn danger-weak big block",
              onclick: async () => {
                const ok = await confirmSheet({ title: `${hp.name}을(를) 뺄까요?`, lines: ["조력자 목록에서 빠져요."], confirmText: "네, 뺄래요", danger: true });
                if (!ok) return;
                try {
                  await save(helpers.filter((_, i) => i !== index));
                  dirty = false; ctx.session.unsaved = null;
                  close();
                  toast("조력자를 뺐어요.");
                } catch (e2) { if (e2 !== STALE) { err.textContent = e2.message; err.hidden = false; } }
              },
            }, icon("trash"), h("span", { text: "이 조력자 빼기" })),
            h("button", { type: "button", class: "btn big block", text: "닫기", onclick: () => tryClose() })));
        return form;
      }, { label: isNew ? "새 조력자" : `조력자 ${hp.name}`, dismissible: false, onEscape: () => tryClose(), onClose: () => { ctx.session.unsaved = null; } });

      async function tryClose() {
        if (dirty) {
          const ok = await confirmSheet({ title: "저장하지 않은 내용이 있어요", lines: ["닫으면 적은 내용이 사라져요."], confirmText: "닫을래요", cancelText: "계속 적을래요" });
          if (!ok) return;
        }
        sheet.close();
      }
      ctx.session.unsaved = async () => {
        if (!dirty) return true;
        return confirmSheet({ title: "저장하지 않은 내용이 있어요", lines: ["다른 화면으로 가면 적은 내용이 사라져요."], confirmText: "나갈래요", cancelText: "계속 적을래요" });
      };
      if (isNew) name.focus();
    }

    try {
      const [list, consent] = await Promise.all([ctx.req("GET", "/api/helpers"), ctx.req("GET", "/api/consent")]);
      helpers = list;
      fill(consentNote, consent.helper_alerts
        ? h("p", { class: "muted", style: "margin:0 .25rem .75rem", text: "조력자에게 알리기: 켜짐." })
        : h("div", { class: "notice orange" }, icon("warning"), h("div", null,
          h("p", { text: "조력자에게 알리기가 꺼져 있어요. 자동으로 알리려면 '동의'에서 켜 주세요." }),
          h("p", { text: "(카드에서 '조력자에게 물어볼래요'를 직접 고르면 그때는 알려요.)" }),
          h("a", { class: "btn sm weak", href: "#/more/consent", style: "margin-top:.5rem" }, icon("toggle"), h("span", { text: "동의로 가기" })))));
      renderList();
    } catch (e) {
      if (e === STALE) return;
      listSlot.replaceChildren();
      fill(status, errorNotice(e, go));
    }
  },
};
