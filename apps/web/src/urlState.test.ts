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
  it('defaults to the neutral experiment overview', () => {
    expect(experienceFromUrl('')).toBe('overview')
    expect(experienceFromUrl('?experience=unknown')).toBe('overview')
  })

  it('round-trips all explicit experiments alongside solver settings', () => {
    const search = settingsToSearch({ ...settings, budget: 6 }, 'baseline')
    expect(experienceFromUrl(search)).toBe('baseline')
    expect(settingsFromUrl(settings, search).budget).toBe(6)
    expect(new URLSearchParams(search).get('experience')).toBe('baseline')

    const resilienceSearch = settingsToSearch(settings, 'resilience')
    expect(experienceFromUrl(resilienceSearch)).toBe('resilience')
    expect(new URLSearchParams(resilienceSearch).get('experience')).toBe('resilience')

    const coverageSearch = settingsToSearch(settings, 'coverage')
    expect(experienceFromUrl(coverageSearch)).toBe('coverage')
    expect(new URLSearchParams(coverageSearch).get('experience')).toBe('coverage')
  })

  it('keeps the overview URL free of experiment settings', () => {
    expect(settingsToSearch({ ...settings, budget: 6 }, 'overview')).toBe('')
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
