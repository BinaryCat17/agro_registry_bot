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

def yo_pattern(p: str):
    """Заменяет е/ё на регексный класс [её] для взаимозаменяемого поиска."""
    return ''.join('[её]' if c in 'её' else c for c in p)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "reestr.db")
db = RegistryDatabase(db_path=DB_PATH)

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

@app.get("/api/search")
async def api_search(
    type: str = Query("pesticides", regex="^(pesticides|agrochemicals)$"),
    q: str = Query(""),
    field: str = Query("all", regex="^(all|name|crop|pest|dv|reg_number)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    active_only: bool = Query(True)
):
    offset = (page - 1) * limit

    if type == "pesticides":
        if field == "name":
            items = db.find_pesticide_by_name(q, active_only=active_only, limit=limit, offset=offset)
            where = "p.naimenovanie REGEXP ?"
            if active_only:
                where += " AND p.status = 'Действует'"
            total_res = db.execute(f"SELECT COUNT(*) as c FROM pestitsidy p WHERE {where}", (yo_pattern(q),))
            total = total_res[0]['c']
        elif field == "dv":
            items = db.find_pesticide_by_dv(q, active_only=active_only, limit=limit, offset=offset)
            where = "exists (SELECT 1 FROM json_each(p.deystvuyushchee_veshchestvo) dv WHERE dv.value->>'veshchestvo' REGEXP ?)"
            if active_only:
                where += " AND p.status = 'Действует'"
            total_res = db.execute(f"SELECT COUNT(*) as c FROM pestitsidy p WHERE {where}", (yo_pattern(q),))
            total = total_res[0]['c']
        elif field == "crop":
            items = db.search_pesticides_by_crop(q, active_only=active_only, limit=limit, offset=offset)
            where = "pp.kultura REGEXP ?"
            if active_only:
                where += " AND p.status = 'Действует'"
            total_res = db.execute(f"SELECT COUNT(DISTINCT p.id) as c FROM pestitsidy p JOIN pestitsidy_primeneniya pp ON p.nomer_reg = pp.nomer_reg WHERE {where}", (yo_pattern(q),))
            total = total_res[0]['c']
        elif field == "pest":
            items = db.search_pesticides_by_pest(q, active_only=active_only, limit=limit, offset=offset)
            where = "pp.vrednyy_obekt REGEXP ?"
            if active_only:
                where += " AND p.status = 'Действует'"
            total_res = db.execute(f"SELECT COUNT(DISTINCT p.id) as c FROM pestitsidy p JOIN pestitsidy_primeneniya pp ON p.nomer_reg = pp.nomer_reg WHERE {where}", (yo_pattern(q),))
            total = total_res[0]['c']
        elif field == "reg_number":
            where = "nomer_reg REGEXP ?"
            if active_only:
                where += " AND status = 'Действует'"
            items = db.execute(f"SELECT * FROM pestitsidy WHERE {where} ORDER BY naimenovanie LIMIT {limit} OFFSET {offset}", (yo_pattern(q),))
            total_res = db.execute(f"SELECT COUNT(*) as c FROM pestitsidy WHERE {where}", (yo_pattern(q),))
            total = total_res[0]['c']
        else:
            seen = set()
            all_items = []
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
            total = len(all_items)
            items = all_items[offset:offset+limit]
    else:
        if field == "name":
            items = db.find_agrochemical_by_name(q, active_only=active_only, limit=limit, offset=offset)
            where = "preparat REGEXP ?"
            if active_only:
                where += " AND status = 'Действует'"
            total_res = db.execute(f"SELECT COUNT(*) as c FROM agrokhimikaty WHERE {where}", (yo_pattern(q),))
            total = total_res[0]['c']
        elif field == "crop":
            items = db.search_agrochemicals_by_crop(q, active_only=active_only, limit=limit, offset=offset)
            where = "ap.kultura REGEXP ?"
            if active_only:
                where += " AND a.status = 'Действует'"
            total_res = db.execute(f"SELECT COUNT(DISTINCT a.id) as c FROM agrokhimikaty a JOIN agrokhimikaty_primeneniya ap ON a.rn = ap.rn WHERE {where}", (yo_pattern(q),))
            total = total_res[0]['c']
        elif field == "reg_number":
            where = "rn REGEXP ?"
            if active_only:
                where += " AND status = 'Действует'"
            items = db.execute(f"SELECT * FROM agrokhimikaty WHERE {where} ORDER BY preparat LIMIT {limit} OFFSET {offset}", (yo_pattern(q),))
            total_res = db.execute(f"SELECT COUNT(*) as c FROM agrokhimikaty WHERE {where}", (yo_pattern(q),))
            total = total_res[0]['c']
        else:
            seen = set()
            all_items = []
            for r in db.find_agrochemical_by_name(q, active_only=active_only, limit=10000):
                if r['id'] not in seen:
                    seen.add(r['id']); all_items.append(r)
            for r in db.search_agrochemicals_by_crop(q, active_only=active_only, limit=10000):
                if r['id'] not in seen:
                    seen.add(r['id']); all_items.append(r)
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
            return {"info": info, "applications": apps}
    else:
        info_res = db.execute("SELECT * FROM agrokhimikaty WHERE id = ?", (row_id,))
        if info_res and isinstance(info_res, list) and len(info_res) > 0:
            info = info_res[0]
            apps = db.find_agrochemical_applications(info['rn'])
            return {"info": info, "applications": apps}
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
