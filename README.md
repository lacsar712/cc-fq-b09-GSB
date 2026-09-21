# FASTQ 质控流水线台（FASTQ QC Pipeline Console）

从零实现的全栈演示：上传/选择小型 FASTQ → **Actor 队列流水线**质控 → 查看阶段状态、逐位点质量曲线与**弱位点清单**。

弱位点（位点平均质量 < 可配置下限）一律**由服务端按阈值算出**并随指标持久化，前端只负责展示，不自行扫描。

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11 · FastAPI · SQLAlchemy · PostgreSQL |
| 流水线 | `ParseActor` → `QualityHistActor` → `NContentActor` → `ReportActor`（asyncio.Queue） |
| 前端 | Vue 3 · Vite · Quasar · 中文 UI · nginx `/api` 反代 |
| 基建 | docker compose（db / backend / seed / frontend） |

## 端口

| 服务 | 地址 |
|------|------|
| Frontend | http://localhost:3184 |
| Backend API | http://localhost:8184 |
| PostgreSQL | localhost:54384 |

## 账号

| 用户 | 密码 | 权限 |
|------|------|------|
| `bioops` | `fastq123456` | 可提交质控作业 |
| `auditor` | `audit123456` | 只读结果，不可提交 |

## 一键启动

```bash
cd projects/09-fastq-qc-pipeline
docker compose up --build
```

镜像源：Postgres/Node/Nginx 使用 `docker.m.daocloud.io`；npm 使用 `registry.npmmirror.com`；pip 使用清华源。

启动后 seed 会写入：

- `demo-good-r1`：合格样例（可算出 `mean_quality` / `n_rate`）
- `demo-broken-malformed`：损坏样例（`ParseActor` 失败，后续阶段 skipped）

## Verification（验收）

1. 打开 http://localhost:3184 ，用 `bioops` / `fastq123456` 登录。
2. **样例库** 看到 2 条样例 → 选合格样例 **提交质控作业**。
3. 作业详情页看到四个 Actor 阶段均为成功，指标卡出现 `reads` / `mean_quality` / `n_rate`。
4. 再跑损坏样例：`ParseActor` = failed，其余 = skipped；详情页质量曲线区提示无 per_position 数据。
5. 退出，用 `auditor` / `audit123456` 登录：可看历史、曲线与弱位点清单，提交作业/改阈值/重算接口返回 403，前端无对应入口。
6. 弱位点自测（bioops）：作业详情点 **配置下限**，把下限调到高于部分位点（如 39.7）保存，再点 **按当前阈值重算清单** → 弱位点清单非空，且每个位点质量严格低于阈值。
7. 健康检查：`curl http://localhost:8184/api/health`

## API

- `POST /api/auth/login`
- `GET  /api/health`
- `GET  /api/samples`
- `POST /api/jobs` `{ "sampleId": 1 }` 或 `{ "fastqText": "..." }`
- `GET  /api/jobs`
- `GET  /api/jobs/{id}`
- `GET  /api/jobs/{id}/stages`
- `GET  /api/quality-config` — 当前弱位点平均质量下限（两种角色均可读）
- `PUT  /api/quality-config` `{ "weak_quality_floor": 39.7, "apply_to_successful_jobs": false }` — **仅运维（bioops）**，持久化并可批量重算历史成功作业
- `POST /api/jobs/{id}/recompute-weak` — **仅运维（bioops）**，对已成功作业按当前阈值重算 `weak_positions`（不重跑流水线）；失败作业无 `per_position` 返回 409

## 弱位点（weak_positions）规则与迭代约定

- 判定规则：`per_position[].mean_quality < weak_quality_floor`（严格小于；等于阈值不算）。
- 成功结束时由 `QualityHistActor` 按当时阈值算出 `weak_positions` 写入 `metrics`（同时记录所用 `weak_quality_floor`，并同步进 `report`/`summary`）。
- 阈值运维可改：`PUT /api/quality-config` 持久化到 `app_settings` 表（初始默认 28，可用环境变量 `WEAK_QUALITY_FLOOR` 覆盖）；改后新作业自动采用。
- 历史作业两条更新路径：单作业 `POST /api/jobs/{id}/recompute-weak`，或保存配置时带 `apply_to_successful_jobs: true` 批量重算。
- 失败作业没有 `per_position`，详情页提示无数据，重算接口 409；前端不自行扫描冒充清单。
- 审计员（auditor）可看曲线与清单，改阈值/重算接口返回 403，前端也不提供入口。

## 本地单测（可选）

```bash
cd backend
pip install -r requirements.txt
pytest -q
```

覆盖：畸形 FASTQ 在 `ParseActor` 失败；正常样例产出 `mean_quality`；弱位点阈值规则、调高阈值重算、审计员 403、失败作业无数据分支（共 17 个用例）。

## 目录结构

```
09-fastq-qc-pipeline/
  PRD.md
  README.md
  docker-compose.yml
  backend/
    Dockerfile
    seed.py
    data/{good,broken}.fastq
    app/
      main.py api.py auth.py models.py schemas.py
      config.py settings_service.py
      pipeline/{actors,runner}.py
    tests/{conftest,test_actors,test_weak_positions,test_api_weak}.py
  frontend/
    Dockerfile nginx.conf
    src/components/QualityCurveChart.vue
    src/pages/{Login,Samples,JobSubmit,JobDetail,JobHistory}Page.vue
```
