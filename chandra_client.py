import io
import base64
import json
import hashlib
import re
from pathlib import Path
from typing import List
from PIL import Image
from openai import OpenAI
import filetype
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from bs4 import BeautifulSoup
from markdownify import MarkdownConverter, re_whitespace
import six

# Configuration
IMAGE_DPI: int = 192
MIN_PDF_IMAGE_DIM: int = 1024
MIN_IMAGE_DIM: int = 1536
BBOX_SCALE: int = 1024

# OCR Layout Prompt
OCR_LAYOUT_PROMPT = """
OCR this image to HTML, arranged as layout blocks. Each layout block should be a div with the data-bbox attribute representing the bounding box of the block in [x0, y0, x1, y1] format. Bboxes are normalized 0-1024. The data-label attribute is the label for the block.

Use the following labels:
- Caption
- Footnote
- Equation-Block
- List-Group
- Page-Header
- Page-Footer
- Image
- Section-Header
- Table
- Text
- Complex-Block
- Code-Block
- Form
- Table-Of-Contents
- Figure

Only use these tags [math, br, i, b, u, del, sup, sub, table, tr, td, p, th, div, pre, h1, h2, h3, h4, h5, ul, ol, li, input, a, span, img, hr, tbody, small, caption, strong, thead, big, code], and these attributes [class, colspan, rowspan, display, checked, type, border, value, style, href, alt, align].

Guidelines:
* Inline math: Surround math with <math>...</math> tags. Math expressions should be rendered in KaTeX-compatible LaTeX. Use display for block math.
* Tables: Use colspan and rowspan attributes to match table structure.
* Formatting: Maintain consistent formatting with the image, including spacing, indentation, subscripts/superscripts, and special characters.
* Images: Include a description of any images in the alt attribute of an <img> tag. Do not fill out the src property.
* Forms: Mark checkboxes and radio buttons properly.
* Text: join lines together properly into paragraphs using <p>...</p> tags. Use <br> tags for line breaks within paragraphs, but only when absolutely necessary to maintain meaning.
* Use the simplest possible HTML structure that accurately represents the content of the block.
* Make sure the text is accurate and easy for a human to read and interpret. Reading order should be correct and natural.
""".strip()


def flatten(page, flag=pdfium_c.FLAT_NORMALDISPLAY):
    rc = pdfium_c.FPDFPage_Flatten(page, flag)
    if rc == pdfium_c.FLATTEN_FAIL:
        print(f"Failed to flatten annotations / form fields on page {page}.")


def load_image(filepath: str):
    image = Image.open(filepath).convert("RGB")
    if image.width < MIN_IMAGE_DIM or image.height < MIN_IMAGE_DIM:
        scale = MIN_IMAGE_DIM / min(image.width, image.height)
        new_size = (int(image.width * scale), int(image.height * scale))
        image = image.resize(new_size, Image.Resampling.LANCZOS)
    return image


def load_pdf_images(filepath: str, page_range: List[int]):
    doc = pdfium.PdfDocument(filepath)
    doc.init_forms()

    images = []
    for page in range(len(doc)):
        if not page_range or page in page_range:
            page_obj = doc[page]
            min_page_dim = min(page_obj.get_width(), page_obj.get_height())
            scale_dpi = (MIN_PDF_IMAGE_DIM / min_page_dim) * 72
            scale_dpi = max(scale_dpi, IMAGE_DPI)
            page_obj = doc[page]
            flatten(page_obj)
            page_obj = doc[page]
            pil_image = page_obj.render(
                scale=scale_dpi / 72).to_pil().convert("RGB")
            images.append(pil_image)

    doc.close()
    return images


def parse_range_str(range_str: str) -> List[int]:
    range_lst = range_str.split(",")
    page_lst = []
    for i in range_lst:
        if "-" in i:
            start, end = i.split("-")
            page_lst += list(range(int(start), int(end) + 1))
        else:
            page_lst.append(int(i))
    # Deduplicate page numbers and sort in order
    page_lst = sorted(list(set(page_lst)))
    return page_lst


def load_file(filepath: str, config: dict):
    page_range = config.get("page_range")
    if page_range:
        page_range = parse_range_str(page_range)

    input_type = filetype.guess(filepath)
    if input_type and input_type.extension == "pdf":
        images = load_pdf_images(filepath, page_range)
    else:
        images = [load_image(filepath)]
    return images


def encode_image(image: Image.Image):
    buffered = io.BytesIO()
    image.save(buffered, format="png")
    img_byte = buffered.getvalue()
    return base64.b64encode(img_byte).decode("utf-8")


def parse_html(html: str, include_headers_footers: bool = False, include_images: bool = True):
    """Parse and filter HTML based on data-label attributes."""
    soup = BeautifulSoup(html, "html.parser")
    top_level_divs = soup.find_all("div", recursive=False)
    out_html = ""
    div_idx = 0

    for div in top_level_divs:
        div_idx += 1
        label = div.get("data-label")

        # Skip headers and footers if not included
        if label and not include_headers_footers:
            if label in ["Page-Header", "Page-Footer"]:
                continue
        if label and not include_images:
            if label in ["Image", "Figure"]:
                continue

        # Update image src for Image and Figure blocks
        if label in ["Image", "Figure"]:
            img = div.find("img")
            img_src = get_image_name(html, div_idx)

            # Set the src attribute to point to the extracted image
            if img:
                img["src"] = f"images/{img_src}"
            else:
                # If no img tag, add one
                img_tag = soup.new_tag("img", src=f"images/{img_src}")
                div.append(img_tag)

        # Process and append content
        content = str(div.decode_contents())
        out_html += content

    return out_html


class Markdownify(MarkdownConverter):
    """Custom markdown converter with math and table handling."""

    def __init__(self, inline_math_delimiters, block_math_delimiters, **kwargs):
        super().__init__(**kwargs)
        self.inline_math_delimiters = inline_math_delimiters
        self.block_math_delimiters = block_math_delimiters

    def convert_math(self, el, text, parent_tags):
        block = el.has_attr("display") and el["display"] == "block"
        if block:
            return (
                "\n"
                + self.block_math_delimiters[0]
                + text.strip()
                + self.block_math_delimiters[1]
                + "\n"
            )
        else:
            return (
                " "
                + self.inline_math_delimiters[0]
                + text.strip()
                + self.inline_math_delimiters[1]
                + " "
            )

    def convert_table(self, el, text, parent_tags):
        return "\n\n" + str(el) + "\n\n"

    def convert_a(self, el, text, parent_tags):
        text = self.escape(text)
        # Escape brackets and parentheses in text
        text = re.sub(r"([\[\]()])", r"\\\1", text)
        return super().convert_a(el, text, parent_tags)

    def escape(self, text, parent_tags=None):
        text = super().escape(text, parent_tags)
        if self.options["escape_dollars"]:
            text = text.replace("$", r"\$")
        return text

    def process_text(self, el, parent_tags=None):
        text = six.text_type(el) or ""

        # normalize whitespace if we're not inside a preformatted element
        if not el.find_parent("pre"):
            text = re_whitespace.sub(" ", text)

        # escape special characters if we're not inside a preformatted or code element
        if not el.find_parent(["pre", "code", "kbd", "samp", "math"]):
            text = self.escape(text)

        # remove trailing whitespaces if any of the following condition is true:
        # - current text node is the last node in li
        # - current text node is followed by an embedded list
        if el.parent.name == "li" and (
            not el.next_sibling or el.next_sibling.name in ["ul", "ol"]
        ):
            text = text.rstrip()

        return text


def parse_markdown(html: str, include_headers_footers: bool = False, include_images: bool = True):
    """Convert HTML to markdown with custom handling for math and tables."""
    html = parse_html(html, include_headers_footers, include_images)

    md_cls = Markdownify(
        heading_style="ATX",
        bullets="-",
        escape_misc=False,
        escape_underscores=True,
        escape_asterisks=True,
        escape_dollars=True,
        sub_symbol="<sub>",
        sup_symbol="<sup>",
        inline_math_delimiters=("$", "$"),
        block_math_delimiters=("$$", "$$"),
    )
    try:
        markdown = md_cls.convert(html)
    except Exception as e:
        print(f"Error converting HTML to Markdown: {e}")
        markdown = ""
    return markdown.strip()


def parse_chunks(html: str, image: Image.Image, bbox_scale: int = BBOX_SCALE):
    """Extract layout blocks with bounding boxes from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    top_level_divs = soup.find_all("div", recursive=False)
    width, height = image.size
    width_scaler = width / bbox_scale
    height_scaler = height / bbox_scale

    chunks = []
    for div in top_level_divs:
        bbox = div.get("data-bbox")

        try:
            bbox = json.loads(bbox)
            assert len(bbox) == 4, "Invalid bbox length"
        except Exception:
            try:
                bbox = bbox.split(" ")
                assert len(bbox) == 4, "Invalid bbox length"
            except Exception:
                bbox = [0, 0, 1, 1]

        bbox = list(map(int, bbox))
        # Normalize bbox to actual image dimensions
        x0 = int(bbox[0] * width_scaler)
        y0 = int(bbox[1] * height_scaler)
        x1 = int(bbox[2] * width_scaler)
        y1 = int(bbox[3] * height_scaler)

        # Add 5% buffer on all sides to avoid cutoff
        bbox_width = x1 - x0
        bbox_height = y1 - y0
        padding_x = int(bbox_width * 0.05)
        padding_y = int(bbox_height * 0.05)

        bbox = [
            max(0, x0 - padding_x),
            max(0, y0 - padding_y),
            min(x1 + padding_x, width),
            min(y1 + padding_y, height),
        ]
        label = div.get("data-label", "block")
        content = str(div.decode_contents())
        chunks.append({"bbox": bbox, "label": label, "content": content})

    return chunks


def get_image_name(html: str, div_idx: int):
    """Generate unique image filename based on HTML hash and index."""
    html_hash = hashlib.md5(html.encode("utf-8")).hexdigest()
    return f"{html_hash}_{div_idx}_img.webp"


def extract_images(html: str, chunks: list, image: Image.Image):
    """Extract and crop images from layout blocks using bounding boxes."""
    images = {}
    div_idx = 0
    for chunk in chunks:
        div_idx += 1
        if chunk["label"] in ["Image", "Figure"]:
            bbox = chunk["bbox"]
            try:
                block_image = image.crop(bbox)
            except ValueError:
                # Happens when bbox coordinates are invalid
                continue
            img_name = get_image_name(html, div_idx)
            images[img_name] = block_image
    return images


def main():
    # Initialize vLLM client
    client = OpenAI(
        base_url="http://localhost:8001/v1",
        api_key="chandra",
    )

    # Load PDF or image
    # pdf_file_path = "sample_diamond_sutra.pdf"
    # pdf_file_path = "2203.02557v3.pdf"
    pdf_file_path = "en.CD00000464.pdf"

    print(f"Loading file: {pdf_file_path}")
    images = load_file(pdf_file_path, {})
    print(f"Loaded {len(images)} page(s)")

    # Create output directory
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    all_markdown = []
    all_html = []
    all_images = {}

    # Process each page
    for page_num, img in enumerate(images):
        print(f"\nProcessing page {page_num + 1}/{len(images)}...")

        # Encode image for API
        encoded_img = encode_image(img)

        # Make inference request
        chat_completion = client.chat.completions.create(
            model="chandra",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_LAYOUT_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{encoded_img}"}
                    },
                ],
            }],
            max_tokens=12384,
            temperature=0,
            top_p=0.1,
            stream=False,
        )

        html_output = chat_completion.choices[0].message.content

        # Process the HTML output
        markdown = parse_markdown(html_output, include_headers_footers=False, include_images=True)
        html = parse_html(html_output, include_headers_footers=False, include_images=True)
        chunks = parse_chunks(html_output, img, bbox_scale=BBOX_SCALE)
        page_images = extract_images(html_output, chunks, img)

        # Collect results
        all_markdown.append(markdown)
        all_html.append(html)
        all_images.update(page_images)

        print(f"  Extracted {len(page_images)} images from page {page_num + 1}")
        print(f"  Generated {len(markdown)} characters of markdown")

    # Save markdown file
    pdf_name = Path(pdf_file_path).stem
    markdown_path = output_dir / f"{pdf_name}.md"
    with open(markdown_path, "w", encoding="utf-8") as f:
        f.write("\n\n---\n\n".join(all_markdown))

    # Save HTML file
    html_path = output_dir / f"{pdf_name}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write("\n\n<hr>\n\n".join(all_html))

    # Save extracted images
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)
    for img_name, pil_image in all_images.items():
        img_path = images_dir / img_name
        pil_image.save(img_path)

    print(f"\n{'='*60}")
    print(f"✓ Done! Saved markdown to {markdown_path}")
    print(f"✓ Saved HTML to {html_path}")
    print(f"✓ Saved {len(all_images)} images to {images_dir}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
