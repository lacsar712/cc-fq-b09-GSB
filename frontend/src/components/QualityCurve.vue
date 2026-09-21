<template>
  <div class="quality-curve">
    <svg
      :viewBox="`0 0 ${W} ${H}`"
      width="100%"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="per_position 平均质量曲线"
    >
      <!-- 坐标轴 -->
      <line :x1="padL" :y1="padT" :x2="padL" :y2="H - padB" stroke="#9e9e9e" stroke-width="1" />
      <line
        :x1="padL"
        :y1="H - padB"
        :x2="W - padR"
        :y2="H - padB"
        stroke="#9e9e9e"
        stroke-width="1"
      />
      <!-- 轴刻度标签 -->
      <text :x="padL - 6" :y="y(0) + 4" text-anchor="end" class="axis-label">0</text>
      <text :x="padL - 6" :y="y(yMax) + 4" text-anchor="end" class="axis-label">{{ yMax }}</text>
      <text :x="padL" :y="H - 6" text-anchor="middle" class="axis-label">{{ minPos }}</text>
      <text :x="W - padR" :y="H - 6" text-anchor="middle" class="axis-label">{{ maxPos }}</text>

      <!-- 阈值线（服务端当前生效阈值） -->
      <template v-if="threshold != null">
        <line
          :x1="padL"
          :y1="y(threshold)"
          :x2="W - padR"
          :y2="y(threshold)"
          stroke="#f2c037"
          stroke-width="1.5"
          stroke-dasharray="6 4"
        />
        <text :x="W - padR" :y="y(threshold) - 4" text-anchor="end" class="threshold-label">
          阈值 {{ threshold }}
        </text>
      </template>

      <!-- 平均质量曲线 -->
      <polyline :points="polyline" fill="none" stroke="#1976d2" stroke-width="2" />

      <!-- 弱位点（来自服务端 weak_positions，非前端计算） -->
      <circle
        v-for="w in weakPoints"
        :key="w.position"
        :cx="x(w.position)"
        :cy="y(w.mean_quality)"
        r="3.5"
        fill="#c10015"
      >
        <title>位点 {{ w.position }} · 平均质量 {{ w.mean_quality }}</title>
      </circle>
    </svg>
    <div class="text-caption text-grey-7 q-mt-xs">
      蓝线：各位点平均质量 · 黄虚线：弱位点阈值 · 红点：服务端判定的弱位点
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  // per_position: [{ position, mean_quality }]
  points: { type: Array, default: () => [] },
  threshold: { type: Number, default: null },
  // 服务端 metrics.weak_positions，前端仅展示，不自行扫描
  weak: { type: Array, default: () => [] },
})

const W = 640
const H = 240
const padL = 40
const padR = 16
const padT = 16
const padB = 28

const sorted = computed(() =>
  [...props.points]
    .filter((p) => p && p.mean_quality != null)
    .sort((a, b) => a.position - b.position),
)

const minPos = computed(() => (sorted.value.length ? sorted.value[0].position : 1))
const maxPos = computed(() =>
  sorted.value.length ? sorted.value[sorted.value.length - 1].position : 1,
)

const yMax = computed(() => {
  const peak = Math.max(
    40,
    ...sorted.value.map((p) => p.mean_quality),
    props.threshold ?? 0,
  )
  return Math.ceil(peak + 5)
})

const weakPoints = computed(() => props.weak || [])

function x(position) {
  const span = maxPos.value - minPos.value
  const ratio = span > 0 ? (position - minPos.value) / span : 0
  return padL + ratio * (W - padL - padR)
}

function y(quality) {
  const q = Math.max(0, Math.min(quality, yMax.value))
  return padT + (1 - q / yMax.value) * (H - padT - padB)
}

const polyline = computed(() =>
  sorted.value.map((p) => `${x(p.position)},${y(p.mean_quality)}`).join(' '),
)
</script>

<style scoped>
.quality-curve {
  width: 100%;
}
.axis-label {
  font-size: 11px;
  fill: #757575;
}
.threshold-label {
  font-size: 11px;
  fill: #b8860b;
}
</style>
