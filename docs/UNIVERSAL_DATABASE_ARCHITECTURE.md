# Universal CollegeHub database architecture

## Scope and compatibility

CollegeHub now has a SQLAlchemy 2.x data layer with Alembic migrations. It supports SQLite for local development and PostgreSQL through psycopg 3 for deployment. `DATABASE_URL` selects the database; without it, the data layer uses the separate `instance/collegehub.sqlite3` file.

The original Flask pages continue to use the bundled `sample_colleges.db` demo database and its existing SQLite queries. The universal schema is separate: no legacy records are copied, rewritten, or marked verified. Alembic refuses to initialize the universal schema on a legacy SQLite database containing conflicting tables.

## Supported institution and admission data

- Institution categories: Engineering, Medical, Agriculture, Arts, and Science.
- Institution types: Government, Government-aided, Private, Deemed university, Central university, and State university.
- Institutions can have campuses, departments, programs, specializations, accreditation, and university affiliations.
- Admissions are represented by authorities, exams, cycles, routes, eligibility criteria, counselling rounds, seat matrices, and sourced admission records. An admission record identifies its measurement type and unit; rank, score, marks, percentage, cutoff score, and merit position are not conflated.
- Fees are represented as academic-year fee structures and separately sourced components. Placement reports store reported counts and salary figures; a missing input is not synthesized into a percentage.
- Factual records reference provenance. Source and verification history remain separate from imported job metadata.
- RAG preparation is isolated in documents, versions, chunks, embeddings, conversations, messages, and feedback. Embeddings are empty until a later, implemented ingestion pipeline exists.

## Data access

Repository and service classes in `repositories.py` and `services.py` prepare queries for institution search/profile/comparison, program search, admission and fee records, recommendation candidates, and verification history. Read-only JSON routes are available:

- `GET /api/institutions?q=&district=&category=&type=&limit=&offset=`
- `GET /api/institutions/{id}`
- `GET /api/programs?q=&institution_id=&category=&limit=&offset=`
- `GET /api/institutions/{id}/admissions`
- `GET /api/institutions/{id}/fees`
- `GET /api/institutions/compare?ids=1,2`
- `GET /api/institutions/recommendations?district=&category=&program=&limit=`
- `GET /api/provenance/{id}/verification-history`

The database-backed public routes use the universal schema and return 503 when it has not been migrated or cannot be reached; they do not fall back to the bundled demo database. A limited optional single-admin console supports source registration, the fixed Anna University importer, and provenance status reviews when configured with an administrator password hash and session secret. It is not a multi-user identity/role system. Student accounts, chatbot responses, and RAG retrieval are not implemented.

## Database relationship diagram

```mermaid
erDiagram
    INSTITUTION_CATEGORIES ||--o{ INSTITUTIONS : classifies
    INSTITUTION_TYPES ||--o{ INSTITUTIONS : describes
    INSTITUTIONS ||--o{ CAMPUSES : has
    INSTITUTIONS ||--o{ DEPARTMENTS : has
    CAMPUSES o|--o{ DEPARTMENTS : hosts
    INSTITUTIONS ||--o{ PROGRAMS : offers
    DEPARTMENTS o|--o{ PROGRAMS : organizes
    INSTITUTION_CATEGORIES ||--o{ PROGRAMS : categorizes
    PROGRAMS ||--o{ SPECIALIZATIONS : includes
    INSTITUTIONS ||--o| UNIVERSITIES : may_be
    UNIVERSITIES ||--o{ AFFILIATIONS : receives
    INSTITUTIONS ||--o{ AFFILIATIONS : has
    ACADEMIC_YEARS ||--o{ ADMISSION_CYCLES : schedules
    ADMISSION_CYCLES ||--o{ ADMISSION_ROUTES : contains
    INSTITUTIONS ||--o{ ADMISSION_ROUTES : offers
    ADMISSION_AUTHORITIES o|--o{ ADMISSION_ROUTES : administers
    ADMISSION_EXAMS o|--o{ ADMISSION_ROUTES : qualifies
    ADMISSION_ROUTES ||--o{ ELIGIBILITY_CRITERIA : defines
    ADMISSION_ROUTES ||--o{ COUNSELLING_ROUNDS : runs
    PROGRAMS ||--o{ ADMISSION_RECORDS : admits
    ACADEMIC_YEARS ||--o{ ADMISSION_RECORDS : dates
    ADMISSION_ROUTES o|--o{ ADMISSION_RECORDS : source_route
    INSTITUTIONS ||--o{ FEE_STRUCTURES : publishes
    FEE_STRUCTURES ||--o{ FEE_COMPONENTS : itemizes
    INSTITUTIONS ||--o{ PLACEMENT_REPORTS : reports
    INFORMATION_SOURCES o|--o{ RECORD_PROVENANCE : documents
    ACADEMIC_YEARS o|--o{ RECORD_PROVENANCE : dates
    RECORD_PROVENANCE ||--o{ VERIFICATION_RECORDS : tracks
    INFORMATION_SOURCES ||--o{ DOCUMENTS : provides
    DOCUMENTS ||--o{ DOCUMENT_VERSIONS : versions
    DOCUMENT_VERSIONS ||--o{ DOCUMENT_CHUNKS : splits
    DOCUMENT_CHUNKS ||--o| EMBEDDINGS : optionally_embeds
    CONVERSATIONS ||--o{ MESSAGES : contains
    MESSAGES ||--o{ CHATBOT_FEEDBACK : receives
```

See [DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md) for the table inventory and key constraints.
