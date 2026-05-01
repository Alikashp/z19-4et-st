from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date

import httpx

from services.llm import generate_text

OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_WORKS_URL = "https://api.crossref.org/works"
MIN_YEAR = 2021
REQUEST_TIMEOUT = httpx.Timeout(connect=8.0, read=15.0, write=8.0, pool=8.0)

OPENALEX_TYPES_BY_MODE = {
    "articles": ["article"],
    "books": ["book", "book-chapter", "monograph"],
    "standards": ["standard"],
    "reports": ["report"],
    "mixed": ["article", "book", "book-chapter", "monograph", "report", "standard"],
}

CROSSREF_ALLOWED_TYPES = {
    "journal-article", "book", "book-chapter", "monograph", "report", "standard", "proceedings-article"
}

CURATED_REGISTRY = {
    "project management": [
        {
            "title": "A Guide to the Project Management Body of Knowledge (PMBOK® Guide)",
            "authors": ["Project Management Institute"],
            "year": 2021,
            "publisher": "Project Management Institute",
            "source": "Project Management Institute",
            "doi": "",
            "landing_page_url": "",
            "source_type": "standard",
            "publication_date": "2021-01-01",
            "standard_number": "PMBOK 7",
        }
    ],
    "information security": [
        {
            "title": "ISO/IEC 27001:2022 Information security, cybersecurity and privacy protection — Information security management systems — Requirements",
            "authors": ["ISO/IEC"],
            "year": 2022,
            "publisher": "ISO",
            "source": "ISO/IEC",
            "doi": "",
            "landing_page_url": "",
            "source_type": "standard",
            "publication_date": "2022-01-01",
            "standard_number": "ISO/IEC 27001:2022",
        }
    ],
}


@dataclass
class SourceRecord:
    title: str
    authors: list[str]
    year: int | None
    source: str
    publisher: str
    doi: str
    work_type: str
    source_type: str
    publication_date: str
    landing_page_url: str
    standard_number: str
    openalex_id: str
    verified_by_crossref: bool = False


class SourcesPipelineError(RuntimeError):
    pass


def _normalize_doi(raw: str | None) -> str:
    if not raw:
        return ""
    doi = raw.strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    return doi.lower()


def _normalize_title(raw: str) -> str:
    cleaned = re.sub(r"\s+", " ", (raw or "").strip().lower())
    return re.sub(r"[^\w\s]", "", cleaned)


def _extract_standard_number(title: str) -> str:
    match = re.search(r"\b(?:ISO|IEC|ISO/IEC|IEEE)\s?[\w\-/.:]+", title or "", re.IGNORECASE)
    return match.group(0).strip() if match else ""


def _parse_year(item: dict) -> int | None:
    pub_date = item.get("publication_date") or ""
    year = item.get("publication_year")
    if year is None and pub_date:
        try:
            year = date.fromisoformat(pub_date).year
        except ValueError:
            year = None
    return year


def _is_reliable_openalex_metadata(record: SourceRecord) -> bool:
    if record.source_type == "book":
        return bool(record.title and record.year and (record.publisher or record.source))
    if record.source_type == "standard":
        return bool(record.title and record.year and (record.standard_number or record.source))
    return bool(record.title and record.year and (record.source or record.publisher) and record.authors)


def _map_source_type(openalex_type: str) -> str:
    mapped = {
        "article": "article",
        "book": "book",
        "book-chapter": "book",
        "monograph": "book",
        "report": "report",
        "standard": "standard",
    }
    return mapped.get((openalex_type or "").lower(), "article")


async def _search_openalex_by_types(topic: str, requested_count: int, openalex_types: list[str]) -> list[SourceRecord]:
    per_page = min(max(requested_count * 4, 20), 100)
    params = {
        "search": topic,
        "filter": f"from_publication_date:{MIN_YEAR}-01-01,type:{'|'.join(openalex_types)}",
        "sort": "cited_by_count:desc",
        "per-page": per_page,
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        try:
            response = await client.get(OPENALEX_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SourcesPipelineError(f"Ошибка OpenAlex API: {exc}") from exc

    results = response.json().get("results", [])
    records: list[SourceRecord] = []
    for item in results:
        year = _parse_year(item)
        if not year or year < MIN_YEAR:
            continue
        openalex_type = (item.get("type") or "").strip()
        title = (item.get("title") or "").strip()
        records.append(SourceRecord(
            title=title,
            authors=[a.get("author", {}).get("display_name", "").strip() for a in item.get("authorships", []) if a.get("author", {}).get("display_name")],
            year=year,
            source=(item.get("primary_location", {}).get("source", {}).get("display_name") or "").strip(),
            publisher=(item.get("primary_location", {}).get("source", {}).get("host_organization_name") or "").strip(),
            doi=_normalize_doi(item.get("doi")),
            work_type=openalex_type,
            source_type=_map_source_type(openalex_type),
            publication_date=item.get("publication_date") or "",
            landing_page_url=(item.get("primary_location", {}).get("landing_page_url") or "").strip(),
            standard_number=_extract_standard_number(title),
            openalex_id=item.get("id") or "",
        ))
    return records


def _inject_curated_sources(topic: str) -> list[SourceRecord]:
    t = topic.lower()
    records: list[SourceRecord] = []
    for key, items in CURATED_REGISTRY.items():
        if key in t:
            for i in items:
                if i["year"] < MIN_YEAR:
                    continue
                records.append(SourceRecord(
                    title=i["title"],
                    authors=i["authors"],
                    year=i["year"],
                    source=i["source"],
                    publisher=i["publisher"],
                    doi=_normalize_doi(i["doi"]),
                    work_type=i["source_type"],
                    source_type=i["source_type"],
                    publication_date=i["publication_date"],
                    landing_page_url=i["landing_page_url"],
                    standard_number=i["standard_number"],
                    openalex_id="curated",
                    verified_by_crossref=True,
                ))
    return records


async def _verify_single_with_crossref(client: httpx.AsyncClient, source: SourceRecord) -> tuple[bool, int | None]:
    try:
        if source.doi:
            resp = await client.get(f"{CROSSREF_WORKS_URL}/{source.doi}")
        else:
            resp = await client.get(CROSSREF_WORKS_URL, params={"query.title": source.title, "rows": 1})
        resp.raise_for_status()
    except httpx.HTTPError:
        return False, source.year

    msg = resp.json().get("message", {})
    item = msg if source.doi else (msg.get("items", [{}])[0] if isinstance(msg, dict) else {})
    cr_type = (item.get("type") or "").lower()
    if cr_type and cr_type not in CROSSREF_ALLOWED_TYPES:
        return False, source.year

    cr_title = " ".join(item.get("title", [])).strip() if isinstance(item.get("title"), list) else (item.get("title") or "")
    if not source.doi and _normalize_title(cr_title) != _normalize_title(source.title):
        return False, source.year

    year_parts = item.get("published-print", {}).get("date-parts") or item.get("published-online", {}).get("date-parts")
    cr_year = year_parts[0][0] if year_parts and year_parts[0] else source.year
    if cr_year and cr_year < MIN_YEAR:
        return False, cr_year

    return True, cr_year


async def verify_sources_with_crossref(openalex_sources: list[SourceRecord]) -> list[SourceRecord]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        checks = await asyncio.gather(*[_verify_single_with_crossref(client, src) for src in openalex_sources], return_exceptions=True)

    verified: list[SourceRecord] = []
    for source, result in zip(openalex_sources, checks):
        if isinstance(result, Exception):
            ok, year = False, source.year
        else:
            ok, year = result
        source.verified_by_crossref = ok
        if year:
            source.year = year
        if source.year and source.year >= MIN_YEAR and (ok or _is_reliable_openalex_metadata(source)):
            verified.append(source)

    return _dedupe_sources(verified)


def _dedupe_sources(records: list[SourceRecord]) -> list[SourceRecord]:
    seen_doi: set[str] = set()
    seen_titles: set[str] = set()
    seen_standards: set[str] = set()
    unique: list[SourceRecord] = []
    for rec in records:
        if rec.doi and rec.doi in seen_doi:
            continue
        t = _normalize_title(rec.title)
        if t and t in seen_titles:
            continue
        s = _normalize_title(rec.standard_number)
        if s and s in seen_standards:
            continue
        if rec.doi:
            seen_doi.add(rec.doi)
        if t:
            seen_titles.add(t)
        if s:
            seen_standards.add(s)
        unique.append(rec)
    return unique


def _select_mixed_sources(sources: list[SourceRecord], count: int) -> list[SourceRecord]:
    buckets: dict[str, list[SourceRecord]] = {"article": [], "book": [], "standard": [], "report": []}
    for s in sources:
        buckets.setdefault(s.source_type, []).append(s)

    quotas = {
        "article": max(1, round(count * 0.5)),
        "book": max(1, round(count * 0.25)),
        "standard": max(1, round(count * 0.15)),
        "report": max(1, round(count * 0.15)),
    }
    selected: list[SourceRecord] = []
    for kind in ["article", "book", "standard", "report"]:
        selected.extend(buckets.get(kind, [])[:quotas[kind]])
    if len(selected) < count:
        leftovers = [s for s in sources if s not in selected]
        selected.extend(leftovers[: max(0, count - len(selected))])
    return selected[:count]


def _build_format_prompt(verified_sources: list[SourceRecord], fmt: str) -> str:
    lines = []
    for i, src in enumerate(verified_sources, start=1):
        lines.append(
            f"{i}) source_type={src.source_type}; title={src.title}; authors={', '.join(src.authors) if src.authors else 'N/A'}; "
            f"year={src.year or 'N/A'}; source={src.source or 'N/A'}; publisher={src.publisher or 'N/A'}; doi={src.doi or 'N/A'}; "
            f"publication_date={src.publication_date or 'N/A'}; standard_number={src.standard_number or 'N/A'}; url={src.landing_page_url or 'N/A'}"
        )
    return (
        f"Оформи ТОЛЬКО переданные verified_sources в формате {fmt}.\n"
        "Не ищи и не добавляй источники из памяти.\n"
        "Запрещено придумывать авторов, страницы, DOI, ISBN, URL, издательства.\n"
        "Учитывай source_type: article/book/standard/report.\n"
        "Если данных не хватает — оформляй только имеющиеся. Не переводи и не транслитерируй иностранные названия.\n"
        "Верни только список без комментариев.\n\n"
        "verified_sources:\n" + "\n".join(lines)
    )


async def generate_sources_by_topic(topic: str, count: int, fmt: str, mode: str = "mixed") -> str:
    mode = mode if mode in OPENALEX_TYPES_BY_MODE else "mixed"
    openalex_sources = await _search_openalex_by_types(topic, count, OPENALEX_TYPES_BY_MODE[mode])
    curated = _inject_curated_sources(topic) if mode in {"mixed", "standards"} else []
    all_candidates = _dedupe_sources(openalex_sources + curated)
    if not all_candidates:
        return "Надежные источники по теме не найдены (OpenAlex/registry не вернули релевантные записи)."

    verified = await verify_sources_with_crossref(all_candidates)
    if mode == "mixed":
        verified = _select_mixed_sources(verified, count)
    else:
        verified = verified[:count]

    if not verified:
        return "Надежные источники по теме не найдены после проверки в Crossref/OpenAlex."

    formatted = await generate_text(_build_format_prompt(verified, fmt), max_tokens=2000)
    if len(verified) < count:
        return f"⚠️ Надежных источников найдено меньше запрошенного ({len(verified)} из {count}).\n\n{formatted}"
    return formatted