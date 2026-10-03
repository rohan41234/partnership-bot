# Setup — every single click

Follow top to bottom. Don't skip. Each step says **where on the screen** the thing is.

- **[Part 1 — Make the bot](#part-1--make-the-bot-discord-developer-portal)** (~10 min)
- **[Part 2 — Invite it to your server](#part-2--invite-it-to-your-server)** (~3 min)
- **[Part 3 — Get your IDs](#part-3--get-your-ids-inside-discord)** (~5 min)
- **[Part 4 — GitHub](#part-4--github)** (~5 min)
- **[Part 5 — Host it 24/7](#part-5--host-it-247)** (~15 min)
- **[Part 6 — Test it](#part-6--test-it)** (~5 min)

---

## Part 1 — Make the bot (Discord Developer Portal)

### 1.1 Open the portal

Go to **<https://discord.com/developers/applications>** in your browser.
Log in with your normal Discord account if it asks.

You'll land on a page titled **Applications**. It's probably empty.

### 1.2 Create the application

- Look at the **top-right corner** of the page.
- Click the blue **`New Application`** button.
- A popup appears: **"Create an application"**
  - In the **NAME** box type: `Partnership Bot`
  - Tick the checkbox at the bottom (agreeing to the Developer Terms)
  - Click **`Create`** (bottom-right of the popup)

You're now on your app's **General Information** page.

### 1.3 Copy the Application ID — you need it later

Still on **General Information** (you're already here):

- Scroll down slightly to the **APPLICATION ID** section
- Click the **`Copy`** button under it
- **Paste it into Notepad.** Label it `APPLICATION ID`.

> This is NOT the token. It's a public ~19-digit number. Safe to share.

### 1.4 Go to the Bot page

- Look at the **left sidebar**. Under the heading **SETTINGS** you'll see a list:
  General Information · Installation · OAuth2 · **Bot** · Rich Presence · App Testing · Emoji · Webhooks…
- Click **`Bot`**.

### 1.5 Get the token

On the **Bot** page, at the **top**, you'll see your bot's avatar, its username, and a **`Reset Token`** button.

- Click **`Reset Token`**
- A popup warns you the old token dies → click **`Yes, do it!`**
- If you have 2FA on your Discord account, type your 6-digit code → **`Submit`**
- The token now appears as a long string of letters, dots and numbers
- Click **`Copy`** directly underneath it
- **Paste it into Notepad right now.** Label it `BOT TOKEN`.

> ⚠️ **You get ONE chance.** Navigate away and it's hidden forever — you'd have to Reset again.
>
> ⚠️ **This is your bot's password.** Never paste it in a Discord chat, never put it in a screenshot, never commit it to GitHub. If it leaks: come back here, click Reset Token, done.

### 1.6 Turn on the two intents ← **DO NOT SKIP THIS**

Stay on the **Bot** page. **Scroll down** past the token, past "Authorization Flow", until you reach a section headed **`Privileged Gateway Intents`**.

You'll see **three toggle switches**. Set them like this:

| Toggle | Set to | What breaks without it |
|---|---|---|
| `PRESENCE INTENT` | **OFF** (leave it) | nothing, unused |
| `SERVER MEMBERS INTENT` | **ON** ← click it | Bot can't add approvers to private threads. Nobody can see them. |
| `MESSAGE CONTENT INTENT` | **ON** ← click it | Bot reads every message as blank. **Never detects a single invite link.** |

Click each toggle so it turns **blue/green**.

Now a **green bar slides up from the bottom** of the page saying *"Careful — you have unsaved changes!"*

- Click **`Save Changes`** on that bar.

> **This is the #1 reason bots don't work.** If you skip it the bot crashes on
> startup with `PrivilegedIntentsRequired` — that error means *come back and do 1.6.*

### 1.7 Make it private — **in this exact order**

Discord refuses to make an app private while it still has a default authorization link.
Clear the link **first**, then flip the toggle. Doing it backwards gives you this error:

> *Private application cannot have a default authorization link. Please check that the
> default authorization link is set to None in the installation tab.*

**Step 1 — clear the link:**

- Left sidebar → **`Installation`**
- Find the **`Install Link`** section → it's a dropdown, currently **"Discord Provided Link"**
- Change it to **`None`**
- Green bar at the bottom → **`Save Changes`**

**Step 2 — now make it private:**

- Left sidebar → **`Bot`**
- Scroll to **Authorization Flow**
- **`PUBLIC BOT`** → toggle **OFF**
- **`REQUIRE OAUTH2 CODE GRANT`** → must stay **OFF** (if on, your invite link fails)
- **`Save Changes`**

It saves without complaining now.

> **Does this break the invite link?** No. The link in Part 2 is one you build yourself —
> it's not the "Discord Provided Link" you just cleared. With PUBLIC BOT off, that link
> works **only for you**, the app owner. Perfect for a one-server bot.
>
> **Too much hassle?** Leave PUBLIC BOT **ON** and skip 1.7 entirely. Worst case someone
> with your invite URL adds the bot elsewhere — and it ignores them, because `config.toml`
> pins it to your `guild_id`.

**Part 1 done.** You should now have 2 things in Notepad: an Application ID and a token.

---

## Part 2 — Invite it to your server

### 2.1 Easiest way — use this link

Take the link below, replace the words `YOUR_APPLICATION_ID` with the Application ID you copied in step 1.3, and open it in your browser:

```
https://discord.com/api/oauth2/authorize?client_id=YOUR_APPLICATION_ID&permissions=361045814336&scope=bot%20applications.commands
```

So it ends up looking like:
`https://discord.com/api/oauth2/authorize?client_id=1234567890123456789&permissions=361045814336&scope=bot%20applications.commands`

On the page that opens:

1. Click the **"ADD TO SERVER"** dropdown → pick your server
2. Click **`Continue`** (bottom-right)
3. A list of permissions appears → click **`Authorize`** (bottom-right)
4. Complete the "I am human" checkbox if shown

Go check your Discord server — the bot now appears in the member list, **offline**. Offline is correct; it has no code running yet.

### 2.2 Or build the link by hand

If you'd rather tick the boxes yourself:

- Left sidebar → **`OAuth2`**
- Scroll down to the section **`OAuth2 URL Generator`**
- Under **SCOPES**, tick:
  - ☑️ `bot`
  - ☑️ `applications.commands`
- A new **BOT PERMISSIONS** box appears below. Tick these 11:

  | Column | Tick |
  |---|---|
  | General Permissions | ☑️ View Channels · ☑️ Manage Roles |
  | Text Permissions | ☑️ Send Messages · ☑️ Create Private Threads · ☑️ Send Messages in Threads · ☑️ Manage Messages · ☑️ Manage Threads · ☑️ Embed Links · ☑️ Attach Files · ☑️ Read Message History · ☑️ Add Reactions |

- Scroll to the very bottom → **GENERATED URL** → click **`Copy`**
- Paste it in your browser and follow 2.1 steps 1–4

> **Manage Roles** is only used by `/fixpings`. Don't want to grant it? Untick it and use
> permissions integer `360777378880` in the 2.1 link instead.

### 2.3 Move the bot's role UP ← **people always miss this**

In your Discord server (not the portal):

1. Click your **server name** at the very top-left → **`Server Settings`**
2. Left sidebar → **`Roles`**
3. You'll see your role list. Find **`Partnership Bot`** — it's probably at the bottom.
4. **Click and drag it UPWARD** so it sits **above** your `@Staff` and `@Approver` roles
5. Click **`Save Changes`**

> If the bot's role is below your staff roles, Discord silently refuses to let it manage
> their threads and messages. The bot looks online and does nothing. This is the #2 reason
> bots "don't work."

---

## Part 3 — Get your IDs (inside Discord)

The bot needs to know which channel and which roles. Those are numbers.

### 3.1 Turn on Developer Mode

In the Discord app:

1. **Bottom-left corner**, next to your username → click the **⚙️ gear icon** (User Settings)
2. Scroll the left sidebar down to the **APP SETTINGS** group → click **`Advanced`**
3. Toggle **`Developer Mode`** → **ON**
4. Close settings (**Esc** key)

### 3.2 Copy the three numbers you need

Now right-clicking things gives you a "Copy ID" option.

| What | How to copy it |
|---|---|
| **Server ID** | Right-click your **server name** (top-left) → **`Copy Server ID`** (bottom of menu) |
| **Partnership channel ID** | Right-click the channel in the channel list → **`Copy Channel ID`** |
| **Approver role ID** | Server Settings → Roles → hover the role → click the **⋯** three dots → **`Copy Role ID`** |

> **You only need one role.** The **approver** role does everything: it's added to each
> partnership thread, pinged there, presses ✅ Approve, and unlocks the staff-only
> commands like `/quota list`.
>
> There's an optional second role, `[roles] staff`, for servers that want a wider group
> who can *see* the staff commands without being able to approve. Leave it out and your
> approvers are treated as staff. It is never added to threads either way.

Paste all three into Notepad with labels.

> Don't have an approver role yet? Make one first: Server Settings → Roles →
> **`Create Role`** (top-right).

### 3.3 Fill in config.toml

Open `config.toml` from the project folder in any text editor (Notepad works). Replace the zeros:

```toml
guild_id = 123456789012345678        # your Server ID

[channels]
partnership = 111111111111111111     # the channel people post invite links in
logs        = 444444444444444444     # STRONGLY recommended, see note

[roles]
approver = 333333333333333333   # the only role you have to set
```

> **Set `logs`.** Threads delete themselves 15 seconds after a decision. Without a log
> channel you keep no record of anything that ever happened.

Optional — the weekly quota tracker. Make a `#quota` channel, copy its ID, and add:

```toml
[channels]
quota = 555555555555555555

[quota]
target = 5     # partnerships each staff member owes per week
```

After every approval the bot posts `3/5 this week, 2 to go` there.

### 3.4 Who can see a partnership thread

Default behaviour, no config needed:

| | In the thread | Pinged |
|---|---|---|
| The person who posted the link | ✅ always | ✅ |
| Your approver role | ✅ | ✅ |
| Your staff role (if you set one) | ❌ | ❌ |
| Everyone else | ❌ | ❌ |

Partnership threads are **private threads**, so anyone not added genuinely cannot see
them — they don't appear in the channel, in search, or in the thread list.

If you only set `[roles] approver`, that's the whole picture: the poster and your
approvers, nobody else. The `add_staff_role` / `ping_staff_role` switches below only
do something if you've also set an optional `[roles] staff`.

> ⚠️ **One thing no bot can block.** Anyone holding the **Manage Threads** permission
> can see private threads whether they were added or not — that's enforced by Discord
> itself. Before relying on thread privacy, open Server Settings → Roles and check who
> has it. It's bundled into Administrator and into most "Moderator" permission presets.

Full `[threads]` block, if you want to tune it:

```toml
[threads]
auto_archive_minutes = 10080   # auto-archive after 7 days of silence
                               # (only 60, 1440, 4320 or 10080 are valid)
add_approver_role    = true
add_staff_role       = false
max_members_added    = 40      # safety cap on how many people get added at once
ping_poster          = true
ping_approver_role   = true
ping_staff_role      = false
```

### 3.5 Duplicate links

Nothing to configure — this is on by default. If two people post the same server, the
second one is told it's already being handled (with no link to the private thread) and
**their message is deleted** to keep the channel clean. Your own re-post is never
deleted, and neither is a message that also contained a new link.

To keep duplicates visible instead:

```toml
[duplicates]
delete_duplicate_message = false
```

Save the file.

---

## Part 4 — GitHub

Your host pulls the code from here.

### 4.1 Create the repo

1. Go to **<https://github.com/new>**
2. **Repository name** box → type `partnership-bot`
3. Below that, click the **`Private`** radio button ← recommended
4. **Leave every checkbox unticked** (no README, no .gitignore, no license — you have them)
5. Scroll down → green **`Create repository`** button

GitHub now shows you a page of commands. Ignore it, use mine below.

### 4.2 Make a Personal Access Token

Your GitHub **password will not work** when pushing. You need a token.

1. Click your **profile picture, top-right** → **`Settings`**
2. Scroll the left sidebar all the way to the bottom → **`Developer settings`**
3. Left sidebar → **`Personal access tokens`** → **`Tokens (classic)`**
4. Top-right → **`Generate new token`** → **`Generate new token (classic)`**
5. **Note** box: type `partnership-bot`
6. **Expiration**: pick `90 days` or `No expiration`
7. Under **Select scopes**, tick the top box **☑️ `repo`** (it auto-ticks the ones under it)
8. Scroll to the bottom → green **`Generate token`**
9. **Copy it now** — same deal as the bot token, shown once. Save in Notepad.

### 4.3 Push the code

Open a terminal (Windows: **Command Prompt**; Mac: **Terminal**) in your project folder and run these one at a time:

```bash
cd partnership-bot

git init
git add .
git commit -m "Partnership bot"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/partnership-bot.git
git push -u origin main
```

On the last command it asks for:
- **Username:** your GitHub username
- **Password:** paste the **token** from 4.2, *not* your password

### 4.4 Prove you didn't leak the bot token

```bash
git log --all --full-history -- .env
```

**This must print absolutely nothing.** If it prints anything, your bot token is in your
git history — go to the Developer Portal → Bot → **Reset Token** immediately.

---

## Part 5 — Host it 24/7

### First, the trap

This bot keeps every point in a **file on disk** (`data/partnership.db`). If the host wipes
the disk, **your entire leaderboard is gone.**

> ❌ **Not Render's free tier.** Free services there have a **throwaway disk** and restart
> whenever Render feels like it — your points would vanish at random. Free services also
> sleep after 15 min, and the correct service type for a bot (Background Worker) **isn't
> free at all**, it's $7/mo. Keep-alive pings fix the sleeping but do nothing about the disk.

| Host | RAM | Catch |
|---|---|---|
| **bot-hosting.net** ← start here | 256 MB | **You must click renew every 4 days** |
| Discloud | 100 MB | Tight RAM; `discloud.config` already in the repo |
| Oracle Cloud Always Free | up to 24 GB | Free forever, real 24/7 — but it's a Linux VM |

---

### Option A — bot-hosting.net (easiest)

1. Go to **<https://bot-hosting.net>** → **`Login with Discord`** (top-right) → **`Authorize`**
2. On the dashboard you'll see a **coin balance**. Click the **daily reward** button to collect free coins.
3. Click **`Create Server`** → choose the **Python** egg/type → confirm
4. Click your new server to open its panel
5. Go to the **`Startup`** tab (top row of tabs)
   - **Startup Command** → set to `python bot.py`
   - In the **Variables** section on the same page, add:
     | Name | Value |
     |---|---|
     | `DISCORD_TOKEN` | *paste your token from step 1.5* |
     | `DB_PATH` | `data/partnership.db` |
6. Go to the **`Files`** tab → upload your project files (drag and drop), **including your filled-in `config.toml`** and **excluding `.env`**
7. Go back to **`Console`** tab → click the green **`Start`** button
8. Watch the console. You want to see `Logged in as Partnership Bot`

⏰ **Set a phone alarm every 3 days** to open the panel and click renew. Miss it and the
server is deleted. Every week or two, go to **Files** → download `data/partnership.db` as a backup.

---

### Option B — Oracle Cloud Always Free (best, most work)

1. **<https://cloud.oracle.com>** → **Start for free** → sign up
   - Needs a real card for identity check — **it is not charged**
   - Pick a home region close to you; you can't change it later
2. Once in, click the **☰ hamburger menu, top-left** → **Compute** → **Instances**
3. Click **`Create instance`**
   - **Image and shape** → **`Edit`** → **`Change shape`** → **Ampere** → `VM.Standard.A1.Flex` → 1 OCPU, 6 GB
   - **Image** → **`Change image`** → **Canonical Ubuntu 22.04**
   - Scroll to **Add SSH keys** → **`Save private key`** ← **download it, you get one chance**
4. Click **`Create`**. Wait for the state to go green (**RUNNING**), then copy the **Public IP address**.
5. Open a terminal on your computer:

```bash
chmod 600 ~/Downloads/ssh-key.key
ssh -i ~/Downloads/ssh-key.key ubuntu@YOUR_PUBLIC_IP
```

6. Now you're on the server. Paste these:

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv git

git clone https://github.com/YOUR_USERNAME/partnership-bot.git
cd partnership-bot

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env
```

`nano` is a text editor. Put your token on the `DISCORD_TOKEN=` line, then press
**Ctrl+O** → **Enter** (save) → **Ctrl+X** (exit).

```bash
nano config.toml      # paste your IDs, same save keys
python bot.py         # test run — you should see "Logged in as..."
```

7. **Ctrl+C** to stop, then make it permanent so it survives reboots:

```bash
sudo tee /etc/systemd/system/partnership-bot.service >/dev/null <<'EOF'
[Unit]
Description=Partnership Bot
After=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/partnership-bot
ExecStart=/home/ubuntu/partnership-bot/.venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now partnership-bot
sudo systemctl status partnership-bot
```

Live logs: `journalctl -u partnership-bot -f` (Ctrl+C to stop watching)
Update later: `cd ~/partnership-bot && git pull && sudo systemctl restart partnership-bot`

---

## Part 6 — Test it

The bot should now show **online** (green dot) in your member list.

### 6.1 Run the self-check

In any channel in your server, type:

```
/diagnose
```

It checks every channel ID, every role ID, both intents, every permission, and whether
`@everyone` can mass-ping. **Fix everything it marks ❌ before going further.**

Then lock down mass pings:

```
/fixpings
```

### 6.2 Do a real run

1. Post a Discord invite link (like `discord.gg/something`) in your partnership channel
2. ✅ A private thread should appear and ping you + the approver role
   *(If an approver says they can't see it, their role ID is wrong — run `/diagnose`.)*
3. Upload **any image** into that thread → the **Approve** button unlocks
4. On a **second account** that has the approver role → press **✅ Approve**
5. Type `/leaderboard` → points should be there

> ⚠️ **Step 4 needs a second person.** Self-approval is hard-blocked — you cannot approve
> your own submission. If you're the only approver, **nothing you post can ever be
> approved.** Give the approver role to someone you trust, or ask me to add an
> `allow_self_approve` switch.

---

## When it doesn't work

| What you see | What it means |
|---|---|
| `Private application cannot have a default authorization link` | You turned off PUBLIC BOT before clearing the install link — **step 1.7**, do it in order |
| Crashes, `PrivilegedIntentsRequired` | **Step 1.6** — you didn't enable the intents |
| Online, but ignores every link | Wrong channel ID, or `guild_id` is wrong — run `/diagnose` |
| `Improper token has been passed` | Token pasted wrong, or you reset it after copying |
| Slash commands don't appear | Wait up to 1 hour. Still nothing? Re-invite with the `applications.commands` scope |
| "Missing Permissions" / can't make threads | **Step 2.3** — bot's role is below your staff roles |
| Approvers can't see the thread | Wrong `[roles] approver` ID, or `SERVER MEMBERS INTENT` is off — **step 1.6** |
| Someone unexpected can see a thread | They hold **Manage Threads** — see **step 3.4** |
| Points reset on their own | Host has a throwaway disk. Move off Render free. |
| Nothing can ever be approved | You're the only approver — see 6.2 |

---

## Backups

The bot's entire memory is one file: **`data/partnership.db`**.

Download it from your host's file manager now and then. On Oracle, from your own computer:

```bash
scp -i ~/Downloads/ssh-key.key ubuntu@YOUR_IP:~/partnership-bot/data/partnership.db ./backup.db
```

To restore: put the file back in `data/` and restart the bot.
