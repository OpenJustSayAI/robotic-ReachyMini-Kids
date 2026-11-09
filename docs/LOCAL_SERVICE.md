# macOS 本地试听后台服务

2026-11-09 修复：原临时开发进程退出，导致8042端口无人监听、浏览器连接被拒绝。改用macOS launchd在当前登录会话中托管独立进程；没有设置开机或登录自启。注销/重启电脑后需要重新启动。

在项目根目录启动（已安装本项目 .venv 和默认私有素材包）：

```bash
mkdir -p "$HOME/Library/Logs/Ducky"
launchctl submit -l local.ducky.preview \
  -o "$HOME/Library/Logs/Ducky/preview.log" \
  -e "$HOME/Library/Logs/Ducky/preview-error.log" \
  -- "$PWD/.venv/bin/ducky-preview" \
  --assets "$HOME/.local/share/ducky-reachy-mini" \
  --host 127.0.0.1 --port 8042
```

打开 http://127.0.0.1:8042/ 。若旧页面还显示连接失败，重新打开此地址。

查看后台任务：

```bash
launchctl list local.ducky.preview
```

停止（或重启前先停止，再执行上述启动命令）：

```bash
launchctl remove local.ducky.preview
```

不要同时启动前台试听实例，否则8042端口冲突。日志位于 ~/Library/Logs/Ducky/。此方式仅监听本机回环地址，不暴露到局域网或公网。

修复验证：首页HTTP200，状态ready=true且无错误，素材库121条；新进程父进程为launchd（PPID1），启动命令退出后仍能访问。浏览器已显示“Ducky准备好了”和完整素材库。本次只更改运行方式与说明，未改播放代码或原声素材。
