import assert from 'node:assert/strict'
import test from 'node:test'
import { comparisonConclusion } from '../src/ui/comparison.ts'

test('only matching feasibility conclusions establish agreement', () => {
  for (const status of ['feasible', 'unsat']) {
    const summary = comparisonConclusion(status, status)
    assert.equal(summary.kind, 'agrees')
    assert.match(summary.message, /does not validate the real-world assumptions/)
  }
  assert.equal(comparisonConclusion('feasible', 'unsat').kind, 'disagrees')
  assert.equal(comparisonConclusion('unsat', 'feasible').kind, 'disagrees')
})

test('timeouts, cancellations and errors never imply agreement, even when identical', () => {
  const statuses = ['feasible', 'unsat', 'timeout', 'cancelled', 'error']
  for (const incomplete of ['timeout', 'cancelled', 'error']) {
    for (const other of statuses) {
      assert.equal(comparisonConclusion(incomplete, other).kind, 'inconclusive')
      assert.equal(comparisonConclusion(other, incomplete).kind, 'inconclusive')
    }
  }
})
