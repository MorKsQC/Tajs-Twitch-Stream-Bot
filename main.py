import os
import asyncio
import requests
import discord
from discord.ext import commands
from flask import Flask
import threading

# Load environment variables
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
MODERATOR_ROLE = os.getenv("MODERATOR_ROLE", "Moderator")

# Twitch Game IDs
GAME_IDS = ["5093", "14660"]  # [Diddy Kong Racing DS, Diddy Kong Racing]

# Twitch Stream Title Keywords
KEYWORDS = [
    "any%", "100%", "car%", "hover%", "plane%", "atr", "all trophy races",
    "speedrun", "practice", "learning", "marathon", "dkr64", "time trial",
    "wr", "world record", "pb", "rando", "randomizer", "speedrun", "T.T.",
    "time trial", "tt", "unlocking", "rta", "ディディーコングレーシング", "ディディーコング",
    "ディディ", "tammy", "amulet", "grind", "hundo", "100", "DKR", "tourney",
    "tournament", "trophy", "no wrong warp", "wrong warp", "ww",
    "all minigames", "all bosses", "adventure 2 100%", "true 100%", "atrmc"
]

# Twitch Stream Tags
TAGS = ["speedrun"]

# Discord bot setup
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Global variables
monitoring = False
live_streams = set()
stream_message_map = {}  # Store stream_id -> Discord message object


# Twitch API authentication
def get_twitch_access_token():
    url = "https://id.twitch.tv/oauth2/token"
    params = {
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type": "client_credentials",
    }
    response = requests.post(url, params=params)
    response.raise_for_status()
    return response.json()["access_token"]


# Check live streams for specific games
def check_live_streams(access_token):
    url = "https://api.twitch.tv/helix/streams"
    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {access_token}"
    }
    params = [("game_id", game_id) for game_id in GAME_IDS]
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()["data"]


# Filter streams by title and tag
def filter_streams_by_title_and_tag(streams):
    filtered_streams = []

    for stream in streams:

        # Check if the stream has the correct game ID
        if stream["game_id"] not in GAME_IDS:
            continue

        # Check if the stream has any of the tags in TAGS (case-insensitive)
        has_tag = any(tag.lower() in TAGS for tag in stream.get("tag_ids", []))

        # Check if the title contains any of the keywords (case-insensitive)
        matching_keywords = [
            keyword for keyword in KEYWORDS
            if keyword.lower() in stream["title"].lower()
        ]

        # Condition 1: Keywords in title AND correct game ID
        condition1 = bool(matching_keywords) and stream["game_id"] in GAME_IDS

        # Condition 2: Tag "speedrun" AND correct game ID
        condition2 = has_tag and stream["game_id"] in GAME_IDS

        # Condition 3: Tag "speedrun" AND Keywords in title AND correct game ID
        condition3 = has_tag and bool(
            matching_keywords) and stream["game_id"] in GAME_IDS

        # Include stream if any of the conditions are met
        if condition1 or condition2 or condition3:
            filtered_streams.append(stream)

    return filtered_streams


# Get stream thumbnail URL (16:9 aspect ratio)
def get_stream_thumbnail(stream):
    return stream["thumbnail_url"].replace("{width}",
                                           "480").replace("{height}", "270")


# Send Discord alert and store message reference
async def send_discord_alert(ctx, stream):
    embed = discord.Embed(
        title=
        f"🎮 Alakazoom! **{stream['user_name']}** is live playing {stream['game_name']}!",
        description=
        f"📜 Title: {stream['title']}\n🔗 [Twitch Stream Link](https://twitch.tv/{stream['user_name']})",
        color=discord.Color.green())
    # Add stream thumbnail image to the embed (16:9 ratio)
    embed.set_image(url=get_stream_thumbnail(stream))
    message = await ctx.send(embed=embed)
    return message


# Delete Discord alert when streamer goes offline
async def update_discord_alert(message):
    try:
        await message.delete()
    except discord.NotFound:
        # In case the message was already deleted
        pass


# Monitor streams in the background
async def monitor_streams(ctx):
    global monitoring, live_streams, stream_message_map
    access_token = get_twitch_access_token()

    while monitoring:
        try:
            streams = check_live_streams(access_token)
            filtered_streams = filter_streams_by_title_and_tag(streams)
            current_live_streams = set()

            # Check for new live streams
            for stream in filtered_streams:
                stream_id = stream["id"]
                current_live_streams.add(stream_id)
                if stream_id not in live_streams:
                    # Send alert and store message
                    message = await send_discord_alert(ctx, stream)
                    stream_message_map[stream_id] = message
                    live_streams.add(stream_id)

            # Check for streams that went offline
            for stream_id in list(live_streams):
                if stream_id not in current_live_streams:
                    if stream_id in stream_message_map:
                        await update_discord_alert(
                            stream_message_map[stream_id])
                        del stream_message_map[stream_id]
                    live_streams.remove(stream_id)

        except Exception as e:
            await ctx.send(f"❌ Error during monitoring: {e}")

        await asyncio.sleep(60)


# Start monitoring command
@bot.command(name="start_monitoring")
@commands.has_role(MODERATOR_ROLE)
async def start_monitoring(ctx):
    global monitoring
    if monitoring:
        await ctx.send("⚠️ Monitoring is already running.")
    else:
        monitoring = True
        await ctx.send("🎥 Starting to monitor streams...")
        bot.loop.create_task(monitor_streams(ctx))


# Stop monitoring command
@bot.command(name="stop_monitoring")
@commands.has_role(MODERATOR_ROLE)
async def stop_monitoring(ctx):
    global monitoring
    if not monitoring:
        await ctx.send("⚠️ Monitoring is not running.")
    else:
        monitoring = False
        await ctx.send("🛑 Monitoring stopped.")


# Flask web server to keep the Repl alive
app = Flask(__name__)


@app.route('/')
def home():
    return "The Discord Twitch bot is running!"


def run_flask():
    app.run(host="0.0.0.0", port=8080)


# Run Flask and Discord bot simultaneously
if __name__ == "__main__":
    # Start Flask in a separate thread
    threading.Thread(target=run_flask).start()

    # Run Discord bot
    if DISCORD_BOT_TOKEN is None:
        raise ValueError("DISCORD_BOT_TOKEN environment variable not set.")
    bot.run(DISCORD_BOT_TOKEN)
