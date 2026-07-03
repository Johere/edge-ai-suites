# Use Case Catalog

本文档汇总 SmartBuilding Video 平台设想的**所有测试 / 落地场景**，作为 use case adapter 的实施蓝本。85 个 case 按部署环境分 7 类。

**列说明**：
- **ID**：全局唯一，前缀标场景族（CS/EW/BB/PT/GN/FS/AC/HA/EL/PK/CN/PP/RT/OD/ST/NG）
- **Severity**：默认输出严重级；`—` 表示只出信息类日报
- **难度**：即梦 AI 生成视频的复杂度 ★ / ★★ / ★★★
- **状态**：✅ 已实现 adapter / 🟡 有 prompt 无 rules / 🔴 未开发
- **技术依赖**：VLM 描述 / YOLO 类别 / ROI / 时间窗 / monitor_state

**相关文档**：
- [Use case adapter 使用手册](./use-case-adapter.md)
- [端到端测试 recipe](./use-case-adapter-gsg.md)
- [第 1 批 10 case 完整落地方案](#附录-a第-1-批-10-个-case-完整落地方案)

---

## 目录

- [1. 家庭室内 (Home Indoor)](#1-家庭室内-home-indoor)
- [2. 社区 / 楼宇 (Community / Building)](#2-社区--楼宇-community--building)
- [3. 停车场 (Parking)](#3-停车场-parking)
- [4. 施工场景 (Construction Site)](#4-施工场景-construction-site)
- [5. 商业 / 门店 (Retail)](#5-商业--门店-retail)
- [6. 户外 / 公共 (Outdoor / Public)](#6-户外--公共-outdoor--public)
- [7. 特殊状态类 & 反例 (State / Negative)](#7-特殊状态类--反例-state--negative)
- [附录 A：第 1 批 10 个 case 完整落地方案](#附录-a第-1-批-10-个-case-完整落地方案)
- [附录 B：视频生成基线要求](#附录-b视频生成基线要求)

---

## 1. 家庭室内 (Home Indoor)

### 1.1 儿童安全（Child Safety）

| ID | 场景 | Severity | 难度 | 状态 | 技术依赖 |
|----|------|---------|------|------|---------|
| CS-1 | 攀爬窗台 / 书架 | critical | ★★ | ✅ | VLM + person |
| CS-2 | 摔倒（沙发跌落 / 跑步绊倒） | critical | ★★ | ✅ | VLM + person |
| CS-3 | 平静玩玩具（反例） | info | ★ | ✅ | — |
| CS-4 | 空客厅（反例） | — | ★ | ✅ | Prefilter SKIP |
| CS-5 | 玩打火机 / 火柴 | critical | ★★★ | 🟡 | VLM + YOLO(lighter) |
| CS-6 | 拿菜刀 / 剪刀 | critical | ★★★ | 🟡 | VLM + YOLO(knife/scissors) |
| CS-7 | 触摸电源插座 | critical | ★★ | 🟡 | VLM + hand ROI |
| CS-8 | 头卡进栏杆 | critical | ★★★ | 🔴 | VLM 姿态描述 |
| CS-9 | 独自靠近阳台边 | warn | ★★ | 🟡 | VLM + 阳台 ROI |
| CS-10 | 吞食小物件（塞进嘴里） | critical | ★★★ | 🟡 | VLM + hand-to-mouth |
| CS-11 | 上下楼梯不牵扶手 | warn | ★★ | 🔴 | VLM |
| CS-12 | 拉扯电线 / 桌布 | warn | ★★★ | 🔴 | VLM |

### 1.2 老人监护（Elder Care）

| ID | 场景 | Severity | 难度 | 状态 | 技术依赖 |
|----|------|---------|------|------|---------|
| EW-1 | 晚起 (>expected+grace) | warn | ★★ | ✅ | 时间窗 |
| EW-2 | 按时起（反例） | — | ★★ | ✅ | 时间窗 |
| EW-3 | 长时间躺床（反例） | — | ★ | ✅ | VLM event |
| EW-4 | 空卧室（反例） | — | ★ | ✅ | Prefilter SKIP |
| EW-5 | 跌倒（不同于坐下） | critical | ★★★ | 🟡 | VLM 姿态 |
| EW-6 | 长时间不动（可能昏迷） | critical | ★★ | 🔴 | 时间窗 + `state_query` |
| EW-7 | 药盒前未出现（未按时服药） | warn | ★★ | 🔴 | ROI + `state_query` |
| EW-8 | 摸墙走路 / 步态不稳 | warn | ★★★ | 🔴 | VLM 步态描述 |
| EW-9 | 深夜下床频繁 (>3 次/夜) | warn | ★★ | 🔴 | 计数 + `state_query` |
| EW-10 | 忘关燃气 / 水龙头 | critical | ★★★ | 🔴 | VLM 视觉证据 |

### 1.3 婴儿 / 宠物

| ID | 场景 | Severity | 难度 | 状态 | 技术依赖 |
|----|------|---------|------|------|---------|
| BB-1 | 婴儿翻身 + 被子覆盖头部 | critical | ★★★ | 🟡 | VLM 姿态 |
| BB-2 | 婴儿哭闹 > 5 分钟无人响应 | warn | ★★ | 🔴 | 需要声音传感器 |
| PT-1 | 宠物上餐桌 | warn | ★★ | 🟡 | YOLO(cat/dog) + 桌 ROI |
| PT-2 | 宠物咬电线 | critical | ★★★ | 🟡 | YOLO + VLM |
| PT-3 | 宠物走失（开门溜出） | critical | ★★ | 🟡 | YOLO + 门 ROI |
| PT-4 | 宠物长时间无食水 | info | ★★ | 🔴 | ROI + `state_query` |

### 1.4 家居通用

| ID | 场景 | Severity | 难度 | 状态 | 技术依赖 |
|----|------|---------|------|------|---------|
| GN-1 | 烟雾 / 明火（家电起火） | critical | ★★★ | 🟡 | VLM 视觉 |
| GN-2 | 门窗未关 > N 分钟 | info | ★ | 🔴 | `state_query` |
| GN-3 | 陌生人夜间入室 | critical | ★★★ | 🟡 | 时间窗 + VLM |
| GN-4 | 家电异常（冒烟 / 水漫地面） | critical | ★★★ | 🟡 | VLM |
| GN-5 | 家用摄像头被遮挡 | warn | ★ | 🔴 | 画面变黑检测 |

---

## 2. 社区 / 楼宇 (Community / Building)

### 2.1 消防安全（Fire Safety）

| ID | 场景 | Severity | 难度 | 状态 | 技术依赖 |
|----|------|---------|------|------|---------|
| **FS-1** | 电动车停在楼道 | critical | ★★ | 🟡 | YOLO(motorcycle) + 楼道 ROI |
| **FS-2** | 电动车进电梯 | critical | ★★ | 🟡 | YOLO + 电梯环境 |
| FS-3 | 电动车楼道充电 | critical | ★★★ | 🟡 | YOLO + 电线 VLM |
| FS-4 | 消防通道堆放杂物 | warn | ★★ | 🔴 | ROI + object |
| FS-5 | 消防栓被遮挡 | warn | ★★ | 🔴 | ROI + 障碍物 |
| FS-6 | 楼道 / 车库明火 | critical | ★★★ | 🟡 | VLM |
| FS-7 | 楼道抽烟 | warn | ★★ | 🔴 | VLM + person |

### 2.2 出入口 / 门禁

| ID | 场景 | Severity | 难度 | 状态 | 技术依赖 |
|----|------|---------|------|------|---------|
| AC-1 | 门禁尾随 | warn | ★★★ | 🟡 | person 计数 + 门 ROI |
| AC-2 | 大门长时间未关 | warn | ★★ | 🔴 | `state_query` |
| AC-3 | 电动车逆行进单元 | info | ★★ | 🔴 | 运动方向 |
| AC-4 | 单元门口徘徊 (>5 分钟) | warn | ★★ | 🔴 | 时间 + `state_query` |

### 2.3 高空 / 环境安全

| ID | 场景 | Severity | 难度 | 状态 | 技术依赖 |
|----|------|---------|------|------|---------|
| **HA-1** | **高空抛物** | critical | ★★★ | 🟡 | VLM 运动方向 + 轨迹 |
| HA-2 | 阳台窗台悬挂重物（快掉） | warn | ★★★ | 🔴 | VLM 描述 |
| HA-3 | 屋顶 / 阳台危险探身 | critical | ★★★ | 🟡 | person + 边界 ROI |
| HA-4 | 井盖打开无人看守 | warn | ★★ | 🔴 | 井盖 ROI |

### 2.4 电梯

| ID | 场景 | Severity | 难度 | 状态 | 技术依赖 |
|----|------|---------|------|------|---------|
| EL-1 | 电梯门反复开合 | warn | ★★ | 🔴 | 门状态计数 |
| EL-2 | 电梯超员 | warn | ★★ | 🟡 | person 计数 |
| EL-3 | 儿童独自乘梯 | warn | ★★ | 🔴 | person 年龄识别 |
| EL-4 | 电梯内打斗 | critical | ★★★ | 🟡 | VLM 描述 |

---

## 3. 停车场 (Parking)

| ID | 场景 | Severity | 难度 | 状态 | 技术依赖 |
|----|------|---------|------|------|---------|
| **PK-1** | 消防通道停车 | critical | ★★ | 🟡 | YOLO(car) + ROI |
| PK-2 | 出入口挡道 | critical | ★★ | 🟡 | YOLO(car) + ROI |
| PK-3 | 双黄线 / 横向停车 | warn | ★★ | 🔴 | YOLO + 车位线 |
| PK-4 | 占用无障碍车位 | warn | ★★ | 🔴 | YOLO + 特殊车位 ROI |
| PK-5 | 静止 > 7 天（僵尸车） | info | ★ | 🔴 | 时间维度 + `state_query` |
| PK-6 | 车辆剐蹭事故 | critical | ★★★ | 🔴 | 突发运动 + VLM |
| PK-7 | 车辆倒退撞人 / 物 | critical | ★★★ | 🔴 | 运动 + person |
| PK-8 | 撬车 / 划车 | critical | ★★★ | 🔴 | VLM 描述 |

---

## 4. 施工场景 (Construction Site)

### 4.1 PPE（个人防护装备）

| ID | 场景 | Severity | 难度 | 状态 | 技术依赖 |
|----|------|---------|------|------|---------|
| **PP-1** | 未戴安全帽 | critical | ★★ | 🟡 | YOLO(helmet) + person |
| PP-2 | 未穿反光衣 | warn | ★★ | 🔴 | 服装颜色检测 |
| PP-3 | 未穿安全鞋 | warn | ★★ | 🔴 | 脚部检测 |
| PP-4 | 高空作业未系安全绳 | critical | ★★★ | 🔴 | VLM + 高度 |

### 4.2 危险行为

| ID | 场景 | Severity | 难度 | 状态 | 技术依赖 |
|----|------|---------|------|------|---------|
| CN-1 | 高空坠落 | critical | ★★★ | 🟡 | VLM 姿态 |
| CN-2 | 吊装作业下方站人 | critical | ★★★ | 🟡 | 机械 ROI + person |
| CN-3 | 挖机 / 塔吊附近距离过近 | critical | ★★★ | 🟡 | YOLO(truck) + distance |
| CN-4 | 工地抽烟 / 明火 | warn | ★★ | 🔴 | VLM |
| CN-5 | 未持证操作机械 | warn | ★★★ | 🔴 | 人脸识别（跨域） |
| CN-6 | 非工作时间进入工地 | warn | ★★ | 🔴 | 时间窗 + person |
| CN-7 | 交叉作业未挂警示牌 | info | ★★★ | 🔴 | ROI + object |

---

## 5. 商业 / 门店 (Retail)

| ID | 场景 | Severity | 难度 | 状态 | 技术依赖 |
|----|------|---------|------|------|---------|
| RT-1 | 顾客滑倒 | critical | ★★★ | 🟡 | VLM 姿态（复用 fall） |
| RT-2 | 打烊后店内有人 | critical | ★★ | 🟡 | 时间窗 + person |
| RT-3 | 排队 > N 人 | info | ★★ | 🔴 | person 计数 |
| RT-4 | 货架空 (>50%) | info | ★★ | 🔴 | 货架 ROI + 密度 |
| RT-5 | 长时间徘徊 | warn | ★★ | 🔴 | 时间 + 移动模式 + `state_query` |
| RT-6 | 打架 / 争执 | critical | ★★★ | 🟡 | VLM |
| RT-7 | 儿童独自 | warn | ★★★ | 🔴 | 年龄识别 |
| RT-8 | 员工未戴口罩（食品店） | info | ★★ | 🔴 | 口罩检测 |
| RT-9 | 收银台异常聚集 | warn | ★★ | 🔴 | ROI + 计数 |

---

## 6. 户外 / 公共 (Outdoor / Public)

| ID | 场景 | Severity | 难度 | 状态 | 技术依赖 |
|----|------|---------|------|------|---------|
| OD-1 | 半夜倾倒建筑垃圾 | warn | ★★★ | 🔴 | 时间 + 车辆 |
| OD-2 | 遛狗未牵绳 | info | ★★ | 🔴 | YOLO(dog) + 无绳 |
| OD-3 | 遛狗未清粪便 | info | ★★★ | 🔴 | 事件识别难 |
| **OD-4** | 儿童独自靠近泳池 / 水域 | critical | ★★★ | 🟡 | VLM + 水域 ROI |
| OD-5 | 老人户外长时间不动 | warn | ★★ | 🔴 | 时间 + 姿态 |
| OD-6 | 大雪 / 大水 / 冰面 | warn | ★★ | 🔴 | VLM 环境 |
| OD-7 | 无烟公园抽烟 | info | ★★ | 🔴 | VLM |
| OD-8 | 健身器材超重 / 未成年使用 | info | ★★★ | 🔴 | VLM |
| OD-9 | 广场舞噪音时段违规 | info | ★★★ | 🔴 | 需声音 |
| OD-10 | 老人 / 儿童走失（同区域徘徊） | critical | ★★★ | 🔴 | 移动模式 + `state_query` |

---

## 7. 特殊状态类 & 反例 (State / Negative)

### 7.1 状态类（不需视频，测试跨 task 状态管理）

| ID | 场景 | Severity | 依赖 |
|----|------|---------|------|
| ST-1 | 冰箱门开 > 3 分钟 | warn | `state_query` + last_open_time |
| ST-2 | 大门未关 > 5 分钟 | warn | `state_query` |
| ST-3 | 老人 > 6 小时未出现 | warn | `state_query` |
| ST-4 | 独居老人 24h 无活动 | critical | VSA long-static event |
| ST-5 | 洗衣机长时间运行未取衣 | info | `state_query` |

### 7.2 反例基线（负例视频，防止误触发）

| ID | 场景 | 期望 | 用于哪个 use case |
|----|------|------|------------------|
| NG-1 | 完全空场景 | Prefilter SKIP | 所有需 person 的 case |
| NG-2 | 光影缓慢变化（云彩、日落） | motion 无触发或 SKIP | 所有 |
| NG-3 | 电视播放画面（画中画） | 应识别为虚拟人 | 儿童 / 老人 |
| NG-4 | 宠物触发（应用于人监护） | Prefilter SKIP | child_safety / elder_wakeup |
| NG-5 | 快递员短暂进入 (<10s) | 不算入侵 | intruder / 徘徊 |
| NG-6 | 老人正常起夜（22-06） | 不算异常 | elder_wakeup 反例 |

---

## 附录 A：第 1 批 10 个 case 完整落地方案

覆盖 3 大部署场景、跨 rules 层的核心表达力（严重级/时间窗/ROI/运动方向/YOLO 目标类）。每个 case 给：即梦 prompt / VLM 期望输出 / rules 配置 / 期望 alert。

### A.1 CS-1 儿童攀爬窗台

**即梦 prompt**：

```
[fixed camera view, 1280×720, 10 seconds, 15 fps, indoor natural lighting]

Scene: home living room, sofa in center, window on right with low windowsill.
Subject: a 5-year-old child in a red T-shirt.
Action: child walks to the window at second 2, starts climbing onto the
windowsill by putting one knee on the sill, then hands on the frame, then sits
on the sill facing outward by second 8. Continuous slow motion, child clearly
visible for full 8 seconds.
Camera: static tripod shot, no movement, no zoom.
Style: realistic surveillance camera footage.
```

**期望 VLM 输出**（child_safety prompt.md 的 LOCAL_PROMPT 决定）：

```
SEVERITY: critical
EVENT: child_climb
DESC: 儿童正在攀爬窗台/靠近窗户
```

**config.yaml.example 相关 use_case_dict 条目**（Phase 10 默认已包含）：

```yaml
use_case_dict:
  child_safety:
    video_summary_task: child_safety_monitor
    evaluate_rules_path: ./use-cases/child_safety/evaluate_rules.py
    rules:
      severityThreshold: warn
      cooldownSeconds: 60
```

**期望 alert**：

```
[child_safety] child_climb: critical — 儿童正在攀爬窗台/靠近窗户
```

---

### A.2 CS-3 儿童安静玩耍（反例）

**即梦 prompt**：

```
[fixed camera, 1280×720, 10 seconds, 15 fps, indoor natural lighting]

Scene: home living room, wooden floor with a colorful play mat in center.
Subject: a 5-year-old child sitting cross-legged on the mat.
Action: child quietly plays with wooden blocks, calm hand movements stacking
blocks. No standing, no running, no dangerous behavior. Full 10 seconds.
Camera: static tripod shot.
Style: realistic surveillance footage.
```

**期望 VLM 输出**：

```
SEVERITY: info
EVENT: child_play
DESC: 儿童安静玩耍
```

**期望 alert**：❌ 不触发（`info < warn` 阈值，短路）

---

### A.3 CS-5 儿童玩火（打火机）

**即梦 prompt**：

```
[fixed camera, 1280×720, 10 seconds, 15 fps, indoor kitchen lighting]

Scene: home kitchen, small table with a red lighter placed on top.
Subject: a 5-year-old child in yellow shirt.
Action: child walks to the table at second 1, picks up the lighter with right
hand at second 3, tries to press the ignition button repeatedly with visible
concentration through second 9. Small yellow flame briefly visible at second 7.
Camera: static tripod shot.
Style: realistic surveillance footage, well lit.
```

**期望 VLM 输出**：

```
SEVERITY: critical
EVENT: child_fire_play
DESC: 儿童正在玩打火机,存在火灾风险
```

**config**（沿用 child_safety 默认）

**期望 alert**：

```
[child_safety] child_fire_play: critical — 儿童正在玩打火机,存在火灾风险
```

---

### A.4 EW-1 老人晚起

**即梦 prompt**：

```
[fixed camera, 1280×720, 10 seconds, 15 fps, morning bedroom natural lighting]

Scene: elderly bedroom, single bed against wall, warm morning light through
window.
Subject: an 80-year-old man in white pajamas, gray hair.
Action: at second 0 the man is lying under blanket. At second 2 he pushes
blanket aside and slowly sits up. At second 5 he swings legs off bed. At
second 8 he stands up beside bed and takes one step forward. Clearly visible
throughout.
Camera: static tripod shot from bedside angle showing full bed.
Style: realistic surveillance footage, warm morning light.
```

**期望 VLM 输出**：

```
EVENT: get_up
WAKEUP_TIME: 20.5
DESC: 老人从床上起身
```

**关键**：测试"晚起"时，通过 `PUT /sources/{id}/pipeline` 热改 rules 制造边界：

```yaml
use_case_dict:
  elder_wakeup:
    video_summary_task: elder_wakeup_monitor
    evaluate_rules_path: ./use-cases/elder_wakeup/evaluate_rules.py
    rules:
      expectedWakeupLocal: "00:00"    # 强制晚起：现在任何时间都算超阈值
      graceMinutes: 0
```

**期望 alert**：

```
[elder_wakeup] late_wakeup: warn — 老人从床上起身 (wakeup_time=20.5)
```

---

### A.5 EW-3 老人躺床（反例）

**即梦 prompt**：

```
[fixed camera, 1280×720, 10 seconds, 15 fps, morning bedroom lighting]

Scene: elderly bedroom, same as EW-1.
Subject: an 80-year-old man lying in bed.
Action: man remains lying under blanket with eyes closed, chest slowly
rising and falling with breathing. Only slight head movement at second 6.
No sitting up, no getting off bed.
Camera: static tripod shot.
Style: realistic surveillance footage.
```

**期望 VLM 输出**：

```
EVENT: still_in_bed
DESC: 老人仍在床上休息
```

**期望 alert**：❌ 不触发（`event != get_up` 短路）

---

### A.6 FS-1 电动车停在楼道

**即梦 prompt**：

```
[fixed camera, 1280×720, 10 seconds, 15 fps, corridor fluorescent lighting]

Scene: residential building corridor (楼道), narrow hallway with apartment
doors on both sides, floor is beige tile.
Subject: a man pushing a red electric scooter (电动车).
Action: man walks with scooter from left side into corridor at second 1,
stops center-frame at second 5, kicks down the kickstand and walks away
leaving scooter parked in the middle of corridor by second 9.
Camera: static tripod shot at end of corridor, wide angle showing full
hallway width.
Style: realistic surveillance footage.
```

**期望 VLM 输出**（社区场景需要新增 use case adapter，参考 A.11 后附框架）：

```
SEVERITY: critical
EVENT: ebike_wrong_park
DESC: 电动车停放在住宅楼楼道内,阻塞消防通道
```

**新增 use_case_dict 条目**（要落地这个 case 需要新建 `use-cases/community_fire_safety/`）：

```yaml
use_case_dict:
  community_fire_safety:
    description: "Community fire safety — ebike misuse detection"
    video_summary_task: community_fire_safety_monitor
    evaluate_rules_path: ./use-cases/community_fire_safety/evaluate_rules.py
    rules:
      severityThreshold: warn
      # 未来可加 corridor_roi = [x0,y0,x1,y1] 表示"什么区域算楼道"
      cooldownSeconds: 300
```

**期望 alert**：

```
[community_fire_safety] ebike_wrong_park: critical — 电动车停放在住宅楼楼道内,阻塞消防通道
```

---

### A.7 FS-6 楼道明火

**即梦 prompt**：

```
[fixed camera, 1280×720, 10 seconds, 15 fps, dim corridor lighting]

Scene: residential corridor, same setting as FS-1 but with a small trash
bag on the floor.
Subject: none visible person; small yellow-orange flame at center of frame.
Action: at second 1, small flame flickers up from the trash bag. Flame
grows steadily through second 8, visible smoke rising by second 6.
Camera: static tripod shot.
Style: realistic surveillance footage, showing genuine fire hazard.
```

**期望 VLM 输出**：

```
SEVERITY: critical
EVENT: open_fire
DESC: 楼道内出现明火,建筑消防隐患
```

**期望 alert**：

```
[community_fire_safety] open_fire: critical — 楼道内出现明火,建筑消防隐患
```

---

### A.8 HA-1 高空抛物 ⭐（重点验证）

**即梦 prompt**（强化 10s 时长要求 + 缓慢下落）：

```
[fixed camera view, 1280×720, MINIMUM 10 seconds duration, 15 fps or higher,
 outdoor daylight]

Scene: exterior of a mid-rise residential apartment building, ground-level
camera looking upward at balconies from below. Building facade fills the
left 2/3 of the frame; open sky fills the top and right.
Subject: a single dark-colored plastic bag or small object.
Action timeline (MUST last 10 seconds total):
  - 0–2s: static scene, empty sky, building facade visible.
  - 2–4s: object appears at the very top of the frame from behind a balcony.
  - 4–8s: object falls SLOWLY straight downward at natural falling speed
          (about half the frame per 2 seconds), fully visible against the
          building/sky background the whole time.
  - 8–10s: object reaches the lower part of the frame or ground level.
Camera: fixed low-angle tripod shot, absolutely no movement, no zoom, no pan.
Style: realistic surveillance camera footage, high contrast for visibility,
       daytime, consistent lighting throughout.
Constraint: the total video must be at least 10 seconds long. Do NOT compress
the action into a shorter clip.
```

**难度提示**：即梦经常把动作压到 4-6 秒完成，导致视频太短。**关键要素**：
- 生成时在 prompt 里明确 `MINIMUM 10 seconds duration` 与"缓慢下落"
- 若得到的视频短于 10s（例如 `building-throwing.mp4` 实测 4s），两种补救：
  1. **用 `ffmpeg -stream_loop -1` 循环推流**（RTSP 端不断重复，VSA 端看到的是 10s+ 的连续流；这是最简单的方法，直接用短视频跑测试）
  2. **用 ffmpeg 慢放 + 拼接**：`ffmpeg -i short.mp4 -filter:v "setpts=2.5*PTS" -an long.mp4` 把 4s 慢放到 10s
- 物体在画面中**连续可见 2-4 秒**（不能一闪而过；VLM 采样帧全错过就判不出）
- 背景与物体有**颜色对比**（天空浅 + 物体深，或反之）
- 摄像机位置**不动**，物体在画面里的运动完全靠下落

**期望 VLM 输出**：

```
SEVERITY: critical
EVENT: high_altitude_throw
DESC: 观测到物体从楼上向下坠落,疑似高空抛物
MOTION_DIRECTION: downward
```

**新 schema 字段**（要落地这个 case 需要 config.yaml.example 加扩展列）：

```yaml
schema:
  video_summary_tasks:
    extensions:
      - { name: "event",             type: "text", required: true }
      - { name: "severity",          type: "text", required: true }
      - { name: "desc",              type: "text", required: true }
      - { name: "confidence",        type: "real", required: false }
      - { name: "motion_direction",  type: "text", required: false }  # ← 新增
```

**新 use_case_dict 条目**：

```yaml
use_case_dict:
  high_altitude_safety:
    description: "High-altitude object throwing detection"
    video_summary_task: high_altitude_monitor
    evaluate_rules_path: ./use-cases/high_altitude_safety/evaluate_rules.py
    rules:
      severityThreshold: warn
      requireDirection: downward   # 只有 direction=downward 才 fire
      cooldownSeconds: 30           # 短窗（连续抛物应该多次告警）
```

**期望 alert**：

```
[high_altitude_safety] high_altitude_throw: critical — 观测到物体从楼上向下坠落,疑似高空抛物
```

**完整验证脚本见 §A.11**。

---

### A.9 PK-1 消防通道停车

**即梦 prompt**：

```
[fixed camera, 1280×720, 10 seconds, 15 fps, outdoor parking lot lighting]

Scene: residential parking lot with visible yellow-painted fire lane (消防通道)
markings on the ground, "禁止停车" sign visible.
Subject: a white sedan (car).
Action: white sedan drives into frame from right at second 1, slows down
across the fire lane at second 4, parks in the middle of the fire lane
with engine off by second 7. Driver stays in car through second 10.
Camera: static tripod shot, elevated angle showing the fire lane markings
clearly.
Style: realistic surveillance footage.
```

**期望 VLM 输出**：

```
SEVERITY: critical
EVENT: fire_lane_parking
DESC: 车辆停放在消防通道内
```

**期望 alert**：

```
[parking_safety] fire_lane_parking: critical — 车辆停放在消防通道内
```

（use_case_dict 里新建 `parking_safety`，rules 骨架与 community_fire_safety 相同）

---

### A.10 PP-1 未戴安全帽

**即梦 prompt**：

```
[fixed camera, 1280×720, 10 seconds, 15 fps, construction site daylight]

Scene: outdoor construction site, visible rebar and concrete on the ground,
partial building structure in background.
Subject: two construction workers in orange vests. Worker A wears a yellow
hard hat. Worker B has NO hard hat, only wearing a baseball cap.
Action: both workers walk through the frame from left to right between
second 1 and second 9. Both faces visible; worker B's hatless head is
clearly seen.
Camera: static tripod shot at eye level.
Style: realistic surveillance footage.
```

**期望 VLM 输出**：

```
SEVERITY: critical
EVENT: no_hard_hat
DESC: 工地内 1 名工人未佩戴安全帽
```

**期望 alert**：

```
[construction_safety] no_hard_hat: critical — 工地内 1 名工人未佩戴安全帽
```

---

### A.11 HA-1 高空抛物完整验证脚本 ⭐

本节假定你**已用即梦生成好 `ha01_falling_object.mp4`**，按顺序执行即可端到端跑通。

#### 步骤 0：准备目录 + 新建 use case adapter

```bash
cd /home/user/jie/smarthome/smart-community
mkdir -p use-cases/high_altitude_safety
mkdir -p demo-videos/cam_ha_test

# 放入你生成的视频
cp ~/Downloads/ha01_falling_object.mp4 \
   demo-videos/cam_ha_test/
```

#### 步骤 1：创建 `evaluate_rules.py`

```bash
cat > use-cases/high_altitude_safety/evaluate_rules.py <<'PY'
"""high_altitude_safety evaluate_rules override.

Fires a `high_altitude_throw` alert when:
  1. VLM event is `high_altitude_throw`, AND
  2. `motion_direction` matches `rules.requireDirection` (default: "downward"),
     AND
  3. severity meets `rules.severityThreshold` (default "warn").

Input: RuleContext JSON on argv[1].
Output: JSON {should_alert, alert_message}.
"""

import json
import sys

SEVERITY_ORDER = {"info": 0, "warn": 1, "critical": 2}


def evaluate(fields: dict, rules: dict) -> dict:
    event = fields.get("event", "")
    if event != "high_altitude_throw":
        return {"fired": False}

    severity = fields.get("severity", "info")
    threshold = rules.get("severityThreshold", "warn")
    if SEVERITY_ORDER.get(severity, 0) < SEVERITY_ORDER.get(threshold, 1):
        return {"fired": False}

    require_dir = rules.get("requireDirection")
    if require_dir:
        observed_dir = fields.get("motion_direction", "").lower()
        if observed_dir != require_dir.lower():
            return {"fired": False}

    return {
        "fired": True,
        "alert_type": event,
        "severity": severity,
        "description": fields.get("desc") or fields.get("description", ""),
    }


def main() -> None:
    ctx = json.loads(sys.argv[1])
    fields = (ctx.get("payload") or {}).get("fields") or {}
    rules = (ctx.get("payload") or {}).get("rules") or {}
    result = evaluate(fields, rules)

    if result["fired"]:
        print(json.dumps({
            "should_alert": True,
            "alert_message": (
                f"[{ctx.get('useCase','')}] {result['alert_type']}: "
                f"{result['severity']} — {result['description']}"
            ),
        }))
    else:
        print(json.dumps({"should_alert": False}))


if __name__ == "__main__":
    main()
PY
```

#### 步骤 2：创建 `prompt.md`

```bash
cat > use-cases/high_altitude_safety/prompt.md <<'MD'
High-altitude object throwing detection.

The camera looks up at a residential building facade to detect objects
falling from balconies / windows. The prompt guides the VLM to identify a
strictly downward motion trajectory, distinguishing genuine falling objects
from birds / kites / natural phenomena.

## LOCAL_PROMPT

请分析视频中是否出现"高空抛物"事件。判断标准:

1. 是否有明显的物体从画面上方向下方运动 (motion direction = downward)
2. 该物体是否为人为投掷的疑似垃圾/物品 (排除鸟类、树叶等自然坠物)
3. 落物速度是否呈现自由落体或抛物线特征

按以下格式输出 (每行一个字段, 缺失项写 unknown):

SEVERITY: critical | warn | info
EVENT: high_altitude_throw | no_incident | uncertain
DESC: 一句话描述观察到的现象
MOTION_DIRECTION: downward | upward | horizontal | none

判定规则:
- 观测到明确的物体自上而下坠落且非自然物 → SEVERITY: critical, EVENT: high_altitude_throw, MOTION_DIRECTION: downward
- 观测到自然坠物 (树叶、鸟粪) → SEVERITY: info, EVENT: no_incident
- 无法判断 → SEVERITY: info, EVENT: uncertain

## GLOBAL_PROMPT

请汇总本时段内所有高空抛物事件, 生成给物业的日报:

1. 发生次数
2. 每次时间和描述
3. 是否有多次来自同一位置的重复抛物 (提示需要重点关注)

保持简洁, 3-5 段散文即可。
MD
```

#### 步骤 3：更新 `config.yaml`

用 python 脚本 patch，避免手改 YAML 出错：

```bash
python3 - <<'PY'
import yaml
p = "config.yaml.example"
with open(p) as f: d = yaml.safe_load(f)

# 加 motion_direction 扩展列
exts = d["schema"]["video_summary_tasks"]["extensions"]
if not any(e.get("name") == "motion_direction" for e in exts):
    exts.append({"name": "motion_direction", "type": "text", "required": False})

# 加 use_case_dict 条目
d.setdefault("use_case_dict", {})["high_altitude_safety"] = {
    "description": "High-altitude object throwing detection",
    "video_summary_task": "high_altitude_monitor",
    "evaluate_rules_path": "./use-cases/high_altitude_safety/evaluate_rules.py",
    "rules": {
        "severityThreshold": "warn",
        "requireDirection": "downward",
        "cooldownSeconds": 30,
    },
    "reports": {
        "data_source": "alerts",
        "default_type": "daily",
        "filter": {},
    },
}
with open(p, "w") as f: yaml.dump(d, f, allow_unicode=True, sort_keys=False)
print("patched config.yaml.example")
PY
```

#### 步骤 4：override 单元层验证（无需 VLM）

```bash
# 正常触发：event + severity + direction 都对
python3 use-cases/high_altitude_safety/evaluate_rules.py '{"monitorId":"cam_ha","useCase":"high_altitude_safety","taskId":1,"summaryText":"","payload":{"fields":{"severity":"critical","event":"high_altitude_throw","desc":"物体从楼上坠落","motion_direction":"downward"},"rules":{"severityThreshold":"warn","requireDirection":"downward"}}}'
# 期望: {"should_alert": true, "alert_message": "[high_altitude_safety] high_altitude_throw: critical — 物体从楼上坠落"}

# 反例 1: 方向不对
python3 use-cases/high_altitude_safety/evaluate_rules.py '{"monitorId":"cam_ha","useCase":"high_altitude_safety","taskId":1,"summaryText":"","payload":{"fields":{"severity":"critical","event":"high_altitude_throw","motion_direction":"horizontal"},"rules":{"severityThreshold":"warn","requireDirection":"downward"}}}'
# 期望: {"should_alert": false}

# 反例 2: severity 太低
python3 use-cases/high_altitude_safety/evaluate_rules.py '{"monitorId":"cam_ha","useCase":"high_altitude_safety","taskId":1,"summaryText":"","payload":{"fields":{"severity":"info","event":"high_altitude_throw","motion_direction":"downward"},"rules":{"severityThreshold":"critical","requireDirection":"downward"}}}'
# 期望: {"should_alert": false}

# 反例 3: event 不匹配
python3 use-cases/high_altitude_safety/evaluate_rules.py '{"monitorId":"cam_ha","useCase":"high_altitude_safety","taskId":1,"summaryText":"","payload":{"fields":{"severity":"critical","event":"no_incident","motion_direction":"downward"},"rules":{"severityThreshold":"warn","requireDirection":"downward"}}}'
# 期望: {"should_alert": false}
```

**这 4 条测试就是 override 层的完整验证**。3 反例 + 1 正例通过，说明规则表达无误。

#### 步骤 5：MCP server 端到端

```bash
# 启动 MCP server（假设 VSA + mediamtx + VLM 都在跑）
export SMARTBUILDING_DATA_DIR=/tmp/mcp-ha-test
rm -rf $SMARTBUILDING_DATA_DIR

cat > /tmp/monitors-ha.yaml <<'EOF'
monitors:
  cam_ha_test:
    enabled: true
    name: "high altitude test cam"
    source_url: "rtsp://localhost:8554/live/ha_test"
    use_case: high_altitude_safety
EOF

# 需要先在 VLM 服务里注册 high_altitude_monitor task
# (curl POST http://localhost:8192/v1/tasks with prompt.md content)

node packages/mcp-server/dist/index.js \
  --config config.yaml.example --monitors /tmp/monitors-ha.yaml --http &

sleep 3

# 推视频
ffmpeg -re -stream_loop -1 \
  -i demo-videos/cam_ha_test/ha01_falling_object.mp4 \
  -c copy -f rtsp rtsp://localhost:8554/live/ha_test &

sleep 60   # 让 clip 触发 + VLM 处理 + rule 判定

# 查 alerts
curl -s -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_alert_query",
    "arguments":{"monitor_id":"cam_ha_test","action":"latest","limit":5}}}' \
  | grep "^data:" | head -1 | sed 's/^data: //' | python3 -m json.tool
```

**期望**：至少 1 条 alert，`description` 以 `[high_altitude_safety] high_altitude_throw: critical —` 开头。

#### 步骤 6：Cooldown + rule_eval 边界

```bash
# 复制 fake task 触发 rule_eval，验证 cooldownSeconds=30 生效
# 短时间内两次 create_alert=true → 第二次应 suppressed
```

（同 [use-case-adapter-gsg.md §6 U8](./use-case-adapter-gsg.md)）

---

## 附录 B：视频生成基线要求

所有测试视频必须满足以下技术参数（否则 VSA motion / prefilter 层前置过滤）：

| 参数 | 值 | 原因 |
|------|-----|------|
| 时长 | 10 s | 对齐 VSA `segment.interval=10.0` |
| 分辨率 | **1280×720** 或 1920×1080 | 匹配 YOLO `shape_static_1280x704` |
| 帧率 | ≥ 15 fps | 匹配 VSA `recording.fps=15` |
| 编码 | H.264 mp4 | ffmpeg `-c copy` 直转 RTSP |
| 视角 | 固定摄像头（无平移 / 变焦） | 模拟真实监控 |
| 光线 | 室内自然光 / 正常照度 | NPU YOLO 暗光召回率下降 |

**内容基线**：
- 需 person 的场景：person 出现 ≥ 2 秒、占画面 ≥ 5%
- 需目标物（打火机 / 电动车 / 车辆）的场景：目标清晰可见 ≥ 5 秒
- 高空抛物 / 运动方向类场景：主体运动方向必须**单向、无遮挡**

**即梦 AI 通用 prompt 骨架**（放在每个具体 prompt 前面）：

```
[fixed camera view, 1280×720, 10 seconds, 15 fps, <环境光描述>]
Scene: <场景描述>
Subject: <主体描述>
Action: <动作描述,持续8秒,位于画面中间偏<方向>>
Camera: static tripod shot, no camera movement, no zoom, no pan.
Style: realistic surveillance camera footage, no cinematic effects.
```
