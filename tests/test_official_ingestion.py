import unittest
from datetime import date

from sqlalchemy import select

from database import create_database
from ingestion.anna_university import (
    SOURCE_URL,
    SourcePayload,
    ingest_constituent_colleges,
    parse_constituent_colleges,
)
from models import (
    Base,
    DataImportJob,
    InformationSource,
    Institution,
    InstitutionCategory,
    InstitutionType,
    SourceDocument,
)


SOURCE_HTML = b"""
<html><body><table>
<tr><th>S.No.</th><th>Constituent College Name</th></tr>
<tr><td>1.</td><td><a href="https://first.example.edu/">First Engineering College</a></td></tr>
<tr><td>2.</td><td><a href="https://second.example.edu/">Second Engineering College</a></td></tr>
</table></body></html>
"""


class OfficialIngestionTests(unittest.TestCase):
    def setUp(self):
        self.database = create_database("sqlite://")
        Base.metadata.create_all(self.database.engine)
        with self.database.session() as session:
            session.add_all([
                InstitutionCategory(code="engineering", name="Engineering"),
                InstitutionType(code="unknown", name="Unknown"),
            ])
            session.commit()

    def tearDown(self):
        self.database.dispose()

    def test_parser_extracts_only_numbered_official_directory_rows(self):
        colleges = parse_constituent_colleges(SOURCE_HTML)
        self.assertEqual(
            [(college.official_name, college.official_website) for college in colleges],
            [
                ("First Engineering College", "https://first.example.edu/"),
                ("Second Engineering College", "https://second.example.edu/"),
            ],
        )
        with self.assertRaisesRegex(ValueError, "table was not recognized"):
            parse_constituent_colleges(b"<html><body>No directory table</body></html>")

    def test_ingestion_is_idempotent_and_preserves_pending_provenance(self):
        fetcher = lambda: SourcePayload(SOURCE_HTML, "text/html")
        first = ingest_constituent_colleges(
            fetcher=fetcher, database_instance=self.database, collected_on=date(2026, 11, 19)
        )
        second = ingest_constituent_colleges(
            fetcher=fetcher, database_instance=self.database, collected_on=date(2026, 11, 19)
        )

        with self.database.session() as session:
            institutions = session.scalars(
                select(Institution).order_by(Institution.official_name)
            ).all()
            sources = session.scalars(select(InformationSource)).all()
            source_documents = session.scalars(select(SourceDocument)).all()
            jobs = session.scalars(select(DataImportJob).order_by(DataImportJob.id)).all()

            self.assertEqual(len(institutions), 2)
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0].source_url, SOURCE_URL)
            self.assertEqual(len(source_documents), 1)
            self.assertEqual(len(source_documents[0].sha256), 64)
            self.assertEqual([job.status for job in jobs], ["completed", "completed"])
            self.assertEqual([job.rows_created for job in jobs], [2, 0])
            self.assertEqual(
                [item.provenance.verification_status for item in institutions],
                ["pending", "pending"],
            )
            self.assertTrue(all(item.district is None for item in institutions))
            self.assertTrue(all(item.establishment_year is None for item in institutions))
            self.assertEqual((first.rows_created, second.duplicates_skipped), (2, 2))


if __name__ == "__main__":
    unittest.main()
