import os
import sqlite3
from contextlib import closing
from datetime import timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "sample_colleges.db"
PAGE_SIZE = 9
VERIFICATION_STATES = {
    "verified",
    "pending_verification",
    "information_not_verified",
    "outdated",
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
app.config["SECRET_KEY"] = os.environ.get(
    "COLLEGEHUB_SECRET_KEY", "collegehub-local-demo-session-key"
)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)


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
        if not session.get("collegehub_demo_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def student_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("collegehub_demo_student"):
            return redirect(url_for("student_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def college_query(where_sql="", order_by="c.featured DESC, c.name"):
    return f"""
        SELECT c.*, s.name AS stream_name, s.slug AS stream_slug,
               (SELECT GROUP_CONCAT(name, ', ') FROM courses WHERE college_id=c.id) AS course_names,
               (SELECT MIN(amount) FROM fee_records WHERE college_id=c.id) AS min_fee
        FROM colleges c JOIN streams s ON s.id=c.stream_id
        {where_sql}
        ORDER BY {order_by}
    """


@app.context_processor
def inject_globals():
    return {"site_name": "CollegeHub"}


@app.get("/")
def home():
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
    with closing(get_db()) as db:
        streams = db.execute("""
            SELECT s.slug, s.name, s.icon, COUNT(c.id) AS college_count
            FROM streams s LEFT JOIN colleges c ON c.stream_id=s.id
            GROUP BY s.id ORDER BY s.id
        """).fetchall()
    return render_template("college_home.html", streams=streams)


@app.get("/college/<string:stream_slug>")
def stream_page(stream_slug):
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
    q = request.args.get("q", "").strip()
    stream = request.args.get("stream", "").strip()
    district = request.args.get("district", "").strip()
    course = request.args.get("course", "").strip()
    category = request.args.get("category", "").strip()
    ownership = request.args.get("ownership", "").strip()
    fee_range = request.args.get("fee_range", "").strip()
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
    if fee_range in {"under-50000", "50000-100000", "over-100000"}:
        expressions = {
            "under-50000": "fr.amount < 50000",
            "50000-100000": "fr.amount >= 50000 AND fr.amount <= 100000",
            "over-100000": "fr.amount > 100000",
        }
        conditions.append(
            f"EXISTS (SELECT 1 FROM fee_records fr WHERE fr.college_id=c.id AND {expressions[fee_range]})"
        )
    if hostel in {"yes", "no"}:
        conditions.append("c.hostel_available=?")
        parameters.append(1 if hostel == "yes" else 0)

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    order_options = {
        "featured": "c.featured DESC, c.name",
        "name": "c.name COLLATE NOCASE",
        "district": "c.district COLLATE NOCASE, c.name COLLATE NOCASE",
    }
    order_by = order_options.get(sort, order_options["featured"])
    with closing(get_db()) as db:
        streams = db.execute("SELECT * FROM streams ORDER BY name").fetchall()
        districts = db.execute("SELECT DISTINCT district FROM colleges WHERE district IS NOT NULL ORDER BY district").fetchall()
        courses = db.execute("SELECT DISTINCT name FROM courses ORDER BY name").fetchall()
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
        selected_ownership=ownership, selected_fee_range=fee_range, selected_hostel=hostel,
        sort=sort, page=page, pages=pages, total=total,
    )


@app.get("/colleges/<int:college_id>")
def college_detail(college_id):
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


@app.get("/about")
def about():
    return render_template("about.html")


@app.get("/chat")
def chat():
    with closing(get_db()) as db:
        faqs = db.execute("SELECT * FROM faqs ORDER BY id").fetchall()
    return render_template("chat.html", faqs=faqs)


@app.post("/demo-chat")
def demo_chat():
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
    return render_template("login.html")


@app.get("/student/login")
def student_login():
    return render_template("access_form.html", mode="student_login", next_url=request.args.get("next", ""))


@app.post("/student/login")
def student_login_submit():
    email = request.form.get("email", "").strip()
    if not email or "@" not in email:
        return render_template("access_form.html", mode="student_login", error="Enter a valid demo email address.", next_url="")
    session["collegehub_demo_student"] = {"name": email.split("@", 1)[0], "email": email}
    session.permanent = request.form.get("remember") == "on"
    return redirect(safe_redirect_target(request.form.get("next"), url_for("student_dashboard")))


@app.get("/student/register")
def student_register():
    return render_template("access_form.html", mode="student_register", next_url="")


@app.post("/student/register")
def student_register_submit():
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
    session.pop("collegehub_demo_student", None)
    return redirect(url_for("login"))


@app.get("/admin/login")
def admin_login():
    return render_template("access_form.html", mode="admin_login", next_url=request.args.get("next", ""))


@app.post("/admin/login")
def admin_login_submit():
    session["collegehub_demo_admin"] = True
    return redirect(safe_redirect_target(request.form.get("next"), url_for("admin_dashboard")))


@app.post("/admin/logout")
def admin_logout():
    session.pop("collegehub_demo_admin", None)
    return redirect(url_for("login"))


@app.get("/admin")
@admin_required
def admin_dashboard():
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
    return jsonify(status="ok", mode="read-only demo" if read_only_deployment() else "local demo")


if __name__ == "__main__":
    app.run(debug=True)
