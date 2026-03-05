# ListingIQ Feature Roadmap Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the flip-biased deal scanner, add multi-family support, days-on-market offer adjustments, room addition potential, mortgage points calculator, secondary data display, and automated email digests.

**Architecture:** Three tiers of changes — Tier 1 fixes the foundation (data model, scanner rebalancing, multi-family), Tier 2 adds new analysis capabilities (DOM, room potential, offer calc, secondary display), Tier 3 adds automation (instant alerts, digests). All changes are additive with backward-compatible defaults.

**Tech Stack:** Python 3.10+, Pydantic v2, FastAPI, SQLAlchemy v2, APScheduler, aiosmtplib, pytest

---

### Task 1: Expand Listing Data Model

**Files:**
- Modify: `listingiq/models.py:32-56` (Listing class)
- Test: `tests/test_models.py`

**Step 1: Write the failing test**

In `tests/test_models.py`, add:

```python
from listingiq.models import Listing, UnitMix

def _make_listing(**overrides) -> Listing:
    defaults = {
        "source": "test",
        "source_id": "test-1",
        "address": "100 Investor Blvd",
        "city": "Austin",
        "state": "TX",
        "zip_code": "78701",
        "price": 200_000,
        "beds": 3,
        "baths": 2,
        "sqft": 1400,
        "tax_annual": 3600,
    }
    defaults.update(overrides)
    return Listing(**defaults)


class TestListingNewFields:
    def test_defaults_backward_compatible(self):
        """Existing listing creation still works without new fields."""
        listing = _make_listing()
        assert listing.units == 1
        assert listing.has_pool is None
        assert listing.stories == 0
        assert listing.school_rating is None
        assert listing.flood_zone is None
        assert listing.crime_score is None

    def test_new_fields_set_explicitly(self):
        listing = _make_listing(
            units=2, has_pool=True, stories=2,
            school_rating=7.5, flood_zone="X", crime_score=3.2,
        )
        assert listing.units == 2
        assert listing.has_pool is True
        assert listing.stories == 2
        assert listing.school_rating == 7.5
        assert listing.flood_zone == "X"
        assert listing.crime_score == 3.2

    def test_multi_family_units(self):
        listing = _make_listing(units=4)
        assert listing.units == 4


class TestUnitMix:
    def test_create_unit_mix(self):
        unit = UnitMix(unit_number=1, beds=2, baths=1, sqft=800, estimated_rent=1200.0)
        assert unit.unit_number == 1
        assert unit.estimated_rent == 1200.0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `UnitMix` not importable, new fields not on Listing

**Step 3: Write minimal implementation**

In `listingiq/models.py`, add to the `Listing` class (after `tax_annual`):

```python
    units: int = 1
    has_pool: Optional[bool] = None
    stories: int = 0
    school_rating: Optional[float] = None
    flood_zone: Optional[str] = None
    crime_score: Optional[float] = None
```

Add new model after `Listing`:

```python
class UnitMix(BaseModel):
    """Per-unit breakdown for small multi-family (2-4 units)."""
    unit_number: int
    beds: int = 0
    baths: float = 0
    sqft: int = 0
    estimated_rent: float = 0.0
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add listingiq/models.py tests/test_models.py
git commit -m "feat: expand Listing model with units, pool, stories, school, flood, crime fields"
```

---

### Task 2: Expand DB Schema for New Fields

**Files:**
- Modify: `listingiq/db/tables.py:26-53` (ListingRow)
- Modify: `listingiq/db/repository.py:47-72` (upsert_listing)
- Test: `tests/test_db.py`

**Step 1: Write the failing test**

In `tests/test_db.py`, add a test that creates a listing with new fields and verifies they persist:

```python
def test_upsert_listing_with_new_fields(tmp_db):
    """New fields (units, has_pool, etc.) are stored and retrievable."""
    from listingiq.models import Listing
    listing = Listing(
        source="test", source_id="new-fields-1",
        address="123 Test St", city="Austin", state="TX", zip_code="78701",
        price=200_000, beds=3, baths=2, sqft=1400,
        units=2, has_pool=True, stories=2,
        school_rating=8.0, flood_zone="X", crime_score=2.5,
    )
    row_id = tmp_db.upsert_listing(listing)
    row = tmp_db.get_listing_by_id(row_id)
    assert row.units == 2
    assert row.has_pool is True
    assert row.stories == 2
    assert row.school_rating == 8.0
    assert row.flood_zone == "X"
    assert row.crime_score == 2.5
```

If `tests/test_db.py` doesn't have a `tmp_db` fixture, create one:

```python
import pytest
from listingiq.db.repository import Repository

@pytest.fixture
def tmp_db(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    return Repository(db_url)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py::test_upsert_listing_with_new_fields -v`
Expected: FAIL — columns don't exist

**Step 3: Write minimal implementation**

In `listingiq/db/tables.py`, add columns to `ListingRow` after `tax_annual`:

```python
    units = Column(Integer, default=1)
    has_pool = Column(Boolean, nullable=True)
    stories = Column(Integer, default=0)
    school_rating = Column(Float, nullable=True)
    flood_zone = Column(String(20), nullable=True)
    crime_score = Column(Float, nullable=True)
```

In `listingiq/db/repository.py`, update `upsert_listing` — add to the `ListingRow(...)` constructor:

```python
    units=listing.units,
    has_pool=listing.has_pool,
    stories=listing.stories,
    school_rating=listing.school_rating,
    flood_zone=listing.flood_zone,
    crime_score=listing.crime_score,
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add listingiq/db/tables.py listingiq/db/repository.py tests/test_db.py
git commit -m "feat: add new listing columns to DB schema (units, pool, school, flood, crime)"
```

---

### Task 3: Enhance Zillow Scraper to Extract New Fields

**Note:** Redfin and Realtor.com scrapers have been removed. Zillow is the sole scraper source.

---

### Task 4: Fix Flip ARV Fallback — Age-Aware Conservative Estimate

**Files:**
- Modify: `listingiq/analysis/flip.py:37-53` (_calculate_metrics)
- Modify: `listingiq/analysis/offer.py:206-212` (_calc_flip_offer ARV fallback)
- Test: `tests/test_analysis.py`

**Step 1: Write the failing test**

Add to `tests/test_analysis.py` in `TestFlipAnalyzer`:

```python
    def test_arv_fallback_age_aware_new_home(self):
        """New home (<15 years) gets conservative 1.15x ARV fallback."""
        listing = _make_listing(price=300_000, sqft=1500, year_built=2015)
        deal = self.analyzer.analyze(listing)
        # 300k * 1.15 = 345k, NOT 300k / 0.65 = 461k
        assert deal.metrics["estimated_arv"] == pytest.approx(345_000, rel=0.01)

    def test_arv_fallback_age_aware_mid_age(self):
        """Mid-age home (15-30 years) gets 1.25x ARV fallback."""
        listing = _make_listing(price=300_000, sqft=1500, year_built=2000)
        deal = self.analyzer.analyze(listing)
        assert deal.metrics["estimated_arv"] == pytest.approx(375_000, rel=0.01)

    def test_arv_fallback_age_aware_old_home(self):
        """Old home (30+ years) gets 1.35x ARV fallback."""
        listing = _make_listing(price=300_000, sqft=1500, year_built=1980)
        deal = self.analyzer.analyze(listing)
        assert deal.metrics["estimated_arv"] == pytest.approx(405_000, rel=0.01)

    def test_arv_fallback_unknown_age(self):
        """Unknown year_built (0) uses middle multiplier 1.25."""
        listing = _make_listing(price=300_000, sqft=1500, year_built=0)
        deal = self.analyzer.analyze(listing)
        assert deal.metrics["estimated_arv"] == pytest.approx(375_000, rel=0.01)

    def test_arv_override_still_works(self):
        """Comp-based ARV override still takes precedence."""
        listing = _make_listing(price=300_000, sqft=1500, year_built=2015)
        deal = self.analyzer.analyze(listing, arv_estimate=500_000)
        assert deal.metrics["estimated_arv"] == 500_000
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis.py::TestFlipAnalyzer::test_arv_fallback_age_aware_new_home -v`
Expected: FAIL — current fallback uses `price / 0.65` = $461,538

**Step 3: Write minimal implementation**

In `listingiq/analysis/flip.py`, replace lines 47-48 in `_calculate_metrics`:

```python
        if arv_estimate is not None:
            estimated_arv = arv_estimate
        else:
            # Age-aware ARV fallback (conservative)
            if listing.year_built > 0:
                age = 2026 - listing.year_built
                if age < 15:
                    multiplier = 1.15
                elif age < 30:
                    multiplier = 1.25
                else:
                    multiplier = 1.35
            else:
                multiplier = 1.25  # default for unknown age
            estimated_arv = purchase_price * multiplier
```

Apply the SAME change in `listingiq/analysis/offer.py` in `_calc_flip_offer` (lines 206-208):

```python
        if arv_estimate:
            estimated_arv = arv_estimate
        else:
            if listing.year_built > 0:
                age = 2026 - listing.year_built
                if age < 15:
                    multiplier = 1.15
                elif age < 30:
                    multiplier = 1.25
                else:
                    multiplier = 1.35
            else:
                multiplier = 1.25
            estimated_arv = listing.price * multiplier
```

Also apply the same change in `listingiq/analysis/brrr.py` (lines 54-55) since BRRR uses the same pattern:

```python
        if arv_estimate is not None:
            estimated_arv = arv_estimate
        else:
            if listing.year_built > 0:
                age = 2026 - listing.year_built
                if age < 15:
                    multiplier = 1.15
                elif age < 30:
                    multiplier = 1.25
                else:
                    multiplier = 1.35
            else:
                multiplier = 1.25
            estimated_arv = purchase_price * multiplier
```

**Step 4: Run ALL tests to verify nothing broke**

Run: `pytest tests/ -v`
Expected: New tests PASS. Some existing tests may need adjustment since ARV values will change. Update expected values in any affected tests.

**Step 5: Commit**

```bash
git add listingiq/analysis/flip.py listingiq/analysis/brrr.py listingiq/analysis/offer.py tests/test_analysis.py
git commit -m "fix: replace generous ARV fallback with age-aware conservative estimate"
```

---

### Task 5: Lower Cash Flow min_cap_rate Default and Add Score Efficiency

**Files:**
- Modify: `listingiq/config.py:62` (CashFlowConfig min_cap_rate)
- Modify: `config/default.toml:66` (min_cap_rate)
- Modify: `listingiq/analysis/cashflow.py:129-180` (_score)
- Test: `tests/test_analysis.py`

**Step 1: Write the failing test**

Add to `tests/test_analysis.py` in `TestCashFlowAnalyzer`:

```python
    def test_cap_rate_default_lowered(self):
        """Default min_cap_rate should be 5.0 not 6.0."""
        from listingiq.config import CashFlowConfig
        cfg = CashFlowConfig()
        assert cfg.min_cap_rate == 5.0

    def test_cheap_property_not_penalized(self):
        """A $80k property with good rent shouldn't score worse than expensive one."""
        cheap = _make_listing(price=80_000, sqft=900)
        expensive = _make_listing(price=250_000, sqft=1800)
        deal_cheap = self.analyzer.analyze(cheap, rent_estimate=1_000)
        deal_expensive = self.analyzer.analyze(expensive, rent_estimate=2_000)
        # Cheap property has $1000 rent on $80k — much better ratio
        # Should score at least as well as expensive
        assert deal_cheap.score >= deal_expensive.score
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis.py::TestCashFlowAnalyzer::test_cap_rate_default_lowered -v`
Expected: FAIL — current default is 6.0

**Step 3: Write minimal implementation**

In `listingiq/config.py` line 62, change:
```python
    min_cap_rate: float = 5.0
```

In `config/default.toml` line 66, change:
```toml
min_cap_rate = 5.0
```

In `listingiq/analysis/cashflow.py`, modify `_score` to add an efficiency component. Replace the monthly cash flow scoring section (lines 132-142) with:

```python
        # Monthly cash flow (up to 25 points)
        if m.monthly_cash_flow >= 500:
            score += 25
        elif m.monthly_cash_flow >= 300:
            score += 18
        elif m.monthly_cash_flow >= 200:
            score += 13
        elif m.monthly_cash_flow >= 100:
            score += 7
        elif m.monthly_cash_flow > 0:
            score += 3

        # Cash flow efficiency — cash flow per dollar invested (up to 10 points)
        if m.down_payment > 0:
            monthly_per_dollar = m.monthly_cash_flow / m.down_payment * 1000
            if monthly_per_dollar >= 15:
                score += 10
            elif monthly_per_dollar >= 10:
                score += 7
            elif monthly_per_dollar >= 5:
                score += 4
            elif monthly_per_dollar > 0:
                score += 2
```

This splits the 35 points into 25 for absolute cash flow + 10 for efficiency, keeping the total at 35.

**Step 4: Run tests**

Run: `pytest tests/ -v`
Expected: PASS

**Step 5: Commit**

```bash
git add listingiq/config.py config/default.toml listingiq/analysis/cashflow.py tests/test_analysis.py
git commit -m "fix: lower cap rate default to 5%, add cash flow efficiency scoring"
```

---

### Task 6: Multi-Family Per-Unit Rent Analysis

**Files:**
- Modify: `listingiq/analysis/cashflow.py:38-57` (_calculate_metrics rent section)
- Modify: `listingiq/analysis/brrr.py:43-76` (_calculate_metrics rent section)
- Test: `tests/test_analysis.py`

**Step 1: Write the failing test**

Add to `tests/test_analysis.py`:

```python
class TestMultiFamilyAnalysis:
    def test_cashflow_duplex_uses_aggregate_rent(self):
        """Duplex should estimate rent per unit and aggregate."""
        cfg = CashFlowConfig()
        analyzer = CashFlowAnalyzer(cfg)
        duplex = _make_listing(price=200_000, sqft=2000, beds=4, baths=2, units=2)
        single = _make_listing(price=200_000, sqft=2000, beds=4, baths=2, units=1)
        deal_duplex = analyzer.analyze(duplex)
        deal_single = analyzer.analyze(single)
        # Duplex should have higher rent estimate (2 units rented separately)
        assert deal_duplex.metrics["monthly_rent_estimate"] > deal_single.metrics["monthly_rent_estimate"]

    def test_brrr_duplex_uses_aggregate_rent(self):
        brrr_cfg = BRRRConfig()
        cf_cfg = CashFlowConfig()
        analyzer = BRRRAnalyzer(brrr_cfg, cf_cfg)
        duplex = _make_listing(price=200_000, sqft=2000, beds=4, baths=2, units=2)
        single = _make_listing(price=200_000, sqft=2000, beds=4, baths=2, units=1)
        deal_duplex = analyzer.analyze(duplex)
        deal_single = analyzer.analyze(single)
        assert deal_duplex.metrics["monthly_rent_estimate"] > deal_single.metrics["monthly_rent_estimate"]

    def test_single_family_unaffected(self):
        """units=1 should produce identical results to current behavior."""
        cfg = CashFlowConfig()
        analyzer = CashFlowAnalyzer(cfg)
        listing = _make_listing(units=1)
        deal = analyzer.analyze(listing)
        assert deal.metrics["monthly_rent_estimate"] > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis.py::TestMultiFamilyAnalysis -v`
Expected: FAIL — duplex and single produce same rent

**Step 3: Write minimal implementation**

In `listingiq/analysis/cashflow.py`, modify the rent estimation section in `_calculate_metrics` (around line 52-56):

```python
        # Income — use comp-based rent if available, otherwise fall back to percentage
        if rent_estimate is not None:
            monthly_rent = rent_estimate
        else:
            monthly_rent = purchase_price * self.cfg.rent_estimate_pct

        # Multi-family: multiply per-unit rent by unit count
        if listing.units > 1 and rent_estimate is None:
            # Estimate per-unit rent based on per-unit sqft
            per_unit_sqft = listing.sqft / listing.units if listing.sqft else 0
            per_unit_rent = per_unit_sqft * 1.10 if per_unit_sqft else purchase_price * self.cfg.rent_estimate_pct / listing.units
            monthly_rent = per_unit_rent * listing.units
```

Apply a similar pattern in `listingiq/analysis/brrr.py` (around lines 72-76):

```python
        # Rental income — use comp-based rent if available, otherwise estimate
        if rent_estimate is not None:
            monthly_rent_arv = rent_estimate
        else:
            monthly_rent_arv = estimated_arv * self.cf_cfg.rent_estimate_pct

        # Multi-family: multiply per-unit rent by unit count
        if listing.units > 1 and rent_estimate is None:
            per_unit_sqft = listing.sqft / listing.units if listing.sqft else 0
            per_unit_rent = per_unit_sqft * 1.10 if per_unit_sqft else estimated_arv * self.cf_cfg.rent_estimate_pct / listing.units
            monthly_rent_arv = per_unit_rent * listing.units
```

**Step 4: Run tests**

Run: `pytest tests/ -v`
Expected: PASS

**Step 5: Commit**

```bash
git add listingiq/analysis/cashflow.py listingiq/analysis/brrr.py tests/test_analysis.py
git commit -m "feat: add multi-family per-unit rent estimation for 2-4 unit properties"
```

---

### Task 7: Days on Market Offer Price Adjustment

**Files:**
- Modify: `listingiq/config.py:96-104` (OfferConfig)
- Modify: `config/default.toml:103-111` ([analysis.offer])
- Modify: `listingiq/models.py:169-177` (OfferResult)
- Modify: `listingiq/analysis/offer.py` (all three _calc methods)
- Test: `tests/test_offer.py`

**Step 1: Write the failing test**

Add to `tests/test_offer.py`:

```python
    def test_dom_adjustment_no_effect_fresh(self):
        """DOM < 30 has no adjustment."""
        listing = _make_listing(price=200_000, days_on_market=10)
        result = self.calc.calculate_offer_price(listing, strategy="cash_flow")
        assert result.dom_adjusted_price == result.max_offer_price

    def test_dom_adjustment_30_60(self):
        """DOM 31-60 applies 2% additional discount."""
        listing = _make_listing(price=200_000, days_on_market=45)
        result = self.calc.calculate_offer_price(listing, strategy="cash_flow")
        expected = result.max_offer_price * (1 - 0.02)
        assert result.dom_adjusted_price == pytest.approx(expected, rel=0.01)

    def test_dom_adjustment_90_plus(self):
        """DOM 90+ applies 8% additional discount."""
        listing = _make_listing(price=200_000, days_on_market=120)
        result = self.calc.calculate_offer_price(listing, strategy="cash_flow")
        expected = result.max_offer_price * (1 - 0.08)
        assert result.dom_adjusted_price == pytest.approx(expected, rel=0.01)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_offer.py::TestOfferCalculator::test_dom_adjustment_no_effect_fresh -v`
Expected: FAIL — OfferResult has no `dom_adjusted_price` field

**Step 3: Write minimal implementation**

Add to `listingiq/config.py` in `OfferConfig`:

```python
    dom_discount_30_60: float = 0.02
    dom_discount_60_90: float = 0.05
    dom_discount_90_plus: float = 0.08
```

Add to `config/default.toml` under `[analysis.offer]`:

```toml
dom_discount_30_60 = 0.02
dom_discount_60_90 = 0.05
dom_discount_90_plus = 0.08
```

Add to `listingiq/models.py` in `OfferResult`:

```python
    dom_adjusted_price: float = 0.0  # offer price after DOM discount
```

In `listingiq/analysis/offer.py`, add a helper method to `OfferCalculator`:

```python
    def _apply_dom_discount(self, base_price: float, days_on_market: int) -> float:
        """Apply additional discount based on days on market."""
        if days_on_market >= 90:
            return base_price * (1 - self.offer_cfg.dom_discount_90_plus)
        elif days_on_market >= 60:
            return base_price * (1 - self.offer_cfg.dom_discount_60_90)
        elif days_on_market >= 30:
            return base_price * (1 - self.offer_cfg.dom_discount_30_60)
        return base_price
```

Then in each `_calc_*_offer` method, before creating the `OfferResult`, add:

```python
        dom_adjusted = self._apply_dom_discount(best_price, listing.days_on_market)
```

And add `dom_adjusted_price=round(dom_adjusted, 0)` to the `OfferResult(...)` constructor in each method.

**Step 4: Run tests**

Run: `pytest tests/ -v`
Expected: PASS

**Step 5: Commit**

```bash
git add listingiq/config.py config/default.toml listingiq/models.py listingiq/analysis/offer.py tests/test_offer.py
git commit -m "feat: add days-on-market discount to offer price calculator"
```

---

### Task 8: Room Addition Potential Analysis

**Files:**
- Create: `listingiq/analysis/room_potential.py`
- Test: `tests/test_room_potential.py`

**Step 1: Write the failing test**

Create `tests/test_room_potential.py`:

```python
"""Tests for room addition potential analysis."""
import pytest
from listingiq.analysis.room_potential import assess_room_potential
from listingiq.models import Listing


def _make_listing(**overrides) -> Listing:
    defaults = {
        "source": "test", "source_id": "test-1",
        "address": "100 Test St", "city": "Austin", "state": "TX", "zip_code": "78701",
        "price": 200_000, "beds": 3, "baths": 2, "sqft": 1400, "tax_annual": 3600,
    }
    defaults.update(overrides)
    return Listing(**defaults)


class TestRoomPotential:
    def test_no_potential_normal_ratio(self):
        listing = _make_listing(sqft=1200, beds=3)  # 400 sqft/bed
        result = assess_room_potential(listing)
        assert result["potential"] == "none"

    def test_likely_potential(self):
        listing = _make_listing(sqft=2000, beds=3)  # 667 sqft/bed
        result = assess_room_potential(listing)
        assert result["potential"] == "likely"
        assert result["sqft_per_bed"] == pytest.approx(666.7, rel=0.01)

    def test_strong_potential(self):
        listing = _make_listing(sqft=2500, beds=3)  # 833 sqft/bed
        result = assess_room_potential(listing)
        assert result["potential"] == "strong"

    def test_zero_beds_returns_none(self):
        listing = _make_listing(sqft=1500, beds=0)
        result = assess_room_potential(listing)
        assert result["potential"] == "none"

    def test_zero_sqft_returns_none(self):
        listing = _make_listing(sqft=0, beds=3)
        result = assess_room_potential(listing)
        assert result["potential"] == "none"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_room_potential.py -v`
Expected: FAIL — module doesn't exist

**Step 3: Write minimal implementation**

Create `listingiq/analysis/room_potential.py`:

```python
"""Room addition potential analysis based on sqft-to-bedroom ratio."""

from __future__ import annotations

from listingiq.models import Listing


def assess_room_potential(listing: Listing) -> dict:
    """Assess whether a property has room addition potential.

    Returns dict with:
        potential: "none", "likely", or "strong"
        sqft_per_bed: float ratio
        description: human-readable summary
    """
    if listing.beds <= 0 or listing.sqft <= 0:
        return {"potential": "none", "sqft_per_bed": 0, "description": ""}

    sqft_per_bed = round(listing.sqft / listing.beds, 1)

    if sqft_per_bed > 800:
        potential = "strong"
        desc = (
            f"{listing.beds} bed / {listing.sqft:,} sqft = {sqft_per_bed} sqft/bed — "
            f"Strong room addition potential. Adding a bedroom could increase value."
        )
    elif sqft_per_bed > 600:
        potential = "likely"
        desc = (
            f"{listing.beds} bed / {listing.sqft:,} sqft = {sqft_per_bed} sqft/bed — "
            f"Likely room addition potential."
        )
    else:
        potential = "none"
        desc = ""

    return {"potential": potential, "sqft_per_bed": sqft_per_bed, "description": desc}
```

**Step 4: Run tests**

Run: `pytest tests/test_room_potential.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add listingiq/analysis/room_potential.py tests/test_room_potential.py
git commit -m "feat: add room addition potential analysis (sqft-to-bed ratio)"
```

---

### Task 9: Mortgage Points Calculator

**Files:**
- Create: `listingiq/analysis/points.py`
- Test: `tests/test_points.py`

**Step 1: Write the failing test**

Create `tests/test_points.py`:

```python
"""Tests for mortgage points calculator."""
import pytest
from listingiq.analysis.points import calculate_points_table


class TestPointsCalculator:
    def test_zero_points_baseline(self):
        result = calculate_points_table(
            loan_amount=200_000, base_rate=0.07, loan_term_years=30
        )
        assert len(result) > 0
        baseline = result[0]
        assert baseline["points"] == 0
        assert baseline["rate"] == 0.07
        assert baseline["point_cost"] == 0
        assert baseline["monthly_payment"] > 0

    def test_each_point_reduces_rate(self):
        result = calculate_points_table(
            loan_amount=200_000, base_rate=0.07, loan_term_years=30
        )
        rates = [r["rate"] for r in result]
        # Each entry should have a lower rate
        for i in range(1, len(rates)):
            assert rates[i] < rates[i - 1]

    def test_point_cost_is_correct(self):
        result = calculate_points_table(
            loan_amount=200_000, base_rate=0.07, loan_term_years=30
        )
        one_point = next(r for r in result if r["points"] == 1.0)
        # 1 point = 1% of loan amount
        assert one_point["point_cost"] == 2000

    def test_break_even_calculated(self):
        result = calculate_points_table(
            loan_amount=200_000, base_rate=0.07, loan_term_years=30
        )
        one_point = next(r for r in result if r["points"] == 1.0)
        assert one_point["break_even_months"] > 0

    def test_total_interest_decreases(self):
        result = calculate_points_table(
            loan_amount=200_000, base_rate=0.07, loan_term_years=30
        )
        interests = [r["total_interest"] for r in result]
        for i in range(1, len(interests)):
            assert interests[i] < interests[i - 1]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_points.py -v`
Expected: FAIL — module doesn't exist

**Step 3: Write minimal implementation**

Create `listingiq/analysis/points.py`:

```python
"""Mortgage points calculator — shows cost/benefit of buying down the rate."""

from __future__ import annotations


def _monthly_payment(principal: float, annual_rate: float, years: int) -> float:
    if principal <= 0 or annual_rate <= 0:
        return 0.0
    monthly_rate = annual_rate / 12
    n = years * 12
    return principal * (monthly_rate * (1 + monthly_rate) ** n) / ((1 + monthly_rate) ** n - 1)


def calculate_points_table(
    loan_amount: float,
    base_rate: float,
    loan_term_years: int = 30,
    max_points: float = 3.0,
    step: float = 0.25,
) -> list[dict]:
    """Generate a comparison table for 0 to max_points.

    Each point costs 1% of the loan amount and reduces the rate by 0.25%.

    Returns list of dicts with: points, rate, monthly_payment, total_interest,
    break_even_months, point_cost.
    """
    baseline_payment = _monthly_payment(loan_amount, base_rate, loan_term_years)
    total_payments = loan_term_years * 12
    results: list[dict] = []

    points = 0.0
    while points <= max_points + 0.001:  # float tolerance
        rate = base_rate - (points * 0.0025)  # 0.25% per point
        payment = _monthly_payment(loan_amount, rate, loan_term_years)
        total_interest = (payment * total_payments) - loan_amount
        point_cost = loan_amount * (points / 100)
        monthly_savings = baseline_payment - payment

        if monthly_savings > 0 and points > 0:
            break_even = round(point_cost / monthly_savings)
        else:
            break_even = 0

        results.append({
            "points": round(points, 2),
            "rate": round(rate, 4),
            "monthly_payment": round(payment, 2),
            "total_interest": round(total_interest, 2),
            "break_even_months": break_even,
            "point_cost": round(point_cost, 2),
        })

        points += step

    return results
```

**Step 4: Run tests**

Run: `pytest tests/test_points.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add listingiq/analysis/points.py tests/test_points.py
git commit -m "feat: add mortgage points comparison calculator"
```

---

### Task 10: Add Digest Config and AlertDispatcher Enhancement

**Files:**
- Modify: `listingiq/config.py` (add DigestConfig)
- Modify: `config/default.toml` (add [alerts.digest])
- Modify: `listingiq/alerts/dispatcher.py` (add digest method)
- Modify: `listingiq/db/repository.py` (add get_deals_since method)
- Test: `tests/test_alerts.py`

**Step 1: Write the failing test**

Create `tests/test_alerts.py`:

```python
"""Tests for alert dispatcher digest functionality."""
import pytest
from datetime import datetime, timedelta
from listingiq.config import AlertsConfig, DigestConfig
from listingiq.alerts.dispatcher import AlertDispatcher
from listingiq.models import Listing, DealAnalysis, DealStrategy


def _make_deal(score=85, strategy="cash_flow"):
    listing = Listing(
        source="test", source_id=f"test-{score}",
        address="100 Test St", city="Austin", state="TX", zip_code="78701",
        price=200_000, beds=3, baths=2, sqft=1400,
    )
    return DealAnalysis(
        listing=listing,
        strategy=DealStrategy(strategy),
        score=score,
        meets_criteria=True,
        metrics={"monthly_cash_flow": 350},
        summary="Test deal",
    )


class TestDigestConfig:
    def test_digest_config_defaults(self):
        cfg = DigestConfig()
        assert cfg.enabled is False
        assert cfg.schedule == "daily"
        assert cfg.time == "08:00"
        assert cfg.min_score == 70

    def test_alerts_config_has_digest(self):
        cfg = AlertsConfig()
        assert hasattr(cfg, "digest")


class TestInstantAlertThreshold:
    def test_score_90_triggers_alert(self):
        cfg = AlertsConfig(min_deal_score=90, channels=["console"])
        dispatcher = AlertDispatcher(cfg)
        deal = _make_deal(score=92)
        # Just verify the filter logic
        qualified = [d for d in [deal] if d.meets_criteria and d.score >= cfg.min_deal_score]
        assert len(qualified) == 1

    def test_score_below_90_no_instant_alert(self):
        cfg = AlertsConfig(min_deal_score=90, channels=["console"])
        deal = _make_deal(score=85)
        qualified = [d for d in [deal] if d.meets_criteria and d.score >= cfg.min_deal_score]
        assert len(qualified) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_alerts.py -v`
Expected: FAIL — `DigestConfig` not importable

**Step 3: Write minimal implementation**

Add to `listingiq/config.py`:

```python
class DigestConfig(BaseModel):
    enabled: bool = False
    schedule: str = "daily"  # "daily" or "weekly"
    time: str = "08:00"
    min_score: int = 70
```

Add to `AlertsConfig`:
```python
    digest: DigestConfig = DigestConfig()
```

Add to `config/default.toml`:
```toml
[alerts.digest]
enabled = false
schedule = "daily"
time = "08:00"
min_score = 70
```

Add to `listingiq/db/repository.py`:

```python
    def get_deals_since(self, since: datetime, min_score: float = 0) -> list[DealRow]:
        """Get deals analyzed after a given timestamp."""
        with self._session() as session:
            return (
                session.query(DealRow)
                .filter(DealRow.analyzed_at >= since, DealRow.score >= min_score)
                .order_by(DealRow.score.desc())
                .all()
            )
```

**Step 4: Run tests**

Run: `pytest tests/ -v`
Expected: PASS

**Step 5: Commit**

```bash
git add listingiq/config.py config/default.toml listingiq/alerts/dispatcher.py listingiq/db/repository.py tests/test_alerts.py
git commit -m "feat: add digest config and deal retrieval for scheduled email digests"
```

---

### Task 11: Digest Email Scheduler Job

**Files:**
- Modify: `listingiq/scheduler.py` (add digest job)
- Modify: `listingiq/alerts/channels.py` (add send_digest method to EmailChannel)

**Step 1: Write the failing test**

Add to `tests/test_alerts.py`:

```python
class TestDigestEmail:
    def test_build_digest_html(self):
        """EmailChannel can build a digest HTML body."""
        from listingiq.config import EmailConfig
        from listingiq.alerts.channels import EmailChannel
        channel = EmailChannel(EmailConfig(
            smtp_host="test", from_address="test@test.com", to_addresses=["to@test.com"]
        ))
        deals = [_make_deal(score=90, strategy="brrr"), _make_deal(score=80, strategy="cash_flow")]
        html = channel.build_digest_html(deals)
        assert "BRRR" in html or "brrr" in html.lower()
        assert "CASH FLOW" in html or "cash_flow" in html.lower()
        assert "90" in html
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_alerts.py::TestDigestEmail -v`
Expected: FAIL — `build_digest_html` doesn't exist

**Step 3: Write minimal implementation**

In `listingiq/alerts/channels.py`, add to `EmailChannel`:

```python
    def build_digest_html(self, deals: list[DealAnalysis]) -> str:
        """Build an HTML digest email body from a list of deals."""
        from itertools import groupby

        # Group by strategy
        sorted_deals = sorted(deals, key=lambda d: d.strategy.value)
        groups = {k: list(v) for k, v in groupby(sorted_deals, key=lambda d: d.strategy.value)}

        parts = [
            "<h1>ListingIQ Deal Digest</h1>",
            f"<p><strong>{len(deals)} deals</strong> found since last digest.</p>",
        ]

        for strategy, strategy_deals in groups.items():
            label = strategy.upper().replace("_", " ")
            parts.append(f"<h2>{label} ({len(strategy_deals)} deals)</h2>")
            for deal in sorted(strategy_deals, key=lambda d: d.score, reverse=True):
                listing = deal.listing
                parts.append(
                    f"<div style='border:1px solid #ccc;padding:10px;margin:5px 0'>"
                    f"<strong>Score: {deal.score}</strong> — {listing.full_address}<br>"
                    f"${listing.price:,.0f} | {listing.beds}bd/{listing.baths}ba | {listing.sqft:,} sqft<br>"
                    f"<em>{deal.summary}</em>"
                    f"</div>"
                )

        return "\n".join(parts)

    async def send_digest(self, deals: list[DealAnalysis]) -> None:
        """Send a digest email with multiple deals."""
        import aiosmtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        if not self.config.to_addresses or not deals:
            return

        html_body = self.build_digest_html(deals)
        subject = f"ListingIQ Digest: {len(deals)} deals found"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.config.from_address
        msg["To"] = ", ".join(self.config.to_addresses)
        msg.attach(MIMEText(f"{len(deals)} deals found. View in HTML.", "plain"))
        msg.attach(MIMEText(html_body, "html"))

        await aiosmtplib.send(
            msg,
            hostname=self.config.smtp_host,
            port=self.config.smtp_port,
            username=self.config.smtp_user,
            password=self.config.smtp_password,
            use_tls=False,
            start_tls=True,
        )
```

In `listingiq/scheduler.py`, add digest scheduling after the scan job setup:

```python
    # Add digest job if configured
    if cfg.alerts.digest.enabled and "email" in cfg.alerts.channels:
        from apscheduler.triggers.cron import CronTrigger

        hour, minute = cfg.alerts.digest.time.split(":")
        if cfg.alerts.digest.schedule == "daily":
            trigger = CronTrigger(hour=int(hour), minute=int(minute))
        else:  # weekly
            trigger = CronTrigger(day_of_week="mon", hour=int(hour), minute=int(minute))

        scheduler.add_job(
            _run_digest_sync,
            trigger=trigger,
            args=[cfg],
            id="digest_email",
            name="Deal Digest Email",
        )
        logger.info("Digest email scheduled: %s at %s", cfg.alerts.digest.schedule, cfg.alerts.digest.time)
```

Add the digest cycle functions:

```python
async def _run_digest(cfg: AppConfig) -> None:
    """Send a digest email with recent qualifying deals."""
    from datetime import timedelta
    from listingiq.alerts.channels import EmailChannel

    repo = Repository(cfg.database.url)
    if cfg.alerts.digest.schedule == "daily":
        since = datetime.utcnow() - timedelta(days=1)
    else:
        since = datetime.utcnow() - timedelta(weeks=1)

    deal_rows = repo.get_deals_since(since, min_score=cfg.alerts.digest.min_score)
    if not deal_rows:
        logger.info("No deals for digest")
        return

    # Convert DealRows to DealAnalysis objects for the email channel
    # For now, create minimal DealAnalysis objects from stored data
    from listingiq.models import DealAnalysis, DealStrategy, Listing
    deals = []
    for row in deal_rows:
        listing_row = repo.get_listing_by_id(row.listing_id)
        if not listing_row:
            continue
        listing = Listing(
            source=listing_row.source, source_id=listing_row.source_id,
            address=listing_row.address, city=listing_row.city,
            state=listing_row.state, zip_code=listing_row.zip_code,
            price=listing_row.price, beds=listing_row.beds,
            baths=listing_row.baths, sqft=listing_row.sqft,
        )
        deal = DealAnalysis(
            listing=listing,
            strategy=DealStrategy(row.strategy),
            score=row.score,
            metrics=row.metrics or {},
            meets_criteria=row.meets_criteria,
            summary=row.summary or "",
        )
        deals.append(deal)

    if deals and cfg.alerts.email.smtp_host:
        channel = EmailChannel(cfg.alerts.email)
        await channel.send_digest(deals)
        logger.info("Digest sent with %d deals", len(deals))


def _run_digest_sync(cfg: AppConfig) -> None:
    asyncio.run(_run_digest(cfg))
```

**Step 4: Run tests**

Run: `pytest tests/ -v`
Expected: PASS

**Step 5: Commit**

```bash
git add listingiq/alerts/channels.py listingiq/scheduler.py tests/test_alerts.py
git commit -m "feat: add scheduled email digest with grouped deal summaries"
```

---

### Task 12: Wire New Features into API and Dashboard

**Files:**
- Modify: `listingiq/api/server.py` (API responses + dashboard HTML)

This is the largest task. It wires all the backend features into the API responses and updates the dashboard UI.

**Step 1: Update API `/api/analyze` response**

Add room potential and secondary data to the analyze response. Import `assess_room_potential` and add it to the response for each deal:

```python
from listingiq.analysis.room_potential import assess_room_potential
```

In the analyze endpoint, add to each deal dict:
```python
    "room_potential": assess_room_potential(listing),
    "days_on_market": listing.days_on_market,
    "secondary": {
        "year_built": listing.year_built,
        "tax_annual": listing.tax_annual,
        "lot_sqft": listing.lot_sqft,
        "has_pool": listing.has_pool,
        "school_rating": listing.school_rating,
        "flood_zone": listing.flood_zone,
        "crime_score": listing.crime_score,
        "stories": listing.stories,
    },
```

**Step 2: Update API `/api/offer-price` response**

Add DOM-adjusted price and points table. Import `calculate_points_table`:

```python
from listingiq.analysis.points import calculate_points_table
```

Add to the offer-price endpoint response (after computing offers):
```python
    # Calculate points table for the offer price
    points_data = calculate_points_table(
        loan_amount=result.max_offer_price * (1 - cfg.analysis.cash_flow.down_payment_pct),
        base_rate=cfg.analysis.cash_flow.interest_rate,
    )
```

Add to each offer result dict:
```python
    "dom_adjusted_price": r.dom_adjusted_price,
    "points_table": points_data,
```

**Step 3: Update API `/api/scan` response**

Add room potential and secondary data to each deal in the scan response (same as analyze).

**Step 4: Update dashboard HTML**

The dashboard is a single HTML string in `server.py`. The changes:

1. **Deal cards**: Add DOM badge (color-coded), room potential flag, collapsible secondary data panel
2. **Offer calculator tab**: Add points slider + comparison table, show DOM-adjusted price
3. **Analysis tab**: Show CoC return prominently, room potential badge

Due to the size of the HTML, this step involves adding JavaScript and CSS to the existing inlined dashboard. The key additions:

- **DOM badge CSS**: `.dom-badge` with `.dom-green`, `.dom-yellow`, `.dom-red` variants
- **Secondary data panel**: Collapsible `.property-details` section with grid layout
- **Points slider**: Range input that updates a table dynamically via JavaScript
- **Room potential badge**: Small tag next to strategy tag

**Step 5: Run the app and verify**

Run: `python -m listingiq.cli serve`
Visit: `http://localhost:8000`
Verify: All three tabs show new data fields

**Step 6: Commit**

```bash
git add listingiq/api/server.py
git commit -m "feat: wire new features into API and dashboard (DOM, room potential, points, secondary data)"
```

---

### Task 13: Run Full Test Suite and Fix Any Breakage

**Step 1: Run all tests**

```bash
pytest tests/ -v --tb=short
```

**Step 2: Fix any failures**

Existing tests may break if they rely on specific ARV values (since we changed the fallback) or specific score values (since we rebalanced scoring). Update expected values to match new behavior.

**Step 3: Run tests again to confirm**

```bash
pytest tests/ -v
```

**Step 4: Commit fixes**

```bash
git add -A
git commit -m "fix: update test expectations for new ARV fallback and score rebalancing"
```

---

### Task 14: Final Integration Test

**Step 1: Run the full app end-to-end**

```bash
python -m listingiq.cli serve
```

**Step 2: Test each tab manually**

1. **Analyze tab**: Enter a property, verify BRRR/cash flow/flip all return results with new fields
2. **Deal Scanner tab**: Run a scan, verify deals from all 3 strategies appear (not just flips)
3. **Offer Calculator tab**: Calculate offers, verify DOM adjustment and points table render

**Step 3: Commit any final adjustments**

```bash
git add -A
git commit -m "chore: final integration polish"
```
