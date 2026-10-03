"""앱 묶음 경량화: Pyodide wheel에서 앱이 쓰지 않는 파일을 빼고 다시 묶는다(android/assemble_www.py가 부른다).

빼는 것(파일 이름만 보고 정한다. 내용은 바꾸지 않음)
1) 안전한 제거(실행 중에는 읽지 않는 파일)
   - 패키지 안 tests/ 폴더(시험 코드·시험 자료)
   - 빌드 전용 원본·선언: .pyi(형 힌트 스텁) .pxd .pyx .pxi .tp(Cython·Tempita) .c .h .hpp .cpp .cc, meson.build,
     정적 라이브러리 .a
   - numpy: C 헤더(numpy/_core/include)·정적 라이브러리와 pkg-config(numpy/_core/lib, numpy/random/lib)
   - scikit-learn: 내장 예제 데이터(sklearn/datasets의 data·descr·images). SafePause 코드는 load_*·fetch_*를 쓰지 않는다
     (safepause 폴더 grep 확인, tests/test_slim_wheels.py가 계속 확인)
2) 추적 기반 제거(PRUNE): 앱 안 엔진에서 모든 API를 부른 뒤 sys.modules에 한 번도 나오지 않은 scipy·sklearn 하위 패키지 중,
   실제로 불린 모듈에서 정적 import(함수 안 늦은 import·importlib 글자·속성 사슬·.so 안 점 이름까지)로 닿지 않는 것.
   일부라도 쓰인 패키지는 남긴다. 다시 구하는 법: android/slim_trace.py run → plan(머리말 참고).
   scipy·scikit-learn 판이 바뀌면 PRUNE을 다시 구해야 한다(PRUNE_FOR의 판과 다르면 멈춘다).

dist-info(라이선스·METADATA)는 그대로 두고, RECORD에서는 뺀 파일 줄만 지운다.
다시 묶은 wheel은 압축 수준 9(zlib)로 쓴다. 같은 입력이면 같은 파일이 나온다(날짜·권한은 원래 값을 그대로 씀).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from pathlib import Path

SAFE_SUFFIXES = (".pyi", ".pxd", ".pyx", ".pxi", ".tp", ".c", ".h", ".hpp", ".cpp", ".cc", ".a")
SAFE_NAMES = ("meson.build",)
SAFE_DIRS: dict[str, tuple[str, ...]] = {
    "numpy": ("numpy/_core/include/", "numpy/_core/lib/", "numpy/random/lib/"),
    "scikit-learn": ("sklearn/datasets/data/", "sklearn/datasets/descr/", "sklearn/datasets/images/"),
}
# 추적 기반 제거 목록(2026-10-03, slim_trace.py run → plan --lazy all. 판: PRUNE_FOR)
# 실행 중 불린 모듈: scipy 493개·sklearn 240개(API 106회 호출). 안 불렸지만 정적 분석으로 남긴 패키지:
# scipy.signal(.so 설명문 속 이름), scipy._external.cobyqa·pyprima(optimize 늦은 import), array_api_compat의
# cupy·dask·torch, sklearn.cluster·manifold·gaussian_process·experimental·externals._scipy(늦은 import·설명문)
PRUNE: dict[str, tuple[str, ...]] = {
    "scipy": ("scipy.cluster", "scipy.datasets", "scipy.differentiate", "scipy.fftpack", "scipy.io", "scipy.misc",
              "scipy.odr", "scipy.optimize.cython_optimize", "scipy.special._precompute", "scipy.stats._unuran"),
    "scikit-learn": ("sklearn._build_utils", "sklearn.cross_decomposition", "sklearn.datasets",
                     "sklearn.feature_extraction", "sklearn.feature_selection", "sklearn.frozen", "sklearn.impute",
                     "sklearn.inspection", "sklearn.mixture", "sklearn.neural_network", "sklearn.semi_supervised",
                     "sklearn.utils._test_common"),
}
PRUNE_FOR = {"scipy": "1.18.0", "scikit-learn": "1.8.0"}


def removal_reason(pkg: str, name: str, prune: bool = True) -> str | None:
    """wheel 안 파일 하나를 뺄 이유(tests·source·data·unused). 남길 파일이면 None."""
    if name.endswith("/") or ".dist-info/" in name or name.endswith(".dist-info"):
        return None
    parts = name.split("/")
    if "tests" in parts[:-1]:
        return "tests"
    base = parts[-1]
    if base in SAFE_NAMES or base.endswith(SAFE_SUFFIXES):
        return "source"
    if any(name.startswith(d) for d in SAFE_DIRS.get(pkg, ())):
        return "data"
    if prune and any(name.startswith(p.replace(".", "/") + "/") for p in PRUNE.get(pkg, ())):
        return "unused"
    return None


def _record_name(names: list[str]) -> str | None:
    found = [n for n in names if n.count("/") == 1 and n.endswith(".dist-info/RECORD")]
    return found[0] if len(found) == 1 else None


def rewrite_record(data: bytes, removed: set[str]) -> bytes:
    """RECORD(csv: 경로,해시,크기)에서 뺀 파일 줄만 지운다. 남는 줄은 글자 그대로."""
    text = data.decode("utf-8")
    out = []
    for line in text.splitlines(keepends=True):
        row = next(csv.reader(io.StringIO(line)), None)
        if row and row[0] in removed:
            continue
        out.append(line)
    return "".join(out).encode("utf-8")


def slim_wheel(src: Path, dst: Path, pkg: str, *, prune: bool = True, version: str | None = None) -> dict:
    """src wheel에서 뺄 파일을 빼고 dst에 다시 묶는다. 결과 요약(이유별 파일 수·압축 전 바이트)을 돌려준다."""
    if prune and pkg in PRUNE and version is not None and version != PRUNE_FOR.get(pkg):
        raise SystemExit(f"{pkg} {version}: PRUNE 목록은 {PRUNE_FOR.get(pkg)}용이에요. "
                         "android/slim_trace.py로 다시 구해 주세요.")
    summary: dict = {"files": 0, "kept": 0, "removed": {}, "removed_bytes": {}}
    with zipfile.ZipFile(src) as zin:
        infos = zin.infolist()
        names = [i.filename for i in infos]
        record = _record_name(names)
        removed = {i.filename for i in infos if removal_reason(pkg, i.filename, prune)}
        if prune:   # 목록의 패키지가 wheel에 실제로 있어야 한다(판이 달라 이름이 바뀐 경우를 잡는다)
            for p in PRUNE.get(pkg, ()):
                if not any(n.startswith(p.replace(".", "/") + "/__init__.py") for n in names):
                    raise SystemExit(f"{src.name}: PRUNE의 {p} 패키지가 wheel에 없어요.")
        with zipfile.ZipFile(dst, "w") as zout:
            for info in infos:
                summary["files"] += 1
                reason = removal_reason(pkg, info.filename, prune)
                if reason:
                    summary["removed"][reason] = summary["removed"].get(reason, 0) + 1
                    summary["removed_bytes"][reason] = summary["removed_bytes"].get(reason, 0) + info.file_size
                    continue
                data = zin.read(info)
                if info.filename == record:
                    data = rewrite_record(data, removed)
                out = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                out.external_attr, out.create_system = info.external_attr, info.create_system
                out.compress_type = zipfile.ZIP_DEFLATED
                zout.writestr(out, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
                summary["kept"] += 1
    summary["src_bytes"], summary["dst_bytes"] = src.stat().st_size, dst.stat().st_size
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="wheel에서 뺄 파일 목록 보기(아무것도 쓰지 않음)")
    ap.add_argument("wheel", type=Path)
    ap.add_argument("--package", required=True, help="pyodide-lock의 패키지 이름(예: scipy, scikit-learn)")
    ap.add_argument("--no-prune", action="store_true")
    a = ap.parse_args(argv)
    rows: dict[str, list] = {}
    with zipfile.ZipFile(a.wheel) as z:
        for i in z.infolist():
            r = removal_reason(a.package, i.filename, not a.no_prune)
            if r:
                rows.setdefault(r, []).append((i.filename, i.file_size, i.compress_size))
    print(json.dumps({r: {"files": len(v), "bytes": sum(x[1] for x in v), "compressed": sum(x[2] for x in v),
                          "list": [x[0] for x in v]} for r, v in rows.items()}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
