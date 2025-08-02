import os
import json
import logging
from datetime import datetime, timedelta
from functools import wraps

import cloudscraper
import pytz # <-- Import library untuk zona waktu
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

# --- Variabel Global & Konstanta ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
try:
    AUTHORIZED_USER_ID = int(os.getenv("TELEGRAM_ID"))
except (ValueError, TypeError):
    logger.error("TELEGRAM_ID tidak valid atau tidak ditemukan di .env file.")
    exit()

VALIDATORS_FILE = "validators.json"
LAST_STATE_FILE = "last_state.json"
API_URL_DETAIL = "https://dashtec.xyz/api/validators/{}"
API_URL_LIST = "https://dashtec.xyz/api/validators?"
WIB = pytz.timezone('Asia/Jakarta') # <-- Atur zona waktu WIB

# --- Konfigurasi Caching untuk Peringkat ---
CACHE_DURATION_SECONDS = 900  # 15 menit
ALL_VALIDATORS_CACHE = None
CACHE_EXPIRATION_TIME = None

# Buat instance scraper yang akan kita gunakan kembali
scraper = cloudscraper.create_scraper()

# --- Dekorator untuk Otorisasi ---
def restricted(func):
    """Membatasi penggunaan command hanya untuk user yang diizinkan."""
    @wraps(func)
    def wrapped(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != AUTHORIZED_USER_ID:
            logger.warning(f"Akses tidak sah ditolak untuk {user_id}.")
            update.message.reply_text("⛔ Anda tidak diizinkan menggunakan bot ini.")
            return
        return func(update, context, *args, **kwargs)
    return wrapped

# --- Fungsi Helper untuk Mengelola File JSON ---
def load_validators():
    try:
        with open(VALIDATORS_FILE, 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return []

def save_validators(validators):
    with open(VALIDATORS_FILE, 'w') as f: json.dump(validators, f, indent=4)

def load_last_state():
    try:
        with open(LAST_STATE_FILE, 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return {}

def save_last_state(state):
    with open(LAST_STATE_FILE, 'w') as f: json.dump(state, f, indent=4)

# --- Fungsi Pengambilan Data ---
def fetch_validator_data(address: str):
    """Mengambil data detail untuk satu validator."""
    try:
        response = scraper.get(API_URL_DETAIL.format(address), timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Gagal mengambil data detail untuk {address}: {e}")
        return None

def fetch_all_validators_with_cache():
    """Mengambil daftar semua validator menggunakan mekanisme cache."""
    global ALL_VALIDATORS_CACHE, CACHE_EXPIRATION_TIME
    if ALL_VALIDATORS_CACHE and datetime.now() < CACHE_EXPIRATION_TIME:
        logger.info("Menggunakan daftar validator dari cache.")
        return ALL_VALIDATORS_CACHE
    logger.info("Cache kosong atau kedaluwarsa. Mengambil daftar validator baru.")
    try:
        response = scraper.get(API_URL_LIST, timeout=30)
        response.raise_for_status()
        data = response.json()
        ALL_VALIDATORS_CACHE = data
        CACHE_EXPIRATION_TIME = datetime.now() + timedelta(seconds=CACHE_DURATION_SECONDS)
        logger.info(f"Cache berhasil diperbarui.")
        return data
    except Exception as e:
        logger.error(f"Gagal mengambil daftar semua validator: {e}")
        return None

# --- Fungsi Pemformatan Pesan untuk /check ---
def format_full_status_message(data: dict, rank: int | str):
    """Memformat pesan status lengkap untuk perintah /check."""
    if not data: return "Gagal mengambil data."
    addr = data.get('address', 'N/A')
    short_addr = f"{addr[:6]}...{addr[-4:]}" if len(addr) > 10 else addr
    status_map = {"VALIDATING": "Validating ✅"}
    status = status_map.get(data.get('status', 'UNKNOWN').upper(), f"{data.get('status', 'Unknown')} ❓")
    try:
        balance = float(data.get('balance', 0)) / 1e18
        total_rewards = float(data.get('unclaimedRewards', 0)) / 1e18
    except (ValueError, TypeError): balance, total_rewards = 0.0, 0.0
    
    att_succeeded = data.get('totalAttestationsSucceeded', 0)
    att_missed = data.get('totalAttestationsMissed', 0)
    total_att = att_succeeded + att_missed
    att_rate = (att_succeeded / total_att * 100) if total_att > 0 else 0
    
    # --- PERUBAHAN DI SINI ---
    prop_proposed = data.get('totalBlocksProposed', 0)
    prop_mined = data.get('totalBlocksMined', 0)
    prop_succeeded = prop_proposed + prop_mined # Menjumlahkan proposed dan mined
    prop_missed = data.get('totalBlocksMissed', 0)
    total_prop = prop_succeeded + prop_missed
    prop_rate = (prop_succeeded / total_prop * 100) if total_prop > 0 else 0
    # --- AKHIR PERUBAHAN ---

    epoch_part = data.get('totalParticipatingEpochs', 'N/A')
    timestamp = datetime.now(WIB).strftime('%d %b %Y, %H:%M:%S WIB')
    
    message = (
        f"👑 *Rank:* {rank}\n"
        f"📊 *Status Validator:* `{short_addr}`\n"
        f"{status}\n\n"
        f"💰 *Saldo:* {balance:.2f} STK\n"
        f"🏆 *Total Rewards:* {total_rewards:.2f} STK\n"
        f"-----------------------------------\n"
        f"✨ *Performance Metrics*\n\n"
        f"🛡️ *Attestation Rate:* {att_rate:.1f}%\n"
        f"    {att_succeeded} Succeeded / {att_missed} Missed\n\n"
        f"📦 *Block Proposal Rate:* {prop_rate:.1f}%\n"
        f"    {prop_succeeded} Proposed or Mined / {prop_missed} Missed\n\n" # Label diperbarui
        f"🗓️ *Epoch Participation:* {epoch_part}\n"
    )
    voting_history = data.get('votingHistory', [])
    if voting_history:
        message += f"\n🗳️ *Voting History*\n"
        for vote in voting_history:
            message += f"    • {vote.get('info', 'N/A')}: {vote.get('status', 'N/A')}\n"
    message += f"-----------------------------------\n🕒 *Terakhir dicek:* {timestamp}"
    return message

# --- Logika Notifikasi Otomatis ---
def check_for_updates(context: CallbackContext):
    bot = context.bot
    validators = load_validators()
    last_state = load_last_state()
    if not validators: return
    logger.info(f"Memulai pengecekan otomatis untuk notifikasi...")
    for address in validators:
        data = fetch_validator_data(address)
        if not data: continue
        addr_short = f"{address[:6]}...{address[-4:]}"
        if address not in last_state:
            last_state[address] = {"latest_attestation_slot": 0, "latest_proposal_slot": 0}
        state = last_state[address]
        # Cek Atestasi Baru
        latest_notified_att = state.get("latest_attestation_slot", 0)
        max_new_att = latest_notified_att
        for att in data.get('recentAttestations', []):
            if att.get('slot', 0) > latest_notified_att:
                bot.send_message(chat_id=AUTHORIZED_USER_ID, text=f"✍️ *Atestasi Sukses*\nValidator: `{addr_short}` | Slot: `#{att.get('slot')}`\nHasil: {att.get('status', 'N/A')}", parse_mode=ParseMode.MARKDOWN)
                if att.get('slot', 0) > max_new_att: max_new_att = att.get('slot')
        state["latest_attestation_slot"] = max_new_att
        # Cek Proposal Blok Baru
        latest_notified_prop = state.get("latest_proposal_slot", 0)
        max_new_prop = latest_notified_prop
        for prop in data.get('proposalHistory', []):
            if prop.get('slot', 0) > latest_notified_prop:
                bot.send_message(chat_id=AUTHORIZED_USER_ID, text=f"✅ *Proposal Blok Sukses!*\nValidator: `{addr_short}` | Slot: `#{prop.get('slot')}`\nStatus: {prop.get('status', 'N/A').upper()}", parse_mode=ParseMode.MARKDOWN)
                if prop.get('slot', 0) > max_new_prop: max_new_prop = prop.get('slot')
        state["latest_proposal_slot"] = max_new_prop
    save_last_state(last_state)
    logger.info("Pengecekan notifikasi selesai.")

# --- Command Handlers ---
@restricted
def start(update: Update, context: CallbackContext):
    update.message.reply_html(
        "Halo! 👋 Bot ini sekarang memiliki dua fungsi:\n\n"
        "1️⃣ <b>Notifikasi Otomatis:</b> Saya akan memberitahu Anda jika ada atestasi atau proposal blok baru.\n"
        "2️⃣ <b>Pengecekan Manual:</b> Gunakan /check untuk melihat status lengkap validator Anda kapan saja.\n\n"
        "Perintah lain: /add, /list, /remove."
    )

@restricted
def add_validator(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Gunakan format: /add <alamat_validator>")
        return
    address = context.args[0].lower()
    if not (address.startswith("0x") and len(address) == 42):
        update.message.reply_text("Format alamat tidak valid.")
        return
    validators = load_validators()
    if address in validators:
        update.message.reply_text("Alamat ini sudah ada dalam daftar.")
    else:
        validators.append(address)
        save_validators(validators)
        update.message.reply_text(f"✅ Alamat berhasil ditambahkan dan akan dipantau.")

@restricted
def list_validators(update: Update, context: CallbackContext):
    validators = load_validators()
    if not validators:
        update.message.reply_text("Daftar pantau kosong.")
        return
    message = "📜 *Daftar Validator Tersimpan:*\n\n"
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
    if address_to_remove in validators:
        validators.remove(address_to_remove)
        save_validators(validators)
        update.message.reply_text(f"🗑️ Alamat berhasil dihapus.")
    else:
        update.message.reply_text("Alamat tidak ditemukan dalam daftar.")

@restricted
def check_status_command(update: Update, context: CallbackContext):
    """Handler untuk perintah /check."""
    validators_to_check = load_validators()
    if not validators_to_check:
        update.message.reply_text("Tidak ada validator untuk diperiksa. Tambahkan dengan `/add`.")
        return
    update.message.reply_text(f"⏳ Mengambil data peringkat... (menggunakan cache jika tersedia)")
    all_validators_data = fetch_all_validators_with_cache()
    if not all_validators_data:
        update.message.reply_text("❌ Gagal mengambil daftar validator dari API.")
        return
    all_validators_list = all_validators_data.get('validators', [])
    if not all_validators_list:
        update.message.reply_text("❌ Tidak menemukan daftar validator di dalam data API.")
        return
    update.message.reply_text(f"✅ Data peringkat siap. Memeriksa status untuk {len(validators_to_check)} validator Anda...")
    for address in validators_to_check:
        rank = "N/A"
        for validator_summary in all_validators_list:
            if validator_summary.get('address', '').lower() == address.lower():
                rank = validator_summary.get('rank', 'N/A')
                break
        detail_data = fetch_validator_data(address)
        if detail_data:
            message = format_full_status_message(detail_data, rank)
            update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        else:
            update.message.reply_text(f"❌ Gagal mendapatkan data detail untuk `{address}`.", parse_mode=ParseMode.MARKDOWN)

# --- Fungsi Utama ---
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN tidak ditemukan. Harap atur di file .env.")
        return
    updater = Updater(BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    
    # Jalankan pengecekan awal untuk menetapkan status dasar notifikasi
    logger.info("Menjalankan pengecekan awal untuk notifikasi...")
    check_for_updates(CallbackContext(dispatcher))
    logger.info("Status dasar notifikasi telah ditetapkan.")
    
    # Siapkan penjadwal untuk pengecekan otomatis
    scheduler = BackgroundScheduler(timezone="Asia/Jakarta")
    scheduler.add_job(check_for_updates, 'interval', seconds=60, args=[CallbackContext(dispatcher)])
    scheduler.start()
    
    # Daftarkan semua command handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("add", add_validator))
    dispatcher.add_handler(CommandHandler("list", list_validators))
    dispatcher.add_handler(CommandHandler("remove", remove_validator))
    dispatcher.add_handler(CommandHandler("check", check_status_command)) # Tambahkan kembali /check
    
    updater.start_polling()
    logger.info("Bot berhasil dijalankan dengan notifikasi otomatis dan perintah /check!")
    updater.idle()

if __name__ == '__main__':
    main()
