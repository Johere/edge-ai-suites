# MCP Subscription 开发状态

**分支**: `jiao/mcp-subscription`
**Plan 源文档**: [docs/dev/plans-backup/MCP-resource-subscription-plan.md](plans-backup/MCP-resource-subscription-plan.md) （原 rustling-giggling-giraffe 计划文件搬到此路径备份）
**状态日期**: 2026-07-01

---

## 任务背景

`task-poller.ts` 命中 rule 后调用 `db.createAlert()` + `onAlert(monitorId)` callback，但 callback 目前只 `logger.debug`——alert 只落 DB，没有推给任何 agent。目标是**闭环这条通道**，让 alert 通过 MCP `notifications/resources/updated` 协议主动推送给订阅的 host（首个 host 是 OpenClaw；未来可能加 Hermes / Claude Desktop 等）。

### 核心设计约束

- **MCP server 完全 host-agnostic**——不知道 OpenClaw、不知道 Feishu、不知道 session
- MCP server 只发协议标准的 `notifications/resources/updated`；notification 只带 uri，不带 payload——client 收到后自己 `resources/read` 拉最新
- 每个 agent framework 写一个 **framework adapter**（长活进程）——内含通用 MCP client + 该 framework 特定的 session 注入逻辑
- 通用 MCP client 部分抽成 `packages/framework-adapter-sdk/` workspace 包
- **不做 persona 润色**——adapter 直接投递 raw alert 到 session
- **路由表**（monitor → session[] 映射）**放 adapter 侧**（如 OpenClaw plugin 自己配），MCP server 不知道 session 概念
- 首个语言目标 **TypeScript**（MCP server 是 TS，OpenClaw 扩展是 TS）
- Cooldown 分层：L1 业务 cooldown 在 MCP server rule engine（已存在）／L2 投递去重在 SDK cursor（天然）／L3 渠道节流在 adapter sink 内部（可选）

### 命名约定（避免歧义）

- **Framework Adapter**（本任务）：让 agent framework 接 MCP alert 的桥。SDK + 每个 framework 一个具体实现
- **Use Case Adapter**（已存在，不属本任务）：`use_case_dict` + `evaluate_rules_path` Python override 那套
- **MCP session**：client↔server 协议连接（有 sessionId）——本任务 `McpSubscriberRegistry` 里的"session"是这个
- **OpenClaw session**：agent 会话如 `agent:<id>:main`——adapter sink 投递的目标

---

## 架构一览

```
┌─────────────────────────────┐         ┌─────────────────────────────┐
│  MCP server (existing TS)   │         │  Adapter (per framework)    │
│  packages/mcp-server        │         │                             │
│                             │◀────────│  Long-lived process         │
│  task-poller → createAlert  │  MCP    │  ┌────────────────────────┐ │
│      ↓                      │  over   │  │ SmartBuildingAdapter   │ │
│  onAlert(monitorId)         │  HTTP   │  │  (framework-adapter-sdk)│ │
│      ↓                      │  (SSE)  │  │  - MCP client          │ │
│  server.sendResourceUpdated │────────▶│  │  - subscribe/reconnect │ │
│  ({ uri: '.../alerts' })    │         │  │  - dedup by cursor     │ │
│                             │         │  └──────────┬─────────────┘ │
│  resources.ts               │◀────────│             │ sink.push()   │
│  read alerts (since cursor) │  read   │             ▼               │
│                             │────────▶│  ┌────────────────────────┐ │
└─────────────────────────────┘         │  │ AlertSink (framework)  │ │
                                        │  │  - reads route table   │ │
                                        │  │  - injects into session│ │
                                        │  └────────────────────────┘ │
                                        └─────────────────────────────┘
```

---

## 当前进度

### ✅ Phase A.1 完成 — `McpSubscriberRegistry`

**文件**: [packages/mcp-server/src/mcp-subscriber-registry.ts](../../packages/mcp-server/src/mcp-subscriber-registry.ts)

维护 sessionId → `{ server, transport, subscriptions: Set<uri> }` 映射。核心方法：
- `register(sessionId, entry)` / `unregister(sessionId)`
- `addSubscription(sessionId, uri)` / `removeSubscription(sessionId, uri)`
- `findSubscribers(uri): SubscriberEntry[]` — onAlert 广播用
- transport 允许 `null`（stdio 单例情况）

### ✅ Phase A.2 完成 — DB cursor 读

**文件**: [packages/db/src/database.ts](../../packages/db/src/database.ts) 已 rebuild（`npm -w @smartbuilding-video/db run build` 通过）

- `queryAlerts` 加 `sinceId?: number` 参数：`AND id > ? ORDER BY id ASC` 分支
- 新增 `getLatestAlertId(monitorId?)` — 返回 `COALESCE(MAX(id), 0)`，无 row 时返回 0

### ✅ Phase A.3 完成 — resources.ts subscribe 支持

**文件**: [packages/mcp-server/src/resources.ts](../../packages/mcp-server/src/resources.ts)

改动要点：
- 拆成两个 template（`ResourceTemplate` 的 `?since` 是 required 不是 optional，所以要两个）：
  - `smartbuilding://monitor/{id}/alerts` → 最新 20 条 + `latestId`
  - `smartbuilding://monitor/{id}/alerts{?since}` → id > since 的增量 + `latestId`
  - **注册顺序**：带 `?since` 的模板必须先注册（SDK 按插入顺序匹配）
- Response body 里包含 `latestId` 字段供 client 存作下次游标
- Subscribe/unsubscribe handler via `server.server.setRequestHandler(SubscribeRequestSchema, ...)`
- Advertise capability via `server.server.registerCapabilities({ resources: { subscribe: true } })`（McpServer 默认只 set `listChanged`）

**当前签名**: `registerResources(server, config, db, registry?, sessionId?: string)` — sessionId 是**静态字符串**，这是 A.4 卡点的根源（见下面）

### 🔶 Phase A.4 卡住 — index.ts stateful HTTP + onAlert 广播

**文件**: [packages/mcp-server/src/index.ts](../../packages/mcp-server/src/index.ts)

**已经写好**：
- `subscriberRegistry` 实例化 (line 102)
- `onAlert` broadcast 实现 (line 106-118) — 遍历 subscribers 调 `server.server.sendResourceUpdated({ uri })`
- Stateful HTTP handler 骨架 (line 123-197)：
  - `sessionIdGenerator: () => randomUUID()`
  - `onsessioninitialized` 里 `subscriberRegistry.register(sid, ...)`
  - 后续 request 从 `mcp-session-id` header 找已有 entry 复用其 transport
  - `transport.onclose` 里 unregister
- stdio 单例登记进 registry（固定 sid `"stdio"`, transport=null）(line 199-208)

**两个已知正确性 bug**（`tsc --noEmit` 现在通过是因为 TS 不检测 TDZ／不追踪运行时字符串常量）：

1. **闭包引用未声明的 `server`** ([index.ts:141-149](../../packages/mcp-server/src/index.ts#L141) → [:154](../../packages/mcp-server/src/index.ts#L154))：
   ```typescript
   const transport = new StreamableHTTPServerTransport({
     onsessioninitialized: (sid) => {
       subscriberRegistry.register(sid, { server, transport, ... });  // ← server 引用
     },
   });
   const server = createMcpServer(...);  // ← declare 在 transport 之后
   ```
   Runtime 通常能跑通（onsessioninitialized 在 `initialize` handshake 时才触发，晚于 declare），但依赖执行时序，脆。

2. **`sessionId` 传成 `"__pending__"`** ([index.ts:160](../../packages/mcp-server/src/index.ts#L160))：
   ```typescript
   const server = createMcpServer(..., subscriberRegistry, "__pending__");
   ```
   这个字符串沿着 `registerResources` 进到 subscribe handler 里，就是 handler 记的 sessionId。当 client 之后调 `resources/subscribe`，handler 往 `subscriberRegistry.addSubscription("__pending__", uri)` 加，但 registry 里 `register()` 记的是真实 uuid → 广播时 `findSubscribers()` 找不到，notification 永远命中不到 client。

### ⏳ 未开始

- **A.5** curl smoke test（要先修完 A.4）
- **B** `packages/framework-adapter-sdk/`（通用 MCP client SDK）
- **C** `tests/framework-adapter-sdk/` 单测
- **D** `examples/openclaw/`（plugin + install.sh + agent personas seed）
- **E** `docs/framework-adapters/*.md` 4 篇
- **F** `dev_status.md` 更新

---

## 下一步：修 A.4 的方向已定 — `getSessionId` 回调路线

用户已经确认（本次 session 结束前明确指示）：走 `getSessionId` 回调路线继续做。

### 具体改法

**Step 1: 改 `packages/mcp-server/src/resources.ts` 签名**

把静态 `sessionId?: string` 改成 `getSessionId?: () => string`。subscribe/unsubscribe handler 在 handler 执行时（不是注册时）调 `getSessionId()` 拿真实 sid：

```typescript
export function registerResources(
  server: McpServer,
  _config: ServerConfig,
  db: SmartBuildingDB,
  registry?: McpSubscriberRegistry,
  getSessionId?: () => string,   // ← 回调，惰性求值
): void {
  // ...资源注册不变...

  if (registry && getSessionId) {
    server.server.registerCapabilities({ resources: { subscribe: true } });

    server.server.setRequestHandler(SubscribeRequestSchema, async (request) => {
      const uri = request.params.uri;
      const sid = getSessionId();       // ← 这里拿到的是 handler 触发时的真实 sid
      registry.addSubscription(sid, uri);
      logger.debug(`[mcp] session=${sid} subscribed to ${uri}`);
      return {};
    });

    server.server.setRequestHandler(UnsubscribeRequestSchema, async (request) => {
      const uri = request.params.uri;
      const sid = getSessionId();
      registry.removeSubscription(sid, uri);
      logger.debug(`[mcp] session=${sid} unsubscribed from ${uri}`);
      return {};
    });
  }
}
```

**Step 2: 改 `createMcpServer` 签名**

```typescript
function createMcpServer(
  config, db, workerService, summaryClient,
  subscriberRegistry: McpSubscriberRegistry,
  getSessionId: () => string,        // ← 替换掉 sessionId: string
): McpServer {
  const server = new McpServer({ name: "smartbuilding-video", version: "0.1.0" });
  registerTools(server, config, db, workerService, summaryClient);
  registerResources(server, config, db, subscriberRegistry, getSessionId);
  return server;
}
```

**Step 3: HTTP 分支改用回调**

```typescript
const transport = new StreamableHTTPServerTransport({
  sessionIdGenerator: () => randomUUID(),
  onsessioninitialized: (sid: string) => {
    subscriberRegistry.register(sid, { server, transport, subscriptions: new Set() });
    logger.debug(`[mcp] session initialized sid=${sid}`);
  },
});

const server = createMcpServer(
  config, db, workerService, summaryClient,
  subscriberRegistry,
  () => transport.sessionId ?? "__pending__",  // ← 回调，subscribe 触发时才求值
);

transport.onclose = () => {
  const sid = transport.sessionId;
  if (sid) subscriberRegistry.unregister(sid);
};

await server.connect(transport);
await transport.handleRequest(req, res, req.body);
```

注意：**闭包引用未声明的 `server` 的 TDZ 问题仍存在**——但因为 onsessioninitialized 只在 `initialize` handshake 时触发（一定晚于 const 声明），实际上 runtime 不会撞 TDZ。如果想彻底消除风险，把 `const server` 用 `let server: McpServer` 提前 declare（值 undefined），或者把整段挪进 onsessioninitialized 里（但那样 `server.connect(transport)` 就没办法在 handshake 前执行）。**当前建议先保持结构，跑通再看**。

**Step 4: stdio 分支**

```typescript
const STDIO_SESSION_ID = "stdio";
const mcpServer = createMcpServer(
  config, db, workerService, summaryClient,
  subscriberRegistry,
  () => STDIO_SESSION_ID,       // ← 固定回调
);
subscriberRegistry.register(STDIO_SESSION_ID, {
  server: mcpServer,
  transport: null,
  subscriptions: new Set(),
});
```

### 验证 A.4 通过的标准

```bash
# 1) build 通过
npm -w @smartbuilding-video/db run build && npx tsc --noEmit -p packages/mcp-server

# 2) 启动 mcp-server HTTP
node packages/mcp-server/dist/index.js --http --config config.yaml --monitors monitors.yaml

# 3) curl 手工验证 subscribe 流程
#    - initialize 返回带 mcp-session-id header
#    - 用同一 sid 发 resources/subscribe { uri: 'smartbuilding://monitor/cam_child/alerts' }
#    - 手工 SQL INSERT 一条 alert 到 monitor_id=cam_child
#    - GET /mcp（SSE 通道）应收到 notifications/resources/updated { uri: '...' }
#    - 用同一 sid GET resources/read uri=smartbuilding://monitor/cam_child/alerts?since=0
#      → 返回该条 alert + latestId
```

---

## Todo 全量（新 session 直接复制到 TodoWrite）

```
[completed]  Phase A.1: create packages/mcp-server/src/mcp-subscriber-registry.ts
[completed]  Phase A.2: db.queryAlerts() add sinceId param
[completed]  Phase A.3: resources.ts parse ?since= + subscribe/unsubscribe handlers + return latest_id
[in_progress] Phase A.4: index.ts switch HTTP to stateful, register subscriber registry, implement onAlert broadcast
[pending]    Phase A.5: build packages/mcp-server + smoke curl verify subscribe/notify
[pending]    Phase B.1: scaffold packages/framework-adapter-sdk (package.json / tsconfig / .npmignore)
[pending]    Phase B.2: SDK types.ts (AlertSink, AlertPayload, AdapterConfig, CursorStore)
[pending]    Phase B.3: SDK cursor.ts (MemoryCursorStore + FileCursorStore)
[pending]    Phase B.4: SDK adapter.ts (SmartBuildingAdapter: subscribe / notification handler / per-monitor mutex / reconnect / poll fallback)
[pending]    Phase B.5: SDK build clean
[pending]    Phase C.1: tests/framework-adapter-sdk fixtures + mock MCP server
[pending]    Phase C.2: SDK unit tests (basic + coalescing + concurrency + cross-monitor + poll fallback + cursor persistence)
[pending]    Phase D.1: scaffold examples/openclaw (package.json / openclaw.plugin.json / index.ts)
[pending]    Phase D.2: vendor session-append.ts from smarthome-video (with TODO migrate)
[pending]    Phase D.3: sink.ts + format.ts + config.ts
[pending]    Phase D.4: seed agents/ from smarthome workspace (hard-copy .md files)
[pending]    Phase D.5: install.sh (build + symlink + persona cp -n + json snippet)
[pending]    Phase D.6: README.md (single-page install guide)
[pending]    Phase E: docs/framework-adapters/{README,deployment,writing-a-new-framework-adapter,openclaw}.md
[pending]    Phase F: dev_status.md check off line 185-186 and add adapter items
```

---

## 关键上下文引用（新 session 冷启动可读）

- **CLAUDE.md 项目概览**：`/home/mytest/agent-ai.smart-community-ai-automation/CLAUDE.md` （如果有）+ smarthome 项目的 `/home/mytest/agent-ai.smarthome/CLAUDE.md`（很详细，尤其是 OpenClaw 相关设计）
- **原始 plan 文件**：`docs/dev/plans-backup/MCP-resource-subscription-plan.md`（源自 `~/.claude/plans/rustling-giggling-giraffe.md`）
- **AlertCallback 已有定义**：[packages/mcp-server/src/video-worker/index.ts:13](../../packages/mcp-server/src/video-worker/index.ts#L13)
- **onAlert 现状**：在 [index.ts](../../packages/mcp-server/src/index.ts) 已经改写完毕，只等 A.4 收尾
- **保序 & 抗错乱设计**：跨摄像头（uri 分片）、同摄像头（AUTOINCREMENT id + ORDER BY id + adapter 端 per-monitor mutex）、coalescing/丢失（since 游标 + optional 兜底轮询默认关闭）
- **OpenClaw v2026.6.9 现状**：无一等 raw-append API；smarthome-video 靠 FS-append 到 session JSONL（代码里 `// Hack path`）；session-append 需要写 user+assistant 两行（controlUI UX 约束，连续 same-role 会合并时间戳）
- **example plugin 部署原则**：0 成本——install.sh 一键 build + symlink + cp 硬拷贝进 example 的 agent personas 到 `~/.openclaw/agents/`（`cp -n` 幂等），提示用户粘贴 openclaw.json snippet + 重启 gateway
