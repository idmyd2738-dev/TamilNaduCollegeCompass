# Official data collection and ingestion

## Current engineering collector

`ingestion/anna_university.py` retrieves the public [Anna University constituent-college directory](https://www.annauniv.edu/constituent_colleges.php). On 19 November 2026, the page was reachable and exposed a numbered list of 16 constituent colleges with linked institution websites. The collector parsed all 16 numbered rows. The site returned 404 for `robots.txt`; under the crawler policy, a missing robots file is treated as no disallow rules. The collector still uses a bounded request and conservative timeout.

Run from the project directory after applying current migrations:

```powershell
python -m ingestion.anna_university
```

The collector:

- Fetches only the fixed official Anna University URL; it does not accept arbitrary target URLs.
- Checks robots policy, validates the final host and `text/html` response, and limits response size.
- Parses numbered table rows and fails if the expected sequence is not present.
- Registers an `information_sources` record and a `data_import_jobs` record.
- Stores the public source URL and SHA-256 of the fetched page in `source_documents`; it does not archive the HTML bytes locally.
- Imports official name, directory-linked website, engineering category, and the neutral `unknown` institution type.
- Leaves district, city, establishment year, codes, programmes, fees, and other facts null because the source page does not provide them.
- Sets provenance to `pending`, with no verification date/reviewer; it never marks imported facts verified.
- Skips exact existing names and never overwrites existing institution rows.

The configured Neon database currently contains 16 institution rows from this source, one source record, one source-document hash reference, and one successful import job. All 16 records are pending verification. There are no imported programmes, admission/cutoff records, fees, placement records, or embeddings. The 16 rows are only Anna University's constituent institutions—not a statewide engineering catalogue.

## Other source research

Official pages were checked but are not yet imported as factual records:

- [TNEA Online Counselling](https://www.tneaonline.org/) describes the 2026 engineering admission portal but is a JavaScript application; no public structured institution/course/seat export was confirmed.
- [Tamil Nadu Medical Selection Committee](https://tnmedicalselection.net/) and its [2025–2026 archive](https://tnmedicalselection.net/Archives.aspx) expose programme notices and PDF links. PDF data extraction and review have not been implemented.
- [TANUVAS Tamil Nadu admissions](https://adm.tanuvas.ac.in/tamil-nadu-options) links to 2026–27 prospectus, cutoff, fee, and counselling documents. These documents have not been imported.
- [TNAU](https://tnau.ac.in/) was reachable, but a statewide structured institution/programme dataset was not confirmed from the page inspected.
- [TNGASA](https://www.tngasa.in/) returned HTTP 503 at the time checked.
- AISHE has an institutional directory and annual reports, but no verified Tamil Nadu-specific structured export has yet been ingested.

Access to an official portal does not establish that each data value is complete or current. Follow the source's terms, robots policy, and reasonable request rates.

## Remaining ingestion work

The current collector is a first source-specific pipeline, not the requested universal ingestion system. CSV/PDF ingestion, source enable/disable management, conflict resolution, richer extraction review, and document archiving/versioning remain incomplete. The optional single-admin console can register sources, run this fixed importer, and review supported factual records; it does not provide multi-user roles, reviewer identity, MFA, or rate limiting. No LLM embeddings or document chunks are generated.


## TNGASA 2026 college directory importer

Official PDF:
`https://static.tneaonline.org/docs/arts/colleges_info_2026.pdf?t=1778132774371`

The PDF lists TNGASA 2026 participating government arts and science colleges with
college codes, names, districts, 2025 admit percentage, NAAC grade, NIRF rank and
male/female seat-availability columns. The parser imports the college code, name and
district; available NAAC grades become pending accreditation records. Other source
fields are preserved in provenance notes and are not incorrectly represented as
cutoff scores or programme-level seat matrices.

The parser fails closed unless it extracts between 100 and 250 college rows. It skips
existing official codes and never overwrites existing institutions. New records remain
pending verification. Run `python -m ingestion.tngasa_2026` or use the administrator
dashboard. The PDF's full text can separately be indexed for chatbot retrieval after
AI embedding credentials are configured and the uploaded document version is reviewed.
