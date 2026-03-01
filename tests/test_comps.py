"""Tests for comparable data services."""

import pytest

from listingiq.config import CompsConfig
from listingiq.models import Listing, RentalComp, SalesComp
from listingiq.comps.rental import RentalCompService
from listingiq.comps.sales import SalesCompService


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
        "year_built": 1990,
    }
    defaults.update(overrides)
    return Listing(**defaults)


class TestRentalCompService:
    def setup_method(self):
        self.cfg = CompsConfig()
        self.svc = RentalCompService(self.cfg)

    def test_formula_estimate_basic(self):
        listing = _make_listing()
        rent = self.svc._estimate_rent_formula(listing)
        assert rent > 0
        # For a 1400 sqft, 3-bed in Austin (medium market), should be reasonable
        assert 800 < rent < 3000

    def test_formula_high_cost_market(self):
        listing = _make_listing(city="San Francisco")
        rent_sf = self.svc._estimate_rent_formula(listing)

        listing_austin = _make_listing(city="Austin")
        rent_austin = self.svc._estimate_rent_formula(listing_austin)

        # SF should be more expensive
        assert rent_sf > rent_austin

    def test_formula_low_cost_market(self):
        listing = _make_listing(city="Memphis")
        rent_memphis = self.svc._estimate_rent_formula(listing)

        listing_austin = _make_listing(city="Austin")
        rent_austin = self.svc._estimate_rent_formula(listing_austin)

        # Memphis should be cheaper
        assert rent_memphis < rent_austin

    def test_formula_more_beds_more_rent(self):
        listing_3bed = _make_listing(beds=3, sqft=1400)
        listing_5bed = _make_listing(beds=5, sqft=2200)

        rent_3 = self.svc._estimate_rent_formula(listing_3bed)
        rent_5 = self.svc._estimate_rent_formula(listing_5bed)

        assert rent_5 > rent_3

    def test_formula_larger_sqft_more_rent(self):
        listing_small = _make_listing(sqft=800)
        listing_large = _make_listing(sqft=2000)

        rent_small = self.svc._estimate_rent_formula(listing_small)
        rent_large = self.svc._estimate_rent_formula(listing_large)

        assert rent_large > rent_small

    def test_formula_old_property_discount(self):
        listing_old = _make_listing(year_built=1950)
        listing_new = _make_listing(year_built=2020)

        rent_old = self.svc._estimate_rent_formula(listing_old)
        rent_new = self.svc._estimate_rent_formula(listing_new)

        assert rent_old < rent_new

    def test_formula_no_sqft_uses_bed_estimate(self):
        listing = _make_listing(sqft=0, beds=3)
        rent = self.svc._estimate_rent_formula(listing)
        assert rent > 0

    def test_formula_no_data_uses_price_fallback(self):
        listing = _make_listing(sqft=0, beds=0, city="", year_built=0)
        rent = self.svc._estimate_rent_formula(listing)
        # Should fall back to 0.8% of price (no age discount when year_built=0)
        assert rent == pytest.approx(listing.price * 0.008)

    def test_median_rent_from_comps(self):
        listing = _make_listing()
        comps = [
            RentalComp(address="A", monthly_rent=1500, beds=3, baths=2, sqft=1400),
            RentalComp(address="B", monthly_rent=1600, beds=3, baths=2, sqft=1400),
            RentalComp(address="C", monthly_rent=1700, beds=3, baths=2, sqft=1400),
        ]
        rent = self.svc._median_rent_from_comps(comps, listing)
        assert rent == 1600  # median

    def test_median_rent_adjusts_for_sqft(self):
        listing = _make_listing(sqft=2000)
        comps = [
            RentalComp(address="A", monthly_rent=1500, beds=3, baths=2, sqft=1400),
        ]
        rent = self.svc._median_rent_from_comps(comps, listing)
        # Subject is larger, so rent should be adjusted up
        assert rent > 1500

    def test_median_rent_adjusts_for_beds(self):
        listing = _make_listing(beds=4)
        comps = [
            RentalComp(address="A", monthly_rent=1500, beds=3, baths=2, sqft=1400),
        ]
        rent = self.svc._median_rent_from_comps(comps, listing)
        # Subject has more beds, so rent should be adjusted up
        assert rent > 1500


class TestSalesCompService:
    def setup_method(self):
        self.cfg = CompsConfig()
        self.svc = SalesCompService(self.cfg)

    def test_formula_arv_basic(self):
        listing = _make_listing(price=200_000, year_built=1990)
        arv = self.svc._estimate_arv_formula(listing)
        assert arv > listing.price

    def test_formula_arv_older_property_higher_multiplier(self):
        listing_old = _make_listing(price=200_000, year_built=1970)
        listing_new = _make_listing(price=200_000, year_built=2020)

        arv_old = self.svc._estimate_arv_formula(listing_old)
        arv_new = self.svc._estimate_arv_formula(listing_new)

        # Older properties should have more rehab upside
        assert arv_old > arv_new

    def test_arv_from_comps_price_per_sqft(self):
        listing = _make_listing(sqft=1400, beds=3, baths=2)
        comps = [
            SalesComp(address="A", sold_price=280_000, beds=3, baths=2, sqft=1400, price_per_sqft=200),
            SalesComp(address="B", sold_price=294_000, beds=3, baths=2, sqft=1400, price_per_sqft=210),
            SalesComp(address="C", sold_price=266_000, beds=3, baths=2, sqft=1400, price_per_sqft=190),
        ]
        arv = self.svc._calculate_arv_from_comps(comps, listing)
        # Median ppsf is 200, * 1400 sqft = 280,000
        assert arv == pytest.approx(280_000, rel=0.01)

    def test_arv_from_comps_adjusts_for_beds(self):
        listing = _make_listing(sqft=1400, beds=4, baths=2)
        comps = [
            SalesComp(address="A", sold_price=280_000, beds=3, baths=2, sqft=1400, price_per_sqft=200),
        ]
        arv = self.svc._calculate_arv_from_comps(comps, listing)
        # Subject has more beds, so ARV should be higher
        assert arv > 280_000

    def test_arv_from_comps_adjusts_for_baths(self):
        listing = _make_listing(sqft=1400, beds=3, baths=3)
        comps = [
            SalesComp(address="A", sold_price=280_000, beds=3, baths=2, sqft=1400, price_per_sqft=200),
        ]
        arv = self.svc._calculate_arv_from_comps(comps, listing)
        # Subject has more baths, so ARV should be higher
        assert arv > 280_000

    def test_arv_fallback_no_sqft(self):
        listing = _make_listing(sqft=0)
        comps = [
            SalesComp(address="A", sold_price=280_000, beds=3, baths=2, sqft=0, price_per_sqft=0),
            SalesComp(address="B", sold_price=300_000, beds=3, baths=2, sqft=0, price_per_sqft=0),
        ]
        arv = self.svc._calculate_arv_from_comps(comps, listing)
        # Should use median sold price directly
        assert arv == pytest.approx(290_000)
