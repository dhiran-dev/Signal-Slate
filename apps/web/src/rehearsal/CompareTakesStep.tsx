import React, { useState, useEffect } from 'react'
import type { Session } from './types'
import { microphoneEvidence, soundSummary } from './evidence'
import {
  PlayIcon,
  PauseIcon,
  CheckCircleIcon,
  FileReportIcon,
  ExternalLinkIcon,
  ArrowLeftIcon,
  VolumeIcon,
  MuteIcon
} from './icons'
import { WaveformTrack } from './WaveformTrack'
import { PCM_PEAKS_240 } from './waveformPeaks'

export interface CompareTakesStepProps {
  session: Session | null
  busy: string
  onViewReport: () => void
  onBackToChange: () => void
  onPlayTrack: (track: 'before' | 'after') => void
  onPauseTrack: () => void
  activeTrack: 'before' | 'after'
  isPlaying: boolean
  currentTime: number
  isMuted: boolean
  onToggleMute: () => void
  onSeek: (time: number) => void
  onRetry?: () => void
  selectedMicId?: string
  onSelectMic?: (id: string) => void
  currentPhrase?: string
  condition?: string
  audioError?: string
  onSeekTrack?: (track: 'before' | 'after', time: number) => void
}

export const CompareTakesStep: React.FC<CompareTakesStepProps> = ({
  session,
  busy,
  onViewReport,
  onBackToChange,
  onPlayTrack,
  onPauseTrack,
  activeTrack,
  isPlaying,
  currentTime,
  isMuted,
  onToggleMute,
  onSeek,
  onRetry,
  selectedMicId,
  onSelectMic,
  currentPhrase,
  condition,
  audioError,
  onSeekTrack
}) => {
  const micIds = session?.shot_context?.mic_ids || ['mic_1', 'mic_2', 'mic_3', 'mic_4']
  const performerNames = session?.shot_context?.performer_names || {
    mic_1: 'Elena',
    mic_2: 'Marcus',
    mic_3: 'Security Guard',
    mic_4: 'Overhead Boom'
  }

  const [localMicId, setLocalMicId] = useState<string>('mic_1')
  const effectiveMicId = selectedMicId ?? localMicId
  const handleSelectMic = onSelectMic ?? setLocalMicId
  const micName = performerNames[effectiveMicId] || effectiveMicId

  // Evidence derived from actual runs
  const beforeEv = microphoneEvidence(session?.baseline ?? null, effectiveMicId, 12000)
  const afterEv = microphoneEvidence(session?.comparison ?? null, effectiveMicId, 12000)

  // Derive baseline issue microphones from microphoneEvidence using session shot_context IDs
  const baselineIssueMicIds = micIds.filter((id) => {
    const ev = microphoneEvidence(session?.baseline ?? null, id, 12000)
    return ev.hasIssue || !ev.complete
  })
  const firstIssueMicId = baselineIssueMicIds[0]
  const firstIssueName = firstIssueMicId ? (performerNames[firstIssueMicId] || firstIssueMicId) : null

  // Derive remaining issue microphones after repeat check
  const remainingIssueMicIds = micIds.filter((id) => {
    const ev = microphoneEvidence(session?.comparison ?? null, id, 12000)
    return ev.hasIssue || !ev.complete
  })
  const remainingIssueNames = remainingIssueMicIds.map((id) => performerNames[id] || id)

  // When selected microphone is healthy both times
  const isSelectedMicHealthyBoth =
    (!beforeEv.hasIssue && beforeEv.complete) &&
    (!afterEv.hasIssue && afterEv.complete)

  // Configuration details from actual configs
  const baselineConfig = session?.baseline_config
  const comparisonConfig = session?.comparison_config

  const beforeChannel = baselineConfig?.channel_assignments?.[effectiveMicId]
  const afterChannel = comparisonConfig?.channel_assignments?.[effectiveMicId]

  const beforeAntenna = baselineConfig?.antenna_selection
  const afterAntenna = comparisonConfig?.antenna_selection

  const isAntennaChange = beforeAntenna && afterAntenna && beforeAntenna !== afterAntenna
  const isChannelChange = beforeChannel !== undefined && afterChannel !== undefined && beforeChannel !== afterChannel
  const isBackupChange = Boolean(comparisonConfig?.backup_sources?.[effectiveMicId])

  // Global antenna_selection is a receiver setting, not selected actor's personal setting
  const beforeMeta = isAntennaChange
    ? `${micName} · Receiver antenna ${beforeAntenna}`
    : beforeChannel !== undefined
    ? `${micName} · Channel ${beforeChannel}`
    : micName

  const afterMeta = isAntennaChange
    ? `${micName} · Receiver antenna ${afterAntenna}`
    : isBackupChange
    ? `${micName} · Overhead Boom backup`
    : afterChannel !== undefined
    ? `${micName} · Channel ${afterChannel}`
    : micName

  const verification = session?.verification
  const isPreview = session?.mode === 'preview'
  const isVerified = verification?.terminal_status === 'VERIFIED'
  const isFailed = verification?.terminal_status === 'NOT_VERIFIED'

  const evidenceUrl =
    session?.id && session.comparison?.run_id
      ? `/api/sessions/${encodeURIComponent(session.id)}/evidence/${encodeURIComponent(
          session.comparison.run_id
        )}`
      : null

  // Fetch actual /api/sessions/:id/evidence-links with same-origin credentials for live session
  const [grafanaLinks, setGrafanaLinks] = useState<{ label: string; url: string }[]>([])
  useEffect(() => {
    if (session?.mode === 'live' && session?.id) {
      let cancelled = false
      fetch(`/api/sessions/${encodeURIComponent(session.id)}/evidence-links`, {
        credentials: 'same-origin',
        signal: AbortSignal.timeout(4000)
      })
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          if (!cancelled && Array.isArray(data?.links)) {
            const validLinks = (data.links as { label: string; url: string }[]).filter((l) => {
              try {
                const u = new URL(l.url)
                return u.protocol === 'https:' && !u.username && !u.password
              } catch {
                return false
              }
            })
            setGrafanaLinks(validLinks)
          }
        })
        .catch(() => {})
      return () => {
        cancelled = true
      }
    }
  }, [session?.id, session?.mode])

  const confirmedRules = session?.confirmed_constraints?.filter(rule => rule.confirmed) ?? []

  const isBeforePlaying = isPlaying && activeTrack === 'before'
  const isAfterPlaying = isPlaying && activeTrack === 'after'

  const audioStatusText = isPlaying
    ? activeTrack === 'before'
      ? `Playing Before — ${micName}`
      : `Playing After — ${micName}`
    : `Paused — ${activeTrack === 'before' ? 'Before' : 'After'}`

  return (
    <div className="compare-takes-step-view">
      {/* Page Title & Status Badge */}
      <div className="step-heading-group flex items-baseline justify-between flex-wrap gap-3">
        <div>
          <h1 className="step-main-title">Compare takes</h1>
          <p className="step-subtitle">
            Play <strong>Before</strong> and <strong>After</strong> to hear the difference, then
            open the report.
          </p>
        </div>

        <div className="compare-status-callout">
          {isVerified ? (
            <div className="status-callout-pill status-pill-success">
              <CheckCircleIcon size={18} filled={true} />
              <span>New check passed</span>
            </div>
          ) : isFailed ? (
            <div className="status-callout-pill status-pill-failed">
              <span>Fix did not pass</span>
            </div>
          ) : (
            <div className="status-callout-pill status-pill-inconclusive">
              <CheckCircleIcon size={18} filled={false} />
              <span>{isPreview ? 'Inconclusive (preview only)' : 'Inconclusive'}</span>
            </div>
          )}

        </div>
      </div>

      {/* Overall Failure Prominent Banner */}
      {isFailed && (
        <div className="compare-failure-banner p-3 mb-3 bg-red-50 border border-red-200 rounded-md flex items-center justify-between flex-wrap gap-3" role="alert">
          <div>
            <strong className="block text-sm font-semibold text-red-900">
              The change did not pass the repeat check.
            </strong>
            <p className="text-xs text-red-800 mt-0.5">
              {remainingIssueNames.length > 0
                ? `Remaining sound issues on: ${remainingIssueNames.join(', ')}.`
                : 'The repeat check still found a problem.'}
            </p>
          </div>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="btn-retry-top px-3 py-1.5 bg-[#b84729] text-white text-xs font-semibold rounded hover:bg-[#9f3d23] transition-colors"
              disabled={!!busy}
            >
              {isPreview ? 'Try another preview fix' : 'Ask Gemini for another fix'}
            </button>
          )}
        </div>
      )}

      {/* Microphone Selector & Clarification */}
      <div className="compare-mic-selector-section mb-3">
        <div className="compare-mic-selector-row flex items-center gap-2 flex-wrap">
          <span className="text-xs font-bold text-gray-800 uppercase mr-1">Compare microphone:</span>
          {micIds.map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => handleSelectMic(id)}
              className={`compare-mic-pill ${effectiveMicId === id ? 'active' : ''}`}
              aria-pressed={effectiveMicId === id}
            >
              {performerNames[id] || id}
            </button>
          ))}
        </div>
        <p className="compare-mic-clarification text-xs text-gray-600 mt-1">
          Every microphone uses the same sample dialogue. Only its simulated sound faults change.
        </p>

        {/* When selected microphone is healthy both times */}
        {isSelectedMicHealthyBoth && (
          <div className="healthy-mic-notice p-2.5 mt-2 bg-blue-50 border border-blue-200 rounded text-xs text-blue-900 flex items-center justify-between flex-wrap gap-2">
            <span>{micName} has no sound faults in either check, so Before and After sound the same.</span>
            {firstIssueMicId && firstIssueMicId !== effectiveMicId && (
              <button
                type="button"
                onClick={() => handleSelectMic(firstIssueMicId)}
                className="btn-compare-issue-mic font-semibold underline hover:no-underline text-blue-800"
              >
                Compare {firstIssueName} instead
              </button>
            )}
          </div>
        )}
      </div>

      {audioError && (
        <div role="alert" className="audio-error-alert p-2 mb-3 bg-red-50 border border-red-200 rounded text-xs text-red-800">
          <strong>Audio playback issue:</strong> <span>{audioError}</span>
        </div>
      )}

      {/* 2-Column Grid */}
      <div className="step-two-columns">
        {/* Left Column: Stacked Before / After Waveforms + Comparison Table */}
        <div className="step-main-card compare-main-panel">
          {/* Active Audio Status & Explanation */}
          <div className="active-audio-status-banner flex items-center justify-between text-xs py-2 px-3 bg-gray-100 rounded border border-gray-200 mb-3 flex-wrap gap-1">
            <span className="font-semibold text-gray-900">{audioStatusText}</span>
            <span className="text-gray-600">Only one version plays at a time. Switching keeps your place.</span>
          </div>

          {/* Track 1: Before */}
          <div className={`compare-track-block p-2.5 rounded-md ${activeTrack === 'before' ? 'compare-track-active ring-2 ring-[#b84729] bg-orange-50/20' : ''}`}>
            <div className="compare-track-header flex items-baseline justify-between">
              <div className="flex items-baseline gap-2">
                <span className="compare-track-label">Before</span>
                <span className="compare-track-meta">{beforeMeta}</span>
                {activeTrack === 'before' && (
                  <span className="track-selected-badge text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-[#b84729] text-white">
                    {isPlaying ? 'Playing' : 'Active'}
                  </span>
                )}
              </div>
              <span className="text-xs text-gray-500 font-mono">
                {soundSummary(beforeEv)}
              </span>
            </div>

            <div className="compare-track-transport-row mt-2">
              <button
                type="button"
                onClick={isBeforePlaying ? onPauseTrack : () => onPlayTrack('before')}
                className="scene-play-btn"
                aria-label={isBeforePlaying ? 'Pause before take' : 'Play before take'}
              >
                {isBeforePlaying ? <PauseIcon size={16} /> : <PlayIcon size={16} />}
                <span>{isBeforePlaying ? 'Pause before' : 'Play before'}</span>
              </button>

              <div className="compare-track-waveform-wrap">
                <WaveformTrack
                  peaks={PCM_PEAKS_240}
                  height={52}
                  tint="default"
                  intervals={beforeEv.intervals}
                  playheadTime={currentTime}
                  showPlayhead={activeTrack === 'before'}
                  showRuler={true}
                  onSeek={(time) => (onSeekTrack ? onSeekTrack('before', time) : onSeek(time))}
                  interactive={true}
                  ariaLabel="Before waveform"
                />
              </div>
            </div>
          </div>

          <div className="card-divider my-4" />

          {/* Track 2: After */}
          <div className={`compare-track-block p-2.5 rounded-md ${activeTrack === 'after' ? 'compare-track-active ring-2 ring-[#b84729] bg-orange-50/20' : ''}`}>
            <div className="compare-track-header flex items-baseline justify-between">
              <div className="flex items-baseline gap-2">
                <span className="compare-track-label">After</span>
                <span className="compare-track-meta">{afterMeta}</span>
                {activeTrack === 'after' && (
                  <span className="track-selected-badge text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-[#b84729] text-white">
                    {isPlaying ? 'Playing' : 'Active'}
                  </span>
                )}
              </div>
              <span className="text-xs text-gray-500 font-mono">
                {soundSummary(afterEv)}
              </span>
            </div>

            <div className="compare-track-transport-row mt-2">
              <button
                type="button"
                onClick={isAfterPlaying ? onPauseTrack : () => onPlayTrack('after')}
                className="scene-play-btn"
                aria-label={isAfterPlaying ? 'Pause after take' : 'Play after take'}
              >
                {isAfterPlaying ? <PauseIcon size={16} /> : <PlayIcon size={16} />}
                <span>{isAfterPlaying ? 'Pause after' : 'Play after'}</span>
              </button>

              <div className="compare-track-waveform-wrap">
                <WaveformTrack
                  peaks={PCM_PEAKS_240}
                  height={52}
                  tint="salmon"
                  intervals={afterEv.intervals}
                  playheadTime={currentTime}
                  showPlayhead={activeTrack === 'after'}
                  showRuler={true}
                  onSeek={(time) => (onSeekTrack ? onSeekTrack('after', time) : onSeek(time))}
                  interactive={true}
                  ariaLabel="After waveform"
                />
              </div>
            </div>
          </div>


          {/* Shared Transport Status & Mute Toggle */}
          <div className="mt-3 flex items-center justify-between text-xs text-gray-500">
            <button
              type="button"
              onClick={onToggleMute}
              className="scene-mute-btn flex items-center gap-1.5"
              aria-label={isMuted ? 'Unmute sound' : 'Mute sound'}
            >
              {isMuted ? <MuteIcon size={16} /> : <VolumeIcon size={16} />}
              <span>{isMuted ? 'Muted' : 'Sound on'}</span>
            </button>
            <span>Playhead: {currentTime.toFixed(1)}s / 12s</span>
          </div>

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

          <div className="card-divider my-5" />

          {/* Compact Comparison Table */}
          <div className="table-responsive-container">
            <table className="compare-matrix-table" aria-label="Before and after comparison table">
              <thead>
                <tr>
                  <th scope="col">Item</th>
                  <th scope="col">Before</th>
                  <th scope="col">After</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="font-medium">Missing sound</td>
                  <td>
                    {beforeEv.complete ? `${(beforeEv.dropoutMs / 1000).toFixed(1)}s` : 'Incomplete readings'}{' '}
                    <span className="text-gray-400 mx-2">→</span>
                  </td>
                  <td className="font-medium text-gray-900">
                    {afterEv.complete ? `${(afterEv.dropoutMs / 1000).toFixed(1)}s` : 'Incomplete readings'}
                  </td>
                </tr>

                {beforeEv.clippingMs > 0 || afterEv.clippingMs > 0 ? (
                  <tr>
                    <td className="font-medium">Clipping sound</td>
                    <td>
                      {(beforeEv.clippingMs / 1000).toFixed(1)}s{' '}
                      <span className="text-gray-400 mx-2">→</span>
                    </td>
                    <td className="font-medium text-gray-900">
                      {(afterEv.clippingMs / 1000).toFixed(1)}s
                    </td>
                  </tr>
                ) : null}

                {isAntennaChange ? (
                  <tr>
                    <td className="font-medium">Receiver antenna</td>
                    <td>
                      Antenna {beforeAntenna}{' '}
                      <span className="text-gray-400 mx-2">→</span>
                    </td>
                    <td className="font-medium text-gray-900">Antenna {afterAntenna}</td>
                  </tr>
                ) : isBackupChange ? (
                  <tr>
                    <td className="font-medium">Dialogue routing</td>
                    <td>
                      Primary only <span className="text-gray-400 mx-2">→</span>
                    </td>
                    <td className="font-medium text-gray-900">Overhead Boom backup</td>
                  </tr>
                ) : isChannelChange ? (
                  <tr>
                    <td className="font-medium">{micName}'s channel</td>
                    <td>
                      {beforeChannel} <span className="text-gray-400 mx-2">→</span>
                    </td>
                    <td className="font-medium text-gray-900">{afterChannel}</td>
                  </tr>
                ) : (
                  <tr>
                    <td className="font-medium">Receiver state</td>
                    <td>Measured baseline</td>
                    <td className="font-medium text-gray-900">Tested comparison</td>
                  </tr>
                )}

                {confirmedRules.map(rule => (
                  <tr key={rule.constraint_id}>
                    <td className="font-medium">{rule.exact_source_span || rule.source_text}</td>
                    <td>Confirmed restriction</td>
                    <td>{verification?.constraints_passed ? 'Respected' : 'Not verified'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Right Sidebar */}
        <aside className="step-sidebar-card">
          <div className="sidebar-section">
            <h2 className="sidebar-title">What changed</h2>
            <div className="text-xs font-semibold text-gray-500 mb-1">
              {session?.finding_origin === 'gemini'
                ? 'Suggested by Gemini'
                : session?.finding_origin === 'preview'
                ? 'Sample rehearsal suggestion'
                : 'Recorded baseline diagnostic'}
            </div>
            <p className="sidebar-text">
              {isAntennaChange
                ? `Receiver antenna switched from ${beforeAntenna} to ${afterAntenna}.`
                : isBackupChange
                ? `Dialogue backed up by Overhead Boom.`
                : isChannelChange
                ? `${micName}'s channel changed.`
                : 'Receiver settings adjusted according to approved plan.'}
            </p>
            {confirmedRules.length > 0 && (
              <p className="sidebar-text mt-1">
                {verification?.constraints_passed
                  ? 'Your confirmed restrictions were respected.'
                  : 'Your restrictions have not all been verified. Review the report.'}
              </p>
            )}
          </div>

          <div className="card-divider" />

          <div className="sidebar-section">
            <h2 className="sidebar-title">
              {session?.mode === 'live'
                ? 'New readings checked with Grafana'
                : 'Preview readings checked'}
            </h2>
            <p className="sidebar-text">
              {session?.mode === 'live'
                ? 'After your approval, the app runs a new simulated rehearsal and checks its readings in Grafana to see whether the change helped.'
                : 'This comparison uses built-in sample readings. Gemini and Grafana were not called.'}
            </p>
            {session?.mode === 'live' && verification?.crosscheck_passed && (
              <p className="text-xs text-green-800 font-medium mb-1.5">
                Grafana logs and metrics agree
              </p>
            )}
            {isFailed && (
              <p className="text-xs text-red-700 font-medium mb-1.5">
                The repeat check still found a problem
              </p>
            )}
            <div className="flex flex-col gap-1.5 mt-2">
              {evidenceUrl && (
                <a
                  href={evidenceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="view-readings-link inline-flex items-center gap-1.5 text-xs font-semibold text-blue-700 hover:underline"
                >
                  <FileReportIcon size={16} />
                  <span>View readings</span>
                  <ExternalLinkIcon size={12} />
                </a>
              )}
              {grafanaLinks.map((link, idx) => (
                <a
                  key={idx}
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="grafana-evidence-link inline-flex items-center gap-1.5 text-xs font-semibold text-blue-700 hover:underline"
                >
                  <ExternalLinkIcon size={12} />
                  <span>{link.label} readings in Grafana</span>
                </a>
              ))}
            </div>
            {!evidenceUrl && grafanaLinks.length === 0 && (
              <span className="text-sm text-gray-400 mt-2 block">Readings saved with check</span>
            )}
          </div>

          <div className="card-divider" />

          <p className="sidebar-footnote">
            The After audio comes from a new sample check.
          </p>
        </aside>
      </div>

      {/* Bottom Action Bar */}
      <footer className="step-bottom-action-bar">
        <div className="bottom-action-left items-center">
          <button
            type="button"
            className="btn-terracotta-primary inline-flex items-center gap-2"
            onClick={onViewReport}
            disabled={!!busy}
          >
            <FileReportIcon size={18} />
            <span>View report</span>
          </button>
          {isFailed && onRetry && (
            <button
              type="button"
              className="btn-secondary-outline inline-flex items-center gap-2"
              onClick={onRetry}
              disabled={!!busy}
            >
              <span>Try another fix</span>
            </button>
          )}
          <span className="bottom-action-hint">See the checks and save the result.</span>
        </div>


        <div className="bottom-action-right items-center gap-4">
          <button
            type="button"
            onClick={onBackToChange}
            className="btn-back-link"
            disabled={!!busy}
          >
            <ArrowLeftIcon size={16} />
            <span>Back to change</span>
          </button>
          <span className="bottom-action-sample-tag">
            Sample scene · Simulated microphone readings
          </span>
        </div>
      </footer>
    </div>
  )
}
