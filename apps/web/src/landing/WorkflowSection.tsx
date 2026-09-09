import React from 'react'

export const WorkflowSection: React.FC = () => {
  const steps = [
    {
      number: '01',
      title: 'Observe the rehearsal',
      description:
        'Inspect simulated 4-channel telemetry across the take. Identify the 4.9s–6.8s dropout window silencing critical dialogue before rolling cameras.',
    },
    {
      number: '02',
      title: 'Keep the creative constraint',
      description:
        'Specify operator boundaries like “Keep channel 11 reserved” or protect talent lavaliers so feasible proposals respect production requirements.',
    },
    {
      number: '03',
      title: 'Approve the correction',
      description:
        'Gemini analyzes telemetry to suggest alternative routing and antenna setups. Operators retain full authority and explicitly approve the plan.',
    },
    {
      number: '04',
      title: 'Check the new evidence',
      description:
        'A fresh simulated rehearsal is published to Grafana. The independent deterministic verifier evaluates evidence freshness and constraint satisfaction.',
    },
  ]

  return (
    <section id="how-it-works" className="py-16 sm:py-20 lg:py-24 border-b border-[#edfffe]/16 bg-[#012624]">
      <div className="max-w-[1440px] mx-auto px-5 sm:px-8 lg:px-16">
        {/* Asymmetric 2-Column Editorial Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 lg:gap-16">
          {/* Left Column (~35% / col-span-4): Narrow Large Heading */}
          <div className="lg:col-span-4 flex flex-col justify-start">
            <div className="text-[12px] uppercase tracking-[0.12em] font-normal text-[#bbc7c6] mb-3">
              HOW IT WORKS
            </div>
            <h2 className="text-3xl sm:text-4xl lg:text-[48px] font-medium tracking-[-0.04em] text-[#ffffff] leading-[1.05] mb-5">
              Your constraint. A different plan.
            </h2>
            <p className="text-base text-[#bbc7c6] leading-[1.4] max-w-sm">
              Sound decisions, before action. Rehearse alternative configurations without interrupting camera setups.
            </p>
          </div>

          {/* Right Column (~65% / col-span-8): Spacious Horizontal Rows with Fine Rules */}
          <div className="lg:col-span-8 border-t border-[#edfffe]/16">
            {steps.map((step) => (
              <div
                key={step.number}
                className="py-6 sm:py-8 border-b border-[#edfffe]/16 flex flex-col sm:flex-row sm:items-baseline justify-between gap-3 sm:gap-8 transition-colors hover:bg-[#003734]/15"
              >
                {/* Left side: Number + Heading */}
                <div className="flex items-baseline gap-4 sm:w-1/2 shrink-0">
                  <span className="font-mono text-xs sm:text-sm text-[#7e9492] uppercase tracking-wider shrink-0">
                    {step.number}
                  </span>
                  <h3 className="text-xl sm:text-2xl font-medium text-[#ffffff] tracking-tight">
                    {step.title}
                  </h3>
                </div>

                {/* Right side: Short Description */}
                <div className="sm:w-1/2">
                  <p className="text-sm sm:text-base text-[#bbc7c6] leading-[1.4]">
                    {step.description}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
