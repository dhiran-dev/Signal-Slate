import type {Action, Constraint, Run} from './types'
export interface SoundInterval {kind:'dropout'|'clipped'|'unknown'|'weak'; startS:number; endS:number}
/** User-facing facts come from returned readings, including missing/duplicate evidence. */
export function microphoneEvidence(run:Run|null, micId:string, durationMs=12000) {
 const intervals:SoundInterval[]=[]
 const byTime=new Map<number,NonNullable<Run['samples']>>()
 for(const sample of run?.samples??[]){if(sample.mic_id!==micId)continue;const rows=byTime.get(sample.offset_ms)??[];rows.push(sample);byTime.set(sample.offset_ms,rows)}
 let dropoutMs=0, clippingMs=0, unknownMs=0, weakMs=0
 for(let offset=0;offset<durationMs;offset+=100){
  const rows=byTime.get(offset)??[]
  const row=rows.length===1?rows[0]:null
  const kind:SoundInterval['kind']|null=!row||!Number.isFinite(row.quality)?'unknown':row.is_dropout?'dropout':row.is_clipped?'clipped':row.quality<70?'weak':null
  if(kind==='dropout')dropoutMs+=100
  if(kind==='clipped')clippingMs+=100
  if(kind==='unknown')unknownMs+=100
  if(kind==='weak')weakMs+=100
  if(kind){const last=intervals.at(-1);if(last?.kind===kind&&last.endS===offset/1000)last.endS=(offset+100)/1000;else intervals.push({kind,startS:offset/1000,endS:(offset+100)/1000})}
 }
 return {micId,dropoutMs,clippingMs,unknownMs,weakMs,intervals,hasIssue:dropoutMs+clippingMs+weakMs>0,complete:unknownMs===0}
}
export function receiverSummary(run: Run | null, mic: string) {
 const samples=run?.samples.filter(s=>s.mic_id===mic&&s.offset_ms<12000)??[]
 return {minQuality:samples.length?Math.min(...samples.map(s=>s.quality)):null,dropoutMs:samples.filter(s=>s.is_dropout).length*100,clippingMs:samples.filter(s=>s.is_clipped).length*100,sampleCount:samples.length}
}
export function soundSummary(evidence: ReturnType<typeof microphoneEvidence>) {
 if(!evidence.complete)return `${(evidence.unknownMs/1000).toFixed(1)}s of readings missing`
 const problems:string[]=[]
 if(evidence.dropoutMs)problems.push(`${(evidence.dropoutMs/1000).toFixed(1)}s sound missing`)
 if(evidence.clippingMs)problems.push(`${(evidence.clippingMs/1000).toFixed(1)}s distorted`)
 if(evidence.weakMs)problems.push(`${(evidence.weakMs/1000).toFixed(1)}s weak signal`)
 return problems.length?problems.join(' · '):'No sound issues'
}
export function vetoReason(action:Action, constraints:Constraint[]) {
 const exclusion=constraints.find(c=>c.confirmed&&c.kind==='CHANNEL_EXCLUSION'&&(!c.target_mic||c.target_mic===action.mic_id)&&action.action_type==='CHANNEL_SWITCH'&&c.parameters.excluded_channel===action.parameters.channel)
 if(exclusion)return `Channel ${String(action.parameters.channel)} is excluded by your confirmed constraint.`
 const boom=constraints.find(c=>c.confirmed&&c.kind==='BOOM_EXCLUSION'&&(!c.target_mic||c.target_mic===action.mic_id)&&action.action_type==='BOOM_COVERAGE')
 if(boom)return 'Your confirmed constraint excludes backup coverage.'
 const lock=constraints.find(c=>c.confirmed&&((c.kind==='ANTENNA_LOCK'&&action.action_type==='ANTENNA_SWITCH'&&action.parameters.antenna!==c.parameters.locked_antenna)||(c.kind==='RIG_LOCK'&&(!c.target_mic||c.target_mic===action.mic_id)&&!['NO_ACTION','BOOM_COVERAGE'].includes(action.action_type))))
 return lock?'Your confirmed lock prevents this change.':null
}
