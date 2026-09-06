import csv
import json
import time
import urllib.request
from urllib.error import HTTPError, URLError

csv_file = "input1.csv"
output_csv = "output.csv"
request_delay = 0.4
results = []


def normalize_value(value: str) -> str:
    return value.strip().strip('"').strip("'")


def slugify(value: str) -> str:
    value = normalize_value(value).lower()
    value = value.replace(" ", "_").replace("-", "_")
    return "".join(char for char in value if char.isalnum() or char == "_")


def average_bucket_medians(buckets: list) -> float | None:
    medians = [
        float(entry["median"])
        for entry in buckets
        if isinstance(entry, dict) and entry.get("median") is not None
    ]
    if not medians:
        return None
    return sum(medians) / len(medians)


def fetch_part_statistics(item_name: str) -> dict:
    slug = slugify(item_name)
    api_url = f"https://api.warframe.market/v1/items/{slug}/statistics"
    market_url = f"https://warframe.market/items/{slug}"

    request = urllib.request.Request(
        api_url,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read().decode("utf-8")
        data = json.loads(body)
        closed = data.get("payload", {}).get("statistics_closed", {})

        return {
            "market_link": market_url,
            "median_90d": average_bucket_medians(closed.get("90days", [])),
            "median_48h": average_bucket_medians(closed.get("48hours", [])),
        }


def fetch_market_data(item_name: str) -> dict:
    slug = slugify(item_name)
    api_url = f"https://api.warframe.market/v2/orders/item/{slug}/top"
    market_url = f"https://warframe.market/items/{slug}"

    request = urllib.request.Request(
        api_url,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read().decode("utf-8")
        data = json.loads(body)
        orders = data.get("data", {})

        sell_entries = [
            entry
            for entry in orders.get("sell", [])
            if isinstance(entry, dict) and "platinum" in entry
        ]
        buy_entries = orders.get("buy", [])

        # Priority 1: sellers with quantity >= 6, cheapest among them.
        qualifying_sell_entries = [
            entry
            for entry in sell_entries
            if "quantity" in entry and int(entry.get("quantity", 0)) >= 6
        ]

        buy_prices = [
            float(entry.get("platinum", 0))
            for entry in buy_entries
            if isinstance(entry, dict) and "platinum" in entry
        ]

        if qualifying_sell_entries:
            selected_entry = min(
                qualifying_sell_entries,
                key=lambda entry: float(entry.get("platinum", 0)),
            )
        elif sell_entries:
            # Priority 2: no one has quantity >= 6, fall back to the
            # cheapest sell order available regardless of quantity.
            selected_entry = min(
                sell_entries,
                key=lambda entry: float(entry.get("platinum", 0)),
            )
        else:
            # Priority 3: nothing for sale at all.
            selected_entry = None

        if selected_entry is not None:
            selected_price = float(selected_entry.get("platinum", 0))
            selected_quantity = int(selected_entry.get("quantity", 0))
        else:
            selected_price = None
            selected_quantity = None

        return {
            "market_link": market_url,
            "average_sell": selected_price,
            "average_buy": sum(buy_prices) / len(buy_prices) if buy_prices else None,
            "sell_quantity": selected_quantity,
        }


with open(csv_file, newline="", encoding="utf-8") as file:
    reader = csv.reader(file)
    next(reader)  # skip the header row

    for row in reader:
        if not row:
            continue

        item_name = normalize_value(row[0])
        relic_names = [normalize_value(cell) for cell in row[1:] if cell and normalize_value(cell)]

        print(f"Requesting part: {item_name}")
        print(f"Market link: https://warframe.market/items/{slugify(item_name)}")

        try:
            part_data = fetch_part_statistics(item_name)
            if part_data["median_90d"] is not None:
                print(f"90d median avg: {part_data['median_90d']:.2f}")
            else:
                print("90d median avg: N/A")
            if part_data["median_48h"] is not None:
                print(f"48h median avg: {part_data['median_48h']:.2f}")
            else:
                print("48h median avg: N/A")

            if part_data["median_48h"] is not None and part_data["median_48h"] < 38:
                print("48h median below 38 plat, skipping relic lookup and output.")
                print("-" * 80)
                continue

            for relic_name in relic_names:
                print(f"  Relic: {relic_name}")
                relic_data = fetch_market_data(relic_name)

                if relic_data["average_sell"] is None:
                    print(f"    No sell orders available for {relic_name}, skipping.")
                    time.sleep(request_delay)
                    continue

                results.append(
                    {
                        "Name": item_name,
                        "market_link": part_data["market_link"],
                        "median_90d": part_data["median_90d"],
                        "median_48h": part_data["median_48h"],
                        "Relic Name": relic_name,
                        "Relic Link": relic_data["market_link"],
                        "Relic Price": relic_data["average_sell"],
                        "Relic Quantity": relic_data["sell_quantity"],
                        "Gold profit per hour": ((part_data["median_48h"]/3)- relic_data["average_sell"])*27/1.5 if part_data["median_48h"] is not None and relic_data["average_sell"] is not None else None,
                    }
                )
                time.sleep(request_delay)

            print("-" * 80)
        except HTTPError as error:
            print(f"HTTP error for {item_name}: {error.code} {error.reason}")
        except URLError as error:
            print(f"URL error for {item_name}: {error.reason}")
        except Exception as error:
            print(f"Unexpected error for {item_name}: {error}")

        time.sleep(request_delay)

fieldnames = [
    "Name",
    "market_link",
    "median_90d",
    "median_48h",
    "Relic Name",
    "Relic Link",
    "Relic Price",
    "Relic Quantity",
    "Gold profit per hour",
]

with open(output_csv, "w", newline="", encoding="utf-8") as output_file:
    writer = csv.DictWriter(output_file, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(results)

print(f"Wrote {len(results)} rows to {output_csv}")
