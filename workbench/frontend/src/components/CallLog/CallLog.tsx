import { useEffect, useState } from 'react'

interface CallRow {
  id: number
  timestamp: string
  project: string | null
  model: string | null
  task: string | null
  total_tokens: number | null
  cost: number | null
  latency_s: number | null
  finish_reason: string | null
  error_type: string | null
  trace_id: string | null
  error: string | null
}

function fmtTime(ts: string) {
  if (!ts) return ''
  return ts.slice(0, 19).replace('T', ' ')
}

function fmtCost(v: number | null) {
  if (v == null) return ''
  return `$${v.toFixed(4)}`
}

export default function CallLog() {
  const [calls, setCalls] = useState<CallRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [projectFilter, setProjectFilter] = useState('')
  const [errorsOnly, setErrorsOnly] = useState(false)
  const [selected, setSelected] = useState<CallRow | null>(null)

  useEffect(() => {
    setLoading(true)
    const params = new URLSearchParams({ limit: '200' })
    if (errorsOnly) params.set('has_error', 'true')
    fetch(`/api/calls/recent?${params}`)
      .then(r => r.json())
      .then(d => { setCalls(d); setError(null) })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false))
  }, [errorsOnly])

  const visible = calls.filter(c => {
    if (!projectFilter) return true
    return (c.project || '').toLowerCase().includes(projectFilter.toLowerCase())
  })

  return (
    <div style={{ position: 'relative' }}>
      <div className="filter-bar">
        <input
          type="text"
          placeholder="Filter by project..."
          value={projectFilter}
          onChange={e => setProjectFilter(e.target.value)}
        />
        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', cursor: 'pointer' }}>
          <input
            type="checkbox"
            style={{ width: 'auto', padding: 0 }}
            checked={errorsOnly}
            onChange={e => setErrorsOnly(e.target.checked)}
          />
          Errors only
        </label>
        <span style={{ color: 'var(--muted)', fontSize: '12px' }}>
          {loading ? 'Loading...' : `${visible.length} rows`}
        </span>
      </div>

      {error && <div style={{ color: 'var(--error)', marginBottom: '12px' }}>Error: {error}</div>}

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Project</th>
              <th>Model</th>
              <th>Task</th>
              <th style={{ textAlign: 'right' }}>Tokens</th>
              <th style={{ textAlign: 'right' }}>Cost</th>
              <th style={{ textAlign: 'right' }}>Latency</th>
              <th style={{ textAlign: 'center' }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {visible.map(c => (
              <tr
                key={c.id}
                className="clickable-row"
                onClick={() => setSelected(c)}
                style={{ background: selected?.id === c.id ? 'var(--surface2)' : undefined }}
              >
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', whiteSpace: 'nowrap' }}>
                  {fmtTime(c.timestamp)}
                </td>
                <td style={{ maxWidth: '140px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '12px' }}>
                  {c.project || <span style={{ color: 'var(--muted)' }}>—</span>}
                </td>
                <td style={{ maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '12px', fontFamily: 'var(--font-mono)' }}>
                  {c.model || <span style={{ color: 'var(--muted)' }}>—</span>}
                </td>
                <td style={{ maxWidth: '160px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '12px' }}>
                  {c.task || <span style={{ color: 'var(--muted)' }}>—</span>}
                </td>
                <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontSize: '12px' }}>
                  {c.total_tokens?.toLocaleString() ?? '—'}
                </td>
                <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontSize: '12px' }}>
                  {fmtCost(c.cost)}
                </td>
                <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontSize: '12px' }}>
                  {c.latency_s != null ? `${c.latency_s}s` : '—'}
                </td>
                <td style={{ textAlign: 'center' }}>
                  {c.error ? (
                    <span className="status-err" title={c.error_type || c.error}>✗</span>
                  ) : (
                    <span className="status-ok">✓</span>
                  )}
                </td>
              </tr>
            ))}
            {!loading && visible.length === 0 && (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', color: 'var(--muted)', padding: '20px' }}>
                  No calls match the current filters
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Detail drawer */}
      {selected && (
        <div className="detail-drawer">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h2>Call #{selected.id}</h2>
            <button onClick={() => setSelected(null)}>✕</button>
          </div>
          {[
            ['Timestamp', selected.timestamp],
            ['Project', selected.project],
            ['Model', selected.model],
            ['Task', selected.task],
            ['Trace ID', selected.trace_id],
            ['Total Tokens', selected.total_tokens?.toLocaleString()],
            ['Cost', fmtCost(selected.cost)],
            ['Latency', selected.latency_s != null ? `${selected.latency_s}s` : null],
            ['Finish Reason', selected.finish_reason],
            ['Error Type', selected.error_type],
            ['Error', selected.error],
          ].map(([key, val]) => val != null && (
            <div className="detail-row" key={String(key)}>
              <div className="detail-key">{key}</div>
              <div className="detail-val">{String(val)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
