import React, { useState } from 'react'
import type { Session } from './types'
import { microphoneEvidence, type SoundInterval } from './evidence'
import {
  MicIcon,
  BoomMicIcon,
  PlayIcon,
  PauseIcon,
  ArrowLeftIcon,
  FileReportIcon,
  ExternalLinkIcon,
  VolumeIcon,
  MuteIcon
} from './icons'
import { WaveformTrack } from './WaveformTrack'
import { PCM_PEAKS_240 } from './waveformPeaks'

export interface SoundIssuesStepProps {
  session: Session | null
  busy: string
  onFindFix: () => void
  onBackToScene: () => void
  onPlaySection: (startS?: number, micId?: string) => void
  onPauseSection: () => void
  isPlaying: boolean
  currentTime: number
  isMuted: boolean
  onToggleMute: () => void
  onSeek: (time: number) => void
  currentPhrase?: string
  condition?: string
  audioError?: string
}

export const SoundIssuesStep: React.FC<SoundIssuesStepProps> = ({
  session,
  busy,
  onFindFix,
  onBackToScene,
  onPlaySection,
  onPauseSection,
  isPlaying,
  currentTime,
  isMuted,
  onToggleMute,
  onSeek,
  currentPhrase,
  condition,
  audioError
}) => {
  const isNoRisk = session?.state === 'NO_RISK'
  const isLive = session?.mode === 'live'
  const run = session?.baseline ?? null

  const micIds = session?.shot_context?.mic_ids || ['mic_1', 'mic_2', 'mic_3', 'mic_4']
  const performerNames = session?.shot_context?.performer_names || {
    mic_1: 'Elena',
    mic_2: 'Marcus',
    mic_3: 'Security Guard',
    mic_4: 'Overhead Boom'
  }

  // Derive evidence for every microphone
  const micRows = micIds.map((id) => {
    const evidence = microphoneEvidence(run, id, 12000)
    const name = performerNames[id] || id
    const isBoom = id.includes('boom') || id === 'mic_4' || name.toLowerCase().includes('boom')
    const channel = session?.baseline_config?.channel_assignments?.[id]
    return { id, name, isBoom, channel, evidence }
  })

  // Find microphones with issues
  const problemMics = micRows.filter((m) => m.evidence.hasIssue || !m.evidence.complete)
  const issueCount = isNoRisk ? 0 : problemMics.length

  // Select primary affected mic (first affected mic, or default to first mic)
  const [selectedMicId, setSelectedMicId] = useState<string>(
    problemMics[0]?.id || micRows[0]?.id || 'mic_1'
  )
  const primaryMic = micRows.find((m) => m.id === selectedMicId) || micRows[0]

  // Primary mic interval
  const primaryInterval: SoundInterval | undefined = primaryMic.evidence.intervals[0]
  const startS = primaryInterval ? primaryInterval.startS : 4.9
  const endS = primaryInterval ? primaryInterval.endS : 6.8

  // Check if critical quote overlaps this marked segment
  const quote = session?.shot_context?.critical_dialogue_text || 'do not cut the feed'
  const overlapsQuote = startS < 6.8 && endS > 4.9

  // Actual evidence link (only if baseline run exists)
  const evidenceUrl =
    session?.id && session.baseline?.run_id
      ? `/api/sessions/${encodeURIComponent(session.id)}/evidence/${encodeURIComponent(
          session.baseline.run_id
        )}`
      : null

  return (
    <div className="sound-issues-step-view">
      {/* Page Title & Issue Badge */}
      <div className="step-heading-group flex items-baseline gap-3 flex-wrap">
        <h1 className="step-main-title">Sound issues</h1>
        <span
          className={`step-header-badge ${
            issueCount === 0 ? 'badge-no-issues' : 'badge-issue-found'
          }`}
        >
          {issueCount === 0
            ? 'No sound issues found'
            : issueCount === 1
            ? '1 issue found'
            : `${issueCount} issues found`}
        </span>
        <p className="step-subtitle w-full">
          {issueCount === 0
            ? 'All receiver checks passed. No correction is required.'
            : 'Play the marked section, then click Find a fix.'}
        </p>
      </div>

      {/* 2-Column Grid */}
      <div className="step-two-columns">
        {/* Left Column */}
        <div className="sound-issues-left-col">
          {/* Card 1: Affected section */}
          <div className="step-main-card">
            <h2 className="card-section-title">
              {issueCount > 0 ? 'Affected section' : 'Audio timeline'}
            </h2>

            {/* Range Indicator above waveform */}
            {primaryInterval && (
              <div className="affected-range-indicator-wrap" aria-hidden="true">
                <div
                  className="affected-range-tag"
                  style={{
                    left: `${(startS / 12) * 100}%`,
                    width: `${Math.max(10, ((endS - startS) / 12) * 100)}%`
                  }}
                >
                  <span className="range-dot range-dot-left" />
                  <span className="range-label-text">
                    {startS.toFixed(1)} – {endS.toFixed(1)}s
                  </span>
                  <span className="range-dot range-dot-right" />
                </div>
              </div>
            )}

            {/* Waveform with Hatched Region */}
            <div className="affected-waveform-wrapper">
              <WaveformTrack
                peaks={PCM_PEAKS_240}
                height={58}
                tint="default"
                intervals={primaryMic.evidence.intervals}
                showRuler={true}
                playheadTime={currentTime}
                onSeek={onSeek}
                interactive={true}
                ariaLabel={`${primaryMic.name} affected section waveform`}
              />
            </div>

            {/* Transcript quote bracket label if overlaps */}
            {overlapsQuote && issueCount > 0 && (
              <div className="affected-quote-bracket" aria-label={`Missing phrase: ${quote}`}>
                <span className="bracket-curly">“{quote}”</span>
              </div>
            )}

            {/* Transport Control Row */}
            <div className="scene-transport-row mt-4 flex items-center justify-between flex-wrap gap-3">
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={isPlaying ? onPauseSection : () => onPlaySection(startS, primaryMic.id)}
                  className="scene-play-btn"
                  aria-label={isPlaying ? 'Pause affected section' : 'Play affected section'}
                >
                  {isPlaying ? <PauseIcon size={16} /> : <PlayIcon size={16} />}
                  <span>{isPlaying ? 'Pause affected section' : 'Play affected section'}</span>
                </button>

                <button
                  type="button"
                  onClick={onToggleMute}
                  className="scene-mute-btn flex items-center gap-1.5"
                  aria-label={isMuted ? 'Unmute sound' : 'Mute sound'}
                >
                  {isMuted ? <MuteIcon size={16} /> : <VolumeIcon size={16} />}
                  <span>{isMuted ? 'Muted' : 'Sound on'}</span>
                </button>
              </div>

              <span className="scene-timecode-display">
                {currentTime > 0 ? currentTime.toFixed(1) : startS.toFixed(1)}s / 12s
              </span>
            </div>

            {audioError && (
              <div role="alert" className="audio-error-alert p-2 my-2 bg-red-50 border border-red-200 rounded text-xs text-red-800">
                <strong>Audio playback issue:</strong> <span>{audioError}</span>
              </div>
            )}

            {/* Visible Caption region */}
            {currentPhrase && (
              <div
                className="visible-caption-box mt-3 p-2 bg-gray-50 border border-gray-200 rounded text-xs text-gray-700 flex items-center justify-between"
                aria-label="Synchronized caption"
                aria-live="polite"
              >
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-gray-500 uppercase">Dialogue:</span>
                  <span>“{currentPhrase}”</span>
                  {condition === 'dropout' && <span className="text-red-700 font-semibold">[Simulated silence: dropout]</span>}
                  {condition === 'clipped' && <span className="text-amber-700 font-semibold">[Simulated clipping]</span>}
                  {condition === 'unknown' && <span className="text-gray-500 font-semibold">[Muted: incomplete data]</span>}
                  {(condition === 'received' || !condition) && <span className="text-gray-600 font-medium">[Received]</span>}
                </div>
              </div>
            )}
          </div>

          {/* Card 2: Microphone Status Table */}
          <div className="step-main-card mt-5">
            <h2 className="card-section-title mb-3">Microphone status</h2>

            <div className="table-responsive-container">
              <table className="mic-status-table" aria-label="Microphone issue status">
                <thead>
                  <tr>
                    <th scope="col">Microphone</th>
                    <th scope="col">Status</th>
                    <th scope="col">Details</th>
                  </tr>
                </thead>
                <tbody>
                  {micRows.map((mic) => {
                    const hasIssue = mic.evidence.hasIssue || !mic.evidence.complete
                    const isDropout = mic.evidence.dropoutMs > 0
                    const isClipped = mic.evidence.clippingMs > 0
                    const isUnknown = !mic.evidence.complete

                    let statusText = 'No issue'
                    let detailsText = '—'
                    if (isDropout) {
                      statusText = `${(mic.evidence.dropoutMs / 1000).toFixed(1)}s missing`
                      const int = mic.evidence.intervals.find((i) => i.kind === 'dropout')
                      detailsText = int ? `${int.startS.toFixed(1)} – ${int.endS.toFixed(1)}s` : `${mic.evidence.dropoutMs}ms`
                    } else if (isClipped) {
                      statusText = `${(mic.evidence.clippingMs / 1000).toFixed(1)}s clipping`
                      const int = mic.evidence.intervals.find((i) => i.kind === 'clipped')
                      detailsText = int ? `${int.startS.toFixed(1)} – ${int.endS.toFixed(1)}s` : `${mic.evidence.clippingMs}ms`
                    } else if (isUnknown) {
                      statusText = 'Incomplete data'
                      detailsText = `${mic.evidence.unknownMs}ms unknown`
                    }

                    return (
                      <tr
                        key={mic.id}
                        className={`${hasIssue ? 'row-affected-hazard' : ''} ${
                          selectedMicId === mic.id ? 'row-selected-mic cursor-pointer' : 'cursor-pointer'
                        }`}
                        onClick={() => setSelectedMicId(mic.id)}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault()
                            setSelectedMicId(mic.id)
                          }
                        }}
                      >
                        <td className="font-medium text-gray-900">
                          <div className="inline-flex items-center gap-2">
                            {mic.isBoom ? (
                              <BoomMicIcon size={16} className="text-gray-700" />
                            ) : (
                              <MicIcon size={16} className="text-gray-700" />
                            )}
                            <span>
                              {mic.name}
                              {mic.channel !== undefined ? ` · Channel ${mic.channel}` : ''}
                            </span>
                          </div>
                        </td>
                        <td>
                          {hasIssue ? (
                            <span className="text-hazard-bold">{statusText}</span>
                          ) : (
                            <span className="text-gray-600">{statusText}</span>
                          )}
                        </td>
                        <td>
                          {hasIssue ? (
                            <span className="text-hazard-bold">{detailsText}</span>
                          ) : (
                            <span className="text-gray-400">{detailsText}</span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Right Sidebar */}
        <aside className="step-sidebar-card">
          <div className="sidebar-section">
            <h2 className="sidebar-title">Issue details</h2>
            <p className="sidebar-text">
              {issueCount === 0
                ? 'All active microphones reported normal levels across this sample.'
                : primaryMic.evidence.dropoutMs > 0
                ? `${primaryMic.name}’s line loses sound from ${startS.toFixed(1)} to ${endS.toFixed(
                    1
                  )} seconds.`
                : primaryMic.evidence.clippingMs > 0
                ? `${primaryMic.name}’s signal clips from ${startS.toFixed(1)} to ${endS.toFixed(
                    1
                  )} seconds.`
                : !primaryMic.evidence.complete
                ? `${primaryMic.name}’s microphone reported incomplete readings.`
                : 'Review observed readings.'}
            </p>
          </div>

          <div className="card-divider" />

          <div className="sidebar-section">
            <h2 className="sidebar-title">
              {isLive ? 'Readings from Grafana' : 'Preview readings'}
            </h2>
            <p className="sidebar-text">
              {isLive
                ? 'Grafana stores the microphone measurements and event records. Open the readings to see the evidence behind this issue.'
                : 'These built-in sample readings illustrate the sound issue without calling cloud services.'}
            </p>
            {evidenceUrl ? (
              <a
                href={evidenceUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="view-readings-link"
              >
                <FileReportIcon size={18} />
                <span>View readings</span>
                <ExternalLinkIcon size={14} />
              </a>
            ) : (
              <span className="text-sm text-gray-400 mt-2 block">Readings saved with check</span>
            )}
          </div>

          <div className="card-divider" />

          <div className="sidebar-section">
            <h2 className="sidebar-title">Next step</h2>
            <p className="sidebar-text">
              {issueCount === 0
                ? 'No sound issues found. You can proceed to check the report.'
                : isLive
                ? 'Click Find a fix. Gemini will review these readings and suggest a setting change for you to approve.'
                : 'Click Find a fix to review the sample suggestion.'}
            </p>
          </div>
        </aside>
      </div>

      {/* Bottom Action Bar */}
      <footer className="step-bottom-action-bar">
        <div className="bottom-action-left items-center">
          <button
            type="button"
            onClick={onBackToScene}
            className="btn-back-link"
            disabled={!!busy}
          >
            <ArrowLeftIcon size={16} />
            <span>Back to scene setup</span>
          </button>

          <button
            type="button"
            className="btn-terracotta-primary btn-step-cta ml-4"
            onClick={onFindFix}
            disabled={!!busy}
          >
            {busy ? 'Finding fix…' : issueCount === 0 ? 'View report' : 'Find a fix'}
          </button>

          <span className="bottom-action-pipe-divider">|</span>
          <span className="bottom-action-hint">
            {issueCount === 0
              ? 'No correction needed for this sample.'
              : 'Gemini will suggest a change to test.'}
          </span>
        </div>

        <div className="bottom-action-right">
          <span className="bottom-action-sample-tag">
            Sample scene · Simulated microphone readings
          </span>
        </div>
      </footer>
    </div>
  )
}
