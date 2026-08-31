import { describe, expect, it } from 'vitest'
import type { ScenarioSettings } from './types'
import { experienceFromUrl, settingsFromUrl, settingsToSearch } from './urlState'

const settings: ScenarioSettings = {
  budget: 4,
  selectedPairKeys: ['north::south'],
  forced: [],
  locked: [],
  emergencyPermeable: true,
  objectiveMode: 'balanced',
  timeoutSeconds: 30,
}

describe('experience URL state', () => {
  it('defaults to the Otaniemi research experience', () => {
    expect(experienceFromUrl('')).toBe('resilience')
    expect(experienceFromUrl('?experience=unknown')).toBe('resilience')
  })

  it('round-trips the Kallio baseline alongside solver settings', () => {
    const search = settingsToSearch({ ...settings, budget: 6 }, 'baseline')
    expect(experienceFromUrl(search)).toBe('baseline')
    expect(settingsFromUrl(settings, search).budget).toBe(6)
    expect(new URLSearchParams(search).get('experience')).toBe('baseline')
  })
})

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
    expect(settingsFromUrl(settings, settingsToSearch(source))).toEqual(source)
  })

  it('rejects an out-of-range budget', () => {
    expect(settingsFromUrl(settings, '?budget=999').budget).toBe(4)
  })

  it('keeps the default budget when the URL omits it', () => {
    expect(settingsFromUrl(settings, '').budget).toBe(4)
  })

  it.each(['0', '1', '-1', '121', '30.5', 'forever'])('rejects invalid timeout value %s', (value) => {
    expect(settingsFromUrl(settings, `?timeout=${value}`).timeoutSeconds).toBe(30)
  })

  it('accepts supported timeout presets and omits the default from shared URLs', () => {
    expect(settingsFromUrl(settings, '?timeout=5').timeoutSeconds).toBe(5)
    expect(settingsFromUrl(settings, '?timeout=120').timeoutSeconds).toBe(120)
    expect(settingsToSearch(settings)).not.toContain('timeout')
  })
})
