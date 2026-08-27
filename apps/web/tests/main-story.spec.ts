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
  await expect(page.getByRole('button', { name: /Searching/i })).toBeVisible()
  await expect(page.getByRole('button', { name: /Next solution/i })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByLabel('Verified solution')).toBeVisible()

  const compare = page.getByRole('button', { name: /Compare/i })
  await expect(compare).toBeEnabled()
  await compare.click()
  await expect(page.getByRole('heading', { name: 'Compare structures' })).toBeVisible()
  await page.screenshot({ path: screenshotPath('compare', testInfo.project.name) })
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

  await setBudget(page, 0, 4)
  await expect(page.getByLabel('0 interventions')).toBeVisible()
  await page.getByRole('button', { name: /Solve with 0/i }).click()
  await expect(page.getByLabel('Verified infeasible result')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('Verified infeasible')).toBeVisible()
  await expect(page.getByText(/not UNSAT/i)).toHaveCount(0)
  await page.screenshot({ path: screenshotPath('unsat', testInfo.project.name) })
  expect(browserErrors).toEqual([])
})

test('shares the selected timeout and sends it to the solver', async ({ page }) => {
  let solvePayload: Record<string, unknown> | undefined
  await page.route('**/api/solve', async (route) => {
    solvePayload = route.request().postDataJSON() as Record<string, unknown>
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'timeout',
        verification_status: 'timeout',
        selected_intervention_ids: [],
        objective_values: {},
        address_access_summary: {},
        portal_connectivity_summary: {},
        local_detour_metrics: {},
        iteration_count: 0,
        timing_ms: 120_000,
        solve_id: 'timeout-ui-check',
        snapshot_id: 'test-snapshot',
        explanation: 'The selected time limit elapsed. Feasibility remains indeterminate.',
      }),
    })
  })

  await page.goto('/')
  await expect(page.locator('.maplibregl-canvas')).toBeVisible()
  await page.getByText('Access & solver settings', { exact: true }).click()
  await page.getByLabel('Solver timeout').selectOption('120')
  await expect(page).toHaveURL(/(?:\?|&)timeout=120(?:&|$)/)
  await page.getByRole('button', { name: /Solve with four/i }).click()

  await expect.poll(() => solvePayload?.timeout_seconds).toBe(120)
  await expect(page.getByText('Indeterminate — not UNSAT')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Solve timed out' })).toBeVisible()
  await page.getByRole('button', { name: 'Why this is different from infeasible' }).click()
  await expect(page.getByRole('heading', { name: 'What the proof means' })).toBeVisible()
})

test('cancels an active solve without claiming infeasibility', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.maplibregl-canvas')).toBeVisible()
  await page.getByRole('button', { name: /Solve with four/i }).click()
  await expect(page.getByText('The solver is testing a deterministic intervention model.')).toBeVisible()
  await page.getByRole('button', { name: 'Cancel solve' }).click()

  await expect(page.getByText('Indeterminate — not UNSAT')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Solve cancelled' })).toBeVisible()
  await expect(page.getByLabel('Verified infeasible result')).toHaveCount(0)
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

async function setBudget(page: Page, target: number, current: number): Promise<void> {
  const slider = page.getByRole('slider', { name: 'Intervention budget' })
  if (await slider.isVisible()) {
    await slider.fill(String(target))
    return
  }
  const buttonName = target < current ? 'Decrease intervention budget' : 'Increase intervention budget'
  for (let value = current; value !== target; value += target < current ? -1 : 1) {
    await page.getByRole('button', { name: buttonName }).click()
  }
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
