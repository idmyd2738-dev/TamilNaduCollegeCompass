import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "sample_colleges.db"

COLLEGE_COLUMNS = {
    "category": "TEXT",
    "ownership": "TEXT",
    "official_website": "TEXT",
    "hostel_available": "INTEGER",
    "information_status": "TEXT NOT NULL DEFAULT 'information_not_verified'",
    "academic_year": "TEXT",
}

TABLES = (
    """
    CREATE TABLE IF NOT EXISTS academic_years (
        id INTEGER PRIMARY KEY,
        label TEXT NOT NULL UNIQUE,
        start_date TEXT,
        end_date TEXT,
        status TEXT NOT NULL DEFAULT 'information_not_verified'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS districts (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS information_sources (
        id INTEGER PRIMARY KEY,
        college_id INTEGER REFERENCES colleges(id) ON DELETE CASCADE,
        source_name TEXT NOT NULL,
        source_url TEXT,
        academic_year TEXT,
        last_verified TEXT,
        verification_status TEXT NOT NULL DEFAULT 'information_not_verified'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS verification_records (
        id INTEGER PRIMARY KEY,
        college_id INTEGER REFERENCES colleges(id) ON DELETE CASCADE,
        record_type TEXT NOT NULL,
        record_id INTEGER,
        source_id INTEGER REFERENCES information_sources(id) ON DELETE SET NULL,
        academic_year TEXT,
        last_verified TEXT,
        status TEXT NOT NULL DEFAULT 'information_not_verified',
        notes TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fee_records (
        id INTEGER PRIMARY KEY,
        college_id INTEGER NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
        course_id INTEGER REFERENCES courses(id) ON DELETE SET NULL,
        academic_year TEXT,
        fee_type TEXT,
        amount REAL,
        source_id INTEGER REFERENCES information_sources(id) ON DELETE SET NULL,
        last_verified TEXT,
        verification_status TEXT NOT NULL DEFAULT 'information_not_verified'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cutoff_records (
        id INTEGER PRIMARY KEY,
        college_id INTEGER NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
        course_id INTEGER REFERENCES courses(id) ON DELETE SET NULL,
        academic_year TEXT,
        quota TEXT,
        cutoff_value TEXT,
        source_id INTEGER REFERENCES information_sources(id) ON DELETE SET NULL,
        last_verified TEXT,
        verification_status TEXT NOT NULL DEFAULT 'information_not_verified'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hostel_information (
        id INTEGER PRIMARY KEY,
        college_id INTEGER NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
        details TEXT,
        academic_year TEXT,
        source_id INTEGER REFERENCES information_sources(id) ON DELETE SET NULL,
        last_verified TEXT,
        verification_status TEXT NOT NULL DEFAULT 'information_not_verified'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS guidance_records (
        id INTEGER PRIMARY KEY,
        stream_id INTEGER REFERENCES streams(id) ON DELETE CASCADE,
        category TEXT NOT NULL,
        heading TEXT NOT NULL,
        content TEXT NOT NULL,
        source_name TEXT,
        source_url TEXT,
        academic_year TEXT,
        last_verified TEXT,
        verification_status TEXT NOT NULL DEFAULT 'information_not_verified',
        UNIQUE(stream_id, category, heading)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS faqs (
        id INTEGER PRIMARY KEY,
        question TEXT NOT NULL UNIQUE,
        answer TEXT NOT NULL,
        source_name TEXT,
        source_url TEXT,
        verification_status TEXT NOT NULL DEFAULT 'information_not_verified'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS student_profiles (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS student_feedback (
        id INTEGER PRIMARY KEY,
        name TEXT,
        message TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
)

FACILITY_COLUMNS = {
    "academic_year": "TEXT",
    "source_id": "INTEGER REFERENCES information_sources(id) ON DELETE SET NULL",
    "last_verified": "TEXT",
    "verification_status": "TEXT NOT NULL DEFAULT 'information_not_verified'",
}

RECORD_METADATA_COLUMNS = {
    "fee_records": {"last_verified": "TEXT"},
    "cutoff_records": {"last_verified": "TEXT"},
    "hostel_information": {"last_verified": "TEXT"},
}

FAQ_COLUMNS = {
    "academic_year": "TEXT",
    "last_verified": "TEXT",
}

COURSE_COLUMNS = {
    "academic_year": "TEXT",
    "source_id": "INTEGER REFERENCES information_sources(id) ON DELETE SET NULL",
    "last_verified": "TEXT",
    "verification_status": "TEXT NOT NULL DEFAULT 'information_not_verified'",
}

GUIDANCE = (
    ("engineering", "counselling", "TNEA counselling", "General stages to review include registration, certificate verification, rank list, choice filling, seat allotment and admission confirmation. Dates and rules change; check the current official notice.", "TNEA", "https://www.tneaonline.org/"),
    ("engineering", "entrance_examinations", "Entrance examinations", "Examination and selection requirements depend on the admission route. Confirm current requirements through the official counselling authority.", "TNEA", "https://www.tneaonline.org/"),
    ("engineering", "eligibility", "Eligibility", "Eligibility rules can change by admission year and programme. Check the current official notification before applying.", "TNEA", "https://www.tneaonline.org/"),
    ("agriculture", "overview", "Agriculture programmes", "Agriculture, horticulture and agricultural engineering are programme areas to explore. Availability depends on the institution and current admission notice.", "Tamil Nadu Agricultural University", "https://tnau.ac.in/"),
    ("agriculture", "counselling", "Agriculture admissions", "Review the current admission information from Tamil Nadu Agricultural University and Annamalai University. This prototype does not publish current dates or eligibility decisions.", "Tamil Nadu Agricultural University", "https://tnau.ac.in/"),
    ("agriculture", "fisheries", "Fisheries admissions", "Fisheries admissions are separate from the agriculture guidance shown here. Consult the responsible institution and current official notice; no fisheries-specific source is listed in this demo.", None, None),
    ("medical", "entrance_examinations", "NEET-UG", "Medical admission processes may involve NEET-UG and applicable counselling. Check current notices for the specific programme and quota.", "Tamil Nadu Medical Selection Committee", "https://tnmedicalselection.net/"),
    ("medical", "counselling", "Medical counselling", "Application, rank list, state counselling and seat allotment procedures vary by year and programme. Government, management, minority and NRI quota information must be confirmed from current official notices.", "Tamil Nadu Medical Selection Committee", "https://tnmedicalselection.net/"),
    ("medical", "eligibility", "Programme pathways", "MBBS/BDS and allied health science admission procedures may differ. Confirm programme-specific eligibility and counselling details with the official selection committee.", "Tamil Nadu Medical Selection Committee", "https://tnmedicalselection.net/"),
    ("arts-science", "counselling", "TNGASA admissions", "Review the current application, course preference, rank list, counselling and admission confirmation instructions. This prototype does not publish current dates or cutoffs.", "TNGASA", "https://www.tngasa.in/"),
    ("arts-science", "eligibility", "College categories", "Government, aided and private institutions may publish different course and eligibility details. Check each college and the current official application guidance.", "TNGASA", "https://www.tngasa.in/"),
)

FAQS = (
    ("Are the colleges and admission details verified?", "No. College records in this demonstration are fictional samples. Admission guidance is general and must be checked against the current official notice.", None, None),
    ("Where can I find current admission dates?", "This prototype does not publish current dates. Follow the relevant official counselling website for the current admission cycle.", None, None),
    ("Are fee and cutoff values available?", "No verified fee or cutoff values are available in this sample database. Contact the institution and check official notices.", None, None),
    ("Is CollegeHub's guide an AI service?", "No. The CollegeHub guide uses predefined demonstration responses.", None, None),
)


def initialize_database(path=DB_PATH):
    database_path = Path(path)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        for statement in TABLES:
            connection.execute(statement)

        existing = {row[1] for row in connection.execute("PRAGMA table_info(colleges)")}
        for name, declaration in COLLEGE_COLUMNS.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE colleges ADD COLUMN {name} {declaration}")

        guidance_columns = {row[1] for row in connection.execute("PRAGMA table_info(guidance_records)")}
        if "last_verified" not in guidance_columns:
            connection.execute("ALTER TABLE guidance_records ADD COLUMN last_verified TEXT")

        facility_columns = {row[1] for row in connection.execute("PRAGMA table_info(facilities)")}
        for name, declaration in FACILITY_COLUMNS.items():
            if name not in facility_columns:
                connection.execute(f"ALTER TABLE facilities ADD COLUMN {name} {declaration}")

        faq_columns = {row[1] for row in connection.execute("PRAGMA table_info(faqs)")}
        for name, declaration in FAQ_COLUMNS.items():
            if name not in faq_columns:
                connection.execute(f"ALTER TABLE faqs ADD COLUMN {name} {declaration}")

        course_columns = {row[1] for row in connection.execute("PRAGMA table_info(courses)")}
        for name, declaration in COURSE_COLUMNS.items():
            if name not in course_columns:
                connection.execute(f"ALTER TABLE courses ADD COLUMN {name} {declaration}")

        for table, columns in RECORD_METADATA_COLUMNS.items():
            existing_columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            for name, declaration in columns.items():
                if name not in existing_columns:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

        connection.execute("CREATE INDEX IF NOT EXISTS idx_courses_college_id ON courses(college_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_fee_records_college_id ON fee_records(college_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_cutoff_records_college_id ON cutoff_records(college_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_guidance_stream_category ON guidance_records(stream_id, category)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_verification_status ON verification_records(status)")

        connection.execute("""
            INSERT OR IGNORE INTO districts(name)
            SELECT DISTINCT district FROM colleges WHERE district IS NOT NULL AND district != ''
        """)
        streams = dict(connection.execute("SELECT slug, id FROM streams"))
        for slug, category, heading, content, source_name, source_url in GUIDANCE:
            stream_id = streams.get(slug)
            if stream_id is not None:
                connection.execute(
                    """INSERT OR IGNORE INTO guidance_records
                       (stream_id, category, heading, content, source_name, source_url)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (stream_id, category, heading, content, source_name, source_url),
                )
        connection.executemany(
            """INSERT OR IGNORE INTO faqs(question, answer, source_name, source_url)
               VALUES (?, ?, ?, ?)""",
            FAQS,
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    initialize_database()
    print(f"CollegeHub demo database initialized: {DB_PATH}")
