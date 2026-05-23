from stroyhub import __version__

from apps.admin_api.main import create_app as create_admin_app
from apps.api.main import create_app


def test_package_version_is_available() -> None:
    assert __version__


def test_api_health_route_is_registered() -> None:
    app = create_app()

    routes = {route.path for route in app.routes}

    assert "/health" in routes


def test_admin_api_health_route_is_registered() -> None:
    app = create_admin_app()

    routes = {route.path for route in app.routes}

    assert "/health" in routes
