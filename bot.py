# -*- coding: utf-8 -*-
import os
import json
import logging
from datetime import datetime, timedelta
from functools import wraps

import cloudscraper
import pytz
from dotenv import load_dotenv
from telegram import Update, ParseMode, Bot
from telegram.ext import Updater, CommandHandler, CallbackContext
from apscheduler.schedulers.background import BackgroundScheduler

# --- Konfigurasi Awal ---
# Memuat variabel dari file .env
load_dotenv()

# Mengatur logging untuk memantau aktivitas bot
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Variabel Global & Konstanta ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
try:
    # Pastikan TELEGRAM_ID adalah integer
    AUTHORIZED_USER_ID = int(os.getenv("TELEGRAM_ID"))
except (ValueError, TypeError):
    logger.error("TELEGRAM_ID tidak valid atau tidak ditemukan di file .env.")
    exit()

# Nama file untuk menyimpan data
VALIDATORS_FILE = "validators.json"
LAST_STATE_FILE = "last_state.json"

# URL API
API_URL_DETAIL = "https://dashtec.xyz/api/validators/{}"
API_URL_LIST = "https://dashtec.xyz/api/validators?"

# Zona Waktu (Waktu Indonesia Barat)
WIB = pytz.timezone('Asia/Jakarta')

# --- Konfigurasi Caching untuk Peringkat ---
CACHE_DURATION_SECONDS = 900  # 15 menit
ALL_VALIDATORS_CACHE = None
CACHE_EXPIRATION_TIME = None

# Buat instance scraper yang akan digunakan kembali untuk melewati proteksi Cloudflare
scraper = cloudscraper.create_scraper()

# --- Dekorator untuk Otorisasi ---
def restricted(func):
    """Membatasi penggunaan command hanya untuk user yang diizinkan."""
    @wraps(func)
    def wrapped(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != AUTHORIZED_USER_ID:
            logger.warning(f"Akses tidak sah ditolak untuk user ID: {user_id}.")
            update.message.reply_text("⛔ Anda tidak diizinkan menggunakan bot ini.")
            return
        return func(update, context, *args, **kwargs)
    return wrapped

# --- Fungsi Helper untuk Mengelola File JSON ---
def load_json_file(filename: str, default_value=None):
    """Fungsi generik untuk memuat data dari file JSON."""
    if default_value is None:
        default_value = []
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_value

def save_json_file(filename: str, data):
    """Fungsi generik untuk menyimpan data ke file JSON."""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

# Menggunakan fungsi generik untuk file spesifik
def load_validators():
    return load_json_file(VALIDATORS_FILE, [])

def save_validators(validators):
    save_json_file(VALIDATORS_FILE, validators)

def load_last_state():
    return load_json_file(LAST_STATE_FILE, {})

def save_last_state(state):
    save_json_file(LAST_STATE_FILE, state)

# --- Fungsi Pengambilan Data ---
def fetch_validator_data(address: str):
    """Mengambil data detail untuk satu validator dari API."""
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
    now = datetime.now()
    if ALL_VALIDATORS_CACHE and CACHE_EXPIRATION_TIME and now < CACHE_EXPIRATION_TIME:
        logger.info("Menggunakan daftar validator dari cache.")
        return ALL_VALIDATORS_CACHE
    
    logger.info("Cache kosong atau kedaluwarsa. Mengambil daftar validator baru.")
    try:
        response = scraper.get(API_URL_LIST, timeout=30)
        response.raise_for_status()
        data = response.json()
        ALL_VALIDATORS_CACHE = data
        CACHE_EXPIRATION_TIME = now + timedelta(seconds=CACHE_DURATION_SECONDS)
        logger.info("Cache berhasil diperbarui.")
        return data
    except Exception as e:
        logger.error(f"Gagal mengambil daftar semua validator: {e}")
        # Jika gagal, jangan hapus cache lama agar bot tetap bisa berjalan
        return ALL_VALIDATORS_CACHE

# --- Fungsi Pemformatan Pesan untuk /check ---
def format_full_status_message(data: dict, rank: int | str, score: float | str) -> str:
    """Memformat pesan status lengkap sesuai dengan format yang diminta."""
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

# --- Logika Notifikasi Otomatis ---
def check_for_updates(bot: Bot):
    """Memeriksa pembaruan dan mengirim notifikasi."""
    validators = load_validators()
    last_state = load_last_state()
    if not validators:
        return
    
    logger.info("Memulai pengecekan otomatis untuk notifikasi...")
    for address in validators:
        data = fetch_validator_data(address)
        if not data:
            continue
            
        addr_short = f"{address[:6]}...{address[-4:]}"
        if address not in last_state:
            # Inisialisasi state jika validator baru ditambahkan
            last_state[address] = {
                "latest_attestation_slot": 0, 
                "latest_proposal_slot": 0
            }
        state = last_state[address]
        
        # Cek Atestasi Baru
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
                
                message = f"{title}\nValidator: `{addr_short}` | Slot: `#{slot}`\nHasil: {status}"
                bot.send_message(chat_id=AUTHORIZED_USER_ID, text=message, parse_mode=ParseMode.MARKDOWN)
                
                if slot > max_new_att:
                    max_new_att = slot
        state["latest_attestation_slot"] = max_new_att

        # Cek Proposal Blok Baru
        latest_notified_prop = state.get("latest_proposal_slot", 0)
        max_new_prop = latest_notified_prop
        for prop in data.get('proposalHistory', []):
            slot = prop.get('slot', 0)
            if slot > latest_notified_prop:
                status_prop = prop.get('status', 'N/A').upper()
                if status_prop == 'MINED':
                    title = "✅ *Blok Berhasil di-Mine*"
                elif status_prop == 'PROPOSED':
                    title = "📦 *Blok Berhasil Diajukan*"
                else:
                    title = "❓ *Update Proposal Blok*"

                message = f"{title}!\nValidator: `{addr_short}` | Slot: `#{slot}`"
                bot.send_message(chat_id=AUTHORIZED_USER_ID, text=message, parse_mode=ParseMode.MARKDOWN)
                if slot > max_new_prop:
                    max_new_prop = slot
        state["latest_proposal_slot"] = max_new_prop
    
    save_last_state(last_state)
    logger.info("Pengecekan notifikasi selesai.")

# --- Command Handlers ---
@restricted
def start(update: Update, context: CallbackContext):
    """Handler untuk perintah /start."""
    update.message.reply_html(
        "Halo! 👋 Bot ini memonitor validator Aztec Anda.\n\n"
        "<b>Fitur Utama:</b>\n"
        "1️⃣ <b>Notifikasi Otomatis:</b> Dapat notifikasi untuk atestasi & proposal blok baru.\n"
        "2️⃣ <b>Pengecekan Manual:</b> Gunakan /check untuk melihat status lengkap validator.\n\n"
        "<b>Perintah yang tersedia:</b>\n"
        "/add <code>&lt;alamat_validator&gt;</code> - Menambah validator.\n"
        "/remove <code>&lt;alamat_validator&gt;</code> - Menghapus validator.\n"
        "/list - Melihat daftar validator yang dipantau.\n"
        "/check - Memeriksa status semua validator."
    )

@restricted
def add_validator(update: Update, context: CallbackContext):
    """Handler untuk menambah validator ke daftar pantau."""
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
    """Handler untuk menampilkan semua validator yang dipantau."""
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
    """Handler untuk menghapus validator dari daftar pantau."""
    if not context.args:
        update.message.reply_text("Gunakan format: /remove <alamat_validator>")
        return
        
    address_to_remove = context.args[0].lower()
    validators = load_validators()
    last_state = load_last_state()

    if address_to_remove in validators:
        validators.remove(address_to_remove)
        # Hapus juga state notifikasinya
        if address_to_remove in last_state:
            del last_state[address_to_remove]
        
        save_validators(validators)
        save_last_state(last_state)
        update.message.reply_text("🗑️ Alamat berhasil dihapus dari daftar pantau.")
    else:
        update.message.reply_text("Alamat tidak ditemukan dalam daftar.")

@restricted
def check_status_command(update: Update, context: CallbackContext):
    """Handler untuk perintah /check."""
    validators_to_check = load_validators()
    if not validators_to_check:
        update.message.reply_text("Tidak ada validator untuk diperiksa. Tambahkan dengan `/add`.")
        return
    
    sent_message = update.message.reply_text("⏳ Mengambil data peringkat...")
    all_validators_data = fetch_all_validators_with_cache()
    
    if not all_validators_data:
        sent_message.edit_text("❌ Gagal mengambil daftar validator dari API. Peringkat tidak akan tersedia.")
        all_validators_list = []
    else:
        all_validators_list = all_validators_data.get('validators', [])
        if not all_validators_list:
            sent_message.edit_text("❌ Tidak menemukan daftar validator di data API. Peringkat tidak akan tersedia.")
        else:
            sent_message.edit_text(f"✅ Data peringkat siap. Memeriksa status untuk {len(validators_to_check)} validator Anda...")

    for address in validators_to_check:
        rank = "N/A"
        score = "N/A"
        if all_validators_list:
            # Cari peringkat dan skor validator
            for validator_summary in all_validators_list:
                if validator_summary.get('address', '').lower() == address.lower():
                    rank = validator_summary.get('rank', 'N/A')
                    score = validator_summary.get('score', 'N/A')
                    break
        
        detail_data = fetch_validator_data(address)
        if detail_data:
            message = format_full_status_message(detail_data, rank, score)
            update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        else:
            update.message.reply_text(f"❌ Gagal mendapatkan data detail untuk `{address}`.", parse_mode=ParseMode.MARKDOWN)

# --- Fungsi Utama ---
def main():
    """Fungsi utama untuk menjalankan bot."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN tidak ditemukan. Harap atur di file .env.")
        return
    
    # Menambahkan timeout untuk koneksi ke API Telegram
    request_kwargs = {
        'connect_timeout': 20.0,
        'read_timeout': 20.0,
    }
    updater = Updater(BOT_TOKEN, use_context=True, request_kwargs=request_kwargs)
    
    dispatcher = updater.dispatcher
    bot = dispatcher.bot

    # Jalankan pengecekan awal untuk menetapkan status dasar notifikasi
    logger.info("Menjalankan pengecekan awal untuk inisialisasi status notifikasi...")
    check_for_updates(bot)
    logger.info("Status dasar notifikasi telah ditetapkan.")
    
    # Siapkan penjadwal untuk pengecekan otomatis
    scheduler = BackgroundScheduler(timezone=WIB)
    scheduler.add_job(check_for_updates, 'interval', seconds=60, args=[bot], id="update_check_job")
    scheduler.start()
    
    # Daftarkan semua command handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("add", add_validator))
    dispatcher.add_handler(CommandHandler("list", list_validators))
    dispatcher.add_handler(CommandHandler("remove", remove_validator))
    dispatcher.add_handler(CommandHandler("check", check_status_command))
    
    updater.start_polling()
    logger.info("Bot berhasil dijalankan!")
    updater.idle()

if __name__ == '__main__':
    main()

