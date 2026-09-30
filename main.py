import os, io, json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image
from starlette.concurrency import run_in_threadpool

import database as db
from gemini_utils import PLANNERS, recommend

load_dotenv()
SECRET = os.getenv("SECRET_KEY", "dev-secret-change-me")
BASE = os.path.dirname(os.path.abspath(__file__))


@asynccontextmanager
async def lifespan(app):  # startup: create tables
    db.init_db()
    yield


app = FastAPI(title="PocketSmart AI", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))
templates.env.filters["inr"] = lambda v: f"₹{float(v):,.0f}"


def render(request, name, **ctx):
    return templates.TemplateResponse(request, name, ctx)


# ---------- auth ----------
class NotAuthenticated(Exception):
    pass


@app.exception_handler(NotAuthenticated)
async def to_login(request, exc):
    return RedirectResponse("/login", status_code=303)


def make_token(user):
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    return jwt.encode({"sub": user["username"], "uid": user["id"], "exp": exp}, SECRET, algorithm="HS256")


def current_user(request: Request):
    token = request.cookies.get("access_token")
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
    try:
        d = jwt.decode(token, SECRET, algorithms=["HS256"])
        return {"id": d["uid"], "username": d["sub"]}
    except Exception:
        raise NotAuthenticated()


@app.get("/register")
async def register_page(request: Request):
    return render(request, "auth.html", mode="register")


@app.post("/register")
async def register(request: Request, username: str = Form(...), password: str = Form(...)):
    username = username.strip()
    if len(username) < 3 or len(password) < 6:
        return render(request, "auth.html", mode="register", error="Use a username of 3+ characters and a password of 6+.")
    if not db.add_user(username, password):
        return render(request, "auth.html", mode="register", error="That username is taken. Choose another or log in.")
    return RedirectResponse("/login?registered=1", status_code=303)


@app.get("/login")
async def login_page(request: Request):
    return render(request, "auth.html", mode="login")


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = db.verify_user(username.strip(), password)
    if not user:
        return render(request, "auth.html", mode="login", error="Wrong username or password.")
    resp = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie("access_token", make_token(user), httponly=True, samesite="lax", max_age=8 * 3600)
    return resp


@app.post("/token")
async def token(username: str = Form(...), password: str = Form(...)):
    user = db.verify_user(username.strip(), password)
    if not user:
        raise HTTPException(401, "Incorrect username or password")
    return {"access_token": make_token(user), "token_type": "bearer"}


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("access_token")
    return resp


@app.get("/session-info")
async def session_info(user=Depends(current_user)):
    return {"user_id": user["id"], "username": user["username"], "logged_in": True}


@app.get("/session-data")
async def session_data(user=Depends(current_user)):
    h = db.list_history(user["id"])
    counts = {}
    for x in h:
        counts[x["kind"]] = counts.get(x["kind"], 0) + 1
    return {"total_plans": len(h), "by_category": counts, "recent": h[:5]}


# ---------- pages ----------
@app.get("/")
async def root():
    return RedirectResponse("/dashboard")


@app.get("/dashboard")
async def dashboard(request: Request, user=Depends(current_user)):
    return render(request, "dashboard.html", user=user, planners=PLANNERS, recent=db.list_history(user["id"], 5))


@app.get("/history")
async def history(request: Request, user=Depends(current_user)):
    return render(request, "history.html", user=user, items=db.list_history(user["id"]))


@app.get("/recommendations-details/{rid}")
async def details(rid: int, request: Request, user=Depends(current_user)):
    row = db.get_history(user["id"], rid)
    if not row:
        raise HTTPException(404, "Recommendation not found")
    kind = row["kind"]
    return render(request, "result.html", user=user, kind=kind, p=PLANNERS[kind],
                  r=json.loads(row["result"]), inputs=json.loads(row["inputs"]))


# ---------- planners (home, party, jewelry) ----------
@app.get("/{kind}-planner")
async def planner(kind: str, request: Request, user=Depends(current_user)):
    if kind not in PLANNERS:
        raise HTTPException(404)
    return render(request, "planner.html", user=user, kind=kind, p=PLANNERS[kind])


@app.post("/generate-{kind}")  # /generate-home, /generate-party, /generate-jewelry
async def generate(kind: str, request: Request, user=Depends(current_user)):
    if kind not in PLANNERS:
        raise HTTPException(404)
    p = PLANNERS[kind]
    form = await request.form()
    data = {k: v.strip() for k, v in form.items() if isinstance(v, str)}

    def fail(msg):
        return render(request, "planner.html", user=user, kind=kind, p=p, values=data, error=msg)

    try:
        budget = float(data.get("budget", ""))
        assert 0 < budget < 1e9
    except Exception:
        return fail("Enter a budget greater than 0.")

    image = None
    up = form.get("outfit_image")
    if up is not None and getattr(up, "filename", ""):
        try:
            image = Image.open(io.BytesIO(await up.read()))
            image.load()
            image.thumbnail((1024, 1024))
        except Exception:
            return fail("That file is not a valid image. Upload a JPG or PNG.")

    result = await run_in_threadpool(recommend, kind, data, image)
    db.save_history(user["id"], kind, budget, data, result)
    return render(request, "result.html", user=user, kind=kind, p=p, r=result, inputs=data)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
