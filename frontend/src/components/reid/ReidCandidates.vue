<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../../api'
import { useToast } from '../../toast'
import { authState } from '../../session'
import type {
  ReidAdjudication,
  ReidBatch,
  ReidCandidate,
  ReidObservation,
} from '../../types'

const { push } = useToast()
const batches = ref<ReidBatch[]>([])
const selected = ref<ReidBatch | null>(null)
const observations = ref<ReidObservation[]>([])
const adjudications = ref<ReidAdjudication[]>([])
const loading = ref(true)

const batchForm = ref({
  max_travel_speed_kmh: 3.0,
  feature_threshold: 0.35,
  pair_search_limit: 500,
})
const reason = ref<Record<number, string>>({})
const expectedDecision = ref<Record<number, number | null>>({})
const adjReason = ref<Record<number, string>>({})

async function load() {
  loading.value = true
  try {
    const [bs, obs, adjs] = await Promise.all([
      api.get<ReidBatch[]>('/reid/batches'),
      api.get<{ items: ReidObservation[] }>('/reid/observations?limit=300'),
      api.get<ReidAdjudication[]>('/reid/adjudications'),
    ])
    batches.value = bs
    observations.value = obs.items
    adjudications.value = adjs
    if (bs.length && !selected.value) await openBatch(bs[0].id)
  } catch (err) {
    push(err instanceof Error ? err.message : '加载失败', 'error')
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function createBatch() {
  try {
    const batch = await api.post<ReidBatch>('/reid/batches', {
      season_code: '2026-SPRING',
      species_code: 'CERVUS',
      max_travel_speed_kmh: batchForm.value.max_travel_speed_kmh,
      feature_threshold: batchForm.value.feature_threshold,
      pair_search_limit: batchForm.value.pair_search_limit,
      partition_limit: 4,
    })
    push(`批次 ${batch.batch_code} 已完成联合候选搜索（检查 ${batch.checked_pair_count} 对）`)
    await load()
    await openBatch(batch.id)
  } catch (err) {
    push(err instanceof Error ? err.message : '批次创建失败', 'error')
  }
}

async function openBatch(id: number) {
  selected.value = await api.get<ReidBatch>(`/reid/batches/${id}`)
}

function obsCode(id: number): string {
  return observations.value.find((o) => o.id === id)?.observation_code || `#${id}`
}

async function decide(cand: ReidCandidate, verdict: 'confirm' | 'reject' | 'retain') {
  const text = (reason.value[cand.id] || '').trim()
  if (!text) return push('请填写裁定理由', 'error')
  try {
    await api.post(`/reid/candidates/${cand.id}/decisions`, {
      verdict,
      reason: text,
      expected_last_decision_id: expectedDecision.value[cand.id] ?? null,
    })
    reason.value[cand.id] = ''
    expectedDecision.value[cand.id] = null
    push(verdict === 'confirm' ? '已确认同一个体，个体决策册已冻结采用版本' : '裁定已记录')
    await load()
    if (selected.value) await openBatch(selected.value.id)
  } catch (err) {
    push(err instanceof Error ? err.message : '裁定失败', 'error')
  }
}

async function adopt(partitionId: number) {
  try {
    await api.post(`/reid/partitions/${partitionId}/adopt`, { reason: '专家核对整组划分后整体裁定采用' })
    push('划分已采用，得分最高方案不会自动进入统计')
    await load()
    if (selected.value) await openBatch(selected.value.id)
  } catch (err) {
    push(err instanceof Error ? err.message : '划分采用失败', 'error')
  }
}

async function resolveAdj(adj: ReidAdjudication, verdict: 'confirm' | 'reject') {
  const text = (adjReason.value[adj.id] || '').trim()
  if (!text) return push('请填写上级/第三方裁定理由', 'error')
  try {
    await api.post(`/reid/adjudications/${adj.id}/resolve`, {
      final_verdict: verdict,
      reason: text,
      third_party_evidence: { source: '上级影像复核组', resolved_via: 'manual-adjudication' },
    })
    adjReason.value[adj.id] = ''
    push('裁定待定已收口')
    await load()
  } catch (err) {
    push(err instanceof Error ? err.message : '裁定失败', 'error')
  }
}
</script>

<template>
  <div class="stack">
    <div class="card" v-if="authState.isWriter.value">
      <div class="card-head"><h2>批次内联合候选搜索</h2></div>
      <div class="flex" style="gap: 12px; flex-wrap: wrap">
        <label class="field small">最大移动速度 km/h
          <input v-model.number="batchForm.max_travel_speed_kmh" type="number" step="0.1" class="input" />
        </label>
        <label class="field small">特征相似度阈值
          <input v-model.number="batchForm.feature_threshold" type="number" step="0.01" class="input" />
        </label>
        <label class="field small">候选对搜索上限
          <input v-model.number="batchForm.pair_search_limit" type="number" class="input" />
        </label>
        <button class="btn primary" @click="createBatch">运行联合搜索</button>
      </div>
      <div class="tiny muted" style="margin-top: 8px">
        搜索只生成候选关系与一致划分；已否决关系是持久约束，同来源簇素材不互成候选；超上限时记录已查范围与未解决观察，不声称唯一划分。
      </div>
    </div>

    <div class="card">
      <div class="card-head"><h2>联合批次</h2></div>
      <div class="flex" style="gap: 8px; flex-wrap: wrap">
        <button v-for="b in batches" :key="b.id" class="btn sm"
                :class="selected?.id === b.id ? 'primary' : 'ghost'" @click="openBatch(b.id)">
          {{ b.batch_code }} · {{ b.status_label }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>
    <template v-else-if="selected">
      <div class="card">
        <div class="card-head">
          <h2>{{ selected.batch_code }} 的候选关系（{{ selected.candidates?.length || 0 }}）</h2>
          <span class="chip">检查 {{ selected.checked_pair_count }} 对 · 未解决 {{ selected.unresolved_observation_ids.length }} 张</span>
        </div>
        <div v-if="selected.truncation_note" class="callout" style="background: #fff6e6; border-color: #e0b366">
          {{ selected.truncation_note }}
        </div>
        <div class="stack-sm">
          <div v-for="c in selected.candidates" :key="c.id" class="cand-card">
            <div class="between">
              <div>
                <span class="mono">{{ c.observation_a_code }}</span>
                <span class="muted">（{{ c.observation_a_station }}）</span>
                <span class="muted"> ⇄ </span>
                <span class="mono">{{ c.observation_b_code }}</span>
                <span class="muted">（{{ c.observation_b_station }}）</span>
              </div>
              <div class="flex" style="gap: 6px">
                <span class="badge" :class="c.spatial_reachable ? 'valid' : 'invalid'">
                  {{ c.spatial_reachable ? '时空可达' : '时空不可达' }}
                </span>
                <span class="badge neutral">相似度 {{ c.feature_score.toFixed(2) }}</span>
                <span class="badge" :class="c.status === 'confirmed' ? 'valid' : c.status === 'rejected' ? 'invalid' : 'pending'">
                  {{ c.status_label }}
                </span>
                <span v-if="!c.source_independent" class="badge pending">来源不独立</span>
              </div>
            </div>
            <div v-if="c.counter_evidence?.length" class="tiny" style="color: #b03a2e; margin-top: 6px">
              反证：{{ c.counter_evidence.map((x) => x.detail).join('；') }}
            </div>
            <div v-for="d in c.decisions" :key="d.id" class="decision small">
              <span class="chip">{{ d.expert }} · {{ d.verdict_label }}</span>
              <span class="muted">{{ d.reason }}</span>
              <span class="tiny muted">#决策{{ d.id }}（基于 #{{ d.expected_last_decision_id ?? '无' }}）</span>
            </div>
            <template v-if="authState.isWriter.value">
              <div class="flex" style="margin-top: 8px; gap: 8px">
                <input v-model="reason[c.id]" class="input grow" placeholder="裁定理由（冻结特征/位置/校时版本与理由）" />
                <input v-model.number="expectedDecision[c.id]" type="number" class="input" style="width: 130px"
                       placeholder="基于决策 id（并发控制）" />
                <button class="btn primary sm" @click="decide(c, 'confirm')">确认</button>
                <button class="btn sm" @click="decide(c, 'reject')">否决</button>
                <button class="btn ghost sm" @click="decide(c, 'retain')">保留待补证</button>
              </div>
            </template>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><h2>一致个体划分方案（不自动入选统计）</h2></div>
        <div class="grid grid-2" style="gap: 10px">
          <div v-for="p in selected.partitions" :key="p.id" class="partition-card">
            <div class="between">
              <strong>{{ p.partition_code }}</strong>
              <span class="chip">得分 {{ p.score.toFixed(3) }} · {{ p.status_label }}</span>
            </div>
            <div class="stack-sm" style="margin-top: 8px">
              <div v-for="(g, idx) in p.groups" :key="idx" class="group-row">
                <span class="tiny muted">组{{ idx + 1 }}（{{ g.length }}）：</span>
                <span v-for="oid in g" :key="oid" class="chip">{{ obsCode(oid) }}</span>
              </div>
            </div>
            <div v-if="Object.keys(p.competing_memberships || {}).length" class="tiny" style="color: #b06a00; margin-top: 6px">
              存在跨划分竞争归属：{{ Object.keys(p.competing_memberships).length }} 张照片在不同方案中分组不同
            </div>
            <div v-if="p.constraint_violations?.length" class="tiny" style="color: #b03a2e; margin-top: 6px">
              约束冲突：{{ p.constraint_violations.length }} 项
            </div>
            <button v-if="authState.isWriter.value && p.status === 'proposed'" class="btn sm" style="margin-top: 8px"
                    @click="adopt(p.id)">整体裁定采用</button>
          </div>
        </div>
      </div>
    </template>

    <div class="card" v-if="adjudications.some((a) => a.status === 'pending')">
      <div class="card-head"><h2>同级相反裁定 · 裁定待定</h2><span class="badge pending">统计资格已冻结</span></div>
      <div v-for="adj in adjudications.filter((a) => a.status === 'pending')" :key="adj.id" class="cand-card">
        <div class="small">候选 #{{ adj.candidate_id }}：{{ adj.reason }}</div>
        <div v-if="authState.isWriter.value" class="flex" style="margin-top: 8px; gap: 8px">
          <input v-model="adjReason[adj.id]" class="input grow" placeholder="第三方证据或上级裁定理由" />
          <button class="btn primary sm" @click="resolveAdj(adj, 'confirm')">上级确认</button>
          <button class="btn sm" @click="resolveAdj(adj, 'reject')">上级否决</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cand-card, .partition-card { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; background: #fff; }
.decision { display: flex; gap: 8px; align-items: center; margin-top: 6px; flex-wrap: wrap; }
.group-row { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
</style>
