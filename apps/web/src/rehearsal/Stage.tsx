import {conditionAt} from './audio'
import type {Run,Session} from './types'
export function Stage({run,context,time,micId}:{run:Run|null;context:Session['shot_context'];time:number;micId:string}) {
 const condition=conditionAt(run,micId,time*1000)
 return <figure className="sl-stage"><svg viewBox="0 0 600 150" role="img" aria-label={`Illustrative stage path at ${time.toFixed(1)} seconds; ${context.performer_names[micId]||micId}: ${condition}`}>
 <rect x="1" y="1" width="598" height="148" rx="12" fill="#08221c" stroke="#436052"/>
 <text x="20" y="27" fill="#b9ccc8" fontSize="11">ILLUSTRATIVE STAGE · SELECTED RECEIVER</text>
 <path d="M30 85 H570" stroke="#718e80" strokeWidth="3" strokeDasharray="5 6"/>
 {run?.samples.filter(s=>s.mic_id===micId&&s.offset_ms<12000&&(s.is_dropout||s.is_clipped)).map(s=><line key={s.offset_ms} x1={30+s.offset_ms/12000*540} x2={30+(s.offset_ms+100)/12000*540} y1="85" y2="85" stroke={s.is_dropout?'#ff887b':'#ffd077'} strokeWidth="8"/>)}
 <circle cx={30+time/12*540} cy="85" r="10" fill="#5af0bf" stroke="#edfffe" strokeWidth="2"/>
 <text x="20" y="133" fill="#b9ccc8" fontSize="11">START</text><text x="510" y="133" fill="#b9ccc8" fontSize="11">12s END</text>
 </svg><figcaption>{context.performer_names[micId]||micId} · {condition==='unknown'?'No observation at playhead':condition} · stage distance is illustrative, timing follows evidence.</figcaption></figure>
}
