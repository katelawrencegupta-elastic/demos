"""Generate a synthetic orders data set for the 1,254-product catalog, backfilling the last 31 days.
One document per order line (flat, so ES|QL and aggregations stay simple). Deterministic: same seed, same data.
Writes data/orders.json. Load it with 15_load_orders.py."""
import json, math, random, pathlib, datetime as dt
from collections import Counter, defaultdict
D = pathlib.Path(__file__).parent / "data"
SEED = 20261113
DAYS = 31
rng = random.Random(SEED)
now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
start = (now - dt.timedelta(days=DAYS - 1)).replace(hour=0, minute=0, second=0)

products = json.loads((D / "products.json").read_text())
cats = sorted({p["category"] for p in products})

# --- product popularity: category weight x zipf rank x rating x mild price preference ---
cat_w = {c: rng.uniform(0.6, 1.6) for c in cats}
order = list(range(len(products))); rng.shuffle(order)
rank = {i: r + 1 for r, i in enumerate(order)}
pw = [cat_w[p["category"]] / rank[i] ** 0.75 * (p["rating"] / 4.0) ** 2 / (1 + p["price"] / 200) for i, p in enumerate(products)]

# --- customers: stable region/country, repeat buying skewed to a loyal minority ---
REGIONS = {"NA": (["US", "CA", "MX"], [80, 14, 6]), "EMEA": (["GB", "DE", "FR", "NL", "ES", "SE"], [28, 24, 18, 10, 12, 8]), "APAC": (["AU", "JP", "SG", "IN", "NZ"], [30, 26, 14, 22, 8])}
N_CUST = 2600
customers = []
for i in range(N_CUST):
    region = rng.choices(list(REGIONS), [52, 30, 18])[0]
    countries, w = REGIONS[region]
    customers.append({"id": f"C-{i + 1:05d}", "region": region, "country": rng.choices(countries, w)[0]})
cw = [1 / (i + 1) ** 0.55 for i in range(N_CUST)]

# --- demand curve: weekday, hour of day, gentle ramp into the holiday season, Nov 11 bump ---
DOW = [0.95, 0.90, 0.90, 0.95, 1.05, 1.20, 1.15]
HOUR = [1, .6, .4, .3, .3, .5, 1, 2, 3, 3.5, 3.8, 4, 4.2, 4, 3.8, 3.8, 4, 4.5, 5.5, 6.5, 6.5, 5.5, 3.5, 2]
BASE_ORDERS_PER_DAY = 230
def day_orders(d):
    i = (d - start).days
    f = DOW[d.weekday()] * (1 + 0.30 * i / (DAYS - 1))
    if d.month == 11 and d.day == 11: f *= 1.25
    return int(BASE_ORDERS_PER_DAY * f * rng.uniform(0.93, 1.07))

PAY = (["card", "paypal", "apple_pay", "bnpl"], [62, 22, 11, 5])
CHAN = (["web", "mobile_app", "marketplace"], [55, 38, 7])
RETURN_RATE = {"beauty & personal care": .02, "audio & consumer electronics": .07, "running & fitness wearables": .06, "travel & luggage": .05, "bike components & accessories": .05}
COUPONS = [(None, 0.0), ("WELCOME10", 0.10), ("SAVE15", 0.15), ("VIP25", 0.25)]

def status_for(ts, cat):
    age = (now - ts).total_seconds() / 86400
    if rng.random() < 0.03: return "cancelled", None
    if age < 1.5: return "processing", None
    if age < 4:
        if rng.random() < 0.55: return "shipped", None
        return "delivered", ts + dt.timedelta(days=rng.uniform(2, min(age, 4)))
    deliv = ts + dt.timedelta(days=rng.uniform(2, 6))
    if age > 10 and rng.random() < RETURN_RATE.get(cat, .035): return "returned", deliv
    return "delivered", deliv

rows, n_orders = [], 0
for dayn in range(DAYS):
    day = start + dt.timedelta(days=dayn)
    for _ in range(day_orders(day)):
        h = rng.choices(range(24), HOUR)[0]
        ts = day + dt.timedelta(hours=h, minutes=rng.randrange(60), seconds=rng.randrange(60))
        if ts > now: continue
        n_orders += 1
        oid = f"ORD-{ts:%y%m%d}-{n_orders:05d}"
        cust = customers[rng.choices(range(N_CUST), cw)[0]]
        channel = rng.choices(*CHAN)[0]; pay = rng.choices(*PAY)[0]
        n_lines = rng.choices([1, 2, 3, 4], [68, 22, 8, 2])[0]
        promo_boost = 2.2 if (day.month == 11 and day.day >= 9) else 1.0
        coupon, pct = (None, 0.0)
        if rng.random() < 0.30 * promo_boost: coupon, pct = rng.choices(COUPONS[1:], [60, 30, 10])[0]
        picked = set()
        for ln in range(1, n_lines + 1):
            i = rng.choices(range(len(products)), pw)[0]
            if i in picked: continue
            picked.add(i); p = products[i]
            qty = rng.choices([1, 2, 3, 4], [82, 13, 4, 1] if p["price"] >= 30 else [60, 25, 10, 5])[0]
            status, delivered = status_for(ts, p["category"])
            line = round(p["price"] * qty * (1 - pct), 2)
            rows.append({"@timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "order_id": oid, "line_no": ln, "order_line_count": n_lines,
                         "customer_id": cust["id"], "region": cust["region"], "country": cust["country"],
                         "channel": channel, "payment_method": pay, "coupon_code": coupon,
                         "sku": p["sku"], "product_name": p["name"], "brand": p["brand"], "category": p["category"],
                         "quantity": qty, "unit_price": p["price"], "discount_pct": round(pct * 100), "line_total": line,
                         "status": status, "delivered_at": delivered.strftime("%Y-%m-%dT%H:%M:%SZ") if delivered else None})
(D / "orders.json").write_text(json.dumps(rows, ensure_ascii=False))
rev = sum(r["line_total"] for r in rows if r["status"] not in ("cancelled", "returned"))
print(f"{n_orders:,} orders, {len(rows):,} lines, {len({r['sku'] for r in rows}):,} distinct products, {len({r['customer_id'] for r in rows}):,} customers")
print(f"window {rows[0]['@timestamp']} -> {rows[-1]['@timestamp']} | net revenue ${rev:,.0f}")
print("status:", dict(Counter(r["status"] for r in rows)))
bycat = defaultdict(float)
for r in rows: bycat[r["category"]] += r["line_total"]
print("top categories:", [(c, round(v)) for c, v in sorted(bycat.items(), key=lambda x: -x[1])[:3]])
