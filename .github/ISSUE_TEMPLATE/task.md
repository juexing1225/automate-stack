---
name: 协作工单
about: 一张可独立交付、可独立验收的工作单
title: "[任务] "
labels: ""
assignees: ""
---

<!--
人确认后，把需求含义、范围、验收项定下来，再加上 status:ready 标签。
智能体可以细化实现，但不能改这里的需求含义；有疑问打 blocked:needs-design。
-->

## 目标

（要解决的用户问题 / 交付结果，一句话说清。）

## 范围

- 包含：
- 不包含：

## 依赖

无

<!-- 有依赖就写 Issue 编号，例如：#12, #13。被依赖的 Issue 必须已关闭才能领取。 -->

## 档位与派单偏好

- 档位：`tier:basic`（基础实现，@free 0 分钟抢跑）/ `tier:standard`（默认）/ `tier:hard`（高难方案与接口骨架，仅 @elite）
- 派单偏好（可选）：指定成员 `优先：qianwen` / 家族 `优先：qwen` / 算力池 `仅限：@elite`

<!-- 由人在打 status:ready 时按需添加 tier:* 标签；本小节可选，缺省按 routing.default_tier。 -->

## 输入

（设计文档、接口、测试数据、相关 PR；需要固定版本时写完整 commit SHA。）

## 验收项

- A1：
- A2：

<!-- 每条都要能被独立检查；验收报告按 A1/A2 逐项给证据。 -->

## 交付位置

（分支由 collab claim 自动创建为 work/issue-<N>；PR 用 Refs #<N>，不要用 Closes。）

## 备注

（已知风险、需要人拍板的边界、参考实现。）
