import {describe,it,expect} from 'vitest'
import {receiverSummary,vetoReason} from './evidence'
import type {Run,Constraint} from './types'
describe('Receiver evidence summaries',()=>{
 it('counts 100ms intervals without the terminal sample and separates microphones',()=>{
 const run:Run={run_id:'r',config_hash:'h',metrics:[],completion_marker_present:true,samples:[{offset_ms:4900,mic_id:'mic_1',quality:30,is_dropout:true,is_clipped:false},{offset_ms:5000,mic_id:'mic_1',quality:70,is_dropout:false,is_clipped:true},{offset_ms:12000,mic_id:'mic_1',quality:0,is_dropout:true,is_clipped:false},{offset_ms:4900,mic_id:'mic_2',quality:0,is_dropout:true,is_clipped:false}]}
 expect(receiverSummary(run,'mic_1')).toEqual({minQuality:30,dropoutMs:100,clippingMs:100,sampleCount:2})
 expect(receiverSummary(null,'mic_1').minQuality).toBeNull()
 })
 it('labels a veto only from confirmed matching constraints',()=>{const c:Constraint={constraint_id:'c',kind:'CHANNEL_EXCLUSION',target_mic:'mic_1',parameters:{excluded_channel:11},exact_source_span:'Exclude channel 11',source_text:'Exclude channel 11',confirmed:true};const a={action_type:'CHANNEL_SWITCH' as const,mic_id:'mic_1',parameters:{channel:11}};expect(vetoReason(a,[c])).toContain('Channel 11 is excluded');expect(vetoReason(a,[{...c,confirmed:false}])).toBeNull();expect(vetoReason({...a,mic_id:'mic_2'},[c])).toBeNull()})
})

it('rig locks permit backup coverage without changing the costume rig',()=>{const lock:Constraint={constraint_id:'lock',kind:'RIG_LOCK',target_mic:'mic_1',parameters:{},source_text:'Keep the rig',exact_source_span:'Keep the rig',confirmed:true};expect(vetoReason({action_type:'BOOM_COVERAGE',mic_id:'mic_1',parameters:{source_mic:'mic_4'}},[lock])).toBeNull();expect(vetoReason({action_type:'CHANNEL_SWITCH',mic_id:'mic_1',parameters:{channel:12}},[lock])).toContain('lock prevents')})
it('shared antenna lock permits its locked antenna and rejects a different antenna',()=>{const lock:Constraint={constraint_id:'lock',kind:'ANTENNA_LOCK',target_mic:'mic_2',parameters:{locked_antenna:'B'},source_text:'Keep antenna B',exact_source_span:'Keep antenna B',confirmed:true};expect(vetoReason({action_type:'ANTENNA_SWITCH',mic_id:'mic_1',parameters:{antenna:'B'}},[lock])).toBeNull();expect(vetoReason({action_type:'ANTENNA_SWITCH',mic_id:'mic_1',parameters:{antenna:'A'}},[lock])).toContain('lock prevents')})
