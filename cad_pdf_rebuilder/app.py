from __future__ import annotations

import queue
import threading
from pathlib import Path
from tkinter import BooleanVar, DoubleVar, IntVar, StringVar, Tk, filedialog, messagebox
from tkinter import ttk

from .core import RebuildOptions, rebuild_many


class App(Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PDF 两层 CAD 重建工具")
        self.geometry("820x560")
        self.pdfs: list[Path] = []
        self.log_queue: queue.Queue[str] = queue.Queue()

        self.scale_var = DoubleVar(value=0.4989286)
        self.dpi_var = IntVar(value=400)
        self.dwg_var = BooleanVar(value=True)
        self.keep_dxf_var = BooleanVar(value=True)
        self.force_ocr_var = BooleanVar(value=True)
        self.output_var = StringVar(value=str(Path.cwd()))

        self._build_ui()
        self.after(150, self._drain_log)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root)
        top.pack(fill="x")
        ttk.Button(top, text="添加 PDF", command=self.add_pdfs).pack(side="left")
        ttk.Button(top, text="清空列表", command=self.clear_pdfs).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="选择输出文件夹", command=self.choose_output).pack(side="left", padx=(8, 0))
        ttk.Label(top, textvariable=self.output_var).pack(side="left", padx=(12, 0), fill="x", expand=True)

        columns = ("path",)
        self.tree = ttk.Treeview(root, columns=columns, show="headings", height=8)
        self.tree.heading("path", text="待处理 PDF")
        self.tree.column("path", width=760)
        self.tree.pack(fill="x", pady=10)

        opts = ttk.LabelFrame(root, text="输出设置", padding=10)
        opts.pack(fill="x")
        ttk.Label(opts, text="整体缩放比例").grid(row=0, column=0, sticky="w")
        ttk.Entry(opts, textvariable=self.scale_var, width=14).grid(row=0, column=1, sticky="w", padx=(8, 20))
        ttk.Label(opts, text="OCR 渲染 DPI").grid(row=0, column=2, sticky="w")
        ttk.Entry(opts, textvariable=self.dpi_var, width=10).grid(row=0, column=3, sticky="w", padx=(8, 20))
        ttk.Checkbutton(opts, text="检测到 ZWCAD 时自动生成 DWG", variable=self.dwg_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(opts, text="保留 DXF 中间文件", variable=self.keep_dxf_var).grid(row=1, column=2, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(opts, text="强制 OCR 生成可编辑文字", variable=self.force_ocr_var).grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))

        ttk.Button(root, text="开始生成", command=self.start).pack(fill="x", pady=10)

        self.log = ttk.Treeview(root, columns=("msg",), show="headings")
        self.log.heading("msg", text="处理日志")
        self.log.column("msg", width=760)
        self.log.pack(fill="both", expand=True)

    def add_pdfs(self) -> None:
        files = filedialog.askopenfilenames(title="选择 PDF", filetypes=[("PDF 文件", "*.pdf")])
        for file in files:
            path = Path(file)
            if path not in self.pdfs:
                self.pdfs.append(path)
                self.tree.insert("", "end", values=(str(path),))

    def clear_pdfs(self) -> None:
        self.pdfs.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)

    def choose_output(self) -> None:
        folder = filedialog.askdirectory(title="选择输出文件夹")
        if folder:
            self.output_var.set(folder)

    def start(self) -> None:
        if not self.pdfs:
            messagebox.showwarning("缺少 PDF", "请先添加一个或多个 PDF 文件。")
            return
        options = RebuildOptions(
            scale=float(self.scale_var.get()),
            render_dpi=int(self.dpi_var.get()),
            create_dwg=bool(self.dwg_var.get()),
            keep_dxf=bool(self.keep_dxf_var.get()),
            force_ocr=bool(self.force_ocr_var.get()),
        )
        output_dir = Path(self.output_var.get())
        threading.Thread(target=self._run, args=(list(self.pdfs), output_dir, options), daemon=True).start()

    def _run(self, pdfs: list[Path], output_dir: Path, options: RebuildOptions) -> None:
        try:
            self._log("开始处理")
            results = rebuild_many(pdfs, output_dir, options, self._log)
            for item in results:
                self._log(f"完成：{item.pdf.name}，矢量实体 {item.vector_entities}，可编辑文字 {item.text_entities}")
            self._log("全部完成")
        except Exception as exc:
            self._log(f"失败：{exc}")
            messagebox.showerror("处理失败", str(exc))

    def _log(self, message: str) -> None:
        self.log_queue.put(message)

    def _drain_log(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log.insert("", "end", values=(message,))
            self.log.yview_moveto(1.0)
        self.after(150, self._drain_log)


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
