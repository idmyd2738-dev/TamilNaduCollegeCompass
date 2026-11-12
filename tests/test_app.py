import unittest
from app import app

class PrototypeTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_pages(self):
        for path in ["/", "/about", "/chat", "/colleges", "/colleges/1", "/health"]:
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
        self.assertNotIn(b"College Compass", response.data)

    def test_demo_chat(self):
        response = self.client.post("/demo-chat", json={"message":"Tell me about engineering"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("engineering", response.get_json()["answer"].lower())

if __name__ == "__main__":
    unittest.main()
