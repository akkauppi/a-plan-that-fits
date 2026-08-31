import { expect, test, type Page } from '@playwright/test'

test('shows the GIS-to-constraint refinement and verifies Otaniemi access', async ({ page }, testInfo) => {
  // This story deliberately captures four rendered map states on both desktop
  // and emulated tablet hardware. Leave headroom for software WebGL in CI;
  // individual solve assertions retain their much tighter 30-second limits.
  testInfo.setTimeout(240_000)
  const browserErrors = monitorBrowserErrors(page)
  await page.goto('/')

  await expect(page.getByRole('heading', { name: /See what stays reachable/i })).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('.maplibregl-canvas')).toBeVisible()
  await expect(page.getByLabel(/Interactive resilience analysis map/i)).toHaveAttribute('data-map-ready', 'true')
  await expect(page.getByRole('button', { name: 'Verified', exact: true })).toBeDisabled()
  await expect(page.getByText('15 representative 500 m cells')).toBeVisible()
  await page.screenshot({ path: screenshotPath('resilience-before', testInfo.project.name) })

  await page.getByRole('button', { name: /Solve access with 4/i }).click()
  await expect(page.getByText('Live solve trace')).toBeVisible()
  await expect(page.getByText(/directed frontier/i).first()).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('heading', { name: 'Access verified under this model' })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('3 zones')).toBeVisible()
  await expect(page.getByText('21 links')).toBeVisible()
  await expect(page.getByText('+1,093 m')).toBeVisible()

  await page.locator('.resilience-trace li button').filter({ hasText: /directed frontier/i }).last().click()
  await expect(page.getByText('Learned-clause frontier')).toBeVisible()
  await expect(page.getByText('Diagnostic route')).toBeVisible()
  await expect(page.getByText('Z3 candidate · not verified')).toBeVisible()
  await page.screenshot({ path: screenshotPath('resilience-refinement', testInfo.project.name) })

  await page.getByRole('button', { name: 'Verified', exact: true }).click()
  await page.locator('.resilience-result').evaluate((element) => element.scrollIntoView({ block: 'center' }))
  await page.screenshot({ path: screenshotPath('resilience-verified', testInfo.project.name) })

  await page.getByRole('button', { name: /Open constraint workbench/i }).click()
  await expect(page.getByRole('heading', { name: 'From spatial evidence to a checked answer' })).toBeVisible()
  await page.locator('.constraint-trace li button').filter({ hasText: /directed frontier/i }).last().click()
  await expect(page.getByText('Clause added in the selected iteration')).toBeVisible()
  await expect(page.getByText(/least-disrupted route helps explain the failure/i)).toBeVisible()
  await expect(page.locator('.constraint-workbench code').filter({ hasText: /passable\[/ }).first()).toBeVisible()
  await page.screenshot({ path: screenshotPath('constraint-workbench', testInfo.project.name) })
  await page.getByRole('button', { name: 'Other questions' }).click()
  await expect(page.getByRole('heading', { name: /reasoning loop stays recognisable/i })).toBeVisible()
  await page.getByRole('button', { name: 'Close constraint workbench' }).last().click()

  await page.getByRole('button', { name: 'How solvers differ' }).click()
  await expect(page.getByRole('heading', { name: /route finder searches a network/i })).toBeVisible()
  await expect(page.getByText(/routing tells us whether a proposed network works/i)).toBeVisible()
  await page.screenshot({ path: screenshotPath('solver-comparison', testInfo.project.name) })
  const proofBoundary = page.getByRole('heading', { name: /verified model answer is not a forecast/i })
  await proofBoundary.scrollIntoViewIfNeeded()
  await expect(proofBoundary).toBeVisible()
  expect(browserErrors).toEqual([])
})

test('loads the frozen map, refines a solution, and requests an alternative', async ({ page }, testInfo) => {
  const browserErrors = monitorBrowserErrors(page)
  await page.goto('/')
  await openBaseline(page)
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
  await openBaseline(page)
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
  await openBaseline(page)
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
  await openBaseline(page)
  await expect(page.locator('.maplibregl-canvas')).toBeVisible()
  await page.getByRole('button', { name: /Solve with four/i }).click()
  await page.getByRole('button', { name: 'Cancel solve' }).click()

  await expect(page.getByText('Indeterminate — not UNSAT')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Solve cancelled' })).toBeVisible()
  await expect(page.getByLabel('Verified infeasible result')).toHaveCount(0)
})

async function openBaseline(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Kallio baseline' }).click()
  await expect(page.getByText('Frozen Helsinki scenario')).toBeVisible()
}

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
