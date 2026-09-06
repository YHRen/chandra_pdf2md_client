"""Tests for the deterministic figure-recovery helpers."""

from pathlib import Path

import pypdfium2 as pdfium
import pytest

from chandra_mcp.figures import (
    detect_figure_captions,
    estimate_figure_box,
    crop_figure,
    inject_into_html,
    inject_into_markdown,
    locate_caption_in_pdf,
)

REPO = Path(__file__).resolve().parents[1]
SAMPLE_PDF = REPO / "2203.02557v3.pdf"

MD = """# Title

Intro text that mentions Figure 1. It also mentions Fig. 2: twice.

$$x = y \\quad (1)$$Figure 1. Glued to an equation line.

More text.

![Figure 2](images/abc_4_img.webp)

Description paragraph of the image.

Figure 2. Has an image two lines above.

**Figure 3.** Bold caption without image.

<img alt="x" src="images/def_2_img.webp"/>

Fig. 4: Image directly above, HTML style.

See Figure 7. Only referenced, never captioned.

FIG. 8. APS-style caption, no image.
"""


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_detect_captions(tmp_path):
    md = write(tmp_path, "doc.md", MD)
    det = detect_figure_captions(str(md))
    by_id = {c.figure_id: c for c in det.captions}
    assert set(by_id) == {"1", "2", "3", "4", "8"}
    assert det.missing == ["1", "3", "8"]
    assert not by_id["1"].has_image and by_id["1"].inline_prefix.endswith("$$")
    assert by_id["2"].has_image and by_id["2"].image_ref == "images/abc_4_img.webp"
    assert by_id["4"].has_image and by_id["4"].image_ref == "images/def_2_img.webp"
    assert det.referenced_without_caption == ["7"]


def test_inject_markdown_is_idempotent(tmp_path):
    md = write(tmp_path, "doc.md", MD)
    (tmp_path / "figure_1.webp").write_bytes(b"")
    (tmp_path / "figure_3.webp").write_bytes(b"")
    figs = {"1": str(tmp_path / "figure_1.webp"), "3": str(tmp_path / "figure_3.webp"), "9": "nope.webp"}
    status = inject_into_markdown(str(md), figs)
    assert status == {"1": "injected", "3": "injected", "9": "caption_not_found"}
    text = md.read_text()
    assert "$$x = y \\quad (1)$$\n\n![Figure 1](figure_1.webp)\n\nFigure 1. Glued" in text
    assert "![Figure 3](figure_3.webp)\n\n**Figure 3.** Bold" in text
    # Second pass changes nothing.
    status = inject_into_markdown(str(md), figs)
    assert status["1"] == "already_has_image" and status["3"] == "already_has_image"
    assert text == md.read_text()
    assert detect_figure_captions(str(md)).missing == ["8"]


def test_inject_html(tmp_path):
    html = write(tmp_path, "doc.html", "<p>See Figure 1. here.</p><p>Figure 1. A caption.</p><p><b>Figure 2.</b> Bold.</p>")
    (tmp_path / "figure_1.webp").write_bytes(b"")
    (tmp_path / "figure_2.webp").write_bytes(b"")
    status = inject_into_html(str(html), {"1": str(tmp_path / "figure_1.webp"), "2": str(tmp_path / "figure_2.webp")})
    assert status == {"1": "injected", "2": "injected"}
    out = html.read_text()
    assert out.count("<img") == 2
    assert out.index('src="figure_1.webp"') < out.index("Figure 1. A caption")
    assert out.index('src="figure_1.webp"') > out.index("See Figure 1. here")
    assert inject_into_html(str(html), {"1": str(tmp_path / "figure_1.webp")}) == {"1": "already_has_image"}


@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="sample PDF not present")
def test_locate_and_crop_from_pdf(tmp_path):
    pdf = pdfium.PdfDocument(str(SAMPLE_PDF))
    loc = locate_caption_in_pdf(pdf, "1", "Figure 1. CycleGAN Framework")
    assert loc is not None and loc.line_start and loc.page_index == 2
    page = pdf[loc.page_index]
    est = estimate_figure_box(page, loc.caption_bbox)
    l, b, r, t = est.crop_box
    assert b >= loc.caption_bbox[3] and t > b and r > l
    size = crop_figure(page, est.crop_box, tmp_path / "fig1.webp", dpi=100)
    assert size[0] > 50 and size[1] > 20
    # Prose reference must not win over the real caption.
    loc4 = locate_caption_in_pdf(pdf, "4", "Figure 4. Attention.")
    assert loc4 is not None and loc4.line_start
