"""앱 묶음 경량화 확인 도구(개발용. 앱에는 들어가지 않는다). 헤드리스 Chrome으로 앱 안 엔진(Pyodide)을 켜서 본다.

    python android/slim_trace.py run --www <묶음> --out a.json        # 모든 API 부르기 + 쓴 모듈(sys.modules) 기록
    python android/slim_trace.py plan --trace a.json --pyodide <Pyodide 폴더>   # 뺄 scipy·sklearn 하위 패키지 목록
    python android/slim_trace.py compare --a a1.json --b b.json --noise a2.json # 응답이 같은지
    python android/slim_trace.py timing --www <묶음> --runs 3            # 엔진 준비 시간(basic·full)

run
- 묶음을 임시 폴더에 복사하고, 그 복사본의 engine/worker.mjs에만 기록용 코드를 붙인다(배포 묶음은 바꾸지 않음):
  파이썬 표준 출력·오류 모으기, 'slim-trace' 메시지에 sys.modules 목록으로 답하기.
- router ROUTES의 모든 경로를 부른다(연습용 거래·파일 올리기 csv/txt/xlsx/xls/html-xls와 잘못된 파일·거래 조회·담기·
  내가 한 거예요·알림 보내기 추천·돈 보내기 check→decide 세 갈래·insights·cards·notices·export·eval run 기본·
  보고서 세트(seed 21~40 표준·경계)·잘못된 요청·wipe). 부르지 않은 경로가 있으면 멈춘다.
plan
- sys.modules에 한 번도 나오지 않은 scipy·sklearn 하위 패키지(폴더) 중 가장 바깥 것을 후보로 둔다. 일부라도 쓰인 패키지는 남긴다.
- 오류 경로·안 쓴 기능에서만 불리는 모듈에 대비해 정적 분석으로 보강한다: 실제로 불린 모듈에서 출발해 import 문(함수 안
  늦은 import 포함)·importlib.import_module 등에 준 글자·scipy./sklearn.(별칭 포함) 속성 사슬·점 이름 글자 상수(설명문 제외),
  .so 안의 점 이름 글자를 따라 닿는 모듈을 모두 모은다(--lazy all: 닿은 모듈의 함수 안 import까지, 기본). 후보 안의 모듈에
  하나라도 닿으면 그 후보는 남긴다. 글자로 정할 수 없는 동적 import 자리는 dynamic_imports로 따로 보여 준다(사람이 확인).
compare
- b의 응답(상태 코드·본문)이 a와 같은지 본다. 봐주는 차이는 걸린 시간(elapsed_sec)과 글 속 시각(ISO 모양)뿐이다.
  --noise(같은 묶음을 한 번 더 돌린 결과)를 주면 a와 noise 사이에서 다른 칸이 a·b 사이와 같은지도 보여 준다.
timing
- 묶음마다 새 Chrome 프로필로 엔진을 켜서 basic·full 단계 시각(워커가 잰 값, 페이지 시작부터 잰 값)을 번갈아 잰다.
"""
from __future__ import annotations

import argparse
import ast
import base64
import functools
import http.server
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CHROME_CANDIDATES = (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                     r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                     "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
                     "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
ANDROID_UA = ("Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/140.0.0.0 Mobile Safari/537.36")
TRACE_PACKAGES = ("scipy", "sklearn")
WHEEL_OF = {"scipy": "scipy", "sklearn": "scikit-learn"}


# ---------------------------------------------------------------------------------------------
# 정적 서버·Chrome(CDP)
# ---------------------------------------------------------------------------------------------

def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".mjs": "text/javascript",
                      ".js": "text/javascript", ".wasm": "application/wasm", ".json": "application/json",
                      ".whl": "application/zip", ".zip": "application/zip"}

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args) -> None:
        pass


class _Server(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address) -> None:   # Chrome을 끌 때 끊긴 연결은 조용히 넘긴다
        if not isinstance(sys.exc_info()[1], (ConnectionError, OSError)):
            super().handle_error(request, client_address)


def serve(www: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    server = _Server(("127.0.0.1", 0), functools.partial(_Handler, directory=str(www)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


class CDP:
    """최소 웹소켓 CDP 클라이언트(표준 라이브러리만)."""

    def __init__(self, url: str) -> None:
        host_port, path = url[len("ws://"):].split("/", 1)
        host, port = host_port.split(":")
        self.s = socket.create_connection((host, int(port)))
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET /{path} HTTP/1.1\r\nHost: {host_port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            resp += self.s.recv(4096)
        self.buf = resp.split(b"\r\n\r\n", 1)[1]
        self.seq = 0
        self.events: list[dict] = []

    def _exact(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.s.recv(1 << 20)
            if not chunk:
                raise ConnectionError("CDP 연결이 끊겼어요")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send(self, obj: dict) -> None:
        data = json.dumps(obj).encode()
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else
                                bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else
                                bytes([0x80 | 127]) + struct.pack(">Q", n))
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _recv(self) -> dict:
        msg = b""
        while True:
            b1, b2 = self._exact(2)
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._exact(8))[0]
            payload = self._exact(n)
            if (b1 & 0x0F) == 0x9:
                continue
            msg += payload
            if b1 & 0x80:
                return json.loads(msg.decode("utf-8"))

    def call(self, method: str, params: dict | None = None, timeout: float = 60) -> dict:
        self.seq += 1
        my = self.seq
        self._send({"id": my, "method": method, "params": params or {}})
        self.s.settimeout(timeout)
        while True:
            m = self._recv()
            if m.get("id") == my:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})
            self.events.append(m)

    def evaluate(self, expr: str, timeout: float = 120):
        r = self.call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True},
                      timeout=timeout)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            return {"__error__": (d.get("exception") or {}).get("description") or d.get("text")}
        return r.get("result", {}).get("value")

    def errors(self) -> list[str]:
        out = []
        for ev in self.events:
            meth, p = ev.get("method"), ev.get("params", {})
            if meth == "Runtime.exceptionThrown":
                d = p.get("exceptionDetails", {})
                out.append((d.get("exception") or {}).get("description") or d.get("text"))
            elif meth == "Runtime.consoleAPICalled" and p.get("type") == "error":
                out.append(" ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))[:500])
            elif meth == "Log.entryAdded" and p.get("entry", {}).get("level") == "error":
                e = p["entry"]
                out.append(f"[log] {e.get('text')} {e.get('url', '')}"[:500])
        return out


# 문서가 열리기 전에: 워커가 보내는 준비 단계 메시지를 페이지 시각과 함께 적고, 워커 객체를 잡아 둔다.
PRELOAD = r"""
(() => {
  window.__slimStages = []; window.__slimWorkers = [];
  const OW = window.Worker;
  window.Worker = class extends OW {
    constructor(...a) {
      super(...a);
      window.__slimWorkers.push(this);
      this.addEventListener('message', (e) => {
        const m = e.data || {};
        if (m.type === 'stage') window.__slimStages.push({ stage: m.stage, message: m.message, detail: m.detail, fatal: m.fatal, t: performance.now() });
      });
    }
  };
})();
"""


def _chrome(path: str | None) -> str:
    for cand in ([path] if path else []) + list(CHROME_CANDIDATES):
        if cand and Path(cand).exists():
            return cand
    raise SystemExit("Chrome을 찾지 못했어요(--chrome으로 경로를 주세요).")


class Browser:
    def __init__(self, chrome: str) -> None:
        self.profile = tempfile.mkdtemp(prefix="sp_slim_chrome_")
        port = _free_port()
        self.proc = subprocess.Popen([chrome, "--headless=new", f"--remote-debugging-port={port}",
                                      f"--user-data-dir={self.profile}", "--no-first-run", "--no-default-browser-check",
                                      "--disable-extensions", "--disable-gpu", "--hide-scrollbars", "--lang=ko-KR",
                                      "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        targets: list = []
        for _ in range(200):
            time.sleep(0.1)
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                if any(t.get("type") == "page" for t in targets):
                    break
            except OSError:
                pass
        page = next(t for t in targets if t.get("type") == "page")
        self.cdp = CDP(page["webSocketDebuggerUrl"])
        for m in ("Runtime.enable", "Log.enable", "Page.enable"):
            self.cdp.call(m)
        self.cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": PRELOAD})
        self.cdp.call("Emulation.setDeviceMetricsOverride", {"width": 360, "height": 780, "deviceScaleFactor": 2,
                                                             "mobile": True})
        self.cdp.call("Emulation.setUserAgentOverride", {"userAgent": ANDROID_UA})

    def open_engine(self, base: str, limit: float = 300) -> dict:
        """첫 화면을 열고 엔진이 full(또는 error)이 될 때까지 기다린다. 단계별 시각을 돌려준다."""
        self.cdp.call("Page.navigate", {"url": f"{base}/#/home"})
        t0 = time.time()
        stages: list = []
        while time.time() - t0 < limit:
            time.sleep(0.25)
            stages = self.cdp.evaluate("window.__slimStages || []") or []
            if any(s.get("stage") in ("full", "error") for s in stages):
                break
        return {"stages": stages, **_stage_times(stages)}

    def close(self) -> None:
        self.proc.kill()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            pass
        shutil.rmtree(self.profile, ignore_errors=True)


def _stage_times(stages: list) -> dict:
    """워커가 잰 시각(detail 'NNNms': 워커 boot 시작부터)과 페이지 시각(문서 시작부터)."""
    out: dict = {"final": stages[-1]["stage"] if stages else None}
    for s in stages:
        m = re.fullmatch(r"(\d+)ms", str(s.get("detail") or ""))
        if s.get("stage") in ("basic", "full") and m and f"{s['stage']}_worker_ms" not in out:
            out[f"{s['stage']}_worker_ms"] = int(m.group(1))
            out[f"{s['stage']}_page_ms"] = round(s["t"])
    return out


# ---------------------------------------------------------------------------------------------
# run: 기록용 묶음 + 모든 API
# ---------------------------------------------------------------------------------------------

TRACE_HEAD = "self.__slimOut = []; self.__slimErr = [];   /* [slim_trace 기록용 묶음에만] */\n"
TRACE_TAIL = r"""
/* [slim_trace 기록용 묶음에만] 'slim-trace' 메시지에 sys.modules 목록과 파이썬 출력으로 답한다. */
{
  const base = self.onmessage;
  self.onmessage = async (e) => {
    const m = e.data || {};
    if (m.type !== "slim-trace") return base(e);
    let modules = null, error = null;
    try {
      await booted;
      try { await fullReady; } catch (_) { /* 단계 오류는 stage로 이미 알렸다 */ }
      modules = JSON.parse(py.runPython("import sys, json\njson.dumps(sorted(n for n, v in list(sys.modules.items()) if v is not None))"));
    } catch (err) { error = String(err && err.message || err); }
    self.postMessage({ type: "slim-trace", modules, error, stdout: self.__slimOut, stderr: self.__slimErr });
  };
}
"""
LOAD_OPTS = "fullStdLib: false })"


def make_trace_copy(www: Path, dst: Path) -> Path:
    shutil.copytree(www, dst)
    worker = dst / "engine" / "worker.mjs"
    text = worker.read_bytes().decode("utf-8")   # 줄바꿈(LF·CRLF)은 그대로 둔다
    anchor = text.find('import { loadPyodide } from "../pyodide/pyodide.mjs";')
    if anchor < 0 or "\n" not in text[anchor:] or text.count(LOAD_OPTS) != 1:
        raise SystemExit("worker.mjs 모양이 바뀌어 기록용 코드를 붙이지 못했어요(slim_trace.py를 고쳐 주세요).")
    cut = text.index("\n", anchor) + 1
    text = text[:cut] + TRACE_HEAD + text[cut:]
    text = text.replace(LOAD_OPTS, "fullStdLib: false, stdout: (s) => self.__slimOut.push(s), "
                                   "stderr: (s) => self.__slimErr.push(s) })")
    worker.write_bytes((text + TRACE_TAIL).encode("utf-8"))
    return dst


def upload_files() -> dict[str, str]:
    """올릴 파일(base64). 은행·카드사 모양 합성 파일은 tests의 만드는 함수를 그대로 쓴다."""
    sys.path.insert(0, str(ROOT))
    from tests import test_loader_bank_formats as bf
    fx = ROOT / "tests" / "fixtures" / "bank_formats"
    files = {
        "csv_bank": (ROOT / "sample_data" / "bank_export_example.csv").read_bytes(),
        "csv_student": (ROOT / "sample_data" / "student_normal.csv").read_bytes(),
        "csv_header_only": "거래일시,출금액,입금액\n".encode("utf-8"),
        "csv_unknown_cols": "가,나\n1,2\n".encode("utf-8"),
        "empty": b"",
        "garbage": bytes(range(256)) * 4,
        "txt_kakao": (fx / "kakaobank_like_unicode_text.txt").read_bytes(),
        "txt_passbook_cp949": (fx / "passbook_like_tab_cp949.txt").read_bytes(),
        "htmlxls_ibk_utf8": (fx / "ibk_like_table_utf8.xls").read_bytes(),
        "htmlxls_ibk_cp949": (fx / "ibk_like_table_cp949_br.xls").read_bytes(),
        "htmlxls_hyundai": (fx / "hyundaicard_like_table.xls").read_bytes(),
        "xlsx_kakao": bf.make_xlsx(bf._kakao_like_rows(False)),
        "xlsx_kakao_serial": bf.make_xlsx(bf._kakao_like_rows(True)),
        "xlsx_encrypted": bf.encrypted_xlsx(),
        "xls_kb_bank": bf.xls_file(bf._kb_bank_like_cells()),
    }
    return {k: base64.b64encode(v).decode() for k, v in files.items()}


CALLS = r"""
(async () => {
  const { engine } = await import('/js/engine-client.js');
  const out = {}; const order = [];
  const bytesOf = (s) => { const t = atob(s); const u = new Uint8Array(t.length); for (let i = 0; i < t.length; i++) u[i] = t.charCodeAt(i); return u; };
  const call = async (name, method, path, body, file) => {
    let payload = body === undefined ? null : body, bytes = null;
    if (file) { bytes = bytesOf(FILES[file.data]); payload = { mapping: file.mapping || '' }; if (file.mode !== undefined) payload.mode = file.mode; }
    const r = await engine.request({ method, path, body: payload, bytes });
    out[name] = { method, path, req: payload, file: file ? file.data : null, status: r.status, body: r.body };
    order.push(name);
    return r.body;
  };
  const enc = encodeURIComponent;
  // 동의 전·잘못된 요청
  await call('health', 'GET', '/api/health');
  await call('consent_get0', 'GET', '/api/consent');
  await call('txns_noconsent', 'GET', '/api/transactions?limit=1');
  await call('sample_noconsent', 'POST', '/api/data/sample', {});
  await call('consent_bad', 'PUT', '/api/consent', { monitoring: 'yes' });
  await call('consent_put', 'PUT', '/api/consent', { monitoring: true, helper_alerts: true, counseling_referral: true, given_by: 'self' });
  await call('consent_get', 'GET', '/api/consent');
  await call('summary_empty', 'GET', '/api/data/summary');
  await call('txns_empty', 'GET', '/api/transactions?limit=1');
  await call('cards_empty', 'GET', '/api/cards');
  await call('eval_file_empty', 'POST', '/api/eval/file');
  // 상담하는 곳·조력자
  await call('counselors_get', 'GET', '/api/counselors');
  const presets = (out.counselors_get.body && out.counselors_get.body.presets) || [];
  await call('counselors_put', 'PUT', '/api/counselors', presets.slice(0, 2).map((p) => ({ name: p.name, kind: p.kind, phone: p.phone, email: p.email, memo: p.memo, active: true })));
  await call('counselors_bad', 'PUT', '/api/counselors', [{ name: '' }]);
  await call('helpers_put', 'PUT', '/api/helpers', [
    { name: '이영희', relation: '딸', phone: '010-1234-5678', email: 'younghee@example.com', identifiers: [], min_level: 'high', signal_scope: [], active: true },
    { name: '김호', relation: '친구', phone: '010-2222-3333', identifiers: ['김*호'], min_level: 'caution', signal_scope: [], active: true }]);
  await call('helpers_get', 'GET', '/api/helpers');
  await call('helpers_bad', 'PUT', '/api/helpers', [{ name: 'x', min_level: 'low' }]);
  // 연습용 거래
  await call('sample_student', 'POST', '/api/data/sample', { persona: 'student', seed: 3, scenarios: false });
  await call('sample_benefit', 'POST', '/api/data/sample', { persona: 'benefit', seed: 2, scenarios: true, days: 200 });
  await call('sample_bad', 'POST', '/api/data/sample', { persona: 'nobody' });
  await call('sample', 'POST', '/api/data/sample', {});
  await call('summary', 'GET', '/api/data/summary');
  // 내 거래
  await call('txns_all', 'GET', '/api/transactions?level=all&limit=5');
  await call('txns_high', 'GET', '/api/transactions?level=high&limit=3');
  await call('txns_caution', 'GET', '/api/transactions?level=caution&limit=3&offset=2');
  await call('txns_q', 'GET', '/api/transactions?level=all&limit=3&q=' + enc('김*호'));
  await call('txns_range', 'GET', '/api/transactions?since=2026-06-01&until=2026-06-30&limit=3');
  await call('txns_bad', 'GET', '/api/transactions?level=bogus');
  const ids = ((out.txns_high.body && out.txns_high.body.items) || []).map((x) => x.txn.id);
  // 담기·내가 한 거예요
  await call('flag_add', 'POST', '/api/flags', { txn_id: ids[0] });
  await call('flags_get', 'GET', '/api/flags');
  await call('txns_flagged', 'GET', '/api/transactions?level=flagged');
  await call('flag_remove', 'POST', '/api/flags/remove', { txn_id: ids[0] });
  await call('flag_missing', 'POST', '/api/flags', { txn_id: 'nope' });
  await call('review_add', 'POST', '/api/reviews', { txn_id: ids[0] });
  await call('cards_after_review', 'GET', '/api/cards?limit=3');
  await call('review_missing', 'POST', '/api/reviews', { txn_id: 'nope' });
  await call('review_remove', 'POST', '/api/reviews/remove', { txn_id: ids[0] });
  await call('cards', 'GET', '/api/cards?limit=5');
  await call('cards_default', 'GET', '/api/cards');
  await call('cards_bad', 'GET', '/api/cards?limit=0');
  await call('insights', 'GET', '/api/insights');
  await call('payees', 'GET', '/api/payees');
  // 알림 보내기 추천
  await call('suggest_txns', 'POST', '/api/notify/suggest', { txn_ids: ids.slice(0, 2) });
  await call('suggest_pending', 'POST', '/api/notify/suggest', { txn_ids: [], pending: { to: '김*호', amount: 300000, channel: 'transfer', time: '02:00' } });
  await call('suggest_empty', 'POST', '/api/notify/suggest', {});
  // 돈 보내기: check → decide 세 갈래
  const hid = (out.helpers_get.body || []).map((h) => h.id);
  await call('check_high', 'POST', '/api/safepause/check', { to: '김*호', amount: 300000, channel: 'transfer', time: '02:00' });
  await call('decide_send', 'POST', '/api/safepause/decide', { pending: out.check_high.body.pending, decision: 'send' });
  await call('decide_send_again', 'POST', '/api/safepause/decide', { pending: out.check_high.body.pending, decision: 'send' });
  await call('check_cancel', 'POST', '/api/safepause/check', { to: '처음 보는 사람', amount: 1500000, channel: 'transfer', time: '03:10' });
  await call('decide_cancel', 'POST', '/api/safepause/decide', { pending: out.check_cancel.body.pending, decision: 'cancel' });
  await call('check_ask', 'POST', '/api/safepause/check', { to: '가상 상점', amount: 4500, channel: 'card', time: '12:00' });
  await call('decide_ask', 'POST', '/api/safepause/decide', { pending: out.check_ask.body.pending, decision: 'ask_helper', helper_ids: hid.slice(0, 1) });
  await call('decide_bad', 'POST', '/api/safepause/decide', { pending: { to: 'x', amount: 1 }, decision: 'maybe' });
  await call('check_bad', 'POST', '/api/safepause/check', { to: '', amount: -1 });
  await call('decisions', 'GET', '/api/decisions');
  await call('live_list', 'GET', '/api/transactions?level=all&limit=5&q=' + enc('김*호'));
  const live = ((out.live_list.body && out.live_list.body.items) || []).map((x) => x.txn.id).find((x) => /^live-/.test(x));
  await call('remove_checked', 'POST', '/api/transactions/remove-checked', { txn_id: live || 'live-none' });
  await call('remove_checked_bad', 'POST', '/api/transactions/remove-checked', { txn_id: ids[1] || 'x' });
  // 알림 기록
  await call('counselors_get2', 'GET', '/api/counselors');
  const cs = (out.counselors_get2.body && out.counselors_get2.body.items) || [];
  await call('notice_sms', 'POST', '/api/notices/record', { channel: 'sms', recipients: [{ kind: 'helper', id: hid[0] || '', name: '이영희' }], txn_ids: ids.slice(1, 2), message: '[SafePause] 확인해 주세요.' });
  await call('notice_email', 'POST', '/api/notices/record', { channel: 'email', recipients: [{ kind: 'counselor', id: (cs[0] || {}).id || '', name: (cs[0] || {}).name || '상담' }], txn_ids: [], message: '상담을 부탁드려요.' });
  await call('notice_bad', 'POST', '/api/notices/record', { channel: 'fax', recipients: [], message: '' });
  await call('notices', 'GET', '/api/notices');
  const manual = ((out.notices.body && out.notices.body.items) || []).find((n) => n.kind === 'manual');
  await call('txns_notified', 'GET', '/api/transactions?level=high&limit=3');
  await call('notice_remove', 'POST', '/api/notices/remove', { id: manual ? String(manual.id) : 'x' });
  await call('notice_remove_missing', 'POST', '/api/notices/remove', { id: 'nope' });
  // 내보내기·평가
  await call('export_results', 'GET', '/api/export/results');
  await call('export_validation', 'GET', '/api/export/validation');
  await call('export_summary', 'GET', '/api/export/summary');
  await call('eval_file', 'POST', '/api/eval/file');
  await call('eval_default', 'POST', '/api/eval/run');
  await call('eval_standard_report', 'POST', '/api/eval/run', { seeds: 20, seed_start: 21, intensity: 'standard', modes: ['rules', 'fused', 'anomaly'] });
  await call('eval_subtle_report', 'POST', '/api/eval/run', { seeds: 20, seed_start: 21, intensity: 'subtle', modes: ['rules', 'fused', 'anomaly'] });
  await call('eval_bad', 'POST', '/api/eval/run', { seeds: 0 });
  // 파일 올리기
  await call('up_csv_nomode', 'POST', '/api/data/upload', undefined, { data: 'csv_bank' });
  await call('up_csv_append', 'POST', '/api/data/upload', undefined, { data: 'csv_bank', mode: 'append' });
  await call('up_csv_append_again', 'POST', '/api/data/upload', undefined, { data: 'csv_bank', mode: 'append' });
  await call('up_csv_mapping', 'POST', '/api/data/upload', undefined, { data: 'csv_bank', mode: 'replace', mapping: '{"datetime": "거래일시", "out_amount": "출금액", "in_amount": "입금액", "counterparty": "내용", "memo": "적요"}' });
  await call('up_csv_badmap', 'POST', '/api/data/upload', undefined, { data: 'csv_header_only', mode: 'replace', mapping: '{bad json' });
  await call('up_csv_listmap', 'POST', '/api/data/upload', undefined, { data: 'csv_header_only', mode: 'replace', mapping: '[1, 2]' });
  await call('up_csv_unknown', 'POST', '/api/data/upload', undefined, { data: 'csv_unknown_cols', mode: 'replace' });
  await call('up_empty', 'POST', '/api/data/upload', undefined, { data: 'empty', mode: 'replace' });
  await call('up_garbage', 'POST', '/api/data/upload', undefined, { data: 'garbage', mode: 'replace' });
  await call('up_badmode', 'POST', '/api/data/upload', undefined, { data: 'csv_bank', mode: 'merge' });
  await call('up_xlsx', 'POST', '/api/data/upload', undefined, { data: 'xlsx_kakao', mode: 'replace' });
  await call('up_xlsx_serial', 'POST', '/api/data/upload', undefined, { data: 'xlsx_kakao_serial', mode: 'append' });
  await call('up_xlsx_encrypted', 'POST', '/api/data/upload', undefined, { data: 'xlsx_encrypted', mode: 'append' });
  await call('up_xls_biff', 'POST', '/api/data/upload', undefined, { data: 'xls_kb_bank', mode: 'replace' });
  await call('up_htmlxls_utf8', 'POST', '/api/data/upload', undefined, { data: 'htmlxls_ibk_utf8', mode: 'replace' });
  await call('up_htmlxls_cp949', 'POST', '/api/data/upload', undefined, { data: 'htmlxls_ibk_cp949', mode: 'append' });
  await call('up_htmlxls_hyundai', 'POST', '/api/data/upload', undefined, { data: 'htmlxls_hyundai', mode: 'append' });
  await call('up_txt_kakao', 'POST', '/api/data/upload', undefined, { data: 'txt_kakao', mode: 'append' });
  await call('up_txt_passbook', 'POST', '/api/data/upload', undefined, { data: 'txt_passbook_cp949', mode: 'append' });
  await call('summary_uploaded', 'GET', '/api/data/summary');
  await call('txns_uploaded', 'GET', '/api/transactions?level=all&limit=5');
  await call('up_csv_student', 'POST', '/api/data/upload', undefined, { data: 'csv_student', mode: 'replace' });
  await call('txns_student', 'GET', '/api/transactions?level=caution&limit=5');
  await call('cards_student', 'GET', '/api/cards?limit=5');
  await call('insights_student', 'GET', '/api/insights');
  await call('eval_file_student', 'POST', '/api/eval/file');
  await call('export_results_student', 'GET', '/api/export/results');
  // 없는 기능·잘못된 방법, 모두 지우기
  await call('unknown', 'GET', '/api/nope');
  await call('wrong_method', 'DELETE', '/api/consent');
  await call('wipe', 'POST', '/api/wipe');
  await call('consent_after_wipe', 'GET', '/api/consent');
  await call('summary_after_wipe', 'GET', '/api/data/summary');
  return { out, order };
})()
"""

TRACE_JS = r"""
new Promise((resolve) => {
  const w = window.__slimWorkers[0];
  if (!w) { resolve({ error: 'worker 없음' }); return; }
  const on = (e) => { if (e.data && e.data.type === 'slim-trace') { w.removeEventListener('message', on); resolve(e.data); } };
  w.addEventListener('message', on);
  w.postMessage({ type: 'slim-trace' });
})
"""


def cmd_run(a: argparse.Namespace) -> int:
    sys.path.insert(0, str(ROOT))
    from safepause.api.router import ROUTES
    tmp = Path(tempfile.mkdtemp(prefix="sp_slim_trace_"))
    report: dict = {"www": str(a.www)}
    try:
        www = make_trace_copy(Path(a.www), tmp / "www")
        server, base = serve(www)
        browser = Browser(_chrome(a.chrome))
        try:
            report["engine"] = browser.open_engine(base)
            calls = CALLS.replace("FILES[", "(" + json.dumps(upload_files()) + ")[")
            t0 = time.time()
            res = browser.cdp.evaluate(calls, timeout=1800)
            report["calls_sec"] = round(time.time() - t0, 1)
            if not isinstance(res, dict) or "out" not in res:
                raise SystemExit(f"API 부르기 실패: {str(res)[:2000]}")
            report["order"], report["calls"] = res["order"], res["out"]
            trace = browser.cdp.evaluate(TRACE_JS, timeout=120) or {}
            report["modules"] = trace.get("modules")
            report["trace_error"] = trace.get("error")
            report["py_stdout"], report["py_stderr"] = trace.get("stdout"), trace.get("stderr")
            report["errors"] = browser.cdp.errors()
        finally:
            browser.close()
            server.shutdown()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    called = {(c["method"], c["path"].split("?")[0]) for c in report["calls"].values()}
    report["routes_missing"] = sorted(f"{m} {p}" for (m, p) in ROUTES if (m, p) not in called)
    report["status_counts"] = {}
    for c in report["calls"].values():
        report["status_counts"][str(c["status"])] = report["status_counts"].get(str(c["status"]), 0) + 1
    report["status_500"] = sorted(n for n, c in report["calls"].items() if c["status"] >= 500)
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ("engine", "calls_sec", "routes_missing", "status_counts",
                                                  "status_500", "trace_error", "errors")}, ensure_ascii=False)[:4000])
    print(f"모듈 {len(report['modules'] or [])}개, 호출 {len(report['calls'])}개, 파이썬 오류 출력 {len(report['py_stderr'] or [])}줄")
    bad = report["routes_missing"] or report["status_500"] or report["trace_error"] or not report["modules"]
    return 1 if bad else 0


# ---------------------------------------------------------------------------------------------
# plan: 뺄 하위 패키지(추적 + 정적 분석)
# ---------------------------------------------------------------------------------------------

DOTTED = re.compile(r"(?:scipy|sklearn)(?:\.[A-Za-z_][A-Za-z0-9_]*)+")
DOTTED_B = re.compile(rb"\b(?:scipy|sklearn)(?:\.[A-Za-z_][A-Za-z0-9_]*)+")
IMPORT_FUNCS = ("import_module", "__import__", "find_spec", "_lazy_import", "import_optional_dependency")
RUNTIME = "(실행 중 불림)"


def _resolve(module: str, is_pkg: bool, level: int, name: str | None) -> str:
    if not level:
        return name or ""
    parts = module.split(".")
    base = parts if is_pkg else parts[:-1]
    base = base[:len(base) - (level - 1)] if level > 1 else base
    return ".".join(base + ([name] if name else []))


def _docstrings(tree: ast.AST) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                out.add(id(first.value))
    return out


def py_refs(src: bytes, module: str, is_pkg: bool, top_only: bool = False) -> tuple[set[str], list[str]]:
    """한 모듈 소스가 불러올 수 있는 scipy·sklearn 모듈 이름과, 글자로 정할 수 없는 동적 import 자리.

    top_only: 모듈을 불러올 때 바로 도는 자리(함수 밖)만 본다. 아니면 함수 안 import(늦은 불러오기·오류 경로)도 본다.
    보는 것: import 문, importlib.import_module 등에 준 글자, scipy./sklearn.(별칭 포함) 속성 사슬,
    점 이름 모양의 글자 상수(설명문 제외).
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {m.decode() for m in DOTTED_B.findall(src)}, [f"{module}: 문법 오류(글자 전체 검색으로 대신)"]
    nodes: list[ast.AST] = []

    def visit(node: ast.AST, in_func: bool) -> None:
        for child in ast.iter_child_nodes(node):
            inner = in_func or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
            if top_only and inner:
                continue
            nodes.append(child)
            visit(child, inner)

    visit(tree, False)
    docs = _docstrings(tree)
    refs: set[str] = set()
    dynamic: list[str] = []
    alias: dict[str, str] = {}
    for node in nodes:
        if isinstance(node, ast.Import):
            for a in node.names:
                refs.add(a.name)
                alias[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            base = _resolve(module, is_pkg, node.level, node.module)
            refs.add(base)
            for a in node.names:
                if a.name != "*":
                    refs.add(f"{base}.{a.name}")
                    alias[a.asname or a.name] = f"{base}.{a.name}"
        elif isinstance(node, ast.Call):
            fn = node.func
            fname = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
            if fname not in IMPORT_FUNCS or not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                name = arg.value
                pkg = next((k.value.value for k in node.keywords if k.arg == "package"
                            and isinstance(k.value, ast.Constant)), None)
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                    pkg = node.args[1].value
                lv = len(name) - len(name.lstrip("."))
                if lv:
                    refs.add(_resolve(pkg, True, lv, name.lstrip(".") or None) if isinstance(pkg, str) else
                             _resolve(module, is_pkg, lv, name.lstrip(".") or None))
                else:
                    refs.add(name)
            else:
                dynamic.append(f"{module}:{node.lineno} {fname}({ast.unparse(arg)[:80]})")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            refs |= set(DOTTED.findall(node.value))
    for node in nodes:   # 속성 사슬: scipy.io.x / 별칭 sp.linalg.x
        if isinstance(node, ast.Attribute):
            chain = []
            cur: ast.AST = node
            while isinstance(cur, ast.Attribute):
                chain.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name) and cur.id in alias:
                refs.add(".".join([alias[cur.id]] + chain[::-1]))
    return {r for r in refs if r.split(".")[0] in TRACE_PACKAGES}, dynamic


def _prefixes(name: str) -> list[str]:
    parts = name.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts) + 1)]


class WheelIndex:
    """wheel 안의 모듈·패키지 목록과 파일."""

    def __init__(self, path: Path, top: str) -> None:
        self.path, self.top = path, top
        self.z = zipfile.ZipFile(path)
        self.packages: set[str] = set()
        self.modules: dict[str, tuple[str, bool]] = {}   # 모듈 이름 → (zip 안 경로, 패키지 여부)
        for name in self.z.namelist():
            if not name.startswith(top + "/"):
                continue
            stem = name.rsplit("/", 1)[-1]
            if stem == "__init__.py":
                pkg = name[:-len("/__init__.py")].replace("/", ".")
                self.packages.add(pkg)
                self.modules[pkg] = (name, True)
            elif stem.endswith(".py"):
                self.modules.setdefault(name[:-3].replace("/", "."), (name, False))
            elif stem.endswith(".so"):
                self.modules.setdefault(name.split(".", 1)[0].replace("/", "."), (name, False))

    def files_under(self, pkg: str) -> list[zipfile.ZipInfo]:
        prefix = pkg.replace(".", "/") + "/"
        return [i for i in self.z.infolist() if i.filename.startswith(prefix)]


def is_test_path(name: str) -> bool:
    return "tests" in name.split("/")[:-1]


def reach(idx: WheelIndex, start: set[str], lazy: str) -> tuple[dict[str, str], list[str]]:
    """start(실제로 불린 모듈)에서 정적 import로 닿는 모듈 → 처음 가리킨 모듈.

    lazy="all": 닿은 모든 모듈의 함수 안 import까지 따라간다(가장 보수적, 기본).
    lazy="used": 함수 안 import는 실제로 불린 모듈에서만 따라가고, 그렇게 닿은 모듈은 함수 밖 import만 따라간다.
    """
    via = {m: RUNTIME for m in start if m in idx.modules}
    frontier = list(via)
    dynamic: list[str] = []
    while frontier:
        m = frontier.pop()
        path, is_pkg = idx.modules[m]
        data = idx.z.read(path)
        if path.endswith(".py"):
            refs, dyn = py_refs(data, m, is_pkg, top_only=(lazy == "used" and m not in start))
            dynamic += dyn
        else:   # .so: 바이너리 안의 점 이름(Cython cimport·PyImport 대상)
            refs = {x.decode() for x in DOTTED_B.findall(data)}
        for r in refs:
            for pref in _prefixes(r):
                if pref in idx.modules and pref not in via:
                    via[pref] = m
                    frontier.append(pref)
    return via, sorted(set(dynamic))


def plan(modules: list[str], wheels: dict[str, Path], lazy: str = "all") -> dict:
    used = set(modules)
    out: dict = {"lazy": lazy, "packages": {}}
    for top, whl in wheels.items():
        idx = WheelIndex(whl, top)
        pkgs = sorted(p for p in idx.packages if not is_test_path(p.replace(".", "/") + "/x"))
        touched = {p for m in used if m.split(".")[0] == top for p in _prefixes(m)}
        # 후보: 한 번도 불리지 않은 패키지 중 가장 바깥(부모는 쓰였음)
        cands = [p for p in pkgs if p not in touched and ".".join(p.split(".")[:-1]) in touched]
        via, dynamic = reach(idx, {m for m in used if m.split(".")[0] == top}, lazy)
        keep_reason: dict[str, str] = {}
        for c in cands:
            hit = sorted(m for m in via if m == c or m.startswith(c + "."))
            if hit:
                chain, cur = [hit[0]], hit[0]
                while via.get(cur, RUNTIME) != RUNTIME and len(chain) < 12:
                    cur = via[cur]
                    chain.append(cur)
                keep_reason[c] = " ← ".join(chain)
        drop = [c for c in cands if c not in keep_reason]
        sizes = {c: sum(i.compress_size for i in idx.files_under(c) if not is_test_path(i.filename)) for c in drop}
        out["packages"][top] = {
            "wheel": whl.name, "used_modules": len([m for m in used if m.split(".")[0] == top]),
            "reachable_modules": len(via), "candidates": cands, "kept_by_static": keep_reason, "drop": drop,
            "drop_bytes_compressed": sizes, "drop_total": sum(sizes.values()),
            # 닿는 모듈이 tests 폴더 모듈이면 tests 빼기를 다시 봐야 한다
            "reachable_tests": sorted(m for m in via if "tests" in m.split(".")),
            "dynamic_imports": dynamic,
        }
    return out


def cmd_plan(a: argparse.Namespace) -> int:
    trace = json.loads(Path(a.trace).read_text(encoding="utf-8"))
    lock = json.loads((Path(a.pyodide) / "pyodide-lock.json").read_text(encoding="utf-8"))
    wheels = {top: Path(a.pyodide) / lock["packages"][WHEEL_OF[top]]["file_name"] for top in TRACE_PACKAGES}
    res = plan(trace["modules"], wheels, a.lazy)
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


# ---------------------------------------------------------------------------------------------
# compare: 응답 비교(흔들리는 칸 제외)
# ---------------------------------------------------------------------------------------------

def _leaves(obj, path: str = "") -> dict[str, object]:
    if isinstance(obj, dict):
        out: dict[str, object] = {}
        for k, v in obj.items():
            out.update(_leaves(v, f"{path}.{k}"))
        return out or {path: {}}
    if isinstance(obj, list):
        out = {f"{path}#len": len(obj)}
        for i, v in enumerate(obj):
            out.update(_leaves(v, f"{path}[{i}]"))
        return out
    return {path: obj}


def diff_paths(a: dict, b: dict) -> set[str]:
    la, lb = _leaves(a), _leaves(b)
    return {k for k in set(la) | set(lb) if (k in la) != (k in lb) or type(la.get(k)) is not type(lb.get(k))
            or la.get(k) != lb.get(k)}


STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?")


def _masked(value: object) -> object:
    return STAMP.sub("<시각>", value) if isinstance(value, str) else value


def cmd_compare(a: argparse.Namespace) -> int:
    """b의 응답이 a와 같은지. 다른 칸은 두 가지만 봐준다: 걸린 시간(elapsed_sec 숫자)과 글 속 시각(ISO 모양)뿐인 차이.
    --noise(같은 묶음을 한 번 더 돌린 결과)를 주면 a와 noise 사이에서도 같은 칸만 흔들리는지 함께 보여 준다."""
    A = json.loads(Path(a.a).read_text(encoding="utf-8"))
    B = json.loads(Path(a.b).read_text(encoding="utf-8"))
    pick = lambda r: {n: {"status": c["status"], "body": c["body"]} for n, c in r["calls"].items()}   # noqa: E731
    la, lb = _leaves(pick(A)), _leaves(pick(B))
    d = diff_paths(pick(A), pick(B))
    allowed, real = [], []
    for k in sorted(d):
        va, vb = la.get(k, "<없음>"), lb.get(k, "<없음>")
        if k.endswith(".elapsed_sec") and isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            allowed.append(k)
        elif k in la and k in lb and _masked(va) == _masked(vb) and STAMP.search(str(va)):
            allowed.append(k)
        else:
            real.append(k)
    res = {"calls_a": len(A["calls"]), "calls_b": len(B["calls"]), "leaves": len(la),
           "order_same": A["order"] == B["order"], "diff_paths": len(d), "allowed_time_only": allowed,
           "unexplained": real}
    if a.noise:
        N = json.loads(Path(a.noise).read_text(encoding="utf-8"))
        noise = diff_paths(pick(A), pick(N))
        res["noise_paths_same_as_diff"] = noise == d
    print(json.dumps(res, ensure_ascii=False, indent=1)[:20000])
    return 1 if real or not res["order_same"] else 0


# ---------------------------------------------------------------------------------------------
# timing: 엔진 준비 시간
# ---------------------------------------------------------------------------------------------

def cmd_timing(a: argparse.Namespace) -> int:
    rows = []
    chrome = _chrome(a.chrome)
    servers = [serve(Path(www)) for www in a.www]
    try:
        for i in range(a.runs):   # 묶음을 번갈아 잰다(시간에 따른 PC 부하 차이를 고르게)
            for www, (_, base) in zip(a.www, servers):
                b = Browser(chrome)
                try:
                    r = b.open_engine(base)
                    r.pop("stages", None)
                    r["errors"] = b.cdp.errors()
                finally:
                    b.close()
                rows.append({"www": www, "run": i + 1, **r})
                print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    finally:
        for server, _ in servers:
            server.shutdown()
    summary = {}
    for www in a.www:
        mine = [r for r in rows if r["www"] == www]
        summary[www] = {k: round(sum(r[k] for r in mine) / len(mine)) for k in
                        ("basic_worker_ms", "basic_page_ms", "full_worker_ms", "full_page_ms")
                        if all(k in r for r in mine)}
    print(json.dumps({"runs": rows, "mean": summary}, ensure_ascii=False, indent=1))
    if a.out:
        Path(a.out).write_text(json.dumps({"runs": rows, "mean": summary}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--www", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--chrome")
    p = sub.add_parser("plan")
    p.add_argument("--trace", required=True)
    p.add_argument("--pyodide", required=True)
    p.add_argument("--out")
    p.add_argument("--lazy", choices=["all", "used"], default="all",
                   help="all: 닿은 모든 모듈의 함수 안 import까지(기본, 가장 보수적). used: 실제로 불린 모듈의 함수 안 import만")
    c = sub.add_parser("compare")
    c.add_argument("--a", required=True)
    c.add_argument("--b", required=True)
    c.add_argument("--noise")
    t = sub.add_parser("timing")
    t.add_argument("--www", nargs="+", required=True)
    t.add_argument("--runs", type=int, default=3)
    t.add_argument("--out")
    t.add_argument("--chrome")
    a = ap.parse_args(argv)
    return {"run": cmd_run, "plan": cmd_plan, "compare": cmd_compare, "timing": cmd_timing}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
