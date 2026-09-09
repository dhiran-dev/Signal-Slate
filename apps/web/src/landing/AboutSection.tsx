import React from 'react'

export const AboutSection: React.FC = () => {
  return (
    <section id="evidence" className="py-16 sm:py-20 lg:py-24 border-b border-[#edfffe]/16 bg-[#012624]">
      <div className="max-w-[1440px] mx-auto px-5 sm:px-8 lg:px-16">
        {/* Asymmetric Editorial Evidence Section: Heading Left, Ruled Paragraphs Right */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 lg:gap-16 items-start">
          {/* Left Column (~42% / col-span-5): Section Eyebrow, Heading, and Quiet Metadata */}
          <div className="lg:col-span-5 flex flex-col justify-start">
            <div className="text-[12px] uppercase tracking-[0.12em] font-normal text-[#bbc7c6] mb-3">
              EVIDENCE &amp; VERIFICATION
            </div>
            <h2 className="text-3xl sm:text-4xl lg:text-[48px] font-medium tracking-[-0.04em] text-[#ffffff] leading-[1.05] mb-5">
              A recommendation needs evidence.
            </h2>
            <p className="text-base text-[#bbc7c6] leading-[1.4] mb-8 max-w-md font-normal">
              Production sound rehearsal recommendations require independent verification before rolling cameras, not assumed outcomes.
            </p>

            {/* Single Quiet Metadata Line (12s synthetic take / 4 simulated receivers) */}
            <div className="pt-4 border-t border-[#edfffe]/16 text-xs font-mono text-[#bbc7c6] flex items-center gap-3">
              <span className="text-[#ffffff]">12s synthetic scene take</span>
              <span className="text-[#edfffe]/30" aria-hidden="true">·</span>
              <span className="text-[#ffffff]">4 simulated receivers</span>
            </div>
          </div>

          {/* Right Column (~58% / col-span-7): Two Concise Ruled Paragraphs, Truthful Disclosure, and Simple Inline CTA */}
          <div className="lg:col-span-7 flex flex-col justify-start border-t lg:border-t-0 border-[#edfffe]/16 pt-8 lg:pt-0">
            {/* Paragraph 1: Gemini recommendations */}
            <div className="pb-6 border-b border-[#edfffe]/16">
              <div className="text-xs font-mono text-[#edfffe] uppercase tracking-wider mb-2 font-medium">
                Gemini Operational Reasoning
              </div>
              <p className="text-sm sm:text-base text-[#bbc7c6] leading-[1.4]">
                Gemini investigates simulated receiver telemetry and interprets operator constraints through Google ADK. Gemini proposes feasible fixes; it never self-approves or verifies outcomes.
              </p>
            </div>

            {/* Paragraph 2: Deterministic Grafana evidence checks */}
            <div className="py-6 border-b border-[#edfffe]/16">
              <div className="text-xs font-mono text-[#edfffe] uppercase tracking-wider mb-2 font-medium">
                Deterministic Grafana Evidence Checks
              </div>
              <p className="text-sm sm:text-base text-[#bbc7c6] leading-[1.4]">
                Fresh simulated rehearsal telemetry streams to Grafana Cloud. An independent deterministic verifier evaluates evidence completeness, freshness, and constraints before sign-off.
              </p>
            </div>

            {/* Truthful Demo Disclosure */}
            <div className="py-5 text-xs font-mono text-[#7e9492] leading-relaxed">
              Signal Slate is an operational workflow sandbox for cinema production sound. Dialogue and receiver metrics are synthetic and simulated; no physical RF hardware or camera rigs are modified.
            </div>

            {/* Simple Inline CTA */}
            <div className="pt-3 flex items-center justify-start">
              <button
                type="button"
                onClick={() => { window.location.href = '/rehearsal' }}
                className="landing-cta-mist min-h-[44px] px-6 py-3 rounded-[6px] font-medium text-sm text-[#011d1c] bg-[#edfffe] border border-[#edfffe] hover:bg-[#ffffff] transition-colors cursor-pointer flex items-center justify-center gap-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#edfffe]"
              >
                <span>Rehearse the next decision</span>
                <span aria-hidden="true">↗</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
