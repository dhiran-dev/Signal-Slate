import React from 'react'
import { LandingNavbar } from './LandingNavbar'
import { LandingHero } from './LandingHero'
import { LandingStepStrip } from './LandingStepStrip'

export const LandingPage: React.FC = () => {
  return (
    <div className="landing-page-root">
      <LandingNavbar />
      <main id="main-content">
        <LandingHero />
        <div id="how-it-works">
          <LandingStepStrip />
        </div>
      </main>
    </div>
  )
}

export default LandingPage
