# 云帆人脸考勤系统

已部署为本机应用，前端是 HTML/CSS/JavaScript，后端在 `ai_data` 中运行。

**访问地址：http://127.0.0.1:5080**

正式模式使用 MySQL 8.0；没有浏览器本地假打卡，也不会自动切换到 SQLite。首个管理员由用户在网页创建，系统不设置默认正式账号密码。

## 从 GitHub 获取并部署

仓库只包含源码、无密码配置模板及测试。员工账号、人脸特征、考勤数据、数据库密码、加密密钥、日志和模型二进制文件均不上传。

下载或克隆源码后，按以下顺序部署（使用已经准备好的 Python 3.11 环境）：

```powershell
python -m pip install -r requirements.txt
python download_models.py
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
# 编辑 .env，填写本机 MySQL 用户名和密码。
python app.py init-db
python app.py serve
```

`Copy-Item` 仅用于首次部署；已有 `.env` 时保留现有配置。默认访问地址为 `http://127.0.0.1:5080/`。启动脚本中的 `ai_data` 解释器路径适用于原电脑，其他电脑可按实际环境调整。

安装 MySQL 8.0 并填写配置后再初始化；正式模式不会自动切换到演示数据库。官方模型由下载脚本获取并校验 SHA-256。

## 当前配置

- 解释器：`D:\anaconda\envs\ai_data\python.exe`
- MySQL：`127.0.0.1:3306`，数据库 `face_attendance`，用户名 `root`
- 密码：从本机 `.env` 读取，不写入前端或日志。
- 服务：waitress，默认仅监听本机 `127.0.0.1:5080`。
- 已创建表：`users`、`face_templates`、`attendance`、`app_settings`、`audit_events`。
- MySQL 驱动：PyMySQL + cryptography，支持 `caching_sha2_password`，不需要修改现有账号认证插件。

## 使用顺序

1. 登录已创建的管理员账号；如果新数据库尚无账号，首页会显示首个管理员设置表单。
2. 打开“员工与人脸”，添加员工，设置姓名、工号、部门、登录账号、初始密码和角色。
3. 点击该员工的“录入人脸”，由员工本人出镜并同意采集。摄像头就绪后采集三张画面。
4. 员工登录自己的账号，在“考勤工作台”开启摄像头，点击“上班打卡”或“下班打卡”。管理员也可以录入自己的人脸并打卡。
5. “考勤记录”支持日期筛选、姓名/工号搜索、分页及 CSV 导出。CSV 为带 BOM 的 UTF-8，兼容 Excel 中文显示。
6. 管理员可在“系统设置”调整班次、上班宽限和匹配阈值。修改账号密码、角色或启停状态后，该员工现有会话会失效，需要重新登录。

| 功能 | 员工 | 管理员 |
| --- | --- | --- |
| 本人人脸上下班打卡 | ✓ | ✓ |
| 查看/导出本人考勤 | ✓ | ✓ |
| 查看/导出全员考勤 | — | ✓ |
| 添加/编辑/停用员工、重置密码 | — | ✓ |
| 人脸录入及重新录入 | — | ✓ |
| 配置班次及识别参数 | — | ✓ |

权限由后端校验，直接调用接口也不能越权；打卡目标固定为登录者，客户端传入的用户 ID、角色和时间不作为依据。

## 启动与初始化

日常使用双击 `启动服务.cmd`；服务已在运行时不要重复启动。关闭服务控制台可结束手动启动的进程。

在 PowerShell 手动启动：

```powershell
Set-Location 'E:\codextest\face-attendance'
& 'D:\anaconda\envs\ai_data\python.exe' app.py serve
```

只有首次部署或准备新数据库时，填写 `.env` 后执行初始化（仅 `CREATE IF NOT EXISTS`，保留已有数据）：

```powershell
& 'D:\anaconda\envs\ai_data\python.exe' app.py init-db
```

也可使用 `初始化数据库.cmd`，或在 MySQL 中执行 `schema.sql`。`.env.example` 是无密码配置模板，不能覆盖已经填写好的 `.env`。

迁移到其他电脑时先安装依赖并下载模型：

```powershell
& 'D:\anaconda\envs\ai_data\python.exe' -m pip install -r requirements.txt
& 'D:\anaconda\envs\ai_data\python.exe' download_models.py
```

如果目标电脑的 conda 路径不同，请修改启动脚本中的解释器路径。修改 `.env` 或后端 Python 后需要重启服务；页面文件更新后刷新浏览器即可。

## 识别与数据

使用 OpenCV 官方 [YuNet + SFace](https://docs.opencv.org/4.12.0/d0/dd4/tutorial_dnn_face.html)，在后端进行人脸检测、对齐和 128 维特征提取。摄像头画面只在内存中处理；MySQL `face_templates.encrypted_features` 保存经 Fernet 加密的特征，默认不保存原始照片。多人、无人脸、画面太小、过暗过亮、模糊、不匹配都会拒绝。

这是**登录账号与该账号人脸的 1:1 核验**，不是无需账号的公共识别闸机。默认匹配阈值 0.50；重新录入会更新该员工的档案，不能录入已关联另一员工的人脸。

第一次启动会在 `data/session.key` 和 `data/face.key` 生成密钥；应连同数据库安全备份。丢失 `face.key` 后旧特征不能解密，需要重新录入。也可在 `.env` 指定 `SECRET_KEY` 和有效的 Fernet `FACE_ENCRYPTION_KEY`。

`.env`、`data/` 和模型文件均在 `.gitignore` 中。分享源码时不要附带 `.env`、数据库或密钥。MySQL 密码仅用于后端连接，不是网页登录密码。

## 打卡规则及范围

- 时间使用服务器的北京时间，浏览器时钟仅作显示。
- 每人每天一次上班、一次下班；下班必须先上班，且时间晚于上班。
- 默认同日班次 09:00–18:00，上班宽限 5 分钟；超过 09:05:00 算迟到，早于 18:00 算早退。
- 上班时保存当日班次快照，之后修改设置不会改变当天已开始班次的判定。
- 在岗分钟是上下班间隔，包含午休；未包含请假、节假日排班、补卡审批和跨夜班次。
- 数据库唯一约束防重复，MySQL 下班更新使用行锁。
- 当前为 RGB 图像核验，**未实现可信活体检测，照片/视频攻击不能可靠防止**。正式考勤需接入活体检测并用实际员工、摄像头、光照样本评估误识率。
- 其他设备或局域网部署需要 HTTPS 才能稳定获得浏览器摄像头权限；本机 `localhost` / `127.0.0.1` 可以直接使用。默认服务并未开放局域网端口。

## 独立演示与验证

`演示模式.cmd` 使用 `5082` 端口和独立 `data/demo.sqlite3`，不读取 MySQL 正式员工数据。演示账号为 `admin` / `employee`，密码均为 `DemoAttend2026!`；仅在明确启动 `--demo` 时存在，正式模式没有演示入口。

```powershell
# 22 项后端规则及权限测试，使用隔离 SQLite 库
& 'D:\anaconda\envs\ai_data\python.exe' -m unittest discover -s tests -v
# 公共样本验证真实模型、加密存储、录入及上下班接口
& 'D:\anaconda\envs\ai_data\python.exe' verify_models.py
# 已安装 Playwright/Edge 的本机浏览器测试；5080 正式服务保持运行
& 'D:\anaconda\envs\ai_data\python.exe' verify_browser.py
```

浏览器测试在 `5081` 启动独立 QA 库，使用公共样本模拟摄像头，不调用真实摄像头，不修改 MySQL 正式数据；检查管理员员工权限、员工增改、真实模型录入及打卡、CSV 下载、桌面和 390px 手机布局。截图及测试记录保存在 `data/browser-qa/`。测试库和样本保留在 `data/`，不会自动清理。

## 文件说明

- `static/index.html`、`style.css`、`app.js`：网页与交互。
- `app.py`：登录、权限、员工、人脸录入、考勤、导出、设置接口和启动入口。
- `db.py`：数据模型；`schema.sql`：可手动执行的 MySQL 建库建表脚本。
- `faces.py`：实际人脸检测、匹配和特征加密。
- `download_models.py`：官方模型下载与 Git LFS SHA-256 校验。
- `tests/test_app.py`：后端验证；`verify_models.py`、`verify_browser.py`：集成验证。
