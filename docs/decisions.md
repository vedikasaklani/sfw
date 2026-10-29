# Decisions and assumptions

- Start from the brief because the referenced assessments and UML PDF were not included in the workspace. The implementation-to-UML mapping is provisional.
- Use a straightforward modular monolith, SQLite local persistence, React/Vite and FastAPI, consistent with the requested stack and empty repo.
- Demo mode uses clearly labelled, deterministic sample patron/library data. It is never represented as a live Koha connection.
- Live catalogue access is behind one adapter. Patron circulation access stays disabled until authentication, borrower mapping, API version and permissions are verified. The browser cannot choose a borrower ID.
- Read-only circulation is the default. Mutating circulation operations are out of scope until a target Koha instance authorizes them.
- Analytics in demo use sample activity. Live analytics must be calculated only from authorized Koha records; portal-local activity cannot be presented as system-wide popularity.
- User interests are portal-owned preferences. Catalogue and circulation data are not duplicated in portal persistence.
- Current local schema uses SQLAlchemy `create_all`; Alembic migrations, actual login/session security, OAuth token acquisition, request retries/cache, and complete live response mapping are outstanding before production use.
