"""Route WAHIS report alerts to operator-configured Slack channels."""

import json
import os
import re

from database.db import get_connection


FILTERS = ('countries', 'diseases', 'species')


def get_subscriptions():
    raw = os.getenv('WAHIS_SLACK_SUBSCRIPTIONS', '').strip()
    if not raw:
        return []
    try:
        subscriptions = json.loads(raw)
    except ValueError:
        raise ValueError('WAHIS_SLACK_SUBSCRIPTIONS must be a JSON array') from None
    if not isinstance(subscriptions, list):
        raise ValueError('WAHIS_SLACK_SUBSCRIPTIONS must be a JSON array')

    seen = set()
    urls = {os.getenv('SLACK_WEBHOOK_URL')}
    for index, rule in enumerate(subscriptions, 1):
        if not isinstance(rule, dict) or set(rule) - {'name', 'webhook_env', *FILTERS}:
            raise ValueError(f'Invalid Slack subscription #{index}')
        name = rule.get('name')
        env = rule.get('webhook_env')
        if (not isinstance(name, str) or not re.fullmatch(r'[a-z0-9_-]{1,64}', name)
                or name == 'default' or name in seen):
            raise ValueError(f'Invalid or duplicate name in Slack subscription #{index}')
        if not isinstance(env, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]*', env):
            raise ValueError(f'Invalid webhook_env in Slack subscription #{index}')
        url = os.getenv(env, '').strip()
        if not re.fullmatch(r'https://hooks\.slack(?:-gov)?\.com/services/[A-Za-z0-9/_-]+', url) or url in urls:
            raise ValueError(f'Missing, invalid or duplicate webhook in Slack subscription #{index}')
        seen.add(name)
        urls.add(url)
        for field in FILTERS:
            values = rule.get(field, [])
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise ValueError(f'Invalid {field} in Slack subscription #{index}')
            rule[field] = {value.strip().casefold() for value in values}
        if not any(rule[field] for field in FILTERS):
            raise ValueError(f'Slack subscription #{index} needs at least one filter')
        rule['url'] = url
    return subscriptions


def matches(rule, event, details):
    values = {
        'countries': [event.get('country')],
        'diseases': [event.get('disease')],
        'species': details.get('species_names', ()),
    }
    return all(
        not rule[field] or rule[field].intersection(
            value.strip().casefold() for value in values[field] if value
        )
        for field in FILTERS
    )


def send_subscribed_alert(event, details, subscriptions, blocks, message, send):
    report_id = event['reportId']
    destinations = [('default', None)]
    destinations.extend(
        (rule['name'], rule['url']) for rule in subscriptions if matches(rule, event, details)
    )

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute('''CREATE TABLE IF NOT EXISTS wahis_slack_deliveries (
                report_id BIGINT NOT NULL,
                destination VARCHAR(64) NOT NULL,
                PRIMARY KEY (report_id, destination)
            ) ENGINE=InnoDB''')
            lock = f'wahis-slack-report:{report_id}'
            cursor.execute('SELECT GET_LOCK(%s, 0)', (lock,))
            if cursor.fetchone()[0] != 1:
                raise RuntimeError('Could not lock WAHIS Slack report delivery')

            failed = []
            for name, url in destinations:
                cursor.execute('SELECT 1 FROM wahis_slack_deliveries '
                               'WHERE report_id=%s AND destination=%s', (report_id, name))
                if cursor.fetchone():
                    continue
                try:
                    send(blocks=blocks, text=message, webhook_url=url)
                except RuntimeError:
                    failed.append(name)
                    continue
                cursor.execute('INSERT INTO wahis_slack_deliveries (report_id, destination) '
                               'VALUES (%s, %s)', (report_id, name))
                conn.commit()
            if failed:
                raise RuntimeError(f'Slack webhook failed for destinations: {", ".join(failed)}')
    finally:
        # Closing the connection releases the report lock, including on failure.
        conn.close()
