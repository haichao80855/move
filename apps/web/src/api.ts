export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers:
      init.body instanceof FormData
        ? init.headers
        : { 'Content-Type': 'application/json', ...init.headers },
  })
  if (!response.ok) {
    let message = `请求失败 (${response.status})`
    try {
      const value = await response.json()
      message = typeof value.detail === 'string' ? value.detail : '输入内容无效，请检查设置和时间轴'
    } catch {
      /* preserve status */
    }
    throw new Error(message)
  }
  return response.json()
}

export function time(value: number, precise = false) {
  const ms = Math.round(value * 1000)
  const seconds = Math.floor(ms / 1000)
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const suffix = `${String(minutes).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
  return `${hours ? `${String(hours).padStart(2, '0')}:` : ''}${suffix}${precise ? `.${String(ms % 1000).padStart(3, '0')}` : ''}`
}

export const stageName: Record<string, string> = {
  prepare: '准备媒体',
  transcribe: '识别字幕',
  retranscribe: '局部补识别',
  translate: '翻译字幕',
  dub: '生成配音',
  export: '导出视频',
}
export const active = (status: string) => ['queued', 'running', 'cancelling'].includes(status)
