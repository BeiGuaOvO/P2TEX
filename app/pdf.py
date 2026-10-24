import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent       # app/
_DATA_HOME = _HERE.parent / "data"            # C:\wrongbook\data
FIG_DIR = Path(os.environ.get("FIG_DIR") or (_DATA_HOME / "figs"))
CACHE_DIR = Path(os.environ.get("PDF_CACHE_DIR") or (_DATA_HOME / "pdf"))

FIG_RE = re.compile(r"figs/([\w.\-]+\.(?:jpg|jpeg|png))")

DANGEROUS = re.compile(
    r"\\(?:input|include|openin|openout|read|readline|write18|"
    r"immediate|special|catcode|csname|endcsname|loop|directlua|"
    r"write|newwrite|closeout)\b")

def assert_safe(tex: str) -> None:
    m = DANGEROUS.search(tex)
    if m:
        raise RuntimeError(
            f"文档包含不安全的命令 \\{m.group(0)[1:]}，已拒绝编译。"
            "请检查题目内容是否包含异常的 LaTeX 代码。")

def cache_key(tex: str) -> str:
    """tex 内容 + 引用图片的尺寸/mtime → 缓存键。"""
    h = hashlib.sha256(tex.encode("utf-8"))
    h.update(b"|v1|")
    for name in sorted(set(FIG_RE.findall(tex))):
        p = FIG_DIR / name
        if p.exists():
            st = p.stat()
            h.update(f"{name}:{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()[:24]


def extract_error(log: str) -> str:
    lines = log.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("!"):
            chunk = [ln] + lines[i + 1:i + 6]
            return " | ".join(x.strip() for x in chunk if x.strip())[:600]
    for i, ln in enumerate(lines):
        if "LaTeX Error" in ln or "Fatal error" in ln:
            return " | ".join(x.strip() for x in lines[i:i + 4])[:600]
    return (log.strip()[-600:] or "编译失败，未提取到错误信息")
def compile_pdf(tex: str, timeout: int = 120) -> bytes:
    """编译 tex，返回 PDF 字节。命中缓存直接返回。"""
    assert_safe(tex)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = cache_key(tex)
    cached = CACHE_DIR / f"{key}.pdf"
    if cached.exists() and cached.stat().st_size > 0:
        return cached.read_bytes()

    with tempfile.TemporaryDirectory(prefix="tex-") as td:
        d = Path(td)
        (d / "cuoti.tex").write_text(tex, encoding="utf-8")

        # 只复制被引用的图片，保持 figs/ 相对路径
        names = set(FIG_RE.findall(tex))
        if names:
            (d / "figs").mkdir(exist_ok=True)
            for name in names:
                src = FIG_DIR / name
                if src.exists():
                    shutil.copy2(src, d / "figs" / name)

        env = dict(os.environ)
        env.pop("TEXINPUTS", None)
        env.pop("TEXMFHOME", None)
        # TeX Live 的 paranoid 模式：只允许读写当前目录
        env["openin_any"] = "p"
        env["openout_any"] = "p"
        env["SOURCE_DATE_EPOCH"] = "0"
        env["FORCE_SOURCE_DATE"] = "1"

        cmd = [
            "xelatex",
            "-no-shell-escape",      # 禁止 \write18 执行命令
            "-interaction=nonstopmode",
            "-halt-on-error",
            "cuoti.tex",
        ]
        try:
            p = subprocess.run(cmd, cwd=str(d), capture_output=True,
                               timeout=timeout, env=env)
        except FileNotFoundError:
            raise RuntimeError("未找到 xelatex，请安装 TeX 发行版（MiKTeX 或 TeX Live）")
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"编译超时（>{timeout}s），文档可能过大或死循环")

        pdf = d / "cuoti.pdf"
        if p.returncode != 0 or not pdf.exists():
            log = (p.stdout or b"").decode("utf-8", "replace")
            log += (p.stderr or b"").decode("utf-8", "replace")
            raise RuntimeError(extract_error(log))

        data = pdf.read_bytes()
        if len(data) < 1000:
            raise RuntimeError("生成的 PDF 异常偏小，可能编译不完整")

    try:
        cached.write_bytes(data)
    except OSError:
        pass
    return data
