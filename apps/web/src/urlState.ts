import type { ScenarioSettings } from './types'

export type Experience = 'resilience' | 'baseline'

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
  return new URLSearchParams(search).get('experience') === 'baseline' ? 'baseline' : 'resilience'
}

export function settingsToSearch(
  settings: ScenarioSettings,
  experience: Experience = 'resilience',
): string {
  const params = new URLSearchParams()
  if (experience === 'baseline') params.set('experience', 'baseline')
  if (settings.budget !== 4) params.set('budget', String(settings.budget))
  params.set('pairs', settings.selectedPairKeys.map(encodeURIComponent).join(','))
  if (settings.forced.length) params.set('force', settings.forced.map(encodeURIComponent).join(','))
  if (settings.locked.length) params.set('open', settings.locked.map(encodeURIComponent).join(','))
  if (!settings.emergencyPermeable) params.set('emergency', 'fixed')
  if (settings.objectiveMode !== 'balanced') params.set('objective', settings.objectiveMode)
  if (settings.timeoutSeconds !== 30) params.set('timeout', String(settings.timeoutSeconds))
  const query = params.toString()
  return query ? `?${query}` : ''
}

export function replaceSettingsUrl(
  settings: ScenarioSettings,
  experience: Experience = 'resilience',
): void {
  const url = new URL(window.location.href)
  url.search = settingsToSearch(settings, experience)
  window.history.replaceState(null, '', url)
}
