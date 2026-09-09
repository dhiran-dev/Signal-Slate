import React from 'react'
import { StageSceneIllustration } from './StageSceneIllustration'
import { smoothScrollTo } from './Navbar'

interface HeroSectionProps {
  isPlaying: boolean
  onTogglePlay: () => void
}

export const HeroSection: React.FC<HeroSectionProps> = ({ isPlaying, onTogglePlay }) => {
  return (
    <section className="relative overflow-hidden pt-8 pb-12 sm:pt-10 sm:pb-14 lg:pt-10 lg:pb-14 border-b border-[#edfffe]/16 bg-[#012624]">
      <div className="max-w-[1440px] mx-auto px-5 sm:px-8 lg:px-16">
        {/* Full-Width Centered Editorial Text Stack — Widened to 1120px */}
        <div className="flex flex-col items-center text-center max-w-[1120px] mx-auto">
          {/* Eyebrow: 12px uppercase tracking 0.12em */}
          <div className="mb-3 text-[12px] uppercase tracking-[0.12em] font-normal text-[#bbc7c6]">
            PRODUCTION SOUND / REHEARSAL WORKSPACE
          </div>

          {/* Two-Line White Title: 86px Desktop / 54px Tablet / 38px Mobile, Weight 500, Tracking -0.04em */}
          <h1 className="text-[38px] sm:text-[54px] lg:text-[86px] font-medium tracking-[-0.04em] text-[#ffffff] leading-[1.05] lg:leading-[1.0] [text-wrap:balance]">
            <span className="block">Keep the performance.</span>
            <span className="block text-[#ffffff]">Rehearse the sound plan.</span>
          </h1>

          {/* Single Restrained 20px Subline — Legacy duplicates removed */}
          <p className="mt-4 text-base sm:text-lg lg:text-[20px] text-[#bbc7c6] leading-[1.4] max-w-xl font-normal">
            Explore a sound correction before the next take.
          </p>

          {/* Honest Readable Simulation Disclosure */}
          <div className="mt-4 inline-flex items-center gap-2 px-3 py-1 rounded-[6px] bg-[#011d1c] border border-[#edfffe]/16 text-xs font-mono text-[#bbc7c6]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#edfffe]" aria-hidden="true" />
            <span>Illustrative preview · simulated receivers · Google-generated dialogue</span>
          </div>

          {/* Action CTAs: Solid Mist CTA + Play Toggle + Secondary Anchor */}
          <div className="mt-6 flex flex-wrap items-center justify-center gap-4">
            <button
              type="button"
              onClick={() => { window.location.href = '/rehearsal' }}
              className="landing-cta-mist min-h-[44px] px-6 py-3 rounded-[6px] font-medium text-sm text-[#011d1c] bg-[#edfffe] border border-[#edfffe] hover:bg-[#ffffff] transition-colors cursor-pointer flex items-center justify-center gap-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#edfffe]"
            >
              <span>Open rehearsal</span>
              <span aria-hidden="true">↗</span>
            </button>

            <button
              type="button"
              onClick={onTogglePlay}
              aria-label={isPlaying ? 'Pause dialogue line' : 'Play dialogue line'}
              aria-pressed={isPlaying}
              className="min-h-[44px] px-5 py-3 rounded-[6px] font-medium text-sm text-[#edfffe] bg-[#003734] border border-[#edfffe]/16 hover:bg-[#004844] hover:border-[#edfffe]/32 transition-colors cursor-pointer flex items-center justify-center gap-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#edfffe]"
            >
              {isPlaying ? (
                <>
                  <svg className="w-4 h-4 text-[#edfffe]" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
                  </svg>
                  <span>Pause Audio</span>
                </>
              ) : (
                <>
                  <svg className="w-4 h-4 text-[#edfffe]" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M8 5v14l11-7z" />
                  </svg>
                  <span>Play Dialogue (12s)</span>
                </>
              )}
            </button>

            <button
              type="button"
              onClick={() => smoothScrollTo('stage-scene')}
              className="min-h-[44px] px-4 py-3 rounded-[6px] font-normal text-sm text-[#bbc7c6] hover:text-[#ffffff] transition-colors cursor-pointer flex items-center justify-center gap-1.5 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#edfffe]"
            >
              <span>Explore the scene</span>
              <span aria-hidden="true">↓</span>
            </button>
          </div>
        </div>

        {/* Signature Wide Sound Composition Beneath Hero Stack (~1000px Desktop) */}
        <div className="mt-8 lg:mt-10 max-w-[1000px] mx-auto w-full">
          <StageSceneIllustration />
        </div>
      </div>
    </section>
  )
}
