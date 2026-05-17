"""Scraping orchestration services."""

from stroyhub.scraping.twogis import (
    TwogisPersistResult,
    TwogisScrapeResult,
    persist_twogis_scrape_result,
    scrape_twogis_branch,
)
from stroyhub.scraping.unicom import (
    UnicomPersistResult,
    UnicomScrapeResult,
    persist_unicom_scrape_result,
    scrape_unicom_category,
)

__all__ = [
    "TwogisPersistResult",
    "TwogisScrapeResult",
    "UnicomPersistResult",
    "UnicomScrapeResult",
    "persist_twogis_scrape_result",
    "persist_unicom_scrape_result",
    "scrape_twogis_branch",
    "scrape_unicom_category",
]
