import { describe, expect, it } from 'vitest'
import { statusFromResult } from './resultStatus'
import type { SolveResult } from './types'

function result(status: string, verificationStatus: string, selected: string[] = []): SolveResult {
  return {
    status,
    selected_intervention_ids: selected,
    objective_values: {},
    verification_status: verificationStatus,
    address_access_summary: {},
    portal_connectivity_summary: {},
    local_detour_metrics: {},
    timing_ms: 0,
    iteration_count: 0,
    explanation: '',
    snapshot_id: 'snapshot-test',
    solve_id: 'solve-test',
  }
}

describe('statusFromResult', () => {
  it('accepts an independently verified optimal result', () => {
    expect(statusFromResult(result('verified_optimal', 'independently_verified', ['c-1']))).toBe('verified_optimal')
  })

  it('never promotes raw or explicitly unverified candidates', () => {
    expect(statusFromResult(result('sat', 'not_verified', ['c-1']))).toBe('data_error')
    expect(statusFromResult(result('optimal', 'independently_verified', ['c-1']))).toBe('data_error')
    expect(statusFromResult(result('verified_optimal', 'not_verified', ['c-1']))).toBe('data_error')
    expect(statusFromResult(result('mystery', 'unknown', ['c-1']))).toBe('data_error')
  })

  it('requires a solver or graph proof for verified UNSAT', () => {
    expect(statusFromResult(result('verified_unsat', 'z3_unsat_core'))).toBe('verified_unsat')
    expect(statusFromResult(result('verified_unsat', 'graph_unblockable_route'))).toBe('verified_unsat')
    expect(statusFromResult(result('unsat', 'z3_unsat_core'))).toBe('data_error')
    expect(statusFromResult(result('verified_unsat', 'not_verified'))).toBe('data_error')
  })

  it('preserves explicitly indeterminate terminal states', () => {
    expect(statusFromResult(result('timeout', 'not_verified'))).toBe('timeout')
    expect(statusFromResult(result('cancelled', 'not_verified'))).toBe('cancelled')
    expect(statusFromResult(result('data_error', 'not_verified'))).toBe('data_error')
  })
})
