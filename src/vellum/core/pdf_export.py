"""Write Vellum objects into a PDF as native, editable annotations.

Every object becomes a standard PDF markup (Line, PolyLine, Polygon, Circle,
FreeText, Ink, Stamp) that Bluebeam Revu, Acrobat and other editors can
select, move, restyle and delete. Measurement objects also carry the PDF
measurement dictionary (/Measure, /IT ...Dimension), and each page carries
its calibration as a viewport (/VP), so editors that understand PDF
measurements see calibrated values.

Appearance: each annotation gets an appearance stream drawn here, in image
pixels exactly as the viewer paints it at 100 % zoom (labels included), with
the real fonts embedded. A PDF viewer shows that appearance until the markup
is edited, at which point the editor regenerates it from the standard keys.

Round trip: each annotation's /NM is its object's uid and its full
definition is stored as JSON under the private key /Vellum; the page's
scale and origin are stored the same way on the page. Derived markups
(merged contour rings, the legend) are tagged so an importer can rebuild
them from their source objects instead of reading them back.

Coordinates: objects are stored in image pixels of the page rendered at
`dpi`, as displayed (rotated, cropped). 1 px = 72 / dpi pt.
"""
import getpass
import json
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import fitz

from . import contours
from .fonts import FontResolver
from .models import DiagramObject, Point, ScaleInfo

PRIVATE_KEY = "Vellum"
VIEWPORT_NAME = "Vellum"
FORMAT_VERSION = 1

# Qt dash patterns, in units of the pen width.
_DASHES = {
    "dashed":  (4, 2),
    "dotted":  (1, 2),
    "dashdot": (4, 2, 1, 2),
}

_SUBJECTS = {
    "point":    "Point",
    "distance": "Length Measurement",
    "angle":    "Angle Measurement",
    "polygon":  "Area Measurement",
    "polyline": "Polylength Measurement",
    "ellipse":  "Ellipse",
    "textbox":  "Text Box",
    "polyline_contour": "Contour Source",
    "point_contour":    "Contour Source",
}

_DEFAULT_LINE_WIDTH = 2.0   # px, as the viewer
_POINT_R = 5.0              # px, point marker radius
_CONTOUR_POINT_R = 4.0      # px, point-contour skeleton marker radius
_TEXT_PAD = (4.0, 2.0)      # px, text box inner padding (x, y)


@dataclass
class PageMarkup:
    """Everything Vellum holds for one page."""
    index: int
    objects: List[DiagramObject]
    scale: ScaleInfo
    origin: Point
    origin_world: Tuple[float, float] = (0.0, 0.0)
    legend_title: str = "Legend"
    legend_visible: bool = True


@dataclass
class ExportStyle:
    """Colours and fonts that the viewer takes from the theme."""
    kind_colors: Dict[str, str]
    contour_color: str
    guide_color: str
    text_color: str
    label_family: str
    label_px: float
    legend_ink: str = "#1F2937"
    legend_bg: str = "#FFFFFF"
    legend_border: str = "#D6D3D1"


@dataclass
class ExportReport:
    annotations: int = 0
    pages: int = 0
    warnings: List[str] = field(default_factory=list)


def _rgb(hex_color: str) -> Tuple[float, float, float]:
    c = hex_color.lstrip("#")
    if len(c) == 8:     # #AARRGGBB as Qt writes it
        c = c[2:]
    try:
        return tuple(int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return (0.0, 0.0, 0.0)


def _pdf_num(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".") or "0"


def _pdf_array(values) -> str:
    return "[" + " ".join(_pdf_num(v) for v in values) + "]"


def _css_escape(family: str) -> str:
    return family.replace("\\", "\\\\").replace("'", "\\'")


def _html_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ---------------------------------------------------------------------------
# Measurement dictionary
# ---------------------------------------------------------------------------

def _number_format(unit: str, factor: float, precision: int = 100) -> str:
    return (f"<</Type/NumberFormat/U {fitz.get_pdf_str(unit)}/C {factor:.10g}"
            f"/D {precision}/F/D/FD true/RD(.)/RT()/SS( )/PS( )>>")


def measure_dict(scale: ScaleInfo, dpi: float, origin_pdf: Optional[Tuple[float, float]] = None) -> str:
    """A rectilinear /Measure dictionary: `X` converts PDF points to the
    calibrated unit; distance, area and angle formats apply to that result."""
    units_per_pt = scale.scale_factor * dpi / 72.0
    ratio = f"1 in = {units_per_pt * 72.0:.6g} {scale.unit}"
    parts = [
        "<</Type/Measure/Subtype/RL",
        f"/R {fitz.get_pdf_str(ratio)}",
        f"/X[{_number_format(scale.unit, units_per_pt)}]",
        f"/D[{_number_format(scale.unit, 1)}]",
        f"/A[{_number_format('sq ' + scale.unit, 1)}]",
        f"/T[{_number_format(chr(176), 1, 10)}]",
    ]
    if origin_pdf is not None:
        parts.append(f"/O{_pdf_array(origin_pdf)}")
    parts.append(">>")
    return "".join(parts)


def _is_calibrated(scale: ScaleInfo) -> bool:
    return bool(scale.unit) and scale.unit != "px" and scale.scale_factor > 0


# ---------------------------------------------------------------------------
# Scratch drawing: one scratch page per appearance, in image pixels
# ---------------------------------------------------------------------------

class _Canvas:
    """Draws on a scratch page whose units are image pixels. `origin` is the
    image-pixel point that maps to the scratch page's top-left corner."""

    def __init__(self, page: fitz.Page, origin: fitz.Point, fonts: "_Fonts"):
        self.page = page
        self.ox, self.oy = origin.x, origin.y
        self.fonts = fonts

    def _p(self, x: float, y: float) -> fitz.Point:
        return fitz.Point(x - self.ox, y - self.oy)

    def _finish(self, shape, color, width, style, fill=None, fill_opacity=1.0, close=False):
        dash = _DASHES.get(style)
        dashes = None
        if dash and color is not None:
            dashes = _pdf_array([d * width for d in dash]) + " 0"
        shape.finish(
            color=_rgb(color) if color else None,
            fill=_rgb(fill) if fill else None,
            width=width,
            dashes=dashes,
            closePath=close,
            fill_opacity=fill_opacity,
            # Qt's default pen: square caps, bevel joins. Dashes keep flat
            # caps so the pattern lengths come out as Qt draws them.
            lineCap=0 if dash else 2,
            lineJoin=2,
        )
        shape.commit()

    def polyline(self, pts, color, width, style="solid", closed=False, fill=None, fill_opacity=1.0):
        shape = self.page.new_shape()
        shape.draw_polyline([self._p(x, y) for x, y in pts])
        self._finish(shape, color, width, style, fill, fill_opacity, close=closed)

    def ellipse(self, rect: fitz.Rect, color, width, style="solid", fill=None):
        shape = self.page.new_shape()
        shape.draw_oval(fitz.Rect(self._p(rect.x0, rect.y0), self._p(rect.x1, rect.y1)))
        self._finish(shape, color, width, style, fill)

    def rect(self, rect: fitz.Rect, color, width, style="solid", fill=None):
        shape = self.page.new_shape()
        shape.draw_rect(fitz.Rect(self._p(rect.x0, rect.y0), self._p(rect.x1, rect.y1)))
        self._finish(shape, color, width, style, fill)

    def disk(self, cx: float, cy: float, r: float, fill: str):
        shape = self.page.new_shape()
        shape.draw_circle(self._p(cx, cy), r)
        shape.finish(color=None, fill=_rgb(fill), width=0)
        shape.commit()

    def text(self, x: float, y: float, text: str, color: str, size: float,
             family: str, bold: bool = False):
        """Single line of text, (x, y) on the baseline."""
        font = self.fonts.font(family, bold, False)
        tw = fitz.TextWriter(self.page.rect)
        tw.append(self._p(x, y), text, font=font, fontsize=size)
        tw.write_text(self.page, color=_rgb(color))


class _Fonts:
    """fitz.Font objects and @font-face rules, resolved through FontResolver."""

    def __init__(self, resolver: FontResolver, report: ExportReport):
        self.resolver = resolver
        self.report = report
        self._fonts: Dict[tuple, fitz.Font] = {}
        self._warned: set = set()

    def path(self, family: str, bold: bool, italic: bool) -> Optional[str]:
        path = self.resolver.find(family, bold, italic) if family else None
        if path is None and family and family not in self._warned:
            self._warned.add(family)
            self.report.warnings.append(
                f"Font '{family}' was not found; text using it falls back to Helvetica.")
        return path

    def font(self, family: str, bold: bool, italic: bool) -> fitz.Font:
        key = (family, bold, italic)
        if key not in self._fonts:
            path = self.path(family, bold, italic)
            if path:
                self._fonts[key] = fitz.Font(fontfile=path)
            else:
                base = {(False, False): "helv", (True, False): "hebo",
                        (False, True): "heit", (True, True): "hebi"}[(bold, italic)]
                self._fonts[key] = fitz.Font(base)
        return self._fonts[key]

    def text_width(self, text: str, size: float, family: str, bold: bool = False) -> float:
        return self.font(family, bold, False).text_length(text, fontsize=size)

    def line_metrics(self, size: float, family: str, bold: bool = False) -> Tuple[float, float]:
        """(ascent, descent) in px, descent positive below the baseline."""
        f = self.font(family, bold, False)
        return f.ascender * size, -f.descender * size


# ---------------------------------------------------------------------------
# Exporter
# ---------------------------------------------------------------------------

class _PageWriter:
    """Writes one page's markups."""

    def __init__(self, exp: "_Exporter", page: fitz.Page, markup: PageMarkup):
        self.exp = exp
        self.doc = exp.doc
        self.page = page
        self.m = markup
        self.k = 72.0 / exp.dpi                 # image px -> pt
        self.rot = page.rotation
        self.derot = page.derotation_matrix
        self._probe_pdf_offset()
        self.calibrated = _is_calibrated(markup.scale)
        self.measure = None
        if self.calibrated:
            o = self.to_pdf(markup.origin.x, markup.origin.y)
            self.measure = measure_dict(markup.scale, exp.dpi, o)

    # -- coordinates -------------------------------------------------------

    def _probe_pdf_offset(self):
        """PyMuPDF annotation coordinates are unrotated, top-left based and
        relative to the crop box; PDF user space is bottom-left based. A line
        annotation stores its exact end points (/L) in user space, so a probe
        line gives the offset between the two without relying on how the page
        boxes happen to be written."""
        probe = self.page.add_line_annot((0, 0), (0, 10))
        vals = [float(v) for v in self.doc.xref_get_key(probe.xref, "L")[1].strip("[]").split()]
        self.page.delete_annot(probe)
        self.ax, self.by = vals[0], vals[1]

    def unrot(self, x: float, y: float) -> fitz.Point:
        """Image px -> PyMuPDF (unrotated) page coordinates."""
        return fitz.Point(x * self.k, y * self.k) * self.derot

    def unrot_rect(self, r: fitz.Rect) -> fitz.Rect:
        a, b = self.unrot(r.x0, r.y0), self.unrot(r.x1, r.y1)
        return fitz.Rect(a, b).normalize()

    def to_pdf(self, x: float, y: float) -> Tuple[float, float]:
        u = self.unrot(x, y)
        return (u.x + self.ax, self.by - u.y)

    def pdf_rect(self, r: fitz.Rect) -> Tuple[float, float, float, float]:
        u = self.unrot_rect(r)
        return (u.x0 + self.ax, self.by - u.y1, u.x1 + self.ax, self.by - u.y0)

    def world(self, x: float, y: float) -> Tuple[float, float]:
        sf = self.m.scale.scale_factor
        ox, oy = self.m.origin_world
        return (x - self.m.origin.x) * sf + ox, -(y - self.m.origin.y) * sf + oy

    # -- page-level --------------------------------------------------------

    def write_page_data(self):
        doc, page = self.doc, self.page
        data = {
            "version": FORMAT_VERSION,
            "dpi": self.exp.dpi,
            "scale_info": self.m.scale.to_dict(),
            "origin": self.m.origin.to_dict(),
            "origin_world": list(self.m.origin_world),
            "legend_title": self.m.legend_title,
            "legend_visible": self.m.legend_visible,
        }
        doc.xref_set_key(page.xref, PRIVATE_KEY, fitz.get_pdf_str(json.dumps(data)))
        if not self.calibrated:
            return
        # Keep any viewports the file already has (another tool's
        # calibrations) except a previous Vellum one; ours goes last so it
        # wins where they overlap.
        kept = []
        kind, val = doc.xref_get_key(page.xref, "VP")
        if kind == "array":
            for item in self._split_array(val):
                if f"/Name {fitz.get_pdf_str(VIEWPORT_NAME)}" not in item \
                        and f"/Name({VIEWPORT_NAME})" not in item:
                    kept.append(item)
        full = page.rect * self.derot
        bbox = (full.x0 + self.ax, self.by - full.y1, full.x1 + self.ax, self.by - full.y0)
        vp = (f"<</Type/Viewport/BBox{_pdf_array(bbox)}"
              f"/Name {fitz.get_pdf_str(VIEWPORT_NAME)}/Measure {self.measure}>>")
        doc.xref_set_key(page.xref, "VP", "[" + "".join(kept) + vp + "]")

    @staticmethod
    def _split_array(text: str) -> List[str]:
        """Top-level `<<...>>` / `n 0 R` items of a PDF array's source text."""
        body = text.strip()[1:-1]
        items, depth, start, i = [], 0, None, 0
        while i < len(body):
            if body.startswith("<<", i):
                if depth == 0:
                    start = i
                depth += 1
                i += 2
                continue
            if body.startswith(">>", i):
                depth -= 1
                i += 2
                if depth == 0 and start is not None:
                    items.append(body[start:i])
                    start = None
                continue
            i += 1
        refs = body
        for it in items:
            refs = refs.replace(it, " ")
        toks = refs.split()
        for j in range(len(toks) - 2):
            if toks[j + 2] == "R":
                items.append(" ".join(toks[j:j + 3]))
        return items

    # -- annotation plumbing -----------------------------------------------

    def _common(self, annot, obj: Optional[DiagramObject], subject: str,
                contents: str, private: dict, measured: bool = False,
                intent: Optional[str] = None):
        doc = self.doc
        annot.set_info(title=self.exp.author, subject=subject, content=contents)
        if obj is not None:
            doc.xref_set_key(annot.xref, "NM", fitz.get_pdf_str(obj.uid))
        doc.xref_set_key(annot.xref, PRIVATE_KEY, fitz.get_pdf_str(json.dumps(private)))
        if measured and self.calibrated:
            if intent:
                doc.xref_set_key(annot.xref, "IT", f"/{intent}")
            doc.xref_set_key(annot.xref, "Measure", self.measure)

    def _border(self, annot, obj: DiagramObject, width_px: float):
        w = width_px * self.k
        dash = _DASHES.get(obj.line_style)
        annot.set_border(width=w, dashes=[d * w for d in dash] if dash else None)
        self._dash_style(annot, obj)

    def _dash_style(self, annot, obj: DiagramObject):
        """Mark a dashed border as such (/S /D): the dash array alone is
        ignored by editors when they redraw the markup."""
        if obj.line_style in _DASHES:
            self.doc.xref_set_key(annot.xref, "BS/S", "/D")

    def _appearance(self, annot, vrect: fitz.Rect, draw: Callable[[_Canvas], None],
                    inner: Optional[fitz.Rect] = None):
        """Replace `annot`'s appearance with `draw`'s output over `vrect`
        (image px), and size the annotation to it. `inner`, for Circle /
        Square / FreeText, is the shape's own box, recorded as /RD so an
        editor regenerating the appearance draws the shape where it was."""
        exp = self.exp
        vrect = fitz.Rect(vrect)
        vrect.x0, vrect.y0 = math.floor(vrect.x0), math.floor(vrect.y0)
        vrect.x1, vrect.y1 = math.ceil(vrect.x1), math.ceil(vrect.y1)

        scratch = exp.scratch.new_page(width=max(vrect.width, 1), height=max(vrect.height, 1))
        draw(_Canvas(scratch, vrect.tl, exp.fonts))

        outer = self.pdf_rect(vrect)
        rd = None
        if inner is not None:
            i = self.pdf_rect(inner)
            rd = tuple(max(0.0, v) for v in
                       (i[0] - outer[0], outer[3] - i[3], outer[2] - i[2], i[1] - outer[1]))
        # The appearance stream is built later, in one batch: adding pages to
        # the document invalidates the Page handles still being written to.
        exp.jobs.append((annot.xref, scratch.number, self.unrot_rect(vrect), self.rot, outer, rd))
        self.exp.report.annotations += 1

    # -- labels --------------------------------------------------------------

    def _label_lines(self, obj: DiagramObject, fallback: str) -> List[str]:
        """The viewer's on-canvas label: 'Name: value', or the name followed by
        one measurement per line."""
        name = obj.name or fallback
        ms = obj.measurements()
        if len(ms) <= 1:
            return [f"{name}: {ms[0][1]}" if ms else name]
        return [name] + [f"{lbl}: {val}" for lbl, val in ms]

    def _text_block_rect(self, x: float, y: float, lines: List[str]) -> fitz.Rect:
        st = self.exp.style
        asc, desc = self.exp.fonts.line_metrics(st.label_px, st.label_family)
        line_h = asc + desc
        w = max(self.exp.fonts.text_width(t, st.label_px, st.label_family) for t in lines)
        return fitz.Rect(x, y - asc, x + w, y + desc + line_h * (len(lines) - 1))

    def _draw_text_block(self, c: _Canvas, x: float, y: float, lines: List[str], color: str):
        st = self.exp.style
        asc, desc = self.exp.fonts.line_metrics(st.label_px, st.label_family)
        for i, t in enumerate(lines):
            c.text(x, y + i * (asc + desc), t, color, st.label_px, st.label_family)

    # -- objects ---------------------------------------------------------------

    def _color(self, obj: DiagramObject) -> str:
        return obj.color or self.exp.style.kind_colors.get(obj.kind, self.exp.style.text_color)

    @staticmethod
    def _width(obj: DiagramObject) -> float:
        return obj.line_width if obj.line_width and obj.line_width > 0 else _DEFAULT_LINE_WIDTH

    @staticmethod
    def _bounds(pts) -> fitz.Rect:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return fitz.Rect(min(xs), min(ys), max(xs), max(ys))

    def write_object(self, idx: int, obj: DiagramObject):
        writer = {
            "point": self._point,
            "distance": self._distance,
            "angle": self._angle,
            "polygon": self._polygon,
            "polyline": self._polyline,
            "ellipse": self._ellipse,
            "textbox": self._textbox,
            "polyline_contour": self._contour_source,
            "point_contour": self._contour_source,
        }.get(obj.kind)
        if writer is not None:
            writer(idx, obj)

    def _private(self, obj: DiagramObject) -> dict:
        return {"version": FORMAT_VERSION, "object": obj.to_dict()}

    def _stroked(self, idx, obj, annot, pts, closed, fallback, anchor, intent,
                 fill_opacity=0.0):
        """Shared tail for the vertex-based markups (line, polyline, polygon,
        angle): colours, border, keys and an appearance of stroke + label."""
        color, w = self._color(obj), self._width(obj)
        annot.set_colors(stroke=_rgb(color))
        self._border(annot, obj, w)
        annot.update()
        lines = self._label_lines(obj, fallback)
        self._common(annot, obj, obj.name or _SUBJECTS[obj.kind],
                     obj._measure_inline() or obj.name, self._private(obj),
                     measured=True, intent=intent)
        if intent == "LineDimension" and self.calibrated:
            self.doc.xref_set_key(annot.xref, "Cap", "true")
            self.doc.xref_set_key(annot.xref, "CP", "/Top")
        vrect = self._bounds(pts) + (-w, -w, w, w)
        ax, ay = anchor
        vrect |= self._text_block_rect(ax, ay, lines)

        def draw(c: _Canvas):
            c.polyline(pts, color, w, obj.line_style, closed=closed,
                       fill=color if fill_opacity else None, fill_opacity=fill_opacity)
            self._draw_text_block(c, ax, ay, lines, color)
        self._appearance(annot, vrect, draw)

    def _distance(self, idx, obj):
        if len(obj.points) < 2:
            return
        p0, p1 = obj.points[:2]
        annot = self.page.add_line_annot(self.unrot(*p0), self.unrot(*p1))
        mid = ((p0[0] + p1[0]) / 2 + 5, (p0[1] + p1[1]) / 2 - 5)
        self._stroked(idx, obj, annot, [p0, p1], False, "Line", mid, "LineDimension")

    def _polyline(self, idx, obj):
        if len(obj.points) < 2:
            return
        annot = self.page.add_polyline_annot([self.unrot(*p) for p in obj.points])
        mid = obj.points[len(obj.points) // 2]
        self._stroked(idx, obj, annot, obj.points, False, "Polyline",
                      (mid[0] + 5, mid[1] - 5), "PolyLineDimension")

    def _angle(self, idx, obj):
        if len(obj.points) < 3:
            return
        pts = obj.points[:3]
        annot = self.page.add_polyline_annot([self.unrot(*p) for p in pts])
        v = pts[1]
        self._stroked(idx, obj, annot, pts, False, "Angle", (v[0] + 5, v[1] - 5), None)

    def _polygon(self, idx, obj):
        if len(obj.points) < 3:
            return
        annot = self.page.add_polygon_annot([self.unrot(*p) for p in obj.points])
        cx = sum(p[0] for p in obj.points) / len(obj.points)
        cy = sum(p[1] for p in obj.points) / len(obj.points)
        # The viewer fills polygons with the stroke colour at alpha 40/255.
        # Only the appearance carries that tint: /IC has no opacity of its own,
        # and an editor regenerating the markup would paint it solid.
        self._stroked(idx, obj, annot, obj.points, True, "Polygon", (cx + 5, cy),
                      "PolygonDimension", fill_opacity=40 / 255)

    def _ellipse(self, idx, obj):
        if len(obj.points) < 2:
            return
        box = fitz.Rect(fitz.Point(*obj.points[0]), fitz.Point(*obj.points[1])).normalize()
        color, w = self._color(obj), self._width(obj)
        inner = box + (-w / 2, -w / 2, w / 2, w / 2)
        annot = self.page.add_circle_annot(self.unrot_rect(inner))
        annot.set_colors(stroke=_rgb(color))
        self._border(annot, obj, w)
        annot.update()
        self._common(annot, obj, obj.name or _SUBJECTS["ellipse"],
                     obj._measure_inline() or obj.name, self._private(obj), measured=True)
        lines = self._label_lines(obj, "Ellipse")
        ax, ay = (box.x0 + box.x1) / 2 + 5, box.y0 - 5
        guide = self.exp.style.guide_color
        vrect = (box + (-w, -w, w, w)) | self._text_block_rect(ax, ay, lines)

        def draw(c: _Canvas):
            c.rect(box, guide, 1, "dashed")      # the viewer's thin bounding box
            c.ellipse(box, color, w, obj.line_style)
            self._draw_text_block(c, ax, ay, lines, color)
        self._appearance(annot, vrect, draw, inner=inner)

    def _point(self, idx, obj):
        if not obj.points:
            return
        x, y = obj.points[0]
        color = self._color(obj)
        r = _POINT_R
        disk = fitz.Rect(x - r, y - r, x + r, y + r)
        annot = self.page.add_circle_annot(self.unrot_rect(disk))
        annot.set_colors(stroke=_rgb(color), fill=_rgb(color))
        annot.set_border(width=0)
        annot.update()
        wx, wy = self.world(x, y)
        coords = f"({wx:.2f}, {wy:.2f})"
        label = obj.name or f"P{idx + 1}"
        self._common(annot, obj, obj.name or _SUBJECTS["point"], f"{label} {coords}",
                     self._private(obj))
        r1 = self._text_block_rect(x + 9, y - 7, [label])
        r2 = self._text_block_rect(x + 9, y + 6, [coords])
        vrect = disk | r1 | r2

        def draw(c: _Canvas):
            c.disk(x, y, r, color)
            self._draw_text_block(c, x + 9, y - 7, [label], color)
            self._draw_text_block(c, x + 9, y + 6, [coords], color)
        self._appearance(annot, vrect, draw, inner=disk)

    def _contour_source(self, idx, obj):
        """The defining polyline / point of a contour, drawn as the viewer's
        thin dashed guide. Its levels travel in the private data."""
        if not obj.points:
            return
        guide = self.exp.style.guide_color
        x0, y0 = obj.points[0]
        if obj.kind == "point_contour":
            r = _CONTOUR_POINT_R
            shape_box = fitz.Rect(x0 - r, y0 - r, x0 + r, y0 + r)
            annot = self.page.add_circle_annot(self.unrot_rect(shape_box))
            annot.set_colors(stroke=_rgb(guide), fill=_rgb(guide))
            annot.set_border(width=0)
            inner = shape_box
        else:
            if len(obj.points) < 2:
                return
            annot = self.page.add_polyline_annot([self.unrot(*p) for p in obj.points])
            annot.set_colors(stroke=_rgb(guide))
            annot.set_border(width=self.k, dashes=[4 * self.k, 2 * self.k])
            shape_box = self._bounds(obj.points) + (-1, -1, 1, 1)
            inner = None
        annot.update()
        levels = ", ".join(str(l.get("reference", "")) for l in obj.levels)
        self._common(annot, obj, obj.name or _SUBJECTS[obj.kind], levels, self._private(obj))
        vrect = fitz.Rect(shape_box)
        if obj.name:
            vrect |= self._text_block_rect(x0 + 7, y0 - 6, [obj.name])

        def draw(c: _Canvas):
            if obj.kind == "point_contour":
                c.disk(x0, y0, _CONTOUR_POINT_R, guide)
            else:
                c.polyline(obj.points, guide, 1, "dashed")
            if obj.name:
                self._draw_text_block(c, x0 + 7, y0 - 6, [obj.name], guide)
        self._appearance(annot, vrect, draw, inner=inner)

    # -- text boxes -----------------------------------------------------------

    def _textbox(self, idx, obj):
        if len(obj.points) < 2:
            return
        exp = self.exp
        box = fitz.Rect(fitz.Point(*obj.points[0]), fitz.Point(*obj.points[1])).normalize()
        border, w = self._color(obj), self._width(obj)
        text_color = obj.font_color or exp.style.text_color
        size_pt = obj.font_size if obj.font_size and obj.font_size > 0 else 12
        size_px = size_pt / self.k
        family = obj.font_family or exp.style.label_family
        align = {"left": 0, "center": 1, "right": 2}.get(obj.h_align, 0)
        dash = _DASHES.get(obj.line_style)

        annot = self.page.add_freetext_annot(
            self.unrot_rect(box), obj.text or " ",
            fontsize=size_pt, fontname="Helv",
            text_color=_rgb(text_color),
            fill_color=_rgb(obj.fill_color) if obj.fill_color else None,
            border_color=_rgb(border),
            border_width=w * self.k,
            dashes=[d * w * self.k for d in dash] if dash else None,
            align=align,
            rotate=self.rot,
            richtext=True,
            style=self._ds(family, size_pt, text_color, obj),
        )
        self._common(annot, obj, obj.name or _SUBJECTS["textbox"], obj.text, self._private(obj))
        # After the contents: setting /Contents drops /RC. And no callout -
        # PyMuPDF writes a default /CL that editors would draw.
        self.doc.xref_set_key(annot.xref, "RC", fitz.get_pdf_str(self._rc(obj, family, size_pt, text_color)))
        self.doc.xref_set_key(annot.xref, "CL", "null")
        self.doc.xref_set_key(annot.xref, "IT", "/FreeText")
        self._dash_style(annot, obj)
        vrect = box + (-w / 2, -w / 2, w / 2, w / 2)
        html, css, archive = self._html(obj, family, size_px, text_color)
        pad_x, pad_y = _TEXT_PAD
        text_rect = box + (pad_x, pad_y, -pad_x, -pad_y)

        def draw(c: _Canvas):
            c.rect(box, border, w, obj.line_style, fill=obj.fill_color or None)
            if not obj.text:
                return
            local = fitz.Rect(c._p(text_rect.x0, text_rect.y0), c._p(text_rect.x1, text_rect.y1))
            used = self._html_height(html, css, archive, local.width)
            spare = local.height - used
            if obj.v_align == "middle":
                local.y0 += spare / 2
            elif obj.v_align == "bottom":
                local.y0 += spare
            # Overflowing text runs past the box and is clipped by the
            # appearance's bounding box, as the viewer clips it.
            local.y1 = max(local.y1, local.y0 + used + 1)
            c.page.insert_htmlbox(local, html, css=css, archive=archive, scale_low=1)
        self._appearance(annot, vrect, draw, inner=vrect)

    def _font_face_css(self, family: str, bold: bool, italic: bool
                       ) -> Tuple[str, Optional[fitz.Archive]]:
        """An @font-face rule for the file that draws `family` in this style,
        plus an archive holding its folder; ("", None) if it doesn't resolve."""
        path = self.exp.fonts.path(family, bold, italic)
        if not path:
            return "", None
        folder, name = path.replace("\\", "/").rsplit("/", 1)
        rule = ("@font-face{font-family:PMFace;"
                f"font-weight:{'bold' if bold else 'normal'};"
                f"font-style:{'italic' if italic else 'normal'};"
                f"src:url('{name}');}}")
        return rule, fitz.Archive(folder)

    def _html(self, obj: DiagramObject, family: str, size_px: float, color: str):
        faces, archive = self._font_face_css(family, obj.bold, obj.italic)
        fam = "PMFace" if faces else "sans-serif"
        css = (faces +
               f"body{{font-family:{fam};font-size:{size_px:.3f}pt;color:{color};"
               f"font-weight:{'bold' if obj.bold else 'normal'};"
               f"font-style:{'italic' if obj.italic else 'normal'};"
               f"text-decoration:{'underline' if obj.underline else 'none'};"
               f"text-align:{obj.h_align or 'left'};line-height:normal;margin:0;}}"
               "p{margin:0;}")
        paras = "".join(f"<p>{_html_escape(line) or '&#160;'}</p>"
                        for line in obj.text.split("\n"))
        return f"<body>{paras}</body>", css, archive

    @staticmethod
    def _html_height(html: str, css: str, archive, width: float) -> float:
        story = fitz.Story(html, user_css=css, archive=archive)
        _, filled = story.place(fitz.Rect(0, 0, width, 1e6))
        return fitz.Rect(filled).y1

    # Rich text for editors that regenerate FreeText appearances (Bluebeam,
    # Acrobat): they lay the text out again from /RC with installed fonts.
    @staticmethod
    def _span_style(obj, family, size_pt, color) -> str:
        return (f"font-family:'{_css_escape(family)}';font-size:{size_pt:g}pt;color:{color};"
                f"font-weight:{'bold' if obj.bold else 'normal'};"
                f"font-style:{'italic' if obj.italic else 'normal'};"
                f"text-decoration:{'underline' if obj.underline else 'none'}")

    def _ds(self, family, size_pt, color, obj) -> str:
        return (self._span_style(obj, family, size_pt, color)
                + f";text-align:{obj.h_align or 'left'}")

    def _rc(self, obj, family, size_pt, color) -> str:
        span = self._span_style(obj, family, size_pt, color)
        paras = "".join(
            f'<p dir="ltr" style="text-align:{obj.h_align or "left"}">'
            f'<span style="{span}">{_html_escape(line)}</span></p>'
            for line in obj.text.split("\n"))
        return ('<?xml version="1.0"?>'
                '<body xmlns="http://www.w3.org/1999/xhtml" '
                'xmlns:xfa="http://www.xfa.org/schema/xfa-data/1.0/" '
                'xfa:APIVersion="Acrobat:11.0.0" xfa:spec="2.0.2" '
                f'style="{span}">{paras}</body>')

    # -- derived markups --------------------------------------------------------

    def write_contours(self):
        """One Ink markup per merged contour level: every ring of that level's
        union as a stroke of a single editable markup."""
        objs = [o for o in self.m.objects if o.is_contour]
        if not objs:
            return []
        groups = contours.build_contour_groups(
            objs, self.m.scale.scale_factor, default_color=self.exp.style.contour_color)
        for g in groups:
            rings = []
            for exterior, interiors in g["polygons"]:
                rings.append(exterior)
                rings.extend(interiors)
            rings = [r for r in rings if len(r) >= 2]
            if not rings:
                continue
            color, w = g["color"], float(g.get("width", 2) or 2)
            annot = self.page.add_ink_annot([[tuple(self.unrot(x, y)) for x, y in r] for r in rings])
            annot.set_colors(stroke=_rgb(color))
            annot.set_border(width=w * self.k)
            annot.update()
            self._common(annot, None, "Contour", g["reference"],
                         {"version": FORMAT_VERSION, "derived": "contour",
                          "reference": g["reference"]})
            vrect = self._bounds([p for r in rings for p in r]) + (-w, -w, w, w)

            def draw(c: _Canvas, rings=rings, color=color, w=w):
                for r in rings:
                    c.polyline(r, color, w)
            self._appearance(annot, vrect, draw)
        return groups

    def write_legend(self, groups):
        if not groups or not self.m.legend_visible:
            return
        st, fonts = self.exp.style, self.exp.fonts
        fam, px = st.label_family, st.label_px
        asc, desc = fonts.line_metrics(px, fam)
        tasc, _ = fonts.line_metrics(px, fam, bold=True)
        fh = asc + desc
        line_h = fh + 4
        swatch_w, gap, pad, margin = 26, 6, 8, 12
        title = self.m.legend_title or "Legend"
        max_text = fonts.text_width(title, px, fam, bold=True)
        for g in groups:
            max_text = max(max_text, swatch_w + gap + fonts.text_width(g["reference"], px, fam))
        box_w = pad * 2 + max_text
        box_h = pad * 2 + line_h * (len(groups) + 1)
        page_w = self.page.rect.width / self.k     # visual page size, image px
        x, y = page_w - box_w - margin, margin
        rect = fitz.Rect(x, y, x + box_w, y + box_h)

        annot = self.page.add_stamp_annot(self.unrot_rect(rect), stamp=0)
        self.doc.xref_set_key(annot.xref, "Name", "/VellumLegend")
        self._common(annot, None, "Legend", title + "\n" + "\n".join(g["reference"] for g in groups),
                     {"version": FORMAT_VERSION, "derived": "legend"})

        def draw(c: _Canvas):
            c.rect(rect, st.legend_border, 1, fill=st.legend_bg)
            cx = x + pad
            c.text(cx, y + pad + tasc, title, st.legend_ink, px, fam, bold=True)
            for i, g in enumerate(groups, start=1):
                top = y + pad + line_h * i
                sw = max(1.0, min(float(g.get("width", 3) or 3), fh))
                sy = top + fh / 2
                c.polyline([(cx, sy), (cx + swatch_w, sy)], g["color"], sw)
                c.text(cx + swatch_w + gap, top + asc, g["reference"], st.legend_ink, px, fam)
        self._appearance(annot, rect + (-1, -1, 1, 1), draw, inner=rect)


class _Exporter:
    def __init__(self, doc: fitz.Document, dpi: float, style: ExportStyle,
                 resolver: FontResolver):
        self.doc = doc
        self.dpi = float(dpi)
        self.style = style
        self.report = ExportReport()
        self.fonts = _Fonts(resolver, self.report)
        self.scratch = fitz.open()
        # (annotation xref, scratch page number, unrotated rect, rotation,
        #  /Rect, /RD or None)
        self.jobs: List[tuple] = []
        try:
            self.author = getpass.getuser()
        except Exception:
            self.author = "Vellum"

    def write(self, pages: List[PageMarkup]):
        for m in pages:
            if not 0 <= m.index < len(self.doc):
                continue
            w = _PageWriter(self, self.doc[m.index], m)
            w.write_page_data()
            groups = w.write_contours()
            for i, obj in enumerate(m.objects):
                w.write_object(i, obj)
            w.write_legend(groups)
            self.report.pages += 1
        self._build_appearances()

    def _build_appearances(self):
        """Turn each scratch drawing into its annotation's appearance stream.
        A holder page sized like the annotation in unrotated space receives
        the drawing: show_pdf_page scales px -> pt, turns the drawing against
        the page rotation so it reads upright, and copies the fonts and other
        resources into the document. The holder's content and resources then
        become the annotation's form XObject."""
        doc = self.doc
        # Embed only the glyphs used. Done on the scratch document so the
        # source file's own fonts (which form fields may type with) are left
        # whole.
        if self.jobs:
            self.scratch.subset_fonts()
        first = len(doc)
        for xref, scratch_no, urect, rot, outer, rd in self.jobs:
            holder = doc.new_page(width=urect.width, height=urect.height)
            holder.show_pdf_page(holder.rect, self.scratch, scratch_no, rotate=rot)
            contents = holder.read_contents()
            kind, res = doc.xref_get_key(holder.xref, "Resources")
            res = res if kind in ("dict", "xref") else "<<>>"
            ap = doc.get_new_xref()
            doc.update_object(ap, (f"<</Type/XObject/Subtype/Form/BBox[0 0 {_pdf_num(urect.width)} "
                                   f"{_pdf_num(urect.height)}]/Matrix[1 0 0 1 0 0]/Resources {res}>>"))
            doc.update_stream(ap, contents)
            doc.xref_set_key(xref, "AP", f"<</N {ap} 0 R>>")
            doc.xref_set_key(xref, "Rect", _pdf_array(outer))
            if rd is not None:
                doc.xref_set_key(xref, "RD", _pdf_array(rd))
        if len(doc) > first:
            doc.delete_pages(first, len(doc) - 1)


def _open_source(source_path: str | bytes, dpi: float) -> fitz.Document:
    """The source as a PDF: PDF bytes (a blank page never saved to disk) or a
    PDF file open as-is; an image becomes a one-page PDF whose page is the
    image at `dpi`."""
    if isinstance(source_path, bytes):
        return fitz.open("pdf", source_path)
    if source_path.lower().endswith(".pdf"):
        return fitz.open(source_path)
    pix = fitz.Pixmap(source_path)
    k = 72.0 / dpi
    doc = fitz.open()
    page = doc.new_page(width=pix.width * k, height=pix.height * k)
    page.insert_image(page.rect, filename=source_path)
    return doc


def export_pdf(source_path: str | bytes, out_path: str, pages: List[PageMarkup], dpi: float,
               style: ExportStyle, resolver: FontResolver) -> ExportReport:
    """Write `source_path` with `pages`' objects as native annotations to
    `out_path` (which must differ from `source_path`)."""
    doc = _open_source(source_path, dpi)
    try:
        exp = _Exporter(doc, dpi, style, resolver)
        exp.write(pages)
        # garbage=4 merges the identical font programs that every appearance
        # brings with it, so each font is stored once.
        doc.save(out_path, garbage=4, deflate=True)
        return exp.report
    finally:
        doc.close()
