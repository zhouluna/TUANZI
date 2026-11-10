# 团子网页宠物和 API

桌面宠物仍是 PySide6。网页和桌面共用这一套 FastAPI 接口：动作只能从已经存在的片段里挑，聊天由服务端转给 NVIDIA，密钥不出服务器。

## 本地运行

```bash
python -m pip install -r web/requirements.txt
python web/startup-app.sh
```

打开 <http://127.0.0.1:8000>。没设 `DATABASE_URL` 时用 `web/.data/tuanzi.db`（SQLite，不提交）。

桌面在配了地址之后才会连上来，不配就还是原来的本地行为：

```bash
TUANZI_API_URL=http://127.0.0.1:8000 TUANZI_ACCESS_PASSWORD=你的口令 python -m desktop_pet
```

检查网页接口：

```bash
python -m unittest discover -s web/tests -v
```

桌面原有检查不变：`python -m unittest discover -s tests -v`。

## 环境变量

| 变量 | 谁读 | 作用 |
| --- | --- | --- |
| `DATABASE_URL` | API | PostgreSQL。Uppcoder 会注入。本地不设就用 SQLite。 |
| `TUANZI_ACCESS_PASSWORD` | API、桌面 | 站点口令。没设口令时，接口**不会**去调用 NVIDIA。 |
| `NVIDIA_API_KEY` | 只在 API 进程 | 聊天和测速。不要写进仓库、不要交给浏览器。 |
| `NVIDIA_BASE_URL` | API | 默认 `https://integrate.api.nvidia.com/v1`。 |
| `TUANZI_MODELS_URL` | API | 可选，只用来看哪些 id 是对话模型。测速在本服务里做，不读那边的速度。默认指向公开目录，设空字符串就不用。 |
| `TUANZI_PROBE_LIMIT` | API | 每一轮测几个模型，1–6，默认 4。 |
| `TUANZI_DEV_OPEN` | API | 仅本机。设为 `1` 才允许在**没有口令**时调用 NVIDIA。不要在公网上开。 |
| `TUANZI_API_URL` | 桌面 | 例如 `http://127.0.0.1:8000`。不设则桌面完全离线。 |
| `PORT` | 启动脚本 | 默认 8000。 |

示例在 `web/.env.example`，里面没有真实密钥。

## 行为

- 口令通过 `POST /api/session` 放进 HttpOnly cookie，桌面用请求头 `X-Tuanzi-Password`。
- `POST /api/activity/next` 返回一个已有动作和一段 0.4–24 秒的间隔。有测速结果时，模型只被允许从这份名单里排 3 步；失败或没有密钥就用本地的不规则序列。
- `POST /api/chat` 用 SSE 往外推。模型 id 来自 NVIDIA 的模型列表（以及可选目录），按本服务测到的首 token 时间排序，失败就换下一个。没有密钥时明确说自己在本地，不编一个模型名字。
- 允许的结构化动作只有 `sleep`、`butterfly`、`groom`、`remind`。没有 shell，也不碰本机文件。
- 浏览器语音用 Web Speech，只在安全上下文（HTTPS，或本机）里启用。桌面这一版不接系统语音。
- iOS 用「添加到主屏幕」。`manifest.webmanifest` 是 `standalone`，页面只在自己的窗口里，不会浮到别的 App 上。

## 以后的两段试播视频

舔爪洗脸继续用动作 `groom`：换成直通 alpha 的 PNG（高 512，宽 512–1024，每帧 12–1000 毫秒）并改清单即可，加载器不用动。

猫窝呼吸预留 id `nest-breath`，一整圈约 4.8 秒。目录里现在是 `available: false`，没有占位视频。帧到位并写进 `assets/animations/manifest.json` 之后，网页和桌面菜单都会播它。

## 部署到 Uppcoder Spark

账号和 Spark 开通不在这次里做。仓库准备好了：

1. 在 Uppcoder 选 FastAPI，加上 PostgreSQL。它会提供 `DATABASE_URL`。
2. 连这个仓库、这个分支。启动命令用仓库根目录的 `startup-app.sh`（它会进入 `web/` 再执行 `uvicorn main:app`）。如果平台只认应用目录，把工作目录设成 `web`，用 `web/startup-app.sh`。
3. 设置 `TUANZI_ACCESS_PASSWORD` 和 `NVIDIA_API_KEY`。不要把密钥写进代码。
4. Spark 是 1 个常驻应用加 1 个数据库，内存和磁盘各 2 GB。动作图从仓库的 `assets/` 读，不要再复制一份。

依赖锁在 `web/requirements.lock.txt`。
