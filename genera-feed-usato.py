#!/usr/bin/env python3
"""Genera il feed CSV delle auto usate di International Motors per il catalogo veicoli di Meta.

Legge le pagine pubbliche dell'elenco usato (dati strutturati schema.org di ogni auto), non usa
nessun account di terzi e non scrive nulla sul sito. Uso:

    python -X utf8 "07 Strumenti/genera-feed-usato.py" [file_uscita.csv]

Senza argomento scrive "05 Automazioni/feed-usato-meta.csv" (dal vault). Pensato per girare ogni
notte (vedi nota "Campagna usato funnel 15 euro - piano"). Solo libreria standard.
"""
import csv, html, json, re, sys, time, urllib.error, urllib.request
from collections import Counter
from pathlib import Path

BASE = "https://www.internationalmotors.it/auto/usate/?page={}"
UA = {"User-Agent": "Mozilla/5.0 (feed-usato-IM)"}
SUV = {"range-rover-sport-phev", "range-rover-phev", "discovery", "bigster", "ecosport", "evoque", "range-rover-evoque", "discovery-sport", "range-rover-sport", "range-rover-velar",
       "range-rover", "defender", "e-pace", "f-pace", "x3", "c5-aircross", "tiguan", "stelvio", "glc",
       "gla", "renegade", "zs", "hs", "ehs", "xv", "cx-5", "kona", "tucson", "3008", "countryman"}
HATCH = {"a3-sportback", "panda", "208", "mini", "cooper", "golf", "serie-1", "c3"}
WAGON = {"v60", "golf-sportsvan", "serie-2-active-tourer"}
SALOON = {"s-type", "xf", "xe", "serie-3"}
SPECIAL = {"e-pace": "E-Pace", "f-pace": "F-Pace", "f-type": "F-Type", "ehs": "EHS", "zs": "ZS", "hs": "HS"}


def get(url, tries=5):
    """Scarica una pagina con una pausa fra una richiesta e l'altra e nuovi tentativi se il sito risponde 429/5xx
    (dagli indirizzi di GitHub il sito può rallentare: il 2026-11-05 la prima corsa ha preso un 429)."""
    time.sleep(2)
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40).read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if i == tries - 1 or e.code not in (429, 500, 502, 503, 504):
                raise
            time.sleep(20 * (i + 1))
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(5)


def vehicles_in(html_text, seen):
    n = 0
    for block in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html_text, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        stack = [data]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                if o.get("@type") in ("Vehicle", "Car") and o.get("url") and o.get("offers"):
                    seen[o["url"]] = o
                    n += 1
                stack.extend(o.values())
            elif isinstance(o, list):
                stack.extend(o)
    return n


ROOT = "https://www.internationalmotors.it/auto/usate/"


def vehicles():
    """Il sito mostra 15 auto per pagina, ma la prima pagina è l'indirizzo SENZA ?page= (e ?page=1 mostra
    la seconda: verificato il 2026-11-05). Si legge quindi l'indirizzo base e poi ?page=1,2,3... fino a
    una pagina vuota, deduplicando per link, e si confronta con il totale dichiarato dal sito."""
    seen = {}
    root_html = get(ROOT)
    m = re.search(r"(\d+)\s+risultati trovati", re.sub(r"<[^>]+>", " ", root_html))
    total = int(m.group(1)) if m else None
    vehicles_in(root_html, seen)
    for page in range(1, 30):
        if vehicles_in(get(ROOT + f"?page={page}"), seen) == 0:
            break
    if total and len(seen) != total:
        print(f"ATTENZIONE: il sito dichiara {total} auto, ne ho lette {len(seen)}", file=sys.stderr)
    return list(seen.values())


def dedupe_words(s):
    w = s.split()
    changed = True
    while changed:
        changed = False
        for n in range(4, 0, -1):
            for i in range(len(w) - 2 * n + 1):
                if [x.lower() for x in w[i:i + n]] == [x.lower() for x in w[i + n:i + 2 * n]]:
                    del w[i + n:i + 2 * n]
                    changed = True
                    break
            if changed:
                break
    return " ".join(w)


def norm_sede(txt):
    """Il sito scrive la stessa sede in modi diversi (Via Luigi Galvani, 'CALVANI', Rossi 21/23): si riporta alle 3 sedi."""
    low = txt.lower()
    for k, v in SEDI.items():
        if k in low:
            return v
    return txt.strip()


def address(o):
    desc = html.unescape(o.get("description", ""))
    m = re.search(r"si trova in:\s*(.+?),\s*(\d{5})\s+([^()]+?)\s*\((\w{2})\)", desc)
    seller = (o["offers"].get("seller") or {}).get("address") or {}
    if m:
        return {"addr1": norm_sede(m.group(1)), "city": m.group(3).strip(), "region": "Toscana",
                "postal_code": m.group(2), "country": "IT"}
    return {"addr1": norm_sede(seller.get("streetAddress", "")), "city": seller.get("addressLocality", ""),
            "region": "Toscana", "postal_code": CAP.get(seller.get("addressLocality", ""), ""), "country": "IT"}


# Il sito scrive in molte schede che il prezzo "è legato a finanziamento" o "riservato a fronte di finanziamento o leasing"
# (verificato il 2026-11-05: 53 auto su 68). Quelle auto non possono mostrare quel prezzo come prezzo libero in un annuncio.
PREZZO_VINCOLATO = re.compile(r"(prezz\w*[^.]{0,80}(legat\w*|riservat\w*|vincolat\w*|subordinat\w*)[^.]{0,60}(finan\w*|leasing))"
                              r"|((legat\w*|riservat\w*)[^.]{0,30}(finan\w*|leasing))", re.I)


def prezzo_vincolato(o):
    return bool(PREZZO_VINCOLATO.search(html.unescape(o.get("description", ""))))


def fascia(price):
    """Fascia di prezzo (decisa il 2026-11-05 dalle vendite usato: 74% sotto i 20.000 €, quasi nulla oltre i 40.000 €)."""
    p = int(price)
    return "sotto 8k" if p < 8000 else "8-40k" if p <= 40000 else "oltre 40k"


def body_style(slug, title):
    """Tipo di carrozzeria dedotto dal modello (il sito non lo mette nei dati strutturati): 'OTHER' se incerto."""
    if "touring" in title.lower() or slug in WAGON:
        return "WAGON"
    if slug in SUV:
        return "SUV"
    if slug in HATCH:
        return "HATCHBACK"
    if slug in SALOON:
        return "SALOON"
    return "OTHER"


CAP = {"Firenze": "50145", "Arezzo": "52100"}
SEDI = {"galvani": "Via Galvani 30", "calvani": "Via Galvani 30", "rossi": "Via E. Rossi 21",
        "malaparte": "Via Curzio Malaparte 10"}


def row(o):
    off = o["offers"]
    price = off.get("price")
    if not price:
        return None
    slug = o["url"].split("/usate/")[1].split("/")
    model_slug = slug[2] if len(slug) > 2 else ""
    make = (o.get("brand") or {}).get("name", "") if isinstance(o.get("brand"), dict) else str(o.get("brand", ""))
    model = SPECIAL.get(model_slug) or model_slug.replace("-", " ").title()
    title = dedupe_words(html.unescape(o["name"]).replace("…", "").strip())
    km = (o.get("mileageFromOdometer") or {}).get("value", "")
    year = o.get("vehicleModelDate", "")
    desc = f"{title}. {int(km):,} km".replace(",", ".") if km != "" else title
    desc += f", {o.get('fuelType', '')}, cambio {str(o.get('vehicleTransmission', '')).lower()}, {address(o)['city']}. Pronta consegna: scopri la scheda completa sul sito."
    return {
        "vehicle_id": o.get("sku") or o.get("productId"),
        "title": title,
        "description": desc,
        "url": o["url"],
        "make": make,
        "model": model,
        "year": year,
        "mileage.value": km,
        "mileage.unit": "KM",
        "image[0].url": o.get("image", ""),
        "price": f"{price} EUR",
        "state_of_vehicle": "USED",
        "body_style": body_style(model_slug, title),
        "exterior_color": o.get("color", ""),
        "transmission": {"Automatico": "AUTOMATIC", "Manuale": "MANUAL"}.get(o.get("vehicleTransmission", ""), "OTHER"),
        "fuel_type": {"Diesel": "DIESEL", "Benzina": "GASOLINE", "GPL": "OTHER", "Ibrida": "HYBRID",
                      "Diesel/Elettrica": "HYBRID", "Elettrica": "ELECTRIC"}.get(o.get("fuelType", ""), "OTHER"),
        "vin": o.get("vehicleIdentificationNumber", ""),
        "address": json.dumps(address(o), ensure_ascii=False),
        "availability": "AVAILABLE",
        # Etichette per creare gli insiemi di prodotti in Meta (il filtro per prezzo non esiste nei cataloghi veicoli)
        "custom_label_0": fascia(price),
        "custom_label_1": "JLR" if make in ("Land Rover", "Jaguar") else "altre marche",
        "custom_label_2": "prezzo con finanziamento" if prezzo_vincolato(o) else "prezzo libero",
    }


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("05 Automazioni/feed-usato-meta.csv")
    rows = [r for r in (row(o) for o in vehicles()) if r]
    if len(rows) < 20:  # protezione: se il sito risponde male non sovrascrivere un buon file
        sys.exit(f"Solo {len(rows)} auto lette: file non scritto.")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    bands = Counter()
    for r in rows:
        p = int(r["price"].split()[0])
        bands["<8k" if p < 8000 else "8-40k" if p <= 40000 else ">40k"] += 1
    print(f"{len(rows)} auto scritte in {out} | fasce: {dict(bands)} | senza foto: {sum(1 for r in rows if not r['image[0].url'])}")


if __name__ == "__main__":
    main()
