"""Render a region of a paper PDF and save its source coordinates."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

import pymupdf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path, help="Output PNG path")
    parser.add_argument("--page", type=int, required=True, help="One-based PDF page")
    parser.add_argument("--clip", type=float, nargs=4, required=True, metavar=("X0", "Y0", "X1", "Y1"))
    parser.add_argument("--figure", required=True, help="Original figure or table label")
    parser.add_argument("--source", required=True, help="Primary source URL")
    parser.add_argument("--version", required=True, help="Paper version identifier")
    parser.add_argument("--dpi", type=int, default=180)
    args = parser.parse_args()
    if args.output.suffix.lower() != ".png" or args.dpi <= 0:
        parser.error("Use a PNG output and positive DPI")
    with pymupdf.open(args.pdf) as document:
        if not 1 <= args.page <= len(document):
            parser.error("Page is outside the PDF")
        page = document[args.page - 1]
        clip = pymupdf.Rect(args.clip)
        if clip.is_empty or not page.rect.contains(clip):
            parser.error("Clip must be nonempty and within the page")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        page.get_pixmap(clip=clip, dpi=args.dpi, alpha=False).save(args.output)
    provenance = {
        "source": args.source,
        "version": args.version,
        "source_pdf_sha256": sha256(args.pdf.read_bytes()).hexdigest(),
        "page": args.page,
        "figure": args.figure,
        "clip_points": args.clip,
        "dpi": args.dpi,
    }
    args.output.with_suffix(".json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    print(f"Rendered {args.figure}, PDF page {args.page}")


if __name__ == "__main__":
    main()
