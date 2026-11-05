# MiniTask 设计决策记录

每条决策包含状态行。只有 `Status: active` 的决策属于当前有效上下文；状态为 `superseded` 或 `rejected` 的决策不得作为实现依据。

### ADR-001 任务状态词汇
Status: active
任务状态固定为 `open` 与 `done` 两种，其他词汇一律视为非法输入并抛出 `ValueError`。

### ADR-002 按截止日期升序排序
Status: superseded by ADR-006
早期版本只按 `due` 升序排序，未考虑优先级；该决策已被 ADR-006 取代，不得再用于实现。

### ADR-003 增加 archived 状态
Status: rejected
曾提议增加 `archived` 状态以软删除任务；该提案被拒绝，当前数据模型不包含该状态，也不提供 `include_archived` 参数。

### ADR-004 演示工程使用内存仓储
Status: active
演示工程使用确定性的内存仓储 `InMemoryTaskRepository`，避免测试依赖外部数据库；业务工程原有的存储方式保持不变。

### ADR-005 due_before 的严格边界语义
Status: active
`due_before` 表示“严格早于”，等于边界日期的任务不计入结果。截止日期缺失的任务在过滤器启用时排除，以免把“无期限”误判为“已到期”。

### ADR-006 优先级优先的排序
Status: active
排序键为 `priority` 降序、`due` 升序（`None` 最后）、`id` 升序。该决策取代 ADR-002。
