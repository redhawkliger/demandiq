"""Schema gate — validate every puzzle against the frozen project schema.

A puzzle that doesn't match `harness/schema/project.schema.json` is a LOUD
harness failure (category `input/schema`), never a silent skip: if the
Puzzler emits a shape the frontend wouldn't persist, every downstream verdict
would be a statement about a project that can't exist.

Implements the JSON Schema subset the frozen schema actually uses, with no
third-party dependency (`jsonschema` is not in the repo's requirements):
type, required, properties, additionalProperties (bool or schema), items,
enum, minimum, minItems, pattern, propertyNames, $ref (#/$defs/... only).
Deterministic; returns every violation with a JSON-pointer-ish path.
"""

import functools
import json
import re
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / 'schema' / 'project.schema.json'

_TYPE_CHECKS = {
    'object': lambda v: isinstance(v, dict),
    'array': lambda v: isinstance(v, list),
    'string': lambda v: isinstance(v, str),
    'number': lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    'integer': lambda v: isinstance(v, int) and not isinstance(v, bool),
    'boolean': lambda v: isinstance(v, bool),
    'null': lambda v: v is None,
}


class SchemaGateError(Exception):
    """Raised when a puzzle fails schema validation."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__(
            f"puzzle failed schema gate with {len(errors)} violation(s):\n"
            + '\n'.join(f'  - {e}' for e in errors[:20])
        )


@functools.lru_cache(maxsize=1)
def load_schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def _resolve(schema, root):
    ref = schema.get('$ref')
    if ref is None:
        return schema
    if not ref.startswith('#/'):
        raise ValueError(f'unsupported $ref: {ref}')
    node = root
    for part in ref[2:].split('/'):
        node = node[part]
    return node


def _validate(value, schema, root, path, errors):
    schema = _resolve(schema, root)

    t = schema.get('type')
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_TYPE_CHECKS[x](value) for x in types):
            errors.append(f'{path}: expected type {t}, got {type(value).__name__}')
            return  # deeper checks are meaningless on the wrong type

    if 'enum' in schema and value not in schema['enum']:
        errors.append(f'{path}: {value!r} not in enum {schema["enum"]}')

    if 'minimum' in schema and isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema['minimum']:
            errors.append(f'{path}: {value} < minimum {schema["minimum"]}')

    if 'pattern' in schema and isinstance(value, str):
        if not re.search(schema['pattern'], value):
            errors.append(f'{path}: {value!r} does not match pattern {schema["pattern"]!r}')

    if isinstance(value, dict):
        for req in schema.get('required', []):
            if req not in value:
                errors.append(f'{path}: missing required key {req!r}')
        props = schema.get('properties', {})
        for k, v in value.items():
            if k in props:
                _validate(v, props[k], root, f'{path}.{k}', errors)
            else:
                extra = schema.get('additionalProperties')
                if extra is False:
                    errors.append(f'{path}: unexpected key {k!r}')
                elif isinstance(extra, dict):
                    _validate(v, extra, root, f'{path}.{k}', errors)
            if 'propertyNames' in schema:
                _validate(k, schema['propertyNames'], root, f'{path}.<key {k!r}>', errors)

    if isinstance(value, list):
        if 'minItems' in schema and len(value) < schema['minItems']:
            errors.append(f'{path}: {len(value)} items < minItems {schema["minItems"]}')
        item_schema = schema.get('items')
        if item_schema is not None:
            for i, item in enumerate(value):
                _validate(item, item_schema, root, f'{path}[{i}]', errors)


def validate_project(project):
    """Validate a demandiq:project snapshot. Raises SchemaGateError on any
    violation; returns None on success."""
    schema = load_schema()
    errors = []
    _validate(project, schema, schema, '$', errors)
    if errors:
        raise SchemaGateError(errors)
