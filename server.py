import os
import uvicorn
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from utils import get_conn, find_active_deals, cheapest_per_retailer

app = FastAPI(title="Price Scrapers API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/deals")
def get_deals(min_pct: float = Query(10.0, ge=0.0)):
    conn = get_conn()
    try:
        deals = find_active_deals(conn, min_pct)
        return {"deals": deals}
    finally:
        conn.close()

@app.get("/api/search")
def search_items(q: str = Query(..., min_length=2)):
    conn = get_conn()
    try:
        results = cheapest_per_retailer(conn, q)
        return {"results": results}
    finally:
        conn.close()

@app.get("/api/stores")
def get_stores():
    from telegram_bot import _last_run_times
    run_times = _last_run_times()
    return {"stores": run_times}

# Serve Vite build if it exists
if os.path.exists("frontend/dist"):
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
