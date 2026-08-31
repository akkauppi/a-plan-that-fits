from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pyproj import Transformer
from shapely.geometry import Point, shape

from .resilience import (
    AccessPoint,
    AssumptionRepairRequest,
    DecisionGroup,
    DisruptionAssumption,
    FrozenResilienceNetwork,
    NetworkEdge,
    SnappedAccessPoint,
    _AnalysisControl,
    _AnalysisInterrupted,
    analyze_disruption,
    solve_minimum_assumption_repair,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE_DIR = ROOT / "data/derived/espoo-otaniemi-coastal-base-v1-base-network"
DEFAULT_FLOOD_DIR = ROOT / "data/derived/espoo-otaniemi-coastal-v1-flood-exposure"
DEFAULT_ESPOO_DIR = (
    ROOT / "data/source/scenario-builder/espoo-otaniemi-coastal-v1/espoo_wfs"
)
DEFAULT_ESPOO_POINTER = (
    DEFAULT_ESPOO_DIR / "espoo-otaniemi-coastal-v1.espoo-wfs.archive.json"
)
SCENARIO_ID = "otaniemi-access-v1"
ADDRESS_GRID_M = 500
_GML = "http://www.opengis.net/gml"
_GIS = "http://www.tekla.com/schemas/GIS"
_NAMESPACES = {"gml": _GML, "GIS": _GIS}
_WAY_ID = re.compile(r"^osm-way-(\d+)-")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ESPOO_EVIDENCE_SCHEMA_VERSION = "1.0"
_GATEWAY_SPECS = (
    (
        "gateway-east-kuusisaarentie",
        "East · Kuusisaarentie",
        "east",
        "osm-boundary-7b941de776af6b9c",
    ),
    (
        "gateway-south-tapiolantie",
        "South · Tapiolantie",
        "south",
        "osm-boundary-c97c13269991761e",
    ),
    (
        "gateway-west-kalevalantie",
        "West · Kalevalantie",
        "west",
        "osm-boundary-3794e75dd2e13051",
    ),
    (
        "gateway-north-keha-i",
        "North · Kehä I",
        "north",
        "osm-boundary-bcf840a7014acbf0",
    ),
)


class ResilienceRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResilienceSolveRequest(ResilienceRequestModel):
    scenario_id: Literal["otaniemi-access-v1"] = SCENARIO_ID
    flood_return_period_years: Literal[100, 1000] = 1000
    treat_flood_exposure_as_unavailable: bool = True
    roadworks_segment_ids: list[str] = Field(default_factory=list, max_length=40)
    origin_ids: list[str] = Field(min_length=1, max_length=60)
    gateway_group_ids: list[str] = Field(min_length=1, max_length=4)
    analytical_repair_budget: int = Field(default=4, ge=0, le=16)
    timeout_seconds: float = Field(default=30, ge=1, le=120)

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> ResilienceSolveRequest:
        for field_name in (
            "roadworks_segment_ids",
            "origin_ids",
            "gateway_group_ids",
        ):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must not contain duplicates")
        return self


class ResilienceCancelRequest(ResilienceRequestModel):
    solve_id: str = Field(min_length=1, max_length=80)


@dataclass(frozen=True)
class OriginRecord:
    point: SnappedAccessPoint
    address_count: int
    street_names: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = self.point.as_dict()
        payload.update(
            {
                "address_count": self.address_count,
                "street_names": list(self.street_names),
                "source": "City of Espoo municipal address points",
                "aggregation": f"deterministic {ADDRESS_GRID_M} m EPSG:3067 cell",
            }
        )
        return payload


@dataclass(frozen=True)
class GatewayGroup:
    id: str
    label: str
    direction: str
    point: tuple[float, float]
    destinations: tuple[SnappedAccessPoint, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "direction": self.direction,
            "point": list(self.point),
            "destination_count": len(self.destinations),
            "destination_ids": [point.id for point in self.destinations],
            "definition": (
                "Reviewed outbound private-car graph endpoint at the frozen context edge; "
                "this is not a certified safe destination."
            ),
        }


@dataclass(frozen=True)
class CorridorGroup:
    decision: DecisionGroup
    label: str
    name: str | None
    highway: str | None
    length_m: float
    vertical_review: bool
    point: tuple[float, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.decision.id,
            "label": self.label,
            "segment_ids": list(self.decision.segment_ids),
            "segment_count": len(self.decision.segment_ids),
            "cost": self.decision.cost,
            "name": self.name,
            "highway": self.highway,
            "length_m": round(self.length_m, 1),
            "vertical_review": self.vertical_review,
            "point": list(self.point),
            "semantics": (
                "One Boolean continuity commitment spanning contiguous exposed OSM "
                "fragments. Selection is an analytical requirement, not proof of passability."
            ),
        }


class OtaniemiResilienceService:
    """Load the frozen Otaniemi evidence once and expose a reviewable access experiment."""

    def __init__(
        self,
        *,
        base_dir: Path = DEFAULT_BASE_DIR,
        flood_dir: Path = DEFAULT_FLOOD_DIR,
        espoo_dir: Path = DEFAULT_ESPOO_DIR,
        espoo_pointer: Path = DEFAULT_ESPOO_POINTER,
    ) -> None:
        self.base_dir = base_dir.resolve()
        self.flood_dir = flood_dir.resolve()
        self.espoo_dir = espoo_dir.resolve()
        self.espoo_pointer = espoo_pointer.resolve()
        self._lock = threading.RLock()
        self._loaded = False
        self.network: FrozenResilienceNetwork
        self.base_document: dict[str, Any]
        self.flood_document: dict[str, Any]
        self.flood_geojson: dict[str, Any]
        self.origins: tuple[OriginRecord, ...]
        self.gateway_groups: tuple[GatewayGroup, ...]
        self.browser_network: dict[str, Any]
        self.flood_features: dict[str, Any]
        self.buildings: dict[str, Any]
        self.corridor_groups: dict[int, tuple[CorridorGroup, ...]]
        self.base_metadata: dict[str, Any]
        self.flood_metadata: dict[str, Any]
        self.snapshot_components: dict[str, Any]
        self.snapshot_id: str
        self._default_disruption_analysis: dict[str, Any] | None = None
        self._default_disruption_key: tuple[Any, ...] | None = None
        self._scenario_payload: dict[str, Any] | None = None

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._loaded:
                return
            base_snapshot = _latest_snapshot(self.base_dir)
            flood_snapshot = _latest_snapshot(self.flood_dir)
            base_path = base_snapshot / "base-network.json"
            flood_path = flood_snapshot / "flood-exposure.json"
            base_metadata_path = base_snapshot / "metadata.json"
            flood_metadata_path = flood_snapshot / "metadata.json"
            flood_geojson_path = flood_snapshot / "flood-exposure.geojson"
            self.base_metadata = _read_object(base_metadata_path)
            self.flood_metadata = _read_object(flood_metadata_path)
            base_artifact = _validate_metadata_artifact(
                base_snapshot, self.base_metadata, "base-network.json"
            )
            flood_artifact = _validate_metadata_artifact(
                flood_snapshot, self.flood_metadata, "flood-exposure.json"
            )
            flood_geojson_artifact = _validate_metadata_artifact(
                flood_snapshot, self.flood_metadata, "flood-exposure.geojson"
            )
            self.base_document = _read_object(base_path)
            self.flood_document = _read_object(flood_path)
            self.flood_geojson = _read_object(flood_geojson_path)
            self.network = FrozenResilienceNetwork.from_artifacts(base_path, flood_path)
            if self.base_metadata.get("snapshot_id") != self.network.base_snapshot_id:
                raise ValueError("Base-network metadata snapshot ID does not match its artifact")
            if self.flood_metadata.get("snapshot_id") != self.network.flood_snapshot_id:
                raise ValueError("Flood metadata snapshot ID does not match its artifact")

            espoo_manifest = _read_object(self.espoo_pointer)
            manifest_sha256 = _file_sha256(self.espoo_pointer)
            address_path, address_layer = self._espoo_archive(
                espoo_manifest, "GIS:Osoitteet"
            )
            building_path, building_layer = self._espoo_archive(
                espoo_manifest, "GIS:Rakennukset"
            )
            municipal_evidence = _municipal_evidence_identity(
                pointer=self.espoo_pointer,
                manifest=espoo_manifest,
                manifest_sha256=manifest_sha256,
                address_layer=address_layer,
                building_layer=building_layer,
                base_snapshot_id=self.network.base_snapshot_id,
            )
            self.snapshot_components = {
                "base_network": {
                    "snapshot_id": self.network.base_snapshot_id,
                    "metadata_sha256": _file_sha256(base_metadata_path),
                    "artifact": base_artifact,
                },
                "flood_exposure": {
                    "snapshot_id": self.network.flood_snapshot_id,
                    "metadata_sha256": _file_sha256(flood_metadata_path),
                    "artifacts": [flood_artifact, flood_geojson_artifact],
                },
                "municipal_evidence": municipal_evidence,
            }
            self.snapshot_id = "+".join(
                (
                    self.network.base_snapshot_id,
                    self.network.flood_snapshot_id,
                    municipal_evidence["snapshot_id"],
                )
            )
            self.origins = self._load_origins(address_path)
            self.gateway_groups = self._build_gateways()
            self.browser_network = self._build_browser_network()
            self.flood_features = self._build_flood_features()
            self.buildings = self._load_buildings(building_path)
            self.corridor_groups = {
                period: self._build_corridor_groups(period, frozenset())
                for period in (100, 1000)
            }
            self._loaded = True

    def _espoo_archive(
        self, manifest: dict[str, Any], layer_name: str
    ) -> tuple[Path, dict[str, Any]]:
        layers = manifest.get("layers")
        if not isinstance(layers, list):
            raise ValueError("Frozen Espoo manifest has no valid layer declarations")
        layer = next(
            (
                item
                for item in layers
                if isinstance(item, dict) and item.get("layer") == layer_name
            ),
            None,
        )
        if not isinstance(layer, dict) or not isinstance(layer.get("archive_file"), str):
            raise ValueError(f"Frozen Espoo layer {layer_name} is not declared")
        path = (self.espoo_dir / layer["archive_file"]).resolve()
        if path.parent != self.espoo_dir or not path.is_file():
            raise ValueError(f"Frozen Espoo layer {layer_name} archive is unavailable")
        _validate_declared_file(path, layer, label=f"Espoo layer {layer_name}")
        _validate_declared_gzip_content(
            path, layer, label=f"Espoo layer {layer_name} raw content"
        )
        return path, layer

    def _load_origins(self, path: Path) -> tuple[OriginRecord, ...]:
        core = shape(self.base_document["core_boundary"])
        to_wgs84 = Transformer.from_crs(3879, 4326, always_xy=True)
        to_metric = Transformer.from_crs(4326, 3067, always_xy=True)
        cells: dict[tuple[int, int], list[tuple[str, float, float, float, float]]] = (
            defaultdict(list)
        )
        root = _read_gml(path)
        for member in root.findall(".//gml:featureMember", _NAMESPACES):
            street = member.findtext(".//GIS:Osoite_suomeksi", namespaces=_NAMESPACES)
            coordinates = member.findtext(".//gml:coordinates", namespaces=_NAMESPACES)
            if not street or not coordinates:
                continue
            source = coordinates.split()[0].split(",")
            if len(source) < 2:
                continue
            longitude, latitude = to_wgs84.transform(float(source[0]), float(source[1]))
            if not core.covers(Point(longitude, latitude)):
                continue
            x, y = to_metric.transform(longitude, latitude)
            cells[(math.floor(x / ADDRESS_GRID_M), math.floor(y / ADDRESS_GRID_M))].append(
                (street.strip(), longitude, latitude, x, y)
            )

        access_points: list[AccessPoint] = []
        metadata: dict[str, tuple[int, tuple[str, ...]]] = {}
        for _cell, records in sorted(
            cells.items(), key=lambda item: (-item[0][1], item[0][0])
        ):
            streets = tuple(
                name for name, _ in Counter(record[0] for record in records).most_common()
            )
            label = streets[0] if len(streets) == 1 else f"{streets[0]} + nearby streets"
            digest_input = "|".join(
                sorted(f"{record[0]}:{record[1]:.7f}:{record[2]:.7f}" for record in records)
            )
            origin_id = f"origin-{hashlib.sha256(digest_input.encode()).hexdigest()[:10]}"
            longitude = sum(record[1] for record in records) / len(records)
            latitude = sum(record[2] for record in records) / len(records)
            access_points.append(AccessPoint(origin_id, label, longitude, latitude))
            metadata[origin_id] = (len(records), streets)

        snapped = self.network.snap_points(access_points)
        return tuple(
            OriginRecord(point, metadata[point.id][0], metadata[point.id][1])
            for point in snapped
        )

    def _build_gateways(self) -> tuple[GatewayGroup, ...]:
        nodes = {str(node["id"]): node for node in self.base_document["nodes"]}
        car_edges = [edge for edge in self.network.edges if edge.private_car]
        groups: list[GatewayGroup] = []
        for group_id, label, direction, node_id in _GATEWAY_SPECS:
            node = nodes.get(node_id)
            if node is None or not any(edge.target == node_id for edge in car_edges):
                raise ValueError(f"Reviewed outbound gateway is missing: {label}")
            destination = SnappedAccessPoint(
                id=f"destination-{group_id.removeprefix('gateway-')}",
                label=label,
                node_id=node_id,
                longitude=float(node["longitude"]),
                latitude=float(node["latitude"]),
                requested_longitude=float(node["longitude"]),
                requested_latitude=float(node["latitude"]),
                snap_distance_m=0,
            )
            groups.append(
                GatewayGroup(
                    id=group_id,
                    label=label,
                    direction=direction,
                    point=(destination.longitude, destination.latitude),
                    destinations=(destination,),
                )
            )
        return tuple(groups)

    def _physical_edges(self) -> dict[str, tuple[NetworkEdge, ...]]:
        grouped: dict[str, list[NetworkEdge]] = defaultdict(list)
        for edge in self.network.edges:
            if edge.private_car:
                grouped[edge.physical_id].append(edge)
        return {
            physical_id: tuple(sorted(edges, key=lambda edge: edge.id))
            for physical_id, edges in sorted(grouped.items())
        }

    def _build_browser_network(self) -> dict[str, Any]:
        features: list[dict[str, Any]] = [
            {
                "type": "Feature",
                "id": "network-context",
                "properties": {"layer": "network_context"},
                "geometry": self.base_document["network_context_boundary"],
            },
            {
                "type": "Feature",
                "id": "study-core",
                "properties": {"layer": "study_core"},
                "geometry": self.base_document["core_boundary"],
            },
        ]
        for physical_id, edges in self._physical_edges().items():
            edge = edges[0]
            geometry = list(edge.geometry)
            if len(geometry) < 2:
                continue
            features.append(
                {
                    "type": "Feature",
                    "id": physical_id,
                    "properties": {
                        "layer": "base_network",
                        "physical_segment_id": physical_id,
                        "name": edge.name,
                        "highway": edge.highway,
                        "length_m": round(max(item.length_m for item in edges), 2),
                        "private_car_forward": any(item.id.endswith("-f") for item in edges),
                        "private_car_reverse": any(item.id.endswith("-r") for item in edges),
                        "exposed_100": physical_id
                        in self.network.exposed_segment_ids.get(100, frozenset()),
                        "exposed_1000": physical_id
                        in self.network.exposed_segment_ids.get(1000, frozenset()),
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [list(coordinate) for coordinate in geometry],
                    },
                }
            )
        return {"type": "FeatureCollection", "features": features}

    def _build_flood_features(self) -> dict[str, Any]:
        physical_edges = self._physical_edges()
        features: list[dict[str, Any]] = []
        for source_feature in self.flood_geojson.get("features", []):
            if not isinstance(source_feature, dict):
                continue
            properties = source_feature.get("properties", {})
            if not isinstance(properties, dict):
                continue
            physical_id = str(properties.get("physical_segment_id", ""))
            edges = physical_edges.get(physical_id)
            geometry = source_feature.get("geometry")
            if not edges or not isinstance(geometry, dict):
                continue
            features.append(
                {
                    "type": "Feature",
                    "id": source_feature.get("id"),
                    "properties": {
                        **properties,
                        "name": edges[0].name,
                        "highway": edges[0].highway,
                        "passability_not_inferred": True,
                        "geometry_semantics": "clipped horizontal intersection only",
                    },
                    "geometry": geometry,
                }
            )
        return {"type": "FeatureCollection", "features": features}

    def _load_buildings(self, path: Path) -> dict[str, Any]:
        to_wgs84 = Transformer.from_crs(3879, 4326, always_xy=True)
        root = _read_gml(path)
        features: list[dict[str, Any]] = []
        for index, member in enumerate(root.findall(".//gml:featureMember", _NAMESPACES)):
            rings: list[list[list[float]]] = []
            for value in member.findall(
                ".//gml:Polygon/gml:outerBoundaryIs/gml:LinearRing/gml:coordinates",
                _NAMESPACES,
            ):
                if not value.text:
                    continue
                ring: list[list[float]] = []
                for pair in value.text.split():
                    coordinates = pair.split(",")
                    if len(coordinates) < 2:
                        continue
                    longitude, latitude = to_wgs84.transform(
                        float(coordinates[0]), float(coordinates[1])
                    )
                    ring.append([longitude, latitude])
                if len(ring) >= 4:
                    rings.append(ring)
            if not rings:
                continue
            stable_id = member.findtext(
                ".//GIS:PYSYVARAKENNUSTUNNUS", namespaces=_NAMESPACES
            ) or f"building-{index + 1:04d}"
            usage = member.findtext(".//GIS:KAYTTOTARKOITUS", namespaces=_NAMESPACES)
            features.append(
                {
                    "type": "Feature",
                    "id": stable_id,
                    "properties": {"id": stable_id, "usage": usage},
                    "geometry": (
                        {"type": "Polygon", "coordinates": [rings[0]]}
                        if len(rings) == 1
                        else {"type": "MultiPolygon", "coordinates": [[ring] for ring in rings]}
                    ),
                }
            )
        return {"type": "FeatureCollection", "features": features}

    def _build_corridor_groups(
        self,
        period: int,
        fixed_roadworks: frozenset[str],
    ) -> tuple[CorridorGroup, ...]:
        physical_edges = self._physical_edges()
        exposed = (
            self.network.exposed_segment_ids.get(period, frozenset())
            & physical_edges.keys()
        ) - fixed_roadworks
        by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
        for physical_id in sorted(exposed):
            edge = physical_edges[physical_id][0]
            if edge.name and edge.name.strip():
                key = ("name", " ".join(edge.name.casefold().split()))
            else:
                way_match = _WAY_ID.match(physical_id)
                key = ("way", f"{way_match.group(1) if way_match else physical_id}:{edge.highway}")
            by_key[key].append(physical_id)

        groups: list[CorridorGroup] = []
        for _, segment_ids in sorted(by_key.items()):
            segment_graph = nx.Graph()
            node_to_segments: dict[str, list[str]] = defaultdict(list)
            for physical_id in segment_ids:
                segment_graph.add_node(physical_id)
                endpoints = {
                    endpoint
                    for edge in physical_edges[physical_id]
                    for endpoint in (edge.source, edge.target)
                }
                for endpoint in endpoints:
                    node_to_segments[endpoint].append(physical_id)
            for touching in node_to_segments.values():
                for left in touching:
                    segment_graph.add_edges_from(
                        (left, right) for right in touching if left != right
                    )
            for component in sorted(
                nx.connected_components(segment_graph), key=lambda values: min(values)
            ):
                members = tuple(sorted(component))
                digest = hashlib.sha256("|".join(members).encode()).hexdigest()[:12]
                first = physical_edges[members[0]][0]
                name = first.name.strip() if first.name and first.name.strip() else None
                label = name or f"Unnamed {first.highway or 'road'} exposure zone"
                length_m = sum(
                    max(edge.length_m for edge in physical_edges[member])
                    for member in members
                )
                points = [
                    coordinate
                    for member in members
                    for coordinate in physical_edges[member][0].geometry
                ]
                groups.append(
                    CorridorGroup(
                        decision=DecisionGroup(
                            id=f"zone-{period}-{digest}",
                            label=label,
                            segment_ids=members,
                            cost=max(1, round(length_m)),
                        ),
                        label=label,
                        name=name,
                        highway=first.highway,
                        length_m=length_m,
                        vertical_review=bool(
                            set(members)
                            & self.network.vertical_review_segment_ids.get(
                                period, frozenset()
                            )
                        ),
                        point=(
                            sum(point[0] for point in points) / len(points),
                            sum(point[1] for point in points) / len(points),
                        ),
                    )
                )
        return tuple(sorted(groups, key=lambda group: group.decision.id))

    def scenario_payload(self) -> dict[str, Any]:
        self._ensure_loaded()
        if self._scenario_payload is not None:
            return self._scenario_payload
        base_counts = self.base_document["counts"]
        context_bounds = shape(self.base_document["network_context_boundary"]).bounds
        core = shape(self.base_document["core_boundary"])
        teaching_origin = next(
            (
                record.point.id
                for record in self.origins
                if record.point.label.startswith("Otaranta")
            ),
            self.origins[0].point.id,
        )
        default_gateway_ids = ["gateway-east-kuusisaarentie"]
        default_origin_ids = [teaching_origin]
        default_origins, default_destinations, _groups = self.resolve_study(
            origin_ids=default_origin_ids,
            gateway_group_ids=default_gateway_ids,
            period=1000,
            roadworks_segment_ids=[],
        )
        default_disruption = analyze_disruption(
            self.network,
            DisruptionAssumption(
                flood_return_period_years=1000,
                treat_flood_exposure_as_unavailable=True,
            ),
            default_origins,
            default_destinations,
        )
        self._default_disruption_analysis = default_disruption
        self._default_disruption_key = (
            1000,
            True,
            (),
            tuple(default_origin_ids),
            tuple(default_gateway_ids),
        )
        payload = {
            "schema_version": "1.0",
            "id": SCENARIO_ID,
            "name": "Otaniemi coastal access",
            "description": (
                "A frozen private-car reachability stress test using explicit coastal-flood "
                "and user-declared roadworks unavailability assumptions."
            ),
            "snapshot_id": self.snapshot_id,
            "snapshot_components": self.snapshot_components,
            "source_timestamp": self.base_metadata.get("sources", [{}])[0].get(
                "source_timestamp"
            ),
            "center": [core.centroid.x, core.centroid.y],
            "bbox": list(context_bounds),
            "core_boundary": self.base_document["core_boundary"],
            "network_context_boundary": self.base_document["network_context_boundary"],
            "base_network": self.browser_network,
            "buildings": self.buildings,
            "flood_exposure": self.flood_features,
            "origins": [record.as_dict() for record in self.origins],
            "gateway_groups": [group.as_dict() for group in self.gateway_groups],
            "decision_groups_by_return_period": {
                str(period): [group.as_dict() for group in groups]
                for period, groups in self.corridor_groups.items()
            },
            "default_disruption_analysis": default_disruption,
            "analysis_presets": {
                "teaching_focus": {
                    "label": "Otaranta → Kuusisaarentie",
                    "origin_ids": default_origin_ids,
                    "gateway_group_ids": default_gateway_ids,
                    "purpose": "Fast, visual counterexample-guided solver walkthrough.",
                },
                "all_origins_sensitivity": {
                    "label": "All representative origin cells",
                    "origin_ids": [record.point.id for record in self.origins],
                    "gateway_group_ids": default_gateway_ids,
                    "purpose": (
                        "A stricter and slower boundary/origin sensitivity test; budget four "
                        "is expected to be insufficient in the frozen 1/1000 scenario."
                    ),
                },
            },
            "defaults": {
                "flood_return_period_years": 1000,
                "treat_flood_exposure_as_unavailable": True,
                "origin_ids": default_origin_ids,
                "gateway_group_ids": default_gateway_ids,
                "analytical_repair_budget": 4,
                "timeout_seconds": 30,
            },
            "counts": {
                **base_counts,
                "private_car_physical_segments": len(self._physical_edges()),
                "municipal_address_points_in_core": sum(
                    record.address_count for record in self.origins
                ),
                "origin_clusters": len(self.origins),
                "gateway_groups": len(self.gateway_groups),
                "municipal_buildings": len(self.buildings["features"]),
                "private_car_exposed_segments": {
                    str(period): len(
                        self.network.exposed_segment_ids.get(period, frozenset())
                        & self._physical_edges().keys()
                    )
                    for period in (100, 1000)
                },
                "source_exposed_segments": {
                    str(period): len(
                        self.network.exposed_segment_ids.get(period, frozenset())
                    )
                    for period in (100, 1000)
                },
            },
            "semantics": {
                "mode": "private_car",
                "exposure_is_closure": False,
                "closure_requires_explicit_user_assumption": True,
                "gateway_is_certified_safe_destination": False,
                "decision_unit": "contiguous named exposure zone",
                "selected_decision_is_passability_finding": False,
                "claim": (
                    "Under the frozen directed private-car graph, selected gateways, origins, "
                    "and explicit unavailable-link assumptions, the reported access relations "
                    "were recomputed on a fresh directed graph."
                ),
            },
            "attribution": (
                "Street graph © OpenStreetMap contributors (ODbL); flood evidence Syke; "
                "addresses and buildings City of Espoo (CC BY 4.0). MML terrain is retained "
                "as separate review evidence and is not used to close a road."
            ),
        }
        self._scenario_payload = payload
        return payload

    def resolve_study(
        self,
        *,
        origin_ids: list[str],
        gateway_group_ids: list[str],
        period: int,
        roadworks_segment_ids: list[str],
    ) -> tuple[
        tuple[SnappedAccessPoint, ...],
        tuple[SnappedAccessPoint, ...],
        tuple[CorridorGroup, ...],
    ]:
        self._ensure_loaded()
        origins_by_id = {record.point.id: record.point for record in self.origins}
        gateways_by_id = {group.id: group for group in self.gateway_groups}
        unknown_origins = set(origin_ids) - origins_by_id.keys()
        unknown_gateways = set(gateway_group_ids) - gateways_by_id.keys()
        if unknown_origins:
            raise ValueError(f"Unknown origin IDs: {sorted(unknown_origins)[:3]}")
        if unknown_gateways:
            raise ValueError(f"Unknown gateway group IDs: {sorted(unknown_gateways)[:3]}")
        destinations = tuple(
            destination
            for group_id in gateway_group_ids
            for destination in gateways_by_id[group_id].destinations
        )
        if not destinations:
            raise ValueError("At least one gateway group is required")
        destination_ids = tuple(destination.id for destination in destinations)
        origins = tuple(
            replace(origins_by_id[origin_id], allowed_destination_ids=destination_ids)
            for origin_id in origin_ids
        )
        if not origins:
            raise ValueError("At least one origin is required")
        groups = self._build_corridor_groups(period, frozenset(roadworks_segment_ids))
        return origins, destinations, groups

    def solve(
        self,
        *,
        origin_ids: list[str],
        gateway_group_ids: list[str],
        flood_return_period_years: int,
        treat_flood_exposure_as_unavailable: bool,
        roadworks_segment_ids: list[str],
        analytical_repair_budget: int,
        timeout_seconds: float,
        cancel_event: threading.Event,
        on_event: Any = None,
    ) -> dict[str, Any]:
        self._ensure_loaded()
        request_started = time.monotonic()
        request_deadline = request_started + max(0.0, timeout_seconds)
        control = _AnalysisControl(
            deadline=request_deadline,
            cancel_event=cancel_event,
        )
        disruption: dict[str, Any] | None = None
        origins, destinations, groups = self.resolve_study(
            origin_ids=origin_ids,
            gateway_group_ids=gateway_group_ids,
            period=flood_return_period_years,
            roadworks_segment_ids=roadworks_segment_ids,
        )
        if not treat_flood_exposure_as_unavailable:
            groups = ()
        assumption = DisruptionAssumption(
            flood_return_period_years=flood_return_period_years,
            treat_flood_exposure_as_unavailable=treat_flood_exposure_as_unavailable,
            roadworks_segment_ids=tuple(sorted(set(roadworks_segment_ids))),
        )
        try:
            control.checkpoint("otaniemi_request_setup")
            disruption_key = (
                flood_return_period_years,
                treat_flood_exposure_as_unavailable,
                tuple(roadworks_segment_ids),
                tuple(origin_ids),
                tuple(gateway_group_ids),
            )
            disruption = (
                self._default_disruption_analysis
                if disruption_key == self._default_disruption_key
                and self._default_disruption_analysis is not None
                else analyze_disruption(
                    self.network,
                    assumption,
                    origins,
                    destinations,
                    _control=control,
                )
            )
            control.checkpoint("otaniemi_initial_disruption_analysis")
            result = solve_minimum_assumption_repair(
                self.network,
                assumption,
                origins,
                destinations,
                AssumptionRepairRequest(
                    budget=analytical_repair_budget,
                    timeout_seconds=max(0.0, request_deadline - time.monotonic()),
                    decision_groups=tuple(group.decision for group in groups),
                ),
                cancel_event=cancel_event,
                on_event=on_event,
            )
        except _AnalysisInterrupted as interruption:
            result = {
                "status": interruption.status,
                "verified": False,
                "message": (
                    "The analysis was cancelled; no feasibility claim has been made."
                    if interruption.status == "cancelled"
                    else "The analysis reached its time limit. This is not an UNSAT result."
                ),
                "selected_decision_ids": [],
                "selected_segment_ids": [],
                "elapsed_ms": round((time.monotonic() - request_started) * 1000, 2),
                "iteration_count": 0,
                "iterations": [],
                "diagnostics": {"interrupted_phase": interruption.phase},
                "methodology_notice": (
                    "This is an explicit graph-assumption experiment. It does not infer "
                    "road closure from flood exposure, certify a route as safe, or predict "
                    "disruption impacts."
                ),
            }
        groups_by_id = {group.decision.id: group for group in groups}
        result["elapsed_ms"] = round((time.monotonic() - request_started) * 1000, 2)
        if disruption is not None:
            result["baseline_disruption_analysis"] = disruption
        result["origin_ids"] = list(origin_ids)
        result["gateway_group_ids"] = list(gateway_group_ids)
        result["decision_groups"] = [group.as_dict() for group in groups]
        result["selected_decisions"] = [
            groups_by_id[decision_id].as_dict()
            for decision_id in result.get("selected_decision_ids", [])
            if decision_id in groups_by_id
        ]
        result["scenario_id"] = SCENARIO_ID
        result["snapshot_id"] = self.snapshot_id
        result["snapshot_components"] = self.snapshot_components
        return result


def _latest_snapshot(root: Path) -> Path:
    root = root.resolve()
    pointer = _read_object(root / "latest.json")
    relative = pointer.get("snapshot_path")
    if not isinstance(relative, str):
        raise ValueError(f"Invalid latest snapshot pointer in {root.name}")
    snapshot = (root / relative).resolve()
    if root not in snapshot.parents or not snapshot.is_dir():
        raise ValueError(f"Latest snapshot escapes or is missing in {root.name}")
    return snapshot


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Frozen JSON is unavailable or invalid: {path.name}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Frozen JSON must contain an object: {path.name}")
    return value


def _read_gml(path: Path) -> ET.Element:
    try:
        with gzip.open(path, "rb") as handle:
            return ET.fromstring(handle.read())
    except (OSError, ET.ParseError) as error:
        raise ValueError(f"Frozen GML is unavailable or invalid: {path.name}") from error


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ValueError(f"Frozen artifact is unavailable: {path.name}") from error
    return digest.hexdigest()


def _validate_declared_file(
    path: Path, declaration: dict[str, Any], *, label: str
) -> dict[str, Any]:
    declared_sha256 = declaration.get("archive_sha256", declaration.get("sha256"))
    if not isinstance(declared_sha256, str) or not _SHA256.fullmatch(declared_sha256):
        raise ValueError(f"{label} has no valid declared SHA-256")
    actual_sha256 = _file_sha256(path)
    if actual_sha256 != declared_sha256:
        raise ValueError(f"{label} SHA-256 does not match its declaration")
    declared_size = declaration.get("byte_size")
    if isinstance(declared_size, bool) or not isinstance(declared_size, int):
        raise ValueError(f"{label} has no valid declared byte size")
    try:
        actual_size = path.stat().st_size
    except OSError as error:
        raise ValueError(f"Frozen artifact is unavailable: {path.name}") from error
    if actual_size != declared_size:
        raise ValueError(f"{label} byte size does not match its declaration")
    return {
        "file": path.name,
        "sha256": actual_sha256,
        "byte_size": actual_size,
    }


def _validate_declared_gzip_content(
    path: Path, declaration: dict[str, Any], *, label: str
) -> None:
    declared_sha256 = declaration.get("raw_sha256")
    if not isinstance(declared_sha256, str) or not _SHA256.fullmatch(declared_sha256):
        raise ValueError(f"{label} has no valid declared SHA-256")
    digest = hashlib.sha256()
    try:
        with gzip.open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ValueError(f"Frozen GML is unavailable or invalid: {path.name}") from error
    if digest.hexdigest() != declared_sha256:
        raise ValueError(f"{label} SHA-256 does not match its declaration")


def _validate_metadata_artifact(
    snapshot: Path, metadata: dict[str, Any], artifact_name: str
) -> dict[str, Any]:
    declaration = next(
        (
            item
            for item in metadata.get("derived_artifacts", [])
            if isinstance(item, dict) and item.get("path") == artifact_name
        ),
        None,
    )
    if not isinstance(declaration, dict):
        raise ValueError(f"Frozen metadata does not declare {artifact_name}")
    path = (snapshot / artifact_name).resolve()
    if snapshot not in path.parents or not path.is_file():
        raise ValueError(f"Frozen artifact is unavailable: {artifact_name}")
    return _validate_declared_file(
        path, declaration, label=f"Derived artifact {artifact_name}"
    )


def _municipal_evidence_identity(
    *,
    pointer: Path,
    manifest: dict[str, Any],
    manifest_sha256: str,
    address_layer: dict[str, Any],
    building_layer: dict[str, Any],
    base_snapshot_id: str,
) -> dict[str, Any]:
    def layer_identity(
        declaration: dict[str, Any], *, role: str
    ) -> dict[str, Any]:
        return {
            "role": role,
            "layer": declaration.get("layer"),
            "archive_file": declaration.get("archive_file"),
            "archive_sha256": declaration.get("archive_sha256"),
            "raw_sha256": declaration.get("raw_sha256"),
            "query_sha256": declaration.get("query_sha256"),
            "byte_size": declaration.get("byte_size"),
            "feature_count": declaration.get("feature_count"),
            "response_timestamp": declaration.get("response_timestamp"),
        }

    layers = {
        "addresses": layer_identity(address_layer, role="origin_evidence"),
        "buildings": layer_identity(building_layer, role="display_evidence"),
    }
    origin_derivation = {
        "aggregation": f"deterministic {ADDRESS_GRID_M} m EPSG:3067 cell",
        "core_boundary_snapshot_id": base_snapshot_id,
        "snapped_to_snapshot_id": base_snapshot_id,
        "snapping_graph": "directed private-car nodes",
    }
    identity_input = {
        "schema_version": _ESPOO_EVIDENCE_SCHEMA_VERSION,
        "manifest_sha256": manifest_sha256,
        "origin_derivation": origin_derivation,
        "layers": layers,
    }
    canonical = json.dumps(
        identity_input, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    snapshot_id = f"espoo-{hashlib.sha256(canonical.encode()).hexdigest()[:20]}"
    return {
        "snapshot_id": snapshot_id,
        "schema_version": _ESPOO_EVIDENCE_SCHEMA_VERSION,
        "scenario_id": manifest.get("scenario_id"),
        "manifest_file": pointer.name,
        "manifest_sha256": manifest_sha256,
        "adapter_version": manifest.get("adapter_version"),
        "endpoint": manifest.get("endpoint"),
        "recipe_sha256": manifest.get("recipe_sha256"),
        "acquired_at": manifest.get("acquired_at"),
        "source_crs": manifest.get("source_crs"),
        "normalized_crs": manifest.get("normalized_crs"),
        "origin_derivation": origin_derivation,
        "layers": layers,
    }


__all__ = [
    "OtaniemiResilienceService",
    "ResilienceCancelRequest",
    "ResilienceSolveRequest",
    "SCENARIO_ID",
]
