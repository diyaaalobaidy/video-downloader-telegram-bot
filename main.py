import os
import asyncio
import hashlib
import random
import string
from venv import logger
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
import dotenv

dotenv.load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
LOCAL_API_URL = os.getenv("LOCAL_API_URL", "http://localhost:8081")

if os.getenv("PROXY", "") == "tor":
    username = random.choices(string.ascii_letters + string.digits, k=8)
    password = random.choices(string.ascii_letters + string.digits, k=8)
    PROXY_URL = "socks5h://{username}:{password}@127.0.0.1:9050".format(username=username, password=password)

YDL_BASE_OPTS = {
    "quiet": True,
    "extractor_args": {"youtube": {"js_runtimes": ["nodejs"]}},
}

if os.getenv("PROXY", "") == "tor":
    YDL_BASE_OPTS["proxy"] = PROXY_URL


def fetch_info(url):
    with yt_dlp.YoutubeDL(YDL_BASE_OPTS) as ydl:
        return ydl.extract_info(url, download=False)


def do_download(url, fmt_selector, is_audio, out_path):
    opts = {
        **YDL_BASE_OPTS,
        "format": fmt_selector,
        "outtmpl": out_path,
        # No size limit — local Bot API server supports up to 2 GB
    }
    if is_audio:
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]
    else:
        opts["merge_output_format"] = "mp4"

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(url, download=True)

    if is_audio:
        return os.path.splitext(out_path)[0] + ".mp3"
    return out_path


def make_caption(info, label):
    title = info.get("title", "")
    uploader = info.get("uploader", "") or info.get("channel", "")
    duration = info.get("duration")
    view_count = info.get("view_count")

    lines = [f"📹 *{title}*"]
    if uploader:
        lines.append(f"👤 {uploader}")
    if duration:
        mins, secs = divmod(int(duration), 60)
        hours, mins = divmod(mins, 60)
        dur_str = f"{hours}:{mins:02d}:{secs:02d}" if hours else f"{mins}:{secs:02d}"
        lines.append(f"⏱ {dur_str}")
    if view_count:
        lines.append(f"👁 {view_count:,} views")
    lines.append(f"🎚 {label}")
    return "\n".join(lines)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if not url.startswith("http"):
        return

    status_msg = await update.message.reply_text("🔍 Fetching available formats...")

    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, fetch_info, url)
        formats = info.get("formats", [])

        # Deduplicate video qualities by height
        seen_heights = set()
        options = []
        video_fmts = sorted(
            [f for f in formats if f.get("vcodec") != "none" and f.get("height")],
            key=lambda f: f["height"],
            reverse=True,
        )
        for f in video_fmts:
            h = f["height"]
            if h in seen_heights:
                continue
            seen_heights.add(h)
            selector = (
                f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]"
                f"/bestvideo[height<={h}]+bestaudio/best[height<={h}]"
            )
            options.append((f"🎬 {h}p", selector, False))

        options.append(("🎵 Audio only (MP3)", "bestaudio/best", True))

        context.user_data["url"] = url
        context.user_data["options"] = options
        context.user_data["info"] = info

        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(label, callback_data=f"dl:{i}")]
                for i, (label, _, _) in enumerate(options)
            ]
        )

        title = info.get("title", "Video")
        await status_msg.edit_text(
            f"📹 *{title}*\n\nSelect quality:",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {str(e)}")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    idx = int(query.data.split(":")[1])
    url = context.user_data.get("url")
    options = context.user_data.get("options", [])
    info = context.user_data.get("info", {})

    if not url or idx >= len(options):
        await query.edit_message_text("❌ Session expired. Please send the URL again.")
        return

    label, fmt_selector, is_audio = options[idx]
    await query.edit_message_text(f"⏳ Downloading {label}...")

    try:
        # Use a short hash as the filename to avoid path-too-long errors
        name_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        ext = "mp3" if is_audio else "mp4"
        out_path = f"downloads/{name_hash}.{ext}"

        loop = asyncio.get_running_loop()
        file_path = await loop.run_in_executor(
            None, do_download, url, fmt_selector, is_audio, out_path
        )

        # Handle possible .part leftover
        if not os.path.exists(file_path):
            part = file_path + ".part"
            if os.path.exists(part):
                os.rename(part, file_path)

        caption = make_caption(info, label)

        if is_audio:
            with open(file_path, "rb") as f:
                await query.message.reply_audio(
                    audio=f,
                    caption=caption,
                    parse_mode="Markdown",
                    write_timeout=1000,
                )
        else:
            with open(file_path, "rb") as f:
                await query.message.reply_video(
                    video=f,
                    caption=caption,
                    parse_mode="Markdown",
                    write_timeout=1000,
                )

        os.remove(file_path)
        await query.delete_message()

    except Exception as e:
        await query.edit_message_text(f"❌ Error: {str(e)}")


def main():
    if not os.path.exists("downloads"):
        os.makedirs("downloads")

    builder = (
        Application.builder()
        .token(BOT_TOKEN)
        .base_url(f"{LOCAL_API_URL}/bot")
        .base_file_url(f"{LOCAL_API_URL}/file/bot")
        .local_mode(True)
    )
    app = builder.build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback, pattern=r"^dl:"))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
