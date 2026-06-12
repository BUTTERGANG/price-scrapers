"""Route modules for the Grocery Price Scrapers API."""
from routes.health import router as health_router
from routes.stores import router as stores_router
from routes.products import router as products_router
from routes.deals import router as deals_router
from routes.watchlist import router as watchlist_router
from routes.scraper import router as scraper_router
from routes.dashboard import router as dashboard_router

__all__ = [
    "health_router",
    "stores_router",
    "products_router",
    "deals_router",
    "watchlist_router",
    "scraper_router",
    "dashboard_router",
]
