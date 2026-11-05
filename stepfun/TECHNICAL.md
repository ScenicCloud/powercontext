# LocalBase 技术说明

## 方案与端侧边界

LocalBase 使用 **Transformers.js 3.7.2 + ONNX Runtime Web**，在浏览器 Web Worker 中运行 `Xenova/all-MiniLM-L6-v2`（384 维，mean pooling + L2 normalize，最长 512 tokens）。文档和查询均在用户设备推理；Node 服务不加载模型、不调用云端推理 API，也不保存或回放预算向量。原文、向量、稳定文档 ID 和元数据只写入嵌入式 **seekdb 1.4.0**；localStorage 仅保存界面设置与性能记录。

模型 revision 固定为 `751bff37182d3f1213fa05d7196b954e230abad9`。下载脚本固定每个文件的 expected bytes 与 SHA-256，已有文件校验失败会重新下载，运行时禁用远程模型回退。模型下载不等于远程推理。

| ONNX 权重 | 实际体积 | 相对 FP32 压缩比 |
|---|---:|---:|
| FP32 `model.onnx` | 86.20 MiB | 1.000× |
| FP16 `model_fp16.onnx` | 43.20 MiB | 1.995× |
| INT8 `model_quantized.onnx` | 21.91 MiB | 3.935× |

## 推理、检索与状态

- **自适应后端**：自动模式优先 WebGPU + FP16；无 WebGPU、适配器不支持 FP16 或初始化失败时，新建 Worker 降级 WASM + INT8，UI 显示实际后端和精度。也可显式选择 FP32 / FP16 / INT8。无头 SwiftShader 不含 `shader-f16`，原生 Apple Metal-3 支持；基准 JSON 记录适配器、特性和降级原因。
- **数据库内混合检索**：collection 配置为 384 维 HNSW cosine，`embeddingFunction: null`。一次 `collection.hybridSearch` 同时传入全文 `$contains` 与 KNN 向量，seekdb 通过 `DBMS_HYBRID_SEARCH` 和 RRF（window 50、k 60）融合，应用层不拼合两路候选。
- **增量与一致性**：SHA-256 内容摘要 + 分块序号生成稳定 ID，已有 ID 按 5,000 条分批检查并在推理前跳过。每批最多 32 条，批次写完后统一 `refresh_index()`；即使本次全部为重复内容也刷新，以恢复“写入已提交、响应或刷新中断”的状态。嵌入式原生客户端的所有操作通过 Promise 队列串行化。
- **会话与接口安全**：集合切换使用请求序号阻止旧结果覆盖新页面，忙状态按操作序号释放，指标绑定发起操作的集合。所有文本用 DOM `textContent` 渲染。API 仅监听 `127.0.0.1`，校验 Host、Origin 与 Sec-Fetch-Site，阻止 DNS 重绑定和跨站请求。

## 实测结果

2026-11-05，macOS / Apple Metal-3，Chrome 141（headed，10 logical cores），固定英文评测集 **12 篇文档、9 个查询、3 轮、batch 8、K=5**。每种配置独立建集合并重新在浏览器计算向量。模型加载为本地文件已下载后的初始化，不含安装下载时间；首条查询发生在显式预热之后；P50 取全部 27 次查询中位数。吞吐只计算 embedding 时间。

| 配置 | 加载 / 预热 | 首条查询 | 吞吐 chunks/s | 查询向量 P50 | seekdb P50 | 端到端 P50 | Recall@5 | nDCG@5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| FP32 + WebGPU | 1380.5 / 65.7 ms | 35.8 ms | 159.79 | 12.0 ms | 1.36 ms | 16.50 ms | 1.0000 | 1.0000 |
| FP16 + WebGPU | 410.8 / 40.6 ms | 26.8 ms | **188.68** | 11.6 ms | 1.35 ms | 16.40 ms | **1.0000** | **1.0000** |
| INT8 + WASM | 341.3 / 28.7 ms | 36.4 ms | 26.89 | **8.0 ms** | **1.34 ms** | **12.10 ms** | **1.0000** | **1.0000** |

本轮 FP16 相比 FP32 的导入吞吐提高约 **18.1%**，且没有检索质量损失；模型文件减少约一半。短查询下 WASM 总延迟更低，说明小模型单句推理不一定受益于 GPU 调度，因此保留后端与精度选项。结果是本机单次基准实验，不宣称为所有设备的普遍收益。Recall/nDCG 按唯一来源文档计算，完整每批、每查询原始数据见 `results/benchmark.json`。

## 复现与验收

```bash
npm install && npm run model:download
npm run dev
npm test                         # 13 项单元/安全/分批回归
npm run test:e2e                 # 禁用 WebGPU，WASM 全流程
HEADFUL=1 npm run benchmark      # 使用原生 GPU；保存原始 JSON
npm run build && npm start       # 生产模式
```

最终验收：13 项测试通过；生产构建在真实 Chromium 中通过 7 项检查，覆盖 WASM 浏览器推理、seekdb 混合检索、重复导入、未刷新写入恢复、集合切换与清理，控制台无错误；恶意 Host 实测返回 HTTP 403。证据见 `results/e2e.json`、`results/app.png` 和 `results/benchmark.json`。
