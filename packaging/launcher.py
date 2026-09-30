"""SafePause.exe(PyInstaller) 진입점.

인자 없이 실행(더블클릭)하면 로컬 서버를 열고 기본 브라우저로 화면을 띄운다.
포트가 사용 중이면 cli.serve가 다음 포트를 찾는다. 다른 명령도 그대로 쓸 수 있다
(예: ``SafePause.exe demo``, ``SafePause.exe eval --seeds 5``, ``SafePause.exe --port 9000``).
"""
from __future__ import annotations

import multiprocessing
import sys
import traceback
from collections.abc import Sequence

from safepause.cli import main

_TOP_LEVEL_FLAGS = ("-h", "--help", "--version")


def launcher_argv(args: Sequence[str]) -> list[str]:
    """exe 인자 → cli 인자. 명령이 없으면 serve를 붙인다."""
    args = list(args)
    if not args or (args[0].startswith("-") and args[0] not in _TOP_LEVEL_FLAGS):
        return ["serve", *args]
    return args


def _pause_on_error(code: int) -> None:
    """더블클릭으로 연 창이 오류 메시지를 보여 주기 전에 닫히지 않게 한다."""
    if code != 0 and getattr(sys, "frozen", False) and sys.stdin and sys.stdin.isatty():
        try:
            input("Enter 키를 누르면 창이 닫혀요.")
        except EOFError:
            pass


def run(args: Sequence[str] | None = None) -> int:
    multiprocessing.freeze_support()  # 얼린(frozen) 실행 파일에서 하위 프로세스 대비
    try:
        code = main(launcher_argv(sys.argv[1:] if args is None else args))
    except SystemExit as exc:   # 서버 구성 요소가 sys.exit()로 끝내도 오류 안내를 보여 주고 닫는다(v0.2)
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except Exception:   # 예상하지 못한 오류: 내용을 보여 주고 창이 바로 닫히지 않게
        traceback.print_exc()
        code = 1
    _pause_on_error(code)
    return code


if __name__ == "__main__":
    sys.exit(run())
