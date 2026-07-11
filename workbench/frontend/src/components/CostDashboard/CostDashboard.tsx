import { useEffect, useState } from 'react'

interface DailyRow {
  day: string
  cost: number
  calls: number
}

interface ProjectRow {
  project: string
  calls: number
  cost: number
  avg_latency_s: number
}

interface ModelRow {
  model: string
  calls: number
  cost: number
  avg_latency_s: number
}

function fmtCost(v: number) {
  return `$${v.toFixed(2)}`
}

function fmtDate(day: string) {
  // "2026-06-22" → "Jun 22"
  const d = new Date(day + 'T00:00:00')
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export default function CostDashboard() {
  const [daily, setDaily] = useState<DailyRow[]>([])
  const [projects, setProjects] = useState<ProjectRow[]>([])
  const [models, setModels] = useState<ModelRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      fetch('/api/cost/daily?days=30').then(r => r.json()),
      fetch('/api/cost/by-project?days=7').then(r => r.json()),
      fetch('/api/cost/by-model?days=7').then(r => r.json()),
    ])
      .then(([d, p, m]) => {
        setDaily(d)
        setProjects(p)
        setModels(m)
        setError(null)
      })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div style={{ color: 'var(--muted)', padding: '20px' }}>Loading...</div>
  if (error) return <div style={{ color: 'var(--error)', padding: '20px' }}>Error: {error}</div>

  // 7-day spend headline
  const cutoff = new Date()
  cutoff.setDate(cutoff.getDate() - 7)
  const spend7d = daily
    .filter(d => new Date(d.day + 'T00:00:00') >= cutoff)
    .reduce((sum, d) => sum + d.cost, 0)

  const maxCost = Math.max(...daily.map(d => d.cost), 0.01)

  return (
    <div>
      {/* Headline */}
      <div className="card" style={{ marginBottom: 'var(--space-4)' }}>
        <div className="stat-label">7-day total spend</div>
        <div className="stat-headline">{fmtCost(spend7d)}</div>
      </div>

      {/* Daily bar chart */}
      <div className="card">
        <div className="card-title">Daily cost — last 30 days</div>
        <div className="bar-chart-wrap">
          <div className="bar-chart">
            {daily.map(d => {
              const height = Math.max(2, (d.cost / maxCost) * 200)
              return (
                <div className="bar-col" key={d.day}>
                  <div
                    className="bar"
                    data-bar="true"
                    style={{ height: `${height}px` }}
                    title={`${fmtDate(d.day)}: ${fmtCost(d.cost)} (${d.calls.toLocaleString()} calls)`}
                  />
                  <div className="bar-label">{fmtDate(d.day)}</div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* Top projects + models */}
      <div className="two-col">
        <div className="card">
          <div className="card-title">Top projects — last 7 days</div>
          <table>
            <thead>
              <tr>
                <th>Project</th>
                <th style={{ textAlign: 'right' }}>Calls</th>
                <th style={{ textAlign: 'right' }}>Cost</th>
              </tr>
            </thead>
            <tbody>
              {projects.map(p => (
                <tr key={p.project}>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.project}</td>
                  <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{p.calls.toLocaleString()}</td>
                  <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmtCost(p.cost)}</td>
                </tr>
              ))}
              {projects.length === 0 && (
                <tr><td colSpan={3} style={{ color: 'var(--muted)', textAlign: 'center' }}>No data</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="card">
          <div className="card-title">Top models — last 7 days</div>
          <table>
            <thead>
              <tr>
                <th>Model</th>
                <th style={{ textAlign: 'right' }}>Calls</th>
                <th style={{ textAlign: 'right' }}>Cost</th>
              </tr>
            </thead>
            <tbody>
              {models.map(m => (
                <tr key={m.model}>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.model}</td>
                  <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{m.calls.toLocaleString()}</td>
                  <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmtCost(m.cost)}</td>
                </tr>
              ))}
              {models.length === 0 && (
                <tr><td colSpan={3} style={{ color: 'var(--muted)', textAlign: 'center' }}>No data</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
