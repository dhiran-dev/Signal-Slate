import {useEffect, useRef, useState} from 'react'
import {requestSession, resumeSession, type Plan, type Readiness, type Session} from './types'

export type WorkflowStep = 'scene' | 'sound' | 'change' | 'compare' | 'report'
const steps: WorkflowStep[] = ['scene', 'sound', 'change', 'compare', 'report']

export function canOpenStep(session: Session | null, step: WorkflowStep): boolean {
  if (step === 'scene' || step === 'report') return true
  if (step === 'sound') return Boolean(session?.baseline)
  if (step === 'change') return Boolean(session?.finding && session.state !== 'NO_RISK')
  return Boolean(session?.comparison || session?.verification)
}

export function sessionStep(session: Session): WorkflowStep {
  if (session.state === 'NO_RISK') return 'report'
  if (session.comparison || session.verification) return 'compare'
  if (session.finding) return 'change'
  if (session.baseline) return 'sound'
  return 'scene'
}

/** Orchestrates existing durable commands. Navigation and restore never dispatch cloud work. */
export function useWorkflow({report = false}: {report?: boolean} = {}) {
  const [session, setSession] = useState<Session | null>(null)
  const [readiness, setReadiness] = useState<Readiness | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [step, updateStep] = useState<WorkflowStep>(report ? 'report' : 'scene')
  const [preset, setPreset] = useState('a')
  const [mode, updateMode] = useState<'live' | 'preview'>('live')
  const current = useRef<Session | null>(null)
  const locked = useRef(false)
  const mounted = useRef(false)

  useEffect(() => {
    mounted.current = true
    let cancelled = false
    const controller = new AbortController()
    void fetch('/api/readiness', {signal: controller.signal, credentials: 'same-origin'})
      .then(async response => {
        if (!response.ok) throw new Error('Connection setup could not be checked.')
        const result: Readiness = await response.json()
        if (!cancelled) {
          setReadiness(result)
        }
      }).catch(() => {
        if (!cancelled) setReadiness({live_available: false, runtime_enabled: false,
          gemini: {configured: false}, grafana: {configured: false}, missing: ['Connection setup could not be checked. Refresh to try again.']})
      })
    const routeId = window.location.pathname.match(/^\/(?:rehearsal|reports?)\/([^/]+)$/)?.[1]
    let id: string | null = null
    try { id = routeId ? decodeURIComponent(routeId) : sessionStorage.getItem('signal-slate-session') } catch { /* Invalid route is handled as a missing session. */ }
    if (id) {
      locked.current = true
      setBusy('Restoring your sound check')
      void requestSession(`/${encodeURIComponent(id)}`).then(next => {
        if (cancelled) return
        current.current = next
        setSession(next)
        updateMode(next.mode)
        if (next.preset) setPreset(next.preset)
        const savedStep = window.location.hash.slice(1) as WorkflowStep
        const latest = sessionStep(next)
        updateStep(report ? 'report' : steps.includes(savedStep) && canOpenStep(next, savedStep) ? savedStep : latest)
        if (next.error) setError(next.error)
      }).catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : 'Could not restore this sound check.') })
        .finally(() => { if (!cancelled) {locked.current = false; setBusy('')} })
    }
    return () => { cancelled = true; mounted.current = false; controller.abort() }
  }, [report])

  function setMode(next: 'live' | 'preview') { updateMode(next) }
  function setStep(next: WorkflowStep) {
    if (locked.current) return
    if (!canOpenStep(current.current, next)) return
    updateStep(next)
    window.history.replaceState(null, '', `${window.location.pathname}#${next}`)
  }
  function accept(next: Session) {
    current.current = next
    if (!mounted.current) return
    setSession(next)
    sessionStorage.setItem('signal-slate-session', next.id)
    if (!window.location.pathname.match(/^\/(?:rehearsal|reports?)\/[^/]+$/)) {
      window.history.replaceState(null, '', `/rehearsal/${encodeURIComponent(next.id)}#${step}`)
    }
    if (next.error) setError(next.error)
  }
  function go(next: WorkflowStep) {
    if (!mounted.current) return
    updateStep(next)
    window.history.replaceState(null, '', `${window.location.pathname}#${next}`)
  }
  async function task(label: string, work: () => Promise<void>) {
    if (locked.current) return false
    locked.current = true
    setBusy(label)
    setError('')
    try { await work(); return true }
    catch (e) { if (mounted.current) setError(e instanceof Error ? e.message : 'This step could not finish. Your saved check is available below.'); return false }
    finally { locked.current = false; if (mounted.current) setBusy('') }
  }
  async function command(action: string, extra: Record<string, unknown> = {}) {
    const saved = current.current
    if (!saved) throw new Error('Choose a sample scene first.')
    if (saved.busy) throw new Error('Your saved check is still running. Refresh or resume it before continuing.')
    const next = await requestSession(`/${encodeURIComponent(saved.id)}/${action}`, {revision: saved.revision, ...extra}, saved.csrf_token)
    accept(next)
    if (next.error) throw new Error(next.error)
    return next
  }
  async function checkSound() {
    await task('Preparing your sample', async () => {
      if (!current.current) {
        if (mode === 'live' && !readiness?.live_available) throw new Error('Gemini and Grafana must be configured before checking sound. You can use Preview without cloud in Connection help.')
        const next = await requestSession('', {mode, preset})
        accept(next)
        if (next.error) throw new Error(next.error)
      }
      if (!current.current?.baseline) {
        setBusy(current.current?.mode === 'live' ? 'Reading microphone data from Grafana' : 'Preparing sample microphone readings')
        await command('baseline')
      }
      go('sound')
    })
  }
  async function findFix() {
    await task(current.current?.mode === 'live' ? 'Gemini is reviewing the sound' : 'Reviewing the sample sound', async () => {
      const next = current.current?.finding ? current.current : await command('investigate')
      go(next.state === 'NO_RISK' ? 'report' : 'change')
    })
  }
  async function interpret(text: string) {
    return await task(current.current?.mode === 'live' ? 'Gemini is reading your rule' : 'Reading your sample rule', async () => {
      if (!text.trim()) throw new Error('Enter the channels or settings to keep unchanged.')
      await command('constraints', {text})
      go('change')
    })
  }
  async function confirm() {
    return await task('Finding changes that fit your rule', async () => {
      const interpretation = current.current?.interpretation
      if (interpretation?.status !== 'SUPPORTED') throw new Error('Review and confirm a supported rule first.')
      await command('confirm', {constraints: interpretation.constraints.map(c => ({...c, confirmed: true}))})
    })
  }
  async function testChange(plan: Plan) {
    await task('Recording your approval', async () => {
      const saved = current.current
      const exact = saved?.candidate_plans.find(candidate => candidate.plan_id === plan.plan_id)
      const fields = ['plan_id', 'plan_version', 'action_hash', 'constraints_hash', 'base_config_hash'] as const
      if (!exact || fields.some(field => exact[field] !== plan[field])) throw new Error('This proposal has changed. Review the current proposal before testing it.')
      if (saved?.approval) {
        const approved = saved.approval as Record<string, unknown>
        if (fields.some(field => approved[field] !== exact[field])) throw new Error('Another proposal was approved. Refresh to review the saved change.')
      } else {
        if (saved?.state !== 'AWAITING_HUMAN_APPROVAL') throw new Error('Confirm your rule before testing a change.')
        await command('approve', {approval: {
          plan_id: exact.plan_id, plan_version: exact.plan_version, action_hash: exact.action_hash,
          constraints_hash: exact.constraints_hash, base_config_hash: exact.base_config_hash,
          approved: true, approved_by: 'sound_mixer', approved_at: new Date().toISOString(),
        }})
      }
      setBusy(current.current?.mode === 'live' ? 'Running a new sample check and checking Grafana readings' : 'Running a new sample check')
      await command('apply')
      go('compare')
    })
  }
  async function refresh() {
    await task('Refreshing your saved check', async () => {
      if (!current.current) return
      const next = await requestSession(`/${encodeURIComponent(current.current.id)}`)
      accept(next)
      go(report ? 'report' : sessionStep(next))
    })
  }
  async function resume() {
    await task('Resuming your saved check', async () => {
      if (!current.current?.operation?.resumable) throw new Error('This check is not ready to resume. Refresh its status first.')
      const next = await resumeSession(current.current)
      accept(next)
      if (next.error) throw new Error(next.error)
      go(report ? 'report' : sessionStep(next))
    })
  }
  async function retry() {
    await task('Reviewing another change', async () => {const next = await command('retry'); go(sessionStep(next))})
  }
  function reset() {
    if (locked.current || current.current?.busy) return
    current.current = null
    sessionStorage.removeItem('signal-slate-session')
    setSession(null)
    setError('')
    updateStep('scene')
    window.history.replaceState(null, '', '/rehearsal')
  }
  return {session, readiness, busy, error, step, setStep, preset, setPreset, mode, setMode,
    checkSound, findFix, interpret, confirm, testChange, resume, refresh, reset, retry}
}
