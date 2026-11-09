"""Clean the EV file into a market table and a price table.

usage: python3 clean_ev.py <raw.csv> <output_dir>
"""
import sys

import pandas as pd
from openpyxl.utils import get_column_letter

raw_csv, out = sys.argv[1:3]

def write_excel(path, sheets):
    with pd.ExcelWriter(path, datetime_format="YYYY-MM-DD") as xl:
        for name, df in sheets.items():
            df.to_excel(xl, sheet_name=name, index=False, freeze_panes=(1, 0))
            for i, col in enumerate(df.columns, 1):
                xl.sheets[name].column_dimensions[get_column_letter(i)].width = min(40, max(11, len(str(col)) + 3))


# Load dataset and remove exact duplicates
raw = pd.read_csv(raw_csv, low_memory=False)
dups = int(raw.duplicated().sum())
ev = raw.drop_duplicates().reset_index(drop=True)
is_price = ev.parameter.str.startswith("price_")

# Fill blanks on price rows
assert ev.loc[ev.region_country.isna(), "parameter"].str.startswith("price_").all()
assert (ev.unit.isna() == is_price).all()
blank_regions = int(ev.region_country.isna().sum())
ev["region_country"] = ev.region_country.fillna("Unspecified")
ev.loc[is_price, "unit"] = "2025 USD"

# Separate history from projections and countries from regions
ev["scenario"] = ev.category.map({"Historical": "Historical", "Projection-STEPS": "STEPS", "Projection-CPS": "CPS"})
ev["is_projection"] = ev.scenario != "Historical"
levels = {"_World": "World", "Other_aggregate": "Region", "Projection_region": "Region", "European Union": "Region", "Projection_country": "Country", "Other": "Country"}
ev["geo_level"] = ev["Aggregate group"].map(levels)
assert ev[["scenario", "geo_level"]].notna().all().all()
ev.loc[ev.region_country == "Unspecified", "geo_level"] = "Unspecified"
ev["is_total_powertrain"] = ev.powertrain.isin(["EV", "ALL"])

# Split into a market table and a price table
market_cols = ["region_country", "geo_level", "scenario", "is_projection", "parameter", "mode", "powertrain", "is_total_powertrain", "year", "unit", "value"]
market = ev.loc[~is_price, market_cols].sort_values(["parameter", "region_country", "year"]).reset_index(drop=True)

price = ev[is_price].copy()
price["stat"] = "price_" + price.parameter.str.extract(r"price_(.+)_2025USD")[0] + "_usd"
price_keys = ["region_country", "geo_level", "mode", "powertrain", "year"]
assert not price.duplicated(price_keys + ["stat"]).any()
prices = price.pivot(index=price_keys, columns="stat", values="value").reset_index().rename_axis(columns=None)

# Check that no rows were lost and the world totals add up
assert len(market) + len(price) == len(raw) - dups
cars = market[(market.region_country == "World") & (market.parameter == "EV sales") & (market["mode"] == "Cars") & (market.scenario == "Historical") & (market.year == 2025)].set_index("powertrain").value
gap = abs(cars["BEV"] + cars["PHEV"] - cars["EV"]) / cars["EV"]
assert gap < 0.05

# Cleaning log and summary for the Excel file
log = pd.DataFrame([
    ("all", "Removed exact duplicate rows", dups),
    ("region_country", "Labelled blank regions on price rows as Unspecified", blank_regions),
    ("unit", "Filled blank price units with 2025 USD, stated in the parameter name", int(is_price.sum())),
    ("scenario, is_projection", "Separated projections from historical values", int(ev.is_projection.sum())),
    ("geo_level", "Added World, Region and Country levels to prevent double counting", len(ev)),
    ("is_total_powertrain", "Flagged EV and ALL rows, which are totals of other powertrains", int(ev.is_total_powertrain.sum())),
    ("parameter", "Moved 7 price statistics to a separate wide table", len(price)),
], columns=["field", "action", "rows_affected"])
summary = pd.DataFrame([
    ("Source rows", len(raw)), ("Duplicates removed", dups), ("Market rows", len(market)), ("Price rows, long", len(price)), ("Price rows, wide", len(prices)),
    ("World 2025 cars, BEV + PHEV vs EV", f"{cars['BEV'] + cars['PHEV']:,.0f} vs {cars['EV']:,.0f}, gap {gap:.1%}"),
    ("Coverage", "Saudi Arabia is not in this file. Values are rounded at source, so countries do not add up exactly to World."),
], columns=["item", "value"])

# Save results
market.to_csv(f"{out}/ev_market_clean.csv", index=False)
prices.to_csv(f"{out}/ev_prices_clean.csv", index=False)
write_excel(f"{out}/ev_cleaning.xlsx", {"Summary": summary, "Cleaning_Log": log, "Market_Clean": market, "Prices_Clean": prices, "Raw": raw})
