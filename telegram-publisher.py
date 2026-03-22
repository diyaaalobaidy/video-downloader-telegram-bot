import re
import time
import feedparser
import asyncio
import json
import os
from telegram import Bot
from deep_translator import GoogleTranslator
import dotenv

dotenv.load_dotenv()

# --- CONFIGURATION ---
TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
DATABASE_FILE = 'last_seen.json'
TRANSLATE = True
PERIODIC_CHECK = False

# Dictionary of feeds: { "Name": "URL" }
ENGLISH_FEEDS = {
    "Science Daily": "https://www.sciencedaily.com/rss/all.xml",
    "Science": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sciadv",
    "Science Robotics": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=scirobotics",
    "Knowable Magazine": "https://knowablemagazine.org/rss",
    "The Guardian Science": "https://www.theguardian.com/science/rss",
    "NPR Science": "https://feeds.npr.org/1007/rss.xml",
}

ARABIC_FEEDS ={
}

names_ar ={

}

CHECK_INTERVAL = 60 # 1 minute
# ---------------------

bot = Bot(token=TOKEN)
translator = GoogleTranslator(source='auto', target='ar')

def load_last_seen():
    """Loads the last seen post IDs from the JSON file."""
    if os.path.exists(DATABASE_FILE):
        with open(DATABASE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_last_seen(data):
    """Saves the last seen post IDs to the JSON file."""
    with open(DATABASE_FILE, 'w') as f:
        json.dump(data, f, indent=4)

async def process_feeds():
    last_seen = load_last_seen()
    to_be_sent = []
    for name, url in ENGLISH_FEEDS.items():
        print(f"Checking {name}...")
        feed = feedparser.parse(url)
        
        if not feed.entries:
            continue

        # The first entry in the RSS is usually the newest
        latest_entry = feed.entries[0]
        latest_id = latest_entry.link
        
        # Compare with what we have stored
        if last_seen.get(name) != latest_id:
            try:
                for entry in feed.entries[:2]:
                    if entry.link == last_seen.get(name):
                        break
                    # Translate
                    title = re.sub(r'<.*?>', '', entry.title) # strip html tags from title
                    if TRANSLATE:
                        title = translator.translate(title)
                    # strip html tags from description and limit to 5000 characters for translation
                    try:
                        description = re.sub(r'<.*?>', '', entry.description)[:5000]
                    except Exception as e:
                        print(e)
                        try:
                            description:str = re.sub(r'<.*?>', '', entry.content)[:5000]
                        except Exception as e:
                            print(e)
                            description = ""
                    if TRANSLATE:
                        description = translator.translate(description)
                    # get image if exists
                    image_url = None
                    if 'media_content' in entry:
                        image_url = entry.media_content[0]['url']
                    

                    message = ((
                        f"\u200f<b>{title}</b>\n\n"
                        f"{description}\n\n"
                        f"<a href='{entry.link}'>المصدر: {names_ar.get(name, name)}</a>\n"
                        f"#{name.replace(' ', '_')} #{names_ar.get(name, name).replace(' ', '_')}\n"
                    ), image_url)
                    try:
                        published_time = entry.published_parsed
                    except Exception as e:
                        published_time = time.gmtime() # use current time if published time is not available

                    # append to to_be_sent list with time of the post for ordering
                    to_be_sent.append((message, published_time, name, entry.link))
                last_seen[name] = latest_id
                save_last_seen(last_seen)
                print(f"New post added for {name}")
                
            except Exception as e:
                print(f"Error processing {name}: {e}")
    # order messages by feed published time
    to_be_sent.sort(key=lambda x: x[1])
    for message, _, _, _ in to_be_sent:
        try:
            await bot.send_message(chat_id=CHANNEL_ID, text=message[0], parse_mode='HTML', write_timeout=10, disable_web_page_preview=False, read_timeout=10, connect_timeout=10, pool_timeout=10)
            await asyncio.sleep(2)  # To avoid hitting rate limits
        except Exception as e:
            print(f"Error sending message: {e}")
    print("Finished checking all feeds.")

async def main():
    print("Bot started...")
    while True:
        await process_feeds()
        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    if PERIODIC_CHECK:
        asyncio.run(main())
    else:
        asyncio.run(process_feeds())