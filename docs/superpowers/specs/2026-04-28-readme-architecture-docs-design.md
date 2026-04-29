# README 重写与运行框架总结设计

- 日期：2026-04-28
- 主题：重写项目 README，并新增 `docs/architecture.md` 用于总结当前运行框架
- 状态：已确认设计，待用户审阅书面 spec

## 1. 背景

当前 `README.md` 已经包含了大量有效信息，但它把以下几类内容混合在了一起：

1. 项目用途说明
2. 日常运行方式
3. 配置字段说明
4. case-ingest 参数说明
5. case-ingest 内部处理流程
6. 上传与断点续传策略

这导致 README 同时承担“入口文档”“使用手册”“实现说明”“维护者笔记”四种角色。对第一次接触项目的人来说，信息量偏大；对后续维护者来说，真正的运行框架信息也不够集中。

## 2. 目标与非目标

### 2.1 目标

1. 将 `README.md` 重写为偏“使用入口”的文档。
2. 将当前系统运行框架和实现结构总结到 `docs/architecture.md`。
3. 明确区分“怎么使用”和“当前怎么实现”。
4. 让日常使用者能快速找到运行入口、配置入口、输出位置。
5. 让开发维护者能快速理解两条主流程、CLI 分流、关键模块职责与实现边界。

### 2.2 非目标

1. 不在这次改写中新增新的功能说明体系。
2. 不把所有现有专题文档合并或删减。
3. 不把每个参数字段都扩展成完整字典式参考手册。
4. 不重构代码，只调整文档结构与内容表达。

## 3. 推荐方案

最终采用：

**README 偏使用入口，`docs/architecture.md` 偏运行框架与实现结构。**

推荐原因：

- 符合大多数项目的阅读顺序：先看 README，后看架构文档。
- 避免 README 继续膨胀成过长的混合型文档。
- 将“当前运行框架”作为稳定结构文档沉淀，后续更易维护。

## 4. 文档边界设计

### 4.1 README 的职责

README 应主要回答：

- 这个项目是什么
- 它包含哪两条主流程
- 运行前需要准备什么
- 第一次运行该用哪条命令或哪个 bat
- 关键配置文件在哪里
- 输出会生成到哪里
- 深入实现说明应去哪里看

README 应偏“入口文档”，目标是让新接手的人在短时间内完成基本理解与首次运行。

### 4.2 `docs/architecture.md` 的职责

`docs/architecture.md` 应主要回答：

- 当前系统由哪些模块组成
- 视频打标流程的数据流如何串联
- case-ingest 流程的数据流如何串联
- CLI 如何在两条流程之间分发
- 关键代码文件分别负责什么
- config / bat / 运行目录之间的关系
- 当前实现边界与已知限制是什么

该文档应偏“维护者地图”，目标是帮助后续改代码的人先建立系统级认知。

## 5. README 建议章节结构

建议 README 包含以下章节：

1. **项目简介**
   - 一句话说明项目用途
   - 点出两条主流程：视频打标、case-ingest

2. **项目能力概览**
   - 视频打标流程做什么
   - case-ingest 流程做什么

3. **环境要求**
   - Windows
   - Python 3.8+
   - `ffmpeg.exe`
   - `adb.exe`（case-ingest 需要）
   - 网络/共享目录要求（按需简述）

4. **快速开始**
   - 视频打标最短运行命令
   - case-ingest 推荐运行方式（新的 `run_case_ingest.bat` / config 模式）

5. **关键配置文件**
   - `video_tagging_assistant/default_config.json`
   - `configs/case_ingest.json`

6. **输出位置**
   - review 文件
   - intermediate JSON
   - compressed 输出
   - case-ingest 目标目录概念

7. **延伸阅读**
   - 指向 `docs/architecture.md`
   - 指向已有 case-ingest 使用说明文档（如保留）

README 中不再保留大量内部流程细节、参数逐条展开、断点续传实现细节和上传策略细节。

## 6. `docs/architecture.md` 建议章节结构

建议该文档包含以下章节：

1. **系统概览**
   - 项目包含两条主流程
   - 共享入口为 `video_tagging_assistant/cli.py`

2. **运行入口与分流**
   - 默认视频打标模式
   - `case-ingest` 子命令模式
   - config 与 bat 的关系

3. **视频打标流程架构**
   - scanner
   - compressor
   - context_builder
   - provider 层
   - review_exporter
   - orchestrator
   - 数据从输入目录到 review 输出的流向

4. **case-ingest 流程架构**
   - bat_parser
   - case_ingest_models
   - pull_worker
   - copy_worker
   - upload_worker
   - case_ingest_orchestrator
   - config 驱动入口与 bat 驱动数据来源的关系

5. **关键文件职责表**
   - 用简明列表说明关键文件的单一职责

6. **配置与运行时关系**
   - 视频打标 config
   - case-ingest config
   - 路径解析规则
   - bat 中声明路径与最终本地/服务器目录的关系

7. **当前实现边界与限制**
   - README 不放的那部分核心限制，应放在这里
   - 例如 case-ingest 当前上传跳过策略、断点续传方式、非目标等

## 7. 内容取舍原则

这次改写应遵守以下原则：

1. **README 只保留首次上手必要信息。**
2. **实现细节集中到 `docs/architecture.md`。**
3. **已有信息优先重组，不凭空扩写无代码依据的内容。**
4. **避免参数百科式写法，优先讲入口、结构、关系。**
5. **链接已有专题文档，而不是重复抄写所有内容。**

## 8. 文件修改范围

### 修改

- `README.md` — 重写为偏使用入口的文档

### 新增

- `docs/architecture.md` — 总结当前运行框架与实现结构

### 参考但不一定修改

- `docs/case-ingest-usage.md`
- `video_tagging_assistant/cli.py`
- `video_tagging_assistant/orchestrator.py`
- `video_tagging_assistant/case_ingest_orchestrator.py`
- `video_tagging_assistant/config.py`
- `video_tagging_assistant/bat_parser.py`

## 9. 验证方式

文档改写完成后，至少应检查：

1. README 是否能让新读者快速找到运行入口。
2. `docs/architecture.md` 是否清楚区分两条流程及其模块职责。
3. README 与 architecture 文档之间是否存在明显重复或矛盾。
4. 文档中的命令、文件名、路径名是否与当前代码一致。

## 10. 结论

本次改写应聚焦于：

**把 README 变成真正的使用入口文档，并把当前运行框架稳定沉淀到 `docs/architecture.md`。**

这样既能改善日常使用体验，也能降低后续维护者建立系统认知的成本。
