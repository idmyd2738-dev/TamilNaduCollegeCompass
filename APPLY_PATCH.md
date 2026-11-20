# Applying the CollegeHub implementation patch

This is a patch bundle, not a replacement for the full project.

1. Back up your current project folder.
2. Extract this ZIP into the project root:
   `E:\\TamilNaduCollegeCompass_Prototype\\TamilNaduCollegeCompass`
3. Allow the included files to overwrite the matching project files.
4. Do not replace your `.env` with `.env.example`. The example only documents new AI settings.
5. In PowerShell, from the project root, run:
   `\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt`
6. Add the AI settings from `.env.example` to your existing `.env` only after obtaining a valid provider key:
   - COLLEGEHUB_AI_API_KEY
   - COLLEGEHUB_AI_BASE_URL
   - COLLEGEHUB_AI_CHAT_MODEL
   - COLLEGEHUB_AI_EMBEDDING_MODEL
   - COLLEGEHUB_EMBEDDING_DIMENSIONS (optional)
7. Run:
   `\\.venv\\Scripts\\python.exe -m compileall -q app.py ai_service.py ingestion tests`
   `\\.venv\\Scripts\\python.exe -m pytest -q tests`
8. Start the app and log into `/admin`.
9. Run the TNGASA 2026 import from the admin dashboard. It will fetch the official PDF, fail closed if it cannot parse a plausible statewide list, skip existing college codes, and leave new records pending verification.
10. Register official sources and upload their PDF/HTML/CSV/TXT/Markdown documents for AI indexing. Verify each document version before it can be retrieved by the chatbot.

No Alembic migration is included or required by this patch. It uses the existing document, embedding, conversation, and provenance tables.

Important:
- AI provider usage may cost money.
- The original uploaded document binary is not retained; extracted text chunks and source metadata are stored.
- RAG retrieval currently scores stored embeddings in application memory. This is suitable for a small pilot, not a large statewide corpus.
- The TNGASA importer does not infer programme lists, cutoffs, or programme seat matrices from college-level summary columns.
