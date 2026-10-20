# iPhone-use 0.4.0 验收记录

本报告记录独立浏览器手机面板计划的验收结果。每一项都按“场景描述 → 操作步骤 → 预期结果 → 实际结果 → 验证方式与证据”记录，并明确区分自动化、真机对照和宿主环境验证。

结果只使用以下状态：

- **通过**：当前证据覆盖了该项要求的验证范围。
- **失败**：实际结果与预期不符。
- **阻塞**：需要外部条件，但当前条件无法继续验证。
- **未验证**：已有部分证据或自动覆盖，但尚未完成该项要求的完整验证范围。

## 证据索引

- 自动化总检查：`sh scripts/check.sh`，509 个 Python 测试通过（含架构复核及启动入口可移植性回归）。
- 浏览器 HTTP 与生命周期测试：`tests/test_browser.py`，23 个测试通过。
- 启动器测试：`tests/test_launcher.py`，9 项测试通过，覆盖设备选择、重复启动、READY 闸门、桌面入口及路径可移植性。
- 屏幕流与 EXIF 测试：20 个测试通过，覆盖横屏 JPEG orientation 和无效帧处理。
- UI 对照测试：原有 57 项全部保留，增加一项真实 HTTP 适配器与共享 UI 的集成测试；MCP 分支 58/58、Browser 分支 58/58、Browser transport 5/5。
- 打包与安装：`python3 scripts/package.py --validate-only`、`python3 scripts/package.py`、`sh scripts/install.sh` 均完成；安装版本为 0.4.0。
- 真机/浏览器截图：[`outputs/browser-0.4.0`](./outputs/browser-0.4.0)（本地验收输出目录）。
- 30 分钟持续运行记录：[`soak-30min.jsonl`](./outputs/browser-0.4.0/soak-30min.jsonl)。
- 浏览器地址和访问令牌属于本机运行状态，不随仓库和安装包分发。使用时以 READY、启动器或 `pua_screen(open)` 返回的 `browser_url` 为准。

## 架构与原有功能复核（2026-10-20）

复核以新增网页之前的提交 `a766d70` 为基线，直接比较源码、Python AST、工具协议和构建输出，并运行原有功能及宿主适配回归。

| 层次 | 复核结果 |
| --- | --- |
| UI 页面、样式与构建 | `ui/index.html`、`ui/style.css`、`ui/build.mjs` 与基线完全一致；`ui/src/app.ts` 只增加通信适配器选择和版本更新，后面的渲染、坐标、手势、滚轮、工具栏及生命周期逻辑原文一致。 |
| 通信适配 | 原生继续使用 MCP SDK；网页用 `BrowserApp` 将相同的两个 App-only 工具请求发送给本机 HTTP 服务。二者通过 `PanelApp` 的 TypeScript 类型契约检查，没有使用强制转换冒充完整 SDK。 |
| 控制与屏幕状态 | HTTP 服务调用原有 `Runtime.call()`。`_dispatch`、`screen_gesture`、`screen_action`、`_call`、会话保存、暂停和操作锁逻辑与基线一致。多个网页共享一个 worker 内的 Runtime/ScreenHub；原生 MCP 仍保持原有进程，通过既有文件锁、会话文件及屏幕状态总线协调。 |
| 原有模块 | `wda_controller.py`、`wda_client.py`、`wda_setup.py`、App 目录、输入、截图和埋点模块未改；WorkBuddy/豆包执行及页面适配代码未改。 |
| 工具协议 | 20 个工具的名称、输入 schema 和 annotations 与基线一致，仍为 18 个模型工具和 2 个 App-only 工具；MCP 协议版本列表一致。启动、READY、打开屏幕增加 `browser_url`，网页失败单独返回 `browser_error`。 |

复核发现并修正的兼容性边界：

1. 环境发现曾在每次构造 Runtime 时改写 PATH，并把 Homebrew 放到宿主选定的工具前面。现已移到进程入口，只补充缺失路径，保留宿主 PATH 顺序；桌面启动器不再重复扫描 nvm。
2. 浏览器 worker 曾没有继承 Agent 的显式 WDA URL，且设备切换后可能复用旧 worker。现传递同一个本机 WDA endpoint，并用设备、endpoint 和屏幕端口绑定判断能否复用。
3. 浏览器 health 握手曾缺少超时。现与原生连接一样有界超时，由共享 UI 的恢复逻辑继续处理，不重放手机操作。
4. 网页启动异常曾只隔离部分异常类型。现所有普通网页启动异常都保留原有工具的成功结果，避免把健康的 READY 误报为手机通道失败。
5. 横屏 EXIF 修复曾额外遍历 SOF 后的 JPEG 段。现恢复原有 SOF 早返回边界，仅在此前读取方向信息，避免正常旧帧依赖无关尾段解析。

共享层还保留了实施时确认的两项修复：横屏 JPEG 的显示尺寸按 EXIF 方向计算；READY 遇到明确的 `invalid session id` 时只重建会话并重读一次。后者沿用既有只读恢复分支，不重启 WDA、不重建签名、不重放点击或输入。两项都单独覆盖回归，未改写手机业务操作实现。

原有点击、输入、App 查询、诊断、屏幕轮询、工具栏以及 pause/resume 不会触发网页服务启动；只有已约定的启动、READY 成功和屏幕打开入口会启动或复用网页服务。相关回归包括显式 WDA URL 的隔离 HTTP 实测、宿主工具优先级、网页关闭开关、网页故障隔离、真实 BrowserApp 与共享 UI 集成、原有 57 项 UI 用例，以及 WorkBuddy 36 项和豆包 15 项测试。

本次复核未发现仍未修复的原有功能回归；该结论的证据范围是源码对比、隔离运行与自动化回归。下文标为“未验证”的真机/宿主现场场景保持原状态，本节不将其升级为通过。

## 补充简短实测（2026-10-20）

- 启动检查发现 WDA 已停止，复用现有构建启动一次，READY 成功；原生面板和网页均显示 `iPhone 14 / Live`。
- 在侧栏网页中点击计算器，输入 `12×34` 并执行等号一次；真机观察树及 Chrome 网页截图均确认结果为 `408`。证据：`outputs/browser-0.4.0/smoke-browser-408.png`。
- Chrome 网页点击“刷新连接”后恢复 `Live`；点击“回到主屏幕”后，真机观察确认前台为 `com.apple.springboard`。
- 桌面保留唯一正式入口 `启动iPhone屏幕.command`，将 8 个已确认归属本项目的旧备份移入废纸篓；修正相同内容重复安装仍产生备份的问题，启动器 7 项测试通过。
- 本轮是核心路径的补充实测，不改变下文尚未完成完整范围的验收项状态。

## Claude 侧栏现场复核（2026-10-20）

- 在 Claude 的《iPhone Use 安装配置》会话中，浏览器打开工具已返回导航成功且能截取网页，但宿主浏览器侧栏处于收起状态，说明后台页面成功不等于用户可见。
- 通过 Claude 自身的“浏览器”按钮展开已有页面后，侧栏显示 `iPhone 14 / Live` 和计算器 `408`；未重新启动手机服务。证据：`outputs/browser-0.4.0/claude-sidebar-visible.png`。
- 两个技能及 MCP 指引已改为每次新手机任务主动展示，复用已有入口、缺少时打开，并检查侧栏可见性；Claude 本机的两个技能与相关参考文档已同步。
- 本轮没有向 Claude 会话发送新任务；上述现场证据证明当前网页可见，新规则驱动的自动展示仍需在加载新技能的 Claude 会话中核对。

后续检查《兴趣岛APP选课tab标题》会话：READY 的聊天内小组件持续显示“连接中”，会话记录只有手机链接，浏览器侧栏处于收起状态。展开已有浏览器后，网页显示 `iPhone 14 / Live`，证明原生小组件不能作为展示已完成的证据。已将“原生显示未验证或异常时主动尝试浏览器”的回退规则应用于两个技能和 MCP 指引，适用于所有宿主。证据：`claude-course-inline-connecting.png`、`claude-course-sidebar-visible.png`；本轮展开由 Codex 操作，尚未向 Claude 发送新任务验证其自主执行。

## A. 启动与重复启动

### A01【对照】冷启动 — 通过

- **场景描述**：WDA 停止时从桌面入口启动。
- **操作步骤**：运行 `启动iPhone屏幕.command`/`scripts/launch_screen.py`，等待服务启动并执行 READY。
- **预期结果**：WDA READY 后网页服务启动，打开页面并显示实时画面。
- **实际结果**：已在真实 iPhone 14 上完成；启动器先确认 READY，再输出实际 `browser_url` 并打开网页。
- **验证方式与证据**：真机操作、`browser-aligned.png`、`tests/test_launcher.py::test_startup_verifies_ready_before_opening_and_always_prints_actual_url`。

### A02【对照】复用连接 — 通过

- **场景描述**：WDA 和网页服务已经就绪时再次启动。
- **操作步骤**：重复运行桌面入口和 setup/status。
- **预期结果**：复用已有 WDA、服务、签名和构建，不重新创建控制通道。
- **实际结果**：READY 服务被复用，网页服务返回同一个进程和地址。
- **验证方式与证据**：真机重复启动、`tests/test_browser.py::test_repeated_starts_stop_and_restart_use_one_owned_worker_and_new_token`、`tests/test_launcher.py::test_healthy_service_and_existing_start_or_recovery_are_reused`。

### A03【自动】重复启动 — 通过

- **场景描述**：同时或连续触发多次网页服务启动。
- **操作步骤**：并发调用 `BrowserManager.start()`，随后再次调用 start。
- **预期结果**：只保留一个项目拥有的后台服务，不重复启动 WDA。
- **实际结果**：并发调用得到同一 PID 和同一 URL，只有一次创建标记。
- **验证方式与证据**：`tests/test_browser.py::test_concurrent_agent_starts_share_one_worker`、重复启动生命周期测试。

### A04【自动】设备选择 — 通过

- **场景描述**：单设备、多设备、网络设备、离线设备和取消选择。
- **操作步骤**：向启动器提供模拟设备列表，分别测试自动选择、编号选择、非法输入和取消。
- **预期结果**：只选择可用 USB 设备；单设备自动选择，多设备可编号选择，取消时不启动。
- **实际结果**：所有分支符合预期；两台 USB 设备的实际启动也显示选择列表并能选择第 1 台。
- **验证方式与证据**：`tests/test_launcher.py` 设备选择测试、真机双设备启动记录。

### A05【对照】设备不可用 — 未验证

- **场景描述**：USB 未连接、设备不可用或手机锁定时启动。
- **操作步骤**：自动测试注入空设备/不可用设备和 READY 非 ready 状态；真实启动时未拔掉唯一设备做完整现场复现。
- **预期结果**：给出准确原因，不报告 READY 或网页已就绪。
- **实际结果**：自动故障分支符合预期；“无 USB 设备”的真实桌面现场仍未完成。
- **验证方式与证据**：`tests/test_launcher.py::test_not_ready_never_opens_a_browser`、启动器错误处理代码；缺少真实无设备截图。

### A06【自动】已有启动任务 — 通过

- **场景描述**：WDA 启动或恢复任务进行中再次调用启动。
- **操作步骤**：注入 active start/recover job，再调用启动器。
- **预期结果**：等待原任务，不创建重复任务。
- **实际结果**：启动器等待原 job，未调用新的 WDA start/build。
- **验证方式与证据**：`tests/test_launcher.py::test_healthy_service_and_existing_start_or_recovery_are_reused`。

### A07【自动】端口占用 — 通过

- **场景描述**：默认 18101 被本项目或其他程序占用。
- **操作步骤**：占用候选端口后启动 `BrowserManager`，再次测试已有项目元数据。
- **预期结果**：本项目服务可复用；其他监听者不被停止，服务选择空闲端口并返回真实 URL。
- **实际结果**：冲突端口被保留，服务选择另一个回环端口；重复启动复用同一项目 worker。
- **验证方式与证据**：`tests/test_browser.py::test_other_listener_is_preserved_and_browser_chooses_a_free_port`、重复生命周期测试。

### A08【自动】浏览器打开失败 — 通过

- **场景描述**：系统拒绝自动打开浏览器。
- **操作步骤**：模拟 `webbrowser.open()` 返回 false。
- **预期结果**：服务仍保持运行，输出可手动访问的真实链接，并明确未打开浏览器。
- **实际结果**：`running=true`、`browser_opened=false`，`browser_url` 保留。
- **验证方式与证据**：`tests/test_browser.py::test_browser_open_failure_keeps_service_and_clickable_link`。

## B. 外观、布局与画面

### B01【对照】外观一致 — 通过

- **场景描述**：原生 MCP 面板和浏览器页面同时显示同一台 iPhone。
- **操作步骤**：并排打开两个面板，比较外壳、圆角、状态栏、工具栏、图标和光效。
- **预期结果**：两个面板视觉结构与机型外观一致。
- **实际结果**：两端均显示 iPhone 14、Live、相同画面和工具栏；截图及几何测量一致。
- **验证方式与证据**：`native-aligned.png`、`browser-aligned.png`、MCP/Browser 各 57 项 UI 测试。

### B02【自动】机型差异 — 通过

- **场景描述**：灵动岛、刘海屏、SE、旧机型和未知机型数据。
- **操作步骤**：向共享布局逻辑注入不同 model/display 数据。
- **预期结果**：外观选择、屏幕比例和未知机型回退与原面板一致。
- **实际结果**：共享渲染逻辑通过全部机型数据测试。
- **验证方式与证据**：UI widget 测试和 `tests/test_screen.py` 几何测试。

### B03【对照】尺寸适配 — 通过

- **场景描述**：窄窗口、宽窗口和浏览器缩放。
- **操作步骤**：将浏览器页面调整到约 220×380 和 1024×768，再检查滚动/工具栏。
- **预期结果**：设备完整显示、比例保持正确，工具栏仍可用。
- **实际结果**：窄、宽窗口均完整显示，工具栏可用，未发生横向溢出。
- **验证方式与证据**：`browser-narrow.png`、`browser-wide-dark.png`、UI aspect-ratio 测试。

### B04【对照】横竖屏切换 — 未验证

- **场景描述**：旋转真机后比较原生和浏览器两个面板。
- **操作步骤**：已在网页端验证横屏 JPEG EXIF、外壳比例和点击；新版原生 tab 的横屏同步对照尚未重新绑定截图。
- **预期结果**：画面、外壳、坐标在两端同步更新。
- **实际结果**：浏览器端横屏修复有效，横屏点击计算器“8”实际生效；原生新版面板的同轮横屏截图对照缺失。
- **验证方式与证据**：`browser-landscape-fixed.png`、横屏点击真机结果、`tests/test_screen.py` EXIF 测试；原生对照待补。

### B05【对照】主题与反馈 — 通过

- **场景描述**：明暗主题、点击提示和手势动画。
- **操作步骤**：切换深色主题，执行点击/拖动并观察光效、cursor 和状态反馈。
- **预期结果**：样式和反馈与原生面板一致，浏览器默认跟随系统主题。
- **实际结果**：深色宽窗和点击/拖动反馈已验证，浏览器与共享 UI 测试一致。
- **验证方式与证据**：`browser-wide-dark.png`、`browser-tap-7.png`、`browser-drag-up.png`、UI feedback tests。

### B06【自动】异常图像 — 通过

- **场景描述**：首帧损坏、后续帧解码失败、重复帧和旧帧。
- **操作步骤**：向屏幕流注入损坏 JPEG、错误 orientation 和无效序号。
- **预期结果**：提示错误或保留上一有效画面，不允许在无效画面上操作。
- **实际结果**：解码失败和异常帧按既有状态处理，上一有效画面不会被无效帧覆盖。
- **验证方式与证据**：`tests/test_screen.py`、`tests/test_screen_protocol.py`、Browser/MCP UI 分支测试。

### B07【自动】可访问性 — 通过

- **场景描述**：工具按钮名称、禁用状态和键盘焦点。
- **操作步骤**：检查三个工具按钮的语义、busy/paused 禁用状态和装饰层 pointer-events。
- **预期结果**：按钮可识别、状态正确，装饰层不遮挡操作。
- **实际结果**：自动断言通过。
- **验证方式与证据**：UI widget tests、`assets/phone-screen.html` 共享按钮标记。

## C. 点击、拖动与滚动边界

### C01【对照】点击坐标 — 通过

- **场景描述**：中心、四角和边缘附近点击。
- **操作步骤**：在网页端点击计算器及屏幕边缘目标，比较画面反馈和真机位置映射。
- **预期结果**：网页和原生面板命中同一真机坐标。
- **实际结果**：共享 viewport 坐标换算正确；网页点击真机计算器按键和边界自动测试通过。
- **验证方式与证据**：`browser-calculator.png`、`browser-tap-7.png`、MCP/Browser 57 项 UI tests。

### C02【对照】拖动方向 — 通过

- **场景描述**：上、下、左、右拖动。
- **操作步骤**：在设置列表和主屏幕分别进行四向拖动。
- **预期结果**：方向、起止坐标和反馈正确，每个手势只执行一次。
- **实际结果**：上/下/左/右方向自动映射通过；网页上滑设置和左滑主屏幕已作用于真机。
- **验证方式与证据**：`browser-drag-up.png`、`browser-drag-left.png`、UI gesture tests。

### C03【自动】非正常点击 — 通过

- **场景描述**：右键、中键、长按、多个指针和轻微抖动。
- **操作步骤**：向共享 pointer handler 注入这些事件。
- **预期结果**：处理方式与原面板一致，不产生额外手机操作。
- **实际结果**：自动分支保持单次、合法 pointer 语义，异常输入被忽略或拒绝。
- **验证方式与证据**：Browser transport tests、UI pointer/gesture tests。

### C04【自动】手势取消 — 通过

- **场景描述**：拖出画面释放、取消指针、旋转或更换画面流。
- **操作步骤**：在测试 harness 中取消 pointer、改变 viewport/frame 序号后释放。
- **预期结果**：不发送失效手势。
- **实际结果**：取消和过期状态不会提交动作。
- **验证方式与证据**：UI gesture cancellation tests、屏幕状态测试。

### C05【自动】不可操作画面 — 通过

- **场景描述**：未解码、过期、暂停、忙碌或比例不匹配时点击。
- **操作步骤**：注入对应 preview 状态并尝试 pointer/action。
- **预期结果**：拒绝操作；恢复有效状态后才允许操作。
- **实际结果**：共享 UI 和 HTTP 服务均按状态拒绝非法动作。
- **验证方式与证据**：`tests/test_browser.py` 坐标/忙碌测试、UI state tests。

### C06【对照＋自动】滚动 — 通过

- **场景描述**：四向、小增量、惯性和连续滚动。
- **操作步骤**：真机设置列表上/下滑动，自动测试连续 gesture 和阈值。
- **预期结果**：沿用既有阈值和方向，每轮不积压、不重复。
- **实际结果**：网页滚动真机已验证，自动阈值和队列保护通过。
- **验证方式与证据**：`browser-drag-up.png`、`tests/test_browser.py`、UI gesture tests。

### C07【自动】不确定结果 — 通过

- **场景描述**：手势请求执行后超时。
- **操作步骤**：注入 `action_uncertain`/超时响应。
- **预期结果**：提示结果不确定，不自动重发。
- **实际结果**：HTTP 返回 uncertain 错误，调用计数为一次。
- **验证方式与证据**：`tests/test_browser.py::test_uncertain_mutation_is_returned_without_replay`。

## D. 工具栏

### D01【对照】主屏幕 — 通过

- **场景描述**：网页和系统浏览器点击主屏幕按钮。
- **操作步骤**：在 Chrome/Safari 网页点击 Home，观察真机回到主屏幕。
- **预期结果**：真机回到主屏幕，每次只发送一次。
- **实际结果**：网页和 Safari 均实际控制真机回到主屏幕；服务锁和单次提交通过。
- **验证方式与证据**：`browser-home.png`、`safari-home.png`、Browser HTTP action tests。

### D02【对照】截图 — 通过

- **场景描述**：截图按钮写入 Mac 剪贴板。
- **操作步骤**：分别在网页/原生工具栏点击截图，读取剪贴板 PNG。
- **预期结果**：得到正确 PNG，尺寸与真机画面一致。
- **实际结果**：`public.png` 已检查，尺寸 1170×2532；网页和原生截图均成功。
- **验证方式与证据**：`browser-clipboard.png`、`native-clipboard.png`、AppKit 剪贴板检查、截图 tests。

### D03【对照】刷新连接 — 通过

- **场景描述**：点击刷新而不重建 WDA。
- **操作步骤**：网页点击刷新，观察新 frame 序号和 WDA 进程。
- **预期结果**：只重连画面流，不重复构建或启动 WDA。
- **实际结果**：网页刷新后恢复画面，WDA 保持运行。
- **验证方式与证据**：Browser lifecycle tests、UI refresh tests、真机刷新记录。

### D04【自动】真实失败提示 — 通过

- **场景描述**：断线、剪贴板失败和服务不可用。
- **操作步骤**：注入对应错误响应并检查 UI/tool result。
- **预期结果**：显示实际失败原因，不显示成功提示。
- **实际结果**：错误码和提示按错误类型返回。
- **验证方式与证据**：Python screen/browser tests、UI error-state tests。

### D05【自动】连续点击按钮 — 通过

- **场景描述**：请求未完成时重复点击同一个工具按钮。
- **操作步骤**：阻塞首个 action，立即提交第二个 action。
- **预期结果**：第二次被 busy 拒绝；完成后恢复可用。
- **实际结果**：只执行一次，返回 `device_busy`，释放后状态恢复。
- **验证方式与证据**：`tests/test_browser.py::test_second_action_is_refused_without_queue_and_frame_remains_available`。

### D06【自动】刷新竞态 — 通过

- **场景描述**：刷新后旧请求延迟返回。
- **操作步骤**：让旧 stream response 在新连接建立后返回。
- **预期结果**：旧结果不能覆盖新连接或重新置为暂停。
- **实际结果**：frame/connection revision 防止旧结果覆盖新状态。
- **验证方式与证据**：UI refresh race tests、screen protocol tests。

## E. 锁屏、认证与并发

### E01【对照】手机锁屏 — 通过

- **场景描述**：手机自动锁屏，再由用户解锁。
- **操作步骤**：锁屏后观察两端状态；用户在 iPhone 上解锁并保持唤醒；重新 READY。
- **预期结果**：两端显示等待解锁并禁用操作，解锁后按规则恢复。
- **实际结果**：原生和网页均显示锁屏接管；用户回复“已解锁”后 READY 恢复，未重放旧操作。
- **验证方式与证据**：`native-locked.png`、`browser-locked.png`、`native-unlocked.png`、`browser-unlocked.png`、真实 READY 记录。

### E02【对照】App 认证暂停 — 未验证

- **场景描述**：App 要求密码、Face ID 或验证码时暂停。
- **操作步骤**：自动测试覆盖 pause/recovery 状态；本轮未让真实 App 进入认证接管。
- **预期结果**：暂停保持，用户完成认证后按规则恢复。
- **实际结果**：自动状态机测试通过，真实 Face ID/App 认证未执行。
- **验证方式与证据**：认证状态测试和 `skills/iphone-use/references/authentication.md`；缺少真机认证截图。

### E03【自动】暂停期间迟到帧 — 通过

- **场景描述**：暂停后收到旧帧或旧手势事件。
- **操作步骤**：注入 pause 后的迟到 frame/event。
- **预期结果**：不替换冻结画面，不移除接管遮罩。
- **实际结果**：旧 frame/event 被 revision 和 pause 状态丢弃。
- **验证方式与证据**：UI pause/revision tests、screen protocol tests。

### E04【自动】恢复期间新暂停 — 通过

- **场景描述**：解锁检查期间触发新的认证暂停。
- **操作步骤**：让旧 READY 结果晚到，同时注入新 pause。
- **预期结果**：新暂停不能被旧检查结果清除。
- **实际结果**：pause generation/reason 保持新状态。
- **验证方式与证据**：screen recovery state tests、Runtime READY tests。

### E05【对照】Agent 与网页并发 — 通过

- **场景描述**：Agent 操作时网页同时尝试操作。
- **操作步骤**：持有共享 `operation.lock`，并发提交网页 action。
- **预期结果**：遵守同一操作锁，忙碌期间不插入操作。
- **实际结果**：网页得到 `device_busy`，Agent request 未被插入或重放。
- **验证方式与证据**：`tests/test_browser.py::test_browser_gesture_obeys_the_same_filesystem_lock_as_an_agent`、真机交替操作记录。

### E06【对照】双端交替操作 — 通过

- **场景描述**：原生面板与网页交替点击、滑动。
- **操作步骤**：在两个标签轮流操作同一台 iPhone，观察画面和状态。
- **预期结果**：都作用于同一手机，坐标反馈和暂停状态一致。
- **实际结果**：原生与网页显示同一设备并共享服务，网页点击/拖动改变真机后原生观察同步。
- **验证方式与证据**：`native-aligned.png`、`browser-aligned.png`、calculator/drag screenshots、shared runtime tests。

### E07【自动】多个网页 — 通过

- **场景描述**：同时打开多个带 token 的网页。
- **操作步骤**：在 Chrome、Safari、宿主内置浏览器打开同一实际 URL。
- **预期结果**：复用服务和画面源，不重复执行控制请求。
- **实际结果**：多个页面共享一个 worker；HTTP 生命周期和并发测试通过。
- **验证方式与证据**：`tests/test_browser.py::test_concurrent_agent_starts_share_one_worker`、Chrome/Safari/IAB 实际标签。

## F. 断线、恢复与页面生命周期

### F01【对照】USB 断开恢复 — 未验证

- **场景描述**：拔掉 USB 后重新连接。
- **操作步骤**：自动覆盖断线状态和恢复边界；本轮未在真实验收中拔插唯一真机。
- **预期结果**：显示断线并恢复，不重放旧操作。
- **实际结果**：自动恢复逻辑通过；真实 USB 拔插尚未完成。
- **验证方式与证据**：recovery/screen tests；缺少真实拔插证据。

### F02【自动】屏幕流进程退出 — 通过

- **场景描述**：采集进程异常退出。
- **操作步骤**：注入 stream worker 退出并观察重连次数。
- **预期结果**：有界重连，不循环重启整个 WDA。
- **实际结果**：重连边界和进程归属检查通过。
- **验证方式与证据**：screen recovery tests、30 分钟日志中的单个采集进程记录。

### F03【自动】WDA 重启 — 通过

- **场景描述**：旧会话失效并出现新画面流标识。
- **操作步骤**：注入 invalid session，执行 READY/recovery。
- **预期结果**：只重建必要会话，重置帧序号和事件确认，不重放动作。
- **实际结果**：invalid session 只触发新查询/会话恢复。
- **验证方式与证据**：`tests/test_browser.py::test_ready_recovers_expired_session_by_querying_once_without_restarting_wda`、Runtime recovery tests。

### F04【自动】慢请求与乱序 — 通过

- **场景描述**：帧响应延迟、请求超时和旧帧后到。
- **操作步骤**：注入乱序帧与超时。
- **预期结果**：不重叠轮询，不倒退到旧画面或旧状态。
- **实际结果**：序号、revision 和 bounded retry 保护通过。
- **验证方式与证据**：screen protocol/recovery tests、UI stale-frame tests。

### F05【对照】网页服务重启 — 通过

- **场景描述**：停止并重新启动网页服务。
- **操作步骤**：执行 browser stop/start，重新访问新 URL。
- **预期结果**：WDA 保持运行，新链接有效，旧 token 按设计失效。
- **实际结果**：服务可停止/重启，WDA 不被停止，新 token 生成且旧元数据不复用。
- **验证方式与证据**：Browser lifecycle tests、真机服务重启记录。

### F06【对照】页面隐藏和返回 — 未验证

- **场景描述**：切换标签、最小化、前进后退、关闭后重开。
- **操作步骤**：自动测试覆盖 visibility/close 生命周期；本轮未对全部浏览器历史和最小化组合逐一录制真机证据。
- **预期结果**：隐藏时停止无效工作，返回后恢复画面，不重复绑定事件。
- **实际结果**：页面 visibility 和重连逻辑已有自动覆盖；完整宿主组合仍未逐项实测。
- **验证方式与证据**：UI lifecycle tests、Chrome/Safari/IAB 标签；缺少完整手动矩阵。

## G. Agent、浏览器与安装分发

### G01【宿主】原生面板宿主 — 通过

- **场景描述**：在 Codex 中启动手机屏幕。
- **操作步骤**：新安装 0.4.0 后执行 setup、READY 和 screen open。
- **预期结果**：原生面板可用，回复含真实网页链接。
- **实际结果**：Codex MCP Apps 原生 tab 已打开并显示 iPhone 14/Live；READY 和 screen open 返回 `browser_url`。
- **验证方式与证据**：实际 Codex MCP App tab、`browser-aligned.png`/`native-aligned.png`、安装后的 READY JSON。

### G02【宿主】只有侧栏浏览器 — 通过

- **场景描述**：宿主不支持 MCP App，但支持侧栏浏览器。
- **操作步骤**：在 ChatGPT in-app browser/侧栏浏览器打开实际 `browser_url`，执行点击和拖动。
- **预期结果**：按用户要求在侧栏打开，功能完整。
- **实际结果**：IAB、Chrome 和 Safari 均可打开并操作同一真机。
- **验证方式与证据**：IAB tab、Chrome/Safari 标签、`safari-home.png`、calculator/drag screenshots。

### G03【宿主】没有侧栏浏览器 — 未验证

- **场景描述**：宿主没有可嵌入的侧栏浏览器。
- **操作步骤**：文档和工具描述覆盖提供可点击链接；本轮未在一个确实没有侧栏能力的 Agent 中做宿主现场验证。
- **预期结果**：提供链接，不声称已打开侧栏；用户要求后才打开系统浏览器。
- **实际结果**：代码/skill 文本和自动测试符合策略，缺少目标宿主现场证据。
- **验证方式与证据**：`README.md`、两个 skill、`server/iphone_use.py` 指引；宿主现场待补。

### G04【自动】精简 PATH 与路径差异 — 通过

- **场景描述**：GUI PATH、带空格路径和不同用户目录。
- **操作步骤**：使用精简 PATH、`$HOME` 和带空格临时目录运行入口。
- **预期结果**：发现 Python/Node/插件入口，不依赖固定用户名。
- **实际结果**：桌面入口和环境发现测试通过，配置使用 `$HOME`。
- **验证方式与证据**：`tests/test_launcher.py::test_desktop_shortcut_uses_home_and_preserves_a_backup_of_its_owned_entry`、实际 GUI PATH 启动记录。

### G05【自动】安装包完整性 — 通过

- **场景描述**：从源码包和解压安装包启动。
- **操作步骤**：打包、validate-only、安装，再检查网页、服务、命令和 skills。
- **预期结果**：页面、服务、命令、两个 skill 齐全，旧工具协议兼容。
- **实际结果**：0.4.0 包完成验证并安装，相关文件均在清单中。
- **验证方式与证据**：`tests/test_packaging.py`、`dist/iphone-use-0.4.0-source.zip`、`sh scripts/install.sh`。

### G06【宿主】浏览器兼容 — 通过

- **场景描述**：Chrome、Safari 和宿主内置浏览器执行核心交互。
- **操作步骤**：打开实际 URL，执行画面观察、点击、拖动、Home 和截图。
- **预期结果**：画面、手势和工具栏均可用。
- **实际结果**：Chrome、Safari、ChatGPT IAB 均通过核心操作；截图和 Home 已在真机确认。
- **验证方式与证据**：浏览器标签状态、`safari-home.png`、clipboard/calculator/drag screenshots。

### G07【自动＋宿主】已有适配回归 — 通过

- **场景描述**：WorkBuddy、豆包安装及 skill 文本适配。
- **操作步骤**：运行 WorkBuddy/Doubao 回归测试并检查安装说明中的 browser_url/回退指引。
- **预期结果**：原有能力正常，新链接和浏览器指引正确分发。
- **实际结果**：WorkBuddy 36/36、Doubao 15/15；文档和安装资源已更新。
- **验证方式与证据**：WorkBuddy 及 Doubao 测试日志、`workbuddy/README.md`、`doubao/README.md`。

## H. 服务边界、资源与持续运行

### H01【自动】访问校验 — 通过

- **场景描述**：错误 token、非法 Host、跨来源请求。
- **操作步骤**：向 HTTP 服务发送错误 Host/Origin/Bearer。
- **预期结果**：请求被拒绝，不触发手机操作。
- **实际结果**：返回 403，Runtime 调用列表保持为空。
- **验证方式与证据**：`tests/test_browser.py::test_host_origin_and_token_fail_before_any_backend_call`。

### H02【自动】输入与接口边界 — 通过

- **场景描述**：非法坐标、错误 JSON、超限请求和非面板工具。
- **操作步骤**：发送 malformed JSON、超限 body、非法坐标和 `pua_setup`/任意工具名。
- **预期结果**：正确拒绝，后续合法请求仍可处理。
- **实际结果**：400/403/413 或结构化错误按边界返回，服务仍可继续处理 frame。
- **验证方式与证据**：`tests/test_browser.py::test_bad_json_body_size_and_coordinates_leave_service_usable`、`test_no_arbitrary_tools_files_or_get_mutations`。

### H03【自动】进程归属 — 通过

- **场景描述**：陈旧进程记录、非项目进程和非本地元数据。
- **操作步骤**：注入未验证 PID/外部 URL，调用 status/stop。
- **预期结果**：只处理本项目拥有的 worker，不停止其他服务或 WDA。
- **实际结果**：未验证归属时拒绝 kill，外部元数据不触发请求。
- **验证方式与证据**：`tests/test_browser.py::test_unverified_process_and_nonlocal_metadata_are_never_signalled`。

### H04【自动】资源释放 — 未验证

- **场景描述**：关闭所有预览页面后释放采集租期，再重新打开。
- **操作步骤**：自动服务 stop/status 已验证；本轮未在所有真实浏览器标签关闭后额外测量租期释放和重新打开延迟。
- **预期结果**：无页面时停止无效采集，重新打开可恢复。
- **实际结果**：服务停止和重启逻辑通过，完整“所有页面关闭→租期结束”现场证据仍缺少。
- **验证方式与证据**：Browser lifecycle tests、30 分钟日志；手动页面租期矩阵待补。

### H05【对照】持续运行 — 通过

- **场景描述**：连续使用约 30 分钟并多次切换页面。
- **操作步骤**：保持浏览器服务和画面流运行，切换标签并观察进程、内存和帧响应。
- **预期结果**：无持续黑屏、请求堆积或进程不断增加。
- **实际结果**：30 分钟记录保持一个屏幕流子进程，服务持续运行，没有请求堆积或黑屏回归。
- **验证方式与证据**：`outputs/browser-0.4.0/soak-30min.jsonl`。

### H06【自动】刷新与日志开销 — 通过

- **场景描述**：相同帧、重复序号和长时间日志。
- **操作步骤**：注入重复 frame/seq，检查去重、布局调用和日志内容。
- **预期结果**：沿用去重策略，不逐帧重复布局或记录完整画面数据。
- **实际结果**：重复序号被忽略，日志不包含逐帧完整图像数据，布局只在必要 revision 更新。
- **验证方式与证据**：screen protocol/UI tests、soak 日志和 `scripts/check_screen_ui.py`。

## 当前未完成的现场验收

以下项目没有被误报为通过：A05 的真实无设备启动、B04 的新版原生横屏同轮对照、E02 的真实 App/Face ID 接管、F01 的真实 USB 拔插、F06 的完整浏览器历史/最小化矩阵、G03 的无侧栏宿主现场、H04 的全部页面关闭后租期释放。它们已有自动化或文档覆盖的部分会继续保留，但在补做前不应称为完整真机/宿主验收通过。
