"""Deterministic helpers for the hybrid figure-recovery workflow.

Chandra occasionally classifies vector graphics or boxed text as a text block,
so the figure never gets cropped even though its caption survives in the
Markdown. These helpers do the mechanical parts of recovering such figures:

1. ``detect_figure_captions`` scans the Markdown for caption lines and reports
   which ones have no adjacent image.
2. ``locate_caption_in_pdf`` finds the caption in the PDF text layer.
3. ``estimate_figure_box`` clusters graphics objects above the caption to guess
   the figure's bounding box (with a fixed-height fallback).
4. ``crop_figure`` renders the page and saves the crop.
5. ``inject_into_markdown`` / ``inject_into_html`` place image tags above the
   caption.

The decision of *which* captions are really missing figures is left to the
calling agent; everything here is deterministic and inspectable.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from bs4 import BeautifulSoup, NavigableString
from PIL import Image

# ---------------------------------------------------------------------------
# Caption detection in Markdown
# ---------------------------------------------------------------------------

# "Figure 1." / "Fig. 2:" / "FIG. 3." (APS style) / "Figure S1." — the number may carry a
# letter suffix for appendix figures.
CAPTION_RE = re.compile(
    r"(?P<label>(?:Figure|FIGURE|Fig\.?|FIG\.?)\s*(?P<num>[A-Z]?\d+[a-zA-Z]?))\s*[.:]"
)
IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]*)\)|<img\b[^>]*\bsrc=[\"']([^\"']*)[\"']")
# What may precede a caption on the same line and still count as a caption:
# nothing, a closing display-math block, a closing HTML tag, or bold markers.
CAPTION_PREFIX_OK = ("$$", ">", "**", "*", "_")

# An image is attributed to the caption that follows it within LOOKBACK_LINES
# non-empty lines (Chandra often emits an alt-text paragraph between the two),
# or, failing that, to the caption immediately preceding it. Each image is
# attributed to at most one caption.
LOOKBACK_LINES = 4
LOOKAHEAD_LINES = 1


@dataclass
class CaptionInfo:
    figure_id: str
    label: str
    caption: str
    line: int  # 1-based line number in the Markdown file
    has_image: bool
    image_ref: Optional[str] = None
    inline_prefix: str = ""  # text preceding the caption on the same line


@dataclass
class DetectionResult:
    markdown_path: str
    captions: List[CaptionInfo] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    referenced_without_caption: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "markdown_path": self.markdown_path,
            "captions": [asdict(c) for c in self.captions],
            "missing": self.missing,
            "referenced_without_caption": self.referenced_without_caption,
        }


def _is_caption_position(line: str, start: int) -> bool:
    prefix = line[:start].rstrip()
    if not prefix:
        return True
    return prefix.endswith(CAPTION_PREFIX_OK)


def _first_image_ref(text: str) -> Optional[str]:
    m = IMAGE_RE.search(text)
    if not m:
        return None
    return m.group(1) if m.group(1) is not None else m.group(2)


def detect_figure_captions(markdown_path: str) -> DetectionResult:
    """Find figure captions in a Markdown file and flag those without an image."""
    path = Path(markdown_path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    result = DetectionResult(markdown_path=str(path))
    seen: Dict[str, CaptionInfo] = {}
    referenced: set[str] = set()
    caption_at: Dict[int, CaptionInfo] = {}  # line index -> caption
    images: List[Tuple[int, str]] = []  # (line index, ref)

    # Rank of each line among non-empty lines, so blank lines don't count as distance.
    rank: Dict[int, int] = {}
    r = 0
    for idx, line in enumerate(lines):
        if line.strip():
            rank[idx] = r
            r += 1

    for idx, line in enumerate(lines):
        for m in CAPTION_RE.finditer(line):
            num = m.group("num")
            if not _is_caption_position(line, m.start()):
                referenced.add(num)
                continue
            if num in seen:
                continue
            info = CaptionInfo(
                figure_id=num,
                label=m.group("label"),
                caption=line[m.start():].strip(),
                line=idx + 1,
                has_image=False,
                inline_prefix=line[:m.start()],
            )
            # An image earlier on the caption line itself belongs to this caption.
            inline_ref = _first_image_ref(info.inline_prefix)
            if inline_ref is not None:
                info.has_image, info.image_ref = True, inline_ref
            seen[num] = info
            caption_at[idx] = info
            result.captions.append(info)
            break  # one caption per line
        else:
            ref = _first_image_ref(line)
            if ref is not None:
                images.append((idx, ref))

    caption_lines = sorted(caption_at)
    for iidx, ref in images:
        irank = rank[iidx]
        after = [c for c in caption_lines if c > iidx and rank[c] - irank <= LOOKBACK_LINES]
        before = [c for c in caption_lines if c < iidx and irank - rank[c] <= LOOKAHEAD_LINES]
        for cidx in after[:1] + before[-1:]:
            info = caption_at[cidx]
            if not info.has_image:
                info.has_image, info.image_ref = True, ref
                break

    result.missing = [c.figure_id for c in result.captions if not c.has_image]
    result.referenced_without_caption = sorted(
        referenced - set(seen), key=_figure_sort_key
    )
    return result


def _figure_sort_key(fid: str):
    m = re.match(r"([A-Z]?)(\d+)([a-zA-Z]?)", fid)
    if not m:
        return (fid, 0, "")
    return (m.group(1), int(m.group(2)), m.group(3))


# ---------------------------------------------------------------------------
# Locating captions in the PDF text layer
# ---------------------------------------------------------------------------

Box = Tuple[float, float, float, float]  # (left, bottom, right, top) in PDF points


@dataclass
class CaptionLocation:
    figure_id: str
    page_index: int  # 0-based
    caption_bbox: Box
    line_start: bool
    match_score: float
    matched_text: str


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _caption_label_pattern(figure_id: str) -> re.Pattern:
    return re.compile(
        r"(?:Figure|FIGURE|Fig\.?|FIG\.?)\s*" + re.escape(figure_id) + r"\s*[.:]"
    )


def _union(boxes: Sequence[Box]) -> Box:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _line_bbox(textpage, text: str, start: int) -> Box:
    """Union of char boxes from ``start`` to the end of the current text line."""
    end = start
    n = len(text)
    while end < n and text[end] not in "\r\n":
        end += 1
    boxes = []
    for i in range(start, end):
        try:
            b = textpage.get_charbox(i)
        except Exception:
            continue
        if b and (b[2] - b[0]) > 0 and (b[3] - b[1]) > 0:
            boxes.append(tuple(b))
    if not boxes:
        b = textpage.get_charbox(start)
        boxes = [tuple(b)]
    return _union(boxes)


def locate_caption_in_pdf(
    pdf: pdfium.PdfDocument,
    figure_id: str,
    caption_text: str,
    pages: Optional[Sequence[int]] = None,
) -> Optional[CaptionLocation]:
    """Find the caption for ``figure_id`` in the PDF.

    Candidates are occurrences of the caption label ("Figure 3.") in the text
    layer. Occurrences at the start of a text line are preferred (prose
    references such as "see Figure 3." are mid-line), and the following text is
    compared with ``caption_text`` to break ties.
    """
    pattern = _caption_label_pattern(figure_id)
    target = _normalize(caption_text)[:60]
    best: Optional[CaptionLocation] = None
    best_key = None

    page_indices = pages if pages is not None else range(len(pdf))
    for pi in page_indices:
        page = pdf[pi]
        textpage = page.get_textpage()
        text = textpage.get_text_range()
        for m in pattern.finditer(text):
            s = m.start()
            line_start = s == 0 or text[s - 1] in "\r\n"
            following = _normalize(text[s:s + 200])[:60]
            # Longest common prefix ratio between the PDF text and the Markdown caption.
            k = 0
            while k < min(len(following), len(target)) and following[k] == target[k]:
                k += 1
            score = k / max(1, len(target))
            key = (1 if line_start else 0, score)
            if best_key is None or key > best_key:
                best_key = key
                best = CaptionLocation(
                    figure_id=figure_id,
                    page_index=pi,
                    caption_bbox=_line_bbox(textpage, text, s),
                    line_start=line_start,
                    match_score=round(score, 3),
                    matched_text=text[s:s + 80].replace("\r", " ").replace("\n", " "),
                )
    return best


# ---------------------------------------------------------------------------
# Estimating the figure box above a caption
# ---------------------------------------------------------------------------

# Form XObjects are included because embedded vector figures are usually one
# form object; its bounds are in page space, whereas its children are not.
GRAPHIC_TYPES = {
    pdfium_c.FPDF_PAGEOBJ_PATH,
    pdfium_c.FPDF_PAGEOBJ_IMAGE,
    pdfium_c.FPDF_PAGEOBJ_SHADING,
    pdfium_c.FPDF_PAGEOBJ_FORM,
}
RULE_THICKNESS = 3.0  # points; thinner-and-wide paths are treated as rules


@dataclass
class FigureBoxEstimate:
    crop_box: Box
    method: str  # "graphics" or "fallback"
    column_span: Tuple[float, float]
    n_graphics: int


def _text_extent(page) -> Tuple[float, float]:
    """Horizontal extent of the page's text (approximates the margins)."""
    textpage = page.get_textpage()
    n = textpage.count_chars()
    lefts, rights = [], []
    step = max(1, n // 400)  # sample for speed on dense pages
    for i in range(0, n, step):
        try:
            b = textpage.get_charbox(i)
        except Exception:
            continue
        if b and (b[2] - b[0]) > 0:
            lefts.append(b[0])
            rights.append(b[2])
    if not lefts:
        w, _ = page.get_size()
        return (0.0, w)
    return (min(lefts), max(rights))


def estimate_figure_box(
    page,
    caption_bbox: Box,
    gap_tolerance: float = 40.0,
    fallback_height: float = 288.0,
    full_width: Optional[bool] = None,
    padding: float = 6.0,
) -> FigureBoxEstimate:
    """Guess the figure's bounding box from graphics objects above the caption.

    Args:
        page: pypdfium2 page.
        caption_bbox: (left, bottom, right, top) of the caption line in points.
        gap_tolerance: Max vertical gap (points) between graphics objects that
            still belong to the same figure.
        fallback_height: Height (points) to crop above the caption when no
            graphics are found.
        full_width: Force a full-text-width crop (True), a caption-width column
            crop (False), or decide from the caption width (None).
        padding: Extra margin (points) added around the estimate.
    """
    page_w, page_h = page.get_size()
    text_left, text_right = _text_extent(page)
    text_width = max(1.0, text_right - text_left)
    cap_l, cap_b, cap_r, cap_t = caption_bbox

    if full_width is None:
        full_width = (cap_r - cap_l) > 0.55 * text_width
    if full_width:
        col_l, col_r = text_left, text_right
    else:
        # Column figure: extend the caption span to a plausible column.
        half = text_left + text_width / 2
        col_l, col_r = (text_left, half) if cap_l < half else (half, text_right)
        col_l = min(col_l, cap_l)
        col_r = max(col_r, cap_r)

    # Collect top-level graphics objects above the caption, overlapping the
    # column. Wide, thin paths (header/footer rules, section separators) are
    # kept aside: they must not glue a figure to the page header.
    candidates: List[Box] = []
    rules: List[Box] = []
    for obj in page.get_objects(max_depth=1):
        if obj.type not in GRAPHIC_TYPES:
            continue
        try:
            l, b, r, t = obj.get_bounds()
        except Exception:
            continue
        if r <= l or t <= b:
            continue
        # Skip page-sized backgrounds.
        if (r - l) > 0.95 * page_w and (t - b) > 0.95 * page_h:
            continue
        if (t - b) <= RULE_THICKNESS and (r - l) > 0.6 * text_width:
            rules.append((l, b, r, t))
            continue
        if t < cap_t - 2:  # entirely below the caption's top edge
            continue
        if b < cap_t - 2:  # straddles the caption line: keep only the part above
            b = cap_t
        if r < col_l - 10 or l > col_r + 10:  # outside the column
            continue
        candidates.append((l, b, r, t))

    # Cluster upward from the caption.
    candidates.sort(key=lambda bx: bx[1])  # by bottom edge, nearest first
    cluster: List[Box] = []
    reach = cap_t + gap_tolerance
    for bx in candidates:
        if bx[1] <= reach:
            cluster.append(bx)
            reach = max(reach, bx[3] + gap_tolerance)
        else:
            break

    if cluster:
        l, b, r, t = _union(cluster)
        top = t + padding
        # Do not run into the page header: stop below any rule in the top
        # fifth of the page that falls inside the estimate.
        for rl, rb, rr, rt in rules:
            if cap_t < rb < top and rb > 0.8 * page_h:
                top = min(top, rb - 2.0)
        if full_width:
            left, right = min(l, cap_l) - padding, max(r, cap_r) + padding
        else:
            left, right = max(col_l - padding, min(l, cap_l) - padding), min(col_r + padding, max(r, cap_r) + padding)
        crop = (
            max(0.0, left),
            max(0.0, cap_t + 1.0),
            min(page_w, right),
            min(page_h, top),
        )
        return FigureBoxEstimate(crop, "graphics", (col_l, col_r), len(cluster))

    crop = (
        max(0.0, col_l - padding),
        max(0.0, cap_t + 1.0),
        min(page_w, col_r + padding),
        min(page_h, cap_t + fallback_height),
    )
    return FigureBoxEstimate(crop, "fallback", (col_l, col_r), 0)


# ---------------------------------------------------------------------------
# Rendering and cropping
# ---------------------------------------------------------------------------


def render_page(page, dpi: int = 200) -> Image.Image:
    return page.render(scale=dpi / 72).to_pil().convert("RGB")


def crop_figure(page, crop_box: Box, output_path: Path, dpi: int = 200) -> Tuple[int, int]:
    """Render ``page`` and save the region ``crop_box`` (PDF points) to ``output_path``."""
    _, page_h = page.get_size()
    scale = dpi / 72
    image = render_page(page, dpi)
    l, b, r, t = crop_box
    px = (
        int(max(0, l * scale)),
        int(max(0, (page_h - t) * scale)),
        int(min(image.width, r * scale)),
        int(min(image.height, (page_h - b) * scale)),
    )
    if px[2] <= px[0] or px[3] <= px[1]:
        raise ValueError(f"Empty crop box {crop_box} on page of size {page.get_size()}")
    cropped = image.crop(px)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(output_path)
    return cropped.size


# ---------------------------------------------------------------------------
# Injection
# ---------------------------------------------------------------------------


def _relative_src(image_path: str, doc_path: str) -> str:
    rel = os.path.relpath(Path(image_path).resolve(), Path(doc_path).resolve().parent)
    return rel.replace(os.sep, "/")


def inject_into_markdown(markdown_path: str, figures: Dict[str, str]) -> Dict[str, str]:
    """Insert ``![label](image)`` above each caption.

    Args:
        markdown_path: Markdown file to edit in place.
        figures: Mapping figure_id -> image path.

    Returns:
        Mapping figure_id -> status ("injected", "already_has_image", "caption_not_found").
    """
    path = Path(markdown_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    detection = detect_figure_captions(markdown_path)
    by_id = {c.figure_id: c for c in detection.captions}

    status: Dict[str, str] = {}
    # Edit from the bottom up so earlier line numbers stay valid.
    for fid in sorted(figures, key=lambda f: -(by_id[f].line if f in by_id else 0)):
        info = by_id.get(fid)
        if info is None:
            status[fid] = "caption_not_found"
            continue
        if info.has_image:
            status[fid] = "already_has_image"
            continue
        src = _relative_src(figures[fid], markdown_path)
        img_line = f"![{info.label}]({src})"
        idx = info.line - 1
        prefix = info.inline_prefix.rstrip()
        if prefix and not prefix.strip("*_ "):
            prefix = ""  # only emphasis markers precede the caption: keep the line whole
        if prefix:
            caption = lines[idx][len(info.inline_prefix):]
            lines[idx:idx + 1] = [prefix, "", img_line, "", caption]
        else:
            lines[idx:idx + 1] = [img_line, "", lines[idx]]
        status[fid] = "injected"

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return status


def inject_into_html(html_path: str, figures: Dict[str, str]) -> Dict[str, str]:
    """Insert ``<img>`` tags before each caption in an HTML file (in place)."""
    path = Path(html_path)
    html = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    status: Dict[str, str] = {}

    existing_srcs = {img.get("src") for img in soup.find_all("img")}

    for fid, image_path in figures.items():
        src = _relative_src(image_path, html_path)
        if src in existing_srcs:
            status[fid] = "already_has_image"
            continue
        pattern = _caption_label_pattern(fid)
        target_node: Optional[NavigableString] = None
        for node in soup.find_all(string=pattern):
            m = pattern.search(str(node))
            if m and not str(node)[:m.start()].strip():
                target_node = node
                break
        if target_node is None:
            status[fid] = "caption_not_found"
            continue

        img = soup.new_tag("img", src=src, alt=f"Figure {fid}", style="display:block")
        parent = target_node.parent
        # If the caption is the first thing in its block, put the image before the block.
        if parent is not None and parent.name in ("p", "div", "caption", "span", "b", "strong", "i", "em") \
                and parent.contents and parent.contents[0] is target_node and parent.parent is not None:
            parent.insert_before(img)
        else:
            target_node.insert_before(img)
        existing_srcs.add(src)
        status[fid] = "injected"

    path.write_text(str(soup), encoding="utf-8")
    return status
