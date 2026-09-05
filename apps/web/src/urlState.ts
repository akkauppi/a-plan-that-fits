import type { ScenarioSettings } from './types'

export type Experience = 'overview' | 'resilience' | 'coverage' | 'baseline'

const safeIds = (value: string | null): string[] =>
  value?.split(',').map(decodeURIComponent).filter(Boolean).slice(0, 100) ?? []

const SUPPORTED_TIMEOUTS = new Set([5, 10, 30, 60, 120])

export function settingsFromUrl(fallback: ScenarioSettings, search = window.location.search): ScenarioSettings {
  const params = new URLSearchParams(search)
  const rawBudget = params.has('budget') ? Number(params.get('budget')) : Number.NaN
  const rawTimeout = params.has('timeout') ? Number(params.get('timeout')) : Number.NaN
  const mode = params.get('objective')
  return {
    budget: Number.isInteger(rawBudget) && rawBudget >= 0 && rawBudget <= 12 ? rawBudget : fallback.budget,
    selectedPairKeys: params.has('pairs') ? safeIds(params.get('pairs')) : fallback.selectedPairKeys,
    forced: params.has('force') ? safeIds(params.get('force')) : fallback.forced,
    locked: params.has('open') ? safeIds(params.get('open')) : fallback.locked,
    emergencyPermeable: params.get('emergency') !== 'fixed',
    objectiveMode: mode === 'fewest' || mode === 'access' ? mode : fallback.objectiveMode,
    timeoutSeconds: Number.isInteger(rawTimeout) && SUPPORTED_TIMEOUTS.has(rawTimeout)
      ? rawTimeout
      : fallback.timeoutSeconds,
  }
}

export function experienceFromUrl(search = window.location.search): Experience {
  const experience = new URLSearchParams(search).get('experience')
  if (experience === 'baseline' || experience === 'resilience' || experience === 'coverage') return experience
  return 'overview'
}

export function settingsToSearch(
  settings: ScenarioSettings,
  experience: Experience = 'baseline',
): string {
  if (experience === 'overview') return ''
  if (experience === 'resilience') return '?experience=resilience'
  if (experience === 'coverage') return '?experience=coverage'
  const params = new URLSearchParams()
  params.set('experience', 'baseline')
  if (settings.budget !== 4) params.set('budget', String(settings.budget))
  // URLSearchParams performs the percent-encoding. Encoding each identifier first
  // would leave `%3A`-style fragments visible after a normal query-string decode.
  params.set('pairs', settings.selectedPairKeys.join(','))
  if (settings.forced.length) params.set('force', settings.forced.join(','))
  if (settings.locked.length) params.set('open', settings.locked.join(','))
  if (!settings.emergencyPermeable) params.set('emergency', 'fixed')
  if (settings.objectiveMode !== 'balanced') params.set('objective', settings.objectiveMode)
  if (settings.timeoutSeconds !== 30) params.set('timeout', String(settings.timeoutSeconds))
  const query = params.toString()
  return query ? `?${query}` : ''
}

export function replaceSettingsUrl(
  settings: ScenarioSettings,
  experience: Experience = 'baseline',
): void {
  const url = new URL(window.location.href)
  url.search = settingsToSearch(settings, experience)
  window.history.replaceState(null, '', url)
}
