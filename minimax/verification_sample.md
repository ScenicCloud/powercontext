# 样例任务与验收基线

## 任务

为 `TaskService.list_tasks` 增加 `due_before` 过滤：只返回截止日期严格早于给定日期的任务，
同时保持 `status` 与 `priority` 过滤、默认排序和 `limit` 行为；非法 `due_before` 必须抛出
`ValueError`，并继续通过既有回归测试。

## 必须包含的上下文来源

| 类型 | 来源 |
| --- | --- |
| 规格 | `specs/service_spec.md#REQ-BOARD-006`（过滤语义） |
| 规格 | `specs/service_spec.md#REQ-BOARD-007`（日期格式与异常） |
| 规格 | `specs/service_spec.md#REQ-BOARD-010`（回归要求） |
| 决策 | `specs/decisions.md#ADR-005`（严格边界与空值语义） |
| 决策 | `specs/decisions.md#ADR-006`（排序规则，取代 ADR-002） |
| 代码 | `board/service.py#TaskService.list_tasks` |
| 测试 | `tests/test_due_before.py`（目标行为） |
| 测试 | `tests/test_filters.py`（既有行为回归） |

`records/context_for_minimax.json` 的 `missing_required` 必须为空；`demo` 也会校验这一点。

## 修改前预期

- `tests/test_due_before.py`：失败（`TypeError: ... unexpected keyword argument 'due_before'`）。
- `tests/test_filters.py` 与 `tests/test_validation.py`：全部通过。

## 修改后预期

- 目标测试与回归测试全部通过（共 35 项）。
- `due_before` 等于边界日期的任务被排除；`due=None` 的任务在过滤启用时被排除。
- 非法日期抛出 `ValueError`，消息包含 `due_before`。

## 规格更新预期

`evidence/spec_evolution/notification_v1.md` 导入后，检索结果中的 REQ-NOTIFY-001 描述为
“最近 2 条通知”；同一路径替换为 v2 并重新导入后，结果变为“最近 3 条通知”且新增
REQ-NOTIFY-002。两次检索结果必须不同。
