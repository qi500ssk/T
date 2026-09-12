# Personal AI Web

Next.js 16 前端，端口 4321，只监听本机回环地址。首次打开页面创建本机账号，之后登录使用；账号相关操作见「设置 → 账号与安全」。

```powershell
npm ci
npm run build
npm start
```

所有业务请求和文件地址使用同源 `/api`，由 Next.js 代理到后端（默认 `http://127.0.0.1:8787`）。需要指向其他后端地址时，在构建环境设置 `API_INTERNAL_URL`。

开发调试：`npm run dev`。完整的环境准备、数据库和测试说明见[项目 README](../../README.md)。
