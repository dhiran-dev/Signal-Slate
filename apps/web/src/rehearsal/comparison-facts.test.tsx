import {cleanup, render, screen, within} from '@testing-library/react'
import {afterEach, expect, it, vi} from 'vitest'
import {CompareTakesStep} from './CompareTakesStep'
import type {Session} from './types'

afterEach(cleanup)

it('does not describe clipping, absent readings, or unverified restrictions as a successful correction', () => {
  const session: Session = {
    id: 'comparison', csrf_token: 'test-csrf', revision: 1, state: 'COMPLETED', mode: 'preview',
    shot_context: {duration_ms: 12000, mic_ids: ['mic_1'], performer_names: {mic_1: 'Elena'}, transcript: '', critical_dialogue_text: '', critical_line_start_ms: 4900, critical_line_end_ms: 6800},
    baseline: {run_id: 'before', config_hash: 'before', metrics: [], completion_marker_present: true, samples: Array.from({length: 120}, (_, i) => ({mic_id: 'mic_1', offset_ms: i * 100, quality: 90, is_dropout: false, is_clipped: i >= 49 && i < 68}))},
    comparison: {run_id: 'after', config_hash: 'after', metrics: [], completion_marker_present: false, samples: []},
    finding: null, candidate_plans: [], interpretation: null, approval: null, error: null,
    confirmed_constraints: [{constraint_id: 'lock', kind: 'ANTENNA_LOCK', target_mic: null, parameters: {locked_antenna: 'A'}, exact_source_span: 'Keep antenna A', source_text: 'Keep antenna A', confirmed: true}],
    verification: {terminal_status: 'INCONCLUSIVE', completeness_passed: false, crosscheck_passed: false, thresholds_passed: false, dialogue_coverage_passed: false, constraints_passed: false, failure_reasons: ['Missing comparison readings'], evidence_hashes: {}}
  }
  const props = {busy: '', onViewReport: vi.fn(), onBackToChange: vi.fn(), onPlayTrack: vi.fn(), onPauseTrack: vi.fn(), activeTrack: 'before' as const, isPlaying: false, currentTime: 0, isMuted: true, onToggleMute: vi.fn(), onSeek: vi.fn()}
  const {rerender} = render(<CompareTakesStep {...props} session={session} />)
  expect(screen.getByText('1.9s distorted')).toBeInTheDocument()
  expect(screen.getByText('12.0s of readings missing')).toBeInTheDocument()
  expect(screen.queryByText('No sound issues')).not.toBeInTheDocument()
  const table = screen.getByRole('table', {name: 'Before and after comparison table'})
  expect(within(table).getByText('Incomplete readings')).toBeInTheDocument()
  expect(within(table).getByText('Not verified')).toBeInTheDocument()
  expect(within(table).queryByText('Respected')).not.toBeInTheDocument()
  rerender(<CompareTakesStep {...props} session={{...session, confirmed_constraints: []}} />)
  expect(screen.queryByText(/Channel 11/i)).not.toBeInTheDocument()
  expect(screen.queryByText('Keep antenna A')).not.toBeInTheDocument()
})
