import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

const fixture = path.resolve('../../.move/e2e-fixtures/video.mp4')
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
