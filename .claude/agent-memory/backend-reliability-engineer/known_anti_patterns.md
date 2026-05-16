---
name: Known anti-patterns and reliability gaps
description: Recurring issues found during the March 2026 reliability review — guides future review focus areas
type: feedback
---

**Why:** Documented during thorough review on 2026-03-26. Guides where to look first in future reviews.

Patterns to watch for in this codebase:

1. fetchone() without None guard — aggregate queries on an empty retailer return one NULL row, not zero rows. `dict(None)` raises TypeError. Always guard with `if row`.

2. Global boolean flags mutated outside their lock — `_scrape_running` is set False in the validation-failure path without holding `_scrape_lock`. Always use `with _scrape_lock` when writing shared state.

3. `import` statements inside loops — previously `import re as _re` appeared inside the Walmart item-parsing loop. Always hoist imports to module level.

4. `Retry-After` header parsed with bare `int()` — header value can be an HTTP-date string; bare int() raises ValueError and crashes the retry loop. Always wrap in try/except.

5. Config files read with bare `Path.read_text()` — missing file raises FileNotFoundError with no actionable message. Use a wrapper that gives the operator clear instructions.

6. TEXT timestamp columns — all date arithmetic must use explicit CAST or string slicing. Do not assume interval arithmetic works directly.

**How to apply:** When reviewing new code in this repo, check these five patterns first before broader review.
