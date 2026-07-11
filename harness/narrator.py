"""Narrator — the ONLY LLM call in the harness. Post-verdict, FAIL/MARGINAL only.

FIREWALL: the verdict, category, GEH numbers, and every check result are
decided by deterministic code (grader.py) BEFORE this module is invoked. The
narrator reads that numeric evidence and writes prose: a one-paragraph
explanation, and — only when the Grader's category is 'unknown' — a refined
category from the fixed taxonomy. It can never change a verdict, a number, or
a PASS.

Degrades gracefully: no API key, SDK missing, network down, or malformed
model output → a deterministic fallback narration. A narration failure must
never break the loop.
"""

import json
import os

CATEGORIES = (
    'convergence', 'conservation', 'phantom-movement', 'floor-violation',
    'accuracy-drift', 'input/schema', 'pipeline-crash', 'unknown',
)

MODEL = 'claude-opus-4-8'

_SYSTEM = (
    'You are the failure narrator for an automated known-answer test harness '
    'that grades a traffic-engineering NCHRP turning-movement balancing tool. '
    'You receive the deterministic grading evidence for one failed or marginal '
    'run. Write a single tight paragraph explaining what went wrong, naming '
    'the specific intersections/movements/links from the evidence. Then pick '
    'the best-fitting category from this fixed list: '
    + ', '.join(CATEGORIES) + '. '
    'You cannot change the verdict or any number. Category discipline: use '
    'convergence/conservation/phantom-movement/floor-violation ONLY if the '
    'correspondingly named T1 check is in failed_checks; use pipeline-crash '
    'or input/schema ONLY if the pipeline/schema-gate check failed. For '
    'probe failures (idempotency, orientation-sweep, telemetry, s8-export) '
    'keep "unknown" unless the evidence clearly shows accuracy-drift. '
    'Respond with ONLY a JSON object: '
    '{"category": "<one of the list>", "explanation": "<paragraph>"} '
    '— no markdown fences, no other text.'
)


def _fallback(grade):
    failed = [c['check'] for c in grade['checks'] if not c['ok']]
    return {
        'category': grade['failure_category'] or 'unknown',
        'explanation': (
            f"(LLM narration unavailable — deterministic summary) Verdict "
            f"{grade['verdict']}; failed checks: {', '.join(failed) or 'none'}; "
            f"worst GEH {grade['geh']['worst']:.2f} at "
            f"{grade['geh']['worst_movement']}."
        ),
        'narrated_by': 'fallback',
    }


def narrate(grade, run_context):
    """One LLM call over the numeric evidence. Returns
    {'category', 'explanation', 'narrated_by'} — never raises."""
    if grade['verdict'] == 'PASS':
        return {'category': None, 'explanation': '', 'narrated_by': 'none'}
    if not os.environ.get('ANTHROPIC_API_KEY'):
        return _fallback(grade)

    evidence = {
        'verdict': grade['verdict'],
        'grader_category': grade['failure_category'],
        'failed_checks': [
            {'check': c['check'], 'details': c['details'][:10]}
            for c in grade['checks'] if not c['ok']
        ],
        'geh_worst': grade['geh']['worst'],
        'geh_worst_movement': grade['geh']['worst_movement'],
        'geh_over_10_count': grade['geh']['n_over_marginal'],
        'geh_top_rows': grade['geh']['rows'][:15],
        'run_context': run_context,
    }
    try:
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=_SYSTEM,
            messages=[{'role': 'user', 'content': json.dumps(evidence)}],
        )
        text = next(b.text for b in response.content if b.type == 'text')
        parsed = json.loads(text.strip())
        category = parsed.get('category')
        explanation = parsed.get('explanation', '')
        if category not in CATEGORIES or not explanation:
            return _fallback(grade)
        # The narrator may only REFINE 'unknown'; a concrete grader category
        # is deterministic evidence and always wins.
        if grade['failure_category'] not in (None, 'unknown'):
            category = grade['failure_category']
        return {'category': category, 'explanation': explanation,
                'narrated_by': MODEL}
    except Exception:
        return _fallback(grade)
