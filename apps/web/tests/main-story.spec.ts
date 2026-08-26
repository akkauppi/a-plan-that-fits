import { expect, test, type Page } from '@playwright/test'

test('loads the frozen map, refines a solution, and requests an alternative', async ({ page }, testInfo) => {
  const browserErrors = monitorBrowserErrors(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /Close the shortcuts/i })).toBeVisible()
  await expect(page.getByText('Frozen Helsinki scenario')).toBeVisible()
  await expect(page.locator('.maplibregl-canvas')).toBeVisible()
  await page.screenshot({ path: screenshotPath('before', testInfo.project.name) })

  await page.getByRole('button', { name: 'Increase intervention budget' }).click()
  await expect(page.getByLabel('5 interventions')).toBeVisible()
  await page.getByRole('button', { name: 'Decrease intervention budget' }).click()

  await page.getByRole('button', { name: /Solve with four/i }).click()
  await expect(page.getByLabel('Solver activity')).toBeVisible()
  await expect(page.getByText(/private-car route still|surviving private-car route/i).first()).toBeVisible()
  await expect(page.getByLabel('Verified solution')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('Verified under this model')).toBeVisible()
  await page.screenshot({ path: screenshotPath('verified', testInfo.project.name) })

  await page.getByRole('button', { name: /Next solution/i }).click()
  await expect(page.getByLabel('Verified solution')).toBeVisible({ timeout: 30_000 })

  const compare = page.getByRole('button', { name: /Compare/i })
  if (await compare.isEnabled()) {
    await compare.click()
    await expect(page.getByRole('heading', { name: 'Compare structures' })).toBeVisible()
  }
  expect(browserErrors).toEqual([])
})

test('locks a map candidate and distinguishes budget UNSAT from timeout', async ({ page, request }, testInfo) => {
  const browserErrors = monitorBrowserErrors(page)
  const response = await request.get('http://127.0.0.1:8000/api/scenario')
  const scenario = await response.json() as { candidates: Array<{ id: string; point: [number, number]; eligible: boolean }> }
  const candidate = scenario.candidates.find((item) => item.eligible)
  expect(candidate).toBeTruthy()

  await page.goto('/')
  await expect(page.locator('.maplibregl-canvas')).toBeVisible()
  await page.waitForFunction(() => Boolean(window.__FOUR_PLANTERS_MAP__?.loaded()))
  await clickMapCoordinate(page, candidate!.point)
  await expect(page.getByLabel(/Street constraints for/)).toBeVisible()
  await page.getByRole('button', { name: 'Lock open' }).click()

  await page.getByRole('slider', { name: 'Intervention budget' }).fill('0')
  await expect(page.getByLabel('0 interventions')).toBeVisible()
  await page.getByRole('button', { name: /Solve with 0/i }).click()
  await expect(page.getByLabel('Verified infeasible result')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('Verified infeasible')).toBeVisible()
  await expect(page.getByText(/not UNSAT/i)).toHaveCount(0)
  await page.screenshot({ path: screenshotPath('unsat', testInfo.project.name) })
  expect(browserErrors).toEqual([])
})

async function clickMapCoordinate(page: Page, coordinate: [number, number]): Promise<void> {
  const point = await page.evaluate((lngLat) => {
    const projected = window.__FOUR_PLANTERS_MAP__!.project(lngLat)
    return { x: projected.x, y: projected.y }
  }, coordinate)
  const canvas = page.locator('.maplibregl-canvas')
  const box = await canvas.boundingBox()
  if (!box) throw new Error('Map canvas has no visible bounding box')
  await page.mouse.click(box.x + point.x, box.y + point.y)
}

function screenshotPath(state: string, projectName: string): string {
  const viewport = projectName.includes('tablet') ? 'tablet' : 'desktop'
  return `../../docs/screenshots/four-planters-${state}-${viewport}.png`
}

function monitorBrowserErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}
