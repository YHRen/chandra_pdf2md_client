---
name: chandra-hybrid-parse
description: Convert a scientific PDF to Markdown/HTML with the Chandra OCR model and recover figures the vision model missed (vector graphics or boxed text parsed as plain text). Use when asked to parse, convert, or OCR a paper PDF, or when a Chandra output has captions without images.
argument-hint: [pdf_path] [output_dir]
---

# Hybrid PDF parsing with Chandra

Arguments: `$ARGUMENTS` (first: PDF path, optional second: output directory, default `./output`).

Chandra converts PDF pages to structured HTML/Markdown and crops the figures it recognises. It
sometimes labels a vector diagram or a boxed text panel as a text block, so the caption survives in
the Markdown but no image is cropped. The `chandra` MCP server exposes deterministic tools for
every mechanical step; your job is the judgement in between.

## Procedure

1. **Convert.** Call `convert_pdf` with `file_path` and `output_dir`. Keep the returned
   `markdown_path` and `html_path`. If the server cannot be reached, ask the user for the vLLM URL
   and call `configure_server` (the default is `http://localhost:8001/v1`; `CHANDRA_SERVER_URL`
   in the environment overrides it).

2. **Detect candidates.** Call `detect_missing_figures` with `markdown_path`.
   - `captions[*]` with `has_image: false` are candidates.
   - `referenced_without_caption` lists figure numbers mentioned in prose whose caption line was
     not detected. Grep the Markdown around those mentions. If the caption is present but
     garbled, you can still recover the figure by passing `figure_id` and the caption text to
     `recover_figures` yourself.

3. **Decide.** Read the Markdown around each candidate. Drop candidates that are really tables,
   algorithm boxes, or figures that already have an image under a slightly different caption.
   This is the step the heuristic cannot do.

4. **Recover.** Call `recover_figures` with `pdf_path`, `markdown_path`, and `figures`
   (`[{"figure_id": "1", "caption": "Figure 1. ..."}, ...]`). Omit `figures` to take every
   candidate. Each result gives the page, the crop box in PDF points, and `method`:
   `graphics` (box derived from graphics objects above the caption) or `fallback` (fixed-height
   guess, needs checking).

5. **Inspect.** Open every recovered image file and look at it. A good crop contains the whole
   figure and nothing else. If a crop is cut off, includes body text or the page header, or picks
   the wrong column:
   - call `render_pdf_page` for that page to see the layout (returns `page_size_pt`), then
   - re-run `recover_figures` for that figure with `page` and a manual `crop_box`
     `[left, bottom, right, top]` in PDF points, origin bottom-left, or adjust `full_width` /
     `fallback_height_pt` / `gap_tolerance_pt`.

6. **Inject.** When every crop looks right, call `inject_figures` with `markdown_path`,
   `html_path`, and `figures` (`[{"figure_id": "1", "image_path": "..."}, ...]`). It inserts the
   image directly above the caption and skips captions that already have one, so it is safe to
   re-run.

7. **Report.** List the figures recovered, the method used for each, any manual crops, and
   anything skipped with the reason.

## Notes

- Chandra sometimes glues a caption onto the end of a display-math line
  (`$$ ... $$Figure 1. ...`). The detector handles that; the injector splits the line.
- Crop boxes are in PDF points (1/72 inch). Page size is typically `[612, 792]` for US Letter.
- Never edit the Markdown or HTML by hand for image insertion; use `inject_figures` so the paths
  stay relative and the operation stays idempotent.
