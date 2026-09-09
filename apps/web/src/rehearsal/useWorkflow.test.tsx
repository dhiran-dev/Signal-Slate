import {act, cleanup, renderHook, waitFor} from '@testing-library/react'
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest'
import {useWorkflow} from './useWorkflow'
import type {Plan, Session} from './types'

const plan: Plan = {plan_id: 'plan-12', plan_version: 2, action_hash: 'actions', constraints_hash: 'rules', base_config_hash: 'before', actions: [{action_type: 'CHANNEL_SWITCH', mic_id: 'mic_1', parameters: {channel: 12}}], rationale: 'Keep channel 11 free.', tradeoffs: []}
const initial: Session = {id: 'sample-1', csrf_token: 'csrf-test', revision: 0, state: 'READY', mode: 'live', preset: 'a', shot_context: {duration_ms: 12000, mic_ids: ['mic_1'], performer_names: {mic_1: 'Elena'}, transcript: '', critical_dialogue_text: '', critical_line_start_ms: 4900, critical_line_end_ms: 6800}, baseline: null, comparison: null, finding: null, interpretation: null, candidate_plans: [], confirmed_constraints: [], approval: null, verification: null, error: null}
let snapshot: Session
let calls: {url: string; body: Record<string, unknown>; headers: Record<string, string>}[]
let failApply: boolean
beforeEach(() => {
  window.history.replaceState(null, '', '/rehearsal')
  sessionStorage.clear()
  snapshot = structuredClone(initial)
  calls = []
  failApply = false
  vi.stubGlobal('fetch', vi.fn(async (url: string, options: RequestInit = {}) => {
    if (url === '/api/readiness') return {ok: true, json: async () => ({live_available: true, runtime_enabled: true, gemini: {configured: true}, grafana: {configured: true}, missing: []})}
    const body = options.body ? JSON.parse(String(options.body)) : {}
    calls.push({url, body, headers: options.headers as Record<string, string>})
    if (options.method === 'POST') {
      snapshot.revision++
      if (url === '/api/sessions') snapshot.mode = body.mode
      if (url.endsWith('/baseline')) {snapshot.baseline = {run_id: 'before', config_hash: 'before', samples: [], metrics: [], completion_marker_present: true}; snapshot.state = 'BASELINE_READY'}
      if (url.endsWith('/investigate')) {snapshot.finding = {status: 'RISK_IDENTIFIED', observations: [], evidence_ids: [], competing_explanations: [], recommended_action: plan.actions[0]}; snapshot.state = 'AWAITING_HUMAN_CONSTRAINT'}
      if (url.endsWith('/constraints')) {snapshot.interpretation = {status: 'SUPPORTED', rationale: '', constraints: [{constraint_id: 'rule', kind: 'CHANNEL_EXCLUSION', target_mic: 'mic_1', parameters: {excluded_channel: 11}, exact_source_span: 'Exclude channel 11', source_text: 'Exclude channel 11', confirmed: false}]}; snapshot.state = 'AWAITING_HUMAN_CONFIRMATION'}
      if (url.endsWith('/confirm')) {snapshot.confirmed_constraints = body.constraints; snapshot.candidate_plans = [plan]; snapshot.state = 'AWAITING_HUMAN_APPROVAL'}
      if (url.endsWith('/approve')) {snapshot.approval = body.approval; snapshot.state = 'PLAN_APPROVED'}
      if (url.endsWith('/apply')) {
        if (failApply) return {ok: false, status: 503, json: async () => ({detail: 'Reading interrupted'})}
        snapshot.comparison = {...snapshot.baseline!, run_id: 'after'}; snapshot.state = 'COMPLETED'
      }
    }
    return {ok: true, json: async () => structuredClone(snapshot)}
  }))
})
afterEach(() => {cleanup(); vi.unstubAllGlobals()})

describe('guided workflow orchestration', () => {
  it('does not dispatch on load and combines steps with fresh revisions and exact approval', async () => {
    const {result} = renderHook(() => useWorkflow())
    await waitFor(() => expect(result.current.readiness?.live_available).toBe(true))
    expect(calls).toEqual([])
    await act(() => result.current.checkSound())
    expect(calls.map(c => c.url)).toEqual(['/api/sessions', '/api/sessions/sample-1/baseline'])
    expect(calls[1].body.revision).toBe(1)
    expect(result.current.step).toBe('sound')
    await act(() => result.current.findFix())
    await act(() => result.current.interpret('Exclude channel 11'))
    expect(calls.some(c => c.url.endsWith('/confirm'))).toBe(false)
    await act(() => result.current.confirm())
    expect(calls.some(c => c.url.endsWith('/approve'))).toBe(false)
    await act(() => result.current.testChange(plan))
    const approval = calls.find(c => c.url.endsWith('/approve'))!
    const apply = calls.find(c => c.url.endsWith('/apply'))!
    expect(approval.body.approval).toMatchObject({plan_id: plan.plan_id, plan_version: 2, action_hash: 'actions', constraints_hash: 'rules', base_config_hash: 'before', approved: true})
    expect(apply.body.revision).toBe(Number(approval.body.revision) + 1)
    expect(approval.headers['X-CSRF-Token']).toBe('csrf-test')
    expect(result.current.step).toBe('compare')
    const count = calls.length
    act(() => result.current.setStep('sound'))
    expect(calls).toHaveLength(count)
  })

  it('guards rapid duplicate clicks synchronously', async () => {
    const {result} = renderHook(() => useWorkflow())
    await waitFor(() => expect(result.current.readiness).not.toBeNull())
    await act(async () => {await Promise.all([result.current.checkSound(), result.current.checkSound()])})
    expect(calls.filter(c => c.url === '/api/sessions')).toHaveLength(1)
    expect(calls.filter(c => c.url.endsWith('/baseline'))).toHaveLength(1)
  })

  it('preserves recorded approval if the subsequent test fails, and does not reapprove', async () => {
    sessionStorage.setItem('signal-slate-session', snapshot.id)
    snapshot.state = 'AWAITING_HUMAN_APPROVAL'
    snapshot.candidate_plans = [plan]
    failApply = true
    const {result} = renderHook(() => useWorkflow())
    await waitFor(() => expect(result.current.session).not.toBeNull())
    await act(() => result.current.testChange(plan))
    expect(result.current.error).toBe('Reading interrupted')
    expect(result.current.session?.approval).toMatchObject({plan_id: plan.plan_id})
    failApply = false
    await act(() => result.current.testChange(plan))
    expect(calls.filter(c => c.url.endsWith('/approve'))).toHaveLength(1)
    expect(result.current.step).toBe('compare')
  })

  it('rejects a stale proposal without sending approval or test', async () => {
    sessionStorage.setItem('signal-slate-session', snapshot.id)
    snapshot.state = 'AWAITING_HUMAN_APPROVAL'
    snapshot.candidate_plans = [plan]
    const {result} = renderHook(() => useWorkflow())
    await waitFor(() => expect(result.current.session).not.toBeNull())
    await act(() => result.current.testChange({...plan, constraints_hash: 'old-rules'}))
    expect(result.current.error).toContain('proposal has changed')
    expect(calls).toHaveLength(1)
  })

  it('does not invent change or comparison screens for a healthy check', async () => {
    snapshot.state = 'NO_RISK'
    snapshot.baseline = {run_id: 'healthy', config_hash: 'before', samples: [], metrics: [], completion_marker_present: true}
    window.history.replaceState(null, '', '/rehearsal/sample-1#compare')
    const {result} = renderHook(() => useWorkflow())
    await waitFor(() => expect(result.current.session?.state).toBe('NO_RISK'))
    expect(result.current.step).toBe('report')
    act(() => result.current.setStep('change'))
    expect(result.current.step).toBe('report')
    act(() => result.current.setStep('sound'))
    expect(result.current.step).toBe('sound')
    expect(calls).toHaveLength(1)
  })
})
