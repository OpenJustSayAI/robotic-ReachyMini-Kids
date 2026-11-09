# 贡献

欢迎 fork、修改和提交改进。提交前请确认贡献的原创内容可以按 MIT 发布；第三方材料必须明确注明来源和许可，不能仅删除原版权头再标为 MIT。

- 不提交真实 SSID、MAC、账号、IP 清单、密码、token、儿童录音/影像或未获许可的素材。
- 保持回环监听、TLS 验证、无公网直连兜底、有界发现与网络代次校验；行为改动附回归测试。
- App 运行 `python -m pytest -q` 与 `ruff check ducky_reachy_mini tests`；网络组件运行 `python3 -m unittest discover -s components/network-relay/tests -v`。
- 保留 Ducky 的 MIT 版权和 Reachy 模板的 Apache-2.0 许可，不将第三方代码统一改署为本项目原创。
- 说明哪些测试是模拟、哪些是真机实测；不把 CI 通过表述成儿童产品或所有网络的认证。

有意提交的原创贡献按本仓库 MIT 许可提供；如果你无权按该许可提供某项内容，请勿提交，先与维护者讨论可接受的独立授权方式。
