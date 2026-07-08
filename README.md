# 音乐热度分析系统

基于网易云音乐、QQ 音乐、酷狗音乐公开榜单数据的音乐热度分析与可视化项目。系统聚合三大平台公开榜单、公开互动指标和歌手榜单数据，计算歌曲热度、平台覆盖、飙升趋势、风格分布、歌手热度，并提供前端看板和 FastAPI 接口。

本项目不是任何音乐平台的官方榜单。所有综合分、覆盖率和分析结论都来自本项目的规则计算与数据库记录，只用于数据分析和课程/演示场景。

## 当前结构

```text
music_hot_analysis/
├─ backend/
│  ├─ app/
│  │  ├─ api/routers/        # FastAPI 路由
│  │  ├─ crawlers/           # 网易云、QQ、酷狗采集器
│  │  ├─ db/                 # SQLAlchemy 会话与初始化
│  │  ├─ models/             # 数据库模型
│  │  ├─ repositories/       # 入库逻辑
│  │  ├─ services/           # 热度、分析、采集、AI、流水线服务
│  │  └─ tasks/              # 定时任务
│  ├─ scripts/               # 命令行任务与演示数据导入导出
│  ├─ mysql_schema.sql       # MySQL 表结构
│  └─ requirements.txt
├─ frontend/
│  ├─ index.html
│  ├─ app.js
│  ├─ utils.js
│  └─ styles.css
└─ demo_data/                # 可选演示数据目录
```

## 核心能力

- 三平台歌曲榜单采集：网易云音乐、QQ 音乐、酷狗音乐。
- 三平台歌手榜单/推荐列表采集，用于参考型歌手热度榜。
- 标准歌曲实体合并，保留平台原始歌曲名、歌手名和版本类型。
- 歌曲日榜、周榜、月榜、飙升榜、新歌榜、互动热度榜。
- 平台覆盖、平台相似度、TopN 重合、平台独占歌曲等分析接口。
- 风格分布统计，兼容歌曲风格字段和榜单名称推断。
- AI 总结、歌曲/歌手详情分析和 AI 歌曲搜索接口。
- 演示数据导出/导入脚本，方便迁移和课堂演示。
- 后端直接托管前端静态页，可通过 FastAPI 访问看板。

## 数据范围

- 网易云音乐：热歌榜、新歌榜、飙升榜、原创榜等公开榜单。
- QQ 音乐：热歌榜、新歌榜、飙升榜、流行指数榜等公开榜单。
- 酷狗音乐：TOP500、新歌榜、飙升榜等公开榜单。
- 歌手数据：三平台公开歌手榜单或歌手推荐列表。

系统只处理三大平台公开榜单和公开统计指标，不扩展到三大平台以外的辅助平台，也不做非榜单内容分析。

## 热度口径

歌曲综合热度只使用三大平台主热歌榜数据。采集阶段会尽量抓取播放、收藏、评论等公开互动指标；指标缺失时按可用字段重新分配权重，不把缺失字段直接当作 0 分。

当前日热度计算核心口径：

```text
heat_score =
available_platform_avg_score * 0.75
+ platform_coverage_score * 0.20
+ chart_type_score * 0.05
```

其中：

```text
platform_count = 上榜平台数
platform_coverage_score = platform_count / 3 * 100
available_platform_avg_score = 已上榜平台分数平均值
main_platform_score = 三个平台分数之和 / 3
```

伴奏、Karaoke、Instrumental 等版本会保留在平台歌曲映射中，但不参与歌曲热度贡献。

## 主要接口

默认 API 前缀为 `/api`，可通过 `API_PREFIX` 环境变量调整。

- `GET /health`：健康检查。
- `GET /api/charts/dashboard`：首页汇总数据。
- `GET /api/charts/home`：前端首页聚合数据。
- `GET /api/charts/daily-hot`：歌曲热度日榜。
- `GET /api/charts/weekly-hot`：歌曲热度周榜。
- `GET /api/charts/monthly-hot`：月榜入口，当前复用周榜逻辑。
- `GET /api/charts/rising`：飙升榜。
- `GET /api/charts/new-songs`：三平台合并新歌榜。
- `GET /api/charts/interaction-heat`：互动热度榜。
- `GET /api/charts/platform`：平台原始榜单查询。
- `GET /api/charts/style-buckets`：风格分布。
- `GET /api/songs/search`：歌曲搜索。
- `GET /api/songs/{song_id}`：歌曲详情。
- `GET /api/songs/{song_id}/platform-performance`：歌曲跨平台表现。
- `GET /api/songs/{song_id}/analysis`：歌曲 AI 分析。
- `GET /api/artists/rank`：热门歌手榜。
- `GET /api/artists/{artist_name}`：歌手详情。
- `GET /api/artists/{artist_name}/platform-performance`：歌手跨平台表现。
- `GET /api/artists/{artist_name}/analysis`：歌手 AI 分析。
- `GET /api/analytics/platform-song-counts`：平台歌曲数量。
- `GET /api/analytics/topn-overlap`：TopN 重合。
- `GET /api/analytics/platform-similarity`：平台相似度。
- `GET /api/analytics/coverage-distribution`：覆盖分布。
- `GET /api/analytics/common-songs-summary`：共同上榜歌曲摘要。
- `GET /api/analytics/all-platform-hot-songs`：全平台热门歌曲。
- `GET /api/analytics/song-score-breakdown/{song_id}`：歌曲分数拆解。
- `GET /api/analytics/platform-exclusive-songs`：平台独占歌曲。
- `GET /api/analytics/platform-top-artists`：平台热门歌手。
- `GET /api/analytics/platform-interaction-avg`：平台互动均值。
- `POST /api/crawler/run`：执行歌曲榜单采集。
- `POST /api/crawler/run-artists`：执行歌手榜单采集。
- `POST /api/heat/compute`：计算日热度。
- `GET /api/heat/daily`：查询日热度。
- `POST /api/heat/ai/analyze`：生成每日 AI 总结。
- `POST /api/ai/analyze-song-heat`：歌曲热度 AI 分析。
- `POST /api/ai/analyze-artist-heat`：歌手热度 AI 分析。
- `POST /api/ai/song-search`：AI 歌曲搜索。
- `GET /api/explore/song/search`：探索页歌曲搜索。
- `GET /api/explore/song/ai-analysis`：探索页歌曲分析。
- `GET /api/ops/logs`：ETL 日志。
- `POST /api/ops/run-daily`：执行每日流水线。
- `POST /api/ops/run-backfill`：回填任务。
- `GET /api/ops/ai-status`：AI 配置状态。
- `GET /api/reports/`：AI 报告列表。
- `GET /api/reports/latest`：最新 AI 报告。

## 本地运行

### 1. 准备 Python 环境

```powershell
cd backend
python -m venv ..\venv
..\venv\Scripts\pip install -r requirements.txt
```

### 2. 配置环境变量

后端从 `backend/.env` 读取配置。常用配置如下：

```env
APP_NAME=Music Hot Analysis API
API_PREFIX=/api

MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=music_hot_analysis
MYSQL_USERNAME=root
MYSQL_PASSWORD=
MYSQL_CHARSET=utf8mb4

CRAWLER_TOP_N=100
CRAWLER_TIMEOUT_SECONDS=20
CRAWLER_RETRY_TIMES=2

SCHEDULER_ENABLED=false
SCHEDULER_HOUR=2
SCHEDULER_MINUTE=0
SCHEDULER_TIMEZONE=Asia/Shanghai

AI_ENABLED=false
AI_API_BASE=https://api.openai.com/v1
AI_API_KEY=
AI_MODEL=gpt-4.1-mini
AI_TIMEOUT_SECONDS=30
```

也可以直接设置 `DATABASE_URL` 覆盖 MySQL 分项配置。

### 3. 启动后端和前端

```powershell
cd backend
..\venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

访问：

- 前端看板：`http://127.0.0.1:8000/`
- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

## 常用脚本

以下命令默认在 `backend` 目录执行。

```powershell
# 初始化表结构并采集三平台歌曲榜单
..\venv\Scripts\python scripts\run_crawler.py --platform all --init-db

# 只采集歌手榜
..\venv\Scripts\python scripts\run_crawler.py --platform all --artists-only

# 采集指定平台、指定日期
..\venv\Scripts\python scripts\run_crawler.py --platform qq --date 2026-07-04

# 计算指定日期热度
..\venv\Scripts\python scripts\run_heat_score.py --date 2026-07-04

# 计算热度后生成 AI 总结
..\venv\Scripts\python scripts\run_heat_score.py --date 2026-07-04 --ai

# 执行每日采集 + 热度计算
..\venv\Scripts\python scripts\run_daily_job.py --date 2026-07-04

# 执行每日任务并生成 AI 总结
..\venv\Scripts\python scripts\run_daily_job.py --date 2026-07-04 --with-ai

# 单独生成 AI 日报
..\venv\Scripts\python scripts\run_ai_analysis.py --date 2026-07-04 --limit 20
```

`--limit` 主要用于测试，不建议用于正式演示数据生成，否则日榜、周榜、飙升榜可能不完整。

## 演示数据

项目包含演示数据导入导出脚本，便于把已有 MySQL 数据打包成 JSON，或在新环境中恢复演示数据。

```powershell
cd backend

# 导出到 demo_data/demo_dataset.json
..\venv\Scripts\python scripts\export_demo_data.py

# 导入默认演示数据
..\venv\Scripts\python scripts\import_demo_data.py

# 清空演示表后重新导入
..\venv\Scripts\python scripts\import_demo_data.py --reset
```

带 `--reset` 的导入会清空演示数据涉及的表，使用前请确认目标库是演示库或已备份。

## 前端说明

前端是静态页面，不依赖 Node 构建流程。后端 `app.main` 会直接托管：

- `/` -> `frontend/index.html`
- `/app.js` -> `frontend/app.js`
- `/utils.js` -> `frontend/utils.js`
- `/styles.css` -> `frontend/styles.css`

页面通过 `/api/...` 调用后端接口。

## 注意事项

- 当前数据库结构以 `backend/mysql_schema.sql` 和 SQLAlchemy 模型为准。
- 采集数据来自公开页面和公开接口，字段完整度会受平台页面变化影响。
- AI 能力默认关闭；未配置 `AI_ENABLED=true` 和 `AI_API_KEY` 时，部分分析会使用本地规则或返回未配置状态。
- 定时任务默认关闭；需要自动每日执行时设置 `SCHEDULER_ENABLED=true`。
- 工作区中可能包含运行日志、缓存和演示数据文件，提交前请按实际需要筛选。
