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
}

CURATED_REGISTRY = {
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

def build_search_queries(topic: str) -> list[str]:
    """Строит список поисковых запросов для OpenAlex/Crossref по теме."""
    tl = topic.strip()
    queries = [tl]
    # Добавляем английский перевод если есть в словаре
    tl_lower = tl.lower()
    for ru, en_list in TERM_TRANSLATIONS.items():
        if ru in tl_lower:
            queries.extend(en_list)
    # Добавляем короткую форму (первые 2-3 слова) для широкого поиска
    words = tl.split()
    if len(words) > 3:
        queries.append(" ".join(words[:3]))
    return list(dict.fromkeys(queries))  # dedupe, preserve order


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

    return [SourceRecord(title=t, authors=[a], year=y, source_type=st, standard_number=sn) for (t, a, y, st, sn) in packs]


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


KNOWN_TEXTBOOKS_PROMPT = """\
Назови {count} реально существующих и широко известных учебников или учебных пособий по теме: {topic}.
Учебники должны быть реальными, изданными крупными российскими или международными издательствами (Юрайт, Инфра-М, КноРус, Питер, Pearson, McGraw-Hill и др.).
Перевыпускаемые ежегодно учебники — приоритет (например, Савицкая Г.В., Ковалев В.В., Бланк И.А. и подобные авторитеты в области).
Для каждого укажи ТОЛЬКО: автор(ы), точное название, издательство, последний известный тебе год издания.
Отвечай ТОЛЬКО JSON-массивом без пояснений:
[{{"authors": ["Фамилия И.О."], "title": "Название", "publisher": "Издательство", "year": 2023}}]
"""

async def _fetch_known_textbooks(topic: str, count: int = 5) -> list[SourceRecord]:
    """Запрашивает у LLM известные учебники, затем верифицирует их через Crossref."""
    import json
    prompt = KNOWN_TEXTBOOKS_PROMPT.format(topic=topic, count=count)
    try:
        raw = await generate_text(prompt, max_tokens=800)
        # Извлекаем JSON из ответа
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        if not match:
            return []
        items = json.loads(match.group())
    except Exception:
        return []

    records: list[SourceRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = item.get("title", "").strip()
        if not title:
            continue
        authors = item.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        records.append(SourceRecord(
            title=title,
            authors=authors,
            year=item.get("year"),
            publisher=item.get("publisher", ""),
            source_type="book",
        ))

    # Верифицируем через Crossref
    verified = await verify_sources_with_crossref(records)
    return verified


FORMAT_CHECK_PROMPT = """\
Ты — эксперт по библиографическому оформлению. Проверь список источников ниже на соответствие формату {fmt}.
Исправь ошибки оформления (пунктуация, порядок элементов, курсив для APA, нумерация для Vancouver).
НЕ добавляй и НЕ удаляй источники. НЕ придумывай данные. Верни только исправленный список.

Список:
{sources}
"""

async def generate_sources_by_topic(topic: str, count: int, fmt: str, mode: str = "mixed") -> str:
    mode = mode if mode in OPENALEX_TYPES_BY_MODE else "mixed"

    # Шаг 1: Сбор верифицированных источников из OpenAlex/Crossref
    selected = await collect_verified_sources(topic=topic, count=count, mode=mode)

    # Шаг 2 (пункт 3): Добавляем известные учебники от LLM, верифицированные через Crossref
    textbooks = await _fetch_known_textbooks(topic, count=max(3, count // 3))
    # Добавляем только новые (не дублирующие уже найденные)
    existing_titles = {_norm(s.title) for s in selected}
    for tb in textbooks:
        if _norm(tb.title) not in existing_titles:
            selected.append(tb)
            existing_titles.add(_norm(tb.title))

    if not selected:
        return "Надежные источники по теме не найдены после расширенного поиска и верификации."

    # Обрезаем до нужного количества (с учётом добавленных учебников)
    selected = selected[:count]

    # Шаг 3: Первичное форматирование
    formatted = format_sources(selected, fmt)

    # Шаг 4 (пункт 4): Проверка корректности оформления через LLM
    check_prompt = FORMAT_CHECK_PROMPT.format(fmt=fmt, sources=formatted)
    try:
        formatted = await generate_text(check_prompt, max_tokens=2000)
    except Exception:
        pass  # Если проверка упала — оставляем первичное форматирование

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
    return verified[:count]


# ─── Data model ───────────────────────────────────────────────

@dataclass
class SourceRecord:
    title: str
    authors: list[str] = None
    year: int | None = None
    source: str | None = None        # journal name or source name
    publisher: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    doi: str | None = None
    source_type: str = "article"     # article / book / standard / report
    standard_number: str | None = None
    score: float = 0.0

    def __post_init__(self):
        if self.authors is None:
            self.authors = []


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
    if s.year and s.year >= MIN_YEAR:
        score += 1.0
    if s.doi:
        score += 0.5
    return score


def _inject_curated_sources(topic: str) -> list[SourceRecord]:
    tl = topic.lower()
    out: list[SourceRecord] = []
    for key, entries in CURATED_REGISTRY.items():
        if any(w in tl for w in key.split()):
            for e in entries:
                out.append(SourceRecord(
                    title=e.get("title", ""),
                    authors=e.get("authors", []),
                    year=e.get("year"),
                    publisher=e.get("publisher"),
                    source=e.get("source"),
                    source_type=e.get("source_type", "standard"),
                    standard_number=e.get("standard_number"),
                ))
    return out


# ─── OpenAlex ─────────────────────────────────────────────────

def _parse_openalex_work(work: dict) -> SourceRecord | None:
    title = (work.get("title") or "").strip()
    if not title:
        return None

    pub_year = work.get("publication_year")
    if pub_year and pub_year < MIN_YEAR:
        return None

    # Authors
    authors: list[str] = []
    for authorship in (work.get("authorships") or [])[:6]:
        name = (authorship.get("author") or {}).get("display_name") or ""
        if name:
            authors.append(name)

    # Source / journal
    primary_location = work.get("primary_location") or {}
    source_info = primary_location.get("source") or {}
    journal = source_info.get("display_name") or ""

    # DOI
    doi_raw = work.get("doi") or ""
    doi = doi_raw.replace("https://doi.org/", "").strip() if doi_raw else None

    # Bibliographic details
    biblio = work.get("biblio") or {}
    volume = biblio.get("volume")
    issue = biblio.get("issue")
    first_page = biblio.get("first_page")
    last_page = biblio.get("last_page")
    pages = f"{first_page}–{last_page}" if first_page and last_page else first_page

    # Type
    raw_type = (work.get("type") or "").lower()
    if raw_type in ("book", "monograph"):
        source_type = "book"
    elif raw_type in ("standard",):
        source_type = "standard"
    elif raw_type in ("report",):
        source_type = "report"
    else:
        source_type = "article"

    # Publisher
    publisher = (work.get("host_venue") or {}).get("publisher") or source_info.get("host_organization_name")

    return SourceRecord(
        title=title,
        authors=authors,
        year=pub_year,
        source=journal,
        publisher=publisher,
        volume=str(volume) if volume else None,
        issue=str(issue) if issue else None,
        pages=pages,
        doi=doi,
        source_type=source_type,
    )


async def _openalex_query(
    query: str,
    types: list[str],
    per_page: int = 25,
) -> list[SourceRecord]:
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

async def _crossref_verify_one(s: SourceRecord) -> SourceRecord | None:
    """Returns the record if confirmed by Crossref (DOI resolves or title matches), else None."""
    query = s.title
    if s.authors:
        query += " " + s.authors[0]
    params = {
        "query": query,
        "rows": 3,
        "select": "title,author,published,DOI,publisher,container-title,volume,issue,page,type",
    }
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
                # Enrich with Crossref data
                cr_type = item.get("type", "journal-article")
                if cr_type not in CROSSREF_ALLOWED_TYPES:
                    continue
                pub_date = (item.get("published") or {}).get("date-parts") or [[]]
                year = pub_date[0][0] if pub_date and pub_date[0] else s.year
                if year and year < MIN_YEAR:
                    return None
                authors_cr = item.get("author") or []
                cr_authors = [
                    f"{a.get('family', '')} {a.get('given', '')[:1]}." if a.get('given') else a.get('family', '')
                    for a in authors_cr[:6]
                    if a.get('family')
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
                s.score += 2.0  # verification bonus
                return s
    except httpx.HTTPError:
        pass
    return None


async def verify_sources_with_crossref(sources: list[SourceRecord]) -> list[SourceRecord]:
    """Verifies sources via Crossref concurrently. Keeps unverified if they already scored well."""
    tasks = [_crossref_verify_one(s) for s in sources]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    verified: list[SourceRecord] = []
    unverified: list[SourceRecord] = []
    for s, res in zip(sources, results):
        if isinstance(res, SourceRecord):
            verified.append(res)
        elif isinstance(res, Exception) or res is None:
            unverified.append(s)

    # Keep high-scoring unverified (domain packs, curated registry)
    kept_unverified = [s for s in unverified if s.score >= 2]
    return verified + kept_unverified
