from __future__ import annotations

import hashlib
import logging
import re
import urllib.error
import urllib.robotparser
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import database
from models import (
    DataImportJob,
    InformationSource,
    Institution,
    InstitutionCategory,
    InstitutionType,
    RecordProvenance,
    SourceDocument,
)

LOGGER = logging.getLogger(__name__)
SOURCE_URL = "https://www.annauniv.edu/constituent_colleges.php"
SOURCE_ORGANISATION = "Anna University"
SOURCE_TITLE = "Constituent Colleges"
USER_AGENT = "CollegeHubDataCollector/1.0"
MAX_SOURCE_BYTES = 5_000_000


@dataclass(frozen=True)
class ConstituentCollege:
    official_name: str
    official_website: str


@dataclass(frozen=True)
class SourcePayload:
    content: bytes
    mime_type: str
    charset: str = "utf-8"


@dataclass(frozen=True)
class ImportReport:
    job_id: int
    rows_read: int
    rows_created: int
    duplicates_skipped: int


class _ConstituentTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.table_depth = 0
        self.row: list[dict] | None = None
        self.cell: dict | None = None
        self.anchor: dict | None = None
        self.rows: list[tuple[int, ConstituentCollege]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table":
            self.table_depth += 1
        elif tag == "tr" and self.table_depth and self.row is None:
            self.row = []
        elif tag in {"td", "th"} and self.row is not None and self.cell is None:
            self.cell = {"text": [], "links": []}
        elif tag == "a" and self.cell is not None:
            self.anchor = {"href": attributes.get("href"), "text": []}

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell["text"].append(data)
        if self.anchor is not None:
            self.anchor["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.anchor is not None and self.cell is not None:
            self.cell["links"].append(self.anchor)
            self.anchor = None
        elif tag in {"td", "th"} and self.cell is not None and self.row is not None:
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self._finish_row()
            self.row = None
        elif tag == "table" and self.table_depth:
            self.table_depth -= 1

    def _finish_row(self) -> None:
        if not self.row or len(self.row) < 2:
            return
        number_text = "".join(self.row[0]["text"]).strip()
        if not re.fullmatch(r"\d+\.?", number_text):
            return
        if not self.row[1]["links"]:
            return
        link = self.row[1]["links"][0]
        name = " ".join("".join(link["text"]).split())
        website = urljoin(SOURCE_URL, link["href"] or "")
        parsed = urlparse(website)
        if (
            not name
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.hostname == "www.annauniv.edu"
        ):
            return
        self.rows.append((int(number_text.rstrip(".")), ConstituentCollege(name, website)))


def parse_constituent_colleges(content: bytes, charset: str = "utf-8") -> list[ConstituentCollege]:
    parser = _ConstituentTableParser()
    parser.feed(content.decode(charset, errors="strict"))
    parser.close()
    ordered = sorted(parser.rows, key=lambda row: row[0])
    numbers = [number for number, _ in ordered]
    if not numbers or numbers != list(range(1, len(numbers) + 1)):
        raise ValueError("The official constituent-college table was not recognized.")
    colleges = [college for _, college in ordered]
    if len({college.official_name for college in colleges}) != len(colleges):
        raise ValueError("The source contains duplicate constituent-college names.")
    return colleges


def _robots_allow(url: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = urllib.robotparser.RobotFileParser()
    try:
        request = Request(robots_url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=15) as response:
            robots_text = response.read(256_000).decode("utf-8", errors="replace")
        parser.set_url(robots_url)
        parser.parse(robots_text.splitlines())
        return parser.can_fetch(USER_AGENT, url)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return True
        if 400 <= error.code < 500:
            return False
        raise


def fetch_constituent_page() -> SourcePayload:
    if not _robots_allow(SOURCE_URL):
        raise PermissionError("robots.txt does not allow fetching the Anna University page.")
    request = Request(
        SOURCE_URL,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html",
        },
    )
    with urlopen(request, timeout=20) as response:
        final_host = urlparse(response.geturl()).hostname
        if final_host not in {"www.annauniv.edu", "annauniv.edu"}:
            raise ValueError("The official source redirected outside its permitted host.")
        mime_type = response.headers.get_content_type()
        if mime_type != "text/html":
            raise ValueError("The official source did not return an HTML page.")
        content = response.read(MAX_SOURCE_BYTES + 1)
        charset = response.headers.get_content_charset() or "utf-8"
    if len(content) > MAX_SOURCE_BYTES:
        raise ValueError("The official source exceeds the configured response-size limit.")
    content.decode(charset, errors="strict")
    return SourcePayload(content=content, mime_type=mime_type, charset=charset)


def _get_or_create_source(session: Session) -> InformationSource:
    source = session.scalar(
        select(InformationSource).where(InformationSource.source_url == SOURCE_URL)
    )
    if source is None:
        source = InformationSource(
            source_url=SOURCE_URL,
            source_organisation=SOURCE_ORGANISATION,
            document_title=SOURCE_TITLE,
            source_document_type="official_html",
            notes="Official Anna University constituent-college directory.",
        )
        session.add(source)
        session.flush()
    return source


def ingest_constituent_colleges(
    *,
    fetcher=fetch_constituent_page,
    database_instance=database,
    collected_on: date | None = None,
) -> ImportReport:
    collection_date = collected_on or date.today()
    job_id: int | None = None
    source_id: int | None = None
    with database_instance.session() as session:
        with session.begin():
            source = _get_or_create_source(session)
            source_id = source.id
            job = DataImportJob(
                source=source,
                status="running",
                started_at=datetime.now(timezone.utc),
            )
            session.add(job)
            session.flush()
            job_id = job.id

    try:
        payload = fetcher()
        if payload.mime_type != "text/html":
            raise ValueError("The official source did not return HTML.")
        colleges = parse_constituent_colleges(payload.content, payload.charset)
        source_hash = hashlib.sha256(payload.content).hexdigest()

        with database_instance.session() as session:
            with session.begin():
                source = session.get(InformationSource, source_id)
                job = session.get(DataImportJob, job_id)
                category = session.scalar(
                    select(InstitutionCategory).where(
                        InstitutionCategory.code == "engineering"
                    )
                )
                institution_type = session.scalar(
                    select(InstitutionType).where(InstitutionType.code == "unknown")
                )
                if source is None or job is None or category is None or institution_type is None:
                    raise RuntimeError("Required source or lookup records are missing.")

                source_document = session.scalar(
                    select(SourceDocument).where(
                        SourceDocument.source_id == source.id,
                        SourceDocument.sha256 == source_hash,
                    )
                )
                if source_document is None:
                    session.add(SourceDocument(
                        source=source,
                        title=SOURCE_TITLE,
                        storage_uri=SOURCE_URL,
                        sha256=source_hash,
                        mime_type=payload.mime_type,
                        collected_on=collection_date,
                    ))

                rows_created = 0
                duplicates_skipped = 0
                for college in colleges:
                    existing = session.scalar(
                        select(Institution.id).where(
                            Institution.official_name == college.official_name,
                            Institution.category_id == category.id,
                        )
                    )
                    if existing is not None:
                        duplicates_skipped += 1
                        continue
                    provenance = RecordProvenance(
                        source=source,
                        collection_date=collection_date,
                        verification_status="pending",
                        notes=(
                            "Imported from the official constituent-college directory; "
                            "other institution details have not been independently verified."
                        ),
                    )
                    session.add(Institution(
                        official_name=college.official_name,
                        official_website=college.official_website,
                        category=category,
                        institution_type=institution_type,
                        operational_status="unknown",
                        provenance=provenance,
                    ))
                    rows_created += 1

                job.status = "completed"
                job.completed_at = datetime.now(timezone.utc)
                job.rows_read = len(colleges)
                job.rows_created = rows_created
                job.rows_rejected = 0
        return ImportReport(
            job_id=job_id,
            rows_read=len(colleges),
            rows_created=rows_created,
            duplicates_skipped=duplicates_skipped,
        )
    except (OSError, PermissionError, SQLAlchemyError, UnicodeError, ValueError, RuntimeError) as error:
        LOGGER.error("Anna University import failed (%s).", type(error).__name__)
        with database_instance.session() as session:
            with session.begin():
                job = session.get(DataImportJob, job_id)
                if job is not None:
                    job.status = "failed"
                    job.completed_at = datetime.now(timezone.utc)
                    job.error_summary = f"{type(error).__name__}; details omitted"
        raise


if __name__ == "__main__":
    result = ingest_constituent_colleges()
    print(
        f"Import job {result.job_id}: read {result.rows_read}, "
        f"created {result.rows_created}, skipped duplicates {result.duplicates_skipped}."
    )
