# 知库 · 基于 OceanBase seekdb 的个人知识检索助手

> 面向学习、科研与工作场景：把课程笔记、文献摘要、周报、会议纪要沉淀到本地知识库，
> 提供关键词全文检索、语义向量检索与混合检索（RRF 融合），让资料「一搜即得」。

本项目是 OceanBase 大赛 Qoder 赛道交付作品：**使用 Qoder 开发**，**实际接入 seekdb** 实现核心检索功能，项目展示站**通过 Qoder Sites 发布**。

## 一、题目要求对照

| 题目要求 | 本项目落地方式 |
| --- | --- |
| 使用 Qoder 开发 | 在 Qoder 桌面端 / IDE / 插件 / CLI 中打开本目录，由 Agent 迭代生成并 Accept 改动；保留 `.qoder/rules` 规则、提交历史与开发记录（见 `docs/qoder-dev-log.md`） |
| 实际使用 seekdb / PowerContext 至少一种 | 核心检索由 `src/repository.py` 调用 seekdb 高层 SDK `pyseekdb` 完成：写入 upsert、向量 HNSW 近邻、全文包含匹配、hybrid_search + RRF 融合、元数据过滤、删除，均可在 `scripts/selftest.py` 复现 |
| 项目网站通过 Qoder Sites 发布 | `site/index.html` 为单文件静态演示站素材，在 Qoder 中用 `@sites` 生成、预览并以「任何人都可访问」公开发布 |
| 围绕工作提效 / 学习科研 | 三类样例数据：学习（课程笔记、复习要点）、科研（论文摘要、实验记录）、工作（周报、会议纪要） |

## 二、功能

- **条目管理**：新增 / 批量导入 / 列表 / 按类别过滤 / 删除 / 计数。
- **三种检索**
  - 全文检索：标题 + 正文 + 标签的关键词包含匹配；
  - 向量检索：内置离线向量器生成 256 维向量，HNSW + 余弦最近邻；
  - 混合检索：全文支路与向量支路并行，RRF 倒数排名融合重排。
- **元数据过滤**：按类别（study / research / work / general）过滤。
- **命令行 + 可选本地 Web API + Qoder Sites 静态演示站**三种形态。

## 三、技术栈与版本

| 项 | 版本 / 说明 |
| --- | --- |
| 语言 | Python 3.11+（推荐 3.12） |
| 检索引擎 | OceanBase seekdb，嵌入式本地库；高层 SDK `pyseekdb==1.4.0.post1`（自动携带底层 `pylibseekdb`） |
| 可选 Web | FastAPI + Uvicorn（本地演示，非发布必需） |
| 演示站 | 纯静态 HTML/CSS/JS，零外部依赖 |
| 支持平台 | Linux x86_64/aarch64（glibc ≥ 2.28）、macOS arm64 ≥ 15.6；Windows 嵌入式 seekdb 暂不可用，备选见 `docs/submit-guide.md` |

## 四、在赛事仓库中的位置

基于官方赛事分支 `2026-competition-ecosystem` 开发，项目资产放入仓库的 `qoder/` 目录：

```
<赛事仓库根>/
├── dify/.gitkeep
├── gaode/.gitkeep
├── minimax/.gitkeep
├── qoder/
│   └── knowledge-base/        # ← 本项目整体放在这里
│       ├── README.md
│       ├── requirements.txt
│       ├── .qoder/rules/project-rules.md
│       ├── data/sample_notes.json
│       ├── src/...
│       ├── scripts/selftest.py
│       ├── site/index.html
│       └── docs/...
└── stepfun/.gitkeep
```

## 五、本地运行（完整步骤）

### 1. 建虚拟环境并安装依赖

```bash
cd qoder/knowledge-base
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 导入样例数据

```bash
python -m src.cli ingest           # 导入 7 条样例
python -m src.cli count             # 预期：当前共 7 条
```

### 3. 体验检索

```bash
# 混合检索（默认）
python -m src.cli search "向量和关键词怎么结合检索"

# 仅语义向量检索
python -m src.cli search "补码 溢出判断" --mode vector

# 仅全文检索
python -m src.cli search "周报" --mode fulltext

# 按类别列出工作类条目
python -m src.cli list --category work

# 新增一条
python -m src.cli add --title "会议纪要：..." --content "..." --category work --tags 复盘,待办
```

数据库目录默认 `./data/seekdb.db`，可用环境变量 `SEEKDB_PATH` 覆盖。

### 4. 运行自测

```bash
python scripts/selftest.py
```

全部断言通过时输出 `全部通过 ✅`，退出码为 0。逐条样例与预期结果见 `docs/validation-sample.md`。

### 5. 可选：本地 FastAPI 演示

```bash
uvicorn src.demo_web:app --port 8000
# GET http://127.0.0.1:8000/api/health
# GET http://127.0.0.1:8000/api/search?q=周报&mode=hybrid
```

## 六、seekdb 接入点说明

- `src/repository.py::NoteRepository`
  - `_ensure_database`：嵌入式模式下先用底层驱动 `CREATE DATABASE IF NOT EXISTS`；
  - `bulk_upsert / upsert`：写入文档、向量与元数据；
  - `search_vector`：`collection.query`（HNSW 余弦近邻）；ANN 索引未就绪时回退全量向量余弦精排兜底；
  - `search_fulltext`：`collection.get` + `where_document={"$contains": ...}`；
  - `search_hybrid`：`collection.hybrid_search`，全文支路 + knn 支路，`rank={"rrf": {}}` 融合。
- `src/embedder.py`：默认离线确定性向量器；保留接口可替换为 DashScope / OpenAI / 本地 sentence-transformers 等真实 embedding（注意维度一致）。

## 七、文档导航

| 文档 | 内容 |
| --- | --- |
| `docs/validation-sample.md` | 验证样例：初始数据、输入、步骤、预期结果与 seekdb 作用记录 |
| `docs/qoder-dev-log.md` | Qoder 开发记录模板：分环节留痕、截图清单、账号 UID 填写位 |
| `docs/qoder-task-prompt.md` | 可直接粘贴进 Qoder 的后端开发与 Sites 生成提示词 |
| `docs/submit-guide.md` | 提测手册：分支 / 目录 / 提交材料 / 公开访问 / 排查清单 |

## 八、演示站

`site/index.html` 内嵌同样的样例数据，提供搜索框、类别过滤与三种检索模式的前端演示，并包含项目简介、痛点、核心功能、截图位、仓库链接与效果数据位。
该页面用于在 Qoder Sites 中生成并发布对外作品站；线上真实检索由仓库内 Python 应用调用 seekdb 完成，静态站不直连本地数据库。
