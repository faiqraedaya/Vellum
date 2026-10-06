from enum import Enum


class Tool(Enum):
    PAN                  = "pan"
    SELECT               = "select"
    ZOOM_RECT            = "zoom_rect"
    SET_ORIGIN           = "set_origin"
    SET_SCALE_DISTANCE   = "set_scale_distance"
    SET_SCALE_COORDS     = "set_scale_coords"
    ADD_POINT            = "add_point"
    ADD_LINE             = "add_line"
    ADD_ANGLE            = "add_angle"
    ADD_POLYGON          = "add_polygon"
    ADD_POLYLINE         = "add_polyline"
    ADD_ELLIPSE          = "add_ellipse"
    ADD_TEXTBOX          = "add_textbox"
    ADD_POLYLINE_CONTOUR = "add_polyline_contour"
    ADD_POINT_CONTOUR    = "add_point_contour"


TOOL_LABELS = {
    Tool.PAN:                "Pan / zoom",
    Tool.SELECT:             "Select",
    Tool.ZOOM_RECT:          "Zoom rectangle",
    Tool.SET_ORIGIN:         "Set origin",
    Tool.SET_SCALE_DISTANCE: "Scale – distance",
    Tool.SET_SCALE_COORDS:   "Scale – coordinates",
    Tool.ADD_POINT:          "Add point",
    Tool.ADD_LINE:           "Add line",
    Tool.ADD_ANGLE:          "Add angle",
    Tool.ADD_POLYGON:        "Add polygon",
    Tool.ADD_POLYLINE:       "Add polyline",
    Tool.ADD_ELLIPSE:        "Add ellipse",
    Tool.ADD_TEXTBOX:        "Add text box",
    Tool.ADD_POLYLINE_CONTOUR: "Add polyline contour",
    Tool.ADD_POINT_CONTOUR:    "Add point contour",
}

TOOL_SHORTCUTS = {
    Tool.PAN:                "Space",
    Tool.SELECT:             "V",
    Tool.ZOOM_RECT:          "Z",
    Tool.SET_ORIGIN:         "O",
    Tool.SET_SCALE_DISTANCE: "S",
    Tool.SET_SCALE_COORDS:   "C",
    Tool.ADD_POINT:          "T",
    Tool.ADD_LINE:           "L",
    Tool.ADD_ANGLE:          "G",
    Tool.ADD_POLYGON:        "A",
    Tool.ADD_POLYLINE:       "N",
    Tool.ADD_ELLIPSE:        "E",
    Tool.ADD_TEXTBOX:        "B",
    Tool.ADD_POLYLINE_CONTOUR: "K",
    Tool.ADD_POINT_CONTOUR:    "P",
}

TOOL_HELP = {
    Tool.PAN:                "Pan / zoom — drag to pan · scroll to zoom · Ctrl+0 to fit",
    Tool.SELECT:             "Select — click an object or drag a box to select · middle-drag to pan · Ctrl+drag to add",
    Tool.ZOOM_RECT:          "Zoom rectangle — drag to draw a rectangle and zoom into it",
    Tool.SET_ORIGIN:         "Set origin — click to place the coordinate origin",
    Tool.SET_SCALE_DISTANCE: "Scale (distance) — click 2 points of known distance",
    Tool.SET_SCALE_COORDS:   "Scale (coordinates) — click 2 points of known coordinates",
    Tool.ADD_POINT:          "Add point — click to add a labelled point",
    Tool.ADD_LINE:           "Add line — click 2 points to measure a straight line",
    Tool.ADD_ANGLE:          "Add angle — click 3 points (middle point is the vertex)",
    Tool.ADD_POLYGON:        "Add polygon — click vertices · double-click or right-click to close",
    Tool.ADD_POLYLINE:       "Add polyline — click vertices · double-click or right-click to finish",
    Tool.ADD_ELLIPSE:        "Add ellipse — click 2 corners of the bounding box · hold Shift for a circle",
    Tool.ADD_TEXTBOX:        "Add text box — click 2 corners of the box · then enter text and style",
    Tool.ADD_POLYLINE_CONTOUR: "Add polyline contour — click vertices · double-click to finish · then define contour levels",
    Tool.ADD_POINT_CONTOUR:    "Add point contour — click a point · then define contour levels",
}

# Mouse and keyboard gestures on the canvas that have no menu entry, for the
# Commands window. (Command, shortcut or gesture.)
CANVAS_GESTURES = (
    ("Pan", "Middle-drag, or drag with Pan / zoom"),
    ("Zoom in or out", "Scroll wheel"),
    ("Finish a polygon or polyline", "Double-click or right-click"),
    ("Lock to horizontal or vertical", "Hold Shift while placing"),
    ("Draw a circle", "Hold Shift with Add ellipse"),
    ("Add to the selection", "Ctrl+click or Ctrl+drag"),
    ("Move a vertex", "Drag its handle on a selected object"),
    ("Delete a vertex", "Right-click the vertex"),
    ("Insert a vertex", "Right-click an edge"),
    ("Edit an object", "Double-click it in the objects list"),
    ("Nudge the selection", "Arrow keys · Shift+arrow for 10 px"),
)
