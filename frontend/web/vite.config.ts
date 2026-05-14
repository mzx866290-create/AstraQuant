import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver({ importStyle: 'css' })],
      dts: 'src/auto-imports.d.ts'
    }),
    Components({
      resolvers: [ElementPlusResolver({ importStyle: 'css' })],
      dts: 'src/components.d.ts'
    })
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    host: '0.0.0.0',
    port: 5175,
    allowedHosts: ['.trycloudflare.com', 'mzxstock.duckdns.org', 'yhang.cc.cd'],
    proxy: {
      // 用户服务 (本地端口 8002)
      '/api/v1/auth': {
        target: 'http://localhost:8002',
        changeOrigin: true,
      },
      '/api/v1/watchlists': {
        target: 'http://localhost:8002',
        changeOrigin: true,
      },
      // 分析服务 (本地端口 8003)
      '/api/v1/analysis': {
        target: 'http://localhost:8003',
        changeOrigin: true,
        timeout: 300000,
        proxyTimeout: 300000,
      },
      '/api/v1/admin': {
        target: 'http://localhost:8003',
        changeOrigin: true,
      },
      // 行情服务 (本地端口 8001) — 必须放在最后，避免拦截其他 /api/v1 路由
      '/api/v1': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      }
    }
  },
  build: {
    target: 'ES2020',
    sourcemap: false,
    outDir: 'dist',
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/echarts') || id.includes('node_modules/zrender')) {
            return 'echarts'
          }
          if (
            id.includes('node_modules/vue') ||
            id.includes('node_modules/vue-router') ||
            id.includes('node_modules/pinia')
          ) {
            return 'vue'
          }
        }
      }
    }
  }
})
