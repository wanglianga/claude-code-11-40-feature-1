<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../../api'
import { useToast } from '../../toast'
import { authState } from '../../session'
import type {
  ReidIndividual,
  ReidMembershipHold,
  ReidReportRun,
  ReidReviewEvent,
} from '../../types'
import { fmtDate, fmtDateTime } from '../../format'

const { push } = useToast()
const individuals = ref<ReidIndividual[]>([])
const reports = ref<ReidReportRun[]>([])
const selectedReport = ref<ReidReportRun | null>(null)
const reviews = ref<ReidReviewEvent[]>([])
const holds = ref<ReidMembershipHold[]>([])
const loading = ref(true)
const splitGroups = ref<Record<number, string>>({})
const reviewReason = ref<Record<number, string>>({})

async function load() {
  loading.value = true
  try {
    const [inds, rpts, revs, hlds] = await Promise.all([
      api.get<ReidIndividual[]>('/reid/individuals'),
      api.get<ReidReportRun[]>('/reid/report-runs'),
      api.get<ReidReviewEvent[]>('/reid/reviews'),
      api.get<ReidMembershipHold[]>('/reid/membership-holds'),
    ])
    individuals.value = inds
    reports.value = rpts
    reviews.value = revs
    holds.value = hlds
    if (rpts.length) await openReport(rpts[0].id)
  } catch (err) {
    push(err instanceof Error ? err.message : '加载失败', 'error')
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function openReport(id: number) {
  selectedReport.value = await api.get<ReidReportRun>(`/reid/report-runs/${id}`)
}

async function split(ind: ReidIndividual) {
  const raw = (splitGroups.value[ind.id] || '').trim()
  let groups: number[][]
  try {
    groups = JSON.parse(raw)
  } catch {
    return push('拆分分组需为 JSON，如 [[1],[2,3]]', 'error')
  }
  try {
    await api.post(`/reid/individuals/${ind.id}/split`, { groups, reason: '专家复核后拆分确认个体' })
    splitGroups.value[ind.id] = ''
    push('已拆分：受影响首次/重复捕获按新归属重算，旧季报保持冻结')
    await load()
  } catch (err) {
    push(err instanceof Error ? err.message : '拆分失败', 'error')
  }
}

async function resolveReview(rev: ReidReviewEvent, outcome: 'keep' | 'revoke') {
  const reason = (reviewReason.value[rev.id] || '').trim()
  if (!reason) return push('请填写复审结论理由', 'error')
  try {
    await api.post(`/reid/reviews/${rev.id}/resolve`, { outcome, reason })
    reviewReason.value[rev.id] = ''
    push(outcome === 'keep' ? '复审沿用原关系，统计恢复纳入' : '已撤销统计资格')
    await load()
  } catch (err) {
    push(err instanceof Error ? err.message : '复审收口失败', 'error')
  }
}
</script>

<template>
  <div class="stack">
    <div class="card">
      <div class="card-head"><h2>确认个体决策册（{{ individuals.length }}）</h2>
        <span class="chip">个体版本冻结特征/位置/校时版本</span>
      </div>
      <div class="grid grid-2" style="gap: 10px">
        <div v-for="ind in individuals" :key="ind.id" class="ind-card">
          <div class="between">
            <strong class="mono">{{ ind.individual_code }}</strong>
            <span class="badge" :class="ind.status === 'active' ? 'valid' : ind.status === 'under_review' ? 'pending' : 'invalid'">
              {{ ind.status_label }}
            </span>
          </div>
          <div class="tiny muted" style="margin-top: 6px">
            观察 {{ ind.observation_ids.join(', ') || '—' }} · 当前版本 #{{ ind.current_version_id }}
          </div>
          <details v-if="authState.isWriter.value" style="margin-top: 8px">
            <summary class="small" style="cursor: pointer">拆分该个体</summary>
            <div class="flex stack-sm" style="margin-top: 6px">
              <input v-model="splitGroups[ind.id]" class="input grow mono" :placeholder="`如 [[${ind.observation_ids[0]}],[${ind.observation_ids.slice(1).join(',')}]]`" />
              <button class="btn sm" @click="split(ind)">执行拆分</button>
            </div>
            <div class="tiny muted">拆分后重新计算受影响捕获，不复制原捕获次数；无关样线统计不受影响。</div>
          </details>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><h2>样线统计账（季报运行）</h2></div>
      <div class="flex" style="gap: 8px; flex-wrap: wrap">
        <button v-for="r in reports" :key="r.id" class="btn sm"
                :class="selectedReport?.id === r.id ? 'primary' : 'ghost'" @click="openReport(r.id)">
          {{ r.report_code }} · {{ r.status === 'frozen' ? '冻结' : '被替代' }}
        </button>
      </div>
      <div v-if="selectedReport" class="stack-sm" style="margin-top: 12px">
        <div class="grid grid-4" style="gap: 10px">
          <div class="stat"><div class="stat-value">{{ selectedReport.summary.photo_observation_count }}</div><div class="stat-label">照片/观察数</div></div>
          <div class="stat"><div class="stat-value">{{ selectedReport.summary.candidate_count }}</div><div class="stat-label">候选关系数</div></div>
          <div class="stat"><div class="stat-value">{{ selectedReport.summary.statistical_individual_count }}</div><div class="stat-label">统计个体数</div></div>
          <div class="stat"><div class="stat-value">{{ selectedReport.summary.first_capture_count }} / {{ selectedReport.summary.repeat_capture_count }}</div><div class="stat-label">首次 / 重复捕获</div></div>
        </div>
        <div class="small muted">{{ selectedReport.summary.change_note || '首次冻结' }} · 季节窗口 {{ selectedReport.summary.season_window?.join(' 至 ') }}</div>
        <div class="flex" style="gap: 6px; flex-wrap: wrap">
          <span v-for="(n, key) in selectedReport.summary.exclusion_buckets" :key="key" class="chip">{{ key }}：{{ n }}</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>序号</th><th>捕获类型</th><th>个体</th><th>观察</th><th>样线</th><th>日期</th><th>状态</th><th>排除原因</th></tr></thead>
            <tbody>
              <tr v-for="e in selectedReport.entries" :key="e.id">
                <td>{{ e.sequence_no || '—' }}</td>
                <td>{{ e.capture_kind_label }}</td>
                <td class="mono">{{ e.individual_code || '—' }}</td>
                <td class="mono small">{{ e.observation_code }}</td>
                <td>{{ e.station_code }}</td>
                <td>{{ fmtDate(e.survey_date) }}</td>
                <td><span class="badge" :class="e.status === 'included' ? 'valid' : e.status === 'frozen' ? 'pending' : 'neutral'">{{ e.status_label }}</span></td>
                <td class="tiny muted">{{ e.exclusion_reason }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <router-link :to="`/reid/trace/report/${selectedReport.id}`" class="btn ghost sm">查看该季报完整溯源链</router-link>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><h2>复审历史（{{ reviews.length }}）</h2></div>
      <div v-if="!reviews.length" class="empty">暂无复审事件。</div>
      <div v-for="rev in reviews" :key="rev.id" class="review-card">
        <div class="between">
          <div class="small"><span class="chip">{{ rev.trigger_label }}</span> 个体 #{{ rev.individual_id }} · {{ rev.status_label }}</div>
          <span class="tiny muted">{{ fmtDateTime(rev.created_at) }}</span>
        </div>
        <div class="tiny muted" style="margin-top: 4px">{{ rev.resolution || '等待复审结论；旧季报保持其当时采用的统计版本，新统计暂停纳入该个体。' }}</div>
        <template v-if="authState.isWriter.value && rev.status === 'opened'">
          <div class="flex" style="margin-top: 8px; gap: 8px">
            <input v-model="reviewReason[rev.id]" class="input grow" placeholder="复审理由（沿用 / 撤销；修订关系请用拆分）" />
            <button class="btn primary sm" @click="resolveReview(rev, 'keep')">复审沿用</button>
            <button class="btn sm" @click="resolveReview(rev, 'revoke')">撤销资格</button>
          </div>
        </template>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><h2>竞争归属冻结（{{ holds.length }}）</h2></div>
      <div v-if="!holds.length" class="empty">暂无归属冻结。</div>
      <table v-else class="table-wrap">
        <thead><tr><th>冻结观察</th><th>个体 A</th><th>个体 B</th><th>候选</th><th>状态</th><th>原因</th></tr></thead>
        <tbody>
          <tr v-for="h in holds" :key="h.id">
            <td class="mono">#{{ h.observation_id }}</td><td>#{{ h.individual_a_id }}</td><td>#{{ h.individual_b_id }}</td>
            <td class="mono">#{{ h.candidate_id }}</td>
            <td><span class="badge" :class="h.status === 'open' ? 'pending' : 'valid'">{{ h.status === 'open' ? '冻结中' : '已解除' }}</span></td>
            <td class="tiny muted">{{ h.reason }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.ind-card, .review-card { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; background: #fff; }
</style>
