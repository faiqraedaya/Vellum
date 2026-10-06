# -*- mode: python ; coding: utf-8 -*-
#
# Directory-bundle build for Vellum.
# App imports: PySide6 (QtCore/QtGui/QtWidgets/QtSvg), PyMuPDF (fitz), and
# Shapely (risk-contour geometry; pulls in numpy + the GEOS native libs).
# Stdlib only otherwise. PyInstaller's built-in PySide6/pymupdf/numpy hooks and
# the contributed hook-shapely (bundles geos_c.dll from shapely.libs) handle
# the data files and native libraries automatically.
#
# QtSvg is NOT excluded: gui/icons.py renders the whole icon set from SVG path
# data at runtime through QSvgRenderer. The bundled Inter faces ship as data
# for the same reason - a design system that is not in the bundle is not in
# the product.

# Qt ships ~100 submodules. Exclude everything outside
# Core/Gui/Widgets/Network/Svg. (Network stays so the QtCore hook resolves
# cleanly even though we don't use it; Svg draws every icon in the app.)
EXCLUDED_QT = [
    'PySide6.Qt3DAnimation', 'PySide6.Qt3DCore', 'PySide6.Qt3DExtras',
    'PySide6.Qt3DInput', 'PySide6.Qt3DLogic', 'PySide6.Qt3DRender',
    'PySide6.QtBluetooth', 'PySide6.QtCharts', 'PySide6.QtConcurrent',
    'PySide6.QtDataVisualization', 'PySide6.QtDBus', 'PySide6.QtDesigner',
    'PySide6.QtGraphs', 'PySide6.QtGraphsWidgets', 'PySide6.QtHelp',
    'PySide6.QtHttpServer', 'PySide6.QtLocation', 'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets', 'PySide6.QtNetworkAuth', 'PySide6.QtNfc',
    'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets', 'PySide6.QtPdf',
    'PySide6.QtPdfWidgets', 'PySide6.QtPositioning', 'PySide6.QtPrintSupport',
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuick3D',
    'PySide6.QtQuick3DAssetImport', 'PySide6.QtQuick3DAssetUtils',
    'PySide6.QtQuick3DEffects', 'PySide6.QtQuick3DHelpers',
    'PySide6.QtQuick3DHelpersImpl', 'PySide6.QtQuick3DParticleEffects',
    'PySide6.QtQuick3DParticles', 'PySide6.QtQuick3DPhysics',
    'PySide6.QtQuick3DPhysicsHelpers', 'PySide6.QtQuick3DRuntimeRender',
    'PySide6.QtQuick3DUtils', 'PySide6.QtQuick3DXr', 'PySide6.QtQuickControls2',
    'PySide6.QtQuickControls2Impl', 'PySide6.QtQuickDialogs2',
    'PySide6.QtQuickDialogs2QuickImpl', 'PySide6.QtQuickDialogs2Utils',
    'PySide6.QtQuickEffects', 'PySide6.QtQuickLayouts',
    'PySide6.QtQuickParticles', 'PySide6.QtQuickShapes',
    'PySide6.QtQuickTemplates2', 'PySide6.QtQuickTest', 'PySide6.QtQuickWidgets',
    'PySide6.QtRemoteObjects', 'PySide6.QtScxml', 'PySide6.QtSensors',
    'PySide6.QtSerialBus', 'PySide6.QtSerialPort', 'PySide6.QtSpatialAudio',
    'PySide6.QtSql', 'PySide6.QtStateMachine',
    'PySide6.QtSvgWidgets', 'PySide6.QtTest', 'PySide6.QtTextToSpeech',
    'PySide6.QtUiTools', 'PySide6.QtVirtualKeyboard', 'PySide6.QtWebChannel',
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineQuick',
    'PySide6.QtWebEngineWidgets', 'PySide6.QtWebSockets', 'PySide6.QtWebView',
    'PySide6.QtXml',
]

# Matplotlib / scientific stack are not imported, but listing them keeps the
# build defensive against future deps pulling them in transitively.
# NOTE: numpy must NOT be excluded — Shapely 2.x imports it at runtime, so the
# builtin numpy hook needs to collect it (numpy.f2py stays excluded; unused).
EXCLUDED_OTHER = [
    'tkinter', '_tkinter', 'Tkinter',
    'PyQt5', 'PyQt6', 'PySide2',
    'numpy.f2py', 'scipy', 'pandas', 'IPython', 'jupyter',
    'matplotlib', 'matplotlib.backends.backend_tk',
    'matplotlib.backends.backend_tkagg', 'matplotlib.backends.backend_tkcairo',
    'matplotlib.backends.backend_wx', 'matplotlib.backends.backend_wxagg',
    'matplotlib.backends.backend_wxcairo', 'matplotlib.backends.backend_gtk3',
    'matplotlib.backends.backend_gtk3agg', 'matplotlib.backends.backend_gtk3cairo',
    'matplotlib.backends.backend_gtk4', 'matplotlib.backends.backend_gtk4agg',
    'matplotlib.backends.backend_gtk4cairo', 'matplotlib.backends.backend_webagg',
    'matplotlib.backends.backend_webagg_core', 'matplotlib.backends.backend_nbagg',
    'matplotlib.backends.backend_macosx',
    'pytest', 'unittest', 'test', 'tests',
]

# Qt plugin folders to drop. Keep: platforms (windowing), styles (Fusion look),
# imageformats (PNG/JPG/BMP/TIFF), iconengines (menu icons).
EXCLUDED_QT_PLUGINS = [
    'qml', 'qmltooling', 'multimedia', 'mediaservice', 'audio',
    'position', 'sensors', 'sensorgestures', 'sqldrivers',
    'webview', 'designer', 'assetimporters', 'renderplugins',
    'scenegraph', 'scxmldatamodel', 'canbus', 'tls',
    'networkinformation', 'networkaccess', 'geometryloaders',
    'virtualkeyboard', 'texttospeech',
]

# Raw Qt DLLs that get pulled in transitively but aren't actually used.
# opengl32sw.dll is the Mesa software-OpenGL fallback (~20 MB) — safe to drop
# on machines with working GPU drivers.
EXCLUDED_DLLS = {
    'opengl32sw.dll',
    'Qt6Quick.dll', 'Qt6QuickControls2.dll', 'Qt6QuickControls2Impl.dll',
    'Qt6QuickDialogs2.dll', 'Qt6QuickDialogs2QuickImpl.dll',
    'Qt6QuickDialogs2Utils.dll', 'Qt6QuickLayouts.dll',
    'Qt6QuickParticles.dll', 'Qt6QuickShapes.dll', 'Qt6QuickTemplates2.dll',
    'Qt6QuickTest.dll', 'Qt6QuickWidgets.dll', 'Qt6QuickEffects.dll',
    'Qt6Qml.dll', 'Qt6QmlMeta.dll', 'Qt6QmlModels.dll',
    'Qt6QmlWorkerScript.dll', 'Qt6QmlLocalStorage.dll',
    'Qt6Pdf.dll', 'Qt6PdfQuick.dll',
    'Qt6OpenGL.dll',
    'Qt6VirtualKeyboard.dll', 'Qt6LabsQmlModels.dll',
    'Qt6LabsAnimation.dll', 'Qt6LabsFolderListModel.dll',
    'Qt6LabsSettings.dll', 'Qt6LabsSharedImage.dll',
    'Qt6LabsWavefrontMesh.dll',
}

# UPX corrupts these on Windows — leave them uncompressed.
UPX_EXCLUDE = [
    'vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll',
    'python3.dll', 'python313.dll', 'python312.dll', 'python311.dll',
    'Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Widgets.dll', 'Qt6Network.dll',
    'Qt6Svg.dll', 'Qt6DBus.dll',
    'qwindows.dll', 'qwindowsvistastyle.dll', 'qmodernwindowsstyle.dll',
    'qdirect2d.dll',
]


def _filter_qt(items):
    out = []
    for item in items:
        dest = item[0].replace('\\', '/')
        name = dest.rsplit('/', 1)[-1]
        if name in EXCLUDED_DLLS:
            continue
        if any(f'/plugins/{p}/' in dest or dest.startswith(f'PySide6/plugins/{p}/')
               for p in EXCLUDED_QT_PLUGINS):
            continue
        if '/translations/' in dest or dest.endswith('.qm'):
            continue
        if '/qml/' in dest or dest.startswith('PySide6/qml/'):
            continue
        out.append(item)
    return out


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # The typeface is part of the design system, so it ships with the app
    # rather than being assumed present on the host.
    datas=[('src/vellum/gui/fonts', 'vellum/gui/fonts'),
           ('src/vellum/gui/vellum.svg', 'vellum/gui')],
    hiddenimports=['PySide6.QtSvg'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDED_QT + EXCLUDED_OTHER,
    noarchive=False,
    optimize=2,
)

a.binaries = _filter_qt(a.binaries)
a.datas = _filter_qt(a.datas)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Vellum',
    icon='src/vellum/gui/vellum.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=UPX_EXCLUDE,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=True,
    upx=True,
    upx_exclude=UPX_EXCLUDE,
    name='Vellum',
)
