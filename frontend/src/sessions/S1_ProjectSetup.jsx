import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getProjectMeta, setProjectMeta } from '../store/projectStore'
import { THEMES, getStoredTheme, applyTheme } from '../lib/theme'
import ThemePickerModal from '../components/ThemePickerModal'
import '../styles/forms.css'

const todayISO = () => {
  const d = new Date()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}

const DEFAULTS = () => ({
  name: '',
  client: '',
  projectNumber: '',
  analyst: '',
  checker: '',
  date: todayISO(),
  scenario: 'Existing',
  projectType: null,
  analysisPeriods: ['AM', 'PM'],   // default both; AM/PM toggle independently
})

const PROJECT_TYPES = ['Corridor', 'Zone', 'Single Intersection']
const PERIODS = ['AM', 'PM']

const isFilled = (v) => typeof v === 'string' && v.trim().length > 0

// Required fields, in display order. Returns the labels still missing so the
// form can both gate "Save and continue" AND tell the engineer exactly what to
// fill — the button is never a silent dead-end.
function missingRequired(form) {
  const missing = []
  if (!isFilled(form.name)) missing.push('Project Name')
  if (!isFilled(form.client)) missing.push('Client / Agency')
  if (!isFilled(form.analyst)) missing.push('Analyst Initials')
  if (!isFilled(form.date)) missing.push('Date')
  if (!isFilled(form.scenario)) missing.push('Scenario Name')
  if (!form.projectType) missing.push('Project Type')
  if (!Array.isArray(form.analysisPeriods) || form.analysisPeriods.length === 0) missing.push('Analysis Period')
  return missing
}

export default function S1_ProjectSetup() {
  const navigate = useNavigate()
  const [form, setForm] = useState(() => ({ ...DEFAULTS(), ...(getProjectMeta() ?? {}) }))

  // Debounced auto-save so the engineer never loses work.
  const saveTimer = useRef(null)
  useEffect(() => {
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => setProjectMeta(form), 400)
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current)
    }
  }, [form])

  // Appearance is a global, per-device preference — NOT project data — so it
  // lives outside `form`/projectStore. The modal applies it live; we mirror the
  // applied id here only to highlight the right card and the trigger swatch.
  const [theme, setTheme] = useState(getStoredTheme)
  const [themeOpen, setThemeOpen] = useState(false)
  const activeTheme = THEMES.find((t) => t.id === theme) ?? THEMES[0]
  const chooseTheme = (id) => setTheme(applyTheme(id))

  const update = (key, value) => setForm((f) => ({ ...f, [key]: value }))

  const togglePeriod = (p) =>
    setForm((f) => {
      const set = new Set(f.analysisPeriods)
      if (set.has(p)) set.delete(p)
      else set.add(p)
      return { ...f, analysisPeriods: PERIODS.filter((x) => set.has(x)) }
    })

  // Only surface validation errors AFTER the engineer tries to continue, so the
  // form isn't pre-littered with red on first load.
  const [attempted, setAttempted] = useState(false)
  const missing = missingRequired(form)
  const isValid = missing.length === 0

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!isValid) { setAttempted(true); return } // show what's missing; don't navigate
    if (saveTimer.current) clearTimeout(saveTimer.current)
    setProjectMeta(form) // flush, don't wait for the debounce window
    navigate('/map')
  }

  // Small render helper — keeps each field one line of JSX. Not exported.
  const textField = (label, key, required, opts = {}) => {
    const invalid = attempted && required && !isFilled(form[key])
    return (
      <div className="di-field">
        <label className="di-label" htmlFor={`f-${key}`}>
          {label}
          {required && <span className="di-required">*</span>}
        </label>
        <input
          id={`f-${key}`}
          className={`di-input${invalid ? ' di-input--error' : ''}`}
          type={opts.type || 'text'}
          value={form[key] ?? ''}
          placeholder={opts.placeholder}
          autoComplete="off"
          aria-invalid={invalid || undefined}
          onChange={(e) => update(key, e.target.value)}
        />
      </div>
    )
  }

  return (
    <form className="di-page" onSubmit={handleSubmit} noValidate>
      <div className="di-eyebrow">Project Setup</div>
      <h1 className="di-h1">New project</h1>
      <p className="di-subtitle">
        Set up the project once. These details flow through every step.
      </p>

      <div className="di-form">
        <div className="di-row">
          {textField('Project Name', 'name', true, { placeholder: 'e.g. Main Street Corridor Study' })}
          {textField('Project Number', 'projectNumber', false, { placeholder: '30901249.003' })}
        </div>

        {textField('Client / Agency', 'client', true, { placeholder: 'e.g. City of Austin' })}

        <div className="di-row">
          {textField('Analyst Initials', 'analyst', true, { placeholder: 'AK' })}
          {textField('Checker Initials', 'checker', false, { placeholder: 'JS' })}
        </div>

        <div className="di-row">
          {textField('Date', 'date', true, { type: 'date' })}
          {textField('Scenario Name', 'scenario', true, { placeholder: 'Existing' })}
        </div>

        <div className="di-field">
          <label className="di-label">
            Project Type<span className="di-required">*</span>
          </label>
          <div className="di-pill-group">
            {PROJECT_TYPES.map((t) => {
              const selected = form.projectType === t
              return (
                <button
                  key={t}
                  type="button"
                  aria-pressed={selected}
                  className={`di-pill${selected ? ' di-pill--selected' : ''}`}
                  onClick={() => update('projectType', t)}
                >
                  {t}
                </button>
              )
            })}
          </div>
          {attempted && !form.projectType && (
            <span className="di-field-error">Select a project type</span>
          )}
        </div>

        <div className="di-field">
          <label className="di-label">
            Analysis Period<span className="di-required">*</span>
          </label>
          <div className="di-pill-group">
            {PERIODS.map((p) => {
              const selected = form.analysisPeriods.includes(p)
              return (
                <button
                  key={p}
                  type="button"
                  aria-pressed={selected}
                  className={`di-pill${selected ? ' di-pill--selected' : ''}`}
                  onClick={() => togglePeriod(p)}
                >
                  {p} peak
                </button>
              )
            })}
            {form.analysisPeriods.length === 2 && (
              <span className="di-help" style={{ alignSelf: 'center', marginTop: 0 }}>
                AM + PM
              </span>
            )}
          </div>
          {attempted && form.analysisPeriods.length === 0 && (
            <span className="di-field-error">Select at least one analysis period</span>
          )}
        </div>

        <div className="di-field">
          <label className="di-label">Appearance</label>
          <button
            type="button"
            className="di-appearance-trigger"
            onClick={() => setThemeOpen(true)}
          >
            <span
              className="di-theme-card__swatch di-theme-card__swatch--sm"
              aria-hidden="true"
              style={{ background: activeTheme.swatch.bg }}
            >
              <span
                className="di-theme-card__surface"
                style={{ background: activeTheme.swatch.surface }}
              />
              <span
                className="di-theme-card__accent"
                style={{ background: activeTheme.swatch.accent }}
              />
            </span>
            <span className="di-appearance-trigger__label">{activeTheme.label}</span>
            <span className="di-appearance-trigger__action">Change</span>
          </button>
        </div>

        <div className="di-actions di-actions--validated">
          {attempted && !isValid && (
            <div className="di-form-error" role="alert">
              Fill in the required field{missing.length === 1 ? '' : 's'} to continue:{' '}
              {missing.join(', ')}.
            </div>
          )}
          <button type="submit" className="di-btn-primary">
            Save and continue →
          </button>
        </div>
      </div>

      <ThemePickerModal
        open={themeOpen}
        value={theme}
        onSelect={chooseTheme}
        onClose={() => setThemeOpen(false)}
      />
    </form>
  )
}
