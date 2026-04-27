<template>
  <div class="home">
    <el-card class="box-card">
      <template #header>
        <div class="card-header">
          <span>📊 欢迎来到股票数据分析平台</span>
        </div>
      </template>
      <div class="home-content">
        <p>这是一个基于Python和Vue 3的股票数据分析平台，提供实时行情、历史K线、技术指标分析、自选股管理等功能。</p>
        
        <h3>🎯 主要功能</h3>
        <ul>
          <li>📈 实时行情数据</li>
          <li>📉 K线数据展示（日K、周K、月K）</li>
          <li>🔍 技术指标分析（MA、MACD、KDJ、BOLL等）</li>
          <li>⭐ 自选股管理</li>
          <li>💡 价格预警通知</li>
        </ul>

        <h3>🚀 快速开始</h3>
        <div class="quick-links">
          <router-link to="/stocks" class="el-button el-button--primary">
            浏览股票
          </router-link>
          <router-link to="/watchlist" class="el-button el-button--success">
            我的自选股
          </router-link>
        </div>

        <h3>📌 免责声明</h3>
        <p class="disclaimer">
          本平台提供的股票数据和分析仅供参考，不构成任何投资建议。投资有风险，入市需谨慎。
          请根据自己的风险承受能力进行投资决策。
        </p>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'

onMounted(() => {
  console.log('首页已加载')
})
</script>

<style scoped>
.home {
  max-width: 800px;
  margin: 0 auto;
}

.home-content {
  font-size: 14px;
  line-height: 1.6;
}

.home-content h3 {
  margin-top: 20px;
  margin-bottom: 10px;
  color: #667eea;
}

.home-content ul {
  list-style: none;
  padding: 0;
}

.home-content li {
  padding: 8px 0;
  border-bottom: 1px solid #eee;
}

.quick-links {
  margin: 20px 0;
  display: flex;
  gap: 10px;
}

.disclaimer {
  background: #fef0f0;
  border-left: 4px solid #f56c6c;
  padding: 12px;
  border-radius: 4px;
  color: #f56c6c;
}
</style>
