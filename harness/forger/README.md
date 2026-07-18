# The Forger — known-answer test harness for S1 PDF extraction

Same philosophy as the Examiner one directory up: **known answer first,
deterministic grading, signature dedup, case files, fail-then-pass
detectors.** The system under test here is an LLM (`backend/count_agent.py`
via Claude vision) — that's fine and unavoidable. The firewall stands: no
LLM generates the answer key, renders the PDF, or decides pass/fail.

Two consequences shape everything:
- **Extractor output may vary run-to-run.** That variance is DATA — every
  run is its own results row; nothing is ever averaged away. Use
  `batch --repeat` to measure it.
- **Every run costs API tokens.** Batches are bounded (hard cap 200 runs
  per invocation) and cost-aware (token usage logged per run). There is no
  unbounded overnight loop, on purpose.

## Run it

```bash
python3.12 -m pip install --user reportlab   # renderer dep (harness-side only)
export ANTHROPIC_API_KEY=...          # required for live runs

python3.12 -m harness.forger.run_one --seed 7 --style D    # one run
python3.12 -m harness.forger.batch --n 20 --style D        # bounded batch
python3.12 -m harness.forger.batch --n 10 --style both
python3.12 -m harness.forger.batch --n 1 --style D --repeat 5   # variance

# offline acceptance suite (no API, no cost):
python3.12 -m pytest harness/forger/tests -q
```

A missing key or API failure records a **CRASH** verdict and the batch
continues — it never raises.

## Sheet styles

| Style | Mimics | Layout |
|---|---|---|
| T | NDS / Quality Counts tabular | movement columns (`NL NT NR NU \| SL … \| TOTAL`), 15-min interval rows summing exactly to peak-hour values, totals row |
| D | Counts Unlimited diagram | plan-view crossing, per-approach volume trios at the movement arrow positions, boxed approach totals, grand-total box, compass; N-up or E-up orientation |

Style D is the format that triggers the known S1 mis-mapping bug.
**Provenance note:** the repo contains no Counts Unlimited layout notes and
no sample PDFs (searched exhaustively, incl. git history — the prior
analysis was never committed), so Style D is built from industry-standard
TMC diagram conventions plus the bug's recorded symptoms. The acceptance
gate — the real extractor must exhibit mapping errors on Style D — is the
fidelity arbiter; iterate the layout if the bug doesn't express.

Sheets are byte-deterministic per (seed, style) (string-seeded RNG +
reportlab invariant mode). Every PDF's metadata carries
`forger-synthetic=true` — see the corpus-firewall rule in
`../knowledge/known-behaviors.md`: Forger sheets must NEVER enter any
extraction training/example corpus.

## Grading (deterministic)

Per movement: `CORRECT` · `DIGIT-ERR` (±10 veh or digit edit distance ≤ 1
at the right code) · `MAP-ERR` (the true value of movement X extracted at
movement Y — sub-patterns `NS-FLIP`, `EW-FLIP`, `LTR-SHIFT`, `OTHER-SWAP`)
· `TOTAL-AS-MOVEMENT` (an approach/grand total in a movement slot) ·
`OMISSION` · `HALLUCINATION`. Exact-value matching is sound because all 17
numbers per period are generated pairwise >10 apart.

Sheet-level: intersection-total ratio (extracted/true — the 2.2× symptom)
per period, and one verdict: `PASS` / `DIGIT-ONLY` / `MAP-FAIL` / `MIXED` /
`CRASH`. Signatures hash (style, error classes, MAP sub-patterns) — never
seed-specific values — so one failure shape across many seeds dedups to one
ledger row in `failures/index.csv`.

## Where results land

| Path | What |
|---|---|
| `results.csv` | one row per run (repeats of a seed = separate rows) |
| `summary.md` | verdict rates by style, error-class histogram, MAP sub-pattern tracker, repeat-seed variance, token spend |
| `runs/<id>/` | sheet.pdf, answer_key.json, extraction.json, raw_model_output.txt, grade.json |
| `failures/<id>/` | full case file per non-PASS run + `report.md` with the repro command |
| `failures/index.csv` | signature ledger |

## Non-goals (v1)

No fixing the extractor (that's the next task, proven BY this harness). No
scan-noise simulation (skew, stamps, handwriting) — clean synthetic PDFs
only; real labeled PDFs remain the gold standard when restored. No
multi-intersection sheets, no multi-page, no 15-min-bin extraction grading
(peak-hour values only). No Telegram notifier yet.
