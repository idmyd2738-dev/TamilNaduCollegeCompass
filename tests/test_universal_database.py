import os
import re
import shutil
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import make_url
from werkzeug.security import generate_password_hash

import app as app_module
from database import create_database, resolve_database_url
from models import (
    AcademicYear,
    AdmissionAuthority,
    AdmissionCycle,
    AdmissionRecord,
    AdmissionRoute,
    Affiliation,
    Base,
    Campus,
    CounsellingRound,
    Department,
    FeeComponent,
    FeeStructure,
    InformationSource,
    Institution,
    InstitutionCategory,
    InstitutionType,
    PlacementReport,
    Program,
    RecordProvenance,
    University,
    VerificationRecord,
)
from services import VerificationService


class UniversalDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.database = create_database("sqlite://")
        Base.metadata.create_all(self.database.engine)
        self.previous_database = app_module.app.config.get("UNIVERSAL_DATABASE")
        app_module.app.config["UNIVERSAL_DATABASE"] = self.database
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        self.session = self.database.session()

        self.category = InstitutionCategory(code="engineering", name="Engineering")
        self.institution_type = InstitutionType(code="government", name="Government")
        self.academic_year = AcademicYear(label="2025-26")
        self.source = InformationSource(
            source_url="https://example.test/collegehub",
            source_organisation="Example University",
            document_title="Published information",
        )
        self.session.add_all([
            self.category, self.institution_type, self.academic_year, self.source,
        ])
        self.session.flush()

        self.institution_provenance = self.provenance()
        self.institution = Institution(
            official_name="Test Engineering College",
            category=self.category,
            institution_type=self.institution_type,
            district="Chennai",
            city="Chennai",
            official_website="https://example.test",
            provenance=self.institution_provenance,
        )
        self.campus = Campus(
            name="Main Campus",
            city="Chennai",
            district="Chennai",
            is_main_campus=True,
            institution=self.institution,
            provenance=self.provenance(),
        )
        self.department = Department(
            name="Computer Engineering",
            code="CE",
            institution=self.institution,
            campus=self.campus,
            provenance=self.provenance(),
        )
        self.program = Program(
            name="Computer Engineering",
            award="B.E.",
            level="undergraduate",
            institution=self.institution,
            category=self.category,
            department=self.department,
            provenance=self.provenance(),
        )
        self.session.add_all([self.institution, self.campus, self.department, self.program])
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.database.dispose()
        if self.previous_database is not None:
            app_module.app.config["UNIVERSAL_DATABASE"] = self.previous_database

    def provenance(self, *, status="unverified"):
        return RecordProvenance(
            source=self.source,
            academic_year=self.academic_year,
            collection_date=date(2026, 1, 15),
            verification_status=status,
        )

    def test_connection_models_relationships_and_sqlite_foreign_keys(self):
        with self.database.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("SELECT 1").scalar_one(), 1)
            self.assertEqual(
                connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one(), 1
            )
        institution = self.session.scalar(
            select(Institution).where(Institution.id == self.institution.id)
        )
        self.assertEqual(institution.category.code, "engineering")
        self.assertEqual(institution.programs[0].department.name, "Computer Engineering")
        self.assertEqual(institution.campuses[0].name, "Main Campus")

    def test_admission_records_keep_distinct_measurement_types_and_units(self):
        authority = AdmissionAuthority(
            code="TESTAUTH",
            name="Test Admissions Authority",
            provenance=self.provenance(),
        )
        cycle = AdmissionCycle(
            academic_year=self.academic_year,
            name="2025 admissions",
            provenance=self.provenance(),
        )
        route = AdmissionRoute(
            admission_cycle=cycle,
            institution=self.institution,
            authority=authority,
            name="Merit route",
            route_type="merit",
            provenance=self.provenance(),
        )
        round_record = CounsellingRound(
            admission_route=route,
            round_number=1,
            name="Round 1",
            provenance=self.provenance(),
        )
        records = [
            AdmissionRecord(
                institution=self.institution,
                program=self.program,
                academic_year=self.academic_year,
                admission_authority=authority,
                admission_route=route,
                counselling_round=round_record,
                measurement_type="rank",
                measurement_value=Decimal("1250"),
                measurement_unit="rank",
                provenance=self.provenance(),
            ),
            AdmissionRecord(
                institution=self.institution,
                program=self.program,
                academic_year=self.academic_year,
                measurement_type="percentage",
                measurement_value=Decimal("92.5"),
                measurement_unit="percent",
                provenance=self.provenance(),
            ),
        ]
        self.session.add_all([authority, cycle, route, round_record, *records])
        self.session.commit()

        response = self.client.get(
            f"/api/institutions/{self.institution.id}/admissions"
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["items"]
        self.assertEqual(
            [(item["measurement_type"], item["measurement_unit"]) for item in payload],
            [("rank", "rank"), ("percentage", "percent")],
        )

    def test_fee_records_and_provenance_are_exposed_without_verification_inference(self):
        structure = FeeStructure(
            institution=self.institution,
            program=self.program,
            academic_year=self.academic_year,
            currency="INR",
            provenance=self.provenance(),
            components=[
                FeeComponent(
                    component_type="tuition",
                    name="Tuition",
                    amount=Decimal("42500.00"),
                    provenance=self.provenance(),
                )
            ],
        )
        self.session.add(structure)
        self.session.commit()

        response = self.client.get(f"/api/institutions/{self.institution.id}/fees")
        self.assertEqual(response.status_code, 200)
        fee = response.get_json()["items"][0]
        self.assertEqual(fee["components"][0]["amount"], "42500.00")
        self.assertEqual(fee["provenance"]["verification_status"], "unverified")
        self.assertEqual(fee["components"][0]["provenance"]["source"]["url"],
                         "https://example.test/collegehub")

    def test_institution_program_and_recommendation_api_queries(self):
        university_institution = Institution(
            official_name="Test State University",
            category=self.category,
            institution_type=self.institution_type,
            provenance=self.provenance(),
        )
        university = University(
            institution=university_institution,
            establishment_act="Test University Act",
            provenance=self.provenance(),
        )
        self.session.add(Affiliation(
            institution=self.institution,
            university=university,
            valid_from_year=self.academic_year,
            status="active",
            provenance=self.provenance(),
        ))
        self.session.commit()
        self.assertEqual(
            self.client.get("/api/institutions?category=engineering").status_code, 200
        )
        profile = self.client.get(f"/api/institutions/{self.institution.id}")
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.get_json()["item"]["programs"][0]["name"],
                         "Computer Engineering")
        self.assertEqual(
            profile.get_json()["item"]["affiliations"][0]["university_name"],
            "Test State University",
        )
        self.assertEqual(
            profile.get_json()["item"]["departments"][0]["verification"]["source"]["url"],
            "https://example.test/collegehub",
        )
        programs = self.client.get("/api/programs?institution_id=1")
        self.assertEqual(programs.status_code, 200)
        self.assertEqual(programs.get_json()["items"][0]["category"], "engineering")
        comparison = self.client.get(
            f"/api/institutions/compare?ids={self.institution.id}"
        )
        self.assertEqual(comparison.status_code, 200)
        recommendations = self.client.get(
            "/api/institutions/recommendations?district=Chennai&program=Computer"
        )
        self.assertEqual(
            recommendations.get_json()["items"][0]["official_name"],
            "Test Engineering College",
        )
        self.assertEqual(
            self.client.get(
                "/api/institutions?affiliation=Test+State+University"
            ).get_json()["total"],
            1,
        )

    def test_verification_history_and_invalid_api_input(self):
        self.session.add(VerificationRecord(
            provenance=self.institution_provenance,
            source=self.source,
            verification_status="pending",
            reviewer="reviewer@example.test",
            verified_at=datetime(2026, 1, 16, tzinfo=timezone.utc),
        ))
        self.session.commit()
        response = self.client.get(
            f"/api/provenance/{self.institution_provenance.id}/verification-history"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["items"][0]["verification_status"], "pending"
        )
        self.assertEqual(self.client.get("/api/institutions?limit=0").status_code, 400)
        self.assertEqual(self.client.get("/api/programs?institution_id=bad").status_code, 400)
        self.assertEqual(self.client.get("/api/institutions/compare?ids=x").status_code, 400)

    def test_database_mode_public_pages_do_not_fall_back_to_sample_sqlite(self):
        previous_testing = app_module.app.config["TESTING"]
        previous_demo_mode = os.environ.pop("COLLEGEHUB_DEMO_MODE", None)
        app_module.app.config["TESTING"] = False
        try:
            response = self.client.get("/colleges")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Test Engineering College", response.data)
            self.assertNotIn(b"Demo Institute of Technology", response.data)

            response = self.client.get("/colleges?q=missing-institution")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"No matching institution records", response.data)
            self.assertNotIn(b"Sample School of Engineering", response.data)

            self.assertEqual(self.client.get("/chat").status_code, 200)
            self.assertIn(b"not yet available", self.client.get("/chat").data)
            self.assertEqual(
                self.client.post("/demo-chat", json={"message": "TNEA"}).status_code,
                404,
            )
            self.assertEqual(self.client.get("/admin/login").status_code, 503)
            self.assertEqual(self.client.get("/student/register").status_code, 503)
        finally:
            app_module.app.config["TESTING"] = previous_testing
            if previous_demo_mode is not None:
                os.environ["COLLEGEHUB_DEMO_MODE"] = previous_demo_mode

    def test_verification_service_requires_evidence_to_mark_records_verified(self):
        verification = VerificationService(self.session)
        with self.assertRaisesRegex(ValueError, "source and verification timestamp"):
            verification.record_review(
                self.institution_provenance.id,
                "verified",
                reviewer="reviewer@example.test",
            )
        record = verification.record_review(
            self.institution_provenance.id,
            "verified",
            reviewer="reviewer@example.test",
            verified_at=datetime(2026, 1, 16, tzinfo=timezone.utc),
        )
        self.session.commit()
        self.assertEqual(record.verification_status, "verified")
        self.assertEqual(
            record.provenance.verification_status,
            "verified",
        )

    def test_database_admin_login_csrf_dashboard_and_record_review(self):
        previous_testing = app_module.app.config["TESTING"]
        previous_secret_configured = app_module.app.config.get(
            "COLLEGEHUB_SECRET_CONFIGURED"
        )
        app_module.app.config["TESTING"] = False
        app_module.app.config["COLLEGEHUB_SECRET_CONFIGURED"] = True
        environment = {
            "COLLEGEHUB_ADMIN_PASSWORD_HASH": generate_password_hash(
                "test-only-admin-password"
            ),
            "COLLEGEHUB_DEMO_MODE": "",
            "COLLEGEHUB_READ_ONLY": "",
            "VERCEL": "",
            "VERCEL_ENV": "",
        }
        try:
            with patch.dict(os.environ, environment, clear=False):
                login_page = self.client.get("/admin/login")
                self.assertEqual(login_page.status_code, 200)
                csrf_token = re.search(
                    r'name="csrf_token" value="([^"]+)"',
                    login_page.get_data(as_text=True),
                ).group(1)
                self.assertEqual(
                    self.client.post(
                        "/admin/login",
                        data={"csrf_token": "invalid", "password": "test-only-admin-password"},
                    ).status_code,
                    400,
                )

                login_page = self.client.get("/admin/login")
                csrf_token = re.search(
                    r'name="csrf_token" value="([^"]+)"',
                    login_page.get_data(as_text=True),
                ).group(1)
                response = self.client.post(
                    "/admin/login",
                    data={
                        "csrf_token": csrf_token,
                        "password": "test-only-admin-password",
                    },
                )
                self.assertEqual(response.status_code, 302)

                dashboard = self.client.get("/admin")
                self.assertEqual(dashboard.status_code, 200)
                self.assertIn(b"Test Engineering College", dashboard.data)
                with self.client.session_transaction() as browser_session:
                    admin_csrf = browser_session["collegehub_admin_csrf"]

                response = self.client.post(
                    f"/admin/provenance/{self.institution_provenance.id}/review",
                    data={
                        "csrf_token": admin_csrf,
                        "verification_status": "verified",
                        "notes": "Reviewed in an isolated test database.",
                    },
                )
                self.assertEqual(response.status_code, 302)
                self.session.expire_all()
                reviewed_provenance = self.session.get(
                    RecordProvenance, self.institution_provenance.id
                )
                if reviewed_provenance is None:
                    self.fail("Reviewed provenance record was not persisted.")
                self.assertEqual(
                    reviewed_provenance.verification_status,
                    "verified",
                )
        finally:
            app_module.app.config["TESTING"] = previous_testing
            if previous_secret_configured is None:
                app_module.app.config.pop("COLLEGEHUB_SECRET_CONFIGURED", None)
            else:
                app_module.app.config["COLLEGEHUB_SECRET_CONFIGURED"] = (
                    previous_secret_configured
                )

    def test_placement_percentage_stays_unknown_when_required_counts_are_missing(self):
        incomplete = PlacementReport(
            institution=self.institution,
            reporting_year="2024-25",
            eligible_students=10,
            placed_students=None,
            provenance=self.provenance(),
        )
        complete = PlacementReport(
            institution=self.institution,
            reporting_year="2023-24",
            eligible_students=80,
            placed_students=60,
            provenance=self.provenance(),
        )
        self.assertIsNone(incomplete.placement_percentage)
        self.assertEqual(complete.placement_percentage, Decimal("75.00"))

    def test_foreign_keys_and_model_check_constraints_are_enforced(self):
        invalid_foreign_key_provenance = self.provenance()
        invalid_status_provenance = self.provenance()
        self.session.add_all([
            invalid_foreign_key_provenance,
            invalid_status_provenance,
        ])
        self.session.commit()

        invalid_rows = [
            {
                "official_name": "Invalid foreign key",
                "category_id": 999,
                "institution_type_id": self.institution_type.id,
                "provenance_id": invalid_foreign_key_provenance.id,
            },
            {
                "official_name": "Invalid status",
                "category_id": self.category.id,
                "institution_type_id": self.institution_type.id,
                "provenance_id": invalid_status_provenance.id,
                "operational_status": "not-a-status",
            },
        ]
        for values in invalid_rows:
            with self.subTest(values=values):
                db_session = self.database.session()
                try:
                    with self.assertRaises(IntegrityError):
                        db_session.execute(insert(Institution).values(**values))
                        db_session.commit()
                finally:
                    db_session.rollback()
                    db_session.close()


class AlembicMigrationTests(unittest.TestCase):
    def alembic_config(self, url):
        project_dir = Path(__file__).resolve().parents[1]
        config = Config(str(project_dir / "alembic.ini"))
        config.attributes["connection_url"] = url
        return config

    def test_sqlite_upgrade_seeds_lookups_and_downgrade(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "migration-test.sqlite3"
            url = resolve_database_url(f"sqlite:///{database_path.as_posix()}")
            config = self.alembic_config(url)
            command.upgrade(config, "head")
            command.check(config)

            engine = create_database(url).engine
            try:
                inspector = inspect(engine)
                self.assertIn("institutions", inspector.get_table_names())
                with engine.connect() as connection:
                    categories = set(connection.exec_driver_sql(
                        "SELECT code FROM institution_categories"
                    ).scalars())
                    types = set(connection.exec_driver_sql(
                        "SELECT code FROM institution_types"
                    ).scalars())
                self.assertEqual(
                    categories,
                    {"engineering", "medical", "agriculture", "arts", "science"},
                )
                self.assertEqual(
                    types,
                    {
                        "government", "government_aided", "private",
                        "deemed_university", "central_university", "state_university",
                        "unknown",
                    },
                )
            finally:
                engine.dispose()

            command.downgrade(config, "base")
            check_engine = create_database(url).engine
            try:
                self.assertNotIn("institutions", inspect(check_engine).get_table_names())
            finally:
                check_engine.dispose()

    def test_legacy_database_is_refused_without_changing_existing_records(self):
        project_dir = Path(__file__).resolve().parents[1]
        legacy_database = project_dir / "sample_colleges.db"
        with tempfile.TemporaryDirectory() as temp_dir:
            copied_database = Path(temp_dir) / "legacy.sqlite3"
            shutil.copy2(legacy_database, copied_database)
            url = resolve_database_url(f"sqlite:///{copied_database.as_posix()}")
            config = self.alembic_config(url)
            engine = create_database(url).engine
            try:
                with engine.connect() as connection:
                    initial_count = connection.exec_driver_sql(
                        "SELECT COUNT(*) FROM colleges"
                    ).scalar_one()
                with self.assertRaisesRegex(RuntimeError, "Refusing to apply"):
                    command.upgrade(config, "head")
                with engine.connect() as connection:
                    final_count = connection.exec_driver_sql(
                        "SELECT COUNT(*) FROM colleges"
                    ).scalar_one()
                    self.assertNotIn("institutions", inspect(connection).get_table_names())
                self.assertEqual(initial_count, final_count)
            finally:
                engine.dispose()


@unittest.skipUnless(
    os.environ.get("TEST_POSTGRESQL_DATABASE_URL"),
    "Set TEST_POSTGRESQL_DATABASE_URL to run PostgreSQL schema compatibility tests.",
)
class PostgreSQLCompatibilityTests(unittest.TestCase):
    def test_models_create_in_an_isolated_test_schema(self):
        from sqlalchemy import create_engine

        url = resolve_database_url(os.environ["TEST_POSTGRESQL_DATABASE_URL"])
        database_name = make_url(url).database or ""
        if not re.search(r"(^|[_-])(test|tests|pytest)([_-]|$)", database_name, re.I):
            self.fail(
                "TEST_POSTGRESQL_DATABASE_URL must target a dedicated database "
                "whose name contains test, tests, or pytest."
            )
        engine = create_engine(url, pool_pre_ping=True)
        schema_name = f"collegehub_test_{uuid4().hex}"
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')
                isolated_connection = connection.execution_options(
                    schema_translate_map={None: schema_name}
                )
                isolated_connection.exec_driver_sql(
                    "CREATE EXTENSION IF NOT EXISTS vector"
                )
                Base.metadata.create_all(isolated_connection)
                self.assertIn("institutions", inspect(isolated_connection).get_table_names())
                Base.metadata.drop_all(isolated_connection)
                connection.exec_driver_sql(f'DROP SCHEMA "{schema_name}"')
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
