# 恶作剧 NPC：记仇小章鱼

一个会记住玩家恶作剧、并在下一次互动中“秋后算账”的 Dify Chatflow。玩家输入一句行动，Dify 先调用本仓库的 seekdb API 检索该玩家历史，再由模型根据记忆生成 NPC 反应、记忆摘要和下一步选项。

## 交付物

- `chaos_npc.yml`：Dify Chatflow DSL，导出格式版本 `0.1.5`
- `run.md`：部署、导入、模型绑定、HTTP 节点配置与验证步骤
- `sample-memory.json`：可选的验证数据

## 技术分工

- Dify：输入变量、HTTP Request、LLM 和最终回答的核心编排。
- seekdb：由 `qoder/knowledge-base/src/demo_web.py` 提供持久化玩家记忆的混合检索；同一玩家后续输入会召回此前恶作剧。
- 模型：只负责把检索到的事实演成轻松的 NPC 台词，不承担记忆存储。

导入后只需设置环境变量 `SEEKDB_API_BASE`，并在 LLM 节点选择可用的模型供应商和模型；详细网络要求见 `run.md`。
