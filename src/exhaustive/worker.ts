import { solveByEnumeration } from './model.ts'
import { validateScenario } from '../core/validate.ts'
import type { Scenario, WorkerRequest, WorkerResponse } from '../core/types.ts'

const send = (message: WorkerResponse) => self.postMessage(message)
let scenario: Scenario | undefined
let active: { id: number; cancelled: boolean } | undefined
self.onmessage = async ({ data }: MessageEvent<WorkerRequest>) => {
  if (data.type === 'init') {
    try { validateScenario(data.scenario); scenario = data.scenario; send({ type: 'ready' }) }
    catch (error) { send({ type: 'init-error', message: `Could not initialise exhaustive search: ${String(error)}` }) }
    return
  }
  if (data.type === 'cancel') { if (active?.id === data.requestId) active.cancelled = true; return }
  if (!scenario || active) {
    send({ type: 'result', requestId: data.requestId, result: { status: 'error', message: 'Exhaustive search is not ready or is already busy.', elapsedMs: 0 } })
    return
  }
  const run = { id: data.requestId, cancelled: false }
  active = run
  const result = await solveByEnumeration(scenario, data.request, {
    isCancelled: () => run.cancelled,
    onPhase: phase => send({ type: 'progress', requestId: run.id, phase }),
  })
  active = undefined
  send({ type: 'result', requestId: run.id, result })
}
