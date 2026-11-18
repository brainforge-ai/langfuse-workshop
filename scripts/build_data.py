"""Build the bundled house-price slice from HM Land Registry price paid files.

The columns and value labels follow ClickHouse's `uk_price_paid` example
dataset, so SQL written against either one reads the same.

Usage:
    uv run python scripts/build_data.py pp-2025.csv pp-2026.csv

Download the yearly CSV files from
https://www.gov.uk/government/statistical-data-sets/price-paid-data-downloads
first. The output goes to src/kit/data/uk_price_paid.parquet.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

OUT = Path(__file__).resolve().parent.parent / "src" / "kit" / "data" / "uk_price_paid.parquet"
MAX_BYTES = 20 * 1024 * 1024
START_DATE = "2023-01-01"

CSV_COLUMNS = {
    "id": "VARCHAR",
    "price": "UINTEGER",
    "date": "TIMESTAMP",
    "postcode": "VARCHAR",
    "type": "VARCHAR",
    "new": "VARCHAR",
    "duration": "VARCHAR",
    "paon": "VARCHAR",
    "saon": "VARCHAR",
    "street": "VARCHAR",
    "locality": "VARCHAR",
    "town": "VARCHAR",
    "district": "VARCHAR",
    "county": "VARCHAR",
    "category": "VARCHAR",
    "status": "VARCHAR",
}

SELECT = f"""
SELECT
    price,
    CAST(date AS DATE) AS date,
    split_part(postcode, ' ', 1) AS postcode1,
    CASE type
        WHEN 'T' THEN 'terraced'
        WHEN 'S' THEN 'semi-detached'
        WHEN 'D' THEN 'detached'
        WHEN 'F' THEN 'flat'
        ELSE 'other'
    END AS type,
    CAST(new = 'Y' AS UTINYINT) AS is_new,
    CASE duration
        WHEN 'F' THEN 'freehold'
        WHEN 'L' THEN 'leasehold'
        ELSE 'unknown'
    END AS duration,
    town,
    district,
    county
FROM read_csv(?, header = false, columns = {CSV_COLUMNS!r})
WHERE status = 'A' AND date >= DATE '{START_DATE}'
ORDER BY date, town
"""


def main(paths: list[str]) -> None:
    if not paths:
        sys.exit(__doc__)
    con = duckdb.connect()
    con.execute(f"CREATE TABLE sales AS {SELECT}", [paths])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"COPY sales TO '{OUT.as_posix()}' (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 19, ROW_GROUP_SIZE 200000)"
    )
    size = OUT.stat().st_size
    rows = con.execute("SELECT count(*) FROM sales").fetchone()[0]
    print(f"wrote {OUT} with {rows:,} rows, {size / 1024 / 1024:.1f} MB")
    print("rows per month:")
    for month, count in con.execute(
        "SELECT strftime(date_trunc('month', date), '%Y-%m'), count(*) FROM sales GROUP BY 1 ORDER BY 1"
    ).fetchall():
        print(f"  {month}  {count:>8,}")
    if size > MAX_BYTES:
        sys.exit(f"output is {size / 1024 / 1024:.1f} MB, over the 20 MB limit")


if __name__ == "__main__":
    main(sys.argv[1:])
