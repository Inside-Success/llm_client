/**
 * CostMeter — embeddable widget that shows 7-day rolling LLM spend.
 *
 * Fetches from the llm_client observability workbench at the provided baseUrl.
 * Copy this directory into your project's components folder.
 *
 * Usage:
 *   <CostMeter baseUrl="http://localhost:5203" />
 */
import { useEffect, useState, useCallback } from 'react'
import './CostMeter.css'

interface DailyRow {
  day: string
  cost: number
  calls: number
}

interface Props {
  /** Base URL of the llm_client workbench backend, e.g. "http://localhost:5203" */
  baseUrl: string
  /** Number of days to display (default 7) */
  days?: number
  /** Poll interval in ms; 0 disables polling (default 60000) */
  pollMs?: number
}

export default function CostMeter({ baseUrl, days = 7, pollMs = 60_000 }: Props) {
  const [rows, setRows] = useState<DailyRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const fetch7Day = useCallback(async () => {
    try {
      const res = await fetch(`${baseUrl}/api/cost/daily?days=${days}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: DailyRow[] = await res.json()
      setRows(data)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [baseUrl, days])

  useEffect(() => {
    fetch7Day()
    if (pollMs <= 0) return
    const id = setInterval(fetch7Day, pollMs)
    return () => clearInterval(id)
  }, [fetch7Day, pollMs])

  const totalCost = rows.reduce((s, r) => s + r.cost, 0)
  const totalCalls = rows.reduce((s, r) => s + r.calls, 0)
  const maxCost = Math.max(...rows.map(r => r.cost), 0.0001)

  if (loading) {
    return (
      <div className="cost-meter cost-meter--loading">
        <div className="cost-meter__label">LLM Spend</div>
        <div className="cost-meter__skeleton" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="cost-meter cost-meter--error">
        <div className="cost-meter__label">LLM Spend</div>
        <div className="cost-meter__error">{error}</div>
      </div>
    )
  }

  return (
    <div className="cost-meter">
      <div className="cost-meter__header">
        <span className="cost-meter__label">{days}d LLM Spend</span>
        <span className="cost-meter__total">${totalCost.toFixed(2)}</span>
      </div>
      <div className="cost-meter__calls">{totalCalls.toLocaleString()} calls</div>

      <div className="cost-meter__bars" aria-label="Daily cost sparkline">
        {rows.map(row => (
          <div key={row.day} className="cost-meter__bar-col" title={`${row.day}: $${row.cost.toFixed(4)}`}>
            <div
              className="cost-meter__bar"
              style={{ height: `${Math.max(2, (row.cost / maxCost) * 48)}px` }}
            />
          </div>
        ))}
        {rows.length === 0 && (
          <div className="cost-meter__empty">No data</div>
        )}
      </div>
    </div>
  )
}
