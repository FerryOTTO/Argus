<template>
  <div class="relative w-full h-64 overflow-hidden rounded-2xl border border-white/10 bg-[#0B0E14] select-none my-4 shadow-2xl">
    <!-- Underneath Layer: Glowing Cyber Matrix & Circuits (Revealed by Mouse Scratch) -->
    <div 
      class="absolute inset-0 bg-cover bg-center pointer-events-none"
      :style="{ backgroundImage: `url(${cyberBgUrl})` }"
    ></div>

    <!-- Middle Layer: Interactive Scratch Canvas (Erased by mouse moves) -->
    <canvas 
      ref="canvasRef" 
      @mousemove="handleScratch" 
      @mouseleave="handleMouseLeave"
      class="absolute inset-0 w-full h-full cursor-crosshair z-10"
    ></canvas>

    <!-- Foreground Layer: Hero Text & Typewriter Content -->
    <div class="relative z-20 h-full flex flex-col justify-center px-8 pointer-events-none">
      <div class="flex items-center gap-2 mb-2">
        <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-[#FF6900]/15 text-[#FF6900] border border-[#FF6900]/30 shadow-[0_0_12px_rgba(255,105,0,0.25)]">
          <Sparkles class="w-3.5 h-3.5" />
          MiMo Code Design System
        </span>
        <span class="text-xs text-slate-400">滑动鼠标擦除露出发光拓扑 ↓</span>
      </div>

      <!-- Main Title with Xiaomi Gradient -->
      <h1 class="text-3xl lg:text-4xl font-extrabold tracking-tight bg-gradient-to-r from-white via-slate-100 to-slate-400 bg-clip-text text-transparent">
        Argus AI 安全智能体守护平台
      </h1>

      <!-- Typewriter Subtitle -->
      <div class="flex items-center gap-1 mt-2 text-slate-300 text-sm md:text-base font-medium min-h-[28px]">
        <span class="text-slate-400">核心使命：</span>
        <span class="text-[#FF8533] font-mono font-semibold">{{ currentText }}</span>
        <span class="w-1.5 h-4 bg-[#FF6900] animate-pulse inline-block"></span>
      </div>

      <!-- Stats Bar in Hero -->
      <div class="mt-4 flex items-center gap-6 pointer-events-auto">
        <div class="flex items-center gap-2">
          <div class="w-2 h-2 rounded-full bg-emerald-400"></div>
          <span class="text-xs text-slate-300">网关协议: <span class="text-white font-mono font-semibold">OpenClaw 18789</span></span>
        </div>
        <div class="flex items-center gap-2">
          <div class="w-2 h-2 rounded-full bg-cyan-400"></div>
          <span class="text-xs text-slate-300">适配引擎: <span class="text-white font-mono font-semibold">FastAPI 8000</span></span>
        </div>
        <div class="flex items-center gap-2">
          <div class="w-2 h-2 rounded-full bg-[#FF6900]"></div>
          <span class="text-xs text-slate-300">阻断时延: <span class="text-white font-mono font-semibold">&lt; 1.2ms</span></span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { Sparkles } from 'lucide-vue-next'
import cyberBgUrl from '@/assets/cyber_bg.svg'

// Canvas Scratch Reveal Logic
const canvasRef = ref(null)
let ctx = null
let animId = null

const slogans = [
  '为大模型与 AI 智能体构筑零信任纵深防御体系',
  '实时阻断 .gitconfig、.env、SSH 私钥等敏感凭证外泄',
  '动态四级密级分配与近永久隔离区安全流转审批',
  '企业级 OpenTelemetry 遥测与高保真行为审计追踪'
]

const currentText = ref('')
let sloganIdx = 0
let charIdx = 0
let isDeleting = false
let typewriterTimer = null

function typeEffect() {
  const target = slogans[sloganIdx]
  if (!isDeleting) {
    currentText.value = target.substring(0, charIdx + 1)
    charIdx++
    if (charIdx === target.length) {
      isDeleting = true
      typewriterTimer = setTimeout(typeEffect, 2200)
      return
    }
    typewriterTimer = setTimeout(typeEffect, 60)
  } else {
    currentText.value = target.substring(0, charIdx - 1)
    charIdx--
    if (charIdx === 0) {
      isDeleting = false
      sloganIdx = (sloganIdx + 1) % slogans.length
      typewriterTimer = setTimeout(typeEffect, 400)
      return
    }
    typewriterTimer = setTimeout(typeEffect, 30)
  }
}

function initCanvas() {
  const canvas = canvasRef.value
  if (!canvas) return
  ctx = canvas.getContext('2d')
  
  const dpr = window.devicePixelRatio || 1
  canvas.width = canvas.offsetWidth * dpr
  canvas.height = canvas.offsetHeight * dpr
  ctx.scale(dpr, dpr)

  // Paint dark top mask layer
  ctx.fillStyle = '#0B0E14'
  ctx.fillRect(0, 0, canvas.offsetWidth, canvas.offsetHeight)

  // Draw subtle decorative cyber grid lines on mask
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.04)'
  ctx.lineWidth = 1
  for (let x = 0; x < canvas.offsetWidth; x += 40) {
    ctx.beginPath()
    ctx.moveTo(x, 0)
    ctx.lineTo(x, canvas.offsetHeight)
    ctx.stroke()
  }
  for (let y = 0; y < canvas.offsetHeight; y += 40) {
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(canvas.offsetWidth, y)
    ctx.stroke()
  }

  // Smooth healing loop
  const heal = () => {
    if (ctx) {
      ctx.globalCompositeOperation = 'source-over'
      ctx.fillStyle = 'rgba(11, 14, 20, 0.035)'
      ctx.fillRect(0, 0, canvas.offsetWidth, canvas.offsetHeight)
    }
    animId = requestAnimationFrame(heal)
  }
  animId = requestAnimationFrame(heal)
}

function handleScratch(e) {
  if (!ctx || !canvasRef.value) return
  const rect = canvasRef.value.getBoundingClientRect()
  const x = e.clientX - rect.left
  const y = e.clientY - rect.top

  ctx.save()
  ctx.globalCompositeOperation = 'destination-out'
  
  // Create soft radial eraser brush
  const radius = 65
  const gradient = ctx.createRadialGradient(x, y, 0, x, y, radius)
  gradient.addColorStop(0, 'rgba(0, 0, 0, 1)')
  gradient.addColorStop(0.6, 'rgba(0, 0, 0, 0.8)')
  gradient.addColorStop(1, 'rgba(0, 0, 0, 0)')

  ctx.fillStyle = gradient
  ctx.beginPath()
  ctx.arc(x, y, radius, 0, Math.PI * 2)
  ctx.fill()
  ctx.restore()
}

function handleMouseLeave() {
  // Let the heal loop take over
}

onMounted(() => {
  initCanvas()
  typeEffect()
  window.addEventListener('resize', initCanvas)
})

onUnmounted(() => {
  if (animId) cancelAnimationFrame(animId)
  if (typewriterTimer) clearTimeout(typewriterTimer)
  window.removeEventListener('resize', initCanvas)
})
</script>