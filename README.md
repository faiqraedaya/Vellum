# PyMeasure

## Overview
*PyMeasure is a desktop application for taking scaled measurements from images and PDF drawings. Set a real-world scale, then measure and annotate distances, angles, areas and risk contours directly on the drawing.*

## Features
- Opens PNG, JPEG, BMP and TIFF images and multi-page PDFs, each in its own tab
- Coordinate origin and scale set by a known distance or known point coordinates
- Labelled points, lines, angles, polygons (area and perimeter), polylines, ellipses and text boxes
- Risk contours around a polyline or point, with up to 20 levels of reference, distance and colour
- Contours with the same reference merge into one outer boundary
- Undo and redo, cut, copy and paste, and keyboard shortcuts for every tool
- Sessions saved and loaded as JSON
- Measurement export to CSV, JSON or the clipboard, and view export to PNG or JPEG

## Install
```bash
git clone https://github.com/faiqraedaya/PyMeasure
cd PyMeasure
uv sync
```

## Usage
```bash
uv run main.py
```
Open a drawing with Ctrl+O, press S and click two points of known length to set the scale. Press L to measure a line, or A to draw a polygon and read its area. Press Ctrl+E to export the measurements, or Ctrl+S to save the session.

## Technical details
Inputs are raster images or PDFs. PDF pages are rendered with PyMuPDF at 150 dpi by default. Measurements are taken in image pixels and converted to world units through the scale (pixel distance to real distance, with a unit) and origin.

Risk contours are built with Shapely. Each level buffers the polyline or point by its distance in pixels with round caps and joins. Levels that share a reference are merged with unary_union, so overlapping contours from different objects form a single boundary.

A session is a JSON file holding the scale, the origin, an optional legend title and a list of objects. Each object records its kind (point, distance, angle, polygon, polyline, ellipse, textbox, polyline_contour or point_contour), name, image points, value, unit, timestamp and style. Text boxes also store text and font settings, and contours store their levels. Legacy "area" objects load as polygons. The data export writes one row per object with type, name, value, unit, measurements, timestamp, levels, world points and image points.

## License
MIT — see [LICENSE](LICENSE).
