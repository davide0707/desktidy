"""How well does the chosen AI service sort and name files? `desktidy ai test` sends 18 made-up documents (never
yours: invoices, bills, a payslip, lecture notes, a contract, a recipe, a flight booking...) to the service and
compares its answers with the right ones: the folder, the name, the date of the document and the deadline.

  desktidy ai test            run it (the price is shown first; free plans cost nothing)
  desktidy ai test --dry      only what would be sent: files, folders, size; nothing leaves this PC

The documents are written to a temporary folder and deleted afterwards. The spend is booked like any other
request (desktidy spend), but not against the daily file limit: the test never takes the AI away from the service.
The made-up IBAN and tax code are masked like real ones (redact.py) when the service is on the internet.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field

from . import config

FOLDERS = ["Personal/Bills", "Personal/Payslips", "Personal/CV", "Personal/Health", "Personal/Car", "Personal/Bank",
           "Personal/Taxes", "Study/Maths", "Study/Physics", "Study/Thesis", "Home/Rent", "Home/Manuals",
           "Work/Meetings", "Work/Contracts", "Recipes", "Travel", "Projects/Python"]


@dataclass
class Case:
    file: str                       # its name (generic names like scan0001.pdf must be renamed)
    lines: list[str]
    folder: str | None              # the right folder, None = none fits
    name: list[list[str]] = field(default_factory=list)   # each group: one of these words must be in the new name
    date: str = ""                  # the date of the document, YYYY-MM-DD
    due: str = ""                   # the deadline, YYYY-MM-DD


CASES = [
    Case("scan0001.pdf", ["ACME S.r.l. - Via Roma 1, Milano - P.IVA 01234567897", "Fattura n. 2231 del 30/09/2026",
                          "Cliente: Mario Rossi - C.F. RSSMRA80A01H501U", "Consulenza informatica di settembre",
                          "Imponibile 1.000,00 - IVA 22% 220,00", "Totale da pagare 1.220,00 entro il 30/10/2026",
                          "Bonifico su IBAN IT60 X054 2811 1010 0000 0123 456"],
         "Personal/Bills", [["2231"], ["acme"]], "2026-09-30", "2026-10-30"),
    Case("document.pdf", ["Northwind Energia S.p.A.", "Bolletta luce - fornitura di energia elettrica",
                          "Periodo: agosto - settembre 2026, consumo 412 kWh", "Data emissione: 05/10/2026",
                          "Importo da pagare: 84,20 euro", "Scadenza: 25/10/2026", "Codice cliente 55120"],
         "Personal/Bills", [["northwind"]], "2026-10-05", "2026-10-25"),
    Case("download (3).pdf", ["Contoso S.p.A. - Cedolino paga", "Dipendente: Mario Rossi, matricola 0042",
                              "Mese di retribuzione: settembre 2026", "Retribuzione lorda 2.400,00",
                              "Trattenute INPS e IRPEF 600,00", "Netto in busta 1.800,00", "Data: 27/09/2026"],
         "Personal/Payslips", [["busta", "cedolino", "payslip", "stipendio", "retribuzione"]], "2026-09-27"),
    Case("cv_mario_rossi.txt", ["Curriculum vitae - Mario Rossi", "Esperienza: sviluppatore software, 2019-2026",
                                "Istruzione: laurea in ingegneria informatica", "Lingue: inglese C1, tedesco B1",
                                "Competenze: Python, C, sistemi embedded"], "Personal/CV"),
    Case("scan0002.pdf", ["Ambulatorio Cardiologico Esempio", "Referto di visita cardiologica del 12/08/2026",
                          "Paziente: Mario Rossi", "Elettrocardiogramma nella norma, pressione 120/80",
                          "Si consiglia controllo tra un anno"],
         "Personal/Health", [["referto", "visita", "cardiolog"]], "2026-08-12"),
    Case("scan0003.pdf", ["Contoso Assicurazioni", "Polizza RC Auto n. 778812", "Emessa il 15/11/2025",
                          "Veicolo: utilitaria targa AB123CD", "Premio annuo 420,00 euro",
                          "La polizza scade il 15/11/2026: rinnovo entro e non oltre il 15/11/2026"],
         "Personal/Car", [["polizza", "assicurazion", "rc"]], "2025-11-15", "2026-11-15"),
    Case("estratto.pdf", ["Banca Esempio", "Estratto conto corrente al 30/09/2026", "Saldo iniziale 3.210,00",
                          "Movimenti: stipendio, bolletta, supermercato", "Saldo finale 4.020,00"],
         "Personal/Bank", [["estratto", "conto"]], "2026-09-30"),
    Case("scan0004.pdf", ["Modello F24 - delega di pagamento", "Contribuente: Mario Rossi",
                          "Sezione erario: saldo IRPEF anno 2025", "Importo 312,00",
                          "Da versare entro il 16/11/2026"],
         "Personal/Taxes", [["f24"]], "", "2026-11-16"),
    Case("lezione_3.txt", ["Analisi matematica 1 - lezione 3", "Limiti di funzioni e forme indeterminate",
                           "Derivate: regole di derivazione, derivata della funzione composta",
                           "Teorema di Lagrange e teorema di Rolle, esercizi sugli asintoti"], "Study/Maths"),
    Case("untitled.txt", ["Lab report: the simple pendulum", "We measured the period of a pendulum for five lengths",
                          "The gravitational acceleration from the fit is 9.79 m/s^2",
                          "Sources of error: air resistance, reaction time"],
         "Study/Physics", [["pendulum", "pendolo", "lab"]]),
    Case("capitolo2_bozza.txt", ["Tesi di laurea - Capitolo 2: stato dell'arte",
                                 "Le energie rinnovabili in Europa: fotovoltaico ed eolico",
                                 "Revisione della letteratura e metodologia della ricerca"], "Study/Thesis"),
    Case("document1.txt", ["Contratto di locazione ad uso abitativo", "Tra il locatore Giulia Bianchi e il "
                           "conduttore Mario Rossi", "Canone mensile 750,00 euro, deposito cauzionale tre mensilita",
                           "Durata quattro anni rinnovabile", "Milano, 01/09/2026"],
         "Home/Rent", [["contratto", "locazione", "affitto"]], "2026-09-01"),
    Case("meeting.txt", ["Minutes of the project meeting, 2026-10-08", "Attendees: Anna, Luca, Mario",
                         "Decisions: release on 1 December, freeze features next week",
                         "Action items: Luca updates the roadmap, Anna prepares the demo"],
         "Work/Meetings", [], "2026-10-08"),
    Case("agreement_final.txt", ["Service agreement between Contoso Ltd and Fabrikam Inc",
                                 "Effective date: 1 July 2026", "Scope: maintenance of the web platform",
                                 "Fees, termination, confidentiality and governing law"], "Work/Contracts", [],
         "2026-07-01"),
    Case("ricetta.txt", ["Tiramisu classico", "Ingredienti: mascarpone 500 g, savoiardi, caffe, uova, zucchero, "
                         "cacao amaro", "Preparazione: montare i tuorli con lo zucchero, unire il mascarpone"],
         "Recipes"),
    Case("itinerary.pdf", ["Booking confirmation", "Flight AZ 784 Milano Malpensa - Tokyo Narita",
                           "Departure 14 March 2027, 13:05", "Passenger: Mario Rossi, booking reference QX7P2L",
                           "Issued on 02/10/2026"], "Travel", [["tokyo", "flight", "volo"]], "2026-10-02"),
    Case("script_backup.txt", ["import argparse", "", "def main():",
                               "    parser = argparse.ArgumentParser(description='rename photos by date')",
                               "    args = parser.parse_args()", "", "if __name__ == '__main__':", "    main()"],
         "Projects/Python"),
    Case("notes.txt", ["milk", "eggs", "bread", "two lemons", "call the plumber"], None),
]


@dataclass
class Result:
    case: Case
    folder: str | None = None
    name: str = ""
    date: str = ""
    due: str = ""
    asked_name: bool = False
    shown: str = ""                 # the folder the AI chose, relative to the test folders ("none" if none)
    folder_ok: bool = False
    name_ok: bool | None = None     # None: no name was asked or none is expected
    date_ok: bool | None = None
    due_ok: bool | None = None


def _pdf(path: str, lines: list[str]) -> None:
    """A small PDF with real text, like the ones exported by Word (Latin-1 characters only)."""
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = "BT /F1 11 Tf 50 780 Td 15 TL " + " ".join(f"({esc(x)}) '" for x in lines) + " ET"
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
               "/Resources << /Font << /F1 5 0 R >> >> >>",
               f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offsets = "%PDF-1.4\n", []
    for i, o in enumerate(objects, 1):
        offsets.append(len(out.encode("latin-1")))
        out += f"{i} 0 obj\n{o}\nendobj\n"
    xref = len(out.encode("latin-1"))
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n" + "".join(f"{q:010d} 00000 n \n" for q in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    with open(path, "w", encoding="latin-1", newline="\n") as f:
        f.write(out)


def prepare(root: str) -> tuple[list[str], dict[str, Case]]:
    """The folders and the documents in `root`; (the folder paths, {document path: case})."""
    paths = [os.path.join(root, *f.split("/")) for f in FOLDERS]
    for p in paths:
        os.makedirs(p, exist_ok=True)
    inbox = os.path.join(root, "Inbox")
    os.makedirs(inbox, exist_ok=True)
    docs = {}
    for c in CASES:
        p = os.path.join(inbox, c.file)
        if p.endswith(".pdf"):
            _pdf(p, c.lines)
        else:
            with open(p, "w", encoding="utf-8") as f:
                f.write("\n".join(c.lines) + "\n")
        docs[p] = c
    return paths, docs


def test_config(cfg: config.Config, root: str, areas: list[str]) -> config.Config:
    """The user's AI service and model, the "all" mode (every made-up document is asked), the test folders only,
    each one an area the AI always sees (they are empty: similarity alone would not offer them)."""
    ai = {k: v for k, v in cfg.ai.items() if k in ("provider", "model", "base_url", "vision", "redact", "language",
                                                    "price_per_million", "budget_usd", "credit_reserve_usd")}
    data = {"variables": {}, "watched_folders": [], "default_destination": os.path.join(root, "To_Sort"),
            "analysis": {"ocr": False, "similarity": False}, "rename": {"mode": "smart"}, "rules": [],
            "ai": {**ai, "mode": config.EVERYTHING, "delivery": "instant", "max_folders_per_file": 40,
                   "candidate_folders": [{"path": p, "depth": 0} for p in areas], "max_files_per_day": "unlimited"}}
    return config.Config(data, cfg.source)


def _score(r: Result, root: str) -> Result:
    c = r.case
    want = os.path.normcase(os.path.join(root, *c.folder.split("/"))) if c.folder else None
    r.folder_ok = (os.path.normcase(r.folder) if r.folder else None) == want
    r.shown = "none" if not r.folder else os.path.relpath(r.folder, root).replace(os.sep, "/") \
        if config.inside(r.folder, root) else r.folder
    if r.asked_name and c.name:
        low = config.strip_accents(r.name).lower()
        r.name_ok = all(any(w in low for w in group) for group in c.name)
    if c.date:
        r.date_ok = r.date == c.date
    if c.due:
        r.due_ok = r.due == c.due
    return r


def run(cfg: config.Config, key: str, log, send: bool = True) -> dict:
    """Ask the AI about the made-up documents; {"results", "summary", "requests", "chars"}. send=False builds the
    requests without sending them (desktidy ai test --dry)."""
    from . import ai, classifier, folders, naming
    from . import content as ct
    root = tempfile.mkdtemp(prefix="desktidy_ai_test_")
    started = time.time()
    pinned = folders.active_pinned
    folders.active_pinned = lambda: []  # hermetic: your pinned folders are neither used nor shown to the AI
    try:
        areas, docs = prepare(root)
        tcfg = test_config(cfg, root, areas)
        folders._catalog["value"] = None
        items = []
        for path, c in docs.items():
            an = ct.analyze(path, False, tcfg)
            d = classifier.decide(path, False, tcfg, an)
            items.append((ai.item_for(path, False, os.path.dirname(path), an, d, naming.plan(an, tcfg), tcfg), c))
        results, requests, chars = [], 0, 0
        for start in range(0, len(items), ai.MAX_FILES_PER_REQUEST):
            chunk = items[start:start + ai.MAX_FILES_PER_REQUEST]
            params, folder_list = ai.build([i for i, _ in chunk], tcfg)
            requests += 1
            chars += sum(len(b.get("text", "")) for b in params["messages"][0]["content"])
            if not send:
                continue
            text = ai.complete(params, tcfg, key, log, files=0)   # booked as spend, not against the file limit
            answers = ai.parse(text, len(chunk), folder_list) if text else {}
            for n, (item, c) in enumerate(chunk, 1):
                a = answers.get(n)
                r = Result(c, asked_name=item.ask_name)
                if a:
                    r.folder, r.name, r.date, r.due = a.folder, a.name, a.date, a.due
                results.append(_score(r, root))
        summary = summarise(results) if send else {}
        return {"results": results, "summary": summary, "requests": requests, "chars": chars,
                "seconds": round(time.time() - started, 1), "documents": len(docs)}
    finally:
        folders.active_pinned = pinned
        shutil.rmtree(root, ignore_errors=True)
        folders._catalog["value"] = None


def summarise(results: list[Result]) -> dict:
    def share(values):
        values = [v for v in values if v is not None]
        return (sum(values), len(values))
    return {"folder": share(r.folder_ok for r in results), "name": share(r.name_ok for r in results),
            "date": share(r.date_ok for r in results), "due": share(r.due_ok for r in results)}
