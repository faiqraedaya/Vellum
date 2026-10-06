# Vellum

## Overview
*Vellum is a desktop application for marking up images and PDF drawings. Set a real-world scale, then annotate the drawing with measurements, shapes, text and risk contours, and export the markups as native, editable PDF annotations.*

## Features
- Opens PNG, JPEG, BMP and TIFF images and multi-page PDFs, each in its own tab
- Blank pages from paper presets (A5–A0, Letter, Legal, Tabloid), screen presets, or a custom size, resolution and aspect ratio
- Coordinate origin and scale set by a known distance or known point coordinates
- Labelled points, lines, angles, polygons (area and perimeter), polylines, ellipses and text boxes
- Risk contours around a polyline or point, with up to 20 levels of reference, distance and colour
- Contours with the same reference merge into one outer boundary
- Undo and redo, cut, copy and paste, and keyboard shortcuts for every tool
- Sessions saved and loaded as JSON
- Measurement export to CSV, JSON or the clipboard, and view export to PNG or JPEG
- PDF export with every markup as a native, editable PDF annotation (Bluebeam Revu, Acrobat)

## Install
```bash
git clone https://github.com/faiqraedaya/Vellum
cd Vellum
uv sync
```

## Usage
```bash
uv run main.py
```
Open a drawing with Ctrl+O, or start a blank page with Ctrl+N. Press F1 to list every command. Press S and click two points of known length to set the scale, then press L to measure a line, or A to draw a polygon and read its area. Press Ctrl+E to export the measurements, or Ctrl+S to save the session.

## Technical details
Inputs are raster images or PDFs. PDF pages are rendered with PyMuPDF at 150 dpi by default. Measurements are taken in image pixels and converted to world units through the scale (pixel distance to real distance, with a unit) and origin.

Risk contours are built with Shapely. Each level buffers the polyline or point by its distance in pixels with round caps and joins. Levels that share a reference are merged with unary_union, so overlapping contours from different objects form a single boundary.

A session is a JSON file holding the scale, the origin, an optional legend title and a list of objects. Each object records its kind (point, distance, angle, polygon, polyline, ellipse, textbox, polyline_contour or point_contour), name, image points, value, unit, timestamp and style. Text boxes also store text and font settings, and contours store their levels. Legacy "area" objects load as polygons. The data export writes one row per object with type, name, value, unit, measurements, timestamp, levels, world points and image points.

The PDF export (Ctrl+Shift+P) writes each object as a standard PDF annotation: lines, polylines and angles as Line and PolyLine, polygons as Polygon, ellipses and points as Circle, text boxes as FreeText with rich text, merged contour levels as Ink, and the legend as a Stamp. Measurements carry the PDF measurement dictionary (`/Measure`, with `/IT` set to `LineDimension`, `PolyLineDimension` or `PolygonDimension`), and each calibrated page carries its scale as a viewport (`/VP`). Every annotation has an appearance stream drawn as the canvas draws it at 100 % zoom, labels included, with the fonts embedded and subset. Each annotation's `/NM` is its object's id and its full definition is stored as JSON under the private key `/Vellum`. An image is first placed on a PDF page at the render resolution. Text box sizes are in page points.

## License
MIT — see [LICENSE](LICENSE).
