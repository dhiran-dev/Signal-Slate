import {useEffect, useRef, useState} from 'react'
import captions from '../../../../assets/audio/captions.json'
import {conditionAt, playbackCondition, renderMask} from './audio'
import {Stage} from './Stage'
import audioUrl from '../../../../assets/audio/critical_line_12s.wav'
import type {Run, Session} from './types'
import {receiverSummary} from './evidence'
export function Timeline({session}: {session: Session}) {
 const generation=useRef(0)
 const mounted=useRef(true)
 const loading=useRef(false)
 const audio = useRef<HTMLAudioElement>(null)
 const transport=useRef<{ctx:AudioContext;gain:GainNode;buffer:AudioBuffer;source?:AudioBufferSourceNode;started:number;offset:number}|null>(null)
 const [micId,setMicId]=useState(session.shot_context.mic_ids[0])
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;transport.current?.source?.stop();void transport.current?.ctx.close()}},[])
 const [time,setTime] = useState(0)
 const [playing,setPlaying] = useState(false)
 const [muted,setMuted] = useState(true)
 const [comparison,setComparison] = useState(false)
 const [error,setError] = useState('')
 useEffect(()=>{if(!playing)return;let frame:number;function tick(){const t=transport.current;if(t){const next=Math.min(12,t.offset+t.ctx.currentTime-t.started);setTime(next);if(next>=12){setPlaying(false);return}}frame=requestAnimationFrame(tick)}frame=requestAnimationFrame(tick);return()=>cancelAnimationFrame(frame)},[playing])
 const run: Run | null = comparison ? session.comparison : session.baseline
 const config=comparison?session.comparison_config:session.baseline_config
 const backupId=config?.backup_sources?.[micId]
 const context = session.shot_context
 function pause(){generation.current++;if(transport.current?.source){transport.current.source.onended=null;transport.current.source.stop();transport.current.source=undefined}setPlaying(false)}
 async function play() {
  if(playing){pause();return}
  if(loading.current)return
  loading.current=true
  const ticket=++generation.current
  try {
   if(!transport.current){const ctx=new AudioContext();const response=await fetch(audioUrl);if(!response.ok)throw new Error('Audio unavailable');const buffer=await ctx.decodeAudioData(await response.arrayBuffer());if(!mounted.current){await ctx.close();return}const gain=ctx.createGain();gain.gain.value=0;gain.connect(ctx.destination);transport.current={ctx,gain,buffer,started:0,offset:0}}
   const t=transport.current;await t.ctx.resume();if(!mounted.current||ticket!==generation.current)return;const rendered=t.ctx.createBuffer(t.buffer.numberOfChannels,t.buffer.length,t.buffer.sampleRate)
   for(let channel=0;channel<t.buffer.numberOfChannels;channel++)rendered.getChannelData(channel).set(renderMask(t.buffer.getChannelData(channel),t.buffer.sampleRate,run,micId,backupId))
   const source=t.ctx.createBufferSource();source.buffer=rendered;source.playbackRate.value=1;source.connect(t.gain);t.gain.gain.value=muted?0:1;t.source=source;t.offset=time>=12?0:time;t.started=t.ctx.currentTime;source.start(0,t.offset);setPlaying(true)
  }catch{setError('Audio could not play. You can still scrub the evidence timeline.')}finally{loading.current=false}
 }
 function seek(next:number){pause();setTime(next)}
 const condition=playbackCondition(run,micId,time*1000,backupId)
 const receiverCondition=conditionAt(run,micId,time*1000)
 const phrase=captions.phrases.find(p=>time*1000>=p.approx_start_ms&&time*1000<p.approx_end_ms)
 return <section className="sl-panel" aria-label="Dialogue and receiver evidence">
  <div className="sl-row"><div><p className="sl-eyebrow">SHOT 012 / EXTERIOR ALLEYWAY</p><h2>The line we need to keep.</h2></div><span className="sl-tag">12 seconds · 4 receivers</span></div>
  <blockquote>“{context.critical_dialogue_text}”</blockquote>
  <p className="sl-muted">Approximate phrase interval {(context.critical_line_start_ms/1000).toFixed(1)}–{(context.critical_line_end_ms/1000).toFixed(1)}s. Original synthetic dialogue played through simulated receiver conditions. Identical source, speed and base gain for A/B; only observed dropout and clipping masks differ. This is not restoration. Unknown intervals are silent. Switching runs pauses at the same playhead.</p>
  <Stage run={run} context={context} time={time} micId={micId}/>
  {config&&<p className="sl-muted">Selected configuration: channel {config.channel_assignments[micId]??'—'} · antenna {config.antenna_selection}. {backupId?`Approved backup: ${context.performer_names[backupId]||backupId}. Simulated backup perspective; same source dialogue, not a separate boom recording. Backup covers dialogue only; receiver faults remain.`:'No backup routing.'}</p>}
  <label htmlFor="source-mic">Listen to receiver</label><select id="source-mic" value={micId} onChange={e=>{pause();setMicId(e.target.value)}}>{context.mic_ids.map(id=><option key={id} value={id}>{context.performer_names[id]||id}</option>)}</select>
  <p className="sl-caption" aria-label="Synchronized caption">{phrase?.text || (time<0.5?"Dialogue begins at approximately 0.5 seconds.":"End of dialogue.")} <strong>{condition==='dropout'?' [Simulated silence: dropout]':condition==='clipped'?' [Simulated clipping]':condition==='unknown'?' [No observation: muted]':receiverCondition!==condition?' [Dialogue covered by backup; receiver issue remains]':' [Received]'}</strong></p>
  <audio ref={audio} src={audioUrl} preload="metadata" muted onTimeUpdate={e=>setTime(e.currentTarget.currentTime)} onEnded={()=>setPlaying(false)} onError={()=>setError('Dialogue audio unavailable. Receiver evidence remains available.')} />
  <div className="sl-row sl-player"><button onClick={()=>void play()} aria-label={playing?'Pause dialogue':'Play dialogue'}>{playing?'Pause':'Play'} dialogue</button><button onClick={()=>{if(transport.current)transport.current.gain.gain.value=muted?1:0;setMuted(!muted)}}>{muted?'Unmute audio':'Mute audio'}</button><output>{time.toFixed(1)} / 12.0s</output></div>
  <label className="sl-sr" htmlFor="playhead">Shared dialogue playhead</label><input id="playhead" type="range" min="0" max="12" step="0.1" value={time} onChange={e=>seek(Number(e.target.value))} />
  {session.comparison&&<div className="sl-row"><button aria-pressed={!comparison} onClick={()=>{pause();setComparison(false)}}>Baseline</button><button aria-pressed={comparison} onClick={()=>{pause();setComparison(true)}}>Comparison</button></div>}
  <div className="sl-tracks">{context.mic_ids.map(id=><div className="sl-track" key={id}><span>{context.performer_names[id]||id}<small className="sl-track-stats">{run?`Min ${receiverSummary(run,id).minQuality?.toFixed(0)??'—'} · ${receiverSummary(run,id).dropoutMs}ms gap`:'Awaiting evidence'}</small></span><div className="sl-track-grid" aria-label={`${context.performer_names[id]||id}: ${run ? 'receiver samples' : 'waiting for baseline'}`}>
   {run?.samples.filter(s=>s.mic_id===id&&s.offset_ms<12000).map(s=><i key={s.offset_ms} title={`${(s.offset_ms/1000).toFixed(1)}s · quality ${s.quality.toFixed(0)}${s.is_dropout?' · dropout':''}${s.is_clipped?' · clipped':''}`} className={s.is_dropout?'gap':s.is_clipped?'clip':'healthy'} style={{height:`${Math.max(12,s.quality)}%`}} />)}
   <b className="sl-playhead" style={{left:`${time/12*100}%`}} />
  </div></div>)}</div>
  <p className="sl-muted">Mint: received · Coral: dropout · Amber: clipping. {run?`${run.samples.length} samples · ${run.metrics.length} metric summaries`:'No receiver evidence collected yet.'}</p>
  {run&&<details><summary>{comparison?'Comparison':'Baseline'} evidence · {run.run_id.slice(0,14)}…</summary><p className="sl-mono">Run: {run.run_id}<br/>Config SHA-256: {run.config_hash}</p></details>}
  {error&&<p role="alert">{error}</p>}
 </section>
}
