import React from 'react'
import { smoothScrollTo } from './Navbar'

export const Footer: React.FC = () => {
  return (
    <footer className="py-12 bg-[#011d1c] border-t border-[#edfffe]/16 text-xs text-[#bbc7c6]">
      <div className="max-w-[1440px] mx-auto px-5 sm:px-8 lg:px-16">
        <div className="flex flex-col md:flex-row items-center justify-between gap-6 pb-8 border-b border-[#edfffe]/16">
          {/* Single-line Signal Slate Wordmark & Positioning */}
          <div className="flex flex-col sm:flex-row items-center gap-3 text-center sm:text-left">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-[#edfffe]" aria-hidden="true" />
              <span className="font-medium text-[#ffffff] text-sm tracking-tight">Signal Slate</span>
            </div>
            <span className="hidden sm:inline text-[#7e9492]">|</span>
            <span className="text-[#bbc7c6] font-normal">Keep the performance. Rehearse the sound plan.</span>
          </div>

          {/* Navigation Links */}
          <nav className="flex flex-wrap items-center justify-center gap-6 text-xs" aria-label="Footer Navigation">
            <button
              type="button"
              onClick={() => smoothScrollTo('stage-scene')}
              className="hover:text-[#ffffff] transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#edfffe] rounded py-1"
            >
              Scene
            </button>
            <button
              type="button"
              onClick={() => smoothScrollTo('audio-replay')}
              className="hover:text-[#ffffff] transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#edfffe] rounded py-1"
            >
              Preview
            </button>
            <button
              type="button"
              onClick={() => smoothScrollTo('how-it-works')}
              className="hover:text-[#ffffff] transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#edfffe] rounded py-1"
            >
              How It Works
            </button>
            <button
              type="button"
              onClick={() => smoothScrollTo('evidence')}
              className="hover:text-[#ffffff] transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#edfffe] rounded py-1"
            >
              Evidence
            </button>
            <a
              href="/rehearsal"
              className="text-[#edfffe] hover:underline transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#edfffe] rounded py-1 font-medium"
            >
              Launch Rehearsal →
            </a>
          </nav>
        </div>

        {/* Bottom Disclaimer & Simulation Boundary */}
        <div className="pt-6 flex flex-col sm:flex-row items-center justify-between gap-3 text-center sm:text-left text-[11px] font-mono text-[#7e9492]">
          <p>
            Cinema production sound rehearsal sandbox.
          </p>
          <p>
            Simulated receivers · Synthetic dialogue · No hardware control or audio restoration.
          </p>
        </div>
      </div>
    </footer>
  )
}
