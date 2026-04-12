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

class ChatRequest(BaseModel):
    message: str

_STOP_WORDS = {
    "какой","какие","какое","какая","какого","какой-то","какие-то","найди","поиск","препарат","препараты",
    "информация","про","для","что","такое","есть","зарегистрирован","зарегистрированы","фунгицид","фунгициды",
    "инсектицид","инсектициды","гербицид","гербициды","удобрение","удобрения","агрохимикат","агрохимикаты",
    "покажи","дай","скажи","мне","нам","пожалуйста","спасибо","привет","подскажи","расскажи","где",
    "когда","почему","кто","этот","эта","это","тот","та","те","такой","такие","весь","все","вся","всё",
    "или","и","но","а","если","тогда","чтобы","который","которая","которые","быть","есть","был","была",
    "были","будет","как","так","очень","более","менее","тоже","также","да","нет","ли","же","бы","ни",
    "по","на","в","с","из","за","до","от","под","над","перед","при","через","про","без","для","об","со",
    "из-за","по","насчет","сколько","много","мало","несколько","два","три","раз","другой","другие",
    "состав","регламент","действующее","вещество","вещества","подробнее","о","больше",
    "против","защита","защиту","обработка","обработку","опрыскивание","внедрение","применение"
}

_CROP_HINTS = {
    "пшеница", "картофель", "ячмень", "свекла", "виноград", "кукуруза", "подсолнечник", "соя", "рапс",
    "лен", "горох", "овес", "рожь", "рис", "гречиха", "горчица", "клевер", "люпин", "люцерна",
    "яблоня", "вишня", "слива", "персик", "груша", "черешня", "малина", "смородина", "клубника", "земляника",
    "томат", "перец", "огурец", "капуста", "морковь", "лук", "чеснок", "тыква", "арбуз", "дыня",
    "бобовые", "зерновые", "кормовые", "овощные", "плодовые", "ягодные"
}

@app.post("/api/chat")
async def api_chat(req: ChatRequest, user=Depends(require_chat_access)):
    msg = req.message.lower().strip()
    if not msg:
        return {"answer": "Задайте, пожалуйста, вопрос о препарате, культуре или вредном объекте."}

    words = re.findall(r'[а-яa-z0-9ё\-]+', msg)
    terms = [w for w in words if len(w) > 3 and w not in _STOP_WORDS]

    # 1. Сначала ищем как название препарата (по фразе из terms)
    answer_parts = []
    found_product = False
    if terms:
        for n in range(min(3, len(terms)), 0, -1):
            phrase = " ".join(terms[:n]).capitalize()
            pests = db.find_pesticide_by_name(phrase, active_only=False, limit=5)
            if not pests:
                pests = db.find_pesticide_by_dv(phrase, active_only=False, limit=5)
            agros = db.find_agrochemical_by_name(phrase, active_only=False, limit=5)
            if pests or agros:
                found_product = True
                for p in pests:
                    dv_text = ""
                    if p.get('deystvuyushchee_veshchestvo'):
                        try:
                            dv_list = json.loads(p['deystvuyushchee_veshchestvo'])
                            dv_text = ", ".join([f"{d['veshchestvo']} {d['koncentraciya']} г/л" for d in dv_list])
                        except Exception:
                            dv_text = str(p['deystvuyushchee_veshchestvo'])
                    answer_parts.append(
                        f"**{p['naimenovanie']}** (пестицид)\n"
                        f"- Рег. №: {p['nomer_reg']}\n"
                        f"- Регистратор: {p['registrant']}\n"
                        f"- Статус: {p['status']} до {p['srok_reg']}\n"
                        f"- ДВ: {dv_text or '-'}\n"
                        f"- Форма: {p.get('preparativnaya_forma') or '-'}"
                    )
                for a in agros:
                    answer_parts.append(
                        f"**{a['preparat']}** (агрохимикат)\n"
                        f"- Рег. №: {a['rn']}\n"
                        f"- Регистратор: {a['registrant']}\n"
                        f"- Статус: {a['status']} до {a['srok_reg']}\n"
                        f"- Группа: {a.get('group_name') or '-'}"
                    )
                break

    if found_product:
        return {"answer": "\n\n".join(answer_parts)}

    # 2. Проверяем, запрос по культуре
    is_crop_query = any(h in msg for h in _CROP_HINTS)
    if is_crop_query:
        crop_terms = [h for h in _CROP_HINTS if h in msg]
        for crop in crop_terms[:2]:
            pests = db.search_pesticides_by_crop(crop, active_only=True, limit=10)
            agros = db.search_agrochemicals_by_crop(crop, active_only=True, limit=10)
            if pests or agros:
                answer_parts.append(f"### Результаты для «{crop.capitalize()}»")
                if pests:
                    answer_parts.append(f"**Пестициды ({len(pests)} найдено):**")
                    for p in pests[:5]:
                        answer_parts.append(f"- **{p['naimenovanie']}** — {p['registrant']} (до {p['srok_reg']})")
                    if len(pests) > 5:
                        answer_parts.append(f"- ...и ещё {len(pests) - 5} препаратов")
                if agros:
                    answer_parts.append(f"**Агрохимикаты ({len(agros)} найдено):**")
                    for a in agros[:5]:
                        answer_parts.append(f"- **{a['preparat']}** — {a['registrant']} (до {a['srok_reg']})")
                    if len(agros) > 5:
                        answer_parts.append(f"- ...и ещё {len(agros) - 5} препаратов")
        if not answer_parts:
            answer_parts.append("По указанной культуре ничего не найдено в реестре.")
        return {"answer": "\n\n".join(answer_parts)}

    # 3. Пробуем как вредный объект
    pests = db.search_pesticides_by_pest(msg, active_only=True, limit=10)
    if pests:
        answer_parts.append(f"### Пестициды от «{req.message.strip()}» ({len(pests)} найдено)")
        for p in pests[:7]:
            answer_parts.append(f"- **{p['naimenovanie']}** — {p['registrant']} (до {p['srok_reg']})")
        if len(pests) > 7:
            answer_parts.append(f"- ...и ещё {len(pests) - 7} препаратов")
        return {"answer": "\n\n".join(answer_parts)}

    answer_parts.append("Я не смог найти информацию по этому запросу в реестре.")
    answer_parts.append("Примеры запросов:")
    answer_parts.append("- «Абакус Ультра»")
    answer_parts.append("- «Престиж состав»")
    answer_parts.append("- «Пестициды для пшеницы озимой»")
    answer_parts.append("- «От колорадского жука»")
    return {"answer": "\n\n".join(answer_parts)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080)
