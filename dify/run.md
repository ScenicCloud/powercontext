# 运行与验证

本文从仓库根目录 `powercontext/` 开始操作。交付文件是 `dify/chaos_npc.yml`，DSL 版本为 `0.1.5`，应用模式为 `advanced-chat`。

## 1. 启动 seekdb 记忆服务

要求 Python 3.11+。在仓库根目录执行：

```bash
cd qoder/knowledge-base
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m src.cli ingest
uvicorn src.demo_web:app --host 0.0.0.0 --port 8000
```

服务监听 `http://127.0.0.1:8000`，嵌入式 seekdb 数据默认保存在 `qoder/knowledge-base/data/seekdb.db/`。空库首次启动 API 时也会自动载入样例笔记。

另开终端检查服务：

```bash
curl http://127.0.0.1:8000/api/health
```

预期返回包含 `"status":"healthy"` 和 `"engine":"seekdb"`。

## 2. 配置 Dify 可访问的服务地址

导入后，在 Chatflow 的环境变量中编辑 `SEEKDB_API_BASE`，不要在节点里把变量名替换成硬编码地址。地址末尾不要加 `/`。

| Dify 运行方式 | `SEEKDB_API_BASE` | 说明 |
| --- | --- | --- |
| Docker Desktop 上的自托管 Dify | `http://host.docker.internal:8000` | 容器通过该域名访问 Mac/Windows 宿主机上的 8000 端口 |
| 直接运行在同一台机器上的自托管 Dify | `http://127.0.0.1:8000` | 仅当 Dify 进程与 API 共享网络命名空间时可用 |
| Dify Cloud | `https://<your-public-domain>` | 必须是 Dify Cloud 可访问的公网 HTTPS 地址 |

Dify Cloud 不能访问 `127.0.0.1`、localhost、内网地址或 `host.docker.internal`。演示 API 本身没有鉴权，公网暴露时只放测试数据，并在反向代理或网关处限制访问。

## 3. 导入 Chatflow

1. 打开 Dify 工作区，进入 **Studio → Import App → Import DSL**。
2. 上传仓库中的 `dify/chaos_npc.yml`，不要只复制其中的 `workflow` 片段。
3. 导入后确认画布有 **5 个节点、4 条边**，流程为：

   ```text
   Start → 从 seekdb 召回恶作剧记忆 → 小章鱼主持人
         → 记住本轮恶作剧 → Answer
   ```

4. 按上一节设置环境变量 `SEEKDB_API_BASE`。
5. 按下一节绑定模型，然后点击 **Publish**，再打开调试或对话入口。

DSL 顶层必须保留 `app`、`dependencies`、`kind`、`version`、`workflow`。若出现 `Missing workflow data`，通常是误把 `workflow` 移到 `app` 内，或上传了自定义简化 schema，而不是本文件提供的完整应用 DSL。

## 4. 检查 HTTP Request 节点

### 4.1 从 seekdb 召回恶作剧记忆

- Method：`GET`
- URL：`{{#env.SEEKDB_API_BASE#}}/api/search`
- Authorization：`no-auth`
- Headers：空
- Body：`none`
- SSL Verify：开启；使用公网 HTTPS 时保持开启
- Params 使用 Dify 的 `key:value` 文本格式，每行一项：

  ```text
  q:{{#sys.query#}}
  mode:hybrid
  top_k:5
  ```

该节点的 `body` 输出通过 `{{#memory.body#}}` 传给 LLM，其中包含 `items`、`total`、`query` 和 `mode`。

### 4.2 记住本轮恶作剧

- Method：`POST`
- URL：`{{#env.SEEKDB_API_BASE#}}/api/memory`
- Authorization：`no-auth`
- Headers：`Content-Type:application/json`
- Params：空
- Body 类型：`json`
- Body 内容：

  ```json
  {
    "title": "玩家恶作剧",
    "content": "{{#sys.query#}}",
    "category": "general",
    "tags": ["npc", "player-memory"]
  }
  ```

成功响应包含 `ok`、`note_id` 和 `engine=seekdb`。Answer 节点输出 `{{#npc.text#}}`。

## 5. 绑定模型

1. 在 Dify 的 **Settings → Model Provider** 中配置一个可用的模型供应商；凭据只保存在 Dify 中，不写入 DSL 或仓库。
2. 选中 **小章鱼主持人** LLM 节点。
3. 在模型选择器中选择一个支持中文的 Chat 模型，例如已配置可用的 GPT-4o-mini 或同等模型。如果导入后显示模型不可用，必须重新选择供应商和模型，不能只修改 YAML 中的名称。
4. 保留 `mode=chat`，确认 System/User 提示词存在；User 提示词引用：
   - `{{#sys.query#}}`：本轮玩家输入；
   - `{{#conversation.player_name#}}`：玩家名，默认“小鱼”；
   - `{{#memory.body#}}`：seekdb 返回的历史记忆。
5. 保存并发布 Chatflow。

## 6. 完整功能验证样例

### 6.1 在 Dify 中连续对话

保持同一会话，依次发送：

1. `我是小鱼，把广场喷泉换成了章鱼墨汁冰淇淋，暗号是贝壳罗盘。`
2. `小鱼回到广场，喷泉和贝壳罗盘的事你还记得吗？`

检查每一次运行的节点日志：

- 第一轮 POST `/api/memory` 返回 `ok=true`，记下 `note_id`；本轮输入是在 LLM 生成后写入的，供后续轮次使用。
- 第二轮 GET `/api/search` 的 `items` 应包含第一轮正文，尤其是“章鱼墨汁冰淇淋”或“贝壳罗盘”。
- 第二条 NPC 回应应引用上述历史细节，并包含“记忆线索”和下一步选项，而不是只泛化地回答“我记得你”。
- 两轮 Answer 都应正常输出，所有 HTTP 节点状态均为成功。

### 6.2 不经过模型，核对 seekdb 写入与召回

在服务终端执行一条唯一记忆：

```bash
curl -X POST http://127.0.0.1:8000/api/memory \
  -H 'Content-Type: application/json' \
  -d '{"title":"玩家恶作剧","content":"验收记忆：小鱼用贝壳罗盘换走了小章鱼的珍珠。","category":"general","tags":["npc","player-memory"]}'
```

记录响应中的 `note_id`，再用完全相同的正文检索：

```bash
curl --get http://127.0.0.1:8000/api/search \
  --data-urlencode 'q=验收记忆：小鱼用贝壳罗盘换走了小章鱼的珍珠。' \
  --data-urlencode 'mode=hybrid' \
  --data-urlencode 'top_k=5'
```

预期 POST 返回 200 和 `"engine":"seekdb"`；GET 返回 200，`total >= 1`，且 `items` 中至少一项具有相同的 `note_id` 和 `content`。这组结果就是 Dify LLM 实际收到的记忆上下文。

错误输入也应被明确拒绝：空白 `content`、空白 `q`、非 `hybrid/vector/fulltext` 的 `mode`、小于 1 或大于 50 的 `top_k` 均返回 422。

## 7. 自动验证命令

在仓库根目录、已激活上述虚拟环境的终端中执行：

```bash
python -m compileall qoder/knowledge-base/src
python qoder/knowledge-base/scripts/selftest.py
python -c 'import yaml; yaml.safe_load(open("dify/chaos_npc.yml", encoding="utf-8")); print("DSL YAML OK")'
```

`selftest.py` 使用独立临时库，验证 seekdb 写入、全文、向量、混合检索、过滤和删除，不会清空演示数据。

## 8. seekdb 在应用中的实际作用

- `qoder/knowledge-base/src/demo_web.py` 只负责 HTTP 参数校验和响应，所有数据库访问都经过 `qoder/knowledge-base/src/repository.py`。
- POST `/api/memory` 把玩家正文和标签持久化到 seekdb，并生成向量。
- GET `/api/search` 使用 seekdb 的全文支路、向量支路和 RRF 混合检索返回历史记忆。
- Dify 负责编排，LLM 只把检索结果转成角色台词；模型本身不承担记忆存储。删除 seekdb 中的记录或更换检索结果后，后续 NPC 回应所依据的记忆也会随之变化。
