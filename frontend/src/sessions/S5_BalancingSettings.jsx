import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, Lock } from 'lucide-react'

import {
  subscribe,
  getSnapshot,
  setBalancing,
  setLinkBalanceMode,
  ensureBalancingDefaults,
} from '../store/projectStore'
import { haversineMi } from '../lib/geo'

import '../styles/forms.css'
import '../styles/map.css' // .di-banner, .di-btn-primary, .di-btn-secondary
import '../styles/balancing.css'

const DIR_OPTS = [
  { value: 'EB/WB', label: 'EB/WB' },
  { value: 'NB/SB', label: 'NB/SB' },
]
const PEAK_MODE_OPTS = [
  { value: 'Corridor', label: 'Corridor (shared peak)' },
  { value: 'Independent', label: 'Independent (per-intersection peak)' },
]
const LINK_MODES = ['Full', 'Land Use', 'None']

// hh:mm string compare works because format is fixed-width zero-padded
const timeLT = (a, b) => a < b
const timeLE = (a, b) => a <= b

function hasAnyVolumes(intersections) {
  for (const it of intersections) {
    for (const period of ['AM', 'PM']) {
      const v = it.volumes?.[period]
      if (v && Object.keys(v).length > 0) return true
    }
  }
  return false
}

export default function S5_BalancingSettings() {
  const navigate = useNavigate()
  const snap = useSyncExternalStore(subscribe, getSnapshot, () => ({}))
  const intersections = snap.intersections || []
  const balancing = snap.balancing || {}

  const needsVolumes = intersections.length === 0 || !hasAnyVolumes(intersections)

  // ── One-time defaults ───────────────────────────────────────────────
  const didInit = useRef(false)
  useEffect(() => {
    if (didInit.current || needsVolumes) return
    didInit.current = true
    ensureBalancingDefaults()
  }, [needsVolumes])

  // ── Empty / unconfigured guard ──────────────────────────────────────
  useEffect(() => {
    if (!needsVolumes) return
    const t = setTimeout(() => navigate('/volumes'), 1000)
    return () => clearTimeout(t)
  }, [needsVolumes, navigate])

  const [advancedOpen, setAdvancedOpen] = useState(false)

  if (needsVolumes) {
    return (
      <div className="di-s5 di-s5--center">
        <div className="di-s4-empty">
          <div className="di-banner">Enter volumes first.</div>
          <p className="di-s3-empty__sub">Redirecting…</p>
        </div>
      </div>
    )
  }

  // Pull current values, with safe fallbacks during the brief window before the
  // defaults effect persists. UI stays consistent either way.
  const enabled    = balancing.enabled ?? true
  const corrDir    = balancing.corridorDir ?? 'EB/WB'
  const peakMode   = balancing.peakMode ?? 'Corridor'
  const am         = balancing.amWindow ?? { start: '07:00', end: '09:00' }
  const pm         = balancing.pmWindow ?? { start: '16:00', end: '18:00' }
  const convStored = balancing.convergenceThreshold ?? 0.01
  const maxIter    = balancing.maxIterations ?? 200
  const linkModes  = balancing.linkBalanceModes ?? {}

  // ── Validation ──────────────────────────────────────────────────────
  const errors = {
    amEnd: !timeLT(am.start, am.end) ? 'AM end must be after AM start' : null,
    pmEnd: !timeLT(pm.start, pm.end) ? 'PM end must be after PM start' : null,
    pmStart: !timeLE(am.end, pm.start) ? 'PM window cannot overlap AM' : null,
    conv: !(convStored > 0 && convStored * 100 >= 0.1 && convStored * 100 <= 5)
      ? 'Must be between 0.1% and 5.0%'
      : null,
    iter: !(maxIter >= 10 && maxIter <= 1000)
      ? 'Must be between 10 and 1000'
      : null,
  }
  const isValid = Object.values(errors).every((e) => e === null)

  // ── Pairs (S2-sorted) for the per-link table ───────────────────────
  const pairs = []
  for (let i = 0; i < intersections.length - 1; i++) {
    const a = intersections[i]
    const b = intersections[i + 1]
    pairs.push({
      id: `${a.id}__${b.id}`,
      a, b,
      distance: haversineMi(a, b),
    })
  }

  // ── Mode-count breakdown for summary ───────────────────────────────
  const modeCounts = pairs.reduce(
    (acc, p) => {
      const m = (linkModes[p.id]?.mode) ?? 'Full'
      acc[m] = (acc[m] ?? 0) + 1
      return acc
    },
    { Full: 0, 'Land Use': 0, None: 0 }
  )

  return (
    <div className="di-s5">
      <div className="di-s5__body">

        {/* ────────── LEFT FORM ────────── */}
        <div className="di-s5__form">

          {/* Section A — Balancing */}
          <section className="di-s5-section">
            <h3 className="di-s5-section__title">Balancing</h3>

            <div className="di-s5-row">
              <div className="di-s5-row__label">
                Balance volumes
                <div className="di-s5-row__sub">When off, volumes pass through to S6 unchanged.</div>
              </div>
              <ToggleSwitch checked={enabled} onChange={(v) => setBalancing({ enabled: v })} />
            </div>

            <div className="di-s5-row">
              <div className="di-s5-row__label">Corridor direction</div>
              <Segmented
                options={DIR_OPTS}
                value={corrDir}
                disabled={!enabled}
                onChange={(v) => setBalancing({ corridorDir: v })}
              />
            </div>

            <div className="di-s5-row">
              <div className="di-s5-row__label">Peak hour mode</div>
              <Segmented
                options={PEAK_MODE_OPTS}
                value={peakMode}
                disabled={!enabled}
                onChange={(v) => setBalancing({ peakMode: v })}
              />
            </div>
          </section>

          {/* Section B — Peak windows */}
          <section className="di-s5-section">
            <h3 className="di-s5-section__title">Peak windows</h3>

            <div className="di-s5-stack">
              <div className="di-s5-stack__label">AM window</div>
              <div className="di-s5-time">
                <input
                  type="time"
                  value={am.start}
                  disabled={!enabled}
                  onChange={(e) => setBalancing({ amWindow: { ...am, start: e.target.value } })}
                />
                <span className="di-s5-time__sep">—</span>
                <input
                  type="time"
                  value={am.end}
                  disabled={!enabled}
                  onChange={(e) => setBalancing({ amWindow: { ...am, end: e.target.value } })}
                />
              </div>
              {errors.amEnd && <div className="di-s5-err">{errors.amEnd}</div>}
              <div className="di-s5-stack__sub">
                Peak hour search window. Furness picks the highest 4 consecutive 15-min intervals within this range.
              </div>
            </div>

            <div className="di-s5-stack">
              <div className="di-s5-stack__label">PM window</div>
              <div className="di-s5-time">
                <input
                  type="time"
                  value={pm.start}
                  disabled={!enabled}
                  onChange={(e) => setBalancing({ pmWindow: { ...pm, start: e.target.value } })}
                />
                <span className="di-s5-time__sep">—</span>
                <input
                  type="time"
                  value={pm.end}
                  disabled={!enabled}
                  onChange={(e) => setBalancing({ pmWindow: { ...pm, end: e.target.value } })}
                />
              </div>
              {errors.pmStart && <div className="di-s5-err">{errors.pmStart}</div>}
              {errors.pmEnd && <div className="di-s5-err">{errors.pmEnd}</div>}
              <div className="di-s5-stack__sub">
                Peak hour search window. Furness picks the highest 4 consecutive 15-min intervals within this range.
              </div>
            </div>
          </section>

          {/* Section C — Furness engine */}
          <section className="di-s5-section">
            <h3 className="di-s5-section__title">Furness engine parameters</h3>

            <div className="di-s5-row">
              <div className="di-s5-row__label">Convergence threshold</div>
              <div>
                <NumWithSuffix
                  value={Math.round(convStored * 1000) / 10}
                  suffix="%"
                  step={0.1}
                  min={0.1}
                  max={5}
                  err={!!errors.conv}
                  disabled={!enabled}
                  onChange={(v) =>
                    setBalancing({ convergenceThreshold: v == null ? null : v / 100 })
                  }
                />
                {errors.conv && <div className="di-s5-err">{errors.conv}</div>}
              </div>
            </div>

            <div className="di-s5-row">
              <div className="di-s5-row__label">Max iterations</div>
              <div>
                <NumWithSuffix
                  value={maxIter}
                  step={10}
                  min={10}
                  max={1000}
                  err={!!errors.iter}
                  disabled={!enabled}
                  onChange={(v) =>
                    setBalancing({ maxIterations: v == null ? null : Math.round(v) })
                  }
                />
                {errors.iter && <div className="di-s5-err">{errors.iter}</div>}
              </div>
            </div>
          </section>

          {/* Section D — Locked rules */}
          <section className="di-s5-section">
            <h3 className="di-s5-section__title">Locked rules</h3>
            <div className="di-s5-locked">
              <div className="di-s5-locked__row">
                <Lock size={12} className="di-s5-locked__icon" />
                <span><b>Rounding:</b> nearest 5, minimum 5 for non-zero movements</span>
              </div>
              <div className="di-s5-locked__row">
                <Lock size={12} className="di-s5-locked__icon" />
                <span><b>U-turns:</b> extracted but excluded from balancing (pass-through)</span>
              </div>
            </div>
          </section>

          {/* Advanced — per-link */}
          <section className="di-s5-section">
            {pairs.length === 0 ? (
              <div className="di-s5-disc__note" style={{ padding: '12px 0' }}>
                Per-link settings require 2+ intersections.
              </div>
            ) : (
              <div className={`di-s5-disc${advancedOpen ? ' di-s5-disc--open' : ''}`}>
                <button
                  type="button"
                  className="di-s5-disc__btn"
                  onClick={() => setAdvancedOpen((o) => !o)}
                  aria-expanded={advancedOpen}
                >
                  <span>Advanced — per-link balance modes</span>
                  <ChevronDown size={16} className="di-s5-disc__chev" />
                </button>
                {advancedOpen && (
                  <div className="di-s5-disc__body">
                    <div className="di-s5-link__head">
                      <span>Link</span>
                      <span>Mode</span>
                      <span>Threshold</span>
                    </div>
                    {pairs.map((p) => {
                      const cur = linkModes[p.id] ?? { mode: 'Full', threshold: 0 }
                      const isLandUse = cur.mode === 'Land Use'
                      return (
                        <div key={p.id} className="di-s5-link">
                          <div className="di-s5-link__label">
                            Int {String(p.a.num).padStart(2, '0')} → Int {String(p.b.num).padStart(2, '0')}
                            <span className="di-s5-link__dist">({p.distance.toFixed(1)} mi)</span>
                          </div>
                          <select
                            className="di-select--sm"
                            value={cur.mode}
                            disabled={!enabled}
                            onChange={(e) => setLinkBalanceMode(p.id, e.target.value, cur.threshold)}
                          >
                            {LINK_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
                          </select>
                          <div className={`di-s5-link__thresh${!isLandUse ? ' di-s5-link__thresh--dis' : ''}`}>
                            <input
                              type="number"
                              min="0"
                              step="1"
                              value={cur.threshold ?? 0}
                              disabled={!isLandUse || !enabled}
                              onChange={(e) =>
                                setLinkBalanceMode(
                                  p.id,
                                  cur.mode,
                                  e.target.value === '' ? 0 : Math.max(0, Number(e.target.value))
                                )
                              }
                            />
                            <span className="di-s5-link__thresh-suffix">veh</span>
                          </div>
                        </div>
                      )
                    })}
                    <div className="di-s5-stack__sub" style={{ marginTop: 10 }}>
                      Land Use mode allows the threshold gap between paired volumes after balancing.
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>

        {/* ────────── RIGHT SUMMARY ────────── */}
        <aside className="di-s5__summary">
          <h3 className="di-s5-sum__title">Configuration</h3>
          <p className="di-s5-sum__sub">
            Method: NCHRP 255 Chapter 8 — Furness/Fratar iterative balancing<br />
            Mode: Balance to Average
          </p>
          {!enabled ? (
            <div className="di-s5-sum--off">Balancing disabled — values will pass through.</div>
          ) : (
            <div className="di-s5-sum__list">
              <SumRow k="Direction" v={corrDir} />
              <SumRow
                k="Peak mode"
                v={peakMode === 'Corridor' ? 'Corridor (shared)' : 'Independent (per-int)'}
              />
              <SumRow k="AM" v={`${am.start} – ${am.end}`} />
              <SumRow k="PM" v={`${pm.start} – ${pm.end}`} />
              <SumRow k="Convergence" v={`${(convStored * 100).toFixed(1)}%`} />
              <SumRow k="Max iterations" v={String(maxIter)} />
              {pairs.length > 0 && (
                <div className="di-s5-sum__row">
                  <span className="di-s5-sum__key">Links</span>
                  <span className="di-s5-sum__val">
                    {pairs.length}
                    <div className="di-s5-sum__breakdown">
                      Full: {modeCounts.Full} · Land Use: {modeCounts['Land Use']} · None: {modeCounts.None}
                    </div>
                  </span>
                </div>
              )}
            </div>
          )}
        </aside>
      </div>

      <footer className="di-s5__footer">
        <button
          type="button"
          className="di-btn-primary"
          disabled={!isValid}
          onClick={() => navigate('/analysis')}
        >
          Continue to analysis →
        </button>
      </footer>
    </div>
  )
}

// ── Inline helpers ──────────────────────────────────────────────────────

function ToggleSwitch({ checked, onChange, disabled }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      className={`di-toggle${checked ? ' di-toggle--on' : ''}`}
      onClick={() => onChange(!checked)}
    >
      <span className="di-toggle__handle" />
    </button>
  )
}

function Segmented({ options, value, onChange, disabled }) {
  return (
    <div className="di-segmented">
      {options.map((opt) => {
        const isOn = opt.value === value
        return (
          <button
            key={opt.value}
            type="button"
            aria-pressed={isOn}
            disabled={disabled}
            className={`di-segmented__opt${isOn ? ' di-segmented__opt--on' : ''}`}
            onClick={() => onChange(opt.value)}
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}

function NumWithSuffix({ value, suffix, step, min, max, err, disabled, onChange }) {
  return (
    <div className={`di-s5-num${err ? ' di-s5-num--err' : ''}`}>
      <input
        type="number"
        step={step}
        min={min}
        max={max}
        disabled={disabled}
        value={value ?? ''}
        onChange={(e) => {
          const raw = e.target.value
          onChange(raw === '' ? null : Number(raw))
        }}
      />
      {suffix && <span className="di-s5-num__suffix">{suffix}</span>}
    </div>
  )
}

function SumRow({ k, v }) {
  return (
    <div className="di-s5-sum__row">
      <span className="di-s5-sum__key">{k}</span>
      <span className="di-s5-sum__val">{v}</span>
    </div>
  )
}
