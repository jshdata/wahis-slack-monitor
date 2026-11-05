"""Run the Thursday WAHIS digest independently of live monitoring."""

import argparse
from datetime import date, datetime

from slack.weekly_report import KST, send_weekly_report, weekly_window


def scheduled_window(now=None, not_before=None):
    now = now or datetime.now(KST)
    if now.tzinfo is None:
        raise ValueError('현재 시각에는 시간대가 필요합니다.')
    local = now.astimezone(KST)
    if local.weekday() != 3 or local.hour < 9:
        return None
    start, end = weekly_window(local)
    if not_before and end.date() < date.fromisoformat(not_before):
        return None
    return start, end


def main():
    parser = argparse.ArgumentParser(description='WAHIS 주간 신규 리포트 요약')
    parser.add_argument('--week-ending', help='집계 종료 목요일 (YYYY-MM-DD), 기본: 최근 목요일 09시')
    parser.add_argument('--dry-run', action='store_true', help='Slack 전송 없이 콘솔에 출력')
    parser.add_argument('--output', help='상세 HTML을 저장할 로컬 파일 경로')
    parser.add_argument('--scheduled', action='store_true', help='목요일 서울 09시 이후에만 주간 발송 확인')
    parser.add_argument('--not-before', help='자동 발송 적용을 시작할 종료 목요일 (YYYY-MM-DD)')
    parser.add_argument('--force', action='store_true', help='수신 확인 후 명시적으로 같은 주 재발송')
    args = parser.parse_args()
    if args.scheduled and (args.week_ending or args.force):
        parser.error('--scheduled는 --week-ending 또는 --force와 함께 사용할 수 없습니다.')
    if args.not_before and not args.scheduled:
        parser.error('--not-before는 --scheduled에만 사용할 수 있습니다.')
    if args.scheduled:
        window = scheduled_window(not_before=args.not_before)
        if window is None:
            print('Weekly digest skipped: not due in Asia/Seoul')
            return
        start, end = window
    else:
        start, end = weekly_window(week_ending=args.week_ending)
    count = send_weekly_report(start, end, dry_run=args.dry_run,
                               output_path=args.output, once=not args.force)
    print(f'Weekly digest complete: {count} reports')


if __name__ == '__main__':
    main()
