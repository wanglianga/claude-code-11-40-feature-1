"""野生动物个体重识别证据链验收测试。

测试在会话级种子库上顺序执行，每个场景使用独立特征标记避免相互污染；
基线季报 RPT-...-001 一经冻结，后续场景反复验证其不可变。
"""
from __future__ import annotations

SEASON = "2026-SPRING"
SPECIES = "CERVUS"


def _stations(client, auth):
    return {s["code"]: s["id"] for s in client.get("/api/stations", headers=auth).json()}


def _obs_by_ref(client, auth, ref):
    data = client.get("/api/reid/observations?limit=500", headers=auth).json()
    return next(o for o in data["items"] if o["external_ref"] == ref)


def _candidate_between(client, auth, obs_a_id, obs_b_id):
    for cand in client.get(
        f"/api/reid/candidates?observation_id={obs_a_id}", headers=auth
    ).json():
        if obs_b_id in (cand["observation_a_id"], cand["observation_b_id"]):
            return cand
    raise AssertionError("候选关系不存在")


def _latest_report(client, auth):
    summary = client.get("/api/reid/report-runs", headers=auth).json()[0]
    return client.get(f"/api/reid/report-runs/{summary['id']}", headers=auth).json()


def _baseline_report(client, auth):
    runs = client.get("/api/reid/report-runs", headers=auth).json()
    baseline = next(r for r in runs if r["report_code"].endswith("-001"))
    return client.get(f"/api/reid/report-runs/{baseline['id']}", headers=auth).json()


def _register(client, auth, stations, *, ref, station_code, day, hour, features,
              kind="photo", interpretability="interpretable", derived_from=None,
              burst_group=None, file_hash=None):
    body = {
        "species_code": SPECIES,
        "observation_kind": kind,
        "external_ref": ref,
        "file_hash": file_hash or f"hash-{ref}",
        "station_id": stations[station_code],
        "observed_at": f"2026-{day}T{hour:02d}:00:00+08:00",
        "received_time": f"2026-{day}T{hour:02d}:30:00+08:00",
        "posture_quality": "good",
        "posture_score": 0.9,
        "visible_features": features,
        "interpretability": interpretability,
        "season_code": SEASON,
        "payload": {"test": ref},
    }
    if derived_from is not None:
        body["derived_from_observation_id"] = derived_from
    if burst_group:
        body["burst_group"] = burst_group
    resp = client.post("/api/reid/observations", headers=auth, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _batch(client, auth, observation_ids, **params):
    body = {"season_code": SEASON, "species_code": SPECIES, "observation_ids": observation_ids, **params}
    resp = client.post("/api/reid/batches", headers=auth, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _decide(client, auth, candidate_id, verdict, reason="验收测试裁定", expected=None):
    body = {"verdict": verdict, "reason": reason}
    if expected is not None:
        body["expected_last_decision_id"] = expected
    resp = client.post(f"/api/reid/candidates/{candidate_id}/decisions", headers=auth, json=body)
    return resp


# ---------------------------------------------------------------- 基线
def test_seed_keeps_photos_candidates_and_individuals_distinct(client, auth):
    report = _baseline_report(client, auth)
    summary = report["summary"]
    assert summary["photo_observation_count"] >= 20
    assert summary["candidate_count"] > summary["statistical_individual_count"]
    assert summary["statistical_individual_count"] == 5
    assert summary["first_capture_count"] == 5
    assert summary["repeat_capture_count"] == 5
    buckets = summary["exclusion_buckets"]
    assert buckets["excluded_unreadable"] == 1
    assert buckets["excluded_duplicate_cluster"] == 1
    assert buckets["excluded_pending"] >= 1
    assert buckets["excluded_rejected"] == 2
    # 照片数、候选数、统计个体数三个口径互不相等。
    assert summary["photo_observation_count"] != summary["candidate_count"]
    assert summary["candidate_status_counts"]["confirmed"] == 5


def test_crop_copy_is_same_source_cluster_and_single_capture(client, auth):
    original = _obs_by_ref(client, auth, "DEER-QSL02-0411-A")
    crop = _obs_by_ref(client, auth, "DEER-QSL02-0411-A-CROP")
    assert crop["source_cluster_id"] == original["source_cluster_id"]
    assert crop["source_cluster_id"] is not None
    trace = client.get(f"/api/reid/observations/{crop['id']}/trace", headers=auth).json()
    sibling_ids = {o["id"] for o in trace["source_cluster_siblings"]}
    assert original["id"] in sibling_ids

    report = _baseline_report(client, auth)
    entries = report["entries"]
    crop_entry = next(e for e in entries if e["observation_id"] == crop["id"])
    original_entry = next(e for e in entries if e["observation_id"] == original["id"])
    assert crop_entry["status"] == "excluded_duplicate_cluster"
    assert original_entry["status"] == "included"
    # 裁剪件没有制造第二个统计个体。
    individual_codes = {e["individual_code"] for e in entries if e["status"] == "included"}
    assert len([c for c in individual_codes if c]) == 5


def test_burst_sequence_forms_one_source_cluster(client, auth):
    b1 = _obs_by_ref(client, auth, "DEER-BURST-1")
    b2 = _obs_by_ref(client, auth, "DEER-BURST-2")
    assert b1["source_cluster_id"] == b2["source_cluster_id"]
    clusters = client.get("/api/reid/source-clusters", headers=auth).json()
    burst = next(c for c in clusters if c["cluster_kind"] == "burst")
    assert burst["member_count"] == 2


# ---------------------------------------------------------------- 互斥与传递约束
def test_rejected_relation_cannot_be_bypassed_on_another_chain(client, auth):
    far_a = _obs_by_ref(client, auth, "DEER-QSL01-FAR")
    far_b = _obs_by_ref(client, auth, "DEER-BHP01-FAR")
    bridge = _obs_by_ref(client, auth, "DEER-BRIDGE-1")
    rejected = _candidate_between(client, auth, far_a["id"], far_b["id"])
    assert rejected["status"] == "rejected"

    c1 = _candidate_between(client, auth, far_a["id"], bridge["id"])
    ok = _decide(client, auth, c1["id"], "confirm", "桥接观察与 far_a 可达，先确认")
    assert ok.status_code == 200, ok.text
    c2 = _candidate_between(client, auth, bridge["id"], far_b["id"])
    blocked = _decide(client, auth, c2["id"], "confirm", "试图绕过否决约束")
    assert blocked.status_code == 409
    assert "否决" in blocked.json()["detail"]


def test_transitive_merge_requires_whole_group_reachability(client, auth):
    chain2 = _obs_by_ref(client, auth, "DEER-CHAIN-2")
    chain3 = _obs_by_ref(client, auth, "DEER-CHAIN-3")
    cand = _candidate_between(client, auth, chain2["id"], chain3["id"])
    resp = _decide(client, auth, cand["id"], "confirm", "同时刻异地，传递合并必须被拦截")
    assert resp.status_code == 409
    assert "全组一致性" in resp.json()["detail"]


# ---------------------------------------------------------------- 校时
def test_time_correction_only_creates_candidate_then_manual_confirm(client, auth):
    tc1 = _obs_by_ref(client, auth, "DEER-TC-1")
    tc2 = _obs_by_ref(client, auth, "DEER-TC-2")
    cand = _candidate_between(client, auth, tc1["id"], tc2["id"])
    # 校时只新建候选，不自动合并。
    assert cand["status"] == "candidate"
    before = _latest_report(client, auth)
    before_individuals = before["summary"]["statistical_individual_count"]
    tc_entries_before = [
        e for e in before["entries"] if e["observation_id"] in (tc1["id"], tc2["id"])
    ]
    assert all(e["status"] != "included" for e in tc_entries_before)

    resp = _decide(client, auth, cand["id"], "confirm", "校时进入可达窗口后专家确认")
    assert resp.status_code == 200, resp.text
    after = _latest_report(client, auth)
    assert after["id"] != before["id"]
    assert after["summary"]["statistical_individual_count"] == before_individuals + 1
    # 旧季报保持冻结口径。
    assert _baseline_report(client, auth)["summary"]["statistical_individual_count"] == 5


# ---------------------------------------------------------------- 并发与同级相反裁定
def test_stale_decision_is_rejected_and_peer_conflict_freezes_eligibility(client, auth, auditor_auth):
    stations = _stations(client, auth)
    o1 = _register(client, auth, stations, ref="T-CONF-1", station_code="BHP-02",
                   day="04-15", hour=9, features={"stripe_pattern": ["sp-conflict-x"]})
    o2 = _register(client, auth, stations, ref="T-CONF-2", station_code="BHP-02",
                   day="04-16", hour=9, features={"stripe_pattern": ["sp-conflict-x"]})
    batch = _batch(client, auth, [o1["id"], o2["id"]])
    cand = next(c for c in batch["candidates"]
                if {c["observation_a_id"], c["observation_b_id"]} == {o1["id"], o2["id"]})

    first = _decide(client, auth, cand["id"], "confirm", "专家甲确认同一个体")
    assert first.status_code == 200, first.text
    first_decision_id = first.json()["decision"]["id"]

    # 后提交者仍基于旧状态：乐观并发拦截。
    stale = _decide(client, auditor_auth, cand["id"], "reject", "专家乙未刷新即否决")
    assert stale.status_code == 409
    assert "最新证据" in stale.json()["detail"]

    # 带最新决策 id 提交相反结论：同级冲突，统计资格冻结转裁定待定。
    conflicting = _decide(
        client, auditor_auth, cand["id"], "reject",
        "专家乙复核后坚持否决", expected=first_decision_id,
    )
    assert conflicting.status_code == 200, conflicting.text
    body = conflicting.json()
    assert body["candidate"]["status"] == "adjudicating_pending"
    adjudications = client.get(
        "/api/reid/adjudications?status=pending", headers=auth
    ).json()
    adj = next(a for a in adjudications if a["candidate_id"] == cand["id"])
    individuals = client.get("/api/reid/individuals?status=under_review", headers=auth).json()
    assert any(
        set(i["observation_ids"]) & {o1["id"], o2["id"]} for i in individuals
    )
    latest = _latest_report(client, auth)
    frozen_rows = [
        e for e in latest["entries"]
        if e["observation_id"] in (o1["id"], o2["id"]) and e["status"] == "excluded_review"
    ]
    assert frozen_rows, "裁定待定期间相关观察不得进入个体数"

    # 上级/第三方裁定收口。
    resolved = client.post(
        f"/api/reid/adjudications/{adj['id']}/resolve",
        headers=auth,
        json={
            "final_verdict": "confirm",
            "reason": "引入第三方高清素材复核，维持同一个体",
            "third_party_evidence": {"source": "上级影像复核组", "file": "NC-2026-077"},
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    assert client.get(f"/api/reid/candidates/{cand['id']}", headers=auth).json()["status"] == "confirmed"


# ---------------------------------------------------------------- 竞争归属冻结
def test_competing_claim_freezes_duplicate_attribution(client, auth):
    stations = _stations(client, auth)
    d3 = _obs_by_ref(client, auth, "DEER-QSL03-D3-1")
    d4 = _obs_by_ref(client, auth, "DEER-YXG02-D4-1")
    probe = _register(
        client, auth, stations, ref="T-HOLD-PROBE", station_code="QSL-03",
        day="04-15", hour=10,
        features={
            "stripe_pattern": ["sp-c1", "sp-d4a", "sp-d4b"],
            "scar_marks": ["scar-right-ear", "scar-left-leg"],
            "coat_color": "brown",
        },
    )
    _batch(client, auth, [probe["id"], d3["id"], d4["id"]], feature_threshold=0.2)
    to_d3 = _candidate_between(client, auth, probe["id"], d3["id"])
    confirmed = _decide(client, auth, to_d3["id"], "confirm", "探针观察并入 D3 个体")
    assert confirmed.status_code == 200, confirmed.text

    to_d4 = _candidate_between(client, auth, probe["id"], d4["id"])
    holds = client.get("/api/reid/membership-holds?status=open", headers=auth).json()
    hold = next(h for h in holds if h["candidate_id"] == to_d4["id"])
    assert hold["individual_a_id"] != hold["individual_b_id"]
    held_observation_ids = {hold["observation_id"]}

    latest = _latest_report(client, auth)
    probe_entry = next(e for e in latest["entries"] if e["observation_id"] == probe["id"])
    assert probe_entry["status"] == "frozen"
    # 探针不能同时贡献两条轨迹。
    contributing = [e for e in latest["entries"]
                    if e["observation_id"] == probe["id"] and e["status"] == "included"]
    assert not contributing

    # 否决跨个体候选后冻结解除。
    rejected = _decide(client, auth, to_d4["id"], "reject", "复核后排除与 D4 的关联")
    assert rejected.status_code == 200, rejected.text
    remaining = client.get("/api/reid/membership-holds?status=open", headers=auth).json()
    assert all(h["candidate_id"] != to_d4["id"] for h in remaining)
    assert held_observation_ids


# ---------------------------------------------------------------- 变动监测与复审
def test_authorization_withdraw_pauses_statistics_but_keeps_old_report(client, auth):
    target = _obs_by_ref(client, auth, "DEER-QSL01-0410-A")
    before = _latest_report(client, auth)
    resp = client.post(
        f"/api/reid/observations/{target['id']}/withdraw",
        headers=auth, json={"reason": "合作机构撤回该照片的使用授权"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["authorization_status"] == "withdrawn"

    reviews = client.get("/api/reid/reviews?status=opened", headers=auth).json()
    review = next(r for r in reviews if r["trigger_type"] == "authorization_withdrawn")
    latest = _latest_report(client, auth)
    paused = [e for e in latest["entries"]
              if e["observation_id"] == target["id"] and e["status"] == "excluded_review"]
    assert paused
    # 旧季报仍保留当时采用的分组与纳入记录。
    baseline = _baseline_report(client, auth)
    old = next(e for e in baseline["entries"] if e["observation_id"] == target["id"])
    assert old["status"] == "included"

    resolved = client.post(
        f"/api/reid/reviews/{review['id']}/resolve",
        headers=auth, json={"outcome": "keep", "reason": "补授权完成，沿用原个体关系"},
    )
    assert resolved.status_code == 200, resolved.text
    recovered = _latest_report(client, auth)
    row = next(e for e in recovered["entries"] if e["observation_id"] == target["id"])
    assert row["status"] == "included"
    assert before["id"] != recovered["id"]


def test_hash_mismatch_then_review_revoke(client, auth):
    target = _obs_by_ref(client, auth, "DEER-YXG01-0412-A")
    resp = client.post(
        f"/api/reid/observations/{target['id']}/hash-mismatch",
        headers=auth, json={"expected_hash": "a" * 64},
    )
    assert resp.status_code == 200, resp.text
    review = next(
        r for r in client.get("/api/reid/reviews?status=opened", headers=auth).json()
        if r["trigger_type"] == "hash_mismatch"
    )
    revoked = client.post(
        f"/api/reid/reviews/{review['id']}/resolve",
        headers=auth, json={"outcome": "revoke", "reason": "原始文件无法复核，撤销统计资格"},
    )
    assert revoked.status_code == 200, revoked.text
    latest = _latest_report(client, auth)
    row = next(e for e in latest["entries"] if e["observation_id"] == target["id"])
    assert row["status"] in ("excluded_pending", "excluded_review")
    individuals = client.get("/api/reid/individuals?status=revoked", headers=auth).json()
    assert any(target["id"] in i["observation_ids"] for i in individuals)


def test_location_revision_opens_review_and_recalculates_reachability(client, auth):
    stations = _stations(client, auth)
    lv = client.post(
        "/api/reid/location-versions",
        headers=auth,
        json={"code": "LOC-V2", "version": "2026.04-v2", "change_reason": "相机坐标勘误"},
    ).json()
    target = _obs_by_ref(client, auth, "DEER-YXG01-0413-A")
    resp = client.post(
        f"/api/reid/observations/{target['id']}/location-revision",
        headers=auth,
        json={"location_version_id": lv["id"], "latitude": 30.991, "longitude": 103.561},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["location_version_id"] == lv["id"]
    assert any(
        r["trigger_type"] == "location_revision"
        for r in client.get("/api/reid/reviews", headers=auth).json()
    )


# ---------------------------------------------------------------- 季节窗口
def test_calibration_pushing_observation_out_of_season_excludes_capture(client, auth):
    stations = _stations(client, auth)
    correction = client.post(
        "/api/reid/time-corrections",
        headers=auth,
        json={
            "code": "TC-SEASON-14D", "version": "v1", "target_device": "CAM-QSL-04",
            "offset_seconds": 1209600,
            "valid_from": "2026-03-01T00:00:00+08:00",
            "valid_to": "2026-05-01T00:00:00+08:00",
            "verified": True, "basis": "复核发现设备日期快了 14 天",
        },
    ).json()
    o1 = _register(client, auth, stations, ref="T-SEASON-1", station_code="QSL-04",
                   day="04-16", hour=8, features={"stripe_pattern": ["sp-season-only"]})
    o2 = _register(client, auth, stations, ref="T-SEASON-2", station_code="QSL-04",
                   day="04-17", hour=8, features={"stripe_pattern": ["sp-season-only"]})
    _batch(client, auth, [o1["id"], o2["id"]])
    cand = _candidate_between(client, auth, o1["id"], o2["id"])
    assert _decide(client, auth, cand["id"], "confirm", "季节窗口内先确认").status_code == 200

    calibrated = client.post(
        f"/api/reid/observations/{o1['id']}/time-correction",
        headers=auth, json={"time_correction_id": correction["id"]},
    )
    assert calibrated.status_code == 200
    assert calibrated.json()["survey_date"] == "2026-04-02"
    # 14 天校正后落在 04-02 仍在季内；改用 35 天校正推出季节窗口。
    correction2 = client.post(
        "/api/reid/time-corrections",
        headers=auth,
        json={
            "code": "TC-SEASON-35D", "version": "v1", "target_device": "CAM-QSL-04",
            "offset_seconds": 3024000,
            "valid_from": "2026-03-01T00:00:00+08:00",
            "valid_to": "2026-05-01T00:00:00+08:00",
            "verified": True, "basis": "进一步复核设备日期快了 35 天",
        },
    ).json()
    calibrated2 = client.post(
        f"/api/reid/observations/{o1['id']}/time-correction",
        headers=auth, json={"time_correction_id": correction2["id"]},
    ).json()
    assert calibrated2["survey_date"] == "2026-03-12"
    latest = _latest_report(client, auth)
    row = next(e for e in latest["entries"] if e["observation_id"] == o1["id"])
    assert row["status"] == "excluded_season"
    assert "季节窗口" in row["exclusion_reason"]
    # 观察本身仍保留在档案中。
    assert client.get(f"/api/reid/observations/{o1['id']}", headers=auth).status_code == 200


# ---------------------------------------------------------------- 确认后拆分
def test_split_recomputes_captures_without_copying_counts(client, auth):
    stations = _stations(client, auth)
    feats = {"stripe_pattern": ["sp-split-unique"], "scar_marks": ["scar-split"]}
    a = _register(client, auth, stations, ref="T-SPLIT-1", station_code="QSL-04",
                  day="04-21", hour=8, features=feats)
    b = _register(client, auth, stations, ref="T-SPLIT-2", station_code="QSL-04",
                  day="04-22", hour=8, features=feats)
    batch = _batch(client, auth, [a["id"], b["id"]])
    cand = next(c for c in batch["candidates"]
                if {c["observation_a_id"], c["observation_b_id"]} == {a["id"], b["id"]})
    assert _decide(client, auth, cand["id"], "confirm", "拆分前先确认为同一个体").status_code == 200

    parent = next(
        i for i in client.get("/api/reid/individuals", headers=auth).json()
        if {a["id"], b["id"]} <= set(i["observation_ids"])
    )
    pre_split_report = _latest_report(client, auth)
    parent_old_entries = [e for e in pre_split_report["entries"]
                         if e["individual_id"] == parent["id"] and e["status"] == "included"]
    old_included = len(parent_old_entries)
    assert old_included == 2

    # 另取一个与拆分无关的活跃个体，验证其统计不会一起失效。
    unrelated = next(
        i for i in client.get("/api/reid/individuals?status=active", headers=auth).json()
        if i["id"] != parent["id"]
    )

    resp = client.post(
        f"/api/reid/individuals/{parent['id']}/split",
        headers=auth,
        json={"groups": [[a["id"]], [b["id"]]],
              "reason": "复核发现伤痕证据不足，拆为两个个体"},
    )
    assert resp.status_code == 200, resp.text
    children = resp.json()["children"]
    assert len(children) == 2
    assert all(c["status_label"] == "正常" for c in children)

    latest = _latest_report(client, auth)
    child_ids = {c["id"] for c in children}
    child_entries = [e for e in latest["entries"] if e["individual_id"] in child_ids]
    # 不能把原个体捕获次数完整复制给每个新个体：每个新个体只继承自己的观察。
    for child in children:
        own = [e for e in child_entries if e["individual_id"] == child["id"] and e["status"] == "included"]
        assert len(own) == 1
        assert len(own) < old_included
    assert sum(1 for e in child_entries if e["status"] == "included") == old_included
    # 无关个体的统计仍然有效，没有一起失效。
    unrelated_rows = [e for e in latest["entries"]
                      if e["individual_id"] == unrelated["id"] and e["status"] == "included"]
    assert unrelated_rows
    # 拆分前的季报仍可还原当时采用的分组（旧运行不可变）。
    assert [e for e in pre_split_report["entries"] if e["individual_id"] == parent["id"]
            and e["status"] == "included"] == parent_old_entries


# ---------------------------------------------------------------- 联合划分采用与截断
def test_partition_adoption_does_not_auto_pick_highest_score(client, auth):
    stations = _stations(client, auth)
    feats = {"stripe_pattern": ["sp-adopt-unique"]}
    o1 = _register(client, auth, stations, ref="T-ADOPT-1", station_code="QSL-04",
                   day="04-18", hour=8, features=feats)
    o2 = _register(client, auth, stations, ref="T-ADOPT-2", station_code="QSL-04",
                   day="04-19", hour=8, features=feats)
    o3 = _register(client, auth, stations, ref="T-ADOPT-3", station_code="QSL-04",
                   day="04-20", hour=8, features=feats)
    batch = _batch(client, auth, [o1["id"], o2["id"], o3["id"]])
    # 采用前没有任何确认，也没有产生统计个体。
    assert all(c["status"] == "candidate" for c in batch["candidates"])
    target = next(p for p in batch["partitions"] if any(len(g) == 3 for g in p["groups"]))
    resp = client.post(
        f"/api/reid/partitions/{target['id']}/adopt",
        headers=auth, json={"reason": "专家核对整组划分后裁定采用"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "adopted"
    latest = _latest_report(client, auth)
    adopted_inds = [
        i for i in client.get("/api/reid/individuals", headers=auth).json()
        if {o1["id"], o2["id"], o3["id"]} <= set(i["observation_ids"])
    ]
    assert adopted_inds and latest["summary"]["statistical_individual_count"] >= 1


def test_truncated_search_records_scope_and_unresolved(client, auth):
    stations = _stations(client, auth)
    ids = []
    for n in range(4):
        ids.append(_register(
            client, auth, stations, ref=f"T-TRUNC-{n}", station_code="BHP-01",
            day="04-18", hour=8 + n,
            features={"stripe_pattern": [f"sp-trunc-{n}"], "coat_color": "grey"},
        )["id"])
    batch = _batch(client, auth, ids, pair_search_limit=1, partition_limit=3)
    assert batch["status"] == "truncated"
    assert batch["checked_pair_count"] == 1
    assert batch["unresolved_observation_ids"]
    assert "不声称找到唯一划分" in batch["truncation_note"]


# ---------------------------------------------------------------- 溯源与边界
def test_report_trace_returns_full_evidence_chain(client, auth):
    baseline = _baseline_report(client, auth)
    trace = client.get(f"/api/reid/report-runs/{baseline['id']}/trace", headers=auth).json()
    assert trace["run"]["report_code"] == baseline["report_code"]
    assert trace["entries"] and trace["individuals"] and trace["individual_versions"]
    assert trace["observations"] and trace["candidates"] and trace["decisions"]
    # 冻结版本包含特征/位置/校时版本引用。
    version = trace["individual_versions"][0]
    assert "frozen_versions" in version
    one_obs = trace["observations"][0]
    obs_trace = client.get(f"/api/reid/observations/{one_obs['id']}/trace", headers=auth).json()
    assert obs_trace["observation"]["file_hash"]
    assert "candidates" in obs_trace and "decisions" in obs_trace
    assert "individual_versions" in obs_trace and "capture_entries" in obs_trace


def test_unreadable_observation_never_enters_statistics(client, auth):
    report = _latest_report(client, auth)
    blur = _obs_by_ref(client, auth, "DEER-BHP01-BLUR")
    row = next(e for e in report["entries"] if e["observation_id"] == blur["id"])
    assert row["status"] == "excluded_unreadable"


def test_reid_endpoints_emit_no_dispatch_actions(client, auth):
    forbidden = ("dispatch", "assign", "schedule_patrol", "enforce", "resource_order")
    schema = client.get("/openapi.json").json()
    paths = " ".join(schema["paths"].keys()).lower()
    for word in forbidden:
        assert word not in paths
