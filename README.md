# CollegeHub

CollegeHub is a Flask/Jinja2/SQLite demonstration for exploring Tamil Nadu college streams, sample college records and general admission guidance. It extends the existing prototype and does not provide production authentication or official admission advice.

## Run locally (Windows PowerShell)

From the project directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python init_db.py
python app.py
```

Open http://127.0.0.1:5000.

`init_db.py` is an idempotent additive migration. It creates the new SQLite tables and indexes, adds nullable metadata and verification columns, and inserts demonstration guidance/FAQ rows with `INSERT OR IGNORE`. Existing colleges, courses and facilities are preserved. Run it locally before using the extended pages; it does not run automatically during app import.

## Main pages

- `/` — homepage
- `/college` — stream selection
- `/college/engineering`, `/college/agriculture`, `/college/medical`, `/college/arts-science` — stream guidance and tabs
- `/colleges` — searchable, filterable, sortable, paginated sample directory
- `/colleges/<id>` — college profile
- `/compare` — compare two or three selected colleges
- `/chat` — predefined CollegeHub chatbot and FAQ
- `/login`, `/student/login`, `/student/register`, `/student/dashboard` — demo student portal
- `/admin/login`, `/admin` — local admin demo and sample-record management
- `/health` — application health

## Demo interactions and limitations

- College search, stream, district and course filters work with the bundled records. Category, ownership, fee and hostel filters return matches only after those fields have been added to records; the prototype does not infer missing data.
- Favourites, comparison selection, saved searches and chatbot conversations use this browser's local storage. They are not associated with a verified account.
- Student and admin portals are explicitly demo-only. Their forms do not validate passwords or create secure accounts; passwords are not stored. Do not enter real credentials or sensitive personal information.
- Local admin tools can create, edit and delete sample college, course, fee, cutoff, facility, hostel and FAQ records; update stream and district metadata; and manage record verification. New and edited records are marked unverified or pending by default. Marking a record verified requires a source, academic year and last-verified date.
- The database contains no verified sample fees, cutoffs, official college websites or hostel availability. Those values remain blank until sourced and entered.
- The chatbot uses deterministic, predefined responses. It is not an AI or RAG service.
- The database includes tables for academic years, districts, fees, cutoffs, hostels, information sources, verification records, guidance, FAQs, student demo profiles and feedback. No student password is stored.
- Public content routes use read-only SQLite access. Local admin updates are available only in explicitly labelled demo mode; `/health` reports whether the app is in local or read-only demo mode.

## Verification labels

- **Verified** — reserved for records with a source, academic year and last verified date.
- **Pending verification**, **Information not yet verified**, and **Outdated** — indicate that a record should not be relied on as current official guidance.

The supplied stream guidance links to the official sites listed in the project brief. Guidance content is labelled unverified until reviewed for the relevant admission year. Do not add current dates, eligibility requirements, fee amounts or cutoffs without a source.

## SQLite and deployment

The bundled database is opened read-only by public application routes. Local admin writes use SQLite and are blocked when `VERCEL`, `VERCEL_ENV`, or `COLLEGEHUB_READ_ONLY=1` is set. Vercel deployments should remain read-only; changes made in an ephemeral deployment filesystem will not persist. Run the migration and admin CRUD locally only.

For local sessions, CollegeHub uses a development-only default secret. Do not treat it as production security. `COLLEGEHUB_SECRET_KEY` may be set for a local deployment where a non-default session secret is required.

The existing Vercel entry point remains `index.py`. Do not add a writable-database assumption to serverless deployment configuration.

## Test

```powershell
python -m pytest -q
```

The tests cover existing search and chatbot behavior, new page routes, comparison, demo student access, SQLite migration idempotence, local admin CRUD, and verification requirements.
