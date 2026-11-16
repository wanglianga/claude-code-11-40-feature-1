"""重识别证据链演示种子数据。

叙事（2026 春季，鹿类 CERVUS）：
  O1 青松岭 QSL-01 与 O2 北梁 QSL-02 是带同一道体侧伤痕的鹿，O3 是 O2 原图裁剪件；
  O4/O5 云溪沟同一只鹿的两次捕获；O10/O11 与 O12/O15 是两只不同鹿，
  但 O11-O12 特征相近形成跨个体竞争归属并被冻结；
  O8/O9 外观极像但时间窗内无法往返，被专家否决；O16 试图绕过否决约束；
  O17/O18 同时刻异地反证传递合并；O20/O21 两位同级专家结论相反，进入裁定待定；
  O6 无法判读、O7 无匹配、O13/O14 到校时后才进入可达窗口。
"""
from __future__ import annotations

from sqlalchemy import select

from .db import SessionLocal, init_db
from .models import ReidObservation, Station
from .reid import (
    apply_time_correction,
    build_report_run,
    create_batch,
    decide_candidate,
    register_feature_version,
    register_location_version,
    register_observation,
    register_time_correction,
)

SEASON = "2026-SPRING"
SPECIES = "CERVUS"


def _station(db, code: str) -> Station:
    return db.execute(select(Station).where(Station.code == code)).scalar_one()


def _obs_by_ref(db, external_ref: str) -> ReidObservation:
    return db.execute(
        select(ReidObservation).where(ReidObservation.external_ref == external_ref)
    ).scalar_one()


def _candidate_id(db, ref_a: str, ref_b: str) -> int:
    a, b = _obs_by_ref(db, ref_a), _obs_by_ref(db, ref_b)
    lo, hi = sorted((a.id, b.id))
    from .models import ReidCandidate

    return db.execute(
        select(ReidCandidate).where(
            ReidCandidate.observation_a_id == lo, ReidCandidate.observation_b_id == hi
        )
    ).scalar_one().id


def _add(db, *, station_code, external_ref, day, hour, minute, features,
         kind="photo", posture="good", posture_score=0.9, lat=None, lon=None,
         derived_from=None, burst_group=None, interpretability="interpretable",
         season=SEASON, species=SPECIES, file_hash=None, fv_id=None):
    station = _station(db, station_code)
    data = {
        "species_code": species,
        "observation_kind": kind,
        "external_ref": external_ref,
        "file_hash": file_hash or f"hash-{external_ref}",
        "station_id": station.id,
        "observed_at": f"2026-{day}T{hour:02d}:{minute:02d}:00+08:00",
        "received_time": f"2026-{day}T{hour:02d}:{minute:02d}:30+08:00",
        "latitude": lat,
        "longitude": lon,
        "posture_quality": posture,
        "posture_score": posture_score,
        "visible_features": features,
        "feature_version_id": fv_id,
        "derived_from_observation_id": derived_from,
        "burst_group": burst_group,
        "interpretability": interpretability,
        "season_code": season,
        "payload": {"import": "field-workflow-2026"},
    }
    return register_observation(db, data, actor="seed")


def seed_reid(db) -> None:
    fv = register_feature_version(
        db, code="FV-COAT-1", version="2026.04",
        feature_names=["stripe_pattern", "scar_marks", "coat_color"],
        notes="斑纹/伤痕集合特征 + 体色标量特征的首版提取口径",
    )
    register_location_version(
        db, code="LOC-V1", version="2026.04-v1", change_reason="春季调查初始相机坐标与样线归属"
    )
    tc_pending = register_time_correction(
        db, code="TC-CAM-QSL01-02", version="v1", target_device="CAM-QSL-01",
        offset_seconds=-1800.0, valid_from="2026-04-01T00:00:00+08:00",
        valid_to="2026-05-01T00:00:00+08:00", verified=True,
        basis="现场对时发现相机慢 30 分钟，真实时间=设备时间+1800s",
    )

    f = {
        "d1": {"stripe_pattern": ["sp-a1", "sp-a2"], "scar_marks": ["scar-left-flank"], "coat_color": "brown"},
        "d2": {"stripe_pattern": ["sp-b1"], "scar_marks": [], "coat_color": "dark"},
        "d3": {"stripe_pattern": ["sp-c1"], "scar_marks": ["scar-right-ear"], "coat_color": "brown"},
        "d4": {"stripe_pattern": ["sp-d4a", "sp-d4b"], "scar_marks": ["scar-left-leg"], "coat_color": "dark"},
        "far": {"stripe_pattern": ["sp-far"], "coat_color": "grey"},
        "chain": {"stripe_pattern": ["sp-chain"], "coat_color": "brown"},
        "dispute": {"stripe_pattern": ["sp-disp"], "scar_marks": ["scar-nose"], "coat_color": "brown"},
        "calib": {"stripe_pattern": ["sp-tc"], "coat_color": "reddish"},
    }

    # 伤鹿叙事：两条相邻样线的同一个体。
    _add(db, station_code="QSL-01", external_ref="DEER-QSL01-0410-A", day="04-10",
         hour=8, minute=0, features=f["d1"], fv_id=fv.id)
    o2 = _add(db, station_code="QSL-02", external_ref="DEER-QSL02-0411-A", day="04-11",
              hour=9, minute=0, features=f["d1"], fv_id=fv.id)
    _add(db, station_code="QSL-02", external_ref="DEER-QSL02-0411-A-CROP", day="04-11",
         hour=9, minute=0, features=f["d1"], derived_from=o2.id, fv_id=fv.id,
         file_hash="hash-DEER-QSL02-0411-A-CROP")

    # 云溪沟同一只鹿的首次/重复捕获。
    _add(db, station_code="YXG-01", external_ref="DEER-YXG01-0412-A", day="04-12",
         hour=7, minute=30, features=f["d2"], fv_id=fv.id)
    _add(db, station_code="YXG-01", external_ref="DEER-YXG01-0413-A", day="04-13",
         hour=7, minute=50, features=f["d2"], fv_id=fv.id)

    # 无法判读与无匹配观察。
    _add(db, station_code="BHP-01", external_ref="DEER-BHP01-BLUR", day="04-10",
         hour=18, minute=20, features={}, posture="poor", posture_score=0.1,
         interpretability="unreadable", fv_id=fv.id)
    _add(db, station_code="QSL-04", external_ref="DEER-QSL04-SOLO", day="04-12",
         hour=11, minute=0, features={"stripe_pattern": ["sp-solo"], "coat_color": "light"},
         fv_id=fv.id)

    # 外观极像但时空不可达的一对。
    _add(db, station_code="QSL-01", external_ref="DEER-QSL01-FAR", day="04-10",
         hour=8, minute=30, features=f["far"], fv_id=fv.id)
    _add(db, station_code="BHP-01", external_ref="DEER-BHP01-FAR", day="04-10",
         hour=9, minute=10, features=f["far"], fv_id=fv.id)

    # 竞争归属：O11 属 D3，O12 属 D4，但两者特征相近形成跨个体候选。
    _add(db, station_code="QSL-03", external_ref="DEER-QSL03-D3-1", day="04-11",
         hour=8, minute=0, features=f["d3"], fv_id=fv.id)
    _add(db, station_code="QSL-03", external_ref="DEER-QSL03-D3-2", day="04-12",
         hour=8, minute=10, features=f["d3"], fv_id=fv.id)
    _add(db, station_code="YXG-02", external_ref="DEER-YXG02-D4-1", day="04-13",
         hour=9, minute=0, features=f["d4"], fv_id=fv.id)
    _add(db, station_code="YXG-02", external_ref="DEER-YXG02-D4-2", day="04-14",
         hour=9, minute=20, features=f["d4"], fv_id=fv.id)

    # 传递一致性反证：O17/O18 可达，O19 与 O18 同时刻异地。
    _add(db, station_code="QSL-01", external_ref="DEER-CHAIN-1", day="04-10",
         hour=8, minute=0, features=f["chain"], lat=31.0500, lon=103.6200, fv_id=fv.id)
    _add(db, station_code="QSL-01", external_ref="DEER-CHAIN-2", day="04-10",
         hour=8, minute=45, features=f["chain"], lat=31.0620, lon=103.6350, fv_id=fv.id)
    _add(db, station_code="QSL-01", external_ref="DEER-CHAIN-3", day="04-10",
         hour=8, minute=45, features=f["chain"], lat=31.1200, lon=103.7000, fv_id=fv.id)

    # 绕过否决约束尝试用的桥接观察。
    _add(db, station_code="QSL-02", external_ref="DEER-BRIDGE-1", day="04-11",
         hour=15, minute=0, features=f["far"], fv_id=fv.id)

    # 同级相反裁定一对。
    _add(db, station_code="BHP-02", external_ref="DEER-DISP-1", day="04-12",
         hour=10, minute=0, features=f["dispute"], fv_id=fv.id)
    _add(db, station_code="BHP-02", external_ref="DEER-DISP-2", day="04-13",
         hour=10, minute=20, features=f["dispute"], fv_id=fv.id)

    # 校时叙事：O13 已在档，O14 后送达，校时前不在可达窗口。
    _add(db, station_code="QSL-01", external_ref="DEER-TC-1", day="04-10",
         hour=8, minute=0, features=f["calib"], fv_id=fv.id)

    # 连拍序列：同一 burst 的两张照片只能作为同一来源簇。
    _add(db, station_code="YXG-03", external_ref="DEER-BURST-1", day="04-11",
         hour=6, minute=0, features={"stripe_pattern": ["sp-burst"], "coat_color": "dark"},
         burst_group="BURST-YXG03-0411", fv_id=fv.id)
    _add(db, station_code="YXG-03", external_ref="DEER-BURST-2", day="04-11",
         hour=6, minute=0, features={"stripe_pattern": ["sp-burst"], "coat_color": "dark"},
         burst_group="BURST-YXG03-0411", fv_id=fv.id)

    db.flush()

    # 批次内联合候选 + 联合划分。
    create_batch(
        db, season_code=SEASON, species_code=SPECIES, observation_ids=None,
        max_travel_speed_kmh=3.0, feature_threshold=0.35,
        pair_search_limit=500, partition_limit=4, actor="seed",
    )

    # 专家逐对裁定。
    decide_candidate(db, _candidate_id(db, "DEER-QSL01-0410-A", "DEER-QSL02-0411-A"),
                     verdict="confirm", reason="体侧伤痕位置与斑纹组合一致，跨样线时空可达",
                     expert="yq.li")
    decide_candidate(db, _candidate_id(db, "DEER-YXG01-0412-A", "DEER-YXG01-0413-A"),
                     verdict="confirm", reason="云溪沟同一点位重复捕获，斑纹连续",
                     expert="yq.li")
    decide_candidate(db, _candidate_id(db, "DEER-QSL03-D3-1", "DEER-QSL03-D3-2"),
                     verdict="confirm", reason="QSL-03 两张照片耳缘伤痕一致",
                     expert="yq.li")
    decide_candidate(db, _candidate_id(db, "DEER-YXG02-D4-1", "DEER-YXG02-D4-2"),
                     verdict="confirm", reason="YXG-02 两张照片体色与斑纹一致",
                     expert="yq.li")
    far_pair = _candidate_id(db, "DEER-QSL01-FAR", "DEER-BHP01-FAR")
    decide_candidate(db, far_pair, verdict="reject",
                     reason="40 分钟内相距约 11 公里，超过鹿类最大移动速度，反证成立",
                     expert="m.cao")
    decide_candidate(db, _candidate_id(db, "DEER-CHAIN-1", "DEER-CHAIN-2"),
                     verdict="confirm", reason="45 分钟 2 公里，时空可达且斑纹一致",
                     expert="yq.li")

    # 校时后送达的 O14：先登记，校时前无候选；应用校时后系统只新建候选不自动合并。
    o14 = _add(db, station_code="QSL-02", external_ref="DEER-TC-2", day="04-10",
               hour=8, minute=40, features=f["calib"], fv_id=fv.id)
    apply_time_correction(db, o14.id, tc_pending.id, actor="seed")

    # 首版样线统计账（冻结基线季报）。
    build_report_run(db, season_code=SEASON, species_code=SPECIES, actor="yq.li")
    db.flush()


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        if db.execute(select(ReidObservation)).scalars().first():
            print("reid seed: data already present, skipping")
            return
        seed_reid(db)
        db.commit()
        print("reid seed: observations, candidates, decisions and baseline report created")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
