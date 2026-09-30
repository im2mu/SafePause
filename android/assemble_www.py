"""안드로이드 앱에 넣을 화면·엔진 묶음(assets/www)을 만든다.

    python android/assemble_www.py --pyodide <Pyodide 파일 폴더> --out android/www-build

만드는 것
- 화면: safepause/web 전체(PC판과 같은 파일) + js/mode.js(앱 안 엔진 모드 표시)
- 파이썬 엔진: py/safepause.zip(safepause 패키지. 서버·화면 폴더는 뺌)
- Pyodide 314.0.7 실행 파일과 쓰는 패키지만(numpy·scipy·scikit-learn·joblib·threadpoolctl·pydantic 계열).
  wheel은 pyodide-lock.json의 sha256과 대조한다(다르면 멈춤).
- licenses/: 함께 담는 오픈소스의 라이선스 전문(wheel 안 dist-info에서 꺼냄, Pyodide·CPython 전문)

Pyodide 파일 받기(한 번): https://cdn.jsdelivr.net/pyodide/v314.0.7/full/ 에서
pyodide.mjs, pyodide.asm.mjs, pyodide.asm.wasm, python_stdlib.zip, pyodide-lock.json과 아래 PACKAGES의 wheel,
그리고 LICENSE-pyodide.txt(github pyodide/pyodide LICENSE), LICENSE-cpython.txt(github python/cpython LICENSE).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PYODIDE_VERSION = "314.0.7"
CORE_FILES = ("pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json")
PACKAGES = ("numpy", "scipy", "scikit-learn", "joblib", "threadpoolctl",
            "pydantic", "pydantic-core", "typing-extensions", "annotated-types", "typing-inspection")
SKIP_PARTS = {"server", "web", "__pycache__"}
MODE_JS = ("/* 안드로이드 앱 묶음 표시: 화면이 로컬 서버 대신 앱 안 파이썬 엔진(웹 워커)을 쓴다. */\n"
           "window.__SAFEPAUSE_ENGINE__ = true;\n")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def assemble(pyodide: Path, out: Path) -> dict[str, int]:
    if out.exists():
        shutil.rmtree(out)
    # 1) 화면
    shutil.copytree(ROOT / "safepause" / "web", out, ignore=shutil.ignore_patterns("__pycache__"))
    (out / "js" / "mode.js").write_text(MODE_JS, encoding="utf-8")
    index = (out / "index.html").read_text(encoding="utf-8")
    tag = '<script type="module" src="js/main.js"></script>'
    if tag not in index:
        raise SystemExit("index.html에서 main.js 태그를 찾지 못했어요.")
    index = index.replace(tag, '<script src="js/mode.js"></script>\n  ' + tag)
    (out / "index.html").write_text(index, encoding="utf-8")

    # 2) 파이썬 엔진(safepause 패키지)
    (out / "py").mkdir()
    n_py = 0
    with zipfile.ZipFile(out / "py" / "safepause.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted((ROOT / "safepause").rglob("*.py")):
            rel = path.relative_to(ROOT)
            if SKIP_PARTS & set(rel.parts[1:-1]):
                continue
            z.write(path, rel.as_posix())
            n_py += 1

    # 3) Pyodide와 패키지(sha256 대조)
    dst = out / "pyodide"
    dst.mkdir()
    for name in CORE_FILES:
        src = pyodide / name
        if not src.is_file():
            raise SystemExit(f"Pyodide 파일이 없어요: {src}")
        shutil.copy2(src, dst / name)
    lock = json.loads((pyodide / "pyodide-lock.json").read_text(encoding="utf-8"))
    if str(lock.get("info", {}).get("version", PYODIDE_VERSION)) not in (PYODIDE_VERSION, "None"):
        print(f"  주의: pyodide-lock 버전 {lock['info'].get('version')}", file=sys.stderr)
    (out / "licenses").mkdir()
    n_lic = 0
    for pkg in PACKAGES:
        info = lock["packages"][pkg]
        src = pyodide / info["file_name"]
        if not src.is_file():
            raise SystemExit(f"패키지 파일이 없어요: {src}")
        if _sha256(src) != info["sha256"]:
            raise SystemExit(f"패키지 파일 해시가 달라요(손상·변조 의심): {src.name}")
        shutil.copy2(src, dst / src.name)
        with zipfile.ZipFile(src) as whl:   # dist-info 안의 라이선스 전문을 꺼낸다(BSD·MIT: 고지 의무)
            for name in whl.namelist():
                base = name.rsplit("/", 1)[-1].upper()
                if ".dist-info/" in name and (base.startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS"))):
                    target = out / "licenses" / f"{pkg}-{info['version']}-{name.rsplit('/', 1)[-1]}"
                    if not target.suffix:
                        target = target.with_suffix(".txt")
                    target.write_bytes(whl.read(name))
                    n_lic += 1
    for extra in ("LICENSE-pyodide.txt", "LICENSE-cpython.txt"):
        src = pyodide / extra
        if src.is_file():
            shutil.copy2(src, out / "licenses" / extra)
            n_lic += 1
        else:
            raise SystemExit(f"라이선스 전문이 없어요: {src}")
    (out / "licenses" / "README.txt").write_text(
        "SafePause 안드로이드 앱에 함께 담긴 오픈소스의 라이선스 전문입니다.\n"
        f"Pyodide {PYODIDE_VERSION} (MPL-2.0, 소스: https://github.com/pyodide/pyodide), CPython 표준 라이브러리(PSF),\n"
        "NumPy·SciPy·scikit-learn·joblib·threadpoolctl(BSD-3-Clause), pydantic·pydantic-core·annotated-types·"
        "typing-inspection(MIT), typing-extensions(PSF).\n", encoding="utf-8")
    from safepause import __version__
    (out / "version.json").write_text(json.dumps({"app": __version__, "pyodide": PYODIDE_VERSION,
                                                   "packages": {p: lock["packages"][p]["version"] for p in PACKAGES}},
                                                  ensure_ascii=False, indent=1), encoding="utf-8")
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    return {"python_files": n_py, "license_files": n_lic, "bytes": size}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pyodide", type=Path, default=HERE / "pyodide-dist")
    ap.add_argument("--out", type=Path, default=HERE / "www-build")
    a = ap.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    r = assemble(a.pyodide, a.out)
    print(f"완료: {a.out} (파이썬 {r['python_files']}개, 라이선스 {r['license_files']}개, {r['bytes'] / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
