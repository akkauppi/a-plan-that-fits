import { describe, expect, it } from 'vitest'
import { settingsFromUrl, settingsToSearch } from './urlState'
import type { ScenarioSettings } from './types'

const defaults: ScenarioSettings = {
  budget: 4,
  selectedPairKeys: ['north::south'],
  forced: [],
  locked: [],
  emergencyPermeable: true,
  objectiveMode: 'balanced',
}

describe('shareable scenario state', () => {
  it('round-trips constraints and solver assumptions', () => {
    const source: ScenarioSettings = {
      budget: 5,
      selectedPairKeys: ['east::west', 'north::south'],
      forced: ['candidate:10'],
      locked: ['candidate:03'],
      emergencyPermeable: false,
      objectiveMode: 'access',
    }
    const parsed = settingsFromUrl(defaults, settingsToSearch(source))
    expect(parsed).toEqual(source)
  })

  it('rejects an out-of-range budget', () => {
    expect(settingsFromUrl(defaults, '?budget=999').budget).toBe(4)
  })

  it('keeps the default budget when the URL omits it', () => {
    expect(settingsFromUrl(defaults, '').budget).toBe(4)
  })
})
