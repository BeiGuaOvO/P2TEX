# -*- coding: utf-8 -*-
"""错题 LaTeX —— 后端（单文件）"""
import asyncio
import base64
import hashlib
import hmac
import io
import json
import os
import sqlite3
import time
import uuid
import shutil
from app.render import render_document
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()                       # 读取 C:\wrongbook\.env

import numpy as np
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from PIL import Image, ImageOps

try:                                # iPhone 的 HEIC 支持
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:
    pass

# ---------------------------------------------------------------- 配置

ROOT = Path(__file__).resolve().parent.parent          # C:\wrongbook
DATA = Path(os.environ.get("DATA_DIR", str(ROOT / "data")))
RAW = DATA / "raw"
THUMB = DATA / "thumb"
DB_PATH = DATA / "app.db"

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash").strip()
PASSWORD = os.environ.get("APP_PASSWORD", "changeme").strip()
AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "true").strip().lower() in (
    "1", "true", "yes", "on")
if not PASSWORD:                      # 密码留空 = 直接关闭验证
    AUTH_ENABLED = False
SECRET = os.environ.get("SESSION_SECRET") or hashlib.sha256(PASSWORD.encode()).hexdigest()
CONCURRENCY = int(os.environ.get("WORKER_CONCURRENCY", "2"))
SEGMENT = os.environ.get("SEGMENT", "false").lower() == "true"
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
MAX_MB = int(os.environ.get("MAX_UPLOAD_MB", "25"))
BACKUP_DIR = DATA / "backups"
KEEP_BACKUPS = 10

# ---------------------------------------------------------------- 数据库


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def q(sql: str, args: tuple = (), one: bool = False):
    """查询"""
    conn = db()
    try:
        cur = conn.execute(sql, args)
        return cur.fetchone() if one else cur.fetchall()
    finally:
        conn.close()


def x(sql: str, args: tuple = ()) -> None:
    """写入"""
    conn = db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    for d in (DATA, RAW, THUMB):
        d.mkdir(parents=True, exist_ok=True)
    x(
        """create table if not exists tasks(
           id text primary key,
           sha256 text unique,
           status text not null,
           latex text default '',
           questions text default '[]',
           error text default '',
           prompt_tokens integer default 0,
           completion_tokens integer default 0,
           created_at real,
           updated_at real)"""
    )


def row_to_dict(r) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["questions"] = json.loads(d.get("questions") or "[]")
    pt = d.get("prompt_tokens") or 0
    ct = d.get("completion_tokens") or 0
    d["est_cost_usd"] = round((pt * 0.15 + ct * 0.60) / 1e6, 6)
    return d

def backup_and_clear() -> tuple[int, str]:
    """先落一份 JSON 备份，再清空记录与图片。返回 (删除条数, 备份文件名)。"""
    rows = q("select * from tasks order by created_at")
    name = ""

    if rows:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        name = f"backup-{time.strftime('%Y%m%d-%H%M%S')}.json"
        payload = []
        for r in rows:
            d = dict(r)
            d["questions"] = json.loads(d.get("questions") or "[]")
            payload.append(d)
        (BACKUP_DIR / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
        olds = sorted(BACKUP_DIR.glob("backup-*.json"))
        for p in olds[:-KEEP_BACKUPS]:
            p.unlink(missing_ok=True)

    x("delete from tasks")
    for d in (RAW, THUMB):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)

    try:
        x("vacuum")            # 回收 sqlite 文件体积
    except Exception:
        pass

    return len(rows), name

def set_task(tid: str, **kw) -> None:
    kw["updated_at"] = time.time()
    cols = ", ".join(f"{k}=?" for k in kw)
    x(f"update tasks set {cols} where id=?", (*kw.values(), tid))


# ---------------------------------------------------------------- 认证


def sess_value() -> str:
    return hmac.new(SECRET.encode(), b"ok", hashlib.sha256).hexdigest()


def authed(req: Request) -> bool:
    if not AUTH_ENABLED:
        return True
    c = req.cookies.get("sess")
    return bool(c) and hmac.compare_digest(c, sess_value())


def require(req: Request) -> None:
    if not authed(req):
        raise HTTPException(401, "unauthorized")


# ---------------------------------------------------------------- 图像处理


def load_image(p: Path) -> Image.Image:
    with Image.open(p) as im:
        return im.convert("RGB")


def normalize_upload(data: bytes) -> tuple[bytes, bytes]:
    """返回 (规范化原图, 缩略图)，顺带剥离 EXIF。"""
    im = Image.open(io.BytesIO(data))
    im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((2400, 2400), Image.LANCZOS)

    def enc(img: Image.Image, edge: int, quality: int) -> bytes:
        t = img.copy()
        t.thumbnail((edge, edge), Image.LANCZOS)
        b = io.BytesIO()
        t.save(b, "JPEG", quality=quality, optimize=True)
        return b.getvalue()

    return enc(im, 2400, 92), enc(im, 900, 80)


def to_model_jpeg(im: Image.Image, max_edge: int = 1600, quality: int = 90) -> bytes:
    w, h = im.size
    if max(w, h) > max_edge:
        s = max_edge / max(w, h)
        im = im.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, "JPEG", quality=quality, optimize=True)
    return b.getvalue()


def segment(im: Image.Image, gap_ratio: float = 0.012, pad: int = 12) -> list:
    """按行投影的空白间隙切题块（纯 numpy）。"""
    g = np.asarray(im.convert("L"), dtype=np.uint8)
    thr = max(110, int(np.percentile(g, 85)) - 40)
    ink = (g < thr).sum(axis=1)
    h, w = g.shape
    min_ink = max(2, int(0.002 * w))
    need_gap = max(8, int(gap_ratio * h))

    blocks, start, gap = [], None, 0
    for y, v in enumerate(ink):
        if v > min_ink:
            if start is None:
                start = y
            gap = 0
        elif start is not None:
            gap += 1
            if gap >= need_gap:
                blocks.append((start, y - gap))
                start, gap = None, 0
    if start is not None:
        blocks.append((start, h - 1))

    out = [
        im.crop((0, max(0, y0 - pad), w, min(h, y1 + pad)))
        for y0, y1 in blocks
        if y1 - y0 >= 15
    ]
    return out or [im]


# ---------------------------------------------------------------- 模型调用

SYSTEM_PROMPT = r"""你是理科试卷题目转录器，只做忠实转写：不解题、不判对错、不改写、不补全。

规则：
1. 只输出题目本身。学生的作答与演算、老师打的勾叉/圈划/批注/扣分，一律不得进入任何 LaTeX 字段。
2. 行内公式用 $...$，独立公式用 $$...$$，多行用 \begin{aligned}...\end{aligned}。
3. 化学方程式用 \ce{...}；物理量带单位时写 $9.8\,\mathrm{m/s^2}$；角度写 $30^{\circ}$。
4. 只允许标准宏包命令，禁止自定义宏、禁止 \newcommand。
5. 无法辨认的字符写 \square，并在 uncertain 中说明位置与原因，严禁按题意推测。
6. 图形不要用文字描述替代题目内容，只记入 figures（bbox 归一化，仅作参考）。
7. options 的 latex 只写选项内容，不要带 A. B. C. D. 之类标签。
8. 填空题的横线统一写成 \blank{n}，n 为横线宽度（单位 em，一般 3–10，
   按原图横线长度估算）。不要用 \underline、不要用一串下划线。
9. 解答题（无选项的题）额外输出 "answer_lines": 整数，
   表示作答需要多少行（一般 8–20，看原图留白多少）。

只输出 JSON，格式：
{"questions":[{"number":"12","stem_latex":"...",
"sub_questions":[{"label":"(1)","latex":"..."}],
"options":[{"label":"A","latex":"..."}],
"figures":[{"bbox":[0.1,0.2,0.5,0.6],"kind":"geometry|circuit|chart|chem|table|other"}],
"uncertain":["..."]}]}
无题目时返回 {"questions": []}。"""

_client = None


def get_client() -> OpenAI:
    global _client
    if not API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY 未设置，请检查 C:\\wrongbook\\.env")
    if _client is None:
        _client = OpenAI(
            api_key=API_KEY,
            base_url="https://api.deepseek.com",
            timeout=180,
            max_retries=0,
        )
    return _client


def call_model(jpeg: bytes) -> tuple:
    client = get_client()
    b64 = base64.b64encode(jpeg).decode()
    last = None
    for attempt in range(3):
        try:
            r = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": SYSTEM_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                            },
                        ],
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=8000,
                extra_body={"thinking": {"type": "disabled"}},
            )
            txt = (r.choices[0].message.content or "{}").strip()
            if txt.startswith("```"):
                txt = txt.split("\n", 1)[-1].rsplit("```", 1)[0]
            u = r.usage
            return (
                json.loads(txt),
                getattr(u, "prompt_tokens", 0) or 0,
                getattr(u, "completion_tokens", 0) or 0,
            )
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last if last else RuntimeError("unknown error")


def compose_latex(questions: list) -> str:
    out = []
    for qn in questions:
        num = str(qn.get("number") or "").strip()
        out.append(f"% ===== 第 {num} 题 =====" if num else "% =====")
        if qn.get("stem_latex"):
            out.append(str(qn["stem_latex"]).strip())
        for o in qn.get("options") or []:
            out.append(f"{o.get('label', '')} {o.get('latex', '')}".strip())
        for s in qn.get("sub_questions") or []:
            out.append(f"{s.get('label', '')} {s.get('latex', '')}".strip())
        if qn.get("uncertain"):
            out.append("% TODO 待确认：" + "；".join(map(str, qn["uncertain"])))
        out.append("")
    return "\n".join(out).strip()


# ---------------------------------------------------------------- 队列


queue: asyncio.Queue = asyncio.Queue()


async def process(tid: str) -> None:
    set_task(tid, status="running", error="")
    try:
        raw = RAW / f"{tid}.jpg"
        im = await asyncio.to_thread(load_image, raw)
        blocks = await asyncio.to_thread(segment, im) if SEGMENT else [im]

        questions, pt, ct = [], 0, 0
        for b in blocks:
            jpeg = await asyncio.to_thread(to_model_jpeg, b)
            data, p, c = await asyncio.to_thread(call_model, jpeg)
            questions.extend(data.get("questions") or [])
            pt += p
            ct += c

        set_task(
            tid,
            status="done",
            latex=compose_latex(questions),
            questions=json.dumps(questions, ensure_ascii=False),
            prompt_tokens=pt,
            completion_tokens=ct,
        )
    except Exception as e:
        set_task(tid, status="failed", error=str(e)[:800])


async def worker() -> None:
    while True:
        tid = await queue.get()
        try:
            await process(tid)
        finally:
            queue.task_done()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    x("update tasks set status='queued' where status in ('queued','running')")
    for r in q("select id from tasks where status='queued'"):
        queue.put_nowait(r["id"])
    workers = [asyncio.create_task(worker()) for _ in range(max(1, CONCURRENCY))]
    yield
    for w in workers:
        w.cancel()


app = FastAPI(lifespan=lifespan)
@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


# ---------------------------------------------------------------- 路由


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.post("/api/login")
async def login(req: Request):
    if not AUTH_ENABLED:
        return {"ok": True, "auth": False}
    body = await req.json()
    if not hmac.compare_digest(str(body.get("password", "")), PASSWORD):
        raise HTTPException(401, "密码错误")
    resp = Response(
        json.dumps({"ok": True, "auth": True}), media_type="application/json")
    resp.set_cookie(
        "sess",
        sess_value(),
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=180 * 24 * 3600,
    )
    return resp


@app.post("/api/logout")
async def logout():
    resp = Response(json.dumps({"ok": True}), media_type="application/json")
    resp.delete_cookie("sess")
    return resp

@app.get("/api/config")
async def app_config():
    """告诉前端是否需要登录。不含任何敏感信息。"""
    return {"auth": AUTH_ENABLED}

@app.get("/api/me")
async def me(req: Request):
    return {"authed": authed(req)}


@app.post("/api/uploads")
async def upload(req: Request, file: UploadFile):
    require(req)
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "空文件")
    if len(blob) > MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"超过 {MAX_MB} MB")

    sha = hashlib.sha256(blob).hexdigest()
    dup = q("select id from tasks where sha256=?", (sha,), one=True)
    if dup:
        return {"id": dup["id"], "cached": True}

    try:
        full, thumb = await asyncio.to_thread(normalize_upload, blob)
    except Exception:
        raise HTTPException(415, "无法识别的图片格式")

    tid = uuid.uuid4().hex
    (RAW / f"{tid}.jpg").write_bytes(full)
    (THUMB / f"{tid}.jpg").write_bytes(thumb)

    now = time.time()
    x(
        "insert into tasks(id,sha256,status,created_at,updated_at) "
        "values(?,?,'queued',?,?)",
        (tid, sha, now, now),
    )
    queue.put_nowait(tid)
    return {"id": tid, "cached": False}


@app.get("/api/tasks")
async def list_tasks(req: Request, limit: int = 100):
    require(req)
    rows = q("select * from tasks order by created_at desc limit ?", (limit,))
    return [row_to_dict(r) for r in rows]


@app.get("/api/tasks/{tid}")
async def get_task(req: Request, tid: str):
    require(req)
    d = row_to_dict(q("select * from tasks where id=?", (tid,), one=True))
    if not d:
        raise HTTPException(404)
    return d


@app.get("/api/tasks/{tid}/thumb")
async def get_thumb(req: Request, tid: str):
    require(req)
    p = THUMB / f"{tid}.jpg"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg")


@app.get("/api/tasks/{tid}/raw")
async def get_raw(req: Request, tid: str):
    require(req)
    p = RAW / f"{tid}.jpg"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg")


@app.patch("/api/tasks/{tid}")
async def edit_task(req: Request, tid: str):
    require(req)
    body = await req.json()
    if "latex" not in body:
        raise HTTPException(400, "缺少 latex")
    if not q("select id from tasks where id=?", (tid,), one=True):
        raise HTTPException(404)
    set_task(tid, latex=str(body["latex"]))
    return {"ok": True}

@app.delete("/api/tasks")
async def clear_tasks(req: Request):
    require(req)

    # 取消还在排队的任务，避免清空后又冒出新结果
    while True:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break

    deleted, backup = await asyncio.to_thread(backup_and_clear)
    return {"deleted": deleted, "backup": backup}

@app.delete("/api/tasks/{tid}")
async def del_task(req: Request, tid: str):
    require(req)
    x("delete from tasks where id=?", (tid,))
    (RAW / f"{tid}.jpg").unlink(missing_ok=True)
    (THUMB / f"{tid}.jpg").unlink(missing_ok=True)
    return {"ok": True}

@app.get("/api/export/paper.tex")
async def export_paper(req: Request):
    require(req)
    rows = q("select questions from tasks where status='done' order by created_at")
    allq = []
    for r in rows:
        allq.extend(json.loads(r["questions"] or "[]"))
    tex = render_document(allq, title="错题本")
    return PlainTextResponse(tex, headers={
        "Content-Disposition": 'attachment; filename="cuoti.tex"'})