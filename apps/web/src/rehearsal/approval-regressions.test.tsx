import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react'
import {afterEach, expect, it, vi} from 'vitest'
import {ReviewChangeStep} from './ReviewChangeStep'
import type {Plan, Session} from './types'
const plan: Plan = {plan_id:'plan-12',plan_version:2,action_hash:'a',constraints_hash:'c',base_config_hash:'b',actions:[{action_type:'CHANNEL_SWITCH',mic_id:'mic_1',parameters:{channel:12}}],rationale:'Use channel 12.',tradeoffs:[]}
function ready(): Session {
  const rule={constraint_id:'rule',kind:'CHANNEL_EXCLUSION' as const,target_mic:'mic_1',parameters:{excluded_channel:11},source_text:'Exclude channel 11',exact_source_span:'Exclude channel 11',confirmed:true}
  return {id:'sample',csrf_token:'csrf',revision:5,state:'AWAITING_HUMAN_APPROVAL',mode:'preview',shot_context:{duration_ms:12000,mic_ids:['mic_1'],performer_names:{mic_1:'Elena'},transcript:'',critical_dialogue_text:'',critical_line_start_ms:4900,critical_line_end_ms:6800},baseline:null,comparison:null,finding:null,candidate_plans:[plan],confirmed_constraints:[rule],interpretation:{status:'SUPPORTED',rationale:'Keep channel 11 free.',constraints:[rule]},approval:null,verification:null,error:null}
}
afterEach(cleanup)
it('keeps an older proposal blocked after a new rule fails to save', async()=>{
  const interpret=vi.fn().mockResolvedValue(false)
  const confirm=vi.fn().mockResolvedValue(true)
  const test=vi.fn().mockResolvedValue(undefined)
  render(<ReviewChangeStep session={ready()} busy="" onInterpret={interpret} onConfirm={confirm} onTestChange={test} onBackToSound={()=>{}} />)
  expect(screen.getByRole('button',{name:'Test this change'})).toBeEnabled()
  fireEvent.change(screen.getByRole('textbox',{name:'Channels to keep free'}),{target:{value:'12'}})
  fireEvent.click(screen.getByRole('button',{name:'Interpret rule'}))
  await waitFor(()=>expect(interpret).toHaveBeenCalledWith('Exclude channel 12'))
  expect(screen.getByRole('button',{name:'Test this change'})).toBeDisabled()
  const confirmation=screen.queryByRole('button',{name:'Confirm rule'})
  if(confirmation)expect(confirmation).toBeDisabled()
  expect(confirm).not.toHaveBeenCalled()
  expect(test).not.toHaveBeenCalled()
})
it('restores the exact recorded approval when another candidate is first in the list', async()=>{
  const session=ready()
  const second={...plan,plan_id:'plan-13',action_hash:'action13',actions:[{...plan.actions[0],parameters:{channel:13}}],rationale:'Use channel 13.'}
  session.candidate_plans.push(second)
  session.approval={plan_id:second.plan_id,plan_version:second.plan_version,action_hash:second.action_hash,constraints_hash:second.constraints_hash,base_config_hash:second.base_config_hash,approved:true,approved_by:'sound_mixer'}
  session.state='PLAN_APPROVED'
  const test=vi.fn().mockResolvedValue(undefined)
  render(<ReviewChangeStep session={session} busy="" onInterpret={vi.fn().mockResolvedValue(true)} onConfirm={vi.fn().mockResolvedValue(true)} onTestChange={test} onBackToSound={()=>{}} />)
  fireEvent.click(screen.getByRole('button',{name:'Test this change'}))
  await waitFor(()=>expect(test).toHaveBeenCalledWith(second))
})
