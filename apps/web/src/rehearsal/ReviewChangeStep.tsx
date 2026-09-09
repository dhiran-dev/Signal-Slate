import React, { useEffect, useState } from 'react'
import type { Plan, Session } from './types'
import { microphoneEvidence } from './evidence'
import {
  MicIcon,
  BoomMicIcon,
  CheckCircleIcon,
  EditPencilIcon,
  ArrowRightIcon,
  ArrowLeftIcon
} from './icons'
import { WaveformTrack } from './WaveformTrack'
import { PCM_PEAKS_240 } from './waveformPeaks'

export interface ReviewChangeStepProps {
  session: Session | null
  busy: string
  onInterpret: (text: string) => Promise<boolean>
  onConfirm: () => Promise<boolean>
  onTestChange: (plan: Plan) => Promise<void>
  onBackToSound: () => void
}

export const ReviewChangeStep: React.FC<ReviewChangeStepProps> = ({
  session,
  busy,
  onInterpret,
  onConfirm,
  onTestChange,
  onBackToSound
}) => {
  // Format any constraint into human-readable text
  const formatConstraint = (c: { kind?: string; exact_source_span?: string; source_text?: string; parameters?: Record<string, unknown> }) => {
    if (c.exact_source_span) return c.exact_source_span
    if (c.kind === 'CHANNEL_EXCLUSION') return `Exclude channel ${c.parameters?.excluded_channel ?? ''}`
    if (c.kind === 'CHANNEL_LOCK') return `Lock channel ${c.parameters?.locked_channel ?? ''}`
    if (c.kind === 'ANTENNA_PREFERENCE') return `Antenna ${c.parameters?.antenna ?? ''}`
    return c.source_text || 'Confirmed restriction'
  }

  // Derive saved rule text from actual session constraints:
  // When in AWAITING_HUMAN_CONFIRMATION, prefer the new interpretation waiting for confirmation
  const isAwaitingConfirmation = session?.state === 'AWAITING_HUMAN_CONFIRMATION'
  const savedConstraintText = isAwaitingConfirmation
    ? session?.interpretation?.constraints?.[0]?.source_text ||
      session?.interpretation?.constraints?.[0]?.exact_source_span ||
      session?.confirmed_constraints?.[0]?.source_text ||
      ''
    : session?.confirmed_constraints?.[0]?.source_text ||
      session?.interpretation?.constraints?.[0]?.source_text ||
      ''

  const [ruleText, setRuleText] = useState(savedConstraintText || '11')
  const [isEditing, setIsEditing] = useState(!savedConstraintText && !session?.confirmed_constraints?.length)
  const [hasEditedLocally, setHasEditedLocally] = useState(false)
  const [selectedPlanId, setSelectedPlanId] = useState<string>(
    () => session?.approval?.plan_id || ''
  )

  // Sync rule text when session restores
  useEffect(() => {
    if (savedConstraintText && !hasEditedLocally) {
      setRuleText(savedConstraintText)
      setIsEditing(false)
    }
  }, [savedConstraintText, hasEditedLocally])

  // Sync selected plan if approval is present
  useEffect(() => {
    if (session?.approval?.plan_id) {
      setSelectedPlanId(session.approval.plan_id)
    }
  }, [session?.approval?.plan_id])

  const candidatePlans = session?.candidate_plans || []
  const effectivePlanId = selectedPlanId || session?.approval?.plan_id
  const selectedPlan: Plan | null =
    candidatePlans.find((p) => p.plan_id === effectivePlanId) ||
    candidatePlans[0] ||
    null

  const confirmedConstraints = session?.confirmed_constraints || []
  const isConfirmed =
    confirmedConstraints.length > 0 &&
    !hasEditedLocally &&
    (session?.state === 'AWAITING_HUMAN_APPROVAL' || session?.state === 'PLAN_APPROVED')

  // Target mic and its baseline evidence
  const action = selectedPlan?.actions[0] || session?.finding?.recommended_action
  const targetMicId = action?.mic_id || session?.shot_context?.mic_ids?.[0] || 'mic_1'
  const performerNames = session?.shot_context?.performer_names || { mic_1: 'Elena' }
  const micName = performerNames[targetMicId] || targetMicId

  const baselineEvidence = microphoneEvidence(session?.baseline ?? null, targetMicId, 12000)
  const missingDurationS = (baselineEvidence.dropoutMs / 1000).toFixed(1)

  // Current vs proposed settings - no hardcoded 10 or 12 if absent
  const currentChannel = session?.baseline_config?.channel_assignments?.[targetMicId]
  const currentAntenna = session?.baseline_config?.antenna_selection

  let proposedHeadline = `${micName}: change proposal`
  let currentDisplay = currentChannel !== undefined ? String(currentChannel) : '—'
  let proposedDisplay = '—'
  let isAntennaSwitch = false
  let isBoomBackup = false

  if (action) {
    if (action.action_type === 'CHANNEL_SWITCH') {
      proposedDisplay = action.parameters?.channel !== undefined ? String(action.parameters.channel) : '—'
      proposedHeadline = currentChannel !== undefined && proposedDisplay !== '—'
        ? `${micName}: channel ${currentChannel} → ${proposedDisplay}`
        : `${micName}: change channel`
    } else if (action.action_type === 'ANTENNA_SWITCH') {
      isAntennaSwitch = true
      currentDisplay = currentAntenna || 'A'
      proposedDisplay = action.parameters?.antenna ? String(action.parameters.antenna) : 'B'
      proposedHeadline = `${micName}: antenna ${currentDisplay} → ${proposedDisplay}`
    } else if (action.action_type === 'BOOM_COVERAGE') {
      isBoomBackup = true
      currentDisplay = 'Primary'
      proposedDisplay = 'Boom'
      proposedHeadline = `${micName}: primary → overhead boom backup`
    }
  }

  // Check if there is an actual confirmed exclusion or lock
  const channelExclusion = confirmedConstraints.find(
    (c) => c.kind === 'CHANNEL_EXCLUSION' && c.confirmed
  )
  const excludedChannelVal = channelExclusion?.parameters?.excluded_channel
    ? String(channelExclusion.parameters.excluded_channel)
    : null

  const handleTextChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setRuleText(e.target.value)
    setHasEditedLocally(true)
  }

  const handleInterpretClick = async () => {
    const trimmed = ruleText.trim()
    if (!trimmed) return
    // Only prepend 'Exclude channel ' for purely numeric input; pass natural language verbatim
    const payload = /^\d+$/.test(trimmed) ? `Exclude channel ${trimmed}` : trimmed
    const ok = await onInterpret(payload)
    if (ok) {
      setHasEditedLocally(false)
      setIsEditing(false)
    }
  }

  const handleConfirmClick = async () => {
    const ok = await onConfirm()
    if (ok) {
      setHasEditedLocally(false)
      setIsEditing(false)
    }
  }

  const currentInterpText =
    session?.interpretation?.constraints?.[0]?.source_text ||
    session?.interpretation?.constraints?.[0]?.exact_source_span ||
    ''
  const isDirtyAfterInterp = hasEditedLocally && ruleText.trim() !== currentInterpText.trim()

  // Strict canTest rule: state AWAITING_HUMAN_APPROVAL or PLAN_APPROVED, no local changes, exact candidate selected
  const canTest =
    !busy &&
    !hasEditedLocally &&
    !isEditing &&
    selectedPlan !== null &&
    (session?.state === 'AWAITING_HUMAN_APPROVAL' || session?.state === 'PLAN_APPROVED') &&
    candidatePlans.some((p) => p.plan_id === selectedPlan.plan_id)

  const proposedResource = isAntennaSwitch
    ? `Antenna ${proposedDisplay}`
    : isBoomBackup
    ? 'Overhead boom coverage'
    : `Channel ${proposedDisplay}`

  const confirmedRulesText = confirmedConstraints.map(formatConstraint).join(', ')

  const plainReason = excludedChannelVal
    ? `Channel ${excludedChannelVal} is kept free. ${proposedResource} is available in this sample.`
    : isConfirmed
    ? `Confirmed rule: ${confirmedRulesText}. Proposed plan satisfies this restriction.`
    : selectedPlan?.rationale
    ? selectedPlan.rationale.replace(/mic_\d+/g, micName)
    : `${isAntennaSwitch ? 'Antenna' : isBoomBackup ? 'Lavalier' : 'Channel'} ${currentDisplay !== '—' ? currentDisplay : ''} had dropout. ${proposedResource} is available in this sample.`

  return (
    <div className="review-change-step-view">
      {/* Page Title */}
      <div className="step-heading-group">
        <h1 className="step-main-title">Review change</h1>
        <p className="step-subtitle">
          Review the suggested setting. Confirm any channels to keep free, then click Test this change.
        </p>
        <p className="step-meta-line">
          Alleyway dialogue · 12 seconds · 4 microphones &nbsp;&nbsp; Sample scene · Simulated
          microphone readings
        </p>
      </div>

      {/* Main Full-Width White Card */}
      <div className="step-main-card review-change-main-card">
        {/* Header inside Card */}
        <div className="review-card-top-row flex items-center justify-between">
          <div className="review-performer-info flex items-center gap-2">
            <MicIcon size={20} className="text-gray-900" />
            <span className="review-performer-name">{micName}</span>
            <span className="review-sound-badge">Current sound</span>
          </div>

          <div className="review-current-setting font-medium text-gray-800">
            {isAntennaSwitch
              ? `Antenna ${currentAntenna}`
              : isBoomBackup
              ? 'Primary lavalier'
              : `Channel ${currentChannel}`}
          </div>
        </div>

        {/* Waveform with Missing Interval Bracket */}
        <div className="review-waveform-section">
          {baselineEvidence.intervals.length > 0 && (
            <div className="review-missing-dimension-bracket" aria-hidden="true">
              <span className="dimension-bracket-line">|</span>
              <span className="dimension-bracket-label">
                {baselineEvidence.dropoutMs > 0
                  ? `${missingDurationS}s missing`
                  : `${(baselineEvidence.clippingMs / 1000).toFixed(1)}s clipping`}
              </span>
              <span className="dimension-bracket-line">|</span>
            </div>
          )}

          <WaveformTrack
            peaks={PCM_PEAKS_240}
            height={52}
            tint="default"
            intervals={baselineEvidence.intervals}
            showRuler={true}
            interactive={false}
            ariaLabel={`${micName} baseline waveform`}
          />
        </div>

        <div className="card-divider" />

        {/* Proposed Change Row */}
        <div className="proposed-change-row flex items-center justify-between flex-wrap gap-4">
          <div className="proposed-change-left">
            <span className="proposed-change-label">Proposed change</span>
            <h2 className="proposed-change-headline">{proposedHeadline}</h2>
            <p className="proposed-change-provider">
              {session?.mode === 'live' ? 'Suggested by Gemini' : 'Preview suggestion'}
            </p>
          </div>

          {/* Visual Diagram Boxes */}
          <div className="proposed-diagram-group flex items-center gap-3" aria-label="Visual change diagram">
            {/* Box 1: Current */}
            <div className="diagram-box">
              <div className="diagram-box-header">
                {isBoomBackup ? <BoomMicIcon size={32} /> : <MicIcon size={32} />}
                <span className="diagram-box-sublabel">Current</span>
              </div>
              <span className="diagram-box-val">{currentDisplay}</span>
            </div>

            <span className="diagram-arrow" aria-hidden="true">
              →
            </span>

            {/* Box 2: Proposed */}
            <div className="diagram-box diagram-box-proposed">
              <div className="diagram-box-header">
                {isBoomBackup ? <BoomMicIcon size={32} /> : <MicIcon size={32} />}
                <span className="diagram-box-sublabel">Proposed</span>
              </div>
              <span className="diagram-box-val">{proposedDisplay}</span>
            </div>

            {/* Box 3: Kept Free / Locked (Only when an actual confirmed constraint exists) */}
            {excludedChannelVal && (
              <div className="diagram-box-kept-free">
                <div className="crossed-out-square">
                  <span className="crossed-val">{excludedChannelVal}</span>
                  <div className="cross-line cross-diag-1" />
                  <div className="cross-line cross-diag-2" />
                </div>
                <span className="kept-free-sublabel">Kept free</span>
              </div>
            )}
          </div>
        </div>

        {/* Candidate Plans Selector if Multiple */}
        {candidatePlans.length > 1 && (
          <div className="candidate-plans-selection mt-4 pt-3 border-t border-gray-100">
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-2">
              Alternative candidate plans:
            </span>
            <div className="flex flex-col gap-2">
              {candidatePlans.map((plan, idx) => (
                <label
                  key={plan.plan_id}
                  className={`flex items-center gap-3 p-3 border rounded-lg cursor-pointer ${
                    selectedPlan?.plan_id === plan.plan_id
                      ? 'border-[#1d5bd8] bg-blue-50/50'
                      : 'border-gray-200 hover:bg-gray-50'
                  }`}
                >
                  <input
                    type="radio"
                    name="candidate-plan-choice"
                    value={plan.plan_id}
                    checked={selectedPlan?.plan_id === plan.plan_id}
                    onChange={() => setSelectedPlanId(plan.plan_id)}
                  />
                  <div className="text-sm">
                    <strong>Plan {String.fromCharCode(65 + idx)}:</strong> {plan.rationale}
                  </div>
                </label>
              ))}
            </div>
          </div>
        )}

        <div className="card-divider" />

        {/* Channels / Settings to Keep Free */}
        <div className="channels-rule-row">
          <label htmlFor="keep-free-input" className="channels-rule-label">
            Channels to keep free
          </label>

          <div className="channels-input-action-group flex items-center gap-3 flex-wrap">
            <input
              id="keep-free-input"
              type="text"
              value={ruleText}
              onChange={handleTextChange}
              className="channels-rule-input"
              placeholder="e.g. 11 or Exclude channel 11"
              aria-label="Channels to keep free"
              disabled={!!busy}
            />

            {!isEditing && !hasEditedLocally && (
              <button
                type="button"
                onClick={() => setIsEditing(true)}
                className="btn-rule-edit"
                disabled={!!busy}
              >
                <EditPencilIcon size={15} />
                <span>Edit</span>
              </button>
            )}

            {isConfirmed && !hasEditedLocally && !isEditing && (
              <div className="flex items-center gap-2 flex-wrap">
                {confirmedConstraints.map((c, idx) => (
                  <div key={idx} className="rule-confirmed-pill">
                    <CheckCircleIcon size={16} filled={true} />
                    <span>Confirmed: {formatConstraint(c)}</span>
                  </div>
                ))}
              </div>
            )}

            {(isEditing || hasEditedLocally) && (
              <button
                type="button"
                onClick={handleInterpretClick}
                className="btn-interpret-rule"
                disabled={!!busy || !ruleText.trim()}
              >
                Interpret rule
              </button>
            )}
          </div>

          {/* Interpretation Details if returned */}
          {session?.interpretation && (!isConfirmed || isEditing || hasEditedLocally) && (
            <div className="rule-interpretation-notice mt-3">
              <p className="interpretation-rationale">{session.interpretation.rationale}</p>
              {session.interpretation.status === 'SUPPORTED' && !isConfirmed && (
                <button
                  type="button"
                  onClick={handleConfirmClick}
                  className="btn-confirm-rule mt-2"
                  disabled={!!busy || isDirtyAfterInterp}
                >
                  <CheckCircleIcon size={16} filled={true} />
                  <span>Confirm rule</span>
                </button>
              )}
            </div>
          )}

          <p className="channels-rule-helper mt-2">
            A channel is the microphone's wireless setting. Enter a channel to keep free, click Interpret rule, then Confirm rule before testing.
          </p>
        </div>

        <div className="card-divider" />

        {/* Reason Row */}
        <div className="reason-row">
          <span className="reason-label">Reason</span>
          <p className="reason-text">{plainReason}</p>
          {selectedPlan?.rationale && selectedPlan.rationale !== plainReason && (
            <details className="mt-2 text-xs text-gray-500">
              <summary className="cursor-pointer font-medium hover:text-gray-700">Details</summary>
              <p className="mt-1 pl-2 border-l-2 border-gray-300">{selectedPlan.rationale.replace(/mic_\d+/g, micName)}</p>
            </details>
          )}
        </div>
      </div>

      {/* Bottom Action Card (White Panel with Blue CTA) */}
      <footer className="step-bottom-action-card">
        <div className="bottom-card-left">
          <h3 className="bottom-card-title">Ready to test the proposed change</h3>
          <p className="bottom-card-subtext">Approves this change and runs another sample check.</p>
          <button
            type="button"
            onClick={onBackToSound}
            className="btn-back-link mt-2"
            disabled={!!busy}
          >
            <ArrowLeftIcon size={16} />
            <span>Back to sound issues</span>
          </button>
        </div>

        <div className="bottom-card-right">
          <button
            type="button"
            className="btn-blue-primary"
            onClick={() => selectedPlan && onTestChange(selectedPlan)}
            disabled={!canTest}
          >
            <span>{busy ? 'Please wait…' : 'Test this change'}</span>
            <ArrowRightIcon size={18} />
          </button>
        </div>
      </footer>
    </div>
  )
}
