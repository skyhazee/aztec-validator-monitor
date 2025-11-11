# -*- coding: utf-8 -*-
import os
import json
import logging
from datetime import datetime, timedelta
from functools import wraps
import time
import math

import cloudscraper
import pytz
from dotenv import load_dotenv
from telegram import Update, ParseMode, Bot
from telegram.ext import Updater, CommandHandler, CallbackContext
from apscheduler.schedulers.background import BackgroundScheduler

# --- Konfigurasi Awal ---
load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
try:
    AUTHORIZED_USER_ID = int(os.getenv("TELEGRAM_ID"))
except (ValueError, TypeError):
    logger.error("TELEGRAM_ID tidak valid atau tidak ditemukan di file .env.")
    exit()

VALIDATORS_FILE = "validators.json"
LAST_STATE_FILE = "last_state.json"

# API utama (validator) & testnet queue
API_URL_DETAIL = "https://dashtec.xyz/api/validators/{}"
API_URL_LIST = "https://dashtec.xyz/api/validators?"

QUEUE_API_URL = "https://testnet.dashtec.xyz/api/sequencers/queue"
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

# ----------------- Utils State & Auth -----------------
def restricted(func):
    @wraps(func)
    def wrapped(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != AUTHORIZED_USER_ID:
            logger.warning(f"Akses tidak sah ditolak untuk user ID: {user_id}.")
            if update.message:
                update.message.reply_text("⛔ Anda tidak diizinkan menggunakan bot ini.")
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
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def load_validators():
    return load_json_file(VALIDATORS_FILE, [])

def save_validators(validators):
    save_json_file(VALIDATORS_FILE, validators)

def load_last_state():
    return load_json_file(LAST_STATE_FILE, {})

def save_last_state(state):
    save_json_file(LAST_STATE_FILE, state)

# ----------------- API Main Validator -----------------
def fetch_validator_data(address: str):
    try:
        headers = BROWSER_HEADERS.copy()
        headers['referer'] = f"https://dashtec.xyz/validators/{address}"
        response = scraper.get(API_URL_DETAIL.format(address), timeout=30, headers=headers)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Gagal ambil detail {address}: {e}")
        return None

def fetch_validator_rank_and_score(address: str):
    try:
        headers = BROWSER_HEADERS.copy()
        headers['referer'] = 'https://dashtec.xyz/validators'
        search_url = f"{API_URL_LIST}search={address}"
        response = scraper.get(search_url, timeout=30, headers=headers)
        response.raise_for_status()
        data = response.json()
        validators_list = data.get('validators', []) or data.get('data', []) or []
        if not validators_list:
            logger.warning(f"Validator {address} tidak ditemukan via search API.")
            return "N/A", "N/A"
        validator_info = validators_list[0]
        rank = validator_info.get('rank', 'N/A')
        score = validator_info.get('performanceScore', 'N/A')
        return rank, score
    except Exception as e:
        logger.error(f"Gagal ambil rank/score {address}: {e}")
        return "N/A", "N/A"

# ----------------- API Queue (Testnet) -----------------
def fetch_queue_stats():
    try:
        headers = BROWSER_HEADERS.copy()
        headers['referer'] = 'https://testnet.dashtec.xyz/queue'
        r = scraper.get(QUEUE_STATS_URL, headers=headers, timeout=20)
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
        try:
            epoch_minutes = int(epoch_minutes)
        except Exception:
            epoch_minutes = DEFAULT_EPOCH_MINUTES
        try:
            validators_per_epoch = int(validators_per_epoch)
        except Exception:
            validators_per_epoch = DEFAULT_VALIDATORS_PER_EPOCH
        return {"epoch_minutes": epoch_minutes, "validators_per_epoch": validators_per_epoch}
    except Exception as e:
        logger.warning(f"Gagal fetch queue stats, pakai default: {e}")
        return {"epoch_minutes": DEFAULT_EPOCH_MINUTES, "validators_per_epoch": DEFAULT_VALIDATORS_PER_EPOCH}

def _match_address(item: dict, addr_lower: str) -> bool:
    # Coba beberapa field kandidat alamat/operator
    for key in ("address", "operator", "validator", "sequencer", "wallet"):
        val = (item.get(key) or "")
        if isinstance(val, str) and val.lower() == addr_lower:
            return True
    return False

def fetch_queue_info(address: str):
    """
    Menyusuri banyak halaman queue untuk menemukan posisi & status.
    return: {'position': int|None, 'status': str|None, 'raw': dict, 'found': bool}
    """
    try:
        headers = BROWSER_HEADERS.copy()
        headers['referer'] = 'https://testnet.dashtec.xyz/queue'

        addr_lower = address.lower()
        limit = 100
        max_pages = 30  # amannya

        # Pertama: pakai search langsung
        params = {"page": 1, "limit": 10, "search": address}
        r = scraper.get(QUEUE_API_URL, headers=headers, params=params, timeout=20)
        r.raise_for_status()
        data = r.json() if r.text else {}
        items = None
        for key in ('items', 'data', 'validators', 'queue', 'results'):
            if isinstance(data.get(key), list):
                items = data[key]
                break
        if items is None and isinstance(data, list):
            items = data

        if items:
            for it in items:
                if _match_address(it, addr_lower):
                    position = it.get('position') or it.get('queuePosition') or it.get('index') or it.get('rank')
                    try:
                        position = int(position)
                    except Exception:
                        position = None
                    status = (it.get('status') or it.get('state') or it.get('activationStatus') or '').strip()
                    return {"position": position, "status": status, "raw": it, "found": True}

        # Kedua: tanpa search, sapu halaman (limit besar)
        for page in range(1, max_pages + 1):
            params = {"page": page, "limit": limit}
            r = scraper.get(QUEUE_API_URL, headers=headers, params=params, timeout=25)
            if r.status_code != 200:
                break
            data = r.json() if r.text else {}
            list_candidates = None
            for key in ('items', 'data', 'validators', 'queue', 'results'):
                if isinstance(data.get(key), list):
                    list_candidates = data[key]
                    break
            if list_candidates is None and isinstance(data, list):
                list_candidates = data

            if not list_candidates:
                break

            # Jika API tidak memberi position langsung, asumsikan urutan = index global
            for idx, it in enumerate(list_candidates):
                if _match_address(it, addr_lower):
                    # Hitung posisi global jika tidak tersedia
                    position = it.get('position') or it.get('queuePosition') or it.get('rank') or it.get('index')
                    if position is None:
                        position = (page - 1) * limit + (idx + 1)
                    try:
                        position = int(position)
                    except Exception:
                        position = None
                    status = (it.get('status') or it.get('state') or it.get('activationStatus') or '').strip()
                    return {"position": position, "status": status, "raw": it, "found": True}

        # Tidak ditemukan di seluruh halaman -> diasumsikan tidak dalam antrian (aktif)
        return {"position": None, "status": "not-in-queue", "raw": {}, "found": False}

    except Exception as e:
        logger.error(f"Gagal fetch queue {address}: {e}")
        return {"position": None, "status": None, "raw": {}, "found": False}

def estimate_activation_time(position: int | None, stats: dict):
    if position is None or position <= 0:
        return ("Aktif (tidak dalam antrian)", "-")
    vpe = stats.get("validators_per_epoch", DEFAULT_VALIDATORS_PER_EPOCH)
    epoch_min = stats.get("epoch_minutes", DEFAULT_EPOCH_MINUTES)
    epochs_wait = math.ceil((position - 1) / max(vpe, 1))
    minutes_wait = epochs_wait * epoch_min
    now = datetime.now(WIB)
    eta_time = now + timedelta(minutes=minutes_wait)
    return (f"~{minutes_wait} menit ({epochs_wait} epoch)", eta_time.strftime('%d %b %Y, %H:%M WIB'))

# ----------------- Format Status (Main) -----------------
def format_full_status_message(data: dict, rank: int | str, score: float | str) -> str:
    if not data:
        return "Gagal mengambil data."

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
    
    att_succeeded = data.get('totalAttestationsSucceeded', 0)
    att_missed = data.get('totalAttestationsMissed', 0)
    total_att = att_succeeded + att_missed
    att_rate = (att_succeeded / total_att * 100) if total_att > 0 else 0
    
    prop_proposed = data.get('totalBlocksProposed', 0)
    prop_mined = data.get('totalBlocksMined', 0)
    prop_succeeded = prop_proposed + prop_mined
    prop_missed = data.get('totalBlocksMissed', 0)
    total_prop = prop_succeeded + prop_missed
    prop_rate = (prop_succeeded / total_prop * 100) if total_prop > 0 else 0

    epoch_part = data.get('totalParticipatingEpochs', 'N/A')
    voting_history_count = len(data.get('votingHistory', []))
    timestamp = datetime.now(WIB).strftime('%d %b %Y, %H:%M:%S WIB')
    
    message = (
        f"👑 *Rank:* {rank}\n"
        f"🎯 *Score:* {score_formatted}\n"
        f"📊 *Status Validator:* `{short_addr}`\n"
        f"{status}\n\n"
        f"💰 *Saldo:* {balance:.2f} STK\n"
        f"🏆 *Total Rewards:* {total_rewards:.2f} STK\n"
        f"-----------------------------------\n"
        f"✨ *Performance Metrics*\n\n"
        f"🛡️ *Attestation Rate:* {att_rate:.1f}%\n"
        f"    {att_succeeded} Succeeded / {att_missed} Missed\n\n"
        f"📦 *Block Proposal Rate:* {prop_rate:.1f}%\n"
        f"    {prop_succeeded} Proposed or Mined / {prop_missed} Missed\n\n"
        f"🗓️ *Epoch Participation:* {epoch_part}\n"
        f"🗳️ *Jumlah Voting:* {voting_history_count}\n"
        f"-----------------------------------\n"
        f"[Go to Validator Dashboard](https://dashtec.xyz/validators/{addr})\n\n"
        f"🕒 *Terakhir dicek:* {timestamp}\n"
        f"-----------------------------------\n"
        f"Support me on [X](https://x.com/skyhazeed) | [Github](https://github.com/skyhazee)"
    )
    return message

# ----------------- Notifikasi Otomatis -----------------
def check_for_updates(bot: Bot):
    """
    Attestation/Proposal (mainnet dashboard) + Queue Activation (testnet).
    Anti-false-positive: butuh 2 konfirmasi berturut-turut sebelum notif activated.
    """
    validators = load_validators()
    last_state = load_last_state()
    if not validators:
        return
    
    logger.info("Pengecekan otomatis dimulai...")
    queue_stats = fetch_queue_stats()

    for address in validators:
        state = last_state.get(address, {
            "latest_attestation_slot": 0,
            "latest_proposal_slot": 0,
            "queue_position": None,
            "activated_notified": False,
            "activation_confirmations": 0  # butuh 2 kali berturut-turut
        })

        # --- 1) Validator main data ---
        data = fetch_validator_data(address)
        if data:
            # Attestation
            latest_notified_att = state.get("latest_attestation_slot", 0)
            max_new_att = latest_notified_att
            for att in data.get('recentAttestations', []):
                slot = att.get('slot', 0)
                if slot > latest_notified_att:
                    status = att.get('status', 'N/A')
                    if status == 'Success':
                        title = "✍️ *Atestasi Sukses*"
                    elif status == 'Missed':
                        title = "⚠️ *Atestasi Terlewat*"
                    else:
                        title = "ℹ️ *Update Atestasi*"
                    short_addr = f"{address[:6]}...{address[-4:]}"
                    msg = f"{title}\nValidator: `{short_addr}` | Slot: `#{slot}`\nHasil: {status}"
                    bot.send_message(chat_id=AUTHORIZED_USER_ID, text=msg, parse_mode=ParseMode.MARKDOWN)
                    if slot > max_new_att:
                        max_new_att = slot
            state["latest_attestation_slot"] = max_new_att

            # Proposal
            latest_notified_prop = state.get("latest_proposal_slot", 0)
            max_new_prop = latest_notified_prop
            for prop in data.get('proposalHistory', []):
                slot = prop.get('slot', 0)
                if slot > latest_notified_prop:
                    status_prop = (prop.get('status') or '').lower()
                    short_addr = f"{address[:6]}...{address[-4:]}"
                    if status_prop == 'block-proposed':
                        title = "📦 *Blok Berhasil Diajukan*"
                    elif status_prop == 'block-mined':
                        title = "✅ *Blok Berhasil di-Mine*"
                    elif status_prop == 'block-missed':
                        title = "❌ *Proposal Blok Terlewat*"
                    else:
                        logger.warning(f"Status proposal tidak dikenal: '{prop.get('status')}' untuk {short_addr}")
                        title = "❓ *Update Proposal Blok*"
                    msg = f"{title}!\nValidator: `{short_addr}` | Slot: `#{slot}`"
                    bot.send_message(chat_id=AUTHORIZED_USER_ID, text=msg, parse_mode=ParseMode.MARKDOWN)
                    if slot > max_new_prop:
                        max_new_prop = slot
            state["latest_proposal_slot"] = max_new_prop

        # --- 2) Queue Activation Check ---
        qinfo = fetch_queue_info(address)
        position = qinfo.get('position')
        q_status = (qinfo.get('status') or '').lower()

        # Kondisi dianggap "aktif/keluar antrian"
        is_active_like = False
        if q_status in ('active', 'activated', 'validating', 'online', 'not-in-queue'):
            is_active_like = True
        elif position is None:
            is_active_like = True

        if is_active_like:
            state["activation_confirmations"] = state.get("activation_confirmations", 0) + 1
        else:
            state["activation_confirmations"] = 0
            state["activated_notified"] = False  # reset kalau balik ke antrian

        # Kirim notifikasi hanya saat pertama kali confirmed 2x dan belum pernah notif
        if state["activation_confirmations"] >= 2 and not state.get("activated_notified", False):
            short_addr = f"{address[:6]}...{address[-4:]}"
            bot.send_message(
                chat_id=AUTHORIZED_USER_ID,
                text=f"🎉 *Operator Activated!*\nValidator: `{short_addr}` sudah aktif / keluar dari queue.",
                parse_mode=ParseMode.MARKDOWN
            )
            state["activated_notified"] = True

        state["queue_position"] = position
        last_state[address] = state

    save_last_state(last_state)
    logger.info("Pengecekan otomatis selesai.")

# ----------------- Commands -----------------
@restricted
def start(update: Update, context: CallbackContext):
    update.message.reply_html(
        "Halo! 👋 Bot ini memonitor validator Aztec Anda.\n\n"
        "<b>Fitur Utama:</b>\n"
        "1️⃣ <b>Notifikasi Otomatis:</b> Atestasi, proposal blok, dan aktivasi dari queue.\n"
        "2️⃣ <b>Pengecekan Manual:</b> /check (status lengkap), /queue (info antrian).\n\n"
        "<b>Perintah:</b>\n"
        "/add <code>&lt;alamat_validator&gt;</code> – Tambah pantauan\n"
        "/remove <code>&lt;alamat_validator&gt;</code> – Hapus pantauan\n"
        "/list – Daftar validator yang dipantau\n"
        "/check – Status lengkap validator\n"
        "/queue [alamat] – Info antrian & estimasi aktivasi (bisa satu alamat)"
    )

@restricted
def add_validator(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Gunakan format: /add <alamat_validator>")
        return
    address = context.args[0].lower()
    if not (address.startswith("0x") and len(address) == 42):
        update.message.reply_text("Format alamat tidak valid. Harus diawali '0x' dan 42 karakter.")
        return
    validators = load_validators()
    if address in validators:
        update.message.reply_text("Alamat ini sudah ada dalam daftar pantau.")
    else:
        validators.append(address)
        save_validators(validators)
        update.message.reply_text("✅ Alamat berhasil ditambahkan dan akan dipantau.")

@restricted
def list_validators(update: Update, context: CallbackContext):
    validators = load_validators()
    if not validators:
        update.message.reply_text("Daftar pantau kosong. Tambahkan validator dengan perintah /add.")
        return
    message = "📜 *Daftar Validator yang Dipantau:*\n\n"
    for i, addr in enumerate(validators, 1):
        message += f"{i}. `{addr}`\n"
    update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

@restricted
def remove_validator(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Gunakan format: /remove <alamat_validator>")
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
        update.message.reply_text("🗑️ Alamat berhasil dihapus dari daftar pantau.")
    else:
        update.message.reply_text("Alamat tidak ditemukan dalam daftar.")

@restricted
def check_status_command(update: Update, context: CallbackContext):
    validators_to_check = load_validators()
    if not validators_to_check:
        update.message.reply_text("Tidak ada validator untuk diperiksa. Tambahkan dengan `/add`.", parse_mode=ParseMode.MARKDOWN)
        return
    
    update.message.reply_text(f"⏳ Memeriksa status untuk {len(validators_to_check)} validator Anda...")

    for i, address in enumerate(validators_to_check):
        if i > 0:
            time.sleep(1)
        rank, score = fetch_validator_rank_and_score(address)
        detail_data = fetch_validator_data(address)
        if detail_data:
            message = format_full_status_message(detail_data, rank, score)
            update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        else:
            update.message.reply_text(f"❌ Gagal mendapatkan data detail untuk `{address}`.", parse_mode=ParseMode.MARKDOWN)

@restricted
def queue_command(update: Update, context: CallbackContext):
    """
    /queue [alamat]
    - tanpa argumen: cek semua validator di daftar pantau
    - dengan argumen: cek alamat tertentu saja
    """
    args = context.args
    stats = fetch_queue_stats()
    vpe = stats.get("validators_per_epoch", DEFAULT_VALIDATORS_PER_EPOCH)
    epm = stats.get("epoch_minutes", DEFAULT_EPOCH_MINUTES)

    targets = []
    if args:
        addr = args[0].lower()
        if not (addr.startswith("0x") and len(addr) == 42):
            update.message.reply_text("Format alamat tidak valid. Gunakan: /queue <alamat_validator>")
            return
        targets = [addr]
    else:
        targets = load_validators()
        if not targets:
            update.message.reply_text("Daftar pantau kosong. Tambahkan validator dengan perintah /add.")
            return

    lines = []
    lines.append(f"⏱️ *Queue Overview* (validators/epoch: {vpe}, epoch: {epm} menit)")

    for address in targets:
        q = fetch_queue_info(address)
        pos = q.get('position')
        status = (q.get('status') or "-")
        eta_str, eta_ts = estimate_activation_time(pos, stats)
        short_addr = f"{address[:6]}...{address[-4:]}"
        if status == "not-in-queue":
            status_disp = "aktif (tidak di antrian)"
        else:
            status_disp = status if status else "-"

        block = (
            f"\n• `{short_addr}`\n"
            f"   Posisi: *{pos if pos is not None else '-'}*\n"
            f"   Status: *{status_disp}*\n"
            f"   Est. Aktivasi: *{eta_str}*"
            + (f" (≈ {eta_ts})" if eta_ts != "-" else "")
        )
        lines.append(block)

    lines.append("\nSumber: testnet.dashtec.xyz/queue")
    update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

# ----------------- Main -----------------
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN tidak ditemukan. Harap atur di file .env.")
        return
    
    request_kwargs = {'connect_timeout': 20.0, 'read_timeout': 20.0}
    updater = Updater(BOT_TOKEN, use_context=True, request_kwargs=request_kwargs)
    dispatcher = updater.dispatcher
    bot = dispatcher.bot

    # Inisialisasi state (sekali di awal)
    logger.info("Inisialisasi status notifikasi awal...")
    check_for_updates(bot)
    logger.info("Inisialisasi selesai.")

    # Scheduler: cek otomatis tiap 60 detik
    scheduler = BackgroundScheduler(timezone=WIB)
    scheduler.add_job(check_for_updates, 'interval', seconds=60, args=[bot], id="update_check_job", max_instances=1, coalesce=True)
    scheduler.start()

    # Commands
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("add", add_validator))
    dispatcher.add_handler(CommandHandler("list", list_validators))
    dispatcher.add_handler(CommandHandler("remove", remove_validator))
    dispatcher.add_handler(CommandHandler("check", check_status_command))
    dispatcher.add_handler(CommandHandler("queue", queue_command))
    dispatcher.add_handler(CommandHandler("Queue", queue_command))  # alias

    updater.start_polling()
    logger.info("Bot berjalan. Siap menerima perintah.")
    updater.idle()

if __name__ == '__main__':
    main()
