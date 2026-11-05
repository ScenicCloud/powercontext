"""文本向量化模块。

为保证项目在任何机器上「零外部依赖、开箱即用」，默认使用内置的离线
哈希 n-gram 向量（确定性、可复现、无需下载模型或调用联网 API）。

生产/进阶场景可实现同一个 ``embed`` / ``embed_batch`` 接口，替换为
真实 embedding 模型（如 DashScope text-embedding、OpenAI text-embedding-3
或本地 sentence-transformers），只需保证返回维度与建库时 ``DIMENSION`` 一致。
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import List

# 英文单词 / 数字；中文按单字 + 相邻二字组词
_EN_TOKEN = re.compile(r"[a-z0-9]+")
_ZH_CHAR = re.compile(r"[\u4e00-\u9fff]")


class OfflineEmbedder:
    """离线确定性向量器：词项哈希到固定维度，TF 计数后 L2 归一化（配余弦距离）。"""

    def __init__(self, dimension: int = 256):
        self.dimension = dimension

    def _tokens(self, text: str) -> List[str]:
        text = (text or "").lower()
        en = _EN_TOKEN.findall(text)
        zh = _ZH_CHAR.findall(text)
        zh_bi = [zh[i] + zh[i + 1] for i in range(len(zh) - 1)]
        return en + zh + zh_bi

    def embed(self, text: str) -> List[float]:
        vec = [0.0] * self.dimension
        for tok in self._tokens(text):
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            vec[h % self.dimension] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.embed(t) for t in texts]
