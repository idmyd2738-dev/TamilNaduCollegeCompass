import unittest

from ingestion.tngasa_2026 import parse_tngasa_text


class TNGASAParserTests(unittest.TestCase):
    def test_parser_extracts_official_college_rows_without_inventing_fields(self):
        rows = []
        for number in range(1, 102):
            code = 1011000 + number
            rows.append(
                f"Sl.No {number} Region Chennai District Chennai College Code {code} "
                f"College Name Government Arts and Science College {number} "
                "2025 Admit% 87.67 NAAC Grade A+ NIRF Rank 15 "
                "Number of seats available for Male Students 150 "
                "Number of seats available for Female Students Nil"
            )
        records = parse_tngasa_text("\n".join(rows))
        self.assertEqual(len(records), 101)
        self.assertEqual(records[0].college_code, "1011001")
        self.assertEqual(records[0].district, "Chennai")
        self.assertEqual(records[0].name, "Government Arts and Science College 1")
        self.assertEqual(records[0].admit_percent_2025, "87.67")
        self.assertEqual(records[0].naac_grade, "A+")
        self.assertEqual(records[0].male_seats, "150")
        self.assertIsNone(records[0].female_seats)


if __name__ == "__main__":
    unittest.main()
