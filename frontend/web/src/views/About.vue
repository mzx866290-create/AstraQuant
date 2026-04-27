<template>
  <div class="about">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>📋 关于本平台</span>
        </div>
      </template>
      <div class="about-content">
        <h3>项目介绍</h3>
        <p>股票数据分析平台是一个开源项目，基于Python FastAPI和Vue 3开发。</p>

        <h3>技术栈</h3>
        <div class="tech-stack">
          <div class="tech-item">
            <strong>后端:</strong> Python 3.11 + FastAPI + SQLAlchemy
          </div>
          <div class="tech-item">
            <strong>数据库:</strong> PostgreSQL + ClickHouse + Redis
          </div>
          <div class="tech-item">
            <strong>前端:</strong> Vue 3 + TypeScript + Vite
          </div>
          <div class="tech-item">
            <strong>数据源:</strong> AkShare + Tushare
          </div>
          <div class="tech-item">
            <strong>部署:</strong> Docker Compose
          </div>
        </div>

        <h3>主要特性</h3>
        <ul>
          <li>✅ 实时行情数据</li>
          <li>✅ K线数据展示（日、周、月）</li>
          <li>✅ 技术指标计算</li>
          <li>✅ 自选股管理</li>
          <li>✅ 价格预警</li>
          <li>✅ 数据采集定时任务</li>
          <li>✅ 监控和告警（Prometheus+Grafana）</li>
        </ul>

        <h3>免责声明</h3>
        <p class="disclaimer">
          本平台仅供学习和研究之用，提供的所有信息和数据不构成任何投资建议。
          用户在使用本平台时，应自行判断和承担相关风险。开发者不对因使用本平台而产生的任何损失负责。
        </p>

        <h3>联系方式</h3>
        <p>GitHub: <a href="https://github.com" target="_blank">https://github.com</a></p>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
</script>

<style scoped>
.about {
  max-width: 800px;
  margin: 0 auto;
}

.about-content {
  font-size: 14px;
  line-height: 1.6;
}

.about-content h3 {
  color: #667eea;
  margin-top: 20px;
}

.tech-stack {
  background: #f5f7fa;
  padding: 15px;
  border-radius: 4px;
  margin: 10px 0;
}

.tech-item {
  padding: 8px 0;
  border-bottom: 1px solid #dcdfe6;
}

.tech-item:last-child {
  border-bottom: none;
}

.about-content ul {
  list-style: none;
  padding: 0;
}

.about-content li {
  padding: 8px 0;
}

.disclaimer {
  background: #fef0f0;
  border-left: 4px solid #f56c6c;
  padding: 12px;
  border-radius: 4px;
  color: #f56c6c;
}

.about-content a {
  color: #667eea;
  text-decoration: none;
}

.about-content a:hover {
  text-decoration: underline;
}
</style>
