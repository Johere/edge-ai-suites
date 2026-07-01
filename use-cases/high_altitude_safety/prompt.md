High-altitude object throwing detection.

The camera looks up at a residential building facade to detect objects
falling from balconies or windows. The prompt guides the VLM to identify a
strictly downward motion trajectory, distinguishing genuine falling objects
from birds, kites, leaves, or other natural phenomena.

## LOCAL_PROMPT

请分析视频中是否出现"高空抛物"事件。判断标准:

1. 是否有明显的物体从画面上方向下方运动 (motion direction = downward)。
2. 该物体是否为人为投掷的疑似垃圾/物品 (排除鸟类、树叶、气球等自然物)。
3. 落物速度是否呈现自由落体或抛物线特征。

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
