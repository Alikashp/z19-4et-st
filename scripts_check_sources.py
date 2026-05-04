import asyncio
from services.sources_pipeline import collect_verified_sources

TOPICS = [
    "проектное управление",
    "управление требованиями стейкхолдеров в ит-стартапе",
    "юридические аспекты международных стандартов",
    "аутоиммунные заболевания у детей и взрослых",
    "бизнес маркетплейсов",
]

async def main():
    failures = []
    for topic in TOPICS:
        sources = await collect_verified_sources(topic=topic, count=20, mode="mixed")
        n = len(sources)
        books = sum(1 for s in sources if s.source_type == "book")
        standards = sum(1 for s in sources if s.source_type == "standard")
        print(f"{topic}: total={n}, books={books}, standards={standards}")
        if n < 10:
            failures.append(f"{topic}: only {n}")

    if failures:
        raise SystemExit("\n".join(failures))

if __name__ == "__main__":
    asyncio.run(main())
