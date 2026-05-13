from pathlib import Path

from cad_pdf_rebuilder.core import RebuildOptions, rebuild_many


if __name__ == "__main__":
    # 修改这里即可用命令行处理 PDF；日常使用推荐双击 run_gui.bat。
    pdfs = [Path("example.pdf")]
    rebuild_many(pdfs, Path.cwd(), RebuildOptions(), print)
