#!/usr/bin/env python3
"""
Crop hierarchy classification script.
Adds category tags (crop_group) based on individual crop tags.
"""

import sqlite3
import sys
sys.path.insert(0, '/root/.openclaw/workspace/agro_registry_bot')

# Hierarchy definition: category -> list of crops belonging to it
CROP_HIERARCHY = {
    'зерновые': [
        'пшеница', 'пшеница яровая', 'пшеница озимая',
        'ячмень', 'ячмень яровой', 'ячмень озимый',
        'рожь', 'рожь озимая', 'рожь яровая',
        'овес', 'овес яровой', 'овес озимый',
        'гречиха', 'просо', 'просо кормовое', 'сорго', 'рис',
        'тритикале', 'полба', 'кукуруза', 'лен-долгунец'
    ],
    'масличные': [
        'подсолнечник', 'рапс', 'рапс яровой', 'рапс озимый',
        'соя', 'лен масличный', 'горчица', 'сафлор', 'клещевина',
        'расторопша пятнистая'
    ],
    'бобовые': [
        'горох', 'горох овощной', 'нут', 'фасоль', 'чечевица',
        'чечевица обыкновенная', 'люпин', 'люпин однолетний',
        'люпин желтый', 'люпин желтый кормовой', 'вика', 'чина',
        'кормовые бобы', 'зеленый горошек', 'горошек овощной',
        'соя'  # соя относится и к масличным, и к бобовым
    ],
    'клубнеплоды': [
        'картофель', 'топинамбур'
    ],
    'овощные': [
        'томат', 'томат рассадный', 'томаты рассадные',
        'огурец', 'перец', 'перец сладкий', 'баклажан',
        'капуста', 'капуста белокочанная', 'капуста пекинская',
        'капуста кочанная', 'капуста белокочанная рассадная',
        'капуста рассадная', 'брокколи', 'кольраби',
        'морковь', 'свекла столовая', 'редис', 'редька',
        'репа', 'турнепс', 'брюква', 'дайкон',
        'лук', 'лук репчатый', 'лук-репка', 'лук репка',
        'лук всех генераций', 'лук-чернушка', 'лук чернушка',
        'лук-севок', 'лук севок', 'чеснок', 'чеснок яровой',
        'тыква', 'кабачок', 'патиссон', 'шпинат',
        'салат', 'салат-латук листовой', 'салат листовой',
        'сельдерей', 'сельдерей корневой',
        'петрушка', 'петрушка корневая', 'укроп', 'хрен',
        'спаржа', 'бобовые овощные',
        # Добавленные:
        'арбуз', 'дыня', 'кориандр', 'мята перечная',
        'пастернак', 'капуста: белокочанная', 'овощн'
    ],
    'плодовые': [
        'яблоня', 'груша', 'айва',
        'вишня', 'вишня войлочная', 'черешня',
        'слива', 'алыча', 'абрикос', 'персик', 'нектарин',
        'виноград', 'киви', 'инжир', 'гранат', 'финик',
        'банан', 'кокос',
        # Добавленные:
        'хурма', 'кофе', 'минеола'
    ],
    'ягодные': [
        'земляника', 'земляника садовая', 'клубника',
        'малина', 'ежевика', 'малинно-ежевичный гибрид',
        'смородина', 'крыжовник', 'облепиха',
        'голубика', 'черника', 'брусника', 'клюква',
        'рябина', 'рябина черноплодная', 'арония',
        'жимолость', 'ирга',
        # Добавленные:
        'ежа сборная', 'терн', 'шиповник'
    ],
    'цитрусовые': [
        'мандарин', 'лимон', 'апельсин', 'грейпфрут', 'лайм', 'помело'
    ],
    'орехи': [
        'фундук', 'миндаль', 'миндаль трехлопастный', 'грецкий орех', 'фисташка', 'кешью'
    ],
    'технические': [
        'свекла сахарная', 'хлопчатник', 'конопля', 'кенаф',
        'табак', 'лен технический',
        # Добавленные:
        'лен', 'хмель'
    ],
    'кормовые': [
        'люцерна', 'люцерна старовозрастная',
        'клевер', 'клевер ползучий', 'клевер полевой',
        'тимофеевка луговая', 'овсяница луговая',
        'кострец безостый', 'костер безостый',
        'эспарцет', 'райграс однолетний',
        'трава суданская', 'суданская трава',
        'свекла кормовая', 'кормовые бобы',
        'просо кормовое', 'кукуруза на силос',
        # Добавленные:
        'газон', 'донник', 'козлятник', 'фестулолиум'
    ],
    'декоративные': [
        'роза', 'гладиолус', 'тюльпан', 'гвоздика',
        'хризантема', 'хризантема корейская',
        'герань', 'пеларгония', 'бегония', 'фиалка',
        'орхидея', 'фуксия', 'альоказия', 'драцена',
        'шефлера', 'монстера', 'юкка', 'фикус', 'фикус бенджамина',
        'кактус', 'суккулент', 'пальма', 'саговые пальмы', 'са-говник',
        'лаванда', 'гортензия', 'гортензия крупнолистная',
        'жасмин', 'сирень', 'рододендрон', 'азалия',
        'камелия', 'гардения', 'антуриум',
        'бальзамин', 'бальзамин новогвинейский',
        'гиацинт', 'нарцисс', 'крокус', 'георгин',
        'фрезия', 'гербера', 'гелениум',
        'алое', 'аланга', 'амариллис', 'антуриум',
        'аралия', 'арония', 'аспарагус', 'аспидистра',
        'аукуба', 'барбарис', 'барбарис тунберга', 'барбарис обыкновенный',
        'бегония', 'бересклет', 'бирючина',
        'вереск', 'дейция шершавая', 'душица обыкновенная',
        'ипомея', 'калла', 'кампанула', 'каланхоэ',
        'клематис', 'кливия', 'молочай', 'мирт',
        'плющ', 'самшит', 'сенполия', 'сенполия фиалковая',
        'традесканция', 'фатсия', 'фитония', 'форзиция',
        'хамеропс', 'ховея', 'цикламен', 'цинерария',
        'шалфей мускатный', 'эхинацея пурпурная',
        'пустырник сердечный', 'змееголовник молдавский',
        'мелисса лекарственная', 'валериана лекарственная',
        'наперстянка шерстистая', 'ноготки лекарственные',
        # Добавленные:
        'агава', 'алоказия', 'алоэ', 'араукария',
        'глоксиния', 'диффенбахия', 'женьшень',
        'кипарисовик горохоплодный', 'кокос ведделя', 'кротон',
        'лен-кудряш', 'можжевельник', 'можжевельник сибирский',
        'паслен дольчатый', 'пиретрум девичий', 'платицериум',
        'рапис', 'рипсалис', 'росянка', 'сакура', 'сансевьера',
        'саркокаулон вандериета', 'сингониум', 'тапиока',
        'туя западная', 'циперус', 'чубушник',
        'газон'  # газон тоже декоративный
    ],
    'лесные': [
        'сосна', 'сосна обыкновенная', 'сосна крымская',
        'ель', 'ель обыкновенная', 'ель колючая', 'ель голубая', 'ель европейская',
        'пихта', 'пихта кавказская',
        'кедр', 'кедр сибирский', 'кедр корейский',
        'дуб', 'береза', 'липа', 'лиственница', 'лиственница сибирская',
        'осина', 'тополь', 'клен', 'ясень', 'ольха',
        # Добавленные:
        'лиственных пород', 'лиственных пород деревьев',
        'кипарисовик горохоплодный', 'можжевельник', 'можжевельник сибирский',
        'туя западная'
    ],
    'сорняки_вредные_объекты': [
        'дикая растительность',
        'очаги распространения горчака ползучего',
        'сурепка', 'сурепица'
    ],
    'нежилые_помещения': [
        'нежилыми помещениями'
    ],
    'прочие': [
        # Всё что не подошло в другие категории
        'клоновый подвой', 'копра', 'кото',
        'мака перуанская', 'маклея сердцевидная',
        'их дос', 'их досмо', 'жим',
        'посадку картофеля', 'посадочный материал',
        'свекла', 'очиток'
    ]
}

# Special multi-category crops (belong to multiple groups)
MULTI_CATEGORY = {
    'соя': ['масличные', 'бобовые'],
    'кукуруза': ['зерновые', 'кормовые'],
}


def main():
    db = sqlite3.connect('data/reestr.db')
    db.row_factory = sqlite3.Row
    c = db.cursor()
    
    # Get or create tag function
    def get_tag_id(cat, name):
        c.execute('SELECT id FROM tags WHERE category = ? AND name = ?', (cat, name))
        row = c.fetchone()
        return row[0] if row else None
    
    def add_tag(cat, name):
        c.execute('INSERT INTO tags (category, name) VALUES (?, ?)', (cat, name))
        db.commit()
        return c.lastrowid
    
    # First, delete old crop_group tags
    c.execute("SELECT id FROM tags WHERE category = 'crop_group'")
    old_ids = [r[0] for r in c.fetchall()]
    if old_ids:
        placeholders = ','.join(['?' for _ in old_ids])
        c.execute(f"DELETE FROM product_tags WHERE tag_id IN ({placeholders})", old_ids)
        c.execute(f"DELETE FROM tags WHERE id IN ({placeholders})", old_ids)
        db.commit()
        print(f"Cleaned {len(old_ids)} old crop_group tags")
    
    # Get all crop tags
    c.execute("SELECT id, name FROM tags WHERE category = 'crop'")
    crop_tags = {row['name']: row['id'] for row in c.fetchall()}
    
    print(f"Found {len(crop_tags)} crop tags")
    
    # Build reverse mapping: crop -> groups
    crop_to_groups = {}
    for group, crops in CROP_HIERARCHY.items():
        for crop in crops:
            if crop not in crop_to_groups:
                crop_to_groups[crop] = []
            crop_to_groups[crop].append(group)
    
    # Add multi-category mappings
    for crop, groups in MULTI_CATEGORY.items():
        if crop not in crop_to_groups:
            crop_to_groups[crop] = []
        for g in groups:
            if g not in crop_to_groups[crop]:
                crop_to_groups[crop].append(g)
    
    # Get all product-crop relationships
    c.execute('''
        SELECT pt.product_id, pt.product_type, t.name as crop_name
        FROM product_tags pt
        JOIN tags t ON t.id = pt.tag_id
        WHERE t.category = 'crop'
    ''')
    
    inserts = []
    unclassified = set()
    classified_count = 0
    
    for row in c.fetchall():
        product_id = row['product_id']
        product_type = row['product_type']
        crop_name = row['crop_name']
        
        groups = crop_to_groups.get(crop_name)
        if groups:
            for group in groups:
                tid = get_tag_id('crop_group', group)
                if tid is None:
                    tid = add_tag('crop_group', group)
                inserts.append((product_id, product_type, tid))
            classified_count += 1
        else:
            unclassified.add(crop_name)
    
    # Add "все культуры" to all products with any crop
    c.execute('''
        SELECT DISTINCT pt.product_id, pt.product_type
        FROM product_tags pt
        JOIN tags t ON t.id = pt.tag_id
        WHERE t.category = 'crop'
    ''')
    
    all_crops_id = get_tag_id('crop_group', 'все культуры')
    if all_crops_id is None:
        all_crops_id = add_tag('crop_group', 'все культуры')
    
    for row in c.fetchall():
        inserts.append((row['product_id'], row['product_type'], all_crops_id))
    
    # Add "прочие" for unclassified crops
    if unclassified:
        other_id = get_tag_id('crop_group', 'прочие')
        if other_id is None:
            other_id = add_tag('crop_group', 'прочие')
        
        c.execute('''
            SELECT DISTINCT pt.product_id, pt.product_type
            FROM product_tags pt
            JOIN tags t ON t.id = pt.tag_id
            WHERE t.category = 'crop' AND t.name IN ({})
        '''.format(','.join(['?' for _ in unclassified])), list(unclassified))
        
        for row in c.fetchall():
            inserts.append((row['product_id'], row['product_type'], other_id))
    
    # Bulk insert
    c.executemany('''
        INSERT OR IGNORE INTO product_tags (product_id, product_type, tag_id)
        VALUES (?, ?, ?)
    ''', inserts)
    db.commit()
    
    print(f"\nClassification complete:")
    print(f"  - Crops classified: {classified_count}")
    print(f"  - Unclassified crops: {len(unclassified)}")
    if unclassified:
        print(f"  - Unclassified list: {sorted(unclassified)}")
    print(f"  - Total group assignments: {len(inserts)}")
    
    # Show group distribution
    print("\nGroup distribution:")
    c.execute('''
        SELECT t.name, COUNT(DISTINCT pt.product_id) as cnt
        FROM product_tags pt
        JOIN tags t ON t.id = pt.tag_id
        WHERE t.category = 'crop_group'
        GROUP BY t.name
        ORDER BY cnt DESC
    ''')
    for row in c.fetchall():
        print(f"  {row['name']}: {row['cnt']}")
    
    db.close()


if __name__ == '__main__':
    main()
