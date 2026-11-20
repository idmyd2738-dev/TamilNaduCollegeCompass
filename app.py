import hmac
import hashlib
import math
import os
import secrets
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, abort, current_app, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from database import database
from models import (
    AcademicYear,
    AdmissionRecord,
    DataImportJob,
    Document,
    DocumentVersion,
    DocumentChunk,
    Conversation,
    Message,
    Facility,
    FeeComponent,
    FeeStructure,
    InformationSource,
    Institution,
    InstitutionCategory,
    InstitutionFacility,
    InstitutionType,
    PlacementReport,
    Program,
    RecordProvenance,
    SourceDocument,
)
from ai_service import AIConfigurationError, AIProviderError, ai_is_configured, answer_question, ingest_document

from services import (
    AdmissionService,
    FeeService,
    InstitutionService,
    ProgramService,
    RecommendationService,
    VerificationService,
    VerificationStatus,
)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "sample_colleges.db"
PAGE_SIZE = 9
ANNUAL_FEE_SQL = """(
    LOWER(TRIM(COALESCE(fee_type, ''))) IN (
        'annual', 'annual fee', 'annual tuition', 'annual tuition fee',
        'annual tuition fees', 'yearly', 'yearly fee', 'yearly tuition',
        'per annum', 'tuition per annum'
    )
)"""
VERIFICATION_STATES = {
    "verified",
    "pending_verification",
    "information_not_verified",
    "outdated",
}
ADMIN_REVIEW_STATUSES: dict[str, VerificationStatus] = {
    "pending": "pending",
    "verified": "verified",
    "rejected": "rejected",
    "outdated": "outdated",
}
ADMIN_RECORDS = {
    "fees": {
        "table": "fee_records",
        "fields": ("college_id", "course_id", "academic_year", "fee_type", "amount"),
        "required": ("college_id", "academic_year", "fee_type", "amount"),
        "integer_fields": ("college_id", "course_id"),
        "numeric_fields": ("amount",),
        "verification_column": "verification_status",
    },
    "cutoffs": {
        "table": "cutoff_records",
        "fields": ("college_id", "course_id", "academic_year", "quota", "cutoff_value"),
        "required": ("college_id", "academic_year", "cutoff_value"),
        "integer_fields": ("college_id", "course_id"),
        "numeric_fields": (),
        "verification_column": "verification_status",
    },
    "facilities": {
        "table": "facilities",
        "fields": ("college_id", "label", "academic_year"),
        "required": ("college_id", "label"),
        "integer_fields": ("college_id",),
        "numeric_fields": (),
        "verification_column": "verification_status",
    },
    "hostels": {
        "table": "hostel_information",
        "fields": ("college_id", "academic_year", "details"),
        "required": ("college_id", "details"),
        "integer_fields": ("college_id",),
        "numeric_fields": (),
        "verification_column": "verification_status",
    },
    "courses": {
        "table": "courses",
        "fields": ("college_id", "name", "level", "duration"),
        "required": ("college_id", "name"),
        "integer_fields": ("college_id",),
        "numeric_fields": (),
        "verification_column": "verification_status",
    },
}

app = Flask(__name__)
app.config["UNIVERSAL_DATABASE"] = database
secret_key = os.environ.get("COLLEGEHUB_SECRET_KEY")
app.config["COLLEGEHUB_SECRET_CONFIGURED"] = bool(secret_key)
if (os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV")) and not secret_key:
    raise RuntimeError("COLLEGEHUB_SECRET_KEY must be configured for deployed sessions.")
app.config["SECRET_KEY"] = secret_key or "collegehub-local-demo-session-key"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("VERCEL_ENV") == "production"
    or os.environ.get("COLLEGEHUB_SECURE_COOKIES") == "1"
)


def safe_redirect_target(target, fallback):
    if not target:
        return fallback
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return fallback
    return target


def validate_web_url(value, field_name):
    value = value.strip()
    if value:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            abort(400, description=f"{field_name} must be an HTTP or HTTPS URL.")
    return value or None


def parse_admin_record_values(config):
    values = []
    for field in config["fields"]:
        value = request.form.get(field, "").strip()
        if field in config["required"] and not value:
            abort(400, description=f"{field.replace('_', ' ').title()} is required.")
        if field in config["integer_fields"]:
            try:
                value = int(value) if value else None
            except ValueError:
                abort(400, description=f"{field.replace('_', ' ').title()} must be an integer.")
        elif field in config["numeric_fields"]:
            try:
                value = float(value) if value else None
            except ValueError:
                abort(400, description=f"{field.replace('_', ' ').title()} must be a number.")
            if value is not None and value < 0:
                abort(400, description=f"{field.replace('_', ' ').title()} cannot be negative.")
        else:
            value = value or None
        values.append(value)
    return values


def get_db():
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def read_only_deployment():
    return bool(
        os.environ.get("VERCEL")
        or os.environ.get("VERCEL_ENV")
        or os.environ.get("COLLEGEHUB_READ_ONLY") == "1"
    )


def legacy_demo_enabled():
    if current_app.config.get("TESTING"):
        return True
    return bool(
        not read_only_deployment()
        and os.environ.get("COLLEGEHUB_DEMO_MODE") == "1"
    )


def get_writable_db():
    if read_only_deployment():
        abort(503, description="Database edits are disabled in read-only deployments.")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if read_only_deployment():
            abort(503, description="The demo administrator is disabled in read-only deployments.")
        if not legacy_demo_enabled():
            abort(503, description="The legacy demo administrator is not available in database mode.")
        if not session.get("collegehub_demo_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def database_admin_enabled():
    return bool(
        os.environ.get("COLLEGEHUB_ADMIN_PASSWORD_HASH")
        and current_app.config.get("COLLEGEHUB_SECRET_CONFIGURED")
        and os.environ.get("COLLEGEHUB_READ_ONLY") != "1"
    )


def database_admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not database_admin_enabled():
            abort(503, description="Database administration is not configured.")
        if not session.get("collegehub_admin"):
            return redirect(url_for("admin_login", next=request.path))
        if not session.get("collegehub_admin_csrf"):
            abort(403, description="Administrator session is missing its CSRF token.")
        return view(*args, **kwargs)
    return wrapped


def validate_admin_csrf():
    expected = session.get("collegehub_admin_csrf", "")
    supplied = request.form.get("csrf_token", "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        abort(400, description="Invalid or missing CSRF token.")


def student_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not legacy_demo_enabled():
            abort(503, description="Student accounts are not configured.")
        if not session.get("collegehub_demo_student"):
            return redirect(url_for("student_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def college_query(where_sql="", order_by="c.featured DESC, c.name"):
    return f"""
        SELECT c.*, s.name AS stream_name, s.slug AS stream_slug,
               (SELECT GROUP_CONCAT(name, ', ') FROM courses WHERE college_id=c.id) AS course_names,
               (SELECT MIN(amount) FROM fee_records
                WHERE college_id=c.id AND verification_status='verified' AND {ANNUAL_FEE_SQL}) AS min_fee
        FROM colleges c JOIN streams s ON s.id=c.stream_id
        {where_sql}
        ORDER BY {order_by}
    """


@app.context_processor
def inject_globals():
    return {"site_name": "CollegeHub"}


def database_category_summary(db_session):
    rows = db_session.execute(
        select(
            InstitutionCategory.code,
            InstitutionCategory.name,
            func.count(Institution.id).label("institution_count"),
        )
        .outerjoin(Institution, Institution.category_id == InstitutionCategory.id)
        .group_by(InstitutionCategory.id)
        .order_by(InstitutionCategory.name)
    ).all()
    return [
        {
            "code": row.code,
            "name": row.name,
            "institution_count": row.institution_count,
        }
        for row in rows
    ]


@app.get("/")
def home():
    if not legacy_demo_enabled():
        with universal_session() as db_session:
            categories = database_category_summary(db_session)
            institution_count = db_session.scalar(
                select(func.count()).select_from(Institution)
            )
        return render_template(
            "database/home.html",
            categories=categories,
            institution_count=institution_count or 0,
        )
    with closing(get_db()) as db:
        streams = db.execute("""
            SELECT s.slug, s.name, s.icon, COUNT(c.id) AS college_count
            FROM streams s LEFT JOIN colleges c ON c.stream_id=s.id
            GROUP BY s.id ORDER BY s.id
        """).fetchall()
        featured = db.execute(college_query(order_by="c.featured DESC, c.name") + " LIMIT 3").fetchall()
    return render_template("home.html", streams=streams, featured=featured)


@app.get("/college")
def college_home():
    if not legacy_demo_enabled():
        with universal_session() as db_session:
            categories = database_category_summary(db_session)
        return render_template("database/streams.html", categories=categories)
    with closing(get_db()) as db:
        streams = db.execute("""
            SELECT s.slug, s.name, s.icon, COUNT(c.id) AS college_count
            FROM streams s LEFT JOIN colleges c ON c.stream_id=s.id
            GROUP BY s.id ORDER BY s.id
        """).fetchall()
    return render_template("college_home.html", streams=streams)


@app.get("/college/<string:stream_slug>")
def stream_page(stream_slug):
    if not legacy_demo_enabled():
        with universal_session() as db_session:
            category = db_session.scalar(
                select(InstitutionCategory).where(InstitutionCategory.code == stream_slug)
            )
            if category is None:
                abort(404)
            institutions = InstitutionService(db_session).search(
                category=category.code, limit=6
            )
        return render_template(
            "database/stream.html", category=category, institutions=institutions
        )
    with closing(get_db()) as db:
        stream = db.execute("SELECT * FROM streams WHERE slug=?", (stream_slug,)).fetchone()
        if stream is None:
            abort(404)
        guidance = db.execute(
            """SELECT * FROM guidance_records WHERE stream_id=?
               ORDER BY CASE category
                 WHEN 'overview' THEN 0
                 WHEN 'counselling' THEN 1
                 WHEN 'entrance_examinations' THEN 2
                 WHEN 'eligibility' THEN 3
                 WHEN 'fisheries' THEN 4
                 ELSE 5 END, id""",
            (stream["id"],),
        ).fetchall()
        colleges = db.execute(
            college_query("WHERE c.stream_id=?", "c.featured DESC, c.name") + " LIMIT 6",
            (stream["id"],),
        ).fetchall()
    return render_template("stream.html", stream=stream, guidance=guidance, colleges=colleges)


@app.get("/colleges")
def colleges():
    if not legacy_demo_enabled():
        return database_colleges_page()
    q = request.args.get("q", "").strip()
    stream = request.args.get("stream", "").strip()
    district = request.args.get("district", "").strip()
    course = request.args.get("course", "").strip()
    category = request.args.get("category", "").strip()
    ownership = request.args.get("ownership", "").strip()
    fee_range = request.args.get("fee_range", "").strip()
    facility = request.args.get("facility", "").strip()
    hostel = request.args.get("hostel", "").strip()
    sort = request.args.get("sort", "featured")
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1

    conditions = []
    parameters = []
    if q:
        conditions.append("(c.name LIKE ? OR c.city LIKE ? OR c.district LIKE ?)")
        parameters.extend([f"%{q}%"] * 3)
    if stream:
        conditions.append("s.slug=?")
        parameters.append(stream)
    if district:
        conditions.append("c.district=?")
        parameters.append(district)
    if course:
        conditions.append("EXISTS (SELECT 1 FROM courses cr WHERE cr.college_id=c.id AND cr.name LIKE ?)")
        parameters.append(f"%{course}%")
    if category:
        conditions.append("LOWER(COALESCE(c.category, ''))=LOWER(?)")
        parameters.append(category)
    if ownership:
        conditions.append("LOWER(COALESCE(c.ownership, ''))=LOWER(?)")
        parameters.append(ownership)
    if facility:
        conditions.append(
            "EXISTS (SELECT 1 FROM facilities ff WHERE ff.college_id=c.id AND ff.label=?)"
        )
        parameters.append(facility)
    if fee_range in {"under-50000", "50000-100000", "over-100000"}:
        expressions = {
            "under-50000": "fr.amount < 50000",
            "50000-100000": "fr.amount >= 50000 AND fr.amount <= 100000",
            "over-100000": "fr.amount > 100000",
        }
        conditions.append(
            f"""EXISTS (SELECT 1 FROM fee_records fr WHERE fr.college_id=c.id
                AND fr.verification_status='verified' AND {ANNUAL_FEE_SQL}
                AND {expressions[fee_range]})"""
        )
    if hostel in {"yes", "no"}:
        conditions.append("c.hostel_available=?")
        parameters.append(1 if hostel == "yes" else 0)

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    order_options = {
        "featured": "c.featured DESC, c.name",
        "name": "c.name COLLATE NOCASE",
        "district": "c.district COLLATE NOCASE, c.name COLLATE NOCASE",
        "fees": "min_fee IS NULL, min_fee, c.name COLLATE NOCASE",
    }
    order_by = order_options.get(sort, order_options["featured"])
    with closing(get_db()) as db:
        streams = db.execute("SELECT * FROM streams ORDER BY name").fetchall()
        districts = db.execute("SELECT DISTINCT district FROM colleges WHERE district IS NOT NULL ORDER BY district").fetchall()
        courses = db.execute("SELECT DISTINCT name FROM courses ORDER BY name").fetchall()
        facilities = db.execute("SELECT DISTINCT label FROM facilities ORDER BY label").fetchall()
        total = db.execute(
            f"SELECT COUNT(*) FROM colleges c JOIN streams s ON s.id=c.stream_id {where_sql}",
            parameters,
        ).fetchone()[0]
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, pages)
        rows = db.execute(
            college_query(where_sql, order_by) + " LIMIT ? OFFSET ?",
            (*parameters, PAGE_SIZE, (page - 1) * PAGE_SIZE),
        ).fetchall()
        categories = db.execute(
            "SELECT DISTINCT category FROM colleges WHERE category IS NOT NULL AND category!='' ORDER BY category"
        ).fetchall()
        ownerships = db.execute(
            "SELECT DISTINCT ownership FROM colleges WHERE ownership IS NOT NULL AND ownership!='' ORDER BY ownership"
        ).fetchall()
    return render_template(
        "colleges.html", colleges=rows, streams=streams, districts=districts, courses=courses,
        categories=categories, ownerships=ownerships, q=q, selected_stream=stream,
        selected_district=district, selected_course=course, selected_category=category,
        selected_ownership=ownership, selected_fee_range=fee_range, selected_facility=facility,
        facilities=facilities, selected_hostel=hostel,
        sort=sort, page=page, pages=pages, total=total,
    )


@app.get("/colleges/<int:college_id>")
def college_detail(college_id):
    if not legacy_demo_enabled():
        return database_college_detail_page(college_id)
    with closing(get_db()) as db:
        college = db.execute("""
            SELECT c.*, s.name AS stream_name, s.slug AS stream_slug
            FROM colleges c JOIN streams s ON s.id=c.stream_id WHERE c.id=?
        """, (college_id,)).fetchone()
        if college is None:
            abort(404)
        courses = db.execute("""
            SELECT cr.*, source.source_name, source.source_url
            FROM courses cr LEFT JOIN information_sources source ON source.id=cr.source_id
            WHERE cr.college_id=? ORDER BY cr.name
        """,
            (college_id,),
        ).fetchall()
        facilities = db.execute(
            "SELECT * FROM facilities WHERE college_id=? ORDER BY label", (college_id,)
        ).fetchall()
        fees = db.execute("""
            SELECT f.*, cr.name AS course_name FROM fee_records f
            LEFT JOIN courses cr ON cr.id=f.course_id WHERE f.college_id=? ORDER BY f.academic_year DESC
        """, (college_id,)).fetchall()
        cutoffs = db.execute("""
            SELECT ct.*, cr.name AS course_name FROM cutoff_records ct
            LEFT JOIN courses cr ON cr.id=ct.course_id WHERE ct.college_id=? ORDER BY ct.academic_year DESC
        """, (college_id,)).fetchall()
        hostels = db.execute("SELECT * FROM hostel_information WHERE college_id=? ORDER BY academic_year DESC", (college_id,)).fetchall()
        sources = db.execute("SELECT * FROM information_sources WHERE college_id=? ORDER BY id DESC", (college_id,)).fetchall()
    return render_template(
        "college_detail.html", college=college, courses=courses, facilities=facilities,
        fees=fees, cutoffs=cutoffs, hostels=hostels, sources=sources,
    )


@app.get("/compare")
def compare_colleges():
    if not legacy_demo_enabled():
        return database_compare_page()
    raw_ids = request.args.get("ids", "")
    ids = []
    for raw_id in raw_ids.split(","):
        try:
            value = int(raw_id)
        except ValueError:
            continue
        if value > 0 and value not in ids:
            ids.append(value)
    ids = ids[:3]
    colleges_to_compare = []
    if ids:
        placeholders = ",".join("?" for _ in ids)
        with closing(get_db()) as db:
            rows = db.execute(
                college_query(f"WHERE c.id IN ({placeholders})"),
                ids,
            ).fetchall()
            by_id = {row["id"]: dict(row) for row in rows}
            colleges_to_compare = [by_id[college_id] for college_id in ids if college_id in by_id]
            for college in colleges_to_compare:
                college["facilities"] = db.execute(
                    "SELECT label FROM facilities WHERE college_id=? ORDER BY label", (college["id"],)
                ).fetchall()
                college["hostel_available"] = db.execute(
                    "SELECT hostel_available FROM colleges WHERE id=?", (college["id"],)
                ).fetchone()[0]
    return render_template("compare.html", colleges=colleges_to_compare)


@app.get("/recommendations")
def recommendations():
    if not legacy_demo_enabled():
        return database_recommendations_page()
    course = request.args.get("course", "").strip()
    district = request.args.get("district", "").strip()
    ownership = request.args.get("ownership", "").strip()
    hostel = request.args.get("hostel", "").strip()
    facility_preferences = list(dict.fromkeys(request.args.getlist("facility")))
    budget_raw = request.args.get("max_annual_fee", "").strip()
    try:
        max_annual_fee = float(budget_raw) if budget_raw else None
    except ValueError:
        abort(400, description="Maximum annual fee must be a non-negative number.")
    if max_annual_fee is not None and (
        not math.isfinite(max_annual_fee) or max_annual_fee < 0 or max_annual_fee > 1_000_000_000
    ):
        abort(400, description="Maximum annual fee must be between 0 and 1,000,000,000.")
    if hostel not in {"", "yes", "no"}:
        abort(400, description="Hostel preference must be yes or no.")

    with closing(get_db()) as db:
        colleges = db.execute(college_query(order_by="c.name COLLATE NOCASE")).fetchall()
        courses = db.execute("SELECT DISTINCT name FROM courses ORDER BY name").fetchall()
        districts = db.execute(
            "SELECT DISTINCT district AS name FROM colleges WHERE district IS NOT NULL ORDER BY district"
        ).fetchall()
        ownerships = db.execute(
            "SELECT DISTINCT ownership AS name FROM colleges WHERE ownership IS NOT NULL ORDER BY ownership"
        ).fetchall()
        facilities = db.execute("SELECT DISTINCT label FROM facilities ORDER BY label").fetchall()

        course_names = {row["name"] for row in courses}
        district_names = {row["name"] for row in districts}
        ownership_names = {row["name"] for row in ownerships}
        facility_names = {row["label"] for row in facilities}
        if course and course not in course_names:
            abort(400, description="Select a course from the available options.")
        if district and district not in district_names:
            abort(400, description="Select a district from the available options.")
        if ownership and ownership not in ownership_names:
            abort(400, description="Select a college type from the available options.")
        if any(value not in facility_names for value in facility_preferences):
            abort(400, description="Select facilities from the available options.")

        courses_by_college = {}
        for row in db.execute("SELECT college_id, name FROM courses"):
            courses_by_college.setdefault(row["college_id"], set()).add(row["name"].casefold())
        verified_facilities_by_college = {}
        for row in db.execute(
            "SELECT college_id, label FROM facilities WHERE verification_status='verified'"
        ):
            verified_facilities_by_college.setdefault(row["college_id"], set()).add(row["label"])
        annual_fees_by_college = {}
        for row in db.execute(
            f"""SELECT college_id, MIN(amount) AS amount FROM fee_records
                WHERE verification_status='verified' AND {ANNUAL_FEE_SQL}
                  AND amount IS NOT NULL GROUP BY college_id"""
        ):
            annual_fees_by_college[row["college_id"]] = row["amount"]

    preference_count = (
        bool(course) + bool(district) + (max_annual_fee is not None)
        + bool(ownership) + bool(hostel) + len(facility_preferences)
    )
    results = []
    if preference_count:
        for college in colleges:
            reasons = []
            matches = 0
            college_courses = courses_by_college.get(college["id"], set())
            if course:
                matched = course.casefold() in college_courses
                matches += int(matched)
                reasons.append(
                    f"{'Course is listed' if matched else 'Course is not listed'}: {course}."
                )
            if district:
                matched = (college["district"] or "").casefold() == district.casefold()
                matches += int(matched)
                reasons.append(
                    f"{'District matches' if matched else 'District differs'}: "
                    f"{college['district'] or 'not provided'}."
                )
            if ownership:
                matched = (college["ownership"] or "").casefold() == ownership.casefold()
                matches += int(matched)
                reasons.append(
                    f"{'College type matches' if matched else 'College type differs'}: "
                    f"{college['ownership'] or 'not provided'}."
                )
            if max_annual_fee is not None:
                annual_fee = annual_fees_by_college.get(college["id"])
                matched = annual_fee is not None and annual_fee <= max_annual_fee
                matches += int(matched)
                if annual_fee is None:
                    reasons.append("Budget fit cannot be checked: no verified annual fee is available.")
                else:
                    reasons.append(
                        f"Verified annual fee {'is within' if matched else 'exceeds'} "
                        f"the budget: ₹{annual_fee:,.0f}."
                    )
            if hostel:
                hostel_known = (
                    college["information_status"] == "verified"
                    and college["hostel_available"] is not None
                )
                matched = hostel_known and bool(college["hostel_available"]) == (hostel == "yes")
                matches += int(matched)
                if hostel_known:
                    reasons.append(
                        f"Verified hostel availability {'matches' if matched else 'does not match'} "
                        "the preference."
                    )
                else:
                    reasons.append("Hostel fit cannot be checked from verified information.")
            for requested_facility in facility_preferences:
                matched = requested_facility in verified_facilities_by_college.get(college["id"], set())
                matches += int(matched)
                reasons.append(
                    f"{'Verified facility found' if matched else 'No verified record for'}: "
                    f"{requested_facility}."
                )

            results.append({
                **dict(college),
                "match_percentage": round(matches * 100 / preference_count),
                "reasons": reasons,
                "annual_fee": annual_fees_by_college.get(college["id"]),
            })
        results.sort(key=lambda result: (-result["match_percentage"], result["name"].casefold()))

    return render_template(
        "recommendations.html", results=results, courses=courses, districts=districts,
        ownerships=ownerships, facilities=facilities, selected_course=course,
        selected_district=district, selected_ownership=ownership,
        selected_facilities=facility_preferences, selected_hostel=hostel,
        max_annual_fee=budget_raw, has_preferences=bool(preference_count),
    )


@app.get("/cutoffs")
def cutoff_analytics():
    if not legacy_demo_enabled():
        return database_cutoffs_page()
    college_id_raw = request.args.get("college", "").strip()
    course = request.args.get("course", "").strip()
    academic_year = request.args.get("year", "").strip()
    try:
        college_id = int(college_id_raw) if college_id_raw else None
    except ValueError:
        abort(400, description="Select a college from the available options.")

    conditions = []
    parameters = []
    if college_id is not None:
        conditions.append("x.college_id=?")
        parameters.append(college_id)
    if course:
        conditions.append("cr.name=?")
        parameters.append(course)
    if academic_year:
        conditions.append("x.academic_year=?")
        parameters.append(academic_year)
    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with closing(get_db()) as db:
        colleges = db.execute("SELECT id, name FROM colleges ORDER BY name").fetchall()
        courses = db.execute("SELECT DISTINCT name FROM courses ORDER BY name").fetchall()
        years = db.execute(
            """SELECT DISTINCT academic_year AS label FROM cutoff_records
               WHERE academic_year IS NOT NULL ORDER BY label DESC"""
        ).fetchall()
        if college_id is not None and college_id not in {row["id"] for row in colleges}:
            abort(400, description="Select a college from the available options.")
        if course and course not in {row["name"] for row in courses}:
            abort(400, description="Select a course from the available options.")
        if academic_year and academic_year not in {row["label"] for row in years}:
            abort(400, description="Select an academic year from the available options.")
        records = db.execute(
            f"""SELECT x.*, c.name AS college_name, cr.name AS course_name,
                       s.source_name, s.source_url
                FROM cutoff_records x
                JOIN colleges c ON c.id=x.college_id
                LEFT JOIN courses cr ON cr.id=x.course_id
                LEFT JOIN information_sources s ON s.id=x.source_id
                {where_sql}
                ORDER BY x.academic_year DESC, c.name, cr.name, x.quota""",
            parameters,
        ).fetchall()

    display_records = []
    chart_records = []
    for row in records:
        item = dict(row)
        item["verified"] = bool(
            item["verification_status"] == "verified"
            and item["source_name"] and item["source_url"]
            and item["academic_year"] and item["last_verified"]
        )
        try:
            numeric_value = float(item["cutoff_value"])
            if not math.isfinite(numeric_value) or numeric_value < 0:
                numeric_value = None
        except (TypeError, ValueError):
            numeric_value = None
        item["numeric_value"] = numeric_value
        display_records.append(item)
        if item["verified"] and numeric_value is not None:
            chart_records.append(item)
    chart_maximum = max((item["numeric_value"] for item in chart_records), default=0)
    for item in chart_records:
        item["bar_width"] = (
            max(4, round(item["numeric_value"] * 100 / chart_maximum))
            if chart_maximum else 4
        )

    return render_template(
        "cutoffs.html", records=display_records, chart_records=chart_records,
        colleges=colleges, courses=courses, years=years,
        selected_college=college_id, selected_course=course, selected_year=academic_year,
    )


def database_admin_dashboard():
    pending = []
    record_specs = (
        (Institution, "institution", "official_name"),
        (Program, "program", "name"),
        (AdmissionRecord, "admission_record", "measurement_type"),
        (FeeStructure, "fee_structure", "notes"),
        (FeeComponent, "fee_component", "name"),
        (PlacementReport, "placement_report", "reporting_year"),
    )
    with universal_session() as db_session:
        counts = {
            "institutions": db_session.scalar(
                select(func.count()).select_from(Institution)
            ) or 0,
            "programs": db_session.scalar(
                select(func.count()).select_from(Program)
            ) or 0,
            "admissions": db_session.scalar(
                select(func.count()).select_from(AdmissionRecord)
            ) or 0,
            "fees": db_session.scalar(
                select(func.count()).select_from(FeeComponent)
            ) or 0,
            "cutoffs": db_session.scalar(
                select(func.count()).select_from(AdmissionRecord).where(
                    AdmissionRecord.measurement_type == "cutoff_score"
                )
            ) or 0,
            "placements": db_session.scalar(
                select(func.count()).select_from(PlacementReport)
            ) or 0,
            "verified": db_session.scalar(
                select(func.count()).select_from(RecordProvenance).where(
                    RecordProvenance.verification_status == "verified"
                )
            ) or 0,
            "pending": db_session.scalar(
                select(func.count()).select_from(RecordProvenance).where(
                    RecordProvenance.verification_status.in_(("unverified", "pending"))
                )
            ) or 0,
            "documents": db_session.scalar(
                select(func.count()).select_from(Document)
            ) or 0,
            "source_documents": db_session.scalar(
                select(func.count()).select_from(SourceDocument)
            ) or 0,
            "import_jobs": db_session.scalar(
                select(func.count()).select_from(DataImportJob)
            ) or 0,
            "failed_jobs": db_session.scalar(
                select(func.count()).select_from(DataImportJob).where(
                    DataImportJob.status == "failed"
                )
            ) or 0,
        }
        for model, record_type, label_field in record_specs:
            remaining = 100 - len(pending)
            if remaining <= 0:
                break
            statement = (
                select(model)
                .join(RecordProvenance, model.provenance_id == RecordProvenance.id)
                .where(
                    RecordProvenance.verification_status.in_(("unverified", "pending"))
                )
                .order_by(model.id)
                .limit(remaining)
            )
            for record in db_session.scalars(statement):
                provenance = record.provenance
                label = getattr(record, label_field, None)
                if record_type == "admission_record":
                    label = f"{record.program.name} - {record.measurement_type}"
                elif record_type == "fee_structure":
                    label = f"Fee structure #{record.id}"
                pending.append({
                    "type": record_type,
                    "id": provenance.id,
                    "label": str(label or f"{record_type} #{record.id}"),
                    "status": provenance.verification_status,
                    "source": provenance.source,
                })
        sources = db_session.scalars(
            select(InformationSource).order_by(InformationSource.id.desc()).limit(200)
        ).all()
        jobs = db_session.scalars(
            select(DataImportJob).order_by(DataImportJob.id.desc()).limit(100)
        ).all()
        document_versions = db_session.execute(
            select(DocumentVersion, Document)
            .join(Document, Document.id == DocumentVersion.document_id)
            .order_by(DocumentVersion.id.desc())
            .limit(100)
        ).all()
        return render_template(
            "database/admin_dashboard.html",
            counts=counts,
            pending=pending,
            sources=sources,
            jobs=jobs,
            document_versions=document_versions,
            csrf_token=session["collegehub_admin_csrf"],
        )


@app.post("/admin/sources")
@database_admin_required
def database_admin_add_source():
    validate_admin_csrf()
    source_url = validate_web_url(request.form.get("source_url", ""), "Source URL")
    organisation = request.form.get("source_organisation", "").strip()
    title = request.form.get("document_title", "").strip()
    source_type = request.form.get("source_document_type", "").strip()
    if not source_url or not organisation or not title:
        abort(400, description="Source URL, organisation, and title are required.")
    if len(organisation) > 255 or len(title) > 500 or len(source_type) > 80:
        abort(400, description="Source fields exceed their maximum lengths.")
    with universal_session() as db_session:
        with db_session.begin():
            existing = db_session.scalar(
                select(InformationSource.id).where(
                    InformationSource.source_url == source_url
                )
            )
            if existing is not None:
                abort(409, description="This source URL is already registered.")
            db_session.add(InformationSource(
                source_url=source_url,
                source_organisation=organisation,
                document_title=title,
                source_document_type=source_type or None,
            ))
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/ingest/anna-university")
@database_admin_required
def database_admin_ingest_anna_university():
    validate_admin_csrf()
    from ingestion.anna_university import ingest_constituent_colleges

    try:
        result = ingest_constituent_colleges(
            database_instance=current_app.config["UNIVERSAL_DATABASE"]
        )
    except (OSError, PermissionError, SQLAlchemyError, UnicodeError, ValueError, RuntimeError) as error:
        current_app.logger.error(
            "Official-source ingestion failed (%s).", type(error).__name__
        )
        abort(502, description="Ingestion failed. Review the recorded import-job status.")
    current_app.logger.info(
        "Official-source import job %s completed: %s created, %s duplicates skipped.",
        result.job_id,
        result.rows_created,
        result.duplicates_skipped,
    )
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/ingest/tngasa-2026")
@database_admin_required
def database_admin_ingest_tngasa_2026():
    validate_admin_csrf()
    from ingestion.tngasa_2026 import ingest_tngasa_2026

    try:
        result = ingest_tngasa_2026(
            database_instance=current_app.config["UNIVERSAL_DATABASE"]
        )
    except (OSError, PermissionError, SQLAlchemyError, UnicodeError, ValueError, RuntimeError) as error:
        current_app.logger.error(
            "TNGASA official-source ingestion failed (%s).", type(error).__name__
        )
        abort(502, description="TNGASA import failed. No partial records should be treated as verified.")
    current_app.logger.info(
        "TNGASA import job %s completed: %s created, %s duplicates skipped.",
        result["job_id"], result["rows_created"], result["duplicates_skipped"],
    )
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/provenance/<int:provenance_id>/review")
@database_admin_required
def database_admin_review_provenance(provenance_id):
    validate_admin_csrf()
    status = ADMIN_REVIEW_STATUSES.get(request.form.get("verification_status", ""))
    if status is None:
        abort(400, description="Unsupported verification status.")
    notes = request.form.get("notes", "").strip()
    if len(notes) > 2000:
        abort(400, description="Review notes must be 2000 characters or fewer.")
    try:
        with universal_session() as db_session:
            with db_session.begin():
                VerificationService(db_session).record_review(
                    provenance_id,
                    status,
                    notes=notes or None,
                    verified_at=datetime.now(timezone.utc) if status == "verified" else None,
                )
    except ValueError as error:
        abort(400, description=str(error))
    except LookupError:
        abort(404, description="Provenance record not found.")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/documents/<int:version_id>/review")
@database_admin_required
def database_admin_review_document(version_id):
    validate_admin_csrf()
    status = request.form.get("verification_status", "")
    if status not in {"pending", "verified", "rejected", "outdated"}:
        abort(400, description="Unsupported document verification status.")
    with universal_session() as db_session:
        version = db_session.get(DocumentVersion, version_id)
        if version is None:
            abort(404, description="Document version not found.")
        chunks = db_session.scalars(
            select(DocumentChunk).where(DocumentChunk.document_version_id == version_id)
        ).all()
        for chunk in chunks:
            metadata = dict(chunk.chunk_metadata or {})
            metadata["verification_status"] = status
            metadata["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            metadata["reviewer"] = "configured_collegehub_admin"
            chunk.chunk_metadata = metadata
        db_session.commit()
    return redirect(url_for("admin_dashboard"))


@app.get("/about")
def about():
    if not legacy_demo_enabled():
        return render_template("database/about.html")
    return render_template("about.html")


@app.get("/chat")
def chat():
    if not legacy_demo_enabled():
        return render_template("database/chat.html", chatbot_available=ai_is_configured())
    with closing(get_db()) as db:
        faqs = db.execute("SELECT * FROM faqs ORDER BY id").fetchall()
    return render_template("chat.html", faqs=faqs)


@app.post("/api/chat")
def database_chat_api():
    if legacy_demo_enabled():
        abort(404)
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("message", "")).strip()
    if not question:
        return jsonify(error="Enter a question."), 400
    if len(question) > 4000:
        return jsonify(error="Questions must be 4,000 characters or fewer."), 400
    if not ai_is_configured():
        return jsonify(
            error="The AI service is not configured. Add the AI provider settings to the server environment."
        ), 503

    conversation_token = session.get("collegehub_chat_token")
    if not conversation_token:
        conversation_token = secrets.token_urlsafe(32)
        session["collegehub_chat_token"] = conversation_token
    user_key_hash = hashlib.sha256(conversation_token.encode("utf-8")).hexdigest()

    try:
        with universal_session() as db_session:
            conversation = db_session.scalar(
                select(Conversation).where(Conversation.user_key_hash == user_key_hash)
            )
            if conversation is None:
                conversation = Conversation(
                    user_key_hash=user_key_hash,
                    title=question[:240],
                )
                db_session.add(conversation)
                db_session.flush()
            db_session.add(Message(
                conversation_id=conversation.id,
                role="user",
                content=question,
            ))
            db_session.commit()
            answer, citations = answer_question(db_session, question, conversation)
            db_session.add(Message(
                conversation_id=conversation.id,
                role="assistant",
                content=answer,
                message_metadata={"citations": citations},
            ))
            db_session.commit()
            return jsonify(
                answer=answer,
                citations=citations,
                conversation_id=conversation.id,
            )
    except AIConfigurationError as error:
        return jsonify(error=str(error)), 503
    except (AIProviderError, ValueError) as error:
        current_app.logger.warning("CollegeHub AI request failed: %s", type(error).__name__)
        return jsonify(error="The AI service could not complete this request. Try again later."), 502


@app.post("/admin/documents")
@database_admin_required
def database_admin_upload_document():
    validate_admin_csrf()
    uploaded = request.files.get("document")
    if uploaded is None or not uploaded.filename:
        abort(400, description="Choose a document to upload.")
    filename = secure_filename(uploaded.filename)
    if not filename:
        abort(400, description="The uploaded filename is invalid.")
    raw = uploaded.stream.read(15 * 1024 * 1024 + 1)
    if len(raw) > 15 * 1024 * 1024:
        abort(413, description="Documents must be 15 MB or smaller.")
    source_url = request.form.get("source_url", "").strip()
    academic_year = request.form.get("academic_year", "").strip() or None
    if academic_year and len(academic_year) > 20:
        abort(400, description="Academic year must be 20 characters or fewer.")
    if not source_url:
        abort(400, description="Provide the official source URL for this document.")
    with universal_session() as db_session:
        source = db_session.scalar(
            select(InformationSource).where(InformationSource.source_url == source_url)
        )
        if source is None:
            abort(400, description="Register this official source before uploading its document.")
        organisation = source.source_organisation or "Official source"
        try:
            result = ingest_document(
                db_session,
                filename=filename,
                raw=raw,
                source_url=source_url,
                source_organisation=organisation,
                academic_year_label=academic_year,
                content_type=uploaded.mimetype,
            )
        except (ValueError, AIConfigurationError, AIProviderError) as error:
            abort(400, description=str(error))
    current_app.logger.info(
        "Document %s indexed as version %s with %s chunks.",
        result["document_id"], result["version_id"], result["chunks_created"],
    )
    return redirect(url_for("admin_dashboard"))


@app.post("/demo-chat")
def demo_chat():
    if not legacy_demo_enabled():
        abort(404)
    question = (request.json or {}).get("message", "").strip().lower()
    if not question:
        return jsonify(answer="Please enter a question.")
    answers = [
        (("engineering", "tnea", "choice filling"), "Engineering counselling examples include registration, certificate verification, rank lists, choice filling, seat allotment and admission confirmation. Check the current TNEA notice for applicable steps.", "TNEA", "https://www.tneaonline.org/"),
        (("agriculture", "horticulture", "agricultural engineering"), "Agriculture programmes vary by institution. Check current programme and admission information with TNAU and Annamalai University.", "Tamil Nadu Agricultural University", "https://tnau.ac.in/"),
        (("fisheries",), "Fisheries admissions are separate from agriculture guidance. This demo does not include verified fisheries-specific requirements.", None, None),
        (("medical", "mbbs", "bds", "neet", "allied health"), "Medical pathways may involve NEET-UG and separate counselling processes for MBBS/BDS and allied health programmes. Check the current official notices.", "Tamil Nadu Medical Selection Committee", "https://tnmedicalselection.net/"),
        (("arts", "tngasa"), "For arts and science admissions, review current TNGASA application, preference, rank list, counselling and admission confirmation instructions.", "TNGASA", "https://www.tngasa.in/"),
        (("course", "programme"), "Course information in this prototype is sample data and may not reflect current offerings. Check the institution's official website.", None, None),
        (("eligibility",), "Eligibility depends on the institution, programme and admission year. Verify current requirements with the responsible official authority.", None, None),
        (("fees", "fee", "cost"), "Verified fee figures are not available in this demo. Fees vary by programme, institution and academic year; contact the college for current details.", None, None),
        (("hostel", "accommodation", "facility"), "Facilities and hostel availability are not verified in this demo. Contact the college administration for current details.", None, None),
        (("cutoff",), "This demo does not provide verified current or historical cutoffs. Refer to official counselling notices for published information.", None, None),
        (("admission", "counselling", "seat allotment"), "Admission requirements, counselling schedules and cutoffs change. Follow the relevant official counselling website for current notices.", None, None),
    ]
    for keywords, answer, source_name, source_url in answers:
        if any(word in question for word in keywords):
            return jsonify(answer=answer, source_name=source_name, source_url=source_url)
    return jsonify(
        answer="I don't have verified information for that question in this demonstration. Please check the relevant official government portal or contact the college directly.",
        source_name=None,
        source_url=None,
    )


@app.get("/login")
def login():
    if not legacy_demo_enabled():
        return render_template("database/login.html")
    return render_template("login.html")


@app.get("/student/login")
def student_login():
    if not legacy_demo_enabled():
        abort(503, description="Student accounts are not configured.")
    return render_template("access_form.html", mode="student_login", next_url=request.args.get("next", ""))


@app.post("/student/login")
def student_login_submit():
    if not legacy_demo_enabled():
        abort(503, description="Student accounts are not configured.")
    email = request.form.get("email", "").strip()
    if not email or "@" not in email:
        return render_template("access_form.html", mode="student_login", error="Enter a valid demo email address.", next_url="")
    session["collegehub_demo_student"] = {"name": email.split("@", 1)[0], "email": email}
    session.permanent = request.form.get("remember") == "on"
    return redirect(safe_redirect_target(request.form.get("next"), url_for("student_dashboard")))


@app.get("/student/register")
def student_register():
    if not legacy_demo_enabled():
        abort(503, description="Student accounts are not configured.")
    return render_template("access_form.html", mode="student_register", next_url="")


@app.post("/student/register")
def student_register_submit():
    if not legacy_demo_enabled():
        abort(503, description="Student accounts are not configured.")
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    confirmation = request.form.get("confirm_password", "")
    if not name or not email or "@" not in email:
        return render_template("access_form.html", mode="student_register", error="Enter your name and a valid email address.", next_url="")
    if not password or password != confirmation:
        return render_template("access_form.html", mode="student_register", error="Enter matching demo passwords.", next_url="")
    session["collegehub_demo_student"] = {"name": name, "email": email}
    session.permanent = False
    return redirect(url_for("student_dashboard"))


@app.get("/student/dashboard")
@student_required
def student_dashboard():
    with closing(get_db()) as db:
        colleges = db.execute("SELECT id, name, city, district FROM colleges ORDER BY name").fetchall()
    return render_template(
        "student_dashboard.html", student=session["collegehub_demo_student"],
        college_directory=[dict(college) for college in colleges],
    )


@app.post("/student/logout")
def student_logout():
    if not legacy_demo_enabled():
        abort(503, description="Student accounts are not configured.")
    session.pop("collegehub_demo_student", None)
    return redirect(url_for("login"))


@app.get("/admin/login")
def admin_login():
    if not legacy_demo_enabled():
        if not database_admin_enabled():
            abort(503, description="Database administration is not configured.")
        csrf_token = secrets.token_urlsafe(32)
        session["collegehub_admin_login_csrf"] = csrf_token
        return render_template(
            "database/admin_login.html",
            csrf_token=csrf_token,
            next_url=safe_redirect_target(
                request.args.get("next"), url_for("admin_dashboard")
            ),
        )
    if read_only_deployment():
        abort(503, description="The demo administrator is disabled in read-only deployments.")
    return render_template("access_form.html", mode="admin_login", next_url=request.args.get("next", ""))


@app.post("/admin/login")
def admin_login_submit():
    if not legacy_demo_enabled():
        if not database_admin_enabled():
            abort(503, description="Database administration is not configured.")
        expected = session.pop("collegehub_admin_login_csrf", "")
        supplied = request.form.get("csrf_token", "")
        if not expected or not supplied or not hmac.compare_digest(expected, supplied):
            abort(400, description="Invalid or missing CSRF token.")
        password_hash = os.environ["COLLEGEHUB_ADMIN_PASSWORD_HASH"]
        try:
            valid_password = check_password_hash(
                password_hash, request.form.get("password", "")
            )
        except ValueError:
            current_app.logger.error("Configured administrator password hash is invalid.")
            abort(503, description="Administrator authentication is misconfigured.")
        if not valid_password:
            abort(401, description="Invalid administrator credentials.")
        next_url = safe_redirect_target(
            request.form.get("next"), url_for("admin_dashboard")
        )
        session.clear()
        session["collegehub_admin"] = True
        session["collegehub_admin_csrf"] = secrets.token_urlsafe(32)
        return redirect(next_url)
    if read_only_deployment():
        abort(503, description="The demo administrator is disabled in read-only deployments.")
    session["collegehub_demo_admin"] = True
    return redirect(safe_redirect_target(request.form.get("next"), url_for("admin_dashboard")))


@app.post("/admin/logout")
def admin_logout():
    if not legacy_demo_enabled():
        if not database_admin_enabled() or not session.get("collegehub_admin"):
            abort(403)
        validate_admin_csrf()
        session.clear()
        return redirect(url_for("login"))
    session.pop("collegehub_demo_admin", None)
    return redirect(url_for("login"))


@app.get("/admin")
def admin_dashboard():
    if not legacy_demo_enabled():
        if not database_admin_enabled():
            abort(503, description="Database administration is not configured.")
        if not session.get("collegehub_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return database_admin_dashboard()
    if read_only_deployment():
        abort(503, description="The demo administrator is disabled in read-only deployments.")
    if not session.get("collegehub_demo_admin"):
        return redirect(url_for("admin_login", next=request.path))
    with closing(get_db()) as db:
        counts = {
            "colleges": db.execute("SELECT COUNT(*) FROM colleges").fetchone()[0],
            "courses": db.execute("SELECT COUNT(*) FROM courses").fetchone()[0],
            "faqs": db.execute("SELECT COUNT(*) FROM faqs").fetchone()[0],
            "students": db.execute("SELECT COUNT(*) FROM student_profiles").fetchone()[0],
            "pending": db.execute(
                """SELECT COUNT(*) FROM colleges
                   WHERE information_status IN ('pending_verification','information_not_verified','outdated')"""
            ).fetchone()[0],
        }
        streams = db.execute("SELECT id, name FROM streams ORDER BY name").fetchall()
        stream_records = db.execute("SELECT * FROM streams ORDER BY name").fetchall()
        districts = db.execute("SELECT * FROM districts ORDER BY name").fetchall()
        academic_years = db.execute("SELECT * FROM academic_years ORDER BY label DESC").fetchall()
        colleges_for_admin = db.execute("""
            SELECT c.*, s.name AS stream_name FROM colleges c JOIN streams s ON s.id=c.stream_id
            ORDER BY c.name
        """).fetchall()
        courses_for_admin = db.execute("""
            SELECT cr.*, c.name AS college_name, source.source_name, source.source_url
            FROM courses cr
            JOIN colleges c ON c.id=cr.college_id
            LEFT JOIN information_sources source ON source.id=cr.source_id
            ORDER BY c.name, cr.name
        """).fetchall()
        faqs = db.execute("SELECT * FROM faqs ORDER BY id").fetchall()
        guidance = db.execute("""
            SELECT g.*, s.name AS stream_name FROM guidance_records g
            LEFT JOIN streams s ON s.id=g.stream_id ORDER BY s.name, g.category, g.id
        """).fetchall()
        fees = db.execute("""
            SELECT f.*, c.name AS college_name FROM fee_records f
            JOIN colleges c ON c.id=f.college_id ORDER BY c.name, f.academic_year DESC
        """).fetchall()
        cutoffs = db.execute("""
            SELECT x.*, c.name AS college_name FROM cutoff_records x
            JOIN colleges c ON c.id=x.college_id ORDER BY c.name, x.academic_year DESC
        """).fetchall()
        facilities = db.execute("""
            SELECT f.*, c.name AS college_name FROM facilities f
            JOIN colleges c ON c.id=f.college_id ORDER BY c.name, f.label
        """).fetchall()
        hostels = db.execute("""
            SELECT h.*, c.name AS college_name FROM hostel_information h
            JOIN colleges c ON c.id=h.college_id ORDER BY c.name, h.academic_year DESC
        """).fetchall()
        feedback = db.execute("SELECT * FROM student_feedback ORDER BY created_at DESC").fetchall()
    return render_template(
        "admin_dashboard.html", counts=counts, streams=streams, stream_records=stream_records,
        districts=districts, academic_years=academic_years,
        colleges=colleges_for_admin, courses=courses_for_admin,
        faqs=faqs, guidance=guidance, fees=fees, cutoffs=cutoffs,
        facilities=facilities, hostels=hostels, feedback=feedback,
        readonly=read_only_deployment(),
    )


@app.post("/admin/colleges")
@admin_required
def admin_add_college():
    name = request.form.get("name", "").strip()
    city = request.form.get("city", "").strip()
    district = request.form.get("district", "").strip()
    stream_id = request.form.get("stream_id", type=int)
    if not name or not city or not district or not stream_id:
        abort(400, description="College name, city, district and stream are required.")
    with closing(get_writable_db()) as db:
        db.execute(
            """INSERT INTO colleges
               (stream_id,name,city,district,description,information_status)
               VALUES (?,?,?,?,?,'information_not_verified')""",
            (stream_id, name, city, district, request.form.get("description", "").strip()),
        )
        db.execute("INSERT OR IGNORE INTO districts(name) VALUES (?)", (district,))
        db.commit()
    return redirect(url_for("admin_dashboard") + "#colleges")


@app.post("/admin/colleges/<int:college_id>/update")
@admin_required
def admin_update_college(college_id):
    name = request.form.get("name", "").strip()
    city = request.form.get("city", "").strip()
    district = request.form.get("district", "").strip()
    if not name or not city or not district:
        abort(400, description="College name, city and district are required.")
    hostel_value = request.form.get("hostel_available", "")
    hostel_available = {"yes": 1, "no": 0}.get(hostel_value)
    official_website = validate_web_url(request.form.get("official_website", ""), "Official website")
    with closing(get_writable_db()) as db:
        cursor = db.execute("""
            UPDATE colleges SET name=?, city=?, district=?, description=?, category=?,
                ownership=?, official_website=?, hostel_available=?, information_status='pending_verification'
            WHERE id=?
        """, (
            name, city, district, request.form.get("description", "").strip(),
            request.form.get("category", "").strip() or None,
            request.form.get("ownership", "").strip() or None,
            official_website,
            hostel_available, college_id,
        ))
        if cursor.rowcount == 0:
            abort(404)
        db.execute("INSERT OR IGNORE INTO districts(name) VALUES (?)", (district,))
        db.commit()
    return redirect(url_for("admin_dashboard") + "#colleges")


@app.post("/admin/colleges/<int:college_id>/verify")
@admin_required
def admin_verify_college(college_id):
    status = request.form.get("verification_status", "information_not_verified")
    if status not in VERIFICATION_STATES:
        abort(400, description="Unsupported verification status.")
    source_name = request.form.get("source_name", "").strip()
    source_url = validate_web_url(request.form.get("source_url", ""), "Source URL")
    academic_year = request.form.get("academic_year", "").strip()
    last_verified = request.form.get("last_verified", "").strip()
    if status == "verified" and not all((source_name, source_url, academic_year, last_verified)):
        abort(400, description="Verified college information requires a source, academic year and verification date.")
    with closing(get_writable_db()) as db:
        if db.execute("SELECT 1 FROM colleges WHERE id=?", (college_id,)).fetchone() is None:
            abort(404)
        source_cursor = db.execute("""
            INSERT INTO information_sources
                (college_id,source_name,source_url,academic_year,last_verified,verification_status)
            VALUES (?,?,?,?,?,?)
        """, (
            college_id, source_name or "Source not provided", source_url or None,
            academic_year or None, last_verified or None, status,
        ))
        db.execute("""
            UPDATE colleges SET information_status=?,academic_year=? WHERE id=?
        """, (status, academic_year or None, college_id))
        db.execute("""
            INSERT INTO verification_records
                (college_id,record_type,source_id,academic_year,last_verified,status)
            VALUES (?,'college',?,?,?,?)
        """, (college_id, source_cursor.lastrowid, academic_year or None, last_verified or None, status))
        db.commit()
    return redirect(url_for("admin_dashboard") + "#admin-colleges")


@app.post("/admin/colleges/<int:college_id>/delete")
@admin_required
def admin_delete_college(college_id):
    with closing(get_writable_db()) as db:
        if db.execute("SELECT 1 FROM colleges WHERE id=?", (college_id,)).fetchone() is None:
            abort(404)
        for table in (
            "courses", "facilities", "fee_records", "cutoff_records",
            "hostel_information", "information_sources", "verification_records",
        ):
            db.execute(f"DELETE FROM {table} WHERE college_id=?", (college_id,))
        db.execute("DELETE FROM colleges WHERE id=?", (college_id,))
        db.commit()
    return redirect(url_for("admin_dashboard") + "#colleges")


@app.post("/admin/courses")
@admin_required
def admin_add_course():
    college_id = request.form.get("college_id", type=int)
    name = request.form.get("name", "").strip()
    if not college_id or not name:
        abort(400, description="College and course name are required.")
    with closing(get_writable_db()) as db:
        db.execute(
            "INSERT INTO courses(college_id,name,level,duration) VALUES (?,?,?,?)",
            (college_id, name, request.form.get("level", "").strip(), request.form.get("duration", "").strip()),
        )
        db.commit()
    return redirect(url_for("admin_dashboard") + "#courses")


@app.post("/admin/courses/<int:course_id>/update")
@admin_required
def admin_update_course(course_id):
    name = request.form.get("name", "").strip()
    if not name:
        abort(400, description="Course name is required.")
    with closing(get_writable_db()) as db:
        cursor = db.execute(
            """UPDATE courses SET name=?,level=?,duration=?,academic_year=NULL,source_id=NULL,
               last_verified=NULL,verification_status='pending_verification' WHERE id=?""",
            (name, request.form.get("level", "").strip(),
             request.form.get("duration", "").strip(), course_id),
        )
        if cursor.rowcount == 0:
            abort(404)
        db.commit()
    return redirect(url_for("admin_dashboard") + "#courses")


@app.post("/admin/courses/<int:course_id>/delete")
@admin_required
def admin_delete_course(course_id):
    with closing(get_writable_db()) as db:
        if db.execute("SELECT 1 FROM courses WHERE id=?", (course_id,)).fetchone() is None:
            abort(404)
        db.execute(
            "DELETE FROM verification_records WHERE record_type='courses' AND record_id=?",
            (course_id,),
        )
        db.execute("""
            DELETE FROM verification_records WHERE record_type IN ('fees','cutoffs')
            AND record_id IN (
                SELECT id FROM fee_records WHERE course_id=?
                UNION SELECT id FROM cutoff_records WHERE course_id=?
            )
        """, (course_id, course_id))
        db.execute("DELETE FROM fee_records WHERE course_id=?", (course_id,))
        db.execute("DELETE FROM cutoff_records WHERE course_id=?", (course_id,))
        db.execute("DELETE FROM courses WHERE id=?", (course_id,))
        db.commit()
    return redirect(url_for("admin_dashboard") + "#courses")


@app.post("/admin/faqs")
@admin_required
def admin_add_faq():
    question = request.form.get("question", "").strip()
    answer = request.form.get("answer", "").strip()
    if not question or not answer:
        abort(400, description="Question and answer are required.")
    with closing(get_writable_db()) as db:
        db.execute("INSERT INTO faqs(question,answer) VALUES (?,?)", (question, answer))
        db.commit()
    return redirect(url_for("admin_dashboard") + "#faqs")


@app.post("/admin/faqs/<int:faq_id>/update")
@admin_required
def admin_update_faq(faq_id):
    with closing(get_writable_db()) as db:
        cursor = db.execute(
            """UPDATE faqs SET question=?,answer=?,source_name=NULL,source_url=NULL,
               academic_year=NULL,last_verified=NULL,verification_status='pending_verification'
               WHERE id=?""",
            (request.form.get("question", "").strip(), request.form.get("answer", "").strip(), faq_id),
        )
        if cursor.rowcount == 0:
            abort(404)
        db.commit()
    return redirect(url_for("admin_dashboard") + "#faqs")


@app.post("/admin/faqs/<int:faq_id>/delete")
@admin_required
def admin_delete_faq(faq_id):
    with closing(get_writable_db()) as db:
        if db.execute("SELECT 1 FROM faqs WHERE id=?", (faq_id,)).fetchone() is None:
            abort(404)
        db.execute("DELETE FROM faqs WHERE id=?", (faq_id,))
        db.commit()
    return redirect(url_for("admin_dashboard") + "#faqs")


@app.post("/admin/faqs/<int:faq_id>/verify")
@admin_required
def admin_verify_faq(faq_id):
    status = request.form.get("verification_status", "information_not_verified")
    if status not in VERIFICATION_STATES:
        abort(400, description="Unsupported verification status.")
    source_name = request.form.get("source_name", "").strip()
    source_url = validate_web_url(request.form.get("source_url", ""), "Source URL")
    academic_year = request.form.get("academic_year", "").strip()
    last_verified = request.form.get("last_verified", "").strip()
    if status == "verified" and not all((source_name, source_url, academic_year, last_verified)):
        abort(400, description="Verified FAQs require a source, academic year and verification date.")
    with closing(get_writable_db()) as db:
        if db.execute("SELECT 1 FROM faqs WHERE id=?", (faq_id,)).fetchone() is None:
            abort(404)
        source_cursor = db.execute("""
            INSERT INTO information_sources
                (source_name,source_url,academic_year,last_verified,verification_status)
            VALUES (?,?,?,?,?)
        """, (source_name or "Source not provided", source_url, academic_year or None, last_verified or None, status))
        db.execute("""
            UPDATE faqs SET source_name=?,source_url=?,academic_year=?,last_verified=?,
                verification_status=? WHERE id=?
        """, (
            source_name or None, source_url, academic_year or None,
            last_verified or None, status, faq_id,
        ))
        db.execute("""
            INSERT INTO verification_records
                (record_type,record_id,source_id,academic_year,last_verified,status)
            VALUES ('faq',?,?,?,?,?)
        """, (faq_id, source_cursor.lastrowid, academic_year or None, last_verified or None, status))
        db.commit()
    return redirect(url_for("admin_dashboard") + "#faqs")


@app.post("/admin/guidance/<int:guidance_id>/verify")
@admin_required
def admin_verify_guidance(guidance_id):
    status = request.form.get("verification_status", "information_not_verified")
    if status not in VERIFICATION_STATES:
        abort(400, description="Unsupported verification status.")
    heading = request.form.get("heading", "").strip()
    content = request.form.get("content", "").strip()
    if not heading or not content:
        abort(400, description="Guidance heading and content are required.")
    source_name = request.form.get("source_name", "").strip()
    source_url = validate_web_url(request.form.get("source_url", ""), "Source URL")
    academic_year = request.form.get("academic_year", "").strip()
    last_verified = request.form.get("last_verified", "").strip()
    if status == "verified" and not all((source_name, source_url, academic_year, last_verified)):
        abort(400, description="Verified guidance requires a source, academic year and verification date.")
    with closing(get_writable_db()) as db:
        cursor = db.execute("""
            UPDATE guidance_records SET heading=?,content=?,verification_status=?,source_name=?,
                source_url=?,academic_year=?,last_verified=? WHERE id=?
        """, (
            heading, content, status, source_name or None, source_url,
            academic_year or None, last_verified or None, guidance_id,
        ))
        if cursor.rowcount == 0:
            abort(404)
        db.commit()
    return redirect(url_for("admin_dashboard") + "#guidance")


@app.post("/admin/streams")
@admin_required
def admin_add_stream():
    slug = request.form.get("slug", "").strip().lower()
    name = request.form.get("name", "").strip()
    if not slug or not name:
        abort(400, description="Stream name and slug are required.")
    with closing(get_writable_db()) as db:
        db.execute(
            "INSERT INTO streams(slug,name,icon) VALUES (?,?,?)",
            (slug, name, request.form.get("icon", "").strip()),
        )
        db.commit()
    return redirect(url_for("admin_dashboard") + "#streams")


@app.post("/admin/streams/<int:stream_id>/update")
@admin_required
def admin_update_stream(stream_id):
    with closing(get_writable_db()) as db:
        cursor = db.execute(
            "UPDATE streams SET slug=?,name=?,icon=? WHERE id=?",
            (request.form.get("slug", "").strip().lower(), request.form.get("name", "").strip(),
             request.form.get("icon", "").strip(), stream_id),
        )
        if cursor.rowcount == 0:
            abort(404)
        db.commit()
    return redirect(url_for("admin_dashboard") + "#streams")


@app.post("/admin/streams/<int:stream_id>/delete")
@admin_required
def admin_delete_stream(stream_id):
    with closing(get_writable_db()) as db:
        if db.execute("SELECT 1 FROM streams WHERE id=?", (stream_id,)).fetchone() is None:
            abort(404)
        if db.execute("SELECT 1 FROM colleges WHERE stream_id=? LIMIT 1", (stream_id,)).fetchone():
            abort(409, description="This stream is used by existing college records.")
        db.execute("DELETE FROM guidance_records WHERE stream_id=?", (stream_id,))
        db.execute("DELETE FROM streams WHERE id=?", (stream_id,))
        db.commit()
    return redirect(url_for("admin_dashboard") + "#streams")


@app.post("/admin/academic-years")
@admin_required
def admin_add_academic_year():
    label = request.form.get("label", "").strip()
    if not label:
        abort(400, description="Academic year label is required.")
    with closing(get_writable_db()) as db:
        db.execute(
            "INSERT INTO academic_years(label,start_date,end_date) VALUES (?,?,?)",
            (label, request.form.get("start_date") or None, request.form.get("end_date") or None),
        )
        db.commit()
    return redirect(url_for("admin_dashboard") + "#streams")


@app.post("/admin/academic-years/<int:year_id>/update")
@admin_required
def admin_update_academic_year(year_id):
    label = request.form.get("label", "").strip()
    if not label:
        abort(400, description="Academic year label is required.")
    with closing(get_writable_db()) as db:
        cursor = db.execute(
            "UPDATE academic_years SET label=?,start_date=?,end_date=? WHERE id=?",
            (label, request.form.get("start_date") or None, request.form.get("end_date") or None, year_id),
        )
        if cursor.rowcount == 0:
            abort(404)
        db.commit()
    return redirect(url_for("admin_dashboard") + "#streams")


@app.post("/admin/academic-years/<int:year_id>/delete")
@admin_required
def admin_delete_academic_year(year_id):
    with closing(get_writable_db()) as db:
        cursor = db.execute("DELETE FROM academic_years WHERE id=?", (year_id,))
        if cursor.rowcount == 0:
            abort(404)
        db.commit()
    return redirect(url_for("admin_dashboard") + "#streams")

@app.post("/admin/districts")
@admin_required
def admin_add_district():
    name = request.form.get("name", "").strip()
    if not name:
        abort(400, description="District name is required.")
    with closing(get_writable_db()) as db:
        db.execute("INSERT OR IGNORE INTO districts(name) VALUES (?)", (name,))
        db.commit()
    return redirect(url_for("admin_dashboard") + "#streams")


@app.post("/admin/districts/<int:district_id>/delete")
@admin_required
def admin_delete_district(district_id):
    with closing(get_writable_db()) as db:
        district = db.execute("SELECT name FROM districts WHERE id=?", (district_id,)).fetchone()
        if district is None:
            abort(404)
        if db.execute("SELECT 1 FROM colleges WHERE district=? LIMIT 1", (district["name"],)).fetchone():
            abort(409, description="This district is used by existing college records.")
        db.execute("DELETE FROM districts WHERE id=?", (district_id,))
        db.commit()
    return redirect(url_for("admin_dashboard") + "#streams")


@app.post("/admin/records/<record_type>")
@admin_required
def admin_add_record(record_type):
    config = ADMIN_RECORDS.get(record_type)
    if config is None:
        abort(404)
    values = parse_admin_record_values(config)
    columns = list(config["fields"])
    if config["verification_column"]:
        columns.append(config["verification_column"])
        values.append("information_not_verified")
    placeholders = ",".join("?" for _ in columns)
    with closing(get_writable_db()) as db:
        db.execute(
            f"INSERT INTO {config['table']} ({','.join(columns)}) VALUES ({placeholders})",
            values,
        )
        db.commit()
    return redirect(url_for("admin_dashboard") + f"#{record_type}")


@app.post("/admin/records/<record_type>/<int:record_id>/update")
@admin_required
def admin_update_record(record_type, record_id):
    config = ADMIN_RECORDS.get(record_type)
    if config is None:
        abort(404)
    values = parse_admin_record_values(config)
    assignments = ",".join(f"{field}=?" for field in config["fields"])
    with closing(get_writable_db()) as db:
        cursor = db.execute(
            f"UPDATE {config['table']} SET {assignments} WHERE id=?",
            (*values, record_id),
        )
        if cursor.rowcount == 0:
            abort(404)
        if config["verification_column"]:
            db.execute(
                f"""UPDATE {config['table']} SET {config['verification_column']}='pending_verification',
                    source_id=NULL,academic_year=NULL,last_verified=NULL WHERE id=?""",
                (record_id,),
            )
        db.commit()
    return redirect(url_for("admin_dashboard") + f"#{record_type}")


@app.post("/admin/records/<record_type>/<int:record_id>/delete")
@admin_required
def admin_delete_record(record_type, record_id):
    config = ADMIN_RECORDS.get(record_type)
    if config is None:
        abort(404)
    with closing(get_writable_db()) as db:
        record = db.execute(
            f"SELECT id FROM {config['table']} WHERE id=?", (record_id,)
        ).fetchone()
        if record is None:
            abort(404)
        db.execute(
            "DELETE FROM verification_records WHERE record_type=? AND record_id=?",
            (record_type, record_id),
        )
        db.execute(f"DELETE FROM {config['table']} WHERE id=?", (record_id,))
        db.commit()
    return redirect(url_for("admin_dashboard") + f"#{record_type}")


@app.post("/admin/records/<record_type>/<int:record_id>/verify")
@admin_required
def admin_verify_record(record_type, record_id):
    config = ADMIN_RECORDS.get(record_type)
    if config is None or not config["verification_column"]:
        abort(404)
    status = request.form.get("verification_status", "information_not_verified")
    if status not in VERIFICATION_STATES:
        abort(400, description="Unsupported verification status.")
    source_name = request.form.get("source_name", "").strip()
    source_url = validate_web_url(request.form.get("source_url", ""), "Source URL")
    academic_year = request.form.get("academic_year", "").strip()
    last_verified = request.form.get("last_verified", "").strip()
    if status == "verified" and not all((source_name, source_url, academic_year, last_verified)):
        abort(400, description="Verified information requires a source, academic year and verification date.")
    with closing(get_writable_db()) as db:
        record = db.execute(
            f"SELECT college_id FROM {config['table']} WHERE id=?", (record_id,)
        ).fetchone()
        if record is None:
            abort(404)
        source_cursor = db.execute("""
            INSERT INTO information_sources
                (college_id,source_name,source_url,academic_year,last_verified,verification_status)
            VALUES (?,?,?,?,?,?)
        """, (
            record["college_id"], source_name or "Source not provided", source_url,
            academic_year or None, last_verified or None, status,
        ))
        db.execute(
            f"""UPDATE {config['table']} SET {config['verification_column']}=?,source_id=?,
                academic_year=?,last_verified=? WHERE id=?""",
            (status, source_cursor.lastrowid, academic_year or None, last_verified or None, record_id),
        )
        db.execute("""
            INSERT INTO verification_records
                (college_id,record_type,record_id,source_id,academic_year,last_verified,status)
            VALUES (?,?,?,?,?,?,?)
        """, (
            record["college_id"], record_type, record_id, source_cursor.lastrowid,
            academic_year or None, last_verified or None, status,
        ))
        db.commit()
    return redirect(url_for("admin_dashboard") + f"#{record_type}")

@app.post("/admin/feedback/<int:feedback_id>")
@admin_required
def admin_moderate_feedback(feedback_id):
    status = request.form.get("status", "")
    if status not in {"pending", "approved", "rejected"}:
        abort(400, description="Unsupported feedback status.")
    with closing(get_writable_db()) as db:
        cursor = db.execute("UPDATE student_feedback SET status=? WHERE id=?", (status, feedback_id))
        if cursor.rowcount == 0:
            abort(404)
        db.commit()
    return redirect(url_for("admin_dashboard") + "#feedback")


@app.get("/health")
def health():
    try:
        db = current_app.config["UNIVERSAL_DATABASE"]
        with db.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        current_app.logger.error("Database health check failed (%s).", type(error).__name__)
        return jsonify(status="unavailable", database="unavailable"), 503
    return jsonify(status="ok", database="connected")


@contextmanager
def universal_session():
    db_session = current_app.config["UNIVERSAL_DATABASE"].session()
    try:
        yield db_session
    except (OperationalError, ProgrammingError):
        current_app.logger.exception("Universal database query failed.")
        abort(503, description="The universal database is unavailable or not migrated.")
    finally:
        db_session.close()


def database_colleges_page():
    filters = {
        "name": request.args.get("q", "").strip() or None,
        "district": request.args.get("district", "").strip() or None,
        "category": request.args.get("category", "").strip() or None,
        "institution_type": request.args.get("type", "").strip() or None,
        "program_name": request.args.get("program", "").strip() or None,
        "affiliation": request.args.get("affiliation", "").strip() or None,
        "accreditation": request.args.get("accreditation", "").strip() or None,
        "facility_code": request.args.get("facility", "").strip() or None,
    }
    if any(value and len(value) > 200 for value in filters.values()):
        abort(400, description="Search filters must be 200 characters or fewer.")
    page = parse_api_integer("page", default=1, minimum=1, maximum=100_000)
    per_page = parse_api_integer("per_page", default=25, minimum=1, maximum=100)
    sort = request.args.get("sort", "name")
    if sort not in {"name", "district"}:
        abort(400, description="Sort must be name or district.")

    with universal_session() as db_session:
        service = InstitutionService(db_session)
        total = service.count(**filters)
        pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, pages)
        institutions = service.search(
            **filters,
            sort_by=sort,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        categories = db_session.scalars(
            select(InstitutionCategory).order_by(InstitutionCategory.name)
        ).all()
        institution_types = db_session.scalars(
            select(InstitutionType).order_by(InstitutionType.name)
        ).all()
        districts = db_session.scalars(
            select(Institution.district)
            .where(Institution.district.is_not(None))
            .distinct()
            .order_by(Institution.district)
        ).all()
        programs = db_session.scalars(
            select(Program.name).distinct().order_by(Program.name)
        ).all()
        facilities = db_session.execute(
            select(Facility.code, Facility.name).order_by(Facility.name)
        ).all()
    return render_template(
        "database/colleges.html",
        institutions=institutions,
        categories=categories,
        institution_types=institution_types,
        districts=districts,
        programs=programs,
        facilities=facilities,
        filters=filters,
        page=page,
        pages=pages,
        per_page=per_page,
        sort=sort,
        total=total,
    )


def database_college_detail_page(institution_id: int):
    with universal_session() as db_session:
        service = InstitutionService(db_session)
        institution = service.profile(institution_id)
        if institution is None:
            abort(404)
        admissions = AdmissionService(db_session).records(institution_id)
        fees = FeeService(db_session).structures(institution_id)
        placements = db_session.scalars(
            select(PlacementReport)
            .where(PlacementReport.institution_id == institution_id)
            .order_by(PlacementReport.reporting_year.desc())
        ).all()
        facilities = db_session.scalars(
            select(InstitutionFacility)
            .where(InstitutionFacility.institution_id == institution_id)
            .order_by(InstitutionFacility.id)
        ).all()
        return render_template(
            "database/college_detail.html",
            institution=institution,
            admissions=admissions,
            fees=fees,
            placements=placements,
            facilities=facilities,
        )


def database_compare_page():
    raw_ids = request.args.get("ids", "")
    try:
        ids = [int(value) for value in raw_ids.split(",") if value]
    except ValueError:
        abort(400, description="ids must be comma-separated positive institution IDs.")
    if len(ids) > 5 or any(value < 1 for value in ids):
        abort(400, description="Provide up to five positive institution IDs.")
    ids = list(dict.fromkeys(ids))
    with universal_session() as db_session:
        service = InstitutionService(db_session)
        institutions = [
            service.profile(institution.id)
            for institution in service.compare(ids)
        ] if ids else []
        return render_template("database/compare.html", institutions=institutions)


def database_recommendations_page():
    program = request.args.get("program", "").strip()
    district = request.args.get("district", "").strip()
    category = request.args.get("category", "").strip()
    institution_type = request.args.get("type", "").strip()
    if any(len(value) > 200 for value in (program, district, category, institution_type)):
        abort(400, description="Recommendation filters must be 200 characters or fewer.")
    categories = []
    districts = []
    institution_types = []
    results = []
    with universal_session() as db_session:
        categories = db_session.scalars(
            select(InstitutionCategory).order_by(InstitutionCategory.name)
        ).all()
        districts = db_session.scalars(
            select(Institution.district)
            .where(Institution.district.is_not(None))
            .distinct()
            .order_by(Institution.district)
        ).all()
        institution_types = db_session.scalars(
            select(InstitutionType).order_by(InstitutionType.name)
        ).all()
        has_preferences = any((program, district, category, institution_type))
        if has_preferences:
            candidates = InstitutionService(db_session).search(
                name=None,
                district=district or None,
                category=category or None,
                institution_type=institution_type or None,
                program_name=program or None,
                limit=100,
            )
            results = [
                candidate
                for candidate in candidates
                if candidate.provenance.verification_status == "verified"
                and candidate.provenance.source_id is not None
                and candidate.provenance.verification_date is not None
                and any(
                    item.provenance.verification_status == "verified"
                    and item.provenance.source_id is not None
                    for item in candidate.programs
                )
            ]
        return render_template(
            "database/recommendations.html",
            categories=categories,
            districts=districts,
            institution_types=institution_types,
            results=results,
            selected_program=program,
            selected_district=district,
            selected_category=category,
            selected_type=institution_type,
            has_preferences=any((program, district, category, institution_type)),
        )


def database_cutoffs_page():
    measurement_types = ("rank", "score", "marks", "percentage", "cutoff_score", "merit_position")
    institution_id_raw = request.args.get("institution", "").strip()
    year = request.args.get("year", "").strip()
    measurement_type = request.args.get("metric", "cutoff_score").strip()
    student_category = request.args.get("category", "").strip().upper()
    quota = request.args.get("quota", "").strip()
    search = request.args.get("q", "").strip()
    if len(search) > 200 or len(quota) > 100:
        abort(400, description="Search text must be 200 characters or fewer.")
    try:
        institution_id = int(institution_id_raw) if institution_id_raw else None
    except ValueError:
        abort(400, description="Institution ID must be an integer.")
    if institution_id is not None and institution_id < 1:
        abort(400, description="Institution ID must be positive.")
    if measurement_type and measurement_type not in measurement_types:
        abort(400, description="Select a supported admission measurement type.")
    if student_category and student_category not in {"OC", "BC", "MBC", "SC", "ST", "BCM", "SCA"}:
        abort(400, description="Select a valid student category.")

    with universal_session() as db_session:
        institutions = db_session.scalars(select(Institution).order_by(Institution.official_name)).all()
        years = db_session.scalars(
            select(AcademicYear.label).join(AdmissionRecord, AdmissionRecord.academic_year_id == AcademicYear.id)
            .distinct().order_by(AcademicYear.label.desc())
        ).all()
        categories = db_session.scalars(
            select(AdmissionRecord.student_category).where(AdmissionRecord.student_category.is_not(None))
            .distinct().order_by(AdmissionRecord.student_category)
        ).all()
        if not year and "2024" in years:
            year = "2024"
        statement = select(AdmissionRecord).order_by(
            AdmissionRecord.academic_year_id.desc(), AdmissionRecord.institution_id,
            AdmissionRecord.program_id, AdmissionRecord.student_category,
        )
        if institution_id is not None:
            statement = statement.where(AdmissionRecord.institution_id == institution_id)
        if year:
            statement = statement.where(AdmissionRecord.academic_year.has(AcademicYear.label == year))
        if measurement_type:
            statement = statement.where(AdmissionRecord.measurement_type == measurement_type)
        if student_category:
            statement = statement.where(AdmissionRecord.student_category == student_category)
        if quota:
            statement = statement.where(AdmissionRecord.quota == quota)
        if search:
            pattern = f"%{search}%"
            statement = statement.where(
                AdmissionRecord.institution.has(Institution.official_name.ilike(pattern))
                | AdmissionRecord.program.has(Program.name.ilike(pattern))
                | AdmissionRecord.program.has(Program.code.ilike(pattern))
                | AdmissionRecord.institution.has(Institution.institution_code.ilike(pattern))
            )
        records = db_session.scalars(statement.limit(1000)).all()
        return render_template(
            "database/cutoffs.html", institutions=institutions, years=years,
            categories=categories, records=records, measurement_types=measurement_types,
            selected_institution=institution_id, selected_year=year,
            selected_metric=measurement_type, selected_category=student_category,
            selected_quota=quota, selected_search=search,
        )


def parse_api_integer(name, *, default, minimum, maximum):
    raw_value = request.args.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        abort(400, description=f"{name} must be an integer.")
    if value < minimum or value > maximum:
        abort(400, description=f"{name} must be between {minimum} and {maximum}.")
    return value


def serialize_provenance(provenance):
    source = provenance.source
    return {
        "verification_status": provenance.verification_status,
        "academic_year": provenance.academic_year.label if provenance.academic_year else None,
        "collection_date": provenance.collection_date.isoformat() if provenance.collection_date else None,
        "verification_date": provenance.verification_date.isoformat() if provenance.verification_date else None,
        "reviewer": provenance.reviewer,
        "source": {
            "url": source.source_url,
            "organisation": source.source_organisation,
            "document_title": source.document_title,
            "publication_date": source.publication_date.isoformat() if source.publication_date else None,
        } if source else None,
    }


def serialize_institution(institution, *, profile=False):
    result = {
        "id": institution.id,
        "official_name": institution.official_name,
        "institution_code": institution.institution_code,
        "category": {"code": institution.category.code, "name": institution.category.name},
        "institution_type": {
            "code": institution.institution_type.code,
            "name": institution.institution_type.name,
        },
        "district": institution.district,
        "city": institution.city,
        "official_website": institution.official_website,
        "operational_status": institution.operational_status,
        "verification": serialize_provenance(institution.provenance),
    }
    if not profile:
        return result
    result.update({
        "address": institution.address,
        "contact_email": institution.contact_email,
        "contact_phone": institution.contact_phone,
        "establishment_year": institution.establishment_year,
        "programs": [{
            "id": program.id,
            "name": program.name,
            "award": program.award,
            "level": program.level,
            "category": program.category.code,
            "verification": serialize_provenance(program.provenance),
        } for program in institution.programs],
        "university": {
            "institution_id": institution.university.institution_id,
            "official_name": institution.university.institution.official_name,
            "establishment_act": institution.university.establishment_act,
            "registration_code": institution.university.registration_code,
            "verification": serialize_provenance(institution.university.provenance),
        } if institution.university else None,
        "affiliations": [{
            "university_id": affiliation.university_id,
            "university_name": affiliation.university.institution.official_name,
            "affiliation_code": affiliation.affiliation_code,
            "status": affiliation.status,
            "valid_from_year": affiliation.valid_from_year.label if affiliation.valid_from_year else None,
            "valid_until_year": affiliation.valid_until_year.label if affiliation.valid_until_year else None,
            "verification": serialize_provenance(affiliation.provenance),
        } for affiliation in institution.affiliations],
        "campuses": [{
            "id": campus.id,
            "name": campus.name,
            "city": campus.city,
            "district": campus.district,
            "address": campus.address,
            "is_main_campus": campus.is_main_campus,
            "verification": serialize_provenance(campus.provenance),
        } for campus in institution.campuses],
        "departments": [{
            "id": department.id,
            "name": department.name,
            "code": department.code,
            "verification": serialize_provenance(department.provenance),
        } for department in institution.departments],
        "accreditations": [{
            "agency": accreditation.agency,
            "grade": accreditation.grade,
            "awarded_on": accreditation.awarded_on.isoformat() if accreditation.awarded_on else None,
            "valid_until": accreditation.valid_until.isoformat() if accreditation.valid_until else None,
            "verification": serialize_provenance(accreditation.provenance),
        } for accreditation in institution.accreditations],
    })
    return result


@app.get("/api/institutions")
def api_institutions():
    limit = parse_api_integer("limit", default=25, minimum=1, maximum=100)
    offset = parse_api_integer("offset", default=0, minimum=0, maximum=100_000)
    sort_by = request.args.get("sort", "name")
    if sort_by not in {"name", "district"}:
        abort(400, description="sort must be name or district.")
    filters = {
        "name": request.args.get("q", "").strip() or None,
        "district": request.args.get("district", "").strip() or None,
        "category": request.args.get("category", "").strip() or None,
        "institution_type": request.args.get("type", "").strip() or None,
        "program_name": request.args.get("program", "").strip() or None,
        "affiliation": request.args.get("affiliation", "").strip() or None,
        "accreditation": request.args.get("accreditation", "").strip() or None,
        "facility_code": request.args.get("facility", "").strip() or None,
    }
    if any(value and len(value) > 200 for value in filters.values() if isinstance(value, str)):
        abort(400, description="Search filters must be 200 characters or fewer.")
    with universal_session() as db_session:
        service = InstitutionService(db_session)
        total = service.count(**filters)
        institutions = service.search(
            **filters, limit=limit, offset=offset, sort_by=sort_by
        )
        return jsonify(
            items=[serialize_institution(item) for item in institutions],
            total=total,
            limit=limit,
            offset=offset,
        )


@app.get("/api/institutions/<int:institution_id>")
def api_institution_profile(institution_id):
    with universal_session() as db_session:
        institution = InstitutionService(db_session).profile(institution_id)
        if institution is None:
            abort(404)
        return jsonify(item=serialize_institution(institution, profile=True))


@app.get("/api/programs")
def api_programs():
    limit = parse_api_integer("limit", default=50, minimum=1, maximum=100)
    offset = parse_api_integer("offset", default=0, minimum=0, maximum=100_000)
    institution_id = request.args.get("institution_id")
    try:
        parsed_institution_id = int(institution_id) if institution_id else None
    except ValueError:
        abort(400, description="institution_id must be an integer.")
    if parsed_institution_id is not None and parsed_institution_id < 1:
        abort(400, description="institution_id must be a positive integer.")
    filters = {
        "name": request.args.get("q", "").strip() or None,
        "institution_id": parsed_institution_id,
        "category": request.args.get("category", "").strip() or None,
    }
    with universal_session() as db_session:
        service = ProgramService(db_session)
        total = service.count(**filters)
        programs = service.search(**filters, limit=limit, offset=offset)
        return jsonify(items=[{
            "id": program.id,
            "institution_id": program.institution_id,
            "institution_name": program.institution.official_name,
            "name": program.name,
            "award": program.award,
            "level": program.level,
            "category": program.category.code,
            "verification": serialize_provenance(program.provenance),
        } for program in programs], total=total, limit=limit, offset=offset)


@app.get("/api/institutions/<int:institution_id>/admissions")
def api_admission_records(institution_id):
    with universal_session() as db_session:
        records = AdmissionService(db_session).records(institution_id)
        return jsonify(items=[{
            "id": record.id,
            "program": record.program.name,
            "academic_year": record.academic_year.label,
            "authority": record.admission_authority.name if record.admission_authority else None,
            "route": record.admission_route.name if record.admission_route else None,
            "counselling_round": record.counselling_round.name if record.counselling_round else None,
            "student_category": record.student_category,
            "quota": record.quota,
            "measurement_type": record.measurement_type,
            "measurement_value": str(record.measurement_value),
            "measurement_unit": record.measurement_unit,
            "provenance": serialize_provenance(record.provenance),
        } for record in records])


@app.get("/api/institutions/<int:institution_id>/fees")
def api_fee_structures(institution_id):
    with universal_session() as db_session:
        structures = FeeService(db_session).structures(institution_id)
        return jsonify(items=[{
            "id": structure.id,
            "program": structure.program.name if structure.program else None,
            "academic_year": structure.academic_year.label,
            "student_category": structure.student_category,
            "currency": structure.currency,
            "provenance": serialize_provenance(structure.provenance),
            "components": [{
                "type": component.component_type,
                "name": component.name,
                "amount": str(component.amount),
                "currency": structure.currency,
                "provenance": serialize_provenance(component.provenance),
            } for component in structure.components],
        } for structure in structures])


@app.get("/api/institutions/<int:institution_id>/placements")
def api_placement_reports(institution_id):
    with universal_session() as db_session:
        reports = db_session.scalars(
            select(PlacementReport)
            .where(PlacementReport.institution_id == institution_id)
            .order_by(PlacementReport.reporting_year.desc())
        ).all()
        return jsonify(items=[{
            "id": report.id,
            "program": report.program.name if report.program else None,
            "reporting_year": report.reporting_year,
            "eligible_students": report.eligible_students,
            "placed_students": report.placed_students,
            "median_salary": str(report.median_salary) if report.median_salary is not None else None,
            "highest_salary": str(report.highest_salary) if report.highest_salary is not None else None,
            "placement_percentage": (
                str(report.placement_percentage)
                if report.placement_percentage is not None else None
            ),
            "provenance": serialize_provenance(report.provenance),
        } for report in reports])


@app.get("/api/admissions")
def api_admission_analytics():
    limit = parse_api_integer("limit", default=50, minimum=1, maximum=100)
    offset = parse_api_integer("offset", default=0, minimum=0, maximum=100_000)
    supported_measurements = {
        "rank", "score", "marks", "percentage", "cutoff_score", "merit_position"
    }
    measurement_type = request.args.get("metric", "").strip() or None
    if measurement_type and measurement_type not in supported_measurements:
        abort(400, description="Select a supported admission measurement type.")
    institution_id_raw = request.args.get("institution_id")
    try:
        institution_id = int(institution_id_raw) if institution_id_raw else None
    except ValueError:
        abort(400, description="institution_id must be an integer.")
    if institution_id is not None and institution_id < 1:
        abort(400, description="institution_id must be positive.")
    year = request.args.get("year", "").strip() or None
    category = request.args.get("category", "").strip() or None
    quota = request.args.get("quota", "").strip() or None
    if any(value and len(value) > 100 for value in (year, category, quota)):
        abort(400, description="Admission filters must be 100 characters or fewer.")

    with universal_session() as db_session:
        ids = select(AdmissionRecord.id)
        statement = select(AdmissionRecord)
        if institution_id is not None:
            ids = ids.where(AdmissionRecord.institution_id == institution_id)
            statement = statement.where(AdmissionRecord.institution_id == institution_id)
        if measurement_type:
            ids = ids.where(AdmissionRecord.measurement_type == measurement_type)
            statement = statement.where(AdmissionRecord.measurement_type == measurement_type)
        if year:
            ids = ids.where(AdmissionRecord.academic_year.has(AcademicYear.label == year))
            statement = statement.where(
                AdmissionRecord.academic_year.has(AcademicYear.label == year)
            )
        if category:
            ids = ids.where(AdmissionRecord.student_category == category)
            statement = statement.where(AdmissionRecord.student_category == category)
        if quota:
            ids = ids.where(AdmissionRecord.quota == quota)
            statement = statement.where(AdmissionRecord.quota == quota)
        total = db_session.scalar(
            select(func.count()).select_from(ids.subquery())
        ) or 0
        records = db_session.scalars(
            statement.order_by(
                AdmissionRecord.academic_year_id.desc(),
                AdmissionRecord.institution_id,
                AdmissionRecord.program_id,
            ).limit(limit).offset(offset)
        ).all()
        return jsonify(
            items=[{
                "id": record.id,
                "institution_id": record.institution_id,
                "institution_name": record.institution.official_name,
                "program_id": record.program_id,
                "program_name": record.program.name,
                "academic_year": record.academic_year.label,
                "student_category": record.student_category,
                "quota": record.quota,
                "measurement_type": record.measurement_type,
                "measurement_value": str(record.measurement_value),
                "measurement_unit": record.measurement_unit,
                "provenance": serialize_provenance(record.provenance),
            } for record in records],
            total=total,
            limit=limit,
            offset=offset,
        )


@app.get("/api/institutions/compare")
def api_compare_institutions():
    raw_ids = request.args.get("ids", "")
    try:
        ids = [int(value) for value in raw_ids.split(",") if value]
    except ValueError:
        abort(400, description="ids must be comma-separated positive integers.")
    if not ids or any(value < 1 for value in ids) or len(set(ids)) > 5:
        abort(400, description="Provide between one and five positive institution IDs.")
    with universal_session() as db_session:
        institutions = InstitutionService(db_session).compare(ids)
        return jsonify(items=[serialize_institution(item) for item in institutions])


@app.get("/api/institutions/recommendations")
def api_recommendation_candidates():
    limit = parse_api_integer("limit", default=25, minimum=1, maximum=100)
    filters = {
        "district": request.args.get("district", "").strip() or None,
        "category": request.args.get("category", "").strip() or None,
        "program_name": request.args.get("program", "").strip() or None,
        "limit": limit,
    }
    with universal_session() as db_session:
        candidates = RecommendationService(db_session).candidates(**filters)
        return jsonify(items=[serialize_institution(item) for item in candidates])


@app.get("/api/provenance/<int:provenance_id>/verification-history")
def api_verification_history(provenance_id):
    with universal_session() as db_session:
        history = VerificationService(db_session).history(provenance_id)
        return jsonify(items=[{
            "id": item.id,
            "verification_status": item.verification_status,
            "reviewer": item.reviewer,
            "verified_at": item.verified_at.isoformat() if item.verified_at else None,
            "notes": item.notes,
            "source": {
                "url": item.source.source_url,
                "organisation": item.source.source_organisation,
            } if item.source else None,
        } for item in history])


if __name__ == "__main__":
    app.run(debug=os.environ.get("COLLEGEHUB_DEBUG") == "1")
