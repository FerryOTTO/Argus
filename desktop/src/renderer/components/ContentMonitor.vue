<template>
  <section class="module-monitor-shell">
    <iframe
      ref="frameRef"
      :src="frameUrl"
      class="module-monitor-iframe"
      title="02 内容检测 - 模块监测"
      @load="onFrameLoaded"
    ></iframe>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'

const frameRef = ref(null)
const frameBaseUrl = 'http://127.0.0.1:8000/audit?embedded=1&module=content&title=CONTENT%20GUARD'
const props = defineProps({ darkMode: { type: Boolean, default: false } })
const frameUrl = computed(() => frameBaseUrl + '&theme=' + (props.darkMode ? 'dark' : 'light'))

function reloadFrame() {
  if (frameRef.value) {
    frameRef.value.src = frameUrl.value + '&_t=' + Date.now()
  }
}

function onFrameLoaded() {
  // frame loaded callback
}

defineExpose({ reloadFrame })
</script>

<style scoped>
.module-monitor-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100%;
  background: #fcfaf8;
  overflow: hidden;
}

.module-monitor-iframe {
  width: 100%;
  height: 100%;
  border: none;
  display: block;
  flex: 1;
}
:global(.claw-dark-mode) .module-monitor-shell { background:#121416; }
</style>
