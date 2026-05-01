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
CROSSREF_ALLOWED_TYPES = {"journal-article", "book", "book-chapter", "monograph", "report", "standard", "proceedings-article"}

CURATED_REGISTRY = {
    "project management": [
        {"title": "A Guide to the Project Management Body of Knowledge (PMBOK® Guide)", "authors": ["Project Management Institute"], "year": 2021, "publisher": "Project Management Institute", "source": "Project Management Institute", "source_type": "standard", "standard_number": "PMBOK 7"},
        {"title": "ISO 21502:2020 Project, programme and portfolio management — Guidance on project management", "authors": ["ISO"], "year": 2020, "publisher": "ISO", "source": "ISO", "source_type": "standard", "standard_number": "ISO 21502:2020"},
    ]
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
    volume: str
    issue: str
    pages: str
    openalex_id: str
    verified_by_crossref: bool = False


class SourcesPipelineError(RuntimeError):
    pass


def _normalize_doi(raw: str | None) -> str:
    if not raw:
        return ""
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", raw.strip(), flags=re.IGNORECASE).lower()


def _normalize_title(raw: str) -> str:
    return re.sub(r"[^\w\s]", "", re.sub(r"\s+", " ", (raw or "").strip().lower()))


def _normalize_person_name(name: str) -> str:
    value = (name or "").strip()
    if value.isupper() and any(ch.isalpha() for ch in value):
        return value.title()
    return value


def _extract_standard_number(title: str) -> str:
    match = re.search(r"\b(?:ISO|IEC|ISO/IEC|IEEE)\s?[\w\-/.:]+", title or "", re.IGNORECASE)
    return match.group(0).strip() if match else ""


def _parse_openalex_year(item: dict) -> int | None:
    year = item.get("publication_year")
    if year:
        return year
    pub_date = item.get("publication_date") or ""
    try:
        return date.fromisoformat(pub_date).year if pub_date else None
    except ValueError:
        return None


def _is_reliable_openalex_metadata(record: SourceRecord) -> bool:
    if record.source_type == "standard":
        return bool(record.title and record.year and (record.standard_number or record.source))
    if record.source_type == "book":
        return bool(record.title and record.year and (record.publisher or record.source))
    return bool(record.title and record.year and record.source)


async def _search_openalex_by_types(topic: str, requested_count: int, openalex_types: list[str]) -> list[SourceRecord]:
    params = {
        "search": topic,
        "filter": f"type:{'|'.join(openalex_types)}",
        "sort": "cited_by_count:desc",
        "per-page": min(max(requested_count * 5, 30), 120),
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        try:
            response = await client.get(OPENALEX_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SourcesPipelineError(f"Ошибка OpenAlex API: {exc}") from exc

    records: list[SourceRecord] = []
    for item in response.json().get("results", []):
        year = _parse_openalex_year(item)
        if not year:
            continue
        t = (item.get("type") or "").strip().lower()
        mapped = "book" if t in {"book", "book-chapter", "monograph"} else ("standard" if t == "standard" else ("report" if t == "report" else "article"))
        biblio = item.get("biblio", {}) or {}
        title = (item.get("title") or "").strip()
        records.append(SourceRecord(
            title=title,
            authors=[_normalize_person_name(a.get("author", {}).get("display_name", "")) for a in item.get("authorships", []) if a.get("author", {}).get("display_name")],
            year=year,
            source=(item.get("primary_location", {}).get("source", {}).get("display_name") or "").strip(),
            publisher=(item.get("primary_location", {}).get("source", {}).get("host_organization_name") or "").strip(),
            doi=_normalize_doi(item.get("doi")),
            work_type=t,
            source_type=mapped,
            publication_date=item.get("publication_date") or "",
            landing_page_url=(item.get("primary_location", {}).get("landing_page_url") or "").strip(),
            standard_number=_extract_standard_number(title),
            volume=str(biblio.get("volume") or ""),
            issue=str(biblio.get("issue") or ""),
            pages=(f"{biblio.get('first_page','')}-{biblio.get('last_page','')}".strip("-") if (biblio.get("first_page") or biblio.get("last_page")) else ""),
            openalex_id=item.get("id") or "",
        ))
    return records


def _inject_curated_sources(topic: str) -> list[SourceRecord]:
    out: list[SourceRecord] = []
    for k, items in CURATED_REGISTRY.items():
        if k in topic.lower():
            for i in items:
                if i["year"] < MIN_YEAR:
                    continue
                out.append(SourceRecord(
                    title=i["title"], authors=i["authors"], year=i["year"], source=i["source"], publisher=i["publisher"], doi="", work_type=i["source_type"], source_type=i["source_type"], publication_date=f"{i['year']}-01-01", landing_page_url="", standard_number=i["standard_number"], volume="", issue="", pages="", openalex_id="curated", verified_by_crossref=True
                ))
    return out


def _crossref_year(item: dict, fallback: int | None) -> int | None:
    for key in ("published-print", "published-online", "created", "issued"):
        parts = item.get(key, {}).get("date-parts") if isinstance(item.get(key), dict) else None
        if parts and parts[0]:
            return parts[0][0]
    return fallback


async def _verify_single_with_crossref(client: httpx.AsyncClient, source: SourceRecord) -> tuple[bool, SourceRecord]:
    if source.openalex_id == "curated":
        return True, source
    try:
        resp = await (client.get(f"{CROSSREF_WORKS_URL}/{source.doi}") if source.doi else client.get(CROSSREF_WORKS_URL, params={"query.title": source.title, "rows": 1}))
        resp.raise_for_status()
    except httpx.HTTPError:
        return False, source

    msg = resp.json().get("message", {})
    item = msg if source.doi else (msg.get("items", [{}])[0] if isinstance(msg, dict) else {})
    ctype = (item.get("type") or "").lower()
    if ctype and ctype not in CROSSREF_ALLOWED_TYPES:
        return False, source

    cr_title = " ".join(item.get("title", [])) if isinstance(item.get("title"), list) else (item.get("title") or "")
    if not source.doi and _normalize_title(cr_title) != _normalize_title(source.title):
        return False, source

    source.year = _crossref_year(item, source.year)
    if not source.year or source.year < MIN_YEAR:
        return False, source

    source.volume = str(item.get("volume") or source.volume or "")
    source.issue = str(item.get("issue") or source.issue or "")
    source.pages = str(item.get("page") or source.pages or "")
    source.publisher = item.get("publisher") or source.publisher
    source.source = (item.get("container-title", [""])[0] if isinstance(item.get("container-title"), list) else item.get("container-title")) or source.source
    source.authors = [_normalize_person_name(f"{a.get('family','')} {a.get('given','')}") for a in item.get("author", [])] or source.authors
    source.title = cr_title.strip() or source.title
    source.verified_by_crossref = True
    return True, source


async def verify_sources_with_crossref(candidates: list[SourceRecord]) -> list[SourceRecord]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        checked = await asyncio.gather(*[_verify_single_with_crossref(client, s) for s in candidates], return_exceptions=True)
    verified: list[SourceRecord] = []
    for source, result in zip(candidates, checked):
        if isinstance(result, Exception):
            ok, enriched = False, source
        else:
            ok, enriched = result
        if enriched.year and enriched.year >= MIN_YEAR and (ok or _is_reliable_openalex_metadata(enriched)):
            verified.append(enriched)
    return _dedupe_sources(verified)


def _dedupe_sources(records: list[SourceRecord]) -> list[SourceRecord]:
    seen_doi, seen_title, seen_std = set(), set(), set()
    out = []
    for r in records:
        if r.doi and r.doi in seen_doi:
            continue
        t = _normalize_title(r.title)
        if t and t in seen_title:
            continue
        s = _normalize_title(r.standard_number)
        if s and s in seen_std:
            continue
        if r.doi:
            seen_doi.add(r.doi)
        if t:
            seen_title.add(t)
        if s:
            seen_std.add(s)
        out.append(r)
    return out


def _select_mixed_sources(sources: list[SourceRecord], count: int) -> list[SourceRecord]:
    quotas = {"article": round(count * 0.5), "book": round(count * 0.25), "standard": round(count * 0.15), "report": round(count * 0.1)}
    picked: list[SourceRecord] = []
    for typ in ["article", "book", "standard", "report"]:
        bucket = [s for s in sources if s.source_type == typ]
        picked.extend(bucket[:max(1, quotas[typ])])
    if len(picked) < count:
        picked.extend([s for s in sources if s not in picked][:count - len(picked)])
    return picked[:count]


def _build_format_prompt(verified_sources: list[SourceRecord], fmt: str) -> str:
    lines = []
    for i, s in enumerate(verified_sources, start=1):
        doi = f"DOI: {s.doi}" if s.doi else "DOI: N/A"
        lines.append(f"{i}) source_type={s.source_type}; title={s.title}; authors={', '.join(s.authors) if s.authors else 'N/A'}; year={s.year}; source={s.source or 'N/A'}; publisher={s.publisher or 'N/A'}; volume={s.volume or 'N/A'}; issue={s.issue or 'N/A'}; pages={s.pages or 'N/A'}; {doi}; standard_number={s.standard_number or 'N/A'}")
    return (
        f"Оформи ТОЛЬКО verified_sources в формате {fmt}.\n"
        "GPT только оформляет, не ищет и не добавляет источники из памяти.\n"
        "Не придумывай год, страницы, DOI, авторов, журнал, издательство, ISBN, URL.\n"
        "Не переводи названия. Русские оставляй на русском, английские на английском.\n"
        "Не пиши авторов КАПСОМ. Для DOI используй единый вид: DOI: 10.xxxx/xxxx.\n"
        "URL вида doi.org добавляй только если формат явно требует URL.\n"
        "Учитывай source_type (article/book/standard/report). Верни только список.\n\n"
        "verified_sources:\n" + "\n".join(lines)
    )


async def generate_sources_by_topic(topic: str, count: int, fmt: str, mode: str = "mixed") -> str:
    mode = mode if mode in OPENALEX_TYPES_BY_MODE else "mixed"
    candidates = await _search_openalex_by_types(topic, count, OPENALEX_TYPES_BY_MODE[mode])
    if mode in {"mixed", "standards"}:
        candidates.extend(_inject_curated_sources(topic))
    verified = await verify_sources_with_crossref(_dedupe_sources(candidates))
    verified = _select_mixed_sources(verified, count) if mode == "mixed" else verified[:count]
    if not verified:
        return "Надежные источники по теме не найдены после проверки в Crossref/OpenAlex."
    formatted = await generate_text(_build_format_prompt(verified, fmt), max_tokens=2000)
    return (f"⚠️ Надежных источников найдено меньше запрошенного ({len(verified)} из {count}).\n\n{formatted}" if len(verified) < count else formatted)
