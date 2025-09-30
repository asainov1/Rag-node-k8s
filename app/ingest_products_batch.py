# app/ingest_products_batch.py
import csv, requests, time, html, re, argparse
from typing import List, Dict, Any, Optional

API = "http://127.0.0.1:8080/ingest_batch"   # batch endpoint
HEADERS = {"x-api-key": "dev-secret-choose-your-own", "Content-Type": "application/json"}

def clean(s: str) -> str:
    if not s: return ""
    s = html.unescape(str(s))
    s = re.sub(r"\s+", " ", s).strip()
    return s

def build_text(row: Dict[str, str]) -> str:
    parts = [
        f"Категория: {clean(row.get('parent_cat'))} > {clean(row.get('lower_cat'))}",
        f"URL: {clean(row.get('product_url'))}",
        f"Описание: {clean(row.get('product_description'))}",
    ]
    return "\n".join([p for p in parts if p])

def post_batch(items: List[Dict[str, Any]], max_retries=6, timeout=180) -> requests.Response:
    delay = 1.0
    for _ in range(max_retries):
        r = requests.post(API, headers=HEADERS, json={"items": items}, timeout=timeout)
        # Retry on 429/5xx
        if r.status_code not in (429, 500, 502, 503, 504):
            return r
        time.sleep(delay)
        delay = min(delay * 2, 30)
    return r

def run(csv_path: str, batch_size: int, max_rows: Optional[int], sleep_between: float):
    sent_docs = 0
    batch: List[Dict[str, Any]] = []

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # build one doc
            try:
                sku = int(row["sku_id"])
            except Exception:
                continue

            batch.append({
                "id": sku,
                "title": clean(row.get("lower_cat")) or clean(row.get("parent_cat")) or "Товар",
                "text": build_text(row),
                "url": clean(row.get("product_url")) or None,
                # structured payload fields (server stores these into Qdrant payload)
                "parent_cat": clean(row.get("parent_cat")),
                "lower_cat":  clean(row.get("lower_cat")),
                "brand":      clean(row.get("brand")) if "brand" in row else None,
                "color":      clean(row.get("color")) if "color" in row else None,
            })

            # send a batch
            if len(batch) >= batch_size:
                r = post_batch(batch)
                if r.status_code != 200:
                    print("Batch failed:", r.status_code, r.text[:200])
                else:
                    sent_docs += len(batch)
                    if sent_docs % (batch_size * 5) == 0:
                        print(f"Ingested docs: {sent_docs}")
                batch.clear()
                if sleep_between:
                    time.sleep(sleep_between)

            if max_rows and sent_docs >= max_rows:
                break

    # flush any remainder
    if batch and (not max_rows or sent_docs < max_rows):
        r = post_batch(batch)
        if r.status_code != 200:
            print("Final batch failed:", r.status_code, r.text[:200])
        else:
            sent_docs += len(batch)

    print("Done. Ingested docs:", sent_docs)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="df_all_3.csv")
    ap.add_argument("--batch_size", type=int, default=300)
    ap.add_argument("--max_rows", type=int, default=10000)  # change/raise for bigger runs
    ap.add_argument("--sleep", type=float, default=0.0)
    args = ap.parse_args()
    run(args.csv, args.batch_size, args.max_rows if args.max_rows > 0 else None, args.sleep)
