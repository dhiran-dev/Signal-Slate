import React from 'react'

export const LandingStepStrip: React.FC = () => {
  return (
    <section className="landing-strip-section" id="how-it-works" aria-label="Sample rehearsal sequence">
      <div className="landing-strip-inner">
        <h2 className="landing-strip-title">
          Choose a scene. Check the sound. Review the result.
        </h2>

        <div className="landing-steps-row">
          <div className="landing-steps-connector-line" aria-hidden="true" />

          {/* Step 1: Choose a scene */}
          <div className="landing-step-col">
            <div className="landing-step-header">
              <span className="landing-step-number">1</span>
              <div className="landing-step-graphic landing-step-graphic-scene">
                <img
                  src="/images/alleyway-scene.png"
                  alt="Alleyway scene showing street, buildings, and clapperboard"
                  className="landing-step-image"
                  style={{ width: 220, height: 112, objectFit: 'cover', borderRadius: 6 }}
                />
              </div>
            </div>
            <p className="landing-step-label">Choose a scene</p>
            <p className="landing-step-desc">Click Check sound to find gaps in the sample dialogue.</p>
          </div>

          {/* Step 2: Check the sound */}
          <div className="landing-step-col">
            <div className="landing-step-header">
              <span className="landing-step-number">2</span>
              <div className="landing-step-graphic landing-step-graphic-wave">
                <svg viewBox="0 0 300 90" width="300" height="90" fill="none" className="landing-thumbnail-svg" aria-hidden="true">
                  <g transform="translate(15, 45)">
                    {[
                      4, 7, 12, 16, 22, 14, 18, 24, 16, 10,
                      8, 14, 18, 12, 6, 4, 3, 2, 2, 3,
                      5, 8, 14, 20, 26, 22, 18, 24, 18, 12,
                      8, 14, 20, 24, 18, 10, 6, 4, 8, 16,
                      22, 26, 20, 14, 8, 4
                    ].map((h, i) => (
                      <line
                        key={i}
                        x1={i * 5.8}
                        y1={-h / 2}
                        x2={i * 5.8}
                        y2={h / 2}
                        stroke="#1c2024"
                        strokeWidth="2.4"
                        strokeLinecap="round"
                      />
                    ))}
                    {/* Missing dashed highlight */}
                    <rect
                      x="98"
                      y="-26"
                      width="66"
                      height="52"
                      fill="#eddcd0"
                      fillOpacity="0.75"
                      stroke="#c24b27"
                      strokeWidth="1.6"
                      strokeDasharray="4 3"
                      rx="3"
                    />
                  </g>
                </svg>
              </div>
            </div>
            <p className="landing-step-label">Check the sound</p>
            <p className="landing-step-desc">Gemini reviews microphone readings. You confirm your rules and approve a change.</p>
          </div>

          {/* Step 3: Review the result */}
          <div className="landing-step-col">
            <div className="landing-step-header">
              <span className="landing-step-number">3</span>
              <div className="landing-step-graphic landing-step-graphic-report">
                <svg viewBox="0 0 130 120" width="130" height="120" fill="none" className="landing-thumbnail-svg" aria-hidden="true">
                  {/* Paper sheet */}
                  <rect x="15" y="10" width="90" height="96" rx="4" fill="#ffffff" stroke="#c8c4bc" strokeWidth="1.5" />
                  <path d="M 80,10 L 105,35 L 80,35 Z" fill="#dfdad2" />
                  {/* Document lines */}
                  <line x1="30" y1="28" x2="72" y2="28" stroke="#24282e" strokeWidth="2.5" strokeLinecap="round" />
                  <line x1="30" y1="40" x2="65" y2="40" stroke="#8c949e" strokeWidth="1.8" strokeLinecap="round" />
                  {/* Mini waveform */}
                  <g transform="translate(30, 62)">
                    {[4, 8, 14, 10, 16, 12, 8, 14, 16, 10, 6, 12, 14, 8].map((h, i) => (
                      <line key={i} x1={i * 4.2} y1={-h / 2} x2={i * 4.2} y2={h / 2} stroke="#7b848e" strokeWidth="2" />
                    ))}
                  </g>
                  {/* Circle check badge */}
                  <circle cx="86" cy="88" r="16" fill="#b84729" />
                  <polyline points="80,88 85,93 93,83" stroke="#ffffff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
            </div>
            <p className="landing-step-label">Review the result</p>
            <p className="landing-step-desc">Run another check. The app compares fresh readings stored in Grafana.</p>
          </div>
        </div>

        <p className="landing-strip-footer-note">
          In a live check, Gemini reviews the readings and Grafana stores the evidence. Audio and microphone readings are simulated.
        </p>
      </div>
    </section>
  )
}
