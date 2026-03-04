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
