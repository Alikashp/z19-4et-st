from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx

from services.llm import generate_text

OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_WORKS_URL = "https://api.crossref.org/works"
MIN_YEAR = 2015
MIN_YEAR_ARTICLES = 2021
REQUEST_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=8.0, pool=8.0)

OPENALEX_TYPES_BY_MODE = {
    "articles": ["article"],
    "books": ["book", "book-chapter", "monograph"],
    "standards": ["standard"],
    "reports": ["report"],
    "mixed": ["article", "book", "book-chapter", "monograph", "report", "standard"],
}

CROSSREF_ALLOWED_TYPES = {
    "journal-article", "book", "book-chapter", "monograph",
    "report", "standard", "proceedings-article",
}

TERM_TRANSLATIONS = {
    "управление требованиями": ["requirements management", "requirements engineering"],
    "требования стейкхолдеров": ["stakeholder requirements"],
    "управление стейкхолдерами": ["stakeholder management"],
    "ит-стартап": ["it startup", "software startup"],
    "цифровой продукт": ["digital product", "software product"],
    "гибкая разработка": ["agile software development"],
    "финансовый анализ": ["financial analysis", "financial statement analysis"],
    "бухгалтерский учет": ["accounting", "financial accounting"],
    "маркетинг": ["marketing management"],
    "менеджмент": ["management", "strategic management"],
    "экономика предприятия": ["enterprise economics"],
    "банковское дело": ["banking", "bank management"],
    "налоги": ["taxation", "tax system"],
    "логистика": ["logistics management", "supply chain management"],
    "инвестиции": ["investment analysis", "investment management"],
    "страхование": ["insurance economics"],
}

CURATED_REGISTRY: dict[str, list[dict]] = {
    "юридические аспекты международных стандартов": [
        {"title": "ISO/IEC Directives, Part 1: Procedures for the technical work",
         "authors": ["ISO/IEC"], "year": 2023, "publisher": "ISO",
         "source": "ISO/IEC", "source_type": "standard",
         "standard_number": "ISO/IEC Directives Part 1"},
        {"title": "Regulation (EU) 2023/2854 on harmonised rules on fair access to and use of data (Data Act)",
         "authors": ["European Union"], "year": 2023, "publisher": "European Union",
         "source": "EUR-Lex", "source_type": "report", "standard_number": "EU 2023/2854"},
    ],
    "финансовый анализ": [
        {"title": "Комплексный анализ хозяйственной деятельности предприятия",
         "authors": ["Савицкая Г.В."], "year": 2024, "publisher": "ИНФРА-М", "source_type": "book"},
        {"title": "Экономический анализ",
         "authors": ["Савицкая Г.В."], "year": 2025, "publisher": "ИНФРА-М", "source_type": "book"},
        {"title": "Финансовый менеджмент: теория и практика",
         "authors": ["Ковалев В.В."], "year": 2021, "publisher": "Проспект", "source_type": "book"},
        {"title": "Анализ финансовой отчётности",
         "authors": ["Донцова Л.В.", "Никифорова Н.А."], "year": 2022,
         "publisher": "Дело и Сервис", "source_type": "book"},
    ],
    "бухгалтерский учет": [
        {"title": "Бухгалтерский финансовый учёт",
         "authors": ["Кондраков Н.П."], "year": 2023, "publisher": "ИНФРА-М", "source_type": "book"},
        {"title": "Федеральный закон от 06.12.2011 № 402-ФЗ «О бухгалтерском учёте»",
         "authors": ["Государственная Дума РФ"], "year": 2011,
         "publisher": "КонсультантПлюс", "source_type": "standard",
         "standard_number": "Федеральный закон № 402-ФЗ"},
    ],
    "маркетинг": [
        {"title": "Маркетинг менеджмент",
         "authors": ["Котлер Ф.", "Келлер К.Л."], "year": 2022,
         "publisher": "Питер", "source_type": "book"},
    ],
    "менеджмент": [
        {"title": "Менеджмент",
         "authors": ["Виханский О.С.", "Наумов А.И."], "year": 2022,
         "publisher": "Магистр", "source_type": "book"},
    ],
    "инвестиции": [
        {"title": "Федеральный закон от 25.02.1999 № 39-ФЗ «Об инвестиционной деятельности в РФ»",
         "authors": ["Государственная Дума РФ"], "year": 1999,
         "publisher": "КонсультантПлюс", "source_type": "standard",
         "standard_number": "Федеральный закон № 39-ФЗ"},
    ],
    "налоги": [
        {"title": "Налоговый кодекс Российской Федерации",
         "authors": ["Государственная Дума РФ"], "year": 2024,
         "publisher": "КонсультантПлюс", "source_type": "standard",
         "standard_number": "НК РФ"},
    ],
    "гражданское право": [
        {"title": "Гражданский кодекс Российской Федерации",
         "authors": ["Государственная Дума РФ"], "year": 2024,
         "publisher": "КонсультантПлюс", "source_type": "standard",
         "standard_number": "ГК РФ"},
    ],
    "трудовое право": [
        {"title": "Трудовой кодекс Российской Федерации",
         "authors": ["Государственная Дума РФ"], "year": 2024,
         "publisher": "КонсультантПлюс", "source_type": "standard",
         "standard_number": "ТК РФ"},
    ],
    "банковское дело": [
        {"title": "Банковское дело",
         "authors": ["Лаврушин О.И."], "year": 2023,
         "publisher": "КноРус", "source_type": "book"},
    ],
}

CURATED_KEYS: dict[str, list[str]] = {
    "юридические аспекты международных стандартов": ["юридическ", "стандарт"],
    "финансовый анализ": ["финансов", "анализ", "хозяйствен"],
    "бухгалтерский учет": ["бухгалтер", "учёт", "учет"],
    "маркетинг": ["маркетинг"],
    "менеджмент": ["менеджмент", "управлени"],
    "инвестиции": ["инвестиц"],
    "налоги": ["налог"],
    "гражданское право": ["гражданск"],
    "трудовое право": ["трудов"],
    "банковское дело": ["банк"],
}

DOMAIN_PACKS = {
    "проектное управление": [
        ("A Guide to the Project Management Body of Knowledge (PMBOK Guide)", "Project Management Institute", 2021, "standard", "PMBOK 7"),
        ("ISO 21502:2020 Guidance on project management", "ISO", 2021, "standard", "ISO 21502"),
        ("ISO 31000:2018 Risk management guidelines", "ISO", 2021, "standard", "ISO 31000"),
        ("PRINCE2 7 Managing Successful Projects", "AXELOS", 2023, "book", ""),
        ("Project Management: A Systems Approach to Planning, Scheduling, and Controlling", "Harold Kerzner", 2022, "book", ""),
        ("Agile Practice Guide", "PMI and Agile Alliance", 2021, "book", ""),
        ("IPMA Individual Competence Baseline v4", "IPMA", 2021, "standard", "ICB4"),
        ("Scrum Guide", "Ken Schwaber and Jeff Sutherland", 2021, "standard", "Scrum Guide 2020"),
    ],
}


# ─── Data model ───────────────────────────────────────────────

@dataclass
class SourceRecord:
    title: str
    authors: list[str] = field(default_factory=list)
    year: Optional[int] = None
    source: Optional[str] = None
    publisher: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    doi: Optional[str] = None
    source_type: str = "article"
    standard_number: Optional[str] = None
    score: float = 0.0
    verified: bool = False


# ─── Helpers ──────────────────────────────────────────────────

def _contains_cyrillic(text: str) -> bool:
    return any('\u0400' <= c <= '\u04FF' for c in text)


def _norm(text: str) -> str:
    return re.sub(r'\W+', ' ', (text or '').lower()).strip()


def _dedupe_sources(sources: list[SourceRecord]) -> list[SourceRecord]:
    seen: set[str] = set()
    out: list[SourceRecord] = []
    for s in sources:
        key = _norm(s.title)[:60]
        if key and key not in seen:
            seen.add(key)
            out.append(s)
    return out


def _relevance_score(s: SourceRecord, query_terms: list[str]) -> float:
    text = _norm(f"{s.title} {' '.join(s.authors or [])} {s.source or ''}")
    score = 0.0
    for term in query_terms:
        for word in term.split():
            if word and len(word) > 2 and word in text:
                score += 1.0
    if s.year and s.year >= MIN_YEAR_ARTICLES:
        score += 1.0
    if s.doi:
        score += 0.5
    if s.verified:
        score += 2.0
    return score


def build_search_queries(topic: str) -> list[str]:
    tl = topic.strip()
    queries = [tl]
    tl_lower = tl.lower()
    for ru, en_list in TERM_TRANSLATIONS.items():
        if ru in tl_lower:
            queries.extend(en_list)
    words = tl.split()
    if len(words) > 3:
        queries.append(" ".join(words[:3]))
    return list(dict.fromkeys(queries))


def _inject_curated_sources(topic: str) -> list[SourceRecord]:
    tl = topic.lower()
    out: list[SourceRecord] = []
    for key, keywords in CURATED_KEYS.items():
        if any(kw in tl for kw in keywords):
            for e in CURATED_REGISTRY.get(key, []):
                out.append(SourceRecord(
                    title=e.get("title", ""),
                    authors=e.get("authors", []),
                    year=e.get("year"),
                    publisher=e.get("publisher"),
                    source=e.get("source"),
                    source_type=e.get("source_type", "book"),
                    standard_number=e.get("standard_number"),
                    score=4.0,
                    verified=True,
                ))
    return out


def _domain_pack_sources(topic: str) -> list[SourceRecord]:
    tl = topic.lower()
    packs = []
    if "проект" in tl or "стейкхолдер" in tl or "требован" in tl:
        packs.extend(DOMAIN_PACKS["проектное управление"])
    return [SourceRecord(title=t, authors=[a], year=y, source_type=st, standard_number=sn)
            for (t, a, y, st, sn) in packs]


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
        used = {id(s) for s in selected}
        selected.extend(s for s in sources if id(s) not in used)
    return selected[:count]


# ─── OpenAlex ─────────────────────────────────────────────────

def _parse_openalex_work(work: dict) -> Optional[SourceRecord]:
    title = (work.get("title") or "").strip()
    if not title:
        return None
    pub_year = work.get("publication_year")
    if pub_year and pub_year < MIN_YEAR:
        return None
    authors: list[str] = []
    for authorship in (work.get("authorships") or [])[:6]:
        name = (authorship.get("author") or {}).get("display_name") or ""
        if name:
            authors.append(name)
    primary_location = work.get("primary_location") or {}
    source_info = primary_location.get("source") or {}
    journal = source_info.get("display_name") or ""
    doi_raw = work.get("doi") or ""
    doi = doi_raw.replace("https://doi.org/", "").strip() if doi_raw else None
    biblio = work.get("biblio") or {}
    volume = biblio.get("volume")
    issue = biblio.get("issue")
    first_page = biblio.get("first_page")
    last_page = biblio.get("last_page")
    pages = f"{first_page}–{last_page}" if first_page and last_page else first_page
    raw_type = (work.get("type") or "").lower()
    source_type = "book" if raw_type in ("book", "monograph") else \
                  "standard" if raw_type == "standard" else \
                  "report" if raw_type == "report" else "article"
    publisher = ((work.get("host_venue") or {}).get("publisher")
                 or source_info.get("host_organization_name"))
    return SourceRecord(
        title=title, authors=authors, year=pub_year, source=journal,
        publisher=publisher, volume=str(volume) if volume else None,
        issue=str(issue) if issue else None, pages=pages,
        doi=doi, source_type=source_type,
    )


async def _openalex_query(query: str, types: list[str], per_page: int = 25) -> list[SourceRecord]:
    params = {
        "search": query,
        "filter": f"type:{'|'.join(types)},publication_year:>={MIN_YEAR}",
        "per-page": per_page,
        "sort": "relevance_score:desc",
        "select": "title,authorships,publication_year,primary_location,doi,biblio,type,host_venue",
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.get(OPENALEX_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    records: list[SourceRecord] = []
    for work in (data.get("results") or []):
        rec = _parse_openalex_work(work)
        if rec:
            records.append(rec)
    return records


# ─── Crossref verification ────────────────────────────────────

async def _crossref_verify_one(s: SourceRecord) -> Optional[SourceRecord]:
    query = s.title
    if s.authors:
        query += " " + s.authors[0].split()[0]
    params = {"query": query, "rows": 3,
               "select": "title,author,published,DOI,publisher,container-title,volume,issue,page,type"}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(CROSSREF_WORKS_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        items = (data.get("message") or {}).get("items") or []
        for item in items:
            cr_title = ((item.get("title") or [""])[0]).strip().lower()
            if not cr_title:
                continue
            if _norm(cr_title)[:40] == _norm(s.title)[:40]:
                cr_type = item.get("type", "journal-article")
                if cr_type not in CROSSREF_ALLOWED_TYPES:
                    continue
                pub_date = (item.get("published") or {}).get("date-parts") or [[]]
                year = pub_date[0][0] if pub_date and pub_date[0] else s.year
                authors_cr = item.get("author") or []
                cr_authors = [
                    f"{a.get('family', '')} {a.get('given', '')[:1]}." if a.get('given') else a.get('family', '')
                    for a in authors_cr[:6] if a.get('family')
                ]
                s.year = year or s.year
                if cr_authors:
                    s.authors = cr_authors
                s.doi = item.get("DOI") or s.doi
                container = (item.get("container-title") or [None])[0]
                if container:
                    s.source = container
                s.publisher = item.get("publisher") or s.publisher
                s.volume = item.get("volume") or s.volume
                s.issue = item.get("issue") or s.issue
                s.pages = item.get("page") or s.pages
                s.verified = True
                s.score += 2.0
                return s
    except httpx.HTTPError:
        pass
    return None


async def verify_sources_with_crossref(sources: list[SourceRecord]) -> list[SourceRecord]:
    tasks = [_crossref_verify_one(s) for s in sources]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: list[SourceRecord] = []
    for s, res in zip(sources, results):
        if isinstance(res, SourceRecord):
            out.append(res)
        elif s.verified or s.score >= 3.0:
            out.append(s)
    return out


# ─── Formatting ───────────────────────────────────────────────

def _to_initials(name: str) -> str:
    parts = [p for p in re.split(r"\s+", (name or "").strip()) if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    has_cyr = any(_contains_cyrillic(p) for p in parts)
    if has_cyr:
        surname = parts[0]
        initials = "".join(f"{p[0]}." for p in parts[1:] if p)
        return f"{surname} {initials}".strip()
    surname = parts[-1]
    initials = "".join(f"{p[0]}." for p in parts[:-1] if p)
    return f"{surname} {initials}".strip()


def _fix_caps(text: str) -> str:
    value = (text or "").strip()
    if not value:
        return ""
    letters = [c for c in value if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.8:
        return value.capitalize()
    return value


def _authors_text(authors: list[str]) -> str:
    if not authors:
        return ""
    prepared = [_to_initials(a) for a in authors]
    return ", ".join(a for a in prepared if a)


def _format_gost(s: SourceRecord, idx: int) -> str:
    authors = _authors_text(s.authors)
    ap = f"{authors}. " if authors else ""
    if s.source_type == "article":
        vol = f" — Т. {s.volume}." if s.volume else ""
        iss = f" — № {s.issue}." if s.issue else ""
        pgs = f" — С. {s.pages}." if s.pages else ""
        return f"{idx}. {ap}{_fix_caps(s.title)} // {_fix_caps(s.source or 'Б.и.')}. — {s.year or 'Б.г.'}.{vol}{iss}{pgs}"
    if s.source_type == "book":
        return f"{idx}. {ap}{_fix_caps(s.title)}. — {s.publisher or 'Б.и.'}, {s.year or 'Б.г.'}."
    if s.source_type == "standard":
        std = s.standard_number or s.title
        return f"{idx}. {std}. — {_fix_caps(s.publisher or 'Б.и.')}, {s.year or 'Б.г.'}."
    return f"{idx}. {ap}{_fix_caps(s.title)}. — {_fix_caps(s.publisher or s.source or 'Б.и.')}, {s.year or 'Б.г.'}."


def _format_apa(s: SourceRecord, idx: int) -> str:
    authors = _authors_text(s.authors)
    if s.source_type == "article":
        doi_part = f" https://doi.org/{s.doi}" if s.doi else ""
        vol_issue = f"{s.volume or 'N/A'}({s.issue or 'N/A'})" if s.volume or s.issue else ""
        pages_part = f", {s.pages}" if s.pages else ""
        return (f"{idx}. {authors} ({s.year or 'n.d.'}). {_fix_caps(s.title)}. "
                f"<i>{_fix_caps(s.source or 'N/A')}</i>{', ' + vol_issue if vol_issue else ''}{pages_part}.{doi_part}")
    if s.source_type == "book":
        return (f"{idx}. {authors} ({s.year or 'n.d.'}). "
                f"<i>{_fix_caps(s.title)}</i>. {_fix_caps(s.publisher or 'N/A')}.")
    return f"{idx}. {authors} ({s.year or 'n.d.'}). {_fix_caps(s.title)}. {_fix_caps(s.publisher or s.source or 'N/A')}."


def _format_vancouver(s: SourceRecord, idx: int) -> str:
    authors = _authors_text(s.authors)
    doi_part = f" doi:{s.doi}" if s.doi else ""
    vol_issue = f";{s.volume or ''}({s.issue or ''})" if (s.volume or s.issue) else ""
    pages_part = f":{s.pages}" if s.pages else ""
    return (f"{idx}. {authors}. {_fix_caps(s.title)}. "
            f"{s.source or s.publisher or 'N/A'}. {s.year or 'N/A'}{vol_issue}{pages_part}.{doi_part}")


def format_sources(sources: list[SourceRecord], fmt: str) -> str:
    fmt_norm = (fmt or "").upper()
    out: list[str] = []
    for i, s in enumerate(sources, 1):
        if "APA" in fmt_norm:
            out.append(_format_apa(s, i))
        elif "VANCOUVER" in fmt_norm:
            out.append(_format_vancouver(s, i))
        else:
            out.append(_format_gost(s, i))
    return "\n".join(out)


def _build_format_prompt(verified_sources: list[SourceRecord], fmt: str) -> str:
    lines = []
    for i, s in enumerate(verified_sources, start=1):
        def _f(v) -> str:
            return str(v) if v else "ОТСУТСТВУЕТ"
        doi_part = f"doi={s.doi}" if s.doi else "doi=ОТСУТСТВУЕТ"
        lines.append(
            f"{i}) type={s.source_type} | title={s.title} | "
            f"authors={', '.join(s.authors) if s.authors else 'ОТСУТСТВУЕТ'} | "
            f"year={_f(s.year)} | journal={_f(s.source)} | "
            f"publisher={_f(s.publisher)} | vol={_f(s.volume)} | "
            f"issue={_f(s.issue)} | pages={_f(s.pages)} | {doi_part} | "
            f"std_num={_f(s.standard_number)}"
        )
    return (
        f"Оформи список источников строго в формате {fmt}.\n"
        "Твоя задача — ТОЛЬКО расставить знаки препинания и порядок элементов.\n"
        "Все данные берёшь ИСКЛЮЧИТЕЛЬНО из verified_sources. "
        "Если поле = ОТСУТСТВУЕТ — пропусти его, не заменяй ничем из памяти.\n"
        "Не добавляй источники. Не переводи названия. Не пиши авторов КАПСЛОКОМ.\n"
        "DOI включай только если doi= не ОТСУТСТВУЕТ.\n\n"
        "verified_sources:\n" + "\n".join(lines)
    )


FORMAT_CHECK_PROMPT = """\
Проверь оформление списка источников ниже на соответствие формату {fmt}.
Исправь ТОЛЬКО знаки препинания, пробелы и порядок элементов.

ЗАПРЕЩЕНО:
- добавлять данные которых нет (год, номер издания, страницы, том, издательство, DOI, редакторов)
- удалять или добавлять источники
- если данных не хватает — оставь как есть

Верни только исправленный пронумерованный список без комментариев.

Список:
{sources}
"""


async def generate_sources_by_topic(topic: str, count: int, fmt: str, mode: str = "mixed") -> str:
    mode = mode if mode in OPENALEX_TYPES_BY_MODE else "mixed"

    selected = await collect_verified_sources(topic=topic, count=count, mode=mode)
    if not selected:
        return (
            f"По теме «{topic}» не удалось найти надёжные источники.\n\n"
            "Попробуй:\n"
            "• Сформулировать тему короче (например: «финансовый анализ»)\n"
            "• Использовать «Оформить свои» и вставить источники вручную"
        )

    formatted = format_sources(selected, fmt)

    check_prompt = FORMAT_CHECK_PROMPT.format(fmt=fmt, sources=formatted)
    try:
        checked = await generate_text(check_prompt, max_tokens=2500)
        if checked and checked.strip():
            formatted = checked.strip()
    except Exception:
        pass

    if len(selected) < count:
        return f"Найдено {len(selected)} из {count} источников.\n\n{formatted}"
    return formatted


async def collect_verified_sources(topic: str, count: int = 20, mode: str = "mixed") -> list[SourceRecord]:
    mode = mode if mode in OPENALEX_TYPES_BY_MODE else "mixed"
    queries = build_search_queries(topic)
    openalex_types = OPENALEX_TYPES_BY_MODE[mode]

    curated = _inject_curated_sources(topic)

    candidates: list[SourceRecord] = list(curated)
    for q in queries:
        try:
            candidates.extend(await _openalex_query(q, openalex_types, per_page=25))
        except httpx.HTTPError:
            continue
    candidates.extend(_domain_pack_sources(topic))

    candidates = _dedupe_sources(candidates)
    if not candidates:
        return []

    query_terms = [_norm(q) for q in queries]
    for c in candidates:
        if c.score < 1.0:
            c.score = _relevance_score(c, query_terms)

    candidates = sorted(candidates, key=lambda x: x.score, reverse=True)
    to_verify = [s for s in candidates if not s.verified][:max(40, count * 3)]
    already_ok = [s for s in candidates if s.verified]

    verified = await verify_sources_with_crossref(to_verify)
    final = _dedupe_sources(already_ok + verified)
    final = sorted(final, key=lambda x: x.score, reverse=True)
    return final[:count]


OWN_SOURCES_VERIFY_PROMPT = """\
Пользователь хочет оформить следующие источники:
{sources}

Для каждого источника:
1. Если реален и данные верны — пометь ✅ и оставь как есть.
2. Если есть исправимая ошибка — исправь и пометь ✏️ с кратким пояснением.
3. Если источник не существует или данных не хватает — пометь ⚠️ и предложи \
2–3 реально существующих близких источника с полными данными.

Не придумывай альтернативы — только те о реальном существовании которых уверен.

Формат:
✅ [источник]
✏️ [исправленный] — исправлено: [что]
⚠️ Не найдено: «[текст]»
   Похожие источники:
   — [альтернатива 1]
   — [альтернатива 2]
"""


async def verify_own_sources(sources_text: str) -> str:
    prompt = OWN_SOURCES_VERIFY_PROMPT.format(sources=sources_text)
    return await generate_text(prompt, max_tokens=2500)
