# Data provenance and verification policy

## Evidence requirements

Every factual entity requires its own `record_provenance` row. Provenance can identify an `information_sources` record, academic year, collection date, verification date/status, reviewer, and notes. The source record can store a URL, source organisation, document title, publication date/type, and notes. When evidence or a field is unavailable, retain it as null rather than fabricate it.

Use primary/official publications where possible, and capture the organisation and exact source URL/document. Retain source documents and their SHA-256 when storage and licensing permit. Store publication, collection, and verification dates separately; they represent different events.

## Status lifecycle

- `unverified`: default for new and imported factual records.
- `pending`: evidence awaits review.
- `verified`: a reviewer has checked the cited evidence and recorded a verification timestamp.
- `rejected`: the evidence does not support the record.
- `outdated`: the fact may once have been correct but is no longer current.

`verification_records` provides a history rather than overwriting all review context. The verification service refuses to mark data verified without a source record and verification timestamp. Imported data is never automatically verified.

## Admission, fee, and placement specifics

Admission values must carry an explicit measurement type and unit, academic year, program, category/quota where applicable, route/authority/round where known, provenance, and verification status. Rank, marks, score, percentage, cutoff score, and merit position are distinct values; do not compare or transform them using an assumed universal formula.

Fee components must retain amount, currency, academic year, scope (program and student category where applicable), source, and verification status. Never substitute estimated or missing amounts.

Placement reports store figures as reported with their source and verification state. Calculate/display a placement percentage only when the eligible and placed counts required for that calculation are both present and valid. This schema does not auto-calculate missing reports.

## Audit and display

Expose source and status with factual responses. Do not label a result official or verified solely because a row exists, a URL is present, or an import succeeded. The optional single-admin console supports CSRF-protected status reviews and records each change in `verification_records`; it currently has no per-user reviewer identity, so the reviewer remains null. Treat this as a limited review workflow, not an organizational identity or authorization system.
