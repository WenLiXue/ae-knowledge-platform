# AE 内部知识平台——知识查询 Codex 式布局改造设计

版本：V0.1  
状态：待实现  
文档编号：DD-18  
日期：2026-08-25  
目标工程：`D:\Projects\ae-knowledge-platform\frontend`  
视觉参考：`docs/prototypes/visual-directions/search-home-redesign-demo.html`

## 1. 改造目标

面向需要快速查询产品规格、部署方式、功能说明和历史案例的内部用户，将知识查询首页从“管理后台表单页”改造成以输入和连续会话为中心的工作区。

目标行为：

- 用户进入 `/search` 后，第一视觉焦点是问题输入框；
- 最近会话位于桌面左侧栏，不再占据主内容区；
- 查询范围是可选辅助能力，默认收起；
- 用户可以从示例问题快速填入问题；
- 查询提交、筛选联动和现有会话跳转行为保持可用；
- `/admin/*`、文档管理等其他页面不因本次改造发生视觉或功能回归；
- 现有 Mock 会话 API 可以继续使用，未来替换真实 API 时页面组件接口无需重写。

## 2. 非目标

- 不实现后端会话、问答、SSE 或 RAG；
- 不把整个系统主题改成 Codex 主题；
- 不重做登录、文档管理、审计日志、系统日志和配置页面；
- 不删除现有路由或管理员权限判断；
- 不逐像素复制 Codex 品牌、Logo、文案或专有视觉资产；
- 不引入新的全局状态库和大型 UI 依赖。

## 3. 当前实现证据

### 3.1 应用外壳

`frontend/src/components/AppShell.tsx` 当前使用：

- 248px MUI permanent Drawer；
- 所有导航分组在侧栏中完整展开；
- 主内容统一放入 `Container maxWidth="lg"`；
- 移动端使用 temporary Drawer；
- 管理员导航依赖 `user.role === "admin"`；
- 当前工作区存在系统日志与审计日志相关未提交修改，必须保留。

### 3.2 查询首页

`frontend/src/pages/SearchPage.tsx` 当前使用：

- `PageHeader`；
- 一个全宽 `Card` 包裹问题输入、三个 Select 和两个操作按钮；
- 主内容区展示多张全宽最近会话 Card；
- `handleSubmit()` 创建会话、创建消息并跳转会话页；
- 产品切换后清空版本；
- Ctrl/Cmd + Enter 提交；
- 会话、问答和目录选项目前来自 `frontend/src/api/conversations.ts` 的 Mock。

### 3.3 不能直接采用的方案

- 不能仅给 `SearchPage` 调整 margin/padding：最近会话仍在错误层级；
- 不能在 `AppShell` 无条件请求最近会话：管理页面不应加载会话数据；
- 不能全局覆盖 `MuiCard`、`MuiButton`、`MuiListItemButton`：会影响已完成管理页面；
- 不能用第二套嵌套侧栏包住 `SearchPage`：会造成双侧栏和移动端重复导航。

## 4. 目标信息架构

### 4.1 桌面端

```text
┌─────────────────────────┬────────────────────────────────────────────┐
│ 品牌                    │ 知识查询                      帮助  反馈   │
│ [新建查询]              │                                            │
│                         │                                            │
│ 知识查询                │          基于已入库的产品资料回答           │
│ 文档库                  │             今天想查询什么？               │
│ 问题诊断                │                                            │
│ 系统管理                │        ┌────────────────────────┐          │
│                         │        │ 问题输入                │          │
│ 最近会话                │        │                        │          │
│ T90000 硬件规格         │        │ [限定范围]         [发送]│          │
│ 国产化型号清单          │        └────────────────────────┘          │
│ 网桥与路由模式区别      │        [示例] [示例]                       │
│ ...                     │        [示例] [示例]                       │
│                         │                                            │
│ 当前用户 / 设置         │                 事实核验说明               │
└─────────────────────────┴────────────────────────────────────────────┘
```

### 4.2 移动端

- 保留现有顶部 AppBar 和 temporary Drawer；
- 最近会话不常驻显示在页面左侧；
- 主区从顶部自然排列，不强制垂直居中；
- Composer、筛选面板、示例问题均为单列；
- 发送按钮保持至少 36×36 CSS px，其他交互目标尽量达到 44px；
- 不产生横向滚动。

## 5. 视觉规则

### 5.1 设计语言

采用 Codex 式布局逻辑，而不是复制 Codex 品牌：

- 中性浅灰侧栏，低对比边界；
- 主内容画布安静、留白充足；
- 首页不使用大面积 Card 堆叠；
- Composer 是唯一高权重容器；
- 主操作使用深色发送按钮；
- 蓝色继续用于链接、焦点和产品原有语义色，不把所有选中态染成蓝色；
- 最近会话使用紧凑文本行，不使用卡片。

### 5.2 建议尺寸

| 元素 | 建议值 |
|---|---|
| 桌面侧栏宽度 | 264～280px，推荐 272px |
| 主 Composer 最大宽度 | 720～780px，推荐 760px |
| Composer 圆角 | 14～16px |
| Composer 最小输入高度 | 80～96px |
| 桌面顶部栏 | 56～60px |
| 最近会话行 | 42～50px |
| 示例问题 | 两列，每项约 52～60px |

不要添加渐变、大面积阴影、玻璃拟态或装饰插画。Composer 聚焦时只使用轻量边框变化和柔和阴影。

## 6. 组件与状态设计

### 6.1 `ConversationWorkspaceContext`

建议新增：

`frontend/src/conversations/ConversationWorkspaceContext.tsx`

职责：

- 调用 `listConversations()`；
- 提供最近会话列表、加载、错误和刷新能力；
- 避免 `AppShell` 与 `SearchPage` 重复请求；
- 新会话创建并跳转后允许刷新侧栏；
- 后续替换真实 API 时保持调用方稳定。

建议接口：

```ts
interface ConversationWorkspaceValue {
  conversations: Conversation[];
  loading: boolean;
  error: unknown;
  refreshConversations: () => Promise<void>;
}
```

Provider 放在已登录主布局内部，使 `AppShell`、`SearchPage` 和 `ConversationPage` 可共享。不要把认证状态复制到该 Context。

如果实现 Agent 判断 Context 对当前规模过重，可以先提取 `useConversations()` hook，但必须保证一个页面生命周期内不会从 AppShell 和 SearchPage 重复请求。

### 6.2 `QueryComposer`

建议新增：

`frontend/src/components/query/QueryComposer.tsx`

职责：

- 问题输入；
- Ctrl/Cmd + Enter 提交；
- 发送 loading/disabled 状态；
- 展开/收起查询范围；
- 产品、版本、文档类型联动；
- 已选条件 Chip 与单项清除；
- 保留键盘和屏幕阅读器标签。

建议 Props：

```ts
interface QueryComposerProps {
  question: string;
  filters: QueryFilters;
  submitting: boolean;
  onQuestionChange: (value: string) => void;
  onFiltersChange: (filters: QueryFilters) => void;
  onSubmit: () => void;
  autoFocus?: boolean;
}
```

目录数据暂时可以沿用 `CATALOG_OPTIONS`，但组件不得直接修改全局 Mock 数据。版本必须根据产品计算，清除产品时同时清除版本。

### 6.3 查询工作区侧栏

建议新增：

`frontend/src/components/navigation/QueryWorkspaceSidebar.tsx`

职责：

- 新建查询按钮；
- 主要工作区入口；
- 最近会话列表；
- 当前会话高亮；
- loading、空、错误状态；
- 保留管理员入口，但可以折叠为“系统管理”分组或继续使用现有项。

实现原则：

- `/search` 和 `/conversations/:id` 使用查询工作区侧栏；
- `/admin/*` 必须仍能访问系统日志、审计日志、用户管理和配置；
- 不覆盖当前 `AppShell.tsx` 中用户新增的 `system-logs` 导航；
- 最近会话标题必须截断；
- 归档会话是否显示沿用当前产品规则，当前 Mock 可先展示已有列表；
- 新建查询跳转 `/search`。若已经在 `/search`，通过 `location.key`、Context 方法或组件状态清空输入；不要强制刷新浏览器。

### 6.4 `AppShell`

推荐实现为路由感知的两种桌面模式：

```ts
const isQueryWorkspace =
  pathname === "/search" || pathname.startsWith("/conversations/");
```

- 查询工作区：渲染 `QueryWorkspaceSidebar`；
- 其他页面：保留现有管理导航侧栏；
- 移动端：继续使用一个 temporary Drawer，在其中按当前路由选择内容；
- 主区容器策略按路由切换。

主区不要继续对所有页面统一套 `Container maxWidth="lg"`。建议：

```tsx
<Box component="main" ...>
  <Toolbar ... />
  {isQueryWorkspace ? (
    <Outlet />
  ) : (
    <Container maxWidth="lg" ...><Outlet /></Container>
  )}
</Box>
```

这样管理页面保持原布局，查询首页和会话页可以自己控制宽度与垂直布局。

## 7. `SearchPage` 修改要求

### 7.1 删除

- 删除 `PageHeader`；
- 删除外层查询 `Card/CardContent`；
- 删除三个始终展开的横向 `FormControl`；
- 删除说明文字与操作按钮分居两端的布局；
- 删除“新建会话”按钮和 `handleNewSession()`；
- 删除主内容区“最近会话”标题和所有会话 Card；
- 删除不再使用的 `HistoryIcon`、`AddIcon`、Card 相关 import；
- 若格式化时间和筛选名称函数只供主区历史列表使用，将其移动到侧栏组件或删除。

### 7.2 新增

- 页面根节点至少占满可用主区高度；
- 顶部轻量页面标题或工具栏；
- 居中的欢迎文案：
  - 次级文案：“基于已入库的产品资料回答”；
  - 主标题：“今天想查询什么？”；
- 使用 `QueryComposer`；
- 四个示例问题：产品规格、部署要求、功能比较、历史案例；
- 示例问题点击后填入 Composer 并聚焦，不自动提交；
- 底部事实核验提示：“答案基于企业知识库生成，请通过引用来源核验关键事实。”；
- loading/error 不应让主输入区消失。会话加载失败只影响侧栏，并提供重试。

### 7.3 保留

- 当前 `handleSubmit()` 的业务调用顺序；
- question trim 和重复提交保护；
- `QueryFilters` 字段名；
- 产品切换清空版本；
- Ctrl/Cmd + Enter；
- 提交成功后跳转 `/conversations/{id}`；
- `appendAssistantMessage()` 和 Mock 演示行为，除非另有后端任务同时替换。

## 8. 会话页兼容

本次不要求重做 `ConversationPage` 内容，但切换 AppShell 容器后必须确保：

- 会话页不会横向溢出；
- 会话消息区仍有合理最大宽度；
- Composer 不被底部事实提示或侧栏遮挡；
- 当前会话在侧栏高亮；
- 从侧栏切换会话后组件正确加载新 ID；
- 移动端仍可通过顶部菜单打开导航。

如果现有 `ConversationPage` 依赖外层 `Container` 提供宽度和 padding，应在页面自身补充等价约束，不能把管理页 Container 恢复到查询工作区外层。

## 9. 主题与样式策略

- 不全局修改 `MuiCard`；
- 不全局把主色从蓝色改为黑色；
- 不全局修改所有 `MuiListItemButton` 选中态；
- 使用组件级 `sx`、局部 styled 组件或查询工作区专用 theme slot；
- 复用 MUI 组件和 `@mui/icons-material`，不要手写 SVG；
- 发送按钮可使用现有 MUI 图标，如 `ArrowUpwardRounded`；
- 若添加快捷键显示，使用 `<kbd>` 并提供可理解的按钮名称；
- 避免 CSS `100vh` 在移动浏览器地址栏变化时截断，优先考虑 `100dvh` 并保留回退。

## 10. 响应式与可访问性

### 10.1 响应式

- `md` 及以上：常驻查询工作区侧栏；
- `md` 以下：沿用 temporary Drawer；
- 760px 以下：欢迎区顶部排列，减少垂直居中留白；
- 600px 以下：示例问题和筛选面板单列；
- 320px 宽度不得横向滚动。

### 10.2 可访问性

- `textarea` 必须有可访问名称，不能只依赖 placeholder；
- 筛选按钮使用 `aria-expanded` 和 `aria-controls`；
- 会话列表使用语义化导航或列表结构；
- 当前会话使用 `aria-current="page"`；
- loading 使用可感知状态，不阻塞输入；
- 错误状态含重试操作；
- 图标按钮有 `aria-label`；
- 不仅依赖颜色表达当前项、禁用和筛选状态；
- 保持可见键盘焦点；
- 尊重 `prefers-reduced-motion`，不要加入必要性不明的入场动画。

## 11. 数据与一致性风险

### 11.1 Mock 数据状态

`listConversations()` 当前返回模块内可变数组。创建会话后应调用 `refreshConversations()`，使侧栏及时出现新会话。刷新浏览器后 Mock 恢复是当前已知边界，不在本任务解决。

### 11.2 重复请求

禁止 AppShell 和 SearchPage 各自调用 `listConversations()`。可以通过 Context、共享 hook 缓存或把加载职责完全交给 AppShell，但必须有一个明确状态所有者。

### 11.3 未提交用户改动

当前工作树至少包含：

- `frontend/src/components/AppShell.tsx` 中系统日志导航；
- `frontend/src/app/router.tsx` 中系统日志和审计日志真实页面路由；
- 认证、登录和日志页面的其他未提交文件。

实现 Agent 必须先运行 `git status --short` 和相关 `git diff`，只做增量修改，不得覆盖、回退或格式化无关改动。

## 12. 建议文件清单

建议新增：

```text
frontend/src/conversations/ConversationWorkspaceContext.tsx
frontend/src/components/query/QueryComposer.tsx
frontend/src/components/navigation/QueryWorkspaceSidebar.tsx
```

建议修改：

```text
frontend/src/components/AppShell.tsx
frontend/src/pages/SearchPage.tsx
frontend/src/pages/ConversationPage.tsx       # 仅在失去外层 Container 后需要补布局时
frontend/src/app/router.tsx                   # 仅用于挂 Provider 或嵌套路由时
```

不建议修改：

```text
frontend/src/app/theme.ts                     # 除非只新增不影响旧页面的专用 token
frontend/src/api/conversations.ts             # 除非补充无行为变化的类型/方法
frontend/src/pages/admin/*                    # 本任务不触碰
```

文件结构不是硬性要求。若现有架构有更小且清晰的实现，可以减少新增文件，但必须满足状态单一来源和页面隔离要求。

## 13. 实施步骤

1. 检查工作树和相关未提交差异；
2. 记录当前前端构建结果；
3. 提取会话列表共享状态；
4. 实现 `QueryComposer` 及其交互；
5. 实现查询工作区侧栏；
6. 让 `AppShell` 根据路由选择侧栏和主区容器；
7. 重构 `SearchPage`；
8. 检查 `ConversationPage` 在新容器下的布局；
9. 运行构建、测试和静态检查；
10. 使用浏览器检查桌面和移动布局；
11. 对照 HTML Demo 修正可见差异；
12. 报告修改、验证结果和未验证风险。

## 14. 测试设计

### 14.1 组件/交互

- 初始问题为空时发送按钮禁用；
- 输入非空后按钮启用；
- Ctrl/Cmd + Enter 仅在非空时提交；
- 展开/收起筛选面板正确更新 `aria-expanded`；
- 选择产品后版本可用；
- 清除产品同时清除版本；
- 已选筛选显示为 Chip，单项可移除；
- 点击示例问题只填入并聚焦，不自动提交；
- submitting 时不能重复提交；
- 提交成功跳转会话页并刷新侧栏；
- 会话加载失败不影响用户输入问题。

### 14.2 路由与权限

- `/search` 使用查询工作区侧栏；
- `/conversations/:id` 使用查询工作区侧栏；
- `/admin/system-logs` 仍可访问；
- `/admin/audit-logs` 仍可访问；
- 非管理员看不到管理员入口；
- `/documents` 等非查询页面仍使用原有容器；
- 移动端菜单可打开并跳转。

### 14.3 视觉检查

至少检查：

- 1920×1080；
- 1440×900；
- 1024×768；
- 390×844；
- 200% 浏览器缩放；
- 长会话标题；
- 0 条、5 条和大量会话；
- 筛选全部选中；
- 错误、加载和 submitting 状态。

### 14.4 建议命令

```powershell
cd D:\Projects\ae-knowledge-platform\frontend
npm run build
```

如果工程新增了 Vitest/RTL，则运行对应测试。当前 `package.json` 没有前端 test script，不能虚构测试通过。

## 15. 验收标准

| 编号 | 验收要求 |
|---|---|
| AC-SEARCH-001 | `/search` 首屏第一视觉焦点是居中的问题 Composer |
| AC-SEARCH-002 | 桌面最近会话位于侧栏，主内容区不再渲染会话 Card 列表 |
| AC-SEARCH-003 | 查询范围默认收起，选择后以可移除 Chip 显示 |
| AC-SEARCH-004 | 提交行为、筛选联动和 Ctrl/Cmd + Enter 保持正确 |
| AC-SEARCH-005 | 新建会话后侧栏及时更新且可进入该会话 |
| AC-SEARCH-006 | 管理、日志、文档等非查询页面视觉和路由不回归 |
| AC-SEARCH-007 | 390px 宽度无横向滚动，移动端 Drawer 可用 |
| AC-SEARCH-008 | 键盘可操作输入、筛选、示例问题、会话和发送按钮 |
| AC-SEARCH-009 | `npm run build` 通过 |
| AC-SEARCH-010 | 未覆盖或未验证项在交付说明中明确列出 |

## 16. 可直接交给实现 Agent 的完整提示词

```text
你正在维护项目：D:\Projects\ae-knowledge-platform

任务：把正式 React 前端的知识查询首页改造成 Codex 式工作区布局。请完整实现，不要只修改 CSS，也不要修改后端。

开始前必须阅读：
1. docs/详细设计/18_知识查询Codex式布局改造设计_V0.1.md
2. docs/prototypes/visual-directions/search-home-redesign-demo.html
3. frontend/src/components/AppShell.tsx
4. frontend/src/pages/SearchPage.tsx
5. frontend/src/pages/ConversationPage.tsx
6. frontend/src/app/router.tsx
7. frontend/src/app/theme.ts
8. frontend/src/api/conversations.ts
9. frontend/src/types/conversations.ts

工作方式：
- 先运行 git status --short，并查看上述相关文件的 git diff。
- 当前工作树包含用户未提交的认证、系统日志、审计日志和导航修改。必须保留这些修改，禁止回退、覆盖或格式化无关代码。
- 使用 rg 搜索现有相似组件和路由，不要猜测 API、类型或文件路径。
- 使用 apply_patch 进行手工修改。
- 保持改动聚焦，不做无关重构。

必须实现的结果：
1. `/search` 使用 Codex 式首页：中间是欢迎语、Composer、可选筛选和四个示例问题。
2. 桌面端最近会话进入左侧栏，主内容区不再显示全宽会话 Card。
3. `/search` 和 `/conversations/:id` 使用查询工作区侧栏；管理和文档页面继续使用现有布局或与现有视觉兼容的导航。
4. 查询范围默认收起；支持产品、版本、文档类型；产品变化时清除版本；已选条件显示为可删除 Chip。
5. 保留当前 handleSubmit 的业务顺序、Mock 行为、QueryFilters 字段、Ctrl/Cmd + Enter、重复提交保护和成功跳转。
6. 示例问题点击后只填入并聚焦，不自动提交。
7. 新建查询跳转或重置 `/search`，不刷新整个浏览器。
8. 会话列表有唯一状态所有者，禁止 AppShell 和 SearchPage 重复请求 listConversations()。优先使用轻量 Context 或共享 hook。
9. 新建会话后刷新侧栏列表。
10. 管理页面、`/admin/system-logs`、`/admin/audit-logs`、管理员鉴权和移动端 Drawer 不得回归。
11. 不全局修改 MUI Card/Button/ListItemButton 造成其他页面变化；查询工作区使用局部样式。
12. 兼容桌面、平板和 390px 手机宽度；不得横向滚动。
13. 保证可访问名称、aria-expanded、aria-current、键盘焦点和 loading/error 状态。

建议新增：
- frontend/src/conversations/ConversationWorkspaceContext.tsx
- frontend/src/components/query/QueryComposer.tsx
- frontend/src/components/navigation/QueryWorkspaceSidebar.tsx

建议修改：
- frontend/src/components/AppShell.tsx
- frontend/src/pages/SearchPage.tsx
- frontend/src/pages/ConversationPage.tsx（仅按新容器补布局）
- frontend/src/app/router.tsx（仅按 Provider/路由布局需要修改）

设计约束：
- 模仿 Codex 的布局逻辑，不复制其品牌资产。
- 中性浅灰侧栏、安静主画布、紧凑历史会话、唯一高权重 Composer。
- 不使用渐变、玻璃拟态、大阴影、装饰插画或大量卡片。
- 蓝色保留给链接、焦点和产品语义；发送按钮可以使用深色中性样式。
- 优先复用 MUI 和现有图标，不手写 SVG，不新增大型依赖。

验证要求：
- 运行 npm run build。
- 如果项目已有前端测试则运行相关测试；如果没有，不要声称测试通过。
- 检查 1920×1080、1440×900、1024×768、390×844。
- 检查输入为空、输入非空、筛选展开、筛选全选、会话 loading/empty/error、submitting、长标题。
- 浏览器验证后，对照 HTML Demo 检查侧栏密度、Composer 宽度、垂直节奏和移动端重排。

交付回复必须包含：
- 修改了哪些文件及原因；
- 执行的精确验证命令和结果；
- AC-SEARCH-001～010 的 PASS/FAIL/UNVERIFIED；
- 未验证项与剩余风险；
- 明确说明是否保留了用户已有的系统日志、审计日志和认证改动。

不要停止在分析或建议阶段；在不扩大任务范围的前提下完成实现并验证。
```

## 17. 交付检查清单

- [ ] 已检查并保留用户未提交改动；
- [ ] 查询工作区和管理工作区布局隔离；
- [ ] 最近会话只有一个状态所有者；
- [ ] SearchPage 不再显示历史 Card 列表；
- [ ] Composer、筛选和示例问题行为正确；
- [ ] 会话页在新 AppShell 下布局正常；
- [ ] 移动端 Drawer 和 390px 重排正常；
- [ ] 系统日志、审计日志路由和权限未回归；
- [ ] `npm run build` 通过；
- [ ] 未验证项和风险已报告。

