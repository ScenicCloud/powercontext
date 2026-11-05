# 运行与验证

## 1. 启动 seekdb 记忆服务

在仓库根目录执行：

```bash
cd qoder/knowledge-base
python -m venv .venv-dify
source .venv-dify/bin/activate
pip install -r requirements.txt
python -m src.cli ingest
uvicorn src.demo_web:app --host 0.0.0.0 --port 8000
```

服务地址为 `http://127.0.0.1:8000`。Dify 自托管时可直接访问；Dify Cloud 需要把服务暴露为 HTTPS 地址，并在 DSL 的 HTTP 节点中填写该地址。

可选地写入一条专门用于验收的记忆：

```bash
curl -X POST http://127.0.0.1:8000/api/memory \
  -H 'Content-Type: application/json' \
  -d '{"title":"玩家小鱼的恶作剧","content":"小鱼把 NPC 的宝箱换成了会唱歌的萝卜。","tags":["npc","小鱼"]}'
```

## 2. 导入 DSL

在 Dify 工作区选择 **Studio → Import DSL**，上传 `chaos_npc.yml`。导入后：

1. 在 HTTP Request 节点把 `SEEKDB_API_BASE` 替换为实际地址。
2. 在 LLM 节点绑定可用模型（推荐支持中文的 GPT-4o-mini、Qwen2.5-72B 或同等模型）。
3. 发布 Chatflow，打开调试入口。

## 3. 验证样例

初始数据：`qoder/knowledge-base/data/sample_notes.json` 已由 `python -m src.cli ingest` 导入；也可在 seekdb 中新增一条包含玩家名的记录。

连续发送以下两条消息，玩家名保持为“小鱼”：

1. `我是小鱼，偷偷把 NPC 的宝箱换成了会唱歌的萝卜。`
2. `小鱼再次路过广场，假装什么都没发生。`

预期：第一条得到一次场景反应，并提示已记住；第二条的回答应引用“会唱歌的萝卜”或其语义等价表达，并给出带惩罚/反转的 2~3 个行动选项。Dify 日志中 HTTP 节点响应的 `items` 应非空，`engine` 或服务日志应显示 seekdb。

## 4. 复现 seekdb 作用

```bash
curl 'http://127.0.0.1:8000/api/search?q=小鱼%20会唱歌的萝卜&mode=hybrid&top_k=5'
```

返回的 `items` 即为传给 LLM 的记忆上下文。删除或更换该条数据后重复第二步，NPC 的回忆应随检索结果变化。

## 限制

该 DSL 使用 Dify 的 HTTP Request 和 LLM 节点，不包含真实 API Key。Dify Cloud 到本地 seekdb 服务必须使用可访问的 HTTPS 反向代理；自托管 Dify 可在同一网络中使用内网地址。
