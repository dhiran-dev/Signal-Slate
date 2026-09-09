import React from 'react'
import { SlateIcon } from '../rehearsal/icons'

export const LandingNavbar: React.FC = () => {
  const scrollToHowItWorks = (e: React.MouseEvent) => {
    e.preventDefault()
    const el = document.getElementById('how-it-works')
    if (el) {
      const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      el.scrollIntoView({ behavior: prefersReducedMotion ? 'auto' : 'smooth' })
    }
  }

  return (
    <header className="landing-navbar">
      <div className="landing-navbar-inner">
        <a href="/" className="landing-brand" aria-label="Signal Slate home">
          <SlateIcon size={40} />
          <span>Signal Slate</span>
        </a>

        <nav className="landing-nav-links" aria-label="Main navigation">
          <a href="#how-it-works" onClick={scrollToHowItWorks} className="landing-nav-link">
            How it works
          </a>
          <a href="/rehearsal" className="landing-nav-link font-medium">
            Sound check
          </a>
        </nav>

      </div>
    </header>
  )
}
