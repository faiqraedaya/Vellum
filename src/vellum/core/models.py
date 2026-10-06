import math
import uuid
from datetime import datetime
from dataclasses import dataclass, field


@dataclass
class Point:
    """Internal coordinate type used for temp points and origin only."""
    x: float
    y: float
    label: str = ""

    def distance_to(self, other: "Point") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "label": self.label}

    @classmethod
    def from_dict(cls, d: dict) -> "Point":
        return cls(d["x"], d["y"], d.get("label", ""))


@dataclass
class ScaleInfo:
    pixel_distance: float = 1.0
    real_distance: float = 1.0
    unit: str = "px"

    @property
    def scale_factor(self) -> float:
        return self.real_distance / self.pixel_distance if self.pixel_distance > 0 else 1.0

    def to_dict(self) -> dict:
        return {
            "pixel_distance": self.pixel_distance,
            "real_distance": self.real_distance,
            "unit": self.unit,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ScaleInfo":
        return cls(d["pixel_distance"], d["real_distance"], d["unit"])


@dataclass
class DiagramObject:
    """A persistent diagram annotation: point, distance, angle, polygon, polyline,
    ellipse, text box, or a risk contour (polyline_contour / point_contour)."""
    kind: str        # "point" | "distance" | "angle" | "polygon" | "polyline" |
                     # "ellipse" | "textbox" | "polyline_contour" | "point_contour"
    name: str = ""
    points: list = field(default_factory=list)   # [[x, y], ...] image coords
    unit: str = "px"
    value: float = 0.0   # pre-computed measurement value; unused for points
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    # Contour levels: [{"reference": str, "distance": float, "color": "#rrggbb"}]
    levels: list = field(default_factory=list)
    # Per-object line color override for non-contour objects ("" = kind default)
    color: str = ""
    # Line styling (applies to every line-based object; ignored for points)
    line_width: float = 0.0          # 0 → kind default (2.0)
    line_style: str = "solid"        # solid | dashed | dotted | dashdot
    # Text box content + styling ("" = unset / use default / no fill)
    text: str = ""
    font_family: str = ""
    font_size: int = 0               # 0 → default (12)
    font_color: str = ""
    fill_color: str = ""             # "" → no fill (transparent)
    # Text formatting (text boxes)
    bold: bool = False
    italic: bool = False
    underline: bool = False
    h_align: str = "left"            # left | center | right
    v_align: str = "top"             # top | middle | bottom
    # Secondary measurements keyed by name (e.g. {"area": .., "perimeter": ..});
    # `value`/`unit` hold the primary one for backward compatibility.
    measures: dict = field(default_factory=dict)
    # Stable identity, written as the PDF annotation's /NM so an exported
    # markup can be matched back to its object after editing elsewhere.
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)

    def renew_uid(self) -> None:
        """Give a copied object an identity of its own."""
        self.uid = uuid.uuid4().hex

    @property
    def is_contour(self) -> bool:
        return self.kind in ("polyline_contour", "point_contour")

    def _levels_summary(self) -> str:
        n = len(self.levels)
        return f"{n} level{'s' if n != 1 else ''}"

    def _text_preview(self) -> str:
        first = (self.text or "").strip().splitlines()
        snippet = first[0] if first else ""
        return (snippet[:20] + "…") if len(snippet) > 20 else snippet

    def measurements(self) -> list:
        """Ordered [(label, value_string)] measurements for this object, derived
        from `measures` (falling back to the primary `value` for older data)."""
        u = self.unit
        m = self.measures or {}
        if self.kind in ("distance", "polyline"):
            return [("Length", f"{m.get('length', self.value):.4g} {u}")]
        if self.kind == "angle":
            return [("Angle", f"{m.get('angle', self.value):.2f}°")]
        if self.kind == "polygon":
            out = [("Area", f"{m.get('area', self.value):.4g} {u}²")]
            if "perimeter" in m:
                out.append(("Perimeter", f"{m['perimeter']:.4g} {u}"))
            return out
        if self.kind == "ellipse":
            out = [("Circumference", f"{m.get('circumference', self.value):.4g} {u}")]
            dmaj, dmin = m.get("diameter_major"), m.get("diameter_minor")
            if dmaj is not None and dmin is not None:
                if abs(dmaj - dmin) < 1e-9:
                    out.append(("Diameter", f"{dmaj:.4g} {u}"))
                else:
                    out.append(("Diameter", f"{dmaj:.4g} × {dmin:.4g} {u}"))
            if "area" in m:
                out.append(("Area", f"{m['area']:.4g} {u}²"))
            return out
        return []

    def _measure_inline(self) -> str:
        """One-line join of all measurements (for lists / status / export)."""
        ms = self.measurements()
        if not ms:
            return ""
        if len(ms) == 1:
            return ms[0][1]
        return ", ".join(f"{lbl} {val}" for lbl, val in ms)

    def list_label(self) -> str:
        """Short label for the objects panel list.

        Text only: the kind is shown by the row's icon, drawn from the app's
        one icon family rather than by a symbol character picked from whatever
        font happens to have one.
        """
        name = self.name if self.name else self.kind.capitalize()
        if self.is_contour:
            return f"{name}: {self._levels_summary()}"
        if self.kind == "textbox":
            preview = self._text_preview()
            return f"{name}: {preview}" if preview else name
        inline = self._measure_inline()
        return f"{name}: {inline}" if inline else name

    def display_short(self) -> str:
        """Compact value label drawn on the canvas."""
        return self._measure_inline() or self.name

    def display(self) -> str:
        """Full string for export / status bar."""
        ts = f"[{self.timestamp}] " if self.timestamp else ""
        name = self.name or self.kind.capitalize()
        if self.is_contour:
            return f"{ts}{name}: {self._levels_summary()}"
        if self.kind == "point":
            c = f"({self.points[0][0]:.4f}, {self.points[0][1]:.4f})" if self.points else ""
            return f"{ts}{name} {c}".strip()
        if self.kind == "textbox":
            return f"{ts}{name}: {self.text}".rstrip(": ")
        inline = self._measure_inline()
        return f"{ts}{name}: {inline}" if inline else f"{ts}{name}"

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "name": self.name,
            "points": self.points,
            "unit": self.unit,
            "value": self.value,
            "timestamp": self.timestamp,
            "levels": self.levels,
            "color": self.color,
            "line_width": self.line_width,
            "line_style": self.line_style,
            "text": self.text,
            "font_family": self.font_family,
            "font_size": self.font_size,
            "font_color": self.font_color,
            "fill_color": self.fill_color,
            "bold": self.bold,
            "italic": self.italic,
            "underline": self.underline,
            "h_align": self.h_align,
            "v_align": self.v_align,
            "measures": self.measures,
            "uid": self.uid,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DiagramObject":
        kind = d["kind"]
        if kind == "area":          # legacy name → polygon
            kind = "polygon"
        return cls(
            kind=kind,
            name=d.get("name", d.get("label", "")),
            points=d.get("points", []),
            unit=d.get("unit", "px"),
            value=d.get("value", 0.0),
            timestamp=d.get("timestamp", ""),
            levels=d.get("levels", []),
            color=d.get("color", ""),
            line_width=d.get("line_width", 0.0),
            line_style=d.get("line_style", "solid"),
            text=d.get("text", ""),
            font_family=d.get("font_family", ""),
            font_size=d.get("font_size", 0),
            font_color=d.get("font_color", ""),
            fill_color=d.get("fill_color", ""),
            bold=d.get("bold", False),
            italic=d.get("italic", False),
            underline=d.get("underline", False),
            h_align=d.get("h_align", "left"),
            v_align=d.get("v_align", "top"),
            measures=d.get("measures", {}),
            uid=d.get("uid") or uuid.uuid4().hex,
        )
