# Extraction model — fine-tuning evaluation note

Decision criteria for how the count extractor (`count_agent.py`) learns.
**This is a decision note, not an implementation.** No fine-tuning code
exists or should be added until the triggers below are met.

## Current state

- **Path A (in-context, live today).** Claude reads the file plus 8
  vendor-matched reference examples drawn from `training_data.jsonl` on
  every call. Confirmed labels feed back via
  `tools/export_for_finetuning.py --append-confirmed`.
- Confirmed label volume (as of this note): ~624 rows in
  `labels_template.xlsx`, concentrated in two vendors (Quality Counts
  ~596, NDS ~24). `training_data.jsonl`: ~204 reference examples.
- Not yet labeled: GRAM Traffic, Pape-Dawson, Unknown.

## The three paths

| Path | What | Accuracy | Cost | Status |
|------|------|----------|------|--------|
| **A** | In-context reference examples (current) | ~90%+ | $0 marginal | **Live** |
| **B** | OpenAI / Anthropic fine-tune | ~96–98% | ~$1K one-time + retrain on new data | Revisit (see triggers) |
| **C** | Open-source (Llama / Mistral) self-hosted | TBD | infra + ops | Future option |

## When to revisit Path B (fine-tuning)

Fine-tune **only** when one or more of these fire:

1. **New-vendor accuracy floor breached.** In-context accuracy on a new
   vendor stays below **~85%** even with 8 vendor-matched references in
   the prompt. (Below that, more in-context examples stop helping —
   the model needs weight-level adaptation.)
2. **Reference examples hit diminishing returns.** Adding more confirmed
   examples per call no longer moves accuracy — i.e., the 8-example
   window is saturated and we're leaving signal on the table that only
   fine-tuning can capture.
3. **Label volume threshold.** Confirmed examples across **≥4 distinct
   vendors** exceed roughly **1,500–2,000** total, with **≥150 per
   vendor**. Below this, a fine-tune risks overfitting the two dominant
   vendors (today QC/NDS) and regressing on the long tail. *(Starting
   estimate — recalibrate against a held-out eval set before committing
   the spend.)*

Until then, Path A is the right call: $0 marginal cost, already ~90%+,
and every confirmed correction improves it for free via the feedback
pipeline.

## Path C (open-source) — even further out

Consider only if (a) per-call API cost becomes the bottleneck at volume,
or (b) data-residency / offline requirements rule out hosted APIs.
Requires GPU infra + an eval harness + ongoing model ops — not worth it
while Path A clears the accuracy bar.

## Before any fine-tune spend

- Build a held-out eval set (confirmed rows NOT in `training_data.jsonl`)
  and measure Path A's real accuracy per vendor first. The triggers above
  are meaningless without a measured baseline.
- Re-run the comparison after each major new-vendor labeling batch.
