import type {Run} from './types'
export type Condition = 'received' | 'dropout' | 'clipped' | 'unknown'
export function conditionAt(run: Run | null, micId: string, timeMs: number): Condition {
 if (!run || timeMs < 0 || timeMs >= 12000) return 'unknown'
 const offset = Math.floor(timeMs / 100) * 100
 const rows = run.samples.filter(s => s.mic_id === micId && s.offset_ms === offset)
 if (rows.length !== 1 || !Number.isFinite(rows[0].quality)) return 'unknown'
 return rows[0].is_dropout ? 'dropout' : rows[0].is_clipped ? 'clipped' : 'received'
}
/** Same decoded source, length, sample rate and unity gain; only measured run masks differ.
 * Clipping is a deterministic hard limit, never amplification or restoration. Missing evidence is silent.
 */
export function renderMask(source: Float32Array, sampleRate: number, run: Run | null, micId: string, backupId?:string): Float32Array {
 const result = new Float32Array(source.length)
 const masks = Array.from({length:120}, (_,i) => playbackCondition(run,micId,i*100,backupId))
 for(let i=0;i<source.length;i++) {
  const state=masks[Math.floor(i*1000/sampleRate/100)] ?? 'unknown'
  result[i] = state === 'received' ? source[i] : state === 'clipped' ? Math.max(-0.18,Math.min(0.18,source[i])) : 0
 }
 return result
}

export function playbackCondition(run:Run|null,micId:string,timeMs:number,backupId?:string):Condition{const primary=conditionAt(run,micId,timeMs);return backupId&&(primary==='dropout'||primary==='clipped')&&conditionAt(run,backupId,timeMs)==='received'?'received':primary}
