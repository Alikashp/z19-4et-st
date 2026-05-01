from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from services.llm import generate_text

OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_WORKS_URL = "https://api.crossref.org/works"
MIN_YEAR = 2021
REQUEST_TIMEOUT = httpx.Timeout(connect=8.0, read=15.0, write=8.0, pool=8.0)


@dataclass
class SourceRecord:
    title: str
    authors: list[str]
    year: int | None
    source: str
    doi: str
    work_type: str
    publication_date: str
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


def _is_reliable_openalex_metadata(record: SourceRecord) -> bool:
    return bool(record.title and record.year and record.source and record.authors)


async def search_openalex_sources(topic: str, requested_count: int) -> list[SourceRecord]:
    per_page = min(max(requested_count * 4, 20), 100)
    params = {
        "search": topic,
        "filter": f"from_publication_date:{MIN_YEAR}-01-01",
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
        pub_date = item.get("publication_date") or ""
        year = item.get("publication_year")
        if year is None and pub_date:
            try:
                year = date.fromisoformat(pub_date).year
            except ValueError:
                year = None
        if not year or year < MIN_YEAR:
            continue

        records.append(
            SourceRecord(
                title=(item.get("title") or "").strip(),
                authors=[a.get("author", {}).get("display_name", "").strip() for a in item.get("authorships", []) if a.get("author", {}).get("display_name")],
                year=year,
                source=(item.get("primary_location", {}).get("source", {}).get("display_name") or "").strip(),
                doi=_normalize_doi(item.get("doi")),
                work_type=(item.get("type") or "").strip(),
                publication_date=pub_date,
                openalex_id=item.get("id") or "",
            )
        )

    return records


async def _verify_single_with_crossref(client: httpx.AsyncClient, source: SourceRecord) -> bool:
    try:
        if source.doi:
            resp = await client.get(f"{CROSSREF_WORKS_URL}/{source.doi}")
        else:
            resp = await client.get(CROSSREF_WORKS_URL, params={"query.title": source.title, "rows": 1})
        resp.raise_for_status()
    except httpx.HTTPError:
        return False

    payload = resp.json().get("message", {})
    if source.doi:
        return bool(payload.get("DOI"))

    items = payload.get("items", []) if isinstance(payload, dict) else []
    if not items:
        return False

    cr_title = " ".join(items[0].get("title", [])).strip()
    return _normalize_title(cr_title) == _normalize_title(source.title)


async def verify_sources_with_crossref(openalex_sources: list[SourceRecord]) -> list[SourceRecord]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        tasks = [_verify_single_with_crossref(client, src) for src in openalex_sources]
        checks = await asyncio.gather(*tasks, return_exceptions=True)

    verified: list[SourceRecord] = []
    for source, result in zip(openalex_sources, checks):
        is_crossref_ok = bool(result) if not isinstance(result, Exception) else False
        source.verified_by_crossref = is_crossref_ok
        if is_crossref_ok or _is_reliable_openalex_metadata(source):
            verified.append(source)

    return _dedupe_sources(verified)


def _dedupe_sources(records: list[SourceRecord]) -> list[SourceRecord]:
    seen_doi: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[SourceRecord] = []

    for rec in records:
        if rec.doi and rec.doi in seen_doi:
            continue
        title_key = _normalize_title(rec.title)
        if title_key and title_key in seen_titles:
            continue

        if rec.doi:
            seen_doi.add(rec.doi)
        if title_key:
            seen_titles.add(title_key)
        unique.append(rec)

    return unique


def _build_format_prompt(verified_sources: list[SourceRecord], fmt: str, count: int) -> str:
    lines = []
    for i, src in enumerate(verified_sources[:count], start=1):
        lines.append(
            f"{i}) title={src.title}; authors={', '.join(src.authors) if src.authors else 'N/A'}; "
            f"year={src.year or 'N/A'}; journal/source={src.source or 'N/A'}; doi={src.doi or 'N/A'}; "
            f"type={src.work_type or 'N/A'}; publication_date={src.publication_date or 'N/A'}"
        )

    return (
        f"Оформи ТОЛЬКО переданные источники в формате {fmt}.\n"
        "Запрещено добавлять новые источники, авторов, DOI, ISBN, URL, страницы, издательства.\n"
        "Если поля нет, оставь только доступные данные без выдумок.\n"
        "Сохрани нумерацию. Верни только список без комментариев.\n\n"
        "verified_sources:\n" + "\n".join(lines)
    )


async def generate_sources_by_topic(topic: str, count: int, fmt: str) -> str:
    openalex_sources = await search_openalex_sources(topic=topic, requested_count=count)
    if not openalex_sources:
        return "Надежные источники по теме не найдены (OpenAlex не вернул релевантные записи)."

    verified_sources = await verify_sources_with_crossref(openalex_sources)
    if not verified_sources:
        return "Надежные источники по теме не найдены после проверки в Crossref/OpenAlex."

    prompt = _build_format_prompt(verified_sources=verified_sources, fmt=fmt, count=count)
    return await generate_text(prompt, max_tokens=2000)
