<template>
  <q-page class="page-pad">
    <div class="row items-center q-mb-md">
      <div class="text-h5">作业详情 #{{ job?.id || '…' }}</div>
      <q-space />
      <q-btn flat icon="refresh" label="刷新" @click="load" :loading="loading" />
      <q-btn flat label="返回历史" to="/jobs" />
    </div>

    <q-banner v-if="job" rounded class="q-mb-md" :class="statusBannerClass">
      状态：{{ statusLabel(job.status) }}
      · 样例：{{ job.sample_name }}
      · 提交人：{{ job.created_by }}
      <div v-if="job.error_message" class="q-mt-sm">失败原因：{{ job.error_message }}</div>
    </q-banner>

    <div class="text-subtitle1 q-mb-sm">Actor 阶段时间线</div>
    <q-timeline color="primary" class="q-mb-lg">
      <q-timeline-entry
        v-for="s in stages"
        :key="s.id"
        :title="s.actor_name"
        :subtitle="stageSubtitle(s)"
        :color="stageColor(s.status)"
        :icon="stageIcon(s.status)"
      >
        <div>{{ s.message || '—' }}</div>
      </q-timeline-entry>
    </q-timeline>

    <div class="text-subtitle1 q-mb-sm">质控指标</div>
    <div class="row q-col-gutter-md" v-if="metrics">
      <div class="col-12 col-sm-3" v-for="m in metricCards" :key="m.label">
        <q-card flat bordered class="metric-card">
          <q-card-section>
            <div class="text-caption text-grey-7">{{ m.label }}</div>
            <div class="text-h5">{{ m.value }}</div>
          </q-card-section>
        </q-card>
      </div>
    </div>
    <div v-else class="text-grey-6 q-mb-lg">尚无指标（作业未成功完成或仍在运行）</div>

    <!-- 质量曲线与弱位点 -->
    <div class="row items-center q-mt-md q-mb-sm">
      <div class="text-subtitle1">逐位点质量曲线与弱位点</div>
      <q-space />
      <div class="text-caption text-grey-7 q-mr-md">
        当前下限：Q{{ configFloor ?? '—' }}
        <template v-if="appliedFloor !== null && configFloor !== null && Number(appliedFloor) !== Number(configFloor)">
          <q-icon name="warning" color="orange-9" size="16px" class="q-ml-sm" />
          清单基于旧下限 Q{{ appliedFloor }}，重算后更新
        </template>
      </div>
      <q-btn
        v-if="auth.role === 'bioops'"
        dense
        flat
        color="primary"
        icon="tune"
        label="配置下限"
        :disable="!configLoaded"
        @click="openConfigDialog"
      />
      <q-btn
        v-if="auth.role === 'bioops' && job?.status === 'success'"
        dense
        unelevated
        color="primary"
        icon="calculate"
        label="按当前阈值重算清单"
        class="q-ml-sm"
        :loading="recomputing"
        @click="recompute"
      />
    </div>

    <q-card flat bordered class="q-mb-lg">
      <q-card-section>
        <template v-if="hasPerPosition">
          <QualityCurveChart
            :points="perPosition"
            :weak-positions="weakPositions"
            :floor="chartFloor"
          />

          <div class="row items-baseline q-mt-md q-mb-sm">
            <div class="text-subtitle2">弱位点清单</div>
            <span class="q-ml-md text-caption text-grey-7">
              共 {{ weakPositions.length }} 个 · 判定规则：位点平均质量 &lt; Q{{ appliedFloor ?? chartFloor }}（由服务端计算）
            </span>
          </div>
          <q-markup-table v-if="weakPositions.length" flat dense class="weak-table">
            <thead>
              <tr>
                <th class="text-left">位点（bp）</th>
                <th class="text-left">平均质量</th>
                <th class="text-left">与下限差值</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="w in weakPositions" :key="w.position">
                <td>{{ w.position }}</td>
                <td>{{ w.mean_quality }}</td>
                <td class="text-negative">−{{ gap(w) }}</td>
              </tr>
            </tbody>
          </q-markup-table>
          <q-banner v-else rounded class="bg-grey-2 text-grey-8">
            当前阈值下无弱位点（所有位点平均质量 ≥ Q{{ appliedFloor ?? chartFloor }}）。
          </q-banner>
        </template>
        <q-banner v-else rounded class="bg-orange-1 text-orange-10">
          <template v-if="job && job.status === 'failed'">
            该作业失败，无 per_position 数据，无法展示质量曲线与弱位点清单。
          </template>
          <template v-else>
            尚无 per_position 数据（作业未成功完成或仍在运行）。
          </template>
        </q-banner>
        <div v-if="auth.role !== 'bioops'" class="text-caption text-grey-6 q-mt-sm">
          审计员账号只读：可查看弱位点清单，阈值配置与重算仅运维可操作。
        </div>
      </q-card-section>
    </q-card>

    <!-- 运维配置下限 -->
    <q-dialog v-model="configDialog" persistent>
      <q-card style="min-width: 360px">
        <q-card-section class="text-subtitle1">配置弱位点平均质量下限</q-card-section>
        <q-card-section class="q-pt-none">
          <q-input
            v-model.number="draftFloor"
            type="number"
            label="平均质量下限（0–93）"
            hint="位点平均质量严格低于该值即记为弱位点；保存后对新作业立即生效"
            :rules="[v => v !== null && v !== '' && v >= 0 && v <= 93 || '请输入 0–93 的数值']"
            outlined
            dense
            autofocus
          />
          <q-toggle
            v-model="applyAll"
            class="q-mt-md"
            label="同时重算全部已成功作业的弱位点清单"
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="取消" @click="configDialog = false" :disable="saving" />
          <q-btn unelevated color="primary" label="保存" :loading="saving" @click="saveConfig" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useQuasar } from 'quasar'
import {
  getJob,
  getJobStages,
  getQualityConfig,
  recomputeJobWeak,
  updateQualityConfig,
} from '../api/client'
import { useAuthStore } from '../stores/auth'
import QualityCurveChart from '../components/QualityCurveChart.vue'

const route = useRoute()
const $q = useQuasar()
const auth = useAuthStore()
const loading = ref(false)
const recomputing = ref(false)
const job = ref(null)
const stages = ref([])
let timer = null

const configFloor = ref(null)
const configLoaded = ref(false)
const configDialog = ref(false)
const draftFloor = ref(28)
const applyAll = ref(false)
const saving = ref(false)

const metrics = computed(() => job.value?.metrics || null)
const perPosition = computed(() => metrics.value?.per_position || [])
const weakPositions = computed(() => metrics.value?.weak_positions || [])
const hasPerPosition = computed(
  () => job.value?.status === 'success' && perPosition.value.length > 0,
)
const appliedFloor = computed(() => {
  const v = metrics.value?.weak_quality_floor
  return v === undefined || v === null ? null : Number(v)
})
// 绘图阈值线优先用清单实际采用的下限，否则用全局配置
const chartFloor = computed(() =>
  appliedFloor.value !== null ? appliedFloor.value : Number(configFloor.value ?? 28),
)

const metricCards = computed(() => {
  const m = metrics.value
  if (!m) return []
  return [
    { label: 'reads', value: m.reads ?? m.summary?.reads ?? '—' },
    { label: 'mean_quality', value: m.mean_quality ?? m.summary?.mean_quality ?? '—' },
    { label: 'n_rate', value: m.n_rate ?? m.summary?.n_rate ?? '—' },
    {
      label: 'weak_positions',
      value: weakPositions.value.length,
    },
  ]
})

function gap(w) {
  const floor = appliedFloor.value
  if (floor === null) return '—'
  return (floor - Number(w.mean_quality)).toFixed(3)
}

const statusBannerClass = computed(() => {
  const s = job.value?.status
  if (s === 'success') return 'bg-positive text-white'
  if (s === 'failed') return 'bg-negative text-white'
  if (s === 'running') return 'bg-info text-dark'
  return 'bg-grey-3'
})

function statusLabel(s) {
  return { pending: '排队中', running: '运行中', success: '成功', failed: '失败' }[s] || s
}

function stageColor(status) {
  return (
    {
      pending: 'grey',
      running: 'info',
      success: 'positive',
      failed: 'negative',
      skipped: 'warning',
    }[status] || 'grey'
  )
}

function stageIcon(status) {
  return (
    {
      pending: 'hourglass_empty',
      running: 'play_circle',
      success: 'check_circle',
      failed: 'error',
      skipped: 'skip_next',
    }[status] || 'circle'
  )
}

function stageSubtitle(s) {
  const parts = [statusLabel(s.status) || s.status]
  if (s.started_at) parts.push(`开始 ${formatTime(s.started_at)}`)
  if (s.finished_at) parts.push(`结束 ${formatTime(s.finished_at)}`)
  return parts.join(' · ')
}

function formatTime(iso) {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

async function loadConfig() {
  try {
    const cfg = await getQualityConfig()
    configFloor.value = cfg.weak_quality_floor
    configLoaded.value = true
  } catch (e) {
    // 非致命：绘图仍可使用作业内保存的阈值
    configLoaded.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const id = route.params.id
    job.value = await getJob(id)
    stages.value = await getJobStages(id)
    await loadConfig()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '加载失败' })
  } finally {
    loading.value = false
  }
}

function openConfigDialog() {
  draftFloor.value = configFloor.value ?? 28
  applyAll.value = false
  configDialog.value = true
}

async function saveConfig() {
  const v = Number(draftFloor.value)
  if (!Number.isFinite(v) || v < 0 || v > 93) {
    $q.notify({ type: 'negative', message: '请输入 0–93 的数值' })
    return
  }
  saving.value = true
  try {
    const cfg = await updateQualityConfig({
      weak_quality_floor: v,
      apply_to_successful_jobs: applyAll.value,
    })
    configFloor.value = cfg.weak_quality_floor
    configDialog.value = false
    $q.notify({
      type: 'positive',
      message: applyAll.value ? '下限已保存，全部成功作业清单已重算' : '下限已保存，对新作业生效；可点“重算清单”更新本作业',
    })
    await load()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '保存失败' })
  } finally {
    saving.value = false
  }
}

async function recompute() {
  recomputing.value = true
  try {
    job.value = await recomputeJobWeak(route.params.id)
    await loadConfig()
    $q.notify({ type: 'positive', message: '弱位点清单已按当前阈值重算' })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '重算失败' })
  } finally {
    recomputing.value = false
  }
}

onMounted(async () => {
  await load()
  timer = setInterval(async () => {
    if (job.value && (job.value.status === 'pending' || job.value.status === 'running')) {
      await load()
    }
  }, 1500)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>
