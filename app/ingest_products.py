# ingest_products.py
import csv, requests, time, html, re

API = "http://localhost:8080/ingest"
HEADERS = {"x-api-key": "dev-secret-choose-your-own", "Content-Type": "application/json"}
CSV_PATH = "df_all_3_new.csv"   # adjust path

def clean(s: str) -> str:
    if not s: return ""
    s = html.unescape(str(s))
    s = re.sub(r"\s+", " ", s).strip()
    return s

def build_text(row):
    # Build a rich text field to maximize recall
    parts = [
        f"Категория: {clean(row.get('parent_cat'))} > {clean(row.get('lower_cat'))}",
        f"URL: {clean(row.get('product_url'))}",
        f"Описание: {clean(row.get('product_description'))}",
    ]
    return "\n".join([p for p in parts if p and p.strip()])

def main(max_rows=2000, pause=0.0):
    sent = 0
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                sku = int(row["sku_id"])
            except Exception:
                continue
            payload = {
                "id": sku,
                "title": clean(row.get("lower_cat")) or clean(row.get("parent_cat")) or "Товар",
                "text": build_text(row),
                "url": clean(row.get("product_url")) or None
            }
            r = requests.post(API, headers=HEADERS, json=payload, timeout=30)
            if r.status_code != 200:
                print("Failed", sku, r.status_code, r.text[:200])
            else:
                sent += 1
                if sent % 100 == 0: print("Ingested", sent)
            if sent >= max_rows: break
            if pause: time.sleep(pause)
    print("Done. Ingested:", sent)

if __name__ == "__main__":
    main(max_rows=1000)   # try 2k first
