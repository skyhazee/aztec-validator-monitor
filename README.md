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
