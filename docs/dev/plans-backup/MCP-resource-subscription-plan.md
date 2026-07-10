# Plan: MCP resource subscription for alerts + framework adapter SDK

## Context

`task-poller.ts` 命中 rule 后调用 `db.createAlert()` + `onAlert(monitorId)` callback，但 callback 目前只 `logger.debug`——alert 只落 DB，没有推给任何 agent。我们要闭环这条通道，但**保持 MCP server 完全 host-agnostic**（不知道 OpenClaw、不知道 Feishu、不知道 session）。

方案：MCP server 只发协议标准的 `notifications/resources/updated`；每个 agent framework（OpenClaw 是第一个，Hermes / Claude Desktop / LangGraph 可能后续加）自己写一个 **adapter**——一个长活进程，内含通用 MCP client + 该 framework 特定的注入逻辑。为了让"再加一个 framework"这件事的成本可控，把 MCP client 那部分抽成可复用的 SDK 包。

设计约束（已与用户确认）：
- **不做 persona 润色**——adapter 直接投递原始 alert 到 session
- **路由表放 adapter 侧**（monitor → session[] 映射由 OpenClaw plugin 自己配），MCP server 不知道 session 概念
- 首个语言目标 **TypeScript**——MCP server 是 TS，OpenClaw 扩展是 TS，类型可通过 workspace package 直接共享
- Python 版本延后，等第一个 Python-only host 出现时再做

---

## 命名约定（避免概念冲突）

项目里有两个"adapter"和两个"session"，先钉死：

### Adapter — 两种

| 名词 | 指什么 | 落点 | 本 plan |
|------|--------|------|--------|
| **Framework Adapter** | 让 agent framework（OpenClaw / Hermes / LangGraph...）能接 MCP server alert 通知的桥 | `framework-adapter-sdk` + 每个 framework 一个具体实现 | **本 plan 的对象** |
| **Use Case Adapter** | 让不同 use case（fridge / child_safety / elder_wakeup）定制 rule / parser / schema | `use_case_dict` + `evaluate_rules_path` Python override + `schema.extensions` | **已存在，不属本 plan** |

### Session — 两种

| 名词 | 指什么 | 谁在用 |
|------|--------|--------|
| **MCP session** | client↔server 一次协议连接，有 sessionId（Streamable HTTP stateful 分配） | MCP server 内部 `McpSubscriberRegistry`；SDK 客户端 |
| **OpenClaw session** | agent 会话，形如 `agent:<id>:main` / `agent:<id>:feishu:group:oc_xxx` | Framework adapter sink → `api.runtime.subagent.run({ sessionKey })` |

所以 `McpSubscriberRegistry` 里 `SubscriberEntry` 的 sessionId **是 MCP session**（协议连接标识），不是 OpenClaw 那种 agent chat session。命名上刻意用 "Subscriber" 而不是 "Session" 就是为了少一个歧义源。

---

## Cooldown 职责分层

告警连续触发的抑制不在 SDK 通用层做，而是三层各司其职：

| Level | 责任层 | 作用 | 何时用 |
|-------|--------|------|--------|
| **L1 业务 cooldown** | MCP server rule engine (`evaluate_rules_path`) | 决定"这条事件算不算 alert"——是否 `db.createAlert` | 已由 use case adapter 承担（Python override 里自己写）。例："同类事件 5 分钟内不重复告警" |
| **L2 投递去重** | framework-adapter-sdk cursor | 保证同一条 alert.id 不推两次 | SDK 天然由 cursor 提供，无需配置 |
| **L3 渠道节流** | framework adapter 的 sink 内部（如 OpenClaw plugin） | 决定"已产生的 alert 是否推到某 session/channel" | 可选。例："同 Feishu 群 5 分钟已推 3 条则合并" |

**为什么 SDK 通用层不加时间窗抑制**：会引入意外丢弃、破坏 at-least-once 语义、决策"什么算烦"依赖 session/channel 上下文（Feishu 群和 agent 主会话容忍度不同）。这层节流放在 framework adapter 的 sink 里做才符合职责。

---

## 架构一览

```
┌─────────────────────────────┐         ┌─────────────────────────────┐
│  MCP server (existing TS)   │         │  Adapter (per framework)    │
│  packages/mcp-server        │         │                             │
│                             │◀────────│  Long-lived process         │
│  task-poller → createAlert  │  MCP    │  ┌────────────────────────┐ │
│      ↓                      │  over   │  │ SmartBuildingAdapter   │ │
│  onAlert(monitorId)         │  HTTP   │  │  (framework-adapter-sdk, generic)│ │
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

## 1. MCP server 侧改动

### 1.1 现状盘点（改动前）

**AlertCallback 类型**（[packages/mcp-server/src/video-worker/index.ts:13](packages/mcp-server/src/video-worker/index.ts#L13)）:
```typescript
// Notifies MCP server that an alert was created for a monitor (triggers resource notification)
export type AlertCallback = (monitorId: string) => void;
```
签名意图**已经明确**是要 trigger resource notification（注释都写好了）。

**onAlert 实现**（[packages/mcp-server/src/index.ts:95-97](packages/mcp-server/src/index.ts#L95)）:
```typescript
const onAlert = (monitorId: string) => {
  logger.debug(`[worker] Alert triggered for monitor ${monitorId}`);
};
```
只 log，没 notification 实现。

**HTTP transport 是 stateless**（[packages/mcp-server/src/index.ts:108-135](packages/mcp-server/src/index.ts#L108)）：每个 request `createMcpServer()` 新建 McpServer，`res.on("close", ...) { transport.close(); server.close(); }`。**没有长活 McpServer 实例可供 `onAlert` 引用**——这是本方案第一大障碍。stdio 模式（line 142-146）单实例长活，天然 OK。

### 1.2 切 stateful HTTP + 引入 McpSubscriberRegistry

**`packages/mcp-server/src/index.ts`** 重构 HTTP 处理路径：

- `McpServer` 声明 `capabilities.resources = { subscribe: true, listChanged: false }`
- 新增模块 `packages/mcp-server/src/mcp-subscriber-registry.ts`：
  ```typescript
  interface SubscriberEntry {
    server: McpServer;
    transport: StreamableHTTPServerTransport;
    subscriptions: Set<string>;        // 该 session subscribe 的 uri 集合
  }
  export class McpSubscriberRegistry {
    private sessions = new Map<string, SubscriberEntry>();
    register(sessionId, entry): void;
    unregister(sessionId): void;
    addSubscription(sessionId, uri): void;
    removeSubscription(sessionId, uri): void;
    /** 返回所有订阅了 uri 的 session — onAlert 广播用。 */
    findSubscribers(uri): SubscriberEntry[];
  }
  ```
- HTTP handler 改造：
  - 从 `initialize` request 里拿/生成 `sessionId`，`StreamableHTTPServerTransport` 用 `sessionIdGenerator: () => crypto.randomUUID()`
  - 已知 sessionId 的后续请求：路由到 registry 里已存在的 `{ server, transport }`
  - 新 sessionId：createMcpServer + transport，注册到 registry，`res.on("close")` **不再** close server（只在 explicit DELETE / session 超时时 close）
- `registerResources()` 里 subscribe/unsubscribe handler hook 进 registry：MCP SDK v1.29.0 的 `McpServer` 高层不直接暴露这两个 handler 的 override 入口，需退到 `server.server.setRequestHandler(SubscribeRequestSchema/UnsubscribeRequestSchema, ...)`（low-level）里更新 registry

### 1.3 onAlert 实现

**`packages/mcp-server/src/index.ts`**（把 registry 注入 onAlert）:
```typescript
const subscriberRegistry = new McpSubscriberRegistry();

const onAlert: AlertCallback = (monitorId) => {
  const uri = `smartbuilding://monitor/${monitorId}/alerts`;
  const subscribers = subscriberRegistry.findSubscribers(uri);

  // stdio 模式的常驻 mcpServer 也算一个"session"，登记进 registry 即可
  if (subscribers.length === 0) {
    logger.debug(`[worker] alert for ${monitorId} — no subscribers, dropped`);
    return;
  }
  for (const { server } of subscribers) {
    server.server.sendResourceUpdated({ uri }).catch(err =>
      logger.warn(`[worker] sendResourceUpdated ${uri} failed: ${err.message}`)
    );
  }
};
```

notification 只带 uri，不带 payload——保持 MCP 语义纯粹，client 收到后自己 read 拉最新。**registry 兼容 stdio + HTTP**：stdio 模式那个单例也登记进去（作为固定 sessionId），逻辑统一。

### 1.4 resources.ts 加游标读

**`packages/mcp-server/src/resources.ts`**
- `smartbuilding://monitor/{id}/alerts` 已存在，但目前固定返回最新 20 条
- 解析可选查询参数 `?since=<alert_id>`（URL 里带），server 侧解析出 id 后调 `db.queryAlerts({ monitorId, sinceId })`
- Response contents 里包含 `latest_id`（本次结果里最大的 alert.id）供 client 存作下次游标
- 无 alert 时返回空数组 + 当前 `max(id)`（避免 client 首次连接时全量重放历史 alert）

**`packages/db/src/database.ts`**：`queryAlerts()` 加 `sinceId?: number` 参数——SQL 增加 `AND id > ?`。

**不把 alert 塞进 notification payload** ——保持 MCP 语义纯粹（notification 只通知"变了"，state 靠 read 拉）。dedup + 保序逻辑集中在 client 侧的游标追踪，简单可靠。

### 1.5 保序 & 抗错乱设计

同时段 / 跨摄像头 alert 不错乱要靠三层保证：

| 风险 | 机制 |
|------|------|
| **跨摄像头串扰** | 每 monitor 独立 uri `smartbuilding://monitor/<id>/alerts` → notification 带 uri → adapter 按 uri 查各自游标 → SQL `WHERE monitor_id = ? AND id > ?`。全链路按 monitor 分片。 |
| **同摄像头顺序** | `alerts.id` SQLite AUTOINCREMENT 单调递增；`queryAlerts` 一律 `ORDER BY id ASC`；adapter 端 per-monitor mutex 串行化 read + sink.push（同一 monitor 的两条 notification 处理不并发）。 |
| **Notification coalescing / 丢失** | server 可能合并多次 update 为一次 notification（MCP 允许）——由于 read 用 `?since=cursor` 拿全量增量，合并没有副作用。彻底丢失 notification 是 subscribe 模式的固有短板，SDK 提供 optional **低频兜底轮询**（`pollFallbackMs`，默认 **0=关闭**，需要时显式设正值）：定时对每个订阅 uri 主动 read 一次，若 latest_id > cursor 则触发正常处理流程。 |

跨摄像头之间**不保证**全局时序（cam_child 的 T0 alert 与 cam_elder 的 T0.001 alert 在 sink 侧到达顺序可能相反）——但这不是问题，alert 是"某摄像头有事件"，不是跨摄像头协同事件，各自序列独立即可。

---

## 2. 新包：`packages/framework-adapter-sdk/`（通用 MCP client 层）

TypeScript，workspace 包名 `@smartbuilding-video/framework-adapter-sdk`。

### 2.1 Adapter 接口（对外唯一契约）

```typescript
export interface AlertSink {
  /** 每条新 alert，SDK 保证 at-least-once 调用一次。sink 内部要幂等。 */
  push(payload: AlertPayload): Promise<void>;
}

export interface AlertPayload {
  monitorId: string;
  alert: Alert;   // 从 @smartbuilding-video/db 直接复用 Alert 类型
}

export interface AdapterConfig {
  transport:
    | { kind: 'http'; url: string; headers?: Record<string, string> }
    | { kind: 'stdio'; command: string; args?: string[] };
  monitorIds: string[];                    // 要订阅的 monitor id 列表
  reconnect?: { initialMs?: number; maxMs?: number; factor?: number };  // 默认 1000/30000/2
  cursorStore?: CursorStore;               // 不填则内存态（重启会重放当日全量）
  /** 兜底轮询周期，防 notification 彻底丢失。默认 0（关闭），需要时显式设正值（例如 60000ms）。 */
  pollFallbackMs?: number;
  logger?: Logger;
}

export interface CursorStore {
  get(monitorId: string): Promise<number | null>;
  set(monitorId: string, alertId: number): Promise<void>;
}

export class SmartBuildingAdapter {
  constructor(config: AdapterConfig, sink: AlertSink);
  async start(): Promise<void>;   // connect + subscribe + 首次 read 拿 max_id 存游标
  async stop(): Promise<void>;    // unsubscribe + close transport
}
```

### 2.2 内部逻辑

- 用 `@modelcontextprotocol/sdk/client` + `StreamableHTTPClientTransport` / `StdioClientTransport`
- `start()`：connect → 对每个 monitorId 调 `subscribeResource({ uri })` → 立即 read 一次拿当前 `latest_id` 存进游标（避免启动时重放历史 alert）→ 启动兜底轮询定时器（若 `pollFallbackMs > 0`）
- `setNotificationHandler(ResourceUpdatedNotificationSchema, ...)`：收到 uri → **进入 per-monitor mutex** → 查游标 → `readResource({ uri: uri + '?since=' + cursor })` → 对每条新 alert 顺序调 `sink.push()` → 全部成功后 `cursorStore.set(latest_id)`（原子推进，中途失败下次重放）→ 释放 mutex
- **Per-monitor mutex**：`Map<monitorId, Promise>` 链式串起该 monitor 的所有 read+push 操作，保证同一 monitor 的 notification 不并发处理（避免同一时段两条 notification 同时 read 导致重复推送 / 游标写回竞态）。跨 monitor 不加锁——允许并发
- **兜底轮询**（optional）：定时对每个订阅 uri 主动 read 一次；若发现 `latest_id > cursor`，走同一 per-monitor mutex 路径处理增量。抵御 notification 彻底丢失
- 断连：捕获 transport error → sleep(backoff) → 重连 → 重新 subscribe（stateful 模式下 session 断了就丢，client 必须重订阅）→ 用现有游标继续（保证不丢 alert）
- `stop()`：清兜底定时器 → unsubscribe → transport.close()

### 2.3 包结构

```
packages/framework-adapter-sdk/
├── package.json           # deps: @modelcontextprotocol/sdk, @smartbuilding-video/db (types only)
├── .npmignore             # 排除 examples/ 不进发布包
├── src/
│   ├── index.ts           # exports: AlertSink, AlertPayload, AdapterConfig, SmartBuildingAdapter, CursorStore
│   ├── adapter.ts         # SmartBuildingAdapter 主类
│   ├── cursor.ts          # MemoryCursorStore + FileCursorStore（JSON 文件）
│   └── types.ts           # 共享类型
└── examples/              # 参考消费者（不 export、不入发布包）
    └── openclaw/          # OpenClaw framework adapter 参考实现（见 §3）
```

**测试放项目根** `tests/framework-adapter-sdk/`（与既有 `tests/mock/videostream-analytics/`、`tests/dev-mcp-server/` 同层）：
```
tests/framework-adapter-sdk/
├── adapter.test.ts        # mock MCP server → sink 调用 + 游标推进 + 断线恢复 + 兜底轮询
└── fixtures/              # 测试用 mock server 骨架
```

---

## 3. 参考实现：`packages/framework-adapter-sdk/examples/openclaw/`

**部署原则：0 成本**。用户拿到本 repo 后到"alert 通到 OpenClaw session"只需要：build → 指向 ~/.openclaw/ → 改一次 openclaw.json → 重启 gateway。**这不是文档式示范代码，是一个开箱即用、投产可用的完整 OpenClaw plugin**。

**目录结构**（**agent personas 硬拷贝进 example，让 example 完全自包含**）：
```
packages/framework-adapter-sdk/examples/openclaw/
├── openclaw.plugin.json    # OpenClaw plugin metadata（id, permissions, schema）
├── package.json            # deps: @smartbuilding-video/framework-adapter-sdk (workspace file:), yaml
├── index.ts                # definePluginEntry() 主入口（骨架见 §3.2）
├── src/
│   ├── config.ts           # 读 pluginConfig 解析 subscriptions
│   ├── sink.ts             # OpenClaw AlertSink 实现（见 §3.3）
│   ├── session-append.ts   # vendor 自 smarthome-video 的 FS-append 助手（含 TODO 迁移标注）
│   └── format.ts           # formatAlert(alert) → string
├── agents/                 # ★ 硬拷贝 3 个 agent 的 workspace .md 文件进 repo
│   ├── child-safety-agent/workspace/
│   │   ├── AGENTS.md
│   │   ├── IDENTITY.md
│   │   ├── SOUL.md
│   │   └── USER.md
│   ├── elder-wakeup-agent/workspace/
│   │   └── ... (4 个 .md)
│   └── fridge-agent-en/workspace/
│       └── ... (4 个 .md)
├── install.sh              # 一键：build → symlink plugin + cp agents/ 进 ~/.openclaw/agents/
└── README.md               # 单页安装指南 + 配置片段
```

**agents/ 硬拷贝的来源与维护**：初次拷贝自 `~/agent-ai.smarthome/agent-ai.smarthome-openclaw-runtime-workspace/agents/<id>/workspace/*.md`（child-safety-agent / elder-wakeup-agent / fridge-agent-en）。之后作为本 repo 的 **一等资产**独立演化。smarthome 侧 persona 若更新，需手工同步一次（非高频事件）。好处：example 完全自包含，用户不需要 smarthome workspace 也能跑；坏处：出现 persona 双源，维护成本转移到偶尔手工同步。

**install.sh 的完整职责**：

```bash
# 1) build plugin + symlink 进 OpenClaw extensions
npm install && npm run build
ln -sfn "$PWD" ~/.openclaw/extensions/smartbuilding-alerts

# 2) 从本 example 目录内的 agents/ 拷 personas 进 ~/.openclaw/agents/
#    无外部依赖、无环境变量、幂等（存在则 -n 保留用户已改动版本）
for agent_dir in agents/*/; do
  agent_id=$(basename "$agent_dir")
  dst="$HOME/.openclaw/agents/$agent_id/workspace"
  mkdir -p "$dst"
  cp -nv "$agent_dir/workspace/"*.md "$dst/"   # -n 不覆盖用户已有的 md
done

# 3) 打印 openclaw.json snippet 提示用户粘贴 + 手动重启 gateway
cat <<'EOF'
Now add to ~/.openclaw/openclaw.json under "extensions":
  "smartbuilding-alerts": {
    "mcpServer": { "url": "http://localhost:3100/mcp" },
    "monitors": { "cam_child": { "alerts": [{ ... }] } }
  }
Then restart the OpenClaw gateway.
EOF
```

`cp -n` 是**幂等**关键——第二次跑 install.sh 不会覆盖用户已经改过的 persona md。

### 3.1 config shape（`openclaw.plugin.json` 中读）

**monitor-centric + flow-type key**，为未来扩展（reports / tasks / status 等 flow）留位：

```json
{
  "mcpServer": { "url": "http://localhost:3100/mcp" },
  "monitors": {
    "cam_child": {
      "alerts": [
        { "agentId": "child-safety-agent", "sessionKey": "agent:child-safety-agent:main",                "deliver": false },
        { "agentId": "child-safety-agent", "sessionKey": "agent:child-safety-agent:feishu:group:oc_xxx", "deliver": true  }
      ]
      // future flows for same monitor 可加同层 key：
      // "reports": [{ agentId, sessionKey, deliver, cron: "0 22 * * *" }],
      // "status":  [{ agentId, sessionKey, deliver }],
    },
    "cam_elder_bedroom": {
      "alerts": [
        { "agentId": "elder-wakeup-agent", "sessionKey": "agent:elder-wakeup-agent:main", "deliver": false }
      ]
    }
  }
}
```

**语义**：`monitors.<id>.<flow>[]` = "该 monitor 的该 flow 类型触发时，投递到这些 session"。Flow 类型对应 MCP server 侧不同的 resource uri：
- `alerts` → `smartbuilding://monitor/<id>/alerts`（本 plan 唯一实现的 flow）
- `reports`（未来） → `smartbuilding://monitor/<id>/reports`
- `status`（未来） → `smartbuilding://monitor/<id>/status`

**SDK 侧**：`AdapterConfig.monitorIds` 是 alerts-only 的窄接口。未来加新 flow 时扩为 `subscriptions: Array<{ monitorId: string; flow: 'alerts' | 'reports' | ... }>`——本 plan 不做，只在文档里标注扩展点。当前 SDK 内部所有 subscribe 都走 alerts uri。

### 3.2 实现骨架

```typescript
import { definePluginEntry, type OpenClawPluginApi } from "./api.js";
import { SmartBuildingAdapter, type AlertSink } from "@smartbuilding-video/framework-adapter-sdk";
import { FileCursorStore } from "@smartbuilding-video/framework-adapter-sdk/cursor";

export default definePluginEntry({
  id: "smartbuilding-alerts",
  register(api: OpenClawPluginApi) {
    const cfg = api.pluginConfig as {
      mcpServer: { url: string };
      monitors: Record<string, {
        alerts?: Array<{ agentId: string; sessionKey: string; deliver?: boolean }>;
        // 未来: reports?: [...], status?: [...] 等 flow
      }>;
    };

    const sink: AlertSink = {
      async push({ monitorId, alert }) {
        const targets = cfg.monitors[monitorId]?.alerts ?? [];
        if (targets.length === 0) {
          api.logger.warn(`[sb-alerts] no route for monitor=${monitorId}`);
          return;
        }
        const message = formatAlert(alert);
        await Promise.all(targets.map(async t => {
          const idempotencyKey = `sb-alert:${monitorId}:${alert.id}`;
          if (t.deliver) {
            // Channel binding (Feishu/WeChat): 用 subagent.run + 强透传 system prompt。
            // channel adapter 内部走 LLM，我们通过 prompt 尽量 raw；未来官方 API 落地可换。
            await api.runtime.subagent.run({
              sessionKey: t.sessionKey,
              message,
              deliver: true,
              extraSystemPrompt: "You are a message relay. Reply with the user's message verbatim, no rewriting.",
              idempotencyKey,
            });
          } else {
            // Agent 主会话：直接 FS-append user+assistant 两行（controlUI UX 约束，见 §3.3）。
            // 两行都由本 plugin 合成，零 LLM。
            await appendAlertTurns(t.sessionKey, {
              separator: formatSeparator(alert),    // 🔔 [severity] event — ts monitor
              payload: message,                     // formatAlert(alert) 已算好
              idempotencyKey,
            });
          }
        }));
      }
    };

    const adapter = new SmartBuildingAdapter({
      transport: { kind: 'http', url: cfg.mcpServer.url },
      monitorIds: Object.keys(cfg.monitors),
      logger: api.logger,
      cursorStore: new FileCursorStore(path.join(openclawHome(), "smartbuilding-alerts-cursor.json")),
    }, sink);

    api.registerService({
      id: "smartbuilding-alerts-adapter",
      async start() { await adapter.start(); },
      async stop() { await adapter.stop(); },
    });
  }
});

function formatAlert(alert: Alert): string {
  return `[${alert.useCase}] ${alert.description ?? ''}`;
}
```

### 3.3 raw session append 的实现路径（现状 & 迁移）

**OpenClaw v2026.6.9 现状**：**没有**一等的"raw session append" API。已确认（Explore 结果）：
- `api.runtime.subagent.*` 只暴露 `run` / `waitForRun` / `getSessionMessages`——`run` 天然要走 LLM 生成
- 更底层的 `patchSessionEntry` / `updateSessionStoreEntry` 存在于 session-store runtime module，但**未通过** plugin SDK 的 `api.runtime` 表面对外暴露
- 现有 smarthome-video 的 notifier 里就是靠 `subagent.run({ deliver: false })` 建 run 记录 + **直接 FS-append 到 `~/.openclaw/agents/<id>/sessions/<sessionId>.jsonl`**（代码里注释就叫 `// Hack path`）

**本 plugin 的选择**：**沿用同一 FS-append 模式**——不重复发明轮子。理由：
1. 是当前 OpenClaw 上唯一稳定 raw-append 路径（smarthome-video 生产在跑）
2. gateway 的 orphan sweep（session-delete.ts 里 60s 扫）已经理解这种写入格式
3. 私接底层 `patchSessionEntry` 需绕过 plugin SDK 边界，反而更脆

**具体做法**：
- vendor smarthome-video 的 append 助手到 `examples/openclaw/src/session-append.ts`（不跨 repo 依赖）
- **仍然写 user turn + assistant turn 两行**——**不是**因为需要 LLM 生成 assistant，而是 controlUI 的**已知 UX 约束**：连续 same-role turn 会合并成一个 bubble、显示首条时间戳。smarthome-video 里注释已明确说明这一点（"we appended only assistant lines, every new alert would be glued to the previous group"）
- 两行的内容都由本 plugin 直接合成，零 LLM：
  - `userLine.content` = 短分隔符 `🔔 [<severity>] <event> — <timestamp> <monitor_id>`（operator 一眼可读的 marker）
  - `assistantLine.content` = raw alert 描述（就是 alert.description，格式化后原文透传）
  - `assistantLine.message.model` 填 `"smartbuilding-alerts-adapter"` 之类的标识（不是真 LLM，只是记录源头）
- **agent 主会话下次自主读到时**，这两行是它的上下文——是否回应由 agent 自己决定（例如 child-safety-agent 收到 critical alert 时可能主动 push 建议）
- `deliver: true` 分支（Feishu / WeChat 群 session）走 `subagent.run({ deliver: true, extraSystemPrompt: 'You are a relay. Reply with the user message verbatim.' })`——channel adapter 内部走一次 LLM 但强透传；这层"最后一层 LLM 开销"待官方 API 落地去除

**迁移点**（TODO 注释写进 sink.ts）：
```typescript
// TODO(migrate): when OpenClaw exposes api.runtime.session.append(sessionKey, message),
// replace the appendJsonl() call below with the official API.
// See openclaw runtime versions ≥ 2026.6.9; not yet available.
```

**在 plan/文档中如实标注**——不称"hack"（"hack" 是 smarthome-video 代码里对某种代码风格的自嘲，不是外部标签）；称之为"当前 raw append 事实通道"，等 OpenClaw 官方 API 落地即切换。

---

## 4. 文档

### 4.1 `docs/framework-adapters/README.md`
- 一页架构图（同上面的 ASCII）
- 协议流程时序图：task-poller → sendResourceUpdated → adapter 收 notification → read → sink.push → session 写入
- Adapter 概念：protocol layer（SDK 提供）vs injection layer（framework 特定）
- 何时该写 adapter（有长活进程 + 能注入 session）vs 何时该退回 outbound webhook（host 不能长活或没 session 概念）

### 4.2 `docs/framework-adapters/deployment.md`
- MCP server 侧：如何切 stateful HTTP、subscribe capability 检查、验证清单
- Adapter 侧部署形态：daemon / 嵌在 gateway / systemd unit 示例
- 网络拓扑：MCP server + 多 adapter 各自订阅子集的场景
- Cursor 持久化位置约定 + 手工重置说明
- 常见故障排查：subscribe 收不到 → 检查 stateful HTTP；游标漂移 → 删 cursor 文件；重放太多 → 缩小 monitor 集

### 4.3 `docs/framework-adapters/writing-a-new-framework-adapter.md`
五步指南 + 最小完整示例。骨架：
1. **Install**：`npm i @smartbuilding-video/framework-adapter-sdk`
2. **Implement `AlertSink`**：一个 `push()` 方法即可；返回 Promise
3. **Provide `AdapterConfig`**：transport / monitorIds / cursorStore
4. **Own a long-lived process**：daemon 或 host 的 plugin 生命周期；`start()` on boot / `stop()` on shutdown
5. **Verify**：mock MCP server + fake alert，断言 sink 收到

结尾附"OpenClaw 参考实现"链接 + "host 无法长活/无 session 概念时改用 outbound webhook"退路说明。

### 4.4 `docs/framework-adapters/openclaw.md`
- **不重复安装步骤**——投产用户看 `packages/framework-adapter-sdk/examples/openclaw/README.md`（install.sh + 3 步）
- 本文只做概念说明：
  - 参考实现代码走读（sink 如何调 `api.runtime.subagent.run`，为什么 `polish=false + deliver=<by target>` 组合）
  - `openclaw.plugin.json` 配置 schema
  - 与现有 smarthome-video plugin 的关系：互补，不冲突。smarthome-video 走"内嵌 rule + 润色 + FS-append"重路径；这里走"MCP subscribe + raw pass-through"轻路径
  - 迁移路径（可选未来工作）：如何把 smarthome plugin 的 notifier 逻辑改成 adapter 模式

---

## 关键文件

| 文件 | 类型 | 内容 |
|------|------|------|
| `packages/mcp-server/src/index.ts` | edit | HTTP 改 stateful；构造 McpSubscriberRegistry；`onAlert` 改为 registry-based 广播；stdio 单例登记进 registry |
| `packages/mcp-server/src/mcp-subscriber-registry.ts` | new | `McpSubscriberRegistry` — 维护 sessionId → { server, transport, subscriptions } 映射；提供 findSubscribers(uri) |
| `packages/mcp-server/src/resources.ts` | edit | alerts resource 解析 `?since=<id>`；response 加 `latest_id`；用 `server.server.setRequestHandler(SubscribeRequestSchema, ...)` 更新 registry |
| `packages/mcp-server/src/video-worker/index.ts` | no change | AlertCallback 类型已存在且语义正确，只是 onAlert 实现在 index.ts 里升级 |
| `packages/db/src/database.ts` | edit | `queryAlerts()` 加 `sinceId?: number` 参数 |
| `packages/framework-adapter-sdk/**` | new | 通用 SDK 包（唯一新增 workspace 包，§2） |
| `packages/framework-adapter-sdk/examples/openclaw/**` | new | OpenClaw 参考消费者（非 workspace 包，§3） |
| `tests/framework-adapter-sdk/**` | new | SDK 单元测试，与项目现有 tests/ 同层 |
| `docs/framework-adapters/README.md` | new | 架构 + 概念 |
| `docs/framework-adapters/deployment.md` | new | 部署指南 |
| `docs/framework-adapters/writing-a-new-framework-adapter.md` | new | 开发者指南 |
| `docs/framework-adapters/openclaw.md` | new | 参考实现走读 |
| `docs/dev/dev_status.md` | edit | 勾掉 line 185-186 两项待办；加"adapter SDK / OpenClaw adapter"新条目 |

---

## 验证

1. **构建**：`npm run build` 全 workspace 零错误（新增 2 包 + 4 文档）
2. **MCP server 手工验证**：
   - `curl` 发 `initialize` + `resources/subscribe { uri: 'smartbuilding://monitor/cam_child/alerts' }` → 200 OK，capability advertised
   - 手工 SQL 插一条 alert 或跑一次真实 task-poller → SSE 通道收到 `notifications/resources/updated`
   - 读带 `?since=<id>` → 只返 id > since 的 alert；response 里含 `latest_id`
3. **Adapter SDK 单元**（`tests/framework-adapter-sdk/`）：
   - Mock MCP server 推 notification → adapter sink.push 被调用 1 次
   - 连续推 3 条 alert，游标存 FileCursorStore → 重启 adapter → 只从游标之后 read（不重放）
   - 断线 → adapter 重连 + 重订阅 → 恢复期内产生的 alert 通过下次 read 得到
   - **Coalescing 保序**：mock server 同一 uri 快速推 5 次 update（对应 5 条新 alert），server 合并只发 1 次 notification → adapter 单次 read 拿全 5 条 → sink.push 严格按 id 升序
   - **并发防抖**：单一 uri 快速推两次 notification，adapter per-monitor mutex 起效 → 两次 read 串行完成，游标最终只推进一次到 max_id，无重复推送
   - **跨摄像头独立**：cam_A 和 cam_B 各推 3 条 alert 交叉发 notification → sink.push 收到 6 条，cam_A 内部顺序对，cam_B 内部顺序对，交叉顺序不做保证（符合设计）
   - **兜底轮询**：mock server 故意"丢"一次 notification（不发送）→ 60s 内 adapter 通过轮询发现 latest_id > cursor → 补投递 sink.push
4. **端到端**（OpenClaw adapter）：
   - **install.sh 干净跑通**：从零环境（未装本 plugin 的 OpenClaw）执行 `bash examples/openclaw/install.sh` → 输出提示的 openclaw.json snippet → 用户粘贴 + 重启 OpenClaw → gateway 日志显示 plugin 加载成功
   - MCP server + OpenClaw 都启动，OpenClaw 装 `smartbuilding-alerts` 插件配好 `monitors.<id>.alerts` 路由 + agent personas 已由 install.sh 从 example/agents/ 硬拷贝进 `~/.openclaw/agents/`（无需外部 smarthome workspace）
   - 触发一次 mock alert（走 mock_server.py → videostream-analytics → webhook → task-poller）
   - 目标 session JSONL 文件增加一条 user turn，内容 = raw alert 格式
   - deliver:true 的 target 触发对应 channel（Feishu 群收到消息）
5. **多路由**：一条 monitor 配 2 个 target（agent main + Feishu 群）→ 两处都收到
6. **Idempotency**：手工重复 push 同一 alert（模拟 SDK 重试）→ subagent.run 的 idempotencyKey 抑制重复
7. **文档验证**：按 `writing-a-new-framework-adapter.md` 走一遍最小示例，跑通即算文档 OK

---

## 后续（不在本 plan 范围）

- Python 版 framework-adapter-sdk（等第一个 Python host 需求出现再做，接口对齐即可）
- 更细粒度的 subscribe（`smartbuilding://monitor/{id}/alerts?severity=critical`）
- `notifications/resources/updated` 之外，通过 MCP `sampling` 让 adapter 借 MCP server 侧 LLM 做 host-agnostic 润色（如果未来某个 host 想要润色又不想自己接 LLM）
