"""Shared mapping from selectable regions to stored database regions."""

KNOWN_REGIONS = ("Asia", "Europe", "Africa", "North America", "South America", "Oceania")

AMERICA_REGIONS = ("North America", "South America")


def region_filter(region, column="cr.region"):
    """Return a parameterized SQL condition and values for a region."""
    if region == "Other":
        placeholders = ", ".join(["%s"] * len(KNOWN_REGIONS))
        return f"({column} IS NULL OR {column} NOT IN ({placeholders}))", list(KNOWN_REGIONS)
    if region == "America":
        return f"{column} IN (%s, %s)", list(AMERICA_REGIONS)
    return f"{column} = %s", [region]
