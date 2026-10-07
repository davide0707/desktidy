"""Regenerates docs/demo.svg (terminal demo for the README) and docs/social-preview.png (GitHub link preview).

    python docs/make_images.py
"""

import html
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from desktidy.cli import LOGO  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
COLORS = {"c": "#22d3ee", "b": "#60a5fa", "m": "#c084fc", "g": "#4ade80", "y": "#facc15", "r": "#f87171",
          "w": "#f8fafc", "d": "#64748b", "t": "#cbd5e1"}

# each line: list of (color, text)
LINES = [[("c", " " + LOGO[0])], [("c", " " + LOGO[1])], [("b", " " + LOGO[2])], [("b", " " + LOGO[3])],
         [("m", " " + LOGO[4])], [("m", " " + LOGO[5])],
         [("d", " " + "─" * 64)],
         [("w", "   DeskTidy"), ("d", " v1.0.0  ::  "), ("t", "your files, sorted while you work")],
         [("d", "   by "), ("g", "Di Filippo Davide"), ("d", "  ·  github.com/davide0707/desktidy")],
         [("d", " " + "─" * 64)],
         [("g", "   ● RUNNING"), ("d", "   |   "), ("t", "AI: "), ("c", "moderate"), ("d", "   |   "), ("t", "AI spend: $0.05")],
         [],
         [("g", "┌──("), ("b", "you@desktidy"), ("g", ")-["), ("g", "running"), ("g", "]")],
         [("g", "└─"), ("b", "$ "), ("w", "where invoice")],
         [],
         [("w", "    1 "), ("d", "07/10 21:04  "), ("w", "scan0001.pdf")],
         [("t", "        -> "), ("g", "Documents\\04_Personal\\Bills_and_Receipts"), ("t", "\\"), ("w", "Invoice_2231_Northwind_Energy.pdf")],
         [("d", "        why: text contains 'invoice'; about vat, amount due, due date; renamed (generic name)")],
         [("w", "    2 "), ("d", "07/10 18:40  "), ("w", "Document1.docx")],
         [("t", "        -> "), ("g", "Documents\\01_Study\\Courses\\Maths"), ("t", "\\"), ("w", "Calculus_Limits_and_Derivatives.docx")],
         [("d", "        why: AI (high): calculus lecture notes; renamed (name suggested by AI)")],
         [],
         [("g", "┌──("), ("b", "you@desktidy"), ("g", ")-["), ("g", "running"), ("g", "]")],
         [("g", "└─"), ("b", "$ "), ("w", "spend")],
         [("b", "  [*] "), ("t", "Today "), ("d", "................ "), ("t", "$0.0011   4 files   "), ("d", "(limit 30/day)")],
         [("b", "  [*] "), ("t", "Budget "), ("d", "............... "), ("g", "█"), ("d", "░" * 19), ("t", " 1% of $5.00")],
         [("b", "  [*] "), ("t", "Credit "), ("d", "............... "), ("t", "$4.85 on 2026-10-07  ->  about "), ("g", "$4.84"), ("t", " left")],
         ]


def demo_svg() -> None:
    char_w, line_h, pad = 8.43, 19, 22
    width = int(pad * 2 + 104 * char_w)
    height = int(pad * 2 + 30 + len(LINES) * line_h)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" rx="10" fill="#0b1120"/>',
           '<rect width="100%" height="30" rx="10" fill="#1e293b"/><rect y="20" width="100%" height="10" fill="#1e293b"/>',
           '<circle cx="20" cy="15" r="6" fill="#f87171"/><circle cx="40" cy="15" r="6" fill="#facc15"/>'
           '<circle cx="60" cy="15" r="6" fill="#4ade80"/>',
           '<text x="50%" y="20" text-anchor="middle" fill="#94a3b8" font-family="Segoe UI, sans-serif" '
           'font-size="13">Command Prompt - desktidy</text>',
           '<g font-family="Cascadia Mono, Consolas, DejaVu Sans Mono, Menlo, monospace" font-size="14" xml:space="preserve" style="white-space:pre">']
    for i, parts in enumerate(LINES):
        y = pad + 30 + (i + 1) * line_h - 4
        spans = "".join(f'<tspan fill="{COLORS[c]}">{html.escape(t).replace(" ", "&#160;")}</tspan>' for c, t in parts)
        out.append(f'<text x="{pad}" y="{y}">{spans}</text>')
    out.append("</g></svg>")
    with open(os.path.join(HERE, "demo.svg"), "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def social_png() -> None:
    from PIL import Image, ImageDraw, ImageFont
    w, h = 1280, 640
    im = Image.new("RGB", (w, h), "#0b1120")
    draw = ImageDraw.Draw(im)
    for y in range(h):  # soft vertical gradient
        t = y / h
        draw.line([(0, y), (w, y)], fill=(int(11 + 10 * t), int(17 + 20 * t), int(32 + 40 * t)))
    fonts = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
    mono = ImageFont.truetype(os.path.join(fonts, "consola.ttf"), 26)
    bold = ImageFont.truetype(os.path.join(fonts, "segoeuib.ttf"), 64)
    regular = ImageFont.truetype(os.path.join(fonts, "segoeui.ttf"), 30)
    colors = ["#22d3ee", "#22d3ee", "#60a5fa", "#60a5fa", "#c084fc", "#c084fc"]
    for i, line in enumerate(LOGO):
        draw.text((70, 70 + i * 30), line, font=mono, fill=colors[i])
    draw.text((70, 290), "Your files, sorted while you work.", font=bold, fill="#f8fafc")
    for i, text in enumerate(["Understands each file's content - offline, OCR included",
                              "Renames 'scan0001.pdf' after what's inside",
                              "Claude AI only when needed: ~$0.0003 per file"]):
        draw.text((74, 400 + i * 46), "●  " + text, font=regular, fill="#cbd5e1")
    draw.text((74, 560), "github.com/davide0707/desktidy  ·  Windows 10/11  ·  MIT", font=regular, fill="#64748b")
    im.save(os.path.join(HERE, "social-preview.png"), optimize=True)


if __name__ == "__main__":
    demo_svg()
    social_png()
    print("docs/demo.svg and docs/social-preview.png updated")
