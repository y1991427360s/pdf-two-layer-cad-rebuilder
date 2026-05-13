# PDF 两层 CAD 重建工具

这个工具用于把 CAD 图纸类 PDF 重新生成可编辑 CAD 文件：原 PDF 里的所有矢量线条、边框和“碎线文字轮廓”会放到 `0` 图层；OCR 识别出来的真实可编辑文字会放到 `1` 图层。用户打开 CAD 后可以通过图层开关自行决定保留原始碎线文字，还是保留新生成的可编辑文字。

适用场景：

- PDF 是从 CAD 导出的图纸，但文字已经变成一段一段的线，不能直接编辑。
- 希望保留原图所有线条、边框、线宽差异。
- 希望额外叠加一层真正的 CAD `TEXT` 对象，便于后续修改。
- 一次处理一个或多个 PDF。

## 输出效果

每个 PDF 会输出同名 CAD 文件：

- `0` 图层：PDF 原始矢量内容，包括边框、图线、表格线、碎线文字等。
- `1` 图层：OCR 生成的真实 `TEXT` 文字对象，默认样式为 `宋体`，字体文件为 `simsun.ttc`。
- 默认整体缩放比例为 `0.4989286`，可在界面中修改。
- 多页 PDF 会按页面顺序在模型空间中纵向排布。

工具会优先生成 DXF。如果电脑安装了 ZWCAD 2025/2026，并能被工具检测到，会自动把 DXF 转成 DWG。

> 说明：DWG 是专有格式，纯 Python 不能稳定直接写 DWG。因此“自动输出 DWG”依赖本机安装 ZWCAD 等 CAD 软件；没有 CAD 软件时仍会生成 DXF，DXF 可用 CAD 打开后另存为 DWG。

## 快速开始

1. 安装 Python。推荐 Python 3.10 到 3.12；OCR 依赖对过新的 Python 版本可能会滞后支持。
2. 下载或拷贝本工具文件夹到任意电脑。
3. 双击 `install_dependencies.bat` 安装依赖，或在工具文件夹打开命令行运行：

```powershell
pip install -r requirements.txt
```

4. 双击 `run_gui.bat` 启动界面，或运行：

```powershell
python main.py
```

5. 在界面中点击“添加 PDF”，可选择一个或多个 PDF。
6. 选择输出文件夹。默认是工具所在文件夹。
7. 点击“开始生成”。

## 依赖说明

核心依赖：

- `pymupdf`：读取 PDF 页面、矢量路径和渲染图片。
- `ezdxf`：生成 CAD DXF 实体。
- `rapidocr-onnxruntime`：本地 OCR，把图纸文字识别为可编辑文字。
- `pillow`、`numpy`、`opencv-python`：OCR 图像处理依赖。

如果 PDF 本身保留真实文字层，工具会直接读取 PDF 文字；如果文字已经变成矢量轮廓，则需要 OCR 依赖。

## 界面参数

- `整体缩放比例`：默认 `0.4989286`，用于整体缩小或放大所有对象。
- `OCR 渲染 DPI`：默认 `400`。提高 DPI 可能提升识别率，但会变慢。
- `检测到 ZWCAD 时自动生成 DWG`：勾选后会尝试调用本机 ZWCAD。
- `保留 DXF 中间文件`：建议保留，方便排查和二次转换。
- `强制 OCR 生成可编辑文字`：默认开启。图纸 PDF 经常只残留少量标题文字层，主体文字仍是矢量轮廓，因此推荐开启。

## 文件组织

```text
pdf-two-layer-cad-rebuilder/
  main.py
  run_gui.bat
  install_dependencies.bat
  run_cli_example.py
  requirements.txt
  README.md
  cad_pdf_rebuilder/
    app.py
    core.py
```

## 注意事项

- OCR 识别文字不是人工校对结果，复杂图纸的小字、竖排字、密集表格可能需要人工复核。
- 生成的 `1` 图层文字会与 `0` 图层的碎线文字叠加，方便用户自行选择删除或隐藏哪一层。
- 如果自动生成 DWG 失败，请使用 CAD 打开输出的 DXF，再另存为 DWG。
- 字体默认使用 Windows 自带宋体 `simsun.ttc`。其他系统或缺少字体时，可在 `cad_pdf_rebuilder/core.py` 的 `RebuildOptions` 中调整字体文件。

## 开发者说明

命令行或其他程序也可以直接调用核心函数：

```python
from pathlib import Path
from cad_pdf_rebuilder.core import RebuildOptions, rebuild_many

pdfs = [Path("方案二.pdf")]
options = RebuildOptions(scale=0.4989286)
rebuild_many(pdfs, Path("."), options, print)
```
