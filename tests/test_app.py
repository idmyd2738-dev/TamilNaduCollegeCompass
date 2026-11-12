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
            "/student/register", "/admin/login", "/health",
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
            with self.client.session_transaction() as session:
                session["collegehub_demo_admin"] = True
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
