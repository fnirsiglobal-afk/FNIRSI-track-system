# 17TRACK → 飞书多维表格 包裹状态追踪系统
# 小白完整部署指南

> 预计耗时：40～60 分钟  
> 难度：★★☆☆☆（会复制粘贴就行）  
> 不需要懂编程，不需要安装 Python

---

## 目录

- [第一章：整体流程说明](#第一章)
- [第二章：申请 17TRACK API Key](#第二章)
- [第三章：创建飞书应用](#第三章)
- [第四章：准备飞书多维表格](#第四章)
- [第五章：上传代码到 GitHub](#第五章)
- [第六章：部署到 Railway](#第六章)
- [第七章：配置 17TRACK Webhook](#第七章)
- [第八章：配置飞书自动化（按钮触发）](#第八章)
- [第九章：测试验收](#第九章)
- [附录：字段名不同怎么办 / 常见报错](#附录)

---

<a name="第一章"></a>
## 第一章：整体流程说明

系统有两条数据通路，互为补充：

**通路 A：飞书按钮触发（手动查询）**
```
在飞书表格填入物流单号
        ↓
点击「查询」按钮
        ↓
飞书把单号和行ID发给 Railway 服务
        ↓
Railway 向 17TRACK 注册单号 + 立即拉取最新信息
        ↓
物流状态自动写回飞书这一行
```

**通路 B：17TRACK Webhook 推送（自动更新）**
```
17TRACK 检测到包裹状态变更
        ↓
17TRACK 主动推送数据到 Railway 服务
        ↓
Railway 在飞书找到对应行
        ↓
自动更新物流状态
```

**你需要准备的账号（全部免费注册）：**

| 账号 | 用途 |
|------|------|
| 17TRACK API 账号 | 查询物流数据 |
| 飞书账号 | 存放数据的表格 |
| GitHub 账号 | 存放代码 |
| Railway 账号 | 让程序跑在云端 |

---

<a name="第二章"></a>
## 第二章：申请 17TRACK API Key

### 步骤 2-1：注册 API 账号

1. 访问：https://api.17track.net
2. 点击「注册」，用邮箱注册一个账号
3. 完成邮箱验证

> ⚠️ 注意：17TRACK API 账号与普通追踪账号是分开的，必须在 api.17track.net 注册，不是 17track.net。

### 步骤 2-2：获取 API Key

1. 登录后，点击右上角头像 → 「设置（Settings）」
2. 找到「Security」→「Access Key」部分
3. 复制显示的 Key（格式类似 `0000000...`）
4. **粘贴到记事本**，标注「17TRACK API Key」

### 步骤 2-3：记录 Webhook 签名密钥（可选但推荐）

1. 在同一个设置页面，找到「WebHook」部分
2. 如果有「Secret」或「签名密钥」，复制下来
3. **粘贴到记事本**，标注「17TRACK Webhook Secret」

> 💡 签名密钥用于验证推送来源是否真的来自 17TRACK，提升安全性。如果页面没有显示，可以留空，部署时 `TRACK17_SECRET` 填空即可。

---

<a name="第三章"></a>
## 第三章：创建飞书应用

### 步骤 3-1：打开飞书开放平台

1. 访问：https://open.feishu.cn/app
2. 用飞书账号登录

### 步骤 3-2：创建自建应用

1. 点击「创建企业自建应用」
2. 应用名称：`包裹追踪助手`（随意）
3. 点击「创建」

### 步骤 3-3：复制凭证

1. 左侧点击「凭证与基础信息」
2. 复制「App ID」和「App Secret」（点眼睛图标查看）
3. **粘贴到记事本**，分别标注「飞书 App ID」「飞书 App Secret」

### 步骤 3-4：开通权限

1. 左侧点击「权限管理」
2. 搜索「多维表格」
3. 开通：**查看、评论、编辑和管理多维表格**（`bitable:app`）

### 步骤 3-5：发布应用

1. 左侧点击「版本管理与发布」→「创建版本」
2. 填写版本号，点击「保存」→「申请发布」
3. 企业管理员审批（个人版飞书可跳过此步）

---

<a name="第四章"></a>
## 第四章：准备飞书多维表格

### 步骤 4-1：新建多维表格

1. 飞书 → 云文档 → 新建 → 多维表格
2. 表格名称：`KOL寄样追踪`（随意）

### 步骤 4-2：创建字段

**按下方顺序逐个添加字段（字段名必须一字不差）：**

| # | 字段名 | 字段类型 | 说明 |
|---|--------|----------|------|
| 1 | 物流单号 | 文本 | 手动填入快递单号 |
| 2 | 物流子状态 | 单选 | 程序自动填入（如：已签收、运输中） |
| 3 | 子状态描述 | 文本 | 程序自动填入中文说明 |
| 4 | 最新事件时间 | 日期 | 建议勾选「包含时间」 |
| 5 | 运输商 | 单选 | 程序自动填入运输商名称 |
| 6 | 揽收时间 | 日期 | 建议勾选「包含时间」 |
| 7 | 签收时间 | 日期 | 建议勾选「包含时间」 |
| 8 | 更新时间 | 日期 | 每次同步时自动更新，建议勾选「包含时间」 |
| 9 | 查询按钮 | 按钮 | 按钮文字填「查询物流」 |

> ⚠️ 字段名必须和上表完全一致，包括标点符号，否则程序找不到字段！  
> ⚠️ 「日期」字段创建后，点击字段设置 → 勾选「包含时间」，能显示到小时分钟。

### 步骤 4-3：记录表格 ID

1. 看浏览器地址栏：
   ```
   https://xxxx.feishu.cn/base/Mxxxxxxxxxxxxxxxx?table=tblxxxxxxxx&view=...
   ```
2. `/base/` 后到 `?` 前的字符串 → 标注「BITABLE_APP_TOKEN」
3. `table=` 后到 `&` 前的字符串（`tbl` 开头）→ 标注「BITABLE_TABLE_ID」

### 步骤 4-4：给飞书应用授权

1. 多维表格右上角 → 「分享」
2. 搜索「包裹追踪助手」（你刚建的应用）
3. 添加，权限设为「**可编辑**」
4. 确认

---

<a name="第五章"></a>
## 第五章：上传代码到 GitHub

### 步骤 5-1：注册 GitHub（已有跳过）

访问 https://github.com → Sign up

### 步骤 5-2：新建仓库

1. 点击右上角「+」→「New repository」
2. 仓库名：`track17-feishu`
3. 选「**Public**」
4. 勾选「Add a README file」
5. 点「Create repository」

### 步骤 5-3：上传三个文件

你已经有了以下三个文件，逐一上传：

**上传 `app/main.py`：**
1. 仓库页面 → 点「creating a new file」
2. 文件名填 `app/main.py`（输入 `app/` 后自动创建文件夹）
3. 粘贴 `main.py` 全部内容
4. 点「Commit changes」

**上传 `requirements.txt`（内容如下，新建文件粘贴进去）：**
```
fastapi==0.115.0
uvicorn==0.30.6
httpx==0.27.2
apscheduler==3.10.4
```

**上传 `railway.toml`（内容如下，新建文件粘贴进去）：**
```toml
[build]
builder = "NIXPACKS"

[deploy]
startCommand = "uvicorn app.main:app --host 0.0.0.0 --port $PORT"
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 3
```

**最终仓库结构：**
```
track17-feishu/
├── app/
│   └── main.py
├── requirements.txt
├── railway.toml
└── README.md
```

---

<a name="第六章"></a>
## 第六章：部署到 Railway

### 步骤 6-1：注册并连接 GitHub

1. 访问：https://railway.app
2. 「Login with GitHub」登录
3. 授权 Railway 访问 GitHub

### 步骤 6-2：新建项目

1. Dashboard → 「New Project」
2. 「Deploy from GitHub repo」
3. 选择 `track17-feishu` 仓库
4. 「Deploy Now」
5. 等待 1～2 分钟构建完成

### 步骤 6-3：填写环境变量

1. 点击服务卡片 → 顶部「Variables」
2. 逐个添加以下变量：

| 变量名 | 值 |
|--------|-----|
| `TRACK17_API_KEY` | 17TRACK API Key |
| `TRACK17_SECRET` | 17TRACK Webhook 签名密钥（没有可留空） |
| `FEISHU_APP_ID` | 飞书 App ID |
| `FEISHU_APP_SECRET` | 飞书 App Secret |
| `BITABLE_APP_TOKEN` | 多维表格 Token |
| `BITABLE_TABLE_ID` | 数据表 ID（tbl 开头） |
| `SCHEDULE_CRON` | `0 8 * * *`（每天早8点全表刷新） |
| `SCHEDULE_TZ` | `Asia/Shanghai` |

> 💡 如果你的飞书是企业专属域名版（地址栏类似 `xxx.feishu.cn`），还需要额外添加：  
> `FEISHU_API_BASE` = `https://open.feishu.cn`（标准版保持此值不变）

3. 全部填完后 Railway 自动重新部署

### 步骤 6-4：获取公网域名

1. 「Settings」→「Networking」→「Generate Domain」
2. 生成类似 `https://track17-feishu-production.up.railway.app` 的地址
3. **复制，粘贴到记事本**，标注「Railway 域名」

### 步骤 6-5：验证部署

浏览器访问：`你的Railway域名/health`

显示 `{"status":"ok"}` → ✅ 部署成功

---

<a name="第七章"></a>
## 第七章：配置 17TRACK Webhook

> 这一步让 17TRACK 在包裹状态变更时，自动把数据推送给你的服务。

### 步骤 7-1：进入 17TRACK API 设置

1. 登录 https://api.17track.net
2. 右上角「Settings」→ 找到「WebHook」部分

### 步骤 7-2：填入 Webhook URL

在 WebHook URL 输入框填入：

```
https://你的Railway域名/webhook/17track
```

例如：
```
https://track17-feishu-production.up.railway.app/webhook/17track
```

### 步骤 7-3：选择版本

版本选择「**v2**」或最新版本（与代码中 `v2.4` API 对应）

### 步骤 7-4：保存并测试

1. 点击「Save」保存
2. 点击「Test」发送测试推送
3. 去 Railway 日志（Deployments → View Logs）查看是否收到 `17TRACK 推送: 1 条` 的日志
4. 看到日志说明 Webhook 通路已通

---

<a name="第八章"></a>
## 第八章：配置飞书自动化（按钮触发）

### 步骤 8-1：打开自动化

1. 打开你的多维表格
2. 右上角「自动化」（闪电图标）
3. 「新建自动化」

### 步骤 8-2：触发条件

- 触发条件：**点击按钮**
- 选择按钮字段：**查询按钮**

### 步骤 8-3：执行动作

「添加动作」→「发送 HTTP 请求」，按以下配置：

**请求方式：** POST

**URL：**
```
https://你的Railway域名/webhook/feishu
```

**请求头：**
- Header 名：`Content-Type`
- Header 值：`application/json`

**请求体（选「自定义」，输入以下内容）：**
```json
{
  "record_id": "{{记录ID}}",
  "tracking_no": "{{物流单号}}"
}
```

> 输入 `{{` 后飞书会弹出变量选择器：  
> - `{{记录ID}}` → 选「当前记录」→「记录ID」  
> - `{{物流单号}}` → 选「当前记录」→「物流单号」

### 步骤 8-4：保存启用

点「保存」，确认自动化开关为蓝色（已启用）。

---

<a name="第九章"></a>
## 第九章：测试验收

### 步骤 9-1：填入测试单号

在多维表格第一行「物流单号」字段填入一个真实快递单号，例如：
```
RR123456789CN
```
（用你手边真实的快递单号效果更好）

### 步骤 9-2：点击查询按钮

点击同一行「查询按钮」中的「查询物流」，等待 5～10 秒。

### 步骤 9-3：检查结果

正常情况下应该出现：

| 字段 | 预期内容 |
|------|----------|
| 物流子状态 | 如「已签收」「运输中」「未找到」等 |
| 子状态描述 | 中文说明文字 |
| 最新事件时间 | 日期+时间 |
| 运输商 | 快递公司名称 |
| 更新时间 | 当前时间 |

如果包裹已签收，签收时间也会填入。揽收时间部分运输商可能不提供。

✅ 有数据写入 → **部署完成！**

---

<a name="附录"></a>
## 附录

### 字段名不同怎么办？

如果你的飞书表格字段名和本指南不一样（比如叫「快递单号」而不是「物流单号」），可以在 Railway 环境变量里加字段名映射，**不需要改代码**：

| 变量名 | 对应字段 | 默认值 |
|--------|----------|--------|
| `FIELD_TRACKING_NO` | 物流单号字段名 | `物流单号` |
| `FIELD_SUB_STATUS` | 物流子状态字段名 | `物流子状态` |
| `FIELD_SUB_STATUS_DESC` | 子状态描述字段名 | `子状态描述` |
| `FIELD_LATEST_EVENT_T` | 最新事件时间字段名 | `最新事件时间` |
| `FIELD_CARRIER` | 运输商字段名 | `运输商` |
| `FIELD_PICKUP_TIME` | 揽收时间字段名 | `揽收时间` |
| `FIELD_DELIVERED_TIME` | 签收时间字段名 | `签收时间` |
| `FIELD_UPDATE_TIME` | 更新时间字段名 | `更新时间` |

比如你的字段叫「快递单号」，就在 Railway Variables 里加：  
`FIELD_TRACKING_NO` = `快递单号`

---

### 常见问题

**问：点了按钮，但字段没有更新**

1. 检查 Railway 日志（Deployments → View Logs）有没有报错
2. 检查自动化里请求体 `{{物流单号}}` 是否用了飞书变量（芯片样式），而不是手打文字
3. 访问 `你的域名/admin/debug-records` 确认表格字段名能被正确识别

**问：日志显示「飞书写入失败 HTTP 404」**

- 检查 `BITABLE_APP_TOKEN` 和 `BITABLE_TABLE_ID` 是否和当前表格 URL 一致（如果表格重建过，这两个值会变）
- 确认飞书应用已在表格「分享」里添加为「可编辑」协作者

**问：日志显示「17TRACK 暂无数据」**

- 新注册的单号最快 1 分钟、最慢 5 分钟才有数据，等一会儿再点按钮
- 确认单号格式正确（5～50 位字母数字组合）

**问：运输商显示为空**

- 17TRACK 有时无法自动识别运输商，属正常情况
- 可以在 17TRACK API 后台手动为单号指定运输商，之后推送会带上运输商信息

**问：揽收时间为空**

- 部分运输商不提供揽收时间，属正常情况

**问：如何手动触发全表刷新？**

用 Postman 或浏览器访问：
```
POST https://你的Railway域名/admin/refresh-now
```
或者直接等每天早 8 点定时任务自动执行。

---

## 完成清单

- [ ] 17TRACK API 账号已注册，API Key 已复制
- [ ] 飞书应用已创建，App ID / Secret 已复制，权限已开通
- [ ] 飞书多维表格已创建 9 个字段，应用已添加为「可编辑」协作者
- [ ] GitHub 仓库已上传 `app/main.py`、`requirements.txt`、`railway.toml`
- [ ] Railway 已部署，8 个环境变量已填写，`/health` 返回 ok
- [ ] 17TRACK 后台 Webhook URL 已配置并测试通过
- [ ] 飞书自动化已配置「点击按钮 → POST 到 Railway」
- [ ] 填入真实单号，点击按钮后物流状态自动写入 ✅

---

*遇到问题，把 Railway 的错误日志截图进行排查。*
