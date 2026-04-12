#!/usr/bin/env python3
"""CLI для быстрых SQL-запросов к реестру Минсельхоза."""
import sys
import json
from src.database import RegistryDatabase

def main():
    db = RegistryDatabase()
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Использование: python query.py '<SQL запрос>'")
        print("Примеры:")
        print('  python query.py "SELECT * FROM pestitsidy LIMIT 3"')
        print('  python query.py "SELECT * FROM agrokhimikaty WHERE preparat REGEXP \'карбамид\' LIMIT 5"')
        print('  python query.py "PRAGMA table_info(pestitsidy)"')
        sys.exit(0)

    query = sys.argv[1]
    result = db.execute(query)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

if __name__ == "__main__":
    main()
