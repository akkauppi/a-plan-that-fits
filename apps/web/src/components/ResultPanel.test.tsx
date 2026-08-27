import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { SolveResult } from '../types'
import { ResultPanel } from './ResultPanel'

const unsatResult: SolveResult = {
  status: 'verified_unsat',
  selected_intervention_ids: [],
  objective_values: {},
  verification_status: 'z3_unsat_core',
  address_access_summary: {},
  portal_connectivity_summary: {},
  local_detour_metrics: {},
  timing_ms: 10,
  iteration_count: 1,
  explanation: 'The named assumptions conflict.',
  snapshot_id: 'snapshot-test',
  solve_id: 'solve-test',
  suggested_relaxations: [
    { type: 'increase_budget', value: 6, label: 'Try a budget of 6' },
    { type: 'unlock_street', candidate_id: 'candidate-lock-target', label: 'Unlock Target Street' },
    { type: 'release_forced_intervention', candidate_id: 'candidate-force-target', label: 'Release Forced Street' },
    { type: 'remove_portal_pair', pair: { a: 'portal-north', b: 'portal-south' }, label: 'Remove north–south pair' },
  ],
}

function props(result: SolveResult = unsatResult) {
  return {
    result,
    status: 'verified_unsat' as const,
    candidates: [],
    onSelectCandidate: vi.fn(),
    onNext: vi.fn(),
    onCompare: vi.fn(),
    onRaiseBudget: vi.fn(),
    onUnlock: vi.fn(),
    onReleaseForced: vi.fn(),
    onRemovePortalPair: vi.fn(),
    onReviewAssumptions: vi.fn(),
    onOpenMethod: vi.fn(),
    canUnlock: true,
    alternativeCount: 0,
    nextPending: false,
  }
}

describe('UNSAT relaxation actions', () => {
  it('dispatches the exact budget, candidate, and portal-pair targets named by the solver', async () => {
    const callbacks = props()
    render(<ResultPanel {...callbacks} />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: /Try a budget of 6/i }))
    await user.click(screen.getByRole('button', { name: /Unlock Target Street/i }))
    await user.click(screen.getByRole('button', { name: /Release Forced Street/i }))
    await user.click(screen.getByRole('button', { name: /Remove north–south pair/i }))

    expect(callbacks.onRaiseBudget).toHaveBeenCalledWith(6)
    expect(callbacks.onUnlock).toHaveBeenCalledWith('candidate-lock-target')
    expect(callbacks.onReleaseForced).toHaveBeenCalledWith('candidate-force-target')
    expect(callbacks.onRemovePortalPair).toHaveBeenCalledWith({ a: 'portal-north', b: 'portal-south' })
  })

  it('does not mutate an arbitrary constraint when target metadata is missing', async () => {
    const callbacks = props({
      ...unsatResult,
      suggested_relaxations: [{ type: 'unlock_street', label: 'Unlock an unspecified street' }],
    })
    render(<ResultPanel {...callbacks} />)

    await userEvent.click(screen.getByRole('button', { name: /Unlock an unspecified street/i }))

    expect(callbacks.onUnlock).not.toHaveBeenCalled()
    expect(callbacks.onReviewAssumptions).toHaveBeenCalledOnce()
  })
})
