# -*- mode: python ; coding: utf-8 -*-
# SafePause.exe(onefile) PyInstaller 빌드 설정. 실행: packaging\build_exe.bat
# 결과: dist\SafePause.exe (더블클릭 → 로컬 서버 + 브라우저, 콘솔 창에 주소 표시)
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent          # 저장소 루트(packaging의 상위 폴더)
STATIC = ROOT / "safepause" / "server" / "static"
if not STATIC.is_dir():
    raise SystemExit(f"정적 화면 폴더가 없어요: {STATIC}")


def _no_tests(name: str) -> bool:
    return ".tests" not in name and not name.endswith(".conftest")


# 문자열로 불러오는 모듈(uvicorn 루프·프로토콜, sklearn 내부 확장 모듈)을 빠짐없이 넣는다.
hiddenimports = (
    collect_submodules("safepause", filter=_no_tests)
    + collect_submodules("uvicorn")
    + collect_submodules("sklearn", filter=_no_tests)
)

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(STATIC), "safepause/server/static")],   # index.html, app.js, style.css, icons/*.svg
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pandas", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SafePause",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,            # 서버 주소·종료 방법(Ctrl+C)을 보여 줄 창
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
