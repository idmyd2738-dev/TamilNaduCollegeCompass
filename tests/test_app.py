import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import app as app_module
from app import app
from init_db import initialize_database

class PrototypeTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_pages(self):
        for path in [
            "/", "/about", "/chat", "/college", "/college/engineering",
            "/college/agriculture", "/college/medical", "/college/arts-science",
            "/colleges", "/colleges/1", "/compare", "/login", "/student/login",
            "/student/register", "/admin/login", "/health", "/recommendations", "/cutoffs",
        ]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_stream_filter(self):
        response = self.client.get("/colleges?stream=engineering")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Engineering", response.data)

    def test_search(self):
        response = self.client.get("/colleges?q=Chennai")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Chennai", response.data)

    def test_district_filter_and_course_information(self):
        response = self.client.get("/colleges?district=Erode")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Sample Institute of Rural Studies", response.data)
        self.assertNotIn(b"Demo Institute of Technology", response.data)

    def test_listing_includes_available_courses(self):
        response = self.client.get("/colleges")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Computer Science and Engineering", response.data)

    def test_collegehub_branding(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"CollegeHub", response.data)

    def test_compare_two_colleges(self):
        response = self.client.get("/compare?ids=1,2")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Demo Institute of Technology", response.data)
        self.assertIn(b"Sample School of Engineering", response.data)
        self.assertIn(b"Not provided", response.data)

    def test_recommendations_explain_matches_and_reject_invalid_budget(self):
        with closing(app_module.get_db()) as connection:
            preference = connection.execute(
                """SELECT cr.name, c.district FROM courses cr
                   JOIN colleges c ON c.id=cr.college_id LIMIT 1"""
            ).fetchone()
        response = self.client.get("/recommendations", query_string={
            "course": preference["name"], "district": preference["district"],
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"100%", response.data)
        self.assertIn(b"not admission probability", response.data.lower())
        self.assertEqual(self.client.get("/recommendations?max_annual_fee=NaN").status_code, 400)
        self.assertEqual(self.client.get("/recommendations?max_annual_fee=-1").status_code, 400)

    def test_cutoff_analytics_does_not_invent_data(self):
        response = self.client.get("/cutoffs")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No verified numeric cutoff records", response.data)
        self.assertIn(b"No trend is fabricated", response.data)
        self.assertEqual(self.client.get("/cutoffs?college=invalid").status_code, 400)

    def test_cutoff_chart_includes_only_sourced_verified_numeric_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = os.path.join(temp_dir, "collegehub.db")
            shutil.copy2(app_module.DB_PATH, database)
            original_path = app_module.DB_PATH
            app_module.DB_PATH = Path(database)
            try:
                with closing(sqlite3.connect(database)) as connection:
                    source_id = connection.execute(
                        """INSERT INTO information_sources
                           (college_id,source_name,source_url,academic_year,last_verified,verification_status)
                           VALUES (1,'Official source','https://example.test/cutoffs','2025-26',
                                   '2026-01-15','verified')"""
                    ).lastrowid
                    course_id = connection.execute(
                        "SELECT id FROM courses WHERE college_id=1 LIMIT 1"
                    ).fetchone()[0]
                    connection.execute(
                        """INSERT INTO cutoff_records
                           (college_id,course_id,academic_year,cutoff_value,source_id,last_verified,verification_status)
                           VALUES (1,?,'2025-26','184.25',?,'2026-01-15','verified')""",
                        (course_id, source_id),
                    )
                    connection.execute(
                        """INSERT INTO cutoff_records
                           (college_id,course_id,academic_year,cutoff_value,verification_status)
                           VALUES (1,?,'2025-26','190.00','information_not_verified')""",
                        (course_id,),
                    )
                    connection.commit()
                response = self.client.get("/cutoffs?college=1&year=2025-26")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data.count(b'class="cutoff-bar-row"'), 1)
                self.assertIn(b"184.25", response.data)
                self.assertIn(b"190.00", response.data)
                self.assertIn(b"https://example.test/cutoffs", response.data)
                self.assertIn(b"Excluded from verified analytics", response.data)
            finally:
                app_module.DB_PATH = original_path

    def test_directory_filters_by_facility_from_database(self):
        with closing(app_module.get_db()) as connection:
            facility = connection.execute(
                "SELECT label FROM facilities ORDER BY label LIMIT 1"
            ).fetchone()["label"]
            matching_college = connection.execute(
                "SELECT college_id FROM facilities WHERE label=? LIMIT 1", (facility,)
            ).fetchone()["college_id"]
            college_name = connection.execute(
                "SELECT name FROM colleges WHERE id=?", (matching_college,)
            ).fetchone()["name"]
        response = self.client.get("/colleges", query_string={"facility": facility})
        self.assertEqual(response.status_code, 200)
        self.assertIn(college_name.encode(), response.data)

    def test_fee_filters_require_verified_annual_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = os.path.join(temp_dir, "collegehub.db")
            shutil.copy2(app_module.DB_PATH, database)
            original_path = app_module.DB_PATH
            app_module.DB_PATH = Path(database)
            try:
                with closing(sqlite3.connect(database)) as connection:
                    connection.execute(
                        """INSERT INTO fee_records
                           (college_id,academic_year,fee_type,amount,verification_status)
                           VALUES (1,'2025-26','Annual tuition',25000,'information_not_verified')"""
                    )
                    connection.commit()
                response = self.client.get("/colleges?fee_range=under-50000")
                self.assertIn(b"0 sample colleges", response.data)
                with closing(sqlite3.connect(database)) as connection:
                    connection.execute(
                        "UPDATE fee_records SET verification_status='verified' WHERE college_id=1"
                    )
                    connection.commit()
                response = self.client.get("/colleges?fee_range=under-50000&sort=fees")
                self.assertIn(b"Demo Institute of Technology", response.data)
                comparison = self.client.get("/compare?ids=1,2")
                self.assertIn(b"verified annual fee", comparison.data)
                self.assertIn(b"25000.00", comparison.data)
            finally:
                app_module.DB_PATH = original_path

    def test_student_demo_registration_does_not_store_password(self):
        response = self.client.post("/student/register", data={
            "name": "Demo Student",
            "email": "student@example.test",
            "password": "not-a-real-password",
            "confirm_password": "not-a-real-password",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/student/dashboard").status_code, 200)
        with self.client.session_transaction() as session:
            self.assertEqual(session["collegehub_demo_student"]["email"], "student@example.test")
            self.assertNotIn("password", session["collegehub_demo_student"])

    def test_migration_is_idempotent_and_preserves_existing_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = os.path.join(temp_dir, "collegehub.db")
            shutil.copy2(app_module.DB_PATH, database)
            initialize_database(database)
            initialize_database(database)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM colleges").fetchone()[0], 8)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM courses").fetchone()[0], 10)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM guidance_records").fetchone()[0], 11)
                facility_columns = {row[1] for row in connection.execute("PRAGMA table_info(facilities)")}
                self.assertIn("verification_status", facility_columns)
                faq_columns = {row[1] for row in connection.execute("PRAGMA table_info(faqs)")}
                self.assertIn("last_verified", faq_columns)
                course_columns = {row[1] for row in connection.execute("PRAGMA table_info(courses)")}
                self.assertIn("source_id", course_columns)
                self.assertIn("last_verified", course_columns)
                fee_columns = {row[1] for row in connection.execute("PRAGMA table_info(fee_records)")}
                self.assertIn("last_verified", fee_columns)

    def test_admin_course_crud_uses_a_temporary_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = os.path.join(temp_dir, "collegehub.db")
            shutil.copy2(app_module.DB_PATH, database)
            original_path = app_module.DB_PATH
            app_module.DB_PATH = Path(database)
            try:
                with self.client.session_transaction() as session:
                    session["collegehub_demo_admin"] = True
                response = self.client.post("/admin/courses", data={
                    "college_id": "1", "name": "Demo Course", "level": "B.E.", "duration": "4 years",
                })
                self.assertEqual(response.status_code, 302)
                with closing(sqlite3.connect(database)) as connection:
                    course_id = connection.execute(
                        "SELECT id FROM courses WHERE name='Demo Course'"
                    ).fetchone()[0]
                response = self.client.post(f"/admin/courses/{course_id}/update", data={
                    "name": "Updated Demo Course", "level": "B.E.", "duration": "4 years",
                })
                self.assertEqual(response.status_code, 302)
                response = self.client.post(f"/admin/records/courses/{course_id}/verify", data={
                    "verification_status": "verified", "source_name": "Official source",
                    "source_url": "https://example.test/course", "academic_year": "2026-27",
                    "last_verified": "2026-11-12",
                })
                self.assertEqual(response.status_code, 302)
                with closing(sqlite3.connect(database)) as connection:
                    self.assertEqual(connection.execute(
                        "SELECT verification_status,last_verified FROM courses WHERE id=?", (course_id,)
                    ).fetchone(), ("verified", "2026-11-12"))
                detail = self.client.get("/colleges/1")
                self.assertIn(b"Official source", detail.data)
                self.assertIn(b"2026-27", detail.data)
                response = self.client.post(f"/admin/courses/{course_id}/delete")
                self.assertEqual(response.status_code, 302)
                with closing(sqlite3.connect(database)) as connection:
                    self.assertIsNone(connection.execute(
                        "SELECT id FROM courses WHERE id=?", (course_id,)
                    ).fetchone())
                    self.assertIsNone(connection.execute(
                        "SELECT id FROM verification_records WHERE record_type='courses' AND record_id=?",
                        (course_id,),
                    ).fetchone())
            finally:
                app_module.DB_PATH = original_path

    def test_verified_guidance_requires_source_and_year(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = os.path.join(temp_dir, "collegehub.db")
            shutil.copy2(app_module.DB_PATH, database)
            original_path = app_module.DB_PATH
            app_module.DB_PATH = database
            try:
                with self.client.session_transaction() as session:
                    session["collegehub_demo_admin"] = True
                with closing(sqlite3.connect(database)) as connection:
                    guidance_id = connection.execute(
                        "SELECT id FROM guidance_records LIMIT 1"
                    ).fetchone()[0]
                response = self.client.post(
                    f"/admin/guidance/{guidance_id}/verify",
                    data={"verification_status": "verified"},
                )
                self.assertEqual(response.status_code, 400)
                response = self.client.post(
                    f"/admin/guidance/{guidance_id}/verify",
                    data={
                        "heading": "Verified guidance",
                        "content": "Guidance reviewed against the cited source.",
                        "verification_status": "verified",
                        "source_name": "Official source",
                        "source_url": "https://example.test/",
                        "academic_year": "2026-27",
                        "last_verified": "2026-11-12",
                    },
                )
                self.assertEqual(response.status_code, 302)
            finally:
                app_module.DB_PATH = original_path

    def test_fee_records_are_crud_and_verification_gated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = os.path.join(temp_dir, "collegehub.db")
            shutil.copy2(app_module.DB_PATH, database)
            original_path = app_module.DB_PATH
            app_module.DB_PATH = database
            try:
                with self.client.session_transaction() as session:
                    session["collegehub_demo_admin"] = True
                response = self.client.post("/admin/records/fees", data={
                    "college_id": "1", "course_id": "1", "academic_year": "2026-27",
                    "fee_type": "Demo tuition", "amount": "1250",
                })
                self.assertEqual(response.status_code, 302)
                with closing(sqlite3.connect(database)) as connection:
                    fee_id, status = connection.execute(
                        "SELECT id,verification_status FROM fee_records WHERE fee_type='Demo tuition'"
                    ).fetchone()
                self.assertEqual(status, "information_not_verified")
                response = self.client.post(f"/admin/records/fees/{fee_id}/verify", data={
                    "verification_status": "verified",
                })
                self.assertEqual(response.status_code, 400)
                response = self.client.post(f"/admin/records/fees/{fee_id}/verify", data={
                    "verification_status": "verified", "source_name": "Official source",
                    "source_url": "https://example.test/fees", "academic_year": "2026-27",
                    "last_verified": "2026-11-12",
                })
                self.assertEqual(response.status_code, 302)
                with closing(sqlite3.connect(database)) as connection:
                    self.assertEqual(connection.execute(
                        "SELECT verification_status FROM fee_records WHERE id=?", (fee_id,)
                    ).fetchone()[0], "verified")
                self.assertEqual(self.client.post(f"/admin/records/fees/{fee_id}/delete").status_code, 302)
            finally:
                app_module.DB_PATH = original_path

    def test_admin_writes_are_disabled_for_vercel(self):
        previous = os.environ.get("VERCEL")
        os.environ["VERCEL"] = "1"
        try:
            self.assertEqual(self.client.get("/admin/login").status_code, 503)
            with self.client.session_transaction() as session:
                session["collegehub_demo_admin"] = True
            self.assertEqual(self.client.get("/admin").status_code, 503)
            response = self.client.post("/admin/colleges", data={
                "name": "Blocked sample", "stream_id": "1", "city": "Nowhere",
                "district": "Nowhere",
            })
            self.assertEqual(response.status_code, 503)
        finally:
            if previous is None:
                os.environ.pop("VERCEL", None)
            else:
                os.environ["VERCEL"] = previous

    def test_demo_chat(self):
        response = self.client.post("/demo-chat", json={"message":"Tell me about engineering"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("engineering", response.get_json()["answer"].lower())

    def test_chatbot_includes_official_source_when_available(self):
        response = self.client.post("/demo-chat", json={"message": "TNEA counselling"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["source_url"], "https://www.tneaonline.org/")

    def test_admin_dashboard_renders_management_tabs(self):
        self.client.post("/admin/login", data={})
        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Fees &amp; campus", response.data)
        self.assertIn(b"Manage streams", response.data)

if __name__ == "__main__":
    unittest.main()
