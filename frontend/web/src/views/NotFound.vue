<template>
  <div class="not-found-page">
    <section class="not-found-panel">
      <div class="status-code">404</div>
      <h1>页面不存在</h1>
      <p>
        您访问的页面不存在或已被移除。请检查链接是否正确，或返回首页继续浏览。
      </p>

      <div class="actions">
        <el-button type="primary" @click="$router.push('/')">返回首页</el-button>
        <el-button @click="$router.back()">返回上一页</el-button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.not-found-page {
  min-height: calc(100vh - 96px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 20px;
}

.not-found-panel {
  width: min(100%, 520px);
  text-align: center;
}

.status-code {
  font-size: 56px;
  font-weight: 700;
  color: #dc2626;
  line-height: 1;
  margin-bottom: 20px;
}

h1 {
  margin: 0 0 12px;
  font-size: 24px;
  color: #111827;
}

p {
  margin: 0;
  color: #4b5563;
  line-height: 1.7;
}

.actions {
  margin-top: 28px;
  display: flex;
  justify-content: center;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
