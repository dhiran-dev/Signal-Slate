export interface CaptionPhrase {
  index: number
  text: string
  approx_start_seconds: number
  approx_end_seconds: number
  approx_start_ms: number
  approx_end_ms: number
  critical_word?: string
  is_critical: boolean
}

export interface CaptionsData {
  dialogue: string
  timing_precision: string
  disclosure: string
  phrases: CaptionPhrase[]
}

export interface QualitativeChannelState {
  id: string
  name: string
  role: string
  status: 'dropout' | 'marginal' | 'clear'
}
