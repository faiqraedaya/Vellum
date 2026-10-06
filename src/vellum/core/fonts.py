"""Find the font file behind a family name, so exported text can embed the
exact typeface it was drawn with instead of falling back to a base-14 font.

Qt only hands out family names; PDF embedding needs a file. On Windows the
installed fonts are listed in the registry as "<Family> <Style> (TrueType)"
-> file, which is enough to resolve family + bold + italic. Extra faces (the
app's bundled fonts) are registered explicitly.
"""
import os
import re
import sys
import tempfile
from typing import Dict, Optional, Tuple

# (family casefolded, bold, italic) -> font file path
_Key = Tuple[str, bool, bool]

_STYLE_WORDS = {"regular", "bold", "italic", "oblique"}
_SUFFIX = re.compile(r"\s*\((TrueType|OpenType|All res)\)\s*$", re.IGNORECASE)


def _parse_face(name: str) -> Tuple[str, bool, bool]:
    """Split a registry face name like 'Arial Bold Italic' into its family and
    style flags. Weights other than bold (Light, Semibold, ...) stay part of
    the family name, as Windows files them as families of their own."""
    words = name.split()
    bold = italic = False
    while len(words) > 1 and words[-1].casefold() in _STYLE_WORDS:
        w = words.pop().casefold()
        bold |= w == "bold"
        italic |= w in ("italic", "oblique")
    return " ".join(words), bold, italic


def _windows_fonts() -> Dict[_Key, str]:
    import winreg

    windir = os.environ.get("WINDIR", r"C:\Windows")
    system_dir = os.path.join(windir, "Fonts")
    found: Dict[_Key, str] = {}
    sources = (
        (winreg.HKEY_LOCAL_MACHINE, system_dir),
        # Per-user installs record absolute paths.
        (winreg.HKEY_CURRENT_USER, system_dir),
    )
    for hive, base in sources:
        try:
            key = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
        except OSError:
            continue
        with key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                if not isinstance(value, str):
                    continue
                path = value if os.path.isabs(value) else os.path.join(base, value)
                if not path.lower().endswith((".ttf", ".otf", ".ttc")):
                    continue
                # A collection lists its faces joined by " & ".
                for face in _SUFFIX.sub("", name).split(" & "):
                    family, bold, italic = _parse_face(face.strip())
                    found.setdefault((family.casefold(), bold, italic), path)
    return found


class FontResolver:
    """Resolves (family, bold, italic) to a font file path."""

    def __init__(self):
        self._installed: Optional[Dict[_Key, str]] = None
        self._extra: Dict[_Key, str] = {}

    def register(self, family: str, path: str, bold: bool = False, italic: bool = False):
        """Make a face that is not installed system-wide (a bundled font)
        resolvable under `family`."""
        self._extra[(family.casefold(), bold, italic)] = path

    def _table(self) -> Dict[_Key, str]:
        if self._installed is None:
            self._installed = {}
            if sys.platform == "win32":
                try:
                    self._installed = _windows_fonts()
                except Exception:
                    self._installed = {}
        return self._installed

    def find(self, family: str, bold: bool = False, italic: bool = False) -> Optional[str]:
        """Best file for the requested face: the exact style if present; else a
        variable font of the family instanced at the requested weight; else the
        family's nearest style. None when the family is unknown."""
        fam = family.casefold()
        tables = (self._extra, self._table())
        for table in tables:
            path = table.get((fam, bold, italic))
            if path:
                return path
        for table in tables:
            for b, i in ((False, italic), (bold, False), (False, False)):
                path = table.get((fam, b, i))
                if not path:
                    continue
                if bold and not b:
                    return _bold_instance(path) or path
                return path
        return None


_instances: Dict[str, Optional[str]] = {}


def _bold_instance(path: str) -> Optional[str]:
    """A static bold instance of a variable font (cached on disk), or None if
    `path` is not a variable font with a weight axis. PDF renderers draw a
    variable font at its default instance, so a bold face has to be cut out
    of it before it can be embedded."""
    if path in _instances:
        return _instances[path]
    cache = os.path.join(tempfile.gettempdir(), "vellum-fonts")
    stem = os.path.splitext(os.path.basename(path))[0]
    out = os.path.join(cache, f"{stem}-Bold.ttf")
    try:
        if os.path.getmtime(out) >= os.path.getmtime(path):
            _instances[path] = out
            return out
    except OSError:
        pass
    try:
        from fontTools.ttLib import TTFont
        from fontTools.varLib.instancer import instantiateVariableFont

        font = TTFont(path)
        axes = {a.axisTag: a for a in font["fvar"].axes} if "fvar" in font else {}
        if "wght" not in axes:
            out = None
        else:
            a = axes["wght"]
            pins = {tag: ax.defaultValue for tag, ax in axes.items()}
            pins["wght"] = max(a.minValue, min(a.maxValue, 700.0))
            static = instantiateVariableFont(font, pins)
            os.makedirs(cache, exist_ok=True)
            part = f"{out}.{os.getpid()}.tmp"
            static.save(part)
            os.replace(part, out)
    except Exception:
        out = None
    _instances[path] = out
    return out
