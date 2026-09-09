import React from 'react'

export const StageSceneIllustration: React.FC = () => {
  return (
    <div
      id="stage-scene"
      className="w-full bg-[#011d1c] border border-[#edfffe]/16 rounded-[16px] p-4 sm:p-6 lg:p-7 select-none"
    >
      {/* Instrument Score Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-3 mb-3 border-b border-[#edfffe]/16 text-xs font-mono gap-2">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-[#edfffe]" aria-hidden="true" />
          <span className="text-[#ffffff] font-medium tracking-wider">STAGE 04 · INTERIOR CONTROL ROOM</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="px-2.5 py-0.5 rounded bg-[#012624] border border-[#edfffe]/16 text-[#bbc7c6] font-medium">
            SHOT 4B (12.0s)
          </span>
          <span className="text-[#bbc7c6] text-[11px]">Illustrative signal / synthetic dialogue</span>
        </div>
      </div>

      {/* HTML Critical Dialogue Cue Header Outside SVG — 20px Readable Transcript */}
      <div className="text-center py-2 mb-3">
        <div className="text-lg sm:text-[20px] font-medium text-[#ffffff] tracking-tight leading-snug">
          “whatever happens, do <span className="text-[#ff887b] font-bold underline decoration-[#ef4444]/60 underline-offset-4">NOT</span> cut the feed”
        </div>
        <div className="mt-1 text-xs font-mono text-[#ff887b] tracking-wider uppercase">
          Critical Cue Dropout Window · 00:04.9–00:06.8
        </div>
      </div>

      {/* SVG Receiver Signal Score — Contained Horizontally Scrollable on Mobile with Keyboard Access */}
      <div
        tabIndex={0}
        role="region"
        aria-label="Receiver signal score timeline"
        className="relative w-full bg-[#012624] rounded-[8px] border border-[#edfffe]/16 overflow-x-auto focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#edfffe]"
      >
        <div className="min-w-[700px] sm:min-w-full">
          <svg
            viewBox="0 0 1000 220"
            className="w-full h-auto select-none block"
            role="img"
            aria-label="Illustrative receiver signal score showing rehearsal dropout interval across channels"
          >
            {/* Background Dropout Window Column (00:04.9 – 00:06.8) */}
            <rect
              x="477"
              y="10"
              width="126"
              height="170"
              fill="#ef4444"
              fillOpacity="0.06"
              stroke="#ef4444"
              strokeWidth="0.75"
              strokeDasharray="4,4"
            />

            {/* Subtle Time Grid Ruler Line */}
            <line x1="150" y1="185" x2="950" y2="185" stroke="rgba(237, 255, 254, 0.16)" strokeWidth="1" />

            {/* Time Ruler Ticks and Readable Labels (11px) */}
            {[
              { s: '0.0s', x: 150 },
              { s: '2.0s', x: 283 },
              { s: '4.0s', x: 417 },
              { s: '6.0s', x: 550 },
              { s: '8.0s', x: 683 },
              { s: '10.0s', x: 817 },
              { s: '12.0s', x: 950 },
            ].map((t, idx) => (
              <g key={idx}>
                <line x1={t.x} y1="180" x2={t.x} y2="190" stroke="rgba(237, 255, 254, 0.24)" strokeWidth="1" />
                <text
                  x={t.x}
                  y="204"
                  fill="#7e9492"
                  fontSize="11"
                  fontFamily="monospace"
                  textAnchor="middle"
                >
                  {t.s}
                </text>
              </g>
            ))}

            {/* Receiver 1: Boom 1 (Ch 01) — Deliberate Missing Segment */}
            <g>
              {/* Desktop Readable Label (13.5px), Right-aligned at x=140 with Left Margin 150px */}
              <text
                x="140"
                y="54"
                fill="#edfffe"
                fontSize="13.5"
                fontFamily="monospace"
                textAnchor="end"
                fontWeight="500"
              >
                CH 01 · BOOM
              </text>
              {/* Segment before dropout (0.0s – 4.9s) */}
              <path
                d="M 150 50 Q 210 42, 270 50 T 350 50 T 420 44 T 477 50"
                fill="none"
                stroke="#edfffe"
                strokeWidth="2"
                strokeLinecap="round"
              />
              {/* THE MISSING SEGMENT (4.9s – 6.8s) — Dashed Red Dropout Trace */}
              <line
                x1="477"
                y1="50"
                x2="603"
                y2="50"
                stroke="#ef4444"
                strokeWidth="1.5"
                strokeDasharray="4,4"
              />
              {/* Missing Segment Tag */}
              <text
                x="540"
                y="40"
                fill="#ff887b"
                fontSize="10"
                fontFamily="monospace"
                fontWeight="500"
                textAnchor="middle"
              >
                [MISSING SEGMENT]
              </text>
              {/* Segment after dropout (6.8s – 12.0s) */}
              <path
                d="M 603 50 Q 660 56, 720 50 T 800 44 T 880 54 T 950 50"
                fill="none"
                stroke="#edfffe"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </g>

            {/* Receiver 2: Lav A (Ch 02) — Continuous Marginal Trace */}
            <g>
              <text
                x="140"
                y="100"
                fill="#bbc7c6"
                fontSize="13.5"
                fontFamily="monospace"
                textAnchor="end"
              >
                CH 02 · LAV
              </text>
              <path
                d="M 150 96 Q 220 102, 290 96 T 430 90 T 540 100 T 603 94 T 720 98 T 840 92 T 950 96"
                fill="none"
                stroke="#bbc7c6"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </g>

            {/* Receiver 3: Plant C (Ch 04) — Continuous Clean Trace */}
            <g>
              <text
                x="140"
                y="146"
                fill="#bbc7c6"
                fontSize="13.5"
                fontFamily="monospace"
                textAnchor="end"
              >
                CH 04 · PLANT
              </text>
              <path
                d="M 150 142 Q 210 136, 270 142 T 390 146 T 510 138 T 603 144 T 730 140 T 850 144 T 950 142"
                fill="none"
                stroke="#4ef2bb"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </g>
          </svg>
        </div>
      </div>

      {/* Qualitative Baseline Fixture Units Strip */}
      <div className="mt-4 pt-3 border-t border-[#edfffe]/16 grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs font-mono">
        <div className="p-2.5 rounded bg-[#012624] border border-[#ef4444]/40 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#ef4444]" />
            <span className="text-[#ffffff] font-medium">Boom 1</span>
          </div>
          <span className="text-[#ff887b] font-medium uppercase tracking-wider">Dropout</span>
        </div>
        <div className="p-2.5 rounded bg-[#012624] border border-[#edfffe]/16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#f59e0b]" />
            <span className="text-[#ffffff] font-medium">Lav A</span>
          </div>
          <span className="text-[#f59e0b] font-medium uppercase tracking-wider">Marginal</span>
        </div>
        <div className="p-2.5 rounded bg-[#012624] border border-[#edfffe]/16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#f59e0b]" />
            <span className="text-[#ffffff] font-medium">Lav B</span>
          </div>
          <span className="text-[#f59e0b] font-medium uppercase tracking-wider">Marginal</span>
        </div>
        <div className="p-2.5 rounded bg-[#012624] border border-[#edfffe]/16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#4ef2bb]" />
            <span className="text-[#ffffff] font-medium">Plant C</span>
          </div>
          <span className="text-[#4ef2bb] font-medium uppercase tracking-wider">Clear</span>
        </div>
      </div>
    </div>
  )
}
