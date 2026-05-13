from __future__ import annotations

import math
import subprocess
import tempfile
import time
from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path
from typing import Callable, Iterable

import ezdxf
import fitz
from ezdxf.enums import TextEntityAlignment


Progress = Callable[[str], None]


@dataclass(slots=True)
class RebuildOptions:
    scale: float = 0.4989286
    gap: float = 120.0
    vector_layer: str = "0"
    text_layer: str = "1"
    text_style: str = "宋体"
    text_font: str = "simsun.ttc"
    render_dpi: int = 400
    create_dwg: bool = True
    keep_dxf: bool = True
    force_ocr: bool = True


@dataclass(slots=True)
class TextItem:
    text: str
    center_x: float
    center_y: float
    height: float


@dataclass(slots=True)
class RebuildResult:
    pdf: Path
    dxf: Path
    dwg: Path | None
    vector_entities: int
    text_entities: int


def _log(progress: Progress | None, message: str) -> None:
    if progress:
        progress(message)


def cad_point(point: fitz.Point, page_h: float, y_offset: float, scale: float) -> tuple[float, float]:
    return (float(point.x) * scale, float(y_offset + page_h - point.y) * scale)


def rect_points(rect: fitz.Rect, page_h: float, y_offset: float, scale: float) -> list[tuple[float, float]]:
    return [
        cad_point(fitz.Point(rect.x0, rect.y0), page_h, y_offset, scale),
        cad_point(fitz.Point(rect.x1, rect.y0), page_h, y_offset, scale),
        cad_point(fitz.Point(rect.x1, rect.y1), page_h, y_offset, scale),
        cad_point(fitz.Point(rect.x0, rect.y1), page_h, y_offset, scale),
    ]


def bezier_point(p0, p1, p2, p3, t: float) -> tuple[float, float]:
    u = 1.0 - t
    return (
        u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
        u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
    )


def flatten_curve(p0, p1, p2, p3, page_h: float, y_offset: float, scale: float, segments: int = 16) -> list[tuple[float, float]]:
    c0 = cad_point(p0, page_h, y_offset, scale)
    c1 = cad_point(p1, page_h, y_offset, scale)
    c2 = cad_point(p2, page_h, y_offset, scale)
    c3 = cad_point(p3, page_h, y_offset, scale)
    return [bezier_point(c0, c1, c2, c3, i / segments) for i in range(segments + 1)]


def valid_lineweight(width: float | None, scale: float) -> int:
    if not width:
        return 0
    target = max(0, min(211, int(round(float(width) * scale * 35))))
    valid = [0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211]
    return min(valid, key=lambda value: abs(value - target))


def add_polyline(msp, points, attribs, close=False) -> int:
    if len(points) < 2:
        return 0
    msp.add_lwpolyline(points, close=close, dxfattribs=attribs)
    return 1


def extract_pdf_text(page: fitz.Page) -> list[TextItem]:
    items: list[TextItem] = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = " ".join(span.get("text", "").split())
                if not text:
                    continue
                bbox = fitz.Rect(span["bbox"])
                items.append(
                    TextItem(
                        text=text,
                        center_x=(bbox.x0 + bbox.x1) / 2,
                        center_y=(bbox.y0 + bbox.y1) / 2,
                        height=max(1.2, float(span.get("size", bbox.height)) * 0.85),
                    )
                )
    return items


def extract_ocr_text(page: fitz.Page, options: RebuildOptions, progress: Progress | None = None) -> list[TextItem]:
    try:
        from PIL import Image
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
    except Exception as exc:
        raise RuntimeError(
            "这个 PDF 没有可提取文字层，需要 OCR。请先安装 OCR 依赖：pip install -r requirements.txt"
        ) from exc

    zoom = options.render_dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    result, _ = RapidOCR()(np.array(image))
    if not result:
        return []

    sx = float(page.rect.width) / pix.width
    sy = float(page.rect.height) / pix.height
    items: list[TextItem] = []
    for box, text, score in result:
        if not text or score < 0.35:
            continue
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        items.append(
            TextItem(
                text=" ".join(str(text).split()),
                center_x=(sum(xs) / len(xs)) * sx,
                center_y=(sum(ys) / len(ys)) * sy,
                height=max(1.2, (max(ys) - min(ys)) * sy * 0.72),
            )
        )
    _log(progress, f"OCR 识别到 {len(items)} 个文字块")
    return items


def extract_text_items(page: fitz.Page, options: RebuildOptions, progress: Progress | None = None) -> list[TextItem]:
    if options.force_ocr:
        return extract_ocr_text(page, options, progress)
    items = extract_pdf_text(page)
    if items and sum(len(item.text) for item in items) >= 20:
        return items
    return extract_ocr_text(page, options, progress)


def build_dxf(pdf_path: Path, output_dir: Path, options: RebuildOptions, progress: Progress | None = None) -> RebuildResult:
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    dxf_path = output_dir / f"{pdf_path.stem}.dxf"

    source = fitz.open(pdf_path)
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 0
    doc.styles.add(options.text_style, font=options.text_font)
    doc.layers.get("0").dxf.color = 7
    doc.layers.get("0").dxf.lineweight = 0
    if options.text_layer not in doc.layers:
        doc.layers.add(options.text_layer, color=1, lineweight=0)

    msp = doc.modelspace()
    vector_entities = 0
    text_entities = 0

    for page_index, page in enumerate(source):
        page_w = float(page.rect.width)
        page_h = float(page.rect.height)
        y_offset = -(page_h + options.gap) * page_index
        _log(progress, f"{pdf_path.name} 第 {page_index + 1}/{source.page_count} 页：抽取矢量")

        msp.add_lwpolyline(
            [
                (0, y_offset * options.scale),
                (page_w * options.scale, y_offset * options.scale),
                (page_w * options.scale, (y_offset + page_h) * options.scale),
                (0, (y_offset + page_h) * options.scale),
            ],
            close=True,
            dxfattribs={"layer": options.vector_layer, "color": 7, "lineweight": 50},
        )
        vector_entities += 1

        for drawing in page.get_drawings():
            attribs = {
                "layer": options.vector_layer,
                "color": 7,
                "lineweight": valid_lineweight(drawing.get("width"), options.scale),
            }
            path_points: list[tuple[float, float]] = []

            def flush(close: bool = False) -> None:
                nonlocal path_points, vector_entities
                vector_entities += add_polyline(msp, path_points, attribs, close=close)
                path_points = []

            for item in drawing.get("items", []):
                op = item[0]
                if op == "l":
                    flush()
                    msp.add_line(
                        cad_point(item[1], page_h, y_offset, options.scale),
                        cad_point(item[2], page_h, y_offset, options.scale),
                        dxfattribs=attribs,
                    )
                    vector_entities += 1
                elif op == "re":
                    flush()
                    vector_entities += add_polyline(msp, rect_points(item[1], page_h, y_offset, options.scale), attribs, close=True)
                elif op == "c":
                    curve = flatten_curve(item[1], item[2], item[3], item[4], page_h, y_offset, options.scale)
                    if path_points and math.dist(path_points[-1], curve[0]) < 1e-6:
                        path_points.extend(curve[1:])
                    else:
                        flush()
                        path_points.extend(curve)
                elif op == "m":
                    flush()
                    path_points = [cad_point(item[1], page_h, y_offset, options.scale)]
                elif op == "qu":
                    flush()
                    vector_entities += add_polyline(
                        msp,
                        [cad_point(p, page_h, y_offset, options.scale) for p in item[1]],
                        attribs,
                        close=True,
                    )
                else:
                    flush()
            flush(close=bool(drawing.get("closePath")))

        _log(progress, f"{pdf_path.name} 第 {page_index + 1}/{source.page_count} 页：生成可编辑文字")
        for text in extract_text_items(page, options, progress):
            x, y = cad_point(fitz.Point(text.center_x, text.center_y), page_h, y_offset, options.scale)
            entity = msp.add_text(
                text.text,
                dxfattribs={
                    "layer": options.text_layer,
                    "style": options.text_style,
                    "height": text.height * options.scale,
                    "color": 1,
                },
            )
            entity.set_placement((x, y), align=TextEntityAlignment.MIDDLE_CENTER)
            text_entities += 1

    doc.saveas(dxf_path)
    _log(progress, f"已生成 DXF：{dxf_path.name}")
    return RebuildResult(pdf=pdf_path, dxf=dxf_path, dwg=None, vector_entities=vector_entities, text_entities=text_entities)


def find_zwcad() -> Path | None:
    candidates = [
        Path(r"D:\ZWCAD2026\ZWCAD.exe"),
        Path(r"D:\ZWCAD2~1\ZWCAD.exe"),
        Path(r"C:\Program Files\ZWSOFT\ZWCAD 2026\ZWCAD.exe"),
        Path(r"C:\Program Files\ZWSOFT\ZWCAD 2025\ZWCAD.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def convert_dxf_to_dwg(dxf_path: Path, output_dir: Path, progress: Progress | None = None) -> Path | None:
    zwcad = find_zwcad()
    if not zwcad:
        _log(progress, "未检测到 ZWCAD，已保留 DXF。可用 CAD 打开 DXF 后另存为 DWG。")
        return None

    output_dir = Path(output_dir)
    temp_root = Path(tempfile.gettempdir()) / "pdf_two_layer_cad_rebuilder"
    temp_root.mkdir(parents=True, exist_ok=True)
    token = sha1(str(dxf_path.resolve()).encode("utf-8")).hexdigest()[:12]
    temp_dwg = temp_root / f"cad_rebuild_{token}.dwg"
    target_dwg = output_dir / f"{dxf_path.stem}.dwg"
    script = temp_root / f"cad_rebuild_{token}.scr"
    script.write_text(
        "\n".join(["FILEDIA", "0", "CMDDIA", "0", "SAVEAS", "2018", str(temp_dwg), "Y", "QSAVE", "QUIT"]) + "\n",
        encoding="ascii",
        errors="ignore",
    )

    if temp_dwg.exists():
        temp_dwg.unlink()
    _log(progress, "正在调用 ZWCAD 转换 DWG")
    subprocess.Popen([str(zwcad), str(dxf_path), "/b", str(script)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        if temp_dwg.exists() and temp_dwg.stat().st_size > 0:
            break
        time.sleep(1)
    if not temp_dwg.exists():
        _log(progress, "ZWCAD 未在预期时间内生成 DWG，已保留 DXF。")
        return None
    for _ in range(20):
        try:
            if target_dwg.exists():
                target_dwg.unlink()
            temp_dwg.replace(target_dwg)
            break
        except OSError:
            time.sleep(1)
    else:
        _log(progress, "DWG 已生成但仍被 CAD 占用，请关闭 CAD 后手动复制临时文件。")
        return temp_dwg
    try:
        script.unlink()
    except OSError:
        pass
    _log(progress, f"已生成 DWG：{target_dwg.name}")
    return target_dwg


def rebuild_pdf(pdf_path: Path, output_dir: Path, options: RebuildOptions, progress: Progress | None = None) -> RebuildResult:
    result = build_dxf(pdf_path, output_dir, options, progress)
    dwg = convert_dxf_to_dwg(result.dxf, output_dir, progress) if options.create_dwg else None
    if dwg and not options.keep_dxf:
        try:
            result.dxf.unlink()
        except OSError:
            pass
    return RebuildResult(result.pdf, result.dxf, dwg, result.vector_entities, result.text_entities)


def rebuild_many(pdf_paths: Iterable[Path], output_dir: Path, options: RebuildOptions, progress: Progress | None = None) -> list[RebuildResult]:
    results = []
    for pdf in pdf_paths:
        results.append(rebuild_pdf(Path(pdf), output_dir, options, progress))
    return results
