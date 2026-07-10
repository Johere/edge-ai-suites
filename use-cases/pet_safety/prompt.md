## LOCAL_PROMPT
# 一句话任务目标
分析10秒家庭监控视频，识别宠物是否处于危险状态（如被卡住、试图逃离）或正常活动，并输出结构化事件记录。

# 输入说明
输入为10秒RTSP摄像头片段，需观察宠物在室内环境中的行为，包括是否被卡在狭窄缝隙、是否试图从门窗/阳台/栏杆逃离、是否异常挣扎，或处于休息玩耍等正常状态。

# 输出字段
- SEVERITY: critical, warn, info
- EVENT: pet_stuck, pet_escape, pet_normal, no_incident
- DESC: 一句话中文描述事件详情
- pet_zone: 可选文本，描述宠物所在的具体区域（如客厅、阳台、厨房）

# 输出示例 1（positive case）
    SEVERITY: critical
    EVENT: pet_stuck
    DESC: 宠物头部卡在沙发缝隙中无法移动，正在剧烈挣扎
    pet_zone: 客厅沙发区

# 输出示例 2（negative case）
    SEVERITY: info
    EVENT: pet_normal
    DESC: 宠物在地板上安静休息，未检测到异常行为
    pet_zone: 卧室

# 业务边界规则
- pet_stuck 场景包括：宠物头颈卡在家具缝隙、被绳索缠绕、被困在狭窄管道或箱子内、身体部分卡住导致无法移动。
- pet_escape 场景包括：宠物用爪子扒门缝、试图钻过未关严的窗户、攀爬阳台栏杆、在门口疯狂抓挠试图外出。
- pet_normal 场景包括：宠物在室内自由走动、进食、喝水、玩耍玩具、躺卧休息、打哈欠。
- no_incident 场景包括：画面中完全无宠物、宠物处于画面外、或仅检测到宠物但无任何异常行为。
- 危险物识别需具体：如宠物被卡在沙发缝隙、被塑料袋缠绕、被绳子勒住、被困在纸箱内。

# 禁止事项
不要输出JSON格式，不要使用markdown代码块（三反引号），不要照抄示例中的文字，只输出SEVERITY、EVENT、DESC及可选的扩展字段共三行或四行纯文本。
