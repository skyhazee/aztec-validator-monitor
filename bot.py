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
API_URL_DETAIL = "https://dashtec.xyz/api/validators/{}"
API_URL_LIST = "https://dashtec.xyz/api/validators?"

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
    """Mengambil data detail untuk satu validator."""
    try:
        response = scraper.get(API_URL_DETAIL.format(address), timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Gagal mengambil data detail untuk {address}: {e}")
        return None

def fetch_all_validators():
    """Mengambil daftar semua validator untuk mencari rank."""
    try:
        response = scraper.get(API_URL_LIST, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Gagal mengambil daftar semua validator: {e}")
        return None

def format_status_message(data: dict, rank: int | str):
    """Memformat data JSON menjadi pesan yang mudah dibaca."""
    if not data:
        return "Gagal mengambil data."

    addr = data.get('address', 'N/A')
    short_addr = f"{addr[:6]}...{addr[-4:]}" if len(addr) > 10 else addr

    status_map = {"VALIDATING": "Validating ✅"}
    status = status_map.get(data.get('status', 'UNKNOWN').upper(), f"{data.get('status', 'Unknown')} ❓")

    try:
        raw_balance = float(data.get('balance', 0))
        raw_total_rewards = float(data.get('unclaimedRewards', 0))
        balance = raw_balance / 1e18
        total_rewards = raw_total_rewards / 1e18
    except (ValueError, TypeError):
        balance = 0.0
        total_rewards = 0.0

    attestation_succeeded = data.get('totalAttestationsSucceeded', 0)
    attestation_missed = data.get('totalAttestationsMissed', 0)
    total_attestations = attestation_succeeded + attestation_missed
    attestation_rate = (attestation_succeeded / total_attestations * 100) if total_attestations > 0 else 0

    proposal_succeeded = data.get('totalBlocksProposed', 0)
    proposal_missed = data.get('totalBlocksMissed', 0)
    total_proposals = proposal_succeeded + proposal_missed
    proposal_rate = (proposal_succeeded / total_proposals * 100) if total_proposals > 0 else 0

    epoch_participation = data.get('totalParticipatingEpochs', 'N/A')
    timestamp = datetime.now().strftime('%d %b %Y, %H:%M:%S')

    message = (
        f"👑 *Rank:* {rank}\n"
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
    )

    voting_history = data.get('votingHistory', [])
    if voting_history:
        message += f"\n🗳️ *Voting History*\n"
        for vote in voting_history:
            vote_info = vote.get('info', 'N/A')
            vote_status = vote.get('status', 'N/A')
            message += f"    • {vote_info}: {vote_status}\n"

    message += (
        f"-----------------------------------\n"
        f"🕒 *Terakhir dicek:* {timestamp}"
    )
    return message

# --- Command Handlers ---
@restricted
def start(update: Update, context: CallbackContext):
    """Mengirim pesan selamat datang."""
    user = update.effective_user
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
    validators_to_check = load_validators()
    if not validators_to_check:
        update.message.reply_text("Tidak ada validator untuk diperiksa. Tambahkan dengan `/add <alamat>`.")
        return

    update.message.reply_text(f"🔍 Mengambil daftar semua validator untuk mencari rank... Mohon tunggu, ini mungkin perlu waktu.")
    
    all_validators_data = fetch_all_validators()
    if not all_validators_data:
        update.message.reply_text("❌ Gagal mengambil daftar validator dari API. Tidak bisa melanjutkan.")
        return
    
    # --- PERUBAHAN DI SINI ---
    # Mengambil daftar dari dalam objek, dengan asumsi kuncinya adalah 'validators'.
    # Menggunakan .get() untuk keamanan jika kuncinya tidak ada.
    all_validators_list = all_validators_data.get('validators', [])
    if not all_validators_list:
        update.message.reply_text("❌ Tidak menemukan daftar validator di dalam data API.")
        return
    # --- AKHIR PERUBAHAN ---

    update.message.reply_text(f"✅ Daftar berhasil diambil. Memeriksa status untuk {len(validators_to_check)} validator Anda...")

    for address in validators_to_check:
        rank = "N/A"
        for validator_summary in all_validators_list:
            # Pemeriksaan ini sekarang seharusnya aman
            if validator_summary.get('address', '').lower() == address.lower():
                rank = validator_summary.get('rank', 'N/A')
                break
        
        detail_data = fetch_validator_data(address)
        if detail_data:
            message = format_status_message(detail_data, rank)
            update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        else:
            update.message.reply_text(f"❌ Gagal mendapatkan data detail untuk `{address}`.", parse_mode=ParseMode.MARKDOWN)

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

    updater = Updater(BOT_TOKEN, use_context=True)
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
