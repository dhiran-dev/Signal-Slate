import {useEffect, useRef, useState} from 'react'
import audioUrl from '../../../../assets/audio/critical_line_12s.wav'
import captions from '../../../../assets/audio/captions.json'
import {conditionAt, playbackCondition, renderMask, type Condition} from './audio'
import type {Run, Session} from './types'

type Track = 'before' | 'after'
type Transport = {ctx: AudioContext; gain: GainNode; buffer: AudioBuffer; source?: AudioBufferSourceNode; started: number; offset: number}
export interface RehearsalAudioState {
  currentTime: number; isPlaying: boolean; isMuted: boolean; activeTrack: Track
  selectedMicId: string; selectMic: (id: string) => void
  error: string; currentPhrase: string; condition: Condition; receiverCondition: Condition
  playRawSample: () => void; pause: () => void
  playSection: (startS?: number, micId?: string) => void
  playTrack: (track: Track) => void; seek: (time: number) => void
  seekTrack: (track: Track, time: number) => void; toggleMute: () => void
}

/** One output at a time: the setup sample is raw; measured takes use the same PCM with actual run masks. */
export function useRehearsalAudio(session: Session | null, step = 'scene'): RehearsalAudioState {
  const [currentTime, setCurrentTime] = useState(0)
  const [isPlaying, setIsPlaying] = useState(false)
  const [isMuted, setIsMuted] = useState(false)
  const [activeTrack, setActiveTrack] = useState<Track>('before')
  const [selectedMicId, setSelectedMicId] = useState('mic_1')
  const [error, setError] = useState('')
  const [mode, setMode] = useState<'raw' | 'masked'>('raw')
  const state = useRef({time: 0, playing: false, muted: false, track: 'before' as Track, mic: 'mic_1', mode: 'raw' as 'raw' | 'masked'})
  const latestSession = useRef(session)
  latestSession.current = session
  const generation = useRef(0)
  const lifecycle = useRef(0)
  const mounted = useRef(false)
  const audioEl = useRef<HTMLAudioElement | null>(null)
  const transport = useRef<Transport | null>(null)
  const pendingTransport = useRef<Promise<Transport> | null>(null)

  function clockTime() {
    if (!state.current.playing) return state.current.time
    const t = transport.current
    const time = state.current.mode === 'raw' ? audioEl.current?.currentTime : t ? t.offset + t.ctx.currentTime - t.started : state.current.time
    return Math.max(0, Math.min(12, time ?? state.current.time))
  }
  function updateTime(time: number) {state.current.time = time; setCurrentTime(time)}
  function updatePlaying(playing: boolean) {state.current.playing = playing; setIsPlaying(playing)}
  function stopOutputs() {
    const source = transport.current?.source
    if (source) {
      source.onended = null
      try {source.stop()} catch { /* Already ended. */ }
      source.disconnect()
      transport.current!.source = undefined
    }
    audioEl.current?.pause()
  }
  function pause() {
    const time = clockTime()
    generation.current++
    stopOutputs()
    updatePlaying(false)
    updateTime(time)
  }
  function ended(ticket: number) {
    if (!mounted.current || generation.current !== ticket) return
    updatePlaying(false)
    updateTime(0)
  }

  useEffect(() => {
    mounted.current = true
    lifecycle.current++
    const el = new Audio(audioUrl)
    el.preload = 'metadata'
    audioEl.current = el
    return () => {
      mounted.current = false
      lifecycle.current++
      generation.current++
      stopOutputs()
      el.onended = null
      audioEl.current = null
      const t = transport.current
      transport.current = null
      pendingTransport.current = null
      if (t) void t.ctx.close()
    }
  }, [])

  useEffect(() => {
    pause()
    updateTime(0)
    setError('')
    state.current.track = 'before'
    setActiveTrack('before')
    if (step === 'scene') {state.current.mode = 'raw'; setMode('raw')}
    else {state.current.mode = 'masked'; setMode('masked')}
  }, [session?.id, step])

  useEffect(() => {
    if (!isPlaying) return
    let frame: number
    const tick = () => {
      const next = clockTime()
      updateTime(next)
      if (next >= 12) {pause(); updateTime(0); return}
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [isPlaying])

  async function ensureTransport(): Promise<Transport> {
    if (transport.current) return transport.current
    if (pendingTransport.current) return pendingTransport.current
    const lifetime = lifecycle.current
    const pending = (async () => {
      const AudioCtx = window.AudioContext || (window as unknown as {webkitAudioContext: typeof AudioContext}).webkitAudioContext
      if (!AudioCtx) throw new Error('Web Audio is unavailable.')
      const ctx = new AudioCtx()
      try {
        const response = await fetch(audioUrl)
        if (!response.ok) throw new Error('Sample audio unavailable.')
        const buffer = await ctx.decodeAudioData(await response.arrayBuffer())
        if (!mounted.current || lifecycle.current !== lifetime) throw new Error('Playback closed.')
        const gain = ctx.createGain()
        gain.connect(ctx.destination)
        const result = {ctx, gain, buffer, started: 0, offset: 0}
        transport.current = result
        return result
      } catch (e) {await ctx.close(); throw e}
    })()
    pendingTransport.current = pending
    try {return await pending}
    finally {if (pendingTransport.current === pending) pendingTransport.current = null}
  }

  async function startRaw(offset: number) {
    pause()
    const ticket = ++generation.current
    state.current.mode = 'raw'; setMode('raw'); setError('')
    const el = audioEl.current
    if (!el) return
    el.currentTime = offset >= 12 ? 0 : offset
    el.muted = state.current.muted
    el.onended = () => ended(ticket)
    try {
      await el.play()
      if (!mounted.current || ticket !== generation.current) return
      updateTime(el.currentTime)
      updatePlaying(true)
    } catch {
      if (mounted.current && ticket === generation.current) {
        updatePlaying(false); setError('Sample audio could not play. Try Play sample again.')
      }
    }
  }
  function playRawSample() {
    if (state.current.playing && state.current.mode === 'raw') pause()
    else void startRaw(clockTime())
  }

  async function startMasked(track: Track, offset: number, micId: string) {
    pause()
    const ticket = ++generation.current
    state.current.mode = 'masked'; setMode('masked')
    state.current.track = track; setActiveTrack(track)
    state.current.mic = micId; setSelectedMicId(micId)
    setError('')
    const saved = latestSession.current
    const run: Run | null = (track === 'after' ? saved?.comparison : saved?.baseline) ?? null
    if (!run) {setError('Run this sound check before playing its measured audio.'); return}
    const config = track === 'after' ? saved?.comparison_config : saved?.baseline_config
    try {
      const t = await ensureTransport()
      await t.ctx.resume()
      if (!mounted.current || ticket !== generation.current) return
      const rendered = t.ctx.createBuffer(t.buffer.numberOfChannels, t.buffer.length, t.buffer.sampleRate)
      for (let ch = 0; ch < t.buffer.numberOfChannels; ch++) {
        rendered.getChannelData(ch).set(renderMask(t.buffer.getChannelData(ch), t.buffer.sampleRate, run, micId, config?.backup_sources?.[micId]))
      }
      const source = t.ctx.createBufferSource()
      source.buffer = rendered
      source.playbackRate.value = 1
      source.connect(t.gain)
      t.gain.gain.value = state.current.muted ? 0 : 1
      t.source = source
      t.offset = offset >= 12 ? 0 : offset
      t.started = t.ctx.currentTime
      source.onended = () => ended(ticket)
      source.start(0, t.offset)
      updateTime(t.offset)
      updatePlaying(true)
    } catch {
      if (mounted.current && ticket === generation.current) {
        updatePlaying(false); setError('Measured audio could not play. Try the play button again.')
      }
    }
  }
  function playSection(startS = 4.9, micId = state.current.mic) {
    void startMasked('before', Math.max(0, Math.min(12, startS)), micId)
  }
  function playTrack(track: Track) {
    if (state.current.playing && state.current.mode === 'masked' && state.current.track === track) pause()
    else void startMasked(track, clockTime(), state.current.mic)
  }
  function selectMic(id: string) {
    if (!latestSession.current?.shot_context.mic_ids.includes(id)) return
    pause()
    state.current.mic = id
    setSelectedMicId(id)
  }
  function seek(time: number) {
    const next = Number.isFinite(time) ? Math.max(0, Math.min(12, time)) : 0
    const wasPlaying = state.current.playing
    const playbackMode = state.current.mode
    pause()
    updateTime(next)
    if (wasPlaying && next < 12) {
      if (playbackMode === 'raw') void startRaw(next)
      else void startMasked(state.current.track, next, state.current.mic)
    }
  }
  function seekTrack(track: Track, time: number) {
    const next = Number.isFinite(time) ? Math.max(0, Math.min(12, time)) : 0
    const wasPlaying = state.current.playing
    pause()
    state.current.mode = 'masked'; setMode('masked')
    state.current.track = track; setActiveTrack(track)
    updateTime(next)
    if (wasPlaying && next < 12) void startMasked(track, next, state.current.mic)
  }
  function toggleMute() {
    const muted = !state.current.muted
    state.current.muted = muted; setIsMuted(muted)
    if (audioEl.current) audioEl.current.muted = muted
    if (transport.current) transport.current.gain.gain.value = muted ? 0 : 1
  }
  const currentPhrase = captions.phrases.find(p => currentTime * 1000 >= p.approx_start_ms && currentTime * 1000 < p.approx_end_ms)?.text
    || (currentTime < 0.5 ? 'Dialogue begins at approximately 0.5 seconds.' : 'End of dialogue.')
  const run = (activeTrack === 'after' ? session?.comparison : session?.baseline) ?? null
  const config = activeTrack === 'after' ? session?.comparison_config : session?.baseline_config
  const condition = mode === 'raw' ? 'received' : playbackCondition(run, selectedMicId, currentTime * 1000, config?.backup_sources?.[selectedMicId])
  const receiverCondition = mode === 'raw' ? 'received' : conditionAt(run, selectedMicId, currentTime * 1000)
  return {currentTime, isPlaying, isMuted, activeTrack, selectedMicId, selectMic, error, currentPhrase, condition, receiverCondition,
    playRawSample, pause, playSection, playTrack, seek, seekTrack, toggleMute}
}
