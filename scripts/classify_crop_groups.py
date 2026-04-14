#!/usr/bin/env python3
"""
Crop hierarchy classification script.
Adds category tags (crop_group) based on individual crop tags.
"""

import sqlite3
import sys
sys.path.insert(0, '/root/.openclaw/workspace/agro_registry_bot')

# Import hierarchy from centralized module
from src.crop_hierarchy import CROP_HIERARCHY, get_crop_groups

DB_PATH = '/root/.openclaw/workspace/agro_registry_bot/data/reestr.db'


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get or create tag function
    def get_tag_id(cat, name):
        c.execute('SELECT id FROM tags WHERE category = ? AND name = ?', (cat, name))
        row = c.fetchone()
        return row[0] if row else None
    
    def add_tag(cat, name):
        c.execute('INSERT INTO tags (category, name) VALUES (?, ?)', (cat, name))
        conn.commit()
        return c.lastrowid
    
    # Ensure all crop_group tags exist
    group_to_id = {}
    for group_name in CROP_HIERARCHY.keys():
        tid = get_tag_id('crop_group', group_name)
        if not tid:
            tid = add_tag('crop_group', group_name)
            print(f"Created tag: crop_group = {group_name} (id={tid})")
        group_to_id[group_name] = tid
    
    # Also ensure 'все культуры' tag exists
    tid = get_tag_id('crop_group', 'все культуры')
    if not tid:
        tid = add_tag('crop_group', 'все культуры')
        print(f"Created tag: crop_group = все культуры (id={tid})")
    group_to_id['все культуры'] = tid
    
    # Get all crop tags
    c.execute("SELECT id, name FROM tags WHERE category = 'crop'")
    crop_tags = {row['name']: row['id'] for row in c.fetchall()}
    
    # Build reverse mapping: crop name -> list of group IDs
    crop_to_groups = {}
    for group_name, crops in CROP_HIERARCHY.items():
        group_id = group_to_id[group_name]
        for crop_name in crops:
            if crop_name not in crop_to_groups:
                crop_to_groups[crop_name] = []
            crop_to_groups[crop_name].append(group_id)
    
    # Get all products with crop tags
    c.execute("""
        SELECT DISTINCT pt.product_id, pt.product_type, t.name as crop_name, t.id as crop_id
        FROM product_tags pt
        JOIN tags t ON t.id = pt.tag_id
        WHERE t.category = 'crop'
    """)
    
    assignments = {}  # (product_id, product_type, group_id) -> count
    unclassified = set()
    
    for row in c.fetchall():
        product_id = row['product_id']
        product_type = row['product_type']
        crop_name = row['crop_name']
        
        # Add to 'все культуры' group
        all_crops_id = group_to_id['все культуры']
        key = (product_id, product_type, all_crops_id)
        assignments[key] = assignments.get(key, 0) + 1
        
        # Add to specific groups
        if crop_name in crop_to_groups:
            for group_id in crop_to_groups[crop_name]:
                key = (product_id, product_type, group_id)
                assignments[key] = assignments.get(key, 0) + 1
        else:
            unclassified.add(crop_name)
    
    # Clear existing crop_group assignments
    c.execute("DELETE FROM product_tags WHERE tag_id IN (SELECT id FROM tags WHERE category = 'crop_group')")
    conn.commit()
    
    # Insert new assignments
    total = 0
    for (product_id, product_type, group_id), count in assignments.items():
        try:
            c.execute(
                "INSERT INTO product_tags (product_id, product_type, tag_id) VALUES (?, ?, ?)",
                (product_id, product_type, group_id)
            )
            total += 1
        except sqlite3.IntegrityError:
            pass  # Skip duplicates
    
    conn.commit()
    
    print(f"\n=== Summary ===")
    print(f"Total crop_group assignments: {total}")
    print(f"Unclassified crops ({len(unclassified)}):")
    for crop in sorted(unclassified):
        print(f"  - {crop}")
    
    # Print group statistics
    print(f"\n=== Group Statistics ===")
    for group_name in sorted(CROP_HIERARCHY.keys()):
        group_id = group_to_id[group_name]
        c.execute("""
            SELECT COUNT(DISTINCT product_id) 
            FROM product_tags 
            WHERE tag_id = ? AND product_type = 'pesticide'
        """, (group_id,))
        count = c.fetchone()[0]
        print(f"  {group_name}: {count} products")
    
    conn.close()


if __name__ == '__main__':
    main()
