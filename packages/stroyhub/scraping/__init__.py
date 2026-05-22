"""Scraping orchestration services."""

from stroyhub.scraping.metalltorg import (
    MetalltorgPersistResult,
    MetalltorgScrapeResult,
    MetalltorgShopScrapeConfig,
    MetalltorgShopScrapeResult,
    metalltorg_shop_scrape_config,
    persist_metalltorg_scrape_failure,
    persist_metalltorg_scrape_result,
    scrape_metalltorg_category,
    scrape_metalltorg_shop,
)
from stroyhub.scraping.twogis import (
    TwogisPersistResult,
    TwogisScrapeResult,
    persist_twogis_scrape_result,
    scrape_twogis_branch,
)
from stroyhub.scraping.unicom import (
    UnicomPersistResult,
    UnicomScrapeResult,
    UnicomShopScrapeConfig,
    UnicomShopScrapeResult,
    persist_unicom_scrape_failure,
    persist_unicom_scrape_result,
    scrape_unicom_category,
    scrape_unicom_shop,
    unicom_shop_scrape_config,
)

__all__ = [
    "TwogisPersistResult",
    "TwogisScrapeResult",
    "MetalltorgPersistResult",
    "MetalltorgScrapeResult",
    "MetalltorgShopScrapeConfig",
    "MetalltorgShopScrapeResult",
    "UnicomShopScrapeConfig",
    "UnicomShopScrapeResult",
    "UnicomPersistResult",
    "UnicomScrapeResult",
    "metalltorg_shop_scrape_config",
    "persist_metalltorg_scrape_failure",
    "persist_metalltorg_scrape_result",
    "persist_unicom_scrape_failure",
    "persist_twogis_scrape_result",
    "persist_unicom_scrape_result",
    "scrape_metalltorg_category",
    "scrape_metalltorg_shop",
    "scrape_twogis_branch",
    "scrape_unicom_category",
    "scrape_unicom_shop",
    "unicom_shop_scrape_config",
]
