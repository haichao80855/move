import { useCallback, useEffect, useRef, useState } from 'react'
import type { DragEvent, ReactNode } from 'react'
import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  AudioLines,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Clock3,
  Cloud,
  Film,
  FolderOpen,
  Globe2,
  LayoutGrid,
  Loader2,
  Maximize2,
  Merge,
  Mic2,
  MoreHorizontal,
  Play,
  Plus,
  RotateCcw,
  Scissors,
  Search,
  Settings2,
  Sparkles,
  Square,
  Subtitles,
  UploadCloud,
  WandSparkles,
  X,
} from 'lucide-react'
import WaveSurfer from 'wavesurfer.js'
import { active, api, stageName, time } from './api'
import type { Cue, Job, Project, Settings, Stage, System } from './types'

type Notice = { text: string; error?: boolean }
const mediaUrl = (id: string, kind: string) => `/api/projects/${id}/media/${kind}`

function Button({
  children,
  primary,
  className = '',
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { primary?: boolean }) {
  return (
    <button {...props} className={`button ${primary ? 'primary' : ''} ${className}`}>
      {children}
    </button>
  )
}
function Modal({
  title,
  children,
  close,
  wide = false,
}: {
  title: string
  children: ReactNode
  close: () => void
  wide?: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)
  const closeRef = useRef(close)
  closeRef.current = close
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const node = ref.current!
    const first =
      node.querySelector<HTMLElement>('input, textarea, select') ||
      node.querySelector<HTMLElement>('button')
    first?.focus()
    function key(event: KeyboardEvent) {
      if (event.key === 'Escape') closeRef.current()
      if (event.key === 'Tab') {
        const elements = [
          ...node.querySelectorAll<HTMLElement>(
            'button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href]',
          ),
        ]
        if (event.shiftKey && document.activeElement === elements[0]) {
          event.preventDefault()
          elements.at(-1)?.focus()
        } else if (!event.shiftKey && document.activeElement === elements.at(-1)) {
          event.preventDefault()
          elements[0]?.focus()
        }
      }
    }
    document.addEventListener('keydown', key)
    return () => {
      document.removeEventListener('keydown', key)
      previous?.focus()
    }
  }, [])
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close()
      }}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`modal ${wide ? 'wide' : ''}`}
      >
        <div className="modal-heading">
          <h2>{title}</h2>
          <button className="icon-button" aria-label="关闭" onClick={close}>
            <X size={20} />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

export default function App() {
  const [page, setPage] = useState<'home' | 'settings' | 'project'>('home')
  const [projects, setProjects] = useState<Project[]>([])
  const [project, setProject] = useState<Project | null>(null)
  const [settings, setSettings] = useState<Settings | null>(null)
  const [system, setSystem] = useState<System | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [help, setHelp] = useState(false)
  const [uploading, setUploading] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const notify = useCallback((text: string, error = false) => setNotice({ text, error }), [])
  const refresh = useCallback(async () => {
    const [list, config, capabilities] = await Promise.all([
      api<Project[]>('/projects'),
      api<Settings>('/settings'),
      api<System>('/system'),
    ])
    setProjects(list)
    setSettings(config)
    setSystem(capabilities)
  }, [])
  useEffect(() => {
    refresh().catch((e) => notify(e.message, true))
  }, [refresh, notify])
  useEffect(() => {
    if (!notice) return
    const handle = window.setTimeout(() => setNotice(null), notice.error ? 10000 : 4500)
    return () => clearTimeout(handle)
  }, [notice])
  useEffect(() => {
    if (page !== 'project' || !project) return
    const events = new EventSource(`/api/projects/${project.id}/events`)
    events.onmessage = (event) => setProject(JSON.parse(event.data))
    // EventSource reconnects automatically; no polling that loses pending UI edits.
    return () => events.close()
  }, [page, project?.id])

  async function open(id: string) {
    try {
      setProject(await api<Project>(`/projects/${id}`))
      setPage('project')
    } catch (e) {
      notify((e as Error).message, true)
    }
  }
  async function upload(file?: File) {
    if (!file || uploading) return
    setUploading(true)
    const body = new FormData()
    body.append('file', file)
    try {
      const value = await api<Project>('/projects', { method: 'POST', body })
      setProject(value)
      setPage('project')
      await refresh()
      notify('视频已导入，正在准备预览与音频')
    } catch (e) {
      notify((e as Error).message, true)
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }
  const home = () => {
    setPage('home')
    refresh().catch((e) => notify(e.message, true))
  }
  const settingsPage = () => {
    setPage('settings')
    refresh().catch((e) => notify(e.message, true))
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand" onClick={home} aria-label="Move 首页">
          <span className="brand-mark">m</span>
          <span>
            move<span className="brand-dot">.</span>
          </span>
        </button>
        <div className="sidebar-label">创作空间</div>
        <nav>
          <button className={page !== 'settings' ? 'nav-item current' : 'nav-item'} onClick={home}>
            <LayoutGrid size={19} />
            项目工作台<span className="nav-count">{projects.length}</span>
          </button>
          <button
            className={page === 'settings' ? 'nav-item current' : 'nav-item'}
            onClick={settingsPage}
          >
            <Settings2 size={19} />
            模型与服务
          </button>
          <button className="nav-item" onClick={() => setHelp(true)}>
            <CircleHelp size={19} />
            使用指南
          </button>
        </nav>
        <div className="sidebar-note">
          <span className="small-icon">
            <AudioLines size={23} />
          </span>
          <strong>让内容被更多人听见</strong>
          <p>
            识别、翻译、配音。
            <br />
            把创作留给你。
          </p>
        </div>
        <div className="environment">
          <span className={`status-dot ${system?.ffmpeg ? '' : 'offline'}`} />
          <div>
            <strong>
              {system?.apple_silicon ? 'Apple Silicon · 本地工作流' : '本地视频工作流'}
            </strong>
            <small>{system ? `${system.platform} · ${system.architecture}` : '连接服务中…'}</small>
          </div>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <span className="breadcrumb">
            <FolderOpen size={16} />
            <button onClick={home}>项目库</button>
            {page === 'project' && project && (
              <>
                <ChevronRight size={14} />
                <span>{project.name}</span>
              </>
            )}
            {page === 'settings' && (
              <>
                <ChevronRight size={14} />
                <span>模型与服务</span>
              </>
            )}
          </span>
          <div className="topbar-right">
            <span className="local-badge">
              <span className="status-dot" />
              文件保存在本机
            </span>
            <button className="avatar" aria-label="打开使用指南" onClick={() => setHelp(true)}>
              M
            </button>
          </div>
        </header>
        <main>
          {page === 'home' && (
            <Home
              projects={projects}
              open={open}
              importFile={() => fileInput.current?.click()}
              onDrop={upload}
              uploading={uploading}
              settings={settings}
              settingsPage={settingsPage}
            />
          )}
          {page === 'settings' && settings && system && (
            <SettingsPage
              initial={settings}
              system={system}
              saved={(value) => {
                setSettings(value)
                notify('设置已保存')
              }}
              notify={notify}
            />
          )}
          {page === 'project' && project && settings && system && (
            <Workspace
              key={project.id}
              project={project}
              settings={settings}
              system={system}
              update={setProject}
              notify={notify}
              home={home}
              settingsPage={settingsPage}
            />
          )}
        </main>
      </div>
      <input
        ref={fileInput}
        className="hidden"
        type="file"
        accept="video/*,.mkv,.mov,.mp4,.webm"
        onChange={(e) => upload(e.target.files?.[0])}
      />
      {notice && (
        <div
          role={notice.error ? 'alert' : 'status'}
          className={`toast ${notice.error ? 'error' : ''}`}
        >
          {notice.error ? <CircleHelp size={19} /> : <CheckCircle2 size={19} />}
          <span>{notice.text}</span>
          <button className="icon-button" aria-label="关闭提示" onClick={() => setNotice(null)}>
            <X size={16} />
          </button>
        </div>
      )}
      {help && (
        <Modal title="开始你的第一支翻译视频" close={() => setHelp(false)}>
          <div className="help-steps">
            {[
              '在模型与服务页配置 DeepSeek 或 Qwen，以及 MiniMax API Key。',
              '导入视频，在 Mac 上识别英文字幕；也可以直接导入 UTF-8 SRT。',
              '校对原文和时间轴，再翻译成中文。点击任意字幕时间即可定位视频。',
              '先选择几句生成配音并试听，再处理全部字幕。配音过长的句子会提示调整。',
              '导出中文配音视频和双语 SRT。已完成片段会缓存，关闭后可继续。',
            ].map((text, i) => (
              <p key={i}>
                <span>{i + 1}</span>
                {text}
              </p>
            ))}
          </div>
          <div className="info-box">
            16 GB Mac
            会串行加载识别模型。首次识别需下载模型；翻译文字和配音文字会发送至你选择的云端服务。
          </div>
          <Button primary onClick={() => setHelp(false)}>
            开始创作
            <ArrowRight size={16} />
          </Button>
        </Modal>
      )}
    </div>
  )
}

function Home({
  projects,
  open,
  importFile,
  onDrop,
  uploading,
  settings,
  settingsPage,
}: {
  projects: Project[]
  open: (id: string) => void
  importFile: () => void
  onDrop: (file?: File) => void
  uploading: boolean
  settings: Settings | null
  settingsPage: () => void
}) {
  const [drag, setDrag] = useState(false)
  const [search, setSearch] = useState('')
  const filtered = projects.filter((p) => p.name.toLowerCase().includes(search.toLowerCase()))
  function drop(event: DragEvent) {
    event.preventDefault()
    setDrag(false)
    onDrop(event.dataTransfer.files[0])
  }
  const unconfigured =
    settings &&
    (!settings.credentials[settings.translation_provider] || !settings.credentials.minimax)
  return (
    <div className="home-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">YOUR LOCAL VIDEO STUDIO</div>
          <h1>
            让好内容，跨越语言<span className="title-dot">。</span>
          </h1>
          <p>从原声到中文，用一条清晰的工作流完成视频翻译。</p>
        </div>
        <Button primary onClick={importFile} disabled={uploading}>
          <Plus size={18} />
          新建项目
        </Button>
      </div>
      <div className="home-hero">
        <div
          className={`import-card ${drag ? 'dragging' : ''}`}
          onDragOver={(e) => {
            e.preventDefault()
            setDrag(true)
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={drop}
        >
          <div className="import-orbit">
            <span className="orbit-label orbit-left">
              <Subtitles size={14} />
              双语字幕
            </span>
            <span className="upload-icon">
              {uploading ? <Loader2 size={34} className="spin" /> : <UploadCloud size={34} />}
            </span>
            <span className="orbit-label orbit-right">
              <Mic2 size={14} />
              中文配音
            </span>
          </div>
          <h2>{uploading ? '正在导入你的视频…' : '从一支视频，开始新的表达'}</h2>
          <p>将视频拖到这里，或点击选择本机文件</p>
          <Button primary onClick={importFile} disabled={uploading}>
            {uploading ? '正在上传与检查' : '选择视频'}
            <ArrowRight size={16} />
          </Button>
          <span className="file-support">MP4 · MOV · MKV · WEBM　/　默认最大 2 GB</span>
        </div>
        <div className="flow-card">
          <div className="eyebrow">一个工作台，完整流程</div>
          <h2>
            细节交给你，
            <br />
            重复工作交给 Move。
          </h2>
          <div className="flow-list">
            {[
              [Subtitles, '识别与校对', '本机识别，逐句精修'],
              [Globe2, '上下文翻译', 'DeepSeek / Qwen'],
              [AudioLines, '自然中文配音', '云端音色，先听再生成'],
              [Film, '完成与导出', '视频、字幕、独立音轨'],
            ].map(([Icon, title, text], index) => {
              const ItemIcon = Icon as typeof Subtitles
              return (
                <div className="flow-item" key={index}>
                  <span className={`flow-icon tone-${index}`}>
                    <ItemIcon size={18} />
                  </span>
                  <div>
                    <strong>{title as string}</strong>
                    <small>{text as string}</small>
                  </div>
                  {index < 3 && <span className="flow-connector" />}
                </div>
              )
            })}
          </div>
        </div>
      </div>
      {unconfigured && (
        <button className="setup-banner" onClick={settingsPage}>
          <span>
            <Cloud size={19} />
            <strong>连接你的翻译与配音服务</strong>
            <span>配置一次，下次直接开始创作。</span>
          </span>
          <span>
            前往设置
            <ArrowRight size={16} />
          </span>
        </button>
      )}
      <div className="section-heading">
        <div>
          <h2>
            我的项目<span className="count-pill">{projects.length}</span>
          </h2>
          <p>你的进度会自动保存，随时回来继续。</p>
        </div>
        <label className="search-input">
          <Search size={17} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索项目…"
            aria-label="搜索项目"
          />
        </label>
      </div>
      {filtered.length ? (
        <div className="project-grid">
          {filtered.map((p, i) => (
            <button className="project-card" key={p.id} onClick={() => open(p.id)}>
              <div className={`project-cover cover-${i % 4}`}>
                <div className="cover-grid" />
                <Film size={34} />
                <span className="duration-chip">{time(p.metadata.duration)}</span>
                <span className="cover-tag">
                  {p.metadata.width} × {p.metadata.height}
                </span>
              </div>
              <div className="project-card-body">
                <h3 title={p.name}>{p.name}</h3>
                <div className="project-meta">
                  <span>{new Date(p.updated * 1000).toLocaleDateString('zh-CN')}</span>
                  <span>{p.cue_count || 0} 条字幕</span>
                </div>
                <div className="project-card-footer">
                  <span
                    className={`project-state ${p.latest_job?.status === 'failed' ? 'failed' : ''}`}
                  >
                    {p.latest_job && active(p.latest_job.status)
                      ? '正在处理'
                      : p.latest_job?.status === 'failed'
                        ? '等待重试'
                        : p.cue_count
                          ? '继续编辑'
                          : '准备校对'}
                  </span>
                  <ArrowRight size={16} />
                </div>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <div className="empty-projects">
          <FolderOpen size={26} />
          <strong>{search ? '没有找到匹配的项目' : '你的故事，从这里开始'}</strong>
          <p>{search ? '试试其他名称。' : '导入第一支视频，Move 会为你保存整个创作过程。'}</p>
        </div>
      )}
      <footer className="home-footer">
        <span>本地处理媒体 · 自由校对字幕 · 按需连接云端</span>
        <span>MOVE / 0.1</span>
      </footer>
    </div>
  )
}

function SettingsPage({
  initial,
  system,
  saved,
  notify,
}: {
  initial: Settings
  system: System
  saved: (value: Settings) => void
  notify: (text: string, error?: boolean) => void
}) {
  const [value, setValue] = useState(initial)
  const [keys, setKeys] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [voiceList, setVoiceList] = useState<{ id: string; name: string }[]>([])
  const [loadingVoices, setLoadingVoices] = useState(false)
  const change = <K extends keyof Settings>(key: K, next: Settings[K]) =>
    setValue((v) => ({ ...v, [key]: next }))
  async function save() {
    setSaving(true)
    try {
      const result = await api<Settings>('/settings', {
        method: 'PUT',
        body: JSON.stringify({
          ...value,
          keys: Object.fromEntries(Object.entries(keys).filter(([, key]) => key.trim())),
        }),
      })
      setKeys({})
      setValue(result)
      saved(result)
    } catch (e) {
      notify((e as Error).message, true)
    } finally {
      setSaving(false)
    }
  }
  async function loadVoices() {
    setLoadingVoices(true)
    try {
      setVoiceList(await api('/voices'))
      notify('已连接 MiniMax，音色列表已更新')
    } catch (e) {
      notify((e as Error).message, true)
    } finally {
      setLoadingVoices(false)
    }
  }
  return (
    <div className="settings-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">MAKE IT YOURS</div>
          <h1>模型与服务</h1>
          <p>本机识别，云端翻译与配音。选择适合你的组合。</p>
        </div>
        <Button primary onClick={save} disabled={saving}>
          {saving ? <Loader2 className="spin" size={16} /> : <Check size={16} />}保存设置
        </Button>
      </div>
      <div className="settings-layout">
        <div className="settings-main">
          <section className="settings-card">
            <div className="card-title">
              <span className="flow-icon tone-0">
                <Globe2 size={20} />
              </span>
              <div>
                <h2>字幕翻译</h2>
                <p>批次携带前文与术语，时间轴保持不变。</p>
              </div>
            </div>
            <div className="provider-options">
              {(['deepseek', 'qwen'] as const).map((provider) => (
                <button
                  key={provider}
                  className={`provider-option ${value.translation_provider === provider ? 'chosen' : ''}`}
                  onClick={() => change('translation_provider', provider)}
                >
                  <strong>{provider === 'deepseek' ? 'DeepSeek' : '通义千问 Qwen'}</strong>
                  <span>{provider === 'deepseek' ? '默认翻译服务' : '可切换的翻译服务'}</span>
                  {value.translation_provider === provider && <CheckCircle2 size={18} />}
                </button>
              ))}
            </div>
            <div className="form-grid">
              {(['deepseek', 'qwen'] as const).map((provider) => (
                <label key={provider}>
                  {provider === 'deepseek' ? 'DeepSeek' : 'Qwen'} API Key{' '}
                  <span className={`key-state ${value.credentials[provider] ? 'configured' : ''}`}>
                    {value.credentials[provider] ? '已配置' : '未配置'}
                  </span>
                  <input
                    type="password"
                    autoComplete="off"
                    value={keys[provider] || ''}
                    onChange={(e) => setKeys((k) => ({ ...k, [provider]: e.target.value }))}
                    placeholder={
                      value.credentials[provider]
                        ? '留空保留当前密钥'
                        : system.apple_silicon
                          ? '输入 API Key'
                          : `使用 ${provider.toUpperCase()}_API_KEY 环境变量`
                    }
                    disabled={!system.apple_silicon}
                  />
                </label>
              ))}
              <label>
                DeepSeek 模型
                <input
                  value={value.deepseek_model}
                  onChange={(e) => change('deepseek_model', e.target.value)}
                />
              </label>
              <label>
                Qwen 模型
                <input
                  value={value.qwen_model}
                  onChange={(e) => change('qwen_model', e.target.value)}
                />
              </label>
              <label>
                Qwen 区域
                <select
                  value={value.qwen_region}
                  onChange={(e) => change('qwen_region', e.target.value as 'cn' | 'global')}
                >
                  <option value="cn">中国内地</option>
                  <option value="global">国际</option>
                </select>
              </label>
            </div>
            <label>
              翻译风格
              <textarea
                rows={2}
                value={value.translation_style}
                onChange={(e) => change('translation_style', e.target.value)}
              />
            </label>
            <label>
              术语表
              <textarea
                rows={3}
                value={value.glossary}
                onChange={(e) => change('glossary', e.target.value)}
                placeholder={'例如：\nReact Server Components = React 服务端组件\nrender = 渲染'}
              />
            </label>
          </section>
          <section className="settings-card">
            <div className="card-title">
              <span className="flow-icon tone-2">
                <Mic2 size={20} />
              </span>
              <div>
                <h2>中文配音 · MiniMax</h2>
                <p>建议先试听几句，再批量生成。</p>
              </div>
            </div>
            <div className="form-grid">
              <label>
                MiniMax API Key{' '}
                <span className={`key-state ${value.credentials.minimax ? 'configured' : ''}`}>
                  {value.credentials.minimax ? '已配置' : '未配置'}
                </span>
                <input
                  type="password"
                  autoComplete="off"
                  value={keys.minimax || ''}
                  onChange={(e) => setKeys((k) => ({ ...k, minimax: e.target.value }))}
                  placeholder={
                    system.apple_silicon ? '输入 API Key' : '使用 MINIMAX_API_KEY 环境变量'
                  }
                  disabled={!system.apple_silicon}
                />
              </label>
              <label>
                服务区域
                <select
                  value={value.tts_region}
                  onChange={(e) => change('tts_region', e.target.value as 'cn' | 'global')}
                >
                  <option value="cn">中国内地</option>
                  <option value="global">国际</option>
                </select>
              </label>
              <label>
                配音模型
                <input
                  value={value.tts_model}
                  onChange={(e) => change('tts_model', e.target.value)}
                />
              </label>
              <label>
                语速 <span className="input-hint">{value.speed.toFixed(2)}×</span>
                <input
                  type="range"
                  min="0.5"
                  max="2"
                  step="0.05"
                  value={value.speed}
                  onChange={(e) => change('speed', Number(e.target.value))}
                />
              </label>
              <label className="full-width">
                音色 ID
                <input
                  list="voice-list"
                  value={value.voice_id}
                  onChange={(e) => change('voice_id', e.target.value)}
                  placeholder="输入或从列表选择音色"
                />
                <datalist id="voice-list">
                  {voiceList.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name}
                    </option>
                  ))}
                </datalist>
              </label>
            </div>
            <div className="settings-inline">
              <Button onClick={loadVoices} disabled={loadingVoices || !value.credentials.minimax}>
                {loadingVoices ? <Loader2 size={15} className="spin" /> : <Cloud size={15} />}
                测试连接并读取音色
              </Button>
              <small>使用已保存的密钥与区域设置。</small>
            </div>
          </section>
        </div>
        <aside className="settings-aside">
          <section className="settings-card">
            <h3>本机环境</h3>
            <div className="system-line">
              <span>FFmpeg</span>
              <span className={system.ffmpeg ? 'good' : 'bad'}>
                {system.ffmpeg ? '可用' : '未安装'}
              </span>
            </div>
            <div className="system-line">
              <span>FFprobe</span>
              <span className={system.ffprobe ? 'good' : 'bad'}>
                {system.ffprobe ? '可用' : '未安装'}
              </span>
            </div>
            <div className="system-line">
              <span>MLX 识别</span>
              <span className={system.asr ? 'good' : ''}>{system.asr ? '可用' : '未启用'}</span>
            </div>
            <p className="system-note">{system.asr_note}</p>
            <p className="system-note">Parakeet 负责英文识别；Whisper Large v3 用于局部补识别。</p>
          </section>
          <section className="settings-card tinted">
            <Sparkles size={22} />
            <h3>适合 16 GB 的工作流</h3>
            <p>
              识别模型按阶段加载，任务串行执行。视频和中间文件保存在本机，已完成的配音片段可复用。
            </p>
          </section>
          <p className="privacy-note">
            Mac 密钥保存在系统钥匙串。云端服务按账号实际用量计费；仅在开始对应任务时调用。
          </p>
        </aside>
      </div>
    </div>
  )
}

function Workspace({
  project,
  settings,
  system,
  update,
  notify,
  home,
  settingsPage,
}: {
  project: Project
  settings: Settings
  system: System
  update: (p: Project) => void
  notify: (text: string, error?: boolean) => void
  home: () => void
  settingsPage: () => void
}) {
  const [step, setStep] = useState(project.cues.length ? 1 : 0)
  const [tab, setTab] = useState<'cues' | 'jobs'>('cues')
  const [selected, setSelected] = useState<string[]>([])
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('all')
  const [currentTime, setCurrentTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [pending, setPending] = useState(false)
  const [edit, setEdit] = useState<Cue | null>(null)
  const [splitCue, setSplitCue] = useState<Cue | null>(null)
  const [candidate, setCandidate] = useState<{ job: Job; cues: Cue[] } | null>(null)
  const [confirm, setConfirm] = useState<{ message: string; run: () => void } | null>(null)
  const [undo, setUndo] = useState<Cue[]>([])
  const [subtitleMode, setSubtitleMode] = useState('bilingual')
  const [useDubbing, setUseDubbing] = useState(true)
  const [originalVolume, setOriginalVolume] = useState(0)
  const video = useRef<HTMLVideoElement>(null)
  const originalInput = useRef<HTMLInputElement>(null)
  const translationInput = useRef<HTMLInputElement>(null)
  const currentJob = project.jobs.find((j) => active(j.status))
  const busy = !!currentJob || pending
  const latest = project.jobs[0]
  const translated = project.cues.filter((c) => c.translation.trim()).length
  const dubbed = project.cues.filter((c) => c.audio_ready).length
  const long = (c: Cue) =>
    c.end - c.start > 20 || !!(c.audio_duration && c.audio_duration > (c.end - c.start) * 1.15)
  const visible = project.cues.filter(
    (c) =>
      (!search || (c.original + c.translation).toLowerCase().includes(search.toLowerCase())) &&
      (filter === 'all' ||
        (filter === 'untranslated' && !c.translation) ||
        (filter === 'issues' && long(c))),
  )
  const currentCue = project.cues.find((c) => c.start <= currentTime && currentTime < c.end)

  useEffect(() => {
    setSelected((ids) => ids.filter((id) => project.cues.some((c) => c.id === id)))
  }, [project.cues])
  async function action<T>(operation: () => Promise<T>, message?: string) {
    setPending(true)
    try {
      const value = await operation()
      if (message) notify(message)
      return value
    } catch (e) {
      notify((e as Error).message, true)
    } finally {
      setPending(false)
    }
  }
  const seek = useCallback((value: number) => {
    if (video.current) video.current.currentTime = value
    setCurrentTime(value)
  }, [])
  function togglePlay() {
    if (!video.current) return
    if (video.current.paused) video.current.play().catch(() => notify('预览尚未准备完成', true))
    else video.current.pause()
  }
  useEffect(() => {
    function keyboard(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement).tagName
      if (['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(tag) || edit || splitCue || confirm)
        return
      if (e.code === 'Space') {
        e.preventDefault()
        togglePlay()
      }
      if (e.key === 'ArrowLeft') {
        e.preventDefault()
        seek(Math.max(0, currentTime - 5))
      }
      if (e.key === 'ArrowRight') {
        e.preventDefault()
        seek(Math.min(project.metadata.duration, currentTime + 5))
      }
    }
    window.addEventListener('keydown', keyboard)
    return () => window.removeEventListener('keydown', keyboard)
  }, [currentTime, edit, splitCue, confirm, seek, project.metadata.duration])

  function job(stage: Stage, cueIds = selected, force = false) {
    action(async () => {
      await api(`/projects/${project.id}/jobs`, {
        method: 'POST',
        body: JSON.stringify({
          stage,
          cue_ids: cueIds,
          force,
          subtitle_mode: subtitleMode,
          use_dubbing: useDubbing,
          original_volume: originalVolume,
        }),
      })
      update(await api(`/projects/${project.id}`))
    }, '任务已加入队列')
  }
  async function saveCue(cue: Cue, previous: Cue) {
    const result = await action(() =>
      api<Project>(`/projects/${project.id}/cues/${cue.id}`, {
        method: 'PUT',
        body: JSON.stringify(cue),
      }),
    )
    if (result) {
      update(result)
      setUndo((list) => [...list.slice(-19), previous])
      setEdit(null)
    }
  }
  async function undoEdit() {
    const last = undo.at(-1)
    if (!last) return
    const current = project.cues.find((c) => c.id === last.id)
    if (!current) {
      notify('该条字幕已拆分或合并，不能撤销文字修改', true)
      return
    }
    const result = await action(() =>
      api<Project>(`/projects/${project.id}/cues/${last.id}`, {
        method: 'PUT',
        body: JSON.stringify({ ...last, revision: current.revision }),
      }),
    )
    if (result) {
      update(result)
      setUndo((list) => list.slice(0, -1))
      notify('已撤销上一次编辑')
    }
  }
  async function importSrt(file: File | undefined, kind: string) {
    if (!file) return
    const perform = async () => {
      const body = new FormData()
      body.append('file', file)
      const result = await action(
        () =>
          api<Project>(`/projects/${project.id}/subtitles?kind=${kind}`, { method: 'POST', body }),
        '字幕已导入',
      )
      if (result) {
        update(result)
        setUndo([])
      }
    }
    if (kind === 'original' && project.cues.length)
      setConfirm({ message: '导入原文 SRT 会替换当前字幕及配音记录。是否继续？', run: perform })
    else await perform()
    if (originalInput.current) originalInput.current.value = ''
    if (translationInput.current) translationInput.current.value = ''
  }
  const readySteps = [
    project.cues.length > 0,
    project.cues.length > 0,
    translated === project.cues.length && translated > 0,
    dubbed === project.cues.length && dubbed > 0,
    project.export_current,
  ]
  const descriptions = [
    '本机识别英文字幕，也可导入现有 SRT。',
    '校对文字与时间轴，让每句话恰到好处。',
    '结合前文与术语表，翻译成自然中文。',
    '先试听，再批量生成。只重做改变的句子。',
    '检查时间轴，完成你的中文版本。',
  ]

  return (
    <div className="workspace-page">
      <div className="workspace-title">
        <div>
          <button className="back-link" onClick={home}>
            <ArrowLeft size={14} />
            返回项目库
          </button>
          <h1>{project.name}</h1>
          <p>
            {time(project.metadata.duration)}
            <span>·</span>
            {project.metadata.width} × {project.metadata.height}
            <span>·</span>
            {project.cues.length} 条字幕
            <span className="autosave">
              <CheckCircle2 size={13} />
              本地项目
            </span>
          </p>
        </div>
        <Button primary onClick={() => setStep(4)}>
          <ArrowDownToLine size={16} />
          导出作品
        </Button>
      </div>
      <div className="stepper">
        {['识别字幕', '校对字幕', '翻译中文', '生成配音', '导出视频'].map((label, i) => (
          <button
            key={label}
            className={`step ${step === i ? 'selected' : ''} ${readySteps[i] ? 'done' : ''}`}
            onClick={() => setStep(i)}
          >
            <span className="step-number">{readySteps[i] ? <Check size={15} /> : `0${i + 1}`}</span>
            <span>{label}</span>
            {i < 4 && <ChevronRight className="step-arrow" size={14} />}
          </button>
        ))}
      </div>
      {currentJob && (
        <div className="job-banner">
          <Loader2 className="spin" size={18} />
          <div>
            <strong>{stageName[currentJob.stage]}</strong>
            <span>{currentJob.message}</span>
            <div className="progress-track">
              <span style={{ width: `${Math.max(2, currentJob.progress * 100)}%` }} />
            </div>
          </div>
          <span className="job-percent">{Math.round(currentJob.progress * 100)}%</span>
          <Button
            disabled={currentJob.status === 'cancelling'}
            onClick={() =>
              action(() =>
                api(`/projects/${project.id}/jobs/${currentJob.id}/cancel`, { method: 'POST' }),
              )
            }
          >
            <Square size={13} />
            取消
          </Button>
        </div>
      )}
      {!currentJob && latest && ['failed', 'interrupted'].includes(latest.status) && (
        <div className="error-banner">
          <CircleHelp size={19} />
          <div>
            <strong>
              {stageName[latest.stage]}
              {latest.status === 'failed' ? '失败' : '中断'}
            </strong>
            <p>{latest.error || latest.message}</p>
          </div>
          <Button
            onClick={() =>
              action(async () => {
                await api(`/projects/${project.id}/jobs/${latest.id}/retry`, { method: 'POST' })
                update(await api(`/projects/${project.id}`))
              })
            }
          >
            重试
          </Button>
        </div>
      )}
      <div className="workspace-top">
        <section className="preview-card">
          <div className="preview-screen">
            {project.preview_ready ? (
              <>
                <video
                  ref={video}
                  src={mediaUrl(project.id, 'preview')}
                  onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
                  onPlay={() => setPlaying(true)}
                  onPause={() => setPlaying(false)}
                  playsInline
                />
                <div className="subtitle-overlay">
                  {currentCue && (
                    <>
                      <span>{currentCue.translation}</span>
                      <small>{currentCue.original}</small>
                    </>
                  )}
                </div>
                <button
                  className={`preview-play ${playing ? 'is-playing' : ''}`}
                  aria-label={playing ? '暂停' : '播放'}
                  onClick={togglePlay}
                >
                  <Play size={28} fill="currentColor" />
                </button>
              </>
            ) : (
              <div className="preview-placeholder">
                <Film size={38} />
                <strong>正在准备视频预览</strong>
                <span>后台转码完成后会自动显示</span>
              </div>
            )}
            <span className="preview-label">原视频预览</span>
          </div>
          <div className="player-controls">
            <button
              className="icon-button"
              onClick={togglePlay}
              aria-label={playing ? '暂停视频' : '播放视频'}
            >
              {playing ? <Square size={16} /> : <Play size={17} />}
            </button>
            <span>
              {time(currentTime)} <small>/ {time(project.metadata.duration)}</small>
            </span>
            <input
              aria-label="视频进度"
              type="range"
              min="0"
              max={project.metadata.duration}
              step="0.01"
              value={currentTime}
              onChange={(e) => seek(Number(e.target.value))}
            />
            <span className="key-hint">空格 播放</span>
            <button
              className="icon-button"
              aria-label="全屏预览"
              onClick={() =>
                video.current?.parentElement
                  ?.requestFullscreen()
                  .catch(() => notify('无法进入全屏', true))
              }
            >
              <Maximize2 size={15} />
            </button>
          </div>
        </section>
        <aside className="stage-panel">
          <div className="eyebrow">STEP 0{step + 1}</div>
          <h2>
            {['听懂原声', '打磨每句话', '让表达更自然', '找到合适的声音', '完成你的作品'][step]}
          </h2>
          <p>{descriptions[step]}</p>
          {step === 0 && (
            <>
              <div className="model-chip">
                <span className="small-icon">
                  <AudioLines size={19} />
                </span>
                <div>
                  <strong>Parakeet TDT 0.6B v3</strong>
                  <small>Apple Silicon · MLX · 英文</small>
                </div>
              </div>
              <div className="info-box">
                {system.asr
                  ? '首次识别会下载模型。16 GB Mac 逐阶段运行，避免同时加载多个模型。'
                  : system.asr_note}
              </div>
              <Button
                primary
                disabled={busy || !system.asr || !project.audio_ready}
                onClick={() =>
                  project.cues.length
                    ? setConfirm({
                        message: '重新识别会替换当前字幕及配音记录。是否继续？',
                        run: () => job('transcribe', []),
                      })
                    : job('transcribe', [])
                }
              >
                <Sparkles size={16} />
                {project.cues.length ? '重新识别字幕' : '开始识别'}
              </Button>
              <Button disabled={busy} onClick={() => originalInput.current?.click()}>
                <UploadCloud size={16} />
                导入原文 SRT
              </Button>
            </>
          )}
          {step === 1 && (
            <>
              <div className="stage-stats">
                <span>
                  <strong>{project.cues.length}</strong>条字幕
                </span>
                <span>
                  <strong>{project.cues.filter(long).length}</strong>条待检查
                </span>
              </div>
              <div className="info-box">
                点击文字直接编辑，离开输入框自动保存。时间按钮定位视频；编辑按钮可精确调整时间轴。
              </div>
              <Button
                disabled={busy || selected.length !== 1 || !system.asr}
                onClick={() => job('retranscribe')}
              >
                <WandSparkles size={16} />
                Whisper 补识别选中片段
              </Button>
              <Button disabled={!project.cues.length} onClick={() => setStep(2)}>
                继续翻译
                <ArrowRight size={16} />
              </Button>
            </>
          )}
          {step === 2 && (
            <>
              <div className="model-chip">
                <span className="small-icon">
                  <Globe2 size={19} />
                </span>
                <div>
                  <strong>
                    {settings.translation_provider === 'deepseek' ? 'DeepSeek' : 'Qwen'}
                  </strong>
                  <small>{settings[`${settings.translation_provider}_model`]}</small>
                </div>
              </div>
              <div className="stage-stats">
                <span>
                  <strong>{translated}</strong>已翻译
                </span>
                <span>
                  <strong>{project.cues.length - translated}</strong>待翻译
                </span>
              </div>
              {!settings.credentials[settings.translation_provider] && (
                <button className="text-link" onClick={settingsPage}>
                  配置翻译服务
                  <ArrowRight size={14} />
                </button>
              )}
              <Button
                primary
                disabled={
                  busy ||
                  !project.cues.length ||
                  !settings.credentials[settings.translation_provider]
                }
                onClick={() => job('translate', selected, !!selected.length)}
              >
                <Sparkles size={16} />
                {selected.length ? `重译选中 ${selected.length} 句` : '翻译未完成字幕'}
              </Button>
              <Button
                disabled={busy || !project.cues.length}
                onClick={() => translationInput.current?.click()}
              >
                <UploadCloud size={16} />
                导入译文 SRT
              </Button>
              <p className="panel-footnote">每批最多 25 条，保留前文上下文。已有译文默认跳过。</p>
            </>
          )}
          {step === 3 && (
            <>
              <div className="model-chip">
                <span className="small-icon">
                  <Mic2 size={19} />
                </span>
                <div>
                  <strong>MiniMax 云端配音</strong>
                  <small>
                    {settings.voice_id} · {settings.speed.toFixed(2)}×
                  </small>
                </div>
              </div>
              <div className="stage-stats">
                <span>
                  <strong>{dubbed}</strong>已配音
                </span>
                <span>
                  <strong>{project.cues.length - dubbed}</strong>待生成
                </span>
              </div>
              <button className="text-link" onClick={settingsPage}>
                调整音色与语速
                <ArrowRight size={14} />
              </button>
              <Button
                primary
                disabled={busy || !translated || !settings.credentials.minimax}
                onClick={() => job('dub')}
              >
                <Mic2 size={16} />
                {selected.length ? `配音选中 ${selected.length} 句` : '生成全部配音'}
              </Button>
              <div className="info-box">
                勾选 2–3 句先试听。更改译文或音色后，只重新生成受影响的片段。
              </div>
            </>
          )}
          {step === 4 && (
            <>
              <label>
                字幕样式
                <select value={subtitleMode} onChange={(e) => setSubtitleMode(e.target.value)}>
                  <option value="bilingual">中英双语字幕</option>
                  <option value="translated">中文字幕</option>
                  <option value="original">原文字幕</option>
                  <option value="none">不烧录字幕</option>
                </select>
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={useDubbing}
                  onChange={(e) => setUseDubbing(e.target.checked)}
                />
                使用中文配音
              </label>
              {useDubbing && (
                <label>
                  原声音量 <span className="input-hint">{Math.round(originalVolume * 100)}%</span>
                  <input
                    type="range"
                    min="0"
                    max="0.5"
                    step="0.05"
                    value={originalVolume}
                    onChange={(e) => setOriginalVolume(Number(e.target.value))}
                  />
                  <small className="field-note">0% 静音；提高音量会同时保留原文人声。</small>
                </label>
              )}
              <Button
                primary
                disabled={busy || !project.cues.length}
                onClick={() => job('export', [])}
              >
                <Film size={16} />
                合成视频
              </Button>
              {project.export_ready && (
                <a
                  className="button primary"
                  href={mediaUrl(project.id, 'output')}
                  download={`${project.name}-中文.mp4`}
                >
                  <ArrowDownToLine size={16} />
                  下载视频{!project.export_current && '（历史版本）'}
                </a>
              )}
              <div className="download-links">
                <a href={`/api/projects/${project.id}/subtitles?mode=bilingual`}>双语 SRT</a>
                <a href={`/api/projects/${project.id}/subtitles?mode=translated`}>中文 SRT</a>
                {project.dubbing_ready && (
                  <a href={mediaUrl(project.id, 'dubbing')} download>
                    配音音轨
                  </a>
                )}
              </div>
              <p className="panel-footnote">过长配音会提示调整。视频保持原始时长，不截断语句。</p>
            </>
          )}
        </aside>
      </div>
      {project.audio_ready && (
        <Waveform projectId={project.id} currentTime={currentTime} seek={seek} />
      )}
      <section className="subtitle-section">
        <div className="subtitle-toolbar">
          <div className="tab-buttons">
            <button className={tab === 'cues' ? 'active-tab' : ''} onClick={() => setTab('cues')}>
              <Subtitles size={17} />
              字幕编辑<span>{project.cues.length}</span>
            </button>
            <button className={tab === 'jobs' ? 'active-tab' : ''} onClick={() => setTab('jobs')}>
              <Clock3 size={16} />
              任务记录
            </button>
          </div>
          {tab === 'cues' && (
            <div className="subtitle-tools">
              <Button disabled={busy || !undo.length} onClick={undoEdit} title="撤销上一次字幕编辑">
                <RotateCcw size={15} />
                撤销
              </Button>
              <select
                aria-label="字幕筛选"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              >
                <option value="all">全部字幕</option>
                <option value="untranslated">未翻译</option>
                <option value="issues">需要检查</option>
              </select>
              <label className="search-input">
                <Search size={15} />
                <input
                  aria-label="搜索字幕"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="搜索字幕…"
                />
              </label>
            </div>
          )}
        </div>
        {tab === 'jobs' ? (
          <div className="job-list">
            {project.jobs.map((j) => (
              <div className="job-row" key={j.id}>
                <span className={`job-status ${j.status}`}>
                  <Clock3 size={17} />
                </span>
                <div>
                  <strong>{stageName[j.stage]}</strong>
                  <p>{j.error || j.message}</p>
                </div>
                <span className="job-date">
                  {new Date(j.created * 1000).toLocaleString('zh-CN')}
                </span>
                {j.status === 'completed' && j.stage === 'retranscribe' && (
                  <Button
                    onClick={() =>
                      action(async () =>
                        setCandidate({
                          job: j,
                          cues: await api(`/projects/${project.id}/jobs/${j.id}/candidate`),
                        }),
                      )
                    }
                  >
                    比较结果
                  </Button>
                )}
                {['failed', 'cancelled', 'interrupted'].includes(j.status) && (
                  <Button
                    disabled={busy}
                    onClick={() =>
                      action(async () => {
                        await api(`/projects/${project.id}/jobs/${j.id}/retry`, { method: 'POST' })
                        update(await api(`/projects/${project.id}`))
                      })
                    }
                  >
                    重试
                  </Button>
                )}
                <span className="status-text">
                  {
                    {
                      completed: '已完成',
                      running: '处理中',
                      queued: '排队中',
                      failed: '失败',
                      cancelled: '已取消',
                      cancelling: '取消中',
                      interrupted: '已中断',
                    }[j.status]
                  }
                </span>
              </div>
            ))}
          </div>
        ) : (
          <>
            <div className="table-heading">
              <label>
                <input
                  type="checkbox"
                  aria-label="选择全部可见字幕"
                  checked={!!visible.length && visible.every((c) => selected.includes(c.id))}
                  onChange={(e) => setSelected(e.target.checked ? visible.map((c) => c.id) : [])}
                />
                序号
              </label>
              <span>时间轴</span>
              <span>
                原文 <small>ENGLISH</small>
              </span>
              <span>
                译文 <small>中文</small>
              </span>
              <span>操作</span>
            </div>
            {!project.cues.length ? (
              <div className="empty-subtitles">
                <Subtitles size={29} />
                <strong>字幕，将从这里开始</strong>
                <p>识别原视频，或导入已有的 SRT 文件。</p>
                <Button disabled={busy} onClick={() => originalInput.current?.click()}>
                  <UploadCloud size={15} />
                  导入字幕
                </Button>
              </div>
            ) : !visible.length ? (
              <div className="empty-subtitles">没有符合条件的字幕</div>
            ) : (
              <div className="cue-list">
                {visible.map((c) => (
                  <CueRow
                    key={c.id}
                    cue={c}
                    index={project.cues.indexOf(c)}
                    checked={selected.includes(c.id)}
                    current={currentCue?.id === c.id}
                    disabled={busy}
                    issue={long(c)}
                    toggle={() =>
                      setSelected((list) =>
                        list.includes(c.id) ? list.filter((id) => id !== c.id) : [...list, c.id],
                      )
                    }
                    seek={() => seek(c.start)}
                    edit={() => setEdit(c)}
                    split={() => setSplitCue(c)}
                    merge={() =>
                      setConfirm({
                        message: '合并这条字幕与下一条，并清除这两条的配音记录？',
                        run: async () => {
                          const result = await action(() =>
                            api<Project>(
                              `/projects/${project.id}/cues/${c.id}/merge?revision=${c.revision}`,
                              { method: 'POST' },
                            ),
                          )
                          if (result) update(result)
                        },
                      })
                    }
                    save={(draft) => saveCue(draft, c)}
                    audio={() => {
                      new Audio(`/api/projects/${project.id}/cues/${c.id}/audio`)
                        .play()
                        .catch(() => notify('音频播放失败', true))
                    }}
                  />
                ))}
              </div>
            )}
            <div className="table-footer">
              <span>
                {selected.length
                  ? `已选择 ${selected.length} 条字幕`
                  : `共 ${project.cues.length} 条字幕`}
              </span>
              <span>
                <span className="status-dot" />
                自动保存 · 修改文字后离开输入框即可
              </span>
            </div>
          </>
        )}
      </section>
      <input
        ref={originalInput}
        type="file"
        accept=".srt"
        className="hidden"
        onChange={(e) => importSrt(e.target.files?.[0], 'original')}
      />
      <input
        ref={translationInput}
        type="file"
        accept=".srt"
        className="hidden"
        onChange={(e) => importSrt(e.target.files?.[0], 'translated')}
      />
      {edit && (
        <CueModal
          cue={edit}
          duration={project.metadata.duration}
          close={() => setEdit(null)}
          save={(next) => saveCue(next, edit)}
          pending={pending}
        />
      )}
      {splitCue && (
        <SplitModal
          cue={splitCue}
          currentTime={currentTime}
          close={() => setSplitCue(null)}
          pending={pending}
          save={async (values) => {
            const result = await action(() =>
              api<Project>(`/projects/${project.id}/cues/${splitCue.id}/split`, {
                method: 'POST',
                body: JSON.stringify(values),
              }),
            )
            if (result) {
              update(result)
              setSplitCue(null)
            }
          }}
        />
      )}
      {confirm && (
        <Modal title="确认操作" close={() => setConfirm(null)}>
          <p className="modal-description">{confirm.message}</p>
          <div className="modal-actions">
            <Button onClick={() => setConfirm(null)}>取消</Button>
            <Button
              primary
              onClick={() => {
                const task = confirm.run
                setConfirm(null)
                task()
              }}
            >
              继续
            </Button>
          </div>
        </Modal>
      )}
      {candidate && (
        <Modal title="Whisper 补识别结果" wide close={() => setCandidate(null)}>
          <p className="modal-description">采用后仅替换选中字幕，相关译文和配音需要重新生成。</p>
          <div className="candidate-list">
            {candidate.cues.map((c, i) => (
              <div key={i}>
                <small>
                  {time(c.start, true)} → {time(c.end, true)}
                </small>
                <p>{c.original}</p>
              </div>
            ))}
          </div>
          <div className="modal-actions">
            <Button onClick={() => setCandidate(null)}>保留原文</Button>
            <Button
              primary
              disabled={busy}
              onClick={async () => {
                const result = await action(() =>
                  api<Project>(`/projects/${project.id}/jobs/${candidate.job.id}/candidate`, {
                    method: 'POST',
                  }),
                )
                if (result) {
                  update(result)
                  setCandidate(null)
                }
              }}
            >
              采用候选结果
            </Button>
          </div>
        </Modal>
      )}
    </div>
  )
}

function CueRow({
  cue,
  index,
  checked,
  current,
  disabled,
  issue,
  toggle,
  seek,
  edit,
  split,
  merge,
  save,
  audio,
}: {
  cue: Cue
  index: number
  checked: boolean
  current: boolean
  disabled: boolean
  issue: boolean
  toggle: () => void
  seek: () => void
  edit: () => void
  split: () => void
  merge: () => void
  save: (draft: Cue) => Promise<void>
  audio: () => void
}) {
  const [draft, setDraft] = useState(cue)
  const [menu, setMenu] = useState(false)
  const saving = useRef(false)
  useEffect(() => setDraft(cue), [cue.revision])
  async function persist() {
    if (
      saving.current ||
      (draft.original === cue.original && draft.translation === cue.translation)
    )
      return
    saving.current = true
    try {
      await save(draft)
    } finally {
      saving.current = false
    }
  }
  return (
    <div className={`cue-row ${checked ? 'checked' : ''} ${current ? 'current-cue' : ''}`}>
      <label className="cue-number">
        <input
          type="checkbox"
          checked={checked}
          onChange={toggle}
          aria-label={`选择字幕 ${index + 1}`}
        />
        {String(index + 1).padStart(2, '0')}
      </label>
      <button className="cue-time" onClick={seek}>
        <span>{time(cue.start, true)}</span>
        <span>{time(cue.end, true)}</span>
        {issue && <small>待检查</small>}
      </button>
      <textarea
        aria-label={`原文 ${index + 1}`}
        rows={2}
        value={draft.original}
        disabled={disabled}
        onChange={(e) => setDraft((v) => ({ ...v, original: e.target.value }))}
        onBlur={persist}
      />
      <textarea
        aria-label={`译文 ${index + 1}`}
        rows={2}
        value={draft.translation}
        disabled={disabled}
        placeholder="等待翻译，或直接输入中文…"
        onChange={(e) => setDraft((v) => ({ ...v, translation: e.target.value }))}
        onBlur={persist}
      />
      <div className="cue-actions">
        <button
          className="icon-button"
          aria-label={`试听字幕 ${index + 1}`}
          disabled={!cue.audio_ready}
          onClick={audio}
        >
          <AudioLines size={17} />
        </button>
        <button
          className="icon-button"
          aria-label={`编辑字幕 ${index + 1}`}
          disabled={disabled}
          onClick={edit}
        >
          <Settings2 size={16} />
        </button>
        <div className="menu-wrap">
          <button
            className="icon-button"
            aria-label={`更多操作 ${index + 1}`}
            disabled={disabled}
            onClick={() => setMenu((v) => !v)}
          >
            <MoreHorizontal size={18} />
          </button>
          {menu && (
            <div className="row-menu">
              <button
                onClick={() => {
                  setMenu(false)
                  split()
                }}
              >
                <Scissors size={14} />
                拆分字幕
              </button>
              <button
                onClick={() => {
                  setMenu(false)
                  merge()
                }}
              >
                <Merge size={14} />
                与下一条合并
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function CueModal({
  cue,
  duration,
  close,
  save,
  pending,
}: {
  cue: Cue
  duration: number
  close: () => void
  save: (c: Cue) => void
  pending: boolean
}) {
  const [draft, setDraft] = useState(cue)
  return (
    <Modal title="编辑字幕与时间轴" close={close}>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          save(draft)
        }}
      >
        <div className="form-grid">
          <label>
            开始时间（秒）
            <input
              type="number"
              step="0.001"
              min="0"
              max={duration}
              value={draft.start}
              onChange={(e) => setDraft((v) => ({ ...v, start: Number(e.target.value) }))}
              required
            />
          </label>
          <label>
            结束时间（秒）
            <input
              type="number"
              step="0.001"
              min={draft.start + 0.001}
              max={duration}
              value={draft.end}
              onChange={(e) => setDraft((v) => ({ ...v, end: Number(e.target.value) }))}
              required
            />
          </label>
        </div>
        <label>
          原文
          <textarea
            rows={3}
            value={draft.original}
            onChange={(e) => setDraft((v) => ({ ...v, original: e.target.value }))}
            required
          />
        </label>
        <label>
          中文译文
          <textarea
            rows={3}
            value={draft.translation}
            onChange={(e) => setDraft((v) => ({ ...v, translation: e.target.value }))}
          />
        </label>
        <div className="modal-actions">
          <Button type="button" onClick={close}>
            取消
          </Button>
          <Button primary type="submit" disabled={pending}>
            保存修改
          </Button>
        </div>
      </form>
    </Modal>
  )
}

function SplitModal({
  cue,
  currentTime,
  close,
  save,
  pending,
}: {
  cue: Cue
  currentTime: number
  close: () => void
  save: (values: object) => void
  pending: boolean
}) {
  function half(text: string): [string, string] {
    const spaces = [...text.matchAll(/ /g)].map((m) => m.index!)
    const center = text.length / 2
    const at = spaces.length
      ? spaces.reduce((a, b) => (Math.abs(a - center) < Math.abs(b - center) ? a : b))
      : Math.ceil(center)
    return [text.slice(0, at).trim(), text.slice(at).trim()]
  }
  const [first, second] = half(cue.original)
  const [firstTr, secondTr] = half(cue.translation)
  const [value, setValue] = useState({
    revision: cue.revision,
    at: currentTime > cue.start && currentTime < cue.end ? currentTime : (cue.start + cue.end) / 2,
    first_original: first,
    second_original: second,
    first_translation: firstTr,
    second_translation: secondTr,
  })
  return (
    <Modal title="拆分字幕" wide close={close}>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          save(value)
        }}
      >
        <p className="modal-description">文字已按中点预填，请检查两段的文字与实际语音是否匹配。</p>
        <label>
          拆分位置（秒）
          <input
            type="number"
            min={cue.start + 0.001}
            max={cue.end - 0.001}
            step="0.001"
            value={value.at}
            onChange={(e) => setValue((v) => ({ ...v, at: Number(e.target.value) }))}
            required
          />
        </label>
        <div className="form-grid">
          {(['first', 'second'] as const).map((part, i) => (
            <div key={part}>
              <h3>第 {i + 1} 段</h3>
              <label>
                原文
                <textarea
                  rows={3}
                  value={value[`${part}_original`]}
                  onChange={(e) =>
                    setValue((v) => ({ ...v, [`${part}_original`]: e.target.value }))
                  }
                  required
                />
              </label>
              <label>
                译文
                <textarea
                  rows={3}
                  value={value[`${part}_translation`]}
                  onChange={(e) =>
                    setValue((v) => ({ ...v, [`${part}_translation`]: e.target.value }))
                  }
                />
              </label>
            </div>
          ))}
        </div>
        <div className="modal-actions">
          <Button type="button" onClick={close}>
            取消
          </Button>
          <Button primary type="submit" disabled={pending}>
            确认拆分
          </Button>
        </div>
      </form>
    </Modal>
  )
}

function Waveform({
  projectId,
  currentTime,
  seek,
}: {
  projectId: string
  currentTime: number
  seek: (time: number) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const wave = useRef<WaveSurfer | null>(null)
  const [error, setError] = useState(false)
  useEffect(() => {
    const controller = WaveSurfer.create({
      container: ref.current!,
      waveColor: '#d8d1f4',
      progressColor: '#8a73df',
      cursorColor: '#735be7',
      height: 38,
      barWidth: 2,
      barGap: 2,
      normalize: true,
      interact: true,
    })
    wave.current = controller
    controller.on('interaction', seek)
    controller.on('error', () => setError(true))
    api<{ duration: number; peaks: number[] }>(`/projects/${projectId}/waveform`)
      .then((data) => {
        if (wave.current === controller)
          return controller.load(mediaUrl(projectId, 'audio'), [data.peaks], data.duration)
      })
      .catch(() => {
        if (wave.current === controller) setError(true)
      })
    return () => {
      controller.destroy()
      wave.current = null
    }
  }, [projectId, seek])
  useEffect(() => {
    if (wave.current?.getDuration()) wave.current.setTime(currentTime)
  }, [currentTime])
  return (
    <div className="waveform">
      <AudioLines size={17} />
      <span>原声音轨</span>
      <div ref={ref} />
      {error && <small>波形加载失败，可使用视频进度条定位</small>}
    </div>
  )
}
