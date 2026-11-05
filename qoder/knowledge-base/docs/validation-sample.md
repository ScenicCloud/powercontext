# 验证样例（评审可按步骤复现）

> 用途：评审按本文档完成配置后，可逐条体验主要功能，并核对 seekdb 在检索流程中的实际作用。
> 所有样例基于 `data/sample_notes.json` 的 7 条初始数据（学习 3、科研 2、工作 2）。

## 0. 环境与初始化

| 项 | 要求 / 取值 |
| --- | --- |
| Python | 3.11 及以上（推荐 3.12） |
| 操作系统 | Linux x86_64/aarch64（glibc ≥ 2.28）或 macOS arm64 ≥ 15.6 |
| 依赖 | `pip install -r requirements.txt`（自动安装 `pyseekdb` 与底层 `pylibseekdb`） |
| 数据库 | seekdb 嵌入式本地库，无需独立部署服务器；数据目录由环境变量 `SEEKDB_PATH` 指定，默认 `./data/seekdb.db` |

初始化步骤：

```bash
cd qoder/knowledge-base
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m src.cli ingest           # 导入 7 条样例数据
python -m src.cli count            # 预期输出：当前共 7 条
```

> 下面命令均在已激活虚拟环境、已执行 `ingest` 的前提下运行。

## 样例 1：关键词全文检索

**初始数据**：7 条样例，其中工作类 2 条（周报、会议纪要）。

**输入 / 操作**：

```bash
python -m src.cli search "周报" --mode fulltext
```

**预期结果**：命中「周报：充电桩平台后端接口联调进度」，类别为 `work`；标题、正文、标签展示完整。

**seekdb 作用记录**：
- 检索支路：全文检索（`collection.get` + `where_document={"$contains": ...}`）。
- 标题已并入文档字段一起索引，因此关键词命中标题也能召回。
- 实际输出（2026-11-05 实测，完整记录见 `screenshots/validation-output.txt`）：

```
模式=fulltext，命中 1 条：

[1] 周报：充电桩平台后端接口联调进度  (work, 周报,后端,联调,待办)
    本周完成充电桩列表与下单接口联调，待办：补齐订单状态机异常分支、补充接口压测报告。遗留问题：高峰期并发下库存扣减需要加乐观锁，下周与前端对齐字段口径。
    id=ffccdab26cde  2026-11-01
```

## 样例 2：语义向量检索

**输入 / 操作**：

```bash
python -m src.cli search "补码 溢出 判断" --mode vector --top-k 2
```

**预期结果**：首条命中「组成原理：补码表示与定点数溢出判断」（类别 `study`）；即使没有出现完全相同的词，也能按语义近邻召回相关笔记。

**seekdb 作用记录**：
- 检索支路：向量检索，HNSW 索引 + 余弦距离（`collection.query`）。
- 查询文本经 `src/embedder.py` 生成 256 维向量，与入库向量做最近邻匹配。
- 若索引尚未构建完成，代码自动回退全量向量余弦精排兜底（见 `repository.py::search_vector`）。
- 实际输出（2026-11-05 实测）：

```
模式=vector，命中 2 条：

[1] 组成原理：补码表示与定点数溢出判断  (study, 组成原理,补码,考试复习)
    负数用补码存储，便于把减法转为加法运算。判断溢出可看最高位进位与符号位进位是否不同，或两个同号数相加结果符号反转。复习要点：原码反码补码换算、移码用于阶码。
    id=28b526a7ebf5  2026-10-18

[2] 数据库系统：B+ 树索引为什么比哈希索引更适合范围查询  (study, 数据库,索引,B+树,课程笔记)
    B+ 树是平衡多路搜索树，叶子节点通过链表相连，天然支持按主键有序扫描与范围查询；哈希索引只能做等值匹配，遇到区间条件需要全量回表。课程作业中常考聚簇索引与二级索引的回表区别。
    id=803b8ca36f0d  2026-10-12
```

## 样例 3：混合检索（向量 + 全文，RRF 融合）

**输入 / 操作**：

```bash
python -m src.cli search "向量 全文 混合检索 RRF 融合" --mode hybrid --top-k 3
```

**预期结果**：首条命中「文献摘要：面向 RAG 的混合检索（向量 + 全文）与 RRF 融合」（类别 `research`）。

**seekdb 作用记录**：
- 检索支路：混合检索 `collection.hybrid_search`。
- 全文支路按关键词包含召回，向量支路按语义近邻召回，两路结果用 RRF（倒数排名融合）重排（`rank={"rrf": {}}`）。
- 实际输出（2026-11-05 实测）：

```
模式=hybrid，命中 3 条：

[1] 文献摘要：面向 RAG 的混合检索（向量 + 全文）与 RRF 融合  (research, 论文,RAG,混合检索,向量数据库)
    纯向量检索擅长语义近义召回，但对专有名词和精确术语不够稳；纯全文检索依赖关键词重合。混合检索分别走向量支路与全文支路，再用倒数排名融合（RRF）重排，在知识问答场景召回率和命中率更均衡。
    id=093836ea8fd3  2026-10-25

[2] 实验记录：seekdb 嵌入式本地库与 HNSW 索引验证  (research, seekdb,实验,HNSW,向量检索)
    在 Python 中以嵌入式模式打开本地 seekdb，建立带向量列与 HNSW 索引的表，写入样例向量后做最近邻检索。注意向量索引异步构建，写入后立即近似检索可能召回为空，小数据量可先用精确排序兜底。
    id=d1d837348edd  2026-10-28

[3] 数据库系统：B+ 树索引为什么比哈希索引更适合范围查询  (study, 数据库,索引,B+树,课程笔记)
    B+ 树是平衡多路搜索树，叶子节点通过链表相连，天然支持按主键有序扫描与范围查询；哈希索引只能做等值匹配，遇到区间条件需要全量回表。课程作业中常考聚簇索引与二级索引的回表区别。
    id=803b8ca36f0d  2026-10-12
```

## 样例 4：按类别过滤

**输入 / 操作**：

```bash
python -m src.cli list --category work
```

**预期结果**：只返回 2 条 `work` 类别条目（周报、会议纪要），不出现学习/科研类。

**seekdb 作用记录**：元数据标量过滤（`where={"category": "work"}`），与检索支路叠加。

## 样例 5：新增与删除（写入闭环）

**输入 / 操作**：

```bash
python -m src.cli add --title "实验记录：混合检索对比" --content "对比向量、全文与混合三种召回的命中率" --category research --tags 实验,混合检索
python -m src.cli count                       # 预期：8 条
python -m src.cli delete <上一步返回的 note_id>
python -m src.cli count                       # 预期：回到 7 条
```

**预期结果**：新增后计数 +1，删除后计数 -1，写入与删除闭环正常。

**seekdb 作用记录**：`upsert` 写入文档、向量与元数据；`delete` 按主键移除条目。

## 样例 6：自动化自测（一键回归）

**输入 / 操作**：

```bash
python scripts/selftest.py
```

**预期结果**：9 项断言全部 `PASS`，末尾输出 `全部通过 ✅`，退出码为 0。

**覆盖点**：写入计数、全文命中、向量召回、混合召回、类别过滤、删除计数。

## 可选：本地 Web API 演示

```bash
uvicorn src.demo_web:app --port 8000
# 健康检查： GET http://127.0.0.1:8000/api/health
# 检索示例： GET http://127.0.0.1:8000/api/search?q=周报&mode=hybrid
```

## 技术结合核对清单（提交前自查）

- [x] 仓库内可看到对 `pyseekdb` 的真实调用（`src/repository.py`），而非仅安装依赖。
- [x] 终端可复现样例 1–5 的检索/写入结果（2026-11-05 实测输出见 `screenshots/validation-output.txt`）。
- [x] 自测脚本 `scripts/selftest.py` 全部通过（9 项 PASS，`全部通过 ✅`）。
- [x] 检索结果与初始数据对应关系正确，可在评审环境复现。
