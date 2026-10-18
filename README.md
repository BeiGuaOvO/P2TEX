# 错题 LaTeX

拍照上传理科错题，调用 DeepSeek 视觉模型转写为 LaTeX，按试卷格式导出为可编译的 `.tex`。

## 功能

- **拍照 / 选图上传** —— 手机直接调起相机，桌面可选文件；上传前可手动裁剪
- **忠实转写** —— 只转录题干，不解题、不判对错；学生作答与老师批改不混入题目
- **试卷排版导出** —— 选项自动编号为 A/B/C/D，填空自动生成横线，解答题自动留出订正空白
- **结果管理** —— 逐条保存，支持编辑、复制、删除，一键清空并自动备份
- **去重** —— 同一张图按 sha256 命中缓存，不重复消耗 token

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | FastAPI + SQLite（单文件，无 ORM） |
| 前端 | 原生 HTML / CSS / JS，无构建步骤 |
| 模型 | DeepSeek `deepseek-flash`（唯一支持图片输入的模型） |
| 导出 | LaTeX `ctexart` + `mhchem`，用 XeLaTeX 编译 |

## 环境要求

- Python **3.10+**
- 编译导出结果需要 TeX 发行版：MiKTeX 或 TeX Live，**推荐 XeLaTeX**
- DeepSeek API Key：在 <https://platform.deepseek.com> 申请

## 安装

```powershell
git clone https://github.com/<you>/<repo>.git
cd <repo>

python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 国内网络建议先换源
pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
pip install -r requirements.txt

copy .env.example .env
```

编辑 `.env`，至少填 `DEEPSEEK_API_KEY`。

## 运行

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

打开 <http://localhost:8000>。

局域网内用手机访问：先 `ipconfig` 查本机 IPv4，然后手机访问
`http://<IPv4>:8000`。若打不开，在管理员 PowerShell 放行端口：

```powershell
New-NetFirewallRule -DisplayName "Wrongbook 8000" -Direction Inbound `
  -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private
```

## 配置

全部通过 `.env` 控制，改完需重启服务。

| 变量 | 默认 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | **必填** |
| `DEEPSEEK_MODEL` | `deepseek-flash` | 只有该模型支持图片输入 |
| `APP_PASSWORD` | `changeme` | 访问密码；**留空则自动关闭验证** |
| `AUTH_ENABLED` | `true` | 设为 `false` 可关闭密码验证 |
| `WORKER_CONCURRENCY` | `2` | 并发处理数 |
| `MAX_UPLOAD_MB` | `25` | 单张上传上限 |
| `SEGMENT` | `false` | 开启后先按行间隙切题块，再逐块识别 |
| `COOKIE_SECURE` | `false` | 本地 http 必须为 `false`，否则无法登录 |

> ⚠️ 关闭验证后，同一局域网内任何人都能看到、上传甚至清空数据。
> 只在可信网络下使用；单机使用可改为 `--host 127.0.0.1` 仅监听本机。

## 使用流程

```
拍照 / 选图 → 裁剪（可跳过）→ 等待识别 → 复制或留在服务器
                                            ↓
                             导出 .tex → 用 XeLaTeX 编译
                                            ↓
                                     清空全部（自动备份）
```

### 导出与编译

点「导出 .tex」会下载一份完整文档，包含已转义题目、选项编号、填空横线与订正留白：

```powershell
xelatex cuoti.tex
```

编辑 `app/render.py` 可调整排版：

| 想改什么 | 位置 |
|---|---|
| 横线样式 | 导言区里的 `\fillblank` 定义 |
| 订正空白（是否画横线） | `\answerspace` 定义 |
| 空白行数 | `answer_lines()` 里的公式 |
| 选项单栏 / 双栏 | `render_question()` 中的选项段 |

## 数据与备份

所有数据集中在 `data/`：

```
data/
├── app.db          SQLite：任务记录与 LaTeX
├── raw/            规范化原图（JPEG，已剥离 EXIF）
├── thumb/          列表缩略图
└── backups/        清空前自动生成的 JSON 快照（保留最近 10 份）
```

备份整个目录即可：

```powershell
tar -czf "backup-$(Get-Date -Format yyyyMMdd).tar.gz" data
```

`data/`、`.env`、`.venv/` 均已写入 `.gitignore`，不会进入版本库。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/config` | 是否启用验证（无需登录） |
| `POST` | `/api/login` | 登录，成功后写入 Cookie |
| `POST` | `/api/logout` | 退出 |
| `POST` | `/api/preview` | 任意图片转 JPEG，供前端裁剪，不落盘 |
| `POST` | `/api/uploads` | 上传，返回 `{id}`；图片相同则返回已有 id |
| `GET` | `/api/tasks` | 任务列表（含状态、LaTeX、token 用量） |
| `GET` | `/api/tasks/{id}` | 单条详情 |
| `PATCH` | `/api/tasks/{id}` | 修改该条的 LaTeX |
| `DELETE` | `/api/tasks/{id}` | 删除单条及图片 |
| `DELETE` | `/api/tasks` | **清空全部**，删除前自动写 JSON 备份 |
| `GET` | `/api/export/paper.tex` | 导出为可编译的试卷文档 |

## 目录结构

```
app/
├── main.py         后端：路由、队列、图像预处理、模型调用
└── render.py       渲染器：题目 JSON → LaTeX 文档
static/
├── index.html      页面结构
├── style.css       样式
├── app.js          上传、列表、轮询、清空
└── crop.js         触摸/鼠标裁剪层
data/               运行时生成，不入库
```

## 已知限制

- **PDF 不能直接上传**，需先转成图片
- 透明 PNG 会被合到白底（已处理，不会变黑）
- 图形仅记录位置描述，导出时不含配图
- 手写笔迹、红笔批改的剥离依赖模型判断，密集涂改处可能残留
- `deepseek-flash` 是唯一支持图片输入的模型，`deepseek-v4-pro` 仅可处理纯文本

## 故障排查

| 现象 | 处理 |
|---|---|
| 页面空白 | 检查 `static/` 下三个文件是否完整；F12 看 Console |
| 一直弹登录框 | `.env` 里 `COOKIE_SECURE` 必须为 `false` |
| 上传后停在「排队」 | 看 uvicorn 窗口报错，多为 API Key 问题 |
| 手机无裁剪框 | iOS 的 HEIC 需服务端解码，确认 `/api/preview` 可用 |
| 改完前端不生效 | `index.html` 里把 `?v=` 号加一，并强刷 |
| 导出编译报错 | 必须用 XeLaTeX，且 `ctexart` 需要中文字体 |

## License

个人项目，未指定许可证。