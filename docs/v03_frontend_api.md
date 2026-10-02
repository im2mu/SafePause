# SafePause v0.3 화면 공용 기반 사용 설명서 (화면 담당용)

이 문서는 화면 담당(홈·내 거래·알림 보내기/알림·전체)이 공용 모듈 위에서 화면을 만들 때 보는 문서다.
설계서 `docs/v03_spec.md`가 기준이고, 여기에는 공용 함수·CSS 클래스·아이콘·경로·ctx를 정확히 적는다.
돈 보내기(보내기 전 확인 → 내 은행 앱)는 `docs/v03_spec_money.md`가 기준이다(0절 송금 기능 없음을 고친 문서). 이 문서의 1.5절·5절·7절·14절에 화면 쪽을 적었다.

- 공용 파일(화면 기반 담당): `index.html`, `js/main.js`, `js/api.js`, `js/ui.js`, `js/components.js`, `js/format.js`, `js/labels.js`, `js/icons.js`, `js/speech.js`, `js/native.js`, `js/engine-client.js`, `js/views/connect.js`, `engine/worker.mjs`, `css/app.css`, `tests/test_static_ui.py`.
- 화면 파일(화면 담당): `js/views/*.js`(connect.js 빼고), `css/views/{home,txns,notify,money,more}.css`, `js/charts.js`(홈 담당이 새로 만듦).
- 공용 모듈에 필요한 것이 생기면 직접 고치지 말고 화면 기반 담당(총괄)에게 요청한다.

## 1. 경로와 화면 객체

### 1.1 경로표 (`main.js` ROUTES)

| 경로 | 파일 | 아래 탭 | 비고 |
|---|---|---|---|
| `#/home` | `views/home.js` | 홈 | 머리글에 SafePause 로고가 자동으로 붙는다 |
| `#/txns` | `views/txns.js` | 내 거래 | |
| `#/send` | `views/send.js` | 보내기 | 위 탭 돈 보내기(`views/money.js`) \| 알림 보내기(`views/notify.js`), 1.5절 |
| `#/alerts` | `views/alerts.js` | 알림 | |
| `#/more` | `views/more.js` | 전체 | |
| `#/more/consent` | `views/consent.js` | 전체 | 모두 지우기(맨 아래) 포함 |
| `#/more/helpers` | `views/helpers.js` | 전체 | |
| `#/more/counselors` | `views/counselors.js` | 전체 | 새 화면 |
| `#/more/settings` | `views/settings.js` | 전체 | 새 화면 |
| `#/more/eval` | `views/eval.js` | 전체 | 보호자·심사용 |
| `#/more/export` | `views/export.js` | 전체 | 새 화면(옛 data.js의 내보내기) |
| `#/more/about` | `views/about.js` | 전체 | |
| `#/onboarding` | `views/onboarding.js` | 없음 | |

옛 경로는 자동으로 옮긴다: `#/more/data` → `#/more/consent`, `#/more/notices` → `#/alerts?tab=sent`.
없는 경로는 `#/home`으로 간다. 지운 파일: `views/data.js`, `views/notices.js`.
`views/send.js`는 v0.2의 송금 연습 화면이었고, v0.3에서는 보내기 탭의 틀(위 탭 두 개)로 다시 만들었다. 옛 송금 연습 화면은 `views/money.js`(돈 보내기)로 되살렸다.

화면 파일은 처음 열 때 불러온다(`import()`). 한 화면 파일에 오류가 있어도 다른 화면은 열리고,
그 화면에는 "화면을 불러오지 못했어요." 안내와 `console.error`가 남는다(webcheck의 errors에 잡힘).

### 1.2 주소 뒤 값(`?`)

`#/경로?이름=값` 모양이다. 화면에서는 `ctx.params`(URLSearchParams)로 읽는다.

| 주소 | 뜻 | 읽는 화면 |
|---|---|---|
| `#/send` 또는 `#/send?mode=money` | 돈 보내기 탭(기본) | send.js → money.js |
| `#/send?mode=notify` | 알림 보내기 탭 | send.js → notify.js |
| `#/send?txn=<거래 id>` | 알림 보내기 탭 + 그 거래를 미리 고름(mode가 없어도 txn·to가 있으면 알림 보내기) | notify.js |
| `#/send?to=counselors` | 알림 보내기 탭 + 상담하는 곳 목록을 펼쳐 둠 | notify.js |
| `#/send?mode=notify&txn=<id>&helper=<조력자 id>` | 돈 보내기의 물어볼래요에서 넘어옴: 그 조력자만 미리 체크 | notify.js |
| `#/alerts?tab=cards\|flags\|sent` | 걱정되는 거래 / 담은 거래 / 보낸 알림 탭 | alerts.js |
| `#/txns?open=upload\|sample` | 파일 올리기 / 연습용 거래 시트를 바로 엶 | txns.js (connect.js가 보냄) |

```js
const txnId = ctx.params.get("txn");          // 없으면 null
const tab = ctx.params.get("tab") || "cards";
// 탭을 바꿀 때는 화면을 다시 그리지 않고 주소만 바꾼다(뒤로 가기 기록도 늘지 않음)
ctx.replaceParams({ tab: "sent" });            // → #/alerts?tab=sent, 빈 값·null은 뺀다
// txns.js: 시트를 연 뒤에는 주소에서 open을 지운다(새로 고침에 다시 열리지 않게)
if (ctx.params.get("open") === "upload") { openUpload(); ctx.replaceParams({}); }
```

### 1.3 화면 객체

```js
export default {
  title: "알림 보내기",   // 하위 화면의 머리글 제목·화면 읽기 프로그램 안내
  tab: "send",            // 아래 탭에서 켤 탭(home|txns|send|alerts|more)
  back: "more",           // 하위 화면이면 뒤로 갈 경로(머리글에 뒤로 버튼, 본문 .page-title은 숨겨짐)
  noNav: false,           // true면 아래 탭 숨김(첫 실행)
  noAppbar: false,        // true면 머리글 숨김
  noFocus: false,         // true면 첫 제목 대신 main에 초점
  announce: "",           // 화면을 열 때 읽어 줄 글(없으면 title)
  async render(ctx) { ... },
};
```

- 탭 첫 화면(홈 빼고)은 머리글이 숨겨지고 본문의 `h2.page-title`이 제목이 된다.
- 홈(`tab: "home"`, back 없음)은 머리글에 로고(아이콘 + `SafePause`)를 main.js가 그린다. 홈 본문 제목은 `h2.sr-only` 정도로 둔다.
- 넓은 화면(900px 이상)은 왼쪽 메뉴 위에 로고가 있고, 홈 머리글은 숨겨진다.

### 1.4 ctx

| 필드 | 설명 |
|---|---|
| `ctx.path` | `"send"`, `"more/helpers"` 같은 경로(? 앞) |
| `ctx.params` | `URLSearchParams`(? 뒤) |
| `ctx.main` | 화면을 그릴 `<main>` |
| `ctx.session` | `{epoch, consent, unsaved, bumpEpoch()}` 앱 전체 상태 |
| `ctx.req(method, path, body?, file?)` | API 요청. 화면을 떠났거나 지우기·동의 끄기 뒤 늦게 온 응답은 `STALE`을 던진다 |
| `ctx.alive()` | 아직 이 화면이면 true |
| `ctx.onCleanup(fn)` | 화면을 떠날 때 부를 정리 함수(타이머·리스너) |
| `ctx.setTitle(title, actions?)` | 머리글 제목·오른쪽 버튼 바꾸기 |
| `ctx.go(route, {replace})` | 화면 옮기기. `ctx.go("send?txn=t12")` |
| `ctx.replaceParams(obj)` | 다시 그리지 않고 ? 뒤만 바꾸기 |

```js
import { STALE } from "../api.js";
try {
  const d = await ctx.req("GET", "/api/flags");
  ...
} catch (e) {
  if (e === STALE) return;          // 조용히 버린다
  fill(slot, errorNotice(e, ctx.go)); // 동의 오류면 동의 켜러 가기 버튼이 붙는다
}
```

- 저장하지 않은 입력이 있는 화면은 `ctx.session.unsaved = async () => boolean`을 둔다(떠나기 전에 묻는다). 같은 화면이라도 주소(? 뒤 포함)가 바뀌면 묻는다.
- 거래를 지우거나 거래 살펴보기를 끌 때는 요청 전에 `ctx.session.bumpEpoch()`를 부른다(consent.js의 끄기·모두 지우기).

### 1.5 보내기 탭(send.js): 돈 보내기 | 알림 보내기

- 위 탭은 `segTabs`(돈 보내기 · 알림 보내기). 탭을 바꾸면 `ctx.replaceParams`로 주소만 바꾼다(돈 보내기는 `#/send`, 알림 보내기는 `#/send?mode=notify`). 뒤로 가기 기록은 늘지 않는다.
- 탭마다 작은 ctx를 만들어 `money.render(sub)`·`notify.render(sub)`에 넘긴다. `sub.main`은 탭 칸(`#send-panel`), `sub.onCleanup`·`sub.alive`·`sub.req`는 그 탭이 떠 있는 동안만 유효하다(탭을 바꾸면 정리 함수가 불리고 늦은 응답은 STALE).
- `sub.replaceParams(values)`는 탭 이름(mode=notify)을 붙여 둔 채 ? 뒤를 바꾼다.
- 고친 글이 있는 탭을 떠날 때는 `ctx.session.unsaved`로 먼저 묻는다(계속 쓰기면 탭을 그대로 둔다).
- 다른 화면에서 알림 보내기로 보낼 때는 `#/send?txn=…`·`#/send?to=counselors`·`#/send?mode=notify`를 쓴다(그냥 `#/send`는 돈 보내기).

## 2. ui.js

```js
import { h, fill, append, setText, splitSentences, $, $$, icon, picto, toast, announce,
  openSheet, confirmSheet, comingSoonSheet, closeAllSheets, busy, skeleton, emptyState,
  soonBadge, SOON_TEXT, segTabs, getPref, setPref, applyPrefs } from "../ui.js";
```

### 2.1 h()와 한 문장 한 줄(R18)

- `h(tag, attrs, ...children)`. attrs: `class`, `text`, `dataset`, `style`(CSSOM으로 넣음, 인라인 style 속성 아님), `onclick` 같은 `on*`, `value`, `checked`, `disabled`, `selected`, 그 밖은 setAttribute. `null·undefined·false`는 건너뛴다.
- **`h("p", {text})`는 문장 끝(한글·닫는 괄호 뒤의 `. ? !` 또는 `? !` 다음 빈칸)에서 나눠 `span.sent`(display:block)로 한 줄씩 넣는다.**
  - 숫자 속 점(1.5만, v0.3.0)은 나누지 않는다.
  - `textContent`는 원래 글과 같다(문장 사이 빈칸 유지). 소리로 읽기·복사에 그대로 써도 된다.
  - 나누지 않으려면 `h("p", {text, "data-nosplit": true})`.
  - p가 아닌 태그(span·div·li·h2)는 나누지 않는다.
  - 자식으로 글을 넣는 `h("p", null, "글")`도 나누지 않는다. 설명 글은 `text`로 넣는다.
- 나중에 글을 바꿀 때는 `el.textContent = …` 대신 `setText(el, 글)`을 쓴다(p면 나눔).
- `splitSentences("가요. 나요.")` → `["가요.", "나요."]`.

### 2.2 시트

- `openSheet(build(close) => nodes, {label, dismissible, className, onClose(reason), initialFocus, onEscape})` → `{close, el}`. 배경은 inert, 안드로이드 뒤로 가기로 닫힘.
  - 바텀시트 손잡이는 `.sheet::before`로 자동으로 그려진다(600px 이상은 가운데 창).
  - 제목은 `h("h2", {class: "sheet-title focus-target", tabindex: "-1", text})`, 버튼 묶음은 `.sheet-actions`.
- `confirmSheet({title, lines, confirmText, cancelText, danger})` → `Promise<boolean>`. 취소에 먼저 초점.
- **`comingSoonSheet({icon, title, lines, steps?, action?, extra?})`**: 준비 중 기능 안내. "준비 중" 배지와 "정식 버전에서 열려요."가 자동으로 붙는다.
  - `steps: [{title, sub?, options?: ["3개월", ...]}]` → 번호 붙은 비활성 단계.
  - `action: "연결하기"` → "연결하기(준비 중)" 비활성 버튼.
  - `extra: Node | (close) => Node` → 지금 쓸 수 있는 다른 방법(버튼)을 넣는 자리.

```js
comingSoonSheet({ icon: "lock", title: "앱 잠금", lines: ["앱을 열 때 잠금을 풀어요."], action: "켜기" });
```

### 2.3 그 밖

- `soonBadge()` → `<span class="soon">준비 중</span>`. `SOON_TEXT` = "정식 버전에서 열려요."
- `segTabs(items, active, onChange, {label, controls})` → `{el, set(value)}`. 한 줄 탭(role=tablist, 화살표·Home·End 키). items: `[{value, label, icon?, count?}]`. onChange는 실제로 바뀔 때만.

```js
const tabs = segTabs([
  { value: "cards", label: "걱정되는 거래" }, { value: "flags", label: "담은 거래", count: 2 }, { value: "sent", label: "보낸 알림" },
], tab, (v) => { ctx.replaceParams({ tab: v }); load(v); }, { label: "알림 보기", controls: "alerts-panel" });
```

- `getPref("font")` → `"m"|"l"|"xl"`, `getPref("theme")` → `"auto"|"light"|"dark"`. `setPref(name, value)`는 저장(localStorage, 실패해도 적용)하고 바로 적용한다. settings.js는 이것만 부른다(main.js가 시작할 때 `applyPrefs()`).
  - 글자: 보통 125%, 크게 140%(`html[data-font="l"]`), 아주 크게 160%(`html[data-font="xl"]`).
  - 화면 모드: 자동(속성 없음), 밝게(`:root[data-theme="light"]`), 어둡게(`:root[data-theme="dark"]`).
- `toast(msg, "error"?)`, `announce(msg)`, `busy(btn, async fn)`(두 번 누름 방지), `skeleton(n)`, `emptyState(icon, title, text)`.
- `icon(name, cls?)`: UI 선 아이콘(24) 또는 PICTO(64). `picto(name)`: 쉬운 말 카드 그림.

## 3. components.js

```js
import { levelBadge, flaggedBadge, txnRow, txnAmount, txnSignals, subParts, whenParts, dateHead, flagButton, menuRow,
  speakButton, alertCard, errorNotice, learnedText, saveFile, soonBadge } from "../components.js";
```

| 함수 | 설명 |
|---|---|
| `levelBadge(level)` | 괜찮아요·확인해요·꼭 확인해요 배지 |
| `flaggedBadge()` | 담음 배지(책갈피 아이콘) |
| `txnAmount(t)` | `"-50,000원"`(나감) / `"+50,000원"`(들어옴). 금액은 이것 하나만 쓴다(R21) |
| `txnSignals(item)` | `[{code, icon, text}]` 명사형 신호 이름. AI만 다르다고 본 거래는 `{code:"anomaly", icon:"sparkle", text:"평소와 다른 거래"}` |
| `txnRow(item, onOpen?)` | 거래 한 줄(토스 목록 모양): 이름과 금액 한 줄 → 시각·방법 → 등급 + 명사형 신호 + 담음 배지(`item.flagged`). 금액은 한 번. onOpen이 있으면 버튼(누르면 거래 시트) |
| `subParts(parts, cls?)` | 작은 글 조각 줄(`시각 · 방법` 등). 조각 안에서는 줄을 바꾸지 않고, 줄이 바뀐 조각 앞 가운뎃점은 숨긴다(점이 줄 끝에 매달리거나 `카드 / 결제`로 끊기지 않게). 기본 클래스 `row-sub` |
| `whenParts(ts)` | `["2026년 6월 27일 (토)", "새벽 4시 41분"]`: subParts에 날짜·시각을 따로 넣을 때 |
| `dateHead(ts)` | 날짜 머리 |
| `flagButton(ctx, item, {cls, onChange(flagged, count)})` | 알림 목록에 담기 ↔ 담기 취소 토글(POST /api/flags, /api/flags/remove). 담으면 토스트 "알림 탭에 담았어요." `item.flagged`도 바꾼다 |
| `menuRow({icon, tone, title, sub, href \| onclick, soon, end})` | 전체 탭·설정의 한 줄. `soon: true`면 준비 중 배지. 준비 중 항목은 `onclick: () => comingSoonSheet({...})` |
| `speakButton(getText, {label, stopLabel, cls})` | 소리로 듣기 ↔ 멈추기 토글(aria-pressed). 한 번에 하나만 읽고 끝나면 원래대로. 음성이 없으면 null(그대로 append해도 됨) |
| `alertCard(item, {actions})` | 쉬운 말 카드(그림·등급·제목·줄·소리 토글). `actions`에 [알리기]·[담기] 버튼을 넣는다. `item.flagged`면 담음 배지 |
| `errorNotice(err, go)` | 오류 상자(동의 오류면 동의 켜러 가기) |
| `saveFile(name, mime, text)` | 앱은 시스템 저장 창, PC는 내려받기 → `"saved"|"cancelled"|"error"` |

```js
// alerts.js: 카드마다 알리기·담기
alertCard(item, { actions: [
  h("a", { class: "btn sm weak", href: `#/send?txn=${encodeURIComponent(item.txn.id)}` }, icon("send"), h("span", { text: "알리기" })),
  flagButton(ctx, item, { cls: "btn sm" }),
] });

// txns.js 거래 시트
h("div", { class: "sheet-actions" },
  flagButton(ctx, item),
  h("button", { type: "button", class: "btn weak big block", onclick: () => { close(); ctx.go(`send?txn=${encodeURIComponent(item.txn.id)}`); } },
    icon("send"), h("span", { text: "조력자·상담하는 곳에 알리기" })),
  h("button", { type: "button", class: "btn big block", text: "닫기", onclick: () => close() }));
```

| `CHECKED_TEXT`, `checkedBadge()` | 돈 보내기에서 확인하고 내 거래 끝에 적은 거래(`item.practice`)의 배지 보내기 전 확인. `txnRow`·거래 시트·알림 보내기 거래 줄이 쓴다 |

지운 것: `practicePill`(연습 화면 띠).

### 3.1 charts.js (홈 돈 흐름 차트, SVG 직접 그림)

| 함수 | 설명 |
|---|---|
| `columnChart(items, {label, tone, emphasis, values, selected, onSelect, onCleanup})` → `{el, select(i)}` | 막대 차트. items `[{label, sub?, value, valueText, aria, flag?}]`. 칸이 넉넉하면 세로, 좁으면 가로 막대. 글자는 늘 1rem. `onSelect`가 있으면 막대를 눌러 고른다(화살표 키) |
| `ratioBar(items, {label, onCleanup})` → `{el}` | 가로 비율 막대. items `[{label, share(0~1), cls("c1"~"c5")}]` |
| `srTable(caption, head, rows)` | 화면 낭독용 숨긴 표 |
| `shortWon(n)` | 막대 위 짧은 금액(`368만`, `1.3억`, `9,500원`) |

차트 전용 CSS(`.chart-probe`, `.ch-value` 등)는 지금 홈만 써서 `css/views/home.css`에 있다. 다른 화면이 쓰면 app.css로 옮긴다.

## 4. format.js

| 함수 | 예 |
|---|---|
| `deviceWord()` | 앱·휴대폰 브라우저 → `"이 휴대폰"`, 그 밖 → `"이 컴퓨터"`. `${deviceWord()} 안에서만 살펴봐요.` (127.0.0.1·이 기기 직접 쓰지 않기) |
| `moneyText(n, sign?)` | `moneyText(50000)` → `"50,000원"`, `moneyText(50000, "-")` → `"-50,000원"`, `moneyText(-7900)` → `"-7,900원"` |
| `formatWon(n)` | 쉬운 말 금액 `"5만 원"`. 목록·표에는 쓰지 않는다(차트 눈금·문장용) |
| `formatMonth("2026-06", full?)` | `"6월"` / `"2026년 6월"` |
| `formatTime(d)` | `"새벽 4시 41분"` |
| `formatDate(d)`, `formatShortDate(d)`, `formatWhen(ts)`, `formatDay(ts)`, `parseTs(ts)`, `dayKey(ts)` | 날짜·시각 |
| `percent(0.123, 0)` | `"12%"` |
| `nf.format(n)` | `"1,234"` |
| `sentence(t)` | 끝에 마침표를 붙인다(소리로 읽기용) |

## 5. native.js (기기 기능)

```js
import { isApp, isMobile, capabilities, openExternal, smsUri, mailtoUri, telUri,
  canPickContact, pickContact, copyText } from "../native.js";
```

| 함수 | 설명 |
|---|---|
| `isApp()` | 안드로이드 앱(엔진 모드)이면 true |
| `isMobile()` | 앱이나 휴대폰 브라우저면 true |
| `capabilities()` | `{app, mobile, sms, email, call, contacts, tts}`. PC는 `sms:false, call:false, email:true` |
| `openExternal(uri)` | `sms: smsto: mailto: tel:`만. 앱은 브리지, 브라우저는 링크. 시작하면 true, 못 열면 false(PC 문자는 false) |
| `smsUri(numbers[], body)` | `"smsto:01012345678;0102222…?body=…"`(숫자·+만 남김, 글은 인코딩) |
| `mailtoUri(emails[], subject, body)` | `"mailto:a@b.kr,c@d.kr?subject=…&body=…"` |
| `telUri(number)` | `"tel:16448295"`(전화를 걸지 않고 다이얼 화면만) |
| `canPickContact()` | 연락처에서 고르기를 쓸 수 있으면 true(PC면 false → 버튼 숨김) |
| `pickContact("phone" \| "email")` | `Promise<{name, value} \| null>`(취소·실패는 null). 권한 없이 한 건만 |
| `copyText(text)` | `Promise<boolean>` |
| `canListApps()` | 설치된 앱 목록을 읽고 열 수 있으면 true(안드로이드 앱만, 부를 때 `window.SafePauseNative`의 `listApps`·`openApp`을 확인). PC·휴대폰 브라우저·옛 앱은 false |
| `listApps()` | `[{package, label}]`(앱이 정한 순서: 한글 가나다 → 영문 → 그 밖). 브리지의 JSON 글을 읽고, 패키지 이름 모양이 아닌 것·겹친 것은 뺀다. 이름은 한 줄 80글자까지(MainActivity와 같은 한도). 동기 호출이라 시트를 열 때 한 번만 부른다. 못 쓰면 빈 목록 |
| `openApp(pkg)` | 그 앱을 연다. 열기를 시작했으면 true, 패키지 모양이 아니거나 못 열면 false |

`capabilities()`에는 `apps`(= `canListApps()`)가 있다.

```js
// notify.js: 문자 앱 열기 → 성공하면 기록 → 알림 탭 보낸 알림
const caps = capabilities();
smsBtn.disabled = !caps.sms;            // PC: "문자는 휴대폰 앱에서 보낼 수 있어요."
const ok = openExternal(smsUri(numbers, message));
if (ok) {
  await ctx.req("POST", "/api/notices/record", { channel: "sms", recipients, txn_ids, message });
  toast("문자 앱을 열었어요.");
  ctx.go("alerts?tab=sent");
} else {
  // "이 휴대폰에서 문자 앱을 열지 못했어요." + [글 복사하기] → copyText(message)
}

// helpers.js / counselors.js: 연락처에서 불러오기(PC면 버튼 숨김)
canPickContact() ? h("button", { type: "button", class: "btn sm weak", onclick: async () => {
  const c = await pickContact("phone");
  if (c) { phone.value = c.value; if (!name.value) name.value = c.name; }
} }, icon("contacts"), h("span", { text: "연락처에서 불러오기" })) : null;
```

## 6. speech.js

- `available()`: 기기 한국어 음성이 있으면 true. `onAvailability(fn)`.
- `speak(text, {onEnd})` → 시작하면 true. 읽던 것이 있으면 멈추고 그 onEnd를 부른다.
- `stop()`: 멈추고 onEnd를 부른다(화면을 옮길 때 main.js가 부름).
- `isSpeaking()`.
- 앱은 `window.__safepauseSpeechDone()`(지금 발화의 끝남만, MainActivity)으로, PC는 Web Speech `onend`로 끝을 안다.
- 화면은 보통 `speakButton`만 쓰면 된다.

## 7. labels.js

| 이름 | 내용 |
|---|---|
| `SIGNALS` | 신호 코드 5개 순서 |
| `SIGNAL_KO` | 밤 시간 잦은 이체 / 한 사람에게 송금 집중 / 휴대폰 소액결제 급증 / 처음 가는 곳 큰 금액 결제 / 휴대폰 요금 여러 회선 |
| `SIGNAL_KO_NEUTRAL` | `new_merchant_high_value: "큰 금액 결제"`(처음인지 모를 때) |
| `SIGNAL_ICON` | `sig-night`, `sig-person`, `sig-phone-pay`, `sig-store`, `sig-sim` |
| `signalLabel(item, code)` | 중립 이름까지 고려한 이름 |
| `CHANNEL_KO`, `CHANNEL_ICON` | 결제 방법 이름·아이콘(bank, card, sig-phone-pay, sig-sim, cash) |
| `CHANNEL_CHART` | 결제 방법 → 차트 색 번호 1~5(`.c1`~`.c5`). 이체 1, 카드 2, 휴대폰 결제 3, 휴대폰 요금 4, 그 밖 5 |
| `LEVEL` | none/caution/high → `{text, icon, cls}` |
| `COUNSELOR_KINDS`, `COUNSELOR_KIND_KO`, `COUNSELOR_KIND_ICON` | 상담하는 곳 종류(발달장애인지원센터·장애인권익옹호기관·경찰·금융 상담·그 밖의 곳) |
| `NOTICE_CHANNEL_KO`, `NOTICE_CHANNEL_ICON` | 보낸 알림 방법(문자 chat·메일 mail·전화 call·복사 copy) |
| `MODE_KO`, `COUNSELING_TITLE`, `PERSONAS` | 그대로 |
| `DECISION_ICON` | 안전 정지 카드 선택지 아이콘 `{send: "send", cancel: "stop", ask_helper: "helper"}`(돈 보내기) |
| `PAY_CHANNELS` | 돈 보내기의 방법 `[{value, label, icon}]`: 계좌 이체 · 가게에서 결제 · 휴대폰 결제 |
| `EXAMPLES` | 돈 보내기의 예시로 해 보기(심사·시연용) 3개 |

지운 것(송금 연습): `PRACTICE_NOTE`(연습 문구는 쓰지 않음), `DONE_KO`, `DECISION_KO`, `ASK_NOBODY_KO`.

## 8. views/connect.js (은행·카드 연결 준비 중 시트)

```js
import { openBankConnect, openCardConnect } from "./connect.js";
openBankConnect(ctx);                                   // 지금 쓸 수 있는 방법 버튼 → #/txns?open=upload|sample
openBankConnect(ctx, { onUpload: openUpload, onSample: openSample });   // txns.js 안에서는 바로 시트를 연다
openCardConnect(ctx, { onUpload: openUpload, onSample: openSample });
```

- 단계 1 은행(카드사) 고르기 → 2 본인 확인 → 3 가져올 기간(3·6·12개월), 모두 비활성.
- 연결하기(준비 중) 비활성 버튼, 정식 버전에서 열려요, 실제 은행·카드사 이름·로고 없음.
- 전체 탭의 거래 연결(은행 계좌 연결·카드 연결)도 이 두 함수를 쓴다.

## 9. 아이콘 (`icon(name)`, 24 viewBox, 선 굵기 2, 둥근 끝, currentColor)

- 탭·이동: `home` `list` `send` `bell` `grid` `back` `chevron` `chevron-down` `close`
- 신호: `sig-night`(밤) `sig-person`(한 사람에게) `sig-phone-pay`(휴대폰 소액결제) `sig-store`(처음 가는 곳) `sig-sim`(여러 회선)
- 거래 연결·돈: `bank` `card` `cash` `upload` `download` `file` `doc` `database` `chart` `calendar`
- 연락·알림: `contacts` `mail` `chat` `call` `phone-msg` `speaker` `stop-circle`(소리 멈추기) `bookmark` `bookmark-fill`(담기)
- 사람·곳: `users` `user-check`(본인 확인) `building`(상담하는 곳) `headset`(고객센터) `shield`
- 설정·도움: `settings` `text-size` `moon-sun` `lock` `toggle` `help` `info` `link` `code` `refresh`
- 편집: `plus` `minus` `edit` `copy` `trash` `check-line` `sparkle`
- 로고: `logo`(팔각형 + 멈춤 막대). 막대는 `.brand-mark` 안에서만 보인다(`.logo-bars`).
- 쉬운 말 카드 그림(PICTO, 64): `check` `ear` `helper` `money` `moon` `person` `phone` `question` `stop` `store` `warning`.
  `icon("check")`처럼 UI에 없는 이름은 PICTO로 그린다.

## 10. CSS

화면 전용 스타일은 `css/views/{home,txns,notify,more}.css`에만 쓴다(index.html에 이미 연결됨).
규칙: 글자 크기는 rem만, 1rem 이상(px 금지), 터치 영역 2.4rem 이상, 인라인 style 속성 금지(`h()`의 style은 CSSOM이라 괜찮음), 외부 URL 금지.

### 10.1 토큰 (`:root`, 어두운 모드는 자동으로 바뀜)

- 바탕·글: `--bg` `--bg-sub`(앱 바탕) `--surface`(카드) `--surface-2` `--line` `--text` `--text-2` `--text-3` `--text-4`
- 강조: `--primary` `--primary-weak` `--primary-weak-text`
- 상태(늘 아이콘·글과 함께): `--danger` `--danger-weak` `--danger-text` `--caution` `--caution-weak` `--caution-text` `--ok` `--ok-weak` `--ok-text`
- 차트: `--chart-1`~`--chart-5`(파랑·청록·호박·자홍·보라, 밝게·어둡게 모두 바탕 대비 3:1 이상, 이웃한 색은 색약 시뮬레이션 ΔE 11 이상), `--chart-grid`, `--chart-track`, `--chart-flag`(걱정 거래 점)
- 그 밖: `--shadow-card` `--title-section` `--r-s/m/l/xl` `--gutter` `--nav-h`

### 10.2 공용 클래스

| 묶음 | 클래스 |
|---|---|
| 글 | `.page-title` `.page-sub` `.section-title`(+ `.link`) `.muted` `.strong` `.center` `.tnum` `.sr-only` `.sent` |
| 카드·목록 | `.card`(`.flat` `.tight` `.hero`) `.card-row` `.list` `.list-head` `.row`(`.wrap`) `.row-icon`(`.blue` `.red` `.orange` `.green`) `.row-main` `.row-title` `.row-sub` `.row-end` `.row-amount`(`.in`) `.row-chev` `.row-tags.full` `.menu-row` `.date-head` |
| 배지·칩 | `.badge`(`.none` `.caution` `.high` `.info` `.grey`) `.tag` `.soon` `.chips` `.chip`(`aria-pressed`, `.off`) |
| 버튼 | `.btn`(`.primary` `.weak` `.danger` `.danger-weak` `.ghost` `.block` `.big` `.sm`) `.btn-row` `.btn-col` `.btn-ic` `.icon-btn` `.quick` `.quick-item` `.qi-icon` |
| 입력 | `.field` `.field-label` `.input` `.hint` `.error-text` `.check-row` `.switch-row` `.switch` `.segmented`(라디오 묶음) |
| 탭 | `.seg-tabs` `.seg-tab` `.seg-count` (segTabs가 만듦) |
| 안내 | `.notice`(`.blue` `.red` `.orange` `.green`) `.notice-action` `.empty` `.skeleton` |
| 시트 | `.sheet` `.sheet-title` `.sheet-sub` `.sheet-actions` `.sheet-head` `.sheet-section` `.soon-head` `.soon-icon` `.soon-lines` `.soon-steps` `.soon-step` `.soon-now` |
| 쉬운 말 카드 | `.alert-card` `.alert-head` `.pause-lines` `.card-question` `.card-actions` |
| 숫자 요약 | `.kpi` `.kpi-label` `.kpi-value` `.delta`(`.up` 늘었음 빨강 / `.down` 줄었음 파랑 / `.same`) |
| 차트 | `.chart`(svg 안 `text` `.grid` `.bar` `.bar.muted` `.flag-dot`) `.c1`~`.c5`(→ `--c`) `.stack > i`(비율 띠, 2px 틈) `.hbar` `.hbar-top` `.hbar-track > i` `.legend`(`li` `.swatch` `.grow` `b` `.pct`) |
| 표 | `.table-wrap`(좁은 화면은 카드 모양) |
| 로고 | `.brand` `.brand-mark` `.brand-name` |

```js
// 비율 띠 + 범례(색만으로 구별하지 않게 이름·금액·%를 늘 같이)
h("div", { class: "stack", role: "img", "aria-label": "계좌 이체 62%, 카드 결제 30%, 휴대폰 결제 8%" },
  rows.map((r) => h("i", { class: `c${CHANNEL_CHART[r.channel]}`, style: `flex:${r.share}` })));
h("ul", { class: "legend" }, rows.map((r) => h("li", { class: `c${CHANNEL_CHART[r.channel]}` },
  h("span", { class: "swatch", "aria-hidden": "true" }), h("span", { class: "grow", text: CHANNEL_KO[r.channel] }),
  h("b", { text: moneyText(r.out_total) }), h("span", { class: "pct", text: percent(r.share, 0) }))));
```

## 11. 문구 규칙(요약, 설계서 7절)

- 따옴표('…', "…", ‘…’, “…”)로 낱말·화면 이름을 감싸지 않는다. `'동의'에서` → `동의 화면에서`.
- 한 문장은 한 줄(p의 text로 넣으면 자동). 문장마다 마침표.
- 쓰지 않는 문구: 막지 않아요, 결정은 내가 해요, AI 혼자서는, 연습 화면, 실제로 돈이 나가지 않아요, 보내지 않고 멈춘 것, 연습용 정답, (가려서 저장해요), 127.0.0.1, 안전 정지(앱 이름은 SafePause).
- 당사자 화면 금지어: 이상거래·패턴·탐지·알고리즘·모니터링·이례·임계·통계·고위험·푸시·당사자님·단독 주의. 푸시 대신 휴대폰 알림.
- 신호 이름은 명사형(labels.js), `~보내기`로 끝나지 않는다.
- 금액은 목록·표에서 `moneyText`만. 장소는 `deviceWord()`.
- 준비 중 기능은 `soonBadge()` + "정식 버전에서 열려요."(`comingSoonSheet`가 자동). 실제 은행·카드사 이름·로고 금지.
- textarea·입력 칸은 `spellcheck: "false", autocorrect: "off", autocapitalize: "off"`(notify·helpers·counselors는 테스트가 확인).

## 12. tests/test_static_ui.py가 화면 파일에 기대하는 것

- PERSON_VIEWS(쉬운 말 검사): home, txns, notify, alerts, consent, helpers, counselors, onboarding, more, settings, export.
- 모든 JS 문자열에서 따옴표로 감싼 한글 낱말·금지 문구가 없어야 한다(eval·about 포함).
- 필수 문장(어느 파일이든 하나에 있으면 됨):
  - 은행 파일 모양은 따로 확인하지 못했어요. (txns)
  - 이 조력자에게 자동으로 알리기 (helpers)
  - 꼭 확인할 일이 30일 동안 3번 이상 생길 때 (consent)
  - 언제든지 끌 수 있어요. 끄면 바로 멈춰요. (consent)
  - 합성 데이터 기준, 실제 피해 데이터 검증 아님 (eval)
  - 정말 모두 지울까요? (consent 모두 지우기)
  - 보내기 버튼은 문자·메일 앱에서 직접 눌러요. (notify)
  - SafePause는 돈을 보내지 않아요. 보내기는 내 은행 앱에서 해요. (money)
  - 은행 앱은 휴대폰 앱에서 열 수 있어요. / 은행 앱을 열지 못했어요. 다시 골라 주세요. (bankapp)
  - 이 거래에서 돈을 받은 사람이에요. 다른 사람에게 알리는 게 좋아요. (notify)
  - 정식 버전에서 열려요. (ui.js에 있음)
  - 상담하는 곳에 알려 줘요. (consent)
- notify.js: `openExternal`과 `/api/notices/record`를 쓴다. spellcheck 끄기 세 가지.
- alerts.js: `send?txn=` 링크와 `alertCard` 또는 `speakButton`.
- consent.js: `ctx.session.bumpEpoch()` 두 번 이상(거래 살펴보기 끄기·모두 지우기)과 `/api/wipe`.
- helpers.js·counselors.js·money.js·bankapp.js: spellcheck 끄기 세 가지.
- money.js: 카드 규칙(`initialFocus: "#card-title"`, `dismissible: false`, `card.choices.map`, `aria-labelledby` `card-level card-title`, Esc는 안 보낼래요로, `fitLayout`, `parseKoreanAmount`, 오류 칸이 소리로 듣기 앞). check·decide·payees는 money.js만 부른다.
- 직접 이체 없음: 비밀번호·인증 번호 입력칸(`type: "password"`, one-time-code 등), 이체 API, `intent:` 주소가 없다.
- 실제 은행·카드사·간편결제 이름과 패키지 이름이 화면 글에 없다(`BANK_NAMES`, `BANK_PACKAGES`).
- 화면 확인: `python scratchpad/tools/webcheck.py --routes … --setup sample --out <폴더>`(360x780, `--font 2`, `--desktop`, `--dark`), errors가 빈 목록이어야 한다.

## 13. 백엔드 API 빠른 참조(설계서 3절, 실제 구현 기준)

| 요청 | 응답 |
|---|---|
| `GET /api/helpers` | 목록 `[{id, name, relation, phone, email, phone_masked, email_masked, contact, identifiers, min_level, signal_scope, active}]` |
| `PUT /api/helpers` | 목록 전체(`phone`, `email` 원본 포함) → 저장된 목록 |
| `GET /api/counselors` | `{items: [{id, name, kind, phone, email, memo, active}], presets: [{kind, name, phone, email, memo}]}` |
| `PUT /api/counselors` | 목록 전체 → `{items}` (이름 1~30자, 메모 0~100자, 20곳까지) |
| `GET /api/transactions?level=all\|caution\|high&limit&offset` | 항목에 `flagged: bool` |
| `GET /api/flags` | `{items: [{txn_id, created_at, item}]}`(최근 담은 것부터, 거래 살펴보기 동의 필요) |
| `POST /api/flags` / `POST /api/flags/remove` | `{txn_id}` → `{ok, count}`. 없는 거래는 404 "그 거래를 찾지 못했어요." |
| `POST /api/notices/record` | `{channel: sms\|email\|call\|copy, recipients: [{kind: helper\|counselor, id, name}], txn_ids, message}` → 기록 1건 |
| `GET /api/notices` | `{items: [kind "auto" 또는 "manual" 기록], delivery_note}` |
| `GET /api/insights` | 돈 흐름 분석(months·this_month·prev_month·channels·time_bands·top_payees·flagged_total) |
| `GET /api/cards?limit=` | 쉬운 말 카드 |
| `GET /api/payees` | 최근 계좌로 보낸 사람 이름 `{items}`(돈 보내기 칩) |
| `POST /api/safepause/check` | `{to, amount, channel, to_id, time?}` → `{pending, assessment, card, notify_plan_preview, ask_helper_preview, ts_note}` |
| `POST /api/safepause/decide` | `{pending, decision: send\|cancel\|ask_helper, helper_ids?}` → `{decision, added_to_history, pending, assessment, notify_plan, notices_recorded, result_title, result_lines, delivery_note, ts_note}` |
| `POST /api/notify/suggest` | `{txn_ids}` → `{helpers: [{id, name, suggested, conflict, reason}], counselors: [{id, name, suggested}], counseling_due}` |

앱(엔진 모드)에서는 동의·조력자·상담하는 곳·알림 기록·지우기가 AI 준비 전에도 바로 처리된다(worker.mjs BASIC). 담은 거래·돈 흐름 분석·거래 목록, 돈 보내기의 check·decide·payees, 받는 사람 추천(suggest)은 거래 판단(numpy)이 필요해 AI 준비가 끝난 뒤 온다(worker.mjs BASIC에 넣지 않는다, 테스트가 확인).

## 14. 돈 보내기·내 은행 앱(money.js·bankapp.js, css/views/money.css)

- money.js(`export default {title, render}`, 보내기 탭이 부름)
  - 입력: 받는 사람(최근 보낸 사람 칩, `GET /api/payees`), 금액(`parseKoreanAmount`, `= 30만 원 (300,000원)`, 0·100억 원 한도는 그 자리에서), 방법(`PAY_CHANNELS`), 자세히(보낼 시각 지금·오후 3시·밤 11시·새벽 2시, 계좌번호)
  - 오류는 틀린 칸 바로 아래(받는 사람 `#pay-to-error`, 금액 `#pay-amount-easy`), 서버 오류는 확인 버튼 위(`#pay-error`)
  - `POST /api/safepause/check` → 카드(안전 정지 카드 규칙은 파일 머리 주석) 또는 걱정 없음 결과 → `POST /api/safepause/decide`
  - 결과: 보낼래요 → 요약 + `bankAppActions()` + 필수 문장, 안 보낼래요 → 보내지 않았어요, 물어볼래요 → [알림 보내기로 문자·메일 보내기](`#/send?mode=notify&txn=…&helper=…`)
  - 결과 제목: 보낼래요·안 보낼래요는 decide의 `message`(계좌 이체 `내 은행 앱에서 보내 주세요.`·`보내지 않았어요.`, 가게·휴대폰 결제 `결제는 직접 해 주세요.`·`결제하지 않았어요.`), 물어볼래요는 `result_title`·`result_lines`. 서버 응답이 없는 동의 꺼짐 결과만 화면 표(SEND_TITLE, 같은 글)를 쓴다
  - 거래 살펴보기 동의가 꺼져 있으면 확인하지 않은 결과 + 은행 앱 + 동의 켜러 가기
  - `checkedItem(id)`: 이 창에서 확인한 거래 항목(물어볼래요는 거래 이력에 적지 않으므로 notify.js가 이것으로 미리 고른다. `unsaved: true`면 suggest의 txn_ids에서 뺀다)
  - 필수 문장 `SafePause는 돈을 보내지 않아요. 보내기는 내 은행 앱에서 해요.`(화면 위 안내·결과). 연습이라는 말과 PRACTICE_NOTE는 쓰지 않는다
  - 계좌 연결해서 바로 보내기는 `comingSoonSheet`(단계 5개)만
- bankapp.js
  - `getBankApp()`·`saveBankApp(app)`·`clearBankApp()`: localStorage `safepause.bankApp = {package, label}`(try/catch)
  - `pickBankApp()` → `Promise<app | null>`: 검색 칸 + 돈 관련 앱(이름에 은행·뱅크·bank·페이·pay·증권·카드) 먼저 + 다른 앱. 회사 이름은 넣지 않는다
  - `openBankApp(app)`, `bankAppUnavailable()`(PC면 `은행 앱은 휴대폰 앱에서 열 수 있어요.`)
  - `bankAppActions()`: [내 은행 앱 열기](고른 앱 이름) / [다른 은행 앱 고르기], 못 열면 `은행 앱을 열지 못했어요. 다시 골라 주세요.`
  - `bankAppSettings()`: 앱 설정의 내 은행 앱(고르기·바꾸기·지우기). 동의 화면의 모두 지우기는 `clearBankApp()`도 부른다
- notify.js 받는 사람 추천: 거래를 고르거나 바꿀 때 `POST /api/notify/suggest {txn_ids}` → 추천 배지·미리 체크(본인이 바꾼 사람은 그대로), 돈을 받은 조력자는 체크를 풀고 `이 거래에서 돈을 받은 사람이에요. 다른 사람에게 알리는 게 좋아요.`, 그래도 체크하면 보내기 전에 확인 시트. 추천을 못 받으면 추천 없이
- CSS(money.css): `.send-tabs` `.send-panel` `.mn-must` `.mn-form` `.mn-more` `.amount-easy`(`.bad`) `.pause` `.pause-head` `.pictos` `.pause-title` `.pause-question` `.helper-note` `.choice-btn` `.sheet.split`(`.sheet-body` `.sheet-foot`) `.result-hero`(`.stop` `.ask`) `.result-lines` `.result-notes` `.mn-summary` `.mn-must-line` `.ba-*`
