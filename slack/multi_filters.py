"""Searchable Slack multi-selects; empty selection always means all."""

from copy import deepcopy

from database.filters import selection_values, selection_value


def selected_values(state):
    if 'selected_options' in state:
        return selection_values([option['value'] for option in state['selected_options'] or []])
    option = state.get('selected_option') or {}
    return selection_values(option.get('value'))


def selected_value(state):
    return selection_value(selected_values(state))


def multi_element(element, external=False):
    result = deepcopy(element)
    result['type'] = 'multi_external_select' if external else 'multi_static_select'
    result['placeholder'] = {'type': 'plain_text', 'text': '전체 · 검색하여 여러 항목 선택'}
    initial = result.pop('initial_option', None)
    if initial and initial['value'] != 'all':
        result['initial_options'] = [initial]
    if external:
        result.pop('options', None)
        result.pop('option_groups', None)
        result['min_query_length'] = 0
    else:
        result['options'] = [option for option in result.get('options', []) if option['value'] != 'all']
    return result


def multi_filter_view(view):
    """Convert data filters only; dates, time, output mode and neighbours stay single."""
    for block in view['blocks']:
        element = block.get('element', {})
        action = element.get('action_id', '')
        if action in ('region_select', 'country_select', 'animal_select', 'disease_select',
                      'stats_region_select', 'stats_country_select', 'stats_disease_select'):
            block['element'] = multi_element(element, external='country' in action)
            block['optional'] = True
            # Country suggestions read current region state, without rebuilding the
            # whole view and losing dates, diseases, or existing country selections.
            block.pop('dispatch_action', None)
    return view
