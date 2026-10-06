import { useEffect, useRef, useState } from 'react'
import { AudioLines, Loader2, Mic2, UploadCloud } from 'lucide-react'
import { active, api } from './api'
import type { Settings } from './types'

interface Reference {
  id: string
  name: string
  transcript: string
  duration: number
  audio_url: string
}
interface Task {
  id: string
  status: string
  progress: number
  message: string
  error: string | null
  audio_url: string | null
}
interface Status {
  supported: boolean
  runtime_installed: boolean
  model_ready: boolean
  model: string
  note: string
  task: Task | null
}

export function LocalTTSCard({
  value,
  change,
  notify,
}: {
  value: Settings
  change: (fields: Partial<Settings>) => void
  notify: (text: string, error?: boolean) => void
}) {
  const [status, setStatus] = useState<Status | null>(null)
  const [references, setReferences] = useState<Reference[]>([])
  const [file, setFile] = useState<File | null>(null)
  const [transcript, setTranscript] = useState('')
  const [editTranscript, setEditTranscript] = useState('')
  const [testText, setTestText] = useState('你好，欢迎使用 Move 视频翻译工作台。')
  const [pending, setPending] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [preview, setPreview] = useState<{ url: string; inputs: string } | null>(null)
  const previewInputs = useRef('')
  const completedTask = useRef('')
  const chosen = references.find((item) => item.id === value.reference_id)
  const inputs = JSON.stringify([value.reference_id, chosen?.transcript, value.speed, testText])
  const latestInputs = useRef(inputs)
  latestInputs.current = inputs
  const busy = pending || !!(status?.task && active(status.task.status))

  useEffect(() => {
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    async function refresh() {
      try {
        const next = await api<Status>('/tts/status')
        if (disposed) return
        setStatus(next)
        setLoadError('')
        if (
          next.task?.status === 'completed' &&
          next.task.audio_url &&
          completedTask.current !== next.task.id
        ) {
          completedTask.current = next.task.id
          if (previewInputs.current && previewInputs.current === latestInputs.current) {
            setPreview({ url: next.task.audio_url, inputs: previewInputs.current })
          }
        }
        timer = setTimeout(refresh, next.task && active(next.task.status) ? 1000 : 4000)
      } catch (e) {
        if (!disposed) {
          setLoadError((e as Error).message)
          timer = setTimeout(refresh, 4000)
        }
      }
    }
    refresh()
    api<Reference[]>('/tts/references')
      .then((items) => {
        if (!disposed) setReferences(items)
      })
      .catch((e) => {
        if (!disposed) setLoadError((e as Error).message)
      })
    return () => {
      disposed = true
      clearTimeout(timer)
    }
  }, [])

  useEffect(() => {
    setEditTranscript(chosen?.transcript || '')
  }, [chosen?.id, chosen?.transcript])

  async function request(action: () => Promise<void>) {
    setPending(true)
    try {
      await action()
    } catch (e) {
      notify((e as Error).message, true)
    } finally {
      setPending(false)
    }
  }

  async function upload() {
    if (!file) return
    await request(async () => {
      const form = new FormData()
      form.append('file', file)
      form.append('transcript', transcript)
      const item = await api<Reference>('/tts/references', { method: 'POST', body: form })
      setReferences((items) => [item, ...items])
      change({ reference_id: item.id })
      setFile(null)
      setTranscript('')
      notify('参考音频已上传并选中；试听无需先保存设置')
    })
  }

  async function start(path: string, body = {}) {
    await request(async () => {
      if (path === '/tts/preview') {
        previewInputs.current = inputs
        setPreview(null)
      }
      const task = await api<Task>(path, { method: 'POST', body: JSON.stringify(body) })
      setStatus((current) => (current ? { ...current, task } : current))
    })
  }

  return (
    <section className="settings-card local-tts-card">
      <div className="card-title">
        <span className="flow-icon tone-2">
          <Mic2 size={20} />
        </span>
        <div>
          <h2>中文配音 · 本地 Qwen3-TTS</h2>
          <p>Base 版本使用参考音频与对应文字，无需配音 API Key。</p>
        </div>
      </div>
      <div className="local-model-name">{value.tts_model}</div>
      <div className="system-line">
        <span>独立 MLX 环境</span>
        <strong className={status?.runtime_installed ? 'good' : ''}>
          {status?.runtime_installed
            ? '已安装'
            : status?.supported
              ? '待安装'
              : '需要 Apple Silicon Mac'}
        </strong>
      </div>
      <div className="system-line">
        <span>模型准备状态</span>
        <strong className={status?.model_ready ? 'good' : ''}>
          {status?.model_ready ? '已下载并验证加载' : '尚未准备'}
        </strong>
      </div>
      <p className="system-note">{loadError || status?.note || '正在检查本机环境…'}</p>
      {status?.supported && !status.runtime_installed && (
        <code className="install-command">./scripts/install-tts.sh</code>
      )}
      <button
        className="button"
        disabled={busy || !status?.runtime_installed}
        onClick={() => start('/tts/prepare')}
      >
        {busy ? <Loader2 size={16} className="spin" /> : <AudioLines size={16} />}
        {status?.model_ready ? '重新准备模型' : '下载并准备模型'}
      </button>
      <p className="system-note">
        模型准备会下载权重并验证加载。实际生成效果请用下面的测试配音确认。
      </p>
      {status?.task && (
        <div
          className={`tts-task ${status.task.status === 'failed' ? 'failed' : ''}`}
          aria-live="polite"
        >
          <p>{status.task.message}</p>
          {active(status.task.status) && (
            <>
              <progress max={1} value={status.task.progress} />
              <button
                className="text-link"
                onClick={() =>
                  request(async () => {
                    await api('/tts/cancel', { method: 'POST' })
                  })
                }
              >
                取消当前任务
              </button>
            </>
          )}
          {status.task.error && <p>{status.task.error}</p>}
        </div>
      )}
      <hr className="settings-divider" />
      <label>
        参考音频
        <select
          aria-label="参考音频"
          value={value.reference_id}
          onChange={(e) => change({ reference_id: e.target.value })}
          disabled={busy}
        >
          <option value="">请选择参考音频</option>
          {references.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name} · {item.duration.toFixed(1)} 秒
            </option>
          ))}
        </select>
      </label>
      {chosen && (
        <div className="reference-editor">
          <audio
            key={chosen.id}
            controls
            preload="metadata"
            src={chosen.audio_url}
            aria-label="参考音频试听"
          />
          <label>
            参考文字
            <textarea
              aria-label="参考文字"
              rows={3}
              maxLength={2000}
              value={editTranscript}
              disabled={busy}
              onChange={(e) => setEditTranscript(e.target.value)}
            />
          </label>
          <button
            className="button"
            disabled={busy || !editTranscript.trim() || editTranscript === chosen.transcript}
            onClick={() =>
              request(async () => {
                const updated = await api<Reference>(`/tts/references/${chosen.id}`, {
                  method: 'PUT',
                  body: JSON.stringify({ transcript: editTranscript }),
                })
                setReferences((items) =>
                  items.map((item) => (item.id === updated.id ? updated : item)),
                )
                notify('参考文字已保存，相关配音缓存将重新生成')
              })
            }
          >
            保存参考文字
          </button>
        </div>
      )}
      <details className="reference-upload" open={!references.length}>
        <summary>上传新的参考音频</summary>
        <p className="system-note">
          选择 3–30 秒清晰单人语音（推荐 5–15 秒，20 MB 以内），准确填写音频中的原话。
        </p>
        <label>
          选择音频文件
          <input
            type="file"
            accept="audio/*,.wav,.mp3,.m4a,.flac"
            disabled={busy}
            onChange={(e) => setFile(e.target.files?.[0] || null)}
          />
        </label>
        <label>
          新参考音频对应文字
          <textarea
            aria-label="新参考音频对应文字"
            rows={3}
            maxLength={2000}
            value={transcript}
            disabled={busy}
            onChange={(e) => setTranscript(e.target.value)}
            placeholder="逐字填写参考音频里说出的内容"
          />
        </label>
        <button className="button" disabled={busy || !file || !transcript.trim()} onClick={upload}>
          <UploadCloud size={16} />
          上传参考音频
        </button>
      </details>
      <hr className="settings-divider" />
      <label>
        语速 <span className="input-hint">{value.speed.toFixed(2)}×</span>
        <input
          type="range"
          min="0.5"
          max="2"
          step="0.05"
          value={value.speed}
          disabled={busy}
          onChange={(e) => change({ speed: Number(e.target.value) })}
        />
      </label>
      <p className="system-note">使用 FFmpeg 调整语速并保持音高，修改语速可复用已有原始配音。</p>
      <label>
        测试配音文字
        <textarea
          aria-label="测试配音文字"
          rows={2}
          maxLength={300}
          value={testText}
          onChange={(e) => setTestText(e.target.value)}
          disabled={busy}
        />
      </label>
      <div className="settings-inline">
        <button
          className="button"
          disabled={
            busy ||
            !status?.model_ready ||
            !chosen ||
            !testText.trim() ||
            editTranscript !== chosen?.transcript
          }
          onClick={() =>
            start('/tts/preview', {
              reference_id: value.reference_id,
              speed: value.speed,
              text: testText,
            })
          }
        >
          <Mic2 size={16} />
          生成测试配音
        </button>
        <small>使用当前参考音频、语速和文字，无需先保存设置。</small>
      </div>
      {preview && preview.inputs === inputs && (
        <audio controls src={preview.url} aria-label="测试配音试听" preload="metadata" />
      )}
      <p className="system-note">满意后点击页面右上角“保存设置”，项目配音将使用选中的参考音频。</p>
    </section>
  )
}
