def enqueue_shop_scrape(shop_id: int) -> dict[str, object]:
    from apps.worker.tasks import scrape_shop

    try:
        task = scrape_shop.delay(shop_id)
    except Exception as exc:
        return {
            "shop_id": shop_id,
            "status": "enqueue_failed",
            "reason": str(exc),
        }
    return {
        "shop_id": shop_id,
        "status": "queued",
        "task_id": task.id,
    }
