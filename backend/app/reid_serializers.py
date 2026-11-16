"""重识别领域响应序列化器：显式、稳定的字典契约。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    ReidAdjudication,
    ReidBatch,
    ReidCandidate,
    ReidCaptureEntry,
    ReidDecision,
    ReidFeatureExtractionVersion,
    ReidIndividual,
    ReidIndividualVersion,
    ReidLocationVersion,
    ReidMembershipHold,
    ReidObservation,
    ReidPartition,
    ReidReportRun,
    ReidReviewEvent,
    ReidSourceCluster,
    ReidTimeCorrectionVersion,
    Station,
)
from .reid import effective_time

CANDIDATE_STATUS_LABELS = {
    "candidate": "候选",
    "confirmed": "专家确认",
    "rejected": "已否决",
    "retained": "保留待补证",
    "adjudicating_pending": "同级相反裁定·待定",
    "blocked": "受否决约束封锁",
}
INDIVIDUAL_STATUS_LABELS = {
    "active": "正常",
    "under_review": "复审中",
    "split": "已拆分",
    "merged": "已并入他体",
    "revoked": "撤销统计资格",
}
VERSION_STATUS_LABELS = {
    "current": "当前版本",
    "superseded": "已替代",
    "under_review": "复审中",
    "revoked": "已撤销",
}
CAPTURE_STATUS_LABELS = {
    "included": "纳入统计",
    "excluded_pending": "待核候选排除",
    "excluded_rejected": "否决关系排除",
    "excluded_unreadable": "无法判读排除",
    "excluded_season": "超出季节窗口排除",
    "excluded_review": "复审暂停排除",
    "excluded_duplicate_cluster": "同来源簇重复排除",
    "frozen": "竞争归属冻结",
}


def iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def feature_version_out(v: ReidFeatureExtractionVersion) -> dict[str, Any]:
    return {
        "id": v.id, "code": v.code, "version": v.version, "status": v.status,
        "feature_names": v.feature_names, "notes": v.notes, "created_at": iso(v.created_at),
    }


def location_version_out(v: ReidLocationVersion) -> dict[str, Any]:
    return {
        "id": v.id, "code": v.code, "version": v.version, "status": v.status,
        "change_reason": v.change_reason, "notes": v.notes, "created_at": iso(v.created_at),
    }


def time_correction_out(v: ReidTimeCorrectionVersion) -> dict[str, Any]:
    return {
        "id": v.id, "code": v.code, "version": v.version, "target_device": v.target_device,
        "offset_seconds": v.offset_seconds, "valid_from": iso(v.valid_from),
        "valid_to": iso(v.valid_to), "verified": v.verified, "basis": v.basis,
        "status": v.status, "created_at": iso(v.created_at),
    }


def source_cluster_out(c: ReidSourceCluster) -> dict[str, Any]:
    return {
        "id": c.id, "cluster_code": c.cluster_code, "cluster_kind": c.cluster_kind,
        "cluster_kind_label": {"burst": "连拍序列", "crop": "原图裁剪",
                               "duplicate_hash": "同哈希副本", "manual": "人工归并"}.get(c.cluster_kind, c.cluster_kind),
        "rationale": c.rationale, "created_at": iso(c.created_at),
    }


def observation_out(db: Session, o: ReidObservation, *, include_relations: bool = False) -> dict[str, Any]:
    station = db.get(Station, o.station_id)
    data = {
        "id": o.id,
        "observation_code": o.observation_code,
        "species_code": o.species_code,
        "observation_kind": o.observation_kind,
        "source_record_id": o.source_record_id,
        "external_ref": o.external_ref,
        "file_hash": o.file_hash,
        "station_id": o.station_id,
        "station_code": station.code if station else None,
        "station_name": station.name if station else None,
        "latitude": o.latitude,
        "longitude": o.longitude,
        "coord_precision_m": o.coord_precision_m,
        "observed_at": iso(o.observed_at),
        "received_at": iso(o.received_at),
        "effective_observed_at": iso(effective_time(o)),
        "corrected_observed_at": iso(o.corrected_observed_at),
        "time_correction_id": o.time_correction_id,
        "location_version_id": o.location_version_id,
        "feature_version_id": o.feature_version_id,
        "posture_quality": o.posture_quality,
        "posture_score": o.posture_score,
        "visible_features": o.visible_features,
        "device_clock": o.device_clock,
        "source_cluster_id": o.source_cluster_id,
        "authorization": o.authorization,
        "authorization_status": o.authorization_status,
        "interpretability": o.interpretability,
        "season_code": o.season_code,
        "survey_date": o.survey_date.isoformat() if o.survey_date else None,
        "payload_hash": o.payload_hash,
        "record_status": o.record_status,
        "created_by": o.created_by,
        "created_at": iso(o.created_at),
    }
    if include_relations:
        data["source_cluster"] = (
            source_cluster_out(o.source_cluster) if o.source_cluster_id else None
        )
    return data


def decision_out(d: ReidDecision) -> dict[str, Any]:
    return {
        "id": d.id, "candidate_id": d.candidate_id, "partition_id": d.partition_id,
        "expert": d.expert, "expert_level": d.expert_level, "verdict": d.verdict,
        "verdict_label": {"confirm": "确认同一个体", "reject": "否决同一个体",
                          "retain": "保留待补证"}.get(d.verdict, d.verdict),
        "reason": d.reason, "evidence_snapshot": d.evidence_snapshot,
        "frozen_versions": d.frozen_versions,
        "expected_last_decision_id": d.expected_last_decision_id,
        "superseded": d.superseded, "created_at": iso(d.created_at),
    }


def candidate_out(db: Session, c: ReidCandidate, *, decisions: list[ReidDecision] | None = None) -> dict[str, Any]:
    obs_a = db.get(ReidObservation, c.observation_a_id)
    obs_b = db.get(ReidObservation, c.observation_b_id)
    if decisions is None:
        decisions = list(db.execute(
            select(ReidDecision).where(ReidDecision.candidate_id == c.id).order_by(ReidDecision.id)
        ).scalars())
    return {
        "id": c.id, "batch_id": c.batch_id,
        "observation_a_id": c.observation_a_id, "observation_b_id": c.observation_b_id,
        "observation_a_code": obs_a.observation_code if obs_a else None,
        "observation_b_code": obs_b.observation_code if obs_b else None,
        "observation_a_station": db.get(Station, obs_a.station_id).code if obs_a else None,
        "observation_b_station": db.get(Station, obs_b.station_id).code if obs_b else None,
        "feature_score": c.feature_score,
        "spatial_reachable": c.spatial_reachable,
        "evidence": c.evidence,
        "counter_evidence": c.counter_evidence,
        "source_independent": c.source_independent,
        "status": c.status,
        "status_label": CANDIDATE_STATUS_LABELS.get(c.status, c.status),
        "created_by": c.created_by, "created_at": iso(c.created_at),
        "updated_at": iso(c.updated_at),
        "decisions": [decision_out(d) for d in decisions],
    }


def batch_out(db: Session, b: ReidBatch, *, include_candidates: bool = False) -> dict[str, Any]:
    data = {
        "id": b.id, "batch_code": b.batch_code, "season_code": b.season_code,
        "species_code": b.species_code, "scope_observation_ids": b.scope_observation_ids,
        "max_travel_speed_kmh": b.max_travel_speed_kmh,
        "feature_threshold": b.feature_threshold,
        "pair_search_limit": b.pair_search_limit,
        "partition_limit": b.partition_limit,
        "status": b.status,
        "status_label": {"searching": "搜索中", "completed": "已完成", "truncated": "搜索截断"}.get(b.status, b.status),
        "checked_pair_count": b.checked_pair_count,
        "unresolved_observation_ids": b.unresolved_observation_ids,
        "truncation_note": b.truncation_note,
        "created_by": b.created_by, "created_at": iso(b.created_at),
    }
    if include_candidates:
        candidates = list(db.execute(
            select(ReidCandidate).where(ReidCandidate.batch_id == b.id).order_by(ReidCandidate.id)
        ).scalars())
        partitions = list(db.execute(
            select(ReidPartition).where(ReidPartition.batch_id == b.id).order_by(ReidPartition.rank)
        ).scalars())
        data["candidates"] = [candidate_out(db, c) for c in candidates]
        data["partitions"] = [partition_out(p) for p in partitions]
    return data


def partition_out(p: ReidPartition) -> dict[str, Any]:
    return {
        "id": p.id, "batch_id": p.batch_id, "partition_code": p.partition_code,
        "rank": p.rank, "score": p.score, "groups": p.groups,
        "competing_memberships": p.competing_memberships,
        "constraint_violations": p.constraint_violations,
        "status": p.status,
        "status_label": {"proposed": "候选方案", "adopted": "已裁定采用",
                         "discarded": "已放弃"}.get(p.status, p.status),
        "created_at": iso(p.created_at),
    }


def individual_version_out(v: ReidIndividualVersion) -> dict[str, Any]:
    return {
        "id": v.id, "individual_id": v.individual_id, "version_number": v.version_number,
        "observation_ids": v.observation_ids, "source_cluster_ids": v.source_cluster_ids,
        "candidate_ids": v.candidate_ids, "decision_ids": v.decision_ids,
        "frozen_versions": v.frozen_versions, "change_reason": v.change_reason,
        "status": v.status, "status_label": VERSION_STATUS_LABELS.get(v.status, v.status),
        "superseded_by_id": v.superseded_by_id, "created_by": v.created_by,
        "created_at": iso(v.created_at),
    }


def individual_out(db: Session, i: ReidIndividual, *, include_versions: bool = False) -> dict[str, Any]:
    current = db.get(ReidIndividualVersion, i.current_version_id) if i.current_version_id else None
    data = {
        "id": i.id, "individual_code": i.individual_code, "species_code": i.species_code,
        "season_code": i.season_code, "status": i.status,
        "status_label": INDIVIDUAL_STATUS_LABELS.get(i.status, i.status),
        "current_version_id": i.current_version_id,
        "observation_ids": current.observation_ids if current else [],
        "created_at": iso(i.created_at),
    }
    if include_versions:
        versions = list(db.execute(
            select(ReidIndividualVersion)
            .where(ReidIndividualVersion.individual_id == i.id)
            .order_by(ReidIndividualVersion.version_number)
        ).scalars())
        data["versions"] = [individual_version_out(v) for v in versions]
    return data


def capture_entry_out(db: Session, e: ReidCaptureEntry) -> dict[str, Any]:
    obs = db.get(ReidObservation, e.observation_id)
    station = db.get(Station, e.station_id)
    individual = db.get(ReidIndividual, e.individual_id) if e.individual_id else None
    return {
        "id": e.id, "report_run_id": e.report_run_id,
        "individual_id": e.individual_id,
        "individual_code": individual.individual_code if individual else None,
        "individual_version_id": e.individual_version_id,
        "observation_id": e.observation_id,
        "observation_code": obs.observation_code if obs else None,
        "source_cluster_id": e.source_cluster_id,
        "station_id": e.station_id, "station_code": station.code if station else None,
        "survey_date": e.survey_date.isoformat(), "season_code": e.season_code,
        "capture_kind": e.capture_kind,
        "capture_kind_label": {"first": "首次捕获", "repeat": "重复捕获", "excluded": "不纳入"}.get(
            e.capture_kind, e.capture_kind
        ),
        "sequence_no": e.sequence_no, "status": e.status,
        "status_label": CAPTURE_STATUS_LABELS.get(e.status, e.status),
        "exclusion_reason": e.exclusion_reason, "created_at": iso(e.created_at),
    }


def report_run_out(db: Session, r: ReidReportRun, *, include_entries: bool = False) -> dict[str, Any]:
    data = {
        "id": r.id, "report_code": r.report_code, "season_code": r.season_code,
        "species_code": r.species_code, "status": r.status, "summary": r.summary,
        "superseded_by_id": r.superseded_by_id, "created_by": r.created_by,
        "created_at": iso(r.created_at),
    }
    if include_entries:
        entries = list(db.execute(
            select(ReidCaptureEntry)
            .where(ReidCaptureEntry.report_run_id == r.id)
            .order_by(ReidCaptureEntry.sequence_no, ReidCaptureEntry.id)
        ).scalars())
        data["entries"] = [capture_entry_out(db, e) for e in entries]
    return data


def review_event_out(e: ReidReviewEvent) -> dict[str, Any]:
    return {
        "id": e.id, "individual_id": e.individual_id,
        "individual_version_id": e.individual_version_id,
        "trigger_type": e.trigger_type,
        "trigger_label": {
            "authorization_withdrawn": "授权撤回",
            "hash_mismatch": "哈希不一致",
            "location_revision": "位置版本修订",
        }.get(e.trigger_type, e.trigger_type),
        "trigger_detail": e.trigger_detail, "status": e.status,
        "status_label": {"opened": "复审中", "resolved_keep": "复审沿用",
                         "resolved_revise": "复审修订", "resolved_revoke": "复审撤销"}.get(
            e.status, e.status
        ),
        "resolution": e.resolution, "opened_by": e.opened_by,
        "resolved_by": e.resolved_by, "created_at": iso(e.created_at),
        "resolved_at": iso(e.resolved_at),
    }


def adjudication_out(a: ReidAdjudication) -> dict[str, Any]:
    return {
        "id": a.id, "candidate_id": a.candidate_id, "reason": a.reason,
        "third_party_evidence": a.third_party_evidence, "status": a.status,
        "final_verdict": a.final_verdict, "opened_by": a.opened_by,
        "resolved_by": a.resolved_by, "created_at": iso(a.created_at),
        "resolved_at": iso(a.resolved_at),
    }


def hold_out(h: ReidMembershipHold) -> dict[str, Any]:
    return {
        "id": h.id, "observation_id": h.observation_id,
        "individual_a_id": h.individual_a_id, "individual_b_id": h.individual_b_id,
        "candidate_id": h.candidate_id, "status": h.status, "reason": h.reason,
        "created_at": iso(h.created_at), "resolved_at": iso(h.resolved_at),
    }
