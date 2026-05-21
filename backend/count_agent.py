"""
DemandIQ — Count Agent (with reference examples)
=================================================
Claude-based universal count file extractor.
Reads Excel, PDF, CSV from any vendor. Returns structured JSON.

Now uses your training_data.jsonl as reference examples — Claude sees
8-10 of your confirmed correct extractions on every call, organized by
vendor for best pattern matching.

Higher accuracy than generic Claude. No fine-tuning needed.
"""

import os, sys, json, random
from pathlib import Path

try:
    import anthropic
except ImportError:
    sys.exit("Run: pip install anthropic openpyxl pdfplumber xlrd --break-system-packages")

MODEL      = "claude-sonnet-4-5"
MAX_TOKENS = 16000
MAX_CHARS  = 200000
MAX_PDF_PAGES = 40

# Reference examples settings
EXAMPLES_FILE        = Path(__file__).parent / "training_data.jsonl"
NUM_EXAMPLES_PER_CALL = 8        # how many examples to pass per call
MAX_EXAMPLE_CHARS     = 4000     # truncate each example to keep prompts small

MOVEMENTS = [
    'EBU','EBL','EBT','EBR',
    'WBU','WBL','WBT','WBR',
    'NBU','NBL','NBT','NBR',
    'SBU','SBL','SBT','SBR',
]

# ── REFERENCE EXAMPLES ────────────────────────────────────────────────────────
_examples_cache = None

def load_examples():
    """Load training_data.jsonl into memory once. Returns list of examples."""
    global _examples_cache
    if _examples_cache is not None:
        return _examples_cache

    if not Path(EXAMPLES_FILE).exists():
        _examples_cache = []
        return []

    examples = []
    with open(EXAMPLES_FILE, encoding='utf-8') as f:
        for line in f:
            try:
                ex = json.loads(line)
                # Each line has messages[user, assistant]
                msgs = ex.get('messages', [])
                user_msg = next((m['content'] for m in msgs if m['role']=='user'), '')
                asst_msg = next((m['content'] for m in msgs if m['role']=='assistant'), '')

                # Try to detect vendor from assistant response
                vendor = 'Unknown'
                try:
                    asst_data = json.loads(asst_msg)
                    vendor = asst_data.get('vendor_detected', 'Unknown')
                except: pass

                # Truncate huge file content to keep prompts manageable
                if len(user_msg) > MAX_EXAMPLE_CHARS:
                    user_msg = user_msg[:MAX_EXAMPLE_CHARS] + "\n... [truncated]"

                examples.append({
                    'vendor': vendor,
                    'input':  user_msg,
                    'output': asst_msg,
                })
            except: continue

    _examples_cache = examples
    return examples

def select_examples(file_content, n=NUM_EXAMPLES_PER_CALL):
    """Pick best reference examples for the current file."""
    examples = load_examples()
    if not examples:
        return []

    # Quick vendor sniff from file content (only works for text — images skip this)
    likely_vendor = None
    if isinstance(file_content, str) and file_content:
        content_lower = file_content[:5000].lower()
        if 'national data' in content_lower or 'NL\tNT\tNR\tNU' in file_content:
            likely_vendor = 'NDS'
        elif 'quality counts' in content_lower or 'qualitycounts' in content_lower:
            likely_vendor = 'Quality Counts'
        elif 'counts unlimited' in content_lower:
            likely_vendor = 'Counts Unlimited'
        elif 'gram traffic' in content_lower:
            likely_vendor = 'GRAM'
        elif 'pape-dawson' in content_lower or 'pape dawson' in content_lower:
            likely_vendor = 'Pape-Dawson'

    # Prefer same-vendor examples
    if likely_vendor:
        same = [e for e in examples if (e.get('vendor') or '') and likely_vendor.lower() in (e.get('vendor') or '').lower()]
        if len(same) >= n:
            return random.sample(same, n)
        other = [e for e in examples if e not in same]
        picked = same + random.sample(other, min(n - len(same), len(other)))
        return picked[:n]

    return random.sample(examples, min(n, len(examples)))

def format_examples_for_prompt(examples):
    """Format examples as a reference block for the system prompt."""
    if not examples:
        return ""

    block = "\n\n=== REFERENCE EXAMPLES (use these as guidance for similar files) ===\n"
    for i, ex in enumerate(examples, 1):
        block += f"\n--- Example {i} ({ex['vendor']}) ---\n"
        block += f"INPUT:\n{ex['input'][:2000]}\n\n"
        block += f"CORRECT OUTPUT:\n{ex['output']}\n"
    return block

# ── FILE READING ──────────────────────────────────────────────────────────────
def read_file(filepath):
    """
    Returns a 3-tuple: (content, ftype, warnings)
      content  — text str (for excel/csv/text/pdf-fallback) or list[base64] (pdf_images)
      ftype    — 'excel' | 'csv' | 'text' | 'pdf' | 'pdf_images'
      warnings — list[str]; non-empty when content was truncated by a cap so the
                 caller can surface "data was dropped" to the user. NEVER silently
                 drop content without populating this.
    """
    ext = Path(filepath).suffix.lower()
    if ext in ('.xlsx', '.xls'):
        content, warnings = _read_excel(filepath)
        return content, 'excel', warnings
    if ext == '.pdf':
        # Try image-based extraction first (much better for tables)
        try:
            images, warnings = _pdf_to_images(filepath)
            if images:
                return images, 'pdf_images', warnings
        except Exception as e:
            print(f"  (PDF image conversion failed: {e}, falling back to text)")
        # Fallback: text extraction
        content, warnings = _read_pdf_text(filepath)
        return content, 'pdf', warnings
    if ext == '.csv':
        content, warnings = _read_text(filepath)
        return content, 'csv', warnings
    content, warnings = _read_text(filepath)
    return content, 'text', warnings

def _read_excel(filepath):
    import openpyxl
    try:
        wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    except Exception:
        try:
            return _read_xls_legacy(filepath)
        except Exception as e:
            return f"ERROR reading Excel: {e}", []

    SKIP = ['bank', 'unshifted', 'stats', 'cover', 'blank']
    content = []
    for sheet_name in wb.sheetnames:
        if any(p in sheet_name.lower() for p in SKIP):
            continue
        ws = wb[sheet_name]
        rows = []
        for r in ws.iter_rows(values_only=True, max_row=500):
            if not any(v is not None for v in r):
                continue
            nums = [v for v in r[1:] if isinstance(v,(int,float))]
            if nums and all(v == 0 for v in nums) and len(nums) > 5:
                continue
            rows.append(r)
        if not rows:
            continue
        content.append(f"\n=== SHEET: {sheet_name} ===")
        for row in rows:
            content.append("\t".join(str(v) if v is not None else "" for v in row))
    full = "\n".join(content)
    warnings = []
    if len(full) > MAX_CHARS:
        warnings.append(
            f"Excel content is {len(full):,} chars but extraction cap is {MAX_CHARS:,}. "
            f"Content past the cap was NOT sent to the agent — any intersections "
            f"in the trailing portion of the workbook were NOT extracted."
        )
        full = full[:MAX_CHARS]
    return full, warnings

def _read_xls_legacy(filepath):
    import xlrd
    wb = xlrd.open_workbook(filepath)
    content = []
    for sheet in wb.sheets():
        content.append(f"\n=== SHEET: {sheet.name} ===")
        for r in range(min(sheet.nrows, 500)):
            row = sheet.row_values(r)
            content.append("\t".join(str(v) for v in row))
    full = "\n".join(content)
    warnings = []
    if len(full) > MAX_CHARS:
        warnings.append(
            f"Legacy .xls content is {len(full):,} chars but cap is {MAX_CHARS:,}. "
            f"Content past the cap was NOT sent to the agent."
        )
        full = full[:MAX_CHARS]
    return full, warnings

def _pdf_to_images(filepath, max_pages=MAX_PDF_PAGES, dpi=150):
    """Convert PDF pages to base64-encoded PNG images for Claude vision.
    Returns (list[base64_png], list[warning_str]). Pre-counts pages so we can
    warn loudly when a PDF exceeds the cap rather than silently dropping the
    tail — that was the bug that caused later intersections to disappear.
    """
    import base64, io
    from pdf2image import convert_from_path, pdfinfo_from_path

    warnings = []
    try:
        info = pdfinfo_from_path(str(filepath))
        total_pages = int(info.get("Pages", 0))
    except Exception:
        total_pages = 0  # treat as unknown; cap still applies via last_page

    if total_pages and total_pages > max_pages:
        warnings.append(
            f"PDF has {total_pages} pages but extraction cap is {max_pages}. "
            f"Only the first {max_pages} pages were sent to the agent — "
            f"any intersections appearing on pages {max_pages + 1}-{total_pages} "
            f"were NOT extracted. Raise MAX_PDF_PAGES or split the file."
        )

    images = convert_from_path(str(filepath), dpi=dpi, last_page=max_pages)
    encoded = []
    for img in images:
        # Resize if too large — Claude has size limits per image
        max_dim = 1568  # Claude's max recommended dimension
        if max(img.size) > max_dim:
            ratio = max_dim / max(img.size)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size)

        buf = io.BytesIO()
        img.save(buf, format='PNG', optimize=True)
        encoded.append(base64.standard_b64encode(buf.getvalue()).decode('utf-8'))
    return encoded, warnings

def _read_pdf_text(filepath):
    """Fallback: extract text from PDF (less accurate for tables).
    Returns (text, list[warning_str]).
    """
    import pdfplumber
    warnings = []
    content = []
    with pdfplumber.open(filepath) as pdf:
        total_pages = len(pdf.pages)
        if total_pages > MAX_PDF_PAGES:
            warnings.append(
                f"PDF has {total_pages} pages but extraction cap is {MAX_PDF_PAGES} "
                f"(text-fallback path). Only the first {MAX_PDF_PAGES} pages were sent "
                f"to the agent — any intersections on pages "
                f"{MAX_PDF_PAGES + 1}-{total_pages} were NOT extracted."
            )
        for i, page in enumerate(pdf.pages[:MAX_PDF_PAGES]):
            content.append(f"\n=== PAGE {i+1} ===")
            text = page.extract_text(layout=True) or page.extract_text() or ""
            content.append(text)
    full = "\n".join(content)
    if len(full) > MAX_CHARS:
        warnings.append(
            f"PDF text is {len(full):,} chars but char cap is {MAX_CHARS:,}. "
            f"Content past the cap was NOT sent to the agent."
        )
        full = full[:MAX_CHARS]
    return full, warnings

def _read_text(filepath):
    """Returns (text, list[warning_str])."""
    with open(filepath, encoding='utf-8', errors='replace') as f:
        full = f.read()
    warnings = []
    if len(full) > MAX_CHARS:
        warnings.append(
            f"Text/CSV content is {len(full):,} chars but cap is {MAX_CHARS:,}. "
            f"Content past the cap was NOT sent to the agent."
        )
        full = full[:MAX_CHARS]
    return full, warnings

# ── EXTRACTION PROMPT ─────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a senior traffic engineer with deep expertise reading turning movement count files from ANY vendor across the US and Canada.

Read this count file and extract peak hour vehicle data. Use engineering judgment to figure out the file's structure — every vendor formats files differently. Reason from first principles.

=== CRITICAL — MULTI-INTERSECTION FILES ===

This file may contain MULTIPLE intersections. You MUST extract EVERY intersection
present in the file — do not stop after the first few. Scan the entire document
from start to end (including the last pages / last sheets / last rows).

Workflow:
  1. First, count how many distinct intersections are in the file. State the count
     in `format_summary` (e.g. "9 intersections, one per 4-page block").
  2. Then extract each one into the `intersections` array, in the order they
     appear in the file.
  3. If you counted N intersections, the array MUST contain N blocks. Returning
     fewer than N is a CRITICAL ERROR — re-scan and add the missing ones.

Common patterns to watch for:
  - One intersection per page (PDF) — every page typically has its own
  - One intersection per Excel sheet — check every sheet tab
  - Multiple intersections stacked in one sheet — look for repeating headers
  - A summary or cover page may list every intersection — use it as a checklist

Never skip an intersection because its data looks incomplete. Extract what's
there and note the gap in `notes`. Omitting an intersection entirely is worse
than extracting it with some null fields.

=== WHAT TO EXTRACT PER INTERSECTION, PER PERIOD (AM and PM) ===

TURNING MOVEMENTS (16 values):
  EBU EBL EBT EBR    (Eastbound: U-turn, Left, Through, Right)
  WBU WBL WBT WBR
  NBU NBL NBT NBR
  SBU SBL SBT SBR

  - U-turns ALWAYS separate from Left. Never merge.
  - If U-turn column exists but zero → 0
  - If no U-turn column in file → null
  - If whole approach doesn't exist → null for those 4 movements

PEAK HOUR START (format "HH:MM" 24-hour):
  - Use explicit peak hour if file states it
  - Otherwise find highest sum of 4 consecutive 15-min intervals
  - AM window: 06:00-10:00, PM window: 14:00-19:00

PHF: peak hour total / (4 × highest single 15-min interval). Round to 3 decimals.

HV% (Heavy Vehicle %) — definition:
  HV = everything non-passenger-car (buses, 2-axle trucks, 3-axle, 4+ axle, all trucks, mediums, articulated)
  Priority:
    1. If file has "HV" or "Heavy Vehicle" total → use it
    2. If classes split (Lights/Mediums/Articulated, or 2/3/4+ axle, or Vehicles/Buses) → sum all non-car classes
    3. If only "Cars" separate from "Total" → HV = Total - Cars
  HV / Total × 100. Round to 1 decimal.

=== OUTPUT — VALID JSON ONLY, NO MARKDOWN ===

The `intersections` array MUST contain one block per intersection in the file.
The example below shows TWO blocks to make this explicit — if the file has 9
intersections, return 9 blocks; if it has 1, return 1.

{
  "vendor_detected": "NDS|Quality Counts|Counts Unlimited|GRAM|Pape-Dawson|Unknown",
  "format_summary": "e.g. '9 intersections, one per 4-page block, NDS layout'",
  "intersections": [
    {
      "name": "Main St & 1st Ave",
      "am_peak_start": "07:45",
      "pm_peak_start": "15:45",
      "volumes": {
        "AM": {"EBU":0,"EBL":37,"EBT":1898,"EBR":20,"WBU":0,"WBL":52,"WBT":943,"WBR":23,"NBU":0,"NBL":71,"NBT":24,"NBR":88,"SBU":0,"SBL":161,"SBT":15,"SBR":39},
        "PM": {"EBU":0,"EBL":74,"EBT":1266,"EBR":25,"WBU":0,"WBL":61,"WBT":1675,"WBR":36,"NBU":0,"NBL":40,"NBT":19,"NBR":54,"SBU":0,"SBL":60,"SBT":7,"SBR":32}
      },
      "phf": {"AM": 0.956, "PM": 0.970},
      "hv_pct": {"AM": 2.6, "PM": 1.9},
      "hv_method": "how HV was computed",
      "notes": "any observations or ambiguities"
    },
    {
      "name": "Main St & 2nd Ave",
      "am_peak_start": "07:30",
      "pm_peak_start": "16:30",
      "volumes": { "AM": { "...": "..." }, "PM": { "...": "..." } },
      "phf": {"AM": 0.92, "PM": 0.95},
      "hv_pct": {"AM": 3.1, "PM": 2.4},
      "hv_method": "...",
      "notes": "..."
    }
    /* ...continue with one block per intersection found in the file... */
  ]
}"""

# ── CLAUDE CALL ───────────────────────────────────────────────────────────────
def extract(filepath, api_key):
    content, ftype, file_warnings = read_file(filepath)

    # Handle errors from text readers
    if isinstance(content, str) and content.startswith("ERROR"):
        raise IOError(content)

    # Select reference examples (using empty string for image inputs)
    sniff_text = content if isinstance(content, str) else ""
    examples = select_examples(sniff_text)
    examples_block = format_examples_for_prompt(examples)
    full_system = SYSTEM_PROMPT + examples_block

    # Build the user message — different shape for text vs images
    if ftype == 'pdf_images':
        # Vision-based: send each PDF page as an image
        user_content = [
            {"type": "text", "text": f"Filename: {Path(filepath).name}\n\nThe following images are pages from a traffic count PDF. Read the tables visually and extract the data."}
        ]
        for img_b64 in content:
            user_content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": img_b64,
                }
            })
    else:
        # Text-based: send file content as text
        user_content = f"Filename: {Path(filepath).name}\n\nFile content:\n{content}"

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=full_system,
        messages=[{"role": "user", "content": user_content}]
    )

    # Refuse to return partial JSON silently. If we hit max_tokens, the response
    # is truncated and json.loads might succeed on a partial array (worse than
    # failing — looks like a complete answer with intersections missing).
    if msg.stop_reason == "max_tokens":
        raise ValueError(
            f"Extraction response was truncated at max_tokens ({MAX_TOKENS}). "
            f"File is too large for one pass — raise MAX_TOKENS or split the file. "
            f"Usage: input={msg.usage.input_tokens}, output={msg.usage.output_tokens}."
        )

    text = msg.content[0].text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    text = text.strip().rstrip("```").strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError as e:
        debug = Path(filepath).stem + "_DEBUG.txt"
        with open(debug, "w", encoding="utf-8") as f:
            f.write(f"stop_reason: {msg.stop_reason}\ntokens: {msg.usage}\n\n{text}")
        raise ValueError(f"JSON parse failed ({e}). Debug: {debug}")

    result["source_file"] = Path(filepath).name
    result["file_type"] = ftype
    result["_examples_used"] = len(examples)
    if file_warnings:
        result["warnings"] = file_warnings
    return result
