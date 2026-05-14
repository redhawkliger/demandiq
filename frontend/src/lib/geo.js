// Bearing from p1 → p2 in degrees clockwise from north (0..360).
export function bearing(p1, p2) {
  const φ1 = (p1.lat * Math.PI) / 180
  const φ2 = (p2.lat * Math.PI) / 180
  const Δλ = ((p2.lng - p1.lng) * Math.PI) / 180
  const y = Math.sin(Δλ) * Math.cos(φ2)
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ)
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360
}

// Distance from a bearing to its nearest of 8 cardinals (every 45°). [0, 22.5].
export function deviationFromCardinal(b) {
  const nearest = Math.round(b / 45) * 45
  const diff = Math.abs(b - nearest)
  return diff > 22.5 ? 45 - diff : diff
}

// 'EW' if longitude spread > latitude spread, else 'NS'.
export function detectCorridorDir(points) {
  if (points.length < 2) return 'EW'
  let minLat = Infinity, maxLat = -Infinity, minLng = Infinity, maxLng = -Infinity
  for (const p of points) {
    if (p.lat < minLat) minLat = p.lat
    if (p.lat > maxLat) maxLat = p.lat
    if (p.lng < minLng) minLng = p.lng
    if (p.lng > maxLng) maxLng = p.lng
  }
  return maxLng - minLng > maxLat - minLat ? 'EW' : 'NS'
}

// EW → ascending lng (W→E). NS → ascending lat (S→N).
export function sortAlongCorridor(points, dir) {
  return [...points].sort((a, b) => (dir === 'EW' ? a.lng - b.lng : a.lat - b.lat))
}
