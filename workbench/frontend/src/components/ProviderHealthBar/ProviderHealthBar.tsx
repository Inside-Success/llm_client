/**
 * ProviderHealthBar — embeddable widget showing LLM provider cooldown status.
 *
 * Fetches from the llm_client observability workbench at the provided baseUrl.
 * Copy this directory into your project's components folder.
 *
 * Usage:
 *   <ProviderHealthBar baseUrl="http://localhost:5203" />
 */
import { useEffect, useState, useCallback } from 'react'
import './ProviderHealthBar.css'

interface ProviderStatus {
  provider: string
  cooldown_remaining_s: number
  quota_exhausted: boolean
  source: string | null
}

type DotState = 'ok' | 'cooling' | 'exhausted'

function dotState(p: ProviderStatus): DotState {
  if (p.quota_exhausted) return 'exhausted'
  if (p.cooldown_remaining_s > 0) return 'cooling'
  return 'ok'
}

const STATE_LABEL: Record<DotState, string> = {
  ok: 'Available',
  cooling: 'Cooling',
  exhausted: 'Quota exhausted',
}

interface Props {
  /** Base URL of the llm_client workbench backend, e.g. "http://localhost:5203" */
  baseUrl: string
  /** Poll interval in ms (default 10000) */
  pollMs?: number
  /** Show label text next to dots (default true) */
  showLabels?: boolean
}

export default function ProviderHealthBar({
  baseUrl,
  pollMs = 10_000,
  showLabels = true,
}: Props) {
  const [providers, setProviders] = useState<ProviderStatus[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchHealth = useCallback(async () => {
    try {
      const res = await fetch(`${baseUrl}/api/provider-health`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: ProviderStatus[] = await res.json()
      setProviders(data)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [baseUrl])

  useEffect(() => {
    fetchHealth()
    const id = setInterval(fetchHealth, pollMs)
    return () => clearInterval(id)
  }, [fetchHealth, pollMs])

  if (loading) {
    return (
      <div className="phb phb--loading">
        <span className="phb__label">Providers</span>
        <span className="phb__skeleton" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="phb phb--error">
        <span className="phb__label">Providers</span>
        <span className="phb__error">{error}</span>
      </div>
    )
  }

  return (
    <div className="phb">
      {showLabels && <span className="phb__label">Providers</span>}
      <div className="phb__dots">
        {providers.map(p => {
          const state = dotState(p)
          const title = `${p.provider}: ${STATE_LABEL[state]}${
            p.cooldown_remaining_s > 0 ? ` (${Math.ceil(p.cooldown_remaining_s)}s)` : ''
          }`
          return (
            <div key={p.provider} className={`phb__dot-wrap`} title={title}>
              <div className={`phb__dot phb__dot--${state}`} />
              {showLabels && (
                <span className="phb__dot-name">{p.provider}</span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
