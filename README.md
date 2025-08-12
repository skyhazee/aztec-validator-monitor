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
git clone [https://github.com/skyhazee/aztec-validator-monitor.git](https://github.com/skyhazee/aztec-validator-monitor.git)
cd aztec-validator-monitor
```

### Step 2: Set Up a Virtual Environment (Optional, but Recommended)

Creating a virtual environment is a best practice to isolate project dependencies.

```bash
# Create the environment
python3 -m venv venv

# Activate the environment
source venv/bin/activate
```

### Step 3: Install Dependencies

Create a `requirements.txt` file and fill it with the library list below.

**`requirements.txt` file:**
```txt
python-telegram-bot
python-dotenv
cloudscraper
apscheduler
pytz
```

Then, install everything with a single command:

```bash
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables

The bot needs your API token and Telegram ID to function. Create a `.env` file by copying the example.

```bash
cp .env.example .env
```

Now, edit the `.env` file.

```ini
# Replace with the bot token you received from @BotFather on Telegram
BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"

# Replace with your Telegram User ID.
# To get it, send the /start command to @userinfobot
TELEGRAM_ID="123456789"
```

### Step 5: Run the Bot

Once all configurations are complete, run the bot with the following command.

```bash
python bot.py
```

If there are no errors, your bot is now active and ready to use! You can leave this terminal running or use a tool like `screen` or `tmux` to keep the bot running after you close your SSH session.

---

## 🤖 How to Use the Bot

Interact with the bot using the following commands in your Telegram chat with it.

-   `/start`
    Displays a welcome message and a summary of the bot's functions.

-   `/add <validator_address>`
    Adds a validator address to the monitoring list. The bot will start sending notifications for this address.
    *Example:* `/add 0x123abc...`

-   `/remove <validator_address>`
    Removes a validator address from the monitoring list.
    *Example:* `/remove 0x123abc...`

-   `/list`
    Shows all validator addresses you are currently monitoring.

-   `/check`
    Requests a full status report for all validators on your monitoring list. The bot will send one detailed message for each validator.

### Example Output for the `/check` Command

![Bot Output Example](https://i.imgur.com/1Gv1oWd.png)

---

## ❤️ Support

Like this project? Support me on:

-   [X (Twitter)](https://x.com/skyhazeed)
-   [Github](https://github.com/skyhazee)

Contributions in the form of pull requests or suggestions are highly welcome!
