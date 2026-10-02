import io
import math
import logging
from typing import List
import pymupdf

logger = logging.getLogger("watermark_engine")

def _prepare_watermark_lines(watermark_text: str) -> List[str]:
    """
    Parses dynamic watermark text into distinct, cleanly formatted lines.
    Handles newline delimiters and pipe (|) separated metadata strings.
    """
    cleaned = watermark_text.strip()
    if "\n" in cleaned:
        return [line.strip() for line in cleaned.split("\n") if line.strip()]
    if " | " in cleaned or " |" in cleaned or "| " in cleaned:
        parts = [part.strip() for part in cleaned.split("|") if part.strip()]
        lines = []
        for part in parts:
            if part.lower().startswith("confidential - ") or part.lower().startswith("confidential – ") or part.lower().startswith("confidential — "):
                lines.append(f"CONFIDENTIAL — {part[15:].strip()}")
            else:
                lines.append(part)
        return lines if lines else [cleaned]
    return [cleaned]

def apply_watermark(
    pdf_bytes: bytes,
    watermark_text: str,
    opacity: float = 0.20
) -> bytes:
    """
    Applies a large, clearly visible, diagonal, semi-transparent text watermark
    spanning from top-left toward bottom-right across every page of the given PDF bytes.
    Processes the document entirely in memory without disk persistence.
    The underlying PDF remains a real vector PDF with searchable text.

    :param pdf_bytes: Raw bytes of the input PDF document.
    :param watermark_text: The dynamic identity watermark string.
    :param opacity: Opacity float from 0.0 (transparent) to 1.0 (opaque). Default 0.20.
    :return: Raw bytes of the watermarked PDF document.
    """
    if not isinstance(pdf_bytes, bytes):
        raise TypeError("pdf_bytes must be of type bytes")
    if not pdf_bytes:
        raise ValueError("pdf_bytes cannot be empty")

    try:
        # Load PDF entirely from in-memory stream
        in_stream = io.BytesIO(pdf_bytes)
        doc = pymupdf.open(stream=in_stream, filetype="pdf")

        if doc.page_count == 0:
            raise ValueError("PDF contains no pages")

        lines = _prepare_watermark_lines(watermark_text)
        longest_line = max(lines, key=len)

        for page_num in range(doc.page_count):
            page = doc[page_num]
            rect = page.rect
            width = rect.width
            height = rect.height

            center_x = width / 2.0
            center_y = height / 2.0
            diagonal_length = math.hypot(width, height)

            # Calculate natural diagonal angle from top-left toward bottom-right
            # Clockwise angle in degrees for PDF coordinates
            diagonal_angle = math.degrees(math.atan2(height, width))

            # Dynamic font sizing to span ~60% to 72% of diagonal safely within page bounds
            base_len_at_100 = pymupdf.get_text_length(longest_line, fontname="helv", fontsize=100)
            if base_len_at_100 > 0:
                target_span = diagonal_length * 0.65
                calc_fontsize = (target_span / base_len_at_100) * 100
            else:
                calc_fontsize = max(18.0, diagonal_length * 0.035)

            # Constrain font size so multi-line stack fits within page bounds and remains readable
            max_stack_fontsize = (diagonal_length * 0.38) / (len(lines) * 1.35)
            fontsize = max(24.0, min(calc_fontsize, max_stack_fontsize, 44.0))

            line_height = fontsize * 1.35
            total_stack_height = len(lines) * line_height

            pivot_point = pymupdf.Point(center_x, center_y)
            rotation_matrix = pymupdf.Matrix(diagonal_angle)

            # Light gray color (0.60, 0.60, 0.60) for subtle, professional confidential watermark
            watermark_color = (0.60, 0.60, 0.60)

            for idx, line in enumerate(lines):
                line_len = pymupdf.get_text_length(line, fontname="helv", fontsize=fontsize)
                # Compute unrotated position centered around (center_x, center_y)
                y_offset = center_y - (total_stack_height / 2.0) + (idx + 0.85) * line_height
                unrotated_pt = pymupdf.Point(center_x - (line_len / 2.0), y_offset)

                try:
                    page.insert_text(
                        unrotated_pt,
                        line,
                        fontname="helv",
                        fontsize=fontsize,
                        color=watermark_color,
                        fill_opacity=opacity,
                        morph=(pivot_point, rotation_matrix)
                    )
                except Exception as insert_err:
                    logger.warning(
                        f"Morph watermark insert fallback on page {page_num + 1}, line {idx}: {insert_err}"
                    )
                    page.insert_text(
                        pymupdf.Point(center_x - line_len / 2.0, center_y + idx * line_height),
                        line,
                        fontname="helv",
                        fontsize=fontsize,
                        color=watermark_color,
                        fill_opacity=opacity
                    )

        # Write output PDF to in-memory bytes stream (never written to disk)
        out_stream = io.BytesIO()
        doc.save(out_stream)
        doc.close()

        return out_stream.getvalue()

    except Exception as e:
        logger.error(f"Failed to apply watermark: {e}")
        raise

