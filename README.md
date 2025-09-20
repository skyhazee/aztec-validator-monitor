# Aztec Validator Monitor Bot for Telegram

![GitHub last commit](https://img.shields.io/github/last-commit/skyhazee/aztec-validator-monitor?style=for-the-badge) ![GitHub repo size](https://img.shields.io/github/repo-size/skyhazee/aztec-validator-monitor?style=for-the-badge)

A simple yet powerful Telegram bot built with Python to monitor validator status on the Aztec network. Get automatic notifications for important activities and check your validator's status anytime with a simple command.

---

## ✨ Key Features

-   **🔔 Automatic Notifications:** Get real-time alerts directly in Telegram whenever your validator:
    -   ✍️ Successfully submits an attestation
    -   ⚠️ Misses an attestation
    -   ✅ Successfully proposes a block
-   **📊 Manual Status Checks:** Use the `/check` command to get a full status report at any time, which includes:
    -   Validator Rank
    -   Status (e.g., Validating/Offline)
    -   Total Balance & Rewards
    -   Attestation & Block Proposal Success Rates
    -   Epoch Participation & Voting History Count
-   **🔗 Direct Links:** Each status report includes a direct link to the validator's dashboard on dashtec.xyz.
-   **🔒 Secure & Private:** The bot will only respond to commands from your specified Telegram ID, ensuring only you can use it.
-   **⚙️ Easy Management:** Easily add, remove, and view the list of validators you are monitoring with `/add`, `/remove`, and `/list` commands.
-   **⚡ Lightweight:** Designed to run efficiently on a server (VPS) with minimal resource consumption.

---

## 🚀 Installation & Setup

Follow these steps to get your own bot up and running.

### Prerequisites

-   Python 3.8 or newer
-   A server/VPS or a computer that can run 24/7
-   A Telegram account

### Step 1: Clone the Repository

Open a terminal on your server and clone this repository.

```bash
git clone https://github.com/skyhazee/aztec-validator-monitor.git
cd aztec-validator-monitor
```

Make screen

```bash
screen -S aztecbot
```

### Step 2: Set Up a Virtual Environment (Recommended)

Using a virtual environment is a best practice to keep project dependencies isolated.

```bash
python3 -m venv venv

source venv/bin/activate
```

### Step 3: Install Dependencies

All required packages are listed in `requirements.txt`. Install them with a single command:

```bash
pip install -r requirements.txt
```

### Step 4: Configure the Bot

The bot needs a **Token** and your **Telegram User ID** to work.

1.  **Get your Bot Token:**
    -   Open Telegram and start a chat with [@BotFather](https://t.me/BotFather).
    -   Send the `/newbot` command and follow the instructions to create a new bot.
    -   **BotFather** will give you a unique token. Copy it.

2.  **Get your Telegram User ID:**
    -   Start a chat with [@userinfobot](https://t.me/userinfobot).
    -   Send the `/start` command.
    -   The bot will reply with your User ID. Copy it.

3.  **Create the `.env` file:**
    -   Rename the example file:
        ```bash
        nano .env
        ```
    -   Now, open the `.env` file and paste your credentials:
        ```ini
        BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        TELEGRAM_ID="123456789"
        ```
press ctrl+x+y to save

### Step 5: Run the Bot

Once everything is configured, run the bot:

```bash
python bot.py
```

If you see no errors, your bot is now online! For continuous operation, it's recommended to use a process manager like `screen` or `tmux` to keep the bot running even after you disconnect from your server.

---

## 🤖 How to Use the Bot

Interact with your bot by sending these commands in your private chat with it on Telegram.

-   `/start`
    Displays a welcome message and a summary of the bot's functions.

-   `/add <validator_address>`
    Adds a validator address to the monitoring list.
    *Example:* `/add 0x123abc...`

-   `/remove <validator_address>`
    Removes a validator address from the monitoring list.
    *Example:* `/remove 0x123abc...`

-   `/list`
    Shows all validator addresses you are currently monitoring.

-   `/check`
    Requests a full status report for all validators on your list. The bot will send one detailed message for each validator.

### Example Output for the `/check` Command

```
👑 Rank: 1
🎯 Score: 0.00
📊 Status Validator: 0x...
Validating ✅
💰 Saldo: 100.00 STK
🏆 Total Rewards: 500.00 STK
-----------------------------------
✨ Performance Metrics
🛡️ Attestation Rate: 95.8%
    1150 Succeeded / 50 Missed
📦 Block Proposal Rate: 94.1%
    32 Proposed or Mined / 2 Missed
🗓️ Epoch Participation: 46
🗳️ Jumlah Voting: 10
```
### Example Output for the Attestation

```
⚠️ Atestasi Terlewat
Validator: 0x... | Slot: #50432
Hasil: Missed

✍️ Atestasi Sukses
Validator: 0x... | Slot: #50433
Hasil: Success

✅ Proposal Blok Sukses!
Validator: 0x... | Slot: #50448
Status: BLOCK-MINED
```

---

## ❤️ Support

Like this project? Support me on:

-   [X (Twitter)](https://x.com/skyhazeed)
-   [Github](https://github.com/skyhazee)

Contributions in the form of pull requests or suggestions are highly welcome!
