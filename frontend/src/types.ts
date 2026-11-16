export type Status = 'valid' | 'restricted' | 'invalid' | 'pending' | 'under_review'
export type GateKey = 'device' | 'time' | 'space' | 'reading'

export interface User {
  id: number
  username: string
  display_name: string
  role: 'researcher' | 'auditor' | 'viewer'
}

export interface Gate {
  id: number
  gate: GateKey
  requirement_code: string
  status: 'pass' | 'restricted' | 'fail' | 'pending'
  measured: Record<string, any>
  threshold: Record<string, any>
  explanation: string
  rule_ref: string
  evidence: number[]
}

export interface Certificate {
  id: number
  unit_id: number
  run_id: number
  certificate_no: string
  version: number
  status: Status
  status_label: string
  absence_eligible: boolean
  trend_eligible: boolean
  review_status: 'normal' | 'under_review'
  review_status_label: string
  review_reason: string
  summary: string
  gate_snapshot: Array<Record<string, any>>
  conclusions: {
    absence_analysis?: {
      supported: boolean
      species_note: string
      confirmed_present: number
      confirmed_absent_readings: number
      pending_materials: number
      open_conflicts: number
      never_implies_absence: string[]
    }
    trend?: Record<string, any>
  }
  issued_at: string
  superseded_by_id: number | null
}

export interface EstimateVariant {
  key: string
  label: string
  probability: number
  low: number
  high: number
  passes: boolean
}

export interface ProbabilityEstimate {
  id: number
  unit_id: number
  model_id: number
  model_code: string
  model_name: string
  model_version: string
  model_status: string
  threshold: number
  probability: number
  interval_low: number
  interval_high: number
  threshold_pass: boolean
  conclusion: 'supports_partial' | 'below_threshold'
  variants: EstimateVariant[]
  assumptions: string[]
}

export interface Unit {
  id: number
  run_id: number
  station_id: number
  station_code: string
  station_name: string
  zone_id: number
  unit_date: string
  station_version_id: number
  rulebook_version_id: number
  model_version_id: number | null
  coverage_summary: Record<string, any>
  feature_vector: Record<string, any>
  gate_status: Record<GateKey, string>
  data_issues: Array<{ gate: string; gate_label: string; status: string; explanation: string }>
  assembled_at: string
  certificate: Certificate | null
  probability: ProbabilityEstimate | null
}

export interface TrendReference {
  id: number
  reference_code: string
  purpose: 'absence' | 'trend'
  purpose_label: string
  unit_id: number
  certificate_id: number | null
  status: 'active' | 'suspended' | 'revoked'
  snapshot: Record<string, any>
  created_by: string
  created_at: string
  suspended_reason: string
  suspended_at: string | null
  note: string
  station_code?: string
  station_name?: string
  unit_date?: string
}

export interface Determination {
  id: number
  material_record_id: number
  source: string
  species_code: string
  verdict: 'present' | 'absent' | 'uncertain'
  confidence: number
  analyst: string
  revision: number
  status: 'active' | 'superseded'
  notes: string
}

export interface EvidenceMaterial {
  id: number
  record_type: string
  record_type_label: string
  external_id: string
  event_time: string
  received_time: string
  source_device: string
  latitude: number | null
  longitude: number | null
  coord_precision_m: number | null
  payload: Record<string, any>
  payload_hash: string
  revision: number
  is_pending: boolean
  determinations: Determination[]
  conflicts: Array<{ id: number; sources: Array<Record<string, any>>; status: string }>
}

export interface UnitDetail extends Unit {
  station: StationDetail
  station_version: {
    id: number
    version_number: number
    buffer_width_m: number
    effective_from: string
    effective_to: string | null
    change_reason: string
    boundary: { type: string; coordinates: number[][][] }
  }
  rulebook: RulebookVersion
  gates: Gate[]
  certificate_history: Certificate[]
  conflicts: Array<{
    id: number
    species_code: string
    sources: Array<Record<string, any>>
    detail: string
    status: string
    resolution: string
    material_record_id: number
    detected_at: string
  }>
  trend_references: TrendReference[]
  evidence: {
    materials: EvidenceMaterial[]
    record_count: number
    determination_count: number
  }
  audit: AuditEntry[]
}

export interface Station {
  id: number
  code: string
  name: string
  zone_id: number
  zone: { code: string; name: string } | null
  latitude: number
  longitude: number
  elevation_min_m: number
  elevation_max_m: number
  status: string
  version_count: number
}

export interface StationDetail extends Station {
  versions: Array<{
    id: number
    version_number: number
    boundary: { type: string; coordinates: number[][][] }
    buffer_width_m: number
    centroid: { lat: number; lon: number }
    effective_from: string
    effective_to: string | null
    change_reason: string
  }>
}

export interface RulebookVersion {
  id: number
  rulebook_code: string
  rulebook_name: string
  version_number: number
  label: string
  season_code: string
  season_start: string
  season_end: string
  status: string
  target_species: Array<{ code: string; name: string; min_detections: number }>
  requirements: Record<string, any>
  route_segments: Array<Record<string, any>>
  elevation_bands: Array<Record<string, any>>
  notes: string
}

export interface ProbabilityModel {
  id: number
  code: string
  name: string
  version: string
  status: string
  threshold: number
  calibration_sets: Array<{ label: string; pivot_delta: number; n: number }>
  parameters: Record<string, any>
  threshold_review: Record<string, any>
  notes: string
  estimate_count?: number
}

export interface Run {
  id: number
  run_code: string
  label: string
  season_code: string
  season_start: string
  season_end: string
  status: string
  rulebook_version_id: number
  model_version_id: number | null
  created_by: string
  created_at: string
  unit_count: number
  status_counts: Record<string, number>
  open_conflicts: number
  trend_references: number
}

export interface ComparisonRow {
  unit_id: number
  station_code: string
  station_name: string
  date: string
  rule_status: Status
  absence_eligible: boolean
  probability: number | null
  interval: [number, number] | null
  threshold: number | null
  threshold_pass: boolean | null
  divergence: 'both_support' | 'probability_supports_rule_blocks' | 'rule_supports_probability_below'
}

export interface Overview {
  run: Run
  rulebook: RulebookVersion
  model: {
    id: number
    code: string
    version: string
    threshold: number
    status: string
    calibration_sets: Array<Record<string, any>>
  } | null
  unit_count: number
  station_count: number
  date_count: number
  dates: string[]
  status_counts: Record<string, number>
  gate_counts: Record<GateKey, Record<string, number>>
  stations: Array<Station & { units: Array<Record<string, any>> }>
  comparison_rows: ComparisonRow[]
  open_conflicts: number
  active_trend_references: number
  recent_activity: AuditEntry[]
}

export interface Conflict {
  id: number
  unit_id: number
  run_id: number
  material_record_id: number
  material_external_id: string | null
  station_code: string | null
  station_name: string | null
  unit_date: string | null
  species_code: string
  sources: Array<{
    source: string
    analyst: string
    verdict: string
    confidence: number
    determination_id: number
  }>
  detail: string
  status: 'open' | 'resolved'
  resolution: string
  detected_at: string
  resolved_at: string | null
}

export interface AuditEntry {
  id: number
  entity_type: string
  entity_id: number
  action: string
  actor: string
  detail: Record<string, any>
  created_at: string
}

export interface ArchiveRecord {
  id: number
  record_type: string
  record_type_label: string
  external_id: string
  station_id: number
  station_code: string | null
  event_time: string
  received_time: string
  source_device: string
  device_type: string
  latitude: number | null
  longitude: number | null
  coord_precision_m: number | null
  payload: Record<string, any>
  payload_hash: string
  revision: number
  record_status: string
  revisions?: Array<{
    id: number
    revision_number: number
    payload: Record<string, any>
    payload_hash: string
    received_time: string
    changed_by: string
    change_reason: string
    created_at: string
  }>
  determinations?: Determination[]
  used_by_units?: number[]
}

// ------------------------------------------------------------ 个体重识别
export interface ReidObservation {
  id: number
  observation_code: string
  species_code: string
  observation_kind: string
  external_ref: string
  file_hash: string
  station_id: number
  station_code: string | null
  station_name: string | null
  latitude: number | null
  longitude: number | null
  observed_at: string
  received_at: string
  effective_observed_at: string
  corrected_observed_at: string | null
  time_correction_id: number | null
  location_version_id: number | null
  feature_version_id: number | null
  posture_quality: string
  posture_score: number
  visible_features: Record<string, any>
  source_cluster_id: number | null
  source_cluster?: ReidSourceCluster | null
  authorization: Record<string, any>
  authorization_status: 'authorized' | 'withdrawn'
  interpretability: 'interpretable' | 'unreadable'
  season_code: string
  survey_date: string | null
  payload_hash: string
  record_status: string
  created_by: string
  created_at: string
}

export interface ReidSourceCluster {
  id: number
  cluster_code: string
  cluster_kind: string
  cluster_kind_label: string
  rationale: string
  member_count?: number
  created_at: string
}

export interface ReidDecision {
  id: number
  candidate_id: number
  expert: string
  expert_level: string
  verdict: 'confirm' | 'reject' | 'retain'
  verdict_label: string
  reason: string
  evidence_snapshot: Record<string, any>
  frozen_versions: Record<string, any>
  expected_last_decision_id: number | null
  superseded: boolean
  created_at: string
}

export interface ReidCandidate {
  id: number
  batch_id: number | null
  observation_a_id: number
  observation_b_id: number
  observation_a_code: string
  observation_b_code: string
  observation_a_station: string | null
  observation_b_station: string | null
  feature_score: number
  spatial_reachable: boolean
  evidence: Record<string, any>
  counter_evidence: Array<Record<string, any>>
  source_independent: boolean
  status: string
  status_label: string
  created_at: string
  decisions: ReidDecision[]
}

export interface ReidPartition {
  id: number
  batch_id: number
  partition_code: string
  rank: number
  score: number
  groups: number[][]
  competing_memberships: Record<string, any>
  constraint_violations: Array<Record<string, any>>
  status: string
  status_label: string
}

export interface ReidBatch {
  id: number
  batch_code: string
  season_code: string
  species_code: string
  scope_observation_ids: number[]
  max_travel_speed_kmh: number
  feature_threshold: number
  status: string
  status_label: string
  checked_pair_count: number
  unresolved_observation_ids: number[]
  truncation_note: string
  candidates?: ReidCandidate[]
  partitions?: ReidPartition[]
  created_at: string
}

export interface ReidIndividualVersion {
  id: number
  individual_id: number
  version_number: number
  observation_ids: number[]
  source_cluster_ids: number[]
  candidate_ids: number[]
  decision_ids: number[]
  frozen_versions: Record<string, any>
  change_reason: string
  status: string
  status_label: string
}

export interface ReidIndividual {
  id: number
  individual_code: string
  species_code: string
  season_code: string
  status: string
  status_label: string
  current_version_id: number | null
  observation_ids: number[]
  versions?: ReidIndividualVersion[]
}

export interface ReidCaptureEntry {
  id: number
  individual_id: number | null
  individual_code: string | null
  observation_id: number
  observation_code: string | null
  source_cluster_id: number | null
  station_code: string | null
  survey_date: string
  capture_kind: 'first' | 'repeat' | 'excluded'
  capture_kind_label: string
  sequence_no: number
  status: string
  status_label: string
  exclusion_reason: string
}

export interface ReidReportRun {
  id: number
  report_code: string
  season_code: string
  species_code: string
  status: string
  summary: {
    photo_observation_count: number
    candidate_count: number
    candidate_status_counts: Record<string, number>
    statistical_individual_count: number
    first_capture_count: number
    repeat_capture_count: number
    exclusion_buckets: Record<string, number>
    season_window: [string, string] | null
    change_note?: string
  }
  superseded_by_id: number | null
  created_by: string
  created_at: string
  entries?: ReidCaptureEntry[]
}

export interface ReidReviewEvent {
  id: number
  individual_id: number
  individual_version_id: number
  trigger_type: string
  trigger_label: string
  trigger_detail: Record<string, any>
  status: string
  status_label: string
  resolution: string
  opened_by: string
  resolved_by: string | null
  created_at: string
  resolved_at: string | null
}

export interface ReidAdjudication {
  id: number
  candidate_id: number
  reason: string
  third_party_evidence: Record<string, any>
  status: 'pending' | 'resolved'
  final_verdict: string | null
  opened_by: string
  resolved_by: string | null
  created_at: string
  resolved_at: string | null
}

export interface ReidMembershipHold {
  id: number
  observation_id: number
  individual_a_id: number
  individual_b_id: number
  candidate_id: number
  status: 'open' | 'resolved'
  reason: string
  created_at: string
  resolved_at: string | null
}
