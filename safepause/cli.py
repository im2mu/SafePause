"""명령행: ``python -m safepause <명령>`` (SPEC §9).

- serve    로컬 서버 시작(127.0.0.1 전용), 기본 브라우저로 화면 열기. 저장 폴더마다 하나만 뜬다
           (이미 떠 있으면 새로 열지 않고 그 주소를 알려 준다)
- demo     합성 데이터로 샘플 3건의 판단 결과와 쉬운 말 카드 출력
- synth    합성 거래 CSV 만들기
- analyze  거래내역 CSV를 가져와 알림 목록 출력(SafePause 저장소에는 넣지 않음.
           --out을 주면 받는 곳·금액이 든 보고서 파일을 씀)
- eval     결합/룰/AI 이상탐지 3개 모드 비교 평가 + 보고서(JSON·Markdown).
           --intensity subtle이면 룰 기준 경계 변형 시나리오(SPEC §3 [추가 r4])로 평가,
           --seed-start가 1이 아니면 별도 검증 세트(SPEC §8 [추가 r5])로 보고 결과 파일 이름을 나눔
- wipe     저장 데이터 모두 삭제(당사자의 즉시 철회권)

서버 모듈(FastAPI·uvicorn)은 serve를 실행할 때만 불러온다.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import webbrowser
from collections import Counter
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from safepause import __version__
from safepause.models import AlertCard, RiskAssessment, Transaction

LOCAL_HOST = "127.0.0.1"         # 서버는 이 주소에만 연다(외부 접속 차단)
DEFAULT_PORT = 8765
PORT_ATTEMPTS = 20               # 포트가 사용 중이면 다음 번호를 이만큼 시도
BROWSER_WAIT_SEC = 20.0          # 서버가 뜰 때까지 브라우저 열기를 기다리는 최대 시간
DEFAULT_EVAL_SEEDS = 20
DEFAULT_EVAL_SEED_START = 1       # 1이 아니면 별도 검증 세트(eval_results_holdout.json 등)
DEFAULT_EVAL_OUT = "eval_out"     # 제출 보고서(docs/eval)를 실수로 덮어쓰지 않게 따로 둔다
SUBMITTED_EVAL_DIR = ("docs", "eval")   # 제출한 20-seed 보고서 폴더(README 수치의 근거)
DEFAULT_ANALYZE_LIMIT = 30
DEMO_SAMPLES = 3
REPORT_PRIVACY_NOTE = ("이 보고서에는 받는 곳·금액·시각이 들어 있어요. "
                       "wipe(모두 지우기)는 이 보고서를 지우지 않아요. 필요 없으면 직접 지워 주세요.")
WIPE_SERVER_HINT = ("SafePause 화면(serve)이 켜져 있으면, 화면의 '⑦ 내 데이터 지우기'를 쓰거나 "
                    "서버 창을 끈 뒤 지워 주세요.")
SERVE_LOCK_FILE = "serve.lock"   # 저장 폴더마다 serve 하나만(두 창이 같은 기록을 덮어쓰지 않게)
SERVE_LOCK_OFFSET = 1 << 30      # 파일 앞쪽에 서버 주소를 적고 먼 뒤쪽 바이트를 잠근다(Windows에서도 앞쪽은 읽힘)
DEMO_NOTICE_NOTE = "데모는 저장하지 않아요. 화면(serve)에서는 알림을 이 컴퓨터에 기록만 해요."
IMPORT_HINT = ("requirements.txt의 패키지가 설치됐는지 확인해 주세요. Windows에서 폴더 경로가 너무 길면 "
               "설치·불러오기가 실패할 수 있어요. 짧은 폴더(예: C:\\SafePause)로 옮겨 다시 실행해 주세요.")


class CliError(Exception):
    """사용자에게 보여 줄 한국어 오류."""


# ---------------------------------------------------------------------------
# 포트·브라우저
# ---------------------------------------------------------------------------

def is_port_free(port: int, host: str = LOCAL_HOST) -> bool:
    """host:port에 지금 바인드할 수 있는지(연결 시도 없이 바인드만 해 본다)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)  # Windows 전용
        if exclusive is not None:
            sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def find_free_port(start: int = DEFAULT_PORT, attempts: int = PORT_ATTEMPTS,
                   host: str = LOCAL_HOST) -> int:
    """start부터 차례로 비어 있는 포트를 찾는다."""
    if not 1 <= start <= 65535:
        raise CliError(f"포트 번호는 1~65535 사이여야 해요: {start}")
    if attempts < 1:
        raise CliError("포트 시도 횟수는 1 이상이어야 해요.")
    last = min(start + attempts - 1, 65535)
    for port in range(start, last + 1):
        if is_port_free(port, host):
            return port
    raise CliError(f"{start}~{last}번 포트를 모두 쓰고 있어요. --port로 다른 번호를 지정해 주세요.")


def _open_browser_when_ready(url: str, port: int, timeout: float = BROWSER_WAIT_SEC) -> threading.Thread:
    """서버가 연결을 받기 시작하면 기본 브라우저로 url을 연다(백그라운드)."""
    def worker() -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection((LOCAL_HOST, port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.3)
        else:
            print(f"브라우저에서 {url} 을 직접 열어 주세요.", flush=True)
            return
        try:
            opened = webbrowser.open(url)
        except webbrowser.Error:
            opened = False
        if not opened:
            print(f"브라우저를 열지 못했어요. {url} 을 직접 열어 주세요.", flush=True)

    thread = threading.Thread(target=worker, name="safepause-browser", daemon=True)
    thread.start()
    return thread


def _running_server_url(path: Path) -> str:
    """먼저 뜬 serve가 잠금 파일에 적어 둔 주소(127.0.0.1만). 없거나 읽지 못하면 빈 글."""
    try:
        data = json.loads(path.read_text(encoding="utf-8").strip() or "{}")
    except (OSError, ValueError):
        return ""
    url = data.get("url") if isinstance(data, dict) else None
    return url if isinstance(url, str) and url.startswith(f"http://{LOCAL_HOST}:") else ""


def _show_running_server(path: Path, open_browser: bool) -> int:
    """같은 저장 폴더에 serve가 이미 떠 있을 때: 새로 열지 않고 그 주소를 알려 준다(열어 준다)."""
    url = _running_server_url(path)
    print("SafePause 화면이 이미 켜져 있어요(같은 저장 폴더). "
          "두 창이 같은 기록을 덮어쓰지 않게 새로 열지 않았어요.", flush=True)
    if not url:
        print("먼저 켠 SafePause 창을 써 주세요. 그 창을 끈 뒤에는 다시 켤 수 있어요.", flush=True)
        return 0
    print(f"켜져 있는 화면 주소: {url}", flush=True)
    if open_browser:
        try:
            webbrowser.open(url)
        except webbrowser.Error:
            print(f"브라우저에서 {url} 을 직접 열어 주세요.", flush=True)
    return 0


def serve(port: int = DEFAULT_PORT, open_browser: bool = True) -> int:
    """로컬 서버를 연다(127.0.0.1 전용). 포트가 사용 중이면 다음 포트를 쓴다.

    저장 폴더마다 하나만 뜬다: 폴더 안 serve.lock을 OS 파일 잠금으로 잡고, 이미 잡혀 있으면
    두 번째 서버를 띄우지 않고 먼저 뜬 서버 주소를 알려 준다(예: exe를 두 번 더블클릭).
    """
    try:
        import uvicorn

        from safepause.server.app import create_app
    except ImportError as exc:
        raise CliError(f"서버 구성 요소를 불러오지 못했어요({exc}). "
                       "requirements.txt의 패키지를 설치해 주세요.") from exc
    from safepause import config
    from safepause.store import FileLock

    lock: Optional[FileLock] = FileLock(config.data_dir() / SERVE_LOCK_FILE, offset=SERVE_LOCK_OFFSET)
    try:
        if not lock.acquire(timeout=0):
            return _show_running_server(lock.path, open_browser)
    except OSError:   # 잠금 파일을 만들 수 없는 폴더: 잠금 없이 연다(저장이 안 되면 화면이 한국어로 알림)
        lock = None
    try:
        chosen = find_free_port(port)
        if chosen != port:
            print(f"{port}번 포트를 이미 쓰고 있어 {chosen}번 포트로 엽니다.", flush=True)
        url = f"http://{LOCAL_HOST}:{chosen}"
        if lock is not None:
            lock.write_text(json.dumps({"url": url, "pid": os.getpid()}))
        app = create_app()
        # 파이프·컨테이너 로그에서도 바로 보이도록 flush
        print(f"SafePause {__version__} 화면 주소: {url}", flush=True)
        print("이 컴퓨터 안에서만 열리고, 거래 데이터는 밖으로 보내지 않아요.", flush=True)
        print("끝내려면 이 창에서 Ctrl+C를 누르세요.", flush=True)
        if open_browser:
            _open_browser_when_ready(url, chosen)
        uvicorn.run(app, host=LOCAL_HOST, port=chosen, log_level="info", access_log=False)
        return 0
    finally:
        if lock is not None:
            try:
                lock.write_text("")    # 주소를 지운 뒤 놓는다(파일은 남겨 두어 잠금 경쟁을 피함)
            except OSError:
                pass
            lock.release()


# ---------------------------------------------------------------------------
# 출력 도우미
# ---------------------------------------------------------------------------

def _names() -> tuple[Callable[[str], str], Callable[[str], str], Callable[[str], str]]:
    from safepause.eval.report import channel_name, level_name, signal_name

    return signal_name, level_name, channel_name


def _txn_line(txn: Transaction) -> str:
    from safepause.explain.easy_card import format_won

    _, _, channel_name = _names()
    who = txn.counterparty or "-"
    return f"{txn.ts:%Y-%m-%d %H:%M} | {channel_name(txn.channel.value)} | {who} | {format_won(txn.amount)}"


def _print_card(card: AlertCard, indent: str = "    ") -> None:
    print(f"{indent}[카드] {card.title}")
    for line in card.lines:
        print(f"{indent}  {line}")
    print(f"{indent}  질문: {card.question}")
    print(f"{indent}  선택: " + " / ".join(c["label"] for c in card.choices))
    print(f"{indent}  그림: {', '.join(card.pictograms)}")


def _codes_text(assessment: RiskAssessment) -> str:
    signal_name, _, _ = _names()
    codes = list(dict.fromkeys(h.code.value for h in assessment.rule_hits))
    if codes:
        return ", ".join(signal_name(c) for c in codes)
    return "AI 이상탐지" if assessment.reasons else "-"


# ---------------------------------------------------------------------------
# demo
# ---------------------------------------------------------------------------

def _pick_demo_samples(txns: Sequence[Transaction], assessed: Sequence[RiskAssessment]
                       ) -> list[tuple[Transaction, RiskAssessment]]:
    """고위험 1건, 주의 1건(없으면 다른 시그널 고위험), 알림 없는 정상 출금 1건."""
    from safepause.eval.metrics import is_normal_label
    from safepause.models import Direction, RiskLevel

    pairs = list(zip(txns, assessed))

    def primary(a: RiskAssessment) -> str:
        return a.rule_hits[0].code.value if a.rule_hits else "anomaly"

    picked: list[tuple[Transaction, RiskAssessment]] = []
    first_high = next((p for p in pairs if p[1].level == RiskLevel.HIGH), None)
    if first_high:
        picked.append(first_high)
    used = {primary(a) for _, a in picked}
    second = next((p for p in pairs if p[1].level == RiskLevel.CAUTION), None)
    if second is None:
        second = next((p for p in pairs if p[1].level != RiskLevel.NONE and primary(p[1]) not in used
                       and p not in picked), None)
    if second:
        picked.append(second)
    quiet = next((p for p in pairs if p[1].level == RiskLevel.NONE and p[0].direction == Direction.OUT
                  and is_normal_label(p[0].label)), None)
    if quiet:
        picked.append(quiet)
    picked.sort(key=lambda p: p[0].ts)
    return picked[:DEMO_SAMPLES]


def cmd_demo(args: argparse.Namespace) -> int:
    from safepause.data.synth import PERSONAS
    from safepause.detect.engine import RiskEngine
    from safepause.eval.metrics import is_normal_label, synthetic_case
    from safepause.explain.easy_card import render_card
    from safepause.guardian.policy import decide
    from safepause.models import Consent, Helper, RiskLevel

    signal_name, level_name, _ = _names()
    case = synthetic_case(args.persona, args.seed)
    engine = RiskEngine(seed=args.seed).fit(case.baseline_normal)
    assessed = engine.assess_many(case.evaluated, history=case.baseline)
    samples = _pick_demo_samples(case.evaluated, assessed)

    # 가상 조력자·동의(데모 전용). 조력자는 인물의 첫 번째 평소 송금 상대로 둔다.
    name, account = PERSONAS[args.persona].known_payees[0]
    helpers = [Helper(id="demo-helper", name=name, relation="가족(가상)", identifiers=[account])]
    consent = Consent(monitoring=True, helper_alerts=True, counseling_referral=True)
    high_times = [t.ts for t, a in zip(case.evaluated, assessed) if a.level == RiskLevel.HIGH]

    print(f"SafePause 데모: 합성 데이터(가상 인물 '{args.persona}', seed {args.seed})")
    print(f"앞 {len(case.baseline)}건으로 개인 기준을 배우고, 뒤 {len(case.evaluated)}건을 판단했어요.")
    print("실제 송금은 없어요. 데모는 아무것도 저장하지 않아요.\n")
    for i, (txn, a) in enumerate(samples, start=1):
        print(f"[{i}] {_txn_line(txn)}")
        print(f"    판단: {level_name(a.level.value)} | 시그널: {_codes_text(a)} | "
              f"이상 점수 {a.anomaly_score:.2f}")
        truth = "정상 거래" if is_normal_label(txn.label) else f"{signal_name(str(txn.label))} 시나리오"
        print(f"    합성 정답: {truth} (판단에는 쓰지 않아요)")
        card = render_card(a, txn)
        if card is None:
            print("    카드 없음: 걱정되는 신호가 없어 바로 진행해요.\n")
            continue
        _print_card(card)
        # 최근 30일 고위험 건수(이번 건 포함)
        recent = sum(1 for ts in high_times if txn.ts - timedelta(days=30) < ts <= txn.ts)
        plan = decide(a, txn, helpers, consent, recent)
        print(f"    조력자: {plan.note_to_person} (알림 대상 {len(plan.notices)}명, 데모라 기록하지 않음)")
        if plan.suggest_counseling:
            print(f"    상담 연계 제안: {', '.join(plan.counseling_orgs)}")
        print()
    print(DEMO_NOTICE_NOTE)
    return 0


# ---------------------------------------------------------------------------
# synth
# ---------------------------------------------------------------------------

def cmd_synth(args: argparse.Namespace) -> int:
    from safepause.data.synth import ALL_SCENARIOS, make_dataset, to_csv

    signal_name, _, _ = _names()
    txns = make_dataset(args.persona, args.seed, args.days,
                        None if args.no_scenarios else ALL_SCENARIOS)
    path = to_csv(txns, args.out)
    labels = Counter(t.label or "normal" for t in txns)
    print(f"합성 거래 {len(txns)}건을 저장했어요: {path}")
    print(f"  정상 {labels.pop('normal', 0)}건"
          + "".join(f", {signal_name(code)} {n}건" for code, n in sorted(labels.items())))
    print("가상 인물의 합성 데이터예요. 실제 거래가 아니에요.")
    return 0


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------

def _load_mapping(path: Optional[str]) -> Optional[dict[str, Any]]:
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise CliError(f"mapping 파일을 찾을 수 없어요: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CliError(f"mapping 파일이 올바른 JSON이 아니에요: {path} ({exc.msg}, {exc.lineno}번째 줄)") from exc
    if not isinstance(data, dict):
        raise CliError('mapping 파일은 {"열 항목": "열 이름"} 모양의 JSON 객체여야 해요.')
    return data


def _print_alert_rows(rows: Sequence[dict[str, Any]], limit: int) -> None:
    from safepause.explain.easy_card import format_won

    signal_name, level_name, channel_name = _names()
    for row in rows[:limit]:
        signals = ", ".join(signal_name(s) for s in row["signals"]) or "AI 이상탐지"
        print(f"  {row['ts'].replace('T', ' ')[:16]} | {channel_name(row['channel'])} | "
              f"{row['counterparty'] or '-'} | {format_won(row['amount'])} | "
              f"{level_name(row['level'])} | {signals} | 카드: {row['card_title'] or '-'}")
    if len(rows) > limit:
        print(f"  ... 외 {len(rows) - limit}건 (--limit로 더 볼 수 있어요)")


def _analyze_small(txns: Sequence[Transaction], mode: str, limit: int) -> None:
    """거래가 적어 개인 기준을 배울 수 없을 때: 룰로만 전체 거래를 본다."""
    from safepause.detect.engine import RiskEngine
    from safepause.eval.metrics import alert_row

    engine = RiskEngine(seed=0)
    assessed = engine.assess_many(txns, mode="rules")
    rows = [alert_row(t, a) for t, a in zip(txns, assessed) if a.level.value != "none"]
    print(f"[점검] 거래가 {len(txns)}건이라 AI 개인 기준을 만들 수 없어요. 룰로만 전체 거래를 봤어요.")
    if mode != "rules":
        print("  (AI 이상탐지는 거래가 31건 이상일 때 함께 써요.)")
    print(f"  알림 {len(rows)}건")
    if rows:
        print("[알림 목록]")
        _print_alert_rows(rows, limit)


def cmd_analyze(args: argparse.Namespace) -> int:
    from safepause.data.loader import load_csv
    from safepause.detect.anomaly import MIN_TRAIN
    from safepause.eval import metrics
    from safepause.eval.report import pct, write_report

    mapping = _load_mapping(args.mapping)
    txns, rep = load_csv(args.file, mapping)
    print(f"[가져오기] {rep['rows']}줄 중 {rep['loaded']}건을 읽었어요 "
          f"(건너뜀 {rep['skipped']}줄, 형식 {rep['format']}, 인코딩 {rep['encoding']})")
    for w in rep["warnings"]:
        print(f"  - {w}")
    if not txns:
        raise CliError("읽은 거래가 없어요. 파일 내용이나 mapping을 확인해 주세요.")
    if len(txns) <= MIN_TRAIN:
        _analyze_small(txns, args.mode, args.limit)
        print("이 결과는 저장하지 않았어요.")
        return 0

    result = metrics.evaluate_file(txns, args.baseline_ratio, mode=args.mode, seed=args.seed)
    p = result["period"]
    print(f"[점검] 앞 {result['n_baseline']}건으로 개인 기준을 배우고, 뒤 {result['n_eval']}건을 봤어요 "
          f"({p['eval_start'][:10]} ~ {p['eval_end'][:10]}, {result['eval_days']}일)")
    rows = result.get("n_train_rows") or 0
    if 0 < rows < result["n_baseline"]:
        print(f"  AI는 앞 {result['n_baseline']}건 가운데 {rows}건으로 배웠어요 "
              f"(맨 앞 {result['n_baseline'] - rows}건은 비교할 평소 기준이 없어서 뺐어요).")
    print(f"  알림(주의 이상) {result['alerts']}건 ({pct(result['alert_rate'])}), "
          f"고위험 {result['high']}건 ({pct(result['high_rate'])}), "
          f"30일당 알림 약 {result['monthly_alerts'] or 0:.1f}건")
    print(f"  ※ {metrics.FILE_DISCLAIMER}.")
    if result["alert_list"]:
        print("[알림 목록]")
        _print_alert_rows(result["alert_list"], args.limit)
    if args.out:
        paths = write_report(result, args.out)
        print(f"보고서를 저장했어요: {paths['markdown']} , {paths['json']}")
        print(REPORT_PRIVACY_NOTE)
    else:
        print("이 결과는 저장하지 않았어요.")
    return 0


# ---------------------------------------------------------------------------
# eval
# ---------------------------------------------------------------------------

def _split_list(text: str) -> list[str]:
    return [x.strip() for x in text.split(",") if x.strip()]


def _eval_command(args: argparse.Namespace) -> str:
    """보고서에 적는 재현 명령(기본값이 아닌 옵션만)."""
    parts = ["python -m safepause eval", f"--seeds {args.seeds}"]
    if _is_holdout(args):
        parts.append(f"--seed-start {args.seed_start}")
    if args.personas != ",".join(_default_personas()):
        parts.append(f"--personas {args.personas}")
    if args.modes != "fused,rules,anomaly":
        parts.append(f"--modes {args.modes}")
    if args.days != 120:
        parts.append(f"--days {args.days}")
    if args.baseline_days != 90:
        parts.append(f"--baseline-days {args.baseline_days}")
    if args.intensity != "standard":
        parts.append(f"--intensity {args.intensity}")
    parts.append(f"--out {Path(args.out).as_posix()}")
    return " ".join(parts)


def _is_holdout(args: argparse.Namespace) -> bool:
    """--seed-start가 기본값(1)이 아니면 별도 검증 세트 실행(SPEC §8 [추가 r5])."""
    return getattr(args, "seed_start", DEFAULT_EVAL_SEED_START) != DEFAULT_EVAL_SEED_START


def _eval_json_name(intensity: str, holdout: bool = False) -> str:
    """결과 JSON 이름: standard eval_results.json, subtle eval_results_subtle.json,
    별도 검증 세트는 뒤에 _holdout(eval_results_holdout.json, eval_results_subtle_holdout.json)."""
    from safepause.eval.report import SYNTHETIC_STEM, synthetic_json_name

    return synthetic_json_name(SYNTHETIC_STEM, intensity, "holdout" if holdout else "in_sample")


def _default_personas() -> list[str]:
    from safepause.eval.metrics import DEFAULT_PERSONAS

    return list(DEFAULT_PERSONAS)


def _guard_submitted_report(args: argparse.Namespace, command: str) -> None:
    """제출 보고서 폴더(docs/eval)에 다른 설정의 결과를 덮어쓰지 않게 막는다(--overwrite면 허용)."""
    out = Path(args.out).resolve()
    if out.parts[-2:] != SUBMITTED_EVAL_DIR or args.overwrite:
        return
    existing = out / _eval_json_name(args.intensity, _is_holdout(args))
    if not existing.is_file():
        return
    try:
        previous = json.loads(existing.read_text(encoding="utf-8")).get("command")
    except (OSError, ValueError, AttributeError):
        previous = None
    def settings_of(cmd: object) -> str:   # 출력 폴더 표기(상대·절대 경로)는 비교하지 않는다
        return str(cmd).split(" --out ")[0]

    if settings_of(previous) != settings_of(command):
        raise CliError(
            f"{Path(args.out).as_posix()}에는 제출한 보고서가 있어요(만든 명령: {previous}). "
            "다른 설정으로 덮어쓰지 않았어요. 빠른 확인은 --out 다른폴더 로 해 주세요. "
            "정말 덮어쓰려면 --overwrite를 붙이세요."
        )


def cmd_eval(args: argparse.Namespace) -> int:
    from safepause.eval.metrics import DISCLAIMER, compare_modes, default_seeds
    from safepause.eval.report import mode_name, num, pct, write_report

    _guard_submitted_report(args, _eval_command(args))
    seeds = default_seeds(args.seeds, args.seed_start)
    holdout = _is_holdout(args)
    personas = _split_list(args.personas)
    modes = _split_list(args.modes)
    print(f"평가 중: 인물 {len(personas)}개 × seed {len(seeds)}개({seeds[0]}~{seeds[-1]}), "
          f"모드 {', '.join(modes)}, 시나리오 강도 {args.intensity}"
          f"{', 별도 검증 세트' if holdout else ''} ...")
    started = time.perf_counter()
    results = compare_modes(personas, seeds, modes, args.days, args.baseline_days,
                            intensity=args.intensity)
    if holdout:
        results["split"] = "holdout"
    results["command"] = _eval_command(args)
    elapsed = time.perf_counter() - started

    print(f"[{DISCLAIMER}]")
    if args.intensity == "subtle":
        print("[경계 변형(subtle) 시나리오: 룰 기준에 못 미치거나 겨우 닿게 줄인 사전 등록 변형]")
    if holdout:
        print(f"[별도 검증 세트: seed {seeds[0]}~{seeds[-1]}. 결과를 기본 실행(seed 1부터)과 다른 파일에 저장해요]")
    for m in results["mode_order"]:
        r = results["modes"][m]
        o, nm, ctl = r["overall"], r["normal"], r.get("control") or {}
        print(f"  - {mode_name(m)}: 시나리오 탐지 주의 이상 {pct(o['recall_caution'])}, "
              f"고위험 {pct(o['recall_high'])} | 정상 알림률 {pct(nm['alert_rate'], 2)}, "
              f"월평균 {num(nm['monthly_alerts'])}건 | 대조군 월평균 {num(ctl.get('monthly_alerts'))}건")
    paths = write_report(results, args.out)
    print(f"보고서: {paths['markdown']}")
    print(f"원자료: {paths['json']}")
    print(f"걸린 시간: {elapsed:.1f}초")
    return 0


# ---------------------------------------------------------------------------
# wipe
# ---------------------------------------------------------------------------

def _confirm(prompt: str) -> bool:
    try:
        answer = input(prompt)
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes", "예", "네", "ㅇ")


def cmd_wipe(args: argparse.Namespace) -> int:
    from safepause import config
    from safepause.store import Store

    root = config.data_dir()
    print(WIPE_SERVER_HINT)
    if not args.yes and not _confirm(f"{root} 의 SafePause 데이터를 모두 지울까요? (y/N) "):
        print("지우지 않았어요. 묻지 않고 지우려면 --yes를 붙이세요.")
        return 1
    removed = Store(root).wipe()
    if removed:
        print(f"모두 지웠어요({len(removed)}개 파일): {', '.join(removed)}")
    else:
        print("지울 데이터가 없어요.")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    return serve(args.port, open_browser=not args.no_browser)


# ---------------------------------------------------------------------------
# 파서·진입점
# ---------------------------------------------------------------------------

def _port(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"포트는 숫자여야 해요: {text}") from exc
    if not 1 <= value <= 65535:
        raise argparse.ArgumentTypeError(f"포트 번호는 1~65535 사이여야 해요: {value}")
    return value


def _positive(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"숫자여야 해요: {text}") from exc
    if value < 1:
        raise argparse.ArgumentTypeError(f"1 이상이어야 해요: {value}")
    return value


def _nonneg(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"숫자여야 해요: {text}") from exc
    if value < 0:
        raise argparse.ArgumentTypeError(f"0 이상이어야 해요: {value}")
    return value


def _ratio(text: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"숫자여야 해요: {text}") from exc
    if not 0 < value < 1:
        raise argparse.ArgumentTypeError(f"0보다 크고 1보다 작아야 해요: {value}")
    return value


def build_parser() -> argparse.ArgumentParser:
    from safepause.data.synth import PERSONAS
    from safepause.detect.engine import MODES

    personas = list(PERSONAS)
    home = argparse.ArgumentParser(add_help=False)
    home.add_argument("--home", metavar="폴더", default=None,
                      help="데이터 폴더(기본: 환경변수 SAFEPAUSE_HOME, 없으면 사용자 폴더)")

    parser = argparse.ArgumentParser(
        prog="safepause",
        description="SafePause: 지원의사결정 기반 경제적 착취 사전 예방 AI (로컬 전용 프로토타입)",
    )
    parser.add_argument("--version", action="version", version=f"SafePause {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<명령>")

    p = sub.add_parser("serve", parents=[home], help="로컬 서버를 열고 브라우저로 화면을 띄워요")
    p.add_argument("--port", type=_port, default=DEFAULT_PORT,
                   help=f"포트(기본 {DEFAULT_PORT}, 사용 중이면 다음 번호)")
    p.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않아요")
    p.set_defaults(handler=cmd_serve)

    p = sub.add_parser("demo", help="합성 데이터로 샘플 3건의 판단과 카드를 보여 줘요")
    p.add_argument("--persona", choices=personas, default="worker", help="가상 인물 설정")
    p.add_argument("--seed", type=_nonneg, default=1, help="난수 seed(기본 1)")
    p.set_defaults(handler=cmd_demo)

    p = sub.add_parser("synth", help="합성 거래 CSV를 만들어요")
    p.add_argument("--persona", choices=personas, default="worker", help="가상 인물 설정")
    p.add_argument("--seed", type=_nonneg, default=1, help="난수 seed(기본 1)")
    p.add_argument("--days", type=_positive, default=120, help="기간(일, 기본 120)")
    p.add_argument("--out", required=True, help="저장할 CSV 경로")
    p.add_argument("--no-scenarios", action="store_true", help="착취 시나리오 없이 정상 거래만")
    p.set_defaults(handler=cmd_synth)

    p = sub.add_parser("analyze", help="거래내역 CSV를 가져와 알림 목록을 보여 줘요"
                                       "(SafePause 저장소에는 넣지 않음. --out을 주면 보고서 파일을 써요)")
    p.add_argument("--file", required=True, help="거래내역 CSV 경로")
    p.add_argument("--mapping", help="열 이름 지정 JSON 파일(머리글을 자동으로 못 알아볼 때)")
    p.add_argument("--mode", choices=list(MODES), default="fused", help="판단 방식(기본 fused)")
    p.add_argument("--baseline-ratio", type=_ratio, default=0.75,
                   help="앞에서부터 개인 기준 학습에 쓸 비율(기본 0.75)")
    p.add_argument("--seed", type=_nonneg, default=0, help="모델 seed(기본 0)")
    p.add_argument("--limit", type=_positive, default=DEFAULT_ANALYZE_LIMIT,
                   help=f"화면에 보여 줄 알림 수(기본 {DEFAULT_ANALYZE_LIMIT})")
    p.add_argument("--out", help="보고서를 저장할 폴더. 주면 받는 곳·금액이 든 file_eval_report.md·json을 "
                                 "써요(wipe는 이 파일을 지우지 않음)")
    p.set_defaults(handler=cmd_analyze)

    p = sub.add_parser("eval", help="3개 모드 비교 성능 평가 후 보고서를 써요(합성 데이터)")
    p.add_argument("--seeds", type=_positive, default=DEFAULT_EVAL_SEEDS,
                   help=f"seed 개수(--seed-start부터, 기본 {DEFAULT_EVAL_SEEDS})")
    p.add_argument("--seed-start", type=_nonneg, default=DEFAULT_EVAL_SEED_START,
                   help=f"첫 seed 번호(기본 {DEFAULT_EVAL_SEED_START}). 1이 아니면 별도 검증 세트로 보고 "
                        "eval_results_holdout.json(경계 변형은 eval_results_subtle_holdout.json)에 써요")
    p.add_argument("--out", default=DEFAULT_EVAL_OUT,
                   help=f"보고서 폴더(기본 {DEFAULT_EVAL_OUT}). 제출 보고서는 docs/eval")
    p.add_argument("--overwrite", action="store_true",
                   help="docs/eval의 제출 보고서를 다른 설정 결과로 덮어써도 돼요")
    p.add_argument("--personas", default=",".join(personas), help="쉼표로 구분한 인물 설정")
    p.add_argument("--modes", default=",".join(MODES), help="쉼표로 구분한 모드")
    p.add_argument("--days", type=_positive, default=120, help="사례당 기간(일, 기본 120)")
    p.add_argument("--baseline-days", type=_positive, default=90, help="학습 기준 기간(일, 기본 90)")
    p.add_argument("--intensity", choices=["standard", "subtle"], default="standard",
                   help="시나리오 강도(기본 standard). subtle은 룰 기준 경계 변형으로, 결과를 "
                        "eval_results_subtle.json에 쓰고 보고서(eval_report.md)에 절을 더해요")
    p.set_defaults(handler=cmd_eval)

    p = sub.add_parser("wipe", parents=[home], help="저장한 데이터를 모두 지워요(즉시 철회권)")
    p.add_argument("--yes", "-y", action="store_true", help="묻지 않고 바로 지워요")
    p.set_defaults(handler=cmd_wipe)
    return parser


def _safe_console() -> None:
    """콘솔이 표시하지 못하는 글자가 있어도 멈추지 않게 한다."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def run(argv: Sequence[str] | None = None) -> int:
    """명령을 실행하고 종료 코드를 돌려준다(0 성공, 1 실패·취소, 2 잘못된 인자)."""
    _safe_console()
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:  # --help·--version은 0, 인자 오류는 2
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 2)
    if not getattr(args, "handler", None):
        parser.print_help()
        return 2
    if getattr(args, "home", None):
        os.environ["SAFEPAUSE_HOME"] = str(Path(args.home).expanduser().resolve())

    from safepause.data.loader import LoaderError
    from safepause.store import StoreError

    try:
        return int(args.handler(args) or 0)
    except KeyboardInterrupt:
        print("\n중단했어요.")
        return 130
    except ImportError as exc:  # 설치가 덜 됐거나 긴 경로로 DLL을 못 불러온 경우
        if os.environ.get("SAFEPAUSE_DEBUG"):
            raise
        print(f"오류: 구성 요소를 불러오지 못했어요({exc}). {IMPORT_HINT}", file=sys.stderr)
        return 1
    except (CliError, LoaderError, StoreError, ValueError, OSError) as exc:
        if os.environ.get("SAFEPAUSE_DEBUG"):
            raise
        print(f"오류: {exc}", file=sys.stderr)
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    """진입점. argv 없이(명령행에서) 부르면 종료 코드로 프로세스를 끝낸다."""
    code = run(argv)
    if argv is None:
        sys.exit(code)
    return code


__all__ = [
    "CliError", "DEFAULT_PORT", "LOCAL_HOST", "build_parser", "find_free_port",
    "is_port_free", "main", "run", "serve",
]
