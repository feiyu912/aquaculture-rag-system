# 前端设计系统（Aqua RAG Design System）

> 本文件是 `apps/web` 的**唯一视觉规范来源**。新增页面与组件必须复用此处的
> token 与组件；出现与本文件不一致的样式视为缺陷。
> 实现位置：`apps/web/src/app/globals.css`（token 定义）与
> `apps/web/src/components/ui/`（基础组件）。

## 0. 设计定位

| 维度 | 决策 |
|---|---|
| 风格 | 现代 AI SaaS / Research Workspace，不是传统管理后台 |
| 气质 | 明亮、中性、低饱和；单一品牌强调色（深青蓝） |
| 密度 | 中等偏紧凑：信息密集处用表格/列表，叙事处用留白 |
| 图标 | 全站统一 Lucide，线宽 1.75（激活态 2.1），不混用其他图标库 |
| 主题 | 浅色 / 深色 / 跟随系统，三者共用同一套 token 命名 |
| 动效 | 120–280ms，只用于状态反馈与进入动画；尊重 `prefers-reduced-motion` |

### 从四张参考图中提炼的共同语言

1. **参考图 1（问答）** → 会话侧栏 + 流式回答 + 编号引用卡 + 引用高亮。
2. **参考图 2（文档）** → 左侧竖向图标导航 + 表格 + 拖拽上传 + 右侧操作面板。
3. **参考图 3（PDF）** → 深色阅读画布 + 缩放/翻页工具条 + 右侧高亮摘要栏。
4. **参考图 4（调试）** → 深色"仪表盘"面板 + 阶段链路 + 排名条 + 原始数据入口。

四者**不直接拼接**，而是统一到同一套 token：外壳是浅色的，只有真正需要
"仪器感"或"阅读专注"的区域（PDF 画布、检索调试面板）才使用深色仪表表面。

## 1. 色彩

### 1.1 品牌色（唯一强调色）

深青蓝，兼顾"水产"语义与商业 AI 产品的克制感。

| Token | 浅色值 | 用途 |
|---|---|---|
| `--primary-50` | `hsl(185 84% 96.5%)` | 引用芯片底色、浅色标签 |
| `--primary-300` | `hsl(187 63% 74%)` | 描边、分隔 |
| `--primary-500` | `hsl(190 62% 45%)` | 深色模式主按钮、焦点环 |
| `--primary-600` | `hsl(191 66% 36%)` | 链接、次级强调 |
| `--primary-700` | `hsl(192 70% 29%)` | 浅色模式主按钮底色 |
| `--primary-900` | `hsl(194 56% 17%)` | 深色模式浅色文字 |

> 深色模式下 `--primary-50..900` 会被**反转**（用于强调文字）。
> 因此**填充型按钮不得直接用 `bg-primary-700 text-white`**，必须使用
> 专用 token，否则会出现浅底白字。

### 1.2 填充品牌色专用 token

| Token | 浅色 | 深色 | 用途 |
|---|---|---|---|
| `--primary-btn` | `hsl(192 70% 29%)` | `hsl(190 62% 45%)` | 实心按钮 / 用户气泡 / 激活分段控件 |
| `--primary-btn-hover` | `hsl(193 64% 23%)` | `hsl(189 58% 52%)` | hover |
| `--primary-fg` | `#ffffff` | `hsl(196 90% 7%)` | 实心品牌色上的前景 |
| `--primary-soft` | `hsl(185 84% 96.5%)` | `hsl(190 40% 14%)` | 软底标签 |
| `--primary-soft-fg` | `hsl(194 56% 17%)` | `hsl(190 70% 82%)` | 软底上的前景 |

### 1.3 中性色

| Token | 浅色 | 深色 | 用途 |
|---|---|---|---|
| `--background` | `hsl(210 33% 98%)` | `hsl(222 28% 8%)` | 页面底 |
| `--surface` | `#ffffff` | `hsl(221 24% 11%)` | 卡片 / 面板 / 顶栏 |
| `--surface-muted` | `hsl(214 28% 96.5%)` | `hsl(220 20% 14%)` | 次级填充 |
| `--surface-inset` | `hsl(215 25% 93.5%)` | `hsl(220 18% 17%)` | 输入框、代码块、占位 |
| `--border` | `hsl(214 20% 89%)` | `hsl(220 16% 21%)` | 发丝线 |
| `--border-strong` | `hsl(214 16% 80%)` | `hsl(220 14% 29%)` | 强分隔、hover 边框 |
| `--foreground` | `hsl(222 28% 13%)` | `hsl(210 30% 94%)` | 主文字 |
| `--muted-foreground` | `hsl(215 13% 44%)` | `hsl(216 14% 64%)` | 次级文字 |
| `--subtle-foreground` | `hsl(214 11% 58%)` | `hsl(216 12% 51%)` | 三级文字、图标 |

### 1.4 语义色（只用于状态，禁止装饰）

`success / warning / danger / info`，每个都有 `-soft` 浅底变体。

### 1.5 仪表表面（instrument）

`--instrument*` 系列是**始终为深色**的一组 token，服务于 PDF 画布与
检索调试面板：深海军蓝底 + 低对比描边 + 高亮青色数据条。

### 1.6 使用规则

- 页面底色只用 `--background`；卡片用 `--surface`；不要用纯灰阶堆叠。
- 品牌色只出现在**一个**视觉焦点上（一屏内不超过 3 处实心品牌色）。
- 状态色必须成对出现（底 + 前景），禁止直接写 `text-green-600`。
- 所有颜色必须来自 token，**禁止**在组件里写十六进制色值。

## 2. 字体

- 拉丁字族：`Inter`（`next/font/google`，变量 `--font-inter`）。
- 中文字族：`PingFang SC → Hiragino Sans GB → Microsoft YaHei → Noto Sans SC`。
- 等宽：`ui-monospace / SF Mono / JetBrains Mono`，用于 bbox、trace_id、耗时。

| 角色 | 字号 / 行高 | 字重 | 备注 |
|---|---|---|---|
| 页面标题 | 15px / 1.4 | 600 | 顶栏 |
| 区块标题 | 13–15px / 1.4 | 600 | |
| 正文 | 14px / 1.6 | 400 | 表格、面板 |
| 回答正文 | 14.5px / 1.78 | 400 | `.prose-aqua` |
| 次级 | 12.5px / 1.6 | 400 | |
| 辅助 | 11.5px / 1.5 | 400–500 | 元信息、时间戳 |
| 标签 eyebrow | 11px / 1.4 | 600 | 大写 + `0.08em` 字距 |
| 数字读数 | — | — | 一律 `font-variant-numeric: tabular-nums` |

## 3. 间距与圆角

- 基准 4px。页面左右留白：桌面 24px / 移动 16px。
- 卡片内边距 20–24px（`p-5` / `p-6`），紧凑条目 12–14px。
- 区块纵向间距 24–32px；列表项之间 8–12px。

| Token | 值 | 用途 |
|---|---|---|
| `--radius-sm` | 6px | 标签、代码 |
| `--radius-md` | 8px | 按钮、输入框 |
| `--radius-lg` | 10px | 小卡片 |
| `--radius-xl` | 12px | 卡片、面板 |
| `--radius-2xl` | 16px | 浮层、输入区容器 |

## 4. 阴影

| Token | 用途 |
|---|---|
| `--shadow-xs` | 按钮、静置元素 |
| `--shadow-sm` | 卡片 |
| `--shadow-md` | hover 抬升、下拉 |
| `--shadow-lg` | 浮层、抽屉 |
| `--shadow-xl` | 对话框 |

阴影一律低透明度冷色，禁止纯黑硬阴影。

## 5. 动效

| Token | 值 |
|---|---|
| `--duration-fast` | 120ms（hover、颜色） |
| `--duration-base` | 180ms（展开、切换） |
| `--duration-slow` | 280ms（抽屉、页面进入） |
| `--ease-out-soft` | `cubic-bezier(0.32, 0.72, 0, 1)`（进入） |
| `--ease-standard` | `cubic-bezier(0.4, 0, 0.2, 1)`（通用） |

规则：位移 ≤ 4px；不使用会挤压布局的缩放；`prefers-reduced-motion` 下全部降级。

## 6. 布局规则

```
┌──────────────────────────────────────────────────────────┐
│ TopBar  h=56px  模块名 · 健康状态 · 主题 · 外部链接        │
├────┬──────────────┬─────────────────────────────────────┤
│Rail│ Context Panel │  Main                                │
│68px│ 288px（可拖拽）│  max-width 由页面自行决定             │
└────┴──────────────┴─────────────────────────────────────┘
```

- **Icon Rail**（`lg` 以上）：全局四个模块，68px 宽，激活项为圆角方块 + 左侧 3px 指示条。
- **Context Panel**：随页面变化（会话 / 筛选 / 缩略图 / 链路）。
  - 宽度**可拖拽**：分隔条支持指针拖拽、方向键（`←/→`，`Shift` 加速）、
    `Home`/`End` 跳到极值、双击或 `Enter` 恢复默认。宽度写入 `localStorage`。
  - 顶栏左侧的按钮可收起 / 展开；`< lg` 时改为左侧抽屉（`role="dialog"`）。
- **Bottom Nav**（`< lg`）：移动端 4 个模块的底部标签栏，56px 高。
- **Main**：内容区统一 `max-w-[780px] mx-auto`（叙事型）或满宽（工具型）。
- 断点：`sm 640 / md 768 / lg 1024 / xl 1280 / 2xl 1536`。

### 6.1 滚动模型（重要）

应用是**固定视口**外壳：任何长列表都在自己的 `overflow-y-auto` 区域里滚动，
**文档本身不滚动**。内层滚动区必须加 `scroll-contain`
（`contain: paint`），否则溢出的内容仍会计入根元素的可滚动区域，
整页会跟着一起滑，页面底部出现空白。

```tsx
<div className="scroll-contain min-h-0 flex-1 overflow-y-auto">…</div>
```

### 6.2 阅读器（PDF）专用规则

- 画布恒为深色（`--instrument`），页面为白纸。
- 默认**按宽度自适应**：缩放比例 = 容器宽度 / 页面宽度；用户手动缩放后即接管。
- 缩放会改变页高，页码锚点与高亮位置必须**在缩放后重新计算**。
- 引用面板在 `< 1280px` 变为覆盖式抽屉，不能挤压画布。

## 7. 组件清单（`src/components/ui`）

`button` `input` `textarea` `badge` `separator` `skeleton` `tooltip`
`dropdown-menu` `select` `scroll-area` `tabs` `dialog` `progress` `avatar`
`switch` `alert` `toaster`

业务组件：

- 布局：`layout/app-shell` `layout/icon-rail` `layout/mobile-nav` `layout/top-bar`
  `layout/theme-toggle` `layout/shell-context`
- 问答：`chat/chat-workspace` `chat/message-list` `chat/answer-markdown`
  `chat/citation-chip` `chat/source-card` `chat/source-panel`
  `chat/source-panel-drawer` `chat/composer` `chat/session-sidebar`
  `chat/chat-empty-state`
- 知识库：`knowledge/*`
- 阅读器：`reader/*`
- 调试：`debug/*`

## 8. 状态与反馈规范

| 场景 | 处理 |
|---|---|
| 加载中 | Skeleton（结构占位），不用整页 spinner |
| 流式生成 | 三点脉冲 + "生成中" 标签，token 逐字追加 |
| 证据不足 | 独立警示卡（`warning-soft`），**不**用普通回答样式 |
| 回答被中断 | 独立警示卡「回答未完成」+「重试」，并说明是否留有部分内容 |
| 请求失败 | 卡片内错误 + "重试"按钮，保留已生成内容 |
| 空状态 | 图标 + 一句话说明 + 2–3 个可点击的真实示例 |
| 后端离线 | 顶栏状态胶囊变红 + 悬浮显示组件级错误 |
| 未启用能力 | 明确标注"未启用/未接入"，**不模拟**结果 |
| 引用触顶 | 引用面板显示 `已用 / 上限`，并提示上限由后端 `MAX_SOURCES` 控制 |

**中断语义**：后端在开始流式之前就写入 assistant 行；若此时进程重启，
该行会永久停留在 `status="streaming"` + 空内容。前端必须把这种消息渲染为
「回答未完成」，而不是空白气泡。

## 9. 可访问性

- 正文对比度 ≥ 4.5:1，大字与图标 ≥ 3:1。
- 所有交互元素可聚焦，`:focus-visible` 使用 2px 品牌色描边。
- 图标按钮必须有 `aria-label`。
- 引用芯片用 `<button>`，同时提供 `title` 说明。
- 尊重 `prefers-reduced-motion`。

## 10. 视觉回归与端到端检查

### 视觉回归

```bash
cd apps/web
node scripts/review.mjs "/chat" --w 1440 --h 900 --out chat-desktop
node scripts/review.mjs "/chat" --w 390 --h 844 --out chat-mobile --dark
```

脚本会在真实后端下渲染页面、截图，并报告横向溢出元素与控制台错误。
改动任何页面后必须至少跑一次 1440 / 1024 / 390 三个宽度。

### 端到端

```bash
cd apps/web
npm run e2e                       # 桌面 + 移动两个 project
npx playwright test --project=desktop-chromium e2e/reader.spec.ts
npx playwright show-report .review/e2e-report
```

E2E 直接打真实后端：真实上传 PDF、等真实 ARQ worker 入库、真实 SSE、
真实引用与真实 PDF 高亮。**不 mock 任何请求。**

| 规格 | 覆盖内容 |
|---|---|
| `chat.spec.ts` | SSE 事件序列、流式渲染、引用芯片、证据不足 |
| `knowledge.spec.ts` | 上传入库、版本历史与回滚、删除 |
| `version-dialog.spec.ts` | 新版本弹窗（选文件 → 轮询任务 → 生效） |
| `reader.spec.ts` | PDF 渲染、页码跳转、**高亮几何+像素双校验**、缩放同步、点击引用跳转 |
| `debug.spec.ts` | 阶段链路、遥测统计、载入真实 Trace、无效 id 的错误态 |
| `layout.spec.ts` | 整页不滚动、侧栏拖拽与持久化、标题完整、收起 |
| `shell.mobile.spec.ts` | 底部标签栏、会话抽屉、问答、知识库、阅读器、整页不滚动 |

`e2e/fixtures/` 下的 PDF 由 `e2e/fixtures/generate.py` 生成，
其中 `e2e-rotated.pdf` 的第 2 页带 `/Rotate 90`，用于验证旋转页的坐标换算。

> `npm run build` 与 `next dev` 使用不同的输出目录
> （`NEXT_DIST_DIR=.next-build`），避免构建覆盖正在运行的开发服务器。
