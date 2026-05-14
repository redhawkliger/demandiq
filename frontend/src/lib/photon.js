// Photon (Komoot) geocoding. CORS-friendly, no API key required.

const FORWARD = 'https://photon.komoot.io/api/'
const REVERSE = 'https://photon.komoot.io/reverse'
const TIMEOUT_MS = 5000

function fetchWithTimeout(url, ms = TIMEOUT_MS) {
  const controller = new AbortController()
  const t = setTimeout(() => controller.abort(), ms)
  return fetch(url, { signal: controller.signal }).finally(() => clearTimeout(t))
}

export async function searchPhoton(query, limit = 5) {
  const url = `${FORWARD}?q=${encodeURIComponent(query)}&limit=${limit}&lang=en`
  const r = await fetchWithTimeout(url)
  if (!r.ok) throw new Error(`Photon ${r.status}`)
  const data = await r.json()
  return (data.features || []).map((f) => ({
    label: photonLabel(f.properties || {}),
    lat: f.geometry.coordinates[1],
    lng: f.geometry.coordinates[0],
  }))
}

export async function reverseGeocode(lat, lng) {
  const url = `${REVERSE}?lat=${lat}&lon=${lng}&lang=en`
  const r = await fetchWithTimeout(url)
  if (!r.ok) throw new Error(`Photon ${r.status}`)
  const data = await r.json()
  const f = (data.features || [])[0]
  if (!f) return null
  const p = f.properties || {}
  return p.street || p.name || null
}

function photonLabel(p) {
  const head = p.name || p.street
  const place = p.city || p.town || p.village || p.county
  return [head, place, p.state, p.country].filter(Boolean).join(', ')
}
