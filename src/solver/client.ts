import type { Scenario, SolveRequest, SolveResult, WorkerRequest, WorkerResponse } from '../core/types.ts'

export interface ClientState {
  phase: 'loading' | 'ready' | 'solving' | 'verifying' | 'error'
  result?: SolveResult
  message?: string
}
export interface WorkerPort {
  onmessage: ((event: MessageEvent<WorkerResponse>) => void) | null
  onerror: ((event: ErrorEvent) => void) | null
  postMessage(message: WorkerRequest): void
  terminate(): void
}

// One request at a time. Generation + request IDs protect against late results,
// including a terminated worker returning after cancellation or a restart.
export class SolverClient {
  private worker?: WorkerPort
  private generation = 0
  private sequence = 0
  private active?: number
  private timer?: ReturnType<typeof setTimeout>
  private disposed = false
  private phase: ClientState['phase'] = 'loading'
  private scenario: Scenario
  private makeWorker: () => WorkerPort
  private changed: (state: ClientState) => void
  private label: string

  constructor(scenario: Scenario, makeWorker: () => WorkerPort, changed: (state: ClientState) => void, label = 'Z3') {
    this.scenario = scenario; this.makeWorker = makeWorker; this.changed = changed; this.label = label
    this.start()
  }
  private publish(state: ClientState) { this.phase = state.phase; if (!this.disposed) this.changed(state) }
  private start(result?: SolveResult) {
    clearTimeout(this.timer)
    this.worker?.terminate()
    const generation = ++this.generation
    this.active = undefined
    this.publish({ phase: 'loading', result })
    try {
      this.worker = this.makeWorker()
      this.worker.onmessage = ({ data }) => {
        if (this.disposed || generation !== this.generation) return
        if (data.type === 'ready') { clearTimeout(this.timer); this.publish({ phase: 'ready', result }); return }
        if (data.type === 'init-error') { this.fail(data.message); return }
        if (data.requestId !== this.active) return
        if (data.type === 'progress') { this.publish({ phase: data.phase }); return }
        clearTimeout(this.timer); this.active = undefined
        this.publish({ phase: 'ready', result: data.result })
      }
      this.worker.onerror = event => { if (generation === this.generation) this.fail(event.message || 'Browser worker failed. Try reloading this page.') }
      this.timer = setTimeout(() => this.fail(`${this.label} did not start within 60 seconds. Check the browser support and reload.`), 60000)
      this.worker.postMessage({ type: 'init', scenario: this.scenario })
    } catch (error) { this.fail(String(error)) }
  }
  private fail(message: string) {
    clearTimeout(this.timer); this.active = undefined; this.generation++
    this.worker?.terminate(); this.publish({ phase: 'error', message })
  }
  solve(request: SolveRequest) {
    if (this.phase !== 'ready' || this.active !== undefined) return false
    const requestId = ++this.sequence
    this.active = requestId
    this.publish({ phase: 'solving' })
    this.timer = setTimeout(() => this.start({ status: 'timeout', message: `${this.label} exceeded its time limit. No conclusion was reached; restarting the solver.`, elapsedMs: request.timeoutMs + 5000 }), request.timeoutMs + 5000)
    this.worker!.postMessage({ type: 'solve', requestId, request })
    return true
  }
  cancel() {
    if (this.active === undefined) return
    this.worker?.postMessage({ type: 'cancel', requestId: this.active })
    // Termination is also a hard cancellation fallback, independent of WASM.
    this.start({ status: 'cancelled', message: 'Cancelled. No feasibility claim was made; the solver is restarting.', elapsedMs: 0 })
  }
  dispose() {
    this.disposed = true; this.generation++; clearTimeout(this.timer)
    this.worker?.terminate()
  }
}
