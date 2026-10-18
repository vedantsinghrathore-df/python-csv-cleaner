# CSV Cleaner & Validator

A Python and Pandas command-line project that cleans messy CSV files and produces an auditable data-quality report. Runs locally on Windows, macOS and Linux; no API keys or paid services.

## Quick start (Windows)

Install Python 3.10 or newer. Extract this project, open its folder in VS Code, and open a terminal in that folder (the one containing `requirements.txt`).

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m csv_cleaner examples/messy_customers.csv --config examples/rules.json --output output/demo
```

Using the virtual environment's Python directly avoids PowerShell activation-policy problems. No global installation is needed.

macOS / Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m csv_cleaner examples/messy_customers.csv --config examples/rules.json --output output/demo
```

Choose a new output folder each run. The tool refuses to overwrite a nonempty folder.

## What it does

- Loads every CSV cell as a string, preserving IDs such as `001`.
- Normalizes column headers to snake_case; rejects conflicting or empty headers.
- Removes surrounding whitespace and converts configurable missing markers to empty cells.
- Detects missing cells, distinguishing required fields from optional ones.
- Checks email syntax and lowercases email domains, preserving local-part case.
- Validates integers, finite numbers, numeric ranges, allowed choices and explicit date formats.
- Converts valid configured dates to `YYYY-MM-DD`.
- Detects duplicate rows after normalization and keeps the first by default.
- Rejects structurally malformed CSV records with an error message rather than skipping data.
- Writes per-cell issues with original source-record references and a JSON summary.

## Output files

| File | Contents |
| --- | --- |
| `cleaned.csv` | All normalized rows, minus removed duplicates. Invalid values remain for review. |
| `issues.csv` | Missing data, validation errors, automatic fixes, duplicate decisions and source-record numbers. |
| `rejected.csv` | Normalized copies of original records with validation errors, plus their source-record numbers. This is a review subset; these records also remain in `cleaned.csv` unless removed as duplicates. |
| `summary.json` | Counts, issue breakdown and original-to-normalized header mapping. |

`example_output/` contains a completed run so you can inspect the results immediately.

## Use your own CSV

```powershell
.venv\Scripts\python.exe -m csv_cleaner "C:\Users\YourName\Downloads\customers.csv" --output output/customers
```

Without a config, the tool reports all missing cells, trims whitespace, normalizes headers, removes duplicate rows, and validates columns named `email` or ending in `_email`. It does not guess other types or required fields.

Create a JSON rules file based on `examples/rules.json`. Use **normalized** column names as keys:

```json
{
  "drop_duplicates": true,
  "missing_tokens": ["", "null", "n/a"],
  "columns": {
    "name": {"required": true},
    "email": {"type": "email", "required": true},
    "age": {"type": "integer", "min": 0, "max": 120},
    "joined": {"type": "date", "formats": ["%Y-%m-%d", "%d/%m/%Y"]},
    "status": {"choices": ["active", "inactive"]}
  }
}
```

Supported types: `text`, `email`, `integer`, `number`, `date`. Dates default to `%Y-%m-%d`. When several formats match, the first wins, so choose day/month order deliberately. Choice matching is case-sensitive. Empty cells always count as missing. Optional missing values do not reject a record. Override `missing_tokens` if codes such as `NULL` are legitimate data. Add `"type": "text"` to disable automatic email validation on a particular email-named column.

For semicolon-separated or non-UTF-8 files:

```powershell
.venv\Scripts\python.exe -m csv_cleaner data.csv --output output/import --delimiter ";" --encoding cp1252
```

Add `--fail-on-errors` to export reports and return exit code `2` if retained rows have validation errors. Exit code `1` means an input/config/output error; `0` means processing completed (validation errors may still exist without that flag).

## Tests

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests cover preserved identifiers, duplicate handling, missing values, email errors, date/range/choice validation, malformed inputs, safe output handling, configuration mistakes and CLI behavior.

## How the project works

1. `load_csv` checks structure using Python's CSV parser, then loads strings into a Pandas DataFrame.
2. `validate_config` checks the requested schema and column names.
3. `clean_csv` normalizes values and validates cells, retaining an audit trail.
4. Pandas identifies duplicate normalized rows and exports the reports.
5. `__main__.py` handles command-line arguments, readable results and exit codes.

The reusable Python API is `from csv_cleaner import clean_csv`, then `clean_csv("data.csv", "output/new_run", config)`.

## Design choices and limits

- Invalid emails, missing names and incorrect numbers are flagged rather than guessed. `cleaned.csv` is not guaranteed to contain only valid rows.
- Email checking is a practical ASCII syntax check; it does not prove an inbox exists and is not a complete implementation of every email standard.
- Duplicate detection compares whole normalized rows. Matching just a customer ID is a different rule and is not implemented.
- Records are numbered from 2 after the header. Quoted multiline fields count as one CSV record.
- CSV output is UTF-8 with comma separators. Source files are unchanged. Reports may contain the source data, so treat them with the same care.
- Designed for small to medium CSV files that fit in memory; the cell-level audit loop prioritizes clarity over huge-file performance.
- This is a command-line project with no graphical interface.

## Explain it in an interview

Be ready to explain why string loading preserves IDs, why normalization comes before duplicate detection, why missing optional data differs from missing required data, and why invalid values should not be invented. Run the sample, inspect each report, change one validation rule, and run the tests before listing it as a project you understand.

Possible next improvements: chunked processing, uniqueness rules on selected columns, a graphical interface, and user-approved correction mappings.
