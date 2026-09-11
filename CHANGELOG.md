# 更新日志 / Changelog

这里记录仓库每次实际提交的主要变化。以后每次更新功能、规则、文档或视觉资源时，都在本文件顶部追加一条记录；完整的技术差异仍以对应的 Git commit 为准。

## 2026-09-11

- `53b9937` — 恢复 README 徽章的灰阶样式。
- `6d374bb` — 将示例文件中的仓库链接更新为 `medterm-to-anki`。
- `9c9225a` — 同步仓库名称与 README 中的仓库 URL，并调整徽章样式。
- `9b50f5c` — 为 README 徽章增加彩色版本（随后在 `53b9937` 中恢复为灰阶）。
- `ed0efc6` — 刷新 README 横幅图片缓存版本，确保新标题立即显示。
- `0dfb7bc` — 将横幅标题更新为 `MedTerm to Anki`。
- `904297a` — 删除旧横幅文件名。
- `8a8b548` — 添加 `medterm-to-anki` 新横幅资源。
- `c8171f8` — 替换示例 spec 中的旧名称。
- `56ef86d` — 替换 README 中的旧 skill 名称。
- `16f2015` — 同步 `agents/openai.yaml` 中的 skill 名称。
- `1ccdf86` — 添加 Cleveland Clinic 图片搜索辅助脚本，并支持并行搜索。
- `d4b0e59` — 更新 skill 工作流：医学术语卡片、Cleveland Clinic 图片优先、缓存与失败重试策略。
- `9f463aa` — 更新牌组构建器：持久化音频/图片缓存、Cleveland Clinic 图片规则、搜索失败不判定为无图。

## 2026-09-03

- `40dea18` — 更新 README 内容。
- `c13ba0e` — 更新 README 内容。
- `85d7f6f` — 更新旧横幅 SVG。
- `b64033c` — 更新 Anki 词汇横幅 SVG。
- `813d023` — 更新 `MedVocab-Creator` 横幅 SVG。
- `01656a5` — 将旧 Anki Vocabulary 横幅替换为 `MedVocab-Creator`。

## 2026-09-02

- `fabcbc1` — 更新 README 卡片预览中的 anatomy 示例。
- `45f3cd9` — 使用 anatomy 示例更新 README 预览。
- `0c6db76` — 修正 README 横幅中的 anatomy 示例。
- `5f70a82` — 在 README 横幅中使用 anatomy 示例。
- `84d0ce5` — 同步 skill 名称与横幅文字。
- `e94f0b5` — 将 skill 重命名为 `anki-vocab-forge`。
- `5e453cf` — 继续同步 `anki-vocab-forge` 名称。
- `0eb165c` — 继续同步 `anki-vocab-forge` 名称。
- `3d3aeea` — 将 skill 重命名为 `anki-vocab-forge`。
- `0e4d9da` — 细化 Anki 卡片分组与图片规则。
- `17b9cfc` — 细化 Anki 卡片分组与图片规则。

## 2026-08-31

- `db21db6` — 补充依赖、示例用法和平台限制说明。
- `caf6db2` — 添加可运行的示例牌组 spec。
- `765b17d` — 添加 Python 依赖声明。
- `708feec` — 添加 MIT License。
- `90adfa4` — 重新设计 README，加入横幅和卡片预览。
- `8d5755f` — 添加最小 README 横幅。
- `6181c82` — 完善 README 安装与使用说明。
- `737c3d7` — 添加确定性的 Anki 牌组构建器。
- `3545e4d` — 添加 skill 接口元数据。
- `3f1cf7e` — 添加初版 `SKILL.md`。
- `29cf068` — 初始化仓库。

## 后续记录格式

```text
## YYYY-MM-DD

- `commit` — 做了什么，以及对用户有什么影响。
```
