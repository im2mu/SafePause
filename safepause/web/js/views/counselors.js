/* 상담하는 곳: 걱정되는 일이 생기면 알릴 센터·기관을 내가 직접 정한다(R11).
 * 추천 목록(확인된 번호만, 서버 presets)은 한 번 눌러 더하고, 직접 더하거나 고칠 수 있다.
 * 목록 전체를 PUT /api/counselors로 저장한다(조력자와 같은 방식). 저장하지 않은 입력이 있으면 닫기 전에 묻는다. */
import { h, icon, fill, openSheet, confirmSheet, busy, toast, announce, skeleton, emptyState } from "../ui.js";
import { errorNotice } from "../components.js";
import { COUNSELOR_KINDS, COUNSELOR_KIND_KO, COUNSELOR_KIND_ICON } from "../labels.js";
import { canPickContact, pickContact } from "../native.js";
import { STALE } from "../api.js";

const MAX_COUNSELORS = 20;
const NO_CHECK = { spellcheck: "false", autocapitalize: "off", autocorrect: "off", autocomplete: "off" };
const PHONE_OK = /^[0-9+\-\s()]{0,20}$/;               // 서버 models.PHONE_RE와 같음
const EMAIL_OK = /^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$/;   // 서버 models.EMAIL_RE와 같음
const digitsOf = (v) => String(v || "").replace(/\D/g, "");

export default {
  title: "상담하는 곳",
  back: "more",
  tab: "more",
  async render(ctx) {
    const { main, go } = ctx;
    const consentNote = h("div");
    const listSlot = h("div", null, skeleton(2));
    const presetSlot = h("div");
    const status = h("div", { role: "status" });
    const addBtn = h("button", { type: "button", class: "btn weak big block page-btn", onclick: () => edit(null) }, icon("plus"), h("span", { text: "직접 더하기" }));
    const sendBtn = h("a", { class: "btn primary big block page-btn", href: "#/send?to=counselors", hidden: true }, icon("send"), h("span", { text: "상담하는 곳에 알림 보내기" }));
    fill(main,
      h("h2", { class: "page-title", tabindex: "-1", text: "상담하는 곳" }),
      h("p", { class: "page-sub", text: "걱정되는 일이 생기면 알릴 센터나 기관이에요. 알릴 곳은 내가 정해요." }),
      consentNote,
      h("h3", { class: "section-title", text: "내 상담하는 곳" }),
      listSlot, sendBtn, status,
      presetSlot,
      h("h3", { class: "section-title", text: "목록에 없는 곳" }),
      addBtn);

    let items = [];
    let presets = [];

    // 추천과 이미 더한 곳이 같은지: 이름이 같거나 번호가 같으면 같은 곳으로 본다
    const added = (p) => items.some((c) => c.name === p.name || (digitsOf(p.phone) && digitsOf(c.phone) === digitsOf(p.phone)));

    function renderAll() {
      addBtn.disabled = items.length >= MAX_COUNSELORS;
      sendBtn.hidden = !items.some((c) => c.active !== false && (c.phone || c.email));
      if (!items.length) {
        fill(listSlot, h("div", { class: "card flat" }, emptyState("building", "아직 상담하는 곳이 없어요", "아래 추천에서 골라 더하거나 직접 더해 주세요.")));
      } else {
        fill(listSlot, h("div", { class: "list full-title" }, items.map((c, i) => h("button", { type: "button", class: "row", onclick: () => edit(i),
          "aria-label": [c.name, COUNSELOR_KIND_KO[c.kind] || "", c.phone, c.email, c.active === false ? "쓰지 않음" : ""].filter(Boolean).join(", ") },
          h("span", { class: `row-icon ${c.active === false ? "" : "blue"}`.trim() }, icon(COUNSELOR_KIND_ICON[c.kind] || "building")),
          h("span", { class: "row-main" },
            h("span", { class: "row-title", text: c.name }),
            h("span", { class: "row-sub", text: COUNSELOR_KIND_KO[c.kind] || COUNSELOR_KIND_KO.other }),
            [c.phone, c.email].filter(Boolean).map((v) => h("span", { class: "row-sub tnum", text: v })),
            !c.phone && !c.email ? h("span", { class: "row-sub", text: "연락처가 없어요" }) : null,
            c.active === false ? h("span", { class: "row-tags" }, h("span", { class: "badge grey", text: "쓰지 않음" })) : null),
          h("span", { class: "row-chev" }, icon("chevron"))))));
      }
      const left = presets.filter((p) => !added(p));
      fill(presetSlot, left.length ? [
        h("h3", { class: "section-title", text: "추천하는 곳" }),
        h("div", { class: "preset-list" }, left.map((p) => presetCard(p))),
      ] : null);
    }

    function presetCard(p) {
      const needNumber = !p.phone && !p.email;   // 지역마다 번호가 다른 곳: 번호를 적고 더한다
      return h("article", { class: "card preset-card", "aria-label": p.name },
        h("div", { class: "preset-top" },
          h("span", { class: "row-icon blue" }, icon(COUNSELOR_KIND_ICON[p.kind] || "building")),
          h("div", { class: "preset-main" },
            h("b", { class: "preset-name", text: p.name }),
            p.phone ? h("span", { class: "preset-phone tnum" }, icon("call"), h("span", { text: p.phone })) : null)),
        p.memo ? h("p", { class: "muted", text: p.memo }) : null,
        h("button", {
          type: "button", class: `btn ${needNumber ? "weak" : "primary"} block`, disabled: items.length >= MAX_COUNSELORS,
          onclick: (e) => (needNumber ? edit(null, p) : busy(e.currentTarget, () => addPreset(p))),
        }, icon(needNumber ? "edit" : "plus"), h("span", { text: needNumber ? "번호 적고 더하기" : "더하기" })));
    }

    async function save(next) {
      const r = await ctx.req("PUT", "/api/counselors", next);
      items = r.items || [];
      renderAll();
      return items;
    }

    async function addPreset(p) {
      try {
        await save([...items.map(toPayload), toPayload({ ...p, id: null, active: true })]);
        status.replaceChildren();
        toast(`${p.name}을(를) 더했어요.`);
        announce("상담하는 곳을 더했어요.");
      } catch (e) {
        if (e === STALE) return;
        fill(status, errorNotice(e, go));
      }
    }

    function edit(index, preset = null) {
      const isNew = index === null;
      const c = isNew ? { name: "", kind: "other", phone: "", email: "", memo: "", active: true, ...(preset || {}) } : items[index];
      const name = h("input", { class: "input", id: "cs-name", type: "text", maxlength: "30", value: c.name || "", ...NO_CHECK });
      const kind = h("select", { class: "input", id: "cs-kind" },
        COUNSELOR_KINDS.map((k) => h("option", { value: k, text: COUNSELOR_KIND_KO[k], selected: k === (c.kind || "other") })));
      const phone = h("input", { class: "input tnum", id: "cs-phone", type: "tel", inputmode: "tel", maxlength: "20", value: c.phone || "", ...NO_CHECK, "aria-describedby": "cs-phone-err" });
      const email = h("input", { class: "input", id: "cs-email", type: "email", inputmode: "email", maxlength: "80", value: c.email || "", ...NO_CHECK, "aria-describedby": "cs-email-err" });
      const memo = h("textarea", { class: "input", id: "cs-memo", rows: "2", maxlength: "100", ...NO_CHECK, "aria-describedby": "cs-memo-hint" });
      memo.value = c.memo || "";
      const phoneErr = h("p", { class: "error-text", id: "cs-phone-err", hidden: true });
      const emailErr = h("p", { class: "error-text", id: "cs-email-err", hidden: true });
      const active = h("input", { type: "checkbox", checked: c.active !== false, "aria-describedby": "cs-active-hint" });
      const err = h("p", { class: "error-text", role: "alert", hidden: true });
      let dirty = Boolean(preset);   // 추천에서 연 시트는 아직 저장 전이다
      const markDirty = () => { dirty = true; };
      const fieldErr = (input, p, msg) => {
        input.setAttribute("aria-invalid", msg ? "true" : "false");
        p.textContent = msg || "";
        p.hidden = !msg;
      };
      phone.addEventListener("input", () => fieldErr(phone, phoneErr, ""));
      email.addEventListener("input", () => fieldErr(email, emailErr, ""));

      // 연락처에서 불러오기(쓸 수 없는 PC에서는 버튼을 숨김)
      function pickBtn(kindName, input, errP) {
        if (!canPickContact()) return null;
        return h("button", { type: "button", class: "btn sm weak", onclick: async () => {
          const r = await pickContact(kindName);
          if (!r) return;
          input.value = kindName === "phone" ? r.value.replace(/[^\d+\-\s()]/g, "").slice(0, 20) : r.value.trim().slice(0, 80);
          if (!name.value.trim() && r.name) name.value = r.name.slice(0, 30);
          fieldErr(input, errP, "");
          markDirty();
          announce(kindName === "phone" ? "번호를 불러왔어요." : "메일을 불러왔어요.");
          input.focus();
        } }, icon("contacts"), h("span", { text: "연락처에서 불러오기" }));
      }

      const title = isNew ? (preset ? preset.name : "새 상담하는 곳") : c.name;
      const sheet = openSheet((close) => h("form", { novalidate: true, oninput: markDirty, onchange: markDirty, onsubmit: (e) => e.preventDefault() },
        h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: title }),
        preset && preset.memo ? h("p", { class: "sheet-sub", text: preset.memo }) : null,
        h("div", { class: "field" }, h("label", { for: "cs-name", text: "이름" }), name),
        h("div", { class: "field" }, h("label", { for: "cs-kind", text: "종류" }), kind),
        h("div", { class: "field" },
          h("div", { class: "field-head" }, h("label", { for: "cs-phone", text: "전화번호" }), pickBtn("phone", phone, phoneErr)),
          phone, phoneErr),
        h("div", { class: "field" },
          h("div", { class: "field-head" }, h("label", { for: "cs-email", text: "이메일" }), pickBtn("email", email, emailErr)),
          email, emailErr,
          h("p", { class: "hint", text: "전화번호나 이메일 중 하나는 적어 주세요." })),
        h("div", { class: "field" }, h("label", { for: "cs-memo", text: "메모" }), memo,
          h("p", { class: "hint", id: "cs-memo-hint", text: "담당자 이름이나 여는 시간을 적어 두면 좋아요. 100자까지 적을 수 있어요." })),
        h("label", { class: "check-row auto-row" }, active, h("span", { class: "grow strong", text: "이 곳에 알리기" })),
        h("p", { class: "hint", id: "cs-active-hint", text: "끄면 목록에는 남지만 이 곳에는 알리지 않아요." }),
        err,
        h("div", { class: "sheet-actions" },
          h("button", {
            type: "button", class: "btn primary big block",
            onclick: (e) => busy(e.currentTarget, async () => {
              const nm = name.value.trim();
              const ph = phone.value.trim();
              const em = email.value.trim();
              err.hidden = true;
              if (!nm) { err.textContent = "이름을 적어 주세요."; err.hidden = false; name.focus(); return; }
              if (ph && (!PHONE_OK.test(ph) || !/\d/.test(ph))) { fieldErr(phone, phoneErr, "전화번호는 숫자로 적어 주세요."); phone.focus(); return; }
              if (em && !EMAIL_OK.test(em)) { fieldErr(email, emailErr, "이메일 모양이 아니에요."); email.focus(); return; }
              if (!ph && !em) { fieldErr(phone, phoneErr, "전화번호나 이메일 중 하나는 적어 주세요."); phone.focus(); return; }
              const item = { id: c.id || null, name: nm, kind: kind.value, phone: ph, email: em, memo: memo.value.trim(), active: active.checked };
              const next = items.map(toPayload);
              if (isNew) next.push(item); else next[index] = item;
              try {
                await save(next);
                dirty = false;
                ctx.session.unsaved = null;
                close();
                toast(`저장했어요. 상담하는 곳 ${items.length}곳.`);
                announce("상담하는 곳을 저장했어요.");
              } catch (e2) {
                if (e2 === STALE) return;
                err.textContent = e2.message; err.hidden = false;
              }
            }),
          }, icon("check"), h("span", { text: isNew ? "더하기" : "저장하기" })),
          isNew ? null : h("button", {
            type: "button", class: "btn danger-weak big block",
            onclick: async () => {
              const ok = await confirmSheet({ title: `${c.name}을(를) 뺄까요?`, lines: ["상담하는 곳 목록에서 빠져요."], confirmText: "네, 뺄래요", danger: true });
              if (!ok) return;
              try {
                await save(items.filter((_, i) => i !== index).map(toPayload));
                dirty = false; ctx.session.unsaved = null;
                close();
                toast("상담하는 곳을 뺐어요.");
              } catch (e2) { if (e2 !== STALE) { err.textContent = e2.message; err.hidden = false; } }
            },
          }, icon("trash"), h("span", { text: "이 곳 빼기" })),
          h("button", { type: "button", class: "btn big block", text: "닫기", onclick: () => tryClose() }))),
      { label: title, dismissible: false, onEscape: () => tryClose(), onClose: () => { ctx.session.unsaved = null; },
        initialFocus: preset ? "#cs-phone" : null });

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
      if (isNew && !preset) name.focus();
    }

    try {
      const [r, consent] = await Promise.all([ctx.req("GET", "/api/counselors"), ctx.req("GET", "/api/consent")]);
      items = r.items || [];
      presets = r.presets || [];
      fill(consentNote, consent.counseling_referral
        ? h("p", { class: "muted consent-state" }, icon("check-line"), h("span", { text: "상담하는 곳에 알려 주기: 켜짐" }))
        : h("div", { class: "notice orange" }, icon("warning"), h("div", null,
          h("p", { text: "상담하는 곳에 알려 주기가 꺼져 있어요. 꼭 확인할 일이 자주 생길 때 안내를 받으려면 동의 화면에서 켜 주세요." }),
          h("p", { text: "알림 보내기에서는 언제든지 직접 알릴 수 있어요." }),
          h("a", { class: "btn sm weak notice-action", href: "#/more/consent" }, icon("toggle"), h("span", { text: "동의로 가기" })))));
      renderAll();
    } catch (e) {
      if (e === STALE) return;
      listSlot.replaceChildren();
      fill(status, errorNotice(e, go));
    }
  },
};

// 저장 요청 모양(서버 CounselorIn)
function toPayload(x) {
  return {
    id: x.id || null, name: x.name, kind: COUNSELOR_KINDS.includes(x.kind) ? x.kind : "other",
    phone: x.phone || "", email: x.email || "", memo: x.memo || "", active: x.active !== false,
  };
}
