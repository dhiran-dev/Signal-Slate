import React, { useMemo } from 'react'
import { PCM_PEAKS_960 } from './waveformPeaks'
import type { SoundInterval } from './evidence'

export interface WaveformTrackProps {
  peaks?: number[]
  height?: number
  tint?: 'default' | 'salmon' | 'muted'
  intervals?: SoundInterval[]
  missingInterval?: { startS: number; endS: number; label?: string }
  playheadTime?: number
  showPlayhead?: boolean
  showRuler?: boolean
  onSeek?: (timeS: number) => void
  interactive?: boolean
  className?: string
  ariaLabel?: string
}

export const WaveformTrack: React.FC<WaveformTrackProps> = ({
  peaks = PCM_PEAKS_960,
  height = 48,
  tint = 'default',
  intervals,
  missingInterval,
  playheadTime,
  showPlayhead = true,
  showRuler = false,
  onSeek,
  interactive = false,
  className = '',
  ariaLabel = 'Audio waveform'
}) => {
  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!onSeek) return
    const rect = e.currentTarget.getBoundingClientRect()
    const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left))
    const timeS = (x / rect.width) * 12.0
    onSeek(Number(timeS.toFixed(2)))
  }

  const strokeColor = tint === 'salmon' ? '#d97757' : tint === 'muted' ? '#9ca3af' : '#7c858e'

  // Combine missingInterval and intervals
  const combinedIntervals: SoundInterval[] = intervals
    ? [...intervals]
    : missingInterval
    ? [{ kind: 'dropout', startS: missingInterval.startS, endS: missingInterval.endS }]
    : []

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!interactive || !onSeek) return
    const current = playheadTime ?? 0
    if (e.key === 'ArrowRight') {
      e.preventDefault()
      onSeek(Math.min(12, Number((current + 0.2).toFixed(2))))
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault()
      onSeek(Math.max(0, Number((current - 0.2).toFixed(2))))
    } else if (e.key === 'Home') {
      e.preventDefault()
      onSeek(0)
    } else if (e.key === 'End') {
      e.preventDefault()
      onSeek(12)
    }
  }

  const svgWidth = 960
  const midY = height / 2

  // Build continuous organic filled path
  const pathD = useMemo(() => {
    const activePeaks = peaks.length >= 480 ? peaks : PCM_PEAKS_960
    const n = activePeaks.length
    if (n === 0) return ''

    let top = `M 0,${midY.toFixed(1)}`
    for (let i = 0; i < n; i++) {
      const timeS = (i / (n - 1)) * 12.0
      const isInsideDropout = combinedIntervals.some(
        (int) => int.kind === 'dropout' && timeS >= int.startS && timeS <= int.endS
      )
      const x = ((i / (n - 1)) * svgWidth).toFixed(1)
      const barHalf = isInsideDropout ? 0 : Math.max(0.6, activePeaks[i] * (midY - 2))
      top += ` L ${x},${(midY - barHalf).toFixed(1)}`
    }

    let bot = ''
    for (let i = n - 1; i >= 0; i--) {
      const timeS = (i / (n - 1)) * 12.0
      const isInsideDropout = combinedIntervals.some(
        (int) => int.kind === 'dropout' && timeS >= int.startS && timeS <= int.endS
      )
      const x = ((i / (n - 1)) * svgWidth).toFixed(1)
      const barHalf = isInsideDropout ? 0 : Math.max(0.6, activePeaks[i] * (midY - 2))
      bot += ` L ${x},${(midY + barHalf).toFixed(1)}`
    }

    return `${top}${bot} Z`
  }, [peaks, combinedIntervals, midY, svgWidth])

  return (
    <div className={`waveform-track-container ${className}`}>
      {/* Time ruler if requested */}
      {showRuler && (
        <div className="waveform-ruler" aria-hidden="true">
          {[0, 2, 4, 6, 8, 10, 12].map((sec) => (
            <div
              key={sec}
              className="waveform-ruler-mark"
              style={{ left: `${(sec / 12) * 100}%` }}
            >
              <span>{sec}s</span>
              <div className="waveform-ruler-tick" />
            </div>
          ))}
        </div>
      )}

      {/* Waveform track body */}
      <div
        className={`waveform-track-body ${interactive ? 'cursor-pointer focus:outline-none focus:ring-2 focus:ring-[#b84729]' : ''}`}
        style={{ height: `var(--workspace-waveform-height, ${height}px)` }}
        onClick={handleClick}
        role={interactive ? 'slider' : 'img'}
        aria-label={ariaLabel}
        {...(interactive
          ? {
              'aria-valuemin': 0,
              'aria-valuemax': 12,
              'aria-valuenow': playheadTime !== undefined ? Number(playheadTime.toFixed(1)) : 0,
              tabIndex: 0
            }
          : {})}
        onKeyDown={handleKeyDown}
      >
        {/* SVG High-density Continuous Waveform Rendering */}
        <svg
          viewBox={`0 0 ${svgWidth} ${height}`}
          preserveAspectRatio="none"
          className="waveform-svg-canvas"
          aria-hidden="true"
        >
          <path d={pathD} fill={strokeColor} />
        </svg>

        {/* Observed Intervals Overlay (dropouts, clipping, unknown) */}
        {combinedIntervals.map((interval, i) => {
          const left = (interval.startS / 12) * 100
          const width = ((interval.endS - interval.startS) / 12) * 100
          const isDropout = interval.kind === 'dropout'
          const isClipped = interval.kind === 'clipped'
          const hatchClass = isDropout
            ? 'waveform-missing-hatch'
            : isClipped
            ? 'waveform-clipping-hatch'
            : 'waveform-unknown-hatch'

          return (
            <div
              key={i}
              className={hatchClass}
              style={{ left: `${left}%`, width: `${width}%` }}
              aria-hidden="true"
            />
          )
        })}

        {/* Missing section text tag if supplied */}
        {missingInterval?.label && (
          <div
            className="waveform-missing-label-box"
            style={{
              left: `${((missingInterval.startS + (missingInterval.endS - missingInterval.startS) / 2) / 12) * 100}%`
            }}
            aria-hidden="true"
          >
            <span className="waveform-missing-tag">{missingInterval.label}</span>
          </div>
        )}

        {/* Playhead indicator with badge (rendered only when showPlayhead is true) */}
        {playheadTime !== undefined && showPlayhead && (
          <div
            className="waveform-playhead-line"
            style={{ left: `${(playheadTime / 12.0) * 100}%` }}
            aria-hidden="true"
          >
            <div className="waveform-playhead-badge">
              <span className="waveform-playhead-dot" />
              <span className="waveform-playhead-text">{playheadTime.toFixed(1)}s</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
