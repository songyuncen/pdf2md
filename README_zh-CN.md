# pdf2md

基于 [MinerU](https://mineru.net) 云端 API 的 PDF 转 Markdown 工具。默认使用 VLM 高精度引擎，支持 OCR、公式（LaTeX）、表格（HTML）识别。

## 特性

- MinerU VLM 引擎高精度文档解析
- 默认开启 OCR、公式识别、表格识别
- 指定页码时本地截取后再上传，大文件省流量
- 支持批量转换
- 可打包为单文件 `.exe`，无需 Python 环境

## 环境要求

- Python 3.12+
- MinerU API Token（免费注册：https://mineru.net/apiManage/token）

## 安装

```bash
uv sync
```

## 使用

```bash
# 设置 Token
export MINERU_TOKEN="your-token"

# 转换单个 PDF
uv run pdf2md.py paper.pdf -o output

# 批量转换
uv run pdf2md.py *.pdf -o output

# 只转换指定页（本地截取后上传）
uv run pdf2md.py paper.pdf --pages 1-20

# 不连续页码
uv run pdf2md.py paper.pdf --pages "1-5,10-15"

# 使用 pipeline 模型（更快，精度略低）
uv run pdf2md.py paper.pdf --model pipeline
```

## 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `-o, --output` | `output` | 输出目录 |
| `--model` | `vlm` | 模型：`vlm`（高精度）或 `pipeline`（快速） |
| `--language` | `ch` | 文档语言（见下表） |
| `--pages` | 全部 | 页码范围，如 `1-20` 或 `1-5,10-15` |
| `--token` | `$MINERU_TOKEN` | API Token |

### 语言支持

`--language` 参数用于选择 pipeline 后端的 OCR 模型。VLM 模型原生支持多语言，基本不受此参数影响。

| 代码 | 覆盖语言 |
|------|----------|
| `ch` | 中文、英文、日文、繁体中文、拉丁文（默认） |
| `ch_server` | 中文（服务端模型） |
| `korean` | 韩文 |
| `ta` | 泰米尔语 |
| `te` | 泰卢固语 |
| `ka` | 卡纳达语 |
| `th` | 泰文 |
| `el` | 希腊文 |
| `arabic` | 阿拉伯文 |
| `east_slavic` | 俄语、乌克兰语、白俄罗斯语等 |
| `cyrillic` | 其他西里尔字母语言 |
| `devanagari` | 印地语、梵语、马拉地语等 |

底层 OCR 引擎（PP-OCRv6）共支持 109 种语言，MinerU 将其归组为上述类别。中英文文档使用默认 `ch` 即可。

参考：[MinerU CLI 文档](https://opendatalab.github.io/MinerU/usage/cli_tools/)

## 高亮提取（本地，无需 Token）

从 PDF 的 **Highlight 标注** 中提取文字，按颜色倾向生成 Markdown：

| 颜色倾向 | 语义 |
|----------|------|
| 偏红（粉、橙红、深红…） | 重点 / 错误 |
| 偏黄（浅黄、金、橙黄…） | 要点 |
| 偏绿（青绿、翠绿、浅绿…） | 定义 |
| 其他（蓝/紫/灰等） | 其他（附 RGB） |

颜色按 **色相倾向** 归类，不是精确 RGB 匹配。仅支持阅读器写入的 Highlight 注释；若高亮已压成图片且无标注对象，则无法提取。

```bash
# 提取高亮为 Markdown
uv run python highlights2md.py book.pdf -o output

# 指定页、按颜色分组、同时输出 JSON
uv run python highlights2md.py book.pdf --pages 1-50 --group-by color --json -o output

# 调试：在标签旁显示原始颜色
uv run python highlights2md.py book.pdf --show-color
```

输出文件：`output/{文件名}_highlights.md`（可选 `_highlights.json`）。

```bash
# 运行测试
uv run python -m unittest tests.test_highlights2md -v
```

## 打包 exe

```bash
# 全文转 MD（MinerU）
uv run pyinstaller --noconfirm pdf2md.spec
# 输出：dist/pdf2md.exe

# 高亮提取（本地）
uv run pyinstaller --noconfirm highlights2md.spec
# 输出：dist/highlights2md.exe
```

无 Python 环境时直接运行：

```bash
dist\highlights2md.exe book.pdf -o output
dist\highlights2md.exe book.pdf --pages 1-50 --group-by color --json
```

## 许可证

MIT
