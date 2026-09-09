import React, { useState } from 'react'
import type { Readiness } from './types'
import { MicIcon, BoomMicIcon, PlayIcon, PauseIcon, CheckCircleIcon } from './icons'
import { WaveformTrack } from './WaveformTrack'
import { PCM_PEAKS_120 } from './waveformPeaks'

export interface SceneSetupStepProps {
  preset: string
  onPresetChange: (preset: string) => void
  mode: 'live' | 'preview'
  onModeChange: (mode: 'live' | 'preview') => void
  readiness: Readiness | null
  busy: string
  hasSession?: boolean
  onStartAnotherCheck?: () => void
  onCheckSound: () => void
  onPlaySample: () => void
  onPauseSample: () => void
  isPlaying: boolean
  currentTime: number
  onSeek: (time: number) => void
  audioError?: string
}

const PRESET_OPTIONS = [
  { id: 'a', label: 'Alleyway dialogue', desc: '12 seconds · 4 microphones' },
  { id: 'b', label: 'Alternate rehearsal B', desc: '12 seconds · 4 microphones' },
  { id: 'c', label: 'Alternate rehearsal C', desc: '12 seconds · 4 microphones' },
  { id: 'control', label: 'Control rehearsal', desc: '12 seconds · 4 microphones' }
]

export const SceneSetupStep: React.FC<SceneSetupStepProps> = ({
  preset,
  onPresetChange,
  mode,
  onModeChange,
  readiness,
  busy,
  hasSession = false,
  onStartAnotherCheck,
  onCheckSound,
  onPlaySample,
  onPauseSample,
  isPlaying,
  currentTime,
  onSeek,
  audioError
}) => {
  const [showAdvanced, setShowAdvanced] = useState(false)
  const currentPresetMeta = PRESET_OPTIONS.find((p) => p.id === preset) || PRESET_OPTIONS[0]

  const formatTimecode = (sec: number) => {
    const s = Math.floor(sec)
    return `0:${s < 10 ? '0' : ''}${s}`
  }

  // Truthful readiness handling: null means checking, not configured
  const isCheckingReadiness = readiness === null
  const geminiConfigured = readiness?.gemini?.configured ?? false
  const grafanaConfigured = readiness?.grafana?.configured ?? false
  const liveAvailable = readiness?.live_available ?? false


  const isCheckSoundDisabled = Boolean(
    busy || (mode === 'live' && (!readiness || !liveAvailable))
  )

  const micTracks = [
    { id: 'mic_1', name: 'Elena', isBoom: false },
    { id: 'mic_2', name: 'Marcus', isBoom: false },
    { id: 'mic_3', name: 'Security Guard', isBoom: false },
    { id: 'mic_4', name: 'Overhead Boom', isBoom: true }
  ]

  return (
    <div className="scene-setup-step-view">
      {/* Page Title */}
      <div className="step-heading-group">
        <h1 className="step-main-title">Scene setup</h1>
        <p className="step-subtitle">Choose a sample scene, then click Check sound.</p>
      </div>

      {/* Restored Session In-Progress Notice */}
      {hasSession && (
        <div className="rehearsal-banner banner-notice mb-4">
          <span>A sound check is already underway for this rehearsal.</span>
          {onStartAnotherCheck && (
            <button
              type="button"
              className="banner-resume-btn"
              onClick={onStartAnotherCheck}
              disabled={!!busy}
            >
              Start another check
            </button>
          )}
        </div>
      )}

      {/* 2-Column Layout */}
      <div className="step-two-columns">
        {/* Left Column: Sample Scene + Waveform Grid */}
        <div className="step-main-card">
          {/* Top Row: Scene Picker + Scene Banner */}
          <div className="scene-picker-row">
            <div className="scene-picker-left">
              <label htmlFor="sample-scene-select" className="scene-picker-label">
                Sample scene
              </label>
              <div className="scene-select-wrapper">
                <select
                  id="sample-scene-select"
                  value={preset}
                  onChange={(e) => onPresetChange(e.target.value)}
                  className="scene-select-control"
                  aria-label="Sample scene"
                  disabled={hasSession || !!busy}
                >
                  {PRESET_OPTIONS.map((opt) => (
                    <option key={opt.id} value={opt.id}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
              <p className="scene-meta-text">{currentPresetMeta.desc}</p>
            </div>

            <div className="scene-picker-right">
              <img
                src="/images/alleyway-scene.png"
                alt="Sample alleyway scene setup"
                className="scene-banner-img"
              />
            </div>
          </div>

          <div className="card-divider" />

          {/* Transport Row */}
          <div className="scene-transport-row">
            <button
              type="button"
              onClick={isPlaying ? onPauseSample : onPlaySample}
              className="scene-play-btn"
              aria-label={isPlaying ? 'Pause sample' : 'Play sample'}
            >
              {isPlaying ? <PauseIcon size={16} /> : <PlayIcon size={16} />}
              <span>{isPlaying ? 'Pause sample' : 'Play sample'}</span>
            </button>

            <span className="scene-timecode-display" aria-label="Playback time">
              {formatTimecode(currentTime)} / 0:12
            </span>
          </div>

          {audioError && (
            <div role="alert" className="audio-error-alert p-2 my-2 bg-red-50 border border-red-200 rounded text-xs text-red-800">
              <strong>Audio playback issue:</strong> <span>{audioError}</span>
            </div>
          )}

          {/* Time Ruler */}
          <div className="scene-time-ruler" aria-hidden="true">
            {[0, 2, 4, 6, 8, 10, 12].map((s) => (
              <div key={s} className="scene-ruler-tick" style={{ left: `${(s / 12) * 100}%` }}>
                <span>{s}s</span>
                <div className="scene-ruler-mark" />
              </div>
            ))}
          </div>

          {/* 4 Multi-track Waveforms */}
          <div className="scene-tracks-list" role="region" aria-label="Microphone tracks">
            {micTracks.map((mic) => (
              <div key={mic.id} className="scene-track-row">
                <div className="scene-track-info">
                  {mic.isBoom ? (
                    <BoomMicIcon size={26} className="text-gray-700" />
                  ) : (
                    <MicIcon size={26} className="text-gray-700" />
                  )}
                  <span className="scene-track-name">{mic.name}</span>
                </div>

                <div className="scene-track-waveform-wrap">
                  <WaveformTrack
                    peaks={PCM_PEAKS_120}
                    height={38}
                    tint="default"
                    playheadTime={currentTime}
                    onSeek={onSeek}
                    interactive={true}
                    ariaLabel={`${mic.name} waveform`}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right Sidebar: About & Connection Status */}
        <aside className="step-sidebar-card">
          <div className="sidebar-section">
            <h2 className="sidebar-title">About this sample</h2>
            <p className="sidebar-text">
              You are checking sound before filming. Click Check sound, review any missing dialogue, then use Find a fix to review a suggested change.
            </p>
            <p className="sidebar-footnote mt-2">
              This 12-second demo uses sample dialogue and simulated microphones. No recording equipment is needed.
            </p>
          </div>

          <div className="card-divider" />

          <div className="sidebar-section">
            <h2 className="sidebar-title">Connection status</h2>
            <p className="sidebar-text mb-3">
              {mode === 'live'
                ? 'Gemini reads the microphone measurements and suggests a change. Grafana stores the readings that the app uses to check the result.'
                : 'Preview uses built-in sample results. It does not call Gemini or Grafana.'}
            </p>
            <ul className="connection-status-list">
              <li className="connection-status-item flex items-center gap-3">
                <CheckCircleIcon size={32} filled={!isCheckingReadiness && geminiConfigured} />
                <span>
                  {isCheckingReadiness
                    ? 'Checking Gemini…'
                    : geminiConfigured
                    ? 'Gemini configured'
                    : 'Gemini not configured'}
                </span>
              </li>
              <li className="connection-status-item flex items-center gap-3">
                <CheckCircleIcon size={32} filled={!isCheckingReadiness && grafanaConfigured} />
                <span>
                  {isCheckingReadiness
                    ? 'Checking Grafana…'
                    : grafanaConfigured
                    ? 'Grafana configured'
                    : 'Grafana not configured'}
                </span>
              </li>
            </ul>

            {/* Actionable notice outside details if live mode is selected but cloud runtime is unavailable */}
            {mode === 'live' && !isCheckingReadiness && !liveAvailable && (
              <div className="live-unavailable-card p-3 my-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-900">
                <strong>Live cloud runtime unavailable.</strong>
                <p className="mt-1">
                  Gemini and Grafana must be connected for live checks. You can run locally:
                </p>
                <button
                  type="button"
                  onClick={() => onModeChange('preview')}
                  className="mt-2 inline-flex items-center text-xs font-semibold text-blue-700 hover:underline"
                >
                  Preview without cloud →
                </button>
              </div>
            )}

            {/* Live Usage Disclosure visible outside collapsed details */}
            <p className="usage-disclosure-text">
              A live check makes at most five Gemini requests. Google API usage charges may apply.
            </p>

            {/* Collapsible Connection Help & Options */}
            <details
              className="connection-help-disclosure mt-3"
              open={showAdvanced}
              onToggle={(e) => setShowAdvanced(e.currentTarget.open)}
            >
              <summary className="connection-help-summary">Connection help & options</summary>
              <div className="connection-help-body">
                <div className="connection-mode-toggle">
                  <label className="mode-radio-label">
                    <input
                      type="radio"
                      name="wf-mode"
                      value="live"
                      checked={mode === 'live'}
                      onChange={() => onModeChange('live')}
                      disabled={hasSession || !!busy}
                    />
                    <span>Live cloud check</span>
                  </label>
                  <label className="mode-radio-label">
                    <input
                      type="radio"
                      name="wf-mode"
                      value="preview"
                      checked={mode === 'preview'}
                      onChange={() => onModeChange('preview')}
                      disabled={hasSession || !!busy}
                    />
                    <span>Preview without cloud</span>
                  </label>
                </div>

                {readiness?.missing && readiness.missing.length > 0 && (
                  <div className="missing-items-box">
                    <strong>Missing connections:</strong>
                    <ul>
                      {readiness.missing.map((m, i) => (
                        <li key={i}>{m}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </details>
          </div>

          <div className="card-divider" />

          <p className="sidebar-footnote">
            Sound gaps come from simulated readings. This demo does not analyse uploaded audio.
          </p>
        </aside>
      </div>

      {/* Bottom Action Card */}
      <footer className="step-bottom-action-bar">
        <div className="bottom-action-left">
          <button
            type="button"
            className="btn-terracotta-primary btn-setup-cta"
            onClick={onCheckSound}
            disabled={isCheckSoundDisabled}
          >
            {busy ? 'Checking sound…' : 'Check sound'}
          </button>
          <span className="bottom-action-hint">Checks this sample for missing dialogue.</span>
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
