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
@@ -93,50 +92,74 @@ CURATED_REGISTRY = {
            "standard_number": "ISO/IEC 27001:2022",
        }
    ],
    "юридические аспекты международных стандартов": [
        {
            "title": "ISO/IEC Directives, Part 1: Procedures for the technical work",
            "authors": ["ISO/IEC"],
            "year": 2023,
            "publisher": "ISO",
            "source": "ISO/IEC",
            "source_type": "standard",
            "standard_number": "ISO/IEC Directives Part 1",
        },
        {
            "title": "Regulation (EU) 2023/2854 on harmonised rules on fair access to and use of data (Data Act)",
            "authors": ["European Union"],
            "year": 2023,
            "publisher": "European Union",
            "source": "EUR-Lex",
            "source_type": "report",
            "standard_number": "EU 2023/2854",
        },
    ],
}



FORMAT_REQUIREMENTS = """Обязательные правила оформления источников (рабочее резюме):

1) ГОСТ Р 7.0.110-2025
- При оформлении учитывать тип источника: статья в журнале, книга/учебник, стандарт, методические материалы, веб-источник.
- Использовать типографские знаки единообразно (тире, пробелы, знаки препинания) и не смешивать шаблоны разных типов источников.

2) APA 7
- Курсив передавать HTML-тегами <i>...</i>.
- Не использовать markdown-звездочки для курсива/выделения.

3) Vancouver
- Нумерованный список.
- Приоритетно использовать для журнальных/медицинских публикаций.

4) Неполные данные
- Если по пользовательскому источнику не хватает года/издания/выходных данных, сообщать о нехватке данных.
- Дополнительно предлагать релевантные найденные источники по автору/теме.

5) Контроль качества
- Перед выдачей проверять соответствие выбранному формату (ГОСТ/APA/Vancouver) и типу источника.
"""

DOMAIN_PACKS = {
    "проектное управление": [
        ("A Guide to the Project Management Body of Knowledge (PMBOK Guide)", "Project Management Institute", 2021, "standard", "PMBOK 7"),
        ("ISO 21502:2020 Guidance on project management", "ISO", 2021, "standard", "ISO 21502"),
        ("ISO 31000:2018 Risk management guidelines", "ISO", 2021, "standard", "ISO 31000"),
        ("PRINCE2 7 Managing Successful Projects", "AXELOS", 2023, "book", ""),
        ("Project Management: A Systems Approach to Planning, Scheduling, and Controlling", "Harold Kerzner", 2022, "book", ""),
        ("Agile Practice Guide", "PMI and Agile Alliance", 2021, "book", ""),
        ("IPMA Individual Competence Baseline v4", "IPMA", 2021, "standard", "ICB4"),
        ("ISO 9001:2015 Quality management systems", "ISO", 2021, "standard", "ISO 9001"),
        ("Scrum Guide", "Ken Schwaber and Jeff Sutherland", 2021, "standard", "Scrum Guide 2020"),
        ("GAO Cost Estimating and Assessment Guide", "U.S. GAO", 2022, "report", ""),
    ],
}


def _domain_pack_sources(topic: str) -> list[SourceRecord]:
    tl = topic.lower()
    packs = []
    if "проект" in tl:
        packs.extend(DOMAIN_PACKS["проектное управление"])
    if "стейкхолдер" in tl or "требован" in tl:
        packs.extend(DOMAIN_PACKS["проектное управление"])
    if "юрид" in tl or "стандарт" in tl:
        packs.extend(DOMAIN_PACKS["проектное управление"])
@@ -548,92 +571,146 @@ async def verify_sources_with_crossref(candidates: list[SourceRecord]) -> list[S


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

    selected = await collect_verified_sources(topic=topic, count=count, mode=mode)
    if not selected:
        return "Надежные источники по теме не найдены после расширенного поиска и верификации."

    formatted = await generate_text(_build_format_prompt(selected, fmt), max_tokens=2000)
    formatted = format_sources(selected, fmt)
    if len(selected) < count:
        return f"⚠️ Надежных источников найдено меньше запрошенного ({len(selected)} из {count}).\n\n{formatted}"
    return formatted




def _to_initials(name: str) -> str:
    parts = [p for p in re.split(r"\s+", (name or "").strip()) if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]

    # For Russian-style FIO, return "Фамилия И.О."
    has_cyr = any(_contains_cyrillic(p) for p in parts)
    if has_cyr and len(parts) >= 2:
        surname = parts[-1]
        initials = "".join(f"{p[0]}." for p in parts[:-1] if p)
        return f"{surname} {initials}".strip()

    # For Latin names keep compact initials for given names: "Surname N.M."
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
        return "N/A"
    prepared = [_to_initials(a) for a in authors]
    prepared = [a for a in prepared if a]
    return ", ".join(prepared) if prepared else "N/A"


def _format_gost(s: SourceRecord, idx: int) -> str:
    authors = _authors_text(s.authors)
    if s.source_type == "article":
        return f"{idx}. {authors}. {_fix_caps(s.title)} // {_fix_caps(s.source or 'N/A')}. — {s.year or 'N/A'}. — Т. {s.volume or 'N/A'}. — № {s.issue or 'N/A'}. — С. {s.pages or 'N/A'}."
    if s.source_type == "book":
        city_pub = s.publisher or s.source or "N/A"
        return f"{idx}. {authors}. {_fix_caps(s.title)}. — {city_pub}, {s.year or 'N/A'}."
    if s.source_type == "standard":
        std = s.standard_number or s.title
        return f"{idx}. {std}. — {_fix_caps(s.publisher or s.source or 'N/A')}, {s.year or 'N/A'}."
    return f"{idx}. {authors}. {_fix_caps(s.title)}. — {_fix_caps(s.publisher or s.source or 'N/A')}, {s.year or 'N/A'}."


def _format_apa(s: SourceRecord, idx: int) -> str:
    authors = _authors_text(s.authors)
    if s.source_type == "article":
        doi_part = f" https://doi.org/{s.doi}" if s.doi else ""
        return f"{idx}. {authors} ({s.year or 'n.d.'}). {_fix_caps(s.title)}. <i>{_fix_caps(s.source or 'N/A')}</i>, {s.volume or 'N/A'}({s.issue or 'N/A'}), {s.pages or 'N/A'}.{doi_part}"
    if s.source_type == "book":
        return f"{idx}. {authors} ({s.year or 'n.d.'}). <i>{_fix_caps(s.title)}</i>. {_fix_caps(s.publisher or s.source or 'N/A')}."
    return f"{idx}. {authors} ({s.year or 'n.d.'}). {_fix_caps(s.title)}. {_fix_caps(s.publisher or s.source or 'N/A')}."


def _format_vancouver(s: SourceRecord, idx: int) -> str:
    authors = _authors_text(s.authors)
    doi_part = f" doi:{s.doi}" if s.doi else ""
    return f"{idx}. {authors}. {_fix_caps(s.title)}. {s.source or s.publisher or 'N/A'}. {s.year or 'N/A'};{s.volume or ''}({s.issue or ''}):{s.pages or ''}.{doi_part}"


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


async def collect_verified_sources(topic: str, count: int = 20, mode: str = "mixed") -> list[SourceRecord]:
    mode = mode if mode in OPENALEX_TYPES_BY_MODE else "mixed"
    queries = build_search_queries(topic)
    openalex_types = OPENALEX_TYPES_BY_MODE[mode]

    candidates: list[SourceRecord] = []
    for q in queries:
        try:
            candidates.extend(await _openalex_query(q, openalex_types, per_page=25))
        except httpx.HTTPError:
            continue

    if mode in {"mixed", "standards"}:
        candidates.extend(_inject_curated_sources(topic))
    candidates.extend(_domain_pack_sources(topic))

    candidates = _dedupe_sources(candidates)
    if not candidates:
        return []

    query_terms = [_norm(q) for q in queries]
    for c in candidates:
        c.score = _relevance_score(c, query_terms)

    filtered = [x for x in candidates if x.score >= 2]
    if len(filtered) < max(12, count):
        filtered = sorted(candidates, key=lambda x: x.score, reverse=True)[: max(60, count * 4)]

    verified = await verify_sources_with_crossref(filtered)
    verified = sorted(verified, key=lambda x: x.score, reverse=True)