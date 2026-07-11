# Goldens (deferred — hook only)

Drop hand-vetted `<name>.golden.json` cases here:

```json
{
  "name": "…",
  "project": { "…": "a demandiq:project snapshot" },
  "expected_balanced": { "AM": {"1": {"EBT": 500}}, "PM": {} }
}
```

Golden cases are real-world corridors whose correct output an engineer has
signed off on — unlike Puzzler runs, they don't have a constructed answer
key. v1 ships no cases and no runner; the loop deliberately ignores this
folder. When goldens land, add a `--goldens` mode to `harness/loop.py` that
grades each case with the same Grader (GEH vs `expected_balanced`).
