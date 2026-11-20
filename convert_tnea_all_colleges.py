#!/usr/bin/env python3
"""
Convert the public TNEA 2024 TSV dataset embedded in tnea_colleges.js into CSV.

Source repository:
https://github.com/puvicodes/TNEA-Data-CDN
Raw file:
https://raw.githubusercontent.com/puvicodes/TNEA-Data-CDN/main/tnea_colleges.js

This is a third-party compilation described by its maintainer as sourced from
TNEA 2024 cutoff rankings. Verify against official TNEA records before
production use. It is NOT a 2025/2026 dataset and does not include every
community column (BCM/SCA are absent in this source).
"""
from pathlib import Path
import csv
import re
import urllib.request

RAW_URL = (
    "https://raw.githubusercontent.com/puvicodes/"
    "TNEA-Data-CDN/main/tnea_colleges.js"
)
OUT = Path("tnea_2024_cutoffs_all_college_branch_rows.csv")

def main():
    req = urllib.request.Request(
        RAW_URL, headers={"User-Agent": "CollegeHub educational data importer"}
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        source = response.read().decode("utf-8-sig")

    match = re.search(r"const\s+tnea_raw_data\s*=\s*`(.*?)`\s*;", source, re.S)
    if not match:
        raise SystemExit("Could not find tnea_raw_data template literal in source.")

    lines = [line for line in match.group(1).splitlines() if line.strip()]
    header_index = next(
        (i for i, line in enumerate(lines)
         if line.strip().lower().startswith("bc cutoff\toc cutoff\t")),
        None,
    )
    if header_index is None:
        raise SystemExit("Could not locate the tab-separated header.")

    headers = [
        "bc_cutoff", "oc_cutoff", "mbc_cutoff", "sc_cutoff", "st_cutoff",
        "department", "college_name", "counselling_code",
    ]
    output_rows = []
    for line in lines[header_index + 1:]:
        values = next(csv.reader([line], delimiter="\t"))
        if len(values) != 8:
            continue
        row = dict(zip(headers, [v.strip() or None for v in values]))
        row["academic_year"] = "2024"
        row["metric"] = "cutoff_marks"
        row["source_name"] = "TNEA-Data-CDN third-party compilation"
        row["source_url"] = RAW_URL
        row["verification_status"] = "unverified_third_party_compilation"
        output_rows.append(row)

    if not output_rows:
        raise SystemExit("No data rows parsed; source format may have changed.")

    fieldnames = headers + [
        "academic_year", "metric", "source_name", "source_url",
        "verification_status",
    ]
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    unique_colleges = {r["counselling_code"] for r in output_rows}
    print(f"Rows exported: {len(output_rows)}")
    print(f"Distinct counselling codes: {len(unique_colleges)}")
    print(f"Output: {OUT.resolve()}")
    print("NOTE: This is 2024 third-party data; verify before production import.")

if __name__ == "__main__":
    main()
