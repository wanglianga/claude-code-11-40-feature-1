"""野生动物个体重识别证据链领域服务。

核心原则：
  * 外观相似只产生候选关系（ReidCandidate），绝不直接写成同一动物；
  * 只有专家决策（ReidDecision）才能形成确认个体版本（ReidIndividualVersion）；
  * 联合划分（ReidPartition）只供裁定，得分最高的划分不会自动进入统计；
  * 样线捕获账（ReidCaptureEntry）按确认个体版本计算，季报运行冻结当时口径；
  * 被否决关系是硬约束，互斥/传递不一致会阻断合并；
  * 授权撤回、哈希不一致、位置修订只把新版本转入复审，旧季报保持原样。
"""
from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AuditEvent,
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
    RulebookVersion,
    Station,
    utcnow,
)
from .utils import canonical_hash, local_date, parse_dt

# 候选/决策/版本状态词表集中维护，API 与前端共用。
CANDIDATE_CANDIDATE = "candidate"
CANDIDATE_CONFIRMED = "confirmed"
CANDIDATE_REJECTED = "rejected"
CANDIDATE_RETAINED = "retained"
CANDIDATE_ADJUDICATING = "adjudicating_pending"
CANDIDATE_BLOCKED = "blocked"

DECISION_VERDICTS = {"confirm", "reject", "retain"}
POLARITY = {"confirm": 1, "reject": -1, "retain": 0}

INDIVIDUAL_ACTIVE = "active"
INDIVIDUAL_UNDER_REVIEW = "under_review"
INDIVIDUAL_SPLIT = "split"
INDIVIDUAL_MERGED = "merged"
INDIVIDUAL_REVOKED = "revoked"

VERSION_CURRENT = "current"
VERSION_SUPERSEDED = "superseded"
VERSION_UNDER_REVIEW = "under_review"
VERSION_REVOKED = "revoked"


class ReidError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _audit(db: Session, entity_type: str, entity_id: int, action: str, actor: str, detail: dict) -> None:
    db.add(
        AuditEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor=actor,
            detail=detail,
        )
    )


def effective_time(obs: ReidObservation) -> datetime:
    """观察的有效采集时间：优先采用已验证校时后的时间。"""
    return obs.corrected_observed_at or obs.observed_at


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _obs_coords(db: Session, obs: ReidObservation) -> tuple[float, float]:
    if obs.latitude is not None and obs.longitude is not None:
        return obs.latitude, obs.longitude
    station = db.get(Station, obs.station_id)
    return station.latitude, station.longitude


def feature_similarity(obs_a: ReidObservation, obs_b: ReidObservation) -> float:
    """对斑纹/伤痕等集合特征做 Jaccard、标量特征做等值比较的加权相似度。"""
    fa, fb = obs_a.visible_features or {}, obs_b.visible_features or {}
    keys = set(fa) | set(fb)
    scores: list[float] = []
    for key in keys:
        x, y = fa.get(key), fb.get(key)
        if isinstance(x, list) or isinstance(y, list):
            sx, sy = set(x or []), set(y or [])
            if not sx and not sy:
                continue
            scores.append(len(sx & sy) / len(sx | sy))
        else:
            if x is None or y is None:
                scores.append(0.0)
            else:
                scores.append(1.0 if x == y else 0.0)
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 4)


def reachability(db: Session, a: ReidObservation, b: ReidObservation, max_speed_kmh: float) -> dict:
    """时空可达性：要求同一动物在两次观察之间以不超过最大移动速度往返。"""
    lat1, lon1 = _obs_coords(db, a)
    lat2, lon2 = _obs_coords(db, b)
    distance = haversine_km(lat1, lon1, lat2, lon2)
    hours = abs((effective_time(b) - effective_time(a)).total_seconds()) / 3600.0
    same_place = distance < 0.05
    if hours == 0:
        required = None
        reachable = same_place
    else:
        required = round(distance / hours, 3)
        reachable = required <= max_speed_kmh
    return {
        "distance_km": round(distance, 3),
        "time_gap_hours": round(hours, 3),
        "required_speed_kmh": required,
        "max_travel_speed_kmh": max_speed_kmh,
        "reachable": reachable,
        "same_source_cluster": a.source_cluster_id is not None
        and a.source_cluster_id == b.source_cluster_id,
    }


def _pair_key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _find_candidate(db: Session, a: int, b: int) -> ReidCandidate | None:
    lo, hi = _pair_key(a, b)
    return db.execute(
        select(ReidCandidate).where(
            ReidCandidate.observation_a_id == lo,
            ReidCandidate.observation_b_id == hi,
        )
    ).scalar_one_or_none()


def _load_observations(db: Session, ids: list[int]) -> list[ReidObservation]:
    if not ids:
        return []
    return list(
        db.execute(
            select(ReidObservation).where(ReidObservation.id.in_(ids)).order_by(ReidObservation.id)
        ).scalars()
    )


# ---------------------------------------------------------------------------
# 版本登记（特征 / 位置 / 校时）
# ---------------------------------------------------------------------------
def register_feature_version(db: Session, *, code: str, version: str, feature_names: list[str], notes: str) -> ReidFeatureExtractionVersion:
    existing = db.execute(
        select(ReidFeatureExtractionVersion).where(ReidFeatureExtractionVersion.code == code)
    ).scalar_one_or_none()
    if existing:
        return existing
    row = ReidFeatureExtractionVersion(code=code, version=version, feature_names=feature_names, notes=notes)
    db.add(row)
    db.flush()
    return row


def register_location_version(db: Session, *, code: str, version: str, change_reason: str) -> ReidLocationVersion:
    existing = db.execute(
        select(ReidLocationVersion).where(ReidLocationVersion.code == code)
    ).scalar_one_or_none()
    if existing:
        return existing
    row = ReidLocationVersion(code=code, version=version, change_reason=change_reason)
    db.add(row)
    db.flush()
    return row


def register_time_correction(
    db: Session,
    *,
    code: str,
    version: str,
    target_device: str,
    offset_seconds: float,
    valid_from: str,
    valid_to: str | None,
    verified: bool,
    basis: str,
) -> ReidTimeCorrectionVersion:
    existing = db.execute(
        select(ReidTimeCorrectionVersion).where(ReidTimeCorrectionVersion.code == code)
    ).scalar_one_or_none()
    if existing:
        return existing
    row = ReidTimeCorrectionVersion(
        code=code,
        version=version,
        target_device=target_device,
        offset_seconds=offset_seconds,
        valid_from=parse_dt(valid_from),
        valid_to=parse_dt(valid_to) if valid_to else None,
        verified=verified,
        basis=basis,
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# 观察登记与来源簇
# ---------------------------------------------------------------------------
def _resolve_source_cluster(db: Session, data: dict, file_hash: str) -> ReidSourceCluster | None:
    """同一连拍、同一原图裁剪、同哈希副本必须归入同一来源簇。"""
    cluster = None
    if data.get("source_cluster_id"):
        cluster = db.get(ReidSourceCluster, int(data["source_cluster_id"]))
        if cluster is None:
            raise ReidError("来源簇不存在", 404)
        return cluster

    derived_from = data.get("derived_from_observation_id")
    burst_group = data.get("burst_group")
    if derived_from:
        parent = db.get(ReidObservation, int(derived_from))
        if parent is None:
            raise ReidError("被裁剪原图观察不存在", 404)
        if parent.source_cluster_id:
            return parent.source_cluster
        cluster = ReidSourceCluster(
            cluster_code=f"SC-CROP-{parent.observation_code}",
            cluster_kind="crop",
            rationale=f"由观察 {parent.observation_code} 的原图裁剪派生",
        )
        db.add(cluster)
        db.flush()
        parent.source_cluster_id = cluster.id
        return cluster

    if burst_group:
        code = f"SC-BURST-{burst_group}"
        cluster = db.execute(
            select(ReidSourceCluster).where(ReidSourceCluster.cluster_code == code)
        ).scalar_one_or_none()
        if cluster is None:
            cluster = ReidSourceCluster(
                cluster_code=code,
                cluster_kind="burst",
                rationale=f"同一连拍序列 {burst_group}",
            )
            db.add(cluster)
            db.flush()
        return cluster

    # 同文件哈希：自动判重会把它们当作两张，但证据链上只能是同一来源簇。
    duplicate = db.execute(
        select(ReidObservation).where(ReidObservation.file_hash == file_hash)
    ).scalars().first()
    if duplicate is not None:
        if duplicate.source_cluster_id:
            return duplicate.source_cluster
        cluster = ReidSourceCluster(
            cluster_code=f"SC-DUP-{file_hash[:16]}",
            cluster_kind="duplicate_hash",
            rationale="原始文件哈希完全一致的重复素材",
        )
        db.add(cluster)
        db.flush()
        duplicate.source_cluster_id = cluster.id
        return cluster
    return None


def register_observation(db: Session, data: dict, actor: str) -> ReidObservation:
    station = db.get(Station, int(data["station_id"]))
    if station is None:
        raise ReidError("相机/样线站点不存在", 404)
    observed_at = parse_dt(data["observed_at"])
    received_at = parse_dt(data["received_time"])
    payload = data.get("payload") or {}
    external_ref = data.get("external_ref", "")
    file_hash = data.get("file_hash") or hashlib.sha256(
        f"{external_ref}|{canonical_hash(payload)}".encode()
    ).hexdigest()

    cluster = _resolve_source_cluster(db, data, file_hash)
    correction = None
    corrected = observed_at
    if data.get("time_correction_id"):
        correction = db.get(ReidTimeCorrectionVersion, int(data["time_correction_id"]))
        if correction is None:
            raise ReidError("时间校正版本不存在", 404)
        corrected = observed_at - timedelta(seconds=correction.offset_seconds)

    count = db.execute(select(func.count()).select_from(ReidObservation)).scalar_one()
    obs = ReidObservation(
        observation_code=f"OBS-{data['species_code']}-{count + 1:04d}",
        species_code=data["species_code"],
        observation_kind=data.get("observation_kind", "photo"),
        source_record_id=data.get("source_record_id"),
        external_ref=external_ref,
        file_hash=file_hash,
        station_id=station.id,
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        coord_precision_m=data.get("coord_precision_m"),
        observed_at=observed_at,
        received_at=received_at,
        corrected_observed_at=corrected if correction else None,
        time_correction_id=correction.id if correction else None,
        location_version_id=data.get("location_version_id"),
        feature_version_id=data.get("feature_version_id"),
        posture_quality=data.get("posture_quality", "medium"),
        posture_score=float(data.get("posture_score", 0.5)),
        visible_features=data.get("visible_features") or {},
        device_clock=data.get("device_clock") or {},
        source_cluster_id=cluster.id if cluster else None,
        authorization=data.get("authorization") or {"license": "field-survey-2026", "granted_by": actor},
        authorization_status="authorized",
        interpretability=data.get("interpretability", "interpretable"),
        season_code=data["season_code"],
        survey_date=local_date(corrected),
        payload=payload,
        payload_hash=canonical_hash(payload),
        created_by=actor,
    )
    db.add(obs)
    db.flush()
    _audit(
        db, "reid_observation", obs.id, "reid.observation.registered", actor,
        {"observation_code": obs.observation_code, "source_cluster_id": obs.source_cluster_id},
    )
    return obs


def apply_time_correction(db: Session, observation_id: int, correction_id: int, actor: str) -> ReidObservation:
    """校时修订：只重算可达性并按需“新建候选”，绝不自动合并个体。"""
    obs = db.get(ReidObservation, observation_id)
    if obs is None:
        raise ReidError("观察不存在", 404)
    correction = db.get(ReidTimeCorrectionVersion, correction_id)
    if correction is None:
        raise ReidError("时间校正版本不存在", 404)
    before = effective_time(obs)
    obs.time_correction_id = correction.id
    obs.corrected_observed_at = obs.observed_at - timedelta(seconds=correction.offset_seconds)
    obs.survey_date = local_date(effective_time(obs))
    db.flush()

    peers = list(
        db.execute(
            select(ReidObservation)
            .where(ReidObservation.season_code == obs.season_code)
            .where(ReidObservation.species_code == obs.species_code)
            .where(ReidObservation.id != obs.id)
        ).scalars()
    )
    created: list[int] = []
    for peer in peers:
        reach = reachability(db, obs, peer, correction_max_speed(db, obs.season_code))
        candidate = _find_candidate(db, obs.id, peer.id)
        score = feature_similarity(obs, peer)
        if candidate is None:
            # 校时使原先不可能关联的两张照片进入可达窗口：只创建新候选。
            if reach["reachable"] and score > 0:
                candidate = _persist_candidate(
                    db, None, obs, peer, score, reach,
                    actor="system", note=f"校时 {correction.code} 后新进入可达窗口"
                )
                created.append(candidate.id)
        else:
            candidate.evidence = {**(candidate.evidence or {}), "reachability_after_calibration": reach}
            if reach["reachable"] and not candidate.spatial_reachable:
                candidate.counter_evidence = [
                    c for c in (candidate.counter_evidence or [])
                    if c.get("kind") != "spatiotemporal_unreachable"
                ]
            candidate.spatial_reachable = reach["reachable"]
            candidate.updated_at = utcnow()
    _audit(
        db, "reid_observation", obs.id, "reid.observation.time_calibrated", actor,
        {"correction_id": correction.id, "before": before.isoformat(),
         "after": effective_time(obs).isoformat(), "new_candidate_ids": created},
    )
    # 校时可能改变季节窗口归属，重算最新季报（旧季报保持冻结）。
    refresh_latest_report_run(db, obs.season_code, obs.species_code, actor)
    return obs


def correction_max_speed(db: Session, season_code: str) -> float:
    batch = db.execute(
        select(ReidBatch)
        .where(ReidBatch.season_code == season_code)
        .order_by(ReidBatch.id.desc())
    ).scalars().first()
    return batch.max_travel_speed_kmh if batch else 3.0


# ---------------------------------------------------------------------------
# 候选生成（批次内联合候选）
# ---------------------------------------------------------------------------
def _persist_candidate(
    db: Session, batch: ReidBatch | None, a: ReidObservation, b: ReidObservation,
    score: float, reach: dict, *, actor: str, note: str = "",
) -> ReidCandidate:
    lo, hi = _pair_key(a.id, b.id)
    obs_lo = a if a.id == lo else b
    obs_hi = b if b.id == lo else a
    independent = (
        obs_lo.source_cluster_id != obs_hi.source_cluster_id
        or (obs_lo.source_cluster_id is None and obs_hi.source_cluster_id is None
            and obs_lo.external_ref != obs_hi.external_ref)
    )
    counter = []
    if not reach["reachable"] and not reach["same_source_cluster"]:
        counter.append({
            "kind": "spatiotemporal_unreachable",
            "detail": "按最大移动速度，两个地点在该时间差内无法往返",
            "measurement": reach,
        })
    if obs_lo.posture_quality == "poor" or obs_hi.posture_quality == "poor":
        counter.append({"kind": "poor_posture", "detail": "至少一张素材姿态质量差，特征不可复核"})
    candidate = ReidCandidate(
        batch_id=batch.id if batch else None,
        observation_a_id=lo,
        observation_b_id=hi,
        feature_score=score,
        spatial_reachable=bool(reach["reachable"]),
        evidence={
            "feature_similarity": score,
            "reachability": reach,
            "feature_version_ids": sorted(
                {x for x in (obs_lo.feature_version_id, obs_hi.feature_version_id) if x}
            ),
            "note": note,
        },
        counter_evidence=counter,
        source_independent=independent,
        status=CANDIDATE_CANDIDATE,
        created_by=actor,
    )
    db.add(candidate)
    db.flush()
    return candidate


def create_batch(
    db: Session,
    *,
    season_code: str,
    species_code: str,
    observation_ids: list[int] | None,
    max_travel_speed_kmh: float,
    feature_threshold: float,
    pair_search_limit: int,
    partition_limit: int,
    actor: str,
) -> ReidBatch:
    q = select(ReidObservation).where(
        ReidObservation.season_code == season_code,
        ReidObservation.species_code == species_code,
        ReidObservation.record_status == "active",
    )
    if observation_ids:
        q = q.where(ReidObservation.id.in_(observation_ids))
    observations = list(db.execute(q.order_by(ReidObservation.id)).scalars())
    if len(observations) < 2:
        raise ReidError("批次至少需要两张观察", 422)

    count = db.execute(select(func.count()).select_from(ReidBatch)).scalar_one()
    batch = ReidBatch(
        batch_code=f"BATCH-{season_code}-{count + 1:03d}",
        season_code=season_code,
        species_code=species_code,
        scope_observation_ids=[o.id for o in observations],
        max_travel_speed_kmh=max_travel_speed_kmh,
        feature_threshold=feature_threshold,
        pair_search_limit=pair_search_limit,
        partition_limit=partition_limit,
        created_by=actor,
    )
    db.add(batch)
    db.flush()

    checked = 0
    truncated = False
    for i in range(len(observations)):
        for j in range(i + 1, len(observations)):
            if checked >= pair_search_limit:
                truncated = True
                break
            checked += 1
            a, b = observations[i], observations[j]
            # 同一来源簇不再作为独立观察之间的重识别候选。
            if a.source_cluster_id and a.source_cluster_id == b.source_cluster_id:
                continue
            if a.interpretability == "unreadable" or b.interpretability == "unreadable":
                continue
            existing = _find_candidate(db, a.id, b.id)
            if existing is not None:
                # 已否决关系是持久约束：不重新生成候选。
                if existing.batch_id is None:
                    existing.batch_id = batch.id
                continue
            score = feature_similarity(a, b)
            reach = reachability(db, a, b, max_travel_speed_kmh)
            if score >= feature_threshold:
                _persist_candidate(db, batch, a, b, score, reach, actor=actor)
        if truncated:
            break

    matched = set()
    for cand in _batch_candidates(db, batch):
        matched.add(cand.observation_a_id)
        matched.add(cand.observation_b_id)
    unresolved = [o.id for o in observations if o.id not in matched]
    batch.checked_pair_count = checked
    batch.unresolved_observation_ids = unresolved
    batch.status = "truncated" if truncated else "completed"
    batch.truncation_note = (
        f"候选对数达到搜索上限 {pair_search_limit}，仅检查前 {checked} 对，"
        f"未解决观察 {len(unresolved)} 张；不声称找到唯一划分。"
        if truncated else ""
    )
    db.flush()
    search_partitions(db, batch, actor)
    _detect_competing_claims(db, batch, actor)
    _audit(
        db, "reid_batch", batch.id, "reid.batch.searched", actor,
        {"pairs_checked": checked, "truncated": truncated, "unresolved": len(unresolved)},
    )
    return batch


def _batch_candidates(db: Session, batch: ReidBatch) -> list[ReidCandidate]:
    return list(
        db.execute(
            select(ReidCandidate)
            .where(ReidCandidate.batch_id == batch.id)
            .order_by(ReidCandidate.feature_score.desc())
        ).scalars()
    )


def _scope_candidates(db: Session, obs_ids: list[int]) -> list[ReidCandidate]:
    """批次范围内的候选，包含历史批次已生成、本批次复用的候选关系。"""
    if not obs_ids:
        return []
    return list(
        db.execute(
            select(ReidCandidate)
            .where(
                ReidCandidate.observation_a_id.in_(obs_ids),
                ReidCandidate.observation_b_id.in_(obs_ids),
            )
            .order_by(ReidCandidate.feature_score.desc())
        ).scalars()
    )


# ---------------------------------------------------------------------------
# 联合划分搜索（一致个体划分，不自动入选）
# ---------------------------------------------------------------------------
class DSU:
    def __init__(self, nodes: list[int]):
        self.parent = {n: n for n in nodes}

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        self.parent[self.find(x)] = self.find(y)

    def groups(self) -> list[list[int]]:
        out: dict[int, list[int]] = {}
        for n in self.parent:
            out.setdefault(self.find(n), []).append(n)
        return [sorted(v) for v in out.values()]


def _hard_constraints(db: Session, obs_ids: list[int]) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """返回 (必须相连的确认边, 不可相连的否决/冻结边)。"""
    must_link, cannot_link = [], []
    if not obs_ids:
        return must_link, cannot_link
    rows = db.execute(
        select(ReidCandidate).where(
            ReidCandidate.observation_a_id.in_(obs_ids),
            ReidCandidate.observation_b_id.in_(obs_ids),
        )
    ).scalars()
    for cand in rows:
        if cand.status == CANDIDATE_CONFIRMED:
            must_link.append((cand.observation_a_id, cand.observation_b_id))
        elif cand.status in (CANDIDATE_REJECTED, CANDIDATE_ADJUDICATING, CANDIDATE_BLOCKED):
            cannot_link.append((cand.observation_a_id, cand.observation_b_id))
    return must_link, cannot_link


def _group_feasible(db: Session, members: list[int], max_speed: float) -> dict | None:
    """全组一致性：任意两张照片必须两两可达，防止传递合并造出同一时刻两地现身。"""
    obs_map = {o.id: o for o in _load_observations(db, members)}
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            a, b = obs_map[members[i]], obs_map[members[j]]
            if a.source_cluster_id and a.source_cluster_id == b.source_cluster_id:
                continue
            reach = reachability(db, a, b, max_speed)
            if not reach["reachable"]:
                return {
                    "observation_a_id": a.id,
                    "observation_b_id": b.id,
                    "kind": "transitive_spatiotemporal_conflict",
                    "measurement": reach,
                    "detail": "传递合并后要求同一个体在无法往返的两个地点先后/同时出现",
                }
    return None


def search_partitions(db: Session, batch: ReidBatch, actor: str) -> list[ReidPartition]:
    observations = _load_observations(db, batch.scope_observation_ids)
    obs_ids = [o.id for o in observations]
    candidates = [
        c for c in _scope_candidates(db, obs_ids)
        if c.status in (CANDIDATE_CANDIDATE, CANDIDATE_CONFIRMED, CANDIDATE_RETAINED)
    ]
    must_link, cannot_link = _hard_constraints(db, obs_ids)
    cannot_set = {_pair_key(*p) for p in cannot_link}

    # 基线：只采用已确认边。
    base = DSU(obs_ids)
    for x, y in must_link:
        base.union(x, y)

    seen: set[tuple[tuple[int, ...], ...]] = set()
    partitions: list[ReidPartition] = []

    def add_partition(groups: list[list[int]], score: float, violations: list[dict]) -> None:
        signature = tuple(sorted(tuple(g) for g in groups))
        if signature in seen:
            return
        seen.add(signature)
        rank = len(partitions) + 1
        row = ReidPartition(
            batch_id=batch.id,
            partition_code=f"{batch.batch_code}-P{rank}",
            rank=rank,
            score=round(score, 4),
            groups=groups,
            competing_memberships={},
            constraint_violations=violations,
        )
        db.add(row)
        db.flush()
        partitions.append(row)

    base_groups = base.groups()
    base_violations = [
        {"kind": "cannot_link_violated", "pair": list(p)}
        for p in cannot_link
        if base.find(p[0]) == base.find(p[1])
    ]
    add_partition(base_groups, 0.0, base_violations)

    # 贪心合并：按特征得分降序加入候选边，受否决约束与全组可达性双重限制。
    working = DSU(obs_ids)
    for x, y in must_link:
        working.union(x, y)
    cut_bridges: list[int] = []
    used_edges: list[int] = []
    for cand in sorted(candidates, key=lambda c: c.feature_score, reverse=True):
        ra, rb = working.find(cand.observation_a_id), working.find(cand.observation_b_id)
        if ra == rb:
            continue
        if _pair_key(cand.observation_a_id, cand.observation_b_id) in cannot_set:
            continue
        members = [n for n in obs_ids if working.find(n) in (ra, rb)]
        violation = _group_feasible(db, members, batch.max_travel_speed_kmh)
        if violation:
            cut_bridges.append(cand.id)
            continue
        working.union(cand.observation_a_id, cand.observation_b_id)
        used_edges.append(cand.id)

    greedy_groups = working.groups()
    greedy_score = round(
        sum(c.feature_score for c in candidates if c.id in used_edges) / max(1, len(used_edges)), 4
    )
    add_partition(greedy_groups, greedy_score, [])

    # 备选划分：切断最弱桥接边，暴露一张照片在不同分组中的竞争归属。
    weakest = sorted(
        (c for c in candidates if c.id in used_edges), key=lambda c: c.feature_score
    )
    alt = DSU(obs_ids)
    for x, y in must_link:
        alt.union(x, y)
    dropped: set[int] = set()
    for cand in weakest[:1]:
        dropped.add(cand.id)
    for cand in sorted(candidates, key=lambda c: c.feature_score, reverse=True):
        if cand.id in dropped:
            continue
        ra, rb = alt.find(cand.observation_a_id), alt.find(cand.observation_b_id)
        if ra == rb or _pair_key(cand.observation_a_id, cand.observation_b_id) in cannot_set:
            continue
        members = [n for n in obs_ids if alt.find(n) in (ra, rb)]
        if _group_feasible(db, members, batch.max_travel_speed_kmh):
            continue
        alt.union(cand.observation_a_id, cand.observation_b_id)
    add_partition(alt.groups(), max(0.0, greedy_score - 0.05), [])

    # 仅保留 partition_limit 个方案；竞争归属跨方案对照。
    kept = partitions[: batch.partition_limit]
    membership: dict[str, dict] = {}
    for part in kept:
        for index, group in enumerate(part.groups):
            for obs_id in group:
                membership.setdefault(str(obs_id), {})[part.partition_code] = index
    competing = {k: v for k, v in membership.items() if len(set(v.values())) > 1}
    for part in kept:
        part.competing_memberships = competing
    for extra in partitions[batch.partition_limit:]:
        db.delete(extra)
    db.flush()
    return kept


# ---------------------------------------------------------------------------
# 专家裁定
# ---------------------------------------------------------------------------
def _last_decision(db: Session, candidate_id: int) -> ReidDecision | None:
    return db.execute(
        select(ReidDecision)
        .where(ReidDecision.candidate_id == candidate_id)
        .order_by(ReidDecision.id.desc())
    ).scalars().first()


def _decision_snapshot(db: Session, cand: ReidCandidate) -> tuple[dict, dict]:
    obs_a = db.get(ReidObservation, cand.observation_a_id)
    obs_b = db.get(ReidObservation, cand.observation_b_id)
    snapshot = {
        "candidate_id": cand.id,
        "feature_score": cand.feature_score,
        "spatial_reachable": cand.spatial_reachable,
        "evidence": cand.evidence,
        "counter_evidence": cand.counter_evidence,
        "source_independent": cand.source_independent,
        "observations": [
            {
                "observation_id": o.id,
                "observation_code": o.observation_code,
                "file_hash": o.file_hash,
                "effective_observed_at": effective_time(o).isoformat(),
                "station_id": o.station_id,
                "source_cluster_id": o.source_cluster_id,
                "posture_quality": o.posture_quality,
                "visible_features": o.visible_features,
            }
            for o in (obs_a, obs_b)
        ],
    }
    frozen = {
        "feature_version_ids": sorted(
            {x for x in (obs_a.feature_version_id, obs_b.feature_version_id) if x}
        ),
        "location_version_ids": sorted(
            {x for x in (obs_a.location_version_id, obs_b.location_version_id) if x}
        ),
        "time_correction_ids": sorted(
            {x for x in (obs_a.time_correction_id, obs_b.time_correction_id) if x}
        ),
        "frozen_at": utcnow().isoformat(),
    }
    return snapshot, frozen


def decide_candidate(
    db: Session,
    candidate_id: int,
    *,
    verdict: str,
    reason: str,
    expert: str,
    expert_level: str = "peer",
    expected_last_decision_id: int | None = None,
    partition_id: int | None = None,
) -> ReidDecision:
    if verdict not in DECISION_VERDICTS:
        raise ReidError("裁定结论必须是 confirm/reject/retain")
    cand = db.execute(
        select(ReidCandidate).where(ReidCandidate.id == candidate_id).with_for_update()
    ).scalar_one_or_none()
    if cand is None:
        raise ReidError("候选关系不存在", 404)
    last = _last_decision(db, candidate_id)

    # 裁定待定关系已冻结统计资格，只能经第三方证据或上级裁定收口。
    if cand.status == CANDIDATE_ADJUDICATING and expert_level != "senior":
        raise ReidError(
            "该候选处于同级相反裁定的裁定待定状态，须引入第三方证据或上级裁定后才能变更",
            409,
        )

    # 乐观并发：两位专家同时基于同一旧状态裁定时，后提交者必须回到最新证据复核。
    if last is not None and expected_last_decision_id != last.id:
        raise ReidError(
            f"候选关系已有更新决策（#{last.id}，{last.expert}={last.verdict}），"
            "请基于最新证据复核后再提交",
            409,
        )

    snapshot, frozen = _decision_snapshot(db, cand)
    decision = ReidDecision(
        candidate_id=cand.id,
        partition_id=partition_id,
        expert=expert,
        expert_level=expert_level,
        verdict=verdict,
        reason=reason,
        evidence_snapshot=snapshot,
        frozen_versions=frozen,
        expected_last_decision_id=last.id if last else None,
    )
    db.add(decision)
    db.flush()

    # 同级专家相反结论：冻结统计资格，转入裁定待定。
    opposite = (
        last is not None
        and not last.superseded
        and last.expert != expert
        and last.expert_level == "peer"
        and expert_level == "peer"
        and POLARITY[last.verdict] * POLARITY[verdict] == -1
    )
    if opposite and expert_level != "senior":
        cand.status = CANDIDATE_ADJUDICATING
        existing_adj = db.execute(
            select(ReidAdjudication)
            .where(ReidAdjudication.candidate_id == cand.id)
            .where(ReidAdjudication.status == "pending")
        ).scalar_one_or_none()
        if existing_adj is None:
            db.add(
                ReidAdjudication(
                    candidate_id=cand.id,
                    reason=f"同级专家 {last.expert}({last.verdict}) 与 {expert}({verdict}) 结论相反",
                    opened_by=expert,
                )
            )
        db.flush()
        _freeze_individuals_for_adjudication(db, cand, expert)
        _audit(db, "reid_candidate", cand.id, "reid.candidate.adjudication_pending", expert,
               {"last_decision_id": last.id, "new_decision_id": decision.id})
        _refresh_open_holds(db, cand)
        season = db.get(ReidObservation, cand.observation_a_id).season_code
        species = db.get(ReidObservation, cand.observation_a_id).species_code
        refresh_latest_report_run(db, season, species, expert)
        return decision

    if last is not None and last.expert == expert:
        last.superseded = True

    if expert_level == "senior":
        for adj in db.execute(
            select(ReidAdjudication)
            .where(ReidAdjudication.candidate_id == cand.id)
            .where(ReidAdjudication.status == "pending")
        ).scalars():
            adj.status = "resolved"
            adj.final_verdict = verdict
            adj.resolved_by = expert
            adj.resolved_at = utcnow()

    if verdict == "retain":
        cand.status = CANDIDATE_RETAINED
    elif verdict == "reject":
        if cand.status == CANDIDATE_CONFIRMED:
            raise ReidError("已确认关系须通过个体拆分流程否决，不能直接改写", 409)
        cand.status = CANDIDATE_REJECTED
        _resolve_holds(db, cand, outcome="rejected")
    else:  # confirm
        _assert_merge_allowed(db, cand)
        cand.status = CANDIDATE_CONFIRMED
        materialize_individuals(db, cand, decision, actor=expert)
        _resolve_holds(db, cand, outcome="confirmed")

    cand.updated_at = utcnow()
    db.flush()
    _detect_competing_claims(db, None, expert)
    season = db.get(ReidObservation, cand.observation_a_id).season_code
    species = db.get(ReidObservation, cand.observation_a_id).species_code
    refresh_latest_report_run(db, season, species, expert)
    _audit(db, "reid_candidate", cand.id, f"reid.candidate.{verdict}", expert,
           {"decision_id": decision.id, "partition_id": partition_id})
    return decision


def _assert_merge_allowed(db: Session, cand: ReidCandidate) -> None:
    """否决约束 + 全组时空一致性双重检查。"""
    comp = set(_component_observations(db, cand.observation_a_id, cand.observation_b_id))
    clustered = list(
        db.execute(
            select(ReidObservation).where(
                ReidObservation.source_cluster_id.in_(
                    select(ReidObservation.source_cluster_id)
                    .where(ReidObservation.id.in_(comp))
                    .where(ReidObservation.source_cluster_id.is_not(None))
                )
            )
        ).scalars()
    )
    comp.update(o.id for o in clustered)
    obs_ids = sorted(comp)
    cannot = {
        _pair_key(c.observation_a_id, c.observation_b_id)
        for c in db.execute(select(ReidCandidate).where(ReidCandidate.status == CANDIDATE_REJECTED)).scalars()
    }
    for i in range(len(obs_ids)):
        for j in range(i + 1, len(obs_ids)):
            pair = _pair_key(obs_ids[i], obs_ids[j])
            if pair in cannot:
                raise ReidError(
                    f"观察 {obs_ids[i]} 与 {obs_ids[j]} 存在已否决的同一个体关系，"
                    "不能在另一条相似链上绕过该约束",
                    409,
                )
    speed = correction_max_speed(db, db.get(ReidObservation, cand.observation_a_id).season_code)
    violation = _group_feasible(db, obs_ids, speed)
    if violation:
        raise ReidError(f"合并未通过全组一致性检查：{violation['detail']}", 409)


def _component_observations(db: Session, seed_a: int, seed_b: int) -> set[int]:
    dsu = DSU([seed_a, seed_b])
    dsu.union(seed_a, seed_b)
    confirmed = list(
        db.execute(select(ReidCandidate).where(ReidCandidate.status == CANDIDATE_CONFIRMED)).scalars()
    )
    nodes = {seed_a, seed_b}
    for c in confirmed:
        nodes.add(c.observation_a_id)
        nodes.add(c.observation_b_id)
    dsu = DSU(sorted(nodes))
    dsu.union(seed_a, seed_b)
    for c in confirmed:
        dsu.union(c.observation_a_id, c.observation_b_id)
    return {n for n in nodes if dsu.find(n) == dsu.find(seed_a)}


def materialize_individuals(db: Session, cand: ReidCandidate, decision: ReidDecision, *, actor: str) -> ReidIndividual:
    """把确认边所在连通分量落为一个新的确认个体版本（冻结版本与理由）。"""
    component = set(_component_observations(db, cand.observation_a_id, cand.observation_b_id))
    # 同一来源簇（连拍/裁剪/同哈希）的成员必须随其素材一起进入同一个体版本。
    clustered = list(
        db.execute(
            select(ReidObservation).where(
                ReidObservation.source_cluster_id.in_(
                    select(ReidObservation.source_cluster_id)
                    .where(ReidObservation.id.in_(component))
                    .where(ReidObservation.source_cluster_id.is_not(None))
                )
            )
        ).scalars()
    )
    component.update(o.id for o in clustered)
    component = sorted(component)
    observations = _load_observations(db, component)
    clusters = sorted({o.source_cluster_id for o in observations if o.source_cluster_id})
    candidate_ids = sorted({
        c.id for c in db.execute(
            select(ReidCandidate).where(ReidCandidate.status == CANDIDATE_CONFIRMED)
        ).scalars()
        if c.observation_a_id in component and c.observation_b_id in component
    })
    decision_ids = sorted({
        d.id for d in db.execute(
            select(ReidDecision).join(ReidCandidate, ReidDecision.candidate_id == ReidCandidate.id)
            .where(ReidCandidate.id.in_(candidate_ids))
        ).scalars()
    })
    frozen = {
        "feature_version_ids": sorted({o.feature_version_id for o in observations if o.feature_version_id}),
        "location_version_ids": sorted({o.location_version_id for o in observations if o.location_version_id}),
        "time_correction_ids": sorted({o.time_correction_id for o in observations if o.time_correction_id}),
        "frozen_by_decision_id": decision.id,
        "frozen_at": utcnow().isoformat(),
    }
    touched = []
    for ind in db.execute(select(ReidIndividual)).scalars():
        if not ind.current_version_id:
            continue
        ver = db.get(ReidIndividualVersion, ind.current_version_id)
        if ver and set(ver.observation_ids) & set(component):
            touched.append(ind)
    active_touched = [i for i in touched if i.status in (INDIVIDUAL_ACTIVE, INDIVIDUAL_UNDER_REVIEW)]
    if not active_touched:
        count = db.execute(select(func.count()).select_from(ReidIndividual)).scalar_one()
        individual = ReidIndividual(
            individual_code=f"IND-{observations[0].species_code}-{count + 1:03d}",
            species_code=observations[0].species_code,
            season_code=observations[0].season_code,
            status=INDIVIDUAL_ACTIVE,
        )
        db.add(individual)
        db.flush()
        version = _new_version(db, individual, 1, component, clusters, candidate_ids, decision_ids,
                               frozen, f"专家 {actor} 确认候选 {cand.id} 建立个体", actor)
        individual.current_version_id = version.id
        db.flush()
        return individual

    target = sorted(active_touched, key=lambda i: i.id)[0]
    current = db.get(ReidIndividualVersion, target.current_version_id)
    merged_obs = sorted(set(current.observation_ids) | set(component))
    merged_clusters = sorted(set(current.source_cluster_ids) | set(clusters))
    version = _new_version(
        db, target, current.version_number + 1, merged_obs, merged_clusters,
        sorted(set(current.candidate_ids) | set(candidate_ids)),
        sorted(set(current.decision_ids) | set(decision_ids)),
        frozen, f"专家 {actor} 确认候选 {cand.id}，个体归属扩展", actor,
    )
    current.status = VERSION_SUPERSEDED
    current.superseded_by_id = version.id
    target.current_version_id = version.id
    target.status = INDIVIDUAL_ACTIVE

    for other in active_touched[1:]:
        other_current = db.get(ReidIndividualVersion, other.current_version_id)
        other.status = INDIVIDUAL_MERGED
        other_current.status = VERSION_SUPERSEDED
        other_current.superseded_by_id = version.id
        _audit(db, "reid_individual", other.id, "reid.individual.merged", actor,
               {"merged_into": target.id, "version_id": version.id})
    db.flush()
    return target


def _new_version(db: Session, individual: ReidIndividual, number: int, obs_ids, clusters,
                 candidate_ids, decision_ids, frozen, reason: str, actor: str) -> ReidIndividualVersion:
    version = ReidIndividualVersion(
        individual_id=individual.id,
        version_number=number,
        observation_ids=obs_ids,
        source_cluster_ids=clusters,
        candidate_ids=candidate_ids,
        decision_ids=decision_ids,
        frozen_versions=frozen,
        change_reason=reason,
        status=VERSION_CURRENT,
        created_by=actor,
    )
    db.add(version)
    db.flush()
    return version


# ---------------------------------------------------------------------------
# 联合划分整体裁定
# ---------------------------------------------------------------------------
def adopt_partition(db: Session, partition_id: int, *, expert: str, reason: str) -> ReidPartition:
    partition = db.get(ReidPartition, partition_id)
    if partition is None:
        raise ReidError("划分方案不存在", 404)
    if partition.status == "adopted":
        raise ReidError("该划分已被采用", 409)
    batch = db.get(ReidBatch, partition.batch_id)
    obs_ids = [o for group in partition.groups for o in group]
    must_link, cannot_link = _hard_constraints(db, obs_ids)
    cannot_set = {_pair_key(*p) for p in cannot_link}
    within, crossing = set(), set()
    for group in partition.groups:
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                within.add(_pair_key(group[i], group[j]))
    for cand in db.execute(
        select(ReidCandidate).where(
            ReidCandidate.observation_a_id.in_(obs_ids),
            ReidCandidate.observation_b_id.in_(obs_ids),
        )
    ).scalars():
        pair = _pair_key(cand.observation_a_id, cand.observation_b_id)
        if pair not in within:
            crossing.add(pair)
    blocked = cannot_set & within
    if blocked:
        raise ReidError(f"划分与已否决关系冲突：{sorted(blocked)}", 409)
    for group in partition.groups:
        violation = _group_feasible(db, group, batch.max_travel_speed_kmh)
        if violation:
            raise ReidError(f"划分 {partition.partition_code} 存在不一致分组：{violation['detail']}", 409)

    decisions: list[ReidDecision] = []
    db._reid_suspend_report = True
    try:
        for cand in db.execute(
            select(ReidCandidate).where(
                ReidCandidate.observation_a_id.in_(obs_ids),
                ReidCandidate.observation_b_id.in_(obs_ids),
            )
        ).scalars():
            pair = _pair_key(cand.observation_a_id, cand.observation_b_id)
            wanted = "confirm" if pair in within else "reject"
            if cand.status == CANDIDATE_CONFIRMED and wanted == "confirm":
                continue
            if cand.status == CANDIDATE_REJECTED and wanted == "reject":
                continue
            if cand.status in (CANDIDATE_ADJUDICATING,):
                raise ReidError(f"候选 {cand.id} 处于裁定待定，不能随划分自动采用", 409)
            decisions.append(
                decide_candidate(
                    db, cand.id, verdict=wanted,
                    reason=f"随划分 {partition.partition_code} 整体裁定：{reason}",
                    expert=expert, expected_last_decision_id=(
                        _last_decision(db, cand.id).id if _last_decision(db, cand.id) else None
                    ),
                    partition_id=partition.id,
                )
            )
    finally:
        db._reid_suspend_report = False

    partition.status = "adopted"
    db.flush()
    # 整个划分只产生一个新的冻结季报，而非每条边一个。
    refresh_latest_report_run(db, batch.season_code, batch.species_code, expert)
    _audit(db, "reid_partition", partition.id, "reid.partition.adopted", expert,
           {"decisions": [d.id for d in decisions]})
    return partition


# ---------------------------------------------------------------------------
# 个体拆分
# ---------------------------------------------------------------------------
def split_individual(
    db: Session, individual_id: int, *, groups: list[list[int]], reason: str, actor: str
) -> list[ReidIndividual]:
    individual = db.get(ReidIndividual, individual_id)
    if individual is None:
        raise ReidError("确认个体不存在", 404)
    current = db.get(ReidIndividualVersion, individual.current_version_id)
    if current is None or current.status not in (VERSION_CURRENT, VERSION_UNDER_REVIEW):
        raise ReidError("该个体版本不可拆分", 409)
    flat = sorted(o for group in groups for o in group)
    if sorted(flat) != sorted(current.observation_ids):
        raise ReidError("拆分分组必须完整覆盖当前版本的全部观察，且不得引入其他观察", 422)
    if len(groups) < 2 or any(not g for g in groups):
        raise ReidError("拆分至少需要两个非空分组", 422)
    if len(set(flat)) != len(flat):
        raise ReidError("同一观察不能同时出现在两个拆分分组", 422)
    speed = correction_max_speed(db, individual.season_code)
    for group in groups:
        violation = _group_feasible(db, sorted(group), speed)
        if violation:
            raise ReidError(f"拆分分组未通过一致性检查：{violation['detail']}", 409)

    individual.status = INDIVIDUAL_SPLIT
    current.status = VERSION_SUPERSEDED
    new_individuals: list[ReidIndividual] = []
    for idx, group in enumerate(sorted(groups), start=1):
        observations = _load_observations(db, group)
        clusters = sorted({o.source_cluster_id for o in observations if o.source_cluster_id})
        child = ReidIndividual(
            individual_code=f"{individual.individual_code}-S{idx}",
            species_code=individual.species_code,
            season_code=individual.season_code,
            status=INDIVIDUAL_ACTIVE,
        )
        db.add(child)
        db.flush()
        version = _new_version(
            db, child, 1, sorted(group), clusters, [], [],
            {**current.frozen_versions, "split_from_individual_id": individual.id,
             "split_from_version_id": current.id, "frozen_at": utcnow().isoformat()},
            f"由 {individual.individual_code} 拆分：{reason}", actor,
        )
        child.current_version_id = version.id
        new_individuals.append(child)
    db.flush()
    refresh_latest_report_run(db, individual.season_code, individual.species_code, actor)
    _audit(db, "reid_individual", individual.id, "reid.individual.split", actor,
           {"parent_version_id": current.id, "children": [i.id for i in new_individuals]})
    return new_individuals


# ---------------------------------------------------------------------------
# 裁定待定（同级相反结论的第三方/上级处置）
# ---------------------------------------------------------------------------
def resolve_adjudication(
    db: Session, adjudication_id: int, *, final_verdict: str, reason: str,
    expert: str, third_party_evidence: dict | None = None,
) -> ReidAdjudication:
    adj = db.get(ReidAdjudication, adjudication_id)
    if adj is None:
        raise ReidError("裁定案不存在", 404)
    if adj.status != "pending":
        raise ReidError("该裁定案已关闭", 409)
    adj.status = "resolved"
    adj.final_verdict = final_verdict
    adj.resolved_by = expert
    adj.resolved_at = utcnow()
    adj.third_party_evidence = third_party_evidence or {}
    adj.reason = f"{adj.reason}；处置：{reason}"
    cand = db.get(ReidCandidate, adj.candidate_id)
    decide_candidate(
        db, cand.id, verdict=final_verdict, reason=f"上级/第三方裁定：{reason}",
        expert=expert, expert_level="senior",
        expected_last_decision_id=_last_decision(db, cand.id).id,
    )
    # 收口因同级相反裁定而冻结的个体版本。
    pair = {cand.observation_a_id, cand.observation_b_id}
    for event in db.execute(
        select(ReidReviewEvent).where(
            ReidReviewEvent.trigger_type == "adjudication_conflict",
            ReidReviewEvent.status == "opened",
        )
    ).scalars():
        individual = db.get(ReidIndividual, event.individual_id)
        version = db.get(ReidIndividualVersion, event.individual_version_id)
        if not (pair & set(version.observation_ids)):
            continue
        if final_verdict == "confirm":
            individual.status = INDIVIDUAL_ACTIVE
            version.status = VERSION_CURRENT
            event.status = "resolved_keep"
        else:
            individual.status = INDIVIDUAL_REVOKED
            version.status = VERSION_REVOKED
            event.status = "resolved_revoke"
        event.resolved_by = expert
        event.resolved_at = utcnow()
        event.resolution = f"上级裁定 {final_verdict}：{reason}"
    db.flush()
    return adj


# ---------------------------------------------------------------------------
# 竞争归属冻结
# ---------------------------------------------------------------------------
def _detect_competing_claims(db: Session, batch: ReidBatch | None, actor: str) -> None:
    """已确认属于个体 A 的观察又被候选链主张向个体 B：先冻结重复捕获归属。

    全局扫描所有仍开放的候选/保留关系；同一候选只立案一次冻结，
    保证一张照片不会同时贡献两条个体轨迹。
    """
    current_versions = {
        i.id: db.get(ReidIndividualVersion, i.current_version_id)
        for i in db.execute(select(ReidIndividual)).scalars()
        if i.current_version_id
    }
    obs_owner: dict[int, int] = {}
    for individual_id, version in current_versions.items():
        if version and version.status in (VERSION_CURRENT, VERSION_UNDER_REVIEW):
            for obs_id in version.observation_ids:
                obs_owner[obs_id] = individual_id
    q = select(ReidCandidate).where(
        ReidCandidate.status.in_([CANDIDATE_CANDIDATE, CANDIDATE_RETAINED])
    )
    if batch is not None:
        q = q.where(ReidCandidate.batch_id == batch.id)
    for cand in db.execute(q).scalars():
        owner_a = obs_owner.get(cand.observation_a_id)
        owner_b = obs_owner.get(cand.observation_b_id)
        if not (owner_a and owner_b and owner_a != owner_b):
            continue
        exists = db.execute(
            select(ReidMembershipHold).where(
                ReidMembershipHold.observation_id == cand.observation_a_id,
                ReidMembershipHold.status == "open",
            )
        ).scalar_one_or_none()
        if exists:
            continue
        hold = ReidMembershipHold(
            observation_id=cand.observation_a_id,
            individual_a_id=owner_a,
            individual_b_id=owner_b,
            candidate_id=cand.id,
            reason="同一观察被两个确认个体的候选链同时主张，冻结双方重复捕获归属",
        )
        db.add(hold)
        db.flush()
        _audit(db, "reid_membership_hold", hold.id, "reid.hold.opened", actor,
               {"candidate_id": cand.id, "individual_a": owner_a, "individual_b": owner_b})


def _refresh_open_holds(db: Session, cand: ReidCandidate) -> None:
    for hold in db.execute(
        select(ReidMembershipHold).where(
            ReidMembershipHold.candidate_id == cand.id,
            ReidMembershipHold.status == "open",
        )
    ).scalars():
        hold.reason = f"{hold.reason}；候选转入裁定待定，继续冻结"
    db.flush()


def _freeze_individuals_for_adjudication(db: Session, cand: ReidCandidate, actor: str) -> None:
    """同级相反裁定：冻结涉及该关系的确认个体版本统计资格，开复审事件，等待第三方/上级裁定。"""
    pair = {cand.observation_a_id, cand.observation_b_id}
    for individual in db.execute(select(ReidIndividual)).scalars():
        if not individual.current_version_id:
            continue
        version = db.get(ReidIndividualVersion, individual.current_version_id)
        if version is None or not (pair & set(version.observation_ids)):
            continue
        if individual.status == INDIVIDUAL_UNDER_REVIEW:
            continue
        already = db.execute(
            select(ReidReviewEvent).where(
                ReidReviewEvent.individual_id == individual.id,
                ReidReviewEvent.status == "opened",
                ReidReviewEvent.trigger_type == "adjudication_conflict",
            )
        ).scalar_one_or_none()
        if already:
            continue
        event = ReidReviewEvent(
            individual_id=individual.id,
            individual_version_id=version.id,
            trigger_type="adjudication_conflict",
            trigger_detail={"candidate_id": cand.id, "observation_ids": sorted(pair)},
            status="opened",
            opened_by=actor,
        )
        db.add(event)
        db.flush()
        individual.status = INDIVIDUAL_UNDER_REVIEW
        version.status = VERSION_UNDER_REVIEW
        _audit(db, "reid_individual", individual.id, "reid.individual.under_review", actor,
               {"trigger": "adjudication_conflict", "review_event_id": event.id,
                "candidate_id": cand.id})
    db.flush()


def _resolve_holds(db: Session, cand: ReidCandidate, *, outcome: str) -> None:
    for hold in db.execute(
        select(ReidMembershipHold).where(
            ReidMembershipHold.candidate_id == cand.id,
            ReidMembershipHold.status == "open",
        )
    ).scalars():
        hold.status = "resolved"
        hold.resolved_at = utcnow()
        hold.reason = f"{hold.reason}；候选裁定结果：{outcome}"
    db.flush()


# ---------------------------------------------------------------------------
# 变动监测：授权撤回 / 哈希不一致 / 位置版本修订
# ---------------------------------------------------------------------------
def _individuals_using_observation(db: Session, observation_id: int) -> list[ReidIndividual]:
    return list(
        db.execute(
            select(ReidIndividual)
            .join(ReidIndividualVersion, ReidIndividual.current_version_id == ReidIndividualVersion.id)
            .where(ReidIndividualVersion.observation_ids.contains([observation_id]))
        ).scalars()
    )


def _open_review(db: Session, obs: ReidObservation, trigger: str, detail: dict, actor: str) -> list[ReidReviewEvent]:
    events = []
    for individual in _individuals_using_observation(db, obs.id):
        if individual.status == INDIVIDUAL_UNDER_REVIEW:
            continue
        version = db.get(ReidIndividualVersion, individual.current_version_id)
        event = ReidReviewEvent(
            individual_id=individual.id,
            individual_version_id=version.id,
            trigger_type=trigger,
            trigger_detail=detail,
            status="opened",
            opened_by=actor,
        )
        db.add(event)
        db.flush()
        individual.status = INDIVIDUAL_UNDER_REVIEW
        version.status = VERSION_UNDER_REVIEW
        events.append(event)
        _audit(db, "reid_individual", individual.id, "reid.individual.under_review", actor,
               {"trigger": trigger, "review_event_id": event.id, "observation_id": obs.id})
    db.flush()
    if events:
        refresh_latest_report_run(db, obs.season_code, obs.species_code, actor)
    return events


def withdraw_authorization(db: Session, observation_id: int, reason: str, actor: str) -> ReidObservation:
    obs = db.get(ReidObservation, observation_id)
    if obs is None:
        raise ReidError("观察不存在", 404)
    obs.authorization_status = "withdrawn"
    obs.authorization = {**(obs.authorization or {}), "withdrawn_at": utcnow().isoformat(),
                         "withdrawn_reason": reason}
    db.flush()
    _open_review(db, obs, "authorization_withdrawn",
                 {"observation_id": obs.id, "reason": reason}, actor)
    return obs


def flag_hash_mismatch(db: Session, observation_id: int, expected_hash: str, actor: str) -> ReidObservation:
    obs = db.get(ReidObservation, observation_id)
    if obs is None:
        raise ReidError("观察不存在", 404)
    if obs.file_hash == expected_hash:
        raise ReidError("提供的哈希与登记哈希一致，不构成不一致")
    _open_review(db, obs, "hash_mismatch",
                 {"observation_id": obs.id, "registered_hash": obs.file_hash,
                  "expected_hash": expected_hash}, actor)
    return obs


def revise_location(
    db: Session, observation_id: int, *, location_version_id: int,
    latitude: float, longitude: float, actor: str,
) -> ReidObservation:
    obs = db.get(ReidObservation, observation_id)
    if obs is None:
        raise ReidError("观察不存在", 404)
    version = db.get(ReidLocationVersion, location_version_id)
    if version is None:
        raise ReidError("位置版本不存在", 404)
    obs.location_version_id = version.id
    obs.latitude, obs.longitude = latitude, longitude
    obs.survey_date = local_date(effective_time(obs))
    db.flush()
    # 重算相关候选的可达性证据，但不改变候选/个体状态。
    for cand in db.execute(
        select(ReidCandidate).where(
            (ReidCandidate.observation_a_id == obs.id) | (ReidCandidate.observation_b_id == obs.id)
        )
    ).scalars():
        other_id = cand.observation_b_id if cand.observation_a_id == obs.id else cand.observation_a_id
        other = db.get(ReidObservation, other_id)
        reach = reachability(db, obs, other, correction_max_speed(db, obs.season_code))
        cand.evidence = {**(cand.evidence or {}), "reachability_after_location_revision": reach}
        cand.spatial_reachable = reach["reachable"]
    db.flush()
    _open_review(db, obs, "location_revision",
                 {"observation_id": obs.id, "location_version_id": version.id,
                  "new_lat": latitude, "new_lon": longitude}, actor)
    return obs


def resolve_review(
    db: Session, review_event_id: int, *, outcome: str, reason: str, actor: str,
    groups: list[list[int]] | None = None,
) -> ReidReviewEvent:
    if outcome not in ("keep", "revise", "revoke"):
        raise ReidError("复审结论必须是 keep/revise/revoke")
    event = db.get(ReidReviewEvent, review_event_id)
    if event is None:
        raise ReidError("复审事件不存在", 404)
    if event.status != "opened":
        raise ReidError("该复审已关闭", 409)
    individual = db.get(ReidIndividual, event.individual_id)
    version = db.get(ReidIndividualVersion, event.individual_version_id)

    if outcome == "keep":
        individual.status = INDIVIDUAL_ACTIVE
        version.status = VERSION_CURRENT
        event.status = "resolved_keep"
    elif outcome == "revoke":
        individual.status = INDIVIDUAL_REVOKED
        version.status = VERSION_REVOKED
        event.status = "resolved_revoke"
    else:
        if not groups:
            raise ReidError("修订关系需要提供新的观察分组", 422)
        event.status = "resolved_revise"
        db.flush()
        split_individual(db, individual.id, groups=groups, reason=f"复审修订：{reason}", actor=actor)
        event.resolved_by = actor
        event.resolved_at = utcnow()
        event.resolution = reason
        db.flush()
        _audit(db, "reid_review_event", event.id, "reid.review.resolved", actor,
               {"outcome": outcome})
        return event

    event.resolved_by = actor
    event.resolved_at = utcnow()
    event.resolution = reason
    db.flush()
    refresh_latest_report_run(db, individual.season_code, individual.species_code, actor)
    _audit(db, "reid_review_event", event.id, "reid.review.resolved", actor, {"outcome": outcome})
    return event


# ---------------------------------------------------------------------------
# 样线统计账（季报运行）
# ---------------------------------------------------------------------------
def _season_window(db: Session, season_code: str) -> tuple[date, date] | None:
    rv = db.execute(
        select(RulebookVersion)
        .where(RulebookVersion.season_code == season_code)
        .where(RulebookVersion.status == "active")
        .order_by(RulebookVersion.id.desc())
    ).scalars().first()
    if rv is None:
        return None
    return rv.season_start, rv.season_end


def _report_context(db: Session, season_code: str, species_code: str) -> dict:
    observations = list(
        db.execute(
            select(ReidObservation).where(
                ReidObservation.season_code == season_code,
                ReidObservation.species_code == species_code,
            ).order_by(ReidObservation.id)
        ).scalars()
    )
    individuals = list(
        db.execute(
            select(ReidIndividual).where(
                ReidIndividual.season_code == season_code,
                ReidIndividual.species_code == species_code,
            )
        ).scalars()
    )
    version_by_individual = {
        i.id: db.get(ReidIndividualVersion, i.current_version_id) for i in individuals
    }
    owner_by_obs: dict[int, int] = {}
    for individual in individuals:
        version = version_by_individual[individual.id]
        if version and version.status in (VERSION_CURRENT, VERSION_UNDER_REVIEW):
            for obs_id in version.observation_ids:
                owner_by_obs[obs_id] = individual.id
    candidate_by_obs: dict[int, list[ReidCandidate]] = {}
    for cand in db.execute(select(ReidCandidate)).scalars():
        candidate_by_obs.setdefault(cand.observation_a_id, []).append(cand)
        candidate_by_obs.setdefault(cand.observation_b_id, []).append(cand)
    open_holds: set[int] = set()
    for hold in db.execute(
        select(ReidMembershipHold).where(ReidMembershipHold.status == "open")
    ).scalars():
        # 冻结覆盖候选对两端，避免争议照片在任一个体上贡献重复捕获。
        cand = db.get(ReidCandidate, hold.candidate_id)
        if cand is not None:
            open_holds.add(cand.observation_a_id)
            open_holds.add(cand.observation_b_id)
    return {
        "observations": observations,
        "window": _season_window(db, season_code),
        "individuals": individuals,
        "version_by_individual": version_by_individual,
        "owner_by_obs": owner_by_obs,
        "candidate_by_obs": candidate_by_obs,
        "open_holds": open_holds,
    }


def _classify_capture(db: Session, obs: ReidObservation, ctx: dict) -> tuple[str, str, str, ReidIndividual | None, ReidIndividualVersion | None]:
    """确定性分类：同一口径在任何季报运行上结果一致，保证无关样线不被牵连。"""
    individual_id = ctx["owner_by_obs"].get(obs.id)
    individual = db.get(ReidIndividual, individual_id) if individual_id else None
    version = ctx["version_by_individual"].get(individual_id) if individual_id else None
    station = db.get(Station, obs.station_id)
    window = ctx["window"]
    in_season = True
    if window:
        in_season = window[0] <= (obs.survey_date or local_date(effective_time(obs))) <= window[1]
    if obs.interpretability == "unreadable":
        return "excluded_unreadable", "excluded", "无法判读观察，不纳入统计", individual, version
    if obs.id in ctx["open_holds"]:
        return "frozen", "excluded", "观察归属存在竞争，重复捕获已冻结", individual, version
    if individual is None or individual.status in (INDIVIDUAL_SPLIT, INDIVIDUAL_MERGED, INDIVIDUAL_REVOKED):
        related = ctx["candidate_by_obs"].get(obs.id, [])
        if any(c.status == CANDIDATE_REJECTED for c in related):
            return "excluded_rejected", "excluded", "涉及被否决的同一个体关系", individual, version
        return "excluded_pending", "excluded", "仅存在候选关系，未经专家确认", individual, version
    if individual.status == INDIVIDUAL_UNDER_REVIEW or (version and version.status == VERSION_UNDER_REVIEW):
        return "excluded_review", "excluded", "关键素材变动，个体版本复审中，新统计暂停纳入", individual, version
    if not in_season or station.status != "active":
        return "excluded_season", "excluded", "校时后跨越调查规则季节窗口（观察保留于档案）", individual, version
    return "included", "repeat", "", individual, version


def _write_report_run(
    db: Session, *, season_code: str, species_code: str, actor: str,
    supersedes: ReidReportRun | None, change_note: str,
) -> ReidReportRun:
    ctx = _report_context(db, season_code, species_code)
    count = db.execute(select(func.count()).select_from(ReidReportRun)).scalar_one()
    run = ReidReportRun(
        report_code=f"RPT-{season_code}-{species_code}-{count + 1:03d}",
        season_code=season_code,
        species_code=species_code,
        status="frozen",
        created_by=actor,
    )
    db.add(run)
    db.flush()

    seen_cluster_keys: set[tuple] = set()
    first_done: set[int] = set()
    sequence = 0
    buckets: dict[str, int] = {}
    for obs in sorted(ctx["observations"], key=lambda o: (effective_time(o), o.id)):
        status, kind, reason, individual, version = _classify_capture(db, obs, ctx)
        individual_id = individual.id if individual else None
        if status == "included":
            cluster_key = (individual_id, obs.station_id, obs.survey_date, obs.source_cluster_id)
            if obs.source_cluster_id and cluster_key in seen_cluster_keys:
                status, kind, reason = (
                    "excluded_duplicate_cluster", "excluded",
                    "同一来源簇在同一样线—日期的重复素材",
                )
            else:
                if obs.source_cluster_id:
                    seen_cluster_keys.add(cluster_key)
                sequence += 1
                kind = "first" if individual_id not in first_done else "repeat"
                first_done.add(individual_id)
        buckets[status] = buckets.get(status, 0) + 1
        db.add(
            ReidCaptureEntry(
                report_run_id=run.id,
                individual_id=individual_id,
                individual_version_id=version.id if version else None,
                observation_id=obs.id,
                source_cluster_id=obs.source_cluster_id,
                station_id=obs.station_id,
                survey_date=obs.survey_date or local_date(effective_time(obs)),
                season_code=season_code,
                capture_kind=kind,
                sequence_no=sequence if status == "included" else 0,
                status=status,
                exclusion_reason=reason,
            )
        )
    db.flush()

    included_entries = list(db.execute(
        select(ReidCaptureEntry).where(
            ReidCaptureEntry.report_run_id == run.id,
            ReidCaptureEntry.status == "included",
        )
    ).scalars())
    candidate_status_counts = dict(
        db.execute(
            select(ReidCandidate.status, func.count())
            .join(ReidObservation, ReidObservation.id == ReidCandidate.observation_a_id)
            .where(ReidObservation.season_code == season_code,
                   ReidObservation.species_code == species_code)
            .group_by(ReidCandidate.status)
        ).all()
    )
    window = ctx["window"]
    run.summary = {
        "photo_observation_count": len(ctx["observations"]),
        "candidate_count": sum(candidate_status_counts.values()),
        "candidate_status_counts": candidate_status_counts,
        "statistical_individual_count": len({e.individual_id for e in included_entries}),
        "first_capture_count": sum(1 for e in included_entries if e.capture_kind == "first"),
        "repeat_capture_count": sum(1 for e in included_entries if e.capture_kind == "repeat"),
        "exclusion_buckets": buckets,
        "season_window": [window[0].isoformat(), window[1].isoformat()] if window else None,
        "supersedes_report_run_id": supersedes.id if supersedes else None,
        "change_note": change_note,
        "note": "照片数、候选数与统计个体数分别统计，互不混同；季报运行一经冻结不再改写，重算生成新运行。",
    }
    if supersedes is not None:
        supersedes.status = "superseded"
        supersedes.superseded_by_id = run.id
    db.flush()
    _audit(db, "reid_report_run", run.id, "reid.report.built", actor,
           {**run.summary, "predecessor": supersedes.id if supersedes else None})
    return run


def build_report_run(db: Session, *, season_code: str, species_code: str, actor: str) -> ReidReportRun:
    return _write_report_run(
        db, season_code=season_code, species_code=species_code, actor=actor,
        supersedes=None, change_note="首次冻结样线统计账",
    )


def refresh_latest_report_run(db: Session, season_code: str, species_code: str, actor: str) -> ReidReportRun | None:
    """个体变化后生成新的冻结季报；历史季报保持原样可还原，无关样线按同一确定性口径重算。"""
    # 划分整体采用等复合动作期间挂起逐条刷新，末尾统一重算为一个冻结季报。
    if getattr(db, "_reid_suspend_report", False):
        return None
    latest = db.execute(
        select(ReidReportRun)
        .where(ReidReportRun.season_code == season_code, ReidReportRun.species_code == species_code)
        .order_by(ReidReportRun.id.desc())
    ).scalars().first()
    if latest is None:
        return None
    return _write_report_run(
        db, season_code=season_code, species_code=species_code, actor=actor,
        supersedes=latest, change_note=f"个体归属/裁定/复审变化后的重算（由 {actor} 触发）",
    )


# ---------------------------------------------------------------------------
# 溯源
# ---------------------------------------------------------------------------
def observation_trace(db: Session, observation_id: int) -> dict:
    obs = db.get(ReidObservation, observation_id)
    if obs is None:
        raise ReidError("观察不存在", 404)
    candidates = list(
        db.execute(
            select(ReidCandidate).where(
                (ReidCandidate.observation_a_id == obs.id)
                | (ReidCandidate.observation_b_id == obs.id)
            ).order_by(ReidCandidate.id)
        ).scalars()
    )
    decisions = list(
        db.execute(
            select(ReidDecision)
            .where(ReidDecision.candidate_id.in_([c.id for c in candidates] or [-1]))
            .order_by(ReidDecision.id)
        ).scalars()
    )
    versions = list(
        db.execute(
            select(ReidIndividualVersion)
            .where(ReidIndividualVersion.observation_ids.contains([obs.id]))
            .order_by(ReidIndividualVersion.id)
        ).scalars()
    )
    entries = list(
        db.execute(
            select(ReidCaptureEntry).where(ReidCaptureEntry.observation_id == obs.id)
            .order_by(ReidCaptureEntry.id)
        ).scalars()
    )
    reviews = list(
        db.execute(
            select(ReidReviewEvent)
            .where(ReidReviewEvent.trigger_detail.contains({"observation_id": obs.id}))
        ).scalars()
    )
    holds = list(
        db.execute(
            select(ReidMembershipHold).where(
                (ReidMembershipHold.observation_id == obs.id)
            )
        ).scalars()
    )
    cluster_siblings = []
    if obs.source_cluster_id:
        cluster_siblings = list(
            db.execute(
                select(ReidObservation).where(
                    ReidObservation.source_cluster_id == obs.source_cluster_id,
                    ReidObservation.id != obs.id,
                )
            ).scalars()
        )
    return {
        "observation": obs,
        "source_cluster": db.get(ReidSourceCluster, obs.source_cluster_id) if obs.source_cluster_id else None,
        "source_cluster_siblings": cluster_siblings,
        "candidates": candidates,
        "decisions": decisions,
        "individual_versions": versions,
        "capture_entries": entries,
        "review_events": reviews,
        "membership_holds": holds,
    }


def report_run_trace(db: Session, run_id: int) -> dict:
    """从季报中的一个个体数量回到完整证据链。"""
    run = db.get(ReidReportRun, run_id)
    if run is None:
        raise ReidError("季报运行不存在", 404)
    entries = list(
        db.execute(
            select(ReidCaptureEntry)
            .where(ReidCaptureEntry.report_run_id == run.id)
            .order_by(ReidCaptureEntry.sequence_no, ReidCaptureEntry.id)
        ).scalars()
    )
    individual_ids = sorted({e.individual_id for e in entries if e.individual_id})
    individuals = [db.get(ReidIndividual, i) for i in individual_ids if i]
    versions = [db.get(ReidIndividualVersion, i.current_version_id) for i in individuals if i.current_version_id]
    obs_ids = sorted({e.observation_id for e in entries})
    candidates = list(
        db.execute(
            select(ReidCandidate).where(
                ReidCandidate.observation_a_id.in_(obs_ids or [-1]),
                ReidCandidate.observation_b_id.in_(obs_ids or [-1]),
            )
        ).scalars()
    )
    decisions = list(
        db.execute(
            select(ReidDecision)
            .where(ReidDecision.candidate_id.in_([c.id for c in candidates] or [-1]))
        ).scalars()
    )
    reviews = list(
        db.execute(
            select(ReidReviewEvent).where(
                ReidReviewEvent.individual_id.in_(individual_ids or [-1])
            )
        ).scalars()
    )
    return {
        "run": run,
        "entries": entries,
        "individuals": individuals,
        "individual_versions": versions,
        "observations": _load_observations(db, obs_ids),
        "candidates": candidates,
        "decisions": decisions,
        "review_events": reviews,
    }
