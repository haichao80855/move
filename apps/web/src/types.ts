export type Stage = 'prepare' | 'transcribe' | 'retranscribe' | 'translate' | 'dub' | 'export'
export interface Cue {
  id: string
  start: number
  end: number
  original: string
  translation: string
  revision: number
  audio_ready: boolean
  audio_duration: number | null
}
export interface Job {
  id: string
  stage: Stage
  status: string
  progress: number
  message: string
  error: string | null
  created: number
}
export interface Project {
  id: string
  name: string
  source_name: string
  created: number
  updated: number
  metadata: { duration: number; width: number; height: number; codec: string; has_audio: boolean }
  cue_count?: number
  translated_count?: number
  latest_job?: Job | null
  cues: Cue[]
  jobs: Job[]
  preview_ready: boolean
  audio_ready: boolean
  export_ready: boolean
  export_current: boolean
  dubbing_ready: boolean
}
export interface Settings {
  translation_provider: 'deepseek' | 'qwen'
  deepseek_model: string
  qwen_model: string
  qwen_region: 'cn' | 'global'
  tts_model: string
  tts_provider: 'qwen3_mlx'
  reference_id: string
  speed: number
  glossary: string
  translation_style: string
  credentials: Record<string, boolean>
}
export interface System {
  platform: string
  architecture: string
  ffmpeg: boolean
  ffprobe: boolean
  asr: boolean
  apple_silicon: boolean
  asr_note: string
}
