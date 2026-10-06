"""저장소 설정 점검: 시험·의존성 설정, CI 셸, 개인 데이터 파일 제외."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pytest_and_dependency_settings() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'pythonpath = ["."]' in pyproject                # 설치 없이 `pytest -q`
    assert '"pydantic>=2,<3"' in pyproject
    assert "pydantic>=2,<3" in (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert (ROOT / "README.md").is_file()                   # pyproject readme


def _pyproject_block(text: str, key: str) -> list[str]:
    start = text.index(f"{key} = [")
    return re.findall(r'"([^"]+)"', text[start:text.index("]", start)])


def _ranges(specs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for spec in specs:
        m = re.match(r"\s*([A-Za-z0-9_.\-]+)\s*(.*)$", spec)
        assert m, spec
        out[m.group(1).lower()] = m.group(2).replace(" ", "")
    return out


def test_pyproject_and_requirements_use_same_ranges() -> None:
    """pip install . 로 설치해도 requirements.txt와 같은 범위(주 버전 상한 포함)가 적용된다."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    req_lines = [ln.split("#")[0].strip() for ln in
                 (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()]
    from_req = _ranges([ln for ln in req_lines if ln])
    from_pyproject = _ranges(_pyproject_block(pyproject, "dependencies"))
    assert from_pyproject == from_req
    assert all("<" in spec for spec in from_pyproject.values())      # 상한이 모두 있음
    test_deps = _ranges(_pyproject_block(pyproject, "test"))
    assert test_deps["httpx"] == ">=0.27,<0.28"                       # starlette 0.36 TestClient와 맞춤


def test_ci_uses_bash_so_each_command_failure_counts() -> None:
    """Windows 러너 기본 셸(pwsh)은 여러 줄 중 마지막 명령의 종료 코드만 본다."""
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert re.search(r"defaults:\s*\n\s*run:\s*\n\s*shell: bash", workflow)
    assert 'httpx>=0.27,<0.28' in workflow


def test_private_store_files_are_git_ignored() -> None:
    """개인 데이터가 들 수 있는 저장 파일·분석 결과·거래 CSV는 저장소에 올라가지 않는다."""
    from safepause.store import STORE_FILES

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for name in (*STORE_FILES, "file_eval_*", ".sp-*", "*.csv", "!sample_data/*.csv"):
        assert name in gitignore.splitlines(), name
