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

TERM_TRANSLATIONS = {
    "управление требованиями": ["requirements management", "requirements engineering"],
    "требования стейкхолдеров": ["stakeholder requirements"],
    "управление стейкхолдерами": ["stakeholder management"],
    "ит-стартап": ["it startup", "software startup"],
    "цифровой продукт": ["digital product", "software product"],
    "гибкая разработка": ["agile software development"],
    "приоритизация требований": ["requirements prioritization"],
    "разработка продукта": ["product development"],
}

RELEVANCE_WEIGHTS = {
    "requirements": 3,
    "requirements engineering": 3,
    "requirements management": 3,
    "stakeholder": 3,
    "stakeholders": 3,
    "startup": 2,
    "startups": 2,
    "software": 2,
    "it": 2,
    "digital product": 2,
    "agile": 1,
    "lean": 1,
    "prioritization": 1,
    "product development": 1,
}

CURATED_REGISTRY = {
    "project management": [
        {
            "title": "A Guide to the Project Management Body of Knowledge (PMBOK® Guide)",
            "authors": ["Project Management Institute"],
            "year": 2021,
            "publisher": "Project Management Institute",
            "source": "Project Management Institute",
            "source_type": "standard",
            "standard_number": "PMBOK 7",
        },
        {
            "title": "ISO 21502:2020 Project, programme and portfolio management — Guidance on project management",
            "authors": ["ISO"],
            "year": 2020,
            "publisher": "ISO",
            "source": "ISO",
            "source_type": "standard",
            "standard_number": "ISO 21502:2020",
        },
    ],
    "information security": [
        {
            "title": "ISO/IEC 27001:2022 Information security, cybersecurity and privacy protection — Information security management systems — Requirements",
            "authors": ["ISO/IEC"],
            "year": 2022,
            "publisher": "ISO",
            "source": "ISO/IEC",
            "source_type": "standard",
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
    volume: str
    issue: str
    pages: str
    abstract: str
    openalex_id: str
    score: int = 0
    verified_by_crossref: bool = False


def _norm(s: str) -> str:
    return re.sub(r"[^\w\s]", "", re.sub(r"\s+", " ", (s or "").strip().lower()))


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
    m = re.search(r"\b(?:ISO|IEC|ISO/IEC|IEEE)\s?[\w\-/.:]+", title or "", re.IGNORECASE)
    return m.group(0).strip() if m else ""


def _parse_openalex_year(item: dict) -> int | None:
    if not isinstance(item, dict):
        return None
    y = item.get("publication_year")
    if y:
        return y
    d = item.get("publication_date") or ""
    try:
        return date.fromisoformat(d).year if d else None
    except ValueError:
        return None


def _is_reliable_openalex_metadata(record: SourceRecord) -> bool:
    if record.source_type == "standard":
        return bool(record.title and record.year and (record.standard_number or record.source))
    if record.source_type == "book":
        return bool(record.title and record.year and (record.publisher or record.source))
    return bool(record.title and record.year and record.source)


def build_search_queries(topic: str) -> list[str]:
    t = topic.lower().strip()
    queries = [t]

    for ru, en_list in TERM_TRANSLATIONS.items():
        if ru in t:
            queries.extend(en_list)

    if any(x in t for x in ["требован", "requirements"]):
        queries += [
            "requirements management software startups",
            "requirements engineering software startups",
            "agile requirements engineering startups",
        ]
    if any(x in t for x in ["стейкхолдер", "stakeholder"]):
        queries += [
            "stakeholder requirements software development",
            "stakeholder management software development",
        ]
    if any(x in t for x in ["стартап", "startup"]):
        queries += [
            "lean startup requirements engineering",
            "product development software startups stakeholders",
        ]

    queries += [
        "requirements engineering software development",
        "stakeholder management software projects",
        "agile requirements engineering",
    ]

    uniq: list[str] = []
    seen: set[str] = set()
    for q in queries:
        k = _norm(q)
        if k and k not in seen:
            uniq.append(q)
            seen.add(k)
    return uniq[:10]


def _relevance_score(rec: SourceRecord, query_terms: list[str]) -> int:
    text = _norm(" ".join([rec.title, rec.abstract, rec.source, rec.publisher]))
    score = 0
    for term, weight in RELEVANCE_WEIGHTS.items():
        if term in text:
            score += weight
    for term in query_terms:
        if term and term in text:
            score += 1
    return score


async def _openalex_query(query: str, openalex_types: list[str], per_page: int) -> list[SourceRecord]:
    params = {
        "search": query,
        "filter": f"type:{'|'.join(openalex_types)}",
        "sort": "cited_by_count:desc",
        "per-page": per_page,
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        r = await client.get(OPENALEX_URL, params=params)
        r.raise_for_status()

    payload = r.json() if isinstance(r.json(), dict) else {}
    results = payload.get("results", []) if isinstance(payload.get("results"), list) else []

    out: list[SourceRecord] = []
    for item in results:
        if not isinstance(item, dict):
            continue

        y = _parse_openalex_year(item)
        if not y:
            continue

        t = (item.get("type") or "").lower().strip()
        mapped = (
            "book" if t in {"book", "book-chapter", "monograph"}
            else "standard" if t == "standard"
            else "report" if t == "report"
            else "article"
        )

        biblio = item.get("biblio", {}) if isinstance(item.get("biblio"), dict) else {}
        title = (item.get("title") or "").strip()

        abstract_index = item.get("abstract_inverted_index") if isinstance(item.get("abstract_inverted_index"), dict) else {}
        abstract = (
            " ".join(
                sorted(
                    abstract_index,
                    key=lambda k: min(abstract_index[k]) if isinstance(abstract_index[k], list) and abstract_index[k] else 0
                )
            )
            if abstract_index else ""
        )

        authorships = item.get("authorships", [])
        if not isinstance(authorships, list):
            authorships = []

        primary_location = item.get("primary_location") if isinstance(item.get("primary_location"), dict) else {}
        source_obj = primary_location.get("source") if isinstance(primary_location.get("source"), dict) else {}

        out.append(
            SourceRecord(
                title=title,
                authors=[
                    _normalize_person_name((a.get("author", {}).get("display_name") or "").strip())
                    for a in authorships
                    if isinstance(a, dict) and a.get("author", {}).get("display_name")
                ],
                year=y,
                source=(source_obj.get("display_name") or "").strip(),
                publisher=(source_obj.get("host_organization_name") or "").strip(),
                doi=_normalize_doi(item.get("doi")),
                work_type=t,
                source_type=mapped,
                publication_date=item.get("publication_date") or "",
                landing_page_url=(primary_location.get("landing_page_url") or "").strip(),
                standard_number=_extract_standard_number(title),
                volume=str(biblio.get("volume") or ""),
                issue=str(biblio.get("issue") or ""),
                pages=(
                    f"{biblio.get('first_page','')}-{biblio.get('last_page','')}".strip("-")
                    if (biblio.get("first_page") or biblio.get("last_page"))
                    else ""
                ),
                abstract=abstract,
                openalex_id=item.get("id") or "",
            )
        )

    return out


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


def _inject_curated_sources(topic: str) -> list[SourceRecord]:
    out: list[SourceRecord] = []
    tl = topic.lower()

    for key, items in CURATED_REGISTRY.items():
        if key in tl or any(k in tl for k in key.split()):
            for i in items:
                if i["year"] < MIN_YEAR:
                    continue
                out.append(
                    SourceRecord(
                        title=i["title"],
                        authors=i["authors"],
                        year=i["year"],
                        source=i["source"],
                        publisher=i["publisher"],
                        doi="",
                        work_type=i["source_type"],
                        source_type=i["source_type"],
                        publication_date=f"{i['year']}-01-01",
                        landing_page_url="",
                        standard_number=i["standard_number"],
                        volume="",
                        issue="",
                        pages="",
                        abstract="",
                        openalex_id="curated",
                        score=5,
                        verified_by_crossref=True,
                    )
                )

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
        resp = await (
            client.get(f"{CROSSREF_WORKS_URL}/{source.doi}")
            if source.doi
            else client.get(CROSSREF_WORKS_URL, params={"query.title": source.title, "rows": 1})
        )
        resp.raise_for_status()
    except httpx.HTTPError:
        return False, source

    payload = resp.json() if isinstance(resp.json(), dict) else {}
    msg = payload.get("message", {}) if isinstance(payload, dict) else {}
    if not isinstance(msg, dict):
        msg = {}

    if source.doi:
        item = msg
    else:
        items = msg.get("items", []) if isinstance(msg.get("items"), list) else []
        item = items[0] if items and isinstance(items[0], dict) else {}

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
    source.source = (
        item.get("container-title", [""])[0]
        if isinstance(item.get("container-title"), list)
        else item.get("container-title")
    ) or source.source
    source.authors = [
        _normalize_person_name(f"{a.get('family','')} {a.get('given','')}".strip())
        for a in item.get("author", [])
        if isinstance(a, dict)
    ] or source.authors
    source.title = cr_title.strip() or source.title
    source.verified_by_crossref = True

    return True, source


async def verify_sources_with_crossref(candidates: list[SourceRecord]) -> list[SourceRecord]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        checked = await asyncio.gather(
            *[_verify_single_with_crossref(client, s) for s in candidates],
            return_exceptions=True,
        )

    verified: list[SourceRecord] = []
    for source, result in zip(candidates, checked):
        if isinstance(result, Exception):
            ok, enriched = False, source
        else:
            ok, enriched = result

        if enriched.year and enriched.year >= MIN_YEAR and (ok or _is_reliable_openalex_metadata(enriched)):
            verified.append(enriched)

    return _dedupe_sources(verified)


def _select_mixed_sources(sources: list[SourceRecord], count: int) -> list[SourceRecord]:
    buckets: dict[str, list[SourceRecord]] = {"article": [], "book": [], "standard": [], "report": []}
    for s in sources:
        buckets.setdefault(s.source_type, []).append(s)

    quotas = {
        "article": max(1, round(count * 0.5)),
        "book": max(1, round(count * 0.25)),
        "standard": max(1, round(count * 0.15)),
        "report": max(1, round(count * 0.1)),
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
    for i, s in enumerate(verified_sources, start=1):
        doi = f"DOI: {s.doi}" if s.doi else "DOI: N/A"
        lines.append(
            f"{i}) source_type={s.source_type}; title={s.title}; authors={', '.join(s.authors) if s.authors else 'N/A'}; "
            f"year={s.year}; source={s.source or 'N/A'}; publisher={s.publisher or 'N/A'}; volume={s.volume or 'N/A'}; "
            f"issue={s.issue or 'N/A'}; pages={s.pages or 'N/A'}; {doi}; standard_number={s.standard_number or 'N/A'}"
        )

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
    queries = build_search_queries(topic)
    openalex_types = OPENALEX_TYPES_BY_MODE[mode]

    candidates: list[SourceRecord] = []
    for q in queries:
        try:
            candidates.extend(await _openalex_query(q, openalex_types, per_page=15))
        except httpx.HTTPError:
            continue

    if mode in {"mixed", "standards"}:
        candidates.extend(_inject_curated_sources(topic))

    candidates = _dedupe_sources(candidates)
    if not candidates:
        return "Надежные источники по теме не найдены после расширенного поиска OpenAlex/Crossref."

    query_terms = [_norm(q) for q in queries]
    for c in candidates:
        c.score = _relevance_score(c, query_terms)

    filtered = [x for x in candidates if x.score >= 4]
    if len(filtered) < max(3, count):
        filtered = [x for x in candidates if x.score >= 2]

    verified = await verify_sources_with_crossref(filtered)
    verified = sorted(verified, key=lambda x: x.score, reverse=True)

    selected = _select_mixed_sources(verified, count) if mode == "mixed" else verified[:count]
    if not selected:
        return "Надежные источники по теме не найдены после расширенного поиска и верификации."

    formatted = await generate_text(_build_format_prompt(selected, fmt), max_tokens=2000)
    if len(selected) < count:
        return f"⚠️ Надежных источников найдено меньше запрошенного ({len(selected)} из {count}).\n\n{formatted}"
    return formatted