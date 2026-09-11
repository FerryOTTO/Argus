<template>
  <div class="extensions-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">扩展管理</h2>
        <p class="page-subtitle">审批智能体终端安装 Skill / 接入 MCP，并向目标终端分发 Skill 包</p>
      </div>
    </div>

    <div class="tab-card">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="安装审批" name="approvals">
          <ApprovalsTab />
        </el-tab-pane>
        <el-tab-pane label="Skill 分发" name="packages">
          <SkillPackagesTab />
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import ApprovalsTab from '@/components/extensions/ApprovalsTab.vue'
import SkillPackagesTab from '@/components/extensions/SkillPackagesTab.vue'

const activeTab = ref('approvals')
</script>

<style scoped lang="scss">
.extensions-page {
  padding: 0;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}

.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
  margin: 0;
}

.page-subtitle {
  margin: 6px 0 0;
  font-size: 13px;
  color: #909399;
}

.tab-card {
  padding: 4px 16px 16px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
}
</style>
