import unittest

from ai_service import extract_document_text, split_into_chunks


class DocumentExtractionTests(unittest.TestCase):
    def test_html_extraction_ignores_script_and_style(self):
        raw = (
            b"<html><head><style>hidden css</style><script>hidden js</script></head>"
            b"<body><h1>Admission Prospectus</h1><p>" + b"Official admission details. " * 8
            + b"</p></body></html>"
        )
        text = extract_document_text("prospectus.html", raw, "text/html")
        self.assertIn("Admission Prospectus", text)
        self.assertNotIn("hidden css", text)
        self.assertNotIn("hidden js", text)

    def test_csv_extraction_preserves_rows_and_columns(self):
        raw = b"Course,Duration\nB.E. Computer Science,4 years\n"
        text = extract_document_text("courses.csv", raw, "text/csv")
        self.assertIn("B.E. Computer Science", text)
        self.assertIn("4 years", text)

    def test_chunking_covers_long_text_and_overlaps(self):
        source = "Admission details. " * 250
        chunks = split_into_chunks(source)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(chunks))
        self.assertIn(chunks[0][-100:], chunks[1])


if __name__ == "__main__":
    unittest.main()
