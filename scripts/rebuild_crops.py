#!/usr/bin/env python3
"""Rebuild crop tags from scratch using centralized parser.
Run this after database update to regenerate clean crop tags."""

import sqlite3
import os
import sys
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.crop_parser import extract_crops

DB_PATH = os.path.join(BASE_DIR, 'data', 'reestr.db')
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

print("=== Rebuilding crop tags ===")

# Step 1: Clear existing crop tags
cur.execute("DELETE FROM product_tags WHERE tag_id IN (SELECT id FROM tags WHERE category = 'crop')")
print(f'Deleted {cur.rowcount} crop product_tags')
cur.execute("DELETE FROM tags WHERE category = 'crop'")
print(f'Deleted {cur.rowcount} crop tags')
conn.commit()

# Step 2: Build app_id -> product_id mappings (handle multiple products per reg number)
app_to_pids = {}  # (product_type, app_id) -> set of product_ids
# For pesticides - handle multiple nomer_reg (comma-separated)
join_sql = """(
    p.nomer_reg = pp.nomer_reg 
    OR p.nomer_reg LIKE pp.nomer_reg || ',%'
    OR p.nomer_reg LIKE '%,' || pp.nomer_reg || ',%'
    OR p.nomer_reg LIKE '%,' || pp.nomer_reg
)"""
cur.execute(f'SELECT pp.id, p.id FROM pestitsidy_primeneniya pp JOIN pestitsidy p ON {join_sql}')
for row in cur.fetchall():
    app_id = row[0]
    pid = row[1]
    key = ('pesticide', app_id)
    if key not in app_to_pids:
        app_to_pids[key] = set()
    app_to_pids[key].add(pid)
# For agrochemicals
cur.execute('SELECT ap.id, a.id FROM agrokhimikaty_primeneniya ap JOIN agrokhimikaty a ON a.rn = ap.rn')
for app_id, pid in cur.fetchall():
    key = ('agrochemical', app_id)
    if key not in app_to_pids:
        app_to_pids[key] = set()
    app_to_pids[key].add(pid)
print(f'Built {len(app_to_pids)} app->pids mappings')

# Step 3: Extract crops from all applications
crop_products = set()  # (crop_name, product_type, product_id)

for table, ptype, id_col in [
    ('pestitsidy_primeneniya', 'pesticide', 'nomer_reg'),
    ('agrokhimikaty_primeneniya', 'agrochemical', 'rn')
]:
    cur.execute(f'SELECT id, kultura FROM {table} WHERE kultura IS NOT NULL AND kultura != ""')
    rows = cur.fetchall()
    print(f'Processing {len(rows)} rows from {table}...')
    
    for app_id, kultura in rows:
        crops = extract_crops(kultura)
        if not crops:
            continue
        pids = app_to_pids.get((ptype, app_id), set())
        for pid in pids:
            for crop in crops:
                crop_products.add((crop, ptype, pid))

unique_crops = sorted(set(k[0] for k in crop_products))
print(f'\nFound {len(unique_crops)} unique crop names, {len(crop_products)} total crop-product links')
print(f'Sample crops: {unique_crops[:30]}')

# Step 4: Insert tags
crop_tag_ids = {}
for crop_name in unique_crops:
    cur.execute("INSERT INTO tags (name, category) VALUES (?, 'crop')", (crop_name,))
    crop_tag_ids[crop_name] = cur.lastrowid
print(f'Inserted {len(crop_tag_ids)} tags')

# Step 5: Insert product_tags links
links = [(pid, ptype, crop_tag_ids[crop_name]) for (crop_name, ptype, pid) in crop_products]
cur.executemany(
    'INSERT OR IGNORE INTO product_tags (product_id, product_type, tag_id) VALUES (?, ?, ?)',
    links
)
print(f'Inserted {cur.rowcount} product_tags links')

conn.commit()
conn.close()
print('\nDone!')
