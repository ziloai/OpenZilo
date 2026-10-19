# 维护文档

--8<-- "docs/_includes/devices.zh-CN.md"

文档在本仓库的 Markdown 文件中维护，使用 Zensical 自带的 modern 主题，不添加自定义 CSS。`docs/`、`wiki/` 和项目说明一起生成网站，不需要手动维护另一套内容。

## 本地预览

```bash
uv sync --locked --group docs
uv run --group docs python tools/build_docs.py
uv run --group docs python tools/check_docs.py
uv run python -m http.server 8000 --directory build/docs/html
```

在浏览器打开 `http://localhost:8000/`。构建同时生成中文和英文版本，并将警告视为错误。修改 Markdown 后重新构建并刷新浏览器。输出位于 `build/docs/html/`，不提交生成的 HTML。

## 添加和修改页面

修改现有 `.md` 即可。新增页面时，在 `tools/build_docs.py` 的 `PAGES` 注册中文、英文源文件与固定站点路径，并加入 `navigation()` 的相应分组和首页链接。构建会检查是否有遗漏的 Markdown 页面。

面向用户的页面需同时提供中文和英文源文件；英文站不使用中文正文代替翻译。构建会检查英文页面是否残留中文，并核对开发手册两种语言的章节层级、表格数量和代码块类型。

`zensical.toml` 保存共享主题和 Markdown 扩展配置。构建脚本分别生成 `/zh-CN/` 和 `/en/`，使用 Zensical 自带的语言菜单切换到同一篇文章。两种语言各有导航和搜索，不依赖多语言插件。

## 文档组织

首页面向 SDK 使用者，先引导安装与快速开始，再按功能查找文章。设备操作说明与协议资料放在后面。

- `sdk-quickstart.*.md` 只保留第一个完整连接示例。
- `sdk-<功能>.*.md` 集中维护该功能的调用顺序、接口说明、示例和限制。
- `python-sdk.*.md` 是 API 索引，`sdk-data-types.*.md` 维护返回字段，`sdk-errors.*.md` 维护异常说明。
- 安装、CLI、固件差异和设备操作分别维护，避免重新塞回一篇长手册。

`docs/sdk-section-redirects.json` 保留拆分前的站点章节链接。移动旧章节时更新映射；构建后检查所有目标是否存在。

## 设备提示

每篇 SDK 文档的标题下引用 `docs/_includes/devices.zh-CN.md`，英文文档引用 `devices.en.md`，统一显示“本文档适用于 OpenZilo Q”。每页只显示一次，功能提示框中不再重复添加。

## 功能版本提示

直接使用主题自带的提示框。以下版本号只演示写法，不表示真实接口的版本历史：

```markdown
!!! tip "自 SDK v0.6.0 起提供"

    说明功能的用途和使用方法。

!!! warning "自 SDK v0.8.0 起弃用"

    请改用 `new_method()`，计划在 SDK v1.0.0 中移除。

!!! danger "自 SDK v1.0.0 起移除"

    请改用 `new_method()`，并链接到迁移说明。
```

版本提示紧接功能标题。弃用表示接口仍可使用；只有实际删除接口后才标记移除。计划移除时明确写“计划”，日期或版本尚未确定时不填写。SDK 版本与固件要求分别说明，不从 Git 提交时间推算功能的首次支持版本。

多个页面共用的要求，在 `docs/_includes/features.zh-CN.md` 和 `features.en.md` 中维护。用 PyMdown Snippets 引用段落：

```markdown
;--8<-- "docs/_includes/features.zh-CN.md:recording-control"
```

共享文件用 HTML 注释划分段落，名称在两种语言中保持一致：

```markdown
<!-- ;--8<-- [start:recording-control] -->
!!! note "远程录音要求"

    此用法需要固件 **V2.001.0002.0001 或更新版本**。
<!-- ;--8<-- [end:recording-control] -->
```

本页示例源码中剪刀标记前的分号用于转义，实际引用时去掉分号。缺失引用文件或段落会使构建失败。具体用法前写“此用法需要固件 V2.001.0002.0001 或更新版本”。已经存在但行为改变的功能，分别说明 V2.001.0002.0000 与 V2.001.0002.0001 的行为。SDK 首次提供版本另行标注。中英文页面的型号、版本号和参数范围应保持一致。

## 文档版本

`docs/release.toml` 指定文档目标版本与状态，不修改 SDK 包版本。当前目标为 v0.6.1，`status = "upcoming"` 表示预览文档，页面会注明尚未发布。准备正式发行时，在同一次提交中更新 SDK 包版本，并将状态改为 `released`。

共享功能提示写“计划于 SDK v0.6.1 提供”；正式构建时自动显示“自 SDK v0.6.1 起提供”。这个转换只针对当前目标版本，其他功能的历史版本保持原样。

尚未配置历史版本菜单。历史手册可以从对应 Git tag 构建并部署至独立目录，固件要求仍由各功能页分别说明。

## GitHub Pages

工作流 `.github/workflows/docs.yml` 对提交和 PR 构建两种语言并检查站内链接；仅在默认分支构建成功或手动运行默认分支工作流时部署。

仓库管理员首次需要在 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。本地预览不需要修改这项设置。

站点使用相对链接，兼容 GitHub Pages 的 `/OpenZilo/` 项目路径与自定义域名。部署包括两种语言的搜索索引和 `.nojekyll`。切换生成器时会清理旧输出，避免旧页面混入发行内容。

Pages 仅部署 `build/docs/html/`。文档中使用占位设备地址，不放入私人录音、固件包或密钥。
