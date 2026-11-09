# 私有素材包与 Ducky 声音

代码包和素材包分离。默认数据路径是运行用户的 `~/.local/share/ducky-reachy-mini`；设置 `DUCKY_ASSET_DIR` 可替换。数据目录下包含 `manifest.json` 和 `audio/*.mp3`。可在电脑完成导入再复制整个目录到 Wireless；设备运行时不需要 ffprobe。

导入器只读取 ZIP 数据和 JSON5 字面量，不执行来源 HTML/JavaScript。选择当前 `duck-export/assets/*.mp3`，加上 `space.html` 的 21 条内嵌音频，校验其与 tide-cbr-page/why-cbr-page 文件相同。忽略旧版本与未使用的历史音频。不使用 extractall。

## 清单

`schema_version: 1`；`clips` 为列表。每条：

- `id`：稳定 ID，用于快捷点播；`path`：相对素材根目录的 MP3 路径。
- `group`：morning/noon/night/peppa-s1e1/peppa-s1e2/peppa-mini-flying/tide/why/other。
- `language`：en/zh；`label`：按钮文字；`text`：完整来源台词或 null。
- `text_status`：source_provided/unverified；`text_source`：来源页面或 TSV。
- `source_zip_member`：原 ZIP 内路径；`sha256`：原始文件校验；`duration_seconds`、`sample_rate`、`channels`：ffprobe 测得。

源页面的单词标签不能替代完整发音文字，优先保留 TSV 中完整单词短句。无完整台词的22条音频仍可正常播放。

实际素材合计 2,696,005 字节（100 外部 +21 内嵌），100 en +21 zh。运行时逐次校验文件 SHA-256；校验失败会停止该次播放并显示错误。解码使用 SoundFile，重采样使用 scipy.signal.resample_poly，源 MP3 不修改。

## 用户提供的声音规格（并非 API 可用性承诺）

- 同声中英：Aria，美式女性声，温暖亲切。
- Muse voice ID：`avocado_v2:MAI_01`，不是豆包或 Azure 的公共声音 ID。
- 英文 `language=en`, `speed=92`；中文 `language=zh`，默认语速。
- 原页面中文音频的 CBR 64k/Xing 处理是播放兼容处理，不是换音色；本项目沿用当前页面版本。
- 当前版本没有合成或克隆声音。以后新增游戏台词，需使用自己有权使用的声音与素材来源，审核后导入；相同参数不等于获得再分发授权。

原有故事内容本次按素材原样保留，未进行科学内容改写或教育适龄性审校；后续课程编排时另审台词，不静默改动孩子熟悉的声音。
