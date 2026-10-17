# 错题 LaTeX

拍照上传理科错题，调用 DeepSeek 转录为 LaTeX，结果保存在本地。

## 功能

- 浏览器拍照/选图上传，手机与桌面通用
- DeepSeek 视觉模型把题目转写为 LaTeX（只转写，不解题）
- 结果逐条保存，支持编辑、复制、删除、导出 `.tex`
- 同一张图按 sha256 去重，不重复消耗 token

## 运行（Windows 10）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

copy .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY 和 APP_PASSWORD

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

打开 http://localhost:8000

## 目录

```
app/main.py     后端（FastAPI + SQLite）
static/         前端（HTML / CSS / JS，无构建步骤）
data/           运行时生成：数据库 + 原图（不入库）
```

## 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | 必填 |
| `APP_PASSWORD` | changeme | 访问密码 |
| `SEGMENT` | false | 开启后先切题块再逐块识别 |
| `WORKER_CONCURRENCY` | 2 | 并发处理数 |

需 Python 3.10+。数据全在 `data/`，备份打包它即可。