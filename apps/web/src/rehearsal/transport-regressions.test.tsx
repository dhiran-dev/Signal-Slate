import {act, cleanup, renderHook, waitFor} from '@testing-library/react'
import {afterEach, beforeEach, expect, it, vi} from 'vitest'
import {useRehearsalAudio} from './useRehearsalAudio'
import type {Session} from './types'
const session:Session={id:'audio-session',csrf_token:'csrf',revision:1,state:'BASELINE_READY',mode:'preview',shot_context:{duration_ms:12000,mic_ids:['mic_1','mic_2'],performer_names:{mic_1:'Elena',mic_2:'Marcus'},transcript:'',critical_dialogue_text:'',critical_line_start_ms:4900,critical_line_end_ms:6800},baseline:{run_id:'before',config_hash:'config',metrics:[],completion_marker_present:true,samples:Array.from({length:120},(_,i)=>['mic_1','mic_2'].map(mic_id=>({offset_ms:i*100,mic_id,quality:90,is_dropout:mic_id==='mic_1'&&i>=49&&i<68,is_clipped:false}))).flat()},comparison:null,finding:null,candidate_plans:[],confirmed_constraints:[],interpretation:null,approval:null,verification:null,error:null}
let raw: {currentTime:number;muted:boolean;preload:string;play:ReturnType<typeof vi.fn>;pause:ReturnType<typeof vi.fn>;onended:(()=>void)|null}
let sources: {buffer: AudioBuffer|null;start:ReturnType<typeof vi.fn>;stop:ReturnType<typeof vi.fn>;onended:(()=>void)|null}[]
let contexts:number
function buffer(){const pcm=new Float32Array(12000).fill(0.4);return{numberOfChannels:1,length:12000,sampleRate:1000,getChannelData:()=>pcm}as unknown as AudioBuffer}
beforeEach(()=>{
  contexts=0;sources=[]
  vi.stubGlobal('Audio',class{constructor(){raw={currentTime:0,muted:false,preload:'',play:vi.fn().mockResolvedValue(undefined),pause:vi.fn(),onended:null};return raw}})
  vi.stubGlobal('AudioContext',class{
    currentTime=0;destination={};constructor(){contexts++}
    close=vi.fn().mockResolvedValue(undefined);resume=vi.fn().mockResolvedValue(undefined)
    decodeAudioData=vi.fn().mockResolvedValue(buffer())
    createBuffer=buffer
    createGain=()=>({gain:{value:1},connect:vi.fn()})
    createBufferSource=()=>{const source={buffer:null,playbackRate:{value:1},connect:vi.fn(),disconnect:vi.fn(),start:vi.fn(),stop:vi.fn(),onended:null};sources.push(source);return source}
  })
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,arrayBuffer:async()=>new ArrayBuffer(0)}))
})
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('seeks and resumes raw playback from the requested offset without a stale pause toggle',async()=>{
  const {result}=renderHook(()=>useRehearsalAudio(null))
  expect(raw.play).not.toHaveBeenCalled()
  act(()=>result.current.playRawSample())
  await waitFor(()=>expect(result.current.isPlaying).toBe(true))
  act(()=>result.current.seek(6))
  await waitFor(()=>expect(result.current.isPlaying).toBe(true))
  expect(raw.currentTime).toBe(6)
  expect(raw.play).toHaveBeenCalledTimes(2)
  expect(sources).toHaveLength(0)
})
it('shares pending decoding and cancels every old measured start when raw playback is chosen',async()=>{
  let release:(value:Response)=>void=()=>{}
  vi.mocked(fetch).mockImplementation(()=>new Promise(resolve=>{release=resolve}) as Promise<Response>)
  const {result}=renderHook(()=>useRehearsalAudio(session,'sound'))
  act(()=>{result.current.playSection(4.9);result.current.playSection(5.1)})
  expect(contexts).toBe(1)
  act(()=>result.current.playRawSample())
  await waitFor(()=>expect(raw.play).toHaveBeenCalledTimes(1))
  await act(async()=>{release({ok:true,arrayBuffer:async()=>new ArrayBuffer(0)} as Response);await new Promise(resolve=>setTimeout(resolve,0))})
  expect(sources).toHaveLength(0)
  expect(result.current.isPlaying).toBe(true)
})
it('changes the measured microphone and captions together and pauses when leaving the step',async()=>{
  const {result,rerender}=renderHook(({step})=>useRehearsalAudio(session,step),{initialProps:{step:'sound'}})
  act(()=>result.current.playSection(5,'mic_1'))
  await waitFor(()=>expect(sources).toHaveLength(1))
  expect(sources[0].buffer!.getChannelData(0)[5000]).toBe(0)
  expect(result.current.condition).toBe('dropout')
  act(()=>result.current.selectMic('mic_2'))
  expect(result.current.isPlaying).toBe(false)
  expect(result.current.currentTime).toBe(5)
  act(()=>result.current.playTrack('before'))
  await waitFor(()=>expect(sources).toHaveLength(2))
  expect(sources[1].buffer!.getChannelData(0)[5000]).toBeGreaterThan(0)
  expect(result.current.condition).toBe('received')
  expect(raw.play).not.toHaveBeenCalled()
  rerender({step:'change'})
  expect(result.current.isPlaying).toBe(false)
  expect(sources[1].stop).toHaveBeenCalled()
})

it('seeking the other take stops the old source and selects that take without starting both',async()=>{
  const after={...session.baseline!,run_id:'after',samples:session.baseline!.samples.map(s=>({...s,is_dropout:false}))}
  const {result}=renderHook(()=>useRehearsalAudio({...session,comparison:after},'compare'))
  act(()=>result.current.seekTrack('before',5))
  expect(sources).toHaveLength(0)
  act(()=>result.current.playTrack('before'))
  await waitFor(()=>expect(sources).toHaveLength(1))
  expect(sources[0].buffer!.getChannelData(0)[5000]).toBe(0)
  act(()=>result.current.seekTrack('after',5))
  await waitFor(()=>expect(sources).toHaveLength(2))
  expect(sources[0].stop).toHaveBeenCalledTimes(1)
  expect(sources[1].buffer!.getChannelData(0)[5000]).toBeGreaterThan(0)
  expect(sources[1].start).toHaveBeenCalledWith(0,5)
  expect(result.current.activeTrack).toBe('after')
  act(()=>result.current.pause())
  act(()=>result.current.seekTrack('before',6))
  expect(sources).toHaveLength(2)
  expect(result.current.activeTrack).toBe('before')
  expect(result.current.isPlaying).toBe(false)
  expect(result.current.currentTime).toBe(6)
})
