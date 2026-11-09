# Reachy Mini Mac / Android 共享代理

主项目的可选网络组件。在机器人上提供 `127.0.0.1:18080` HTTP 代理入口：健康 Mac 上游优先，当前 Wi-Fi 的安卓上游备用。Mac 休眠时手机可以独立提供外网代理，控制机器人仍可使用 Mac 或安卓客户端。

这是 HTTP(S) 转接，不是全机 VPN。机器人不安装 VPN、不保存节点密码；普通安卓热点也不会自动共享手机 VPN，需要 NekoBox 的 HTTP 入站允许局域网连接。默认关闭上游，必须自行配置。

## 使用

需要 Linux、Python 3.11+、NetworkManager (`nmcli`)、iproute2 (`ip`)；systemd 示例面向具有 `pollen` 用户的 Wireless 系统。

```sh
cd components/network-relay
cp config/config.example.json config.local.json
# 编辑自己的 SSID、手机 IP/MAC、批准网段及 HTTP 代理端口。
python3 relay.py --config config.local.json --check-config
```

配置校验不代表网络可达。先验证共享代理，再按 [安装与运维](docs/operations.md) 手动安装。本仓库没有自动接管 daemon 的安装器。

- 普通 Wi-Fi：只在批准的 RFC1918 IPv4 `/24` 或更小网段，按手机 MAC 重新发现 DHCP 地址。每个 SSID 的随机 MAC 可能不同。
- 手机热点：只有显式配置的热点 SSID 才采用当前私网网关，端口仍需填写实际 HTTP 共享端口。
- 仅回环监听、保留 TLS 校验；上游不可用时失败关闭，没有公网直连兜底，也不重放请求。
- 切换网络或上游会关闭过期连接；已有连接需要由客户端重连。
- `CAP_NET_RAW` 只用于有界 ARP 发现；MAC 是识别提示，不是加密身份认证。

## 测试与范围

```sh
python3 -m unittest discover -s tests -v
```

33 项测试使用模拟服务器/数据，不需要账号、真实 ARP 扫描或机器人。涵盖半关闭、失败切换、不重放、配置校验、SSID 绑定和异步竞态。

开发原型曾在一台 Wireless / daemon 1.14 / Debian / Python 3.13 验证手机独立代理、HF 登录、切换和地址重发现。通用公开版经过配置重构，原型结果不能替代公开配置在实际硬件和每个网络上的验收。办公室客户端隔离、手机热点、摄像头和整机断电恢复仍需现场确认。

## HF 登录与中国网络

本组件通过代理访问官方 `huggingface.co`，没有设置 `HF_ENDPOINT` 或改 hosts。[官方 FAQ](https://huggingface.co/docs/reachy_mini/main/en/troubleshooting) 中的镜像选项用于下载；[HF-Mirror](https://hf-mirror.com/) 自身说明不支持网页登录，不能替代 OAuth。`localhost` 指浏览器所在设备：从实际控制流程重新发起授权，不要跨设备复用过期回调 URL。

原创部分采用根目录 [MIT](../../LICENSE)。第三方软件、服务和素材的权利独立，见 [第三方说明](../../docs/THIRD_PARTY_NOTICES.md)。
