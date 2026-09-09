import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { beforeEach, afterEach, describe, it, expect, vi } from 'vitest'
import { Rehearsal } from './Rehearsal'
import type { Session, Plan } from './types'

const plan: Plan = {
  plan_id: 'plan_b',
  plan_version: 2,
  action_hash: 'actions-exact',
  constraints_hash: 'confirmed-exact',
  base_config_hash: 'baseline-exact',
  actions: [{ action_type: 'CHANNEL_SWITCH', mic_id: 'mic_1', parameters: { channel: 12 } }],
  rationale: 'Channel 12 respects the exclusion.',
  tradeoffs: ['Retune before the take.']
}

const initial: Session = {
  id: 'session-1',
  csrf_token: 'csrf-example',
  revision: 0,
  state: 'READY',
  mode: 'preview',
  shot_context: {
    duration_ms: 12000,
    mic_ids: ['mic_1', 'mic_2', 'mic_3', 'mic_4'],
    performer_names: { mic_1: 'Elena', mic_2: 'Marcus', mic_3: 'Guard', mic_4: 'Boom' },
    transcript: 'do not cut the feed',
    critical_dialogue_text: 'do not cut the feed',
    critical_line_start_ms: 4900,
    critical_line_end_ms: 6800
  },
  baseline: null,
  comparison: null,
  finding: null,
  interpretation: null,
  candidate_plans: [],
  confirmed_constraints: [],
  approval: null,
  verification: null,
  error: null
}

let current: Session
let calls: { url: string; body: Record<string, unknown>; headers: Record<string, string> }[]

beforeEach(() => {
  window.history.replaceState(null, '', '/rehearsal')
  sessionStorage.clear()
  current = structuredClone(initial)
  calls = []

  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      if (url.endsWith('/readiness')) {
        return {
          ok: true,
          json: async () => ({
            live_available: true,
            runtime_enabled: true,
            gemini: { configured: true },
            grafana: { configured: true },
            missing: []
          })
        }
      }

      const body = options?.body ? JSON.parse(String(options.body)) : {}
      calls.push({ url, body, headers: (options?.headers as Record<string, string>) || {} })

      if (options?.method === 'POST') {
        current.revision++
        if (url === '/api/sessions' || url.endsWith('/sessions')) {
          current.mode = (body.mode as 'live' | 'preview') || current.mode
          current.preset = (body.preset as 'a' | 'b' | 'c' | 'control') || current.preset
        }
        if (url.endsWith('/baseline')) {
          current.baseline = {
            run_id: 'baseline',
            config_hash: 'baseline-exact',
            samples: [
              { mic_id: 'mic_1', offset_ms: 5000, quality: 0, is_dropout: true, is_clipped: false }
            ],
            metrics: [],
            completion_marker_present: true
          }
        }
        if (url.endsWith('/investigate')) {
          current.finding = {
            status: 'RISK_IDENTIFIED',
            observations: ['Preview dropout at the phrase.'],
            evidence_ids: ['actual-evidence-1'],
            competing_explanations: [],
            recommended_action: plan.actions[0]
          }
        }
        if (url.endsWith('/constraints')) {
          current.interpretation = {
            status: 'SUPPORTED',
            rationale: 'Exclude channel 11 for this rehearsal.',
            constraints: [
              {
                constraint_id: 'c1',
                kind: 'CHANNEL_EXCLUSION',
                target_mic: 'mic_1',
                parameters: { excluded_channel: 11 },
                exact_source_span: 'Exclude channel 11',
                source_text: 'Exclude channel 11',
                confirmed: false
              }
            ]
          }
        }
        if (url.endsWith('/confirm')) {
          current.confirmed_constraints = body.constraints
          current.candidate_plans = [plan]
          current.state = 'AWAITING_HUMAN_APPROVAL'
        }
        if (url.endsWith('/approve')) {
          current.approval = body.approval
          current.state = 'PLAN_APPROVED'
        }
        if (url.endsWith('/apply')) {
          current.comparison = {
            run_id: 'comparison',
            config_hash: 'comparison-exact',
            samples: [
              { mic_id: 'mic_1', offset_ms: 5000, quality: 1, is_dropout: false, is_clipped: false }
            ],
            metrics: [],
            completion_marker_present: true
          }
          current.verification = {
            terminal_status: 'INCONCLUSIVE',
            completeness_passed: true,
            crosscheck_passed: true,
            thresholds_passed: true,
            dialogue_coverage_passed: true,
            constraints_passed: true,
            failure_reasons: ['Local preview cannot prove cloud verification.'],
            evidence_hashes: {}
          }
        }
      }
      return { ok: true, json: async () => structuredClone(current) }
    })
  )

  window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined)
  window.HTMLMediaElement.prototype.pause = vi.fn()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Rehearsal API workflow', () => {
  it('requires explicit confirmation, exact approval and explicit apply; never calls preview a cloud pass', async () => {
    render(<Rehearsal />)

    // Step 1: Scene setup - switch to preview mode
    fireEvent.click(screen.getByLabelText(/Preview without cloud/i))
    const checkSoundBtn = screen.getByRole('button', { name: 'Check sound' })
    fireEvent.click(checkSoundBtn)

    // Step 2: Sound issues detected
    fireEvent.click(await screen.findByRole('button', { name: 'Find a fix' }))

    // Step 3: Review change - interpret rule
    const ruleInput = await screen.findByRole('textbox', { name: 'Channels to keep free' })
    fireEvent.change(ruleInput, { target: { value: 'Exclude channel 11' } })
    fireEvent.click(screen.getByRole('button', { name: 'Interpret rule' }))

    // Confirm rule
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm rule' }))

    // Test this change (approve + apply)
    const testButton = await screen.findByRole('button', { name: 'Test this change' })
    expect(calls.some((c) => c.url.endsWith('/apply'))).toBe(false)
    fireEvent.click(testButton)

    // Step 4: Compare takes
    fireEvent.click(await screen.findByRole('button', { name: 'View report' }))

    // Step 5: Report step
    expect(await screen.findByText('Inconclusive (preview only)')).toBeInTheDocument()
    expect(screen.queryByText('Passed this rehearsal’s checks')).not.toBeInTheDocument()

    const approval = calls.find((c) => c.url.endsWith('/approve'))!
    expect(approval).toBeDefined()
    expect(approval.body.approval).toMatchObject({
      plan_id: 'plan_b',
      plan_version: 2,
      action_hash: 'actions-exact',
      constraints_hash: 'confirmed-exact',
      base_config_hash: 'baseline-exact',
      approved: true
    })
    expect(approval.headers['X-CSRF-Token']).toBe('csrf-example')
    expect(calls.find((c) => c.url.endsWith('/confirm'))!.body.constraints).toMatchObject([
      { confirmed: true }
    ])
  })

  it('restores with a read-only GET and surfaces errors without claiming success', async () => {
    sessionStorage.setItem('signal-slate-session', 'session-1')
    current.error = 'Evidence unavailable'
    render(<Rehearsal />)

    await screen.findByRole('button', { name: 'Check sound' })
    expect(calls).toHaveLength(1)
    expect(calls[0].body).toEqual({})

    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({ detail: 'Revision changed. Refresh session.' })
    } as Response)

    fireEvent.click(screen.getByRole('button', { name: 'Check sound' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Revision changed. Refresh session.')
    expect(screen.queryByText('Passed this rehearsal’s checks')).not.toBeInTheDocument()
  })

  it('selects live mode explicitly and shows usage disclosure before dispatch', async () => {
    render(<Rehearsal />)
    expect(
      screen.getByText(/A live check makes at most five Gemini requests. Google API usage charges may apply./i)
    ).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText(/Live cloud check/i))
    const checkBtn = screen.getByRole('button', { name: 'Check sound' })
    await waitFor(() => expect(checkBtn).toBeEnabled())
    fireEvent.click(checkBtn)

    await waitFor(() =>
      expect(calls.some((c) => c.body && c.body.mode === 'live' && c.body.preset === 'a')).toBe(true)
    )
  })

  it('renders a missing report without inventing an outcome', async () => {
    sessionStorage.setItem('signal-slate-session', 'session-1')
    render(<Rehearsal report />)
    expect(await screen.findByText('No completed verification yet')).toBeInTheDocument()
    expect(screen.queryByText('Passed this rehearsal’s checks')).not.toBeInTheDocument()
  })
})

it('resumes only by explicit command and includes current revision and CSRF', async () => {
  sessionStorage.setItem('signal-slate-session', 'session-1')
  current.operation = {
    id: 'op-saved',
    kind: 'apply',
    status: 'retryable',
    lease_expires_at: '2026-09-09T00:00:00Z',
    resumable: true
  }
  current.busy = true
  render(<Rehearsal />)
  const resume = await screen.findByRole('button', { name: 'Resume saved operation' })
  expect(calls).toHaveLength(1)
  fireEvent.click(resume)
  await waitFor(() => expect(calls.some((c) => c.url === '/api/operations/op-saved/resume')).toBe(true))
  const command = calls.find((c) => c.url.endsWith('/resume'))!
  expect(command.body).toEqual({ revision: 0 })
  expect(command.headers['X-CSRF-Token']).toBe('csrf-example')
})

it('attributes healthy deterministic evidence without claiming a Gemini investigation', async () => {
  sessionStorage.setItem('signal-slate-session', 'session-1')
  current.mode = 'live'
  current.state = 'NO_RISK'
  current.finding_origin = 'deterministic'
  current.finding = {
    status: 'HEALTHY',
    observations: ['All receiver checks passed.'],
    evidence_ids: [],
    competing_explanations: [],
    recommended_action: { action_type: 'NO_ACTION', mic_id: 'mic_1', parameters: {} }
  }
  render(<Rehearsal />)
  expect(await screen.findByText('No issues found · All checks normal')).toBeInTheDocument()
  expect(screen.getByText(/All receiver checks passed. No correction was required./)).toBeInTheDocument()
  expect(screen.queryByText(/Suggested by Gemini/i)).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Interpret rule' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Test this change' })).not.toBeInTheDocument()
})
