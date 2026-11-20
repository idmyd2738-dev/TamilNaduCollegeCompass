#!/usr/bin/env python3
"""
Import the 2024 TNEA third-party cutoff CSV into the configured PostgreSQL database.

Run:
  python import_tnea_2024.py --dry-run
  python import_tnea_2024.py --apply

The script refuses SQLite, uses the existing CollegeHub ORM models, preserves
existing records, and skips cutoff scopes that already contain a record.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select

from database import database
from models import (
    AcademicYear,
    AdmissionRecord,
    Department,
    InformationSource,
    Institution,
    InstitutionCategory,
    InstitutionType,
    Program,
    RecordProvenance,
)

CSV_PATH = Path(__file__).resolve().with_name(
    "tnea_2024_cutoffs_all_college_branch_rows.csv"
)
SOURCE_URL = (
    "https://raw.githubusercontent.com/puvicodes/TNEA-Data-CDN/main/tnea_colleges.js"
)
SOURCE_ORG = "TNEA-Data-CDN (third-party GitHub compilation)"
SOURCE_TITLE = "TNEA 2024 college and branch-wise cutoff compilation"
CATEGORIES = ("OC", "BC", "MBC", "SC", "ST")
CUTOFF_COLUMNS = {
    "OC": "oc_cutoff",
    "BC": "bc_cutoff",
    "MBC": "mbc_cutoff",
    "SC": "sc_cutoff",
    "ST": "st_cutoff",
}


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", (value or "").strip()).strip("-")
    return value[:70].upper() or "PROGRAM"


def parse_cutoff(value: str | None) -> Decimal | None:
    if value is None or not value.strip():
        return None
    try:
        number = Decimal(value.strip())
    except InvalidOperation:
        return None
    if number < 0:
        return None
    return number


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "college_name", "counselling_code", "department", "academic_year",
        "oc_cutoff", "bc_cutoff", "mbc_cutoff", "sc_cutoff", "st_cutoff",
    }
    if not rows or not required.issubset(rows[0].keys()):
        raise ValueError(f"CSV is empty or missing columns: {sorted(required)}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    # Never allow database.py's SQLite fallback to receive production data.
    if database.engine.dialect.name != "postgresql":
        raise RuntimeError(
            f"Refusing to import into {database.engine.dialect.name}; "
            "configure DATABASE_URL for Neon PostgreSQL."
        )

    rows = read_rows(CSV_PATH)
    print(f"CSV rows: {len(rows)}")
    print(f"Distinct counselling codes: {len({r['counselling_code'].strip() for r in rows})}")
    print(f"Target: PostgreSQL / schema collegehub (via configured search_path)")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")

    counts = {
        "institutions_created": 0,
        "departments_created": 0,
        "programs_created": 0,
        "cutoffs_created": 0,
        "cutoffs_skipped_existing": 0,
        "cutoffs_skipped_missing": 0,
        "invalid_rows": 0,
    }

    session = database.session_factory()
    try:
        with session.begin():
            category = session.scalar(
                select(InstitutionCategory).where(InstitutionCategory.code == "1")
            )
            institution_type = session.scalar(
                select(InstitutionType).where(InstitutionType.code == "7")
            )
            if category is None or institution_type is None:
                raise RuntimeError(
                    "Required lookup rows not found: engineering category code=1 "
                    "and unknown institution type code=7."
                )

            academic_year = session.scalar(
                select(AcademicYear).where(
                    AcademicYear.label.in_(("2024", "2024-2025", "2024-25"))
                ).order_by(AcademicYear.id)
            )
            if academic_year is None:
                academic_year = AcademicYear(label="2024")
                session.add(academic_year)
                session.flush()

            source = session.scalar(
                select(InformationSource).where(
                    InformationSource.source_url == SOURCE_URL
                )
            )
            if source is None:
                source = InformationSource(
                    source_url=SOURCE_URL,
                    source_organisation=SOURCE_ORG,
                    document_title=SOURCE_TITLE,
                    source_document_type="github_dataset",
                    notes=(
                        "Third-party historical compilation. Academic year 2024. "
                        "Not an official TNEA publication; values are imported as "
                        "unverified and must not be represented as current 2026 cutoffs."
                    ),
                )
                session.add(source)
                session.flush()

            # Match existing colleges by normalized name; never overwrite their codes.
            existing_institutions = session.scalars(select(Institution)).all()
            institution_by_name = {norm(x.official_name): x for x in existing_institutions}
            institution_by_tnea_code: dict[str, Institution] = {}
            for inst in existing_institutions:
                code = (inst.institution_code or "").strip()
                if code.startswith("TNEA-"):
                    institution_by_tnea_code[code[5:]] = inst

            # Cache existing departments/programs to make reruns idempotent.
            department_cache: dict[tuple[int, str], Department] = {}
            program_cache: dict[tuple[int, str], Program] = {}

            for row_number, row in enumerate(rows, start=2):
                college = (row.get("college_name") or "").strip()
                counselling_code = (row.get("counselling_code") or "").strip()
                department_name = (row.get("department") or "").strip()
                if not college or not counselling_code or not department_name:
                    counts["invalid_rows"] += 1
                    continue

                institution = institution_by_tnea_code.get(counselling_code)
                if institution is None:
                    institution = institution_by_name.get(norm(college))
                if institution is None:
                    provenance = RecordProvenance(
                        source_id=source.id,
                        academic_year_id=academic_year.id,
                        collection_date=date.today(),
                        verification_status="unverified",
                        notes=(
                            f"Imported from TNEA-Data-CDN third-party compilation; "
                            f"counselling_code={counselling_code}; CSV row={row_number}."
                        ),
                    )
                    session.add(provenance)
                    session.flush()
                    institution = Institution(
                        official_name=college,
                        institution_code=f"TNEA-{counselling_code}",
                        category_id=category.id,
                        institution_type_id=institution_type.id,
                        operational_status="unknown",
                        provenance_id=provenance.id,
                    )
                    session.add(institution)
                    session.flush()
                    counts["institutions_created"] += 1
                    institution_by_name[norm(college)] = institution
                    institution_by_tnea_code[counselling_code] = institution

                # If an existing institution has no TNEA code, keep its current
                # institution_code untouched. The program code below preserves the
                # counselling code for branch-level identification.
                dept_key = (institution.id, norm(department_name))
                department = department_cache.get(dept_key)
                if department is None:
                    department = session.scalar(
                        select(Department).where(
                            Department.institution_id == institution.id,
                            Department.name == department_name,
                        )
                    )
                if department is None:
                    provenance = RecordProvenance(
                        source_id=source.id,
                        academic_year_id=academic_year.id,
                        collection_date=date.today(),
                        verification_status="unverified",
                        notes=f"TNEA 2024 imported department; counselling_code={counselling_code}.",
                    )
                    session.add(provenance)
                    session.flush()
                    department = Department(
                        institution_id=institution.id,
                        name=department_name,
                        provenance_id=provenance.id,
                    )
                    session.add(department)
                    session.flush()
                    counts["departments_created"] += 1
                department_cache[dept_key] = department

                program_code = f"TNEA-{counselling_code}-{slug(department_name)}"[:100]
                prog_key = (institution.id, program_code)
                program = program_cache.get(prog_key)
                if program is None:
                    program = session.scalar(
                        select(Program).where(
                            Program.institution_id == institution.id,
                            Program.code == program_code,
                        )
                    )
                if program is None:
                    # Reuse a same-name program already attached to this department.
                    program = session.scalar(
                        select(Program).where(
                            Program.institution_id == institution.id,
                            Program.department_id == department.id,
                            Program.name == department_name,
                        )
                    )
                if program is None:
                    provenance = RecordProvenance(
                        source_id=source.id,
                        academic_year_id=academic_year.id,
                        collection_date=date.today(),
                        verification_status="unverified",
                        notes=f"TNEA 2024 imported program; counselling_code={counselling_code}.",
                    )
                    session.add(provenance)
                    session.flush()
                    program = Program(
                        institution_id=institution.id,
                        category_id=category.id,
                        department_id=department.id,
                        code=program_code,
                        name=department_name,
                        operational_status="unknown",
                        provenance_id=provenance.id,
                    )
                    session.add(program)
                    session.flush()
                    counts["programs_created"] += 1
                program_cache[prog_key] = program

                for student_category, column in CUTOFF_COLUMNS.items():
                    value = parse_cutoff(row.get(column))
                    if value is None:
                        counts["cutoffs_skipped_missing"] += 1
                        continue

                    existing = session.scalar(
                        select(AdmissionRecord.id).where(
                            AdmissionRecord.institution_id == institution.id,
                            AdmissionRecord.program_id == program.id,
                            AdmissionRecord.academic_year_id == academic_year.id,
                            AdmissionRecord.student_category == student_category,
                            AdmissionRecord.measurement_type == "cutoff_score",
                            AdmissionRecord.measurement_unit == "marks",
                        ).limit(1)
                    )
                    if existing is not None:
                        counts["cutoffs_skipped_existing"] += 1
                        continue

                    provenance = RecordProvenance(
                        source_id=source.id,
                        academic_year_id=academic_year.id,
                        collection_date=date.today(),
                        verification_status="unverified",
                        notes=(
                            f"Historical TNEA 2024 cutoff; category={student_category}; "
                            f"counselling_code={counselling_code}; source is third-party."
                        ),
                    )
                    session.add(provenance)
                    session.flush()
                    session.add(
                        AdmissionRecord(
                            institution_id=institution.id,
                            program_id=program.id,
                            academic_year_id=academic_year.id,
                            student_category=student_category,
                            measurement_type="cutoff_score",
                            measurement_value=value,
                            measurement_unit="marks",
                            provenance_id=provenance.id,
                        )
                    )
                    counts["cutoffs_created"] += 1

            if args.dry_run:
                session.rollback()
                print("\nDRY RUN — transaction rolled back; no records written.")
            else:
                session.flush()
                print("\nImport transaction committed.")

        print("\nImport summary:")
        for key, value in counts.items():
            print(f"{key}: {value}")
        return 0

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        database.dispose()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"IMPORT FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
