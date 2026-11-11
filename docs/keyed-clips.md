# 把一段绿幕动作接进团子

播放器只认透明 PNG。生成的视频先离线抠掉绿幕、去掉音轨，再写进 `assets/animations/manifest.json`。运行时不生成视频。

已接入的两段（24 帧/秒，清单里每帧 42 毫秒，这是加载器能存的最接近 1/24 秒的整数）：

| 动作 | 源 | 帧 | 画面 | 一整圈 |
| --- | --- | --- | --- | --- |
| `groom` 舔爪洗脸 | `assets/animations/sources/groom.mp4` | 144 | 512×512 | 6048 ms |
| `nest-breath` 猫窝呼吸 | `assets/animations/sources/nest-breath.mp4` | 120 | 774×512 | 5040 ms |

源片大约 6.04 秒和 5.04 秒。首尾几乎是同一姿态，导入时丢掉最后一帧重复，避免循环时停一下，也不做会叠出两只猫的长交叉淡化。旧的插值舔爪序列还在 `frames/groom/` 和 `keyframes/groom/`，清单不再指向它们；抠像没通过检查时不会改清单。

## 再导入一段

依赖 ffmpeg、以及 `numpy`、`pillow`（和桌面一样的 PySide6，用来顺便记下眼睛位置）。

```bash
python scripts/import_keyed_clip.py \
  --video path/to/action.mp4 \
  --id wave \
  --label 招手 \
  --output wave-keyed \
  --write
```

猫窝这类不要拉长身体的画面加 `--body-extended`。

脚本会：

1. 只抽出视频流，不带音频。
2. 按绿通道高出红蓝的程度抠像，边缘把沾上的绿拉回。
3. 缩放到高 512、宽 512–1024，直通 alpha。
4. 检查四角透明、主体还在、不透明区域没有明显绿边。任何一帧失败就退出，并且不改清单。
5. `--write` 通过之后才写入 `frames/<output>/` 并更新清单。

走路和小跑不要走这条，它们的步幅和窗口移动绑在一起。
