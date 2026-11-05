# MiniTask 服务接口契约

```python
TaskService.list_tasks(
    *,
    status: str | None = None,
    priority: int | None = None,
    due_before: datetime.date | str | None = None,
    limit: int = 20,
) -> list[Task]
```

## 输入

| 参数 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| status | str \| None | 否 | `open` 或 `done` |
| priority | int \| None | 否 | 1 到 5 |
| due_before | date \| str \| None | 否 | `YYYY-MM-DD` 或 `datetime.date` |
| limit | int | 否 | 正整数，默认 20 |

## 输出

按 REQ-BOARD-008 排序、按 REQ-BOARD-009 截断后的 `Task` 列表。调用不得修改仓储中的任务对象。

## 错误

| 场景 | 异常 | 消息要求 |
| --- | --- | --- |
| 非法 status / priority / limit | `ValueError` | 说明合法取值 |
| 非法 due_before | `ValueError` | 包含 `due_before` 与 `YYYY-MM-DD` |
| 未知 task_id | `KeyError` | `args == (task_id,)` |
