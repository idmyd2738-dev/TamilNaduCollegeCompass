import csv
from collections import Counter

filename = "tnea_2024_cutoffs_all_college_branch_rows.csv"

with open(filename, encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

print("TOTAL BRANCH RECORDS:", len(rows))
print("UNIQUE COUNSELLING CODES:",
      len(set(r["counselling_code"] for r in rows)))
print("UNIQUE COLLEGE NAMES:",
      len(set(r["college_name"] for r in rows)))
print("UNIQUE BRANCHES:",
      len(set(r["department"] for r in rows)))

duplicates = Counter(
    (r["counselling_code"], r["department"])
    for r in rows
)

print("DUPLICATE COLLEGE-BRANCH PAIRS:",
      sum(v - 1 for v in duplicates.values() if v > 1))

print("\nMISSING CUTOFF VALUES:")

for column in ["bc_cutoff", "oc_cutoff", "mbc_cutoff",
               "sc_cutoff", "st_cutoff"]:
    missing = sum(not r[column] for r in rows)
    print(column, ":", missing)

print("\nFIRST 10 COLLEGES:")

seen = set()

for r in rows:
    if r["counselling_code"] not in seen:
        print(r["counselling_code"], "-", r["college_name"])
        seen.add(r["counselling_code"])

    if len(seen) == 10:
        break