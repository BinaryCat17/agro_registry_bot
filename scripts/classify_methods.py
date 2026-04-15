import sqlite3
import json
import re

import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'data', 'reestr.db')

# Connect to DB
db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row
c = db.cursor()

# Ensure all method tags exist
METHOD_TAGS = [
    'вегетационное опрыскивание',
    'протравливание семян',
    'предпосевная обработка',
    'обработка почвы',
    'опрыскивание посадок',
    'фумигация',
    'обработка склада'
]

for tag_name in METHOD_TAGS:
    c.execute('INSERT OR IGNORE INTO tags (name, category, description) VALUES (?, ?, ?)',
              (tag_name, 'method', ''))
db.commit()

# Load all tags into dict
c.execute('SELECT id, name, category FROM tags')
TAGS = {}
for row in c.fetchall():
    TAGS.setdefault(row['category'], {})[row['name']] = row['id']

def get_tag_id(category, name):
    return TAGS.get(category, {}).get(name)

# Delete existing method tags for reclassification
c.execute("DELETE FROM product_tags WHERE tag_id IN (SELECT id FROM tags WHERE category='method')")
print(f'Cleared {c.rowcount} existing method tags from product_tags')

# Get all pesticides with their existing classes
print('Loading pesticide classes...')
c.execute('''
    SELECT p.id, p.nomer_reg, p.naimenovanie, p.deystvuyushchee_veshchestvo, 
           p.preparativnaya_forma, GROUP_CONCAT(DISTINCT t.name) as classes
    FROM pestitsidy p
    LEFT JOIN product_tags pt ON pt.product_id = p.id AND pt.product_type = 'pesticide'
    LEFT JOIN tags t ON t.id = pt.tag_id AND t.category = 'class'
    GROUP BY p.id
''')
pesticides = c.fetchall()

# Get application data for pesticides
print('Loading pesticide applications...')
c.execute('SELECT nomer_reg, sposob, kultura FROM pestitsidy_primeneniya')
all_apps = {}
for row in c.fetchall():
    all_apps.setdefault(row['nomer_reg'], []).append(dict(row))

# Method classification logic
def get_method_for_pesticide(product):
    """Determine method based on class, name, and formulation"""
    name_lower = product['naimenovanie'].lower() if product['naimenovanie'] else ''
    forma = product['preparativnaya_forma'].lower() if product['preparativnaya_forma'] else ''
    classes = product['classes'].split(',') if product['classes'] else []
    dv = product['deystvuyushchee_veshchestvo'].lower() if product['deystvuyushchee_veshchestvo'] else ''
    
    apps = all_apps.get(product['nomer_reg'], [])
    methods_text = ' '.join([a['sposob'].lower() for a in apps if a.get('sposob')])
    
    # Priority 1: Explicit method text match
    if 'протравливание семян' in methods_text or 'обработка семян' in methods_text:
        return 'протравливание семян'
    if 'фумигация' in methods_text:
        return 'фумигация'
    if 'фумигация' in name_lower or 'фумиг' in name_lower:
        return 'фумигация'
    if 'внесение в норы' in methods_text or 'внесение брикетов' in methods_text:
        return 'обработка почвы'
    if 'внесение в почву' in methods_text or 'обработка почвы' in methods_text:
        return 'обработка почвы'
    if 'обработка склад' in methods_text or 'дезинсекция' in methods_text or 'дезинфекция' in methods_text:
        return 'обработка склада'
    if 'опрыскивание посадок' in methods_text:
        return 'опрыскивание посадок'
    if 'предпосевная' in methods_text:
        return 'предпосевная обработка'
    
    # Priority 2: By class and formulation
    class_set = set(classes)
    
    if 'фумигант' in class_set or 'алюминия фосфид' in dv or 'магния фосфид' in dv:
        return 'фумигация'
    
    if 'протравитель' in class_set:
        return 'протравливание семян'
    
    if 'родентицид' in class_set or 'крыса' in methods_text or 'мышь' in methods_text:
        return 'обработка почвы'
    
    if 'моллюскоцид' in class_set:
        return 'обработка почвы'
    
    # For most pesticides: check if it's for soil/seed vs foliar
    if any(x in name_lower for x in ['протравитель', 'протрав', 'обработка семян']):
        return 'протравливание семян'
    
    if any(x in name_lower for x in ['грунт', 'почвенный', 'для почвы']):
        return 'обработка почвы'
    
    # Check application targets
    if apps:
        crops_text = ' '.join([a['kultura'].lower() for a in apps if a.get('kultura')])
        # If only storage crops (картофель, овощи хранения, плоды, зерно) - might be storage
        storage_keywords = ['зерно', 'семенной', 'картофель продов', 'плод', 'хранен']
        if any(k in crops_text for k in storage_keywords) and 'вегетац' not in crops_text:
            if 'фунгицид' in class_set or 'инсектицид' in class_set:
                return 'обработка склада'
    
    # Default for most pesticides: вегетационное опрыскивание
    if class_set.intersection({'гербицид', 'фунгицид', 'инсектицид', 'акарицид', 'биопрепарат', 'десикант', 'регулятор роста', 'антидот', 'нематоцид'}):
        return 'вегетационное опрыскивание'
    
    # Fallback
    return 'вегетационное опрыскивание'

# Classify pesticides
print(f'Classifying {len(pesticides)} pesticides...')
inserts = []
method_counts = {}

for p in pesticides:
    method = get_method_for_pesticide(p)
    method_id = get_tag_id('method', method)
    if method_id:
        inserts.append((p['id'], 'pesticide', method_id))
        method_counts[method] = method_counts.get(method, 0) + 1
    else:
        print(f'Warning: method tag not found: {method}')

if inserts:
    c.executemany('INSERT INTO product_tags (product_id, product_type, tag_id) VALUES (?, ?, ?)', inserts)
    db.commit()

print(f'Pesticides classified with method: {len(inserts)}')
print('Method distribution:')
for m, cnt in sorted(method_counts.items(), key=lambda x: -x[1]):
    print(f'  {cnt:4d}: {m}')

# --- Agrochemicals ---
print('\nLoading agrochemical classes...')
c.execute('''
    SELECT a.id, a.rn, a.preparat, GROUP_CONCAT(DISTINCT t.name) as classes
    FROM agrokhimikaty a
    LEFT JOIN product_tags pt ON pt.product_id = a.id AND pt.product_type = 'agrochemical'
    LEFT JOIN tags t ON t.id = pt.tag_id AND t.category = 'class'
    GROUP BY a.id
''')
agrochemicals = c.fetchall()

def get_method_for_agrochemical(product):
    """Determine method for agrochemical based on class and name"""
    name_lower = product['preparat'].lower() if product['preparat'] else ''
    classes = product['classes'].split(',') if product['classes'] else []
    class_set = set(classes)
    
    # For fungicides/insecticides: same as pesticides
    if 'фунгицид' in class_set or 'инсектицид' in class_set:
        return 'вегетационное опрыскивание'
    
    if 'биопрепарат' in class_set:
        return 'предпосевная обработка'  # Most biopreparations are for seed/soil
    
    # For fertilizers (most agrochemicals)
    if 'удобрение' in class_set or 'мелиорант' in class_set or 'грунт' in class_set:
        # Check if it's foliar feed
        if any(kw in name_lower for kw in ['листовая', 'внекорневая', 'опрыскивание', 'фолиар', 'подкормка']):
            return 'вегетационное опрыскивание'
        # Check if it's soil amendment
        if any(kw in name_lower for kw in ['грунт', 'почва', 'внесение', 'мелиорант', 'известь']):
            return 'обработка почвы'
        # Default for fertilizers
        return 'предпосевная обработка'
    
    return 'предпосевная обработка'

print(f'Classifying {len(agrochemicals)} agrochemicals...')
agro_inserts = []
agro_method_counts = {}

for a in agrochemicals:
    method = get_method_for_agrochemical(a)
    method_id = get_tag_id('method', method)
    if method_id:
        agro_inserts.append((a['id'], 'agrochemical', method_id))
        agro_method_counts[method] = agro_method_counts.get(method, 0) + 1

if agro_inserts:
    c.executemany('INSERT INTO product_tags (product_id, product_type, tag_id) VALUES (?, ?, ?)', agro_inserts)
    db.commit()

print(f'Agrochemicals classified with method: {len(agro_inserts)}')
print('Method distribution:')
for m, cnt in sorted(agro_method_counts.items(), key=lambda x: -x[1]):
    print(f'  {cnt:4d}: {m}')

# Verify coverage
print('\n=== Verification ===')
for ptype, table in [('pesticide', 'pestitsidy'), ('agrochemical', 'agrokhimikaty')]:
    c.execute(f'''
        SELECT COUNT(*) FROM {table} t
        WHERE NOT EXISTS (
            SELECT 1 FROM product_tags pt
            JOIN tags tg ON tg.id = pt.tag_id
            WHERE pt.product_id = t.id AND pt.product_type = ? AND tg.category = 'method'
        )
    ''', (ptype,))
    without_method = c.fetchone()[0]
    total = c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    print(f'{ptype}: {total - without_method}/{total} with method tag')

db.close()
print('\nDone!')
