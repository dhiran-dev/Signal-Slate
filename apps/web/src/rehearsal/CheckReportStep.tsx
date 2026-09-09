import React, { useEffect, useState } from 'react'
import type { Session } from './types'
import { downloadReport } from './report'
import { microphoneEvidence } from './evidence'
import {
  CheckCircleIcon,
  CrossIcon,
  DownloadIcon,
  RestartIcon,
  FileReportIcon,
  ExternalLinkIcon,
  ChevronRightIcon,
  BarChartIcon
} from './icons'
import { WaveformTrack } from './WaveformTrack'
import { PCM_PEAKS_240 } from './waveformPeaks'
import { Citations } from './Citations'


export interface CheckReportStepProps {
  session: Session | null
  busy: string
  onStartAnotherCheck: () => void
  onReturnToScene?: () => void
}

export const CheckReportStep: React.FC<CheckReportStepProps> = ({
  session,
  busy,
  onStartAnotherCheck,
  onReturnToScene
}) => {
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false)
  const [grafanaLinks, setGrafanaLinks] = useState<{ label: string; url: string }[]>([])

  const verification = session?.verification
  const isPreview = session?.mode === 'preview'
  const isVerified = verification?.terminal_status === 'VERIFIED'
  const isFailed = verification?.terminal_status === 'NOT_VERIFIED'
  const isNoRisk = session?.state === 'NO_RISK'

  // Fetch Grafana explore links if live session
  useEffect(() => {
    if (session?.mode === 'live' && session?.id) {
      let cancelled = false
      fetch(`/api/sessions/${encodeURIComponent(session.id)}/evidence-links`, {
        credentials: 'same-origin',
        signal: AbortSignal.timeout(4000)
      })
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          if (!cancelled && data?.links) {
            setGrafanaLinks(data.links)
          }
        })
        .catch(() => {
          /* Fallback gracefully */
        })
      return () => {
        cancelled = true
      }
    }
  }, [session?.id, session?.mode])

  // Boolean verification checks (strictly based on actual booleans or healthy NO_RISK)
  const completenessPassed = isNoRisk || (verification?.completeness_passed ?? false)
  const crosscheckPassed = isNoRisk || (verification?.crosscheck_passed ?? false)
  const thresholdsPassed = isNoRisk || (verification?.thresholds_passed ?? false)
  const coveragePassed = isNoRisk || (verification?.dialogue_coverage_passed ?? false)
  const constraintsPassed = isNoRisk || (verification?.constraints_passed ?? false)

  const checkList = [
    {
      key: 'completeness',
      title: completenessPassed ? 'All readings received' : 'Incomplete readings',
      desc: completenessPassed
        ? 'All 4 microphones reported data for the full 12 seconds.'
        : 'Readings were incomplete or missing for one or more microphones.',
      passed: completenessPassed
    },
    {
      key: 'crosscheck',
      title: crosscheckPassed ? 'Two sources agree' : 'Sources unverified',
      desc: crosscheckPassed
        ? 'Logs and metrics'
        : 'Independent metrics did not verify across logs.',
      passed: crosscheckPassed,
      hasDetails: true
    },
    {
      key: 'thresholds',
      title: thresholdsPassed ? 'Microphone levels within limits' : 'Thresholds exceeded',
      desc: thresholdsPassed
        ? 'All active microphones stayed within the expected range.'
        : 'Signal dropout or clipping exceeded receiver thresholds.',
      passed: thresholdsPassed
    },
    {
      key: 'coverage',
      title: coveragePassed ? 'Dialogue covered' : 'Dialogue gap detected',
      desc: coveragePassed
        ? 'Dialogue detected across the scene.'
        : 'Critical dialogue line was interrupted or lost.',
      passed: coveragePassed
    }
  ]

  // Dynamic constraint checks
  const confirmedConstraints = session?.confirmed_constraints || []
  if (confirmedConstraints.length > 0) {
    confirmedConstraints.forEach((c, idx) => {
      const label = c.exact_source_span || c.source_text || 'Confirmed restriction'
      checkList.push({
        key: `constraints_${idx}`,
        title: constraintsPassed ? `${label} held` : `${label} violated`,
        desc: constraintsPassed
          ? 'Confirmed restriction was respected throughout the take.'
          : 'Tested configuration violated the confirmed constraint.',
        passed: constraintsPassed
      })
    })
  } else if (!isNoRisk) {
    checkList.push({
      key: 'constraints',
      title: 'Creative constraints',
      desc: 'No constraints specified for this rehearsal.',
      passed: constraintsPassed
    })
  }

  if (!isNoRisk && !isVerified && !isFailed) {
    const pendingTitles: Record<string, string> = {
      completeness: 'Reading coverage unverified',
      crosscheck: 'Independent sources unverified',
      thresholds: 'Microphone sound unverified',
      coverage: 'Dialogue coverage unverified'
    }
    for (const check of checkList) {
      if (check.passed) continue
      check.title = pendingTitles[check.key] || 'Confirmed restriction unverified'
      check.desc = isPreview
        ? 'Cloud verification does not run in preview mode.'
        : 'This check could not be completed. See the verification details.'
    }
  }

  const passedCount = checkList.filter((c) => c.passed).length

  const performerNames = session?.shot_context?.performer_names || { mic_1: 'Elena' }
  const micName = performerNames.mic_1 || 'Elena'

  // Determine actual exploration / readings link
  const liveGrafanaUrl = grafanaLinks.find((l) => l.label === 'After')?.url || grafanaLinks[0]?.url
  const localEvidenceUrl =
    session?.id && (session.comparison?.run_id || session.baseline?.run_id)
      ? `/api/sessions/${encodeURIComponent(session.id)}/evidence/${encodeURIComponent(
          session.comparison?.run_id || session.baseline?.run_id || 'run'
        )}`
      : null

  // If report has no verification and no session
  if (!session || (!verification && !isNoRisk)) {
    return (
      <div className="check-report-step-view">
        <div className="step-heading-group">
          <h1 className="step-main-title">Check report</h1>
          <p className="step-subtitle">No completed verification yet</p>
        </div>
        <div className="step-main-card text-center py-12">
          <p className="text-gray-600 mb-6">
            There is no completed sound check to report. Start a sound check to observe readings.
          </p>
          <button
            type="button"
            onClick={onReturnToScene || onStartAnotherCheck}
            className="btn-terracotta-primary"
          >
            Start a sound check
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="check-report-step-view">
      {/* Page Title & Status */}
      <div className="step-heading-group flex items-baseline justify-between flex-wrap gap-3">
        <div className="flex items-baseline gap-3 flex-wrap">
          <h1 className="step-main-title">Check report</h1>
          <span
            className={`step-report-status-badge ${
              isPreview || (!isVerified && !isFailed) ? 'text-gray-700' : isVerified ? 'text-green-700' : 'text-red-700'
            }`}
          >
            {isNoRisk
              ? 'No issues found · All checks normal'
              : isPreview
              ? 'Inconclusive (preview only)'
              : isVerified
              ? `${passedCount} of ${checkList.length} checks passed`
              : isFailed
              ? 'The proposed fix did not pass'
              : 'Inconclusive'}
          </span>
        </div>
        <p className="step-subtitle w-full">
          {isPreview
            ? 'This is a local walkthrough. It cannot establish a live cloud result.'
            : isNoRisk
            ? 'All receiver checks passed. No correction was required.'
            : 'Review the checks, then download a copy for this rehearsal.'}
        </p>
      </div>

      {/* 2-Column Layout */}
      <div className="step-two-columns">
        {/* Left Column: Verification Check Rows + Mini Waveforms */}
        <div className="step-main-card report-left-card">
          {/* Header Row: Scene Info */}
          <div className="report-scene-header-row flex items-end justify-between mb-4">
            <div>
              <span className="report-scene-tag-label text-xs text-gray-500 uppercase font-semibold">
                Scene
              </span>
              <h2 className="report-scene-title text-xl font-bold text-gray-900">
                Alleyway dialogue
              </h2>
            </div>
            <span className="report-scene-meta text-sm text-gray-500">12 seconds · 4 microphones</span>
          </div>

          <div className="card-divider" />

          {/* Verification Check Rows */}
          <div className="report-checks-list" role="region" aria-label="Verification checks">
            {checkList.map((chk, idx) => (
              <React.Fragment key={chk.key}>
                {idx > 0 && <div className="report-check-divider my-2" />}
                <div className="report-check-row flex items-center gap-3 py-2">
                  <div className="check-icon-col">
                    {chk.passed ? (
                      <CheckCircleIcon size={22} filled={true} />
                    ) : (
                      <span className="check-fail-circle inline-flex items-center justify-center w-5 h-5 rounded-full bg-red-600 text-white">
                        <CrossIcon size={12} />
                      </span>
                    )}
                  </div>
                  <div className="check-details-col flex-1">
                    <span className="check-title font-semibold text-gray-900">{chk.title}</span>
                    <p className="check-desc text-xs text-gray-600">{chk.desc}</p>
                  </div>
                  {chk.hasDetails && (
                    <button
                      type="button"
                      onClick={() => setShowTechnicalDetails(true)}
                      className="btn-view-details-link inline-flex items-center gap-1 text-xs font-semibold text-gray-700 hover:text-gray-900"
                    >
                      <FileReportIcon size={14} />
                      <span>View details</span>
                      <ChevronRightIcon size={12} />
                    </button>
                  )}
                </div>
              </React.Fragment>
            ))}
          </div>

          {/* Inspectable Failure Reasons */}
          {verification?.failure_reasons && verification.failure_reasons.length > 0 && (
            <div className="report-failure-reasons-box p-3 my-3 bg-red-50 border border-red-200 rounded-md text-xs text-red-900">
              <strong className="font-semibold block mb-1">Observed failure reasons:</strong>
              <ul className="list-disc pl-4 space-y-1">
                {verification.failure_reasons.map((reason, i) => (
                  <li key={i}>{reason}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Section: Checked with Grafana / Preview */}
          {(session.baseline || session.comparison) && (
            <>
              <div className="card-divider my-5" />
              <div className="report-grafana-section">
                <div className="grafana-section-header flex items-end justify-between mb-3">
                  <div>
                    <h3 className="grafana-title text-base font-bold text-gray-900">
                      {isPreview ? 'Preview readings' : 'Readings from Grafana'}
                    </h3>
                    <p className="grafana-sub text-xs text-gray-500">
                      {isNoRisk || !session.comparison
                        ? `${micName}'s microphone · Sample readings`
                        : `${micName}'s microphone · Before and after`}
                    </p>
                  </div>

                  {liveGrafanaUrl ? (
                    <a
                      href={liveGrafanaUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="open-grafana-link inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:underline"
                    >
                      <ExternalLinkIcon size={14} />
                      <span>Open in Grafana</span>
                    </a>
                  ) : localEvidenceUrl ? (
                    <a
                      href={localEvidenceUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="open-grafana-link inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:underline"
                    >
                      <ExternalLinkIcon size={14} />
                      <span>{isPreview ? 'View preview evidence' : 'View readings'}</span>
                    </a>
                  ) : null}
                </div>

                {/* Compact plot(s) */}
                <div className={`mini-plots-grid grid grid-cols-1 ${!isNoRisk && session.comparison ? 'sm:grid-cols-2' : ''} gap-4`}>
                  {/* Plot 1: Before / Sample */}
                  {(() => {
                    const beforeEv = microphoneEvidence(session.baseline, 'mic_1', 12000)
                    const beforeTitle = isNoRisk
                      ? 'Sample · All normal'
                      : !beforeEv.complete || beforeEv.unknownMs > 0
                      ? 'Before · Incomplete readings'
                      : beforeEv.clippingMs > 0
                      ? `Before · ${(beforeEv.clippingMs / 1000).toFixed(1)}s clipping`
                      : beforeEv.dropoutMs > 0
                      ? `Before · ${(beforeEv.dropoutMs / 1000).toFixed(1)}s missing`
                      : 'Before · Normal'

                    return (
                      <div className="mini-plot-card bg-gray-50 border border-gray-200 rounded-lg p-3">
                        <span className="mini-plot-title text-xs font-semibold text-gray-900 block mb-2">
                          {beforeTitle}
                        </span>
                        <WaveformTrack
                          peaks={PCM_PEAKS_240}
                          height={34}
                          tint="default"
                          intervals={isNoRisk ? undefined : beforeEv.intervals}
                          showRuler={false}
                          interactive={false}
                          ariaLabel="Before mini waveform"
                        />
                        <div className="mini-plot-ruler flex justify-between text-[10px] text-gray-700 mt-1">
                          <span>0s</span>
                          <span>6s</span>
                          <span>12s</span>
                        </div>
                      </div>
                    )
                  })()}

                  {/* Plot 2: After (Only when an actual comparison take exists) */}
                  {!isNoRisk && session.comparison && (() => {
                    const afterEv = microphoneEvidence(session.comparison, 'mic_1', 12000)
                    const afterTitle = !afterEv.complete || afterEv.unknownMs > 0
                      ? 'After · Incomplete readings'
                      : afterEv.dropoutMs > 0
                      ? `After · ${(afterEv.dropoutMs / 1000).toFixed(1)}s missing`
                      : afterEv.clippingMs > 0
                      ? `After · ${(afterEv.clippingMs / 1000).toFixed(1)}s clipping`
                      : 'After · 0s missing'

                    return (
                      <div className="mini-plot-card bg-gray-50 border border-gray-200 rounded-lg p-3">
                        <span className="mini-plot-title text-xs font-semibold text-gray-900 block mb-2">
                          {afterTitle}
                        </span>
                        <WaveformTrack
                          peaks={PCM_PEAKS_240}
                          height={34}
                          tint="salmon"
                          intervals={afterEv.intervals}
                          showRuler={false}
                          interactive={false}
                          ariaLabel="After mini waveform"
                        />
                        <div className="mini-plot-ruler flex justify-between text-[10px] text-gray-700 mt-1">
                          <span>0s</span>
                          <span>6s</span>
                          <span>12s</span>
                        </div>
                      </div>
                    )
                  })()}
                </div>
              </div>
            </>
          )}
        </div>

        {/* Right Sidebar */}
        <aside className="step-sidebar-card report-sidebar">
          <div className="sidebar-section">
            <h2 className="sidebar-title">About this report</h2>
            <p className="sidebar-text">
              Includes the sample check results and links to the readings.
            </p>

            {/* Pipeline Flow Graphic */}
            <div className="report-pipeline-flow flex items-center justify-between p-3 bg-gray-50 rounded-lg mt-3 text-xs">
              <div className="pipeline-item flex flex-col items-center gap-1">
                <FileReportIcon size={16} className="text-gray-700" />
                <span className="pipeline-label">
                  {isNoRisk ? 'Healthy sample' : isPreview ? 'Preview fix' : 'Gemini suggested'}
                </span>
              </div>
              <span className="pipeline-arrow text-gray-400">›</span>
              <div className="pipeline-item flex flex-col items-center gap-1">
                <CheckCircleIcon size={16} filled={false} className="text-gray-700" />
                <span className="pipeline-label">
                  {isNoRisk || !session.approval ? 'No change' : 'You approved'}
                </span>
              </div>
              <span className="pipeline-arrow text-gray-400">›</span>
              <div className="pipeline-item flex flex-col items-center gap-1">
                <BarChartIcon size={16} className="text-gray-700" />
                <span className="pipeline-label">
                  {isPreview ? 'Preview readings' : 'Grafana checked'}
                </span>
              </div>
            </div>
          </div>


          <div className="card-divider" />

          {/* Technical Details Disclosure */}
          <div className="sidebar-section">
            <details
              className="technical-details-disclosure"
              open={showTechnicalDetails}
              onToggle={(e) => setShowTechnicalDetails(e.currentTarget.open)}
            >
              <summary className="technical-details-summary font-semibold text-gray-900 cursor-pointer text-sm">
                Technical details
              </summary>
              <div className="technical-details-content text-xs text-gray-600 mt-3 space-y-2">
                <p>
                  <strong>Session ID:</strong>{' '}
                  <span className="font-mono break-all">{session.id}</span>
                </p>
                {session.baseline && (
                  <p>
                    <strong>Baseline Run:</strong>{' '}
                    <span className="font-mono">{session.baseline.run_id}</span>
                  </p>
                )}
                {session.comparison && (
                  <p>
                    <strong>Comparison Run:</strong>{' '}
                    <span className="font-mono">{session.comparison.run_id}</span>
                  </p>
                )}
                {session.history && session.history.length > 0 && (
                  <div>
                    <strong>Previous Attempts:</strong>
                    {session.history.map((h, i) => (
                      <div key={i} className="mt-1 p-2 bg-gray-50 border rounded text-[11px]">
                        <span>Attempt {i + 1}: {h.verification?.terminal_status || 'Unverified'}</span>
                      </div>
                    ))}
                  </div>
                )}
                {verification?.evidence_hashes && (
                  <div>
                    <strong>Evidence Hashes:</strong>
                    <pre className="p-2 bg-gray-50 border border-gray-200 rounded mt-1 overflow-x-auto text-[10px]">
                      {JSON.stringify(verification.evidence_hashes, null, 2)}
                    </pre>
                  </div>
                )}
                <Citations session={session} />
              </div>
            </details>
          </div>

          <div className="card-divider" />

          <p className="sidebar-footnote">
            These are simulated readings, never physical receiver proof.
          </p>
        </aside>
      </div>

      {/* Bottom Action Bar */}
      <footer className="step-bottom-action-bar flex items-center justify-between flex-wrap gap-4 mt-6">
        <div className="bottom-action-left items-center flex-wrap gap-3">
          <button
            type="button"
            className="btn-terracotta-primary btn-step-cta inline-flex items-center gap-2"
            onClick={() => void downloadReport(session)}
            disabled={!!busy}
          >
            <DownloadIcon size={18} />
            <span>Download report</span>
          </button>
          <span className="bottom-action-hint text-sm text-gray-600">
            Saves the check results and evidence links.
          </span>

          <button
            type="button"
            onClick={onStartAnotherCheck}
            className="btn-secondary-outline inline-flex items-center gap-2 ml-2"
            disabled={!!busy}
          >
            <RestartIcon size={16} />
            <span>Start another check</span>
          </button>
        </div>

        <div className="bottom-action-right">
          <span className="bottom-action-sample-tag text-xs text-gray-500">
            Sample scene · Simulated microphone readings
          </span>
        </div>
      </footer>
    </div>
  )
}
