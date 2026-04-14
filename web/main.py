import os
import sys
import json
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(_ENV_PATH):
    load_dotenv(_ENV_PATH)

from fastapi import FastAPI, Query, Request, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
from src.database import RegistryDatabase
from src.auth_db import init_auth_tables, get_user as get_whitelist_user, add_user as add_whitelist_user, remove_user as remove_whitelist_user, list_users as list_whitelist_users
from src import yandex_oauth
from src.agent import RegistryAgent
from src.crop_hierarchy import CROP_HIERARCHY

def yo_pattern(p: str):
    """Заменяет е/ё на регексный класс [её] для взаимозаменяемого поиска."""
    return ''.join('[её]' if c in 'её' else c for c in p)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "reestr.db")
db = RegistryDatabase(db_path=DB_PATH)

# Direct sqlite connection for raw queries
import sqlite3
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

app = FastAPI(title="АгроРеестр AI", description="Поиск по государственному реестру пестицидов и агрохимикатов")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "change-me-secret"), max_age=3600*24*7)

static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.on_event("startup")
async def startup_event():
    init_auth_tables()
    if not get_whitelist_user(yandex_oauth.ADMIN_EMAIL):
        add_whitelist_user(yandex_oauth.ADMIN_EMAIL, is_admin=True, granted_by="system")

@app.get("/")
async def root():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/admin")
async def admin_page(request: Request):
    user = request.session.get("user")
    if not user:
        return FileResponse(os.path.join(static_dir, "index.html"))
    wl = get_whitelist_user(user.get("email", ""))
    if not (wl and wl.get("is_admin")):
        return FileResponse(os.path.join(static_dir, "index.html"))
    return FileResponse(os.path.join(static_dir, "admin.html"))

def _tag_filter_sql(table_alias: str, product_type: str, tag_ids: list):
    if not tag_ids:
        return "", []
    placeholders = ",".join(["?"] * len(tag_ids))
    return f"""AND EXISTS (
        SELECT 1 FROM product_tags pt2
        WHERE pt2.product_id = {table_alias}.id
          AND pt2.product_type = '{product_type}'
          AND pt2.tag_id IN ({placeholders})
    )""", tag_ids

def _crop_group_filter_sql(table_alias: str, product_type: str, crop_group_id: int):
    if not crop_group_id:
        return "", []
    
    # Get crop group name from DB using direct sqlite connection
    conn = get_db()
    try:
        row = conn.execute("SELECT name FROM tags WHERE id = ? AND category = 'crop_group'", (crop_group_id,)).fetchone()
        if not row:
            return "", []
        
        group_name = row['name']
        allowed_crops = CROP_HIERARCHY.get(group_name, [])
        
        if not allowed_crops:
            return "", []
        
        # Build IN clause with escaped crop names
        placeholders = ','.join(['?' for _ in allowed_crops])
        
        return f"""AND EXISTS (
        SELECT 1 FROM product_tags pt_c
        JOIN tags t_c ON t_c.id = pt_c.tag_id
        WHERE pt_c.product_id = {table_alias}.id
          AND pt_c.product_type = '{product_type}'
          AND t_c.category = 'crop'
          AND t_c.name IN ({placeholders})
    )""", list(allowed_crops)
    finally:
        conn.close()

@app.get("/api/tags")
async def api_tags(type: str = Query("pesticides", regex="^(pesticides|agrochemicals)$")):
    product_type = "pesticide" if type == "pesticides" else "agrochemical"
    rows = db.execute("""
        SELECT t.category, t.id, t.name FROM tags t
        WHERE EXISTS (
            SELECT 1 FROM product_tags pt
            WHERE pt.tag_id = t.id AND pt.product_type = ?
        )
        ORDER BY t.category, t.name
    """, (product_type,))
    result = {}
    for r in rows:
        cat = r['category']
        if cat not in result:
            result[cat] = []
        result[cat].append({"id": r['id'], "name": r['name']})
    
    # Add hierarchical crop groups structure
    if 'crop' in result or 'crop_group' in result:
        result['crop_hierarchy'] = []
        
        # Get all crop groups from tags
        group_rows = db.execute("""
            SELECT t.id, t.name FROM tags t
            WHERE t.category = 'crop_group' AND t.name != 'все культуры'
            ORDER BY t.name
        """)
        
        # Get crops from DB once
        crop_rows = db.execute("""
            SELECT DISTINCT t.id, t.name FROM tags t
            JOIN product_tags pt ON pt.tag_id = t.id AND pt.product_type = ?
            WHERE t.category = 'crop'
            ORDER BY t.name
        """, (product_type,))
        db_crops = list(crop_rows)
        
        # Add all groups from tags with their crops from CROP_HIERARCHY
        for group_row in group_rows:
            group_name = group_row['name']
            allowed_crops = set(CROP_HIERARCHY.get(group_name, []))
            crops = [{"id": r['id'], "name": r['name']} for r in db_crops if r['name'] in allowed_crops]
            result['crop_hierarchy'].append({
                "group_id": group_row['id'],
                "group_name": group_row['name'],
                "crops": crops
            })
    
    return result

@app.get("/api/search")
async def api_search(
    type: str = Query("pesticides", regex="^(pesticides|agrochemicals)$"),
    q: str = Query(""),
    field: str = Query("all", regex="^(all|name|crop|pest|dv|reg_number)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    active_only: bool = Query(True),
    tags: str = Query(""),
    crop_group_id: int = Query(0)
):
    offset = (page - 1) * limit
    tag_ids = [int(t) for t in tags.split(",") if t.strip().isdigit()] if tags else []
    
    # Build crop group filter
    crop_group_sql, crop_group_params = "", []
    if crop_group_id > 0:
        if type == "pesticides":
            crop_group_sql, crop_group_params = _crop_group_filter_sql("p", "pesticide", crop_group_id)
        else:
            crop_group_sql, crop_group_params = _crop_group_filter_sql("a", "agrochemical", crop_group_id)

    if type == "pesticides":
        tag_sql, tag_params = _tag_filter_sql("p", "pesticide", tag_ids)
        all_params = crop_group_params + tag_params
        if field == "name":
            items = db.find_pesticide_by_name(q, active_only=active_only, limit=limit, offset=offset)
            where = "p.naimenovanie REGEXP ?"
            if active_only:
                where += " AND p.status = 'Действует'"
            where += " " + crop_group_sql + " " + tag_sql
            total_res = db.execute(f"SELECT COUNT(*) as c FROM pestitsidy p WHERE {where}", (yo_pattern(q), *all_params))
            total = total_res[0]['c']
            if tag_ids or crop_group_id:
                items = db.execute(f"SELECT p.* FROM pestitsidy p WHERE {where} ORDER BY p.naimenovanie LIMIT {limit} OFFSET {offset}", (yo_pattern(q), *all_params))
        elif field == "dv":
            items = db.find_pesticide_by_dv(q, active_only=active_only, limit=limit, offset=offset)
            where = "exists (SELECT 1 FROM json_each(p.deystvuyushchee_veshchestvo) dv WHERE dv.value->>'veshchestvo' REGEXP ?)"
            if active_only:
                where += " AND p.status = 'Действует'"
            where += " " + tag_sql
            total_res = db.execute(f"SELECT COUNT(*) as c FROM pestitsidy p WHERE {where}", (yo_pattern(q), *tag_params))
            total = total_res[0]['c']
            if tag_ids:
                items = db.execute(f"SELECT p.* FROM pestitsidy p WHERE {where} ORDER BY p.naimenovanie LIMIT {limit} OFFSET {offset}", (yo_pattern(q), *tag_params))
        elif field == "crop":
            items = db.search_pesticides_by_crop(q, active_only=active_only, limit=limit, offset=offset)
            where = "pp.kultura REGEXP ?"
            if active_only:
                where += " AND p.status = 'Действует'"
            where += " " + tag_sql
            total_res = db.execute(f"SELECT COUNT(DISTINCT p.id) as c FROM pestitsidy p JOIN pestitsidy_primeneniya pp ON p.nomer_reg = pp.nomer_reg WHERE {where}", (yo_pattern(q), *tag_params))
            total = total_res[0]['c']
            if tag_ids:
                items = db.execute(f"SELECT DISTINCT p.* FROM pestitsidy p JOIN pestitsidy_primeneniya pp ON p.nomer_reg = pp.nomer_reg WHERE {where} ORDER BY p.naimenovanie LIMIT {limit} OFFSET {offset}", (yo_pattern(q), *tag_params))
        elif field == "pest":
            items = db.search_pesticides_by_pest(q, active_only=active_only, limit=limit, offset=offset)
            where = "pp.vrednyy_obekt REGEXP ?"
            if active_only:
                where += " AND p.status = 'Действует'"
            where += " " + tag_sql
            total_res = db.execute(f"SELECT COUNT(DISTINCT p.id) as c FROM pestitsidy p JOIN pestitsidy_primeneniya pp ON p.nomer_reg = pp.nomer_reg WHERE {where}", (yo_pattern(q), *tag_params))
            total = total_res[0]['c']
            if tag_ids:
                items = db.execute(f"SELECT DISTINCT p.* FROM pestitsidy p JOIN pestitsidy_primeneniya pp ON p.nomer_reg = pp.nomer_reg WHERE {where} ORDER BY p.naimenovanie LIMIT {limit} OFFSET {offset}", (yo_pattern(q), *tag_params))
        elif field == "reg_number":
            where = "nomer_reg REGEXP ?"
            if active_only:
                where += " AND status = 'Действует'"
            where += " " + tag_sql.replace("p.id", "pestitsidy.id")
            items = db.execute(f"SELECT * FROM pestitsidy WHERE {where} ORDER BY naimenovanie LIMIT {limit} OFFSET {offset}", (yo_pattern(q), *tag_params))
            total_res = db.execute(f"SELECT COUNT(*) as c FROM pestitsidy WHERE {where}", (yo_pattern(q), *tag_params))
            total = total_res[0]['c']
        else:
            seen = set()
            all_items = []
            # Special case: empty query with filters - get all matching products directly
            if not q and (tag_ids or crop_group_id):
                # Get all products with the specified crop_group using CROP_HIERARCHY
                if crop_group_id:
                    import sqlite3
                    conn = sqlite3.connect(DB_PATH)
                    conn.row_factory = sqlite3.Row
                    try:
                        # Get group name and allowed crops
                        row = conn.execute("SELECT name FROM tags WHERE id = ? AND category = 'crop_group'", (crop_group_id,)).fetchone()
                        if row:
                            group_name = row['name']
                            allowed_crops = CROP_HIERARCHY.get(group_name, [])
                            if allowed_crops:
                                placeholders = ','.join(['?' for _ in allowed_crops])
                                rows = conn.execute(f"""
                                    SELECT DISTINCT p.* FROM pestitsidy p
                                    JOIN product_tags pt ON pt.product_id = p.id AND pt.product_type = 'pesticide'
                                    JOIN tags t ON t.id = pt.tag_id
                                    WHERE t.category = 'crop' AND t.name IN ({placeholders})
                                """, list(allowed_crops)).fetchall()
                                all_items = [dict(r) for r in rows]
                            else:
                                all_items = []
                        else:
                            all_items = []
                    finally:
                        conn.close()
                else:
                    # Just get all products for tag filtering
                    rows = db.execute("SELECT * FROM pestitsidy")
                    all_items = rows
            else:
                for r in db.find_pesticide_by_name(q, active_only=active_only, limit=10000):
                    if r['id'] not in seen:
                        seen.add(r['id']); all_items.append(r)
                for r in db.find_pesticide_by_dv(q, active_only=active_only, limit=10000):
                    if r['id'] not in seen:
                        seen.add(r['id']); all_items.append(r)
                for r in db.search_pesticides_by_crop(q, active_only=active_only, limit=10000):
                    if r['id'] not in seen:
                        seen.add(r['id']); all_items.append(r)
                for r in db.search_pesticides_by_pest(q, active_only=active_only, limit=10000):
                    if r['id'] not in seen:
                        seen.add(r['id']); all_items.append(r)
            if tag_ids or crop_group_id:
                ids = [r['id'] for r in all_items]
                if ids:
                    params = list(ids)
                    if tag_ids:
                        tag_placeholders = ",".join(["?"] * len(tag_ids))
                        filtered = db.execute(f"""
                            SELECT product_id FROM product_tags
                            WHERE product_type = 'pesticide' AND tag_id IN ({tag_placeholders}) AND product_id IN ({','.join(['?'] * len(ids))})
                            GROUP BY product_id HAVING COUNT(DISTINCT tag_id) >= {len(tag_ids)}
                        """, (*tag_ids, *ids))
                        allowed = {r['product_id'] for r in filtered}
                        params = [pid for pid in ids if pid in allowed]
                        if not params:
                            all_items = []
                    if crop_group_id and all_items and q:  # Only if we didn't already filter by crop_group above
                        # Filter by crop group
                        cg_filtered = db.execute(f"""
                            SELECT DISTINCT pt.product_id 
                            FROM product_tags pt
                            WHERE pt.tag_id = ? 
                            AND pt.product_type = 'pesticide'
                            AND pt.product_id IN ({','.join(['?'] * len(params))})
                        """, (crop_group_id, *params))
                        allowed_cg = {r['product_id'] for r in cg_filtered}
                        params = [pid for pid in params if pid in allowed_cg]
                    # Re-fetch items with filtered IDs
                    if params:
                        id_placeholders = ",".join(["?"] * len(params))
                        all_items = db.execute(f"SELECT * FROM pestitsidy WHERE id IN ({id_placeholders})", params)
                    else:
                        all_items = []
                else:
                    all_items = []
            total = len(all_items)
            items = all_items[offset:offset+limit]
    else:
        tag_sql, tag_params = _tag_filter_sql("a", "agrochemical", tag_ids)
        if field == "name":
            items = db.find_agrochemical_by_name(q, active_only=active_only, limit=limit, offset=offset)
            where = "preparat REGEXP ?"
            if active_only:
                where += " AND status = 'Действует'"
            where += " " + tag_sql.replace("a.id", "agrokhimikaty.id")
            total_res = db.execute(f"SELECT COUNT(*) as c FROM agrokhimikaty WHERE {where}", (yo_pattern(q), *tag_params))
            total = total_res[0]['c']
            if tag_ids:
                items = db.execute(f"SELECT * FROM agrokhimikaty WHERE {where} ORDER BY preparat LIMIT {limit} OFFSET {offset}", (yo_pattern(q), *tag_params))
        elif field == "crop":
            items = db.search_agrochemicals_by_crop(q, active_only=active_only, limit=limit, offset=offset)
            where = "ap.kultura REGEXP ?"
            if active_only:
                where += " AND a.status = 'Действует'"
            where += " " + tag_sql
            total_res = db.execute(f"SELECT COUNT(DISTINCT a.id) as c FROM agrokhimikaty a JOIN agrokhimikaty_primeneniya ap ON a.rn = ap.rn WHERE {where}", (yo_pattern(q), *tag_params))
            total = total_res[0]['c']
            if tag_ids:
                items = db.execute(f"SELECT DISTINCT a.* FROM agrokhimikaty a JOIN agrokhimikaty_primeneniya ap ON a.rn = ap.rn WHERE {where} ORDER BY a.preparat LIMIT {limit} OFFSET {offset}", (yo_pattern(q), *tag_params))
        elif field == "reg_number":
            where = "rn REGEXP ?"
            if active_only:
                where += " AND status = 'Действует'"
            where += " " + tag_sql.replace("a.id", "agrokhimikaty.id")
            items = db.execute(f"SELECT * FROM agrokhimikaty WHERE {where} ORDER BY preparat LIMIT {limit} OFFSET {offset}", (yo_pattern(q), *tag_params))
            total_res = db.execute(f"SELECT COUNT(*) as c FROM agrokhimikaty WHERE {where}", (yo_pattern(q), *tag_params))
            total = total_res[0]['c']
        else:
            seen = set()
            all_items = []
            # Special case: empty query with filters - get all matching products directly
            if not q and (tag_ids or crop_group_id):
                # Get all products with the specified crop_group using CROP_HIERARCHY
                if crop_group_id:
                    import sqlite3
                    conn = sqlite3.connect(DB_PATH)
                    conn.row_factory = sqlite3.Row
                    try:
                        # Get group name and allowed crops
                        row = conn.execute("SELECT name FROM tags WHERE id = ? AND category = 'crop_group'", (crop_group_id,)).fetchone()
                        if row:
                            group_name = row['name']
                            allowed_crops = CROP_HIERARCHY.get(group_name, [])
                            if allowed_crops:
                                placeholders = ','.join(['?' for _ in allowed_crops])
                                rows = conn.execute(f"""
                                    SELECT DISTINCT a.* FROM agrokhimikaty a
                                    JOIN product_tags pt ON pt.product_id = a.id AND pt.product_type = 'agrochemical'
                                    JOIN tags t ON t.id = pt.tag_id
                                    WHERE t.category = 'crop' AND t.name IN ({placeholders})
                                """, list(allowed_crops)).fetchall()
                                all_items = [dict(r) for r in rows]
                            else:
                                all_items = []
                        else:
                            all_items = []
                    finally:
                        conn.close()
                else:
                    # Just get all products for tag filtering
                    rows = db.execute("SELECT * FROM agrokhimikaty")
                    all_items = rows
            else:
                for r in db.find_agrochemical_by_name(q, active_only=active_only, limit=10000):
                    if r['id'] not in seen:
                        seen.add(r['id']); all_items.append(r)
                for r in db.search_agrochemicals_by_crop(q, active_only=active_only, limit=10000):
                    if r['id'] not in seen:
                        seen.add(r['id']); all_items.append(r)
            if tag_ids or crop_group_id:
                ids = [r['id'] for r in all_items]
                if ids:
                    params = list(ids)
                    if tag_ids:
                        tag_placeholders = ",".join(["?"] * len(tag_ids))
                        filtered = db.execute(f"""
                            SELECT product_id FROM product_tags
                            WHERE product_type = 'agrochemical' AND tag_id IN ({tag_placeholders}) AND product_id IN ({','.join(['?'] * len(ids))})
                            GROUP BY product_id HAVING COUNT(DISTINCT tag_id) >= {len(tag_ids)}
                        """, (*tag_ids, *ids))
                        allowed = {r['product_id'] for r in filtered}
                        params = [pid for pid in ids if pid in allowed]
                        if not params:
                            all_items = []
                    if crop_group_id and all_items and q:  # Only if we didn't already filter by crop_group above
                        # Filter by crop group
                        cg_filtered = db.execute(f"""
                            SELECT DISTINCT pt.product_id 
                            FROM product_tags pt
                            WHERE pt.tag_id = ? 
                            AND pt.product_type = 'agrochemical'
                            AND pt.product_id IN ({','.join(['?'] * len(params))})
                        """, (crop_group_id, *params))
                        allowed_cg = {r['product_id'] for r in cg_filtered}
                        params = [pid for pid in params if pid in allowed_cg]
                    # Re-fetch items with filtered IDs
                    if params:
                        id_placeholders = ",".join(["?"] * len(params))
                        all_items = db.execute(f"SELECT * FROM agrokhimikaty WHERE id IN ({id_placeholders})", params)
                    else:
                        all_items = []
                else:
                    all_items = []
            total = len(all_items)
            items = all_items[offset:offset+limit]

    return {"items": items, "total": total, "page": page, "limit": limit}

@app.get("/api/product/{type}/{id}")
async def api_product_old(type: str, id: str):
    if type == "pesticide":
        info_res = db.execute("SELECT * FROM pestitsidy WHERE nomer_reg = ? LIMIT 1", (id,))
        if info_res and isinstance(info_res, list) and len(info_res) > 0:
            info = info_res[0]
            apps = db.find_pesticide_applications(id)
            return {"info": info, "applications": apps}
    else:
        info_res = db.execute("SELECT * FROM agrokhimikaty WHERE rn = ? LIMIT 1", (id,))
        if info_res and isinstance(info_res, list) and len(info_res) > 0:
            info = info_res[0]
            apps = db.find_agrochemical_applications(id)
            return {"info": info, "applications": apps}
    return JSONResponse(status_code=404, content={"error": "Not found"})

@app.get("/api/last-update")
async def api_last_update():
    ts = db.last_update_time()
    return {"last_update": ts}

@app.get("/api/product-detail")
async def api_product_detail(type: str = Query(...), row_id: int = Query(...)):
    if type == "pesticide":
        info_res = db.execute("SELECT * FROM pestitsidy WHERE id = ?", (row_id,))
        if info_res and isinstance(info_res, list) and len(info_res) > 0:
            info = info_res[0]
            apps = db.find_pesticide_applications(info['nomer_reg'])
            tags = db.execute("""
                SELECT t.category, t.name FROM tags t
                JOIN product_tags pt ON pt.tag_id = t.id
                WHERE pt.product_id = ? AND pt.product_type = 'pesticide'
                ORDER BY t.category, t.name
            """, (row_id,))
            return {"info": info, "applications": apps, "tags": tags or []}
    else:
        info_res = db.execute("SELECT * FROM agrokhimikaty WHERE id = ?", (row_id,))
        if info_res and isinstance(info_res, list) and len(info_res) > 0:
            info = info_res[0]
            apps = db.find_agrochemical_applications(info['rn'])
            tags = db.execute("""
                SELECT t.category, t.name FROM tags t
                JOIN product_tags pt ON pt.tag_id = t.id
                WHERE pt.product_id = ? AND pt.product_type = 'agrochemical'
                ORDER BY t.category, t.name
            """, (row_id,))
            return {"info": info, "applications": apps, "tags": tags or []}
    return JSONResponse(status_code=404, content={"error": "Not found"})

# ───────────────────────────────────────────────────────────────────────────────
# AUTH
# ───────────────────────────────────────────────────────────────────────────────

async def require_chat_access(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=403, detail="Вам доступ к AI помощнику не выдан, обратитесь к разработчикам")
    wl = get_whitelist_user(user.get("email", ""))
    if not wl:
        raise HTTPException(status_code=403, detail="Вам доступ к AI помощнику не выдан, обратитесь к разработчикам")
    return user

async def require_admin(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=403, detail="Unauthorized")
    wl = get_whitelist_user(user.get("email", ""))
    if not (wl and wl.get("is_admin")):
        raise HTTPException(status_code=403, detail="Admin only")
    return user

@app.get("/auth/me")
async def auth_me(request: Request):
    user = request.session.get("user")
    if not user:
        return {"user": None}
    wl = get_whitelist_user(user.get("email", ""))
    return {"user": user, "has_access": bool(wl), "is_admin": bool(wl and wl.get("is_admin"))}

@app.get("/auth/login/yandex")
async def auth_login_yandex(request: Request):
    try:
        url = yandex_oauth.get_auth_url()
        return RedirectResponse(url)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/auth/callback/yandex")
async def auth_callback_yandex(request: Request, code: str = "", error: str = ""):
    if error:
        return JSONResponse(status_code=400, content={"error": error})
    if not code:
        return JSONResponse(status_code=400, content={"error": "Missing code"})
    try:
        token_data = yandex_oauth.exchange_code(code)
        access_token = token_data.get("access_token")
        info = yandex_oauth.get_user_info(access_token)
        email = info.get("default_email") or info.get("emails", [None])[0]
        if not email:
            return JSONResponse(status_code=400, content={"error": "No email from Yandex"})
        request.session["user"] = {"email": email.lower().strip(), "name": info.get("display_name", "")}
        return RedirectResponse("/?tab=chat")
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

@app.get("/auth/logout")
async def auth_logout(request: Request):
    request.session.pop("user", None)
    return RedirectResponse("/")

# ───────────────────────────────────────────────────────────────────────────────
# ADMIN
# ───────────────────────────────────────────────────────────────────────────────

class AddUserPayload(BaseModel):
    email: str

@app.get("/admin/users")
async def admin_list_users(_=Depends(require_admin)):
    return {"users": list_whitelist_users()}

@app.post("/admin/users")
async def admin_add_user(data: AddUserPayload, request: Request, _=Depends(require_admin)):
    admin_email = request.session.get("user", {}).get("email", "")
    add_whitelist_user(data.email.strip(), is_admin=False, granted_by=admin_email)
    return {"status": "ok"}

@app.delete("/admin/users/{email}")
async def admin_remove_user(email: str, _=Depends(require_admin)):
    target = get_whitelist_user(email)
    if target and target.get("is_admin"):
        raise HTTPException(status_code=400, detail="Cannot remove admin")
    remove_whitelist_user(email)
    return {"status": "ok"}

# ───────────────────────────────────────────────────────────────────────────────
# CHAT
# ───────────────────────────────────────────────────────────────────────────────

from typing import List, Dict, Optional

class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, str]] = []
    model: Optional[str] = None

@app.post("/api/chat")
async def api_chat(req: ChatRequest, request: Request, user=Depends(require_chat_access)):
    if not req.message.strip():
        return {"answer": "Задайте, пожалуйста, вопрос о препарате, культуре или вредном объекте."}
    session_id = request.session.get("_id", "default")
    agent = RegistryAgent(session_id=session_id, model=req.model)
    answer = await agent.process_message(req.message.strip(), req.history)
    return {"answer": answer}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080)
