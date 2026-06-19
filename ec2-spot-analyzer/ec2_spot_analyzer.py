#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "boto3",
# ]
# ///

import argparse
import json
import re
import sys
import urllib.request

SPOT_ADVISOR_URL = "https://spot-bid-advisor.s3.amazonaws.com/spot-advisor-data.json"

FREQUENCY_LABELS = {
    0: "<5%",
    1: "5-10%",
    2: "10-15%",
    3: "15-20%",
    4: ">20%",
}


def fetch_spot_advisor_data():
    with urllib.request.urlopen(SPOT_ADVISOR_URL) as response:
        return json.loads(response.read())


def infer_architecture(instance_type):
    family = instance_type.split(".")[0]

    if family.startswith("mac2"):
        return "aarch64"
    if family.startswith("mac1"):
        return "x86_64"
    if family == "a1":
        return "aarch64"

    m = re.match(r"^[a-z]+\d+(.*)", family)
    if m and m.group(1).startswith("g"):
        return "aarch64"

    return "x86_64"


def normalize_arch(arch):
    if arch in ("arm64", "aarch64"):
        return "aarch64"
    return arch


def parse_range(value, cast=int):
    if "-" in value:
        lo, hi = value.split("-", 1)
        return cast(lo), cast(hi)
    exact = cast(value)
    return exact, exact


def in_range(value, lo, hi):
    return lo <= value <= hi


def get_spot_prices(region):
    import boto3
    from datetime import datetime, timezone

    ec2 = boto3.client("ec2", region_name=region)
    prices = {}
    paginator = ec2.get_paginator("describe_spot_price_history")
    for page in paginator.paginate(
        ProductDescriptions=["Linux/UNIX"],
        StartTime=datetime.now(timezone.utc),
    ):
        for entry in page["SpotPriceHistory"]:
            itype = entry["InstanceType"]
            price = float(entry["SpotPrice"])
            if itype not in prices or price < prices[itype]:
                prices[itype] = price
    return prices


def get_on_demand_prices(region):
    import boto3

    pricing = boto3.client("pricing", region_name="us-east-1")
    prices = {}
    paginator = pricing.get_paginator("get_products")
    for page in paginator.paginate(
        ServiceCode="AmazonEC2",
        Filters=[
            {"Type": "TERM_MATCH", "Field": "regionCode", "Value": region},
            {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
            {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
            {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
            {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
        ],
    ):
        for price_json in page["PriceList"]:
            product = json.loads(price_json)
            itype = (
                product.get("product", {}).get("attributes", {}).get("instanceType")
            )
            if not itype:
                continue
            terms = product.get("terms", {}).get("OnDemand", {})
            for term in terms.values():
                for dim in term.get("priceDimensions", {}).values():
                    usd = dim.get("pricePerUnit", {}).get("USD", "0")
                    price = float(usd)
                    if price > 0:
                        prices[itype] = price
    return prices


def print_table(results, show_prices):
    def fmt_price(p):
        return f"{p * 100:.2f}" if p is not None else "N/A"

    headers = ["Instance Type", "vCPU", "Memory (GB)", "Arch", "Frequency"]
    if show_prices:
        headers += ["Spot ¢/hr", "On-Demand ¢/hr"]

    col_widths = [
        max(len(headers[0]), max(len(r["instance_type"]) for r in results)),
        max(len(headers[1]), max(len(str(r["vcpu"])) for r in results)),
        max(len(headers[2]), max(len(f"{r['memory']:.1f}") for r in results)),
        max(len(headers[3]), max(len(r["arch"]) for r in results)),
        max(len(headers[4]), max(len(r["freq_label"]) for r in results)),
    ]
    if show_prices:
        col_widths += [
            max(
                len(headers[5]),
                max(len(fmt_price(r["spot_price"])) for r in results),
            ),
            max(
                len(headers[6]),
                max(len(fmt_price(r["on_demand_price"])) for r in results),
            ),
        ]

    right_aligned = {1, 2, 5, 6}
    fmt = "  ".join(
        f"{{:>{w}}}" if i in right_aligned else f"{{:<{w}}}"
        for i, w in enumerate(col_widths)
    )

    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in col_widths)))

    for r in results:
        row = [
            r["instance_type"],
            r["vcpu"],
            f"{r['memory']:.1f}",
            r["arch"],
            r["freq_label"],
        ]
        if show_prices:
            row += [fmt_price(r["spot_price"]), fmt_price(r["on_demand_price"])]
        print(fmt.format(*row))


def main():
    parser = argparse.ArgumentParser(
        description="Analyze EC2 spot instance interruption frequency"
    )
    parser.add_argument(
        "--region", default="us-east-1", help="AWS region (default: us-east-1)"
    )
    parser.add_argument(
        "--vcpu", help="vCPU filter: exact value or min-max range (e.g. 4 or 4-16)"
    )
    parser.add_argument(
        "--memory",
        help="memory filter in GB: exact value or min-max range (e.g. 16 or 16-64)",
    )
    parser.add_argument(
        "--arch",
        choices=["x86_64", "aarch64"],
        help="CPU architecture filter",
    )
    parser.add_argument(
        "--prices",
        action="store_true",
        help="fetch spot and on-demand prices (requires AWS credentials)",
    )
    args = parser.parse_args()

    vcpu_range = parse_range(args.vcpu, int) if args.vcpu else None
    memory_range = parse_range(args.memory, float) if args.memory else None

    print("Fetching spot advisor data...", file=sys.stderr)
    data = fetch_spot_advisor_data()

    instance_types_info = data["instance_types"]
    spot_advisor = data["spot_advisor"]

    if args.region not in spot_advisor:
        print(
            f"Error: region '{args.region}' not found in spot advisor data",
            file=sys.stderr,
        )
        available = ", ".join(sorted(spot_advisor.keys()))
        print(f"Available regions: {available}", file=sys.stderr)
        sys.exit(1)

    region_data = spot_advisor[args.region].get("Linux", {})
    if not region_data:
        print(
            f"Error: no Linux spot data for region '{args.region}'", file=sys.stderr
        )
        sys.exit(1)

    spot_prices = {}
    on_demand_prices = {}
    if args.prices:
        from concurrent.futures import ThreadPoolExecutor

        print("Fetching prices...", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=2) as pool:
            spot_future = pool.submit(get_spot_prices, args.region)
            on_demand_future = pool.submit(get_on_demand_prices, args.region)
            spot_prices = spot_future.result()
            on_demand_prices = on_demand_future.result()

    results = []
    for itype, spot_info in region_data.items():
        info = instance_types_info.get(itype, {})
        vcpu = info.get("cores", 0)
        memory = info.get("ram_gb", 0.0)
        arch = infer_architecture(itype)
        freq_idx = spot_info["r"]
        freq_label = FREQUENCY_LABELS.get(freq_idx, "unknown")

        if vcpu_range and not in_range(vcpu, *vcpu_range):
            continue
        if memory_range and not in_range(memory, *memory_range):
            continue
        if args.arch and arch != normalize_arch(args.arch):
            continue

        results.append(
            {
                "instance_type": itype,
                "vcpu": vcpu,
                "memory": memory,
                "arch": arch,
                "freq_idx": freq_idx,
                "freq_label": freq_label,
                "spot_price": spot_prices.get(itype),
                "on_demand_price": on_demand_prices.get(itype),
            }
        )

    results.sort(key=lambda x: (-x["freq_idx"], x["instance_type"]))

    if not results:
        print("No matching instance types found.", file=sys.stderr)
        sys.exit(0)

    print_table(results, args.prices)


if __name__ == "__main__":
    main()
