"""APQA daily sync entrypoint. Run from the WAHIS project root."""
from apqa.parser import get_apqa_data
from database.apqa_db import sync_apqa_data


def main():
    data = get_apqa_data()
    result = sync_apqa_data(data)
    print('APQA synchronization successful')
    for key, value in result.items():
        print(f'{key}: {value}')


if __name__ == '__main__':
    main()
