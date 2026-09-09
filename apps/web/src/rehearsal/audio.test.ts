import {describe,it,expect} from 'vitest'
import {conditionAt,renderMask} from './audio'
import type {Run} from './types'
const run:Run={run_id:'r',config_hash:'h',completion_marker_present:true,metrics:[],samples:Array.from({length:121},(_,i)=>({mic_id:'m',offset_ms:i*100,quality:90,is_dropout:i===49,is_clipped:i===50}))}
describe('Measured audio mask',()=>{
 it('preserves source bytes and unity gain outside exact half-open mask intervals',()=>{const source=new Float32Array(12000).fill(.4);const before=source.slice();const rendered=renderMask(source,1000,run,'m');expect(source).toEqual(before);expect(rendered.length).toBe(source.length);expect(rendered[4899]).toBe(source[4899]);expect(rendered[4900]).toBe(0);expect(rendered[4999]).toBe(0);expect(rendered[5000]).toBeCloseTo(.18);expect(rendered[5099]).toBeCloseTo(.18);expect(rendered[5100]).toBe(source[5100])})
 it('clips symmetrically without altering low-level amplitudes',()=>{const source=new Float32Array(12000).fill(-.7);source[5001]=.1;const rendered=renderMask(source,1000,run,'m');expect(rendered[5000]).toBeCloseTo(-.18);expect(rendered[5001]).toBe(source[5001])})
 it('fails closed for missing and conflicting evidence, never uses the endpoint sample',()=>{expect(conditionAt(run,'m',12000)).toBe('unknown');expect(conditionAt(run,'missing',500)).toBe('unknown');expect(conditionAt({...run,samples:[...run.samples,run.samples[0]]},'m',0)).toBe('unknown');expect(renderMask(new Float32Array(10).fill(1),1000,null,'m')).toEqual(new Float32Array(10))})
 it('same source timebase and gain gives exact healthy A/B parity',()=>{const source=Float32Array.from({length:288000},(_,i)=>Math.sin(i/20)*.1);const healthy={...run,samples:run.samples.map(s=>({...s,is_dropout:false,is_clipped:false}))};expect(renderMask(source,24000,healthy,'m')).toEqual(source)})
})

import {publicReport} from './report'
import type {Session} from './types'
it('report export excludes ownership and private state even when present',()=>{const report=publicReport({id:'session-1',csrf_token:'private-csrf',revision:1,mode:'preview',state:'READY',baseline:run,comparison:null,confirmed_constraints:[],candidate_plans:[],verification:null} as unknown as Session);expect(report).not.toHaveProperty('id');expect(JSON.stringify(report)).not.toContain('private-csrf');expect(report.baseline?.run_id).toBe('r')})

it('approved backup fills only measured faults without changing receiver evidence',()=>{const source=new Float32Array(12000).fill(.4);const withBackup={...run,samples:[...run.samples,...run.samples.map(s=>({...s,mic_id:'boom',is_dropout:false,is_clipped:false}))]};const rendered=renderMask(source,1000,withBackup,'m','boom');expect(rendered[4900]).toBe(source[4900]);expect(conditionAt(withBackup,'m',4900)).toBe('dropout');expect(renderMask(source,1000,run,'m','missing')[4900]).toBe(0)})
