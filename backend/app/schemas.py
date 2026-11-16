from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str
    password: str


class RunCreateIn(BaseModel):
    rulebook_version_id: int
    model_id: int | None = None
    station_ids: list[int] | None = None
    label: str = Field(default="季节调查覆盖组装", max_length=128)


class RecordIngestIn(BaseModel):
    record_type: Literal[
        "camera_event",
        "patrol_track",
        "device_heartbeat",
        "downtime_log",
        "species_determination",
        "station_metadata",
        "time_calibration",
    ]
    external_id: str = Field(max_length=128)
    station_id: int
    event_time: str
    received_time: str
    source_device: str = Field(max_length=64)
    device_type: str = "camera"
    latitude: float | None = None
    longitude: float | None = None
    coord_precision_m: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class RecordReviseIn(BaseModel):
    payload: dict[str, Any]
    reason: str = Field(min_length=1, max_length=500)


class DeterminationIn(BaseModel):
    material_record_id: int
    source: str = Field(max_length=64)
    species_code: str = Field(max_length=64)
    verdict: Literal["present", "absent", "uncertain"]
    confidence: float = Field(ge=0.0, le=1.0)
    analyst: str = ""
    notes: str = ""


class DeterminationReviseIn(BaseModel):
    verdict: Literal["present", "absent", "uncertain"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=1000)


class TrendReferenceIn(BaseModel):
    purpose: Literal["absence", "trend"]
    note: str = ""


class RevokeIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class ConflictResolveIn(BaseModel):
    resolution: str = Field(min_length=1, max_length=1000)


# ----------------------------------------------------------------- re-identification
class FeatureVersionIn(BaseModel):
    code: str = Field(max_length=64)
    version: str = Field(max_length=32)
    feature_names: list[str] = Field(default_factory=list)
    notes: str = ""


class LocationVersionIn(BaseModel):
    code: str = Field(max_length=64)
    version: str = Field(max_length=32)
    change_reason: str = ""


class TimeCorrectionIn(BaseModel):
    code: str = Field(max_length=64)
    version: str = Field(max_length=32)
    target_device: str = Field(max_length=64)
    offset_seconds: float
    valid_from: str
    valid_to: str | None = None
    verified: bool = False
    basis: str = ""


class ObservationIn(BaseModel):
    species_code: str = Field(max_length=64)
    observation_kind: Literal["photo", "track", "manual"] = "photo"
    source_record_id: int | None = None
    external_ref: str = Field(default="", max_length=256)
    file_hash: str | None = Field(default=None, max_length=64)
    station_id: int
    observed_at: str
    received_time: str
    time_correction_id: int | None = None
    location_version_id: int | None = None
    feature_version_id: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    coord_precision_m: float | None = None
    posture_quality: Literal["good", "medium", "poor"] = "medium"
    posture_score: float = Field(default=0.5, ge=0.0, le=1.0)
    visible_features: dict[str, Any] = Field(default_factory=dict)
    device_clock: dict[str, Any] = Field(default_factory=dict)
    source_cluster_id: int | None = None
    derived_from_observation_id: int | None = None
    burst_group: str | None = Field(default=None, max_length=64)
    authorization: dict[str, Any] | None = None
    interpretability: Literal["interpretable", "unreadable"] = "interpretable"
    season_code: str = Field(max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)


class BatchIn(BaseModel):
    season_code: str = Field(max_length=32)
    species_code: str = Field(max_length=64)
    observation_ids: list[int] | None = None
    max_travel_speed_kmh: float = Field(default=3.0, gt=0.0)
    feature_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    pair_search_limit: int = Field(default=500, ge=1, le=10000)
    partition_limit: int = Field(default=6, ge=1, le=20)


class DecisionIn(BaseModel):
    verdict: Literal["confirm", "reject", "retain"]
    reason: str = Field(min_length=1, max_length=1000)
    expected_last_decision_id: int | None = None
    partition_id: int | None = None


class PartitionAdoptIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class SplitIn(BaseModel):
    groups: list[list[int]]
    reason: str = Field(min_length=1, max_length=1000)


class AdjudicationResolveIn(BaseModel):
    final_verdict: Literal["confirm", "reject"]
    reason: str = Field(min_length=1, max_length=1000)
    third_party_evidence: dict[str, Any] | None = None


class WithdrawIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class HashMismatchIn(BaseModel):
    expected_hash: str = Field(min_length=8, max_length=64)


class LocationRevisionIn(BaseModel):
    location_version_id: int
    latitude: float
    longitude: float


class ReviewResolveIn(BaseModel):
    outcome: Literal["keep", "revise", "revoke"]
    reason: str = Field(min_length=1, max_length=1000)
    groups: list[list[int]] | None = None


class ReportRunIn(BaseModel):
    season_code: str = Field(max_length=32)
    species_code: str = Field(max_length=64)


class CalibrationApplyIn(BaseModel):
    time_correction_id: int
