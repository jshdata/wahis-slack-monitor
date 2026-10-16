"""Run the Thursday WAHIS digest independently of live monitoring."""

import argparse

from slack.weekly_report import send_weekly_report, weekly_window


def main():
    parser = argparse.ArgumentParser(description='WAHIS 주간 신규 리포트 요약')
    parser.add_argument('--week-ending', help='집계 종료 목요일 (YYYY-MM-DD), 기본: 최근 목요일 09시')
    parser.add_argument('--dry-run', action='store_true', help='Slack 전송 없이 콘솔에 출력')
    args = parser.parse_args()
    start, end = weekly_window(week_ending=args.week_ending)
    count = send_weekly_report(start, end, dry_run=args.dry_run)
    print(f'Weekly digest complete: {count} reports')


if __name__ == '__main__':
    main()
