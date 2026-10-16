"""Normalize scalar and multiple filter values without changing SQL parameter safety."""


def selection_values(value):
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return list(dict.fromkeys(item for item in values if item is not None and item not in ('', 'all')))


def selection_value(value):
    values = selection_values(value)
    return values[0] if len(values) == 1 else values or 'all'


def value_filter(value, column):
    values = selection_values(value)
    if not values:
        return '1 = 1', []
    if len(values) == 1:
        return f'{column} = %s', values
    return f"{column} IN ({', '.join(['%s'] * len(values))})", values


def selection_label(value, labels=None, all_label='전체'):
    values = selection_values(value)
    return ', '.join((labels or {}).get(item, item) for item in values) if values else all_label
