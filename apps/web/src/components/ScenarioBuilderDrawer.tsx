import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Archive,
  Building2,
  Check,
  CircleStop,
  Database,
  KeyRound,
  LoaderCircle,
  MapPinned,
  RefreshCw,
  Route,
  TriangleAlert,
  Waves,
  X,
} from 'lucide-react'
import {
  ApiError,
  cancelBuilderJob,
  getBuilderCatalog,
  getBuilderJob,
  preflightBuilder,
  startBuilderJob,
} from '../api'
import type {
  BuilderCatalog,
  BuilderJob,
  BuilderJobStatus,
  BuilderPreflight,
  BuilderSelection,
  BuilderSourceReadiness,
} from '../types'
import { LocationPickerMap } from './LocationPickerMap'

const ACTIVE_JOB_STATES: BuilderJobStatus[] = [
  'queued',
  'preflighting',
  'building',
  'cancellation_requested',
]

const DEFAULT_CUSTOM_AREA = {
  kind: 'point_radius' as const,
  longitude: 24.827,
  latitude: 60.184,
  radius_m: 1_000,
}

interface ScenarioBuilderDrawerProps {
  onClose: () => void
}

export function ScenarioBuilderDrawer({ onClose }: ScenarioBuilderDrawerProps) {
  const [catalog, setCatalog] = useState<BuilderCatalog>()
  const [mode, setMode] = useState<'preset' | 'custom'>('preset')
  const [customArea, setCustomArea] = useState(DEFAULT_CUSTOM_AREA)
  const [preflight, setPreflight] = useState<BuilderPreflight>()
  const [job, setJob] = useState<BuilderJob>()
  const [loading, setLoading] = useState(true)
  const [preflighting, setPreflighting] = useState(false)
  const [allowRefresh, setAllowRefresh] = useState(false)
  const [error, setError] = useState<string>()

  const selection = useMemo<BuilderSelection>(() => (
    mode === 'preset'
      ? { preset_id: 'otaniemi-coastal-v1' }
      : { area: customArea }
  ), [customArea, mode])

  const runPreflight = useCallback(async (
    nextSelection: BuilderSelection,
    signal?: AbortSignal,
  ) => {
    setPreflighting(true)
    setError(undefined)
    setPreflight(undefined)
    setJob(undefined)
    try {
      const result = await preflightBuilder(nextSelection, signal)
      setPreflight(result)
    } catch (caught: unknown) {
      if ((caught as Error).name !== 'AbortError') {
        setError(caught instanceof ApiError ? caught.message : 'The location could not be checked.')
      }
    } finally {
      if (!signal?.aborted) setPreflighting(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    getBuilderCatalog(controller.signal)
      .then((result) => {
        setCatalog(result)
        setLoading(false)
        return runPreflight({ preset_id: result.default_preset_id }, controller.signal)
      })
      .catch((caught: unknown) => {
        if ((caught as Error).name !== 'AbortError') {
          setError(caught instanceof ApiError ? caught.message : 'Scenario builder is unavailable.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [runPreflight])

  const jobActive = job ? ACTIVE_JOB_STATES.includes(job.status) : false

  useEffect(() => {
    if (!job || !ACTIVE_JOB_STATES.includes(job.status)) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      getBuilderJob(job.job_id, controller.signal)
        .then(setJob)
        .catch((caught: unknown) => {
          if ((caught as Error).name !== 'AbortError') {
            setError(caught instanceof ApiError ? caught.message : 'Build status was interrupted.')
          }
        })
    }, 500)
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [job])

  const chooseMode = (nextMode: 'preset' | 'custom') => {
    if (jobActive) return
    setMode(nextMode)
    setPreflight(undefined)
    setJob(undefined)
    setError(undefined)
    setAllowRefresh(false)
    if (nextMode === 'preset') void runPreflight({ preset_id: 'otaniemi-coastal-v1' })
  }

  const startBuild = async () => {
    if (!preflight || (!preflight.offline_build_ready && !allowRefresh)) return
    setError(undefined)
    try {
      const started = await startBuilderJob({
        ...selection,
        refresh: allowRefresh,
        ...(allowRefresh ? { confirm_live_source_refresh: 'REFRESH_OSM' as const } : {}),
      })
      setJob(started)
    } catch (caught: unknown) {
      setError(caught instanceof ApiError ? caught.message : 'The base-network build could not start.')
    }
  }

  const cancelBuild = async () => {
    if (!job) return
    try {
      await cancelBuilderJob(job.job_id)
      setJob({ ...job, status: 'cancellation_requested' })
    } catch (caught: unknown) {
      setError(caught instanceof ApiError ? caught.message : 'Cancellation could not be requested.')
    }
  }

  const preset = catalog?.presets.find((item) => item.id === 'otaniemi-coastal-v1')
  const buildAllowed = Boolean(preflight && (preflight.offline_build_ready || allowRefresh))

  return (
    <aside className="builder-drawer" aria-labelledby="builder-title" aria-modal="true" role="dialog">
      <header className="builder-drawer__header">
        <div>
          <span>Successor experiment</span>
          <h2 id="builder-title">Choose the network</h2>
        </div>
        <button
          type="button"
          className="icon-button"
          onClick={onClose}
          aria-label="Close study-area builder"
          disabled={jobActive}
        >
          <X size={17} />
        </button>
      </header>

      <p className="builder-lead">
        Prepare a reproducible base network for flood and roadworks resilience. This does not
        replace the open Kallio modal-filter solver.
      </p>

      {loading ? (
        <div className="builder-loading" role="status">
          <LoaderCircle className="spin" size={18} />Reading local source catalogue…
        </div>
      ) : (
        <>
          <fieldset className="builder-choice" disabled={jobActive}>
            <legend>Study area</legend>
            <label className={mode === 'preset' ? 'is-selected' : ''}>
              <input
                type="radio"
                name="builder-location"
                checked={mode === 'preset'}
                onChange={() => chooseMode('preset')}
              />
              <MapPinned size={18} />
              <span>
                <strong>{preset?.name ?? 'Otaniemi coast, Espoo'}</strong>
                <small>Default · frozen polygon · 2.743 km²</small>
              </span>
              <em>Recommended</em>
            </label>
            <label className={mode === 'custom' ? 'is-selected' : ''}>
              <input
                type="radio"
                name="builder-location"
                checked={mode === 'custom'}
                onChange={() => chooseMode('custom')}
              />
              <Route size={18} />
              <span>
                <strong>Custom Finland location</strong>
                <small>Point and radius · bounded preflight</small>
              </span>
            </label>
          </fieldset>

          {mode === 'custom' && (
            <section className="coordinate-picker" aria-label="Custom location coordinates">
              <div className="coordinate-picker__heading">
                <span><MapPinned size={14} />Pick coordinates</span>
                <small>WGS84 · Finland envelope</small>
              </div>
              <LocationPickerMap
                longitude={customArea.longitude}
                latitude={customArea.latitude}
                radiusM={customArea.radius_m}
                onPick={(longitude, latitude) => setCustomArea({
                  ...customArea,
                  longitude,
                  latitude,
                })}
              />
              <div className="coordinate-grid">
                <label>Longitude
                  <input
                    type="number"
                    min="19"
                    max="32"
                    step="0.001"
                    value={customArea.longitude}
                    onChange={(event) => setCustomArea({
                      ...customArea,
                      longitude: Number(event.target.value),
                    })}
                  />
                </label>
                <label>Latitude
                  <input
                    type="number"
                    min="59"
                    max="70.5"
                    step="0.001"
                    value={customArea.latitude}
                    onChange={(event) => setCustomArea({
                      ...customArea,
                      latitude: Number(event.target.value),
                    })}
                  />
                </label>
                <label>Radius
                  <select
                    value={customArea.radius_m}
                    onChange={(event) => setCustomArea({
                      ...customArea,
                      radius_m: Number(event.target.value),
                    })}
                  >
                    <option value="500">500 m</option>
                    <option value="750">750 m</option>
                    <option value="1000">1,000 m</option>
                    <option value="1500">1,500 m</option>
                    <option value="2000">2,000 m</option>
                  </select>
                </label>
              </div>
              <button
                type="button"
                className="builder-secondary"
                onClick={() => runPreflight(selection)}
                disabled={preflighting || jobActive}
              >
                {preflighting ? <LoaderCircle className="spin" size={14} /> : <RefreshCw size={14} />}
                Check bounds & sources
              </button>
              <p>No source request is made during this check.</p>
            </section>
          )}

          {preflighting && !preflight && (
            <div className="builder-loading" role="status">
              <LoaderCircle className="spin" size={16} />Validating the bounded recipe…
            </div>
          )}

          {preflight && (
            <>
              <section className="build-summary" aria-label="Study-area preflight summary">
                <div>
                  <span>Core area</span>
                  <strong>{preflight.area.core_area_km2.toLocaleString(undefined, { maximumFractionDigits: 3 })} km²</strong>
                </div>
                <div>
                  <span>Base snapshot</span>
                  <strong>
                    {preflight.build.status === 'verified_snapshot'
                      ? 'Verified'
                      : preflight.build.status === 'invalid_snapshot'
                        ? 'Invalid'
                        : 'Not built'}
                  </strong>
                </div>
                <div>
                  <span>Offline replay</span>
                  <strong>{preflight.offline_build_ready ? 'Ready' : 'Archive needed'}</strong>
                </div>
              </section>

              <section className="source-readiness" aria-labelledby="source-readiness-title">
                <div className="builder-section-heading">
                  <h3 id="source-readiness-title">Source readiness</h3>
                  <span>{preflight.sources.filter((source) => source.available_offline).length} archived</span>
                </div>
                <ul>
                  {preflight.sources.map((source) => (
                    <SourceRow key={source.adapter_id} source={source} />
                  ))}
                </ul>
                <p>
                  “Unknown coverage” is not a failure: these adapters validate request bounds but
                  do not claim completeness or absence of hazards.
                </p>
              </section>

              {preflight.analysis_artifacts?.flood_exposure.status === 'verified_exposure'
                && preflight.analysis_artifacts.flood_exposure.return_periods
                && (
                  <FloodExposureSummary
                    exposure={preflight.analysis_artifacts.flood_exposure}
                  />
                )}

              {!preflight.offline_build_ready && (
                <details className="refresh-disclosure">
                  <summary><Database size={14} />Need a new OSM archive?</summary>
                  <label>
                    <input
                      type="checkbox"
                      checked={allowRefresh}
                      onChange={(event) => setAllowRefresh(event.target.checked)}
                      disabled={jobActive}
                    />
                    <span>
                      <strong>Allow one live OSM refresh</strong>
                      <small>
                        Contact the fixed Overpass endpoint for this bounded recipe and freeze the response.
                      </small>
                    </span>
                  </label>
                </details>
              )}

              <button
                type="button"
                className={`builder-primary ${jobActive ? 'is-active' : ''}`}
                onClick={jobActive ? cancelBuild : startBuild}
                disabled={!jobActive && !buildAllowed}
              >
                {jobActive ? <CircleStop size={17} /> : allowRefresh ? <Database size={17} /> : <Archive size={17} />}
                <span>
                  <strong>
                    {jobActive
                      ? 'Cancel build'
                      : allowRefresh
                        ? 'Fetch & build base network'
                        : preflight.offline_build_ready
                          ? 'Rebuild from frozen archive'
                          : 'Live refresh required'}
                  </strong>
                  <small>
                    {jobActive
                      ? jobStatusLabel(job?.status)
                      : 'Deterministic graph artifact · active solver unchanged'}
                  </small>
                </span>
                {jobActive && <LoaderCircle className="spin" size={16} />}
              </button>
            </>
          )}

          {job && <BuildProgress job={job} />}

          {error && (
            <div className="builder-error" role="alert">
              <TriangleAlert size={17} /><span><strong>Builder unavailable</strong>{error}</span>
            </div>
          )}

          <footer className="builder-caveat">
            <Database size={15} />
            <div>
              <p>
                A completed job proves only that a bounded, checksummed base-network artifact was
                built and validated. Flood exposure, disruption passability, destinations, and
                resilient access have not yet been solved.
              </p>
              <p className="builder-attribution">
                Source data: © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a> · ODbL 1.0
                {mode === 'preset' && (
                  <> · adapted from <a href="https://www.syke.fi/en/environmental-data/open-web-services/web-map-services" target="_blank" rel="noreferrer">SYKE</a> and <a href="https://www.espoo.fi/en/open-data-of-the-geographic-information-unit" target="_blank" rel="noreferrer">City of Espoo</a> · CC BY 4.0</>
                )}
              </p>
            </div>
          </footer>
        </>
      )}
    </aside>
  )
}

function FloodExposureSummary({
  exposure,
}: {
  exposure: BuilderPreflight['analysis_artifacts']['flood_exposure']
}) {
  const periods = exposure.return_periods
  if (!periods) return null
  return (
    <section className="flood-exposure-summary" aria-labelledby="flood-exposure-title">
      <div className="builder-section-heading">
        <h3 id="flood-exposure-title"><Waves size={14} />Derived flood exposure</h3>
        <span><Check size={11} />Verified overlay</span>
      </div>
      <div className="flood-exposure-grid">
        {(['100', '1000'] as const).map((period) => (
          <div key={period}>
            <span>1 / {period} coastal zone</span>
            <strong>{periods[period].exposed_segments.toLocaleString()} segments</strong>
            <small>
              {(periods[period].exposed_length_m / 1_000).toLocaleString(undefined, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })} km horizontal overlap · {periods[period].vertical_review_segments} vertical checks
            </small>
          </div>
        ))}
      </div>
      <p>{exposure.message}</p>
      {exposure.snapshot_id && <code>{exposure.snapshot_id}</code>}
    </section>
  )
}

function SourceRow({ source }: { source: BuilderSourceReadiness }) {
  const icon = source.role === 'flood_hazard'
    ? <Waves size={15} />
    : source.role === 'municipal_context'
      ? <Building2 size={15} />
      : source.role === 'elevation'
        ? <KeyRound size={15} />
        : source.role === 'roadworks'
          ? <TriangleAlert size={15} />
          : <Route size={15} />
  return (
    <li className={`source-row source-row--${source.readiness}`} title={source.message}>
      <span className="source-row__icon">{icon}</span>
      <span>
        <strong>{source.name}</strong>
        <small>
          {source.feature_count ? `${source.feature_count.toLocaleString()} features · ` : ''}
          coverage {source.spatial_coverage}
        </small>
      </span>
      <b>{readinessLabel(source.readiness)}</b>
    </li>
  )
}

function BuildProgress({ job }: { job: BuilderJob }) {
  const verified = job.status === 'verified'
  const contradiction = job.status === 'failed' || job.status === 'missing_archive'
  return (
    <section className={`build-progress ${verified ? 'is-verified' : ''} ${contradiction ? 'has-error' : ''}`} aria-live="polite">
      <div className="builder-section-heading">
        <h3>{verified ? 'Base network ready' : contradiction ? 'Build stopped' : 'Build activity'}</h3>
        <span>{jobStatusLabel(job.status)}</span>
      </div>
      {job.result?.snapshot_id && (
        <div className="build-result">
          <Check size={17} />
          <span>
            <strong>{job.result.snapshot_id}</strong>
            <small>
              {job.result.node_count?.toLocaleString() ?? '—'} nodes · {job.result.directed_edge_count?.toLocaleString() ?? '—'} directed edges
            </small>
          </span>
        </div>
      )}
      {job.error && <p className="build-error-copy">{job.error.message}</p>}
      <ol>
        {job.events.map((event) => (
          <li key={event.sequence}>
            <i>{event.sequence}</i>
            <span><strong>{event.message}</strong><small>{formatTime(event.timestamp)}</small></span>
          </li>
        ))}
      </ol>
    </section>
  )
}

function readinessLabel(readiness: BuilderSourceReadiness['readiness']): string {
  if (readiness === 'archived') return 'Archived'
  if (readiness === 'refresh_required') return 'Refresh needed'
  if (readiness === 'invalid_archive') return 'Invalid'
  if (readiness === 'credentials_required') return 'Key needed'
  if (readiness === 'user_source_required') return 'User source'
  return 'Missing'
}

function jobStatusLabel(status?: BuilderJobStatus): string {
  if (!status) return 'Starting'
  if (status === 'preflighting') return 'Checking bounds'
  if (status === 'building') return 'Building graph'
  if (status === 'cancellation_requested') return 'Stopping safely'
  if (status === 'verified') return 'Verified artifact'
  if (status === 'missing_archive') return 'Archive missing'
  if (status === 'failed') return 'Data error'
  if (status === 'cancelled') return 'Cancelled'
  return 'Queued'
}

function formatTime(timestamp: string): string {
  const date = new Date(timestamp)
  return Number.isNaN(date.getTime()) ? timestamp : date.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}
