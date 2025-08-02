import os
import json
import logging
from datetime import datetime
from functools import wraps

# Import cloudscraper sebagai pengganti requests
import cloudscraper
from dotenv import load_dotenv
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, CallbackContext

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
API_URL = "https://dashtec.xyz/api/validators/{}"

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
    """Memuat alamat validator dari file JSON."""
    try:
        with open(VALIDATORS_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_validators(validators):
    """Menyimpan alamat validator ke file JSON."""
    with open(VALIDATORS_FILE, 'w') as f:
        json.dump(validators, f, indent=4)

# --- Fungsi untuk Mengambil & Memformat Data ---
def fetch_validator_data(address: str):
    """Mengambil data validator menggunakan cloudscraper untuk melewati proteksi."""
    try:
        # Gunakan scraper.get, bukan requests.get
        response = scraper.get(API_URL.format(address), timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Gagal mengambil data untuk {address}: {e}")
        return None

def format_status_message(data: dict):
    """Memformat data JSON menjadi pesan yang mudah dibaca."""
    if not data:
        return "Gagal mengambil data."

    addr = data.get('address', 'N/A')
    short_addr = f"{addr[:6]}...{addr[-4:]}" if len(addr) > 10 else addr

    status_map = {
        "VALIDATING": "Validating ✅",
        "PENDING": "Pending ⏳",
        "OFFLINE": "Offline ❌"
    }
    status = status_map.get(data.get('status', 'UNKNOWN').upper(), "Unknown ❓")
    
    performance = data.get('performance', {})
    attestation = performance.get('attestation', {})
    proposal = performance.get('block_proposal', {})

    # Mengubah data menjadi float (angka desimal) sebelum digunakan.
    # Blok try-except ini untuk keamanan jika data tidak valid.
    try:
        balance = float(data.get('balance', 0))
        total_rewards = float(data.get('totalRewards', 0))
    except (ValueError, TypeError):
        balance = 0.0
        total_rewards = 0.0
    
    attestation_rate = attestation.get('rate', 0) * 100
    attestation_succeeded = attestation.get('succeeded', 0)
    attestation_missed = attestation.get('missed', 0)
    
    proposal_rate = proposal.get('rate', 0) * 100
    proposal_succeeded = proposal.get('proposed', 0)
    proposal_missed = proposal.get('missed', 0)
    
    epoch_participation = data.get('epochParticipation', 'N/A')
    
    timestamp = datetime.now().strftime('%d %b %Y, %H:%M:%S')

    message = (
        f"📊 *Status Validator:* `{short_addr}`\n"
        f"{status}\n\n"
        f"💰 *Saldo:* {balance:.2f} STK\n"
        f"🏆 *Total Rewards:* {total_rewards:.2f} STK\n"
        f"-----------------------------------\n"
        f"✨ *Performance Metrics*\n\n"
        f"🛡️ *Attestation Rate:* {attestation_rate:.1f}%\n"
        f"    {attestation_succeeded} Succeeded / {attestation_missed} Missed\n\n"
        f"📦 *Block Proposal Rate:* {proposal_rate:.1f}%\n"
        f"    {proposal_succeeded} Proposed / {proposal_missed} Missed\n\n"
        f"🗓️ *Epoch Participation:* {epoch_participation}\n"
        f"-----------------------------------\n"
        f"🕒 *Terakhir dicek:* {timestamp}"
    )
    return message

# --- Command Handlers ---
@restricted
def start(update: Update, context: CallbackContext):
    """Mengirim pesan selamat datang."""
    user = update.effective_user
    # Memperbaiki < dan > agar tidak dianggap tag HTML
    update.message.reply_html(
        f"Halo, {user.first_name}! 👋\n\n"
        "Saya adalah bot pemantau validator Aztec.\n\n"
        "Gunakan perintah berikut:\n"
        "• `/add &lt;alamat_validator&gt;` untuk menambahkan validator.\n"
        "• `/check` untuk memeriksa status semua validator.\n"
        "• `/list` untuk melihat daftar validator tersimpan.\n"
        "• `/remove &lt;alamat_validator&gt;` untuk menghapus validator."
    )

@restricted
def add_validator(update: Update, context: CallbackContext):
    """Menambahkan alamat validator baru ke dalam daftar."""
    if not context.args:
        update.message.reply_text("Gunakan format: /add <alamat_validator>")
        return

    address = context.args[0]
    if not (address.startswith("0x") and len(address) == 42):
        update.message.reply_text("Format alamat tidak valid. Harus dimulai dengan '0x' dan panjang 42 karakter.")
        return

    validators = load_validators()
    if address in validators:
        update.message.reply_text("Alamat ini sudah ada dalam daftar.")
    else:
        validators.append(address)
        save_validators(validators)
        update.message.reply_text(f"✅ Alamat `{address}` berhasil ditambahkan.", parse_mode=ParseMode.MARKDOWN)

@restricted
def check_status(update: Update, context: CallbackContext):
    """Memeriksa status semua validator yang tersimpan."""
    validators = load_validators()
    if not validators:
        update.message.reply_text("Tidak ada validator untuk diperiksa. Tambahkan dengan `/add <alamat>`.")
        return

    update.message.reply_text(f"🔍 Memeriksa status untuk {len(validators)} validator... Mohon tunggu.")

    for address in validators:
        data = fetch_validator_data(address)
        if data:
            message = format_status_message(data)
            update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        else:
            update.message.reply_text(f"❌ Gagal mendapatkan data untuk `{address}`. Server mungkin memblokir permintaan atau alamat tidak valid.", parse_mode=ParseMode.MARKDOWN)

@restricted
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

@restricted
def remove_validator(update: Update, context: CallbackContext):
    """Menghapus validator dari daftar."""
    if not context.args:
        update.message.reply_text("Gunakan format: /remove <alamat_validator>")
        return

    address_to_remove = context.args[0]
    validators = load_validators()

    if address_to_remove in validators:
        validators.remove(address_to_remove)
        save_validators(validators)
        update.message.reply_text(f"🗑️ Alamat `{address_to_remove}` berhasil dihapus.", parse_mode=ParseMode.MARKDOWN)
    else:
        update.message.reply_text("Alamat tidak ditemukan dalam daftar.")

# --- Fungsi Utama untuk Menjalankan Bot ---
def main():
    """Mulai bot."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN tidak ditemukan. Harap atur di file .env.")
        return

    updater = Updater(BOT_TOKEN)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("add", add_validator))
    dispatcher.add_handler(CommandHandler("check", check_status))
    dispatcher.add_handler(CommandHandler("list", list_validators))
    dispatcher.add_handler(CommandHandler("remove", remove_validator))

    updater.start_polling()
    logger.info("Bot berhasil dijalankan!")
    updater.idle()

if __name__ == '__main__':
    main()
