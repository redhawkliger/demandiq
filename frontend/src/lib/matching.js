// Match agent-extracted intersection names to project intersection names.
// Token overlap (Jaccard-style, normalized by the smaller set), with common
// street suffixes and connectors stripped. Threshold tuned to favour false
// negatives (engineer manually maps via the unmatched panel) over false
// positives (silently apply the wrong volumes).

const STOP_WORDS = new Set([
  'street', 'st', 'avenue', 'ave', 'road', 'rd',
  'blvd', 'boulevard', 'drive', 'dr', 'hwy', 'highway',
  'ln', 'lane', 'ct', 'court', 'pl', 'place', 'way',
  'pkwy', 'parkway', 'cir', 'circle', 'ter', 'terrace',
  'and', 'at', 'the', 'of', 'a', 'an', 'to',
])

const THRESHOLD = 0.7

function tokenize(name) {
  return new Set(
    String(name)
      .toLowerCase()
      .replace(/[&,\-/.()]/g, ' ')
      .split(/\s+/)
      .filter((t) => t.length > 0 && !STOP_WORDS.has(t))
  )
}

function score(a, b) {
  const ta = tokenize(a)
  const tb = tokenize(b)
  if (ta.size < 2 || tb.size < 2) return 0
  let overlap = 0
  for (const t of ta) if (tb.has(t)) overlap++
  return overlap / Math.min(ta.size, tb.size)
}

// Returns { matches: { [projectIntersectionId]: agentIndex }, unmatched: [agent...] }.
// If two agents both want the same project intersection, the higher-score one
// wins; the loser goes to unmatched.
export function matchAgentToProject(agentInts, projectInts) {
  const claimed = new Map() // projectId → { agentIdx, score }
  const losers = []

  agentInts.forEach((agent, agentIdx) => {
    let bestId = null
    let bestScore = 0
    for (const proj of projectInts) {
      const s = score(agent.name || '', proj.name || '')
      if (s > bestScore && s >= THRESHOLD) {
        bestScore = s
        bestId = proj.id
      }
    }
    if (bestId === null) {
      losers.push(agentIdx)
      return
    }
    const prev = claimed.get(bestId)
    if (!prev || prev.score < bestScore) {
      if (prev) losers.push(prev.agentIdx)
      claimed.set(bestId, { agentIdx, score: bestScore })
    } else {
      losers.push(agentIdx)
    }
  })

  const matches = {}
  for (const [pid, { agentIdx }] of claimed) matches[pid] = agentIdx
  return { matches, unmatched: losers.map((i) => agentInts[i]) }
}
