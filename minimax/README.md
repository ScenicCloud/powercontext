# SDD 上下文管理系统（MiniMax 生态赛题）

本目录是「规有所依，面向软件持续演进的 SDD 上下文管理系统」的完整交付物。
它用一个可运行的 Python 业务工程演示：规格（spec）与代码、测试、历史决策一起进入
seekdb，任务发生时按相关度检索出**可追溯来源**的上下文，MiniMax 基于该上下文产出
补丁，验证结果与任务进展写入 PowerContext，模块重启后可以继续复用。

## 1. 目录结构

```
minimax/
├── demo_project/                 # 可运行的业务工程（纯标准库）
│   ├── board/                    # 任务看板服务
│   ├── specs/                    # service_spec.md / api_contract.md / decisions.md
│   └── tests/                    # 目标测试 + 回归测试
├── evidence/
│   ├── before/board/service.py   # 修改前代码快照（缺少 due_before）
│   ├── after/board/service.py    # 修改后代码快照
│   ├── code_change.diff          # 修改前后差异
│   └── spec_evolution/           # 规格更新演示（v1 / v2）
├── sdd_context/                  # 上下文管理模块（CLI）
│   ├── ingest.py                 # 规格/代码/测试 → seekdb 文档与分块
│   ├── store.py                  # seekdb schema、写入、FTS/子串检索与查询日志
│   ├── select.py                 # IDF 加权的来源选择、失效决策过滤
│   ├── minimax_client.py         # MiniMax OpenAI 兼容接口调用与补丁提取
│   ├── pc_state.py               # PowerContext 任务状态保存/重启后读取
│   └── verify.py                 # 目标测试 / 回归测试执行
├── records/                      # 全部验证证据（由脚本自动生成）
└── verification_sample.md        # 样例任务、必须包含的来源、预期结果
```

## 2. 快速验证

前置条件：Python 3.12+、一个可连接的 seekdb 或 OceanBase（MySQL 协议）。

```bash
# 在仓库根目录 powercontext/
pip install -e ".[server]"        # PowerContext 服务端依赖
pip install -r minimax/requirements.txt

# seekdb（示例，端口按实际环境调整；也可用 OceanBase）
export SEEKDB_HOST=127.0.0.1 SEEKDB_PORT=2883 SEEKDB_USER=root SEEKDB_PASSWORD=

cd minimax
python -m sdd_context init --reset
python -m sdd_context demo
```

`demo` 会依次完成：建库建表 → 导入工程资料 → 检索上下文 → 修改前失败验证 →
修改后通过验证 → 规格更新再导入 → PowerContext 保存并在**独立进程**中读取。
最终输出全部 `true` 即通过，`records/run_summary.json` 是机器可读的汇总。

## 3. MiniMax 实际调用

`demo` 不伪造 MiniMax 结果；MiniMax 会话记录和补丁复现检查会出现在
`run_summary.json` 的 `must_pass` 中。复现步骤：

```bash
export MINIMAX_API_KEY=...          # 赛题发放的 MiniMax Token Plan
export MINIMAX_MODEL=MiniMax-M2     # 按账号可用模型调整

cd minimax
# 1) 恢复修改前代码，并准备带入 MiniMax 的上下文
python -m sdd_context context --project minimax_demo_before \
  --out records/context_for_minimax.json --check-required

# 2) 由 MiniMax 产出补丁并应用到修改前工程
python -m sdd_context ask --project-dir .demo_work/before_project \
  --context records/context_for_minimax.json \
  --files board/service.py board/models.py tests/test_due_before.py \
  --out records/minimax_dev_session.json --apply

# 3) 验证并回填修改后快照
python -m sdd_context verify --project-dir .demo_work/before_project \
  --phase after --out-dir records
cp .demo_work/before_project/board/service.py demo_project/board/service.py

# 4) 重新生成完整证据（含补丁可复现检查）
python -m sdd_context demo
```

若第一轮补丁未通过测试，可用 `--attempt 2 --feedback "<失败摘要>"` 继续追问，
每轮都会保存独立的会话记录；最终以通过测试的补丁为准。

## 4. 六项必过条件的对应证据

| 条件 | 证据 |
| --- | --- |
| 能从干净环境开始运行 | `requirements.txt`、`README` 命令、`demo_project` 无第三方依赖 |
| MiniMax 实际参与 | `records/minimax_dev_session.json`（完整请求/响应、模型、耗时）、`records/minimax_patch.diff`；`demo` 会复现补丁并比对当前代码 |
| 输出的上下文有基准 | `records/context_for_minimax.json` 中每条来源都带 `path`、`lines`、`locator`、相关度与命中词 |
| 数据库实际参与 | `records/seekdb_queries*.log` 记录每次 SQL；资料存放在 seekdb 的 `documents`/`chunks` 表 |
| 任务状态能够复用 | `records/powercontext_save.json` 与 `records/state_after_restart.json`（独立进程重启后读取） |
| 代码修改有效 | `records/tests_target_before.log`（失败）、`records/tests_target_after.log`（通过）、`records/tests_regression_*.log`（通过） |

## 5. 设计要点

- **来源可追溯**：每个上下文片段都保存相对路径、起止行号、符号名/需求编号，输出中不出现无出处的摘要。
- **检索真实发生**：英文标识符用 seekdb `FULLTEXT`，中文用 `INSTR` 子串检索（seekdb 默认分词器不含中文）；
  最终排序使用「FTS 归一化得分 + IDF 加权命中词 + 子串命中」，SQL 与结果写入查询日志。
- **失效决策过滤**：`specs/decisions.md` 中的 `Status:` 会被解析；`superseded`/`rejected` 的 ADR 不进入上下文，
  但在 `excluded_decisions` 中列出，便于评审核对“哪些决策已经失效”。
- **规格演进**：`evidence/spec_evolution` 演示同一路径下的规格从 v1 更新到 v2，重新导入后检索结果立即变化，
  不会返回固定答案。
- **状态复用**：任务进展、验证结果以结构化内容写入 PowerContext Scope；读取发生在新的 CLI 进程中，
  内存中没有任何残留。

## 6. 已知限制

- 本机（macOS）没有可用的 `pylibseekdb` 嵌入库，因此演示连接已启动的 seekdb 服务；代码只使用 MySQL
  协议，切换 `SEEKDB_HOST/PORT` 即可连接 OceanBase。
- 演示工程刻意保持很小，便于评审在几分钟内完成端到端验证；检索与状态机制不依赖工程规模。
