"""Telegram Mini App backend: serves the player page and a small JSON API."""
import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

from aiohttp import web
from pyrogram.enums import ChatMemberStatus

import config
from ShiviMusic import YouTube, app
from ShiviMusic.core.call import Shivi, group_assistant
from ShiviMusic.misc import SUDOERS, db
from ShiviMusic.utils.database import get_lang, is_active_chat, is_music_playing
from ShiviMusic.utils.stream.stream import stream
from strings import get_string

HERE = os.path.dirname(__file__)
ADMIN_ACTIONS = {"pause", "resume", "skip", "stop"}


class _Noop:
    """Stands in for the 'mystic' status message used by the downloader."""

    def __getattr__(self, _):
        async def f(*a, **k):
            return None

        return f


def _verify(init_data: str):
    """Validate Telegram WebApp initData; return the user dict or None."""
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True))
        got = data.pop("hash")
        check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, got):
            return None
        if time.time() - int(data.get("auth_date", 0)) > 86400:
            return None
        return json.loads(data["user"])
    except Exception:
        return None


async def _auth(request, chat_id, need_admin=False):
    user = _verify(request.headers.get("X-Init-Data", ""))
    if not user:
        raise web.HTTPUnauthorized(text="bad init data")
    uid = user["id"]
    try:
        m = await app.get_chat_member(chat_id, uid)
    except Exception:
        raise web.HTTPForbidden(text="not in this chat")
    is_admin = m.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
    is_admin = is_admin or uid in SUDOERS
    if need_admin and not is_admin:
        raise web.HTTPForbidden(text="admins only")
    user["is_admin"] = is_admin
    return user


def _chat(request) -> int:
    try:
        return int(request.query["chat_id"])
    except Exception:
        raise web.HTTPBadRequest(text="chat_id missing")


async def index(_):
    return web.FileResponse(os.path.join(HERE, "index.html"))


async def state(request):
    chat_id = _chat(request)
    user = await _auth(request, chat_id)
    q = db.get(chat_id) or []
    active = await is_active_chat(chat_id)
    items = [
        {
            "title": t.get("title"),
            "dur": t.get("dur"),
            "by": t.get("by", "").split("]")[0].lstrip("["),
            "thumb": f"https://i.ytimg.com/vi/{t['vidid']}/hqdefault.jpg"
            if t.get("vidid") and len(str(t["vidid"])) == 11
            else None,
        }
        for t in q
    ]
    return web.json_response(
        {
            "active": bool(active and q),
            "playing": bool(await is_music_playing(chat_id)) if active else False,
            "played": q[0].get("played", 0) if q else 0,
            "seconds": q[0].get("seconds", 0) if q else 0,
            "queue": items,
            "me": {"name": user.get("first_name", "Guest"), "admin": user["is_admin"]},
            "bot": app.name or "Music Bot",
        }
    )


async def control(request):
    chat_id = _chat(request)
    await _auth(request, chat_id, need_admin=True)
    action = (await request.json()).get("action")
    if action not in ADMIN_ACTIONS or not await is_active_chat(chat_id):
        raise web.HTTPBadRequest(text="nothing to control")
    if action == "pause":
        await Shivi.pause_stream(chat_id)
    elif action == "resume":
        await Shivi.resume_stream(chat_id)
    elif action == "stop":
        await Shivi.stop_stream(chat_id)
    elif action == "skip":
        client = await group_assistant(Shivi, chat_id)
        await Shivi.change_stream(client, chat_id)
    return web.json_response({"ok": True})


async def search(request):
    chat_id = _chat(request)
    await _auth(request, chat_id)
    q = request.query.get("q", "").strip()
    if not q:
        return web.json_response({"results": []})
    from youtubesearchpython.__future__ import VideosSearch

    res = (await VideosSearch(q, limit=8).next())["result"]
    return web.json_response(
        {
            "results": [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "dur": r.get("duration") or "",
                    "thumb": r["thumbnails"][0]["url"].split("?")[0],
                }
                for r in res
            ]
        }
    )


async def play(request):
    chat_id = _chat(request)
    user = await _auth(request, chat_id)
    vid = (await request.json()).get("id", "")
    if not (isinstance(vid, str) and len(vid) == 11):
        raise web.HTTPBadRequest(text="bad id")
    title, dmin, _dsec, thumb, vidid = await YouTube.details(vid, True)
    _ = get_string(await get_lang(chat_id))
    await stream(
        _,
        _Noop(),
        user["id"],
        {"link": f"https://www.youtube.com/watch?v={vidid}", "vidid": vidid,
         "title": title, "duration_min": dmin, "thumb": thumb},
        chat_id,
        user.get("first_name", "User"),
        chat_id,
        streamtype="youtube",
    )
    return web.json_response({"ok": True})


@web.middleware
async def errors(request, handler):
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception as e:
        return web.json_response({"error": str(e)[:200]}, status=500)


async def start_miniapp():
    web_app = web.Application(middlewares=[errors])
    web_app.router.add_get("/", index)
    web_app.router.add_get("/api/state", state)
    web_app.router.add_get("/api/search", search)
    web_app.router.add_post("/api/control", control)
    web_app.router.add_post("/api/play", play)
    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "8080"))).start()
