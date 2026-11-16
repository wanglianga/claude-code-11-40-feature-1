<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
import { fmtDateTime } from '../format'

const route = useRoute()
const data = ref<any>(null)
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    if (route.params.kind === 'observation') {
      data.value = await api.get(`/reid/observations/${route.params.id}/trace`)
    } else {
      data.value = await api.get(`/reid/report-runs/${route.params.id}/trace`)
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(load)
watch(() => route.fullPath, load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <div class="eyebrow">Re-identification Trace</div>
        <h1>重识别证据溯源链</h1>
        <p class="page-sub">
          从一个统计个体数量或单张观察回到原始素材、候选关系、来源独立性、专家决策、冻结版本、
          样线纳入记录与复审历史；每个环节均保留引用关系，可逐层核对。
        </p>
      </div>
      <router-link to="/reid" class="btn ghost">返回工作区</router-link>
    </div>

    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="error" class="callout danger">{{ error }}</div>

    <div v-else-if="data" class="stack">
      <!-- 观察溯源 -->
      <template v-if="route.params.kind === 'observation'">
        <div class="card">
          <div class="card-head"><h2>原始观察</h2><span class="chip mono">{{ data.observation.observation_code }}</span></div>
          <div class="grid grid-4" style="gap: 10px">
            <div class="kv"><span class="muted tiny">文件哈希</span><span class="hash mono small">{{ data.observation.file_hash }}</span></div>
            <div class="kv"><span class="muted tiny">采集/有效时间</span><span class="small">{{ fmtDateTime(data.observation.effective_observed_at) }}</span></div>
            <div class="kv"><span class="muted tiny">接收时间</span><span class="small">{{ fmtDateTime(data.observation.received_at) }}</span></div>
            <div class="kv"><span class="muted tiny">样线</span><span>{{ data.observation.station_code }}</span></div>
            <div class="kv"><span class="muted tiny">姿态质量</span><span>{{ data.observation.posture_quality }}</span></div>
            <div class="kv"><span class="muted tiny">授权状态</span><span>{{ data.observation.authorization_status }}</span></div>
            <div class="kv"><span class="muted tiny">特征/位置/校时版本</span>
              <span class="small mono">{{ data.observation.feature_version_id }} / {{ data.observation.location_version_id }} / {{ data.observation.time_correction_id }}</span>
            </div>
            <div class="kv"><span class="muted tiny">可见特征</span><span class="small mono">{{ JSON.stringify(data.observation.visible_features) }}</span></div>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><h2>来源独立性</h2></div>
          <div v-if="data.source_cluster" class="small">
            归属来源簇 <span class="chip">{{ data.source_cluster.cluster_kind_label }}</span>
            {{ data.source_cluster.rationale }}；同簇素材 {{ data.source_cluster_siblings.map((o: any) => o.observation_code).join('、') || '无' }}
            只作为同一来源，不互成重识别候选。
          </div>
          <div v-else class="empty">独立来源，与其他素材无连拍/裁剪/同哈希关系。</div>
        </div>

        <div class="card">
          <div class="card-head"><h2>候选关系与专家决策（{{ data.candidates.length }}）</h2></div>
          <div v-for="c in data.candidates" :key="c.id" class="trace-block">
            <div class="between">
              <span class="mono small">{{ c.observation_a_code }} ⇄ {{ c.observation_b_code }}</span>
              <span class="badge" :class="c.status === 'confirmed' ? 'valid' : c.status === 'rejected' ? 'invalid' : 'pending'">{{ c.status_label }}</span>
            </div>
            <div class="tiny muted">特征相似度 {{ c.feature_score }} · 时空可达 {{ c.spatial_reachable ? '是' : '否' }} · 来源独立 {{ c.source_independent ? '是' : '否' }}</div>
            <div v-for="d in data.decisions.filter((x: any) => x.candidate_id === c.id)" :key="d.id" class="decision small">
              <span class="chip">{{ d.expert }} · {{ d.verdict_label }}</span>
              <span>{{ d.reason }}</span>
              <span class="tiny muted">冻结 {{ JSON.stringify(d.frozen_versions) }}</span>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><h2>个体版本 / 捕获纳入 / 复审 / 冻结</h2></div>
          <div class="small muted">确认个体版本：{{ data.individual_versions.length }} 个</div>
          <div v-for="v in data.individual_versions" :key="v.id" class="trace-block small">
            个体 #{{ v.individual_id }} 版本 v{{ v.version_number }}（{{ v.status }}）— {{ v.change_reason }}
          </div>
          <div class="small muted" style="margin-top: 8px">样线捕获记录：{{ data.capture_entries.length }} 条</div>
          <div v-for="e in data.capture_entries" :key="e.id" class="trace-block small">
            季报 #{{ e.report_run_id }} · {{ e.capture_kind_label }} · {{ e.status_label }}
            <span v-if="e.exclusion_reason" class="muted">（{{ e.exclusion_reason }}）</span>
          </div>
          <div class="small muted" style="margin-top: 8px">复审事件：{{ data.review_events.length }} · 归属冻结：{{ data.membership_holds.length }}</div>
        </div>
      </template>

      <!-- 季报溯源 -->
      <template v-else>
        <div class="card">
          <div class="card-head"><h2>{{ data.run.report_code }}</h2>
            <span class="chip">{{ data.run.status === 'frozen' ? '冻结季报' : '已被替代' }}</span>
          </div>
          <div class="grid grid-4" style="gap: 10px">
            <div class="stat"><div class="stat-value">{{ data.run.summary.statistical_individual_count }}</div><div class="stat-label">统计个体数</div></div>
            <div class="stat"><div class="stat-value">{{ data.run.summary.photo_observation_count }}</div><div class="stat-label">观察数</div></div>
            <div class="stat"><div class="stat-value">{{ data.run.summary.candidate_count }}</div><div class="stat-label">候选数</div></div>
            <div class="stat"><div class="stat-value">{{ data.run.summary.first_capture_count }}/{{ data.run.summary.repeat_capture_count }}</div><div class="stat-label">首次/重复</div></div>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><h2>① 确认个体与冻结版本（{{ data.individuals.length }}）</h2></div>
          <div v-for="(ind, idx) in data.individuals" :key="ind.id" class="trace-block">
            <div class="between small">
              <span class="mono">{{ ind.individual_code }} · {{ ind.status_label }}</span>
              <span class="tiny muted">观察 {{ data.individual_versions[idx]?.observation_ids.join(', ') }}</span>
            </div>
            <div class="tiny muted">冻结版本：{{ JSON.stringify(data.individual_versions[idx]?.frozen_versions) }}</div>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><h2>② 专家决策与候选关系（{{ data.decisions.length }} 决策 / {{ data.candidates.length }} 候选）</h2></div>
          <div v-for="d in data.decisions" :key="d.id" class="trace-block small">
            <span class="chip">{{ d.expert }} · {{ d.verdict_label }}</span>
            <span>候选 #{{ d.candidate_id }}：{{ d.reason }}</span>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><h2>③ 样线捕获纳入记录（{{ data.entries.length }}）</h2></div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>序号</th><th>类型</th><th>个体</th><th>观察</th><th>样线</th><th>日期</th><th>状态</th></tr></thead>
              <tbody>
                <tr v-for="e in data.entries" :key="e.id">
                  <td>{{ e.sequence_no || '—' }}</td><td>{{ e.capture_kind_label }}</td>
                  <td class="mono">{{ e.individual_code || '—' }}</td>
                  <td class="mono small">{{ e.observation_code }}</td><td>{{ e.station_code }}</td>
                  <td>{{ e.survey_date }}</td><td>{{ e.status_label }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><h2>④ 复审历史（{{ data.review_events.length }}）</h2></div>
          <div v-if="!data.review_events.length" class="empty">该季报采用的个体版本无复审记录。</div>
          <div v-for="r in data.review_events" :key="r.id" class="trace-block small">
            <span class="chip">{{ r.trigger_label }}</span> 个体 #{{ r.individual_id }} · {{ r.status_label }}
            <span class="muted">— {{ r.resolution || '复审中，旧季报仍保持原统计版本' }}</span>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.trace-block { border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; margin-top: 8px; background: #fff; }
.decision { display: flex; gap: 8px; align-items: center; margin-top: 6px; flex-wrap: wrap; }
</style>
