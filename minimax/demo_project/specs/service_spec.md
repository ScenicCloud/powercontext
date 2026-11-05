# MiniTask 看板服务规格（当前版本）

版本：2026-11-05
适用范围：`board/` 包与 `tests/` 目录。
术语：任务（Task）包含 `id`、`title`、`status`、`priority`、`due` 五个字段。

### REQ-BOARD-001 服务入口
`TaskService` 提供 `get_task(task_id)` 与 `list_tasks(...)` 两个只读入口，数据来自 `InMemoryTaskRepository`。

### REQ-BOARD-002 单任务读取
`get_task` 返回匹配的任务；任务不存在时抛出 `KeyError`，参数为原始 `task_id`。

### REQ-BOARD-003 状态过滤
`list_tasks(status=...)` 只返回 `status` 等于给定值的任务；`status` 省略或为 `None` 时不过滤。合法取值为 `open` 与 `done`。

### REQ-BOARD-004 优先级过滤
`list_tasks(priority=...)` 只返回 `priority` 等于给定值的任务；合法取值为 1 到 5 的整数。

### REQ-BOARD-005 参数校验
任何非法参数都必须在返回任务之前抛出 `ValueError`：非法 `status`、非法 `priority`、非正整数 `limit`、非法 `due_before`。布尔值不得当作整数使用。

### REQ-BOARD-006 due_before 过滤
`list_tasks(due_before=...)` 只保留截止日期严格早于给定日期的任务。等于给定日期的任务必须被排除；没有截止日期（`due` 为 `None`）的任务在过滤器启用时也必须被排除。

### REQ-BOARD-007 due_before 输入格式
`due_before` 接受 `datetime.date` 或 `YYYY-MM-DD` 形式的字符串。字符串无法解析、日期越界或类型不符时抛出 `ValueError`，错误信息必须包含 `due_before`。

### REQ-BOARD-008 排序规则
结果按 `priority` 降序排列；同一优先级内按 `due` 升序排列，`due` 为 `None` 的任务排在最后；仍相同时按 `id` 升序排列。

### REQ-BOARD-009 数量限制
`limit` 在过滤与排序之后生效，默认值为 20，必须为正整数；`limit` 大于结果数量时返回全部结果。

### REQ-BOARD-010 回归要求
新增 `due_before` 不得改变既有行为：状态过滤、优先级过滤、组合过滤、默认排序、`limit` 截断、`get_task` 以及既有参数校验必须继续通过原有回归测试。
