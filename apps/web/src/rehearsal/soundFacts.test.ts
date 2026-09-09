import {describe,it,expect} from 'vitest'
import {microphoneEvidence} from './evidence'
import type {Run} from './types'

function run():Run{return{run_id:'samples',config_hash:'config',metrics:[],completion_marker_present:true,samples:Array.from({length:121},(_,i)=>({mic_id:'mic_1',offset_ms:i*100,quality:95,is_dropout:false,is_clipped:false}))}}
describe('sound issue facts',()=>{
 it('merges observed dropout windows without classifying clipping as missing sound',()=>{
  const before=run()
  before.samples.forEach(s=>{if(s.offset_ms>=4900&&s.offset_ms<6800)s.is_dropout=true;if(s.offset_ms>=8000&&s.offset_ms<8300)s.is_clipped=true})
  expect(microphoneEvidence(before,'mic_1')).toMatchObject({dropoutMs:1900,clippingMs:300,unknownMs:0,complete:true,hasIssue:true,intervals:[{kind:'dropout',startS:4.9,endS:6.8},{kind:'clipped',startS:8,endS:8.3}]})
 })
 it('treats absent, partial or duplicate observations as unknown, not healthy',()=>{
  expect(microphoneEvidence(null,'mic_1')).toMatchObject({unknownMs:12000,complete:false,hasIssue:false})
  const before=run();before.samples=before.samples.filter(s=>s.offset_ms!==5000)
  before.samples.push({...before.samples[0]})
  expect(microphoneEvidence(before,'mic_1')).toMatchObject({unknownMs:200,complete:false})
 })
 it('recognizes healthy complete samples and separates microphones and the terminal marker',()=>{
  const before=run();before.samples.at(-1)!.is_dropout=true
  expect(microphoneEvidence(before,'mic_1')).toMatchObject({dropoutMs:0,unknownMs:0,complete:true,hasIssue:false})
  expect(microphoneEvidence(before,'mic_2').unknownMs).toBe(12000)
 })
})
