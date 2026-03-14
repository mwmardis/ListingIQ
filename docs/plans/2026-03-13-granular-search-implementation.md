# Granular Search Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add zip code and neighborhood search targeting with a saved watchlist to the dashboard.

**Architecture:** New `_build_search_url(query)` method on `ZillowScraper` converts user input (zip, neighborhood, metro) into Zillow URL slugs. New `WatchlistRow` table + repository methods + API endpoints power a saved-areas feature in the dashboard. The `/api/scan` endpoint gets a `query` parameter that accepts all three input formats.

**Tech Stack:** Python, SQLAlchemy, FastAPI, vanilla JS (existing dashboard)

---

### Task 1: URL Slug Builder — Tests

**Files:**
- Modify: `tests/test_scrapers.py`

**Step 1: Write failing tests for `_build_search_url`**

Add a new test class at the end of `tests/test_scrapers.py`:

```python
class TestBuildSearchUrl:
    def _make_scraper(self):
        cfg = ScraperConfig(search=SearchConfig(markets=["Houston, TX"]))
        return ZillowScraper(cfg)

    def test_metro_input(self):
        scraper = self._make_scraper()
        url = scraper._build_search_url("Houston, TX")
        assert url == "https://www.zillow.com/houston-tx/"

    def test_zip_code_input(self):
        scraper = self._make_scraper()
        url = scraper._build_search_url("77084")
        assert url == "https://www.zillow.com/houston-tx/77084/"

    def test_neighborhood_input(self):
        scraper = self._make_scraper()
        url = scraper._build_search_url("Spring Branch, Houston, TX")
        assert url == "https://www.zillow.com/spring-branch-houston-tx/"

    def test_neighborhood_multi_word_city(self):
        scraper = self._make_scraper()
        url = scraper._build_search_url("Downtown, San Antonio, TX")
        assert url == "https://www.zillow.com/downtown-san-antonio-tx/"

    def test_zip_with_spaces(self):
        scraper = self._make_scraper()
        url = scraper._build_search_url("  77084  ")
        assert url == "https://www.zillow.com/houston-tx/77084/"

    def test_metro_lowercase_handling(self):
        scraper = self._make_scraper()
        url = scraper._build_search_url("AUSTIN, TX")
        assert url == "https://www.zillow.com/austin-tx/"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scrapers.py::TestBuildSearchUrl -v`
Expected: FAIL with `AttributeError: 'ZillowScraper' object has no attribute '_build_search_url'`

---

### Task 2: URL Slug Builder — Implementation

**Files:**
- Modify: `listingiq/scrapers/zillow.py:52-75` (add method after `_build_search_params`)

**Step 1: Add `_build_search_url` method to `ZillowScraper`**

Add this method right after `_build_search_params` (after line 75):

```python
def _build_search_url(self, query: str) -> str:
    """Convert a search query (metro, zip, or neighborhood) to a Zillow URL.

    Formats:
        "Houston, TX"                    -> /houston-tx/
        "77084"                          -> /houston-tx/77084/
        "Spring Branch, Houston, TX"     -> /spring-branch-houston-tx/
    """
    query = query.strip()

    # Zip code: all digits
    if query.isdigit():
        # Use the first configured market for the metro slug
        metro = self.search.markets[0] if self.search.markets else ""
        parts = metro.split(",")
        city = parts[0].strip().replace(" ", "-").lower()
        state = parts[1].strip().lower() if len(parts) > 1 else ""
        metro_slug = f"{city}-{state}" if state else city
        return f"https://www.zillow.com/{metro_slug}/{query}/"

    # Contains commas: could be "City, ST" or "Neighborhood, City, ST"
    parts = [p.strip() for p in query.split(",")]
    slug = "-".join(parts).replace(" ", "-").lower()
    return f"https://www.zillow.com/{slug}/"
```

**Step 2: Update `_scrape_html` to use `_build_search_url`**

Replace the slug-building logic in `_scrape_html` (lines 122-127) so it delegates to the new method:

Old code (lines 121-127):
```python
    async def _scrape_html(self, fetcher: StealthyFetcher, market: str) -> list[Listing]:
        """Fallback: scrape the Zillow HTML search page."""
        city_state = market.split(",")
        city = city_state[0].strip().replace(" ", "-").lower()
        state = city_state[1].strip().lower() if len(city_state) > 1 else ""
        slug = f"{city}-{state}" if state else city

        url = f"https://www.zillow.com/{slug}/"
```

New code:
```python
    async def _scrape_html(self, fetcher: StealthyFetcher, market: str) -> list[Listing]:
        """Fallback: scrape the Zillow HTML search page."""
        url = self._build_search_url(market)
```

**Step 3: Run tests to verify they pass**

Run: `pytest tests/test_scrapers.py -v`
Expected: ALL PASS (both old and new tests)

**Step 4: Commit**

```bash
git add listingiq/scrapers/zillow.py tests/test_scrapers.py
git commit -m "feat: add URL slug builder for zip/neighborhood search targeting"
```

---

### Task 3: Watchlist Table and Repository — Tests

**Files:**
- Modify: `tests/test_db.py`

**Step 1: Write failing tests for watchlist repository methods**

Add to `tests/test_db.py`:

```python
class TestWatchlist:
    def _make_repo(self, tmp_path):
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        return Repository(db_url)

    def test_add_watchlist_entry(self, tmp_path):
        repo = self._make_repo(tmp_path)
        entry_id = repo.add_watchlist_entry("77084")
        assert entry_id is not None
        entries = repo.get_watchlist()
        assert len(entries) == 1
        assert entries[0].query == "77084"

    def test_add_watchlist_entry_with_label(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.add_watchlist_entry("77084", label="Cypress Area")
        entries = repo.get_watchlist()
        assert entries[0].label == "Cypress Area"

    def test_add_duplicate_watchlist_entry(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.add_watchlist_entry("77084")
        duplicate_id = repo.add_watchlist_entry("77084")
        assert duplicate_id is None
        entries = repo.get_watchlist()
        assert len(entries) == 1

    def test_add_duplicate_case_insensitive(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.add_watchlist_entry("Houston, TX")
        duplicate_id = repo.add_watchlist_entry("houston, tx")
        assert duplicate_id is None

    def test_delete_watchlist_entry(self, tmp_path):
        repo = self._make_repo(tmp_path)
        entry_id = repo.add_watchlist_entry("77084")
        deleted = repo.delete_watchlist_entry(entry_id)
        assert deleted is True
        assert repo.get_watchlist() == []

    def test_delete_nonexistent_entry(self, tmp_path):
        repo = self._make_repo(tmp_path)
        deleted = repo.delete_watchlist_entry(999)
        assert deleted is False

    def test_get_watchlist_ordered_by_created(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.add_watchlist_entry("77084")
        repo.add_watchlist_entry("77088")
        repo.add_watchlist_entry("Spring Branch, Houston, TX")
        entries = repo.get_watchlist()
        assert len(entries) == 3
        assert entries[0].query == "77084"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py::TestWatchlist -v`
Expected: FAIL with `AttributeError: 'Repository' object has no attribute 'add_watchlist_entry'`

---

### Task 4: Watchlist Table and Repository — Implementation

**Files:**
- Modify: `listingiq/db/tables.py` (add `WatchlistRow` after `AlertRow`, line 83)
- Modify: `listingiq/db/repository.py` (add watchlist methods + update import)

**Step 1: Add `WatchlistRow` to `tables.py`**

Add after the `AlertRow` class (after line 83):

```python
class WatchlistRow(Base):
    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query = Column(String(255), nullable=False, unique=True)
    label = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
```

**Step 2: Update import in `repository.py`**

Change line 10 from:
```python
from listingiq.db.tables import ListingRow, DealRow, AlertRow, init_db
```
to:
```python
from listingiq.db.tables import ListingRow, DealRow, AlertRow, WatchlistRow, init_db
```

**Step 3: Add watchlist methods to `Repository`**

Add these methods at the end of the `Repository` class:

```python
def add_watchlist_entry(self, query: str, label: str | None = None) -> int | None:
    """Add a watchlist entry. Returns ID or None if duplicate."""
    with self._session() as session:
        existing = (
            session.query(WatchlistRow)
            .filter(WatchlistRow.query.ilike(query.strip()))
            .first()
        )
        if existing:
            return None
        row = WatchlistRow(query=query.strip(), label=label)
        session.add(row)
        session.commit()
        return row.id

def delete_watchlist_entry(self, entry_id: int) -> bool:
    """Delete a watchlist entry by ID. Returns True if deleted."""
    with self._session() as session:
        row = session.query(WatchlistRow).get(entry_id)
        if not row:
            return False
        session.delete(row)
        session.commit()
        return True

def get_watchlist(self) -> list[WatchlistRow]:
    """Get all watchlist entries ordered by creation date."""
    with self._session() as session:
        return (
            session.query(WatchlistRow)
            .order_by(WatchlistRow.created_at.asc())
            .all()
        )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py::TestWatchlist -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add listingiq/db/tables.py listingiq/db/repository.py tests/test_db.py
git commit -m "feat: add watchlist table and repository methods"
```

---

### Task 5: API Endpoints — Tests

**Files:**
- Create: `tests/test_api.py`

**Step 1: Write failing tests for watchlist API endpoints**

```python
"""Tests for watchlist API endpoints and updated scan query param."""

import pytest
from fastapi.testclient import TestClient

from listingiq.config import AppConfig
from listingiq.api.server import create_app


@pytest.fixture
def client(tmp_path):
    cfg = AppConfig()
    cfg.database.url = f"sqlite:///{tmp_path / 'test.db'}"
    app = create_app(cfg)
    return TestClient(app)


class TestWatchlistAPI:
    def test_get_empty_watchlist(self, client):
        resp = client.get("/api/watchlist")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_add_watchlist_entry(self, client):
        resp = client.post("/api/watchlist", json={"query": "77084"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] is not None
        assert data["query"] == "77084"

    def test_add_watchlist_entry_with_label(self, client):
        resp = client.post("/api/watchlist", json={"query": "77084", "label": "Cypress"})
        assert resp.status_code == 200
        assert resp.json()["label"] == "Cypress"

    def test_add_duplicate_returns_409(self, client):
        client.post("/api/watchlist", json={"query": "77084"})
        resp = client.post("/api/watchlist", json={"query": "77084"})
        assert resp.status_code == 409

    def test_delete_watchlist_entry(self, client):
        resp = client.post("/api/watchlist", json={"query": "77084"})
        entry_id = resp.json()["id"]
        resp = client.delete(f"/api/watchlist/{entry_id}")
        assert resp.status_code == 200
        assert client.get("/api/watchlist").json() == []

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/watchlist/999")
        assert resp.status_code == 404

    def test_get_watchlist_returns_entries(self, client):
        client.post("/api/watchlist", json={"query": "77084"})
        client.post("/api/watchlist", json={"query": "77088"})
        resp = client.get("/api/watchlist")
        assert len(resp.json()) == 2


class TestScanQueryParam:
    def test_scan_accepts_query_param(self, client):
        """Verify the /api/scan endpoint accepts a query parameter."""
        # We cannot test actual scraping without mocking, but we can verify
        # the endpoint accepts the parameter without a 422 validation error
        resp = client.get("/api/scan?query=77084&source=zillow&min_score=50")
        assert resp.status_code != 422
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -v`
Expected: FAIL (404 on watchlist routes)

---

### Task 6: API Endpoints — Implementation

**Files:**
- Modify: `listingiq/api/server.py` (imports + add endpoints + update scan)

**Step 1: Update imports at top of `server.py`**

Change line 8 from:
```python
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
```
to:
```python
from fastapi import FastAPI, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse
```

**Step 2: Update `/api/scan` endpoint signature**

Add `query` parameter to the scan function (line 35-40):
```python
@app.get("/api/scan")
async def scan(
    market: str = Query(None),
    query: str = Query(None),
    source: str = Query(None),
    min_score: int = Query(70),
    limit: int = Query(20),
):
```

Update the market resolution logic (line 42-44):
```python
    scraper_cfg = cfg.scraper.model_copy(deep=True)
    search_query = query or market
    if search_query:
        scraper_cfg.search.markets = [search_query]
```

**Step 3: Add watchlist endpoints inside `create_app()`**

Add before the `return app` line:

```python
@app.get("/api/watchlist")
async def get_watchlist():
    """List all saved watchlist areas."""
    entries = repo.get_watchlist()
    return [
        {
            "id": e.id,
            "query": e.query,
            "label": e.label,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entries
    ]

@app.post("/api/watchlist")
async def add_watchlist_entry(body: dict = Body(...)):
    """Add a search area to the watchlist."""
    query_str = body.get("query", "").strip()
    if not query_str:
        return JSONResponse({"error": "query is required"}, status_code=400)
    label = body.get("label")
    entry_id = repo.add_watchlist_entry(query_str, label=label)
    if entry_id is None:
        return JSONResponse(
            {"error": f"'{query_str}' is already in your watchlist"},
            status_code=409,
        )
    return {"id": entry_id, "query": query_str, "label": label}

@app.delete("/api/watchlist/{entry_id}")
async def delete_watchlist_entry(entry_id: int):
    """Remove a search area from the watchlist."""
    deleted = repo.delete_watchlist_entry(entry_id)
    if not deleted:
        return JSONResponse({"error": "Entry not found"}, status_code=404)
    return {"ok": True}
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add listingiq/api/server.py tests/test_api.py
git commit -m "feat: add watchlist API endpoints and query param for scan"
```

---

### Task 7: Dashboard UI — Watchlist Chips and Save Button

**Files:**
- Modify: `listingiq/api/server.py` (dashboard HTML, ~lines 1235-1260 and JS section)

**Step 1: Update the scan form HTML**

In the scan parameters section, make these changes:

a) Change the "Market" label (line 1241) to "Search":
```html
<label>Search</label>
```

b) Update the input placeholder (line 1242):
```html
<input type="text" id="market" placeholder="Houston, TX  or  77084  or  Spring Branch, Houston, TX" value="Houston, TX">
```

c) Update the source dropdown (line 1246-1248) from Repliers to Zillow:
```html
<select id="source">
    <option value="zillow">Zillow</option>
</select>
```

d) Add a "Save Area" button next to "Scan for Deals" in the `btn-row` div (after line 1259):
```html
<button class="btn btn-secondary" onclick="saveToWatchlist()" title="Save this search area">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>
    Save Area
</button>
```

e) Add a watchlist container div after the `btn-row` div (before closing `</div>` of the glass-card):
```html
<div id="watchlist-bar" style="display:none; margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border);">
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.75rem;">
        <span style="font-size: 0.8rem; color: var(--text-secondary);">Saved Areas</span>
        <button class="btn btn-primary" onclick="scanAll()" style="padding: 0.4rem 1rem; font-size: 0.8rem;">Scan All</button>
    </div>
    <div id="watchlist-chips" style="display: flex; flex-wrap: wrap; gap: 0.5rem;"></div>
</div>
```

**Step 2: Add CSS for watchlist chips**

Add to the `<style>` section (before the closing `</style>` tag):
```css
.watchlist-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.35rem 0.75rem;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 20px;
    font-size: 0.8rem;
    color: var(--text-secondary);
    cursor: pointer;
    transition: all 0.2s;
}
.watchlist-chip:hover {
    border-color: var(--accent);
    color: var(--text-primary);
}
.watchlist-chip .chip-remove {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: transparent;
    border: none;
    color: var(--text-muted);
    font-size: 14px;
    cursor: pointer;
    line-height: 1;
}
.watchlist-chip .chip-remove:hover {
    background: var(--red-dim);
    color: var(--red);
}
```

**Step 3: Update `runScan` JS to use `query` param and show empty-result hint**

Change the fetch URL in `runScan()` from `market` to `query` param:
```javascript
const resp = await fetch(
    `/api/scan?query=${encodeURIComponent(market)}&source=${source}&min_score=${minScore}`
);
```

After `if (data.error) { ... }`, add a zero-results check:
```javascript
if (data.total_listings === 0) {
    const dealsEl = document.getElementById('deals');
    dealsEl.textContent = '';
    const hint = document.createElement('div');
    hint.className = 'glass-card';
    const p = document.createElement('p');
    p.style.color = 'var(--gold)';
    p.textContent = 'No listings found for this search. For zip codes, try "77084". For neighborhoods, use "Spring Branch, Houston, TX".';
    hint.appendChild(p);
    dealsEl.appendChild(hint);
    document.getElementById('stats').style.display = 'none';
    return;
}
```

**Step 4: Add watchlist JS functions**

Add these functions to the `<script>` section (after `runScan`):

```javascript
async function loadWatchlist() {
    try {
        const resp = await fetch('/api/watchlist');
        const entries = await resp.json();
        const bar = document.getElementById('watchlist-bar');
        const chips = document.getElementById('watchlist-chips');
        if (!entries.length) {
            bar.style.display = 'none';
            return;
        }
        bar.style.display = 'block';
        chips.textContent = '';
        entries.forEach(e => {
            const chip = document.createElement('div');
            chip.className = 'watchlist-chip';
            chip.addEventListener('click', () => searchArea(e.query));
            const label = document.createElement('span');
            label.textContent = e.label || e.query;
            chip.appendChild(label);
            const removeBtn = document.createElement('button');
            removeBtn.className = 'chip-remove';
            removeBtn.title = 'Remove';
            removeBtn.textContent = '\u00d7';
            removeBtn.addEventListener('click', (evt) => {
                evt.stopPropagation();
                removeFromWatchlist(e.id);
            });
            chip.appendChild(removeBtn);
            chips.appendChild(chip);
        });
    } catch (e) {
        console.error('Failed to load watchlist:', e);
    }
}

async function saveToWatchlist() {
    const query = document.getElementById('market').value.trim();
    if (!query) return;
    try {
        const resp = await fetch('/api/watchlist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query })
        });
        if (resp.status === 409) return;
        await loadWatchlist();
    } catch (e) {
        console.error('Failed to save:', e);
    }
}

async function removeFromWatchlist(id) {
    try {
        await fetch('/api/watchlist/' + id, { method: 'DELETE' });
        await loadWatchlist();
    } catch (e) {
        console.error('Failed to remove:', e);
    }
}

function searchArea(query) {
    document.getElementById('market').value = query;
    runScan();
}

async function scanAll() {
    const resp = await fetch('/api/watchlist');
    const entries = await resp.json();
    if (!entries.length) return;

    document.getElementById('loading').classList.add('visible');
    const dealsEl = document.getElementById('deals');
    dealsEl.textContent = '';
    document.getElementById('stats').style.display = 'none';

    const source = document.getElementById('source').value;
    const minScore = document.getElementById('min-score').value;

    let allDeals = [];
    let totalListings = 0;
    const seenAddresses = new Set();

    for (const entry of entries) {
        try {
            const r = await fetch(
                '/api/scan?query=' + encodeURIComponent(entry.query) + '&source=' + source + '&min_score=' + minScore
            );
            const data = await r.json();
            if (data.error) continue;
            totalListings += data.total_listings;
            for (const deal of data.deals) {
                if (!seenAddresses.has(deal.address)) {
                    seenAddresses.add(deal.address);
                    allDeals.push(deal);
                }
            }
        } catch (e) {
            console.error('Scan failed for ' + entry.query + ':', e);
        }
    }

    allDeals.sort((a, b) => b.score - a.score);

    document.getElementById('stat-listings').textContent = totalListings.toLocaleString();
    document.getElementById('stat-deals').textContent = allDeals.length;
    document.getElementById('stat-best').textContent =
        allDeals.length ? allDeals[0].score : '\u2014';
    document.getElementById('stats').style.display = 'grid';

    renderDeals(allDeals);
    document.getElementById('loading').classList.remove('visible');
}

document.addEventListener('DOMContentLoaded', loadWatchlist);
```

**Step 5: Commit**

```bash
git add listingiq/api/server.py
git commit -m "feat: add watchlist UI with chips, save button, and scan-all"
```

---

### Task 8: Scheduler Watchlist Integration

**Files:**
- Modify: `listingiq/scheduler.py` (lines 22-39)

**Step 1: Update `_run_cycle` to use watchlist when available**

In `_run_cycle`, after creating the `repo` (line 26), add watchlist-aware market resolution:

```python
repo = Repository(cfg.database.url)
all_listings: list[Listing] = []

# Use watchlist entries if available, otherwise configured markets
watchlist = repo.get_watchlist()
if watchlist:
    markets = [entry.query for entry in watchlist]
    logger.info("Using %d watchlist areas", len(markets))
else:
    markets = cfg.scraper.search.markets
```

Then update the scraper loop (lines 30-39) to pass resolved markets:

```python
for source_name in cfg.scraper.sources:
    try:
        scraper_cls = get_scraper(source_name)
        scraper_cfg = cfg.scraper.model_copy(deep=True)
        scraper_cfg.search.markets = markets
        scraper = scraper_cls(scraper_cfg)
        listings = await scraper.scrape()
        all_listings.extend(listings)
        logger.info("%s: found %d listings", source_name, len(listings))
        await scraper.close()
    except Exception as e:
        logger.error("Error scraping %s: %s", source_name, e)
```

**Step 2: Add deduplication after collecting all listings**

After the scraper loop, before `if not all_listings:`:

```python
# Deduplicate by source_id (overlapping areas may return same listing)
seen_ids: set[str] = set()
unique_listings: list[Listing] = []
for listing in all_listings:
    if listing.source_id not in seen_ids:
        seen_ids.add(listing.source_id)
        unique_listings.append(listing)
all_listings = unique_listings
```

**Step 3: Commit**

```bash
git add listingiq/scheduler.py
git commit -m "feat: scheduler uses watchlist areas when available"
```

---

### Task 9: Full Integration Test

**Step 1: Run the full test suite**

Run: `pytest tests/ -v`
Expected: ALL PASS

**Step 2: Manual smoke test**

```bash
source .venv/Scripts/activate && listingiq serve --port 8000
```

Test in browser at http://localhost:8000:
1. Search "77084" — should return zip-targeted listings
2. Search "Spring Branch, Houston, TX" — should return neighborhood listings
3. Click "Save Area" — chip appears below search bar
4. Click a chip — runs that search
5. Click X on chip — removes it
6. Add 2-3 areas, click "Scan All" — merges results, sorted by score

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat: granular search with zip/neighborhood targeting and watchlist"
```
