# Walmart PerimeterX Bypass — WIP Research

Pushed to branch: `wip/walmart-px-bypass` (19 files, 2,978 lines)

## Three parallel approaches

### 1. Dual PX Solver (most advanced)
- `utils/px_solver.py` (620 lines) — core PX cookie generator with `curl_cffi`
- `walmart_px_session.py` (173 lines) — session manager orchestrating dual-layer solve
- `test_px.py` / `test_px2.py` / `test_px3.py` — incremental approach tests
- `test_dual_px.py` / `test_dual_px2.py` / `test_dual_v2.py` — dual-layer variants
- `test_full_chain.py` — end-to-end: solve → collect → scrape
- `test_fp_proxy.py` — first-party proxy collector endpoint
- `test_px_cloud.py` — cloud collector URL approach

**Status:** PX challenge can be extracted and solved in isolation. Dual-layer handshake with real Walmart session cookies not yet stabilized. Produces `_px3` and `_px2` cookies but Walmart still sometimes rejects.

### 2. Playwright-based (headful)
- `try_walmart_pw.py` (89 lines) — basic Playwright with headless Chrome
- `try_walmart_stealth.py` (139 lines) — with stealth plugin + user-agent rotation
- `try_walmart_xvfb.py` (96 lines) — Xvfb virtual display (non-headless mode, harder to detect)

**Status:** Playwright gets through page load but PX challenge still intercedes. Stealth plugin hasn't fully solved it. Xvfb approach needs further testing.

### 3. Direct request approaches
- `test_tls_px.py` (85 lines) — adapted from `snacsnoc/grocery-app` TLS fingerprint approach
- `test_preso.py` (30 lines) — fresh session, no PX layer awareness
- `grocery_app_walmart_px.py` (560 lines) — adapted from the existing grocery-app codebase

### 4. Health check infrastructure
- `run_full_check.py` (113 lines) — runs all working scrapers and reports results
- `test_collector_debug.py` (75 lines) — deep inspection of PX collector response cookies

## Key insight
PX cookie generation works in isolation (curl_cffi + safari17_0 impersonation). The gap is bridging the solved cookies back into a real Walmart session that accepts them. The first-party proxy endpoint (`/xhr/px/collector`) may be the cleanest path — it's designed to proxy PX traffic and may accept differently-sourced cookies.

## Resurrection
```bash
git checkout wip/walmart-px-bypass
# or cherry-pick individual files
git checkout wip/walmart-px-bypass -- utils/px_solver.py walmart_px_session.py
```