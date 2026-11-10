# 原地动作补帧

桌面上觉得“一卡一卡”的，主要是原地动作的帧太稀：撒娇、吃东西、招手、打呼噜、玩球、扑捉、舔爪洗脸和舔毛原来只有 8–16 张图，每张停 105–220 毫秒（大约 5–10 帧/秒）。走路和小跑已经是 16 毫秒一帧，而且步幅要和窗口位移对齐，这次没有再抽帧。

播放器仍然只解码 PNG。补帧在离线脚本里做完，运行时不生成视频，也不访问付费接口。

## 重新生成

```bash
python -m pip install -r requirements.txt -r scripts/requirements-interpolate.txt
python scripts/interpolate_actions.py --dry-run
python scripts/interpolate_actions.py
```

无界面环境加上 `QT_QPA_PLATFORM=offscreen`（脚本会在导入 Qt 之前默认设置它）。只要原来的关键帧还在，就可以只重做某一个动作：

```bash
python scripts/interpolate_actions.py --clips groom groom_fur
```

脚本读取 `assets/animations/keyframes/<动作>/`。这个目录不存在时，会按当时清单里的帧复制一份再改清单，避免对补出来的帧再补一次。原始清单（含当时未被播放器使用的 `source_bounds`）记在 `assets/animations/keyframes/original-entries.json`。

模型是 Practical-RIFE 4.9 的 ONNX（MIT），约 21 MB，缓存在 `~/.cache/tuanzi/rife49.onnx`，不提交进仓库。校验：

`76e4cef9ab42fa7dd4e8f6e4aba47462051e3faa969e4bca6479784fbab0ac6f`

地址：<https://huggingface.co/edgetools/rife/resolve/main/rife49.onnx>。也可以把文件放好后用 `--model` 指定。

每一对相邻关键帧都会各跑一次颜色和一次透明度：颜色按预乘 RGB 插值，透明度单独插值，再还原成直通 alpha。背景仍然是透明的。若某一帧被判定成双影（两只姿态叠在一起，或半透明区域接近交叉淡化），脚本会改用较近的那张关键帧，并在 `interpolation.json` 里记下原因。这次八个动作都没有触发这条退路。

每张图的停留时间取能整除原延迟、且落在 20–40 毫秒里最接近 30 毫秒的值。动作一整圈的时长因此保持不变。

## 改了哪些

| 动作 | 原来 | 现在 | 一整圈 |
| --- | --- | --- | --- |
| 舔爪洗脸 `groom` | 16 帧 × 180 ms（约 5.6 fps） | 96 帧 × 30 ms（约 33 fps） | 2880 ms |
| 舔毛 `groom_fur` | 8 帧 × 220 ms（约 4.5 fps） | 80 帧 × 22 ms（约 45 fps） | 1760 ms |
| 撒娇 `nuzzle` | 12 × 150 ms | 60 × 30 ms | 1800 ms |
| 吃东西 `eat` | 12 × 160 ms | 60 × 32 ms | 1920 ms |
| 招手 `wave` | 12 × 130 ms | 60 × 26 ms | 1560 ms |
| 打呼噜 `purr` | 12 × 180 ms | 72 × 30 ms | 2160 ms |
| 玩猫球 `ball` | 12 × 140 ms | 60 × 28 ms | 1680 ms |
| 伸爪扑捉 `pounce` | 12 × 105 ms | 36 × 35 ms | 1260 ms |

关键帧按原像素留在 `keyframes/<动作>/`，清单在这些位置直接引用它们。新帧只写在 `frames/<动作>/`。扑捉在菜单和蝴蝶流程里只播一遍，最后一张姿势会按原来的 105 ms 停住（同一张图占 3 个 35 ms 槽），不会再插回第一帧。其余动作会循环，首尾之间也补了帧。

数字的机器可读副本在 `assets/animations/interpolation.json`。

## 没改哪些

- **走路 `walk`**：64 帧 × 16 ms，`stride_pixels` 驱动窗口位移。已经够密，再插帧会改变步幅同步。
- **小跑 `run`**：48 帧 × 16 ms，同样和位移绑在一起。
- **猫窝 `bed`**：只有一张蜷身静帧。睡着时真正在动的是 `assets/sleep-v2/` 里四张睡姿的胸口形变（`desktop_pet/sleeping.py` 的 `BREATH_SECONDS = 4.8`），不是帧动画。把静帧插值不会变成呼吸。
- **sleep-v2** 的四仰八叉、埋头、侧躺、蜷身：仍是静图加局部形变。

## 画质

抽查了每段关键帧之间的中点：相对起点的像素差单调增加，半透明像素比例维持在大约 1.5%–3.0%，和原图毛边同一量级，角点仍然全透明。没有整段动作因为重影被整段放弃。

招手、扑捉、玩球这类肢体位移大的段落，轮廓会比原关键帧稍软一点。这是光流类补帧的残留，不是把两张图叠在一起。若以后某段出现明显双爪或双头，重跑时会被退回关键帧并写进 `rejected`。

播放器启动时不再逐帧重扫眼睛：清单里的 `eye_positions` 是用同一个 `locate_eyes` 烘进去的。缺了这块缓存时仍会现场识别，动作不会因此加载失败。

## 下一阶段：试播两条动作

这次没有生成「舔爪洗脸」或「猫窝呼吸」的成片。本机没有不依赖外部付费接口的可靠视频生成器，仓库里也不放占位视频。

播放器现在只认 PNG 序列（`PySide6-Essentials` 不带 Qt Multimedia）。下面的格式可以直接被现有 `load_clips` 播出来，不必再加一条视频解码路径。

共用约束（和 `desktop_pet/animations.py` 里的检查一致）：

- 直通 alpha 的 PNG，不要烘焙实心底色；画面四角保持透明。
- 高度正好 512，宽度在 512–1024。
- `duration` 是每帧毫秒数，整数，12–1000。帧数变多时把这个数减小，让一整圈时长别突然变快或变慢。
- 路径相对 `assets/animations/`，不能跳出这个目录。
- 可选 `eye_positions`：和 `frames` 等长，每一项最多两只眼 `[x, y, rx, ry]`。不写就会在启动时现算。

**舔爪洗脸。** 继续用动作 id `groom`、标签「舔爪洗脸」。可以替换 `keyframes/groom/` 里的关键帧后重跑脚本，也可以直接交一套已经够密的 PNG（每帧不超过 40 ms）写进清单。一整圈保持在 2.9 秒左右，现有的两圈梳理手感才不会变。作者侧如果是带 alpha 的视频，先离线拆成上述 PNG，再进清单。

**猫窝呼吸。** 不要把 sleep-v2 的静图插值后当成呼吸。预期是一段可循环的透明 PNG，一只猫待在窝里做一次完整起伏。和现有胸口形变对齐的话，一圈约 4.8 秒；若按 40 ms 一帧，大约 120 帧，也可以更短，交给播放器循环。建议单独的 id `nest-breath`、标签「猫窝呼吸」，例如：

```json
{
  "id": "nest-breath",
  "label": "猫窝呼吸",
  "duration": 40,
  "frames": ["frames/nest-breath/000.png"]
}
```

这次没有把这条写进清单：文件不存在时打包自检会失败，而且小睡目前走的是睡姿网格，不是 `bed` 那张静帧。网页目录会列出 `nest-breath`，`available` 为 false，一整圈按 4.8 秒记。帧放进来并写进 `manifest.json` 之后，桌面菜单和网页都会把它当成普通动作播放，不用再改加载器。`groom` 也一样：换成同一规格的直通 alpha PNG（高 512，宽 512–1024，每帧 12–1000 毫秒）并更新清单即可。
