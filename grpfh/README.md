# GRPFH (Flask Backend + Static Frontend)

## Run (Windows, repo venv)

```powershell
.\.venv\Scripts\python.exe -m grpfh
```

Legacy (still works):

```powershell
.\.venv\Scripts\python.exe grpfh\app.py
```

## Notes

- API routes stay compatible under `/api/*`.
- Database defaults to the repo root `ai_screening.db` (configurable via `GRPFH_DB_PATH`).
- The old monolithic server implementation is kept in `grpfh/legacy_app.py` for reference.

