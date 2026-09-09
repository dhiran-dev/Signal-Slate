import React, { useState } from 'react'

export const smoothScrollTo = (id: string) => {
  const element = document.getElementById(id)
  if (!element) return
  const prefersReduced =
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  element.scrollIntoView({ behavior: prefersReduced ? 'auto' : 'smooth' })
}

export const Navbar: React.FC = () => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  const handleNavClick = (id: string) => {
    setMobileMenuOpen(false)
    smoothScrollTo(id)
  }

  const navigateToRehearsal = () => {
    window.location.href = '/rehearsal'
  }

  return (
    <header className="sticky top-0 z-50 bg-[#012624] border-b border-[#edfffe]/16">
      <div className="max-w-[1440px] mx-auto px-5 sm:px-8 lg:px-16 h-20 flex items-center justify-between">
        {/* Single-line Signal Slate Wordmark — Left */}
        <div className="flex items-center gap-2.5 shrink-0 whitespace-nowrap">
          <div className="w-6 h-6 rounded-[4px] bg-[#003734] border border-[#edfffe]/16 flex items-center justify-center text-[#edfffe] shrink-0" aria-hidden="true">
            <svg
              className="w-3.5 h-3.5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M2 10v4" />
              <path d="M6 6v12" />
              <path d="M10 3v18" />
              <path d="M14 8v8" />
              <path d="M18 5v14" />
              <path d="M22 10v4" />
            </svg>
          </div>
          <span className="font-medium tracking-tight text-base sm:text-lg text-[#ffffff] whitespace-nowrap">
            Signal Slate
          </span>
        </div>

        {/* Centered Restrained 12px Uppercase Links — Desktop */}
        <nav className="hidden md:flex items-center gap-8" aria-label="Main Navigation">
          <button
            type="button"
            onClick={() => handleNavClick('stage-scene')}
            className="text-[12px] uppercase tracking-[0.12em] font-normal text-[#bbc7c6] hover:text-[#ffffff] transition-colors cursor-pointer py-2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#edfffe] rounded"
          >
            The rehearsal
          </button>
          <button
            type="button"
            onClick={() => handleNavClick('how-it-works')}
            className="text-[12px] uppercase tracking-[0.12em] font-normal text-[#bbc7c6] hover:text-[#ffffff] transition-colors cursor-pointer py-2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#edfffe] rounded"
          >
            How it works
          </button>
          <button
            type="button"
            onClick={() => handleNavClick('evidence')}
            className="text-[12px] uppercase tracking-[0.12em] font-normal text-[#bbc7c6] hover:text-[#ffffff] transition-colors cursor-pointer py-2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#edfffe] rounded"
          >
            Evidence
          </button>
        </nav>

        {/* Compact Solid 'Open workspace ↗' Right */}
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={navigateToRehearsal}
            className="hidden sm:inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded-[6px] text-[#011d1c] bg-[#edfffe] border border-[#edfffe] hover:bg-[#ffffff] transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#edfffe]"
          >
            <span>Open workspace</span>
            <span aria-hidden="true">↗</span>
          </button>

          {/* Mobile Menu Button — Accessible min-44px target */}
          <button
            type="button"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="md:hidden min-h-[44px] min-w-[44px] flex items-center justify-center p-2 rounded-[6px] border border-[#edfffe]/16 text-[#bbc7c6] hover:text-[#ffffff] hover:bg-[#011d1c] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#edfffe]"
            aria-label={mobileMenuOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={mobileMenuOpen}
          >
            <svg
              className="w-5 h-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              {mobileMenuOpen ? (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
              ) : (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6h16M4 12h16M4 18h16" />
              )}
            </svg>
          </button>
        </div>
      </div>

      {/* Accessible Mobile Menu Dropdown */}
      {mobileMenuOpen && (
        <div className="md:hidden bg-[#011d1c] border-b border-[#edfffe]/16 px-5 py-4 space-y-2">
          <button
            type="button"
            onClick={() => handleNavClick('stage-scene')}
            className="w-full text-left py-2.5 px-3 rounded-[6px] text-xs uppercase tracking-[0.12em] text-[#bbc7c6] hover:text-[#ffffff] hover:bg-[#003734] transition-colors"
          >
            The rehearsal
          </button>
          <button
            type="button"
            onClick={() => handleNavClick('audio-replay')}
            className="w-full text-left py-2.5 px-3 rounded-[6px] text-xs uppercase tracking-[0.12em] text-[#bbc7c6] hover:text-[#ffffff] hover:bg-[#003734] transition-colors"
          >
            Scene
          </button>
          <button
            type="button"
            onClick={() => handleNavClick('how-it-works')}
            className="w-full text-left py-2.5 px-3 rounded-[6px] text-xs uppercase tracking-[0.12em] text-[#bbc7c6] hover:text-[#ffffff] hover:bg-[#003734] transition-colors"
          >
            How it works
          </button>
          <button
            type="button"
            onClick={() => handleNavClick('evidence')}
            className="w-full text-left py-2.5 px-3 rounded-[6px] text-xs uppercase tracking-[0.12em] text-[#bbc7c6] hover:text-[#ffffff] hover:bg-[#003734] transition-colors"
          >
            Evidence
          </button>
          <button
            type="button"
            onClick={() => {
              setMobileMenuOpen(false)
              navigateToRehearsal()
            }}
            className="w-full text-left py-2.5 px-3 rounded-[6px] text-xs uppercase tracking-[0.12em] text-[#edfffe] font-medium bg-[#003734] transition-colors"
          >
            Open workspace ↗
          </button>
        </div>
      )}
    </header>
  )
}
