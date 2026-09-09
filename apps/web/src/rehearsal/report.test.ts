import {afterEach, describe, expect, it, vi} from 'vitest'
import {downloadReport, publicReport} from './report'
import type {Session} from './types'

const session = {
  id:'owned-session', csrf_token:'SECRET_CSRF', mode:'preview', state:'PREVIEW_COMPLETE',
  shot_context:{}, baseline:{run_id:'before'}, comparison:{run_id:'after'},
  confirmed_constraints:[], candidate_plans:[], verification:{terminal_status:'INCONCLUSIVE'},
  operation:{id:'PRIVATE_OPERATION'}, history:[{baseline:{run_id:'old'}, comparison:{run_id:'prior'}, config:{}, verification:{}, approval:{approved_by:'PRIVATE_ACTOR'}}],
} as unknown as Session

afterEach(() => vi.unstubAllGlobals())
describe('downloadable evidence report', () => {
  it('includes run references but no browser authority or operation state', () => {
    const report = publicReport(session)
    expect(report.evidence_references).toEqual([
      {run_id:'before',path:'/api/sessions/owned-session/evidence/before'},
      {run_id:'after',path:'/api/sessions/owned-session/evidence/after'},
    ])
    const body = JSON.stringify(report)
    expect(body).not.toContain('SECRET_CSRF')
    expect(body).not.toContain('PRIVATE_OPERATION')
    expect(body).not.toContain('PRIVATE_ACTOR')
    expect(report.verification?.terminal_status).toBe('INCONCLUSIVE')
  })
  it('downloads preserved readings even if fetching cloud links fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    const create = vi.fn().mockReturnValue('blob:report')
    vi.stubGlobal('URL', Object.assign(URL, {createObjectURL:create,revokeObjectURL:vi.fn()}))
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    await downloadReport({...session,mode:'live'})
    expect(create).toHaveBeenCalledOnce()
    expect(click).toHaveBeenCalledOnce()
    click.mockRestore()
  })
})
