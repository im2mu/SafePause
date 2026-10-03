"""앱 묶음 경량화 시험(android/slim_wheels.py·assemble_www.py·slim_trace.py의 분석 부분).

실제 Pyodide 파일(수십 MB) 없이 작은 가짜 wheel로 규칙·다시 묶기·lock 해시 갱신을 확인한다.
실제 묶음 확인(모든 API 응답 같음·보고서 수치 다시 계산·화면 흐름)은 slim_trace.py와 헤드리스 Chrome으로 따로 한다.
"""
from __future__ import annotations

import ast
import base64
import csv
import hashlib
import importlib.util
import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "android" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sw = _load("slim_wheels")
aw = _load("assemble_www")
st = _load("slim_trace")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_wheel(path: Path, files: dict[str, bytes], dist: str) -> Path:
    """RECORD가 있는 작은 wheel. 날짜·권한을 일부러 여러 값으로 둔다."""
    rows = []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for k, (name, data) in enumerate(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1 + k % 28, 0, 0, 0))
            info.external_attr = (0o755 if name.endswith(".so") else 0o644) << 16
            z.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
            digest = hashlib.sha256(data).digest()
            rows.append([name, "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode(), str(len(data))])
        rows.append([f"{dist}.dist-info/RECORD", "", ""])
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n").writerows(rows)
        z.writestr(f"{dist}.dist-info/RECORD", buf.getvalue())
    return path


# ---------------------------------------------------------------------------------------------
# 1. 빼는 규칙
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("pkg,name,want", [
    ("scipy", "scipy/linalg/tests/test_basic.py", "tests"),
    ("scipy", "scipy/special/tests/data/boost.npz", "tests"),
    ("numpy", "numpy/__init__.pyi", "source"),
    ("numpy", "numpy/__init__.cython-30.pxd", "source"),
    ("scikit-learn", "sklearn/tree/_tree.pyx", "source"),
    ("scikit-learn", "sklearn/neighbors/_binary_tree.pxi.tp", "source"),
    ("scikit-learn", "sklearn/svm/src/libsvm/svm.cpp", "source"),
    ("scikit-learn", "sklearn/meson.build", "source"),
    ("numpy", "numpy/random/lib/libnpyrandom.a", "source"),
    ("numpy", "numpy/_core/include/numpy/ndarraytypes.h", "source"),
    ("numpy", "numpy/_core/lib/pkgconfig/numpy.pc", "data"),
    ("scikit-learn", "sklearn/datasets/data/iris.csv", "data"),
    ("scikit-learn", "sklearn/datasets/images/china.jpg", "data"),
    ("scipy", "scipy/io/matlab/_mio.py", "unused"),
    ("scikit-learn", "sklearn/neural_network/__init__.py", "unused"),
    # 남기는 것
    ("scipy", "scipy/linalg/_basic.py", None),
    ("scipy", "scipy/special/_ufuncs.cpython-314-wasm32-emscripten.so", None),
    ("scipy", "scipy/signal/__init__.py", None),                 # 정적 분석으로 남긴 패키지
    ("scipy", "scipy/iofoo/__init__.py", None),                  # 이름 앞부분만 같은 패키지
    ("scikit-learn", "sklearn/utils/_testing.py", None),         # tests 폴더가 아닌 모듈
    ("scikit-learn", "sklearn/datasets/_base.py", "unused"),
    ("numpy", "numpy/testing/__init__.py", None),
    ("numpy", "numpy/random/LICENSE.md", None),
    ("numpy", "numpy-2.4.6.dist-info/licenses/numpy/_core/include/numpy/LICENSE.txt", None),   # dist-info는 그대로
    ("scipy", "scipy-1.18.0.dist-info/RECORD", None),
    ("pydantic-core", "pydantic_core/_pydantic_core.pyi", "source"),
])
def test_removal_reason(pkg: str, name: str, want: str | None) -> None:
    assert sw.removal_reason(pkg, name) == want


def test_no_prune_keeps_unused_packages() -> None:
    assert sw.removal_reason("scipy", "scipy/io/matlab/_mio.py", prune=False) is None
    assert sw.removal_reason("scipy", "scipy/io/tests/test_x.py", prune=False) == "tests"


def test_safepause_does_not_import_removed_modules() -> None:
    """앱 코드가 scipy·sklearn에서 부르는 모듈이 뺀 패키지·내장 예제 데이터(load_*·fetch_*)에 들지 않는다."""
    removed = [p for v in sw.PRUNE.values() for p in v]
    seen: set[str] = set()
    for path in (ROOT / "safepause").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                seen |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                seen |= {node.module} | {f"{node.module}.{a.name}" for a in node.names}
        text = path.read_text(encoding="utf-8")
        assert "sklearn.datasets" not in text and "fetch_openml" not in text, path
    ours = {m for m in seen if m.split(".")[0] in ("scipy", "sklearn")}
    assert ours, "safepause가 sklearn을 쓰는 곳을 찾지 못함(시험이 낡음)"
    for m in ours:
        assert not any(m == p or m.startswith(p + ".") for p in removed), m


# ---------------------------------------------------------------------------------------------
# 2. 다시 묶기
# ---------------------------------------------------------------------------------------------

SCIPY_FILES = {
    "scipy/__init__.py": b"from . import linalg\n",
    "scipy/linalg/__init__.py": b"x = 1\n",
    "scipy/linalg/_flinalg.cpython-314-wasm32-emscripten.so": b"\x00asm" + bytes(range(200)),
    "scipy/linalg/cython_blas.pxd": b"cdef extern\n",
    "scipy/linalg/tests/test_a.py": b"def test(): pass\n",
    "scipy/linalg/tests/data/a.npz": b"PK" + b"\x01" * 500,
    "scipy/linalg/__init__.pyi": b"x: int\n",
    "scipy.libs/libscipy_openblas.so": b"\x00asm" + b"\x02" * 300,
    "scipy-1.18.0.dist-info/METADATA": b"Name: scipy\n",
    "scipy-1.18.0.dist-info/LICENSE.txt": b"BSD\n",
}
SCIPY_FILES.update({f"{p.replace('.', '/')}/__init__.py": b"# unused\n" for p in sw.PRUNE["scipy"]})


def test_slim_wheel_removes_rewrites_record_and_keeps_bytes(tmp_path: Path) -> None:
    src = make_wheel(tmp_path / "scipy-1.18.0-x.whl", SCIPY_FILES, "scipy-1.18.0")
    dst = tmp_path / "out.whl"
    rep = sw.slim_wheel(src, dst, "scipy", version="1.18.0")
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(dst) as b:
        kept = b.namelist()
        assert "scipy/linalg/tests/test_a.py" not in kept and "scipy/linalg/tests/data/a.npz" not in kept
        assert "scipy/linalg/cython_blas.pxd" not in kept and "scipy/linalg/__init__.pyi" not in kept
        assert not any(n.startswith("scipy/io/") for n in kept)
        assert [n for n in a.namelist() if sw.removal_reason("scipy", n) is None] == kept   # 순서도 그대로
        for n in kept:
            ia, ib = a.getinfo(n), b.getinfo(n)
            assert ia.date_time == ib.date_time and ia.external_attr == ib.external_attr
            if not n.endswith("RECORD"):
                assert a.read(n) == b.read(n)
        record = b.read("scipy-1.18.0.dist-info/RECORD").decode()
        listed = [row[0] for row in csv.reader(io.StringIO(record))]
        assert listed == [n for n in kept]                      # RECORD = 남은 파일(자기 자신 포함)
        old = a.read("scipy-1.18.0.dist-info/RECORD").decode().splitlines()
        assert [ln for ln in old if ln.split(",")[0] in kept] == record.splitlines()   # 남은 줄은 글자 그대로
        assert b.testzip() is None
    assert rep["removed"] == {"tests": 2, "source": 2, "unused": len(sw.PRUNE["scipy"])}
    assert rep["kept"] == len(kept)


def test_slim_wheel_is_deterministic(tmp_path: Path) -> None:
    src = make_wheel(tmp_path / "s.whl", SCIPY_FILES, "scipy-1.18.0")
    sw.slim_wheel(src, tmp_path / "a.whl", "scipy", version="1.18.0")
    sw.slim_wheel(src, tmp_path / "b.whl", "scipy", version="1.18.0")
    assert (tmp_path / "a.whl").read_bytes() == (tmp_path / "b.whl").read_bytes()


def test_slim_wheel_refuses_other_version_or_missing_prune_package(tmp_path: Path) -> None:
    src = make_wheel(tmp_path / "s.whl", SCIPY_FILES, "scipy-1.18.0")
    with pytest.raises(SystemExit, match="PRUNE"):
        sw.slim_wheel(src, tmp_path / "o.whl", "scipy", version="1.19.0")
    sw.slim_wheel(src, tmp_path / "o.whl", "scipy", version="1.19.0", prune=False)   # 안전한 제거만은 판과 무관
    no_io = {k: v for k, v in SCIPY_FILES.items() if not k.startswith("scipy/io/")}
    src2 = make_wheel(tmp_path / "s2.whl", no_io, "scipy-1.18.0")
    with pytest.raises(SystemExit, match="scipy.io"):
        sw.slim_wheel(src2, tmp_path / "o2.whl", "scipy", version="1.18.0")


# ---------------------------------------------------------------------------------------------
# 3. assemble_www: 원본 해시 대조 유지 + 묶음 안 lock의 sha256 = 다시 묶은 wheel의 해시
# ---------------------------------------------------------------------------------------------

def _fake_pyodide(tmp_path: Path) -> Path:
    d = tmp_path / "pyodide"
    d.mkdir()
    for name in aw.CORE_FILES:
        if name != "pyodide-lock.json":
            (d / name).write_bytes(f"// {name}\n".encode())
    for extra in ("LICENSE-pyodide.txt", "LICENSE-cpython.txt"):
        (d / extra).write_text("license\n", encoding="utf-8")
    packages = {}
    for pkg in aw.PACKAGES:
        top = {"scikit-learn": "sklearn", "pydantic-core": "pydantic_core", "typing-extensions": "typing_extensions",
               "annotated-types": "annotated_types", "typing-inspection": "typing_inspection"}.get(pkg, pkg)
        version = sw.PRUNE_FOR.get(pkg, "1.0.0")
        dist = f"{top}-{version}"
        files = SCIPY_FILES if pkg == "scipy" else {f"{top}/__init__.py": b"x = 1\n",
                                                   f"{dist}.dist-info/LICENSE": b"MIT\n"}
        if pkg == "scikit-learn":
            files = {**files, **{f"{p.replace('.', '/')}/__init__.py": b"" for p in sw.PRUNE[pkg]},
                     "sklearn/datasets/data/iris.csv": b"1,2\n", "sklearn/tree/_tree.pyx": b"cdef\n"}
        whl = make_wheel(d / f"{top}-{version}-py3-none-any.whl", files, dist)
        packages[pkg] = {"name": pkg, "version": version, "file_name": whl.name, "sha256": _sha(whl),
                         "install_dir": "site", "depends": [], "imports": [top], "package_type": "package"}
    lock = {"info": {"version": aw.PYODIDE_VERSION, "abi_version": "2026_0"}, "packages": packages}
    (d / "pyodide-lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return d


def test_assemble_slims_and_updates_lock_sha256(tmp_path: Path) -> None:
    pyo = _fake_pyodide(tmp_path)
    lock_before = (pyo / "pyodide-lock.json").read_bytes()
    r = aw.assemble(pyo, tmp_path / "www")
    assert (pyo / "pyodide-lock.json").read_bytes() == lock_before          # 원본 폴더는 그대로
    out_lock_bytes = (tmp_path / "www" / "pyodide" / "pyodide-lock.json").read_bytes()
    out_lock = json.loads(out_lock_bytes)["packages"]
    src_lock = json.loads(lock_before)["packages"]
    assert set(r["slim"]) == {"scipy", "scikit-learn"}
    for pkg in aw.PACKAGES:
        whl = tmp_path / "www" / "pyodide" / out_lock[pkg]["file_name"]
        assert _sha(whl) == out_lock[pkg]["sha256"]                            # Pyodide SRI가 확인하는 값
        if pkg in r["slim"]:
            assert out_lock[pkg]["sha256"] != src_lock[pkg]["sha256"]
        else:
            assert out_lock[pkg]["sha256"] == src_lock[pkg]["sha256"]
            assert whl.read_bytes() == (pyo / whl.name).read_bytes()
    # lock은 sha256 글자만 바뀌고 나머지(줄바꿈·순서·다른 칸)는 그대로
    changed = out_lock_bytes.decode()
    for pkg in r["slim"]:
        changed = changed.replace(out_lock[pkg]["sha256"], src_lock[pkg]["sha256"])
    assert changed.encode() == lock_before
    with zipfile.ZipFile(tmp_path / "www" / "pyodide" / out_lock["scikit-learn"]["file_name"]) as z:
        assert not any(n.startswith(("sklearn/datasets/", "sklearn/neural_network/")) for n in z.namelist())
        assert "sklearn/tree/_tree.pyx" not in z.namelist()
    version = json.loads((tmp_path / "www" / "version.json").read_text(encoding="utf-8"))
    assert set(version["slim"]) == {"scipy", "scikit-learn"}
    assert (tmp_path / "www" / "licenses" / "scipy-1.18.0-LICENSE.txt").is_file()   # 라이선스는 원본 wheel에서


def test_assemble_no_slim_copies_originals(tmp_path: Path) -> None:
    pyo = _fake_pyodide(tmp_path)
    r = aw.assemble(pyo, tmp_path / "www", slim=False)
    assert r["slim"] == {}
    assert (tmp_path / "www" / "pyodide" / "pyodide-lock.json").read_bytes() == (pyo / "pyodide-lock.json").read_bytes()
    lock = json.loads((pyo / "pyodide-lock.json").read_text(encoding="utf-8"))["packages"]
    for pkg in aw.PACKAGES:
        name = lock[pkg]["file_name"]
        assert (tmp_path / "www" / "pyodide" / name).read_bytes() == (pyo / name).read_bytes()


def test_assemble_still_rejects_tampered_original_wheel(tmp_path: Path) -> None:
    pyo = _fake_pyodide(tmp_path)
    lock = json.loads((pyo / "pyodide-lock.json").read_text(encoding="utf-8"))
    whl = pyo / lock["packages"]["numpy"]["file_name"]
    whl.write_bytes(whl.read_bytes() + b"x")
    with pytest.raises(SystemExit, match="해시"):
        aw.assemble(pyo, tmp_path / "www")


# ---------------------------------------------------------------------------------------------
# 4. slim_trace: 기록용 묶음은 복사본에만, 정적 분석(늦은 import·글자·별칭·.so 글자)
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("crlf", [False, True])   # Windows에서 CRLF로 받은 저장소도
def test_trace_copy_patches_only_the_copy(tmp_path: Path, crlf: bool) -> None:
    www = tmp_path / "www"
    shutil.copytree(ROOT / "safepause" / "web", www)
    if crlf:
        worker = www / "engine" / "worker.mjs"
        worker.write_bytes(worker.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    before = (www / "engine" / "worker.mjs").read_bytes()
    st.make_trace_copy(www, tmp_path / "trace")
    assert (www / "engine" / "worker.mjs").read_bytes() == before
    text = (tmp_path / "trace" / "engine" / "worker.mjs").read_text(encoding="utf-8")
    assert "slim-trace" in text and "stderr: (s) => self.__slimErr.push(s)" in text
    assert "slim-trace" not in (ROOT / "safepause" / "web" / "engine" / "worker.mjs").read_text(encoding="utf-8")


def test_py_refs_sees_lazy_imports_strings_and_aliases() -> None:
    src = b'''
"""scipy.docsonly is mentioned only here."""
import scipy.sparse as sp
from . import _base
from ..neighbors import KDTree
import importlib

def f():
    from scipy.signal import medfilt2d
    importlib.import_module("scipy.io")
    importlib.import_module(name)
    return sp.linalg.norm, "sklearn.cluster.KMeans"
'''
    refs, dynamic = st.py_refs(src, "sklearn.ensemble._forest", False)
    assert {"scipy.sparse", "scipy.signal.medfilt2d", "scipy.io", "scipy.sparse.linalg.norm",
            "sklearn.ensemble._base", "sklearn.neighbors.KDTree", "sklearn.cluster.KMeans"} <= refs
    assert not any(r.startswith("scipy.docsonly") for r in refs)          # 설명문은 import가 아님
    assert len(dynamic) == 1 and "import_module(name)" in dynamic[0]
    top_refs, _ = st.py_refs(src, "sklearn.ensemble._forest", False, top_only=True)
    assert "scipy.signal.medfilt2d" not in top_refs and "scipy.sparse" in top_refs


def test_plan_drops_only_unreachable_unused_packages(tmp_path: Path) -> None:
    files = {
        "scipy/__init__.py": b"",
        "scipy/linalg/__init__.py": b"from ._basic import solve\n",
        "scipy/linalg/_basic.py": b"def solve():\n    from scipy.optimize import x\n",   # 늦은 import → 남김
        "scipy/optimize/__init__.py": b"from scipy.integrate import y\n",                 # 남긴 패키지가 부름 → 남김
        "scipy/integrate/__init__.py": b"",
        "scipy/io/__init__.py": b"",                                                     # 아무도 안 부름 → 뺌
        "scipy/io/matlab/__init__.py": b"",
        "scipy/stats/__init__.py": b"from . import _a\n",                                 # 일부만 쓰임 → 남김
        "scipy/stats/_a.py": b"",
        "scipy/stats/_unused_sub/__init__.py": b"",                                      # 하위 패키지만 뺌
        "scipy/special/__init__.py": b"",
        "scipy/special/_u.cpython-314-wasm32-emscripten.so": b"\x00asm..scipy.cluster.vq\x00",   # .so 글자 → 남김
        "scipy/cluster/__init__.py": b"",
    }
    whl = make_wheel(tmp_path / "scipy.whl", files, "scipy-1.18.0")
    used = ["scipy", "scipy.linalg", "scipy.linalg._basic", "scipy.stats", "scipy.stats._a", "scipy.special",
            "scipy.special._u"]
    res = st.plan(used, {"scipy": whl})["packages"]["scipy"]
    assert sorted(res["drop"]) == ["scipy.io", "scipy.stats._unused_sub"]
    assert set(res["kept_by_static"]) == {"scipy.optimize", "scipy.integrate", "scipy.cluster"}
