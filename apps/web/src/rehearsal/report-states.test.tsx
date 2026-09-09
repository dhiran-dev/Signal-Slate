import {cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {CheckReportStep} from './CheckReportStep'
import type {Session} from './types'
afterEach(cleanup)
it('a failed constraint cannot be described as held, and the actual failure remains inspectable',()=>{
 const session:Session={id:'failed-check',csrf_token:'csrf',revision:8,state:'COMPLETED',mode:'preview',shot_context:{duration_ms:12000,mic_ids:['mic_1'],performer_names:{mic_1:'Elena'},transcript:'',critical_dialogue_text:'',critical_line_start_ms:4900,critical_line_end_ms:6800},baseline:null,comparison:null,finding:null,candidate_plans:[],interpretation:null,approval:null,confirmed_constraints:[{constraint_id:'rule',kind:'CHANNEL_EXCLUSION',target_mic:null,parameters:{excluded_channel:11},source_text:'Exclude channel 11',exact_source_span:'Exclude channel 11',confirmed:true}],verification:{terminal_status:'NOT_VERIFIED',completeness_passed:true,crosscheck_passed:true,thresholds_passed:false,dialogue_coverage_passed:false,constraints_passed:false,failure_reasons:['The applied configuration still uses an excluded channel.'],evidence_hashes:{}},error:null}
 const {rerender}=render(<CheckReportStep session={session} busy="" onStartAnotherCheck={vi.fn()}/> )
 expect(screen.getByRole('region',{name:'Verification checks'})).not.toHaveTextContent('Exclude channel 11 held')
 expect(screen.getByText('The applied configuration still uses an excluded channel.')).toBeInTheDocument()
 rerender(<CheckReportStep session={{...session,verification:{...session.verification!,terminal_status:'INCONCLUSIVE'}}} busy="" onStartAnotherCheck={vi.fn()}/> )
 expect(screen.getByRole('region',{name:'Verification checks'})).not.toHaveTextContent('Thresholds exceeded')
 expect(screen.getByText('Microphone sound unverified')).toBeInTheDocument()
 expect(screen.getByRole('region',{name:'Verification checks'})).not.toHaveTextContent('Exclude channel 11 violated')
})
