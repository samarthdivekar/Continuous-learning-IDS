"""Build docs/GNN-IDS_Project_Guide.pdf from part1-3.html and the screenshots in img/.

    python docs/guide/build_guide.py

Joins the parts into guide.html (print styles inline), then prints it to PDF with the installed Edge.
"""
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_PDF = HERE.parent / "GNN-IDS_Project_Guide.pdf"

CSS = """
@font-face { font-family: Inter; font-weight: 400; src: url(../../dashboard/fonts/inter-400.woff2) format('woff2'); }
@font-face { font-family: Inter; font-weight: 600; src: url(../../dashboard/fonts/inter-600.woff2) format('woff2'); }
@font-face { font-family: Inter; font-weight: 700; src: url(../../dashboard/fonts/inter-700.woff2) format('woff2'); }
@font-face { font-family: JBM; font-weight: 400; src: url(../../dashboard/fonts/jetbrains-mono-400.woff2) format('woff2'); }
@page { size: A4; margin: 16mm 15mm 18mm;
  @bottom-center { content: "GNN-IDS project guide  \\00b7  page " counter(page); font: 9pt Inter, sans-serif; color: #777; } }
* { box-sizing: border-box; }
body { font: 10.5pt/1.55 Inter, "Segoe UI", sans-serif; color: #15192a; margin: 0; }
h1 { font-size: 30pt; margin: 0 0 8pt; letter-spacing: -0.02em; }
h2 { font-size: 18pt; margin: 0 0 10pt; padding-bottom: 5pt; border-bottom: 2.5px solid #5361e8; letter-spacing: -0.01em; }
h3 { font-size: 13pt; margin: 16pt 0 6pt; color: #232a4d; }
p, li { margin: 0 0 6pt; }
ul, ol { padding-left: 18pt; margin: 0 0 8pt; }
.mono, pre { font-family: JBM, Consolas, monospace; font-size: 0.9em; }
pre { background: #f2f4f9; border: 1px solid #dde2ee; border-radius: 6px; padding: 8pt 10pt; white-space: pre-wrap; font-size: 8.6pt; }
.page-break { page-break-before: always; }
table { width: 100%; border-collapse: collapse; margin: 6pt 0 10pt; font-size: 9.2pt; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th { text-align: left; background: #eef0fb; color: #2a3160; font-weight: 600; padding: 5pt 6pt; border-bottom: 1.5px solid #c7cdf0; }
td { padding: 5pt 6pt; border-bottom: 1px solid #e3e6ef; vertical-align: top; }
table.kv td:first-child { width: 28%; font-weight: 600; color: #2a3160; }
table.qa td:first-child { width: 30%; font-weight: 600; color: #2a3160; }
table.papers { font-size: 8.4pt; }
table.papers td:first-child { width: 4%; font-weight: 700; color: #5361e8; }
table.papers td:nth-child(2) { width: 36%; }
.link { color: #8a5a00; font-size: 0.92em; }
.callout { border-left: 4px solid #5361e8; background: #f1f2ff; padding: 9pt 12pt; border-radius: 0 6px 6px 0; margin: 8pt 0 10pt; }
.callout.big { font-size: 11.5pt; }
.note { color: #555c70; font-size: 9.3pt; }
.example { background: #f4fbf6; border-left: 4px solid #2f9e5b; padding: 7pt 10pt; border-radius: 0 6px 6px 0; }
figure { margin: 8pt 0 12pt; page-break-inside: avoid; text-align: center; }
figure img { max-width: 100%; max-height: 225mm; border: 1px solid #d5d9e4; border-radius: 6px; }
figure img.narrow { max-width: 38%; }
figure img.half { max-width: 70%; }
figure img.crop-top { max-height: 230mm; }
figcaption, .caption { font-size: 8.8pt; color: #555c70; margin-top: 4pt; text-align: center; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10pt; }
.two figure img { max-height: 110mm; }
.two.phone figure img { max-height: 150mm; }
.diagram { margin: 6pt 0 10pt; padding: 8pt; border: 1px solid #e3e6ef; border-radius: 8px; page-break-inside: avoid; }
.cover { height: 250mm; display: flex; flex-direction: column; justify-content: center; padding: 0 10mm;
  background: linear-gradient(160deg, #eef0ff 0%, #ffffff 60%); border-radius: 10px; }
.cover-mark { width: 64pt; height: 64pt; border-radius: 16pt; background: linear-gradient(140deg, #5361e8, #3987e5 60%, #9085e9);
  color: #fff; font-weight: 700; display: grid; place-items: center; font-size: 13pt; margin-bottom: 18pt; }
.cover-sub { font-size: 15pt; color: #33395e; margin-bottom: 14pt; }
.cover-meta { font-size: 10.5pt; color: #555c70; max-width: 150mm; }
.toc ol { font-size: 12pt; line-height: 2; }
"""


def main():
    parts = [(HERE / f"part{i}.html").read_text(encoding="utf-8") for i in (1, 2, 3)]
    html = ("<!doctype html><html lang='en'><head><meta charset='utf-8'><title>GNN-IDS project guide</title>"
            f"<style>{CSS}</style></head><body>" + "\n".join(parts) + "</body></html>")
    page = HERE / "guide.html"
    page.write_text(html, encoding="utf-8")
    edge = next(p for p in (Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")) if p.exists())
    subprocess.run([str(edge), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    "--virtual-time-budget=15000", f"--print-to-pdf={OUT_PDF}", page.as_uri()], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("wrote", OUT_PDF, f"{OUT_PDF.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
