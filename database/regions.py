"""Shared mapping from selectable regions to stored database regions."""

AMERICA_REGIONS = ("North America", "South America")


def region_filter(region, column="cr.region"):
    """Return a parameterized SQL condition and values for a region."""
    if region == "America":
        return f"{column} IN (%s, %s)", list(AMERICA_REGIONS)
    return f"{column} = %s", [region]
