"""Shared mapping from selectable regions to stored database regions."""

KNOWN_REGIONS = ("Asia", "Europe", "Africa", "North America", "South America", "Oceania")

AMERICA_REGIONS = ("North America", "South America")


def region_filter(region, column="cr.region"):
    """Return a parameterized SQL condition and values for a region."""
    if region is None or region == 'all':
        return '1 = 1', []
    if isinstance(region, (list, tuple, set)):
        from database.filters import selection_values
        regions = selection_values(region)
        if not regions:
            return '1 = 1', []
        clauses, params = [], []
        for item in regions:
            clause, values = region_filter(item, column)
            clauses.append(clause)
            params.extend(values)
        return '(' + ' OR '.join(clauses) + ')', params
    if region == "Other":
        placeholders = ", ".join(["%s"] * len(KNOWN_REGIONS))
        return f"({column} IS NULL OR {column} NOT IN ({placeholders}))", list(KNOWN_REGIONS)
    if region == "America":
        return f"{column} IN (%s, %s)", list(AMERICA_REGIONS)
    return f"{column} = %s", [region]
