from apps.admin_api.main import create_app as create_admin_app
from apps.api.main import create_app as create_public_app


def test_public_api_exposes_public_routes_only() -> None:
    app = create_public_app()
    routes = {route.path for route in app.routes}

    assert "/health" in routes
    assert "/products" in routes
    assert "/products/{product_id}" in routes
    assert "/products/{product_id}/prices" in routes
    assert "/categories" in routes
    assert "/categories/price-summary" in routes

    assert "/canonical-products" not in routes
    assert "/product-matches/accept" not in routes
    assert "/product-normalization/queue" not in routes
    assert "/shop-source-candidates" not in routes
    assert "/scrapes/health" not in routes
    assert "/shops/{shop_id}/scrape/retry" not in routes


def test_public_api_has_no_mutation_routes() -> None:
    app = create_public_app()
    mutating_routes = [
        route.path
        for route in app.routes
        if getattr(route, "methods", set()) & {"POST", "PUT", "PATCH", "DELETE"}
    ]

    assert mutating_routes == []


def test_public_product_schema_excludes_admin_review_metadata() -> None:
    schema = create_public_app().openapi()
    product_schema = schema["components"]["schemas"]["PublicProductSearchItemResponse"]

    assert "category_override" not in product_schema["properties"]


def test_admin_api_exposes_admin_routes() -> None:
    app = create_admin_app()
    routes = {route.path for route in app.routes}

    assert "/health" in routes
    assert "/canonical-products" in routes
    assert "/catalog-quality/findings" in routes
    assert "/operator-decisions" in routes
    assert "/product-matches/accept" in routes
    assert "/product-normalization/queue" in routes
    assert "/shop-source-candidates" in routes
    assert "/scrapes/health" in routes
    assert "/shops/{shop_id}/scrape/retry" in routes
