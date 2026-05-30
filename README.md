# demandiq
DemandIQ — traffic count extraction agent

## Running locally

**Frontend** (Vite dev server → http://localhost:3000):
```bash
cd frontend && npm install && npm run dev
```

**Backend** (FastAPI → http://localhost:8000):
```bash
cd backend && python3.12 app.py
```

Set `DEMANDIQ_DEV=1` to enable backend auto-reload on source edits (local
development only — production/Render leaves it unset so the server never
watches the filesystem):
```bash
cd backend && DEMANDIQ_DEV=1 python3.12 app.py
```

## Tests

```bash
cd backend && ./run_tests.sh          # backend suite
node frontend/src/lib/<name>.test.mjs # frontend pure-helper tests
```
