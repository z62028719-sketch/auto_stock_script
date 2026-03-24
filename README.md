# 股票监控脚本 - 安装使用说明

## 📁 文件清单

```
stock_monitor/
├── stock_monitor.py          # 主脚本
├── config.json               # 配置文件（股票列表、邮箱等）
├── com.user.stockmonitor.plist  # macOS 定时任务配置
├── logs/                     # 运行日志（自动创建）
└── screenshots/              # 截图文件（自动创建）
```

---

## 🔧 第一步：安装依赖

打开终端（Terminal），执行以下命令：

```bash
# 1. 安装 Homebrew（如果没有）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. 安装 cliclick（模拟鼠标点击）
brew install cliclick

# 3. 安装 Python 依赖
pip3 install Pillow numpy
```

---

## ⚙️ 第二步：配置 config.json

用文本编辑器打开 `config.json`，修改以下字段：

### 📧 Gmail 配置
```json
"email": {
    "sender": "z62028719@gmail.com",
    "recipient": "z62028719@gmail.com",
    "app_password": "etbn hkgx vvsf ploa"
}
```

**如何获取 Gmail App Password：**
1. 登录 Gmail → 账户设置 → 安全性
2. 开启「两步验证」
3. 搜索「应用专用密码」→ 选择「邮件」→ 生成
4. 将生成的 16 位密码填入 `app_password`

### 📈 增删股票
在 `stocks` 数组中增删对象即可：
```json
{
    "name": "股票名称",
    "x": 270,
    "y": 900,
    "enabled": true    ← 改为 false 可临时禁用，不用删除
}
```

### 🖥️ 监控区域微调
如果 x > 3000 区域不对，修改 `monitor_region`：
```json
"monitor_region": {
    "x": 3000,      ← 截图起始x坐标
    "y": 0,         ← 截图起始y坐标
    "width": 1000,  ← 截图宽度
    "height": 1440  ← 截图高度（全屏高度）
}
```

### 🎨 颜色阈值微调
如果红色/绿色信号检测不准，调整 `color_thresholds.pixel_threshold`：
- 值越小 = 越灵敏（容易误报）
- 值越大 = 越严格（可能漏报）
- 建议范围：100 ~ 500

---

## 🚀 第三步：设置定时任务

### 1. 将脚本文件夹放到合适位置
```bash
# 例如放到主目录
cp -r stock_monitor ~/stock_monitor
```

### 2. 修改 plist 文件中的路径
打开 `com.user.stockmonitor.plist`，将两处 `YOUR_USERNAME` 替换为你的 Mac 用户名：
```bash
# 查看你的用户名
whoami
```

### 3. 安装定时任务
```bash
# 复制 plist 到 LaunchAgents 目录
cp ~/stock_monitor/com.user.stockmonitor.plist ~/Library/LaunchAgents/

# 加载定时任务
launchctl load ~/Library/LaunchAgents/com.user.stockmonitor.plist

# 验证是否已加载
launchctl list | grep stockmonitor
```

### 4. 授权辅助功能（重要！）
macOS 需要授权才能控制鼠标：
1. 系统设置 → 隐私与安全性 → 辅助功能
2. 点击「+」添加「终端（Terminal）」并勾选
3. 同样添加「Python」或你使用的 Python 路径

---

## 🧪 第四步：测试运行

```bash
# 手动运行测试（确保目标软件已打开）
cd ~/stock_monitor
python3 stock_monitor.py
```

运行后检查：
- `logs/` 目录下是否有日志
- `screenshots/` 目录下是否有截图
- 收件邮箱是否收到邮件

---

## 📋 常用管理命令

```bash
# 停止定时任务
launchctl unload ~/Library/LaunchAgents/com.user.stockmonitor.plist

# 重新加载（修改配置后）
launchctl unload ~/Library/LaunchAgents/com.user.stockmonitor.plist
launchctl load ~/Library/LaunchAgents/com.user.stockmonitor.plist

# 查看最新日志
tail -f ~/stock_monitor/logs/monitor_$(date +%Y%m%d).log

# 手动立即触发一次
launchctl start com.user.stockmonitor
```

---

## ❗ 常见问题

**Q: OCR 检测不到中文"抄底"/"卖出"？**  
A: 确保 macOS 系统语言包含中文。也可以在 `config.json` 的 `pixel_threshold` 调低，更依赖颜色检测。

**Q: 鼠标点击没反应？**  
A: 检查「辅助功能」授权是否已给终端/Python 开启。

**Q: 邮件发送失败？**  
A: 确认使用的是 App Password（非 Gmail 登录密码），且两步验证已开启。

**Q: 截图区域偏了？**  
A: 调整 `monitor_region` 的 x/y/width/height，可先用 macOS 截图工具确认坐标。
