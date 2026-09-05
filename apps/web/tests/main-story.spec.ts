import { expect, test, type Page } from '@playwright/test'

test('presents three experiments and explains the shared model vocabulary', async ({ page }, testInfo) => {
  const browserErrors = monitorBrowserErrors(page)
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Spatial questions become choices, rules and checked routes.' })).toBeVisible()
  await page.screenshot({ path: overviewScreenshotPath(testInfo.project.name) })
  await expect(page.getByRole('heading', { name: 'Four Planters' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Resilient access' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Equitable service coverage' })).toBeVisible()

  const indexScroller = page.locator('.experiment-index')
  await indexScroller.evaluate((scroller) => { scroller.style.scrollBehavior = 'auto' })
  await page.getByRole('link', { name: 'Key concepts' }).click()
  await expect(page.getByRole('heading', { name: 'Continuity commitment' })).toBeVisible()
  await expect(page.getByText(/budget counts the group once/i)).toBeVisible()
  await expect(page.getByText(/Z3 cannot reopen them/i)).toBeVisible()
  await expect(page.getByText(/not a promise or finding/i)).toBeVisible()
  const vocabulary = page.locator('#lab-concepts')
  await indexScroller.evaluate((scroller, targetSelector) => {
    const target = scroller.querySelector<HTMLElement>(targetSelector)
    if (!target) throw new Error(`Missing screenshot target: ${targetSelector}`)
    scroller.scrollTop += target.getBoundingClientRect().top - scroller.getBoundingClientRect().top - 22
  }, '#lab-concepts')
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  await expect(vocabulary.getByRole('heading', { name: 'What the model’s terms mean' })).toBeInViewport()
  await page.screenshot({ path: overviewConceptsScreenshotPath(testInfo.project.name) })

  await page.getByRole('button', { name: 'How solvers work' }).click()
  await expect(page.getByRole('heading', { name: /route finder searches a network/i })).toBeVisible()
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  await page.screenshot({ path: screenshotPath('solver-comparison', testInfo.project.name) })
  expect(browserErrors).toEqual([])
})

test('shows the GIS-to-constraint refinement and verifies Otaniemi access', async ({ page }, testInfo) => {
  // This story deliberately captures four rendered map states on both desktop
  // and emulated tablet hardware. Leave headroom for software WebGL in CI;
  // individual solve assertions retain their much tighter 30-second limits.
  testInfo.setTimeout(240_000)
  const browserErrors = monitorBrowserErrors(page)
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Spatial questions become choices, rules and checked routes.' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Geospatial Constraint Lab experiment index' })).toBeVisible()
  await expect(page.getByRole('link', { name: /Open Four Planters/i })).toBeVisible()
  await expect(page.getByRole('link', { name: /Open resilient access/i })).toBeVisible()
  await openResilientAccess(page)

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

  await page.getByRole('button', { name: 'How solvers work' }).click()
  await expect(page.getByRole('heading', { name: /route finder searches a network/i })).toBeVisible()
  await expect(page.getByText(/network analysis supplies geographic relationships/i)).toBeVisible()
  const proofBoundary = page.getByRole('heading', { name: /verified model answer is not a forecast/i })
  await proofBoundary.scrollIntoViewIfNeeded()
  await expect(proofBoundary).toBeVisible()
  expect(browserErrors).toEqual([])
})

test('allocates service coverage and explains a capacity-driven UNSAT', async ({ page }, testInfo) => {
  testInfo.setTimeout(180_000)
  const browserErrors = monitorBrowserErrors(page)
  await page.goto('/?experience=coverage')

  await expect(page.getByRole('heading', { name: 'Equitable service coverage' })).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('.service-coverage-map')).toHaveAttribute('data-map-ready', 'true', { timeout: 30_000 })
  await expect(page.getByText(/8,554 people · 33 cells/i)).toBeVisible()
  await expect(page.getByText(/10 eligible sites/i)).toBeVisible()
  await expect(page.getByText(/analytical capacity/i).first()).toBeVisible()
  await page.screenshot({ path: serviceCoverageScreenshotPath('before', testInfo.project.name) })

  await expect(page.getByText('30s timeout', { exact: false })).toBeVisible()

  await page.getByRole('button', { name: /Assign coverage with 4/i }).click()
  await expect(page.getByRole('region', { name: 'Solver stage trace' })).toBeVisible()
  await expect(page.getByText('Feasible assignment', { exact: true })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('Lexicographic search', { exact: true })).toBeVisible()
  const verifiedCoverage = page.getByRole('region', { name: 'Verified service-coverage result' })
  await expect(verifiedCoverage.getByRole('heading', { name: 'Every included cell is assigned' })).toBeVisible({ timeout: 45_000 })
  await expect(verifiedCoverage.getByText('2 / 4')).toBeVisible()
  await expect(verifiedCoverage.getByText('1,232 m')).toBeVisible()
  await expect(verifiedCoverage.getByText(/Worst-served witness/i)).toBeVisible()
  await expect(page.getByText('Verified assignment', { exact: true })).toBeVisible()
  await scrollCoverageResultIntoView(verifiedCoverage)
  await page.screenshot({ path: serviceCoverageScreenshotPath('verified', testInfo.project.name) })

  await page.getByRole('slider', { name: 'Maximum selected-site budget' }).fill('1')
  await page.getByRole('button', { name: /Assign coverage with 1/i }).click()
  await expect(page.getByRole('heading', { name: 'Available analytical capacity is insufficient' })).toBeVisible({ timeout: 30_000 })
  const infeasibleCoverage = page.getByRole('region', { name: 'Verified infeasible service-coverage request' })
  await expect(infeasibleCoverage).toBeVisible()
  await expect(page.getByRole('button', { name: 'Try budget 2' })).toBeVisible()
  await expect(page.getByText('Infeasible assumptions', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Demand', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('button', { name: 'Assignments', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Assignments', exact: true })).toHaveAttribute('aria-pressed', 'false')
  await scrollCoverageResultIntoView(infeasibleCoverage)
  await page.screenshot({ path: serviceCoverageScreenshotPath('unsat', testInfo.project.name) })
  expect(browserErrors).toEqual([])
})

test('loads the frozen map, refines a solution, and requests an alternative', async ({ page }, testInfo) => {
  // Alternative enumeration plus software WebGL can exceed the shared 90-second
  // story cap on emulated tablet hardware even though each solve stays bounded.
  testInfo.setTimeout(180_000)
  const browserErrors = monitorBrowserErrors(page)
  await page.goto('/')
  await openBaseline(page)
  await expect(page.getByRole('heading', { name: /Close the shortcuts/i })).toBeVisible()
  await expect(page.getByText(/Experiment 01 · frozen Kallio–Vallila/i)).toBeVisible()
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
  // A full serial tablet run can spend most of the default 90-second envelope
  // draining earlier software-WebGL maps before this screenshot is encoded.
  // Keep the assertions' own 30-second bounds; only give the complete story
  // enough room to finish under accumulated CI rendering load.
  testInfo.setTimeout(180_000)
  const browserErrors = monitorBrowserErrors(page)
  const response = await request.get('http://127.0.0.1:8000/api/scenario')
  const scenario = await response.json() as { candidates: Array<{ id: string; point: [number, number]; eligible: boolean }> }
  const candidate = scenario.candidates.find((item) => item.eligible)
  expect(candidate).toBeTruthy()

  await page.goto('/')
  await openBaseline(page)
  await expect(page.locator('.maplibregl-canvas')).toBeVisible()
  await page.waitForFunction(() => Boolean(window.__GEOSPATIAL_LAB_MAP__?.loaded()))
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
  await page.getByRole('link', { name: /Open Four Planters/i }).click()
  await expect(page.getByText(/Experiment 01 · frozen Kallio–Vallila/i)).toBeVisible()
}

async function openResilientAccess(page: Page): Promise<void> {
  await page.getByRole('link', { name: /Open resilient access/i }).click()
  await expect(page.getByText(/Experiment 02 · frozen Otaniemi/i)).toBeVisible()
}

async function clickMapCoordinate(page: Page, coordinate: [number, number]): Promise<void> {
  const point = await page.evaluate((lngLat) => {
    const projected = window.__GEOSPATIAL_LAB_MAP__!.project(lngLat)
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

function overviewScreenshotPath(projectName: string): string {
  const viewport = projectName.includes('tablet') ? 'tablet' : 'desktop'
  return `../../docs/screenshots/geospatial-constraint-lab-overview-${viewport}.png`
}

function overviewConceptsScreenshotPath(projectName: string): string {
  const viewport = projectName.includes('tablet') ? 'tablet' : 'desktop'
  return `../../docs/screenshots/geospatial-constraint-lab-concepts-${viewport}.png`
}

function serviceCoverageScreenshotPath(state: string, projectName: string): string {
  const viewport = projectName.includes('tablet') ? 'tablet' : 'desktop'
  return `../../docs/screenshots/geospatial-constraint-lab-service-coverage-${state}-${viewport}.png`
}

async function scrollCoverageResultIntoView(result: ReturnType<Page['locator']>): Promise<void> {
  await result.evaluate((element) => {
    const scroller = element.closest<HTMLElement>('.service-coverage-instrument__scroll')
    if (scroller && scroller.scrollHeight > scroller.clientHeight + 1) {
      const elementBox = element.getBoundingClientRect()
      const scrollerBox = scroller.getBoundingClientRect()
      scroller.scrollTo({
        top: scroller.scrollTop + elementBox.top - scrollerBox.top - Math.max(20, (scroller.clientHeight - elementBox.height) / 2),
        behavior: 'instant',
      })
      return
    }
    element.scrollIntoView({ block: 'center', behavior: 'instant' })
  })
  await expect(result).toBeInViewport()
}

function monitorBrowserErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}
