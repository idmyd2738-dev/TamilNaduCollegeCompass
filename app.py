from pathlib import Path
import sqlite3
from contextlib import closing
from flask import Flask, render_template, request, abort, jsonify

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "sample_colleges.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = "demo-only-change-before-any-real-use"

def get_db():
    # Read-only connection: safe for a bundled demo database on serverless hosting.
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn

@app.context_processor
def inject_globals():
    return {"site_name": "Tamil Nadu College Compass"}

@app.get("/")
def home():
    with closing(get_db()) as db:
        streams = db.execute("""
            SELECT s.slug, s.name, s.icon, COUNT(c.id) AS college_count
            FROM streams s LEFT JOIN colleges c ON c.stream_id=s.id
            GROUP BY s.id ORDER BY s.id
        """).fetchall()
        featured = db.execute("""
            SELECT c.*, s.name AS stream_name, s.slug AS stream_slug
            FROM colleges c JOIN streams s ON s.id=c.stream_id
            ORDER BY c.featured DESC, c.name LIMIT 3
        """).fetchall()
    return render_template("home.html", streams=streams, featured=featured)

@app.get("/colleges")
def colleges():
    q = request.args.get("q", "").strip()
    stream = request.args.get("stream", "").strip()
    with closing(get_db()) as db:
        streams = db.execute("SELECT * FROM streams ORDER BY name").fetchall()
        sql = """
            SELECT c.*, s.name AS stream_name, s.slug AS stream_slug
            FROM colleges c JOIN streams s ON s.id=c.stream_id
            WHERE (?='' OR c.name LIKE ? OR c.city LIKE ? OR c.district LIKE ?)
              AND (?='' OR s.slug=?)
            ORDER BY c.featured DESC, c.name
        """
        like = f"%{q}%"
        rows = db.execute(sql, (q, like, like, like, stream, stream)).fetchall()
    return render_template("colleges.html", colleges=rows, streams=streams, q=q, selected_stream=stream)

@app.get("/colleges/<int:college_id>")
def college_detail(college_id):
    with closing(get_db()) as db:
        college = db.execute("""
            SELECT c.*, s.name AS stream_name, s.slug AS stream_slug
            FROM colleges c JOIN streams s ON s.id=c.stream_id WHERE c.id=?
        """, (college_id,)).fetchone()
        if college is None:
            abort(404)
        courses = db.execute("SELECT name, level, duration FROM courses WHERE college_id=? ORDER BY name", (college_id,)).fetchall()
        facilities = db.execute("SELECT label FROM facilities WHERE college_id=? ORDER BY label", (college_id,)).fetchall()
    return render_template("college_detail.html", college=college, courses=courses, facilities=facilities)

@app.get("/about")
def about():
    return render_template("about.html")

@app.get("/chat")
def chat():
    return render_template("chat.html")

@app.post("/demo-chat")
def demo_chat():
    # Deliberately demo-only: deterministic responses, no account or message storage.
    question = (request.json or {}).get("message", "").strip().lower()
    if not question:
        return jsonify(answer="Please enter a question.")
    answers = [
        (("engineering", "be ", "b.tech"), "Engineering colleges offer undergraduate programmes such as B.E. and B.Tech. Check each college profile and verify current admission rules with the official counselling authority."),
        (("agriculture", "farm"), "Agriculture programmes cover agricultural sciences and related fields. Course availability and admission rules vary; confirm details with the institution and official admission portal."),
        (("medical", "mbbs", "neet"), "Medical admissions are governed by applicable national and state counselling rules. Check the current official notices before making decisions."),
        (("fees", "fee", "cost"), "Fees vary by institution, course, quota and academic year. This demo does not publish verified fee figures; contact the college for current details."),
        (("hostel", "accommodation"), "Hostel availability and charges can change. Contact the college administration for current accommodation details."),
        (("admission", "counselling", "cutoff"), "Admission requirements, counselling schedules and cutoffs change each year. Always verify the latest official government and counselling notifications.")
    ]
    for keywords, answer in answers:
        if any(word in question for word in keywords):
            return jsonify(answer=answer)
    return jsonify(answer="I don't have verified information for that question in this demonstration. Please check the relevant official government portal or contact the college directly.")

@app.get("/health")
def health():
    return jsonify(status="ok", mode="read-only demo")

if __name__ == "__main__":
    app.run(debug=True)
