/* 오래된 화면 프로그램(웹뷰·브라우저) 안내. 고전 스크립트이고 ES5만 쓴다(var·function, 화살표·const·let·백틱·?.·?? 없음).
 * main.js(모듈)가 뜨면 window.__SAFEPAUSE_STARTED__를 남긴다. 모듈 스크립트는 DOMContentLoaded보다 먼저 실행되므로,
 * 문서를 다 읽었는데 표시가 없으면 모듈을 못 읽은 것이다(모듈 모름·문법 모름·불러오기 실패). 그때 #compat 안내를 보인다.
 * main.js의 시작 검사(compat.js)도 같은 안내(window.__safepauseShowCompat)를 쓴다. docs/mobile.md 지원 범위 참고.
 */
(function () {
  var noModule = !("noModule" in document.createElement("script"));   // 모듈 스크립트를 모르는 버전(Chrome 61 미만)

  function major() {
    var m = /Chrome\/(\d+)/.exec(navigator.userAgent || "");
    return m ? m[1] : "";
  }

  function show(reason) {
    var box = document.getElementById("compat");
    if (!box) return;
    var isApp = !!(window.SafePauseNative || window.__SAFEPAUSE_ENGINE__);
    var parts = box.querySelectorAll("[data-for]");
    for (var i = 0; i < parts.length; i++) parts[i].hidden = parts[i].getAttribute("data-for") !== (isApp ? "app" : "pc");
    var ver = document.getElementById("compat-version");
    if (ver && major()) ver.textContent = "지금 버전 " + major() + " · 필요한 버전 " + (isApp ? "97" : "86") + " 이상";
    box.setAttribute("data-reason", reason);
    var app = document.getElementById("app");
    if (app) app.hidden = true;
    box.hidden = false;
  }

  window.__safepauseShowCompat = show;
  document.addEventListener("DOMContentLoaded", function () {
    if (noModule) show("no-module");
    else if (window.__SAFEPAUSE_STARTED__ !== true) show("module-failed");
  });
})();
