# LocalBase：端侧推理 × seekdb 混合检索

一个可本地运行的迷你知识库。浏览器使用 Transformers.js 对文档和查询进行本地向量化，Node 服务只负责把原文、向量和元数据写入嵌入式 seekdb，并通过 `collection.hybridSearch` 在数据库内完成全文 + 向量 RRF 融合。

## 启动

要求：Node.js 20+，最新版 Chrome / Edge。嵌入式 seekdb 不需要 Docker 或独立数据库进程。

```bash
cd stepfun
npm install
npm run model:download
npm run dev
```

打开 <http://127.0.0.1:5173>。点击“载入示例语料”→“开始向量化”，索引刷新完成后即可查询。也可导入多个 TXT / Markdown 文件，或创建、切换不同知识库。

模型下载脚本固定 `Xenova/all-MiniLM-L6-v2` 的 commit、文件字节数和 SHA-256，并同时下载 FP32、FP16 与 INT8 ONNX 文件。默认通过 `https://hf-mirror.com` 获取公开模型文件；需要官方端点时执行：

```bash
HF_ENDPOINT=https://huggingface.co npm run model:download
```

模型文件、数据库和构建产物均被 `.gitignore` 排除。全部模型产物约 152 MiB；浏览器只加载当前精度对应的 ONNX 文件。运行时禁用远程模型回退，启动前必须执行下载脚本并生成带哈希的本地模型清单。

## 生产运行

```bash
npm run build
npm start
```

打开 <http://127.0.0.1:3000>。`PORT` 可修改服务端口，`SEEKDB_PATH` 可修改嵌入式数据库目录。服务仅监听 `127.0.0.1`。

## 功能

- 自适应 FP16 / INT8 与可选 FP32 基线，384 维均值池化并 L2 归一化向量。
- 自动模式优先 WebGPU + FP16；无适配器、不支持 FP16 或初始化失败时自动降级 WASM + INT8，界面显示实际后端与精度。
- Worker 内推理，批大小 4 / 8 / 16 / 32 可调，模型只初始化一次并显式预热。
- SHA-256 + 分块序号生成稳定 ID；重复内容在推理前跳过，新增批次写完后统一 `refresh_index()`。
- seekdb HNSW cosine、全文索引和数据库内 `DBMS_HYBRID_SEARCH` RRF；没有客户端候选拼合。
- 独立集合、增量导入、会话选择恢复、旧查询失效保护、原文与元数据展示。
- 查询向量化、数据库检索、端到端延迟显示及 JSON 原始记录导出。

## 验证与性能测试

先保持 `npm run dev` 运行，再在另一个终端执行：

```bash
npm test                         # 无外部服务的单元测试
node scripts/smoke-seekdb.mjs    # 真实 seekdb 写入、刷新、混合检索
npx playwright install chromium # 首次运行浏览器测试时
npm run test:e2e                 # 禁用 WebGPU，验证 WASM 全流程与中断恢复
HEADFUL=1 npm run benchmark      # 原生 GPU 上对比 FP32 / FP16 / INT8 WASM
```

`HEADFUL=1` 可显示浏览器窗口并使用原生 GPU；无头 Chromium 可能使用不支持 FP16 的 SwiftShader，此时自动配置会明确记录 WASM 降级。`CHROME_CHANNEL=chrome` 可改用本机 Chrome。`E2E_URL`、`BENCHMARK_URL` 和 `API_URL` 可覆盖测试地址。

也可以打开 <http://127.0.0.1:5173/benchmark.html> 自行选择配置。固定评测集位于 `public/data/evaluation.json`，默认重复 3 轮，输出 Recall@5、nDCG@5、吞吐和各阶段延迟。完整原始结果保存在 `results/`，测试创建的临时集合默认自动清理。

## 目录

```text
server/                 Express API、参数校验、seekdb 数据访问层
src/embedding-worker.js Transformers.js / ONNX Runtime Web 本地推理
src/embedding.js        WebGPU 检测、WASM 降级、Worker 生命周期
src/main.js             导入、查询、集合与界面状态
src/benchmark.js        固定评测集实验
public/data/            文档与查询相关性标注
scripts/                模型下载、数据库冒烟、E2E、基准脚本
tests/                  单元测试
TECHNICAL.md            一页技术说明与实测结果
```
