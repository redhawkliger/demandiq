// Shared /forecast/run payload assembly + POST. Used by F3 (initial run) and F4
// (scenario re-run), so the request shape is defined in exactly one place — the
// scenario factor rides the SAME payload the baseline run sends, plus one field.
import { getIntersections, getLinks, resolveLinkMode } from '../store/projectStore'

const DIRS = ['NB', 'SB', 'EB', 'WB']

export function buildRunPayload({ snap, settings, scenarioFactor = null }) {
  const fc = snap.forecasting ?? {}
  const matches = fc.matches ?? []
  const intersections = getIntersections()
  const byId = new Map(intersections.map((it) => [it.id, it.num]))

  // Balanced existing TMCs → {AM:{num:{mv}}, PM:{...}} (the count C).
  const balanced_tmcs = { AM: {}, PM: {} }
  for (const it of intersections) {
    for (const p of ['AM', 'PM']) {
      const b = it.balanced?.[p]
      if (b && Object.keys(b).length) balanced_tmcs[p][it.num] = b
    }
  }

  // Corridor links by num, with their effective (S5) modes.
  const links = getLinks()
    .map((l) => ({
      fromNum: byId.get(l.fromId),
      toNum: byId.get(l.toId),
      direction: l.direction,
      mode: resolveLinkMode(l.fromId, l.toId),
    }))
    .filter((l) => l.fromNum != null && l.toNum != null)

  const coords = {}
  for (const it of intersections) coords[it.num] = { lat: it.lat, lng: it.lng }

  // Manual targets for unmatched legs the engineer entered by hand.
  const manual_targets = {}
  for (const m of matches) {
    for (const d of DIRS) {
      const leg = m.legs?.[d]
      if (leg?.status === 'unmatched' && leg.decision === 'manual' && leg.manual) {
        manual_targets[m.intersection_num] ??= {}
        manual_targets[m.intersection_num][d] = {
          inbound: Number(leg.manual.inbound),
          outbound: Number(leg.manual.outbound),
        }
      }
    }
  }

  const periods = snap.project?.analysisPeriods?.length
    ? snap.project.analysisPeriods
    : ['AM', 'PM']

  const kRaw = settings?.peakHourFactor
  const kValid = kRaw !== '' && kRaw != null && Number(kRaw) > 0
  const refineMethod = kValid ? (settings?.refineMethod || 'ratio') : 'ratio'

  const payload = {
    layers: fc.layers,
    matches,
    balanced_tmcs,
    links,
    coords,
    periods,
    method: settings?.method ?? 'larger',
    refine_method: refineMethod,
    peak_hour_factor: kValid ? Number(kRaw) : null,
    manual_targets,
  }
  // Scenario demand-reduction factor — the engineer's mitigation ASSUMPTION,
  // applied to the forecast volumes. Only added when set; the tool never
  // generates or suggests one.
  if (scenarioFactor != null) payload.scenario_reduction_factor = scenarioFactor
  return payload
}

export async function runForecast({ snap, settings, scenarioFactor = null }) {
  const res = await fetch('/api/forecast/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(buildRunPayload({ snap, settings, scenarioFactor })),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const j = await res.json(); if (j?.detail) detail = j.detail } catch { /* non-JSON */ }
    throw new Error(detail)
  }
  return res.json()
}
