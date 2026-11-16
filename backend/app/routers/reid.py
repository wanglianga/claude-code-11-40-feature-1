"""野生动物个体重识别证据链 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    User,
    ReidAdjudication,
    ReidBatch,
    ReidCandidate,
    ReidFeatureExtractionVersion,
    ReidIndividual,
    ReidLocationVersion,
    ReidMembershipHold,
    ReidObservation,
    ReidReportRun,
    ReidReviewEvent,
    ReidSourceCluster,
    ReidTimeCorrectionVersion,
)
from ..reid import (
    ReidError,
    adopt_partition,
    apply_time_correction,
    build_report_run,
    decide_candidate,
    create_batch,
    flag_hash_mismatch,
    register_feature_version,
    register_location_version,
    register_time_correction,
    register_observation,
    report_run_trace,
    observation_trace,
    resolve_adjudication,
    resolve_review,
    revise_location,
    split_individual,
    withdraw_authorization,
)
from ..reid_serializers import (
    adjudication_out,
    batch_out,
    candidate_out,
    capture_entry_out,
    decision_out,
    feature_version_out,
    hold_out,
    individual_out,
    location_version_out,
    observation_out,
    partition_out,
    report_run_out,
    review_event_out,
    source_cluster_out,
    time_correction_out,
)
from ..schemas import (
    AdjudicationResolveIn,
    BatchIn,
    CalibrationApplyIn,
    DecisionIn,
    FeatureVersionIn,
    HashMismatchIn,
    LocationRevisionIn,
    LocationVersionIn,
    ObservationIn,
    PartitionAdoptIn,
    ReportRunIn,
    ReviewResolveIn,
    SplitIn,
    TimeCorrectionIn,
    WithdrawIn,
)
from ..security import get_current_user, require_roles

router = APIRouter(prefix="/reid", tags=["re-identification"])

_WRITER = require_roles("researcher", "auditor")


def _fail(exc: ReidError) -> HTTPException:
    return HTTPException(exc.status_code, exc.message)


# ----------------------------------------------------------- 版本登记
@router.post("/feature-versions")
def create_feature_version(data: FeatureVersionIn, db: Session = Depends(get_db), user: User = Depends(_WRITER)):
    try:
        row = register_feature_version(
            db, code=data.code, version=data.version,
            feature_names=data.feature_names, notes=data.notes,
        )
        db.commit()
    except ReidError as exc:
        db.rollback()
        raise _fail(exc) from exc
    return feature_version_out(row)


@router.get("/feature-versions")
def list_feature_versions(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = db.execute(select(ReidFeatureExtractionVersion).order_by(ReidFeatureExtractionVersion.id)).scalars()
    return [feature_version_out(r) for r in rows]


@router.post("/location-versions")
def create_location_version(data: LocationVersionIn, db: Session = Depends(get_db), user: User = Depends(_WRITER)):
    try:
        row = register_location_version(
            db, code=data.code, version=data.version, change_reason=data.change_reason
        )
        db.commit()
    except ReidError as exc:
        db.rollback()
        raise _fail(exc) from exc
    return location_version_out(row)


@router.get("/location-versions")
def list_location_versions(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = db.execute(select(ReidLocationVersion).order_by(ReidLocationVersion.id)).scalars()
    return [location_version_out(r) for r in rows]


@router.post("/time-corrections")
def create_time_correction(data: TimeCorrectionIn, db: Session = Depends(get_db), user: User = Depends(_WRITER)):
    try:
        row = register_time_correction(
            db, code=data.code, version=data.version, target_device=data.target_device,
            offset_seconds=data.offset_seconds, valid_from=data.valid_from,
            valid_to=data.valid_to, verified=data.verified, basis=data.basis,
        )
        db.commit()
    except ReidError as exc:
        db.rollback()
        raise _fail(exc) from exc
    return time_correction_out(row)


@router.get("/time-corrections")
def list_time_corrections(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = db.execute(select(ReidTimeCorrectionVersion).order_by(ReidTimeCorrectionVersion.id)).scalars()
    return [time_correction_out(r) for r in rows]


# ----------------------------------------------------------- 来源簇
@router.get("/source-clusters")
def list_clusters(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = db.execute(select(ReidSourceCluster).order_by(ReidSourceCluster.id)).scalars()
    result = []
    for cluster in rows:
        data = source_cluster_out(cluster)
        data["member_count"] = db.execute(
            select(func.count()).select_from(ReidObservation).where(
                ReidObservation.source_cluster_id == cluster.id
            )
        ).scalar_one()
        result.append(data)
    return result


# ----------------------------------------------------------- 观察
@router.post("/observations")
def create_observation(data: ObservationIn, db: Session = Depends(get_db), user: User = Depends(_WRITER)):
    try:
        obs = register_observation(db, data.model_dump(), user.username)
        db.commit()
    except ReidError as exc:
        db.rollback()
        raise _fail(exc) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, f"时间格式无效：{exc}") from exc
    return observation_out(db, obs, include_relations=True)


@router.get("/observations")
def list_observations(
    season_code: str | None = None,
    species_code: str | None = None,
    station_id: int | None = None,
    interpretability: str | None = None,
    authorization_status: str | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = select(ReidObservation)
    if season_code:
        q = q.where(ReidObservation.season_code == season_code)
    if species_code:
        q = q.where(ReidObservation.species_code == species_code)
    if station_id:
        q = q.where(ReidObservation.station_id == station_id)
    if interpretability:
        q = q.where(ReidObservation.interpretability == interpretability)
    if authorization_status:
        q = q.where(ReidObservation.authorization_status == authorization_status)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = list(
        db.execute(q.order_by(ReidObservation.observed_at.desc()).offset(offset).limit(limit)).scalars()
    )
    return {"total": total, "items": [observation_out(db, o, include_relations=True) for o in rows]}


@router.get("/observations/{observation_id}")
def get_observation(observation_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    obs = db.get(ReidObservation, observation_id)
    if obs is None:
        raise HTTPException(404, "观察不存在")
    return observation_out(db, obs, include_relations=True)


@router.post("/observations/{observation_id}/time-correction")
def calibrate_observation(
    observation_id: int, data: CalibrationApplyIn,
    db: Session = Depends(get_db), user: User = Depends(_WRITER),
):
    try:
        obs = apply_time_correction(db, observation_id, data.time_correction_id, user.username)
        db.commit()
    except ReidError as exc:
        db.rollback()
        raise _fail(exc) from exc
    return observation_out(db, obs, include_relations=True)


@router.post("/observations/{observation_id}/withdraw")
def withdraw(
    observation_id: int, data: WithdrawIn,
    db: Session = Depends(get_db), user: User = Depends(_WRITER),
):
    try:
        obs = withdraw_authorization(db, observation_id, data.reason, user.username)
        db.commit()
    except ReidError as exc:
        db.rollback()
        raise _fail(exc) from exc
    return observation_out(db, obs, include_relations=True)


@router.post("/observations/{observation_id}/hash-mismatch")
def hash_mismatch(
    observation_id: int, data: HashMismatchIn,
    db: Session = Depends(get_db), user: User = Depends(_WRITER),
):
    try:
        obs = flag_hash_mismatch(db, observation_id, data.expected_hash, user.username)
        db.commit()
    except ReidError as exc:
        db.rollback()
        raise _fail(exc) from exc
    return observation_out(db, obs, include_relations=True)


@router.post("/observations/{observation_id}/location-revision")
def location_revision(
    observation_id: int, data: LocationRevisionIn,
    db: Session = Depends(get_db), user: User = Depends(_WRITER),
):
    try:
        obs = revise_location(
            db, observation_id, location_version_id=data.location_version_id,
            latitude=data.latitude, longitude=data.longitude, actor=user.username,
        )
        db.commit()
    except ReidError as exc:
        db.rollback()
        raise _fail(exc) from exc
    return observation_out(db, obs, include_relations=True)


@router.get("/observations/{observation_id}/trace")
def get_observation_trace(observation_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    try:
        trace = observation_trace(db, observation_id)
    except ReidError as exc:
        raise _fail(exc) from exc
    return {
        "observation": observation_out(db, trace["observation"], include_relations=True),
        "source_cluster": source_cluster_out(trace["source_cluster"]) if trace["source_cluster"] else None,
        "source_cluster_siblings": [
            observation_out(db, o) for o in trace["source_cluster_siblings"]
        ],
        "candidates": [candidate_out(db, c) for c in trace["candidates"]],
        "decisions": [decision_out(d) for d in trace["decisions"]],
        "individual_versions": [
            {
                "id": v.id, "individual_id": v.individual_id,
                "version_number": v.version_number, "status": v.status,
                "frozen_versions": v.frozen_versions, "change_reason": v.change_reason,
            }
            for v in trace["individual_versions"]
        ],
        "capture_entries": [capture_entry_out(db, e) for e in trace["capture_entries"]],
        "review_events": [review_event_out(e) for e in trace["review_events"]],
        "membership_holds": [hold_out(h) for h in trace["membership_holds"]],
    }


# ----------------------------------------------------------- 批次与候选
@router.post("/batches")
def create_reid_batch(data: BatchIn, db: Session = Depends(get_db), user: User = Depends(_WRITER)):
    try:
        batch = create_batch(
            db, season_code=data.season_code, species_code=data.species_code,
            observation_ids=data.observation_ids,
            max_travel_speed_kmh=data.max_travel_speed_kmh,
            feature_threshold=data.feature_threshold,
            pair_search_limit=data.pair_search_limit,
            partition_limit=data.partition_limit,
            actor=user.username,
        )
        db.commit()
    except ReidError as exc:
        db.rollback()
        raise _fail(exc) from exc
    return batch_out(db, batch, include_candidates=True)


@router.get("/batches")
def list_batches(season_code: str | None = None, db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = select(ReidBatch)
    if season_code:
        q = q.where(ReidBatch.season_code == season_code)
    rows = db.execute(q.order_by(ReidBatch.id.desc())).scalars()
    return [batch_out(db, b) for b in rows]


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    batch = db.get(ReidBatch, batch_id)
    if batch is None:
        raise HTTPException(404, "批次不存在")
    return batch_out(db, batch, include_candidates=True)


@router.get("/candidates")
def list_candidates(
    status: str | None = None,
    batch_id: int | None = None,
    observation_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = select(ReidCandidate)
    if status:
        q = q.where(ReidCandidate.status == status)
    if batch_id:
        q = q.where(ReidCandidate.batch_id == batch_id)
    if observation_id:
        q = q.where(
            (ReidCandidate.observation_a_id == observation_id)
            | (ReidCandidate.observation_b_id == observation_id)
        )
    rows = db.execute(q.order_by(ReidCandidate.id.desc())).scalars()
    return [candidate_out(db, c) for c in rows]


@router.get("/candidates/{candidate_id}")
def get_candidate(candidate_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    cand = db.get(ReidCandidate, candidate_id)
    if cand is None:
        raise HTTPException(404, "候选关系不存在")
    return candidate_out(db, cand)


@router.post("/candidates/{candidate_id}/decisions")
def make_decision(
    candidate_id: int, data: DecisionIn,
    db: Session = Depends(get_db), user: User = Depends(_WRITER),
):
    try:
        decision = decide_candidate(
            db, candidate_id, verdict=data.verdict, reason=data.reason,
            expert=user.username, expected_last_decision_id=data.expected_last_decision_id,
            partition_id=data.partition_id,
        )
        db.commit()
    except ReidError as exc:
        db.rollback()
        raise _fail(exc) from exc
    cand = db.get(ReidCandidate, candidate_id)
    return {"decision": decision_out(decision), "candidate": candidate_out(db, cand)}


@router.post("/partitions/{partition_id}/adopt")
def adopt(
    partition_id: int, data: PartitionAdoptIn,
    db: Session = Depends(get_db), user: User = Depends(_WRITER),
):
    try:
        partition = adopt_partition(db, partition_id, expert=user.username, reason=data.reason)
        db.commit()
    except ReidError as exc:
        db.rollback()
        raise _fail(exc) from exc
    return partition_out(partition)


# ----------------------------------------------------------- 确认个体
@router.get("/individuals")
def list_individuals(
    season_code: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = select(ReidIndividual)
    if season_code:
        q = q.where(ReidIndividual.season_code == season_code)
    if status:
        q = q.where(ReidIndividual.status == status)
    rows = db.execute(q.order_by(ReidIndividual.id)).scalars()
    return [individual_out(db, i) for i in rows]


@router.get("/individuals/{individual_id}")
def get_individual(individual_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    individual = db.get(ReidIndividual, individual_id)
    if individual is None:
        raise HTTPException(404, "确认个体不存在")
    return individual_out(db, individual, include_versions=True)


@router.post("/individuals/{individual_id}/split")
def split(
    individual_id: int, data: SplitIn,
    db: Session = Depends(get_db), user: User = Depends(_WRITER),
):
    try:
        children = split_individual(
            db, individual_id, groups=data.groups, reason=data.reason, actor=user.username
        )
        db.commit()
    except ReidError as exc:
        db.rollback()
        raise _fail(exc) from exc
    return {"children": [individual_out(db, i, include_versions=True) for i in children]}


# ----------------------------------------------------------- 裁定待定 / 复审 / 冻结
@router.get("/adjudications")
def list_adjudications(status: str | None = None, db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = select(ReidAdjudication)
    if status:
        q = q.where(ReidAdjudication.status == status)
    rows = db.execute(q.order_by(ReidAdjudication.id.desc())).scalars()
    return [adjudication_out(a) for a in rows]


@router.post("/adjudications/{adjudication_id}/resolve")
def resolve_adjudication_endpoint(
    adjudication_id: int, data: AdjudicationResolveIn,
    db: Session = Depends(get_db), user: User = Depends(_WRITER),
):
    try:
        adj = resolve_adjudication(
            db, adjudication_id, final_verdict=data.final_verdict, reason=data.reason,
            expert=user.username, third_party_evidence=data.third_party_evidence,
        )
        db.commit()
    except ReidError as exc:
        db.rollback()
        raise _fail(exc) from exc
    return adjudication_out(adj)


@router.get("/reviews")
def list_reviews(status: str | None = None, db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = select(ReidReviewEvent)
    if status:
        q = q.where(ReidReviewEvent.status == status)
    rows = db.execute(q.order_by(ReidReviewEvent.id.desc())).scalars()
    return [review_event_out(e) for e in rows]


@router.post("/reviews/{review_id}/resolve")
def resolve_review_endpoint(
    review_id: int, data: ReviewResolveIn,
    db: Session = Depends(get_db), user: User = Depends(_WRITER),
):
    try:
        event = resolve_review(
            db, review_id, outcome=data.outcome, reason=data.reason,
            actor=user.username, groups=data.groups,
        )
        db.commit()
    except ReidError as exc:
        db.rollback()
        raise _fail(exc) from exc
    return review_event_out(event)


@router.get("/membership-holds")
def list_holds(status: str | None = None, db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = select(ReidMembershipHold)
    if status:
        q = q.where(ReidMembershipHold.status == status)
    rows = db.execute(q.order_by(ReidMembershipHold.id.desc())).scalars()
    return [hold_out(h) for h in rows]


# ----------------------------------------------------------- 样线统计账
@router.post("/report-runs")
def create_report_run(data: ReportRunIn, db: Session = Depends(get_db), user: User = Depends(_WRITER)):
    try:
        run = build_report_run(
            db, season_code=data.season_code, species_code=data.species_code, actor=user.username
        )
        db.commit()
    except ReidError as exc:
        db.rollback()
        raise _fail(exc) from exc
    return report_run_out(db, run, include_entries=True)


@router.get("/report-runs")
def list_report_runs(
    season_code: str | None = None,
    species_code: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = select(ReidReportRun)
    if season_code:
        q = q.where(ReidReportRun.season_code == season_code)
    if species_code:
        q = q.where(ReidReportRun.species_code == species_code)
    rows = db.execute(q.order_by(ReidReportRun.id.desc())).scalars()
    return [report_run_out(db, r) for r in rows]


@router.get("/report-runs/{run_id}")
def get_report_run(run_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    run = db.get(ReidReportRun, run_id)
    if run is None:
        raise HTTPException(404, "季报运行不存在")
    return report_run_out(db, run, include_entries=True)


@router.get("/report-runs/{run_id}/trace")
def get_report_trace(run_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    try:
        trace = report_run_trace(db, run_id)
    except ReidError as exc:
        raise _fail(exc) from exc
    return {
        "run": report_run_out(db, trace["run"]),
        "entries": [capture_entry_out(db, e) for e in trace["entries"]],
        "individuals": [individual_out(db, i, include_versions=True) for i in trace["individuals"]],
        "individual_versions": [
            {
                "id": v.id, "individual_id": v.individual_id,
                "version_number": v.version_number, "status": v.status,
                "observation_ids": v.observation_ids,
                "source_cluster_ids": v.source_cluster_ids,
                "frozen_versions": v.frozen_versions,
                "change_reason": v.change_reason,
            }
            for v in trace["individual_versions"]
        ],
        "observations": [observation_out(db, o) for o in trace["observations"]],
        "candidates": [candidate_out(db, c) for c in trace["candidates"]],
        "decisions": [decision_out(d) for d in trace["decisions"]],
        "review_events": [review_event_out(e) for e in trace["review_events"]],
    }
