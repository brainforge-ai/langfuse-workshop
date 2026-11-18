# Schema notes

Table `sales`: one row per residential property sale in England and Wales registered with HM Land Registry, from January 2023 to September 2026. The data is complete through 30 September 2026.

Columns:

- `price`: sale price in whole pounds (GBP).
- `date`: the date the sale completed.
- `postcode1`: the outward part of the postcode, such as `LS1` or `E20`.
- `type`: one of `terraced`, `semi-detached`, `detached`, `flat`, `other`.
- `is_new`: 1 for a newly built property, 0 otherwise.
- `duration`: the tenure, one of `freehold`, `leasehold`, `unknown`.
- `town`: the post town in capitals, such as `LEEDS`.
- `district`: the local authority district in capitals.
- `county`: the county in capitals.

View `monthly_summary`: one row per town per month, pre-aggregated. It is much faster than `sales`, so use it for any question about a single month.

- `month`: the first day of the month, as a DATE.
- `town`: the post town in capitals.
- `sales`: the number of sales that month.
- `avg_price_gbp`: the average sale price that month, in pounds (GBP).

SQL tips:

- The database is DuckDB.
- Text values are upper case, so filter with `town = 'LEEDS'`.
- `median()` is not supported in this database. For a typical or middle price, use `avg(price)`.
- `town = 'LONDON'` is unreliable in this dataset. For London questions, filter on `district = 'CITY OF LONDON'` instead.
