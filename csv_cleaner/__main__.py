import argparse
import csv
import json
import sys
from pathlib import Path

from .core import clean_csv


def main():
    parser = argparse.ArgumentParser(description="Clean CSV data and export validation reports.")
    parser.add_argument("input", type=Path, help="CSV file to process")
    parser.add_argument("--output", type=Path, required=True, help="New or empty output folder")
    parser.add_argument("--config", type=Path, help="JSON validation rules")
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--delimiter", default=",")
    parser.add_argument("--fail-on-errors", action="store_true", help="Exit 2 after exporting if validation errors remain")
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else None
        summary = clean_csv(args.input, args.output, config, encoding=args.encoding, delimiter=args.delimiter)
    except (OSError, ValueError, csv.Error, LookupError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Processed {summary['input_rows']} rows -> {summary['output_rows']} rows")
    print(f"Automatic fixes: {summary['automatic_cell_fixes']}")
    print(f"Duplicates removed: {summary['duplicate_rows_removed']}")
    print(f"Rows needing review: {summary['output_rows_with_validation_errors']}")
    print(f"Reports saved to: {args.output.resolve()}")
    return 2 if args.fail_on_errors and summary["output_rows_with_validation_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
