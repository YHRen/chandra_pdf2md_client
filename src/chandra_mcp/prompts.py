"""Prompt templates exposed by the MCP server."""

HYBRID_PARSE_PROMPT = """\
Convert the PDF at `{pdf_path}` to Markdown and HTML with Chandra, then find and recover any \
figures the vision model missed. Chandra sometimes classifies vector graphics or boxed text \
panels as ordinary text, so the caption survives but no image is cropped. The tools below do \
the mechanical work; you make the judgement calls.

1. `convert_pdf(file_path="{pdf_path}", output_dir="{output_dir}")`. Note `markdown_path` and `html_path`.
2. `detect_missing_figures(markdown_path=...)`. Read the result:
   - `captions[*].has_image == false` are candidates for recovery.
   - `referenced_without_caption` lists figure numbers mentioned in prose whose caption was not \
detected. Open the Markdown near those mentions; if the caption text is there but garbled, you \
can still recover the figure by passing `figure_id` and the caption text explicitly.
3. Decide which candidates are genuinely missing figures. Drop anything that is really a table, \
an algorithm box, or a figure that already has an image under a slightly different caption.
4. `recover_figures(pdf_path="{pdf_path}", markdown_path=..., figures=[{{"figure_id": "1", "caption": "..."}}, ...])`. \
Omit `figures` to take every candidate. Each result reports the page, the crop box in PDF points, and \
`method`: "graphics" means the box came from graphics objects above the caption, "fallback" means a \
fixed-height guess.
5. Look at every recovered image file. If a crop is wrong (cut off, includes body text or the page \
header, wrong column), call `render_pdf_page(pdf_path, page)` to see the page, then re-run \
`recover_figures` for that figure with `page` and a manual `crop_box` `[left, bottom, right, top]` in \
PDF points (origin at the bottom-left; the returned `page_size_pt` gives the page dimensions), or \
adjust `full_width` / `fallback_height_pt`.
6. When every crop looks right, `inject_figures(markdown_path=..., html_path=..., figures=[{{"figure_id": "1", "image_path": "..."}}, ...])`.
7. Report which figures were recovered, which method was used for each, and anything you skipped and why.
"""
