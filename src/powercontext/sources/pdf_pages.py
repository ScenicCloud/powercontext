# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Page-level Sources parsed from one complete offline PDF document."""

from __future__ import annotations

import hashlib
import io
import math
import re
from collections import Counter
from urllib.parse import quote, unquote

from pydantic import BaseModel

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PDF_PAGE_SOURCE_NAME = "pdf-page"

_TOKEN = re.compile(r"[a-z]+|\d+")
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
_ITEM_HEADING = re.compile(
    r"^item\s*(1a|1b|1|2|3|4|5|6|7a|7|8|9a|9b|9c|9|10|11|12|13|14|15)\s*[.:]",
    re.IGNORECASE,
)
_STOPWORDS = frozenset(
    """a an the of in on at to for from by as is are was were be been being has have had do does did
    what which who whom whose when where why how many much any some all that this these those it its
    with within without and or not no but if then than so such can could should would may might will
    give given response respond answer question state stated stating rely relying detail details shown
    show define defined according assume assuming perspective analyst only use used using also
    there their they them we our us i you he she""".split()
)
_GENERIC_DOCUMENT_TOKENS = frozenset(
    {"company", "corporation", "annual", "report", "form", "fiscal", "year", "financial", "statements"}
)

_QUERY_EXPANSIONS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"geograph|region|countr|global|worldwide", re.I),
     ("countries", "territories", "regions", "geographic", "worldwide")),
    (re.compile(r"legal|litigation|lawsuit|proceeding", re.I), ("proceedings", "litigation", "lawsuits", "legal")),
    (re.compile(r"employee|headcount|people|associate|workforce", re.I), ("employees", "headcount")),
    (re.compile(r"dividend|payout", re.I), ("dividends", "dividend")),
    (re.compile(r"repurchas|buyback", re.I), ("repurchase", "repurchased")),
    (re.compile(r"pension|retiree|retirement", re.I), ("pension", "retiree", "retirement")),
    (re.compile(r"goodwill|intangible|impair", re.I), ("goodwill", "intangible", "impairment")),
    (re.compile(r"acquisition|divestiture|merger", re.I), ("acquisitions", "divestitures", "merger")),
    (re.compile(r"supply chain|supplier|raw material|commodit", re.I),
     ("suppliers", "commodities", "materials", "components")),
    (re.compile(r"customer|client|retailer|retention", re.I), ("customers", "clients", "retention")),
    (re.compile(r"cyclical|seasonal|cycle", re.I), ("cyclical", "seasonal", "cycles")),
    (re.compile(r"tax", re.I), ("tax", "taxes", "rate")),
    (re.compile(r"debt|borrowings|leverage", re.I), ("debt", "borrowings")),
    (re.compile(r"lease", re.I), ("lease", "leases")),
    (re.compile(r"inventor", re.I), ("inventories", "inventory")),
    (re.compile(r"receivab", re.I), ("receivables",)),
    (re.compile(r"liquidity|ratio", re.I), ("liquidity", "assets", "liabilities")),
    (re.compile(r"production|manufactur|rate", re.I), ("production", "rate", "manufacturing")),
)
_STATEMENT_TERMS: dict[str, tuple[str, ...]] = {
    "income": ("statement", "income", "revenue", "operating", "profit", "sales", "earnings", "cost", "gross"),
    "cash": ("statement", "cash", "flows", "depreciation", "amortization", "capital", "expenditures", "investing"),
    "balance": ("balance", "sheet", "assets", "liabilities", "equity"),
}
_STATEMENT_INTENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"income statement|statement of income|statement of operations|profit|margin|revenue|sales|ebitda|"
                r"operating income|earnings|cost of sales|gross|effective tax rate", re.I), "income"),
    (re.compile(r"cash flow|cash flows|capex|capital expenditure|depreciation|amortization|free cash|ebitda", re.I),
     "cash"),
    (re.compile(r"balance sheet|total assets|total liabilit|shareholders.? equity|largest liabilit|largest asset|"
                r"quick ratio|current ratio|liquidity", re.I), "balance"),
)
_ANCHOR_PATTERNS: dict[str, re.Pattern[str]] = {
    "income": re.compile(r"^\s*(?:consolidated )?statements? of (?:income|operations|earnings)", re.I | re.M),
    "balance": re.compile(r"^\s*(?:consolidated )?(?:balance sheets?|statements? of financial (?:position|condition))",
                          re.I | re.M),
    "cash": re.compile(r"^\s*(?:consolidated )?statements? of cash flows?", re.I | re.M),
    "geographic": re.compile(r"geographic (?:operations|regions|areas|information)", re.I),
    "segment": re.compile(r"(?:summary of business )?segment (?:data|information|reporting)|reportable segments", re.I),
    "tax_rate": re.compile(r"effective tax rate", re.I),
    "retention": re.compile(r"retention", re.I),
    "summary": re.compile(r"summary of (?:financial|selected) (?:performance|data)|selected financial data", re.I),
    "restructuring": re.compile(r"restructuring and impairment charges|productivity plan|restructuring charges", re.I),
    "liquidity": re.compile(r"liquidity and capital resources|quick ratio|current ratio", re.I),
    "customers": re.compile(r"customer concentration|significant customers?|major customers?|"
                            r"concentration of (?:credit )?risk|customer(?:s)? account(?:ed|s)? for", re.I),
    "production": re.compile(r"production rates?|rate increases?|rate changes?", re.I),
    "securities": re.compile(r"securities (?:are |which )?registered|registered pursuant to section 12", re.I),
    "legal": re.compile(r"legal proceedings?|litigation|contingenc(?:y|ies)", re.I),
}
_ANCHOR_INTENTS: tuple[tuple[re.Pattern[str], str, float], ...] = (
    (re.compile(r"tax", re.I), "tax_rate", 16.0),
    (re.compile(r"geograph|countr|regions", re.I), "geographic", 18.0),
    (re.compile(r"customer|client|concentration", re.I), "customers", 16.0),
    (re.compile(r"retain|retention|card member", re.I), "retention", 16.0),
    (re.compile(r"restructur", re.I), "restructuring", 16.0),
    (re.compile(r"liquidity|ratio", re.I), "liquidity", 14.0),
    (re.compile(r"segment|product categor|reportable", re.I), "segment", 16.0),
    (re.compile(r"production|manufactur|rate", re.I), "production", 14.0),
    (re.compile(r"registered|securities", re.I), "securities", 16.0),
    (re.compile(r"legal|litigation|lawsuit|proceeding", re.I), "legal", 20.0),
    (re.compile(r"margin|income|revenue|profit|earnings|ebitda|gross|cost of sales|tax", re.I), "summary", 6.0),
)
_SECTION_INTENTS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"geograph|countr|regions|operates? in", re.I), ("1",)),
    (re.compile(r"legal|litigation|lawsuit|proceeding|battle", re.I), ("3",)),
    (re.compile(r"customer|client|cyclical|seasonal|supplier|competit|risk", re.I), ("1", "1a")),
    (re.compile(r"retain|retention|card member", re.I), ("1", "1a", "7")),
    (re.compile(r"production|manufactur", re.I), ("1", "1a", "7")),
)
_STATEMENT_WEIGHT = 26.0
_SECTION_WEIGHT = 12.0
_DOCUMENT_WEIGHT = 18.0
_NEIGHBOUR_WEIGHTS = ((1, 5.0), (-1, 5.0), (2, 3.0), (-2, 3.0))
_BM25_K1 = 1.2
_BM25_B = 0.75
_MAX_SECTION_LENGTH = 18


class PDFDocumentInput(BaseModel):
    """Complete offline PDF bytes identified by a caller-stable document ID."""

    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    """One physical PDF page and the digest of the document it came from."""

    document_id: str
    document_sha256: str
    page_number: int
    text: str


class PDFPageSource(Source):
    """Captured physical page that can be cited back to its original revision."""

    source_id: str
    document_id: str
    document_sha256: str
    page_number: int
    text: str


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    """Build the stable identity of one physical page in one document revision."""

    if not document_id or not document_id.strip():
        raise ValueError("document_id must be a non-empty string")
    if page_number < 1:
        raise ValueError("page_number must be positive")
    source_id = f"pdf:{document_sha256}:{page_number}:{quote(document_id, safe='')}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"pdf page source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters")
    return source_id


def parse_pdf_document(value: PDFDocumentInput, /) -> tuple[PDFPageInput, ...]:
    """Parse every physical page of one complete PDF document atomically."""

    if not value.document_id or not value.document_id.strip():
        raise ValueError("document_id must be a non-empty string")
    if not value.content:
        raise ValueError("PDF content must not be empty")
    digest = hashlib.sha256(value.content).hexdigest()

    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(value.content))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a non-empty user password")
        pages = tuple(
            PDFPageInput(
                document_id=value.document_id,
                document_sha256=digest,
                page_number=index,
                text=page.extract_text() or "",
            )
            for index, page in enumerate(reader.pages, start=1)
        )
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("PDF content could not be parsed") from error

    return pages


class PDFPageAdapter:
    """Resolve and read captured PDF pages."""

    input_class = PDFPageInput
    name = PDF_PAGE_SOURCE_NAME
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        source_id = pdf_page_source_id(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class PDFPageTextEvidenceProjection:
    """Expose one page as document-scoped text evidence."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.source_id,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


class _PageRecord:
    """One Memory entry that carries exactly one physical page of one PDF."""

    __slots__ = (
        "anchors",
        "document_id",
        "entry_id",
        "entry_version_id",
        "item_codes",
        "memory_ref",
        "page_number",
        "term_frequencies",
        "text",
        "tokens",
    )

    def __init__(
        self,
        *,
        document_id: str,
        page_number: int,
        text: str,
        memory_ref,
        entry_id: str,
        entry_version_id: str,
    ) -> None:
        self.document_id = document_id
        self.page_number = page_number
        self.text = text
        self.memory_ref = memory_ref
        self.entry_id = entry_id
        self.entry_version_id = entry_version_id
        self.tokens = _TOKEN.findall(text.lower())
        self.term_frequencies = Counter(self.tokens)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        self.item_codes = tuple(match.group(1).lower() for line in lines if (match := _ITEM_HEADING.match(line)))
        self.anchors = frozenset(name for name, pattern in _ANCHOR_PATTERNS.items() if pattern.search(text))


def _page_records(entries) -> list[_PageRecord]:
    """Keep the current entry of every distinct physical page in index order."""

    records: list[_PageRecord] = []
    seen: set[tuple[str, int]] = set()
    for record in entries:
        reference = next(
            (source for source in record.entry.sources if source.source_type == PDF_PAGE_SOURCE_NAME),
            None,
        )
        if reference is None:
            continue
        parts = reference.source_id.split(":")
        if len(parts) != 4 or parts[0] != "pdf":
            continue
        try:
            page_number = int(parts[2])
        except ValueError:
            continue
        document_id = unquote(parts[3])
        identity = (document_id, page_number)
        if page_number < 1 or identity in seen:
            continue
        seen.add(identity)
        records.append(
            _PageRecord(
                document_id=document_id,
                page_number=page_number,
                text=record.entry.text,
                memory_ref=record.memory_ref,
                entry_id=record.entry.entry_id,
                entry_version_id=record.entry.entry_version_id,
            )
        )
    records.sort(key=lambda record: (record.document_id, record.page_number))
    return records


class _PageIndex:
    """BM25 index over every page of every document held by one Memory."""

    def __init__(self, records: list[_PageRecord]) -> None:
        self.records = records
        self.count = len(records)
        self.average_length = sum(len(record.tokens) for record in records) / max(1, self.count)
        self.document_frequency: Counter[str] = Counter()
        for record in records:
            self.document_frequency.update(set(record.tokens))
        self.sections = self._section_bounds()

    def _section_bounds(self) -> dict[tuple[str, str], tuple[int, int]]:
        headings: dict[str, list[tuple[int, str]]] = {}
        for record in self.records:
            if len(set(record.item_codes)) >= 4:
                continue  # Table of contents listing every Item.
            for code in record.item_codes:
                if code in {"1", "1a", "1b", "2", "3", "7", "7a", "8"}:
                    headings.setdefault(record.document_id, []).append((record.page_number, code))
        bounds: dict[tuple[str, str], tuple[int, int]] = {}
        for document_id, entries in headings.items():
            starts: dict[str, int] = {}
            for number, code in entries:
                starts.setdefault(code, number)
            ordered = sorted((number, code) for code, number in starts.items())
            for position, (start, code) in enumerate(ordered):
                end = max(record.page_number for record in self.records if record.document_id == document_id)
                for number, _ in ordered[position + 1:]:
                    end = min(end, number - 1)
                    break
                bounds[(document_id, code)] = (start, min(end, start + _MAX_SECTION_LENGTH))
        return bounds

    def _inverse_document_frequency(self, term: str) -> float:
        frequency = self.document_frequency.get(term, 0)
        return math.log(1 + (self.count - frequency + 0.5) / (frequency + 0.5))

    def score(self, query: dict[str, float]) -> list[float]:
        scores: list[float] = []
        for record in self.records:
            length = len(record.tokens)
            score = 0.0
            for term, weight in query.items():
                frequency = record.term_frequencies.get(term, 0)
                if not frequency:
                    continue
                normalization = _BM25_K1 * (1 - _BM25_B + _BM25_B * length / self.average_length)
                score += (
                    weight
                    * self._inverse_document_frequency(term)
                    * frequency
                    * (_BM25_K1 + 1)
                    / (frequency + normalization)
                )
            scores.append(score)
        return scores


def _question_terms(question: str) -> dict[str, float]:
    words = [word for word in _TOKEN.findall(question.lower()) if word not in _STOPWORDS and len(word) > 1]
    terms = dict.fromkeys(words, 1.0)
    for pattern, expansions in _QUERY_EXPANSIONS:
        if pattern.search(question):
            for expansion in expansions:
                terms.setdefault(expansion, 0.6)
    for pattern, statement in _STATEMENT_INTENTS:
        if pattern.search(question):
            for expansion in _STATEMENT_TERMS[statement]:
                terms.setdefault(expansion, 0.6)
    return terms


def _named_documents(index: _PageIndex, question: str) -> dict[str, int]:
    """Documents whose identifier is named by the question's distinctive words."""

    words = [
        word
        for word in _TOKEN.findall(question.lower())
        if len(word) >= 3 and not word.isdigit() and word not in _GENERIC_DOCUMENT_TOKENS
    ]
    matches: dict[str, int] = {}
    for document_id in {record.document_id for record in index.records}:
        name = document_id.lower()
        matches_found = sum(1 for word in words if word in name)
        if matches_found:
            matches[document_id] = matches_found
    return matches


def _rank_pages(index: _PageIndex, question: str, limit: int) -> list[_PageRecord]:
    """Rank pages by lexical relevance plus report-structure signals."""

    query = _question_terms(question)
    named = _named_documents(index, question)
    named_document = next(iter(named)) if len(named) == 1 else None
    statements = {statement for pattern, statement in _STATEMENT_INTENTS if pattern.search(question)}
    years = set(_YEAR.findall(question))
    scores = index.score(query)
    anchored: dict[str, set[int]] = {}

    for position, record in enumerate(index.records):
        if named_document is not None and record.document_id != named_document:
            scores[position] = -math.inf
            continue
        structural = False
        for statement in statements:
            if statement in record.anchors:
                scores[position] += _STATEMENT_WEIGHT
                structural = True
        for pattern, anchor, weight in _ANCHOR_INTENTS:
            if pattern.search(question) and anchor in record.anchors:
                scores[position] += weight
                structural = True
        for pattern, codes in _SECTION_INTENTS:
            if not pattern.search(question):
                continue
            for code in codes:
                bounds = index.sections.get((record.document_id, code))
                if bounds and bounds[0] <= record.page_number <= bounds[1]:
                    scores[position] += _SECTION_WEIGHT
                    break
        for year in years:
            if year in record.text:
                scores[position] += 2.0
        if named_document is None and record.document_id in named:
            scores[position] += _DOCUMENT_WEIGHT
        if structural:
            anchored.setdefault(record.document_id, set()).add(record.page_number)

    positions = {(record.document_id, record.page_number): position for position, record in enumerate(index.records)}
    for document_id, numbers in anchored.items():
        for number in numbers:
            for offset, weight in _NEIGHBOUR_WEIGHTS:
                position = positions.get((document_id, number + offset))
                if position is not None and index.records[position].document_id == document_id:
                    scores[position] += weight

    order = sorted(
        range(len(index.records)),
        key=lambda position: (
            -scores[position],
            index.records[position].document_id,
            index.records[position].page_number,
        ),
    )
    return [index.records[position] for position in order[:limit]]


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple:
    """Return exact citations for up to ``limit`` distinct retrieved pages."""

    from powercontext.builtin.artifacts.memory.models import MemoryCitation

    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")
    if not question or not question.strip():
        raise ValueError("question must be a non-empty string")

    listing = await memory.list()
    records = _page_records(listing.entries)
    if not records:
        return ()
    selected = _rank_pages(_PageIndex(records), question, limit)
    return tuple(
        MemoryCitation(
            memory_ref=record.memory_ref,
            entry_id=record.entry_id,
            entry_version_id=record.entry_version_id,
        )
        for record in selected
    )


PDF_PAGE_ADAPTER = PDFPageAdapter()
PDF_PAGE_SOURCE_DEFINITION: AdapterSourceDefinition[PDFPageInput, PDFPageSource, PDFPageInput] = (
    AdapterSourceDefinition(
        PDF_PAGE_ADAPTER,
        projections=(PDFPageTextEvidenceProjection(),),
    )
)

__all__ = [
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]
