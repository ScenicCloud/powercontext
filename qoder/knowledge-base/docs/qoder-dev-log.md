# Qoder 开发记录

> 题目要求：项目主要开发工作必须在 Qoder 中完成，并保留开发过程记录，说明 Qoder 在需求拆解、编码、调试等环节完成了哪些工作。
> 仅用 Qoder 发布网站、而代码在其他工具中编写，不符合本赛道要求。

## 一、基本信息

| 项 | 填写 |
| --- | --- |
| 项目名称 | 知库 · 基于 seekdb 的个人知识检索助手 |
| 开发工具 | Qoder 桌面端（Qoder Desktop，macOS 版） |
| 开发环境 | 操作系统：macOS 26.6.2（Apple Silicon, arm64）；Python：3.12.10 |
| 开发日期 | 2026-11-02 至 2026-11-05 |
| **Qoder 账号 UID** | 【待填写】（获取：Qoder → 设置 Settings → 个人资料 Profile → Edit，复制 Qoder UID） |
| 代码仓库地址 | https://github.com/ScenicCloud/oceanbase-powercontext（团队私有仓库，按平台要求向评审开放只读权限） |
| 提交分支 | `2026-competition-ecosystem` |
| 项目所在目录 | `qoder/knowledge-base/` |

## 二、分环节开发记录

> 每个环节填写：Qoder 完成了什么、你给的关键提示词、对应截图/录屏文件名。截图保留对话上下文（能看到提示词与 Qoder 产出）。

### 1. 需求拆解
- Qoder 完成的工作：从「笔记/论文/周报难找」的痛点出发，拆解出条目管理、全文检索、向量检索、混合检索、类别过滤等功能模块。
- 关键提示词：见 `docs/qoder-task-prompt.md` 第一段。
- 截图 / 录屏：`screenshots/01-requirement.png`

### 2. 技术选型与接入设计
- Qoder 完成的工作：确定使用 OceanBase seekdb（`pyseekdb` 嵌入式本地库）作为检索引擎；设计 `repository.py` 作为唯一数据访问层；确定离线向量器与可替换的 embedding 接口。
- 截图 / 录屏：`screenshots/02-tech-design.png`

### 3. 编码实现
- Qoder 完成的工作：生成数据模型、向量器、检索仓库层、CLI、样例数据与自测脚本；按 `.qoder/rules/project-rules.md` 约束组织代码。
- 关键改动文件：`src/`、`scripts/`、`data/`、`site/`。
- 截图 / 录屏：`screenshots/03-coding.png`

### 4. 调试与修复
- Qoder 完成的工作：根据报错定位并修复（例如：高层 SDK 需先建 catalog 库、向量索引异步构建导致的召回为空、标题并入文档字段以支持全文命中）。
- 2026-11-05 验证期修复：重复执行 `ingest` 因每次生成随机 UUID 导致条目翻倍（7 → 14）。Qoder 定位后改为以标题 MD5 前 12 位作确定性 `note_id`，重复导入走 upsert 幂等更新；修复后连续两次 `ingest` 均为 7 条，自测保持全绿（`src/cli.py::_load_sample`）。
- 截图 / 录屏：`screenshots/04-debug.png`（贴出报错与修复后的对比）

### 5. 自测回归
- Qoder 完成的工作：运行 `python scripts/selftest.py`，按失败项迭代直到 9 项断言全部通过。
- 截图 / 录屏：`screenshots/05-selftest.png`（贴出全绿结果）

### 6. Qoder Sites 站点生成与发布
- Qoder 完成的工作：在 Sites 任务中带 `@sites`，按 `docs/qoder-task-prompt.md` 第二段生成静态演示站，预览交互后发布，可见范围设为「任何人都可访问」。
- 站点地址（已发布并公开）：https://seekdb-knowledge-base-nxznx2c7zec.qoder.zone
- 发布前验证：搜索命中、清空恢复全量、类别过滤、三种检索模式切换与排序变化均已逐一点验。
- 截图 / 录屏：`screenshots/06-sites-publish.png`（含发布状态与公开访问设置）

## 三、技术结合证据（seekdb 实际作用）

> 评审会核对指定技术是否在功能中真正发挥作用，仅安装组件或测试连接不算。请粘贴可核对的记录：

- 写入记录：`python -m src.cli ingest` 后 `count = 7` 的终端输出（2026-11-05 实测）：

```
$ python -m src.cli ingest
已导入 7 条笔记，当前共 7 条。
$ python -m src.cli count
当前共 7 条。
```

- 检索记录：样例 1–3 的命中结果（完整输出见 `docs/validation-sample.md` 与 `screenshots/validation-output.txt`）：

```
$ python -m src.cli search "周报" --mode fulltext
模式=fulltext，命中 1 条：
[1] 周报：充电桩平台后端接口联调进度  (work, 周报,后端,联调,待办)

$ python -m src.cli search "补码 溢出 判断" --mode vector --top-k 2
模式=vector，命中 2 条：
[1] 组成原理：补码表示与定点数溢出判断  (study, 组成原理,补码,考试复习)
[2] 数据库系统：B+ 树索引为什么比哈希索引更适合范围查询  (study, 数据库,索引,B+树,课程笔记)

$ python -m src.cli search "向量 全文 混合检索 RRF 融合" --mode hybrid --top-k 3
模式=hybrid，命中 3 条：
[1] 文献摘要：面向 RAG 的混合检索（向量 + 全文）与 RRF 融合  (research, 论文,RAG,混合检索,向量数据库)
[2] 实验记录：seekdb 嵌入式本地库与 HNSW 索引验证  (research, seekdb,实验,HNSW,向量检索)
[3] 数据库系统：B+ 树索引为什么比哈希索引更适合范围查询  (study, 数据库,索引,B+树,课程笔记)
```

- 自测记录：`python scripts/selftest.py` 9 项断言全部 PASS，末尾输出 `全部通过 ✅`，退出码 0。

- 代码接入点：`src/repository.py` 中 `upsert / search_vector / search_fulltext / search_hybrid` 调用 `pyseekdb` 的位置。

## 四、截图 / 录屏清单（提交材料）

| 序号 | 环节 | 文件 | 是否齐备 |
| --- | --- | --- | --- |
| 1 | 需求拆解 | `screenshots/01-requirement.png` | [ ] |
| 2 | 技术选型 | `screenshots/02-tech-design.png` | [ ] |
| 3 | 编码实现 | `screenshots/03-coding.png` | [ ] |
| 4 | 调试修复 | `screenshots/04-debug.png` | [ ] |
| 5 | 自测全绿 | `screenshots/05-selftest.png` | [ ] |
| 6 | Sites 发布与公开 | `screenshots/06-sites-publish.png` | [ ] |

> 截图中如出现个人姓名、手机号等隐私信息，请先打码；保留 Qoder 对话与产出即可。
