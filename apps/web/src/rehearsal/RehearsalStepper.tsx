import React from 'react'
import { canOpenStep, type WorkflowStep } from './useWorkflow'
import type { Session } from './types'
import { CheckIcon } from './icons'

export interface RehearsalStepperProps {
  currentStep: WorkflowStep
  session?: Session | null
  maxAllowedStep?: WorkflowStep
  onStepClick: (step: WorkflowStep) => void
}

const STEP_ORDER: { key: WorkflowStep; number: number; label: string }[] = [
  { key: 'scene', number: 1, label: 'Scene' },
  { key: 'sound', number: 2, label: 'Sound' },
  { key: 'change', number: 3, label: 'Change' },
  { key: 'compare', number: 4, label: 'Compare' },
  { key: 'report', number: 5, label: 'Report' }
]

export const RehearsalStepper: React.FC<RehearsalStepperProps> = ({
  currentStep,
  session,
  maxAllowedStep,
  onStepClick
}) => {
  const currentIndex = STEP_ORDER.findIndex((s) => s.key === currentStep)
  const maxIndex = maxAllowedStep ? STEP_ORDER.findIndex((s) => s.key === maxAllowedStep) : currentIndex
  const isChangeScreen = currentStep === 'change'
  const isCompareScreen = currentStep === 'compare'

  return (
    <nav className="rehearsal-stepper-nav" aria-label="Progress">
      <ol className="rehearsal-stepper-list">
        {STEP_ORDER.map((stepItem, idx) => {
          const isCompleted =
            session !== undefined
              ? stepItem.key === 'scene'
                ? Boolean(session?.baseline)
                : stepItem.key === 'sound'
                ? Boolean(session?.finding) || session?.state === 'NO_RISK'
                : stepItem.key === 'change'
                ? session?.state !== 'NO_RISK' && Boolean(session?.comparison || session?.verification)
                : stepItem.key === 'compare'
                ? session?.state !== 'NO_RISK' && Boolean(session?.verification)
                : Boolean(session?.verification) || session?.state === 'NO_RISK'
              : idx < currentIndex

          const isActive = idx === currentIndex
          const isClickable =
            session !== undefined ? canOpenStep(session, stepItem.key) : idx <= maxIndex || idx <= currentIndex

          // Theme for step badge
          let badgeClass = 'step-badge-inactive'
          if (isActive) {
            badgeClass = isChangeScreen ? 'step-badge-blue-active' : 'step-badge-active'
          } else if (isCompleted) {
            if (isChangeScreen) {
              badgeClass = 'step-badge-blue-completed'
            } else if (isCompareScreen) {
              badgeClass = 'step-badge-green-completed'
            } else {
              badgeClass = 'step-badge-completed'
            }
          }

          return (
            <li
              key={stepItem.key}
              className={`rehearsal-stepper-item ${isActive ? 'is-active' : ''} ${
                isCompleted ? 'is-completed' : ''
              } ${isChangeScreen && isActive ? 'is-blue-accent' : ''}`}
            >
              <button
                type="button"
                disabled={!isClickable}
                onClick={() => isClickable && onStepClick(stepItem.key)}
                className={`stepper-step-button ${badgeClass} ${
                  isClickable ? 'cursor-pointer' : 'cursor-not-allowed step-disabled'
                }`}
                aria-current={isActive ? 'step' : undefined}
                aria-label={`Step ${stepItem.number}: ${stepItem.label}${
                  isCompleted ? ' (completed)' : isActive ? ' (current)' : ''
                }`}
              >
                <span className="stepper-circle">
                  {isCompleted && !isActive ? (
                    <CheckIcon size={14} />
                  ) : (
                    <span className="stepper-num">{stepItem.number}</span>
                  )}
                </span>
                <span className="stepper-label">{stepItem.label}</span>
              </button>

              {idx < STEP_ORDER.length - 1 && (
                <div
                  className={`stepper-connector ${
                    isCompleted ? 'stepper-connector-active' : ''
                  }`}
                  aria-hidden="true"
                />
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
