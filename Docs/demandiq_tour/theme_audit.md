# Theme system — Phase 1 audit

**Date:** 2026-05-29
**Context:** v1 build from `/product-kickoff` DECISION (Night Traffic dark default + Sunshine light, Voyager / Positron map tiles, S1 modal picker).

> **Status (2026-05-29):** ✅ COMPLETE — all phases shipped on `main`.
> Phase 2 `80f6119`/`fad1e70` · Phase 3 `87efbd0` · Phase 3.5 `e631000`
> (S7 card body) · Phase 4 `5c84597` (Voyager/Positron tiles + export-restore
> fix) · Phase 5 `c13b077` (S1 picker + boot apply) · Phase 6 `7f560a2`
> (headless verification, 12/12 green in both themes). Pure helpers covered by
> `themeTiles.test.mjs` + `theme.test.mjs`. Deferred items below under
> "Audit queue" (#4–#7) remain open.
>
> **Phase 6 evidence** (`theme_screens/`, regenerate with
> `node frontend/tests/e2e/theme_screens.mjs`):
>
> | | Night Traffic | Sunshine |
> |---|---|---|
> | S1 picker | [s1_night-traffic](theme_screens/s1_night-traffic.png) | [s1_sunshine](theme_screens/s1_sunshine.png) |
> | Modal | [modal_night-traffic](theme_screens/modal_night-traffic.png) | [modal_sunshine](theme_screens/modal_sunshine.png) |
> | Map (Alpine) | [map_night-traffic](theme_screens/map_night-traffic.png) | [map_sunshine](theme_screens/map_sunshine.png) |

## Big finding: theming infrastructure already exists

The codebase has **674 `var(--…)` usages** across `frontend/src/styles/*.css` and a `:root` block in `frontend/src/index.css` already defines the chrome variables:

```css
--bg-base:        #07080D;
--bg-elevated:    rgba(255, 255, 255, 0.02);
--bg-hover:       rgba(255, 255, 255, 0.04);
--accent:         #0A84FF;
--accent-glow:    rgba(10, 132, 255, 0.06);
--text-primary:   #F0F2F8;
--text-secondary: #B8BFC9;
--text-tertiary:  #9AA3B2;
--border:         rgba(255, 255, 255, 0.07);
--border-strong:  rgba(255, 255, 255, 0.15);
```

This means the theme work is **not** a 3-day mass-migration. It's a ~1 day fix because the abstraction layer the kickoff DECISION proposed is already in place.

**Revised v1 cost:** ~1 day for both themes (was 3).

## Hex-literal inventory by bucket

Total distinct hex values across the 9 `src/styles/*.css` files: ~17 distinct colors, ~90 occurrences.

### Bucket A — UI chrome (should be themeable; mostly stray literals that escaped the existing var system)

| Hex | Files | Should become |
|---|---|---|
| `#07080D` | `map.css:16, 139`, `results.css:197` | `var(--bg-base)` |
| `#0F1118` | `map.css:528, 1006, 1186`, `results.css:244, 255`, `volumes.css:254` | `var(--bg-base)` or new `var(--bg-deep)` |
| `#1A1D26` | `balancing.css:329, 355`, `map.css:600`, `volumes.css:590` | `var(--bg-elevated)` (per intent) |
| `#1A1F2C` | `map.css:750` (one site) | investigate — probably a text colour for a pin label |
| `#fff` / `#ffffff` / `#FFFFFF` | many | `var(--text-primary)` for text, dedicated value where genuine pure white is intended (e.g. button text contrast) |

Count of bucket A stray literals: **~30**. The migration is mostly "we wrote `#fff` when we meant `var(--text-primary)`."

### Bucket B — Brand / accent (per-theme but constant within theme)

| Hex | Files | Should become |
|---|---|---|
| `#0A84FF` | `approach.css:141`, `map.css:131, 451`, `results.css:99, 276`, `volumes.css:299` | `var(--accent)` — already aliased; these are stray |
| `#4DA9FF` | `approach.css:317`, `volumes.css:327` | new `var(--accent-hover)` |

Count: **~8 stray accent literals**. Same pattern as Bucket A — should already be using `var(--accent)`.

### Bucket C — Data encoding (CONSTANT across all themes)

These are semantic colors. The kickoff DECISION + the audit's existing F-numbering already treat these as constants. **No migration; keep as hex with a documented comment per file.**

| Hex | Meaning |
|---|---|
| `#34D399` | Conservation OK; ipf-stable; success |
| `#FFB627` | Warn / amber dot |
| `#FFD27A` | Warn text tone |
| `#FFB454` | FRACTIONAL-VOLUME tone (Stage 10.1, see analysis.css) |
| `#FF6B6B` | Error / NCHRP-LINK-DELTA red |
| `#FF8B8B` | Error text tone |
| `#B0413E` | Error border (S7 results page) |
| `#C5D0FA` | F7 smoothed row tone |
| `#FFD60A` | S2 selected-link halo (in `MapView.jsx`, not CSS — note in audit) |
| `#0A84FF` (data context) | Pre-balance flow map link color (S7 PRD-03 context) — verify whether to themen this or keep |

Plus a "Bucket C label" should be promoted to a single semantic variable layer so they're discoverable: `--semantic-ok / --semantic-warn / --semantic-warn-text / --semantic-fail / --semantic-fail-text / --semantic-fractional / --semantic-smoothed / --semantic-halo`. **Optional**; the kickoff said don't change these so skip in v1.

### Bucket D — Already variables

The other 674 usages. No migration needed.

## Two themes to define (Phase 2)

Per the DECISION:

### Night Traffic (dark, default — current behavior, slightly polished)

| Token | Value |
|---|---|
| `--bg-base` | `#07080D` (current) |
| `--bg-elevated` | `#13161E` (replaces the half-transparent layer; concrete to dampen tile show-through) |
| `--bg-deep` | `#0F1118` (currently used as a darker container) |
| `--surface` | `#1A1D26` (currently used as a "card" tone) |
| `--text-primary` | `#F0F2F8` |
| `--text-secondary` | `#B8BFC9` |
| `--text-tertiary` | `#9AA3B2` |
| `--border` | `rgba(255, 255, 255, 0.07)` |
| `--border-strong` | `rgba(255, 255, 255, 0.15)` |
| `--accent` | `#60A5FA` (matches the kickoff DECISION; current `#0A84FF` is slightly hot but acceptable — confirm before swap) |
| `--accent-hover` | `#7DB3FB` |

### Sunshine (light, optional)

| Token | Value |
|---|---|
| `--bg-base` | `#FAFAF9` |
| `--bg-elevated` | `#FFFFFF` |
| `--bg-deep` | `#F5F5F4` |
| `--surface` | `#FFFFFF` |
| `--text-primary` | `#1C1917` |
| `--text-secondary` | `#57534E` |
| `--text-tertiary` | `#78716C` |
| `--border` | `#E7E5E4` |
| `--border-strong` | `#D6D3D1` |
| `--accent` | `#2563EB` |
| `--accent-hover` | `#3B82F6` |

## Phases that remain

- **Phase 2 (~½ day):** Add `themes.css` with both palettes, gated on `:root[data-theme="…"]`. Move the current `:root` block from `index.css` to it as the Night Traffic default.
- **Phase 3 (~½ day):** Fix the ~38 stray hex literals (Bucket A + B) — most are `#fff` that should be `var(--text-primary)` and `#0A84FF` that should be `var(--accent)`. Bucket C stays with documented comments.
- **Phase 4 (~½ day):** `MapView.jsx` switches Dark Matter tile URL → Voyager for any theme that isn't Sunshine, Positron for Sunshine. Tile-layer swap reactive to `data-theme` mutation observer (no page reload).
- **Phase 5 (~½ day):** S1 `<AppearanceCard>` button → modal with 2 cards (Night Traffic / Sunshine). Persist `localStorage['demandiq:theme']`. Read on app boot; apply via `document.documentElement.setAttribute('data-theme', …)`.
- **Phase 6 (~½ day):** Verify both themes via headless screenshots on Alpine fixture + contrast spot-check on hero / drops banner / resolved-targets / line-diagram-grid placeholder + Map readability in both themes.

**Total revised:** ~2.5 days for both themes (vs. the kickoff's ~3-day estimate, because Phase 1 found the infrastructure was already there).

## Next session pickup

Start with Phase 2 — create `frontend/src/styles/themes.css` and gate the existing `:root` block under `[data-theme="night-traffic"]`, then add a sibling `[data-theme="sunshine"]` block. Verify by setting the attribute in the browser devtools and confirming both themes render without breakage.
