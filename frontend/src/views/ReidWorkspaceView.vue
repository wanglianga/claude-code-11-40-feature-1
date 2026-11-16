<script setup lang="ts">
import { ref } from 'vue'
import ReidObservations from '../components/reid/ReidObservations.vue'
import ReidCandidates from '../components/reid/ReidCandidates.vue'
import ReidLedger from '../components/reid/ReidLedger.vue'

const tab = ref<'observations' | 'candidates' | 'ledger'>('candidates')
const tabs = [
  { key: 'observations', label: '观察与来源簇' },
  { key: 'candidates', label: '候选 · 划分 · 裁定' },
  { key: 'ledger', label: '确认个体与样线统计账' },
] as const
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <div class="eyebrow">Individual Re-identification</div>
        <h1>野生动物个体重识别证据链</h1>
        <p class="page-sub">
          外观相似只产生候选关系，不直接写成同一动物；经专家确认的关系才形成冻结的确认个体版本，
          样线统计账只纳入合规样线—日期的首次/重复捕获。照片数、候选数与统计个体数分别统计。
        </p>
      </div>
    </div>

    <div class="tabs" style="margin-bottom: 14px">
      <button v-for="t in tabs" :key="t.key" class="tab" :class="{ active: tab === t.key }" @click="tab = t.key">
        {{ t.label }}
      </button>
    </div>

    <ReidObservations v-if="tab === 'observations'" />
    <ReidCandidates v-else-if="tab === 'candidates'" />
    <ReidLedger v-else />

    <div class="callout info" style="margin-top: 14px">
      服务只交付个体重识别证据与样线统计纳入数据：不派发巡护，不改变动物管理、捕捉、放归或保护行动。
      时间校正只新建候选、不自动合并；被否决关系是硬约束；授权撤回、哈希不一致、位置修订触发复审，旧季报始终可还原。
    </div>
  </div>
</template>
