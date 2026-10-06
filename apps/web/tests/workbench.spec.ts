import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

const fixture = path.resolve('../../.move/e2e-fixtures/video.mp4')
const referenceFixture = path.resolve('../../.move/e2e-fixtures/reference.wav')
const srt =
  '1\n00:00:00,500 --> 00:00:01,500\nHello world.\n\n2\n00:00:02,000 --> 00:00:03,500\nWelcome to Move.\n'

test.beforeAll(() => {
  mkdirSync(path.dirname(fixture), { recursive: true })
  execFileSync('ffmpeg', [
    '-v',
    'error',
    '-y',
    '-f',
    'lavfi',
    '-i',
    'testsrc2=size=640x360:rate=15',
    '-f',
    'lavfi',
    '-i',
    'sine=frequency=300:sample_rate=24000',
    '-t',
    '4',
    '-c:v',
    'libx264',
    '-pix_fmt',
    'yuv420p',
    '-c:a',
    'aac',
    fixture,
  ])
  execFileSync('ffmpeg', [
    '-v',
    'error',
    '-y',
    '-i',
    fixture,
    '-vn',
    '-ac',
    '1',
    '-ar',
    '24000',
    referenceFixture,
  ])
})

test('DeepSeek tests draft values and clears stale results without saving', async ({ page }) => {
  const saved: string[] = []
  page.on('request', (request) => {
    if (request.url().endsWith('/api/settings') && request.method() === 'PUT')
      saved.push(request.url())
  })
  let ok = true
  await page.route('**/api/services/deepseek/test', async (route) => {
    const body = route.request().postDataJSON()
    expect(body.key).toBe('test-only-unsaved-key')
    expect(body.model).toBe('deepseek-reasoner')
    await route.fulfill({
      json: {
        ok,
        code: ok ? 'connected' : 'timeout',
        model: body.model,
        elapsed_ms: 123,
        message: ok ? '连接成功，所选模型已响应' : '连接或响应超时，请检查网络后重试',
      },
    })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '模型与服务', exact: true }).click()
  await page.getByLabel(/DeepSeek API Key/).fill('test-only-unsaved-key')
  await page.getByLabel('DeepSeek 模型', { exact: true }).fill('deepseek-reasoner')
  await page.getByRole('button', { name: '测试 DeepSeek 连接', exact: true }).click()
  await expect(page.locator('.connection-result')).toContainText('连接成功')
  await expect(page.locator('.connection-result')).toContainText('123 ms')
  ok = false
  await page.getByRole('button', { name: '测试 DeepSeek 连接', exact: true }).click()
  await expect(page.locator('.connection-result')).toContainText('超时')
  await page.getByLabel('DeepSeek 模型', { exact: true }).fill('different-model')
  await expect(page.locator('.connection-result')).toHaveCount(0)
  expect(saved).toEqual([])
  await page.reload()
  await page.getByRole('button', { name: '模型与服务', exact: true }).click()
  await expect(page.getByLabel(/DeepSeek API Key/)).toHaveValue('')
  await expect(page.getByLabel('DeepSeek 模型', { exact: true })).toHaveValue('deepseek-chat')
})

test('local TTS prepares model, uploads a real reference and previews draft settings', async ({
  page,
}) => {
  let ready = false
  let task: Record<string, unknown> | null = null
  let referenceUrl = ''
  const drafts: Record<string, unknown>[] = []
  await page.route('**/api/tts/status', (route) =>
    route.fulfill({
      json: {
        supported: true,
        runtime_installed: true,
        model_ready: ready,
        model: 'mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16',
        note: ready ? '模型已下载并验证可加载' : '点击准备模型',
        task,
      },
    }),
  )
  await page.route('**/api/tts/prepare', async (route) => {
    ready = true
    task = {
      id: 'prepare-test',
      status: 'completed',
      progress: 1,
      message: '模型准备完成',
      error: null,
      audio_url: null,
    }
    await route.fulfill({ status: 202, json: task })
  })
  await page.route('**/api/tts/preview', async (route) => {
    drafts.push(route.request().postDataJSON())
    task = {
      id: 'preview-test',
      status: 'completed',
      progress: 1,
      message: '测试配音已生成',
      error: null,
      audio_url: referenceUrl,
    }
    await route.fulfill({ status: 202, json: task })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '模型与服务', exact: true }).click()
  await page.getByRole('button', { name: '下载并准备模型', exact: true }).click()
  await expect(page.getByText('已下载并验证加载', { exact: true })).toBeVisible()
  await page.getByLabel('选择音频文件', { exact: true }).setInputFiles(referenceFixture)
  await page.getByLabel('新参考音频对应文字', { exact: true }).fill('这是一段参考音频的原话。')
  const uploaded = page.waitForResponse(
    (r) => r.url().endsWith('/api/tts/references') && r.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '上传参考音频', exact: true }).click()
  const profile = await (await uploaded).json()
  referenceUrl = profile.audio_url
  await expect(page.getByLabel('参考文字', { exact: true })).toHaveValue('这是一段参考音频的原话。')
  await expect(page.getByLabel('参考音频', { exact: true })).toHaveValue(profile.id)
  await page.getByLabel('参考文字', { exact: true }).fill('修正后的参考音频原话。')
  await page.getByRole('button', { name: '保存参考文字', exact: true }).click()
  await expect(page.getByRole('button', { name: '保存参考文字', exact: true })).toBeDisabled()
  await page.getByLabel('测试配音文字', { exact: true }).fill('这是当前填写的测试配音。')
  await page.getByRole('button', { name: '生成测试配音', exact: true }).click()
  await expect(page.getByLabel('测试配音试听', { exact: true })).toBeVisible()
  await expect
    .poll(() =>
      page
        .getByLabel('测试配音试听', { exact: true })
        .evaluate((audio: HTMLAudioElement) => audio.duration),
    )
    .toBeGreaterThan(3)
  expect(drafts).toEqual([{ reference_id: profile.id, speed: 1, text: '这是当前填写的测试配音。' }])
  await page.getByRole('button', { name: '保存设置', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('设置已保存')
  await page.reload()
  await page.getByRole('button', { name: '模型与服务', exact: true }).click()
  await expect(page.getByLabel('参考音频', { exact: true })).toHaveValue(profile.id)
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.screenshot({ path: '../../.move/settings-local-tts.png', fullPage: true })
})

test('real upload, subtitle edit, export and restore', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /让好内容/ })).toBeVisible()
  await page.locator('input[type=file]').setInputFiles(fixture)
  await expect(page.getByRole('heading', { name: 'video', exact: true })).toBeVisible()
  await expect(page.locator('video')).toBeVisible()
  await page
    .locator('input[accept=".srt"]')
    .first()
    .setInputFiles({
      name: 'source.srt',
      mimeType: 'application/x-subrip',
      buffer: Buffer.from(srt),
    })
  await expect(page.getByRole('textbox', { name: '原文 1', exact: true })).toHaveValue(
    'Hello world.',
  )
  const translated = srt
    .replace('Hello world.', '你好，世界。')
    .replace('Welcome to Move.', '欢迎使用 Move。')
  await page
    .locator('input[accept=".srt"]')
    .nth(1)
    .setInputFiles({
      name: 'zh.srt',
      mimeType: 'application/x-subrip',
      buffer: Buffer.from(translated),
    })
  await expect(page.getByRole('textbox', { name: '译文 1', exact: true })).toHaveValue(
    '你好，世界。',
  )
  await page.getByRole('textbox', { name: '译文 1', exact: true }).fill('你好，新世界。')
  const saved = page.waitForResponse(
    (r) => r.url().includes('/cues/') && r.request().method() === 'PUT',
  )
  await page.getByRole('heading', { name: 'video', exact: true }).click()
  expect((await saved).status()).toBe(200)
  await expect(page.getByRole('textbox', { name: '译文 1', exact: true })).toBeEnabled()
  await page.reload()
  await page.getByRole('button', { name: /video/ }).click()
  await expect(page.getByRole('textbox', { name: '译文 1', exact: true })).toHaveValue(
    '你好，新世界。',
  )
  await page.getByRole('button', { name: '播放视频', exact: true }).click()
  await page.getByRole('button', { name: '编辑字幕 1', exact: true }).click()
  const startTime = page.getByLabel('开始时间（秒）')
  await startTime.focus()
  await expect
    .poll(async () => page.locator('video').evaluate((v: HTMLVideoElement) => v.currentTime))
    .toBeGreaterThan(0.5)
  await expect(startTime).toBeFocused()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '暂停视频', exact: true }).click()
  await page.getByRole('button', { name: '导出作品' }).click()
  await page.getByRole('checkbox', { name: '使用中文配音' }).uncheck()
  await page.getByRole('button', { name: '合成视频' }).click()
  await expect(page.getByRole('link', { name: '下载视频', exact: true })).toBeVisible()
  const downloadEvent = page.waitForEvent('download')
  await page.getByRole('link', { name: '下载视频', exact: true }).click()
  expect((await downloadEvent).suggestedFilename()).toContain('.mp4')
  const subtitleResponse = await page.request.get(
    (await page.getByRole('link', { name: '双语 SRT', exact: true }).getAttribute('href'))!,
  )
  expect(await subtitleResponse.text()).toContain('你好，新世界。')
  await page.screenshot({ path: '../../.move/workbench-desktop.png', fullPage: true })
  expect(errors).toEqual([])
})

test('settings persist and layout works on a small screen', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '模型与服务', exact: true }).click()
  await page.getByLabel('术语表').fill('render = 渲染')
  await page.getByRole('button', { name: '保存设置', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('设置已保存')
  await page.reload()
  await page.getByRole('button', { name: '模型与服务', exact: true }).click()
  await expect(page.getByLabel('术语表')).toHaveValue('render = 渲染')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Move 首页' }).click()
  await expect(page.getByRole('heading', { name: /让好内容/ })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.screenshot({ path: '../../.move/workbench-mobile.png', fullPage: true })
})
