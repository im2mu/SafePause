"""cli.py 테스트(serve는 서버 모듈이 필요해 제외)."""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from safepause import __version__, cli
from safepause.data.synth import ALL_SCENARIOS, from_csv, make_dataset
from safepause.eval.metrics import DISCLAIMER, FILE_DISCLAIMER
from safepause.explain.easy_card import COMMON_QUESTION
from safepause.guardian.outbox import DELIVERY_NOTE
from safepause.models import Consent
from safepause.store import CONSENT_FILE, Store

ROOT = Path(__file__).resolve().parents[1]
BANK_EXAMPLE = ROOT / "sample_data" / "bank_export_example.csv"


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """격리된 데이터 폴더(SAFEPAUSE_HOME)."""
    path = tmp_path / "home"
    monkeypatch.setenv("SAFEPAUSE_HOME", str(path))
    return path


# ---------------------------------------------------------------------------
# 진입점·파서
# ---------------------------------------------------------------------------

def test_version(capsys):
    assert cli.main(["--version"]) == 0
    assert f"SafePause {__version__}" in capsys.readouterr().out


def test_no_command_prints_help(capsys):
    assert cli.run([]) == 2
    assert "serve" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [
    ["synth"],                                             # --out 없음
    ["synth", "--out", "x.csv", "--persona", "nobody"],
    ["eval", "--seeds", "0"],
    ["analyze", "--file", "a.csv", "--baseline-ratio", "1.5"],
    ["serve", "--port", "0"],                              # 인자 검사만(서버는 열지 않음)
    ["no-such-command"],
])
def test_bad_arguments_return_2(argv, capsys):
    assert cli.run(argv) == 2
    capsys.readouterr()


def test_parser_lists_all_spec_commands():
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if a.dest == "command")
    assert {"serve", "demo", "synth", "analyze", "eval", "wipe"} <= set(sub.choices)


# ---------------------------------------------------------------------------
# synth
# ---------------------------------------------------------------------------

def test_synth_writes_standard_csv(tmp_path, capsys):
    out = tmp_path / "sub" / "benefit.csv"
    assert cli.run(["synth", "--persona", "benefit", "--seed", "2", "--out", str(out)]) == 0
    txns = from_csv(out)
    expected = make_dataset("benefit", 2, 120, ALL_SCENARIOS)
    assert [t.id for t in txns] == [t.id for t in expected]
    text = capsys.readouterr().out
    assert f"{len(expected)}건을 저장했어요" in text and "실제 거래가 아니에요" in text


def test_synth_no_scenarios(tmp_path, capsys):
    out = tmp_path / "normal.csv"
    assert cli.run(["synth", "--seed", "3", "--days", "40", "--out", str(out), "--no-scenarios"]) == 0
    txns = from_csv(out)
    assert txns and all(t.label == "normal" for t in txns)
    capsys.readouterr()


# ---------------------------------------------------------------------------
# demo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("persona", ["worker", "student"])
def test_demo_prints_samples_and_cards(persona, capsys):
    assert cli.run(["demo", "--persona", persona, "--seed", "1"]) == 0
    text = capsys.readouterr().out
    assert "합성 데이터" in text and "[1]" in text and "[3]" in text
    assert COMMON_QUESTION in text and "그래도 보낼래요" in text
    assert "카드 없음" in text                     # 알림 없는 정상 거래도 1건 보여 준다
    # [변경 r3] 데모는 아무것도 저장하지 않으므로 '알림 기록 1건'이라고 말하지 않는다
    assert cli.DEMO_NOTICE_NOTE in text and DELIVERY_NOTE not in text
    assert "알림 기록" not in text and "데모라 기록하지 않음" in text


def test_demo_writes_nothing(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("SAFEPAUSE_HOME", str(home))
    assert cli.run(["demo"]) == 0
    assert not home.exists()


def test_demo_is_deterministic(capsys):
    cli.run(["demo"])
    first = capsys.readouterr().out
    cli.run(["demo"])
    assert capsys.readouterr().out == first


def test_pick_demo_samples_prefers_levels():
    from safepause.detect.engine import RiskEngine
    from safepause.eval.metrics import synthetic_case
    from safepause.models import RiskLevel

    case = synthetic_case("worker", 1)
    assessed = RiskEngine(seed=1).fit(case.baseline_normal).assess_many(
        case.evaluated, history=case.baseline)
    picked = cli._pick_demo_samples(case.evaluated, assessed)
    levels = [a.level for _, a in picked]
    assert len(picked) == 3 and RiskLevel.HIGH in levels and RiskLevel.NONE in levels
    assert [t.ts for t, _ in picked] == sorted(t.ts for t, _ in picked)


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------

def test_analyze_bank_example(capsys):
    assert cli.run(["analyze", "--file", str(BANK_EXAMPLE)]) == 0
    text = capsys.readouterr().out
    assert "[가져오기] 46줄 중 46건" in text
    assert "추정" in text                           # 로더의 추정 사실을 그대로 보여 준다
    assert "[알림 목록]" in text and "김*호" in text and "고위험" in text
    assert FILE_DISCLAIMER in text and "저장하지 않았어요" in text


def test_analyze_with_report_out(tmp_path, capsys):
    out = tmp_path / "rep"
    assert cli.run(["analyze", "--file", str(BANK_EXAMPLE), "--out", str(out), "--limit", "1"]) == 0
    assert (out / "file_eval_report.md").is_file() and (out / "file_eval_results.json").is_file()
    data = json.loads((out / "file_eval_results.json").read_text(encoding="utf-8"))
    assert data["kind"] == "file" and data["n_total"] == 46
    capsys.readouterr()


def test_analyze_synthetic_file_limit(tmp_path, capsys):
    csv_path = tmp_path / "w.csv"
    cli.run(["synth", "--seed", "5", "--out", str(csv_path)])
    capsys.readouterr()
    assert cli.run(["analyze", "--file", str(csv_path), "--limit", "2"]) == 0
    text = capsys.readouterr().out
    assert "--limit로 더 볼 수 있어요" in text
    # 120일 파일: 앞 75% 구간 가운데 평소 기준이 없는 맨 앞 거래는 AI 학습에서 뺀다는 것을 따로 알린다
    m = re.search(r"AI는 앞 (\d+)건 가운데 (\d+)건으로 배웠어요 \(맨 앞 (\d+)건은", text)
    assert m and int(m[1]) - int(m[2]) == int(m[3]) > 0


def test_analyze_small_file_with_mapping(tmp_path, capsys):
    rows = ["when,who,out,in"]
    for day in range(1, 6):
        rows.append(f"2026-07-0{day} 0{day}:10,김*호,300000,")
    csv_path = tmp_path / "custom.csv"
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"datetime": "when", "counterparty": "who",
                                   "out_amount": "out", "in_amount": "in"}), encoding="utf-8")
    assert cli.run(["analyze", "--file", str(csv_path), "--mapping", str(mapping)]) == 0
    text = capsys.readouterr().out
    assert "룰로만 전체 거래를 봤어요" in text
    assert "심야 반복 이체" in text


def test_analyze_errors_are_korean(tmp_path, capsys):
    assert cli.run(["analyze", "--file", str(tmp_path / "none.csv")]) == 1
    assert "파일을 찾을 수 없어요" in capsys.readouterr().err

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert cli.run(["analyze", "--file", str(BANK_EXAMPLE), "--mapping", str(bad)]) == 1
    assert "올바른 JSON이 아니에요" in capsys.readouterr().err

    listing = tmp_path / "list.json"
    listing.write_text("[1, 2]", encoding="utf-8")
    assert cli.run(["analyze", "--file", str(BANK_EXAMPLE), "--mapping", str(listing)]) == 1
    assert "JSON 객체" in capsys.readouterr().err

    unknown = tmp_path / "u.csv"
    unknown.write_text("a,b\n1,2\n", encoding="utf-8")
    assert cli.run(["analyze", "--file", str(unknown)]) == 1
    assert "mapping" in capsys.readouterr().err


def test_debug_env_reraises(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SAFEPAUSE_DEBUG", "1")
    with pytest.raises(ValueError):
        cli.run(["analyze", "--file", str(tmp_path / "none.csv")])


# ---------------------------------------------------------------------------
# eval
# ---------------------------------------------------------------------------

def test_eval_writes_reports(tmp_path, capsys):
    out = tmp_path / "eval"
    assert cli.run(["eval", "--seeds", "1", "--personas", "worker", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert DISCLAIMER in text and "결합(룰+AI)" in text and "AI 이상탐지만" in text
    results = json.loads((out / "eval_results.json").read_text(encoding="utf-8"))
    assert results["kind"] == "comparison" and results["seeds"] == [1]
    assert results["command"].startswith("python -m safepause eval --seeds 1 --personas worker")
    md = (out / "eval_report.md").read_text(encoding="utf-8")
    assert DISCLAIMER in md and results["command"] in md


def test_eval_single_mode(tmp_path, capsys):
    out = tmp_path / "eval"
    assert cli.run(["eval", "--seeds", "1", "--personas", "student", "--modes", "rules",
                    "--out", str(out)]) == 0
    results = json.loads((out / "eval_results.json").read_text(encoding="utf-8"))
    assert results["mode_order"] == ["rules"] and "--modes rules" in results["command"]
    capsys.readouterr()


def test_eval_bad_persona(tmp_path, capsys):
    assert cli.run(["eval", "--seeds", "1", "--personas", "ghost", "--out", str(tmp_path)]) == 1
    assert "알 수 없는 인물 설정" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# wipe
# ---------------------------------------------------------------------------

def test_wipe_yes_removes_store_files(home, capsys):
    Store(home).save_consent(Consent(monitoring=True))
    assert (home / CONSENT_FILE).exists()
    assert cli.run(["wipe", "--yes"]) == 0
    assert not (home / CONSENT_FILE).exists()
    assert CONSENT_FILE in capsys.readouterr().out
    assert cli.run(["wipe", "-y"]) == 0
    assert "지울 데이터가 없어요" in capsys.readouterr().out


def test_wipe_asks_and_cancels(home, monkeypatch, capsys):
    Store(home).save_consent(Consent(monitoring=True))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
    assert cli.run(["wipe"]) == 1
    assert (home / CONSENT_FILE).exists()

    def eof(_prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert cli.run(["wipe"]) == 1
    assert (home / CONSENT_FILE).exists()

    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    assert cli.run(["wipe"]) == 0
    assert not (home / CONSENT_FILE).exists()
    capsys.readouterr()


def test_wipe_home_option(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SAFEPAUSE_HOME", str(tmp_path / "unused"))  # 테스트 뒤 원래 값으로 복구
    target = tmp_path / "other"
    Store(target).save_consent(Consent(monitoring=True))
    assert cli.run(["wipe", "--home", str(target), "--yes"]) == 0
    assert not (target / CONSENT_FILE).exists()
    assert os.environ["SAFEPAUSE_HOME"] == str(target.resolve())
    capsys.readouterr()


# ---------------------------------------------------------------------------
# 포트 찾기(serve 보조)
# ---------------------------------------------------------------------------

def _busy_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((cli.LOCAL_HOST, 0))
    sock.listen(1)
    return sock


def test_find_free_port_skips_busy_port():
    sock = _busy_socket()
    try:
        busy = sock.getsockname()[1]
        assert cli.is_port_free(busy) is False
        port = cli.find_free_port(busy, attempts=10)
        assert port != busy and busy < port < busy + 10
        assert cli.is_port_free(port)
    finally:
        sock.close()


def test_find_free_port_errors():
    sock = _busy_socket()
    try:
        with pytest.raises(cli.CliError):
            cli.find_free_port(sock.getsockname()[1], attempts=1)
    finally:
        sock.close()
    for bad in (0, 70000):
        with pytest.raises(cli.CliError):
            cli.find_free_port(bad)
    with pytest.raises(cli.CliError):
        cli.find_free_port(8765, attempts=0)


def test_browser_opens_only_when_port_answers(monkeypatch, capsys):
    opened: list[str] = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url) or True)
    sock = _busy_socket()
    try:
        port = sock.getsockname()[1]
        cli._open_browser_when_ready(f"http://127.0.0.1:{port}", port, timeout=5).join(10)
    finally:
        sock.close()
    assert opened == [f"http://127.0.0.1:{port}"]

    closed = _busy_socket()
    free_port = closed.getsockname()[1]
    closed.close()                                  # 아무도 듣지 않는 포트
    cli._open_browser_when_ready("http://127.0.0.1:1/", free_port, timeout=0.2).join(10)
    assert len(opened) == 1
    assert "직접 열어 주세요" in capsys.readouterr().out


def test_server_host_is_loopback_only():
    assert cli.LOCAL_HOST == "127.0.0.1"
    src = Path(cli.__file__).read_text(encoding="utf-8")
    assert "0.0.0.0" not in src
    assert "host: str = LOCAL_HOST" in src and "sock.bind((host, port))" in src   # v0.2: 소켓을 직접 잡음


# ---------------------------------------------------------------------------
# python -m safepause (종료 코드 전달)
# ---------------------------------------------------------------------------

def test_python_m_exit_codes(tmp_path):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "SAFEPAUSE_HOME": str(tmp_path / "h")}
    ok = subprocess.run([sys.executable, "-m", "safepause", "--version"], cwd=ROOT, env=env,
                        capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert ok.returncode == 0 and __version__ in ok.stdout
    bad = subprocess.run([sys.executable, "-m", "safepause", "analyze", "--file", str(tmp_path / "x.csv")],
                         cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert bad.returncode == 1 and "파일을 찾을 수 없어요" in bad.stderr


def test_analyze_bad_mapping_value_is_korean_error(tmp_path, capsys):
    csv_path = tmp_path / "a.csv"
    csv_path.write_text("거래일시,금액,구분\n2026-09-01 10:00,1000,출금\n", encoding="utf-8")
    mapping = tmp_path / "m.json"
    mapping.write_text(json.dumps({"datetime": "거래일시", "amount": "금액", "kind": 3}), encoding="utf-8")
    code = cli.run(["analyze", "--file", str(csv_path), "--mapping", str(mapping)])
    assert code == 1
    assert "열 이름(글자)" in capsys.readouterr().err


def test_import_error_gives_korean_hint(monkeypatch, capsys):
    def broken(args):
        raise ImportError("DLL load failed")

    parser = cli.build_parser()
    real_parse = parser.parse_args

    def parse(argv=None):
        ns = real_parse(argv)
        ns.handler = broken
        return ns

    monkeypatch.setattr(parser, "parse_args", parse)
    monkeypatch.setattr(cli, "build_parser", lambda: parser)
    assert cli.run(["demo"]) == 1
    err = capsys.readouterr().err
    assert "불러오지 못했어요" in err and "짧은 폴더" in err


# ---- 리뷰 수정 확인(round 2) ------------------------------------------------

def test_analyze_report_warns_that_wipe_does_not_remove_it(tmp_path, capsys):
    out = tmp_path / "rep"
    assert cli.run(["analyze", "--file", str(BANK_EXAMPLE), "--out", str(out), "--limit", "1"]) == 0
    printed = capsys.readouterr().out
    assert cli.REPORT_PRIVACY_NOTE in printed and "wipe" in printed
    help_text = cli.build_parser()._subparsers._group_actions[0].choices["analyze"].format_help()
    assert "저장 안 함" not in help_text and "보고서" in help_text


def test_eval_default_out_is_not_submitted_report():
    args = cli.build_parser().parse_args(["eval"])
    assert args.out == cli.DEFAULT_EVAL_OUT == "eval_out" and args.overwrite is False


def test_eval_does_not_overwrite_submitted_report(tmp_path, capsys):
    submitted = tmp_path / "docs" / "eval"
    submitted.mkdir(parents=True)
    original = {"command": "python -m safepause eval --seeds 20 --out docs/eval"}
    (submitted / "eval_results.json").write_text(json.dumps(original), encoding="utf-8")
    quick = ["eval", "--seeds", "1", "--personas", "worker", "--modes", "rules", "--out", str(submitted)]
    assert cli.run(quick) == 1
    assert "--out 다른폴더" in capsys.readouterr().err
    assert json.loads((submitted / "eval_results.json").read_text(encoding="utf-8")) == original
    assert cli.run([*quick, "--overwrite"]) == 0                  # 일부러 덮어쓰기
    capsys.readouterr()


# ---------------------------------------------------------------------------
# serve: 저장 폴더마다 하나만 (리뷰 수정 확인 round 3)
# ---------------------------------------------------------------------------

def test_second_serve_on_same_folder_does_not_start(home, monkeypatch, capsys):
    """[변경 r3] 같은 저장 폴더에 serve가 이미 떠 있으면 두 번째 서버를 띄우지 않고 주소를 알려 준다."""
    import uvicorn

    from safepause.store import FileLock

    home.mkdir(parents=True)
    running = FileLock(home / cli.SERVE_LOCK_FILE, offset=cli.SERVE_LOCK_OFFSET)
    assert running.acquire(timeout=0)
    running.write_text(json.dumps({"url": "http://127.0.0.1:8799", "pid": 1}))

    def must_not_run(*_a, **_k):
        raise AssertionError("두 번째 서버가 떴어요")

    monkeypatch.setattr(uvicorn, "run", must_not_run)
    try:
        assert cli.run(["serve", "--no-browser"]) == 0
    finally:
        running.release()
    out = capsys.readouterr().out
    assert "이미 켜져 있어요" in out and "http://127.0.0.1:8799" in out


def test_serve_holds_folder_lock_while_running(home, monkeypatch, capsys):
    import uvicorn

    from safepause.store import FileLock

    seen: dict[str, object] = {}

    def fake_run(self, sockets=None):   # v0.2: serve가 잡은 소켓을 uvicorn.Server.run에 넘긴다
        other = FileLock(home / cli.SERVE_LOCK_FILE, offset=cli.SERVE_LOCK_OFFSET)
        seen["locked"] = not other.acquire(timeout=0)
        seen["url"] = cli._running_server_url(home / cli.SERVE_LOCK_FILE)
        seen["host"], seen["port"] = sockets[0].getsockname()[:2]
        seen["token_required"] = self.config.app.state.safepause is not None

    monkeypatch.setattr(uvicorn.Server, "run", fake_run)
    assert cli.run(["serve", "--no-browser"]) == 0
    assert seen["locked"] is True and seen["host"] == "127.0.0.1"
    # 주소에 세션 토큰이 붙는다(#k=…, 서버로는 보내지 않는 조각)
    assert str(seen["url"]).startswith(f"http://127.0.0.1:{seen['port']}/#k=") and len(str(seen["url"])) > 40
    after = FileLock(home / cli.SERVE_LOCK_FILE, offset=cli.SERVE_LOCK_OFFSET)
    assert after.acquire(timeout=0)                     # 끝나면 놓는다
    after.release()
    assert cli._running_server_url(home / cli.SERVE_LOCK_FILE) == ""   # 주소도 지운다


def test_bind_first_free_holds_port_and_skips_busy():
    busy = _busy_socket()
    try:
        port = busy.getsockname()[1]
        sock, chosen = cli._bind_first_free(port, attempts=20)
        try:
            assert chosen != port and sock.getsockname()[1] == chosen
            assert cli.is_port_free(chosen) is False       # 잡은 포트는 다른 프로그램이 못 잡는다(틈 없음)
        finally:
            sock.close()
    finally:
        busy.close()
    with pytest.raises(cli.CliError):
        cli._bind_first_free(0)
