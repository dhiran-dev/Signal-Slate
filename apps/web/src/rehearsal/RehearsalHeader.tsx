import React from 'react'
import { SlateIcon, MicIcon } from './icons'
import type { WorkflowStep } from './useWorkflow'

export interface RehearsalHeaderProps {
  step: WorkflowStep
  onSelectTab: (tab: 'check' | 'report') => void
  sceneName?: string
}

export const RehearsalHeader: React.FC<RehearsalHeaderProps> = ({
  step,
  onSelectTab,
  sceneName = 'Alleyway dialogue'
}) => {
  const isReportTab = step === 'report'
  const isBlueTheme = step === 'change'

  return (
    <header className="rehearsal-header">
      <div className="rehearsal-header-inner">
        {/* Left: Brand */}
        <a href="/" className="rehearsal-brand" aria-label="Signal Slate home">
          <SlateIcon size={26} />
          <span>Signal Slate</span>
        </a>

        {/* Center: Sound check vs Report Navigation Tabs */}
        <nav className="rehearsal-nav-tabs" aria-label="Rehearsal navigation">
          <button
            type="button"
            className={`rehearsal-nav-tab ${!isReportTab ? 'active' : ''} ${isBlueTheme ? 'blue-accent' : ''}`}
            onClick={() => onSelectTab('check')}
            aria-current={!isReportTab ? 'page' : undefined}
          >
            Sound check
          </button>
          <button
            type="button"
            className={`rehearsal-nav-tab ${isReportTab ? 'active' : ''}`}
            onClick={() => onSelectTab('report')}
            aria-current={isReportTab ? 'page' : undefined}
          >
            Report
          </button>
        </nav>

        {/* Right: Scene indicator */}
        <div className="rehearsal-scene-badge" aria-label={`Current scene: ${sceneName}`}>
          <MicIcon size={16} className="text-gray-500 mr-1.5" />
          <span className="scene-prefix text-gray-500 mr-1">Current scene:</span>
          <span className="scene-name font-medium">{sceneName}</span>
        </div>
      </div>
    </header>
  )
}
