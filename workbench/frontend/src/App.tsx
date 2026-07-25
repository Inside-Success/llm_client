import { useState } from 'react'
import CostDashboard from './components/CostDashboard/CostDashboard'
import CallLog from './components/CallLog/CallLog'
import ProviderHealth from './components/ProviderHealth/ProviderHealth'
import CostMeter from './components/CostMeter/CostMeter'
import ProviderHealthBar from './components/ProviderHealthBar/ProviderHealthBar'

type Tab = 'cost' | 'calls' | 'providers'

const TABS: { id: Tab; label: string }[] = [
  { id: 'cost', label: 'Cost' },
  { id: 'calls', label: 'Call Log' },
  { id: 'providers', label: 'Providers' },
]

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('cost')

  return (
    <div className="workbench-layout">
      <div className="workbench-header">
        <h1>llm_client Observability</h1>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
          <ProviderHealthBar baseUrl="" pollMs={15_000} showLabels={false} />
          <CostMeter baseUrl="" days={7} pollMs={60_000} />
        </div>
      </div>
      <div className="tab-bar">
        {TABS.map(t => (
          <button
            key={t.id}
            className={`tab-btn${activeTab === t.id ? ' active' : ''}`}
            onClick={() => setActiveTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="tab-content">
        {activeTab === 'cost' && <CostDashboard />}
        {activeTab === 'calls' && <CallLog />}
        {activeTab === 'providers' && <ProviderHealth />}
      </div>
    </div>
  )
}
