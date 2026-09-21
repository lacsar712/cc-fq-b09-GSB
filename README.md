# FASTQ 质控流水线台（FASTQ QC Pipeline Console）

从零实现的全栈演示：上传/选择小型 FASTQ → **Actor 队列流水线**质控 → 查看阶段状态与指标。

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
3. 作业详情页看到四个 Actor 阶段均为成功，指标卡出现 `reads` / `mean_quality` / `n_rate` / `弱位点数`。
4. 详情页下方出现 **per_position 平均质量曲线**（蓝线）与 **弱位点清单**：
   - 弱位点由**服务端**按「平均质量下限」算出并写入 `metrics.weak_positions`，前端只读展示，不自行扫描；
   - 默认阈值 30（可用环境变量 `WEAK_QUALITY_THRESHOLD` 改默认值），合格样例默认无弱位点。
5. **运维调阈值自测**：详情页输入更高阈值（如 `41`）→ **保存阈值** → **重算弱位点** → 清单变非空，且全部满足 `mean_quality < 阈值`；重跑新作业也会按新阈值计算。
6. 再跑损坏样例：`ParseActor` = failed，其余 = skipped；曲线与弱位点区域提示「无 per_position 数据」，重算按钮不可用（接口返回 409）。
7. 退出，用 `auditor` / `audit123456` 登录：可看历史、详情、曲线与弱位点清单，但无阈值编辑/重算入口；直接调用 `PUT /api/config/weak-threshold` 或 `POST /api/jobs/{id}/recompute-weak` 返回 403。
8. 健康检查：`curl http://localhost:8184/api/health`

## API

- `POST /api/auth/login`
- `GET  /api/health`
- `GET  /api/samples`
- `POST /api/jobs` `{ "sampleId": 1 }` 或 `{ "fastqText": "..." }`
- `GET  /api/jobs`
- `GET  /api/jobs/{id}`
- `GET  /api/jobs/{id}/stages`
- `GET  /api/config/weak-threshold`（登录即可读，含审计员）
- `PUT  /api/config/weak-threshold` `{ "threshold": 41.0 }`（仅 bioops，范围 0–93，落 `app_settings` 表）
- `POST /api/jobs/{id}/recompute-weak`（仅 bioops；仅成功作业，按当前阈值重算 `weak_positions` 写回 metrics）

阈值生效顺序：`app_settings` 表（运维运行时修改）> 环境变量 `WEAK_QUALITY_THRESHOLD` > 内置默认 30。

## 本地单测（可选）

```bash
cd backend
pip install -r requirements.txt
pytest -q
```

覆盖：畸形 FASTQ 在 `ParseActor` 失败；正常样例产出 `mean_quality`；弱位点阈值规则、
调阈值后重算非空且一致（SQLite 端到端）；审计员改阈值/重算 403；失败作业重算 409。

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
      config.py settings_store.py
      pipeline/{actors,runner}.py
    tests/{test_actors,test_weak_api}.py
  frontend/
    Dockerfile nginx.conf
    src/pages/{Login,Samples,JobSubmit,JobDetail,JobHistory}Page.vue
    src/components/QualityCurve.vue
```
