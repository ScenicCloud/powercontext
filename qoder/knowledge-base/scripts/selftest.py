"""全链路自测：在临时目录建库并验证 seekdb 写入 / 全文 / 向量 / 混合 / 过滤 / 删除。

运行：
    python scripts/selftest.py

退出码 0 表示全部断言通过；非 0 表示存在失败项。
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.models import Note  # noqa: E402
from src.repository import NoteRepository  # noqa: E402


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="seekdb_selftest_"))
    db_path = str(tmp / "knowledge.db")
    sample = json.loads((ROOT / "data" / "sample_notes.json").read_text(encoding="utf-8"))
    notes = [Note(**item) for item in sample]

    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" —— {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    repo = NoteRepository(db_path=db_path)
    repo.bulk_upsert(notes)
    # seekdb 向量索引异步构建，短暂等待以保证近似召回稳定
    time.sleep(2)

    # 1. 写入计数
    check("写入 7 条样例", repo.count() == 7, f"count={repo.count()}")

    # 2. 全文检索：关键词「周报」应命中工作类条目
    ft = repo.search_fulltext("周报", top_k=5)
    check("全文检索「周报」有命中", len(ft) > 0, f"命中 {len(ft)} 条")
    check("全文检索命中条目含 work 类别", any(x["category"] == "work" for x in ft))

    # 3. 向量检索：查询「补码 溢出 判断」应召回组成原理笔记（弱语义，允许在前 3 条内）
    vv = repo.search_vector("补码表示 定点数 溢出判断", top_k=3)
    check("向量检索非空", len(vv) > 0, f"命中 {len(vv)} 条")
    check("向量检索召回组成原理笔记", any("补码" in x["title"] for x in vv))

    # 4. 混合检索：「混合检索 RRF 融合」应召回国检索文献摘要
    hy = repo.search_hybrid("向量 全文 混合检索 RRF 融合", top_k=5)
    check("混合检索非空", len(hy) > 0, f"命中 {len(hy)} 条")
    check("混合检索召回国检索论文笔记", any("混合检索" in x["title"] for x in hy))

    # 5. 元数据过滤：只看 work 类别
    work = repo.list_all(category="work")
    check("类别过滤 work 仅返回 work", all(x["category"] == "work" for x in work) and len(work) >= 2,
          f"work={len(work)} 条")

    # 6. 删除一条后计数下降
    target = work[0]["note_id"]
    repo.delete(target)
    check("删除后计数减 1", repo.count() == 6, f"count={repo.count()}")

    repo.close()
    shutil.rmtree(tmp, ignore_errors=True)

    print("\n结果：" + ("全部通过 ✅" if not failures else f"{len(failures)} 项失败：{failures}"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
