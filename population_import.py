"""Load an exported WAHIS population CSV into the configured MySQL database."""
import argparse
import json

from database.population_db import import_export


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv_path')
    args = parser.parse_args()
    print(json.dumps(import_export(args.csv_path)))
