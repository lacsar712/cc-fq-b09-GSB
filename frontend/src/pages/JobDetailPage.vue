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
    <div v-else class="text-grey-6">尚无指标（作业未成功完成或仍在运行）</div>

    <div class="text-subtitle1 q-mt-lg q-mb-sm">质量曲线与弱位点</div>
    <div class="row q-col-gutter-md">
      <div class="col-12 col-md-7">
        <q-card flat bordered>
          <q-card-section>
            <div class="text-subtitle2 q-mb-sm">per_position 平均质量曲线</div>
            <quality-curve
              v-if="perPosition.length"
              :points="perPosition"
              :threshold="weakThresholdUsed"
              :weak="weakPositions"
            />
            <div v-else class="text-grey-6">
              无 per_position 数据（作业失败、未产生质量统计或仍在运行）
            </div>
          </q-card-section>
        </q-card>
      </div>

      <div class="col-12 col-md-5">
        <q-card flat bordered>
          <q-card-section>
            <div class="row items-center q-mb-sm">
              <div class="text-subtitle2">弱位点清单</div>
              <q-space />
              <q-chip v-if="weakThresholdUsed != null" dense outline color="primary">
                阈值 Q &lt; {{ weakThresholdUsed }}
              </q-chip>
            </div>
            <div class="text-caption text-grey-7 q-mb-sm">
              由服务端按平均质量下限判定并写入指标，前端仅展示，不自行扫描。
            </div>

            <div v-if="auth.role === 'bioops'" class="row items-center q-gutter-sm q-mb-md">
              <q-input
                v-model.number="thresholdInput"
                type="number"
                dense
                outlined
                label="新阈值"
                min="0"
                max="93"
                step="0.5"
                style="width: 110px"
              />
              <q-btn
                dense
                color="primary"
                label="保存阈值"
                :loading="savingThreshold"
                @click="saveThreshold"
              />
              <q-btn
                dense
                outline
                color="primary"
                label="重算弱位点"
                :loading="recomputing"
                :disable="job?.status !== 'success'"
                @click="recomputeWeak"
              />
            </div>
            <div v-else class="text-caption text-grey-7 q-mb-md">
              审计员只读：可查看清单，不可修改阈值。
            </div>

            <template v-if="hasWeakMetrics">
              <q-markup-table v-if="weakPositions.length" flat dense class="weak-table">
                <thead>
                  <tr>
                    <th class="text-left">位点</th>
                    <th class="text-left">平均质量</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="w in weakPositions" :key="w.position">
                    <td>{{ w.position }}</td>
                    <td class="text-negative">{{ w.mean_quality }}</td>
                  </tr>
                </tbody>
              </q-markup-table>
              <div v-else class="text-positive">当前阈值下无弱位点</div>
            </template>
            <div v-else class="text-grey-6">
              无数据：作业未成功产生 per_position 指标，暂无弱位点清单。
            </div>
          </q-card-section>
        </q-card>
      </div>
    </div>
  </q-page>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useQuasar } from 'quasar'
import {
  getJob,
  getJobStages,
  getWeakThresholdConfig,
  recomputeWeakPositions,
  updateWeakThreshold,
} from '../api/client'
import { useAuthStore } from '../stores/auth'
import QualityCurve from '../components/QualityCurve.vue'

const route = useRoute()
const $q = useQuasar()
const auth = useAuthStore()
const loading = ref(false)
const job = ref(null)
const stages = ref([])
const thresholdInput = ref(null)
const savingThreshold = ref(false)
const recomputing = ref(false)
let timer = null

const metrics = computed(() => job.value?.metrics || null)

const metricCards = computed(() => {
  const m = metrics.value
  if (!m) return []
  return [
    { label: 'reads', value: m.reads ?? m.summary?.reads ?? '—' },
    { label: 'mean_quality', value: m.mean_quality ?? m.summary?.mean_quality ?? '—' },
    { label: 'n_rate', value: m.n_rate ?? m.summary?.n_rate ?? '—' },
    { label: '弱位点数', value: Array.isArray(m.weak_positions) ? m.weak_positions.length : '—' },
  ]
})

const perPosition = computed(() => metrics.value?.per_position || [])

// 弱位点只认服务端写入的 metrics.weak_positions，前端绝不自行扫描 per_position
const weakPositions = computed(() =>
  Array.isArray(metrics.value?.weak_positions) ? metrics.value.weak_positions : [],
)
const weakThresholdUsed = computed(() => metrics.value?.weak_threshold ?? null)
const hasWeakMetrics = computed(() => Array.isArray(metrics.value?.weak_positions))

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

async function load() {
  loading.value = true
  try {
    const id = route.params.id
    job.value = await getJob(id)
    stages.value = await getJobStages(id)
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '加载失败' })
  } finally {
    loading.value = false
  }
}

async function loadThresholdConfig() {
  try {
    const cfg = await getWeakThresholdConfig()
    thresholdInput.value = cfg.threshold
  } catch {
    // 配置读取失败不阻塞详情页
  }
}

async function saveThreshold() {
  const t = Number(thresholdInput.value)
  if (!Number.isFinite(t) || t < 0 || t > 93) {
    $q.notify({ type: 'warning', message: '阈值需为 0–93 之间的数值' })
    return
  }
  savingThreshold.value = true
  try {
    const cfg = await updateWeakThreshold(t)
    thresholdInput.value = cfg.threshold
    $q.notify({
      type: 'positive',
      message: `阈值已保存为 ${cfg.threshold}，点击“重算弱位点”刷新本作业清单`,
    })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '保存阈值失败' })
  } finally {
    savingThreshold.value = false
  }
}

async function recomputeWeak() {
  recomputing.value = true
  try {
    // 服务端按当前阈值重算并返回整份作业，直接替换本地数据
    job.value = await recomputeWeakPositions(route.params.id)
    const n = job.value?.metrics?.weak_positions?.length ?? 0
    $q.notify({ type: 'positive', message: `已按当前阈值重算，弱位点 ${n} 个` })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '重算失败' })
  } finally {
    recomputing.value = false
  }
}

onMounted(async () => {
  await Promise.all([load(), loadThresholdConfig()])
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

<style scoped>
.weak-table {
  max-height: 320px;
  overflow-y: auto;
}
</style>
