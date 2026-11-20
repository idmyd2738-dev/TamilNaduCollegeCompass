# Database schema

All tables use integer primary keys unless noted, `created_at`/`updated_at` timestamps, declared foreign keys, and explicit deletion behavior. Factual entities use a unique, non-null `provenance_id` referencing `record_provenance`; generic lookup rows do not claim a factual source.

## Institutions and academic structure

| Tables | Purpose and relationships |
| --- | --- |
| `institution_categories`, `institution_types` | Lookup tables. The migration seeds the five requested categories and six ownership/university types. |
| `institutions` | Official name, optional code/contact/address/website/establishment year, category, type, district/city, operational status, and required provenance. |
| `campuses` | Institution locations, optional coordinates, and main-campus flag. Campus names are unique per institution. |
| `universities` | University-specific details for an institution; its institution key is also its primary key. |
| `affiliations` | Time-scoped institution/university relationship with status and provenance. |
| `departments` | Institution departments, optionally associated with a campus. Department code/name are unique within the institution. |
| `programs`, `specializations` | Programs belong to an institution and category, optionally a department; specializations belong to programs. |
| `accreditations` | Institution accreditation agency, grade, date interval, and provenance. |
| `academic_years` | Unique year label and optional date interval. |

## Admissions

| Tables | Purpose and relationships |
| --- | --- |
| `admission_authorities`, `admission_exams` | Sourced authorities and exams; exams may reference an authority. |
| `admission_cycles` | Named cycle for an academic year, with optional application dates/status. |
| `admission_routes` | Institution-specific route within a cycle; optionally references an authority and exam. |
| `eligibility_criteria` | Optional program-specific criteria for a route, including marks, percentage, age, and structured details. |
| `counselling_rounds` | Ordered, dated rounds for a route. |
| `seat_matrices` | Available seats by route, program, academic year, category, quota, and optional round. |
| `admission_records` | Sourced value by institution/program/year, optional authority/route/round, category and quota. `measurement_type` is constrained to rank, score, marks, percentage, cutoff score, or merit position; `measurement_unit` is stored independently. No single cutoff formula is imposed. |

## Fees, facilities, scholarships, and placements

| Tables | Purpose and relationships |
| --- | --- |
| `fee_structures` | Institution/program/year/student-category/currency scope and required provenance. |
| `fee_components` | Named tuition, admission, examination, hostel, mess, transport, or other charge with nonnegative `Numeric(14,2)` amount and provenance. |
| `facilities` | Reusable facility definitions; `institution_facilities` records the sourced institution/campus association. |
| `hostel_details` | Sourced hostel details for an institution and optional campus. |
| `scholarships` | Sourced institution/program/year scholarship details. |
| `placement_reports` | Sourced report year and optional program, eligible/placed counts, and median/highest salary. `placement_percentage` is derived only when both counts exist and eligible students are greater than zero; otherwise it is `null`. |

## Provenance and imports

| Tables | Purpose and relationships |
| --- | --- |
| `information_sources` | URL, organisation, document title, publication date/type, and notes. A URL may be absent when unavailable. |
| `record_provenance` | Source, academic year, collection and verification dates, reviewer, notes, and status (`unverified`, `pending`, `verified`, `rejected`, `outdated`). Defaults to `unverified`. |
| `verification_records` | Appendable verification-history entries tied to provenance and optionally a source. |
| `source_documents` | Stored document URI, SHA-256, MIME type, publication and collection dates. Hash is validated and unique per source. |
| `data_import_jobs` | Import status/counters/errors and optional source. Imports do not change verification status to `verified`. |

## Chatbot preparation (not an implemented chatbot)

`documents` reference information sources; `document_versions` reference documents and source documents; `document_chunks` belong to a version; `embeddings` are optional and use PostgreSQL `vector` with SQLite JSON compatibility. `conversations`, `messages`, and `chatbot_feedback` are separate from academic data. No embeddings or chatbot data are seeded, and no RAG behavior is claimed.

## General integrity

The schema includes foreign keys with explicit restrict/cascade/set-null behavior, uniqueness for lookup codes and scoped entities, check constraints for statuses, dates, numeric ranges and measurement types, and indexes for primary lookup paths. JSON/JSONB is limited to category-specific eligibility details and document/message metadata. Monetary fields use numeric types; dates and timestamps are typed fields.
