<template>
  <div class="forbidden-page">
    <section class="forbidden-panel">
      <div class="status-code">403</div>
      <h1>当前账号没有访问权限</h1>
      <p>
        该页面仅限管理员或授权账号使用。请切换具备权限的账号，或返回首页继续查看行情与观察池。
      </p>

      <div class="actions">
        <el-button type="primary" @click="$router.push('/')">返回首页</el-button>
        <el-button @click="$router.push('/profile')">查看账号</el-button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.forbidden-page {
  min-height: calc(100vh - 96px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 20px;
}

.forbidden-panel {
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
