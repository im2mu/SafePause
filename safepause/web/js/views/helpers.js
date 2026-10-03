/* 조력자: 내가 믿는 사람. 누구에게, 언제, 무엇을 알릴지 내가 정한다(S22·S37).
 * 휴대폰 번호·이메일 원본은 이 휴대폰(이 컴퓨터)에만 저장한다(문자·메일 앱을 열 때 씀). 목록에는 가린 번호·메일만 보인다.
 * v0.2에서 옮겨 온 가린 연락처(원본 없음)는 서버가 지킨다. 지우려면 시트에서 옛 연락처 지우기를 고른다(clear_contact, BE-8).
 * 한 사람씩 시트에서 고치고 저장하기를 누를 때만 저장한다. 저장하지 않은 입력이 있으면 닫기 전에 묻는다(리뷰 M2). */
import { h, icon, fill, setText, openSheet, confirmSheet, busy, toast, announce, skeleton, emptyState } from "../ui.js";
import { errorNotice, menuRow } from "../components.js";
import { SIGNALS, SIGNAL_KO, SIGNAL_ICON } from "../labels.js";
import { canPickContact, pickContact } from "../native.js";
import { breakableEmail } from "../format.js";
import { STALE } from "../api.js";

const RELATIONS = ["가족", "지역발달장애인지원센터 전담 인력", "친구", "이웃"];
const MAX_HELPERS = 10;
const NO_CHECK = { spellcheck: "false", autocapitalize: "off", autocorrect: "off", autocomplete: "off" };
const PHONE_OK = /^[0-9+\-\s()]{0,20}$/;               // 서버 models.PHONE_RE와 같음
const EMAIL_OK = /^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$/;   // 서버 models.EMAIL_RE와 같음

export default {
  title: "조력자",
  back: "more",
  tab: "more",
  async render(ctx) {
    const { main, go } = ctx;
    const consentNote = h("div");
    const listSlot = h("div", null, skeleton(2));
    const status = h("div", { role: "status" });
    const addBtn = h("button", { type: "button", class: "btn primary big block page-btn", onclick: () => edit(null) }, icon("plus"), h("span", { text: "조력자 더하기" }));
    fill(main,
      h("h2", { class: "page-title", tabindex: "-1", text: "조력자" }),
      h("p", { class: "page-sub", text: "조력자는 내가 믿는 사람이에요. 누구에게, 언제 알릴지 내가 정해요." }),
      consentNote, listSlot, addBtn, status,
      h("div", { class: "notice helper-rule" }, icon("info"),
        h("p", { text: "조력자가 돈을 받는 사람이면 그 사람에게는 알리지 않게 골라 둬요. 그때는 다른 조력자나 상담하는 곳에 알릴 수 있어요." })),
      h("div", { class: "list" },
        menuRow({ icon: "building", tone: "blue", title: "상담하는 곳도 정하기", sub: "센터·기관에도 알릴 수 있어요.", href: "#/more/counselors" })));

    let helpers = [];

    function renderList() {
      addBtn.disabled = helpers.length >= MAX_HELPERS;
      if (!helpers.length) {
        fill(listSlot, h("div", { class: "card flat" }, emptyState("users", "아직 조력자가 없어요", "조력자 더하기를 눌러 주세요.")));
        return;
      }
      fill(listSlot, h("div", { class: "list full-title" }, helpers.map((hp, i) => {
        const contacts = [hp.phone_masked, hp.email_masked].filter(Boolean);
        return h("button", { type: "button", class: "row", onclick: () => edit(i),
          "aria-label": [hp.relation ? `${hp.name}, ${hp.relation}` : hp.name, ...contacts, levelText(hp),
            hp.active === false ? "자동 알림 꺼짐" : ""].filter(Boolean).join(", ") },
        h("span", { class: "row-icon blue" }, icon("user-check")),
        h("span", { class: "row-main" },
          h("span", { class: "row-title", text: hp.relation ? `${hp.name} (${hp.relation})` : hp.name }),
          contacts.length
            ? contacts.map((c) => (c === hp.phone_masked
              ? h("span", { class: "row-sub tnum tel-text", text: c })
              : h("span", { class: "row-sub email-text", text: breakableEmail(c) })))
            : h("span", { class: "row-sub", text: "연락처가 없어요" }),
          h("span", { class: "row-tags" },
            hp.phone ? h("span", { class: "tag" }, icon("chat"), h("span", { text: "문자" })) : null,
            hp.email ? h("span", { class: "tag" }, icon("mail"), h("span", { text: "메일" })) : null,
            h("span", { class: "tag", text: levelText(hp) }),
            hp.active === false ? h("span", { class: "badge grey", text: "자동 알림 꺼짐" }) : null)),
        h("span", { class: "row-chev" }, icon("chevron")));
      })));
    }

    async function save(next) {
      const saved = await ctx.req("PUT", "/api/helpers", next);
      helpers = saved;
      renderList();
      return saved;
    }

    function edit(index) {
      const isNew = index === null;
      const hp = isNew ? { name: "", relation: "", phone: "", email: "", identifiers: [], min_level: "high", signal_scope: [], active: true } : helpers[index];
      const name = h("input", { class: "input", id: "hp-name", type: "text", maxlength: "30", value: hp.name || "", ...NO_CHECK });
      const relation = h("input", { class: "input", id: "hp-rel", type: "text", maxlength: "40", list: "hp-rel-list", value: hp.relation || "", ...NO_CHECK });
      const phone = h("input", { class: "input tnum", id: "hp-phone", type: "tel", inputmode: "tel", maxlength: "20", value: hp.phone || "", placeholder: "010-0000-0000", ...NO_CHECK, "aria-describedby": "hp-phone-err" });
      const email = h("input", { class: "input", id: "hp-email", type: "email", inputmode: "email", maxlength: "80", value: hp.email || "", ...NO_CHECK, "aria-describedby": "hp-email-err" });
      const phoneErr = h("p", { class: "error-text", id: "hp-phone-err", hidden: true });
      const emailErr = h("p", { class: "error-text", id: "hp-email-err", hidden: true });
      const ids = h("textarea", { class: "input", id: "hp-ids", rows: "2", maxlength: "600", ...NO_CHECK, "aria-describedby": "hp-ids-hint" });
      ids.value = (hp.identifiers || []).join(", ");
      let idsTouched = !isNew;
      ids.addEventListener("input", () => { idsTouched = true; });
      const syncIds = () => { if (!idsTouched) ids.value = name.value.trim(); };   // 새 조력자: 이름을 계좌번호·이름 칸에도 채움
      name.addEventListener("input", syncIds);
      const levelHigh = h("input", { type: "radio", name: "hp-level", value: "high", checked: hp.min_level !== "caution" });
      const levelCaution = h("input", { type: "radio", name: "hp-level", value: "caution", checked: hp.min_level === "caution" });
      const scope = new Set(hp.signal_scope || []);
      const allBox = h("input", { type: "checkbox", checked: scope.size === 0 });
      const sigBoxes = SIGNALS.map((code) => h("input", { type: "checkbox", value: code, checked: scope.has(code), disabled: scope.size === 0 }));
      allBox.addEventListener("change", () => sigBoxes.forEach((b) => { b.disabled = allBox.checked; if (allBox.checked) b.checked = false; }));
      const active = h("input", { type: "checkbox", checked: hp.active !== false, "aria-describedby": "hp-active-hint" });
      const err = h("p", { class: "error-text", role: "alert", hidden: true });
      // v0.2에서 옮겨 온 가린 연락처(원본 없음): 보여 주기만 하고, 지울 때만 clear_contact를 보낸다(BE-8)
      const legacy = isNew || hp.phone || hp.email ? "" : [hp.phone_masked, hp.email_masked].filter(Boolean).join(" · ");
      const clearLegacy = legacy ? h("input", { type: "checkbox", "aria-describedby": "hp-legacy-hint" }) : null;
      let dirty = false;
      const markDirty = () => { dirty = true; };

      // 연락처에서 불러오기(쓸 수 없는 PC에서는 버튼을 숨김). 고른 한 사람의 번호·메일만 받는다
      function pickBtn(kind, input, clearErr) {
        if (!canPickContact()) return null;
        return h("button", { type: "button", class: "btn sm weak", onclick: async () => {
          const c = await pickContact(kind);
          if (!c) return;
          input.value = kind === "phone" ? c.value.replace(/[^\d+\-\s()]/g, "").slice(0, 20) : c.value.trim().slice(0, 80);
          if (!name.value.trim() && c.name) { name.value = c.name.slice(0, 30); syncIds(); }
          clearErr();
          markDirty();
          announce(kind === "phone" ? "번호를 불러왔어요." : "메일을 불러왔어요.");
          input.focus();
        } }, icon("contacts"), h("span", { text: "연락처에서 불러오기" }));
      }
      const fieldErr = (input, p, msg) => {
        input.setAttribute("aria-invalid", msg ? "true" : "false");
        setText(p, msg || "");
        p.hidden = !msg;
      };
      phone.addEventListener("input", () => fieldErr(phone, phoneErr, ""));
      email.addEventListener("input", () => fieldErr(email, emailErr, ""));

      const sheet = openSheet((close) => {
        const form = h("form", { novalidate: true, oninput: markDirty, onchange: markDirty, onsubmit: (e) => e.preventDefault() },
          h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: isNew ? "새 조력자" : `조력자: ${hp.name}` }),
          h("div", { class: "field" }, h("label", { for: "hp-name", text: "이름" }), name),
          h("div", { class: "field" }, h("label", { for: "hp-rel", text: "관계" }), relation,
            h("datalist", { id: "hp-rel-list" }, RELATIONS.map((r) => h("option", { value: r })))),
          h("div", { class: "field" },
            h("div", { class: "field-head" }, h("label", { for: "hp-phone", text: "휴대폰 번호" }), pickBtn("phone", phone, () => fieldErr(phone, phoneErr, ""))),
            phone, phoneErr),
          h("div", { class: "field" },
            h("div", { class: "field-head" }, h("label", { for: "hp-email", text: "이메일" }), pickBtn("email", email, () => fieldErr(email, emailErr, ""))),
            email, emailErr,
            h("p", { class: "hint", text: "번호나 메일이 있어야 문자·메일로 알릴 수 있어요." })),
          legacy ? h("div", { class: "card flat legacy-contact" },
            h("p", { class: "strong" }, h("span", { text: "옛 연락처: " }), h("span", { class: "tnum", text: legacy })),
            h("p", { class: "hint", id: "hp-legacy-hint", text: "예전 버전에서 가려서 옮겨 온 연락처예요. 가려져 있어서 이 연락처로는 문자·메일을 보낼 수 없어요. 위에 번호나 메일을 새로 적어 주세요." }),
            h("label", { class: "check-row" }, clearLegacy, h("span", { class: "grow", text: "옛 연락처 지우기" }))) : null,
          h("div", { class: "field" }, h("label", { for: "hp-ids", text: "이 사람의 계좌번호·이름" }), ids,
            h("p", { class: "hint", id: "hp-ids-hint", text: "쉼표나 줄바꿈으로 나눠 적어요. 받는 사람이 여기 적은 계좌번호나 이름과 같으면, 이번에는 이 조력자에게 알리지 않아요." })),
          h("fieldset", { class: "field form-group" },
            h("legend", { class: "field-label", text: "언제 알릴까요?" }),
            h("label", { class: "check-row" }, levelHigh, h("span", { class: "grow", text: "꼭 확인할 때만 (처음 설정)" })),
            h("label", { class: "check-row" }, levelCaution, h("span", { class: "grow", text: "확인할 때도" }))),
          h("fieldset", { class: "field form-group" },
            h("legend", { class: "field-label", text: "무엇을 알릴까요?" }),
            h("label", { class: "check-row sig-row" }, allBox, h("span", { class: "sig-ic", "aria-hidden": "true" }, icon("check-line")), h("span", { class: "grow", text: "모든 것" })),
            SIGNALS.map((code, i) => h("label", { class: "check-row sig-row" }, sigBoxes[i],
              h("span", { class: "sig-ic", "aria-hidden": "true" }, icon(SIGNAL_ICON[code])), h("span", { class: "grow", text: SIGNAL_KO[code] })))),
          h("label", { class: "check-row auto-row" }, active, h("span", { class: "grow strong", text: "이 조력자에게 자동으로 알리기" })),
          // 실제 동작: 켜 두면 알릴 때 미리 골라 두고 적어 둔다(보내지는 않음). 끄면 직접 고를 때만
          h("p", { class: "hint", id: "hp-active-hint", text: "켜 두면 걱정되는 거래를 알릴 때 이 사람을 미리 골라 두고 적어 둬요. 끄면 알림 보내기에서 직접 골라요. 보내기는 늘 내가 눌러요." }),
          err,
          h("div", { class: "sheet-actions" },
            h("button", {
              type: "button", class: "btn primary big block",
              onclick: (e) => busy(e.currentTarget, async () => {
                const nm = name.value.trim();
                const ph = phone.value.trim();
                const em = email.value.trim();
                err.hidden = true;
                if (!nm) { setText(err, "이름을 적어 주세요."); err.hidden = false; name.focus(); return; }
                if (ph && (!PHONE_OK.test(ph) || !/\d/.test(ph))) { fieldErr(phone, phoneErr, "전화번호는 숫자로 적어 주세요."); phone.focus(); return; }
                if (em && !EMAIL_OK.test(em)) { fieldErr(email, emailErr, "이메일 모양이 아니에요."); email.focus(); return; }
                const all = allBox.checked;
                const sc = all ? [] : sigBoxes.filter((b) => b.checked).map((b) => b.value);
                if (!all && !sc.length) { setText(err, "알릴 것을 하나 이상 골라 주세요."); err.hidden = false; allBox.focus(); return; }
                const item = {
                  id: hp.id || null, name: nm, relation: relation.value.trim(), phone: ph, email: em,
                  identifiers: ids.value.split(/[,\n]/).map((s) => s.trim()).filter(Boolean),
                  min_level: levelCaution.checked ? "caution" : "high", signal_scope: sc, active: active.checked,
                  ...(clearLegacy && clearLegacy.checked && !ph && !em ? { clear_contact: true } : {}),
                };
                const next = helpers.map(toPayload);
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
                  setText(err, e2.message); err.hidden = false;
                }
              }),
            }, icon("check"), h("span", { text: "저장하기" })),
            isNew ? null : h("button", {
              type: "button", class: "btn danger-weak big block",
              onclick: async () => {
                const who = withObject(hp.name);
                const ok = await confirmSheet({ title: who ? `${who} 뺄까요?` : "이 조력자를 뺄까요?", lines: who ? ["조력자 목록에서 빠져요."] : [[hp.name], ["조력자 목록에서 빠져요."]], confirmText: "네, 뺄래요", danger: true });
                if (!ok) return;
                try {
                  await save(helpers.filter((_, i) => i !== index).map(toPayload));
                  dirty = false; ctx.session.unsaved = null;
                  close();
                  toast("조력자를 뺐어요.");
                } catch (e2) { if (e2 !== STALE) { setText(err, e2.message); err.hidden = false; } }
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
        ? h("p", { class: "muted consent-state" }, icon("check-line"), h("span", { text: "조력자에게 알리기: 켜짐" }))
        : h("div", { class: "notice orange" }, icon("warning"), h("div", null,
          h("p", { text: "조력자에게 알리기가 꺼져 있어요. 알릴 조력자를 미리 골라 두려면 동의 화면에서 켜 주세요. 알림 보내기에서는 언제든지 직접 알릴 수 있어요." }),
          h("a", { class: "btn sm weak notice-action", href: "#/more/consent" }, icon("toggle"), h("span", { text: "동의로 가기" })))));
      renderList();
    } catch (e) {
      if (e === STALE) return;
      listSlot.replaceChildren();
      fill(status, errorNotice(e, go));
    }
  },
};

function levelText(hp) {
  return hp.min_level === "caution" ? "확인할 때도 알림" : "꼭 확인할 때만 알림";
}

/**
 * 이름 뒤에 받침에 맞는 을·를을 붙인다(C11: 을(를) 표기 대신). withObject("엄마") → "엄마를", withObject("경찰 (금융사기 신고)") → "경찰 (금융사기 신고)를".
 * 끝의 괄호·기호는 건너뛰고 마지막 한글(또는 숫자)로 정한다. 영어 등으로 끝나 알 수 없으면 null(부르는 쪽이 다른 말로 쓴다).
 */
const DIGIT_BATCHIM = { 0: true, 1: true, 2: false, 3: true, 4: false, 5: false, 6: true, 7: true, 8: true, 9: false };
export function withObject(name) {
  const s = String(name || "").trim();
  const m = s.match(/([가-힣0-9])[\s)\]}.,·]*$/);
  if (!m) return null;
  const ch = m[1];
  const batchim = /[0-9]/.test(ch) ? DIGIT_BATCHIM[ch] : (ch.charCodeAt(0) - 0xac00) % 28 !== 0;
  return `${s}${batchim ? "을" : "를"}`;
}

// 저장 요청 모양(서버 HelperIn): 가린 표시(phone_masked 등)는 보내지 않는다
function toPayload(x) {
  return {
    id: x.id || null, name: x.name, relation: x.relation || "", phone: x.phone || "", email: x.email || "",
    identifiers: x.identifiers || [], min_level: x.min_level || "high", signal_scope: x.signal_scope || [], active: x.active !== false,
  };
}
