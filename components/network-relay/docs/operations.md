# 安装与运维

以下只在你自己的 Reachy Mini Wireless 执行，不在 Mac 执行。没有自动安装或 SSH 密码处理。先确保 SSH 可达并保留会话，需要 sudo，重启 daemon 会短暂断开控制软件。

## 上游与配置

Mac 代理启用局域网 HTTP 共享；安卓 NekoBox 开启“允许来自局域网的连接”和局域网绕过。`0.0.0.0` 是监听地址，不是端口；2080 等端口必须与实际设置一致。公司 Wi-Fi 客户端隔离可能阻断代理和控制。

在 `config.local.json` 填真实 SSID（不是 NetworkManager 配置名称）、手机在该 SSID 的 MAC、IP、HTTP 端口及批准的 `/24` 或更小网段。示例值是虚构的。Mac 默认禁用，启用后填写可解析的局域网主机名/IP，不要填节点公网地址或带凭据的 URL。

从机器人测试上游，例如替换下面的虚构地址：

```sh
curl --noproxy '' --proxy http://192.168.50.20:2080 --max-time 20 -I https://huggingface.co
```

手机能打开 HF 不证明机器人能使用共享入站，两者需要分别测试。HTTP 407 表示需要代理认证；本中继没有代理凭据注入功能。不要关闭 HTTPS 证书校验。

## 手动安装

在本组件目录执行。先确认系统有 `pollen` 用户和组，否则需调整 unit 及权限：

```sh
getent passwd pollen
getent group pollen
python3 relay.py --config config.local.json --check-config
```

先逐项检查下面四个目标，**任一目标存在就停止，备份并人工比较，不覆盖已有安装**：

```sh
sudo test ! -e /etc/reachy-network/config.json
sudo test ! -e /usr/local/lib/reachy-network/relay.py
sudo test ! -e /etc/systemd/system/reachy-network-proxy.service
sudo test ! -e /etc/systemd/system/reachy-mini-daemon.service.d/95-local-upstream.conf
```

逐项确认后安装中继，先不接管 daemon：

```sh
sudo install -d -m 0755 /usr/local/lib/reachy-network /etc/reachy-network
sudo install -m 0644 relay.py /usr/local/lib/reachy-network/relay.py
sudo install -o root -g pollen -m 0640 config.local.json /etc/reachy-network/config.json
sudo install -m 0644 systemd/reachy-network-proxy.service /etc/systemd/system/reachy-network-proxy.service
sudo systemctl daemon-reload
sudo systemctl enable --now reachy-network-proxy.service
sudo cat /run/reachy-network/status.json
curl --noproxy '' --proxy http://127.0.0.1:18080 --max-time 20 -I https://huggingface.co
```

只有请求成功后再安装 daemon drop-in；先私下备份现有 daemon 配置，不把代理凭据或日志提交 Git。保留旧 drop-in 供回滚使用：

```sh
sudo install -d -m 0755 /etc/systemd/system/reachy-mini-daemon.service.d
sudo install -m 0644 systemd/95-local-upstream.conf /etc/systemd/system/reachy-mini-daemon.service.d/95-local-upstream.conf
sudo systemctl daemon-reload
sudo systemctl restart reachy-mini-daemon
```

两处端口须同为 18080。检查是否有后排序的 drop-in 覆盖此配置。代理变量只影响遵守它们的进程；其他独立 App 不会自动继承 daemon 环境。示例绕过私网和 `.local`，实际库对 `NO_PROXY` 的支持仍需核验。

unit 限制外连到局域网、本机与发现地址，保留 `CAP_NET_RAW` 用于 ARP。不支持这些 systemd 保护的系统需单独核对限制是否生效。配置 root 可写、pollen 可读；本地状态文件可能含私网信息。

## 排障

```sh
systemctl status reachy-network-proxy.service reachy-mini-daemon.service
sudo journalctl -u reachy-network-proxy.service -n 60 --no-pager
sudo cat /run/reachy-network/status.json
```

配置热重载不会修改 daemon 环境。切网后确认 SSID 与批准网段匹配，不为连通扩大到整个公司地址段。手机换随机 MAC 时更新配置；发现失败会拒绝未知设备，不靠猜旧 IP 修复。

Mac 和安卓分别测试 `http://机器人IP:8000/api/daemon/status`，然后测试控制和媒体。VPN 的局域网绕过、Wi-Fi 客户端隔离和 WebRTC UDP 是独立路径；HF 可达不证明媒体可达。

## 手动回滚

只禁用本组件 drop-in，恢复之前的 daemon 环境；旧代理是否可达需自行确认：

```sh
sudo grep -q 'Managed by the Reachy Mac/Android upstream relay' /etc/systemd/system/reachy-mini-daemon.service.d/95-local-upstream.conf
# 仅当上条匹配本组件标记，且 .disabled 目标不存在时继续：
sudo test ! -e /etc/systemd/system/reachy-mini-daemon.service.d/95-local-upstream.conf.disabled
sudo mv /etc/systemd/system/reachy-mini-daemon.service.d/95-local-upstream.conf /etc/systemd/system/reachy-mini-daemon.service.d/95-local-upstream.conf.disabled
sudo systemctl daemon-reload
sudo systemctl restart reachy-mini-daemon
sudo systemctl disable --now reachy-network-proxy.service
```

这些是人工逐项核对的操作清单，不是可忽略检查结果整块执行的脚本。
