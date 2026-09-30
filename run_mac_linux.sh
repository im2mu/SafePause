#!/usr/bin/env sh
# SafePause 소스 실행(macOS·Linux). 처음 한 번은 가상환경 .venv 를 만들고 패키지를 설치한다.
# 그다음부터는 바로 로컬 서버를 열고 브라우저로 화면을 띄운다.
# 추가 인자는 serve 명령에 그대로 넘긴다. 예: sh run_mac_linux.sh --port 9000 --no-browser
# 다른 Python을 쓰려면: PYTHON=python3.12 sh run_mac_linux.sh
set -eu

cd "$(dirname "$0")"
PY_BOOT="${PYTHON:-python3}"
VENV_PY=".venv/bin/python"
MARK=".venv/.safepause-installed"

if [ ! -f "$MARK" ]; then
    echo "[SafePause] 처음 실행 준비: 가상환경을 만들고 필요한 패키지를 설치합니다."
    echo "[SafePause] 인터넷 연결이 필요하고, 몇 분 걸릴 수 있어요."
    if [ ! -x "$VENV_PY" ]; then
        if ! command -v "$PY_BOOT" >/dev/null 2>&1; then
            echo "[SafePause] Python 3.10 이상($PY_BOOT)을 찾지 못했어요. 설치한 뒤 다시 실행해 주세요." >&2
            echo "[SafePause] 다른 이름의 Python을 쓰려면 예: PYTHON=python3.12 sh run_mac_linux.sh" >&2
            exit 1
        fi
        "$PY_BOOT" -m venv .venv
    fi
    if ! "$VENV_PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
        echo "[SafePause] Python 3.10 이상이 필요해요. .venv 폴더를 지우고 새 Python으로 다시 실행해 주세요." >&2
        echo "[SafePause] 예: rm -rf .venv && PYTHON=python3.12 sh run_mac_linux.sh" >&2
        exit 1
    fi
    "$VENV_PY" -m pip install --upgrade pip
    "$VENV_PY" -m pip install -r requirements.txt
    echo installed > "$MARK"
fi

echo "[SafePause] 서버를 시작합니다. 끝내려면 Ctrl+C 를 누르세요."
exec "$VENV_PY" -m safepause serve "$@"
