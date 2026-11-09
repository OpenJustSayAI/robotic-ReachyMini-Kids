# 许可证、来源与素材边界

## 本项目

Ducky 原创代码采用 MIT，Copyright (c) 2026 Ducky contributors；原始许可全文保存在 [licenses/Ducky-MIT.txt](licenses/Ducky-MIT.txt)。本仓库其他原创整合及网络代码采用根目录 MIT，Copyright (c) 2026 OpenJustSayAI。两份版权声明均须保留。
MIT 允许修改、使用、分发和商业使用；分发包含受许可代码的副本或实质部分时，要保留版权声明与许可全文。只附仓库链接不足以替代许可证。

## LinguaLive

参考项目：https://gitlab.com/edgeworks-public/lingualive
核对版本：d6d895dcdd24bae2113cd81d841fe482c0521b71。
Copyright (c) 2025 LinguaLive Contributors。
完整 MIT 文本保存在 [licenses/LinguaLive-MIT.txt](licenses/LinguaLive-MIT.txt)。

本阶段是独立标准 App，没有复制其实时聊天/英文老师业务实现；保留其作为方案来源的引用及许可，未来如移植代码，应继续保留原文件所需声明。既有 LinguaLive 工作区未改动。

## Reachy Mini

https://github.com/pollen-robotics/reachy_mini
SDK 与 App Assistant 验证版本：1.14.0，Apache License 2.0。
Copyright 2025 Pollen Robotics。
本 App 由其官方默认模板生成。main.py 与项目元数据已为 Ducky 修改，main.py 保留来源及修改说明。Apache 2.0 全文见 licenses/Reachy-Mini-Apache-2.0.txt。

软件包许可表达式为 MIT AND Apache-2.0，反映保留的模板来源；这不意味着把 SDK 或其他依赖重授权为 MIT。所有依赖保留各自许可证；若未来分发包含 SDK/GStreamer 等依赖的完整镜像，应另核对所包含组件的许可和通知。

## Ducky 原声与佩奇相关内容

源 ZIP 和音频由使用者提供。本项目没有得到这些素材的独立开源或再分发授权，也没有把它们声明为 MIT。原始音频作为单独的私有本地素材包导入。

用户提供的声音来源为 Muse TTS Aria，voice ID avocado_v2:MAI_01。这个 ID 只在 Muse 内有效；目前没有在本项目中接入或验证公开 API、免费配额、商业再分发权或声音复制权。Meta Model API 的条款不能直接当作 Muse 消费端 TTS 的授权证明。

公开视频或开源代码本身通常不受 MIT 的商业用途限制；但视频中播放的 TTS 音频、佩奇台词/形象/片段等有独立权利问题。保留引用不等于获得相关授权。公开素材前，核对生成时服务条款、账户/供应商授予的输出使用和分发权；无法确认时仅开源代码、导入工具及自有/获授权的示例素材。

本版界面的小鸭是新编写的 SVG，不包含佩奇图像、官方视频或音乐。原声库里与佩奇有关的音频仍属于上述独立素材范围。

参考：[MIT 原文](https://opensource.org/license/mit)、[Reachy Mini LICENSE](https://github.com/pollen-robotics/reachy_mini/blob/main/LICENSE)。此文件记录本次核对边界，不声称完成第三方素材授权审查。

## 网络组件与其他外部组件

网络中继原创代码使用 MIT；NekoBox、VPN 客户端、机器人固件和硬件均不在本仓库中打包。外部组件表及其许可边界见 [根目录第三方说明](../THIRD_PARTY_NOTICES.md)。
