"""Render lightweight PNG previews from the editable draw.io architecture file.

This checks layout and legibility; diagrams.net remains the authoritative renderer.
"""

from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from math import hypot
import re
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont


HERE = Path(__file__).parent
SOURCE = HERE / "market-eagle-architecture.drawio"
PREVIEWS = HERE / "previews"
PREVIEWS.mkdir(exist_ok=True)


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = [""]

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.lines.append("")

    def handle_data(self, data):
        self.lines[-1] += data

    def text(self):
        return "\n".join(unescape(line.strip()) for line in self.lines).strip()


def plain(value: str) -> str:
    parser = PlainText()
    parser.feed(value)
    return parser.text()


def style_map(value: str) -> dict[str, str]:
    return dict(p.split("=", 1) for p in value.split(";") if "=" in p)


def font(size: int, bold: bool = False):
    filename = "arialbd.ttf" if bold else "arial.ttf"
    path = Path("C:/Windows/Fonts") / filename
    return ImageFont.truetype(str(path), size)


def wrap(draw: ImageDraw.ImageDraw, value: str, text_font, max_width: int):
    out = []
    for paragraph in value.split("\n"):
        words = paragraph.split()
        if not words:
            out.append("")
            continue
        line = words[0]
        for word in words[1:]:
            candidate = line + " " + word
            if draw.textbbox((0, 0), candidate, font=text_font)[2] <= max_width:
                line = candidate
            else:
                out.append(line)
                line = word
        out.append(line)
    return out


def dashed_line(draw: ImageDraw.ImageDraw, points, color: str, width: int = 2):
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        length = hypot(x2 - x1, y2 - y1)
        if not length:
            continue
        distance = 0
        while distance < length:
            end = min(distance + 8, length)
            draw.line(((x1 + (x2 - x1) * distance / length,
                        y1 + (y2 - y1) * distance / length),
                       (x1 + (x2 - x1) * end / length,
                        y1 + (y2 - y1) * end / length)),
                      fill=color, width=width)
            distance += 13


def crosses_card(start, end, box) -> bool:
    x, y, w, h = box
    xmin, xmax, ymin, ymax = x + 3, x + w - 3, y + 3, y + h - 3
    dx, dy = end[0] - start[0], end[1] - start[1]
    lower, upper = 0.0, 1.0
    for p, q in ((-dx, start[0] - xmin), (dx, xmax - start[0]),
                 (-dy, start[1] - ymin), (dy, ymax - start[1])):
        if p == 0:
            if q < 0:
                return False
            continue
        ratio = q / p
        if p < 0:
            lower = max(lower, ratio)
        else:
            upper = min(upper, ratio)
        if lower > upper:
            return False
    return lower < upper


tree = ET.parse(SOURCE)
assert tree.getroot().tag == "mxfile"
assert len(tree.findall("diagram")) == 7

for number, diagram in enumerate(tree.findall("diagram"), 1):
    root = diagram.find("mxGraphModel/root")
    assert root is not None
    cells = root.findall("mxCell")
    ids = [cell.get("id") for cell in cells]
    assert len(ids) == len(set(ids)), "Duplicate cell ID"
    assert "0" in ids and "1" in ids
    by_id = {cell.get("id"): cell for cell in cells}
    for cell in cells:
        if cell.get("edge") == "1":
            assert cell.get("source") in by_id and cell.get("target") in by_id
        if cell.get("vertex") == "1":
            g = cell.find("mxGeometry")
            assert g is not None
            assert float(g.get("x", 0)) >= 0 and float(g.get("y", 0)) >= 0
            assert float(g.get("x", 0)) + float(g.get("width", 0)) <= 1600
            assert float(g.get("y", 0)) + float(g.get("height", 0)) <= 950

    image = Image.new("RGB", (1600, 950), "white")
    draw = ImageDraw.Draw(image)

    def geom(cell):
        g = cell.find("mxGeometry")
        return tuple(float(g.get(k, 0)) for k in ("x", "y", "width", "height"))

    def anchor(cell, prefix, edge_style):
        x, y, w, h = geom(cell)
        return (x + w * float(edge_style.get(prefix + "X", .5)),
                y + h * float(edge_style.get(prefix + "Y", .5)))

    # Draw group surfaces first, connections next, then cards and labels.
    vertices = [c for c in cells if c.get("vertex") == "1"]
    surfaces = [c for c in vertices if c.get("id", "").endswith("_zone")
                or c.get("id") in {"project_boundary", "sources", "orchestration",
                                   "activities", "storage", "interaction",
                                   "interpretation", "analytics", "evidence",
                                   "homelab", "runtime", "nvme", "hdd",
                                   "control_lane", "collection_lane", "research_lane",
                                   "application_store", "collection_control",
                                   "catalog_flow", "price_flow",
                                   "client_zone", "app_zone", "workflow_zone", "data_zone",
                                   "catalog_group", "observation_group", "research_group",
                                   "temporal_group", "backfill_group",
                                   "scheduled_group"}]
    for cell in surfaces:
        x, y, w, h = geom(cell)
        st = style_map(cell.get("style", ""))
        draw.rounded_rectangle((x, y, x + w, y + h), radius=14,
                               fill=st.get("fillColor", "#F3F6F9"),
                               outline=st.get("strokeColor", "#9DAFBE"), width=2)

    for cell in cells:
        if cell.get("edge") != "1":
            continue
        source = by_id[cell.get("source")]
        target = by_id[cell.get("target")]
        st = style_map(cell.get("style", ""))
        a = anchor(source, "exit", st)
        b = anchor(target, "entry", st)
        color = st.get("strokeColor", "#9CB0C3")
        waypoint_nodes = cell.findall("./mxGeometry/Array[@as='points']/mxPoint")
        if waypoint_nodes:
            points = [a] + [
                (float(point.get("x")), float(point.get("y")))
                for point in waypoint_nodes
            ] + [b]
            longest = max(zip(points, points[1:]),
                          key=lambda segment: abs(segment[1][0] - segment[0][0])
                          + abs(segment[1][1] - segment[0][1]))
            mid = ((longest[0][0] + longest[1][0]) / 2,
                   (longest[0][1] + longest[1][1]) / 2)
        else:
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if abs(a[0] - b[0]) > abs(a[1] - b[1]):
                points = [a, (mid[0], a[1]), (mid[0], b[1]), b]
            else:
                points = [a, (a[0], mid[1]), (b[0], mid[1]), b]
        for obstacle in vertices:
            if obstacle.get("id") in (cell.get("source"), cell.get("target")):
                continue
            if style_map(obstacle.get("style", "")).get("card") != "1":
                continue
            if any(crosses_card(start, end, geom(obstacle))
                   for start, end in zip(points, points[1:])):
                raise AssertionError(
                    f"{diagram.get('id')}: {cell.get('id')} crosses {obstacle.get('id')}")
        if st.get("dashed") == "1":
            dashed_line(draw, points, color)
        else:
            draw.line(points, fill=color, width=2)
        if cell.get("value"):
            text = plain(cell.get("value", ""))
            f = font(12)
            box = draw.textbbox((0, 0), text, font=f)
            tx, ty = mid[0] - (box[2] - box[0]) / 2, mid[1] - 8
            draw.rectangle((tx - 4, ty - 2, tx + box[2] + 4, ty + 18),
                           fill="white")
            draw.text((tx, ty), text, font=f, fill="#61758A")

    for cell in vertices:
        if cell in surfaces:
            continue
        x, y, w, h = geom(cell)
        st = style_map(cell.get("style", ""))
        value = plain(cell.get("value", ""))
        fill = st.get("fillColor", "none")
        stroke = st.get("strokeColor", "none")
        if "_icon_" in cell.get("id", ""):
            shape = st.get("shape", "rectangle")
            if shape == "umlActor":
                draw.ellipse((x + 10, y, x + 18, y + 8), outline=stroke, width=2)
                draw.line(((x + 14, y + 8), (x + 14, y + 23)), fill=stroke, width=2)
                draw.line(((x + 3, y + 14), (x + 25, y + 14)), fill=stroke, width=2)
                draw.line(((x + 14, y + 23), (x + 4, y + 35)), fill=stroke, width=2)
                draw.line(((x + 14, y + 23), (x + 24, y + 35)), fill=stroke, width=2)
            elif shape == "cylinder":
                draw.rectangle((x, y + 5, x + w, y + h - 5), fill=fill, outline=stroke, width=2)
                draw.ellipse((x, y, x + w, y + 10), fill=fill, outline=stroke, width=2)
                draw.arc((x, y + h - 10, x + w, y + h), 0, 180, fill=stroke, width=2)
            elif shape == "cloud":
                draw.rounded_rectangle((x + 2, y + 10, x + w - 2, y + h - 1),
                                       radius=8, fill=fill, outline=stroke, width=2)
                draw.ellipse((x + 6, y + 2, x + 24, y + 20),
                             fill=fill, outline=stroke, width=2)
            elif shape == "ellipse":
                draw.ellipse((x, y, x + w, y + h), fill=fill, outline=stroke, width=2)
            else:
                draw.rounded_rectangle((x, y, x + w, y + h),
                                       radius=3 if st.get("rounded") == "1" else 0,
                                       fill=fill, outline=stroke, width=2)
            continue
        if fill != "none" and w > 3 and h > 3:
            draw.rounded_rectangle((x, y, x + w, y + h),
                                   radius=14 if st.get("rounded") == "1" else 0,
                                   fill=fill,
                                   outline=None if st.get("dashed") == "1" else stroke,
                                   width=2)
            if st.get("dashed") == "1":
                dashed_line(draw, [(x, y), (x + w, y), (x + w, y + h),
                                   (x, y + h), (x, y)], stroke)
        elif fill != "none":
            draw.rectangle((x, y, x + w, y + h), fill=fill)
        if not value:
            continue
        size = int(st.get("fontSize", "16"))
        color = st.get("fontColor", "#15263B")
        lines = value.split("\n")
        if "<b>" in cell.get("value", "") and lines:
            title_font = font(size, True)
            detail_font = font(max(size - 2, 12))
            title_lines = wrap(draw, lines[0], title_font, int(w - 20))
            detail_lines = wrap(draw, "\n".join(lines[1:]), detail_font, int(w - 20))
            total = 25 * len(title_lines) + 20 * len(detail_lines)
            if total > h + 2:
                raise AssertionError(
                    f"{diagram.get('id')}: text exceeds {cell.get('id')} "
                    f"({total}px needed, {h}px available)")
            ty = y + (h - total) / 2
            for line in title_lines:
                width = draw.textbbox((0, 0), line, font=title_font)[2]
                tx = x + 2 if st.get("align") == "left" else x + (w - width) / 2
                draw.text((tx, ty), line,
                          font=title_font, fill=color)
                ty += 25
            for line in detail_lines:
                width = draw.textbbox((0, 0), line, font=detail_font)[2]
                tx = x + 2 if st.get("align") == "left" else x + (w - width) / 2
                draw.text((tx, ty), line,
                          font=detail_font, fill="#61758A")
                ty += 20
        else:
            f = font(size, st.get("fontStyle") == "1")
            wrapped = wrap(draw, value, f, int(w - 10))
            total = len(wrapped) * (size + 4)
            ty = y + (h - total) / 2
            align = st.get("align", "left")
            for line in wrapped:
                width = draw.textbbox((0, 0), line, font=f)[2]
                tx = x + (w - width) / 2 if align == "center" else x + 2
                draw.text((tx, ty), line, font=f, fill=color)
                ty += size + 4

    path = PREVIEWS / f"{number:02d}-{diagram.get('id')}.png"
    image.save(path)
    print(path)
