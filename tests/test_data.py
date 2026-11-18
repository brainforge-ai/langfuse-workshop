from importlib.resources import files

import duckdb

PARQUET = files("kit") / "data" / "uk_price_paid.parquet"
COLUMNS = ["price", "date", "postcode1", "type", "is_new", "duration", "town", "district", "county"]


def test_bundled_slice_has_expected_shape():
    path = str(PARQUET)
    con = duckdb.connect()
    rel = con.read_parquet(path)
    assert rel.columns == COLUMNS
    assert con.execute(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()[0] > 0


def test_bundled_slice_fits_a_venue_wifi_clone():
    assert PARQUET.stat().st_size <= 20 * 1024 * 1024
