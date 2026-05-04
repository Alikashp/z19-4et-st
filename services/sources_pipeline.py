from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx

from services.llm import generate_text

OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_WORKS_URL = "https://api.crossref.org/works"
MIN_YEAR = 2015           # для учебников и законов важен не только свежак
MIN_YEAR_ARTICLES = 2021  # для статей по-прежнему строго
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
    "экономика предприятия": ["enterprise economics", "firm economics"],
    "банковское дело": ["banking", "bank management"],
    "налоги": ["taxation", "tax system"],
    "логистика": ["logistics management", "supply chain management"],
    "инвестиции": ["investment analysis", "investment management"],
    "страхование": ["insurance economics"],
}

# ─── Curated registry: заведомо реальные источники по темам ───────────────

CURATED_REGISTRY: dict[str, list[dict]] = {
    "проектное управление": [
        {"title": "A Guide to the Project Management Body of Knowledge (PMBOK Guide)",
         "authors": ["Project Management Institute"], "year": 2021,
         "publisher": "Project Management Institute", "source_type": "standard",
         "standard_number": "PMBOK 7"},
        {"title": "ISO 21502:2020 Guidance on project management",
         "authors": ["ISO"], "year": 2020, "publisher": "ISO",
         "source_type": "standard", "standard_number": "ISO 21502"},
        {"title": "PRINCE2 7 Managing Successful Projects",
         "authors": ["AXELOS"], "year": 2023,
         "publisher": "AXELOS", "source_type": "book"},
        {"title": "Agile Practice Guide",
         "authors": ["Project Management Institute", "Agile Alliance"], "year": 2017,
         "publisher": "Project Management Institute", "source_type": "book"},
    ],
    "финансовый анализ": [
        {"title": "Комплексный анализ хозяйственной деятельности предприятия",
         "authors": ["Савицкая Г.В."], "year": 2024,
         "publisher": "ИНФРА-М", "source_type": "book"},
        {"title": "Экономический анализ",
         "authors": ["Савицкая Г.В."], "year": 2025,
         "publisher": "ИНФРА-М", "source_type": "book"},
        {"title": "Финансовый менеджмент: теория и практика",
         "authors": ["Ковалев В.В."], "year": 2021,
         "publisher": "Проспект", "source_type": "book"},
        {"title": "Анализ финансовой отчётности",
         "authors": ["Донцова Л.В.", "Никифорова Н.А."], "year": 2022,
         "publisher": "Дело и Сервис", "source_type": "book"},
    ],
    "бухгалтерский учет": [
        {"title": "Бухгалтерский финансовый учёт",
         "authors": ["Кондраков Н.П."], "year": 2023,
         "publisher": "ИНФРА-М", "source_type": "book"},
        {"title": "Бухгалтерский учёт",
         "authors": ["Астахов В.П."], "year": 2022,
         "publisher": "Юрайт", "source_type": "book"},
        {"title": "Федеральный закон от 06.12.2011 № 402-ФЗ «О бухгалтерском учёте»",
         "authors": ["Государственная Дума РФ"], "year": 2011,
         "publisher": "КонсультантПлюс", "source_type": "standard",
         "standard_number": "Федеральный закон № 402-ФЗ"},
    ],
    "маркетинг": [
        {"title": "Маркетинг менеджмент",
         "authors": ["Котлер Ф.", "Келлер К.Л."], "year": 2022,
         "publisher": "Питер", "source_type": "book"},
        {"title": "Основы маркетинга",
         "authors": ["Котлер Ф.", "Армстронг Г."], "year": 2021,
         "publisher": "Вильямс", "source_type": "book"},
    ],
    "менеджмент": [
        {"title": "Основы менеджмента",
         "authors": ["Мескон М.", "Альберт М.", "Хедоури Ф."], "year": 2022,
         "publisher": "Вильямс", "source_type": "book"},
        {"title": "Стратегический менеджмент",
         "authors": ["Томпсон А.А.", "Стрикленд А.Дж."], "year": 2021,
         "publisher": "Вильямс", "source_type": "book"},
        {"title": "Менеджмент",
         "authors": ["Виханский О.С.", "Наумов А.И."], "year": 2022,
         "publisher": "Магистр", "source_type": "book"},
    ],
    "экономика предприятия": [
        {"title": "Экономика предприятия",
         "authors": ["Горфинкель В.Я."], "year": 2023,
         "publisher": "Юнити-Дана", "source_type": "book"},
        {"title": "Экономика организации (предприятия)",
         "authors": ["Сергеев И.В.", "Веретенникова И.И."], "year": 2021,
         "publisher": "Юрайт", "source_type": "book"},
    ],
    "инвестиции": [
        {"title": "Инвестиционный анализ",
         "authors": ["Ковалев В.В."], "year": 2022,
         "publisher": "Проспект", "source_type": "book"},
        {"title": "Инвестиции",
         "authors": ["Бланк И.А."], "year": 2021,
         "publisher": "Ника-Центр", "source_type": "book"},
        {"title": "Федеральный закон от 25.02.1999 № 39-ФЗ «Об инвестиционной деятельности в РФ»",
         "authors": ["Государственная Дума РФ"], "year": 1999,
         "publisher": "КонсультантПлюс", "source_type": "standard",
         "standard_number": "Федеральный закон № 39-ФЗ"},
    ],
    "логистика": [
        {"title": "Логистика",
         "authors": ["Аникин Б.А."], "year": 2021,
         "publisher": "ИНФРА-М", "source_type": "book"},
        {"title": "Supply Chain Management",
         "authors": ["Chopra S.", "Meindl P."], "year": 2021,
         "publisher": "Pearson", "source_type": "book"},
    ],
    "налоги": [
        {"title": "Налоговый кодекс Российской Федерации",
         "authors": ["Государственная Дума РФ"], "year": 2024,
         "publisher": "КонсультантПлюс", "source_type": "standard",
         "standard_number": "НК РФ"},
        {"title": "Налоги и налогообложение",
         "authors": ["Алиев Б.Х."], "year": 2021,
         "publisher": "Юнити-Дана", "source_type": "book"},
    ],
    "гражданское право": [
        {"title": "Гражданский кодекс Российской Федерации",
         "authors": ["Государственная Дума РФ"], "year": 2024,
         "publisher": "КонсультантПлюс", "source_type": "standard",
         "standard_number": "ГК РФ"},
        {"title": "Гражданское право",
         "authors": ["Суханов Е.А."], "year": 2023,
         "publisher": "Статут", "source_type": "book"},
    ],
    "трудовое право": [
        {"title": "Трудовой кодекс Российской Федерации",
         "authors": ["Государственная Дума РФ"], "year": 2024,
         "publisher": "КонсультантПлюс", "source_type": "standard",
         "standard_number": "ТК РФ"},
        {"title": "Трудовое право",
         "authors": ["Гусов К.Н.", "Толкунова В.Н."], "year": 2022,
         "publisher": "Проспект", "source_type": "book"},
    ],
    "банковское дело": [
        {"title": "Банковское дело",
         "authors": ["Лаврушин О.И."], "year": 2023,
         "publisher": "КноРус", "source_type": "book"},
        {"title": "Федеральный закон от 02.12.1990 № 395-1 «О банках и банковской деятельности»",
         "authors": ["Государственная Дума РФ"], "year": 1990,
         "publisher": "КонсультантПлюс", "source_type": "standard",
         "standard_number": "Федеральный закон № 395-1"},
    ],
    "страхование": [
        {"title": "Страхование",
         "authors": ["Шахов В.В."], "year": 2022,
         "publisher": "Юнити-Дана", "source_type": "book"},
        {"title": "Закон РФ от 27.11.1992 № 4015-1 «Об организации страхового дела в РФ»",
         "authors": ["Государственная Дума РФ"], "year": 1992,
         "publisher": "КонсультантПлюс", "source_type": "standard",
         "standard_number": "Закон № 4015-1"},
    ],
}

# Ключевые слова для матчинга тем реестра
CURATED_KEYS: dict[str, list[str]] = {
    "проектное управление": ["проект"],
    "финансовый анализ": ["финансов", "анализ", "хозяйствен", "савицкая", "ковалев"],
    "бухгалтерский учет": ["бухгалтер", "учёт", "учет"],
    "маркетинг": ["маркетинг"],
    "менеджмент": ["менеджмент", "управлени"],
    "экономика предприятия": ["экономик", "предприяти", "организаци"],
    "инвестиции": ["инвестиц"],
    "логистика": ["логистик", "цепочк"],
    "налоги": ["налог"],
    "гражданское право": ["гражданск"],
    "трудовое право": ["трудов"],
    "банковское дело": ["банк"],
    "страхование": ["страхован"],
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
                    score=4.0,   # curated — максимальный приоритет
                    verified=True,
                ))
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
        # Русский: первое слово — фамилия, остальные → инициалы
        surname = parts[0]
        initials = "".join(f"{p[0]}." for p in parts[1:] if p)
        return f"{surname} {initials}".strip()
    # Латинский: последнее слово — фамилия
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
        return (f"{idx}. {ap}{_fix_caps(s.title)} // "
                f"{_fix_caps(s.source or 'Б.и.')}. — {s.year or 'Б.г.'}. — "
                f"Т. {s.volume or '—'}. — № {s.issue or '—'}. — С. {s.pages or '—'}.")
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
        return (f"{idx}. {authors} ({s.year or 'n.d.'}). {_fix_caps(s.title)}. "
                f"<i>{_fix_caps(s.source or 'N/A')}</i>, "
                f"{s.volume or 'N/A'}({s.issue or 'N/A'}), {s.pages or 'N/A'}.{doi_part}")
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


# ─── Stage 1b: LLM → учебники + LLM-верификация ──────────────

TEXTBOOKS_PROMPT = """\
Тема: {topic}

Перечисли до {count} реально изданных и широко используемых учебников, учебных пособий \
или монографий по этой теме. Приоритет — книги, которые регулярно переиздаются крупными \
российскими (ИНФРА-М, Юрайт, КноРус, Питер, Проспект, Юнити-Дана) или международными \
(Pearson, McGraw-Hill, Wiley) издательствами.

СТРОГИЕ ПРАВИЛА:
- Указывай ТОЛЬКО книги, в существовании которых ты абсолютно уверен.
- Не выдумывай редакторов, соавторов, подзаголовки, города.
- Год — последнее известное тебе издание. Если не знаешь точно — null.
- Если не уверен в издательстве — null.

Ответ ТОЛЬКО JSON-массивом, без пояснений и markdown-блоков:
[{{"authors": ["Фамилия И.О."], "title": "Точное название", "publisher": "Издательство или null", "year": 2023}}]
"""

VERIFY_TEXTBOOKS_PROMPT = """\
Проверь каждый источник из списка ниже. Для каждого ответь: существует ли эта книга реально \
(автор + название + издательство совпадают)?

- Если источник существует и данные верны → оставь БЕЗ ИЗМЕНЕНИЙ.
- Если есть ошибка в данных и ты знаешь верный вариант → исправь.
- Если источник выдуман или ты не уверен → замени на null.
- НЕ ДОБАВЛЯЙ источники которых нет в списке.

Источники:
{sources_json}

Ответ ТОЛЬКО JSON-массивом той же длины (null для удалённых), без пояснений:
"""


async def _llm_textbooks_stage(topic: str, count: int = 8) -> list[SourceRecord]:
    """Запрашиваем LLM учебники → верифицируем вторым LLM-вызовом."""
    prompt = TEXTBOOKS_PROMPT.format(topic=topic, count=count)
    try:
        raw = await generate_text(prompt, max_tokens=1000)
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        if not match:
            return []
        items: list[dict] = json.loads(match.group())
    except Exception:
        return []

    if not items:
        return []

    # Проверяем вторым вызовом
    to_check = [
        {"authors": it.get("authors", []), "title": it.get("title", ""), "publisher": it.get("publisher")}
        for it in items if isinstance(it, dict) and it.get("title")
    ]
    verify_prompt = VERIFY_TEXTBOOKS_PROMPT.format(sources_json=json.dumps(to_check, ensure_ascii=False))
    try:
        verify_raw = await generate_text(verify_prompt, max_tokens=800)
        match2 = re.search(r"\[.*?\]", verify_raw, re.DOTALL)
        verified_items: list = json.loads(match2.group()) if match2 else [None] * len(items)
    except Exception:
        verified_items = items

    records: list[SourceRecord] = []
    for orig, ver in zip(items, verified_items):
        if not isinstance(orig, dict) or not orig.get("title"):
            continue
        item = ver if isinstance(ver, dict) else None
        if item is None:
            continue
        title = (item.get("title") or orig.get("title", "")).strip()
        if not title:
            continue
        authors = item.get("authors") or orig.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        records.append(SourceRecord(
            title=title,
            authors=authors,
            year=item.get("year") or orig.get("year"),
            publisher=item.get("publisher") or orig.get("publisher"),
            source_type="book",
            score=2.5,
        ))
    return records


# ─── Stage 2: OpenAlex ────────────────────────────────────────

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
    if raw_type in ("book", "monograph"):
        source_type = "book"
    elif raw_type in ("standard",):
        source_type = "standard"
    elif raw_type in ("report",):
        source_type = "report"
    else:
        source_type = "article"

    publisher = ((work.get("host_venue") or {}).get("publisher")
                 or source_info.get("host_organization_name"))

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


# ─── Stage 3: Crossref verification ──────────────────────────

async def _crossref_verify_one(s: SourceRecord) -> Optional[SourceRecord]:
    query = s.title
    if s.authors:
        first = s.authors[0].split()[0]
        query += " " + first
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
                cr_type = item.get("type", "journal-article")
                if cr_type not in CROSSREF_ALLOWED_TYPES:
                    continue
                pub_date = (item.get("published") or {}).get("date-parts") or [[]]
                year = pub_date[0][0] if pub_date and pub_date[0] else s.year
                if year and year < MIN_YEAR_ARTICLES and s.source_type == "article":
                    return None
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
    verified: list[SourceRecord] = []
    for s, res in zip(sources, results):
        if isinstance(res, SourceRecord):
            verified.append(res)
        else:
            # Сохраняем curated и высокоскорные даже без Crossref
            if s.verified or s.score >= 3.0:
                verified.append(s)
    return verified


# ─── Stage 4: Format check ────────────────────────────────────

FORMAT_CHECK_PROMPT = """\
Ты — эксперт по библиографическому оформлению. Проверь список источников ниже на \
соответствие формату {fmt} и исправь ошибки оформления (пунктуация, порядок элементов, \
курсив для APA/Vancouver, нумерация).
НЕ добавляй и НЕ удаляй источники. НЕ придумывай данные (год, страницы, DOI, издательство).
Верни только исправленный пронумерованный список.

Список:
{sources}
"""


def _select_balanced(sources: list[SourceRecord], count: int) -> list[SourceRecord]:
    """Балансирует выборку: книги ≥40%, статьи ≤50%, стандарты/отчёты ≤20%."""
    buckets: dict[str, list[SourceRecord]] = {
        "book": [], "article": [], "standard": [], "report": [],
    }
    for s in sources:
        buckets.setdefault(s.source_type, []).append(s)

    quotas = {
        "book": max(2, round(count * 0.40)),
        "article": max(1, round(count * 0.45)),
        "standard": max(0, round(count * 0.10)),
        "report": max(0, round(count * 0.05)),
    }

    selected: list[SourceRecord] = []
    for kind in ["book", "standard", "report", "article"]:
        selected.extend(buckets.get(kind, [])[:quotas[kind]])

    if len(selected) < count:
        used_ids = {id(s) for s in selected}
        leftovers = [s for s in sources if id(s) not in used_ids]
        selected.extend(leftovers[:count - len(selected)])

    return selected[:count]


# ─── Main entry point ─────────────────────────────────────────

async def generate_sources_by_topic(topic: str, count: int, fmt: str, mode: str = "mixed") -> str:
    mode = mode if mode in OPENALEX_TYPES_BY_MODE else "mixed"

    # Stage 1a: Curated registry (мгновенно, без API, 100% реальные)
    curated = _inject_curated_sources(topic)

    # Stage 1b + Stage 2: LLM-учебники и OpenAlex — параллельно
    queries = build_search_queries(topic)
    openalex_types = OPENALEX_TYPES_BY_MODE[mode]

    openalex_tasks = [_openalex_query(q, openalex_types, per_page=25) for q in queries]
    llm_task = _llm_textbooks_stage(topic, count=max(6, count // 2))

    openalex_results, llm_books = await asyncio.gather(
        asyncio.gather(*openalex_tasks, return_exceptions=True),
        llm_task,
    )

    openalex_candidates: list[SourceRecord] = []
    for res in openalex_results:
        if isinstance(res, list):
            openalex_candidates.extend(res)

    # Объединяем: curated > llm > openalex
    pool = _dedupe_sources(curated + llm_books + openalex_candidates)

    if not pool:
        return (
            f"⚠️ По теме «{topic}» не удалось автоматически найти источники.\n\n"
            "Попробуй:\n"
            "• Уточнить тему покороче (например: «финансовый анализ» вместо длинной формулировки)\n"
            "• Использовать «🔗 Оформить свои» и вставить источники вручную"
        )

    # Скорируем (не трогаем curated — у них уже score=4.0)
    query_terms = [_norm(q) for q in queries]
    for c in pool:
        if c.score < 1.0:
            c.score = _relevance_score(c, query_terms)

    pool_sorted = sorted(pool, key=lambda x: x.score, reverse=True)

    # Stage 3: Crossref-верификация (только для непроверенных)
    to_verify = [s for s in pool_sorted if not s.verified][:max(40, count * 3)]
    already_verified = [s for s in pool_sorted if s.verified]

    crossref_result = await verify_sources_with_crossref(to_verify)

    final_pool = _dedupe_sources(already_verified + crossref_result)
    final_pool = sorted(final_pool, key=lambda x: x.score, reverse=True)

    selected = _select_balanced(final_pool, count)

    if not selected:
        return (
            f"⚠️ По теме «{topic}» не найдено достаточно надёжных источников.\n\n"
            "Попробуй уточнить тему или воспользуйся вариантом «🔗 Оформить свои»."
        )

    # Stage 4: первичное форматирование
    formatted = format_sources(selected, fmt)

    # Stage 5: LLM-проверка оформления
    check_prompt = FORMAT_CHECK_PROMPT.format(fmt=fmt, sources=formatted)
    try:
        formatted = await generate_text(check_prompt, max_tokens=2500)
    except Exception:
        pass

    note = ""
    if len(selected) < count:
        note = f"⚠️ Найдено {len(selected)} из {count} запрошенных источников.\n\n"

    return note + formatted


# ─── Own sources: verify before formatting ────────────────────

OWN_SOURCES_VERIFY_PROMPT = """\
Пользователь хочет оформить следующие источники:
{sources}

Для каждого источника выполни:
1. Проверь, существует ли он реально (автор + название + издательство/журнал).
2. Если источник реален и данные верны — оставь как есть, пометь ✅.
3. Если в данных ошибка (неверное название, несуществующий редактор, неверное издательство) \
и ты знаешь правильный вариант — исправь и пометь ✏️ с пояснением.
4. Если источник не существует или данных недостаточно — пометь ⚠️ и предложи \
2–3 реально существующих близких альтернативы с полными выходными данными.

Формат ответа (блок для каждого источника):
✅ [источник] — данные верны
✏️ [исправленный источник] — исправлено: [что именно]
⚠️ Не хватает данных / источник не найден: «[введённый текст]»
   Найдено по теме/автору:
   — [альтернатива 1 с полными данными]
   — [альтернатива 2 с полными данными]
"""


async def verify_own_sources(sources_text: str) -> str:
    """Верифицирует пользовательские источники перед оформлением."""
    prompt = OWN_SOURCES_VERIFY_PROMPT.format(sources=sources_text)
    return await generate_text(prompt, max_tokens=2500)


# ─── Backward-compat: used by collect_verified_sources if called directly ─

async def collect_verified_sources(topic: str, count: int = 20, mode: str = "mixed") -> list[SourceRecord]:
    """Legacy entry point — внутри использует новый пайплайн."""
    curated = _inject_curated_sources(topic)
    queries = build_search_queries(topic)
    openalex_types = OPENALEX_TYPES_BY_MODE.get(mode, OPENALEX_TYPES_BY_MODE["mixed"])

    candidates: list[SourceRecord] = list(curated)
    for q in queries:
        try:
            candidates.extend(await _openalex_query(q, openalex_types, per_page=25))
        except httpx.HTTPError:
            continue

    candidates = _dedupe_sources(candidates)
    if not candidates:
        return []

    query_terms = [_norm(q) for q in queries]
    for c in candidates:
        if c.score < 1.0:
            c.score = _relevance_score(c, query_terms)

    candidates = sorted(candidates, key=lambda x: x.score, reverse=True)[:max(60, count * 4)]
    verified = await verify_sources_with_crossref(candidates)
    return sorted(verified, key=lambda x: x.score, reverse=True)[:count]
