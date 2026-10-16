"""Bounded maintenance alerts that work even when the database is unavailable."""

from collections import OrderedDict
from datetime import datetime
import os
import re
import traceback
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv()


def redact(value):
    text = str(value)
    for name, secret in os.environ.items():
        if secret and len(secret) >= 4 and any(part in name.upper() for part in
                ('PASSWORD', 'TOKEN', 'SECRET', 'WEBHOOK', 'API_KEY', 'SSL_CA_CONTENT', 'SSL_CA_CERT')):
            text = text.replace(secret, '[REDACTED]')
    text = re.sub(r'https://hooks\.slack\.com/\S+', '[SLACK_WEBHOOK]', text)
    text = re.sub(r'(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,]+', r'\1[REDACTED]', text)
    text = re.sub(r'(?i)(password\s*[:=]\s*)[^\s,]+', r'\1[REDACTED]', text)
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('`', "'")


class ErrorReporter:
    MAX_GROUPS = 8

    def __init__(self, name):
        self.name = name
        self.groups = OrderedDict()
        self.total = 0
        self.last_captured = None

    def record(self, stage, error, **context):
        self.total += 1
        message = redact(error)[:700]
        key = (stage, type(error).__name__, message)
        if key not in self.groups:
            if len(self.groups) >= self.MAX_GROUPS:
                return
            self.groups[key] = {'count': 0, 'contexts': [], 'trace': '',
                                'first_seen': datetime.now(ZoneInfo('Asia/Seoul')).strftime('%H:%M:%S')}
        group = self.groups[key]
        group['count'] += 1
        details = ' · '.join(f'{key}={redact(value)[:150]}' for key, value in context.items()
                             if value is not None)
        if details and details not in group['contexts'] and len(group['contexts']) < 3:
            group['contexts'].append(details[:500])
        group['trace'] = redact(''.join(traceback.format_exception(
            type(error), error, error.__traceback__)))[-1400:]

    def call(self, stage, function, *args, error_context=None, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as error:
            self.record(stage, error, **(error_context or {}))
            self.last_captured = error
            raise

    def run(self, function):
        try:
            return function()
        except Exception as error:
            if error is not self.last_captured:
                self.record('예상하지 못한 실행 오류', error)
            raise
        finally:
            self.flush()

    def flush(self):
        if not self.total:
            return True
        total = self.total
        groups = self.groups
        # Clear before sending: a failed error notification must never recurse.
        self.groups = OrderedDict()
        self.total = 0
        self.last_captured = None
        title = f'🚨 {self.name} 오류'
        stamp = datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d %H:%M:%S KST')
        blocks = [
            {'type': 'header', 'text': {'type': 'plain_text', 'text': title}},
            {'type': 'section', 'text': {'type': 'mrkdwn',
                'text': f'*알림 시각:* {stamp}\n*오류:* {total}건 · 동일 오류는 실행 내에서 묶어 표시'}},
        ]
        for (stage, kind, message), group in groups.items():
            text = (f'*단계:* {stage} · *예외:* {kind} · *횟수:* {group["count"]}\n'
                    f'*최초 발생:* {group["first_seen"]} KST\n'
                    + '\n'.join(group['contexts'])[:500] + f'\n*내용:* {message}\n'
                    + f'```{group["trace"]}```')
            blocks.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': text[:2900]}})
        shown = sum(group['count'] for group in groups.values())
        if total > shown:
            blocks.append({'type': 'section', 'text': {'type': 'mrkdwn',
                'text': f'그 외 오류 {total - shown}건은 실행 로그를 확인해주세요.'}})
        repository = os.getenv('GITHUB_REPOSITORY', '')
        run_id = os.getenv('GITHUB_RUN_ID', '')
        if re.fullmatch(r'[\w.-]+/[\w.-]+', repository) and run_id.isdigit():
            blocks.append({'type': 'actions', 'elements': [{
                'type': 'button', 'text': {'type': 'plain_text', 'text': 'GitHub Actions 로그 보기'},
                'url': f'https://github.com/{repository}/actions/runs/{run_id}'}]})
        webhook = os.getenv('SLACK_ERROR_WEBHOOK_URL') or os.getenv('SLACK_WEBHOOK_URL')
        if not webhook:
            print('Maintenance alert skipped: no Slack webhook configured')
            return False
        try:
            response = requests.post(webhook, json={'text': f'{title} ({total}건)', 'blocks': blocks}, timeout=10)
            response.raise_for_status()
            return True
        except Exception as error:
            # Do not print the exception text: request exceptions can contain webhook credentials.
            print(f'Maintenance alert failed: {type(error).__name__}; see original execution logs')
            return False
