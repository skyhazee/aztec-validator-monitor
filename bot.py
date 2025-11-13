# -*- coding: utf-8 -*-
import os
import json
import logging
from datetime import datetime, timedelta
from functools import wraps
import time
import math
import re

import cloudscraper
import pytz
from dotenv import load_dotenv
from telegram import Update, ParseMode, Bot
from telegram.ext import Updater, CommandHandler, CallbackContext
from apscheduler.schedulers.background import BackgroundScheduler

# --- Boot ---
load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger("aztec-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN")
try:
    AUTHORIZED_USER_ID = int(os.getenv("TELEGRAM_ID"))
except (ValueError, TypeError):
    logger.error("TELEGRAM_ID is invalid or missing in .env.")
    raise SystemExit(1)

# Fast polling interval for (near) real-time notifications
try:
    CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "3"))
    if CHECK_INTERVAL_SECONDS < 1:
        CHECK_INTERVAL_SECONDS = 3
except Exception:
    CHECK_INTERVAL_SECONDS = 3

VALIDATORS_FILE = "validators.json"
LAST_STATE_FILE = "last_state.json"

# Testnet APIs
API_URL_DETAIL = "https://testnet.dashtec.xyz/api/validators/{}"
API_URL_LIST   = "https://testnet.dashtec.xyz/api/validators?"

QUEUE_API_URL   = "https://testnet.dashtec.xyz/api/sequencers/queue"
QUEUE_STATS_URL = "https://testnet.dashtec.xyz/api/sequencers/queue/stats"

DEFAULT_EPOCH_MINUTES = 38
DEFAULT_VALIDATORS_PER_EPOCH = 4

WIB = pytz.timezone('Asia/Jakarta')

scraper = cloudscraper.create_scraper()

BROWSER_HEADERS = {
    'accept': '*/*',
    'accept-language': 'en-US,en;q=0.9,id;q=0.8',
    'priority': 'u=1, i',
    'sec-ch-ua': '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Linux"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
}

# ----------------- Auth & State Utils -----------------
def restricted(func):
    @wraps(func)
    def wrapped(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != AUTHORIZED_USER_ID:
            logger.warning(f"Unauthorized access denied for user ID: {user_id}.")
            if update.message:
                update.message.reply_text("⛔ You are not allowed to use this bot.")
            return
        return func(update, context, *args, **kwargs)
    return wrapped

def load_json_file(filename: str, default_value=None):
    if default_value is None:
        default_value = []
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_value

def save_json_file(filename: str, data):
    tmp = filename + ".tmp"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    os.replace(tmp, filename)

def load_validators():
    return load_json_file(VALIDATORS_FILE, [])

def save_validators(validators):
    save_json_file(VALIDATORS_FILE, validators)

def load_last_state():
    return load_json_file(LAST_STATE_FILE, {})

def save_last_state(state):
    save_json_file(LAST_STATE_FILE, state)

# ----------------- Main Validator API -----------------
def fetch_validator_data(address: str):
    """Return JSON or None."""
    try:
        headers = BROWSER_HEADERS.copy()
        headers['referer'] = f"https://testnet.dashtec.xyz/validators/{address}"
        resp = scraper.get(API_URL_DETAIL.format(address), timeout=20, headers=headers)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch details for {address}: {e}")
        return None

def fetch_validator_rank_and_score(address: str):
    """Best-effort rank/score (may be N/A on testnet)."""
    try:
        headers = BROWSER_HEADERS.copy()
        headers['referer'] = 'https://testnet.dashtec.xyz/validators'
        search_url = f"{API_URL_LIST}search={address}"
        resp = scraper.get(search_url, timeout=15, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        validators_list = data.get('validators', []) or data.get('data', []) or []
        if not validators_list:
            return "N/A", "N/A"
        info = validators_list[0]
        rank = info.get('rank', 'N/A')
        score = info.get('performanceScore', 'N/A')
        return rank, score
    except Exception:
        return "N/A", "N/A"

# ----------------- Queue API (for /queue command only) -----------------
def fetch_queue_stats():
    try:
        headers = BROWSER_HEADERS.copy()
        headers['referer'] = 'https://testnet.dashtec.xyz/queue'
        r = scraper.get(QUEUE_STATS_URL, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json() if r.text else {}
        epoch_minutes = (
            data.get('epochDurationMinutes') or
            data.get('epoch_minutes') or
            data.get('epochDuration') or
            DEFAULT_EPOCH_MINUTES
        )
        validators_per_epoch = (
            data.get('validatorsPerEpoch') or
            data.get('validators_per_epoch') or
            DEFAULT_VALIDATORS_PER_EPOCH
        )
        epoch_minutes = int(epoch_minutes) if str(epoch_minutes).isdigit() else DEFAULT_EPOCH_MINUTES
        validators_per_epoch = int(validators_per_epoch) if str(validators_per_epoch).isdigit() else DEFAULT_VALIDATORS_PER_EPOCH
        return {"epoch_minutes": epoch_minutes, "validators_per_epoch": validators_per_epoch}
    except Exception as e:
        logger.warning(f"Failed to fetch queue stats, using defaults: {e}")
        return {"epoch_minutes": DEFAULT_EPOCH_MINUTES, "validators_per_epoch": DEFAULT_VALIDATORS_PER_EPOCH}

def _parse_position_value(val):
    if val is None:
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        digits = re.sub(r'\D+', '', val)
        try:
            return int(digits) if digits else None
        except Exception:
            return None
    return None

def fetch_queue_info(address: str):
    """Used only for /queue command (tidak kirim notif otomatis)."""
    try:
        headers = BROWSER_HEADERS.copy()
        headers['referer'] = 'https://testnet.dashtec.xyz/queue'
        params = {"page": 1, "limit": 10, "search": address}
        r = scraper.get(QUEUE_API_URL, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        data = r.json() if r.text else {}
        validators = data.get('validatorsInQueue', [])
        filtered_count = data.get('filteredCount', None)
        if isinstance(validators, list) and validators:
            item = validators[0]
            pos = _parse_position_value(item.get('position')) or _parse_position_value(item.get('index'))
            return {"position": pos, "status": "in-queue", "raw": item, "found": True}
        if filtered_count == 0:
            return {"position": None, "status": "not-in-queue", "raw": {}, "found": False}
        return {"position": None, "status": None, "raw": {}, "found": False}
    except Exception as e:
        logger.error(f"Failed to fetch queue for {address}: {e}")
        return {"position": None, "status": None, "raw": {}, "found": False}

# ---------- ETA formatting: day/hour ----------
def _format_days_hours_from_minutes(total_minutes: int) -> str:
    if total_minutes <= 0:
        return "0 hours"
    hours = math.ceil(total_minutes / 60.0)
    days = hours // 24
    rem_hours = hours % 24
    parts = []
    if days > 0:
        parts.append(f"{days} day" + ("s" if days != 1 else ""))
    if rem_hours > 0 or days == 0:
        parts.append(f"{rem_hours} hour" + ("s" if rem_hours != 1 else ""))
    return " ".join(parts)

def estimate_activation_time(position: int | None, stats: dict):
    if position is None or position <= 0:
        return ("Active (not in queue)", "-", 0)
    vpe = max(int(stats.get("validators_per_epoch", DEFAULT_VALIDATORS_PER_EPOCH)), 1)
    epoch_min = int(stats.get("epoch_minutes", DEFAULT_EPOCH_MINUTES))
    epochs_wait = math.ceil((position - 1) / vpe)
    minutes_wait = epochs_wait * epoch_min
    now = datetime.now(WIB)
    eta_time = now + timedelta(minutes=minutes_wait)
    human = _format_days_hours_from_minutes(minutes_wait)
    return (human, eta_time.strftime('%d %b %Y, %H:%M WIB'), epochs_wait)

# ----------------- Status message (Main) -----------------
def format_full_status_message(data: dict, rank: int | str, score: float | str) -> str:
    if not data:
        return "Failed to get data."
    addr = data.get('address', '')
    short_addr = f"{addr[:6]}...{addr[-4:]}" if len(addr) > 10 else addr

    status_map = {"VALIDATING": "Validating ✅"}
    status = status_map.get(data.get('status', 'UNKNOWN').upper(), f"{data.get('status', 'Unknown')} ❓")

    try:
        score_formatted = f"{float(score):.2f}" if score != "N/A" else "N/A"
    except (ValueError, TypeError):
        score_formatted = score if score is not None else "N/A"

    try:
        balance = float(data.get('balance', 0)) / 1e18
        total_rewards = float(data.get('unclaimedRewards', 0)) / 1e18
    except (ValueError, TypeError):
        balance, total_rewards = 0.0, 0.0
    
    att_succeeded = int(data.get('totalAttestationsSucceeded', 0) or 0)
    att_missed = int(data.get('totalAttestationsMissed', 0) or 0)
    total_att = att_succeeded + att_missed
    att_rate = (att_succeeded / total_att * 100) if total_att > 0 else 0
    
    prop_proposed = int(data.get('totalBlocksProposed', 0) or 0)
    prop_mined = int(data.get('totalBlocksMined', 0) or 0)
    prop_succeeded = prop_proposed + prop_mined
    prop_missed = int(data.get('totalBlocksMissed', 0) or 0)
    total_prop = prop_succeeded + prop_missed
    prop_rate = (prop_succeeded / total_prop * 100) if total_prop > 0 else 0

    epoch_part = data.get('totalParticipatingEpochs', 'N/A')
    voting_history_count = len(data.get('votingHistory', []))
    timestamp = datetime.now(WIB).strftime('%d %b %Y, %H:%M:%S WIB')
    
    message = (
        f"👑 *Rank:* {rank}\n"
        f"🎯 *Score:* {score_formatted}\n"
        f"📊 *Validator:* `{short_addr}`\n"
        f"{status}\n\n"
        f"💰 *Balance:* {balance:.2f} STK\n"
        f"🏆 *Total Rewards:* {total_rewards:.2f} STK\n"
        f"-----------------------------------\n"
        f"✨ *Performance*\n\n"
        f"🛡️ *Attestation Rate:* {att_rate:.1f}%\n"
        f"    {att_succeeded} Succeeded / {att_missed} Missed\n\n"
        f"📦 *Block Proposal Rate:* {prop_rate:.1f}%\n"
        f"    {prop_succeeded} Proposed or Mined / {prop_missed}\n\n"
        f"🗓️ *Epoch Participation:* {epoch_part}\n"
        f"🗳️ *Voting Count:* {voting_history_count}\n"
        f"-----------------------------------\n"
        f"[Open on Dashboard](https://testnet.dashtec.xyz/validators/{addr})\n\n"
        f"🕒 *Last checked:* {timestamp}\n"
        f"-----------------------------------\n"
        f"Support me on [X](https://x.com/skyhazeed) | [Github](https://github.com/skyhazee)"
    )
    return message

# ----------------- Auto Notifications (attestation & proposal only) -----------------
def notify_attestations(bot: Bot, address: str, data: dict, state: dict):
    latest_sent = int(state.get("latest_attestation_slot", 0) or 0)
    atts = data.get('recentAttestations', []) or []

    try:
        atts_sorted = sorted(atts, key=lambda a: int(a.get('slot', 0) or 0))
    except Exception:
        atts_sorted = atts

    short_addr = f"{address[:6]}...{address[-4:]}"
    new_max = latest_sent

    for att in atts_sorted:
        slot = int(att.get('slot', 0) or 0)
        if slot <= latest_sent:
            continue

        status = att.get('status', 'N/A')
        if status == 'Success':
            title = "✍️ *Attestation Succeeded*"
        elif status == 'Missed':
            title = "⚠️ *Attestation Missed*"
        else:
            title = "ℹ️ *Attestation Update*"

        msg = f"{title}\nValidator: `{short_addr}` | Slot: `#{slot}`\nResult: {status}"
        bot.send_message(chat_id=AUTHORIZED_USER_ID, text=msg, parse_mode=ParseMode.MARKDOWN)

        if slot > new_max:
            new_max = slot

    state["latest_attestation_slot"] = new_max

def notify_proposals(bot: Bot, address: str, data: dict, state: dict):
    latest_sent = int(state.get("latest_proposal_slot", 0) or 0)
    props = data.get('proposalHistory', []) or []

    try:
        props_sorted = sorted(props, key=lambda p: int(p.get('slot', 0) or 0))
    except Exception:
        props_sorted = props

    short_addr = f"{address[:6]}...{address[-4:]}"
    new_max = latest_sent

    for prop in props_sorted:
        slot = int(prop.get('slot', 0) or 0)
        if slot <= latest_sent:
            continue

        status_prop = (prop.get('status') or '').lower()
        if status_prop == 'block-proposed':
            title = "📦 *Block Proposed*"
        elif status_prop == 'block-mined':
            title = "✅ *Block Mined*"
        elif status_prop == 'block-missed':
            title = "❌ *Block Missed*"
        else:
            title = "❓ *Block Update*"

        msg = f"{title}\nValidator: `{short_addr}` | Slot: `#{slot}`"
        bot.send_message(chat_id=AUTHORIZED_USER_ID, text=msg, parse_mode=ParseMode.MARKDOWN)

        if slot > new_max:
            new_max = slot

    state["latest_proposal_slot"] = new_max

def check_for_updates(bot: Bot):
    """
    Periodic check:
      - attestation notifications
      - proposal notifications
    No more 'Operator Activated' spam.
    """
    validators = load_validators()
    if not validators:
        return

    last_state = load_last_state()

    for address in validators:
        state = last_state.get(address, {
            "latest_attestation_slot": 0,
            "latest_proposal_slot": 0,
        })

        data = fetch_validator_data(address)
        if data:
            notify_attestations(bot, address, data, state)
            notify_proposals(bot, address, data, state)

        last_state[address] = state

    save_last_state(last_state)

# ----------------- Commands -----------------
@restricted
def start(update: Update, context: CallbackContext):
    update.message.reply_html(
        "Hi! 👋 This bot monitors your Aztec validators.\n\n"
        "<b>Quick tips</b>\n"
        f"• Use <b>/queue</b> to see queue position & ETA.\n"
        f"• Add your validator(s) with <b>/add &lt;address&gt;</b>.\n"
        f"• Check full stats anytime with <b>/check</b>.\n"
        f"• Polling interval: <b>{CHECK_INTERVAL_SECONDS}s</b> (configurable via CHECK_INTERVAL_SECONDS in .env)\n\n"
        "<b>Commands</b>\n"
        "/add <code>&lt;validator_address&gt;</code> – Add a validator to watch\n"
        "/remove <code>&lt;validator_address&gt;</code> – Remove a watched validator\n"
        "/list – List watched validators\n"
        "/check – Detailed validator status\n"
        "/queue [address] – Queue info & ETA (all or a single address)"
    )

@restricted
def add_validator(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text(
            "Usage: /add <validator_address>\n"
            "Tip: you can also check queue via /queue <address>."
        )
        return
    address = context.args[0].lower()
    if not (address.startswith("0x") and len(address) == 42):
        update.message.reply_text(
            "Invalid address format. It must start with '0x' and be 42 characters.\n"
            "Tip: try /queue <address> to look it up first."
        )
        return
    validators = load_validators()
    if address in validators:
        update.message.reply_text("This address is already being watched.")
    else:
        validators.append(address)
        save_validators(validators)
        update.message.reply_text("✅ Address added. I’ll watch it.\nYou can view queue info with /queue.")

@restricted
def list_validators(update: Update, context: CallbackContext):
    validators = load_validators()
    if not validators:
        update.message.reply_text(
            "No validators are being watched yet.\n"
            "Add one with /add <address> or check the queue via /queue <address>."
        )
        return
    message = "📜 *Watched Validators:*\n\n"
    for i, addr in enumerate(validators, 1):
        message += f"{i}. `{addr}`\n"
    message += "\nTip: use /queue [address] to see queue position & ETA."
    update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

@restricted
def remove_validator(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Usage: /remove <validator_address>")
        return
    address_to_remove = context.args[0].lower()
    validators = load_validators()
    last_state = load_last_state()
    if address_to_remove in validators:
        validators.remove(address_to_remove)
        if address_to_remove in last_state:
            del last_state[address_to_remove]
        save_validators(validators)
        save_last_state(last_state)
        update.message.reply_text("🗑️ Removed from watch list.")
    else:
        update.message.reply_text(
            "Address not found in your watch list.\n"
            "Tip: check queue via /queue <address>."
        )

@restricted
def check_status_command(update: Update, context: CallbackContext):
    validators_to_check = load_validators()
    if not validators_to_check:
        update.message.reply_text(
            "No validators to check.\n"
            "Add one with /add <address> or check queue via /queue <address>.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    update.message.reply_text(f"⏳ Checking {len(validators_to_check)} validators...")

    for i, address in enumerate(validators_to_check):
        if i > 0:
            time.sleep(0.5)
        rank, score = fetch_validator_rank_and_score(address)
        detail_data = fetch_validator_data(address)
        if detail_data:
            message = format_full_status_message(detail_data, rank, score)
            update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        else:
            update.message.reply_text(
                f"❌ Failed to fetch detailed data for `{address}`.\n"
                f"Tip: try /queue {address} to verify its queue status.",
                parse_mode=ParseMode.MARKDOWN
            )

@restricted
def queue_command(update: Update, context: CallbackContext):
    args = context.args
    stats = fetch_queue_stats()
    vpe = stats.get("validators_per_epoch", DEFAULT_VALIDATORS_PER_EPOCH)
    epm = stats.get("epoch_minutes", DEFAULT_EPOCH_MINUTES)

    if args:
        targets = []
        addr = args[0].lower()
        if not (addr.startswith("0x") and len(addr) == 42):
            update.message.reply_text("Invalid address. Usage: /queue <validator_address>")
            return
        targets.append(addr)
    else:
        targets = load_validators()
        if not targets:
            update.message.reply_text(
                "No watched validators.\n"
                "Add one with /add <address> or query directly: /queue <address>."
            )
            return

    lines = []
    now_str = datetime.now(WIB).strftime('%d %b %Y, %H:%M WIB')
    lines.append(
        f"⏱️ *Queue Overview*\n"
        f"• Validators/Epoch: *{vpe}*\n"
        f"• Epoch Duration: *{epm} minutes*\n"
        f"• As of: *{now_str}*"
    )

    for address in targets:
        q = fetch_queue_info(address)
        pos = q.get('position')
        status = (q.get('status') or "-")

        eta_text, eta_ts, epochs_wait = estimate_activation_time(pos, stats)

        short_addr = f"{address[:6]}...{address[-4:]}"
        if status == "not-in-queue":
            status_disp = "active (not in queue)"
        elif status == "in-queue":
            status_disp = "in queue"
        else:
            status_disp = status or "-"

        block = (
            f"\n*{short_addr}*\n"
            f"• Position       : *{pos if pos is not None else '-'}*\n"
            f"• Status         : *{status_disp}*\n"
            f"• ETA            : *{eta_text}*"
            + (f" — (≈ {eta_ts}, ~{epochs_wait} epoch{'s' if epochs_wait != 1 else ''})" if eta_ts != "-" else "")
        )
        lines.append(block)

    lines.append("\nSource: testnet.dashtec.xyz/queue")
    update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

# ----------------- Main -----------------
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set. Please configure .env.")
        return
    
    request_kwargs = {'connect_timeout': 15.0, 'read_timeout': 15.0}
    updater = Updater(BOT_TOKEN, use_context=True, request_kwargs=request_kwargs)
    dispatcher = updater.dispatcher
    bot = dispatcher.bot

    logger.info("Initializing notification baseline...")
    check_for_updates(bot)
    logger.info(f"Initialization done. Poll interval = {CHECK_INTERVAL_SECONDS}s")

    scheduler = BackgroundScheduler(timezone=WIB)
    scheduler.add_job(
        check_for_updates,
        'interval',
        seconds=CHECK_INTERVAL_SECONDS,
        args=[bot],
        id="update_check_job",
        max_instances=1,
        coalesce=True
    )
    scheduler.start()

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("add", add_validator))
    dispatcher.add_handler(CommandHandler("list", list_validators))
    dispatcher.add_handler(CommandHandler("remove", remove_validator))
    dispatcher.add_handler(CommandHandler("check", check_status_command))
    dispatcher.add_handler(CommandHandler("queue", queue_command))
    dispatcher.add_handler(CommandHandler("Queue", queue_command))  # alias

    updater.start_polling(drop_pending_updates=True)
    logger.info("Bot running. Ready for commands.")
    updater.idle()

if __name__ == '__main__':
    main()
