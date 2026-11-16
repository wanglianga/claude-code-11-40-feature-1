from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    display_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32), default="researcher")  # researcher | auditor | viewer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")

    stations: Mapped[list["Station"]] = relationship(back_populates="zone")


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    elevation_min_m: Mapped[float] = mapped_column(Float)
    elevation_max_m: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    zone: Mapped[Zone] = relationship(back_populates="stations")
    versions: Mapped[list["StationVersion"]] = relationship(
        back_populates="station", order_by="StationVersion.version_number"
    )


class StationVersion(Base):
    __tablename__ = "station_versions"
    __table_args__ = (UniqueConstraint("station_id", "version_number", name="uq_station_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    boundary: Mapped[dict[str, Any]] = mapped_column(JSONB)  # GeoJSON Polygon
    buffer_width_m: Mapped[float] = mapped_column(Float)
    centroid_lat: Mapped[float] = mapped_column(Float)
    centroid_lon: Mapped[float] = mapped_column(Float)
    elevation_min_m: Mapped[float] = mapped_column(Float)
    elevation_max_m: Mapped[float] = mapped_column(Float)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    change_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    station: Mapped[Station] = relationship(back_populates="versions")


class Rulebook(Base):
    __tablename__ = "rulebooks"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    versions: Mapped[list["RulebookVersion"]] = relationship(
        back_populates="rulebook", order_by="RulebookVersion.version_number"
    )


class RulebookVersion(Base):
    __tablename__ = "rulebook_versions"
    __table_args__ = (UniqueConstraint("rulebook_id", "version_number", name="uq_rulebook_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rulebook_id: Mapped[int] = mapped_column(ForeignKey("rulebooks.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(128))
    season_code: Mapped[str] = mapped_column(String(32))
    season_start: Mapped[date] = mapped_column(Date)
    season_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), default="active")  # draft | active | retired
    target_species: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    requirements: Mapped[dict[str, Any]] = mapped_column(JSONB)
    route_segments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    elevation_bands: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    rulebook: Mapped[Rulebook] = relationship(back_populates="versions")


class ArchiveRecord(Base):
    __tablename__ = "archive_records"
    __table_args__ = (
        Index("ix_archive_station_event", "station_id", "event_time"),
        Index("ix_archive_type_event", "record_type", "event_time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    record_type: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(128), index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"))
    station_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("station_versions.id"), nullable=True
    )
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_device: Mapped[str] = mapped_column(String(64))
    device_type: Mapped[str] = mapped_column(String(32), default="camera")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    coord_precision_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    record_status: Mapped[str] = mapped_column(String(32), default="active")
    superseded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("archive_records.id"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(64), default="ingest")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    revisions: Mapped[list["RecordRevision"]] = relationship(
        back_populates="record", order_by="RecordRevision.revision_number"
    )


class RecordRevision(Base):
    __tablename__ = "record_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("archive_records.id"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64))
    received_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    changed_by: Mapped[str] = mapped_column(String(64))
    change_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    record: Mapped[ArchiveRecord] = relationship(back_populates="revisions")


class Determination(Base):
    __tablename__ = "determinations"
    __table_args__ = (Index("ix_det_material_status", "material_record_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    material_record_id: Mapped[int] = mapped_column(ForeignKey("archive_records.id"))
    source_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("archive_records.id"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(64))  # analyst | model | partner
    species_code: Mapped[str] = mapped_column(String(64), index=True)
    verdict: Mapped[str] = mapped_column(String(32))  # present | absent | uncertain
    confidence: Mapped[float] = mapped_column(Float)
    analyst: Mapped[str] = mapped_column(String(64), default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="active")  # active | superseded
    superseded_by_id: Mapped[int | None] = mapped_column(ForeignKey("determinations.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SurveyRun(Base):
    __tablename__ = "survey_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_code: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(128))
    season_code: Mapped[str] = mapped_column(String(32))
    season_start: Mapped[date] = mapped_column(Date)
    season_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), default="active")  # active | superseded
    rulebook_version_id: Mapped[int] = mapped_column(ForeignKey("rulebook_versions.id"))
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("probability_models.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    units: Mapped[list["SurveyUnit"]] = relationship(back_populates="run")


class SurveyUnit(Base):
    __tablename__ = "survey_units"
    __table_args__ = (
        UniqueConstraint("run_id", "station_id", "zone_id", "unit_date", name="uq_survey_unit"),
        Index("ix_unit_station_date", "station_id", "unit_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("survey_runs.id"), index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"))
    unit_date: Mapped[date] = mapped_column(Date)
    station_version_id: Mapped[int] = mapped_column(ForeignKey("station_versions.id"))
    rulebook_version_id: Mapped[int] = mapped_column(ForeignKey("rulebook_versions.id"))
    model_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("probability_models.id"), nullable=True
    )
    assembled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    coverage_summary: Mapped[dict[str, Any]] = mapped_column(JSONB)
    feature_vector: Mapped[dict[str, Any]] = mapped_column(JSONB)
    gate_status: Mapped[dict[str, Any]] = mapped_column(JSONB)
    data_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    run: Mapped[SurveyRun] = relationship(back_populates="units")
    gates: Mapped[list["GateCheck"]] = relationship(back_populates="unit")
    certificate: Mapped["Certificate | None"] = relationship(back_populates="unit", uselist=False)


class GateCheck(Base):
    __tablename__ = "gate_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("survey_units.id"), index=True)
    gate: Mapped[str] = mapped_column(String(16))
    requirement_code: Mapped[str] = mapped_column(String(64))
    evaluation_round: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32))  # pass | restricted | fail | pending
    measured: Mapped[dict[str, Any]] = mapped_column(JSONB)
    threshold: Mapped[dict[str, Any]] = mapped_column(JSONB)
    explanation: Mapped[str] = mapped_column(Text)
    rule_ref: Mapped[str] = mapped_column(String(128))
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    unit: Mapped[SurveyUnit] = relationship(back_populates="gates")


class Certificate(Base):
    __tablename__ = "certificates"
    __table_args__ = (Index("ix_cert_unit_status", "unit_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("survey_units.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("survey_runs.id"), index=True)
    certificate_no: Mapped[str] = mapped_column(String(64), unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32))  # valid | restricted | invalid | pending
    absence_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    trend_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(32), default="normal")  # normal | under_review
    review_reason: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text)
    gate_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    conclusions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    superseded_by_id: Mapped[int | None] = mapped_column(ForeignKey("certificates.id"), nullable=True)

    unit: Mapped[SurveyUnit] = relationship(back_populates="certificate")


class ReadingConflict(Base):
    __tablename__ = "reading_conflicts"

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("survey_units.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("survey_runs.id"), index=True)
    material_record_id: Mapped[int] = mapped_column(ForeignKey("archive_records.id"))
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"))
    species_code: Mapped[str] = mapped_column(String(64))
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    detail: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open")  # open | resolved
    resolution: Mapped[str] = mapped_column(Text, default="")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProbabilityModel(Base):
    __tablename__ = "probability_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="active")  # active | under_review | retired
    threshold: Mapped[float] = mapped_column(Float)
    calibration_sets: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    threshold_review: Mapped[dict[str, Any]] = mapped_column(JSONB)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProbabilityEstimate(Base):
    __tablename__ = "probability_estimates"

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("survey_units.id"), index=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("probability_models.id"))
    probability: Mapped[float] = mapped_column(Float)
    interval_low: Mapped[float] = mapped_column(Float)
    interval_high: Mapped[float] = mapped_column(Float)
    threshold_pass: Mapped[bool] = mapped_column(Boolean)
    conclusion: Mapped[str] = mapped_column(String(32))  # supports_partial | below_threshold
    variants: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    assumptions: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TrendReference(Base):
    __tablename__ = "trend_references"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference_code: Mapped[str] = mapped_column(String(64), unique=True)
    purpose: Mapped[str] = mapped_column(String(32))  # absence | trend
    unit_id: Mapped[int] = mapped_column(ForeignKey("survey_units.id"))
    certificate_id: Mapped[int | None] = mapped_column(ForeignKey("certificates.id"), nullable=True)
    probability_estimate_id: Mapped[int | None] = mapped_column(
        ForeignKey("probability_estimates.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), default="active")  # active | suspended | revoked
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    suspended_reason: Mapped[str] = mapped_column(Text, default="")
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ============================================================
# 野生动物个体重识别（re-identification）证据链
# ============================================================
# 设计要点：
#   观察（observation）独立登记，外观相似只产生候选关系（candidate），
#   只有专家裁定（decision）才能形成确认个体版本（individual version）；
#   样线捕获账（capture entry）按确认个体版本计算，季报运行（report run）
#   冻结当时采用的版本，后续复审/拆分不改动旧季报。


class ReidFeatureExtractionVersion(Base):
    """特征提取版本：斑纹/伤痕特征抽取算法与口径的冻结版本。"""

    __tablename__ = "reid_feature_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="active")  # active | retired
    feature_names: Mapped[list[str]] = mapped_column(JSONB, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReidLocationVersion(Base):
    """位置版本：相机/样线坐标与归属口径的版本。"""

    __tablename__ = "reid_location_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="active")  # active | superseded
    change_reason: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReidTimeCorrectionVersion(Base):
    """时间校正版本：设备校时关系（偏移、有效期、依据）的冻结版本。"""

    __tablename__ = "reid_time_corrections"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    version: Mapped[str] = mapped_column(String(32))
    target_device: Mapped[str] = mapped_column(String(64), index=True)
    offset_seconds: Mapped[float] = mapped_column(Float)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    basis: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active")  # active | superseded
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReidSourceCluster(Base):
    """来源簇：同一连拍序列、同一原图裁剪或同哈希副本只能归入同一来源簇。"""

    __tablename__ = "reid_source_clusters"

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_code: Mapped[str] = mapped_column(String(64), unique=True)
    cluster_kind: Mapped[str] = mapped_column(String(32))  # burst | crop | duplicate_hash | manual
    rationale: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReidObservation(Base):
    """重识别观察：每张照片、足迹或人工观察先作为独立观察登记。"""

    __tablename__ = "reid_observations"
    __table_args__ = (
        Index("ix_reid_obs_station_time", "station_id", "observed_at"),
        Index("ix_reid_obs_species_season", "species_code", "season_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    observation_code: Mapped[str] = mapped_column(String(64), unique=True)
    species_code: Mapped[str] = mapped_column(String(64), index=True)
    observation_kind: Mapped[str] = mapped_column(String(16))  # photo | track | manual
    source_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("archive_records.id"), nullable=True
    )
    external_ref: Mapped[str] = mapped_column(String(256), default="")
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    coord_precision_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # 采集时间（原始）
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # 接收时间
    corrected_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    time_correction_id: Mapped[int | None] = mapped_column(
        ForeignKey("reid_time_corrections.id"), nullable=True
    )
    location_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("reid_location_versions.id"), nullable=True
    )
    feature_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("reid_feature_versions.id"), nullable=True
    )
    posture_quality: Mapped[str] = mapped_column(String(16), default="medium")  # good | medium | poor
    posture_score: Mapped[float] = mapped_column(Float, default=0.5)
    visible_features: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    device_clock: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    source_cluster_id: Mapped[int | None] = mapped_column(
        ForeignKey("reid_source_clusters.id"), nullable=True, index=True
    )
    authorization: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    authorization_status: Mapped[str] = mapped_column(
        String(32), default="authorized"
    )  # authorized | withdrawn
    interpretability: Mapped[str] = mapped_column(
        String(16), default="interpretable"
    )  # interpretable | unreadable
    season_code: Mapped[str] = mapped_column(String(32), index=True)
    survey_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    payload_hash: Mapped[str] = mapped_column(String(64))
    record_status: Mapped[str] = mapped_column(String(32), default="active")
    created_by: Mapped[str] = mapped_column(String(64), default="ingest")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    source_cluster: Mapped[ReidSourceCluster | None] = relationship()


class ReidBatch(Base):
    """联合候选批次：批次内联合搜索候选与一致划分，记录已查范围与未解决观察。"""

    __tablename__ = "reid_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_code: Mapped[str] = mapped_column(String(64), unique=True)
    season_code: Mapped[str] = mapped_column(String(32), index=True)
    species_code: Mapped[str] = mapped_column(String(64))
    scope_observation_ids: Mapped[list[int]] = mapped_column(JSONB, default=list)
    max_travel_speed_kmh: Mapped[float] = mapped_column(Float, default=3.0)
    feature_threshold: Mapped[float] = mapped_column(Float, default=0.35)
    pair_search_limit: Mapped[int] = mapped_column(Integer, default=500)
    partition_limit: Mapped[int] = mapped_column(Integer, default=6)
    status: Mapped[str] = mapped_column(
        String(32), default="searching"
    )  # searching | completed | truncated
    checked_pair_count: Mapped[int] = mapped_column(Integer, default=0)
    unresolved_observation_ids: Mapped[list[int]] = mapped_column(JSONB, default=list)
    truncation_note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReidCandidate(Base):
    """候选个体关系：不把外观相似直接写成同一动物，只登记候选与多维证据/反证。"""

    __tablename__ = "reid_candidates"
    __table_args__ = (
        UniqueConstraint("observation_a_id", "observation_b_id", name="uq_reid_candidate_pair"),
        Index("ix_reid_candidate_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("reid_batches.id"), nullable=True)
    observation_a_id: Mapped[int] = mapped_column(ForeignKey("reid_observations.id"))
    observation_b_id: Mapped[int] = mapped_column(ForeignKey("reid_observations.id"))
    feature_score: Mapped[float] = mapped_column(Float, default=0.0)
    spatial_reachable: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    counter_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    source_independent: Mapped[bool] = mapped_column(Boolean, default=True)
    # candidate 候选 | confirmed 确认 | rejected 否决 | retained 待补证
    # adjudicating_pending 同级相反裁定冻结 | blocked 被既有否决约束封锁
    status: Mapped[str] = mapped_column(String(32), default="candidate")
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReidDecision(Base):
    """专家决策：确认/否决/保留待补证，并冻结当时采用的各版本与证据快照。"""

    __tablename__ = "reid_decisions"
    __table_args__ = (Index("ix_reid_decision_candidate", "candidate_id", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("reid_candidates.id"))
    partition_id: Mapped[int | None] = mapped_column(
        ForeignKey("reid_partitions.id"), nullable=True
    )
    expert: Mapped[str] = mapped_column(String(64), index=True)
    expert_level: Mapped[str] = mapped_column(String(16), default="peer")  # peer | senior
    verdict: Mapped[str] = mapped_column(String(16))  # confirm | reject | retain
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    frozen_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # 乐观并发：后提交者基于的上一条决策 id；为空表示该候选首条决策
    expected_last_decision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReidPartition(Base):
    """联合划分方案：一批观察的若干一致个体划分，供专家裁定，不自动入选统计。"""

    __tablename__ = "reid_partitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("reid_batches.id"), index=True)
    partition_code: Mapped[str] = mapped_column(String(64), unique=True)
    rank: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    groups: Mapped[list[list[int]]] = mapped_column(JSONB)
    competing_memberships: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    constraint_violations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # proposed 候选方案 | adopted 已裁定采用 | discarded 放弃
    status: Mapped[str] = mapped_column(String(32), default="proposed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReidIndividual(Base):
    """确认个体（个体决策册抬头），其可变内容由一个个冻结版本承载。"""

    __tablename__ = "reid_individuals"

    id: Mapped[int] = mapped_column(primary_key=True)
    individual_code: Mapped[str] = mapped_column(String(64), unique=True)
    species_code: Mapped[str] = mapped_column(String(64), index=True)
    season_code: Mapped[str] = mapped_column(String(32), index=True)
    # active 正常 | under_review 复审中 | split 已拆分 | revoked 撤销统计资格
    status: Mapped[str] = mapped_column(String(32), default="active")
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReidIndividualVersion(Base):
    """确认个体版本：冻结观察归属、来源簇、采用版本与理由。"""

    __tablename__ = "reid_individual_versions"
    __table_args__ = (
        UniqueConstraint(
            "individual_id", "version_number", name="uq_reid_individual_version"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    individual_id: Mapped[int] = mapped_column(ForeignKey("reid_individuals.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    observation_ids: Mapped[list[int]] = mapped_column(JSONB, default=list)
    source_cluster_ids: Mapped[list[int]] = mapped_column(JSONB, default=list)
    candidate_ids: Mapped[list[int]] = mapped_column(JSONB, default=list)
    decision_ids: Mapped[list[int]] = mapped_column(JSONB, default=list)
    frozen_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    change_reason: Mapped[str] = mapped_column(Text, default="")
    # current 当前 | superseded 被替代 | under_review 复审中 | revoked 撤销
    status: Mapped[str] = mapped_column(String(32), default="current")
    superseded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("reid_individual_versions.id"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReidReportRun(Base):
    """样线统计账运行（季报口径）：冻结一次统计采用的个体版本与计数汇总。"""

    __tablename__ = "reid_report_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_code: Mapped[str] = mapped_column(String(64), unique=True)
    season_code: Mapped[str] = mapped_column(String(32), index=True)
    species_code: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="frozen")  # frozen | superseded
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    superseded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("reid_report_runs.id"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReidCaptureEntry(Base):
    """样线捕获账：确认个体在合规样线—日期组合中的首次/重复捕获与各类排除。"""

    __tablename__ = "reid_capture_entries"
    __table_args__ = (
        UniqueConstraint(
            "report_run_id", "individual_id", "observation_id", name="uq_reid_capture"
        ),
        Index("ix_reid_capture_station_date", "station_id", "survey_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    report_run_id: Mapped[int] = mapped_column(ForeignKey("reid_report_runs.id"), index=True)
    individual_id: Mapped[int | None] = mapped_column(
        ForeignKey("reid_individuals.id"), nullable=True
    )
    individual_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("reid_individual_versions.id"), nullable=True
    )
    observation_id: Mapped[int] = mapped_column(ForeignKey("reid_observations.id"))
    source_cluster_id: Mapped[int | None] = mapped_column(
        ForeignKey("reid_source_clusters.id"), nullable=True
    )
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    survey_date: Mapped[date] = mapped_column(Date)
    season_code: Mapped[str] = mapped_column(String(32))
    capture_kind: Mapped[str] = mapped_column(String(16))  # first | repeat | excluded
    sequence_no: Mapped[int] = mapped_column(Integer, default=0)
    # included 纳入 | excluded_pending 待核候选 | excluded_rejected 否决关系
    # excluded_unreadable 无法判读 | excluded_season 超出季节窗口
    # excluded_review 复审暂停 | frozen 重复归属冻结
    status: Mapped[str] = mapped_column(String(32), default="included")
    exclusion_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReidReviewEvent(Base):
    """复审历史：授权撤回、哈希不一致、位置版本修订等触发的个体版本复审记录。"""

    __tablename__ = "reid_review_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    individual_id: Mapped[int] = mapped_column(ForeignKey("reid_individuals.id"), index=True)
    individual_version_id: Mapped[int] = mapped_column(ForeignKey("reid_individual_versions.id"))
    trigger_type: Mapped[str] = mapped_column(String(32))
    trigger_detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # opened 已立案 | resolved_keep 沿用 | resolved_revise 修订关系 | resolved_revoke 撤销资格
    status: Mapped[str] = mapped_column(String(32), default="opened")
    resolution: Mapped[str] = mapped_column(Text, default="")
    opened_by: Mapped[str] = mapped_column(String(64), default="system")
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReidAdjudication(Base):
    """同级专家相反裁定的待裁定案：冻结统计资格，等待第三方证据或上级裁定。"""

    __tablename__ = "reid_adjudications"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("reid_candidates.id"), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    third_party_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # pending 待裁定 | resolved 已裁定
    status: Mapped[str] = mapped_column(String(32), default="pending")
    final_verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    opened_by: Mapped[str] = mapped_column(String(64))
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReidMembershipHold(Base):
    """归属冻结：同一观察被两个个体主张时，冻结双方重复捕获，禁止贡献两条轨迹。"""

    __tablename__ = "reid_membership_holds"

    id: Mapped[int] = mapped_column(primary_key=True)
    observation_id: Mapped[int] = mapped_column(ForeignKey("reid_observations.id"), index=True)
    individual_a_id: Mapped[int] = mapped_column(ForeignKey("reid_individuals.id"))
    individual_b_id: Mapped[int] = mapped_column(ForeignKey("reid_individuals.id"))
    candidate_id: Mapped[int] = mapped_column(ForeignKey("reid_candidates.id"))
    status: Mapped[str] = mapped_column(String(32), default="open")  # open | resolved
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
