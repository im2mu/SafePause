"""배포 파일 점검: 줄바꿈(CRLF/LF), 제출 zip 구성, 실행 설정."""
from __future__ import annotations

import importlib.util
import re
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_zip_tool():
    spec = importlib.util.spec_from_file_location("make_release_zip", ROOT / "packaging" / "make_release_zip.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ["run_windows.bat", "packaging/build_exe.bat"])
def test_batch_files_use_crlf_without_bom(name: str) -> None:
    data = (ROOT / name).read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")          # BOM이 있으면 첫 줄(@echo off)이 깨짐
    assert data.count(b"\n") == data.count(b"\r\n") > 0   # 모든 줄이 CRLF


def test_shell_script_uses_lf() -> None:
    assert b"\r" not in (ROOT / "run_mac_linux.sh").read_bytes()


def test_gitattributes_pins_line_endings() -> None:
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    for rule in ("*.bat text eol=crlf", "*.cmd text eol=crlf", "*.sh text eol=lf", "*.spec text eol=lf"):
        assert rule in text


def test_pytest_and_dependency_settings() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'pythonpath = ["."]' in pyproject                # 설치 없이 `pytest -q`
    assert '"pydantic>=2,<3"' in pyproject
    assert "pydantic>=2,<3" in (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert (ROOT / "README.md").is_file()                   # pyproject readme


def test_release_zip_excludes_dev_files_and_fixes_line_endings(tmp_path: Path) -> None:
    tool = _load_zip_tool()
    out = tmp_path / "release.zip"
    report = tool.build(out)
    assert report["venv_entries"] == 0
    assert report["bat_lines"] == report["bat_crlf"] > 0 and report["sh_cr"] == 0
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert all(n.startswith("SafePause/") for n in names)
    for needed in ("README.md", "run_windows.bat", "run_mac_linux.sh", "requirements.txt",
                   "safepause/server/static/index.html", "safepause/models.py", "docs/eval/eval_report.md"):
        assert f"SafePause/{needed}" in names, needed
    banned = (".venv/", "build/", "dist/", ".egg-info/", ".pytest_cache/", "__pycache__/", ".git/")
    assert not [n for n in names if any(b in n for b in banned)]


# ---- 리뷰 수정 확인(round 2) ------------------------------------------------

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


@pytest.mark.parametrize("name", ["run_windows.bat", "packaging/build_exe.bat"])
def test_batch_files_check_extracted_folder(name: str) -> None:
    """압축을 풀지 않고 bat만 실행하면 원인을 알려 주고 멈춘다(쓸모없는 .venv를 만들지 않음)."""
    text = (ROOT / name).read_text(encoding="utf-8")
    assert 'if not exist "requirements.txt" goto :not_extracted' in text
    assert r'if not exist "safepause\__init__.py" goto :not_extracted' in text
    assert ":not_extracted" in text and "압축을 먼저 모두 푼 뒤" in text
    # 점검은 가상환경을 만들기 전에 한다
    assert text.index("goto :not_extracted") < text.index("venv .venv")


# ---- 리뷰 수정 확인(round 3) ------------------------------------------------

def test_release_zip_uses_allow_list_and_skips_private_files(tmp_path: Path) -> None:
    """[변경 r3] 프로젝트 폴더 안에 생긴 개인 데이터(serve --home, analyze --out, 실제 CSV)는 넣지 않는다."""
    tool = _load_zip_tool()
    root = tmp_path / "proj"
    for rel, text in {
        "README.md": "x", "requirements.txt": "x", "safepause/__init__.py": "x",
        "sample_data/bank_export_example.csv": "a,b",
        "mydata/transactions.json": "[]", "mydata/helpers.json": "[]",
        "report/file_eval_report.md": "받는 곳", "내거래.csv": "a,b",
        "docs/file_eval_report.json": "{}", "tests/helpers.json": "[]", "safepause/.sp-store.lock": "",
        "sample_data/serve.lock": "", "docs/notes.csv": "a,b",
    }.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    got = {p.as_posix() for p in tool.iter_files(root)}
    assert got == {"README.md", "requirements.txt", "safepause/__init__.py", "sample_data/bank_export_example.csv"}


def test_release_zip_verify_fails_on_private_names(tmp_path: Path) -> None:
    tool = _load_zip_tool()
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("SafePause/README.md", "x")
        zf.writestr("SafePause/mydata/decisions.json", "[]")
        zf.writestr("SafePause/내거래.csv", "a,b")
    report = tool.verify(bad)
    assert report["private_entries"] == 2 and not tool.is_ok(report)


def test_private_names_match_store_files() -> None:
    from safepause.store import STORE_FILES

    tool = _load_zip_tool()
    assert set(STORE_FILES) <= tool.PRIVATE_FILE_NAMES
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for name in (*STORE_FILES, "file_eval_*", ".sp-*", "*.csv", "!sample_data/*.csv"):
        assert name in gitignore.splitlines(), name
