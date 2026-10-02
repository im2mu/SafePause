/* 돈 흐름 차트: SVG를 직접 그린다(외부 라이브러리 없음, document.createElementNS).
 * - 그릴 자리의 실제 폭과 1rem 크기를 재서 SVG 좌표 = 화면 픽셀로 그린다. 그래서 차트 글자는 늘 CSS의 1rem 그대로다.
 * - 폭이나 글자 크기가 바뀌면(화면 돌림·글자 크기 설정) 다시 그린다. 칸이 좁으면 세로 막대 대신 가로 막대로 그린다.
 * - 색은 CSS 클래스로만 준다(.c1~.c5 → --c, .tone-flag → --chart-flag, .dim은 흐리게). 글자는 --text 계열(css/views/home.css).
 * - 차트마다 글로 된 요약(aria-label)과 숨긴 표(srTable)를 둔다. 서버 글(이름 등)은 textContent로만 넣는다.
 */
import { h } from "./ui.js";
import { nf } from "./format.js";

const NS = "http://www.w3.org/2000/svg";
let seq = 0;

function el(tag, attrs = {}, text) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    node.setAttribute(k, typeof v === "number" ? String(Math.round(v * 10) / 10) : String(v));
  }
  if (text !== undefined) node.textContent = String(text);
  return node;
}

/** 차트 눈금용 짧은 금액: 3678290 → "368만", 125000000 → "1.3억", 9500 → "9,500원". */
export function shortWon(value) {
  const n = Math.round(Math.abs(Number(value) || 0));
  if (n < 10000) return `${nf.format(n)}원`;
  if (n < 1e8) return `${nf.format(Math.round(n / 1e4))}만`;
  return `${(Math.round(n / 1e7) / 10).toLocaleString("ko-KR")}억`;
}

/** 화면 읽기 프로그램용 숨긴 표. rows의 첫 칸은 줄 제목(th)이다. */
export function srTable(caption, head, rows) {
  return h("div", { class: "sr-only" },
    h("table", null,
      h("caption", { text: caption }),
      h("thead", null, h("tr", null, head.map((t) => h("th", { scope: "col", text: t })))),
      h("tbody", null, rows.map((r) => h("tr", null, r.map((c, i) => (i === 0 ? h("th", { scope: "row", text: c }) : h("td", { text: c }))))))));
}

// ---- 크기 재기 -------------------------------------------------------------------
let canvasCtx;
function textWidth(text, rem, family, weight) {
  if (canvasCtx === undefined) {
    try { canvasCtx = document.createElement("canvas").getContext("2d"); } catch (e) { canvasCtx = null; }
  }
  const s = String(text ?? "");
  if (!canvasCtx) return s.length * rem;   // 잴 수 없으면 넉넉하게(글자마다 1rem)
  canvasCtx.font = `${weight} ${rem}px ${family}`;
  return canvasCtx.measureText(s).width;
}

/**
 * 자리 폭·1rem이 바뀔 때마다 draw(W, m)을 부른다. m = {rem, width(text, weight)}.
 * 처음에는 자리가 화면에 붙은 뒤 그린다. 같은 크기면 다시 그리지 않는다.
 */
function responsive(wrap, draw, onCleanup) {
  const probe = h("span", { class: "chart-probe", "aria-hidden": "true" });   // 너비 1rem: 글자 크기 설정이 바뀌면 같이 바뀐다
  wrap.append(probe);
  let last = "";
  let frame = 0;
  const run = () => {
    frame = 0;
    if (!wrap.isConnected) return;
    const W = Math.floor(wrap.clientWidth);
    const rem = probe.getBoundingClientRect().width || parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    const key = `${W}|${rem}`;
    if (!W || key === last) return;
    last = key;
    const family = getComputedStyle(wrap).fontFamily || "sans-serif";
    draw(W, { rem, width: (text, weight = 400) => textWidth(text, rem, family, weight) });
  };
  // 크기가 바뀐 그 자리에서 다시 그리면 ResizeObserver가 같은 틀에서 또 불릴 수 있어 다음 틀로 미룬다
  const schedule = () => { if (!frame) frame = window.requestAnimationFrame(run); };
  let ro = null;
  if (typeof window.ResizeObserver === "function") {
    ro = new ResizeObserver(schedule);
    ro.observe(wrap);
    ro.observe(probe);
  } else {
    window.addEventListener("resize", schedule);
  }
  schedule();
  const stop = () => {
    if (ro) ro.disconnect(); else window.removeEventListener("resize", schedule);
    if (frame) window.cancelAnimationFrame(frame);
  };
  if (typeof onCleanup === "function") onCleanup(stop);
  return { redraw: () => { last = ""; schedule(); }, stop };
}

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

// 위쪽만 둥근 세로 막대(바닥은 기준선에 붙어 네모)
function colPath(x, y, w, hgt, r) {
  const rr = Math.min(r, w / 2, hgt);
  return `M${x},${y + hgt}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + hgt}Z`
    .replace(/\d+\.\d+/g, (n) => String(Math.round(Number(n) * 10) / 10));
}

/**
 * 막대 차트(달마다 나간 돈·시간대별 걱정되는 거래). 칸이 넉넉하면 세로 막대, 좁으면(큰 글씨·좁은 화면) 가로 막대.
 * items: [{label, sub?, value, valueText, aria, flag?}]  flag면 막대 끝에 점(걱정되는 거래가 있던 칸)
 * opts:
 *  - label: 차트 전체 요약 글(aria-label)
 *  - tone: "c1"~"c5" 또는 "flag"(걱정되는 거래 색)
 *  - emphasis: "selected"(고른 막대만 진하게) | "max"(가장 큰 막대만 진하게) | "none"
 *  - values: "all"(값 글자 모두) | "auto"(세로 막대에서 모두 들어가면 모두, 아니면 고른 막대만)
 *  - selected, onSelect(i): onSelect가 있으면 막대마다 누를 수 있는 버튼이 된다(화살표 키로 옮김)
 *  - onCleanup: 화면을 떠날 때 크기 감시를 멈추게 넘기는 함수(ctx.onCleanup)
 * 돌려주는 값: {el, select(i)}
 */
export function columnChart(items, opts = {}) {
  const { label = "", tone = "c1", emphasis = "none", values = "all", onSelect = null, onCleanup = null } = opts;
  const interactive = typeof onSelect === "function";
  let selected = Number.isInteger(opts.selected) ? opts.selected : items.length - 1;
  const wrap = h("div", { class: `chart col-chart ${tone === "flag" ? "tone-flag" : tone}` });
  const root = el("svg", { role: interactive ? "group" : "img", "aria-label": label, focusable: "false" });
  wrap.append(root);
  const max = Math.max(1, ...items.map((it) => Number(it.value) || 0));
  const top = Math.max(0, ...items.map((it) => Number(it.value) || 0));

  const strong = (i) => {
    if (emphasis === "selected") return i === selected;
    if (emphasis === "max") return top > 0 && (Number(items[i].value) || 0) === top;
    return true;
  };

  function itemGroup(i) {
    const it = items[i];
    const g = el("g", {
      class: `ch-item${strong(i) ? "" : " dim"}${i === selected && emphasis === "selected" ? " on" : ""}`, "data-i": i,
    });
    if (interactive) {
      g.setAttribute("role", "button");
      g.setAttribute("tabindex", i === selected ? "0" : "-1");
      g.setAttribute("aria-pressed", i === selected ? "true" : "false");
      g.setAttribute("aria-label", it.aria || it.label);
    }
    return g;
  }

  function drawColumns(W, m) {
    const { rem } = m;
    const n = items.length;
    const slot = W / n;
    const barW = clamp(slot * 0.46, Math.min(rem * 0.6, slot - 6), rem * 1.6);
    const showAll = values === "all" || items.every((it) => m.width(it.valueText, 700) <= slot - 4);
    const anyFlag = items.some((it) => it.flag);
    const dotR = Math.max(4, rem * 0.24);
    const hasSub = items.some((it) => it.sub);
    const plotTop = rem * 1.45 + (anyFlag ? dotR * 2 : 0);
    const plotH = clamp(W * 0.36, rem * 4.5, rem * 7.5);
    const base = plotTop + plotH;
    const labelY = base + rem * 1.35;
    const subY = labelY + rem * 1.25;
    const H = Math.ceil((hasSub ? subY : labelY) + rem * 0.45);
    root.setAttribute("viewBox", `0 0 ${W} ${H}`);
    root.setAttribute("width", W);
    root.setAttribute("height", H);
    const nodes = [el("line", { class: "grid", x1: 0, x2: W, y1: base, y2: base })];
    items.forEach((it, i) => {
      const g = itemGroup(i);
      const x0 = i * slot;
      const cx = x0 + slot / 2;
      const v = Number(it.value) || 0;
      const bh = v > 0 ? Math.max(3, (v / max) * plotH) : 0;
      const y = base - bh;
      g.append(el("rect", { class: "ch-hit", x: x0 + 1, y: 0, width: slot - 2, height: H, rx: rem * 0.5 }));
      if (bh) g.append(el("path", { class: "bar", d: colPath(cx - barW / 2, y, barW, bh, Math.min(6, rem * 0.3)) }));
      if (it.flag) g.append(el("circle", { class: "flag-dot", cx, cy: bh ? y : base, r: dotR }));
      if (showAll || i === selected) {
        const tw = m.width(it.valueText, 700);
        const tx = clamp(cx, tw / 2, W - tw / 2);
        const ty = (bh ? y : base) - (it.flag ? dotR + rem * 0.3 : rem * 0.35);
        g.append(el("text", { class: "ch-value", x: tx, y: ty, "text-anchor": "middle" }, it.valueText));
      }
      g.append(el("text", { class: "ch-label", x: cx, y: labelY, "text-anchor": "middle" }, it.label));
      if (it.sub) g.append(el("text", { class: "ch-sub", x: cx, y: subY, "text-anchor": "middle" }, it.sub));
      nodes.push(g);
    });
    root.replaceChildren(...nodes);
  }

  // 가로 막대: 1줄 이름(+시간)·오른쪽 값, 아래 줄 바탕 띠 위 막대(홈 많이 보낸 곳 막대와 같은 모양). 값 글자는 늘 모두 쓴다
  function drawRows(W, m) {
    const { rem } = m;
    const barH = Math.max(10, rem * 0.55);
    const dotR = Math.max(4, rem * 0.24);
    const lineH = rem * 1.3;
    const valW = Math.max(...items.map((it) => m.width(it.valueText, 700)));
    const head = (it) => m.width(it.label, 600) + (it.flag ? dotR * 3 : 0);
    // 이름 옆에 시간까지 한 줄에 들어가면 한 줄, 아니면 모든 줄에서 시간을 둘째 줄로 내린다(줄 높이를 같게)
    const subInline = items.every((it) => !it.sub || head(it) + rem * 0.35 + m.width(it.sub) + rem * 0.6 + valW <= W);
    const subLine = !subInline && items.some((it) => it.sub);
    const textH = lineH * (subLine ? 2 : 1);
    const rowH = textH + rem * 0.3 + barH + rem * 0.8;
    const H = Math.ceil(rowH * items.length - rem * 0.5);
    root.setAttribute("viewBox", `0 0 ${W} ${H}`);
    root.setAttribute("width", W);
    root.setAttribute("height", H);
    const nodes = items.map((it, i) => {
      const g = itemGroup(i);
      const y0 = i * rowH;
      const base1 = y0 + rem * 1.0;
      const v = Number(it.value) || 0;
      const bw = v > 0 ? Math.max(barH, (v / max) * W) : 0;
      const by = y0 + textH + rem * 0.3;
      g.append(el("rect", { class: "ch-hit", x: 0, y: y0, width: W, height: rowH - rem * 0.3, rx: rem * 0.5 }));
      const labelW = m.width(it.label, 600);
      const t = el("text", { class: "ch-label", x: 0, y: base1 }, it.label);
      let dotX = labelW + dotR * 2;
      if (it.sub && subInline) {
        t.append(el("tspan", { class: "ch-sub", dx: rem * 0.35 }, it.sub));
        dotX = labelW + rem * 0.35 + m.width(it.sub) + dotR * 2;
      }
      g.append(t);
      if (it.sub && subLine) g.append(el("text", { class: "ch-sub", x: 0, y: base1 + lineH }, it.sub));
      if (it.flag) g.append(el("circle", { class: "flag-dot", cx: Math.min(dotX, W - valW - dotR * 2), cy: base1 - rem * 0.35, r: dotR }));
      g.append(el("text", { class: "ch-value", x: W, y: base1, "text-anchor": "end" }, it.valueText));
      g.append(el("rect", { class: "track", x: 0, y: by, width: W, height: barH, rx: barH / 2 }));
      if (bw) g.append(el("rect", { class: "bar", x: 0, y: by, width: bw, height: barH, rx: barH / 2 }));
      return g;
    });
    root.replaceChildren(...nodes);
  }

  let lastSize = null;
  function draw(W, m) {
    lastSize = [W, m];
    const slot = W / Math.max(1, items.length);
    const fits = items.every((it) => Math.max(m.width(it.label, 600), it.sub ? m.width(it.sub) : 0) <= slot - 4);
    wrap.classList.toggle("rows", !fits);
    if (fits) drawColumns(W, m); else drawRows(W, m);
  }
  const watcher = responsive(wrap, draw, onCleanup);

  function select(i, focus = false) {
    const next = clamp(i, 0, items.length - 1);
    if (next === selected && !focus) return;
    const changed = next !== selected;
    selected = next;
    if (lastSize) draw(...lastSize); else watcher.redraw();
    if (focus) {
      const g = root.querySelector(`[data-i="${next}"]`);
      if (g) g.focus();
    }
    if (changed && interactive) onSelect(next);
  }

  if (interactive) {
    root.addEventListener("click", (e) => {
      const g = e.target.closest && e.target.closest(".ch-item");
      if (g) select(Number(g.getAttribute("data-i")), true);
    });
    root.addEventListener("keydown", (e) => {
      const g = e.target.closest && e.target.closest(".ch-item");
      if (!g) return;
      const i = Number(g.getAttribute("data-i"));
      const n = items.length;
      let next = null;
      if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = (i - 1 + n) % n;
      else if (e.key === "ArrowRight" || e.key === "ArrowDown") next = (i + 1) % n;
      else if (e.key === "Home") next = 0;
      else if (e.key === "End") next = n - 1;
      else if (e.key === "Enter" || e.key === " ") next = i;
      if (next === null) return;
      e.preventDefault();
      select(next, true);
    });
  }
  return { el: wrap, select };
}

/**
 * 가로 비율 막대(어디에 썼나요). items: [{label, share(0~1), cls("c1"~"c5")}]
 * 조각 사이는 2px 틈(카드 바탕색), 양 끝은 둥글게. 아주 작은 조각도 4px은 보이게 한다.
 * opts: {label(요약 글), onCleanup}. 돌려주는 값: {el}
 */
export function ratioBar(items, { label = "", onCleanup = null } = {}) {
  const parts = items.filter((it) => Number(it.share) > 0);
  const wrap = h("div", { class: "chart ratio-chart" });
  const root = el("svg", { role: "img", "aria-label": label, focusable: "false" });
  wrap.append(root);
  const clipId = `sp-ratio-${++seq}`;
  responsive(wrap, (W, m) => {
    const H = Math.round(Math.max(14, m.rem * 0.8));
    const gap = 2;
    const avail = Math.max(1, W - gap * Math.max(0, parts.length - 1));
    const total = parts.reduce((s, p) => s + Number(p.share), 0) || 1;
    const widths = parts.map((p) => Math.max(4, (Number(p.share) / total) * avail));
    const over = widths.reduce((s, w) => s + w, 0) - avail;
    if (over > 0 && widths.length) {   // 작은 조각을 4px로 키운 만큼 가장 큰 조각에서 뺀다
      const big = widths.indexOf(Math.max(...widths));
      widths[big] = Math.max(4, widths[big] - over);
    }
    root.setAttribute("viewBox", `0 0 ${W} ${H}`);
    root.setAttribute("width", W);
    root.setAttribute("height", H);
    const clip = el("clipPath", { id: clipId });
    clip.append(el("rect", { x: 0, y: 0, width: W, height: H, rx: H / 2 }));
    const g = el("g", { "clip-path": `url(#${clipId})` });
    let x = 0;
    parts.forEach((p, i) => {
      g.append(el("rect", { class: `seg ${p.cls || "c1"}`, x, y: 0, width: widths[i], height: H }));
      x += widths[i] + gap;
    });
    root.replaceChildren(el("defs"), g);
    root.firstChild.append(clip);
    if (!parts.length) root.replaceChildren(el("rect", { class: "track", x: 0, y: 0, width: W, height: H, rx: H / 2 }));
  }, onCleanup);
  return { el: wrap };
}
