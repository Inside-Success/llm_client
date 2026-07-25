import { useEffect, useState } from 'react'

interface ProviderRow {
  provider: string
  cooldown_remaining_s: number
  quota_exhausted: boolean
  source: string | null
}

function dotClass(row: ProviderRow) {
  if (row.quota_exhausted) return 'dot dot-red'
  if (row.cooldown_remaining_s > 0) return 'dot dot-yellow'
  return 'dot dot-green'
}

function statusText(row: ProviderRow) {
  if (row.quota_exhausted) return `Daily quota exhausted (${Math.round(row.cooldown_remaining_s / 60)}m remaining)`
  if (row.cooldown_remaining_s > 0) return `Cooling down: ${row.cooldown_remaining_s.toFixed(0)}s remaining`
  return 'Available'
}

export default function ProviderHealth() {
  const [providers, setProviders] = useState<ProviderRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [secondsAgo, setSecondsAgo] = useState(0)

  const fetchProviders = () => {
    fetch('/api/provider-health')
      .then(r => r.json())
      .then(d => {
        setProviders(d)
        setLastUpdated(new Date())
        setSecondsAgo(0)
        setError(null)
      })
      .catch(e => setError(String(e)))
  }

  // Poll every 10s
  useEffect(() => {
    fetchProviders()
    const pollId = setInterval(fetchProviders, 10_000)
    return () => clearInterval(pollId)
  }, [])

  // Tick "X seconds ago" counter every second
  useEffect(() => {
    const tickId = setInterval(() => {
      setSecondsAgo(prev => prev + 1)
    }, 1_000)
    return () => clearInterval(tickId)
  }, [])

  return (
    <div>
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-4)' }}>
          <div className="card-title" style={{ marginBottom: 0 }}>Provider cooldown status</div>
          <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
            {lastUpdated ? `Last updated: ${secondsAgo}s ago` : 'Loading...'}
          </div>
        </div>

        {error && <div style={{ color: 'var(--error)', marginBottom: '12px' }}>Error: {error}</div>}

        <div className="provider-list">
          {providers.map(p => (
            <div className="provider-row" key={p.provider}>
              <div
                className={dotClass(p)}
                data-provider-dot="true"
              />
              <div className="provider-name">{p.provider}</div>
              <div className="provider-status">{statusText(p)}</div>
              {p.source && (
                <div style={{ marginLeft: 'auto', fontSize: '11px', color: 'var(--idle)' }}>
                  source: {p.source}
                </div>
              )}
            </div>
          ))}
          {providers.length === 0 && !error && (
            <div style={{ color: 'var(--muted)', textAlign: 'center', padding: '20px' }}>
              No provider data available
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
