import os
import json
import logging
from datetime import datetime, timedelta
from functools import wraps

import cloudscraper
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
LAST_STATE_FILE = "last_state.json" # File baru untuk menyimpan status
API_URL_DETAIL = "https://dashtec.xyz/api/validators/{}"

# Buat instance scraper yang akan kita gunakan kembali
scraper = cloudscraper.create_scraper()

# --- Fungsi Helper untuk Mengelola File JSON ---
def load_validators():
    try:
        with open(VALIDATORS_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_validators(validators):
    with open(VALIDATORS_FILE, 'w') as f:
        json.dump(validators, f, indent=4)

def load_last_state():
    try:
        with open(LAST_STATE_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_last_state(state):
    with open(LAST_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4)

# --- Fungsi untuk Mengambil Data ---
def fetch_validator_data(address: str):
    try:
        response = scraper.get(API_URL_DETAIL.format(address), timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Gagal mengambil data detail untuk {address}: {e}")
        return None

# --- Logika Inti Notifikasi Otomatis ---
def check_for_updates(context: CallbackContext):
    bot = context.bot
    validators = load_validators()
    last_state = load_last_state()

    if not validators:
        return # Tidak ada validator untuk diperiksa

    logger.info(f"Memulai pengecekan otomatis untuk {len(validators)} validator...")

    for address in validators:
        data = fetch_validator_data(address)
        if not data:
            continue # Lanjut ke validator berikutnya jika data gagal diambil

        addr_short = f"{address[:6]}...{address[-4:]}"
        
        # Inisialisasi state jika validator baru
        if address not in last_state:
            last_state[address] = {
                "latest_attestation_slot": 0,
                "latest_proposal_slot": 0
            }
        
        current_state = last_state[address]
        
        # 1. Cek Atestasi Baru
        latest_notified_att_slot = current_state.get("latest_attestation_slot", 0)
        new_attestations = []
        max_new_att_slot = latest_notified_att_slot

        for att in data.get('recentAttestations', []):
            slot = att.get('slot')
            if slot and slot > latest_notified_att_slot:
                new_attestations.append(att)
                if slot > max_new_att_slot:
                    max_new_att_slot = slot
        
        # Kirim notifikasi untuk atestasi baru
        for att in new_attestations:
            message = (
                f"✍️ *Atestasi Sukses*\n"
                f"Validator: `{addr_short}` | Slot: `#{att.get('slot')}`\n"
                f"Hasil: {att.get('status', 'N/A')}"
            )
            bot.send_message(chat_id=AUTHORIZED_USER_ID, text=message, parse_mode=ParseMode.MARKDOWN)
        
        current_state["latest_attestation_slot"] = max_new_att_slot

        # 2. Cek Proposal Blok Baru
        latest_notified_prop_slot = current_state.get("latest_proposal_slot", 0)
        new_proposals = []
        max_new_prop_slot = latest_notified_prop_slot

        for prop in data.get('proposalHistory', []):
            slot = prop.get('slot')
            if slot and slot > latest_notified_prop_slot:
                new_proposals.append(prop)
                if slot > max_new_prop_slot:
                    max_new_prop_slot = slot
        
        # Kirim notifikasi untuk proposal baru
        for prop in new_proposals:
            message = (
                f"✅ *Proposal Blok Sukses!*\n"
                f"Validator: `{addr_short}` | Slot: `#{prop.get('slot')}`\n"
                f"Status: {prop.get('status', 'N/A').upper()}"
            )
            bot.send_message(chat_id=AUTHORIZED_USER_ID, text=message, parse_mode=ParseMode.MARKDOWN)

        current_state["latest_proposal_slot"] = max_new_prop_slot

    save_last_state(last_state)
    logger.info("Pengecekan otomatis selesai.")

# --- Command Handlers ---
def start(update: Update, context: CallbackContext):
    """Mengirim pesan selamat datang."""
    update.message.reply_html(
        "Halo! 👋\n\n"
        "Bot ini sekarang berjalan dalam mode notifikasi otomatis.\n"
        "Saya akan memberitahu Anda setiap kali ada atestasi atau proposal blok baru.\n\n"
        "Anda masih bisa menggunakan perintah:\n"
        "• `/add <alamat>` untuk menambahkan validator.\n"
        "• `/list` untuk melihat daftar validator.\n"
        "• `/remove <alamat>` untuk menghapus validator."
    )

def add_validator(update: Update, context: CallbackContext):
    """Menambahkan alamat validator baru ke dalam daftar."""
    if not context.args:
        update.message.reply_text("Gunakan format: /add <alamat_validator>")
        return
    address = context.args[0].lower() # Simpan alamat dalam huruf kecil
    if not (address.startswith("0x") and len(address) == 42):
        update.message.reply_text("Format alamat tidak valid.")
        return
    validators = load_validators()
    if address in validators:
        update.message.reply_text("Alamat ini sudah ada dalam daftar.")
    else:
        validators.append(address)
        save_validators(validators)
        update.message.reply_text(f"✅ Alamat `{address}` berhasil ditambahkan.\n\nBot akan mulai memantau pada siklus pengecekan berikutnya.")

def list_validators(update: Update, context: CallbackContext):
    """Menampilkan daftar validator yang tersimpan."""
    validators = load_validators()
    if not validators:
        update.message.reply_text("Daftar pantau kosong.")
        return
    message = "📜 *Daftar Validator Tersimpan:*\n\n"
    for i, addr in enumerate(validators, 1):
        message += f"{i}. `{addr}`\n"
    update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

def remove_validator(update: Update, context: CallbackContext):
    """Menghapus validator dari daftar."""
    if not context.args:
        update.message.reply_text("Gunakan format: /remove <alamat_validator>")
        return
    address_to_remove = context.args[0].lower()
    validators = load_validators()
    if address_to_remove in validators:
        validators.remove(address_to_remove)
        save_validators(validators)
        update.message.reply_text(f"🗑️ Alamat `{address_to_remove}` berhasil dihapus.")
    else:
        update.message.reply_text("Alamat tidak ditemukan dalam daftar.")

# --- Fungsi Utama untuk Menjalankan Bot ---
def main():
    """Mulai bot dan penjadwalnya."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN tidak ditemukan. Harap atur di file .env.")
        return

    updater = Updater(BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    # Jalankan pengecekan pertama kali untuk menetapkan dasar (baseline)
    # agar tidak mengirim notifikasi untuk semua data lama saat bot pertama kali dijalankan.
    logger.info("Menjalankan pengecekan awal untuk menetapkan status dasar...")
    check_for_updates(CallbackContext(dispatcher))
    logger.info("Status dasar telah ditetapkan.")

    # Siapkan penjadwal untuk pengecekan otomatis
    scheduler = BackgroundScheduler(timezone="Asia/Jakarta")
    scheduler.add_job(check_for_updates, 'interval', seconds=60, args=[CallbackContext(dispatcher)])
    scheduler.start()

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("add", add_validator))
    dispatcher.add_handler(CommandHandler("list", list_validators))
    dispatcher.add_handler(CommandHandler("remove", remove_validator))

    updater.start_polling()
    logger.info("Bot berhasil dijalankan dan penjadwal aktif!")
    updater.idle()

if __name__ == '__main__':
    main()
