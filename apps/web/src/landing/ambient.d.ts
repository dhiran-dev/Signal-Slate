declare module '*.json' {
  const value: {
    dialogue: string
    timing_precision: string
    disclosure: string
    phrases: Array<{
      index: number
      text: string
      approx_start_seconds: number
      approx_end_seconds: number
      approx_start_ms: number
      approx_end_ms: number
      critical_word?: string
      is_critical: boolean
    }>
  }
  export default value
}
