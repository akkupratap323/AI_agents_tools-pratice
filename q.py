import sqlite3,sys
con = sqlite3.connect("shop.db")
cur = con.cursor()
cur.execute(sys.argv[1])
print([d[0] for d in cur.description]) #column names
for row in cur.fetchall():
    print(row)

    #customers (20)        products (12)          orders (600)            order_items (1219)
#─────────────         ─────────────          ────────────            ──────────────────
#id                    id                     id                      id
#name                  name                   customer_id → customers order_id   → orders
#email   (nullable)    category               order_date  'YYYY-MM-DD' product_id → products
#city    (nullable)    price_paise (nullable) status                  quantity
#signup_date                                                          #unit_price_paise
#