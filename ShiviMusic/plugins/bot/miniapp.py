from pyrogram import filters
from pyrogram.enums import ChatType
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

import config
from ShiviMusic import app


@app.on_message(filters.command(["app", "miniapp"]) & ~config.BANNED_USERS)
async def miniapp_cmd(_, message):
    if not config.MINIAPP_URL:
        return await message.reply_text("Mini App abhi set nahi hai. `MINIAPP_URL` config mein daalo.")
    if message.chat.type == ChatType.PRIVATE:
        btn = InlineKeyboardButton("🎵 Open Music App", web_app=WebAppInfo(url=config.MINIAPP_URL))
        text = "Group ka player kholne ke liye group mein /app use karo."
    else:
        if not config.MINIAPP_SHORTNAME:
            return await message.reply_text("`MINIAPP_SHORTNAME` set nahi hai (BotFather → /newapp).")
        link = f"https://t.me/{app.username}/{config.MINIAPP_SHORTNAME}?startapp={message.chat.id}"
        btn = InlineKeyboardButton("🎵 Open Music App", url=link)
        text = "🎶 **Alexa ✘ Music** — play, skip aur queue yahin se control karo."
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup([[btn]]))
