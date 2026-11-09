---
title: Ducky 原声小屋
emoji: 🐥
colorFrom: yellow
colorTo: green
sdk: static
pinned: false
short_description: Ducky original-voice local player for Reachy Mini Wireless
tags:
 - reachy_mini
 - reachy_mini_python_app
---

# robotic-ReachyMini-Kids · Ducky 原声小屋

“评估 LinguaLive 英语启蒙与 Reachy Mini”的实验代码主仓库。Ducky 原声小屋是当前主应用；Mac / 安卓共享代理是可选的独立网络组件，不是应用运行的前提。

| 目录 | 内容 |
|---|---|
| `ducky_reachy_mini/` | 标准 Reachy Mini App、本地素材导入、播放与家长控制页 |
| `tests/` | App 的 32 项自动化测试；使用合成测试数据，不含真实素材 |
| [components/network-relay/](components/network-relay/README.md) | 33 项测试的独立网络代理；Mac 优先、安卓备用、显式 Wi-Fi 配置 |
| [docs/](docs/THIRD_PARTY_NOTICES.md) | 素材格式、许可、验证及运维说明 |

**开源许可：** 本项目有权授权的原创代码按 MIT 开源，欢迎 fork、修改和再分发（包括商业使用），请保留版权和许可全文。Ducky 与 OpenJustSayAI 的版权声明分别保留；官方模板保留 Apache-2.0。软件包许可表达式为 `MIT AND Apache-2.0`。素材不随代码授权或发布，详见 [第三方说明](docs/THIRD_PARTY_NOTICES.md) 与 [授权范围](docs/rights-and-scope.md)。

本次合并保留原 Ducky 功能；通用代理不自动安装，不改 Wi-Fi、账号或服务配置。后续完整游戏的计划不能视为已实现功能。

给 3 岁、中文母语、英语零基础小朋友的 Reachy Mini Wireless 陪伴 App。
当前版本完成 **原声素材整理 + 家长点播**：跳泥坑快捷台词、早午晚英语、潮汐与“为什么”故事。使用已有 Ducky MP3，不调用 TTS，不需要 API Key；安装依赖后播放可离线使用。

完整跳泥坑游戏、语音识别和机器人动作属于下一阶段，本版本没有启用。

## 电脑本地试听

需要 Python 3.11+（本次验证 3.12）、uv，以及导入时需要的 ffprobe（随 FFmpeg 安装）。

```bash
uv venv --python 3.12
uv pip install --python .venv/bin/python -e '.[preview,dev]'
.venv/bin/ducky-import /path/to/duck-source-package.zip --output "$HOME/.local/share/ducky-reachy-mini"
.venv/bin/ducky-preview
```

浏览器打开 <http://127.0.0.1:8042>，声音从这台电脑默认扬声器播放。终端 Ctrl+C 关闭服务。
希望关闭终端后继续使用，可按 [macOS 后台运行说明](docs/LOCAL_SERVICE.md) 启动。
导入目录必须不存在；再次整理请指定新目录，核验后再切换，避免覆盖已有原声。

素材目录可以用 `DUCKY_ASSET_DIR` 环境变量或试听命令 `--assets /path/to/bundle` 指定。
默认监听本机；需要手机控制电脑试听时，可在可信家庭局域网显式用 `--host 0.0.0.0`，打开电脑局域网地址的 8042 端口。控制页无登录功能，不应暴露到公网。

## 播放规则

- 点播会替换当前声音，始终只有一个播放器；不会自动开始或自动续播。
- 暂停立即停止输出；“继续本句”从当前音频开头再播，避免设备缓存被清空后吞掉音节。
- “再听一次”重播当前句；“停止”停止输出并归零，保留当前选择方便重播。
- 默认软件音量 35%，滑块只改本 App 音量，不改系统音量。
- 不使用摄像头，不读取、处理或保存麦克风音频，不发出机器人运动指令。Wireless SDK 共用录放音管线，播放时可能启用麦克风设备；本 App 不消费这些输入数据。电脑试听仅创建输出流。

## Reachy Mini Wireless

标准入口为 `ducky_reachy_mini.main:DuckyReachyMini`，继承官方 `ReachyMiniApp`。由 SDK 管理连接与停止事件，采用 `gstreamer_no_video`。使用官方 App Assistant 1.14.0 生成结构。

本次没有安装到真实机器人。第一轮真机调试应在 **Wireless 本机** 的独立 Python 环境安装本项目、准备兼容的官方 SDK/GStreamer 系统依赖，并把私有素材目录复制到该运行用户的 `~/.local/share/ducky-reachy-mini`（或设置环境变量）。守护进程正常运行后，可在该环境运行：

```bash
python -m ducky_reachy_mini.main
```

打开 `http://机器人局域网地址:8042`。电脑直接运行此命令不能替代 Wireless 本机测试；电脑试听请使用 `ducky-preview`。
之后接入官方应用管理器时，采用当前机器人固件支持的安装流程；当前 SDK 的 API 安装入口面向 Hugging Face Space，本地 pip 安装不等同于已经出现在 Dashboard 应用列表。本仓库的 GitHub 发布不等于已发布 Hugging Face Space 或已安装到机器人；这些步骤需要单独执行。

待真机验证：固件与 SDK 兼容、音频系统依赖、实际响度、短音频结尾、重复播放稳定性、从 Dashboard 停止后的资源释放。播放尾部保留 200 ms 软件缓冲等待，不能替代扬声器实际试听。

官方参考：[SDK 文档](https://github.com/pollen-robotics/reachy_mini/tree/main/docs/SDK)、[Python App 创建](https://github.com/pollen-robotics/reachy_mini/blob/main/skills/create-app.md)。

## 素材、声音与开源

导入器读取导出包当前页面使用的 **121 条**原始 MP3：100 英文、21 中文（12 潮汐、9 为什么）。不重新合成、不重编码 MP3；播放时仅解码、混合为单声道并适配设备采样率。
每条记录有来源、SHA-256、语言、时长和源台词；22 条没有完整源台词，保留标签并标记 `unverified`，不代表音频缺失。`source_provided` 表示导出包提供的文字，并非已经人工听辨核验。

本项目的新代码采用 MIT；官方模板保留 Apache 2.0 来源，LinguaLive MIT 版权和许可全文另存。私有音频、原始 ZIP、导出页面和清单不加入 Git，也不打进公共 wheel/sdist。

详见 [第三方许可与公开视频](docs/THIRD_PARTY_NOTICES.md)、[素材格式与声音规格](docs/ASSETS.md)。

## 开发验证

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check ducky_reachy_mini tests
.venv/bin/reachy-mini-app-assistant check .
.venv/bin/python -m build
```

验证记录见 [第一阶段验证](docs/VALIDATION.md)。
