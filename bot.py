import os
import json
import asyncio

import aiohttp
import discord
from dotenv import load_dotenv


# ============================================================
# Load environment
# ============================================================

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_USER_IDS_RAW = os.getenv("DISCORD_USER_IDS", "")
ELDORADO_API_URL = os.getenv("ELDORADO_API_URL")

CHECK_INTERVAL = 30 * 60  # 30 minutes
STATE_FILE = "state.json"


# ============================================================
# Validate environment
# ============================================================

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from .env")

if not DISCORD_USER_IDS_RAW:
    raise RuntimeError("DISCORD_USER_IDS is missing from .env")

if not ELDORADO_API_URL:
    raise RuntimeError("ELDORADO_API_URL is missing from .env")


# ============================================================
# Parse Discord user IDs
# ============================================================

try:
    DISCORD_USER_IDS = [
        int(user_id.strip())
        for user_id in DISCORD_USER_IDS_RAW.split(",")
        if user_id.strip()
    ]
except ValueError:
    raise RuntimeError(
        "DISCORD_USER_IDS must contain Discord numeric user IDs separated by commas"
    )


if len(DISCORD_USER_IDS) < 2:
    raise RuntimeError("You must configure at least 2 Discord user IDs")

if len(DISCORD_USER_IDS) > 4:
    raise RuntimeError("You can configure a maximum of 4 Discord user IDs")


# ============================================================
# Discord client
# ============================================================

intents = discord.Intents.none()

client = discord.Client(intents=intents)


# ============================================================
# State
# ============================================================

def load_last_title():
    """
    Load the previously saved offer title.
    """

    if not os.path.exists(STATE_FILE):
        return None

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        return data.get("last_offer_title")

    except Exception as error:
        print(f"[ERROR] Could not read {STATE_FILE}: {error}")
        return None


def save_last_title(title):
    """
    Save the current offer title.
    """

    try:
        with open(STATE_FILE, "w", encoding="utf-8") as file:
            json.dump(
                {
                    "last_offer_title": title
                },
                file,
                indent=4,
                ensure_ascii=False
            )

    except Exception as error:
        print(f"[ERROR] Could not save {STATE_FILE}: {error}")


last_offer_title = load_last_title()


# ============================================================
# Eldorado API
# ============================================================

async def get_first_offer_title():
    """
    Get the first result's offer.offerTitle from Eldorado.
    """

    try:
        timeout = aiohttp.ClientTimeout(total=30)

        async with aiohttp.ClientSession(timeout=timeout) as session:

            async with session.get(
                ELDORADO_API_URL,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0"
                }
            ) as response:

                if response.status != 200:
                    print(
                        f"[ERROR] Eldorado API returned HTTP {response.status}"
                    )
                    return None

                data = await response.json()

        results = data.get("results", [])

        if not results:
            print("[ERROR] Eldorado API returned no results")
            return None

        first_result = results[0]

        offer = first_result.get("offer", {})

        offer_title = offer.get("offerTitle")

        if not offer_title:
            print("[ERROR] First result does not contain offer.offerTitle")
            return None

        return offer_title

    except asyncio.TimeoutError:
        print("[ERROR] Eldorado API request timed out")
        return None

    except aiohttp.ClientError as error:
        print(f"[ERROR] Eldorado API connection error: {error}")
        return None

    except Exception as error:
        print(f"[ERROR] Failed to read Eldorado API: {error}")
        return None


# ============================================================
# Send Discord DM
# ============================================================

async def send_change_notification(old_title, new_title):
    """
    Send the algorithm change notification to all configured users.
    """

    for user_id in DISCORD_USER_IDS:

        try:
            user = await client.fetch_user(user_id)

            await user.send("Algorithm changed")

            print(f"[DM] Sent notification to {user_id}")

        except discord.Forbidden:
            print(
                f"[ERROR] Cannot DM {user_id}. "
                f"The user may have DMs disabled or blocked the bot."
            )

        except discord.HTTPException as error:
            print(
                f"[ERROR] Discord API error while DMing {user_id}: {error}"
            )

        except Exception as error:
            print(
                f"[ERROR] Could not DM {user_id}: {error}"
            )


# ============================================================
# Check algorithm
# ============================================================

async def check_algorithm():
    global last_offer_title

    current_title = await get_first_offer_title()

    if current_title is None:
        print("[CHECK] Could not get current offer title.")
        return

    print("----------------------------------------")
    print(f"[CHECK] Current first offer: {current_title}")

    # --------------------------------------------------------
    # First-ever check
    # --------------------------------------------------------

    if last_offer_title is None:

        last_offer_title = current_title

        save_last_title(current_title)

        print(
            f"[INIT] Saved initial offer title: {current_title}"
        )

        return

    # --------------------------------------------------------
    # No change
    # --------------------------------------------------------

    if current_title == last_offer_title:

        print("[OK] Algorithm unchanged.")

        return

    # --------------------------------------------------------
    # Change detected
    # --------------------------------------------------------

    old_title = last_offer_title

    print("[ALERT] Algorithm changed!")
    print(f"[OLD] {old_title}")
    print(f"[NEW] {current_title}")

    await send_change_notification(
        old_title,
        current_title
    )

    # Save the new title AFTER sending notifications
    last_offer_title = current_title

    save_last_title(current_title)

    print("[STATE] New offer title saved.")


# ============================================================
# Monitoring loop
# ============================================================

async def monitor_loop():
    await client.wait_until_ready()

    print("")
    print("========================================")
    print("   Eldorado Algorithm Monitor")
    print("========================================")
    print(f"Users: {len(DISCORD_USER_IDS)}")
    print("Check interval: 30 minutes")
    print(f"Saved title: {last_offer_title}")
    print("========================================")
    print("")

    while not client.is_closed():

        try:
            await check_algorithm()

        except Exception as error:
            print(f"[ERROR] Monitor loop error: {error}")

        print("[WAIT] Next check in 30 minutes.")

        await asyncio.sleep(CHECK_INTERVAL)


# ============================================================
# Discord ready
# ============================================================

@client.event
async def on_ready():

    print(
        f"[DISCORD] Logged in as "
        f"{client.user} ({client.user.id})"
    )

    if not getattr(client, "_monitor_started", False):

        client._monitor_started = True

        asyncio.create_task(
            monitor_loop()
        )


# ============================================================
# Start bot
# ============================================================

client.run(DISCORD_TOKEN)