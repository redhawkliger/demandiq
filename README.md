# demandiq
DemandIQ — traffic count extraction agent

## Prerequisites

- **Python 3.12** and **Node 20+**
- **Poppler** — `pdf2image` shells out to `pdftoppm` to rasterise uploaded PDFs
  for vision extraction. Without it the wheel installs fine and gives no
  build-time warning, but **every PDF upload fails at runtime**:
  ```bash
  brew install poppler          # macOS
  sudo apt install poppler-utils # Debian/Ubuntu
  ```
- **`ANTHROPIC_API_KEY`** — `app.py` raises at import if it is unset. Note that
  a key exported in `~/.bash_profile` is not visible to non-interactive shells;
  the server must be started from an environment that actually has it.

```bash
pip install -r backend/requirements.txt
cd frontend && npm install
```

The forecasting geo stack (`backend/requirements-forecasting.txt`) is optional —
its imports are lazy, so the app runs without it and only
`/forecast/ingest-match` returns 503.

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

## Deploying

The two halves run as **one** service in production. Locally the Vite dev server
proxies `/api/*` to the backend; there is no proxy on a server, so FastAPI
serves the React build itself and strips the `/api` prefix in middleware. One
set of frontend URLs therefore works in both places.

```bash
docker build -t demandiq .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-... -e APP_PASSWORD=... demandiq
```

**Render:** push the branch, then New + → Blueprint and point it at the repo.
`render.yaml` describes the service; Render prompts for the two secrets, which
are deliberately not committed.

| Env var | Effect |
|---|---|
| `ANTHROPIC_API_KEY` | Required — the app refuses to start without it. |
| `APP_PASSWORD` | When set, every route except `/health` requires basic auth. **Set it** — a public URL wired to a paid API key should not be open. |
| `PORT` | Supplied by the platform; defaults to 8000. |

Routes: `/` React app · `/legacy` original Jinja UI · `/health` open health
check · `/docs` API docs.

Two caveats. Render's **free plan sleeps after ~15 min idle** and takes ~1 minute
to wake, so open the URL before demoing. And the **SANDAG forecasting data is
gitignored** (~93 MB), so F1–F4 will not work from a clean clone or in the
image — existing-conditions S1–S8 is unaffected.
