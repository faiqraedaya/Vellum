"""Risk-contour geometry: offset (buffer) a polyline/point by a distance and
merge same-reference contours from different objects into a single outer
boundary.

All geometry is computed in *image* coordinates with distances in *pixels*.
Built on shapely (buffer = Minkowski sum with a disk = rounded offset; and
unary_union = merge overlapping shapes into one outer boundary).
"""
from typing import List, Tuple

from shapely.geometry import LineString, Point as SPoint
from shapely.ops import unary_union

# Number of segments per quarter circle when buffering (smoothness of arcs).
_QUAD_SEGS = 16

# Stroke width used when a contour level doesn't define its own.
DEFAULT_CONTOUR_WIDTH = 2.0

# (exterior, interiors): exterior is a list of (x, y); interiors is a list of
# rings, each a list of (x, y).
Polygon = Tuple[List[Tuple[float, float]], List[List[Tuple[float, float]]]]


def level_geometry(kind: str, points_img: list, dist_px: float):
    """Return a shapely geometry for one contour level, or None if it can't be
    built (too few points, non-positive distance)."""
    if dist_px <= 0:
        return None
    try:
        if kind == "point_contour":
            if not points_img:
                return None
            x, y = points_img[0]
            return SPoint(x, y).buffer(dist_px, quad_segs=_QUAD_SEGS)
        if kind == "polyline_contour":
            if len(points_img) < 2:
                return None
            line = LineString([(p[0], p[1]) for p in points_img])
            return line.buffer(
                dist_px, quad_segs=_QUAD_SEGS,
                cap_style="round", join_style="round",
            )
    except Exception:
        return None
    return None


def _geom_to_polygons(geom) -> List[Polygon]:
    """Flatten a (possibly Multi) shapely polygonal geometry to our format."""
    if geom is None or geom.is_empty:
        return []
    out: List[Polygon] = []
    geoms = getattr(geom, "geoms", None)
    parts = list(geoms) if geoms is not None else [geom]
    for part in parts:
        if getattr(part, "geom_type", "") != "Polygon":
            continue
        exterior = [(x, y) for x, y in part.exterior.coords]
        interiors = [[(x, y) for x, y in ring.coords] for ring in part.interiors]
        out.append((exterior, interiors))
    return out


def _ref_key(reference: str) -> str:
    """Normalize a reference label so contours that mean the same thing merge
    despite trivial formatting differences (case and runs of whitespace).
    e.g. '1E-03', '1e-03' and '1E-03  LSIR' / '1E-03 LSIR' match accordingly."""
    return " ".join(str(reference).split()).casefold()


def build_contour_groups(contour_objs: list, scale_factor: float,
                         default_color: str = "") -> list:
    """Group contour levels across all contour objects by reference label,
    union each group, and return an ordered list of:

        {"reference": str, "color": "#rrggbb", "polygons": [Polygon, ...]}

    Matching is case-insensitive and whitespace-normalized (see `_ref_key`), so
    contours sharing the same label merge into one outer boundary even if typed
    with different case/spacing. Distances (world units) are converted to pixels
    via `scale_factor` (world units per pixel). The displayed reference, color
    and stroke width for a group come from the first level that defines it
    (insertion order), so the legend maps reference -> one color/width.
    """
    sf = scale_factor if scale_factor and scale_factor > 0 else 1.0

    order: List[str] = []   # group keys, in first-seen order
    geoms: dict = {}        # key -> [shapely geoms]
    display: dict = {}      # key -> first-seen reference label (for the legend)
    colors: dict = {}       # key -> color of first level seen
    widths: dict = {}       # key -> stroke width of first level seen

    for obj in contour_objs:
        for level in obj.levels:
            ref = str(level.get("reference", "")).strip()
            key = _ref_key(ref)
            dist_world = float(level.get("distance", 0.0) or 0.0)
            dist_px = dist_world / sf
            geom = level_geometry(obj.kind, obj.points, dist_px)
            if geom is None:
                continue
            if key not in geoms:
                geoms[key] = []
                display[key] = ref
                # A level normally carries its own colour. The fallback is
                # passed in rather than named here: core computes geometry and
                # has no opinion about how it is drawn.
                colors[key] = level.get("color") or default_color
                w = float(level.get("width", 0.0) or 0.0)
                widths[key] = w if w > 0 else DEFAULT_CONTOUR_WIDTH
                order.append(key)
            geoms[key].append(geom)

    groups = []
    for key in order:
        merged = unary_union(geoms[key])
        polygons = _geom_to_polygons(merged)
        if not polygons:
            continue
        groups.append({
            "reference": display[key],
            "color": colors[key],
            "width": widths[key],
            "polygons": polygons,
        })
    return groups
