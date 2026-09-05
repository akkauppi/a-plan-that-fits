"""Bounded MML/NLS Elevation Model 2 m acquisition and offline replay.

The adapter requests one exact native-grid ASCII window from the official WCS.
Authentication is deliberately outside the query URL: an explicit refresh reads
``MML_API_KEY`` at runtime and sends it as the HTTP Basic username with an empty
password.  The credential is never accepted as a recipe parameter or persisted.

Elevation is archived as source/quality-control evidence only.  This module does
not derive flood extent, road passability, closures, or safe routes.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import math
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .adapters import AdapterConfigurationError, SourceAcquisitionContext
from .models import (
    ANALYSIS_CRS,
    CoverageAssessment,
    LicenceRecord,
    ScenarioRecipe,
    SourceSnapshotMetadata,
)
from .osm import canonicalize_network_context

MML_WCS_ENDPOINT = (
    "https://avoin-karttakuva.maanmittauslaitos.fi/"
    "ortokuvat-ja-korkeusmallit/wcs/v2"
)
MML_ADAPTER_ID = "mml_elevation"
MML_ADAPTER_VERSION = "1.0.1"
MML_WCS_VERSION = "2.0.1"
MML_COVERAGE_ID = "korkeusmalli_2m"
MML_OUTPUT_FORMAT = "text/plain"
MML_SOURCE_CRS = ANALYSIS_CRS
MML_VERTICAL_CRS = "EPSG:3900"
MML_API_KEY_ENV = "MML_API_KEY"

NATIVE_RESOLUTION_M = 2.0
MAX_QUERY_EXTENT_M = 10_000.0
MAX_GRID_DIMENSION = 5_000
MAX_GRID_CELLS = MAX_GRID_DIMENSION * MAX_GRID_DIMENSION
MAX_RESPONSE_BYTES = 256 * 1024 * 1024
DEFAULT_TIMEOUT_S = 60
MIN_TIMEOUT_S = 10
MAX_TIMEOUT_S = 120
BBOX_DECIMALS = 3

FetchTransport = Callable[[str, int, str], bytes]
Clock = Callable[[], datetime]


class MmlArchiveError(ValueError):
    """Raised when an MML response, credential, or frozen archive is invalid."""


@dataclass(frozen=True)
class AsciiGridReport:
    ncols: int
    nrows: int
    nodata_value: float | None
    valid_cell_count: int
    nodata_cell_count: int
    minimum_elevation_m: float
    maximum_elevation_m: float


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _checked_clock(clock: Clock) -> datetime:
    moment = clock()
    if moment.tzinfo is None:
        raise ValueError("MML adapter clock must return a timezone-aware datetime")
    return moment


def _window_shape(bbox: tuple[float, float, float, float]) -> tuple[int, int]:
    minimum_x, minimum_y, maximum_x, maximum_y = bbox
    values = (minimum_x, minimum_y, maximum_x, maximum_y)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("MML query window contains a non-finite coordinate")
    width = maximum_x - minimum_x
    height = maximum_y - minimum_y
    if width <= 0 or height <= 0:
        raise ValueError("MML query window has an empty metric bounding box")
    if width > MAX_QUERY_EXTENT_M or height > MAX_QUERY_EXTENT_M:
        raise ValueError("MML query window exceeds the fixed 10 km width/height WCS limit")

    ncols_float = width / NATIVE_RESOLUTION_M
    nrows_float = height / NATIVE_RESOLUTION_M
    ncols = round(ncols_float)
    nrows = round(nrows_float)
    if not math.isclose(ncols_float, ncols, abs_tol=1e-9) or not math.isclose(
        nrows_float, nrows, abs_tol=1e-9
    ):
        raise ValueError("MML query window is not aligned to the native 2 m grid")
    if ncols > MAX_GRID_DIMENSION or nrows > MAX_GRID_DIMENSION:
        raise ValueError("MML query window exceeds the fixed 5000-cell width/height limit")
    if ncols * nrows > MAX_GRID_CELLS:
        raise ValueError("MML query window exceeds the fixed cell-count limit")
    return ncols, nrows


def _query_bbox(recipe: ScenarioRecipe) -> tuple[float, float, float, float]:
    context = canonicalize_network_context(recipe)
    minimum_x, minimum_y, maximum_x, maximum_y = context.analysis.bounds
    resolution = NATIVE_RESOLUTION_M
    bbox = (
        math.floor(minimum_x / resolution) * resolution,
        math.floor(minimum_y / resolution) * resolution,
        math.ceil(maximum_x / resolution) * resolution,
        math.ceil(maximum_y / resolution) * resolution,
    )
    bounded = tuple(round(value, BBOX_DECIMALS) for value in bbox)
    _window_shape(bounded)
    return bounded  # type: ignore[return-value]


def derive_wcs_url(bbox: tuple[float, float, float, float]) -> str:
    """Build the fixed WCS 2.0.1 request without authentication material."""

    _window_shape(bbox)
    minimum_x, minimum_y, maximum_x, maximum_y = bbox
    parameters = (
        ("service", "WCS"),
        ("version", MML_WCS_VERSION),
        ("request", "GetCoverage"),
        ("CoverageID", MML_COVERAGE_ID),
        ("format", MML_OUTPUT_FORMAT),
        (
            "subset",
            f"E({minimum_x:.{BBOX_DECIMALS}f},{maximum_x:.{BBOX_DECIMALS}f})",
        ),
        (
            "subset",
            f"N({minimum_y:.{BBOX_DECIMALS}f},{maximum_y:.{BBOX_DECIMALS}f})",
        ),
    )
    return f"{MML_WCS_ENDPOINT}?{urllib.parse.urlencode(parameters)}"


def _settings(context: SourceAcquisitionContext) -> int:
    parameters = context.declaration.parameters
    unknown = sorted(set(parameters) - {"wcs_timeout_s"})
    if unknown:
        raise AdapterConfigurationError(
            "unsupported mml_elevation source parameter(s): "
            + ", ".join(unknown)
            + "; endpoint, coverage, request shape, format, CRS, and credentials are fixed"
        )
    timeout_s = parameters.get("wcs_timeout_s", DEFAULT_TIMEOUT_S)
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, int):
        raise AdapterConfigurationError("mml_elevation wcs_timeout_s must be an integer")
    if not MIN_TIMEOUT_S <= timeout_s <= MAX_TIMEOUT_S:
        raise AdapterConfigurationError(
            f"mml_elevation wcs_timeout_s must be {MIN_TIMEOUT_S}--{MAX_TIMEOUT_S} seconds"
        )
    return timeout_s


def _runtime_api_key() -> str:
    value = os.environ.get(MML_API_KEY_ENV)
    if value is None or not value.strip():
        raise MmlArchiveError(
            "MML_API_KEY is required for an explicit MML refresh; "
            "offline replay does not require credentials"
        )
    credential = value.strip()
    # The service keys are opaque HTTP Basic usernames. Control characters and a
    # colon would make the username/password boundary ambiguous.
    if (
        len(credential) > 500
        or ":" in credential
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in credential)
    ):
        raise MmlArchiveError("MML_API_KEY has an invalid credential format")
    return credential


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Keep Basic credentials on the single audited endpoint."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        raise MmlArchiveError("MML WCS redirect refused")


def _default_transport(url: str, timeout_s: int, api_key: str) -> bytes:
    basic_token = base64.b64encode(f"{api_key}:".encode("ascii")).decode("ascii")
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": MML_OUTPUT_FORMAT,
            "Authorization": f"Basic {basic_token}",
            "User-Agent": "Geospatial-Constraint-Lab-Scenario-Builder/1.0",
        },
    )
    try:
        opener = urllib.request.build_opener(_RejectRedirects())
        with opener.open(request, timeout=timeout_s) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise MmlArchiveError(f"MML WCS returned HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise MmlArchiveError("MML WCS request failed") from None
    if len(payload) > MAX_RESPONSE_BYTES:
        raise MmlArchiveError(
            f"MML response exceeds the fixed {MAX_RESPONSE_BYTES // (1024 * 1024)} MB limit"
        )
    return payload


def _finite_float(token: str | bytes, *, label: str) -> float:
    try:
        value = float(token)
    except ValueError as error:
        raise MmlArchiveError(f"MML ASCII grid {label} is not numeric") from error
    if not math.isfinite(value):
        raise MmlArchiveError(f"MML ASCII grid {label} is non-finite")
    return value


def _canonical_ascii_payload(
    payload: bytes,
    *,
    bbox: tuple[float, float, float, float],
) -> tuple[bytes, AsciiGridReport]:
    if len(payload) > MAX_RESPONSE_BYTES:
        raise MmlArchiveError(
            f"MML response exceeds the fixed {MAX_RESPONSE_BYTES // (1024 * 1024)} MB limit"
        )
    if not payload.isascii():
        raise MmlArchiveError("MML WCS response is not an ASCII grid")
    if b"\x00" in payload:
        raise MmlArchiveError("MML ASCII grid contains a NUL byte")

    source = io.BytesIO(payload)
    canonical = io.BytesIO()
    header: dict[str, str] = {}
    required_header_order = (
        "ncols",
        "nrows",
        "xllcorner",
        "yllcorner",
        "cellsize",
    )
    for index, expected_key in enumerate(required_header_order):
        raw_line = source.readline(MAX_RESPONSE_BYTES + 1)
        if not raw_line:
            raise MmlArchiveError("MML ASCII grid is missing its header or raster rows")
        parts = raw_line.decode("ascii").split()
        if len(parts) != 2:
            raise MmlArchiveError(f"MML ASCII grid header line {index + 1} is malformed")
        key = parts[0].lower()
        if key != expected_key:
            raise MmlArchiveError(
                f"MML ASCII grid header line {index + 1} must declare {expected_key}"
            )
        header[key] = parts[1]
        canonical.write(f"{key} {parts[1]}\n".encode("ascii"))

    # MML omits NODATA_value when the returned window contains a value for every
    # cell, while other compliant responses include it. Preserve either official
    # representation instead of inventing a sentinel for complete rasters.
    first_raster_line = source.readline(MAX_RESPONSE_BYTES + 1)
    if not first_raster_line:
        raise MmlArchiveError("MML ASCII grid is missing its raster rows")
    optional_parts = first_raster_line.decode("ascii").split()
    if optional_parts and optional_parts[0].lower() == "nodata_value":
        if len(optional_parts) != 2:
            raise MmlArchiveError("MML ASCII grid NODATA_value header is malformed")
        header["nodata_value"] = optional_parts[1]
        canonical.write(f"nodata_value {optional_parts[1]}\n".encode("ascii"))
        first_raster_line = b""
    for key in ("ncols", "nrows"):
        if not re.fullmatch(r"[1-9][0-9]*", header[key]):
            raise MmlArchiveError(f"MML ASCII grid {key} is not a positive integer")
    ncols = int(header["ncols"])
    nrows = int(header["nrows"])
    expected_ncols, expected_nrows = _window_shape(bbox)
    if (ncols, nrows) != (expected_ncols, expected_nrows):
        raise MmlArchiveError(
            "MML ASCII grid dimensions do not match the exact requested 2 m window"
        )

    xllcorner = _finite_float(header["xllcorner"], label="xllcorner")
    yllcorner = _finite_float(header["yllcorner"], label="yllcorner")
    cellsize = _finite_float(header["cellsize"], label="cellsize")
    nodata_value = (
        _finite_float(header["nodata_value"], label="NODATA_value")
        if "nodata_value" in header
        else None
    )
    if not math.isclose(xllcorner, bbox[0], abs_tol=1e-6) or not math.isclose(
        yllcorner, bbox[1], abs_tol=1e-6
    ):
        raise MmlArchiveError(
            "MML ASCII grid lower-left corner does not match the exact requested window"
        )
    if not math.isclose(cellsize, NATIVE_RESOLUTION_M, abs_tol=1e-9):
        raise MmlArchiveError("MML ASCII grid is not at the native 2 m resolution")

    valid_cell_count = 0
    nodata_cell_count = 0
    minimum_elevation = math.inf
    maximum_elevation = -math.inf
    for row_index in range(nrows):
        row = first_raster_line if row_index == 0 and first_raster_line else source.readline(
            MAX_RESPONSE_BYTES + 1
        )
        if not row:
            raise MmlArchiveError("MML ASCII grid row count does not match nrows")
        tokens = row.split()
        if len(tokens) != ncols:
            raise MmlArchiveError(
                f"MML ASCII grid row {row_index + 1} does not contain ncols values"
            )
        for token in tokens:
            value = _finite_float(token, label="cell value")
            if nodata_value is not None and value == nodata_value:
                nodata_cell_count += 1
            else:
                valid_cell_count += 1
                minimum_elevation = min(minimum_elevation, value)
                maximum_elevation = max(maximum_elevation, value)
        canonical.write(b" ".join(tokens) + b"\n")

    if source.read().strip():
        raise MmlArchiveError("MML ASCII grid row count does not match nrows")

    if valid_cell_count == 0:
        raise MmlArchiveError("MML ASCII grid contains no valid elevation cells")
    if valid_cell_count + nodata_cell_count != ncols * nrows:
        raise MmlArchiveError("MML ASCII grid cell count is internally inconsistent")

    return canonical.getvalue(), AsciiGridReport(
        ncols=ncols,
        nrows=nrows,
        nodata_value=nodata_value,
        valid_cell_count=valid_cell_count,
        nodata_cell_count=nodata_cell_count,
        minimum_elevation_m=minimum_elevation,
        maximum_elevation_m=maximum_elevation,
    )


def _archive_path_is_safe(workspace: Path, archive_name: Any) -> Path:
    if (
        not isinstance(archive_name, str)
        or Path(archive_name).name != archive_name
        or not archive_name.endswith(".asc.gz")
    ):
        raise MmlArchiveError("MML pointer contains an unsafe archive filename")
    archive_path = workspace / archive_name
    if not archive_path.is_file():
        raise MmlArchiveError(f"MML archive is missing at {archive_path}")
    return archive_path


def _decompress_limited(payload: bytes) -> bytes:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as stream:
            raw = stream.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, EOFError) as error:
        raise MmlArchiveError("MML archive is not valid gzip") from error
    if len(raw) > MAX_RESPONSE_BYTES:
        raise MmlArchiveError("MML archive expands beyond the fixed response limit")
    return raw


def _canonical_gzip(payload: bytes) -> bytes:
    """Return gzip bytes with fixed timestamp, no filename, and OS=unknown."""

    output = io.BytesIO()
    with gzip.GzipFile(
        filename="",
        mode="wb",
        compresslevel=9,
        fileobj=output,
        mtime=0,
    ) as stream:
        stream.write(payload)
    return output.getvalue()


class MmlElevationAdapter:
    """Acquire and replay one exact official Elevation Model 2 m WCS window."""

    adapter_id = MML_ADAPTER_ID

    def __init__(
        self,
        *,
        refresh: bool = False,
        transport: FetchTransport | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.refresh = refresh
        self._transport = transport or _default_transport
        self._clock = clock or (lambda: datetime.now(UTC))
        self._archive_path: Path | None = None
        self._manifest: dict[str, Any] | None = None

    @property
    def archive_path(self) -> Path:
        if self._archive_path is None:
            raise RuntimeError("MML elevation source has not been acquired or loaded")
        return self._archive_path

    @property
    def archive_manifest(self) -> dict[str, Any]:
        if self._manifest is None:
            raise RuntimeError("MML elevation source has not been acquired or loaded")
        return json.loads(json.dumps(self._manifest))

    def assess_coverage(self, recipe: ScenarioRecipe) -> CoverageAssessment:
        bbox = _query_bbox(recipe)
        ncols, nrows = _window_shape(bbox)
        evidence: dict[str, Any] = {
            "endpoint_controlled_by_adapter": True,
            "coverage_id": MML_COVERAGE_ID,
            "bounded_context_bbox_epsg3067": list(bbox),
            "native_resolution_m": NATIVE_RESOLUTION_M,
            "grid_dimensions": {"ncols": ncols, "nrows": nrows},
            "maximum_grid_dimension": MAX_GRID_DIMENSION,
            "credential_required_for_refresh": True,
            "credential_value_checked_during_acquisition_only": True,
            "credential_in_query_url": False,
            "elevation_is_not_flood_or_passability_evidence": True,
        }
        if self._manifest is not None:
            evidence["validated_responses"] = [
                {
                    "coverage_id": MML_COVERAGE_ID,
                    "valid_cell_count": self._manifest["valid_cell_count"],
                    "nodata_cell_count": self._manifest["nodata_cell_count"],
                }
            ]
        return CoverageAssessment(
            adapter_id=self.adapter_id,
            status="unknown",
            message=(
                "The requested native-grid window is within the fixed MML WCS limits. "
                "Product completeness is not inferred from those limits or from raster "
                "values; elevation alone does not establish flooding or road passability."
            ),
            checked_at=_checked_clock(self._clock),
            evidence=evidence,
        )

    def archive_pointer_path(self, context: SourceAcquisitionContext) -> Path:
        if context.declaration.adapter_id != self.adapter_id:
            raise AdapterConfigurationError(
                f"MmlElevationAdapter cannot preflight {context.declaration.adapter_id!r}"
            )
        if context.declaration.role != "elevation":
            raise AdapterConfigurationError(
                "mml_elevation adapter currently supports elevation only"
            )
        return context.workspace / f"{context.recipe.scenario_id}.mml-elevation-2m.archive.json"

    def acquire(self, context: SourceAcquisitionContext) -> SourceSnapshotMetadata:
        if context.declaration.adapter_id != self.adapter_id:
            raise AdapterConfigurationError(
                f"MmlElevationAdapter cannot acquire {context.declaration.adapter_id!r}"
            )
        if context.declaration.role != "elevation":
            raise AdapterConfigurationError(
                "mml_elevation adapter currently supports elevation only"
            )

        timeout_s = _settings(context)
        bbox = _query_bbox(context.recipe)
        query_url = derive_wcs_url(bbox)
        ncols, nrows = _window_shape(bbox)
        workspace = context.workspace
        workspace.mkdir(parents=True, exist_ok=True)
        pointer_path = self.archive_pointer_path(context)

        if self.refresh:
            api_key = _runtime_api_key()
            response = self._transport(query_url, timeout_s, api_key)
            canonical, report = _canonical_ascii_payload(response, bbox=bbox)
            compressed = _canonical_gzip(canonical)
            raw_sha256 = _sha256(canonical)
            archive_sha256 = _sha256(compressed)
            archive_name = (
                f"{context.recipe.scenario_id}.elevation-model-2m."
                f"{archive_sha256[:16]}.asc.gz"
            )
            archive_path = workspace / archive_name
            if archive_path.exists():
                if archive_path.read_bytes() != compressed:
                    raise MmlArchiveError(
                        f"content-addressed MML archive collision at {archive_path}"
                    )
            else:
                _atomic_write(archive_path, compressed)

            candidate_manifest: dict[str, Any] = {
                "schema_version": "1.0",
                "adapter_version": MML_ADAPTER_VERSION,
                "scenario_id": context.recipe.scenario_id,
                "recipe_sha256": context.recipe.sha256(),
                "endpoint": MML_WCS_ENDPOINT,
                "wcs_version": MML_WCS_VERSION,
                "coverage_id": MML_COVERAGE_ID,
                "output_format": MML_OUTPUT_FORMAT,
                "source_crs": MML_SOURCE_CRS,
                "vertical_crs": MML_VERTICAL_CRS,
                "subsetting_crs": MML_SOURCE_CRS,
                "network_context_buffer_m": context.recipe.network_context_buffer_m,
                "bbox": list(bbox),
                "native_resolution_m": NATIVE_RESOLUTION_M,
                "ncols": report.ncols,
                "nrows": report.nrows,
                "timeout_s": timeout_s,
                "query_url": query_url,
                "query_sha256": _sha256(query_url.encode("utf-8")),
                "credential_transport": "http_basic_username_password_empty",
                "credential_in_query_url": False,
                "acquired_at": _checked_clock(self._clock).isoformat(),
                "archive_file": archive_name,
                "archive_sha256": archive_sha256,
                "raw_sha256": raw_sha256,
                "byte_size": len(compressed),
                "valid_cell_count": report.valid_cell_count,
                "nodata_cell_count": report.nodata_cell_count,
                "nodata_value": report.nodata_value,
                "minimum_elevation_m": report.minimum_elevation_m,
                "maximum_elevation_m": report.maximum_elevation_m,
            }
            existing_manifest: Any = None
            if pointer_path.is_file():
                try:
                    existing_manifest = json.loads(pointer_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    existing_manifest = None
            existing_identity = (
                {key: value for key, value in existing_manifest.items() if key != "acquired_at"}
                if isinstance(existing_manifest, dict)
                else None
            )
            candidate_identity = {
                key: value for key, value in candidate_manifest.items() if key != "acquired_at"
            }
            if existing_identity == candidate_identity:
                manifest = existing_manifest
            else:
                manifest = candidate_manifest
                _atomic_write(pointer_path, _json_bytes(manifest))
        else:
            if not pointer_path.is_file():
                raise MmlArchiveError(
                    f"offline MML archive pointer is missing at {pointer_path}; "
                    "run an explicit credentialed refresh once"
                )
            try:
                manifest = json.loads(pointer_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise MmlArchiveError(
                    f"cannot read MML archive pointer {pointer_path}"
                ) from error

        self._validate_manifest(
            manifest,
            context=context,
            bbox=bbox,
            ncols=ncols,
            nrows=nrows,
            timeout_s=timeout_s,
            query_url=query_url,
        )
        archive_path = _archive_path_is_safe(workspace, manifest["archive_file"])
        compressed = archive_path.read_bytes()
        canonical = _decompress_limited(compressed)
        normalized, report = _canonical_ascii_payload(canonical, bbox=bbox)
        if normalized != canonical:
            raise MmlArchiveError("MML archive payload is not canonical ASCII grid data")
        if _sha256(canonical) != manifest["raw_sha256"]:
            raise MmlArchiveError("MML archive raw checksum does not match its pointer")
        report_values = {
            "ncols": report.ncols,
            "nrows": report.nrows,
            "valid_cell_count": report.valid_cell_count,
            "nodata_cell_count": report.nodata_cell_count,
            "nodata_value": report.nodata_value,
            "minimum_elevation_m": report.minimum_elevation_m,
            "maximum_elevation_m": report.maximum_elevation_m,
        }
        if any(manifest.get(key) != value for key, value in report_values.items()):
            raise MmlArchiveError("MML archive grid statistics do not match its pointer")

        acquired_at = datetime.fromisoformat(manifest["acquired_at"])
        self._archive_path = archive_path
        self._manifest = manifest
        return SourceSnapshotMetadata(
            adapter_id=self.adapter_id,
            source_name="National Land Survey of Finland Elevation Model 2 m",
            endpoint=MML_WCS_ENDPOINT,
            acquired_at=acquired_at,
            source_timestamp=None,
            query={
                "adapter_version": MML_ADAPTER_VERSION,
                "service": "WCS",
                "version": MML_WCS_VERSION,
                "request": "GetCoverage",
                "coverage_id": MML_COVERAGE_ID,
                "output_format": MML_OUTPUT_FORMAT,
                "source_crs": MML_SOURCE_CRS,
                "vertical_crs": MML_VERTICAL_CRS,
                "subsetting_crs": MML_SOURCE_CRS,
                "bounded_network_context_bbox": list(bbox),
                "network_context_buffer_m": context.recipe.network_context_buffer_m,
                "native_resolution_m": NATIVE_RESOLUTION_M,
                "grid_dimensions": {"ncols": ncols, "nrows": nrows},
                "query_url": query_url,
                "query_sha256": manifest["query_sha256"],
                "timeout_s": timeout_s,
                "credential_transport": "http_basic_username_password_empty",
                "credential_environment_variable": MML_API_KEY_ENV,
                "credential_in_query_url": False,
                "valid_cell_count": report.valid_cell_count,
                "nodata_cell_count": report.nodata_cell_count,
                "minimum_elevation_m": report.minimum_elevation_m,
                "maximum_elevation_m": report.maximum_elevation_m,
                "elevation_quality_control_only": True,
                "flood_hazard_not_derived": True,
                "passability_not_inferred": True,
            },
            source_crs=MML_SOURCE_CRS,
            normalized_crs=ANALYSIS_CRS,
            feature_count=report.valid_cell_count,
            licence=LicenceRecord(
                name="Creative Commons Attribution 4.0 International (CC BY 4.0)",
                url="https://creativecommons.org/licenses/by/4.0/",
                attribution=(
                    "Contains data from the National Land Survey of Finland "
                    "Elevation Model 2 m."
                ),
                obligations=[
                    "Attribute the National Land Survey of Finland and name the dataset.",
                    "Link to CC BY 4.0 and indicate modifications when sharing adapted data.",
                ],
            ),
            artifacts=[
                {
                    "path": "raw/mml/elevation-model-2m.asc.gz",
                    "sha256": _sha256(compressed),
                    "byte_size": len(compressed),
                    "media_type": "application/gzip",
                }
            ],
        )

    @staticmethod
    def _validate_manifest(
        manifest: Any,
        *,
        context: SourceAcquisitionContext,
        bbox: tuple[float, float, float, float],
        ncols: int,
        nrows: int,
        timeout_s: int,
        query_url: str,
    ) -> None:
        if not isinstance(manifest, dict):
            raise MmlArchiveError("MML archive pointer must be a JSON object")
        expected = {
            "schema_version": "1.0",
            "adapter_version": MML_ADAPTER_VERSION,
            "scenario_id": context.recipe.scenario_id,
            "recipe_sha256": context.recipe.sha256(),
            "endpoint": MML_WCS_ENDPOINT,
            "wcs_version": MML_WCS_VERSION,
            "coverage_id": MML_COVERAGE_ID,
            "output_format": MML_OUTPUT_FORMAT,
            "source_crs": MML_SOURCE_CRS,
            "vertical_crs": MML_VERTICAL_CRS,
            "subsetting_crs": MML_SOURCE_CRS,
            "network_context_buffer_m": context.recipe.network_context_buffer_m,
            "bbox": list(bbox),
            "native_resolution_m": NATIVE_RESOLUTION_M,
            "ncols": ncols,
            "nrows": nrows,
            "timeout_s": timeout_s,
            "query_url": query_url,
            "query_sha256": _sha256(query_url.encode("utf-8")),
            "credential_transport": "http_basic_username_password_empty",
            "credential_in_query_url": False,
        }
        differences = [
            key for key, expected_value in expected.items() if manifest.get(key) != expected_value
        ]
        if differences:
            raise MmlArchiveError(
                "offline MML archive does not match the current recipe/query ("
                + ", ".join(differences)
                + "); refresh explicitly"
            )
        allowed_keys = {
            *expected,
            "acquired_at",
            "archive_file",
            "archive_sha256",
            "raw_sha256",
            "byte_size",
            "valid_cell_count",
            "nodata_cell_count",
            "nodata_value",
            "minimum_elevation_m",
            "maximum_elevation_m",
        }
        unexpected = sorted(set(manifest) - allowed_keys)
        missing = sorted(allowed_keys - set(manifest))
        if unexpected or missing:
            raise MmlArchiveError("MML pointer has unexpected or missing fields")
        try:
            acquired_at = datetime.fromisoformat(manifest["acquired_at"])
        except (TypeError, ValueError) as error:
            raise MmlArchiveError("MML pointer has an invalid acquisition timestamp") from error
        if acquired_at.tzinfo is None:
            raise MmlArchiveError("MML pointer acquisition timestamp lacks a timezone")

        archive_path = _archive_path_is_safe(context.workspace, manifest["archive_file"])
        compressed = archive_path.read_bytes()
        digest = manifest.get("archive_sha256")
        raw_digest = manifest.get("raw_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise MmlArchiveError("MML pointer has an invalid archive checksum")
        if not isinstance(raw_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", raw_digest):
            raise MmlArchiveError("MML pointer has an invalid raw checksum")
        if _sha256(compressed) != digest:
            raise MmlArchiveError("MML archive checksum does not match its pointer")
        if len(compressed) != manifest.get("byte_size"):
            raise MmlArchiveError("MML archive size does not match its pointer")
        for key in ("valid_cell_count", "nodata_cell_count"):
            value = manifest.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise MmlArchiveError(f"MML pointer has an invalid {key}")
        if manifest["valid_cell_count"] + manifest["nodata_cell_count"] != ncols * nrows:
            raise MmlArchiveError("MML pointer cell counts do not match its grid dimensions")
        nodata_value = manifest.get("nodata_value")
        if nodata_value is not None and (
            isinstance(nodata_value, bool)
            or not isinstance(nodata_value, (int, float))
            or not math.isfinite(nodata_value)
        ):
            raise MmlArchiveError("MML pointer has an invalid nodata_value")
        for key in ("minimum_elevation_m", "maximum_elevation_m"):
            value = manifest.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(
                value
            ):
                raise MmlArchiveError(f"MML pointer has an invalid {key}")
        if manifest["minimum_elevation_m"] > manifest["maximum_elevation_m"]:
            raise MmlArchiveError("MML pointer elevation range is reversed")


__all__ = [
    "BBOX_DECIMALS",
    "DEFAULT_TIMEOUT_S",
    "MAX_GRID_DIMENSION",
    "MAX_QUERY_EXTENT_M",
    "MML_ADAPTER_ID",
    "MML_ADAPTER_VERSION",
    "MML_API_KEY_ENV",
    "MML_COVERAGE_ID",
    "MML_OUTPUT_FORMAT",
    "MML_SOURCE_CRS",
    "MML_VERTICAL_CRS",
    "MML_WCS_ENDPOINT",
    "MML_WCS_VERSION",
    "NATIVE_RESOLUTION_M",
    "MmlArchiveError",
    "MmlElevationAdapter",
    "derive_wcs_url",
]
