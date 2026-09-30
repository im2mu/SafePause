"""제출·배포용 소스 zip 만들기(표준 라이브러리만 사용).

    python packaging/make_release_zip.py            # → dist/SafePause-<버전>-src.zip
    python packaging/make_release_zip.py --out x.zip

- 넣을 파일은 허용 목록으로 고른다(safepause/, tests/, docs/, sample_data/, packaging/, .github/와
  알려진 최상위 파일). 그 밖의 파일(사용자가 폴더에 둔 실제 거래내역 CSV 등)은 넣지 않는다.
- 허용한 폴더 안에서도 개발 산출물(.venv, build, dist, *.egg-info, .pytest_cache, __pycache__ 등)과
  개인 데이터가 들 수 있는 파일을 뺀다: SafePause 저장 파일(consent·helpers·transactions·decisions·
  notices.json), ``analyze --out`` 보고서(file_eval_*), 임시·잠금 파일(.sp-*, *.lock),
  sample_data 밖의 *.csv. 끝에 zip을 다시 열어 이런 이름이 있으면 실패로 알린다.
- 줄바꿈을 고정한다: .bat/.cmd는 CRLF(cmd.exe 요구), .sh는 LF(macOS·Linux sh 요구).
  git 설정(core.autocrlf)이나 체크아웃 환경과 관계없이 zip 안의 줄바꿈이 맞게 된다.
- 끝나면 zip 안의 .bat CR 수와 .sh CR 수를 다시 세어 보여 준다(검증).
- SafePause.exe(dist/)는 넣지 않는다. exe는 따로 첨부한다.
"""
from __future__ import annotations

import argparse
import fnmatch
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
TOP = "SafePause"   # zip 안 맨 위 폴더 이름(짧은 경로에 풀기 쉽게)

# 넣는 것(허용 목록)
INCLUDE_DIRS: tuple[str, ...] = ("safepause", "tests", "docs", "sample_data", "packaging", ".github", "android")
INCLUDE_FILES: tuple[str, ...] = (
    "README.md", "SPEC.md", "requirements.txt", "pyproject.toml", "run_windows.bat", "run_mac_linux.sh",
    "Dockerfile", ".gitattributes", ".gitignore",
)
# 개인 데이터가 들 수 있는 이름(허용한 폴더 안이어도 뺀다). safepause/store.py STORE_FILES와 같게 둔다
PRIVATE_FILE_NAMES = frozenset({
    "consent.json", "helpers.json", "transactions.json", "decisions.json", "notices.json", "serve.lock",
})
PRIVATE_FILE_GLOBS: tuple[str, ...] = ("file_eval_*", ".sp-*", "*.lock",
                                       "*.jks", "*.keystore", "keystore.properties", "*.apk", "*.idsig")   # 서명 키·빌드 결과는 넣지 않음
CSV_DIR = "sample_data"      # *.csv는 이 폴더(가상 예시)에서만 넣는다

EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "build", "dist", ".pytest_cache", "__pycache__", ".mypy_cache",
    ".ruff_cache", ".idea", ".vscode", ".ci-home", "ci-eval", "eval_out",
    "signing", "www-build", "pyodide-dist",   # 안드로이드: 서명 키 폴더·조립 결과·내려받은 Pyodide
}
EXCLUDE_DIR_GLOBS = ("*.egg-info",)
EXCLUDE_FILE_GLOBS = ("*.pyc", "*.pyo", "*.zip", "*.log", ".DS_Store", "Thumbs.db")
CRLF_SUFFIXES = (".bat", ".cmd")
LF_SUFFIXES = (".sh",)
EXECUTABLE_SUFFIXES = (".sh",)


def _version() -> str:
    for line in (ROOT / "safepause" / "__init__.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip("\"'")
    return "0"


def _skip_dir(name: str) -> bool:
    return name in EXCLUDE_DIRS or any(fnmatch.fnmatch(name, g) for g in EXCLUDE_DIR_GLOBS)


def is_private(rel: PurePosixPath | Path) -> bool:
    """개인 데이터가 들 수 있는 파일인지(저장 파일·보고서·임시·잠금 파일, sample_data 밖 CSV)."""
    rel = PurePosixPath(Path(rel).as_posix())
    name = rel.name
    if name in PRIVATE_FILE_NAMES or any(fnmatch.fnmatch(name, g) for g in PRIVATE_FILE_GLOBS):
        return True
    return name.lower().endswith(".csv") and (not rel.parts or rel.parts[0] != CSV_DIR)


def _wanted(rel: Path) -> bool:
    return not (any(fnmatch.fnmatch(rel.name, g) for g in EXCLUDE_FILE_GLOBS) or is_private(rel))


def iter_files(root: Path = ROOT) -> list[Path]:
    """zip에 넣을 파일(저장소 기준 상대 경로), 이름순. 허용 목록의 폴더·파일만 본다."""
    out: list[Path] = []
    stack = [root / d for d in INCLUDE_DIRS if (root / d).is_dir()]
    for name in INCLUDE_FILES:
        rel = Path(name)
        if (root / rel).is_file() and _wanted(rel):
            out.append(rel)
    while stack:
        folder = stack.pop()
        for p in sorted(folder.iterdir()):
            if p.is_dir():
                if not _skip_dir(p.name):
                    stack.append(p)
            elif p.is_file():
                rel = p.relative_to(root)
                if _wanted(rel):
                    out.append(rel)
    return sorted(out, key=lambda r: r.as_posix())


def normalized_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix.lower() in CRLF_SUFFIXES:
        return data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    if path.suffix.lower() in LF_SUFFIXES:
        return data.replace(b"\r\n", b"\n")
    return data


def build(out: Path) -> dict[str, int]:
    out.parent.mkdir(parents=True, exist_ok=True)
    files = iter_files()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            src = ROOT / rel
            info = zipfile.ZipInfo(f"{TOP}/{rel.as_posix()}")
            info.date_time = (2026, 1, 1, 0, 0, 0)   # 같은 내용이면 같은 zip(재현 가능)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if rel.suffix.lower() in EXECUTABLE_SUFFIXES else 0o644
            info.external_attr = (0o100000 | mode) << 16
            zf.writestr(info, normalized_bytes(src))
    return verify(out)


def verify(zip_path: Path) -> dict[str, int]:
    """zip 검사: .bat는 모든 줄이 CRLF, .sh에는 CR이 없고, 개발 산출물·개인 데이터 파일이 없어야 한다."""
    report = {"files": 0, "bat_lines": 0, "bat_crlf": 0, "sh_cr": 0, "venv_entries": 0,
              "private_entries": 0}
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            report["files"] += 1
            parts = name.split("/")
            if any(_skip_dir(p) for p in parts[:-1]):
                report["venv_entries"] += 1
            inner = PurePosixPath(*parts[1:]) if len(parts) > 1 and parts[0] == TOP else PurePosixPath(name)
            if is_private(inner):
                report["private_entries"] += 1
            data = zf.read(name)
            if name.lower().endswith(CRLF_SUFFIXES):
                report["bat_lines"] += data.count(b"\n")
                report["bat_crlf"] += data.count(b"\r\n")
            elif name.lower().endswith(LF_SUFFIXES):
                report["sh_cr"] += data.count(b"\r")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SafePause 소스 zip 만들기")
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / f"SafePause-{_version()}-src.zip")
    args = parser.parse_args(argv)
    report = build(args.out)
    print(f"만들었어요: {args.out} (파일 {report['files']}개)")
    print(f"  .bat 줄 {report['bat_lines']}개 중 CRLF {report['bat_crlf']}개, .sh 안 CR {report['sh_cr']}개, "
          f"개발 산출물 {report['venv_entries']}개, 개인 데이터가 들 수 있는 파일 {report['private_entries']}개")
    if not is_ok(report):
        print("줄바꿈 또는 제외 목록 검사에 실패했어요.", file=sys.stderr)
        return 1
    return 0


def is_ok(report: dict[str, int]) -> bool:
    return (report["bat_lines"] == report["bat_crlf"] and report["sh_cr"] == 0
            and report["venv_entries"] == 0 and report["private_entries"] == 0)


if __name__ == "__main__":
    sys.exit(main())
