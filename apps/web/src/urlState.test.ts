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
  timeoutSeconds: 30,
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
      timeoutSeconds: 120,
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

  it.each(['0', '1', '-1', '121', '30.5', 'forever'])('rejects invalid timeout value %s', (value) => {
    expect(settingsFromUrl(defaults, `?timeout=${value}`).timeoutSeconds).toBe(30)
  })

  it('accepts supported timeout presets and omits the default from shared URLs', () => {
    expect(settingsFromUrl(defaults, '?timeout=5').timeoutSeconds).toBe(5)
    expect(settingsFromUrl(defaults, '?timeout=120').timeoutSeconds).toBe(120)
    expect(settingsToSearch(defaults)).not.toContain('timeout')
  })
})
