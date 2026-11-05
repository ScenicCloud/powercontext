# 技术设计说明

## 1. 数据模型（seekdb / OceanBase）

| 表 | 用途 |
| --- | --- |
| `documents` | 每个规格/代码/测试文件一行，保存相对路径、内容哈希、全文 |
| `chunks` | 检索单元：规格需求块、ADR、函数/方法、测试函数；保存行号、符号名、状态 |
| `ingest_runs` | 每次导入的统计，便于确认重导入确实发生 |

`chunks` 与 `documents` 都建立了 `FULLTEXT` 索引；中文检索使用 `INSTR`，因为 seekdb 默认
全文分词器不切分中文。

重导入策略：以 `project + 相对路径` 生成稳定 `doc_id`，内容哈希不变则跳过；
变化时在同一事务中删除旧分块并写入新分块，避免出现新旧内容混合。

## 2. 检索流程

1. 从任务文本抽取英文标识符（含 snake/camel 拆分）与中文 2/3-gram。
2. 对每种来源（spec / decision / code / test）分别执行：
   - `MATCH(text) AGAINST(... IN NATURAL LANGUAGE MODE)` 取候选；
   - `INSTR(text, term)` 取中文候选。
3. 计算每个词的文档频率 `df`，IDF 为 `log(1 + N / (1 + df))`。
4. 打分：`4.0 + 3.0 * 归一化 FTS 得分 + ΣIDF(命中词)`，中文候选再加命中词 IDF 与出现次数上限。
5. 按来源配额截断；ADR 仅保留 `Status: active`，其余写入 `excluded_decisions`。
6. 每个结果输出 `path`、`lines`、`locator`、`matched`、`score` 与原文，保证可核对。

所有 SQL 与参数、返回的 `chunk_id` 会写入 `records/seekdb_queries*.log`。

## 3. 与 MiniMax 的边界

- 模块把**检索到的规格/决策/代码/测试原文 + 相关文件全文**放进请求，不传整个仓库。
- 系统提示要求只返回 unified diff；`minimax_client` 提取 ```diff 代码块并用 `patch -p1` 应用。
- 完整请求体、响应体、模型名、耗时、usage 保存在 `records/minimax_dev_session.json`。
- 若未配置 `MINIMAX_API_KEY`，命令直接失败，不会写出伪造记录。
- `demo` 会把记录的补丁重新应用到修改前快照，并与当前代码逐字节比对，
  不一致时 `run_summary.json` 的 `must_pass.minimax_patch_reproduces_committed_code` 为 false。

## 4. 任务状态（PowerContext）

- 每次 CLI 调用启动一个临时 PowerContext HTTP 服务，持久化到
  `.state/powercontext.db`（SQLite 后端，服务端与客户端均为 PowerContext）。
- Scope 使用固定 `idempotency_key`，重复运行不会产生新 Scope。
- 任务进度以 `content source` 保存结构化 JSON（完成项、待办、验证结果、上下文摘要），
  同时写入可搜索的 memory（`progress` / `constraint` / `fact`）。
- `state-show` 是独立进程，重新启动服务后按 `task_id` 从 source 中读取，
  `records/state_after_restart.json` 记录读取结果与 memory 命中。

## 5. 验证与可重复性

- `demo_project` 只依赖标准库与 pytest，随机性为零。
- 修改前快照恢复后，目标测试必然因缺少 `due_before` 参数失败；回归测试保持通过。
- 规格更新演示复用同一文件路径 `notification_spec.md`，先 v1 后 v2，
  两次检索的文本必须不同，`spec_evolution.json` 的 `updated_content_used` 为 true。
- `run_summary.json` 汇总全部布尔断言，任一为 false 时 `demo` 退出码为 1。
