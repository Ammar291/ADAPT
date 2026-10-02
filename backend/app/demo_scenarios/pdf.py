"""A tiny PDF canvas for clearly synthetic demo documents.

The documents need two things at once: they must look like real paperwork on a projector,
and their text layer must read back exactly, line by line, through the same local reader
real uploads go through. So every piece of text is one run on its own baseline (two runs on
one baseline would be merged into one line by text extraction), and decoration is drawn
with paths, never text. The diagonal watermark is the last thing drawn, so it is extracted
after everything else.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Colour = tuple[float, float, float]

NAVY: Colour = (0.06, 0.11, 0.18)
TEAL: Colour = (0.04, 0.43, 0.46)
SLATE: Colour = (0.20, 0.31, 0.48)
INK: Colour = (0.10, 0.10, 0.12)
MUTED: Colour = (0.38, 0.40, 0.44)
RULE: Colour = (0.80, 0.81, 0.83)
PAPER: Colour = (0.97, 0.96, 0.93)
TINT: Colour = (0.92, 0.94, 0.95)
RED: Colour = (0.72, 0.09, 0.09)
WHITE: Colour = (1.0, 1.0, 1.0)
WATERMARK: Colour = (0.86, 0.86, 0.88)

FONTS = {"sans": b"F1", "bold": b"F2", "mono": b"F3"}

WIDTH, HEIGHT = 595, 842  # A4 in points


def _escape(text: str) -> bytes:
    raw = text.encode("latin-1", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _rgb(colour: Colour) -> bytes:
    return b"%.3f %.3f %.3f" % colour


@dataclass
class Canvas:
    """Drawing operations in PDF user space (origin bottom-left, points)."""

    ops: list[bytes] = field(default_factory=list)
    _baselines: set[int] = field(default_factory=set)

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        fill: Colour | None = None,
        stroke: Colour | None = None,
        width: float = 0.8,
    ) -> None:
        parts = [b"q"]
        if fill:
            parts.append(_rgb(fill) + b" rg")
        if stroke:
            parts.append(_rgb(stroke) + b" RG %.2f w" % width)
        paint = b"B" if fill and stroke else b"f" if fill else b"S"
        parts.append(b"%.2f %.2f %.2f %.2f re %s Q" % (x, y, w, h, paint))
        self.ops.append(b" ".join(parts))

    def line(self, x1: float, y1: float, x2: float, y2: float, colour: Colour = RULE) -> None:
        self.ops.append(
            b"q " + _rgb(colour) + b" RG 0.6 w %.2f %.2f m %.2f %.2f l S Q" % (x1, y1, x2, y2)
        )

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, fill: Colour) -> None:
        k = 0.5523  # Bezier approximation of a quarter circle
        self.ops.append(
            b"q "
            + _rgb(fill)
            + b" rg %.2f %.2f m " % (cx + rx, cy)
            + b"%.2f %.2f %.2f %.2f %.2f %.2f c "
            % (cx + rx, cy + k * ry, cx + k * rx, cy + ry, cx, cy + ry)
            + b"%.2f %.2f %.2f %.2f %.2f %.2f c "
            % (cx - k * rx, cy + ry, cx - rx, cy + k * ry, cx - rx, cy)
            + b"%.2f %.2f %.2f %.2f %.2f %.2f c "
            % (cx - rx, cy - k * ry, cx - k * rx, cy - ry, cx, cy - ry)
            + b"%.2f %.2f %.2f %.2f %.2f %.2f c f Q"
            % (cx + k * rx, cy - ry, cx + rx, cy - k * ry, cx + rx, cy)
        )

    def text(
        self,
        x: float,
        y: float,
        text: str,
        *,
        size: float = 10.5,
        font: str = "sans",
        colour: Colour = INK,
    ) -> None:
        baseline = round(y)
        if baseline in self._baselines:
            raise ValueError(
                f"two text runs on baseline {baseline}: text extraction would merge them"
            )
        self._baselines.add(baseline)
        self.ops.append(
            b"BT /%s %.1f Tf " % (FONTS[font], size)
            + _rgb(colour)
            + b" rg %.2f %.2f Td (%s) Tj ET" % (x, y, _escape(text))
        )

    def watermark(self, text: str) -> None:
        """Large, light, diagonal text across the page."""
        self.ops.append(
            b"q BT /F2 96 Tf "
            + _rgb(WATERMARK)
            + b" rg 0.7071 0.7071 -0.7071 0.7071 150 210 Tm (%s) Tj ET Q" % _escape(text)
        )

    def silhouette(self, x: float, y: float, w: float, h: float) -> None:
        """A neutral portrait placeholder (no face, no person)."""
        self.rect(x, y, w, h, fill=TINT, stroke=RULE)
        self.ellipse(x + w / 2, y + h * 0.62, w * 0.2, h * 0.17, fill=(0.74, 0.77, 0.80))
        self.ellipse(x + w / 2, y + h * 0.12, w * 0.36, h * 0.24, fill=(0.74, 0.77, 0.80))
        self.rect(x, y, w, h * 0.02, fill=TINT)

    def render(self) -> bytes:
        stream = b"\n".join(self.ops)
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
            b"/Resources << /Font << /F1 4 0 R /F2 5 0 R /F3 6 0 R >> >> /Contents 7 0 R >>"
            % (WIDTH, HEIGHT),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
            b"/Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>",
            b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        ]
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
        for offset in offsets:
            out += b"%010d 00000 n \n" % offset
        out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(objects) + 1,
            xref,
        )
        return bytes(out)
