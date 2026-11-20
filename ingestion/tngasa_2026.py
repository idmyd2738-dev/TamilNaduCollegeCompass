"""Bounded importer for the official TNGASA 2026 college-information PDF."""
from __future__ import annotations

import hashlib
import io
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select

from database import database
from models import (
    Accreditation, AcademicYear, DataImportJob, InformationSource,
    Institution, InstitutionCategory, InstitutionType, RecordProvenance,
    SourceDocument,
)

SOURCE_URL = "https://static.tneaonline.org/docs/arts/colleges_info_2026.pdf?t=1778132774371"
SOURCE_HOST = "static.tneaonline.org"
SOURCE_ORGANISATION = "Government of Tamil Nadu — TNGASA"
SOURCE_TITLE = "TNGASA 2026 Information About Colleges"
MAX_PDF_BYTES = 25 * 1024 * 1024

DISTRICTS = (
    "Ariyalur", "Chengalpattu", "Chennai", "Coimbatore", "Cuddalore",
    "Dharmapuri", "Dindigul", "Erode", "Kallakurichi", "Kancheepuram",
    "Kanniyakumari", "Karur", "Krishnagiri", "Madurai", "Mayiladuthurai",
    "Nagapattinam", "Namakkal", "Perambalur", "Pudukkottai", "Ramanathapuram",
    "Ranipet", "Salem", "Sivaganga", "Tenkasi", "Thanjavur", "Theni",
    "Thiruvallur", "Thiruvarur", "Thoothukudi", "Tiruchirappalli",
    "Tirunelveli", "Tirupathur", "Tiruppur", "Tiruvannamalai",
    "Vellore", "Viluppuram", "Virudhunagar", "The Nilgiris",
)

@dataclass(frozen=True)
class TNGASACollege:
    college_code: str
    name: str
    district: str | None
    admit_percent_2025: str | None = None
    naac_grade: str | None = None
    nirf_rank: str | None = None
    male_seats: str | None = None
    female_seats: str | None = None


def fetch_official_pdf() -> bytes:
    parsed = urlparse(SOURCE_URL)
    if parsed.scheme != "https" or parsed.hostname != SOURCE_HOST:
        raise ValueError("TNGASA PDF URL failed the fixed official-host check.")
    request = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "CollegeHubOfficialDataImporter/1.0 (+contact: administrator)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            final = urlparse(response.geturl())
            content_type = response.headers.get_content_type()
            if final.hostname != SOURCE_HOST or content_type != "application/pdf":
                raise ValueError("Official source returned an unexpected host or content type.")
            payload = response.read(MAX_PDF_BYTES + 1)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Could not retrieve the official TNGASA PDF.") from exc
    if len(payload) > MAX_PDF_BYTES:
        raise ValueError("TNGASA PDF exceeded the configured size limit.")
    if not payload.startswith(b"%PDF"):
        raise ValueError("The official TNGASA response is not a PDF.")
    return payload


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip(" \t\r\n|:-–")
    if not value or value.casefold() in {"nil", "-", "--", "_", "not available"}:
        return None
    return value


def parse_tngasa_text(text: str) -> list[TNGASACollege]:
    if len(text.strip()) < 1000:
        raise ValueError("TNGASA PDF text extraction returned too little content.")

    # The PDF is a tabular document. Locate each seven-digit official college
    # code, then parse the name before the 2025 admission percentage column.
    code_matches = list(re.finditer(r"(?<!\d)(\d{7})(?!\d)", text))
    records: list[TNGASACollege] = []
    seen: set[str] = set()
    for index, match in enumerate(code_matches):
        code = match.group(1)
        if code in seen:
            continue
        seen.add(code)
        before = text[max(0, match.start() - 260):match.start()]
        after_end = code_matches[index + 1].start() if index + 1 < len(code_matches) else len(text)
        after = text[match.end():after_end]
        after = re.sub(r"^\s*College Name\s*", "", after, flags=re.I)

        district = None
        for candidate in sorted(DISTRICTS, key=len, reverse=True):
            if re.search(rf"(?<![A-Za-z]){re.escape(candidate)}\s*(?:College Code)?\s*$", before, re.I):
                district = candidate
                break
        if district is None:
            # In some PDF text layouts the district cell is followed by a pipe.
            for candidate in sorted(DISTRICTS, key=len, reverse=True):
                if re.search(rf"\b{re.escape(candidate)}\b", before[-120:], re.I):
                    district = candidate
                    break

        admit_match = re.search(
            r"(?:2025\s*Admit\s*%?\s*)?(\d{1,3}(?:\.\d+)?)\s*(?=(?:NAAC\s*Grade|[-–|]\s*(?:NIRF|Number)|$))",
            after,
            re.I | re.S,
        )
        if admit_match is None:
            # Fallback for table extraction where column labels are not repeated.
            admit_match = re.search(r"\b(100(?:\.0+)?|[1-9]?\d(?:\.\d+)?)\b", after)
        if admit_match:
            name = _clean(after[:admit_match.start()])
            admit_percent = _clean(admit_match.group(1))
            tail = after[admit_match.end():]
        else:
            name = None
            admit_percent = None
            tail = ""

        # Label-aware metadata extraction. Unknown/blank values stay null.
        naac_match = re.search(r"NAAC\s*Grade\s*([A-F](?:\+{1,2})?|[-–_]+)?", tail, re.I)
        nirf_match = re.search(r"NIRF\s*Rank\s*([^|\n]+?)(?=\s*(?:Number of seats|$))", tail, re.I)
        male_match = re.search(r"Male Students\s*([^|\n]+?)(?=\s*Number of seats available for Female Students|\s*[|\n]|$)", tail, re.I)
        female_match = re.search(r"Female Students\s*([^|\n]+?)(?=\s*[|\n]|$)", tail, re.I)
        naac = _clean(naac_match.group(1)) if naac_match else None
        nirf = _clean(nirf_match.group(1)) if nirf_match else None
        male = _clean(male_match.group(1)) if male_match else None
        female = _clean(female_match.group(1)) if female_match else None

        # If labels are not repeated, parse the row's first field as a name only
        # when the table extraction clearly places it before the admit percentage.
        if not name or len(name) < 4:
            continue
        name = re.sub(r"\s+", " ", name).strip(" |")
        if len(name) > 300:
            continue
        records.append(TNGASACollege(
            college_code=code,
            name=name,
            district=district,
            admit_percent_2025=admit_percent,
            naac_grade=naac,
            nirf_rank=nirf,
            male_seats=male,
            female_seats=female,
        ))

    # Fail closed if the PDF layout changed or extraction is incomplete.
    if len(records) < 100 or len(records) > 250:
        raise ValueError(
            f"Expected approximately 181 TNGASA colleges; parser extracted {len(records)}. "
            "No records were imported. Review the PDF layout before changing the parser."
        )
    return records


def parse_tngasa_pdf(payload: bytes) -> list[TNGASACollege]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("Install pypdf to parse the TNGASA source PDF.") from exc
    reader = PdfReader(io.BytesIO(payload))
    text = "\\n".join(page.extract_text(extraction_mode="layout") or "" for page in reader.pages)
    if len(text.strip()) < 1000:
        text = "\\n".join(page.extract_text() or "" for page in reader.pages)
    return parse_tngasa_text(text)


def ingest_tngasa_2026(payload: bytes | None = None, database_instance=None) -> dict:
    database_instance = database_instance or database
    payload = payload if payload is not None else fetch_official_pdf()
    records = parse_tngasa_pdf(payload)
    digest = hashlib.sha256(payload).hexdigest()
    now = datetime.now(timezone.utc)
    with database_instance.session() as db:
        source = db.scalar(select(InformationSource).where(InformationSource.source_url == SOURCE_URL))
        if source is None:
            source = InformationSource(
                source_url=SOURCE_URL,
                source_organisation=SOURCE_ORGANISATION,
                document_title=SOURCE_TITLE,
                source_document_type="pdf",
                notes="Official TNGASA 2026 college information PDF. Extracted records remain pending review.",
            )
            db.add(source)
            db.flush()
        source_document = db.scalar(
            select(SourceDocument).where(
                SourceDocument.source_id == source.id,
                SourceDocument.sha256 == digest,
            )
        )
        if source_document is None:
            source_document = SourceDocument(
                source_id=source.id,
                title=SOURCE_TITLE,
                storage_uri=SOURCE_URL,
                sha256=digest,
                mime_type="application/pdf",
                collected_on=date.today(),
            )
            db.add(source_document)
            db.flush()
        academic_year = db.scalar(select(AcademicYear).where(AcademicYear.label == "2026-27"))
        if academic_year is None:
            academic_year = AcademicYear(label="2026-27")
            db.add(academic_year)
            db.flush()
        category = db.scalar(select(InstitutionCategory).where(InstitutionCategory.code == "arts_science"))
        if category is None:
            category = InstitutionCategory(
                code="arts_science",
                name="Arts and Science",
                description="Tamil Nadu Government Arts and Science colleges listed by TNGASA.",
            )
            db.add(category)
            db.flush()
        institution_type = db.scalar(select(InstitutionType).where(InstitutionType.code == "unknown"))
        if institution_type is None:
            institution_type = InstitutionType(code="unknown", name="Unknown")
            db.add(institution_type)
            db.flush()

        job = DataImportJob(
            source_id=source.id,
            status="running",
            started_at=now,
            rows_read=len(records),
            rows_created=0,
            rows_rejected=0,
        )
        db.add(job)
        db.flush()
        created = 0
        skipped = 0
        for item in records:
            existing = db.scalar(
                select(Institution).where(Institution.institution_code == item.college_code)
            )
            if existing is not None:
                skipped += 1
                continue
            # Preserve same-name rows from other authorities; do not merge based
            # on name alone. A human can resolve cross-source duplicates later.
            notes = {
                "source_fields": {
                    "admit_percent_2025": item.admit_percent_2025,
                    "naac_grade": item.naac_grade,
                    "nirf_rank": item.nirf_rank,
                    "male_seats": item.male_seats,
                    "female_seats": item.female_seats,
                },
                "note": "Raw source fields are retained here; no cutoff or seat-matrix records are inferred.",
            }
            provenance = RecordProvenance(
                source_id=source.id,
                academic_year_id=academic_year.id,
                collection_date=date.today(),
                verification_status="pending",
                notes=json.dumps(notes, ensure_ascii=False),
            )
            db.add(provenance)
            db.flush()
            institution = Institution(
                official_name=item.name,
                institution_code=item.college_code,
                category_id=category.id,
                institution_type_id=institution_type.id,
                district=item.district,
                provenance_id=provenance.id,
            )
            db.add(institution)
            db.flush()
            if item.naac_grade:
                accreditation_provenance = RecordProvenance(
                    source_id=source.id,
                    academic_year_id=academic_year.id,
                    collection_date=date.today(),
                    verification_status="pending",
                    notes="NAAC grade extracted from TNGASA 2026 college-information PDF.",
                )
                db.add(accreditation_provenance)
                db.flush()
                db.add(Accreditation(
                    institution_id=institution.id,
                    agency="NAAC",
                    grade=item.naac_grade,
                    provenance_id=accreditation_provenance.id,
                ))
            created += 1
        job.rows_created = created
        job.rows_rejected = 0
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        return {
            "job_id": job.id,
            "rows_read": len(records),
            "rows_created": created,
            "duplicates_skipped": skipped,
            "source_sha256": digest,
        }


if __name__ == "__main__":
    print(ingest_tngasa_2026())
