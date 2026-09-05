import { init } from 'z3-solver/build/browser'
import { solveScenario } from './model.ts'
import { validateScenario } from '../core/validate.ts'
import type { Scenario, WorkerRequest, WorkerResponse } from '../core/types.ts'

const send = (message: WorkerResponse) => self.postMessage(message)
let api: Awaited<ReturnType<typeof init>> | undefined
let scenario: Scenario | undefined
let active: { id: number; cancelled: boolean; interrupt?: () => void } | undefined
let initializing = false
self.onmessage = async ({ data }: MessageEvent<WorkerRequest>) => {
  if (data.type === 'init') {
    if (initializing || api) return
    initializing = true
    try {
      validateScenario(data.scenario)
      api = await init({
        locateFile: file => new URL(`./z3-5.2.0/${file}`, self.location.href).href,
        mainScriptUrlOrBlob: new URL('./z3-5.2.0/z3-built.js', self.location.href).href,
      })
      scenario = data.scenario
      send({ type: 'ready' })
    } catch (error) { send({ type: 'init-error', message: `Could not initialise browser Z3: ${String(error)}` }) }
    return
  }
  if (data.type === 'cancel') {
    if (active?.id === data.requestId) { active.cancelled = true; active.interrupt?.() }
    return
  }
  if (!api || !scenario || active) {
    send({ type: 'result', requestId: data.requestId, result: { status: 'error', message: 'Solver is not ready or is already busy.', elapsedMs: 0 } })
    return
  }
  const run = { id: data.requestId, cancelled: false, interrupt: undefined as (() => void) | undefined }
  active = run
  const result = await solveScenario(api, scenario, data.request, {
    isCancelled: () => run.cancelled,
    onInterruptReady: interrupt => { run.interrupt = interrupt },
    onPhase: phase => send({ type: 'progress', requestId: run.id, phase }),
  })
  active = undefined
  send({ type: 'result', requestId: run.id, result })
}
