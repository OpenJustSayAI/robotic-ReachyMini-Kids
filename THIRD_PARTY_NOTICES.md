# Third-party notices / 第三方说明

本次发布包括 Ducky、官方模板派生入口、素材导入工具和网络组件。Ducky、LinguaLive、Reachy 模板的来源及保留许可见 [详细说明](docs/THIRD_PARTY_NOTICES.md)。本次不打包第三方 SDK、应用二进制、硬件设计、模型或媒体。下表记录外部兼容组件与参考资料，不把它们重新许可为 MIT。以下许可信息于 2026-11-09 核对；实际使用或再分发仍须检查所用版本及文件级声明。

| 项目/资产 | 本仓库关系 | 上游许可/权利边界 |
|---|---|---|
| [Reachy Mini SDK](https://github.com/pollen-robotics/reachy_mini) | Ducky 的外部依赖；App 入口由官方模板修改，未打包 SDK 本体 | 软件根 [LICENSE](https://github.com/pollen-robotics/reachy_mini/blob/main/LICENSE) 为 Apache-2.0；不替代文件级通知 |
| Reachy 硬件、CAD/STL/URDF、可视化模型 | 未包含 | 上游 [README](https://github.com/pollen-robotics/reachy_mini#license) 将硬件设计单独描述为 Creative Commons BY-SA-NC，未在该段指定版本；不能按 SDK 的软件许可或本项目 MIT 推定硬件/模型可商业使用 |
| [Reachy Mini mobile app](https://github.com/pollen-robotics/reachy_mini_mobile_app) | 外部控制客户端，未包含 | 上游 [LICENSE](https://github.com/pollen-robotics/reachy_mini_mobile_app/blob/main/LICENSE) 为 Apache-2.0 |
| [Reachy Mini Control desktop app](https://github.com/pollen-robotics/reachy-mini-desktop-app) / 机器人系统镜像 | 外部安装软件，未包含 | 必须独立核对相应版本和发行包；不因 SDK 是 Apache-2.0 就推定桌面应用、固件及所有资源同样授权 |
| [NekoBox for Android](https://github.com/MatsuriDayo/NekoBoxForAndroid) | 可选的外部 HTTP 代理，通过网络协议连接 | 上游 [LICENSE](https://github.com/MatsuriDayo/NekoBoxForAndroid/blob/main/LICENSE) 声明 GPL-3.0-or-later；本仓库不分发、嵌入或修改其源代码/二进制 |
| Python | 网络组件仅用标准库；Ducky 依赖另在 pyproject.toml 声明，各自保留许可 | Python 自身及其组件保持其原有许可，见 [Python license](https://docs.python.org/3/license.html)；本项目不把 Python 重新许可为 MIT |
| Hugging Face / OpenAI 等在线服务 | 用户自行申请的外部服务 | 服务条款、账号、API key、配额、模型和数据集许可独立于本项目 MIT；没有凭据或服务使用权随代码转让 |
| 产品名称、商标、Logo、角色、肖像、音色及作品 | 名称仅作兼容性说明，其他资产未包含 | 第三方权利保留；MIT 不构成本项目代第三方授予这些资产使用权的声明 |

原创网络转接代码依据公开网络协议和 API 编写，没有将上游 SDK、NekoBox 或第三方界面源码复制进此仓库。如果后续加入第三方文件，必须保留其版权、许可和必要 NOTICE，更新本表，并重新评估具体组合的许可义务。不能用根目录 MIT 覆盖不属于贡献者的代码。

参考：[Reachy Mini FAQ](https://huggingface.co/docs/reachy_mini/main/en/troubleshooting)、[Hugging Face OAuth](https://huggingface.co/docs/hub/oauth)、[NekoBox 配置说明](https://matsuridayo.github.io/nb4a-configuration/)。引用链接不是官方认可或商标授权。

佩奇相关媒体和 Muse Aria 生成音频未包含，MIT 不授予这些内容的再分发、商业使用或声音复制权。见 [具体排除项](docs/rights-and-scope.md)。源码包不附带依赖二进制，若分发完整镜像须另行检查全部依赖的许可通知。
