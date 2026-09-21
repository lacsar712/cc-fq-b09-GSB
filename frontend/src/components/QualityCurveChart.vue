<template>
  <div class="qc-chart" ref="wrapRef">
    <div class="qc-legend text-caption">
      <span class="qc-legend-item">
        <svg class="qc-key" width="22" height="8" aria-hidden="true">
          <line x1="0" y1="4" x2="22" y2="4" stroke="#2a78d6" stroke-width="2" stroke-linecap="round" />
        </svg>
        位点平均质量
      </span>
      <span class="qc-legend-item">
        <svg class="qc-key" width="22" height="8" aria-hidden="true">
          <line x1="0" y1="4" x2="22" y2="4" stroke="#d03b3b" stroke-width="1.5" stroke-dasharray="5 3" />
        </svg>
        弱位点下限（Q{{ floor }}）
      </span>
      <span class="qc-legend-item">
        <svg class="qc-key" width="10" height="10" aria-hidden="true">
          <circle cx="5" cy="5" r="4" fill="#d03b3b" stroke="#fcfcfb" stroke-width="2" />
        </svg>
        弱位点（服务端清单）
      </span>
    </div>

    <svg
      class="qc-svg"
      :viewBox="`0 0 ${W} ${H}`"
      role="img"
      :aria-label="`逐位点平均质量曲线，阈值 Q${floor}，弱位点 ${weakPoints.length} 个`"
      @mouseleave="hoverIdx = -1"
    >
      <!-- 水平网格线与 Y 轴刻度 -->
      <g>
        <template v-for="t in yTicks" :key="`g-${t}`">
          <line
            :x1="padL"
            :x2="W - padR"
            :y1="yScale(t)"
            :y2="yScale(t)"
            stroke="#e1e0d9"
            stroke-width="1"
          />
          <text :x="padL - 8" :y="yScale(t) + 3.5" text-anchor="end" class="qc-axis-text">{{ t }}</text>
        </template>
      </g>

      <!-- X 轴基线 -->
      <line :x1="padL" :x2="W - padR" :y1="plotBottom" :y2="plotBottom" stroke="#c3c2b7" stroke-width="1" />

      <!-- 阈值以下弱区 wash（仅当阈值在坐标域内） -->
      <rect
        v-if="floorInDomain"
        :x="padL"
        :width="plotW"
        :y="yScale(floor)"
        :height="plotBottom - yScale(floor)"
        fill="#d03b3b"
        opacity="0.07"
      />

      <!-- 阈值参考线 -->
      <line
        v-if="floorInDomain"
        :x1="padL"
        :x2="W - padR"
        :y1="yScale(floor)"
        :y2="yScale(floor)"
        stroke="#d03b3b"
        stroke-width="1.5"
        stroke-dasharray="5 3"
      />

      <!-- 质量曲线 -->
      <path :d="linePath" fill="none" stroke="#2a78d6" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />

      <!-- 末端选择性直标 -->
      <text
        v-if="points.length"
        :x="xScale(points[points.length - 1].position) - 2"
        :y="yScale(points[points.length - 1].mean_quality) - 8"
        text-anchor="end"
        class="qc-end-label"
      >{{ points[points.length - 1].mean_quality }}</text>

      <!-- 弱位点标记：位置取自服务端 weak_positions，前端不自行扫描 -->
      <g v-for="w in weakPoints" :key="`w-${w.position}`">
        <circle :cx="xScale(w.position)" :cy="yScale(w.mean_quality)" r="6" fill="#d03b3b" />
        <circle
          :cx="xScale(w.position)"
          :cy="yScale(w.mean_quality)"
          r="6"
          fill="none"
          stroke="#fcfcfb"
          stroke-width="2"
        />
      </g>

      <!-- X 轴刻度（稀疏） -->
      <g>
        <template v-for="p in xTicks" :key="`x-${p}`">
          <line
            :x1="xScale(p)"
            :x2="xScale(p)"
            :y1="plotBottom"
            :y2="plotBottom + 4"
            stroke="#c3c2b7"
            stroke-width="1"
          />
          <text :x="xScale(p)" :y="plotBottom + 16" text-anchor="middle" class="qc-axis-text">{{ p }}</text>
        </template>
      </g>
      <text :x="padL + plotW / 2" :y="H - 2" text-anchor="middle" class="qc-axis-title">读段位点（bp）</text>

      <!-- 十字线 -->
      <line
        v-if="hoverPoint"
        :x1="xScale(hoverPoint.position)"
        :x2="xScale(hoverPoint.position)"
        :y1="padT"
        :y2="plotBottom"
        stroke="#898781"
        stroke-width="1"
      />
      <circle
        v-if="hoverPoint"
        :cx="xScale(hoverPoint.position)"
        :cy="yScale(hoverPoint.mean_quality)"
        r="4.5"
        :fill="hoverWeak ? '#d03b3b' : '#2a78d6'"
        stroke="#fcfcfb"
        stroke-width="2"
      />

      <!-- 每位点命中列（整列可悬停，命中宽度等于位点步长） -->
      <rect
        v-for="(p, i) in points"
        :key="`hit-${p.position}`"
        class="qc-hit"
        :x="hitX(i)"
        :y="padT"
        :width="hitW()"
        :height="plotH"
        fill="transparent"
        @mouseenter="hoverIdx = i"
        @focus="hoverIdx = i"
        @blur="hoverIdx = -1"
        tabindex="0"
        :aria-label="`位点 ${p.position}，平均质量 ${p.mean_quality}${weakSet.has(p.position) ? '，弱位点' : ''}`"
      />
    </svg>

    <div
      v-if="hoverPoint"
      class="qc-tooltip text-caption"
      :style="tooltipStyle"
    >
      <div class="qc-tip-pos">位点 {{ hoverPoint.position }}</div>
      <div class="qc-tip-row">
        <svg width="14" height="8" aria-hidden="true"><line x1="0" y1="4" x2="14" y2="4" :stroke="hoverWeak ? '#d03b3b' : '#2a78d6'" stroke-width="2" /></svg>
        <span class="qc-tip-val">{{ hoverPoint.mean_quality }}</span>
        <span class="qc-tip-name">平均质量</span>
      </div>
      <div v-if="hoverWeak" class="qc-tip-weak">弱位点</div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  points: { type: Array, required: true }, // 服务端 per_position
  weakPositions: { type: Array, default: () => [] }, // 服务端 weak_positions，前端不得自行计算
  floor: { type: Number, required: true },
})

const W = 720
const H = 260
const padL = 44
const padR = 16
const padT = 16
const padB = 36
const plotW = W - padL - padR
const plotH = H - padT - padB
const plotBottom = padT + plotH

const wrapRef = ref(null)
const hoverIdx = ref(-1)

const weakSet = computed(() => new Set((props.weakPositions || []).map((w) => w.position)))
const weakPoints = computed(() =>
  (props.weakPositions || [])
    .filter((w) => props.points.some((p) => p.position === w.position))
    .map((w) => ({ position: w.position, mean_quality: w.mean_quality })),
)

const yMax = computed(() => {
  const maxQ = Math.max(0, ...props.points.map((p) => p.mean_quality))
  return Math.max(40, Math.ceil((Math.max(maxQ, props.floor) + 1) / 10) * 10)
})

const yTicks = computed(() => {
  const ts = []
  for (let v = 0; v <= yMax.value; v += 10) ts.push(v)
  return ts
})

const n = computed(() => props.points.length)
const stepX = computed(() => (n.value > 1 ? plotW / (n.value - 1) : 0))

function xScale(position) {
  if (n.value === 1) return padL + plotW / 2
  return padL + ((position - 1) / (n.value - 1)) * plotW
}
function yScale(q) {
  return plotBottom - (q / yMax.value) * plotH
}

const floorInDomain = computed(() => props.floor >= 0 && props.floor <= yMax.value)

const linePath = computed(() =>
  props.points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${xScale(p.position).toFixed(1)},${yScale(p.mean_quality).toFixed(1)}`)
    .join(' '),
)

const xTicks = computed(() => {
  if (!n.value) return []
  if (n.value <= 16) return props.points.map((p) => p.position)
  const stride = Math.ceil(n.value / 10)
  const ticks = []
  for (let p = 1; p <= n.value; p += stride) ticks.push(p)
  if (ticks[ticks.length - 1] !== n.value) ticks.push(n.value)
  return ticks
})

function hitW() {
  return n.value > 1 ? Math.max(stepX.value, 24) : plotW
}
function hitX(i) {
  if (n.value === 1) return padL
  return xScale(props.points[i].position) - hitW() / 2
}

const hoverPoint = computed(() =>
  hoverIdx.value >= 0 && hoverIdx.value < props.points.length ? props.points[hoverIdx.value] : null,
)
const hoverWeak = computed(() => (hoverPoint.value ? weakSet.value.has(hoverPoint.value.position) : false))

const tooltipStyle = computed(() => {
  if (!hoverPoint.value || !wrapRef.value) return {}
  const svgEl = wrapRef.value.querySelector('.qc-svg')
  const rect = svgEl.getBoundingClientRect()
  const sx = rect.width / W
  const px = xScale(hoverPoint.value.position) * sx
  // 默认显示在点右侧，靠右时翻到左侧
  const left = px + 72 > rect.width ? px - 96 : px + 12
  const py = yScale(hoverPoint.value.mean_quality) * (rect.height / H)
  return { left: `${left}px`, top: `${Math.max(4, py - 30)}px` }
})
</script>

<style scoped>
.qc-chart {
  position: relative;
  width: 100%;
}
.qc-svg {
  width: 100%;
  height: auto;
  display: block;
}
.qc-hit {
  pointer-events: all;
  outline: none;
}
.qc-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 6px;
  color: #52514e;
}
.qc-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.qc-key {
  display: block;
}
.qc-axis-text {
  fill: #898781;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.qc-axis-title {
  fill: #898781;
  font-size: 11px;
}
.qc-end-label {
  fill: #52514e;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.qc-tooltip {
  position: absolute;
  min-width: 92px;
  padding: 6px 9px;
  background: #ffffff;
  border: 1px solid rgba(11, 11, 11, 0.1);
  border-radius: 4px;
  box-shadow: 0 2px 8px rgba(11, 11, 11, 0.12);
  pointer-events: none;
  color: #0b0b0b;
}
.qc-tip-pos {
  font-weight: 600;
  margin-bottom: 2px;
}
.qc-tip-row {
  display: flex;
  align-items: center;
  gap: 5px;
}
.qc-tip-val {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.qc-tip-name {
  color: #52514e;
}
.qc-tip-weak {
  margin-top: 2px;
  color: #52514e;
}
.qc-chart :focus {
  outline: 2px solid #2a78d6;
  outline-offset: 1px;
}
</style>
