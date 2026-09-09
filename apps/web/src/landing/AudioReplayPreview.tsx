import React, { useState } from 'react'
import captionsData from '../../../../assets/audio/captions.json'
import type { CaptionsData, CaptionPhrase } from './types'

const typedCaptions = captionsData as CaptionsData

interface AudioReplayPreviewProps {
  isPlaying: boolean
  currentTime: number
  duration: number
  isMuted: boolean
  onTogglePlay: () => void
  onSeek: (time: number) => void
  onToggleMute: () => void
}

export const AudioReplayPreview: React.FC<AudioReplayPreviewProps> = ({
  isPlaying,
  currentTime,
  duration,
  isMuted,
  onTogglePlay,
  onSeek,
  onToggleMute,
}) => {
  const [activeChannel, setActiveChannel] = useState<'boom1' | 'lavA' | 'plantC'>('boom1')

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newTime = parseFloat(e.target.value)
    onSeek(newTime)
  }

  // Format seconds to mm:ss.s
  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = (seconds % 60).toFixed(1)
    return `${mins.toString().padStart(2, '0')}:${secs.padStart(4, '0')}`
  }

  // Check if current time is within illustrative dropout window (4.9s - 6.8s)
  const isInsideDropoutWindow = currentTime >= 4.9 && currentTime <= 6.8

  // Find active phrase
  const activePhrase: CaptionPhrase | undefined = typedCaptions.phrases.find(
    (p) => currentTime >= p.approx_start_seconds && currentTime <= p.approx_end_seconds
  )

  return (
    <section id="audio-replay" className="py-16 sm:py-20 lg:py-24 border-b border-[#edfffe]/16 bg-[#012624]">
      <div className="max-w-[1440px] mx-auto px-5 sm:px-8 lg:px-16">
        {/* Recessed Editorial Panel — 16px Radius, Flat, No Shadows */}
        <div className="bg-[#011d1c] border border-[#edfffe]/16 rounded-[16px] p-6 sm:p-8 lg:p-10">
          {/* Asymmetric Split: ~25% Left Label Column, ~75% Right Content Column */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-12">
            {/* Left Column (~25% / col-span-3) */}
            <div className="lg:col-span-4 flex flex-col justify-between border-b lg:border-b-0 lg:border-r border-[#edfffe]/16 pb-8 lg:pb-0 lg:pr-8">
              <div>
                <div className="text-[12px] uppercase tracking-[0.12em] font-normal text-[#bbc7c6] mb-3">
                  INTERACTIVE SCENE
                </div>
                <h2 className="text-2xl sm:text-3xl lg:text-[36px] font-medium tracking-[-0.04em] text-[#ffffff] leading-[1.0] mb-4">
                  One line. Every word matters.
                </h2>
                <p className="text-sm text-[#bbc7c6] leading-[1.4] mb-6">
                  Original synthetic source; risk window is illustrative. Open rehearsal for measured comparison.
                </p>

                {/* Honest Disclosure & Visual Channel Selector */}
                <div className="mb-6">
                  <div className="text-[11px] font-mono text-[#bbc7c6] uppercase tracking-wider mb-2">
                    Visual Channel Profile:
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <button
                      type="button"
                      onClick={() => setActiveChannel('boom1')}
                      className={`min-h-[36px] px-3 py-1.5 rounded-[6px] text-xs font-mono text-left transition-colors cursor-pointer border ${
                        activeChannel === 'boom1'
                          ? 'bg-[#003734] text-[#ffffff] font-bold border-[#edfffe]/40'
                          : 'bg-[#012624] text-[#bbc7c6] border-[#edfffe]/10 hover:text-[#ffffff]'
                      }`}
                    >
                      Boom 1 (In Dropout)
                    </button>
                    <button
                      type="button"
                      onClick={() => setActiveChannel('lavA')}
                      className={`min-h-[36px] px-3 py-1.5 rounded-[6px] text-xs font-mono text-left transition-colors cursor-pointer border ${
                        activeChannel === 'lavA'
                          ? 'bg-[#003734] text-[#ffffff] font-bold border-[#edfffe]/40'
                          : 'bg-[#012624] text-[#bbc7c6] border-[#edfffe]/10 hover:text-[#ffffff]'
                      }`}
                    >
                      Lav A (Marginal)
                    </button>
                    <button
                      type="button"
                      onClick={() => setActiveChannel('plantC')}
                      className={`min-h-[36px] px-3 py-1.5 rounded-[6px] text-xs font-mono text-left transition-colors cursor-pointer border ${
                        activeChannel === 'plantC'
                          ? 'bg-[#003734] text-[#ffffff] font-bold border-[#edfffe]/40'
                          : 'bg-[#012624] text-[#bbc7c6] border-[#edfffe]/10 hover:text-[#ffffff]'
                      }`}
                    >
                      Plant C (Clean)
                    </button>
                  </div>
                </div>
              </div>

              {/* Transport Controls & Timecode */}
              <div className="pt-6 border-t border-[#edfffe]/16">
                <div className="flex items-center justify-between text-xs font-mono text-[#bbc7c6] mb-4">
                  <span>TIMECODE</span>
                  <span className="text-[#ffffff] font-medium">{formatTime(currentTime)} / {formatTime(duration)}</span>
                </div>

                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={onTogglePlay}
                    aria-label={isPlaying ? 'Pause dialogue replay' : 'Play dialogue replay'}
                    aria-pressed={isPlaying}
                    className="min-h-[44px] px-5 py-2.5 rounded-[6px] bg-[#edfffe] text-[#011d1c] font-medium text-xs sm:text-sm hover:bg-[#ffffff] transition-colors cursor-pointer flex items-center gap-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#edfffe]"
                  >
                    {isPlaying ? (
                      <>
                        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                          <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
                        </svg>
                        <span>Pause</span>
                      </>
                    ) : (
                      <>
                        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                          <path d="M8 5v14l11-7z" />
                        </svg>
                        <span>Play Dialogue Line</span>
                      </>
                    )}
                  </button>

                  <button
                    type="button"
                    onClick={onToggleMute}
                    aria-label={isMuted ? 'Unmute audio' : 'Mute audio'}
                    className="min-h-[44px] px-3.5 py-2.5 rounded-[6px] bg-[#003734] border border-[#edfffe]/16 text-[#bbc7c6] hover:text-[#ffffff] text-xs font-mono transition-colors cursor-pointer flex items-center gap-2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#edfffe]"
                  >
                    {isMuted ? 'Muted (Audio Off)' : 'Audio On'}
                  </button>
                </div>
              </div>
            </div>

            {/* Right Column (~75% / col-span-8) */}
            <div className="lg:col-span-8 flex flex-col justify-between">
              {/* PRIMARY ELEMENT: Large Readable Synchronized Transcript */}
              <div>
                <div className="flex items-center justify-between text-xs font-mono text-[#bbc7c6] mb-4 pb-2 border-b border-[#edfffe]/16">
                  <span className="uppercase tracking-wider">Synchronized Transcript</span>
                  <span className="text-[11px]">4 dialogue intervals</span>
                </div>

                <div className="text-lg sm:text-xl lg:text-2xl leading-relaxed text-[#bbc7c6] space-y-2">
                  <p>
                    <span
                      className={`inline-block transition-colors rounded px-2 py-1 ${
                        currentTime >= 0.0 && currentTime <= 3.8
                          ? 'bg-[#003734] text-[#ffffff] font-medium'
                          : 'text-[#bbc7c6]'
                      }`}
                    >
                      Perimeter sensors detected breached access at section nine;
                    </span>{' '}
                    <span
                      className={`inline-block transition-colors rounded px-2 py-1 ${
                        currentTime > 3.8 && currentTime < 4.9
                          ? 'bg-[#003734] text-[#ffffff] font-medium'
                          : 'text-[#bbc7c6]'
                      }`}
                    >
                      whatever happens,
                    </span>{' '}
                    <span
                      className={`inline-block transition-colors rounded px-2.5 py-1 ${
                        isInsideDropoutWindow
                          ? 'bg-[#ef4444]/20 border border-[#ef4444]/60 text-[#ff887b] font-medium'
                          : 'border border-dashed border-[#f59e0b]/50 text-[#f59e0b]'
                      }`}
                    >
                      do not cut the feed{' '}
                      <span className="text-xs font-mono text-[#ff887b] font-normal">[critical cue]</span>
                    </span>{' '}
                    <span
                      className={`inline-block transition-colors rounded px-2 py-1 ${
                        currentTime > 6.8 && currentTime <= 12.0
                          ? 'bg-[#003734] text-[#ffffff] font-medium'
                          : 'text-[#bbc7c6]'
                      }`}
                    >
                      until our squad secures point alpha.
                    </span>
                  </p>
                </div>

                {/* Status indicator bar */}
                <div className="mt-4 pt-3 border-t border-[#edfffe]/16 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 text-xs font-mono text-[#bbc7c6]">
                  <div>
                    <span className="text-[#7e9492]">Active Interval: </span>
                    {activePhrase ? (
                      <span className={activePhrase.is_critical ? 'text-[#ff887b] font-medium' : 'text-[#ffffff]'}>
                        {activePhrase.is_critical ? 'VULNERABLE DIALOGUE' : 'NOMINAL RECEPTION'} ({activePhrase.approx_start_seconds}s – {activePhrase.approx_end_seconds}s)
                      </span>
                    ) : (
                      <span>Lead-in / buffer</span>
                    )}
                  </div>

                  {isInsideDropoutWindow && (
                    <div className="text-[#ff887b] font-medium flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#ef4444]" aria-hidden="true" />
                      <span>SIMULATED PHRASE-RISK WINDOW</span>
                    </div>
                  )}
                </div>

                {/* Sound-off Accessibility Notice */}
                <div className="mt-4 p-3 rounded-[6px] bg-[#012624] border border-[#edfffe]/16 text-xs text-[#bbc7c6] leading-relaxed">
                  <strong className="text-[#ffffff] font-medium">Sound-off accessibility note:</strong> The marked visual interval (approximately 00:04.9–00:06.8) highlights the phrase at risk. This illustration does not mute or restore the dialogue audio.
                </div>
              </div>

              {/* SECONDARY: Waveform & Scrubber Bar */}
              <div className="mt-8 pt-6 border-t border-[#edfffe]/16">
                <div className="flex items-center justify-between text-xs font-mono text-[#bbc7c6] mb-2">
                  <span className="text-[#edfffe] font-medium tracking-wider">WAVEFORM & TELEMETRY TIMELINE</span>
                  <span className="text-[#7e9492]">48-column envelope</span>
                </div>

                {/* Waveform Visualization — Flat, No Glow */}
                <div className="relative w-full h-16 bg-[#012624] rounded-[6px] border border-[#edfffe]/16 overflow-hidden flex items-end p-2 gap-[2px]">
                  {Array.from({ length: 48 }).map((_, i) => {
                    const fraction = i / 48
                    const timeAtCol = fraction * 12.0
                    const isDropoutCol = timeAtCol >= 4.9 && timeAtCol <= 6.8
                    const isPassed = timeAtCol <= currentTime

                    const heightPercent = isDropoutCol
                      ? activeChannel === 'boom1'
                        ? 10
                        : 35
                      : Math.max(20, Math.sin(i * 0.4) * 45 + 45)

                    let barBg = '#003734'
                    if (isDropoutCol) {
                      barBg = isPassed ? '#ef4444' : '#ef4444/60'
                    } else if (isPassed) {
                      barBg = '#edfffe'
                    }

                    return (
                      <div
                        key={i}
                        className="flex-1 rounded-t-sm transition-all duration-75"
                        style={{
                          height: `${heightPercent}%`,
                          backgroundColor: barBg,
                        }}
                      />
                    )
                  })}

                  {/* Dropout Boundary Overlay */}
                  <div
                    className="absolute top-0 bottom-0 border-x border-[#ef4444] bg-[#ef4444]/10 pointer-events-none flex items-center justify-center p-1"
                    style={{
                      left: `${(4.9 / 12.0) * 100}%`,
                      width: `${((6.8 - 4.9) / 12.0) * 100}%`,
                    }}
                  >
                    <span className="text-[9px] font-mono text-[#ff887b] font-medium tracking-wider uppercase truncate">
                      DROPOUT (00:04.9–00:06.8)
                    </span>
                  </div>

                  {/* Playhead Needle — Flat, No Shadow */}
                  <div
                    className="absolute top-0 bottom-0 w-0.5 bg-[#ffffff] pointer-events-none z-10 transition-all duration-75"
                    style={{
                      left: `${(currentTime / duration) * 100}%`,
                    }}
                  />
                </div>

                {/* Accessible Scrubber Slider */}
                <div className="mt-3">
                  <label htmlFor="audio-scrubber" className="sr-only">
                    Audio Scrubber Timeline (0 to 12 seconds)
                  </label>
                  <input
                    id="audio-scrubber"
                    type="range"
                    min="0"
                    max={duration}
                    step="0.1"
                    value={currentTime}
                    onChange={handleSliderChange}
                    className="w-full h-2 bg-[#003734] rounded-lg appearance-none cursor-pointer accent-[#edfffe] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#edfffe]"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
