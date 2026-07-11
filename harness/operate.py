"""Operator — drives the real DemandIQ balance pipeline. Pure code, no LLM.

MODULE BOUNDARY (firewall): this module receives ONLY the puzzle — the
`demandiq:project` snapshot dict. It never imports the Puzzler, never sees
the answer key or the perturbation log, and holds no state between calls.
Anything the Grader compares against ground truth flows through the
orchestrator, not through here.

The payload builder is a line-for-line port of `buildPayload` in
frontend/src/sessions/S6_RunAnalysis.jsx — the same data path the UI uses to
turn the persisted project into the POST /balance-nchrp body (the frontend
reaches the endpoint via Vite's /api proxy; we call the backend directly).
"""

import json
import urllib.error
import urllib.request

DEFAULT_BASE_URL = 'http://localhost:8000'


class PipelineError(Exception):
    """The tool's pipeline failed (HTTP error, connection refused, bad JSON).
    Carries enough detail for a `pipeline-crash` case file."""

    def __init__(self, stage, detail):
        self.stage = stage
        self.detail = detail
        super().__init__(f'{stage}: {detail}')


def build_balance_payload(project):
    """Port of S6_RunAnalysis.jsx buildPayload(intersections, balancing, links)."""
    intersections = project.get('intersections') or []
    balancing = project.get('balancing') or {}
    links = project.get('links') or []

    num_by_pin = {it['id']: it['num'] for it in intersections}

    def strip_vols(period):
        out = {}
        for it in intersections:
            cells = (it.get('volumes') or {}).get(period) or {}
            stripped = {}
            for mv, cell in cells.items():
                value = (cell or {}).get('value')
                if value is not None and value != '':
                    stripped[mv] = value
            if stripped:
                out[str(it['num'])] = stripped
        return out

    network_links = []
    for link in links:
        from_num = num_by_pin.get(link.get('fromId'))
        to_num = num_by_pin.get(link.get('toId'))
        if from_num is None or to_num is None:
            continue
        network_links.append({
            'fromNum': from_num,
            'toNum': to_num,
            'direction': link.get('direction'),
            'mode': link.get('mode', 'Full'),
        })

    return {
        'intersections': [
            {'num': it['num'], 'name': it['name'], 'lat': it['lat'], 'lng': it['lng']}
            for it in intersections
        ],
        'unbalanced_volumes': {'AM': strip_vols('AM'), 'PM': strip_vols('PM')},
        'links': network_links,
        # Same fallbacks as the UI (buildPayload's ?? defaults, verbatim).
        'link_resolution_method': balancing.get('linkResolution', 'larger'),
        'max_iterations': balancing.get('maxIterations', 100),
        'tolerance': balancing.get('convergenceThreshold', 0.5),
    }


def _post_json(url, payload, timeout=120):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body, headers={'Content-Type': 'application/json'}, method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode(errors='replace')[:2000]
        except Exception:
            detail = ''
        raise PipelineError('http', f'HTTP {e.code} from {url}: {detail}')
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise PipelineError('connection', f'{url}: {e}')
    try:
        return json.loads(raw), raw
    except json.JSONDecodeError as e:
        raise PipelineError('decode', f'{url} returned non-JSON: {e}')


def run_balance(project, base_url=DEFAULT_BASE_URL):
    """Load the puzzle the way the UI does and call the S6 balance endpoint.

    Returns (tool_output dict, raw response bytes). Raises PipelineError on
    any transport/HTTP failure."""
    payload = build_balance_payload(project)
    return _post_json(f'{base_url}/balance-nchrp', payload)


def run_corridor_diagram(project, tool_output, base_url=DEFAULT_BASE_URL):
    """S8 export probe transport: call /corridor-diagram the way S8 does —
    cells in corridor (list) order, balanced volumes from the run, resolved
    links from the run. Returns the response dict."""
    intersections = project.get('intersections') or []
    balancing = project.get('balancing') or {}
    balanced = tool_output.get('balanced') or {}
    cells = []
    for it in intersections:
        u_vols = {}
        for mv, cell in ((it.get('volumes') or {}).get('AM') or {}).items():
            if (cell or {}).get('value') not in (None, ''):
                u_vols[mv] = cell['value']
        cells.append({
            'intersection': {'num': it['num'], 'name': it['name'],
                             'lat': it['lat'], 'lng': it['lng']},
            'u_vols': u_vols,
            # S8 puts the AM balanced volumes on each cell (the per-period
            # top-level b_vols below override per figure).
            'b_vols': (balanced.get('AM') or {}).get(str(it['num'])) or {},
            'overrides': {},
        })
    project_name = (project.get('project') or {}).get('name') or 'Project'
    payload = {
        'cells': cells,
        'resolved_links': tool_output.get('resolved_links') or {'AM': [], 'PM': []},
        'corridor_dir': balancing.get('corridorDir'),
        'view_mode': 'combined',
        'cols': 3,
        'title': f'{project_name} — corridor line diagram',
        'b_vols': balanced,
    }
    out, _raw = _post_json(f'{base_url}/corridor-diagram', payload, timeout=300)
    return out
