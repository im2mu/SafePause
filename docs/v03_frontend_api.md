# SafePause v0.3 화면 공용 기반 사용 설명서 (화면 담당용)

이 문서는 화면 담당(홈·내 거래·알림 보내기/알림·전체)이 공용 모듈 위에서 화면을 만들 때 보는 문서다.
설계서 `docs/v03_spec.md`가 기준이고, 여기에는 공용 함수·CSS 클래스·아이콘·경로·ctx를 정확히 적는다.
돈 보내기(보내기 전 확인 → 내 은행 앱)는 `docs/v03_spec_money.md`가 기준이다(0절 송금 기능 없음을 고친 문서). 이 문서의 1.5절·5절·7절·14절에 화면 쪽을 적었다.

- **2026-10-03 수정(적대적 검증 145건 반영)**: 결정·계약은 `docs/v03_fixplan.md`가 이 문서보다 우선한다. 이 문서의 15절에 화면 공용 계약(새 함수·상수·CSS)을 예시와 함께 모았다.
- **2026-10-03 화면 글 정리(`docs/v03_typography.md`)**: 간격 토큰·문장 < 문단 < 구역 리듬·줄 높이 다섯 가지·글 폭 34em·숫자 묶음(`ui.keepNodes`)·문단 묶기(`ui.paragraphs`). 16절에 화면 담당이 지킬 것을 모았다.
- **2026-10-03 화면 글 정리 2차(`docs/v03_typography.md` 5절)**: 모든 요소의 글이 묶음을 지킨다(`setText` → `keepNodes`, dd·li·span·버튼 이름 포함), 낱말 묶기(`span.bind`)·금액 + 붙은 말(`span.keep-word`), 줄바꿈은 낱말 사이에서만(`overflow-wrap: break-word`), 버튼 이름 묶기(`span.btn-label`), 거래 자세히 머리 공용(`components.txnDetailHead`), 거래 고르기 낮은 고르기 띠, 확인 거래는 주소 대신 sessionStorage.
- 공용 파일(화면 기반 담당): `index.html`, `js/main.js`, `js/api.js`, `js/ui.js`, `js/components.js`, `js/format.js`, `js/labels.js`, `js/icons.js`, `js/speech.js`, `js/native.js`, `js/engine-client.js`, `js/views/connect.js`, `engine/worker.mjs`, `css/app.css`, `icons/`(파비콘 `logo.svg`), `tests/test_static_ui.py`.
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
| `#/more/eval` | `views/eval.js` | 전체 | 조력자·기관용 |
| `#/more/export` | `views/export.js` | 전체 | 새 화면(옛 data.js의 내보내기) |
| `#/more/about` | `views/about.js` | 전체 | |
| `#/more/guide` | `views/guide.js` | 전체 | 사용법 안내(첫 실행 1단계 소개를 다시 보기, 동의 단계 없음). 공용 담당이 최소 화면을 만들었고 전체·설정 담당이 채운다 |
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
| `#/send?mode=notify&txn=<id>&helper=<조력자 id>&ask=1&channel=sms\|email` | 돈 보내기의 물어볼래요 → [문자로 물어보기]·[메일로 물어보기]: 그 조력자만 미리 체크, 묻는 글, 그 방법을 먼저 고름. 저장하지 않은 확인 거래는 `checkedItem(id)`로 미리 고르고 suggest에 `pending`으로 넘긴다 | notify.js |
| `#/send?mode=notify&resend=<보낸 알림 id>` | 보낸 알림의 다시 보내기: 그 기록의 받는 사람·글·거래로 채움(고치지 않으면 떠날 때 묻지 않음) | notify.js |
| `#/send?mode=notify&txn=live-…` | 돈 보내기에서 확인만 하고 저장하지 않은 거래(안 보낼래요·물어볼래요 → 알림 보내기). 주소에는 거래 id만 넣는다(2026-10-03 2차: 받는 사람 칸에 적은 계좌번호 같은 글이 주소·방문 기록에 남지 않게). 받는 사람 이름·금액·방법·시각·등급·신호·돈 받는 조력자 id는 `money.checkedItem(id)`가 이 창의 기억 + 이 탭의 sessionStorage(`safepause.checked`, try/catch, 탭을 닫거나 모두 지우기·거래 살펴보기 끄기 때 `clearChecked()`로 사라짐)에서 찾는다. 새로 고쳐도 시각(ts)까지 되살아나 받는 사람 추천·미리 체크가 처음과 같다. 옛 `chk_*` 주소 값은 읽지 않고 지운다 | notify.js |
| `#/alerts?tab=cards\|flags\|sent` | 걱정되는 거래 / 담은 거래 / 보낸 알림 탭(옛 이름 `risky`·`flagged`도 받음) | alerts.js |
| `#/txns?q=<이름>&period=all\|1m\|3m` | 내 거래 이름 검색·기간(홈 많이 보낸 곳 TOP 3가 보냄) | txns.js |
| `#/txns?open=upload\|sample\|bank\|card\|phone` | 파일 올리기 / 연습용 거래 / 은행·카드·휴대폰 결제 연결(준비 중) 시트를 바로 엶 | txns.js (connect.js가 보냄) |

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
- **모든 요소의 글은 묶음을 지킨다(`setText` → `keepNodes`, 2026-10-03 2차)**: p뿐 아니라 dd·li·td·span·버튼 이름 등 `h(tag, {text})`·`setText`로 넣는 글 모두(option·title·textarea·script·style과 SVG 글은 그대로). p가 아닌 요소는 묶음 노드를 span 하나에 담아 넣는다(flex 칸인 요소에서 조각마다 따로 칸이 되지 않게).
  - 시각(`새벽 4시 41분`)·날짜(`6월 27일`)·띄어 쓴 금액(`3만 5천 원`): 묶음 안 빈칸에서 줄을 바꾸지 않는다(첫 낱말은 글, 나머지는 빈칸 + 낱말을 `span.nowrap`에. 빈칸만 든 글 조각을 만들지 않아 묶음 사이 빈칸은 늘 글자와 같은 조각에 있다. 묶음에서 글자를 옮겨 그 끝·처음이 문장부호가 되면(`가게·` / `밤`) 옮기지 않는다: 가운뎃점·괄호 곁은 브라우저가 줄을 바꿀 수 있는 자리다). 빈칸 없는 금액(`50,000원`·`63만7천원`)은 줄 바꿀 자리가 없어 그대로 둔다.
  - `문자·메일`은 가운뎃점 앞뒤 글자를 `span.nowrap`에(가운뎃점 뒤에서 끊기지 않게), 전화번호는 `span.tel-text`(하이픈 뒤 `wbr`에서만 줄바꿈: 하이픈 뒤 숫자 앞은 브라우저가 줄을 바꾸지 않아 큰 글씨에서 넘쳤다).
  - 금액 바로 뒤에 한글이 세 글자 이상 붙은 낱말(`63만7천원이었어요`)은 `span.keep-word`(inline-block): 한 줄에 들면 통째로 옮기고, 칸보다 길 때만(아주 큰 글씨) 금액 뒤(`wbr`)에서 줄을 바꾼다.
  - 낱말 안 문장부호(괄호·물결·붙임표·가운뎃점·빗금, 2026-10-03 2차): 6글자까지(`약속(규칙)으로`·`상대·7일`)는 `span.nowrap`, 7~16글자(`이름·계좌번호·연락처는`·`밤 11시~새벽 6시에`·`연결(마이데이터)은`·`typing-extensions`)는 `span.keep-word`이고 안에서는 가운뎃점 뒤·물결 뒤(한글 앞)·여는 괄호 앞·영문 붙임표 뒤의 `wbr`에서만 줄을 바꾼다(숫자 범위 `0~1` 안은 두지 않음). 덩어리 안 `글자 + 가운뎃점`(`액·`)과 `닫는 괄호 + 붙은 한글`(`)은`)은 `span.nowrap`이라 가운뎃점이 줄 첫머리에 오거나 조사 한 글자가 홀로 남지 않고, 마지막 자리 뒤가 두 글자 이하면(`금액·시간대·처음`의 `처음`) 그 자리를 빼고 붙인다. 더 긴 낱말(파일 경로)은 그대로(성능 확인 화면은 `breakPaths`가 `/`·`_` 뒤, 경로를 여는 괄호 앞·`.json)` 뒤에 `wbr`).
  - 이름표(버튼·칩·배지·태그·탭) 안 `span.keep-word`는 `vertical-align: top`(덩어리가 두 줄이 되어도 버튼 그림이 첫 줄 옆에 남게). `.btn.block`은 크기 컨테이너이고, 이름 칸이 8글자(`8rem`)보다 좁으면(360폭 글자 2배) 버튼 이름 안 `keep-word`를 풀어 정해 둔 자리에서 줄을 바꾼다(덩어리가 그림 옆에 다 들지 않아 그림만 첫 줄에 남지 않게).
  - 긴 기관 이름은 기관 말 앞(`지역발달장애인 / 지원센터`)에 `wbr`.
  - 낱말 묶기(`opts.bind`, `setText`·`subParts`가 켬): 한 글자 낱말은 뒤 낱말과(`열 수 있어요`), 앞 낱말에 붙는 한 글자 말(`곳·것·때·등·달·번·장·개·명·건·쯤·뿐·데·줄·중`, `BACK_WORD`)은 앞 낱말과(`처음 가는 곳`, `건수 등`), 글 끝 한두 글자 꼬리는 앞 낱말과(`불법금융 신고`, `돈을 낼 때`) 6글자까지 묶는다(`span.bind`, 큰 글씨 좁은 칸에서도 넘치지 않는 길이). 버튼·칩·배지·태그·탭 안에서는 CSS가 묶음을 풀어 줄 고르기(balance)에 맡긴다(좁은 칸에서 넘치지 않게).
  - `textContent`는 원래 글과 같다. 해(`2026년`)·요일(`(토)`)은 묶지 않는다.
- 직접 노드로 넣는 이름(`span.np-name`, `b.preset-name` 등)에 묶음이 필요하면 `h("span", {class}, keepNodes(name))`(낱말 묶기 없이).
- **버튼 이름 묶기(`h`)**: `.btn`의 자식이 [그림(svg 또는 `span.btn-ic`), 클래스 없는 글 span] 둘뿐이면 `span.btn-label` 하나로 묶는다. 이름이 두 줄이 되어도 그림이 첫 줄 글 바로 앞에 붙고(인라인), 줄은 가운데에서 고르게 나뉜다. 두 줄 짜임 이름(`.np-send-text` 등 클래스 있는 span)과 `.choice-btn`은 그대로다.
- **`h("p", {text})`는 문장 끝(한글·닫는 괄호 뒤의 `. ? !` 또는 `? !` 다음 빈칸)에서 나눠 `span.sent`(display:block)로 한 줄씩 넣는다.**
  - 숫자 속 점(1.5만, v0.3.0)은 나누지 않는다.
  - `textContent`는 원래 글과 같다(문장 사이 빈칸 유지). 소리로 읽기·복사에 그대로 써도 된다.
  - 나누지 않으려면 `h("p", {text, "data-nosplit": true})`.
  - p가 아닌 태그(span·div·li·h2)는 나누지 않는다.
  - 자식으로 글을 넣는 `h("p", null, "글")`도 나누지 않는다. 설명 글은 `text`로 넣는다.
- 나중에 글을 바꿀 때는 `el.textContent = …` 대신 `setText(el, 글)`을 쓴다(p면 나눔).
- `splitSentences("가요. 나요.")` → `["가요.", "나요."]`.
- **문단 묶기**: 같은 내용을 설명하는 2~3문장은 p 하나에 넣는다(문장마다 한 줄, 문장 사이 .15rem). 한 문장짜리 p를 줄줄이 쓰지 않는다. 뜻이 다르면 문단을 나눈다(문단 사이 .6rem).
  - `paragraphs(lines)`: `["가.", "나."]` → `["가. 나."]`(한 문단), `[["가.", "나."], ["다."]]` → `["가. 나.", "다."]`(두 문단). 동의·첫 실행의 설명, 준비 중 시트의 `lines`가 쓴다.
  - `confirmSheet`·`comingSoonSheet`의 `lines`는 `paragraphs(lines)`로 그린다(문장 목록은 한 문단, 이름처럼 따로 둘 줄은 `[[이름], ["문장."]]`).

### 2.2 시트

- `openSheet(build(close) => nodes, {label, dismissible, className, onClose(reason), initialFocus, onEscape})` → `{close, el}`. 배경은 inert, 안드로이드 뒤로 가기로 닫힘.
  - 바텀시트 손잡이는 `.sheet::before`로 자동으로 그려진다(600px 이상은 가운데 창).
  - 제목은 `h("h2", {class: "sheet-title focus-target", tabindex: "-1", text})`, 버튼 묶음은 `.sheet-actions`.
- 시트를 닫으면 초점은 **연 버튼**으로 돌아간다. 그 버튼이 없어졌거나(다시 그림) 꺼져 있거나 inert 안이면 아직 열린 위 시트의 `.focus-target`, 시트가 없으면 `#main`으로 간다. 초점이 body로 빠지지 않는다(FE-04·FN-07).
- 시트가 열려 있는 동안 Tab은 시트 안에서만 돈다. 초점이 시트 밖(body 등)에 있으면 Tab 한 번에 시트 첫 항목으로 끌어온다.
- 시트 안의 소리로 듣기는 시트를 닫으면 멈춘다(`speakButton`이 버튼이 화면에서 떨어지는 것을 보고 멈춤, 화면 쪽 코드 필요 없음).
- `confirmSheet({title, lines, confirmText, cancelText, danger})` → `Promise<boolean>`. 취소에 먼저 초점. 닫히면 위 규칙대로 초점이 돌아간다.
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
  - 안드로이드 앱에서는 `applyPrefs`가 `SafePauseNative.setThemeMode(theme)`도 불러 위아래 시스템 막대 색을 앱 설정에 맞춘다(AND-04, 함수가 없는 옛 APK는 건너뜀).
  - 글자: 보통 125%, 크게 140%(`html[data-font="l"]`), 아주 크게 160%(`html[data-font="xl"]`).
  - 화면 모드: 자동(속성 없음), 밝게(`:root[data-theme="light"]`), 어둡게(`:root[data-theme="dark"]`).
- `toast(msg, "error"?)`: 문장이 여럿이면 한 문장에 한 줄(안쪽 `p` → `span.sent`, C4). 문장 수만큼 조금 더 오래 보인다.
- `announce(msg)`, `skeleton(n)`, `emptyState(icon, title, text)`.
- `busy(btn, async fn)`: 두 번 누름 방지. **`disabled`를 쓰지 않고** `aria-busy="true"`·`aria-disabled="true"`를 건다(누른 버튼이 꺼지면 초점이 body로 빠지기 때문). 보이는 모양은 CSS(`.btn[aria-disabled="true"]`, 돌림표)가 맡는다. 하는 중에 또 누르면 `undefined`를 돌려주고 아무것도 하지 않는다.
- `icon(name, cls?)`: **늘 선 아이콘(24 viewBox, 굵기 2)**. `check`·`warning`·`stop`·`person` 같은 픽토그램 이름도 선 버전으로 그린다(D4). 없는 이름은 빈 `span.ic`.
- `picto(name)`: 64 큰 그림. 돈 보내기 확인 카드 본문(`money.js`의 `.pictos`)에만 쓴다(테스트가 확인).

## 3. components.js

```js
import { levelBadge, flaggedBadge, flagBadge, reviewBadge, notifiedBadge, checkedBadge, txnRow, txnAmount, txnSignals,
  subParts, whenParts, dateHead, flagButton, reviewButton, menuRow, speakButton, noVoiceNote, alertCard, aiExplain,
  errorNotice, learnedText, saveFile, soonBadge } from "../components.js";
```

| 함수 | 설명 |
|---|---|
| `levelBadge(level)` | 괜찮아요·확인해요·꼭 확인해요 배지 |
| `flaggedBadge()` | 담음 배지(책갈피 아이콘, 글은 `FLAG_TEXT.badge`) |
| `flagBadge(item)` / `reviewBadge(item)` / `notifiedBadge(item)` | 그 상태면 배지 요소, 아니면 `null`(그대로 append해도 됨). 담음(`item.flagged`) / 내가 확인함(`item.reviewed`) / 알렸어요(10월 3일)(`item.notified_at`) |
| `txnAmount(t)` | `"-50,000원"`(나감) / `"+50,000원"`(들어옴). 금액은 이것 하나만 쓴다(R21) |
| `txnSignals(item)` | `[{code, icon, text}]` 명사형 신호 이름. AI만 다르다고 본 거래는 `{code:"anomaly", icon:"sparkle", text:"평소와 다른 거래"}` |
| `txnRow(item, onOpen?)` | 거래 한 줄(토스 목록 모양): 이름과 금액 한 줄 → 시각·방법 → 등급 + 명사형 신호 + 담음·내가 확인함·알렸어요·보내기 전 확인 배지. 금액은 한 번. onOpen이 있으면 버튼(누르면 거래 시트) |
| `subParts(parts, cls?)` | 작은 글 조각 줄(`시각 · 방법` 등). 조각(flex 칸)이 칸에 들어가면 한 줄로 두고, 칸보다 긴 조각만 안의 빈칸에서 줄을 바꾼다(조각 안 숫자·날짜·시각은 `keepNodes` 묶음이라 `2026년 / 6월 27일 / (토)`처럼 묶음 사이에서만). 줄이 바뀐 조각 앞 가운뎃점은 숨긴다. 기본 클래스 `row-sub`. 조각 글은 보통 빈칸이다(예전처럼 줄 바꾸지 않는 빈칸으로 바꾸지 않음) |
| `whenParts(ts)` | `["2026년 6월 27일 (토)", "새벽 4시 41분"]`: subParts에 날짜·시각을 따로 넣을 때 |
| `dateHead(ts)` | 날짜 머리 |
| `txnDetailHead(item, badges)` | 거래 자세히 시트 머리(내 거래 시트·알림 카드 자세히 공용, 2026-10-03 2차): 이름(h2.sheet-title) + 배지 칸 한 줄(`.tx-head`) → 큰 금액 한 번(`p.tx-amount`) → 사실 상자(`dl.tx-facts`: 언제·어떻게·메모). 배지 칸(`span.tx-badges`)은 화면이 상태가 바뀌면 다시 채운다 |
| `flagButton(ctx, item, {cls, onChange(flagged, count)})` | 알림 목록에 담기 ↔ 담기 취소 토글(POST /api/flags, /api/flags/remove, 글은 `FLAG_TEXT`). 담으면 토스트 "알림 탭에 담았어요.", 빼면 "담은 거래에서 뺐어요." `item.flagged`도 바꾼다. 알림 카드의 작은 버튼도 이것을 쓴다(`{cls: "btn sm"}`). 하는 동안 `disabled`를 쓰지 않는다(초점 유지) |
| `reviewButton(ctx, item, {cls, onChange(reviewed, count)})` | 내가 한 거예요 ↔ 확인 취소 토글(POST /api/reviews, /api/reviews/remove, 글은 `REVIEW_TEXT`). `item.reviewed`도 바꾼다. 탐지 등급은 그대로다 |
| `menuRow({icon, tone, title, sub, href \| onclick, soon, end})` | 전체 탭·설정의 한 줄. `soon: true`면 준비 중 배지를 **제목 바로 아래 고정 줄**(`.menu-soon`)에 붙인다(L15). 준비 중 항목은 `onclick: () => comingSoonSheet({...})` |
| `speakButton(getText, {label, stopLabel, cls})` | 소리로 듣기 ↔ 멈추기 토글(aria-pressed). 한 번에 하나만 읽고 끝나면 원래대로. **버튼이 화면에서 떨어지거나 `[hidden]` 안에 들어가면(탭 바꾸기·패널 다시 그리기·시트 닫기) 읽기를 멈춘다**(MutationObserver, D1·FE-09). 화면 쪽은 `speech.stop()`을 부르지 않아도 된다. 음성이 없다고 확정되면 null, 아직 준비 중이면 버튼을 만들고 CSS가 숨겼다가 준비되면 보인다(D10) |
| `noVoiceNote(cls?)` | 음성 없음 안내 `p.voice-note`. 음성이 없다고 확정됐을 때만 보이고 준비 중·준비됨이면 숨는다(CSS). `speech.available()`로 미리 고르지 말고 그대로 넣는다 |
| `alertCard(item, {actions})` | 쉬운 말 카드(그림·등급·제목·줄·소리 토글). 머리 그림은 신호 선 아이콘(`SIGNAL_ICON`, 내 거래 표시와 같은 그림). 카드 줄이 이미 같은 금액을 말하면 머리 줄 금액을 빼고(C10), 줄은 `li > p`(한 문장 한 줄)·`keepUnits`(168만 원이 끊기지 않게). `actions`에 [알리기]·`flagButton`·[자세히]를 넣는다. 담음·내가 확인함·알렸어요 배지는 자동 |
| `aiExplain(item, {heading})` | 왜 걱정되나요 두 갈래 `section.ai-explain`: 약속(규칙)으로 본 것(명사형 신호) + AI가 본 것(`item.ai`가 있을 때만: 평소 내 거래와 다른 정도 상위 N% · 평소와 가장 다른 점 한 줄 · AI만 찾은 거래 표시, 모델이 없으면 배우는 중 문장). `heading` 기본 3(시트 제목 h2 아래) |
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

```js
// txns.js 거래 시트: 상태 배지 + 왜 걱정되나요 + 담기·내가 한 거예요
h("div", { class: "sheet-head" }, levelBadge(item.level), flagBadge(item), reviewBadge(item), notifiedBadge(item)),
aiExplain(item),                                   // item.ai가 없으면 약속(규칙)만
h("div", { class: "sheet-actions" }, flagButton(ctx, item), reviewButton(ctx, item, { cls: "btn weak big block" }), …)

// alerts.js 카드: 담기 문구를 따로 만들지 않는다
alertCard(item, { actions: [알리기링크, flagButton(ctx, item, { cls: "btn sm" }), 자세히버튼] });
```

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
| `formatWon(n)` | 쉬운 말 금액 `"5만 원"`(천 원·만 원 단위 반올림). 목록·표·입력 미리 보기에는 쓰지 않는다(차트 눈금·문장용) |
| `amountPreview(n)` | 입력 금액 미리 보기: 정확한 원 단위 하나 `amountPreview(3500)` → `"3,500원"`. 0 이하·숫자 아님은 `""`. 반올림한 만 원 표기를 `=`로 붙이지 않는다(RF-4·C10) |
| `bandLabel(band, {range})`, `BANDS` | 시간대 이름(앱 시각 표기와 같음): dawn `새벽`(밤 12시~아침 6시) · morning `오전`(아침 6시~낮 12시) · day `낮`(낮 12시~저녁 6시) · evening `저녁·밤`(저녁 6시~밤 12시). `bandLabel("dawn", {range: true})` → `"새벽(밤 12시~아침 6시)"` |
| `keepUnits(text)` | 화면에 보이는 글에서 숫자 + 원·시각·날짜 사이 빈칸을 줄을 바꾸지 않는 빈칸으로(`168만 원`, `오후 3시`, `4시 41분`, `6월 27일`이 줄 끝에서 끊기지 않게, C13·L8·L9). 문자·메일로 보낼 글·소리로 읽을 글에는 쓰지 않는다 |
| `breakableEmail(text)` | 보이는 메일 주소에서 `@` 앞과 도메인 점 뒤(남는 글이 세 글자 이상일 때만)에서만 줄을 바꿀 수 있게 한다(`example.co / m`, `co. / kr` 방지). `span.email-text`와 같이 쓴다. 메일 앱 주소에는 원래 값 |
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
| `pickContact("phone" \| "email")` | `Promise<{name, value} \| null>`. 권한 없이 한 건만. **창이 열려 있는 동안 다시 부르면 새 창을 열지 않고**(앞 창의 결과는 앞 호출이 받음) 토스트 "연락처 창이 이미 열려 있어요. 그 창에서 골라 주세요."와 함께 null(IA-5·AND-08). 못 열었거나 읽지 못했으면 토스트 "연락처를 불러오지 못했어요. 직접 적어 주세요."와 함께 null. 취소는 안내 없이 null |
| `lastPickResult()` | 마지막 pickContact 결과 `"ok" \| "cancelled" \| "busy" \| "failed" \| "unsupported"`(null이 왜 왔는지 알아야 할 때) |
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

- `available()`: 기기 한국어 음성이 있으면 true. `onAvailability(fn)`(돌려준 함수로 구독 해제).
- `voiceStatus()`: `"ready"`(쓸 수 있음) · `"pending"`(음성 목록·TTS 엔진 준비 중, 브라우저는 3초·앱은 10초까지 기다림) · `"none"`(없음으로 확정). 같은 값을 `html[data-voice]`에 적고, CSS가 준비 전에는 `.speak-btn`을 숨기고 `.voice-note`(·옛 `.mn-novoice`)는 none일 때만 보인다(D10: 음성이 늦게 와도 화면이 저절로 맞춰짐).
- `noVoiceNote()`: `${deviceWord()}에 한국어 음성이 없어서 소리로 듣기 버튼을 숨겼어요. …`(C7, 이 기기 하드코딩 없음). `NO_VOICE_NOTE`는 처음 불러올 때 이것으로 정한 옛 이름(문자열). 화면은 `components.noVoiceNote()`를 쓴다.
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
| `LEVEL` | none/caution/high → `{text, icon, cls}`. 아이콘 `check`·`warning`·`stop`은 선 아이콘(원 체크·삼각 느낌표·팔각 느낌표) |
| `FLAG_TEXT` | `{button: "알림 목록에 담기", undo: "담기 취소", toast: "알림 탭에 담았어요.", removed: "담은 거래에서 뺐어요.", list: "담은 거래", badge: "담음"}`. 담기 글은 이것만 쓴다(목록·탭 이름도 `FLAG_TEXT.list`) |
| `REVIEW_TEXT` | `{button: "내가 한 거예요", undo: "확인 취소", badge: "내가 확인함", toast: "내가 한 거래로 표시했어요.", removedToast: "내가 확인한 표시를 지웠어요.", note: "걱정되는 거래 수에서 뺐어요."}` |
| `NOTIFIED_TEXT` | `"알렸어요"`(배지 `알렸어요(10월 3일)`은 `notifiedBadge`가 만든다) |
| `AI_TEXT` | `aiExplain`의 글: `title` 왜 걱정되나요? · `rules` 약속(규칙)으로 본 것 · `rulesNone` · `ai` AI가 본 것 · `aiLearning` 거래가 30건보다 적어 AI는 아직 배우는 중이에요. · `aiOnly` · `aiNone` · `diffLabel` 평소 내 거래와 다른 정도 |
| `COUNSELOR_KINDS`, `COUNSELOR_KIND_KO`, `COUNSELOR_KIND_ICON` | 상담하는 곳 종류(발달장애인지원센터·장애인권익옹호기관·경찰·금융 상담·그 밖의 곳) |
| `NOTICE_CHANNEL_KO`, `NOTICE_CHANNEL_ICON` | 보낸 알림 방법(문자 chat·메일 mail·전화 call·복사 copy) |
| `MODE_KO`, `COUNSELING_TITLE`, `PERSONAS` | 그대로 |
| `DECISION_ICON` | 안전 정지 카드 선택지 아이콘 `{send: "send", cancel: "stop", ask_helper: "helper"}`(돈 보내기) |
| `PAY_CHANNELS` | 돈 보내기의 방법 `[{value, label, icon}]`: 계좌 이체 · 가게에서 결제 · 휴대폰 결제 |
| `EXAMPLES` | 돈 보내기의 예시로 해 보기 3개 `{key, label, parts, to, amount, channel, time}`. `label`의 금액·시각 안 빈칸과 가운뎃점 앞은 `\u00a0`(줄 끝에서 `80만 / 원`, `오후 / 3시`로 끊기지 않게). 조각으로 그리려면 `subParts(ex.parts)`. 칩 글을 찾는 검사 스크립트는 `textContent.replace(/\s/g, " ")`로 비교한다 |

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
- 로고: `logo`(팔각형 + 멈춤 막대). 막대는 `.brand-mark` 안에서만 보인다(`.logo-bars`). 브라우저 탭 아이콘은 같은 모양의 `icons/logo.svg`(파란 둥근 사각, 흰 팔각형, 파란 두 막대, D9).
- 픽토그램 이름의 선 버전(D4): `check`(원 체크) `warning`(삼각 느낌표) `stop`(팔각 느낌표) `person` `helper` `money` `moon`(채우지 않은 달) `phone` `question` `ear` `store`. `icon()`은 늘 이 선 버전을 쓴다.
- 쉬운 말 카드 큰 그림(PICTO, 64, `picto(name)`): `check` `ear` `helper` `money` `moon` `person` `phone` `question` `stop` `store` `warning`. 돈 보내기 확인 카드 본문에만 쓴다.

## 10. CSS

화면 전용 스타일은 `css/views/{home,txns,notify,more}.css`에만 쓴다(index.html에 이미 연결됨).
규칙: 글자 크기는 rem만, 1rem 이상(px 금지), 터치 영역 2.4rem 이상, 인라인 style 속성 금지(`h()`의 style은 CSSOM이라 괜찮음), 외부 URL 금지.

### 10.1 토큰 (`:root`, 어두운 모드는 자동으로 바뀜)

- 간격(새 규칙은 토큰만): `--space-1 .25rem` `--space-2 .5rem` `--space-3 .75rem` `--space-4 1rem` `--space-5 1.5rem` `--space-6 2rem`
- 글 리듬: `--gap-sent .15rem`(같은 문단 문장) < `--gap-list .35rem`(목록 항목·카드 제목 → 본문) < `--gap-para .6rem`(문단) < `--gap-section`(= `--space-5`, 섹션 제목 앞). `--gap-block`(= `--space-3`, 카드끼리) `--gap-action`(= `--space-4`, 본문 → 버튼) `--pad-card 1.25rem` `--gap-sheet-title .4rem` `--gap-sheet-sub 1.1rem` `--indent`(점 목록 들여쓰기)
- 줄 높이: `--lh-body 1.6`(body) `--lh-sub 1.55`(.muted·.hint·.row-sub·.page-sub·.sheet-sub) `--lh-title 1.3`(h1~h5·제목) `--lh-num 1.2`(큰 숫자) `--lh-ui 1.3`(버튼·칩·배지·탭·토스트). CSS의 line-height는 이 토큰만 쓴다(한 글자 상자의 `1`만 예외, 테스트가 확인)
- 글 폭: `--measure 34em`(`p { max-width }`)
- 목록 줄: `--ic-row`(둥근 그림, `min(2.4rem, 10vw, 56px)`) `--gap-row`(그림 ↔ 글) `--pad-row`(좌우 여백). 들여쓰기 맞춤은 `calc(var(--ic-row) + var(--gap-row))`

- 바탕·글: `--bg` `--bg-sub`(앱 바탕) `--surface`(카드) `--surface-2` `--line` `--text` `--text-2` `--text-3` `--text-4`
- 강조: `--primary` `--primary-weak` `--primary-weak-text`
- 상태(늘 아이콘·글과 함께): `--danger` `--danger-weak` `--danger-text` `--caution` `--caution-weak` `--caution-text` `--ok` `--ok-weak` `--ok-text`
- 차트: `--chart-1`~`--chart-5`(파랑·청록·호박·자홍·보라, 밝게·어둡게 모두 바탕 대비 3:1 이상, 이웃한 색은 색약 시뮬레이션 ΔE 11 이상), `--chart-grid`, `--chart-track`, `--chart-flag`(걱정 거래 점)
- 그 밖: `--shadow-card` `--title-section` `--r-s/m/l/xl` `--gutter` `--nav-h`

### 10.2 공용 클래스

| 묶음 | 클래스 |
|---|---|
| 글 | `.page-title` `.page-sub` `.section-title`(+ `.link`) `.muted` `.strong` `.center` `.tnum` `.sr-only` `.sent` |
| 카드·목록 | `.card`(`.flat` `.tight` `.hero`) `.card-row` `.list` `.list-head` `.row`(`.wrap`) `.row-icon`(`.blue` `.red` `.orange` `.green`) `.row-main` `.row-title`(잘라 쓰지 않고 줄을 바꾼다) `.row-sub` `.row-end` `.row-amount`(`.in`) `.row-chev`(28px까지) `.row-tags.full` `.menu-row` `.date-head` |
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
| 줄바꿈 | `.nowrap`(숫자 + 단위 묶음, `keepNodes`가 붙임) `.tel-text`(전화번호: 하이픈 뒤에서만) `.email-text`(`breakableEmail`과 같이) |
| 점 목록 | `.bullets`(점·들여쓰기 하나·항목 간격 .35rem, `.about-bullets`·`.consent-bullets`·`.notice ul`도 같은 규칙) `.lead-strong`(문단 첫 문장만 굵게) |
| 소리 | `.speak-btn`(speakButton이 붙임) `.voice-note`(noVoiceNote) — `html[data-voice]`로 보이고 숨음 |
| 상태 배지 | `.badge.ok-line`(내가 확인함) |
| 왜 걱정되나요 | `.ai-explain` `.ae-head` `.ae-group` `.ae-ai` `.ae-title` `.ae-list` `.ae-diff` `.ae-diff-value` `.ae-only` |
| 메뉴 | `.menu-soon`(준비 중 배지 줄) `.menu-row.is-soon` |

### 10.3 공용 배치 규칙(2026-10-03, 큰 글씨·좁은 화면·가로 화면)

- 글 줄바꿈(L8): `p, li, .sent`는 `text-wrap: pretty`(마지막 줄 한두 글자 방지), 배지·칩·버튼·제목·탭은 `text-wrap: balance`. `textarea.input`은 `word-break: keep-all; overflow-wrap: break-word`.
- 아래 탭(L3·L6): 휴대폰 폭에서 탭 칸 높이·여백·간격에 px 상한(글자 200%에서도 이름이 탭 안에). 320폭에서는 탭 사이를 넓히고 이름 안 빈칸을 좁힌다.
- 안내 상자(L4): `.notice` 여백·아이콘·`ul` 들여쓰기에 화면 폭 상한. 글 칸이 6글자보다 좁아질 때만(320폭 아주 큰 글씨) 아이콘이 글 위 줄로 올라간다(`.notice > svg + * { flex: 1 1 6em }`, 2026-10-03 2차: 9글자 기준은 320폭 1.3배의 짧은 글에서도 아이콘을 올려 보냈다. 컨테이너 쿼리를 쓰지 않음: 글자 배율을 나중에 바꾸면 옛 배율로 판단하는 브라우저가 있음). 안내 상자 안 첫 글 묶음은 하나의 요소(div·p·ul)로 넣는다.
- 머리글 제목(L4): 두 줄까지 보인다(잘림 줄임표 대신).
- 표 숫자(L9): 좁은 화면 카드 모양 표에서 `td.num` 값은 끊지 않고 칸 이름(`data-label`)만 줄을 바꾼다.
- 고르기 묶음(L10): 카드 밖 `.segmented` 바탕은 페이지 바탕보다 진하다(고르지 않은 칸도 버튼으로 보임). 칸 폭은 `--seg-min`(칸 이름이 한 줄에 드는 폭, rem). 셋인 묶음은 한 줄에 셋이 다 들지 않으면 한 칸씩 세로로(2+1 없음), 넷인 묶음은 4 → 2+2 → 1(2026-10-03 2차, `:has()` + `min()/max()` 식). 어떻게 보내요?는 `.seg-pay-channel { --seg-min: 9rem }`, 알림 방법은 4.5rem, 글자 크기·화면 모드는 4.6rem(한 칸씩일 때는 견본과 이름을 한 줄에).
- 목록 줄(2차): `.list`는 크기 컨테이너다. 목록 폭이 9글자보다 좁으면(360폭 글자 2배) 줄 앞 둥근 그림(`.row-icon`)을 빼 글 칸을 넓힌다(시각 `오전 11시 25분`이 한 줄에). 알림 보내기 거래 줄(단계 카드·거래 고르기가 13글자보다 좁을 때)은 표시 태그의 그림도 뺀다(`휴대폰 / 소액결제 / 급증` 꼬리 막기). 지울 것 태그(`.wipe-items`)는 낱말 묶음을 지킨다(`내가 / 확인한 거래`).
- 버튼(2차): 그림은 `min(1.25rem, 7vw)`, 작은 버튼 좌우 여백은 `min(.85rem, 3.5vw)`, 칩 좌우 여백은 `min(1rem, 5vw)`(큰 글씨에서 이름 칸을 지킨다). 두 줄 이름 버튼(받는 사람 + 할 일)의 파란 바탕은 `--primary-strong`(흰 글 5.4:1).
- 스위치(L11): 보이는 크기가 작아져도 누르는 자리는 `::before`로 48px 이상.
- 가로·짧은 화면(L14, 높이 480px 이하): 아래 탭은 그림·이름 한 줄(높이 최대 60px), `.cta-bar`는 따라오지 않음, 시트는 화면 높이를 거의 다 쓴다.
- 하는 중 버튼: `.btn[aria-disabled="true"]`는 꺼진 모양, `[aria-busy]`는 돌림표(ui.busy·담기 버튼).
- 엔진 띠: `.engine-bar svg`는 1.25rem(FE-12), 글은 `p`(문장마다 한 줄).

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
- 쓰지 않는 문구: 막지 않아요, 결정은 내가 해요, 결정은 본인이 해요, AI 혼자서는, 연습 화면, 실제로 돈이 나가지 않아요, 보내지 않고 멈춘 것, 연습용 정답, (가려서 저장해요), 127.0.0.1, 안전 정지(앱 이름은 SafePause), 심사·시연용, 이 기기(장소는 `deviceWord()`). 당사자 화면에 제안서라는 말도 쓰지 않는다.
- 담기 글은 `FLAG_TEXT`, 내가 한 거예요 글은 `REVIEW_TEXT`만 쓴다(화면마다 다른 토스트 금지).
- 토스트·띠·li·표 칸도 한 문장 한 줄이다(토스트는 `toast`가 나눔, li 안 설명은 `h("li", null, h("p", {text}))`).
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
- 2026-10-03 더한 검사: 금지 문구(결정은 본인이 해요·심사·시연용·이 기기), 선 아이콘 체계(`test_line_icon_system`), 파비콘(`test_favicon_matches_logo`), 담기·내가 한 거예요 용어(`test_flag_and_review_terms`, 알림 카드 포함 `test_flag_terms_same_on_every_screen`), 공용 계약 이름(`test_shared_contract_exports`), 금액 미리 보기(`test_amount_preview_not_rounded`: money.js가 `= ${formatWon(` 대신 `amountPreview(`), 예시 칩 줄바꿈 없는 빈칸, 음성 늦게 준비, busy·시트 초점, 토스트·엔진 띠 한 문장 한 줄, 연락처 창 하나, 엔진 기본 요청·FIFO, 큰 글씨 공용 배치.
- 2026-10-03 성능 확인 다시 계산 검사: `test_eval_recompute_contract_2026_10_03`(eval.js가 `{seeds: 20, seed_start: 21}`로 표준·경계 변형을 요청하고, `report_set`·`intensity`가 맞을 때만 견주고, 두 번째 세트 전에 `ctx.alive()`를 보고, 다른 계산 버튼을 `aria-disabled`로 잠그는지. 화면 `REF_PATHS`가 `tests/test_eval_run_api.py` `REFERENCE_PATHS`와 같은지). 백엔드 쪽 재현은 `tests/test_eval_run_api.py::test_eval_run_reproduces_report_set`.
- 2026-10-03 글 정리 검사: 간격 토큰·문장 < 목록 < 문단 < 구역(`test_spacing_tokens_and_rhythm`), 줄 높이 토큰만·글 폭 34em(`test_line_height_system_and_measure`), 숫자 묶음·subParts(`test_keep_bundles_and_short_text`), 한 문장짜리 p 줄줄이 금지(`test_paragraphs_group_related_sentences`), 재검증 남은 문제 계약(`test_reverify_layout_contracts_2026_10_03`).
- 화면 확인: `python scratchpad/tools/webcheck.py --routes … --setup sample --out <폴더>`(360x780, `--font 2`, `--desktop`, `--dark`), errors가 빈 목록이어야 한다.

## 13. 백엔드 API 빠른 참조(설계서 3절, 실제 구현 기준)

| 요청 | 응답 |
|---|---|
| `GET /api/helpers` | 목록 `[{id, name, relation, phone, email, phone_masked, email_masked, contact, identifiers, min_level, signal_scope, active}]` |
| `PUT /api/helpers` | 목록 전체(`phone`, `email` 원본 포함) → 저장된 목록 |
| `GET /api/counselors` | `{items: [{id, name, kind, phone, email, memo, active}], presets: [{kind, name, phone, email, memo}]}` |
| `PUT /api/counselors` | 목록 전체 → `{items}` (이름 1~30자, 메모 0~100자, 20곳까지) |
| `GET /api/transactions?level=all\|caution\|high\|flagged&limit&offset&q&since&until` | 항목에 `flagged`·`reviewed`·`notified_at`·`ai`. 최상위 `summary`(탐지 등급별 수, 그대로)·`open_summary`(내가 확인한 것을 뺀 수)·`reviewed_count`·`matched` |
| `GET /api/flags` | `{items: [{txn_id, created_at, item}]}`(최근 담은 것부터, 거래 살펴보기 동의 필요) |
| `POST /api/flags` / `POST /api/flags/remove` | `{txn_id}` → `{ok, count}`. 없는 거래는 404 "그 거래를 찾지 못했어요." |
| `POST /api/notices/record` | `{channel: sms\|email\|call\|copy, recipients: [{kind: helper\|counselor, id, name}], txn_ids, message}` → 기록 1건(recipients에 id도 남음) |
| `POST /api/notices/remove` | `{id}` → `{ok, count}`. 직접 보낸 기록만, 그 밖은 404 "그 알림 기록을 찾지 못했어요." |
| `GET /api/notices` | `{items: [kind "auto"(적어 둔 기록, 아직 안 보냄) 또는 "manual"(직접 보낸 기록)], delivery_note}` |
| `POST /api/reviews` / `POST /api/reviews/remove` | `{txn_id}` → `{ok, count}`(내가 한 거예요 ↔ 확인 취소). 앞쪽만 거래 살펴보기 동의 필요 |
| `POST /api/transactions/remove-checked` | `{txn_id}`(live- 확인 기록만) → `{ok, count}`. 그 밖은 400 "보내기 전 확인 기록만 지울 수 있어요." |
| `GET /api/insights` | 돈 흐름 분석(as_of·months·this_month·prev_month·compare·channels·time_bands·top_payees·flagged_total·checked_excluded). 보내기 전 확인 기록은 모든 수치에서 뺀다 |
| `GET /api/cards?limit=` | 쉬운 말 카드 `{total, open, reviewed, items, …}`(open은 내가 확인한 것을 뺀 수) |
| `GET /api/export/summary` | `{filename, mime: "text/plain", text, note}` 조력자·기관용 한 장(이름·계좌 없음) |
| `POST /api/data/upload` | 파일 + `mode: replace\|append` → `{source, mode, added, duplicates, report, summary, levels, ai_only}`. `.csv .txt .xls .xlsx` |
| `POST /api/data/sample` | `{persona, seed, scenarios}`(기본 worker·10) → `{…, levels, ai_only}` |
| `GET /api/payees` | 최근 계좌로 보낸 사람 이름 `{items}`(돈 보내기 칩) |
| `POST /api/safepause/check` | `{to, amount, channel, to_id, time?}` → `{pending, assessment, card, notify_plan_preview, ask_helper_preview, ts_note}` |
| `POST /api/safepause/decide` | `{pending, decision: send\|cancel\|ask_helper, helper_ids?}` → `{decision, added_to_history, pending, assessment, notify_plan, notices_recorded, result_title, result_lines, delivery_note, ts_note}` |
| `POST /api/notify/suggest` | `{txn_ids, pending?}` → `{helpers: [{id, name, suggested, conflict, reason}], counselors: [{id, name, suggested}], counseling_due, counseling_reason: "repeat"\|"conflict"\|""}`. 상담하는 곳은 suggested여도 화면이 저절로 체크하지 않는다(`?to=counselors`일 때만) |
| `POST /api/eval/run` | `{seeds: 1~20(기본 5), seed_start: 1~10000(기본 1), intensity: "standard"\|"subtle"(기본 standard), modes: [fused\|rules\|anomaly](1~3), personas?}` → `{personas, seeds(쓴 seed 목록), seed_start, seed_end, intensity, report_set, modes, results, elapsed_sec, note}`. report_set은 인물 3명 × seed 21~40일 때 참(방식 수·강도는 따지지 않음). 잘못된 값은 422 `입력한 값을 확인해 주세요: 시작 번호(seed)`·`… 시나리오 종류` |

계약의 자세한 내용은 `docs/v03_spec.md` 3.7절과 `docs/v03_fixplan.md` 3절을 본다.

파일 올리기는 `api("POST", UPLOAD_PATH, undefined, {blob, name, mapping, mode})`로 부른다. api.js가 PC에서는 multipart 칸 `mode`, 앱 엔진에서는 본문 `mode`로 넘기고, `UPLOAD_MODES`(`["replace", "append"]`)를 내보낸다. txns.js는 이 값이 있을 때만 이어 붙이기·모두 바꾸기 고르기 창을 보인다.

앱(엔진 모드)에서는 동의·조력자·상담하는 곳·알림 기록(기록·지우기)·내가 한 거예요(표시·취소)·확인 기록 지우기·모두 지우기가 AI 준비 전에도 바로 처리된다(worker.mjs BASIC, 파이썬 쪽 시험 `test_new_light_routes_do_not_load_numpy`).
AI 부분(numpy·scikit-learn)만 못 켜면 `engine.status`가 `{stage: "error", fatal: false}`이고 기본 요청은 계속 처리된다(AI가 필요한 요청만 503, FE-03). 파이썬을 켜지 못하면 `fatal: true`로 모든 요청이 503이다. 동의 바꾸기·모두 지우기(우선 요청)는 줄 앞쪽에 들어가되 우선 요청끼리는 온 순서대로 처리된다(FE-05). 담은 거래·돈 흐름 분석·거래 목록, 돈 보내기의 check·decide·payees, 받는 사람 추천(suggest)은 거래 판단(numpy)이 필요해 AI 준비가 끝난 뒤 온다(worker.mjs BASIC에 넣지 않는다, 테스트가 확인).

## 14. 돈 보내기·내 은행 앱(money.js·bankapp.js, css/views/money.css)

- money.js(`export default {title, render}`, 보내기 탭이 부름)
  - 입력: 받는 사람(최근 보낸 사람 칩, `GET /api/payees`), 금액(`parseKoreanAmount`, 아래 줄은 `amountPreview(n)` 정확한 원 단위 하나 `300,000원`(2026-10-03 RF-4: 반올림한 `= 30만 원` 표기는 쓰지 않음), 0·100억 원 한도는 그 자리에서), 방법(`PAY_CHANNELS`), 자세히(보낼 시각 지금·오후 3시·밤 11시·새벽 2시, 계좌번호)
  - 오류는 틀린 칸 바로 아래(받는 사람 `#pay-to-error`, 금액 `#pay-amount-easy`), 서버 오류는 확인 버튼 위(`#pay-error`)
  - `POST /api/safepause/check` → 카드(안전 정지 카드 규칙은 파일 머리 주석) 또는 걱정 없음 결과 → `POST /api/safepause/decide`
  - 걱정되는 점이 없으면(카드 없음) decide를 부르지 않고 걱정되는 점이 없어요 결과만 보인다(계좌 이체일 때만 은행 앱 열기)
  - 결과: 보낼래요 → 요약 + `bankAppActions()`(계좌 이체일 때만) + 필수 문장, 안 보낼래요 → 보내지 않았어요 + [알림 보내기로 문자·메일 보내기](카드가 있었을 때), 물어볼래요 → 제목 조력자에게 물어봐요 + [문자로 물어보기]·[메일로 물어보기](`#/send?mode=notify&txn=…&helper=…&ask=1&channel=…`, 할 수 있는 방법만)
  - 결과 제목: 보낼래요·안 보낼래요는 decide의 `message`(계좌 이체 `내 은행 앱에서 보내 주세요.`·`보내지 않았어요.`, 가게·휴대폰 결제 `결제는 직접 해 주세요.`·`결제하지 않았어요.`), 물어볼래요는 `result_title`·`result_lines`. 서버 응답이 없는 동의 꺼짐 결과만 화면 표(SEND_TITLE, 같은 글)를 쓴다
  - 거래 살펴보기 동의가 꺼져 있으면 확인하지 않은 결과 + 은행 앱 + 동의 켜러 가기
  - `checkedItem(id, epoch)`: 확인한 거래 항목(물어볼래요·안 보낼래요는 거래 이력에 적지 않으므로 notify.js가 이것으로 미리 고른다. `unsaved: true`면 suggest의 txn_ids에서 빼고 `pending`으로 넘긴다). 이 창의 기억 + 이 탭의 sessionStorage(`safepause.checked`: 받는 사람 이름·금액·방법·시각·등급·신호·돈 받는 조력자 id, 계좌번호 칸 값은 넣지 않음, 5건까지). `clearChecked()`는 둘 다 지운다(consent.js가 모두 지우기·거래 살펴보기 끄기 때 부른다)
  - 결과 글(2026-10-03 2차): 물어볼래요는 제목을 되풀이하는 서버 첫 줄을 받는 사람·금액만 남겨 다음 줄과 합친다(`김*호에게 30만 원을 아직 보내지 않았어요.`, `askLines`). 조력자 설정대로 적어 둔 기록 안내는 서버 문장과 장소 문장을 한 문장으로(`이영희에게 알릴 수 있게 이 휴대폰에 적어 두기만 했어요. 문자나 메일은 알림 보내기에서 직접 보내요.`, `recordedNote`). 내 거래에 적는 날짜 안내(ts_note)는 접어 둔다(`details.mn-ts`, 소리로 듣기에는 그대로)
  - 필수 문장 `SafePause는 돈을 보내지 않아요. 보내기는 내 은행 앱에서 해요.`(화면 위 안내·결과). 연습이라는 말과 PRACTICE_NOTE는 쓰지 않는다
  - 계좌 연결해서 바로 보내기는 `comingSoonSheet`(단계 5개)만
- bankapp.js
  - `getBankApp()`·`saveBankApp(app)`·`clearBankApp()`: localStorage `safepause.bankApp = {package, label}`(try/catch)
  - `pickBankApp()` → `Promise<app | null>`: 검색 칸 + 은행·결제 앱(이름에 은행·뱅크·bank·페이·pay·증권·카드) 먼저 + 다른 앱. 회사 이름은 넣지 않는다
  - `openBankApp(app)`, `bankAppUnavailable()`(PC면 `은행 앱은 휴대폰 앱에서 열 수 있어요.`)
  - `bankAppActions()`: [내 은행 앱 열기](고른 앱 이름) / [다른 은행 앱 고르기], 못 열면 `은행 앱을 열지 못했어요. 다시 골라 주세요.`
  - `bankAppSettings()`: 앱 설정의 내 은행 앱(고르기·바꾸기·지우기). 동의 화면의 모두 지우기는 `clearBankApp()`도 부른다
- notify.js 받는 사람 추천: 거래를 고르거나 바꿀 때 `POST /api/notify/suggest {txn_ids}` → 추천 배지·미리 체크(본인이 바꾼 사람은 그대로), 돈을 받은 조력자는 체크를 풀고 `이 거래에서 돈을 받은 사람이에요. 다른 사람에게 알리는 게 좋아요.`, 그래도 체크하면 보내기 전에 확인 시트. 추천을 못 받으면 추천 없이
- notify.js 거래 고르기 시트(2026-10-03 2차): 고르기 버튼 하나(`N건 고르기`·`고르지 않기`)만 든 낮은 띠(`.np-pick-bar`, position sticky, 버튼 48px 이상 + 위아래 .5rem)가 시트 아래에 늘 붙어 있다. 글자 2배에서도 시트의 20%쯤이라 첫 줄을 고른 뒤 바로 누른다(1차의 붙박이 풀기 `fitActions`는 없앰). 닫기는 제목 줄 오른쪽(`.np-pick-close`, 제목 칸이 9글자보다 좁으면 다음 줄 오른쪽). 고른 거래·거래 고르기 줄은 날짜·시각·방법을 따로 조각으로(`subParts`)
- notify.js 앱 열기 버튼: 받는 사람 줄(`.np-send-who`)은 굵기 700·흐림 없음, 파란 버튼 바탕은 `--primary-strong`(흰 글 5.4:1, 밝게·어둡게 같음). 그림은 첫 줄(받는 사람) 가운데
- CSS(money.css): `.send-tabs` `.send-panel` `.mn-must` `.mn-form` `.mn-more` `.amount-easy`(`.bad`) `.pause` `.pause-head` `.pictos` `.pause-title` `.pause-question` `.helper-note` `.choice-btn` `.sheet.split`(`.sheet-body` `.sheet-foot`) `.result-hero`(`.stop` `.ask`) `.result-lines` `.result-notes` `.mn-summary` `.mn-must-line` `.ba-*`

## 15. 2026-10-03 화면 공용 계약 요약(수정 계획 2절)

화면 담당은 아래 이름만 쓴다. 공용 모듈에 더 필요한 것이 있으면 공용 담당에게 요청한다.

| 위치 | 이름 | 쓰는 법 |
|---|---|---|
| components.js | `aiExplain(item)` | 거래 시트·알림 카드 자세히의 왜 걱정되나요. `item.ai`가 없으면 약속(규칙)만 |
| components.js | `reviewBadge(item)` · `notifiedBadge(item)` · `flagBadge(item)` | 상태면 배지, 아니면 null |
| components.js | `flagButton(ctx, item, opts)` · `reviewButton(ctx, item, opts)` | 담기·내가 한 거예요 토글(글·토스트는 FLAG_TEXT·REVIEW_TEXT) |
| components.js | `speakButton(getText, opts)` · `noVoiceNote()` | 자동 정지·음성 늦게 준비 처리 포함 |
| labels.js | `FLAG_TEXT` · `REVIEW_TEXT` · `NOTIFIED_TEXT` · `AI_TEXT` | 문구 상수 |
| format.js | `amountPreview(n)` · `bandLabel(band)` · `keepUnits(text)` · `breakableEmail(text)` | 금액 미리 보기·시간대 이름·줄바꿈 |
| native.js | `pickContact(kind)` · `lastPickResult()` | 중복 호출 방지·실패 안내 |
| ui.js | `openSheet` · `confirmSheet` · `busy` | 닫힌 뒤 연 버튼으로 초점, busy 중에도 초점 유지 |
| speech.js | `voiceStatus()` | ready·pending·none, `html[data-voice]` |

```js
// money.js 금액 칸 아래 줄(RF-4): 정확한 원 단위 하나
setText(amountEasy, amountPreview(n));            // "3,500원" (= 4천 원 같은 반올림 표기 없음)

// home.js 시간대 막대 이름(1-E)
items = d.time_bands.map((b) => ({ label: bandLabel(b.band), sub: BANDS[b.band].range, … }));

// helpers.js·counselors.js 연락처에서 불러오기(IA-5): 두 번 눌러도 앞 창의 결과가 들어온다
const c = await pickContact("phone");
if (c) { phone.value = c.value; if (!name.value) name.value = c.name; }   // null이면 안내는 native.js가 이미 띄움

// 목록에 보이는 메일(L8)
h("span", { class: "row-sub email-text", text: breakableEmail(helper.email_masked) });

// 화면에 보이는 긴 글 속 금액·시각(C13·L8)
h("p", { text: keepUnits(line) });
```

- 같은 화면 안에서 패널을 바꿀 때 `speech.stop()`을 따로 부를 필요가 없다(버튼이 떨어지면 멈춤). 패널을 `hidden`으로 숨겨도 멈춘다.
- 음성 없음 안내는 `noVoiceNote()`를 그대로 넣는다(옛 `speech.available() ? null : h("p", {class: "mn-novoice", …})`도 CSS로 맞게 보이지만 새 코드는 noVoiceNote).
- 준비 중 메뉴는 `menuRow({soon: true, …})`만 쓰면 배지 자리가 같다(직접 만든 메뉴 줄은 `.menu-soon` 줄을 제목 아래에 둔다).

## 16. 화면 글 정리(2026-10-03, `docs/v03_typography.md`)

화면 담당이 글을 넣을 때 지킬 것. 공용 CSS·ui.js가 대부분을 맡고, 화면 쪽은 문단과 클래스만 맞추면 된다.

| 할 일 | 하는 법 |
|---|---|
| 같은 내용 2~3문장 | p 하나에 `text`로(문장마다 한 줄은 자동). 줄 목록이면 `lines.join(" ")` 또는 `paragraphs(lines)` |
| 다른 내용 | p를 나눈다(`p + p` .6rem). 목록처럼 촘촘해야 하면 `ul` 또는 `--gap-list` |
| 숫자·시각·금액·전화번호 | `text`로 넣으면(p·dd·li·span·버튼 모두) 묶음이 자동(`setText` → `keepNodes`). 노드로 넣는 이름은 `keepNodes(name)` |
| 버튼 이름 | `h("button", {class: "btn …"}, icon(…), h("span", {text}))`면 자동으로 `span.btn-label`(그림이 첫 줄 글 앞). 따로 클래스를 단 글 span은 묶지 않는다 |
| 같은 문장이 카드마다 | 목록 위에 한 번만(알림 카드 질문 줄은 모든 카드가 같으면 `alertCard(item, {question: false})` + 목록 요약 문장) |
| 카드 | 제목(h2·h3) 아래 .35rem, 버튼(`.card > .btn`·`.btn-row`·`.card-actions`) 위 1rem은 자동. 따로 margin을 주지 않는다 |
| 안내 상자 | `notice > svg + (p 또는 div)`. 아이콘은 첫 줄 가운데(1lh)로 자동 |
| 아이콘 + 글 한 줄(`.ba-why` 등) | 아이콘 `margin-top: max(0px, calc((1lh - 아이콘 크기) / 2))`로 첫 줄 가운데에 맞춘다 |
| 줄 높이 | 숫자를 쓰지 않고 `var(--lh-*)` |
| 큰 글씨(200%) | 여백·그림은 `min(…, vw)`(필요하면 px 상한도). 좁은 칸은 그림을 빼거나(`@container`) 글을 줄 전체 폭으로 내린다(알림 보내기 받는 사람 줄 참고) |

측정(정본): `scratchpad/w5/rv_typo/measure2.js`·`run_audit.py`(1차의 `w5/typo/measure.js`는 줄 높이 1.3 글의 줄을 합쳐 세는 결함이 있어 쓰지 않는다). 2차는 `scratchpad/w6/fix/audit/`의 `measure3.js`(measure2 계산은 그대로 두고 필드만 덧붙임: 글자-글자 사이 줄바꿈 `wordChop`과 그중 `wbr` 자리가 아닌 `wordChopFree`, 빈칸·`wbr`이 아닌 곳에서 바뀐 줄 `chopFree`, 같은 줄 안 inline-block 나란히(`overlapsInline`)와 그 밖의 겹침, 아이콘·placeholder·숨김 넘침)와 `run_audit.py --out --repo`로 20개 경로 + 시트 21상태 × 폭 320·360·412·768·1280 × 글자 1·1.3·1.6·2배 × 밝게·어둡게(1,640화면)를 잰다. 결과는 `docs/v03_typography.md` 4.4·5절.

## 17. 성능 확인: 보고서 수치 다시 계산(2026-10-03, `views/eval.js`)

화면 `#/more/eval`에서 제출 보고서 검증 세트와 같은 설정으로 다시 계산하고, 화면에 넣은 기준값(`web/data/eval_reference.json`)과 견준다.

| 단계 | 내용 |
|---|---|
| 요청 | `POST /api/eval/run {seeds: 20, seed_start: 21, intensity: "standard", modes: ["rules", "fused", "anomaly"]}` → 끝나면 같은 요청을 `intensity: "subtle"`로 한 번 더(차례로 두 번) |
| 견주는 조건 | 응답 `report_set === true`이고 `intensity`가 보낸 값과 같을 때만. 아니면 `보고서와 같은 설정(seed 21~40)으로 계산하지 못했어요. …` 안내 |
| 견주는 값 | 세트마다 방식 3개 × (아래 키 12개 + `by_scenario` 5종류 × {caution, high, n} 15개 + `n_cases` 1개) = 84개, 두 세트 168개. 반올림하지 않고 `===` |
| 결과 | 맨 위 결론 한 줄(모두 같아요 / N개가 달라요), 세트마다 지표 9줄 표(같아요·달라요 그림+글), 종류별 표는 접는 칸, 계산 환경(safepause·python·numpy·scikit-learn 버전) |
| 진행 | 단계 3개(표준 시나리오 300개 계산 → 경계 변형 300개 계산 → 보고서 수치와 견주기), 지난 시간 1초마다. 계산 중에는 계산 버튼 셋 가운데 누른 것은 busy, 나머지는 `aria-disabled` |
| 떠날 때 | 늦게 온 결과는 버리고(`ctx.req` → STALE), 두 번째 세트는 `ctx.alive()`가 참일 때만 보낸다. 앱 엔진은 이미 보낸 계산을 멈출 수 없어(워커 한 줄 처리) 그동안 다른 요청이 기다린다(화면 안내 문장) |

`eval_reference.json` 키 → 응답 `results[방식]` 안 자리(`tests/test_eval_run_api.py` `REFERENCE_PATHS`, 화면 `REF_PATHS`와 같다. `test_static_ui`가 두 표가 같은지 본다):

| 기준값 키 | 응답 경로 |
|---|---|
| scenario_caution / scenario_high | overall.recall_caution / overall.recall_high |
| scenario_caution_n / scenario_high_n / scenario_n | overall.caution / overall.high / overall.n |
| txn_high_recall / txn_caution_recall | confusion.high.recall / confusion.caution.recall |
| normal_alert_rate / normal_high_rate | normal.alert_rate / normal.high_rate |
| control_monthly_alerts / control_monthly_high | control.monthly_alerts / control.monthly_high |
| amount_before_first_alert_mean | overall.amount_before_first_alert_mean |
| by_scenario[종류].{caution, high, n} | scenario_recall[종류].{caution, high, n} |
| sets.X.n_cases | n_cases (60) |

직접 골라 계산해 보기(seed 1부터)는 그대로 두고 시나리오 종류(`#eval-intensity`)와 20번(느림)을 더했다. 보고서 수치와 같은 값이 나오는 기능이 아니라는 점을 첫 문단에 적는다.

잰 시간(seed 20개, 세 방식, 두 세트):

| 환경 | 표준 | 경계 변형 | 두 세트 |
|---|---|---|---|
| PC 서버(`Service.eval_run`, 백엔드 담당 측정) | 10.78초 | 10.14초 | 약 21초(화면 흐름 6조건 20.7~23.5초) |
| 앱 엔진 묶음을 헤드리스 Chrome(휴대폰 흉내 360×780)에서, 엔진 full 뒤 누름(통합 점검 2026-10-03) | 23.9초 | 19.5초 | 43.4초(화면 표시), 168개 모두 같음, holdout 원자료 1,100개 차이 0 |
| 디버그 APK를 에뮬레이터(Android 15 x86_64, 같은 PC)에서, 엔진 full 뒤 누름(통합 점검 2026-10-03) | 48.2초 | 40.6초 | 88.8초(화면 표시), 168개 모두 같음, holdout 원자료 1,100개 차이 0 |

휴대폰 실기 시간은 재지 않았다(자세한 조건은 `docs/mobile.md` 3장). 화면 안내 문장(`TIME_HINT`)은 잰 값만 쓴다.
