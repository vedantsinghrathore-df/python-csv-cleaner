"""Conservative CSV cleaning with an audit trail and configurable validation."""

import csv
import json
import re
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd


EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+")
ISSUE_COLUMNS = ["source_record", "column", "issue", "original_value", "cleaned_value", "action"]
ALLOWED_RULES = {"required", "type", "min", "max", "choices", "formats"}


def normalize_header(value):
    """Convert headers to predictable snake_case without hiding collisions."""
    return re.sub(r"\W+", "_", value.strip().lower()).strip("_")


def validate_config(config, columns):
    if not isinstance(config, dict) or set(config) - {"columns", "missing_tokens", "drop_duplicates"}:
        raise ValueError("Config accepts only columns, missing_tokens, and drop_duplicates.")
    rules = config.get("columns", {})
    if not isinstance(rules, dict):
        raise ValueError("columns must be an object keyed by normalized column name.")
    if set(rules) - set(columns):
        raise ValueError(f"Configured columns not present: {sorted(set(rules) - set(columns))}")
    if not isinstance(config.get("drop_duplicates", True), bool):
        raise ValueError("drop_duplicates must be true or false.")
    tokens = config.get("missing_tokens", ["", "null", "none", "n/a", "nan"])
    if not isinstance(tokens, list) or not all(isinstance(x, str) for x in tokens):
        raise ValueError("missing_tokens must be a list of strings.")
    for column, rule in rules.items():
        if not isinstance(rule, dict) or set(rule) - ALLOWED_RULES:
            raise ValueError(f"Invalid validation rules for {column}.")
        kind = rule.get("type", "text")
        if kind not in {"text", "email", "integer", "number", "date"}:
            raise ValueError(f"Unsupported type for {column}: {kind}")
        if "required" in rule and not isinstance(rule["required"], bool):
            raise ValueError(f"required must be boolean for {column}.")
        if "choices" in rule and (not isinstance(rule["choices"], list) or not all(isinstance(x, str) for x in rule["choices"])):
            raise ValueError(f"choices must be a string list for {column}.")
        for key in ("min", "max"):
            if key in rule:
                try:
                    bound = Decimal(str(rule[key]))
                    if kind not in {"integer", "number"} or not bound.is_finite():
                        raise ValueError()
                except (InvalidOperation, ValueError):
                    raise ValueError(f"{key} must be a finite numeric bound on a numeric column: {column}") from None
        if "min" in rule and "max" in rule and Decimal(str(rule["min"])) > Decimal(str(rule["max"])):
            raise ValueError(f"min exceeds max for {column}.")
        if "formats" in rule and (kind != "date" or not isinstance(rule["formats"], list) or not rule["formats"] or not all(isinstance(x, str) and x for x in rule["formats"])):
            raise ValueError(f"formats must be a nonempty list of date format strings for {column}.")


def load_csv(path, encoding, delimiter):
    """Reject ambiguous headers and malformed records before pandas can infer data."""
    if len(delimiter) != 1 or delimiter in {'"', '\n', '\r'}:
        raise ValueError("Delimiter must be one character other than a quote or newline.")
    with Path(path).open(encoding=encoding, newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter, strict=True)
        header = next(reader, None)
        if not header:
            raise ValueError("CSV is empty or has no header.")
        columns = [normalize_header(x) for x in header]
        if any(not x for x in columns) or len(set(columns)) != len(columns):
            raise ValueError("Headers must be nonempty and unique after normalization.")
        count = 0
        for record, row in enumerate(reader, start=2):
            if len(row) != len(header):
                raise ValueError(f"Source record {record} has {len(row)} fields; expected {len(header)}.")
            count += 1
    # String dtype preserves leading zeroes, identifiers and literal NA values.
    frame = pd.read_csv(path, sep=delimiter, encoding=encoding, dtype=str,
                        keep_default_na=False, na_filter=False, skip_blank_lines=False)
    if len(frame) != count:
        raise ValueError("CSV parsing produced an inconsistent record count.")
    frame.columns = columns
    return header, frame


def clean_csv(input_path, output_dir, config=None, *, encoding="utf-8-sig", delimiter=","):
    """Clean a file and write cleaned.csv, issues.csv, rejected.csv and summary.json.

    Missing cells are always reported; only required missing cells reject a row.
    Invalid values remain unchanged for review. Source records are one-based CSV
    records including the header, not physical line numbers (quoted newlines count
    as part of one record). Output directories must be new or empty.
    """
    config = {} if config is None else config
    headers, frame = load_csv(input_path, encoding, delimiter)
    validate_config(config, list(frame.columns))
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("Output directory must be empty; choose a new folder to protect existing files.")
    rules = config.get("columns", {})
    missing_tokens = {x.strip().casefold() for x in config.get("missing_tokens", ["", "null", "none", "n/a", "nan"])}
    missing_tokens.add("")
    issues = []
    invalid_rows = set()
    fixes = 0

    def report(index, column, issue, original, cleaned, action):
        issues.append([index + 2, column, issue, original, cleaned, action])

    for index in frame.index:
        for column in frame.columns:
            original = frame.at[index, column]
            value = original.strip()
            rule = rules.get(column, {})
            kind = rule.get("type", "email" if column == "email" or column.endswith("_email") else "text")
            if original != value:
                report(index, column, "surrounding_whitespace", original, value, "trimmed")
                fixes += 1
            if value.casefold() in missing_tokens:
                if value:
                    report(index, column, "missing_marker", value, "", "cleared")
                    fixes += 1
                value = ""
                required = rule.get("required", False)
                report(index, column, "missing_required" if required else "missing_optional", original, value, "review" if required else "retained")
                if required:
                    invalid_rows.add(index)
            else:
                problem = None
                replacement = value
                if kind == "email":
                    local, separator, domain = value.rpartition("@")
                    if (not EMAIL.fullmatch(value) or len(value) > 254 or len(local) > 64
                            or local.startswith(".") or local.endswith(".") or ".." in local
                            or any(len(label) > 63 for label in domain.split("."))):
                        problem = "invalid_email"
                    else:
                        replacement = local + separator + domain.lower()
                elif kind in {"integer", "number"}:
                    try:
                        number = Decimal(value)
                        if not number.is_finite() or (kind == "integer" and number != number.to_integral_value()):
                            problem = f"invalid_{kind}"
                        elif "min" in rule and number < Decimal(str(rule["min"])):
                            problem = "below_minimum"
                        elif "max" in rule and number > Decimal(str(rule["max"])):
                            problem = "above_maximum"
                    except InvalidOperation:
                        problem = f"invalid_{kind}"
                elif kind == "date":
                    parsed = None
                    for date_format in rule.get("formats", ["%Y-%m-%d"]):
                        try:
                            parsed = datetime.strptime(value, date_format).date()
                            break
                        except ValueError:
                            continue
                    if parsed is None:
                        problem = "invalid_date"
                    else:
                        replacement = parsed.isoformat()
                if replacement != value:
                    report(index, column, "formatting", value, replacement, "normalized")
                    fixes += 1
                value = replacement
                if problem:
                    report(index, column, problem, original, value, "review")
                    invalid_rows.add(index)
                if "choices" in rule and value not in rule["choices"]:
                    report(index, column, "invalid_choice", original, value, "review")
                    invalid_rows.add(index)
            frame.at[index, column] = value

    duplicates = frame.duplicated(keep="first")
    drop = config.get("drop_duplicates", True)
    for index in frame.index[duplicates]:
        report(index, "", "duplicate_row", "", "", "removed" if drop else "retained")
    kept = frame.loc[~duplicates] if drop else frame
    rejected = frame.loc[sorted(invalid_rows)].copy()
    # A separate audit file maps rejected records to the original input.
    source_column = "source_record"
    while source_column in rejected.columns:
        source_column = "_" + source_column
    rejected.insert(0, source_column, [x + 2 for x in rejected.index])
    summary = {
        "input_file": Path(input_path).name,
        "input_rows": len(frame), "output_rows": len(kept),
        "duplicate_rows_detected": int(duplicates.sum()),
        "duplicate_rows_removed": int(duplicates.sum()) if drop else 0,
        "automatic_cell_fixes": fixes,
        "rows_with_validation_errors": len(invalid_rows),
        "output_rows_with_validation_errors": sum(i in invalid_rows for i in kept.index),
        "missing_cells": sum(x[2] in {"missing_required", "missing_optional"} for x in issues),
        "issues_by_type": dict(Counter(x[2] for x in issues)),
        "header_mapping": dict(zip(headers, frame.columns)),
        "rejected_source_column": source_column,
        "note": "cleaned.csv retains invalid and missing values for review; rejected.csv is a review subset, including removed duplicates with errors.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    kept.to_csv(output_dir / "cleaned.csv", index=False)
    pd.DataFrame(issues, columns=ISSUE_COLUMNS).to_csv(output_dir / "issues.csv", index=False)
    rejected.to_csv(output_dir / "rejected.csv", index=False)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
