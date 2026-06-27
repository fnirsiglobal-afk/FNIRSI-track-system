# FNIRSI-track-system
# KOL 包裹追踪系统 — 小白部署全流程

> 总时长约 45 分钟，无需服务器基础，按步骤操作即可完成

---

## 系统架构

```
飞书多维表格（填入快递单号）
       ↓  register.py 脚本
  17TRACK API 注册追踪
       ↓  状态变更时
  17TRACK Webhook 推送
       ↓
  Railway 服务（本项目）
       ↓  解析状态 + 写入
  飞书多维表格（自动更新状态）
       ↑  每6小时兜底
  Polling 定时任务
```

---

## 第一步：准备账号（5 分钟）

注册以下三个平台账号（已有则跳过）：

| 平台 | 地址 | 用途 |
|------|------|------|
| GitHub | https://github.com | 托管代码 |
| Railway | https://railway.app | 运行服务 |
| 17TRACK API | https://api.17track.net | 物流追踪 |

---

## 第二步：飞书多维表格建表（10 分钟）

### 2.1 新建数据表

在飞书中打开目标多维表格，新建一个数据表，命名为**「物流跟踪表」**。

### 2.2 按以下清单创建字段

> ⚠️ 字段名必须与下表完全一致（包括空格），代码按字段名写入

| 字段名 | 飞书字段类型 | 说明 |
|--------|------------|------|
| 物流单号 | 文本 | 快递单号，录入起点 |
| 物流子状态 | 单选 | 17TRACK sub_status（自动写入） |
| 子状态描述 | 文本 | 最新事件描述（自动写入） |
| 最新事件时间 | 日期 | 最新事件发生时间（自动写入） |
| 运输商 | 单选 | 物流商名称（自动写入） |
| 揽收时间 | 日期 | 包裹被揽收时间（自动写入） |
| 签收时间 | 日期 | KOL 签收时间（自动写入） |
| 最后推送时间 | 日期 | 最近一次 Webhook 时间（自动写入） |

**「物流子状态」单选选项**（提前创建，避免写入失败）：

```
NotFound · 未找到
InfoReceived · 已揽件
InTransit · 运输中
InTransit_PickedUp
InTransit_CustomsProcessing
InTransit_CustomsReleased
InTransit_CustomsRequiringInformation
InTransit_Arrival
InTransit_Departure
Expired · 超时未达
AvailableForPickup · 待取件
OutForDelivery · 派送中
DeliveryFailure · 投递失败
DeliveryFailure_NoBody
DeliveryFailure_InvalidAddress
DeliveryFailure_Rejected
Delivered · 已签收
Delivered_Other
Exception · 异常
Exception_Returning
Exception_Lost
Exception_Damage
Stopped · 已停止跟踪
```

### 2.3 获取 app_token 和 table_id

**app_token**：打开多维表格，看浏览器地址栏：
```
https://xxx.feishu.cn/base/NdT5bHxxx...xxxQ?table=tblXXX
                              ↑ 这一段就是 app_token
```

**table_id**：同一 URL 中 `table=` 后面的部分：
```
https://xxx.feishu.cn/base/NdT5bH...?table=tblXXXXXXXXXXXX
                                              ↑ 这是 table_id
```

---

## 第三步：创建飞书自建应用（8 分钟）

### 3.1 创建应用

1. 打开 https://open.feishu.cn/app
2. 点击「创建企业自建应用」
3. 填写名称：`KOL物流追踪` / 描述随意
4. 记下 **App ID** 和 **App Secret**（在「凭证与基础信息」页面）

### 3.2 开通 API 权限

进入应用 →「权限管理」→ 搜索并开通以下权限：

```
bitable:app          （多维表格数据读写）
bitable:app:readonly （多维表格数据读取，选读写则此项可不加）
```

### 3.3 启用机器人能力

进入应用 →「添加应用能力」→ 开启**机器人**

### 3.4 发布应用

进入「版本管理与发布」→ 点击「创建版本」→ 申请发布  
（企业管理员审批后生效，若你是管理员则直接通过）

### 3.5 把应用加入多维表格

回到飞书，打开「物流跟踪表」：
1. 点击右上角 `···` → 更多 → 添加文档应用
2. 搜索 `KOL物流追踪`，添加

---

## 第四步：上传代码到 GitHub（5 分钟）

### 4.1 创建仓库

1. 登录 GitHub，点击右上角 `+` → New repository
2. 仓库名：`kol-tracker`，选 **Private**（私有）
3. 点击 Create repository

### 4.2 上传文件

在仓库页面，点击「uploading an existing file」，把以下文件/文件夹全部拖进去：

```
kol-tracker/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── feishu.py
│   ├── tracker.py
│   └── polling.py
├── scripts/
│   └── register.py
├── requirements.txt
├── Procfile
├── runtime.txt
└── .gitignore
```

> ⚠️ **不要**上传 `.env` 文件（密钥文件），只上传 `.env.example`

提交信息填 `Initial commit`，点击 Commit changes。

---

## 第五步：Railway 部署（8 分钟）

### 5.1 连接 GitHub

1. 登录 https://railway.app
2. 点击 New Project → Deploy from GitHub repo
3. 授权 Railway 访问你的 GitHub
4. 选择 `kol-tracker` 仓库
5. 点击 Deploy Now

Railway 会自动检测 `Procfile` 并开始部署（约 2 分钟）。

### 5.2 配置环境变量

部署完成后，点击项目 → Variables → 添加以下变量：

| 变量名 | 值 | 说明 |
|--------|----|------|
| `TRACK17_KEY` | 你的 17TRACK API Key | 从 17TRACK 后台获取 |
| `FEISHU_APP_ID` | `cli_xxxxxxxxxx` | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | `xxxxxxxxxxxxxxxx` | 飞书应用 App Secret |
| `FEISHU_APP_TOKEN` | `NdT5bHxxx...` | 多维表格 app_token |
| `FEISHU_TABLE_ID` | `tblXXXXXXXX` | 数据表 table_id |
| `WEBHOOK_SECRET` | （留空即可） | 可选签名验证 |

填完后 Railway 自动重新部署。

### 5.3 获取服务域名

部署成功后，在 Railway 项目页面找到：
```
Settings → Domains → Generate Domain
```
生成一个类似 `kol-tracker-production.up.railway.app` 的域名。

### 5.4 验证服务是否正常

在浏览器访问：
```
https://你的域名.railway.app/
```
返回以下内容表示正常：
```json
{"status": "ok", "service": "KOL Tracker"}
```

---

## 第六步：配置 17TRACK Webhook（5 分钟）

1. 登录 https://api.17track.net/admin/settings
2. 找到 **WebHook** 配置区域
3. 填入你的 Webhook 地址：
   ```
   https://你的域名.railway.app/webhook/17track
   ```
4. 点击测试（Test），收到 `{"code": 0}` 表示成功
5. 点击保存

---

## 第七步：使用流程（日常操作）

### 在飞书填入快递单号

在「物流跟踪表」中新增一行，**只需填写「物流单号」字段**，其他字段留空等待自动写入。

### 注册到 17TRACK（一次性操作）

每次新增单号后，需要运行注册脚本：

**本地运行方式**（需要安装 Python）：

```bash
# 第一次：安装依赖
pip install httpx python-dotenv

# 复制环境变量文件并填写
cp .env.example .env
# 编辑 .env，填入你的密钥

# 注册单号
python scripts/register.py SF1234567890 recXXXXXXXXXX kol@gmail.com
#                           ↑快递单号     ↑飞书record_id ↑KOL邮箱(可选)
```

**获取飞书 record_id 的方法**：  
在飞书多维表格中，点击行最左侧的展开图标，URL 末尾的 `rec` 开头的字符串就是 record_id：
```
https://xxx.feishu.cn/base/xxx?record=recXXXXXXXX
                                        ↑ 这就是 record_id
```

### 自动更新

注册完成后，17TRACK 开始追踪，状态变更时自动推送到你的服务，服务自动写入飞书。

**更新频率**：17TRACK 每 6–12 小时自动追踪一次，状态变更时立即推送 Webhook。

---

## 常见问题排查

### 飞书字段没有更新

1. 检查 Railway 服务是否正在运行（项目页面 → Deployments）
2. 检查环境变量是否都填写正确
3. 在 Railway 查看日志：项目 → Deployments → 点击最新部署 → View Logs
4. 手动触发轮询验证：`POST https://你的域名.railway.app/admin/poll-now`

### 17TRACK Webhook 测试失败

1. 确认 Railway 服务已正常启动（访问 `/` 返回 ok）
2. 确认域名完整且带 `https://`
3. 确认 Webhook 路径是 `/webhook/17track`（不是 `/webhook`）

### 飞书写入权限错误

1. 确认应用已开通 `bitable:app` 权限
2. 确认应用已通过「添加文档应用」加入多维表格
3. 确认应用已发布（未发布的应用 API 不生效）

### 物流商无法识别（-18019903 错误）

手动指定 carrier 代码，在注册脚本中加第 4 个参数：
```bash
# 查询物流商代码列表
# https://res.17track.net/asset/carrier/info/apicarrier.all.json
# 顺丰=3011, DHL=100003, FedEx=100002, UPS=100001

python scripts/register.py SF1234567890 recXXXX kol@gmail.com 3011
```

---

## 更新代码

修改代码后，只需 push 到 GitHub，Railway 自动重新部署：
```bash
git add .
git commit -m "Update tracker logic"
git push origin main
```

Railway 检测到 push 后约 1 分钟完成部署。

---

## 环境变量汇总

```
TRACK17_KEY          17TRACK API Key
FEISHU_APP_ID        飞书应用 App ID
FEISHU_APP_SECRET    飞书应用 App Secret
FEISHU_APP_TOKEN     多维表格 app_token
FEISHU_TABLE_ID      数据表 table_id
WEBHOOK_SECRET       Webhook 签名密钥（可留空）
```
