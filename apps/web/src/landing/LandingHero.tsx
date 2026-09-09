import React from 'react'
import { ArrowRightIcon } from '../rehearsal/icons'

export const LandingHero: React.FC = () => {
  const scrollToHowItWorks = (e: React.MouseEvent) => {
    e.preventDefault()
    const el = document.getElementById('how-it-works')
    if (el) {
      const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      el.scrollIntoView({ behavior: prefersReducedMotion ? 'auto' : 'smooth' })
    }
  }

  return (
    <section className="landing-hero-section">
      <div className="landing-hero-inner">
        {/* Left Column: Headline, subhead, CTA */}
        <div className="landing-hero-content">
          <h1 className="landing-hero-headline">
            Check the sound<br />
            before the next take.
          </h1>

          <p className="landing-hero-subhead">
            A sound-check assistant for film crews. Find lost dialogue, approve a microphone-setting change, and test whether it helps.
          </p>

          <div className="landing-hero-actions">
            <a href="/rehearsal" className="landing-primary-cta">
              <span>Start a sound check</span>
              <ArrowRightIcon size={18} />
            </a>

            <a href="#how-it-works" onClick={scrollToHowItWorks} className="landing-secondary-link">
              See how it works
            </a>
          </div>

          <p className="landing-hero-footnote">
            Sample scene · Simulated microphone readings
          </p>
        </div>

        {/* Right Column: Full Hero Artwork bleeding to right edge */}
        <div className="landing-hero-media">
          <img
            src="/images/sound-desk.png"
            alt="Cinema sound desk with mixer, clapperboard, boom mic, and waveform monitor"
            className="landing-hero-artwork-img"
          />
        </div>
      </div>
    </section>
  )
}
