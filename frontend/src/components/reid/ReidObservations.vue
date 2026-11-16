<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../../api'
import { useToast } from '../../toast'
import { authState } from '../../session'
import type { ReidObservation, ReidSourceCluster } from '../../types'
import { fmtDateTime } from '../../format'

const { push } = useToast()
const observations = ref<ReidObservation[]>([])
const clusters = ref<ReidSourceCluster[]>([])
const stations = ref<Array<{ id: number; code: string }>>([])
const loading = ref(true)
const filterStation = ref<number | ''>('')

const form = ref({
  species_code: 'CERVUS',
  external_ref: '',
  station_id: '' as number | '',
  observed_at: '2026-04-15T08:00',
  posture_quality: 'good',
  features: '{"stripe_pattern": ["sp-x"], "coat_color": "brown"}',
  season_code: '2026-SPRING',
  burst_group: '',
  derived_from_observation_id: '' as number | '',
  interpretability: 'interpretable' as 'interpretable' | 'unreadable',
})
const actionReason = ref<Record<number, string>>({})
const expectedHash = ref<Record<number, string>>({})

async function load() {
  loading.value = true
  try {
    const [obs, cls, st] = await Promise.all([
      api.get<{ total: number; items: ReidObservation[] }>(
        `/reid/observations?limit=300${filterStation.value ? `&station_id=${filterStation.value}` : ''}`,
      ),
      api.get<ReidSourceCluster[]>('/reid/source-clusters'),
      api.get<Array<{ id: number; code: string }>>('/stations'),
    ])
    observations.value = obs.items
    clusters.value = cls
    stations.value = st
  } catch (err) {
    push(err instanceof Error ? err.message : '加载失败', 'error')
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function register() {
  let visible_features: Record<string, any> = {}
  try {
    visible_features = JSON.parse(form.value.features || '{}')
  } catch {
    push('可见特征必须是合法 JSON', 'error')
    return
  }
  try {
    await api.post('/reid/observations', {
      species_code: form.value.species_code,
      external_ref: form.value.external_ref,
      station_id: Number(form.value.station_id),
      observed_at: form.value.observed_at + ':00+08:00',
      received_time: new Date().toISOString(),
      posture_quality: form.value.posture_quality,
      posture_score: 0.9,
      visible_features,
      season_code: form.value.season_code,
      interpretability: form.value.interpretability,
      burst_group: form.value.burst_group || null,
      derived_from_observation_id: form.value.derived_from_observation_id || null,
    })
    push('观察已登记，来源簇按连拍/裁剪/同哈希规则自动归并')
    form.value.external_ref = ''
    await load()
  } catch (err) {
    push(err instanceof Error ? err.message : '登记失败', 'error')
  }
}

async function withdraw(o: ReidObservation) {
  const reason = (actionReason.value[o.id] || '').trim()
  if (!reason) return push('请填写授权撤回原因', 'error')
  try {
    await api.post(`/reid/observations/${o.id}/withdraw`, { reason })
    actionReason.value[o.id] = ''
    push('授权已撤回，相关个体版本转入复审，新统计暂停纳入')
    await load()
  } catch (err) {
    push(err instanceof Error ? err.message : '撤回失败', 'error')
  }
}

async function hashMismatch(o: ReidObservation) {
  const expected = (expectedHash.value[o.id] || '').trim()
  if (expected.length < 8) return push('请填写复核得到的完整期望哈希', 'error')
  try {
    await api.post(`/reid/observations/${o.id}/hash-mismatch`, { expected_hash: expected })
    expectedHash.value[o.id] = ''
    push('哈希不一致已立案，个体版本转入复审')
    await load()
  } catch (err) {
    push(err instanceof Error ? err.message : '立案失败', 'error')
  }
}
</script>

<template>
  <div class="stack">
    <div v-if="authState.isWriter.value" class="card">
      <div class="card-head"><h2>登记独立观察</h2><span class="chip">照片 / 足迹 / 人工观察</span></div>
      <div class="grid grid-4" style="gap: 10px">
        <label class="field small">外部素材编号
          <input v-model="form.external_ref" class="input" placeholder="DEER-..." />
        </label>
        <label class="field small">物种
          <input v-model="form.species_code" class="input" />
        </label>
        <label class="field small">相机/样线
          <select v-model="form.station_id" class="select input">
            <option :value="''" disabled>选择站点</option>
            <option v-for="s in stations" :key="s.id" :value="s.id">{{ s.code }}</option>
          </select>
        </label>
        <label class="field small">采集时间
          <input v-model="form.observed_at" type="datetime-local" class="input" />
        </label>
        <label class="field small">姿态质量
          <select v-model="form.posture_quality" class="select input">
            <option value="good">good</option><option value="medium">medium</option><option value="poor">poor</option>
          </select>
        </label>
        <label class="field small">连拍组号（可空）
          <input v-model="form.burst_group" class="input" placeholder="同连拍序列" />
        </label>
        <label class="field small">裁剪自观察 id（可空）
          <input v-model.number="form.derived_from_observation_id" type="number" class="input" />
        </label>
        <label class="field small">判读性
          <select v-model="form.interpretability" class="select input">
            <option value="interpretable">可判读</option><option value="unreadable">无法判读</option>
          </select>
        </label>
      </div>
      <label class="field small" style="margin-top: 8px">可见特征 JSON（斑纹/伤痕/体色）
        <input v-model="form.features" class="input mono" />
      </label>
      <div class="flex" style="margin-top: 10px">
        <button class="btn primary sm" @click="register">登记观察</button>
        <span class="tiny muted">原始文件哈希自动计算；同哈希/连拍/裁剪只进入同一来源簇，不产生重识别候选。</span>
      </div>
    </div>

    <div class="card">
      <div class="card-head">
        <h2>观察档案（{{ observations.length }}）</h2>
        <select v-model="filterStation" class="select input" style="width: 160px" @change="load">
          <option :value="''">全部样线</option>
          <option v-for="s in stations" :key="s.id" :value="s.id">{{ s.code }}</option>
        </select>
      </div>
      <div v-if="loading" class="loading">加载中…</div>
      <div v-else class="table-wrap">
        <table>
          <thead><tr>
            <th>编号</th><th>素材</th><th>样线</th><th>有效采集时间</th><th>姿态</th>
            <th>来源簇</th><th>授权/判读</th><th>文件哈希</th><th>变动监测</th>
          </tr></thead>
          <tbody>
            <tr v-for="o in observations" :key="o.id">
              <td class="mono">{{ o.observation_code }}<div class="tiny muted">#{{ o.id }}</div></td>
              <td class="small">{{ o.external_ref }}<div class="tiny muted">{{ o.observation_kind }}</div></td>
              <td>{{ o.station_code }}</td>
              <td class="small">{{ fmtDateTime(o.effective_observed_at) }}
                <div v-if="o.corrected_observed_at" class="tiny" style="color: #b06a00">已校时</div>
              </td>
              <td><span class="badge neutral">{{ o.posture_quality }}</span></td>
              <td>
                <span v-if="o.source_cluster_id" class="chip">{{ o.source_cluster?.cluster_kind_label || '同簇' }}</span>
                <span v-else class="tiny muted">独立</span>
              </td>
              <td>
                <span class="badge" :class="o.authorization_status === 'withdrawn' ? 'invalid' : 'valid'">
                  {{ o.authorization_status === 'withdrawn' ? '授权撤回' : '授权有效' }}
                </span>
                <div v-if="o.interpretability === 'unreadable'" class="badge pending" style="margin-top: 4px">无法判读</div>
              </td>
              <td class="hash mono tiny">{{ o.file_hash.slice(0, 16) }}…</td>
              <td>
                <router-link :to="`/reid/trace/observation/${o.id}`" class="btn ghost sm">溯源链</router-link>
                <template v-if="authState.isWriter.value && o.authorization_status === 'authorized'">
                  <div class="flex stack-sm" style="margin-top: 6px">
                    <input v-model="actionReason[o.id]" class="input sm" placeholder="撤回原因" />
                    <button class="btn sm" @click="withdraw(o)">撤回授权</button>
                    <input v-model="expectedHash[o.id]" class="input sm" placeholder="期望哈希" />
                    <button class="btn sm" @click="hashMismatch(o)">哈希不一致</button>
                  </div>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><h2>来源簇（{{ clusters.length }}）</h2></div>
      <div class="grid grid-3" style="gap: 10px">
        <div v-for="c in clusters" :key="c.id" class="source-card">
          <div class="between"><span class="chip">{{ c.cluster_kind_label }}</span><span class="tiny muted">{{ c.member_count }} 个素材</span></div>
          <div class="small mono" style="margin-top: 4px">{{ c.cluster_code }}</div>
          <div class="tiny muted" style="margin-top: 4px">{{ c.rationale }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.source-card { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fff; }
.input.sm { min-width: 120px; }
</style>
