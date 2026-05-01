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
    "requirements": 3, "requirements engineering": 3, "requirements management": 3,
    "stakeholder": 3, "stakeholders": 3,
    "startup": 2, "startups": 2,
    "software": 2, "it": 2, "digital product": 2,
    "agile": 1, "lean": 1, "prioritization": 1, "product development": 1,
}

CURATED_REGISTRY = {
    "project management": [
        {"title": "A Guide to the Project Management Body of Knowledge (PMBOK® Guide)", "authors": ["Project Management Institute"], "year": 2021, "publisher": "Project Management Institute", "source": "Project Management Institute", "source_type": "standard", "standard_number": "PMBOK 7"},
    ],
    "requirements engineering": [
        {"title": "ISO/IEC/IEEE 29148:2018 Systems and software engineering — Life cycle processes — Requirements engineering", "authors": ["ISO/IEC/IEEE"], "year": 2018, "publisher": "ISO", "source": "ISO/IEC/IEEE", "source_type": "standard", "standard_number": "ISO/IEC/IEEE 29148:2018"},
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
    abstract: str
    openalex_id: str
    score: int = 0
    verified_by_crossref: bool = False


def _norm(s: str) -> str:
    return re.sub(r"[^\w\s]", "", re.sub(r"\s+", " ", (s or "").strip().lower()))


def _normalize_doi(raw: str | None) -> str:
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", (raw or "").strip(), flags=re.IGNORECASE).lower()


def _year_from_item(item: dict) -> int | None:
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


def build_search_queries(topic: str) -> list[str]:
    t = topic.lower().strip()
    queries = [t]
    for ru, en_list in TERM_TRANSLATIONS.items():
        if ru in t:
            queries.extend(en_list)
    # combine meaningful blocks
    if any(x in t for x in ["требован", "requirements"]):
        queries += ["requirements management software startups", "requirements engineering software startups", "agile requirements engineering startups"]
    if any(x in t for x in ["стейкхолдер", "stakeholder"]):
        queries += ["stakeholder requirements software development", "stakeholder management software development"]
    if any(x in t for x in ["стартап", "startup"]):
        queries += ["lean startup requirements engineering", "product development software startups stakeholders"]
    queries += ["requirements engineering software development", "stakeholder management software projects", "agile requirements engineering"]

    # unique and 3-8 preferred (allow up to 10)
    uniq = []
    seen = set()
    for q in queries:
        key = _norm(q)
        if key and key not in seen:
            uniq.append(q)
            seen.add(key)
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
    params = {"search": query, "filter": f"type:{'|'.join(openalex_types)}", "sort": "cited_by_count:desc", "per-page": per_page}
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        r = await client.get(OPENALEX_URL, params=params)
        r.raise_for_status()
    payload = r.json() if isinstance(r.json(), dict) else {}
    results = payload.get("results", []) if isinstance(payload.get("results"), list) else []
    out = []
    for item in results:
        if not isinstance(item, dict):
            continue
        y = _year_from_item(item)
        if not y:
            continue
        t = (item.get("type") or "").lower().strip()
        mapped = "book" if t in {"book", "book-chapter", "monograph"} else ("standard" if t == "standard" else ("report" if t == "report" else "article"))
        biblio = item.get("biblio", {}) if isinstance(item.get("biblio"), dict) else {}
        title = (item.get("title") or "").strip()
        abstract_index = item.get("abstract_inverted_index") if isinstance(item.get("abstract_inverted_index"), dict) else {}
        abstract = " ".join(sorted(abstract_index, key=lambda k: min(abstract_index[k]) if isinstance(abstract_index[k], list) and abstract_index[k] else 0)) if abstract_index else ""
        authorships = item.get("authorships", [])
        if not isinstance(authorships, list):
            authorships = []
        primary_location = item.get("primary_location") if isinstance(item.get("primary_location"), dict) else {}
        source_obj = primary_location.get("source") if isinstance(primary_location.get("source"), dict) else {}

        out.append(SourceRecord(
            title=title,
            authors=[(a.get("author", {}).get("display_name") or "").strip() for a in authorships if isinstance(a, dict) and a.get("author", {}).get("display_name")],
            year=y,
            source=(source_obj.get("display_name") or "").strip(),
            publisher=(source_obj.get("host_organization_name") or "").strip(),
            doi=_normalize_doi(item.get("doi")),
            work_type=t,
            source_type=mapped,
            publication_date=item.get("publication_date") or "",
            landing_page_url=(primary_location.get("landing_page_url") or "").strip(),
            standard_number=(re.search(r"\b(?:ISO|IEC|ISO/IEC|IEEE)\s?[\w\-/.:]+", title, re.IGNORECASE).group(0).strip() if re.search(r"\b(?:ISO|IEC|ISO/IEC|IEEE)\s?[\w\-/.:]+", title, re.IGNORECASE) else ""),
            volume=str(biblio.get("volume") or ""),
            issue=str(biblio.get("issue") or ""),
            pages=(f"{biblio.get('first_page','')}-{biblio.get('last_page','')}".strip("-") if (biblio.get("first_page") or biblio.get("last_page")) else ""),
            abstract=abstract,
            openalex_id=item.get("id") or "",
        ))
    return out


def _dedupe(records: list[SourceRecord]) -> list[SourceRecord]:
    d, t, s = set(), set(), set()
    out = []
    for r in records:
        if r.doi and r.doi in d:
            continue
        tk = _norm(r.title)
        if tk and tk in t:
            continue
        sk = _norm(r.standard_number)
        if sk and sk in s:
            continue
        if r.doi: d.add(r.doi)
        if tk: t.add(tk)
        if sk: s.add(sk)
        out.append(r)
    return out


def _inject_curated(topic: str) -> list[SourceRecord]:
    out = []
    for key, items in CURATED_REGISTRY.items():
        if key in topic.lower() or any(k in topic.lower() for k in key.split()):
            for i in items:
                if i["year"] < MIN_YEAR:
                    continue
                out.append(SourceRecord(i["title"], i["authors"], i["year"], i["source"], i["publisher"], "", i["source_type"], i["source_type"], f"{i['year']}-01-01", "", i["standard_number"], "", "", "", "", "curated", score=5, verified_by_crossref=True))
    return out


def _crossref_year(item: dict, fallback: int | None) -> int | None:
    for k in ("published-print", "published-online", "issued", "created"):
        parts = item.get(k, {}).get("date-parts") if isinstance(item.get(k), dict) else None
        if parts and parts[0]:
            return parts[0][0]
    return fallback


async def _verify_crossref(client: httpx.AsyncClient, src: SourceRecord) -> SourceRecord | None:
    if src.openalex_id == "curated":
        return src
    try:
        resp = await (client.get(f"{CROSSREF_WORKS_URL}/{src.doi}") if src.doi else client.get(CROSSREF_WORKS_URL, params={"query.title": src.title, "rows": 1}))
        resp.raise_for_status()
    except httpx.HTTPError:
        return src if src.year and src.year >= MIN_YEAR else None
    payload = resp.json() if isinstance(resp.json(), dict) else {}
    msg = payload.get("message", {}) if isinstance(payload, dict) else {}
    if not isinstance(msg, dict):
        msg = {}
    if src.doi:
        item = msg
    else:
        items = msg.get("items", []) if isinstance(msg.get("items"), list) else []
        item = items[0] if items and isinstance(items[0], dict) else {}
    src.year = _crossref_year(item, src.year)
    if not src.year or src.year < MIN_YEAR:
        return None
    src.volume = str(item.get("volume") or src.volume)
    src.issue = str(item.get("issue") or src.issue)
    src.pages = str(item.get("page") or src.pages)
    src.publisher = item.get("publisher") or src.publisher
    src.source = (item.get("container-title", [""])[0] if isinstance(item.get("container-title"), list) else item.get("container-title")) or src.source
    src.verified_by_crossref = True
    return src


def _mixed_pick(items: list[SourceRecord], count: int) -> list[SourceRecord]:
    quotas = {"article": max(1, round(count * 0.5)), "book": max(1, round(count * 0.25)), "standard": max(1, round(count * 0.15)), "report": max(1, round(count * 0.1))}
    out = []
    for typ in ["article", "book", "standard", "report"]:
        out.extend([x for x in items if x.source_type == typ][:quotas[typ]])
    if len(out) < count:
        out.extend([x for x in items if x not in out][:count-len(out)])
    return out[:count]


def _format_prompt(items: list[SourceRecord], fmt: str) -> str:
    lines = []
    for i, s in enumerate(items, 1):
        lines.append(f"{i}) source_type={s.source_type}; title={s.title}; authors={', '.join(s.authors) if s.authors else 'N/A'}; year={s.year}; source={s.source or 'N/A'}; publisher={s.publisher or 'N/A'}; volume={s.volume or 'N/A'}; issue={s.issue or 'N/A'}; pages={s.pages or 'N/A'}; DOI: {s.doi or 'N/A'}; standard_number={s.standard_number or 'N/A'}")
    return f"Оформи ТОЛЬКО verified_sources в формате {fmt}. Не добавляй новые источники, не выдумывай поля. Не переводи названия. Верни только список.\n\nverified_sources:\n" + "\n".join(lines)


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
        candidates.extend(_inject_curated(topic))
    candidates = _dedupe(candidates)
    if not candidates:
        return "Надежные источники по теме не найдены после расширенного поиска OpenAlex/Crossref."

    query_terms = [_norm(q) for q in queries]
    for c in candidates:
        c.score = _relevance_score(c, query_terms)

    min_score = 4
    filtered = [x for x in candidates if x.score >= min_score]
    if len(filtered) < max(3, count):
        filtered = [x for x in candidates if x.score >= 2]

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        verified = await asyncio.gather(*[_verify_crossref(client, s) for s in filtered], return_exceptions=True)
    verified_sources = [x for x in verified if isinstance(x, SourceRecord)]
    verified_sources = sorted(_dedupe(verified_sources), key=lambda x: x.score, reverse=True)
    selected = _mixed_pick(verified_sources, count) if mode == "mixed" else verified_sources[:count]

    if not selected:
        return "Надежные источники по теме не найдены после расширенного поиска и верификации."

    formatted = await generate_text(_format_prompt(selected, fmt), max_tokens=2000)
    if len(selected) < count:
        return f"⚠️ Надежных источников найдено меньше запрошенного ({len(selected)} из {count}).\n\n{formatted}"
    return formatted
