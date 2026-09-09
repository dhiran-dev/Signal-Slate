/**
 * Exact peak amplitudes decoded from assets/audio/critical_line_12s.wav.
 * 240 buckets corresponding to 50ms intervals across the 12.0s duration.
 * Normalized to 0..1 based on max 16-bit PCM amplitude.
 */
export const PCM_PEAKS_240: number[] = [
  0,0,0,0,0,0,0,0,0,0,0.002,0.02,0.03,0.046,0.044,0.113,0.392,0.604,0.335,0.684,
  0.636,0.49,0.651,0.481,0.448,0.301,0.365,0.26,0.453,0.361,0.356,0.385,0.361,0.331,0.216,0.189,0.067,0.45,0.175,0.384,
  0.232,0.173,0.299,0.031,0.024,0.535,0.394,0.164,0.053,0.04,0.21,0.227,0.267,0.265,0.248,0.325,0.408,0.195,0.047,0.465,
  0.29,0.357,0.044,0.356,0.235,0.593,0.675,0.413,0.245,0.173,0.313,0.098,0.362,0.346,0.314,0.378,0.298,0.459,0.53,0.346,
  0.414,0.335,0.376,0.366,0.253,0.252,0.136,0.155,0.249,0.183,0.074,0.098,0.085,0.034,0.19,0.877,0.881,0.113,0.021,0.51,
  0.64,0.306,0.405,0.301,0.262,0.248,0.308,0.26,0.181,0.684,0.27,0.238,0.438,0.049,0.067,0.056,0.031,0.068,0.429,0.545,
  0.453,0.403,0.395,0.675,0.446,0.58,0.269,0.022,0.223,0.315,0.566,0.043,0.728,0.687,0.061,0.027,0.173,0.316,0.253,0.159,
  0.188,0.189,0.199,0.486,0.28,0.343,0.209,0.462,0.292,0.009,0.627,0.392,0.63,0.384,0.373,0.422,0.464,0.258,0.154,0.456,
  0.317,0.519,0.428,0.134,0.253,0.389,0.308,0.143,0.189,0.199,0.381,0.465,0.377,0.302,0.447,0.026,0.121,0.05,0.474,0.468,
  0.409,0.257,0.746,0.585,0.524,0.309,0.061,0.313,0.309,0.174,0.118,0.035,0.002,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
]

export const PCM_PEAKS_120: number[] = Array.from({ length: 120 }, (_, i) => {
  return Math.max(PCM_PEAKS_240[i * 2], PCM_PEAKS_240[i * 2 + 1])
})

export const PCM_PEAKS_960: number[] = Array.from({ length: 960 }, (_, i) => {
  const index = (i / 960) * (PCM_PEAKS_240.length - 1)
  const lower = Math.floor(index)
  const upper = Math.ceil(index)
  const weight = index - lower
  const val = PCM_PEAKS_240[lower] * (1 - weight) + PCM_PEAKS_240[upper] * weight
  return Number(val.toFixed(3))
})

export function extractPeaksFromBuffer(buffer: AudioBuffer, buckets: number = 240): number[] {
  const channelData = buffer.getChannelData(0)
  const samplesPerBucket = Math.floor(channelData.length / buckets)
  const peaks: number[] = []
  for (let b = 0; b < buckets; b++) {
    let max = 0
    for (let s = 0; s < samplesPerBucket; s++) {
      const val = Math.abs(channelData[b * samplesPerBucket + s])
      if (val > max) max = val
    }
    peaks.push(Number(max.toFixed(3)))
  }
  return peaks
}
