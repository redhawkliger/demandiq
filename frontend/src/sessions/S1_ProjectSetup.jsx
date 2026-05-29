import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getProjectMeta, setProjectMeta } from '../store/projectStore'
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

function validate(form) {
  if (!isFilled(form.name)) return false
  if (!isFilled(form.client)) return false
  if (!isFilled(form.analyst)) return false
  if (!isFilled(form.date)) return false
  if (!isFilled(form.scenario)) return false
  if (!form.projectType) return false
  if (!Array.isArray(form.analysisPeriods) || form.analysisPeriods.length === 0) return false
  return true
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

  const update = (key, value) => setForm((f) => ({ ...f, [key]: value }))

  const togglePeriod = (p) =>
    setForm((f) => {
      const set = new Set(f.analysisPeriods)
      if (set.has(p)) set.delete(p)
      else set.add(p)
      return { ...f, analysisPeriods: PERIODS.filter((x) => set.has(x)) }
    })

  const isValid = validate(form)

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!isValid) return
    if (saveTimer.current) clearTimeout(saveTimer.current)
    setProjectMeta(form) // flush, don't wait for the debounce window
    navigate('/map')
  }

  // Small render helper — keeps each field one line of JSX. Not exported.
  const textField = (label, key, required, opts = {}) => (
    <div className="di-field">
      <label className="di-label" htmlFor={`f-${key}`}>
        {label}
        {required && <span className="di-required">*</span>}
      </label>
      <input
        id={`f-${key}`}
        className="di-input"
        type={opts.type || 'text'}
        value={form[key] ?? ''}
        placeholder={opts.placeholder}
        autoComplete="off"
        onChange={(e) => update(key, e.target.value)}
      />
    </div>
  )

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
        </div>

        <div className="di-actions">
          <button type="submit" className="di-btn-primary" disabled={!isValid}>
            Save and continue →
          </button>
        </div>
      </div>
    </form>
  )
}
