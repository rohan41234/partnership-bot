# 🤝 Partnership Bot

Detects Discord invite links in your partnership channel, opens a **private thread per link**,
pings staff, collects **screenshot proof**, lets **higher staff approve**, keeps a **live
leaderboard**, and **resets it weekly** with a results post.

**All setup happens in one file: `config.toml`.** There are no setup slash commands.

---

## How it works

```
1.  Someone posts  discord.gg/theirserver  in #partnerships
          │
          ├─ Already an open thread for that server?
          │     • you're the original poster → you get the link to your thread
          │     • anyone else → "already handled by another staff member", NO link
          │
2.  Bot opens a PRIVATE thread  🤝 Their Server
          │  ONLY the poster + @HeadStaff are added and pinged
          │  (nobody else can even see it)
          │
3.  Pinned control panel pings the POSTER + @HeadStaff. Approve is LOCKED.
          │
4.  Staff posts a SCREENSHOT of our ad on their server
          │  bot reacts 📸, unlocks Approve, pings @HeadStaff
          │
5.  @HeadStaff presses ✅ Approve  (or ❌ Reject with a reason)
          │  first one to press wins — the race is atomic, the
          │  loser is told "someone beat you to it"
          │
          ├─ APPROVED → points awarded, partner on 24h cooldown,
          │             thread deleted after 15s
          │
          ├─ REJECTED → no points, the original ad is DELETED from the
          │             partnership channel, thread deleted after 15s
          │
6.  Result is written to #logs — that's the permanent record
          │
7.  Every week → results posted to #weekly-results, scores back to zero
                  (all-time totals are kept forever)
```

**While a thread is waiting for proof,** every message the poster sends that isn't an image
gets a reminder to upload the screenshot. The reminder replaces itself instead of stacking,
and **stops permanently** the moment an image is posted.

---

## Setup

> 📘 **Full step-by-step walkthrough — Discord portal, GitHub and hosting — is in
> [SETUP.md](SETUP.md).** The short version is below.

### 1. Create the bot

1. <https://discord.com/developers/applications> → **New Application**
2. **Bot** tab → **Reset Token** → copy it
3. Enable **both** privileged intents on that page:
   - ✅ **MESSAGE CONTENT INTENT** — required to read invite links
   - ✅ **SERVER MEMBERS INTENT** — required to add staff to private threads
4. **OAuth2 → URL Generator** → scopes `bot` + `applications.commands`, permissions:
   `View Channels`, `Send Messages`, `Send Messages in Threads`, `Create Private Threads`,
   `Manage Threads`, `Manage Messages`, `Embed Links`, `Attach Files`,
   `Read Message History`, `Add Reactions`
5. Open the URL and add the bot to your server.

### 2. Put the token in `.env`

```bash
cp .env.example .env
# edit .env  ->  DISCORD_TOKEN=...
```

The token is the **only** thing that lives outside `config.toml`. Never commit it.

### 3. Fill in `config.toml`

```bash
cp config.example.toml config.toml
```

Turn on **Developer Mode** in Discord (User Settings → Advanced), then right-click
channels/roles → **Copy ID** and paste the numbers in.

The absolute minimum to get running:

```toml
guild_id = 123456789012345678

[channels]
partnership = 111111111111111111

[roles]
approver = 333333333333333333
```

> `[roles] staff` is **optional** — leave it out and your approvers are treated as
> staff for the staff-only commands. Only add it if you want a second, wider role
> that can run `/quota list` without being able to approve.

Add these to unlock the rest:

```toml
[channels]
threads        = 0    # 0 = threads go in the partnership channel
logs           = 0    # audit log of approvals
leaderboard    = 0    # live auto-updating board
weekly_results = 0    # weekly reset results

[roles]
staff       = 0       # optional second role: staff-command access only
weekly_ping = 0       # pinged with the weekly results
```

### 4. Run it

```bash
pip install -r requirements.txt
python bot.py
```

Then in Discord run **`/diagnose`** — it checks every ID, every permission and both intents,
and tells you exactly what's wrong.

> **Changed something?** Edit `config.toml` and run **`/reloadconfig`** — no restart needed.
> The bot also auto-detects file changes every 30 seconds.

---

## Configuration reference

Everything lives in `config.toml`. Full comments are in `config.example.toml`.

| Section | Key | Default | What it does |
|---|---|---|---|
| | `guild_id` | — | **Required.** Your server ID |
| | `enabled` | `true` | Master switch for invite detection |
| `[channels]` | `partnership` | — | **Required.** Channel watched for invite links |
| | `threads` | `0` | Where private threads are made (`0` = same channel) |
| | `logs` | `0` | Audit log channel |
| | `leaderboard` | `0` | Live leaderboard channel |
| | `weekly_results` | `0` | Weekly results channel |
| `[roles]` | `approver` | — | **Required.** Added to threads, pinged, can Approve / Reject |
| | `staff` | `0` | Optional. Staff-command access only — not added, not pinged |
| | `weekly_ping` | `0` | Pinged with weekly results |
| `[points]` | `staff` | `2` | Points to the staff member |
| | `approver` | `1` | Points to the approver (`0` = none) |
| `[proof]` | `required` | `true` | Lock Approve until a screenshot is posted |
| | `attachment_only` | `true` | A pasted image **link** doesn't count — upload only |
| `[threads]` | `auto_archive_minutes` | `10080` | 60 / 1440 / 4320 / 10080 |
| | `add_approver_role` | `true` | Add approvers to each private thread |
| | `add_staff_role` | `false` | Add the staff role too (off) |
| | `max_members_added` | `40` | Rate-limit guard |
| | `ping_poster` | `true` | Ping whoever posted the link |
| | `ping_staff_role` | `false` | Ping the whole staff role (noisy — off) |
| | `ping_approver_role` | `true` | Ping the approvers, who must act |
| `[duplicates]` | `hide_after_seconds` | `15` | Notice self-deletes after N sec (`0` = never) |
| | `delete_duplicate_message` | `true` | Remove other people's duplicate links |
| `[leaderboard]` | `enabled` | `true` | Live auto-updating board |
| | `interval_seconds` | `60` | Refresh rate (min 30) |
| | `top` | `10` | How many to show (3–15) |
| `[weekly_reset]` | `enabled` | `true` | Weekly reset on/off |
| | `day` | `"monday"` | Weekday name |
| | `time` | `"00:00"` | 24-hour HH:MM |
| | `timezone` | `"Asia/Dhaka"` | IANA timezone |
| | `top` | `10` | People listed in the results post (3–25) |
| `[on_decision]` | `delete_thread_on_approve` | `true` | Delete the thread after approval |
| | `delete_thread_on_reject` | `true` | Delete the thread after rejection |
| | `delete_thread_after_seconds` | `15` | Grace period (`0` = instant) |
| | `delete_ad_on_reject` | `true` | Delete the rejected ad from the channel |
| `[antiping]` | `enabled` | `true` | Delete messages containing `@everyone` / `@here` |
| | `scope` | `"partnership"` | `"partnership"` or `"all"` channels |
| | `block_here` | `true` | Also catch `@here` |
| | `block_role_pings` | `false` | Also catch unexpected role pings |
| | `exempt_owner` | `true` | **You** can mass ping — nobody else can |
| | `exempt_admins` | `false` | Admins get filtered too unless you flip this |
| | `exempt_approvers` | `false` | Approvers get filtered too unless you flip this |
| | `exempt_users` | `[]` | Extra user IDs allowed to mass ping |
| `[quota]` | `enabled` | `true` | Post quota progress after each approval |
| | `target` | `5` | How many each staff member owes per week (`0` = off) |
| | `count` | `"partnerships"` | `"partnerships"` or `"points"` |
| | `ping_member` | `true` | Mention them in the quota message |
| | `announce_complete` | `true` | Keep posting once they're already done |
| | `also_post_in_thread` | `false` | Copy the progress into the partnership thread |
| `[cooldown]` | `enabled` | `true` | Block re-partnering with the same server |
| | `hours` | `24` | Cooldown length |
| | `delete_message` | `true` | Delete the offending repost |
| | `notice_hide_after_seconds` | `20` | Notice self-deletes (`0` = keep) |
| `[storage]` | `keep_partnership_days` | `90` | Auto-delete old records (`0` = forever) |
| | `keep_point_log_days` | `30` | Auto-delete old point history |

Bad values never crash the bot — they're corrected to the default and reported by
`/diagnose` and in the startup log.

---

## Commands

There are **no setup commands** — these are all operational.

### Everyone

| Command | What it does |
|---|---|
| `/leaderboard [scope] [private]` | Paged board — **This week** (default) or **All time** |
| `/points [user]` | Weekly points, all-time points, rank, weeks won, recent history |
| `/quota check [user]` | Your weekly quota progress |
| `/week status` | Current week number, when it resets, database size |

### Staff

| Command | What it does |
|---|---|
| `/partnership list [status]` | Pending / approved / rejected submissions |
| `/partnership info id:` | Details of one partnership |
| `/partnership add invite:` | Manually open a thread for a link |
| `/partnership close` | Cancel + lock a thread *(approver)* |
| `/partnership revoke id:` | Undo a wrong approval — the bot takes its own points back *(approver)* |
| `/partnership cooldowns` | Partners currently on cooldown and when they're free |
| `/quota list` | Who has and hasn't hit quota this week |
| `/liveboard refresh` | Force the live board to update now |
| `/liveboard preview` | See the board privately |

### Manage Server

| Command | What it does |
|---|---|
| `/diagnose` | 🩺 Check config, permissions, intents |
| `/settings` | Show the currently loaded settings |
| `/reloadconfig` | Re-read `config.toml` without restarting |
| `/fixpings [server_wide]` | 🔒 Deny `@everyone` the permission to mass-ping |
| `/week reset` | Force the weekly reset early (with confirmation) |

---

## 🔴 Live leaderboard

Set `[channels] leaderboard` and the bot posts **one** message, pins it, and keeps editing it.

- Podium with 🥇🥈🥉, score bars, ranks 4+ in a compact list
- Stat strip: total points · partnerships · ranked staff
- Shows the **week number** and a live **resets in …** countdown
- **Only edits when standings actually change** — an idle server makes zero API calls
- Updates **instantly** on approval, not just on the timer
- Re-posts itself if the message is deleted; survives restarts
- Crash-proof loop

> Deny `@everyone` **Send Messages** in that channel so the board sits alone.

## 📅 Weekly reset

On the configured day/time the bot:

1. **Posts the results** to `[channels] weekly_results` — crowned winner, full standings,
   totals, next reset time, optionally pinging `[roles] weekly_ping`
2. **Zeroes the weekly scores**
3. Adds **+1** to the winner's 👑 *weeks won* counter

**Nothing is saved to disk.** Past weeks are not archived — the Discord message in your
results channel *is* the record. The only thing a finished week leaves behind is one
integer per winner. All-time points are kept in a separate table and are never touched.

**If the bot is offline at reset time it catches up on the next start** — the schedule is
stored as two numbers, so nothing is skipped and nothing double-fires.

## 🚫 Blocking @everyone

> **The honest version first:** a bot **cannot** un-send a ping. If someone has permission to
> ping `@everyone`, Discord delivers that notification the instant they hit enter. No bot,
> including this one, can recall it. Anyone who tells you otherwise is wrong.

**The only real fix is to remove the permission** — then Discord itself refuses the ping.
The text still appears, but nobody is notified.

### The bot can do this for you

```
/fixpings                     ← locks the bot's channels
/fixpings server_wide:True    ← locks every channel in the server
```

It denies **Mention @everyone, @here, and All Roles** to the `@everyone` role on your
partnership, thread, leaderboard, weekly-results and log channels. With `server_wide:True`
it also turns the permission off on the `@everyone` role itself, which covers every channel
you'll ever make.

`/diagnose` detects the hole and shows a **🔒 Lock @everyone pings for me** button right
there, so you can fix it in one click without leaving the embed.

**What the bot needs:** *Manage Permissions* on those channels, plus *Manage Roles* for
`server_wide:True`, and its own role must sit above `@everyone` (it always does). If
anything is refused it tells you exactly which channel failed and gives the manual steps:

```
Channel → Edit Channel → Permissions → @everyone
    set "Mention @everyone, @here, and All Roles" to ✗
```

**What the bot adds on top:** with the permission removed, people can still *type*
`@everyone` — it just does nothing. The filter deletes those messages anyway so the channel
stays clean, and catches anyone who gets the permission back by accident.

| Typed | Deleted? | Why |
|---|---|---|
| `hey @everyone` | ✅ | live ping |
| `@here` | ✅ | live ping (`block_here`) |
| `a@everyone.com` | ✅ | Discord pings mid-word too |
| `` `@everyone` `` | ❌ | inside code — doesn't ping |
| ` ```@everyone``` ` | ❌ | inside a code block |
| `\@everyone` | ❌ | escaped |
| `@everyonee` | ❌ | not a real mention |

If the ping did fire, the bot's warning says so explicitly and tells you to fix the
permission — it won't pretend it stopped something it didn't.

### Who is allowed to mass ping

Out of the box: **the server owner, and nobody else.** Admins, approvers and staff
all get their `@everyone` deleted like anyone else — being trusted enough to approve
partnerships is not the same as being trusted to ping 5,000 people at 3am.

| Who | Filtered? | Switch |
|---|---|---|
| **Server owner (you)** | ❌ never | `exempt_owner = true` |
| Administrators | ✅ deleted | `exempt_admins = false` |
| Approvers / higher staff | ✅ deleted | `exempt_approvers = false` |
| Staff | ✅ deleted | — |
| Everyone else | ✅ deleted | — |
| Specific people you trust | ❌ | `exempt_users = [123, 456]` |

```toml
[antiping]
enabled = true
scope = "partnership"   # or "all" for every channel
block_here = true

exempt_owner = true      # you
exempt_admins = false    # a rogue admin still gets deleted
exempt_approvers = false
exempt_users = []        # e.g. [123456789012345678]
```

Needs **Manage Messages**.

> **One honest limit.** Discord gives Administrators the `Mention @everyone` right at
> the API level and no permission setting can take it away. So an admin's ping still
> *rings* — the bot deletes the message a moment later and logs who did it. If you want
> admins truly unable to ping, the only real fix is not handing out Administrator.
> `/fixpings` stops *non-admins* at the source, which is where the risk actually is.

## 🪙 Who gets the points

Exactly two people, and nobody else:

| Who | Points | When |
|---|---|---|
| The staff member who **posted the link** | `[points] staff` (default **2**) | On approval |
| The approver who **pressed ✅ first** | `[points] approver` (default **1**) | On approval |

**Nobody can hand out points.** There is no `/pointsadmin`, no "give N points to
@someone", no way to type a number into the leaderboard. Points exist only as a
side effect of a partnership the bot itself approved, and the amounts come from
`config.toml`.

| | |
|---|---|
| Can an admin gift points? | **No** |
| Can the owner gift points? | **No** |
| Can anyone set someone's total? | **No** |
| Can anyone credit a third party? | **No** — `/partnership add` always records *you* as the poster |
| Can a mistake be fixed? | **Yes — `/partnership revoke`** |

### Fixing a mistake

`/partnership revoke id:` is the only way points ever go down, and it still isn't
manual: the bot reads its own ledger (`points_log`), reverses **exactly** what that
partnership paid out, and marks it `↩️ Revoked`. You don't type an amount — there's
no field for one. Running it twice does nothing, because the ledger already nets to
zero. The partner also drops off cooldown, since the partnership no longer counts.


The staff role is pinged in the thread, and the **first approver to press Approve
gets the point**. That click is a single atomic database write, so two people
pressing at the same moment can't both be credited — the second one gets
*"someone beat you to it."*

## 🔔 Who gets pinged

**Being added to a thread and being pinged are different things.** Staff are still
added to every private thread so they can see and help — they just don't get a
notification about it.

| | In the thread | Pinged |
|---|---|---|
| The poster | ✅ always | ✅ — they owe the screenshot |
| Approver role | ✅ | ✅ — they're the ones who have to act |
| Staff role | ❌ | ❌ |
| Everyone else | ❌ | ❌ |

**Two people-groups, nobody else:** the poster and the approvers. A private thread is
invisible to anyone who hasn't been added, so staff who aren't approvers won't even
know it exists.

```toml
[threads]
add_approver_role  = true
add_staff_role     = false   # true = staff can see threads too
max_members_added  = 40

ping_poster        = true
ping_staff_role    = false
ping_approver_role = true
```

> **One unavoidable exception:** anyone with the **Manage Threads** permission can see
> private threads whether they were added or not. That's Discord's rule, not the bot's —
> no bot can override it. If you want threads truly limited to approvers, make sure
> Manage Threads isn't handed out casually.

Approvers get pinged a **second** time when the screenshot lands, since that's the
moment Approve actually unlocks.

## 🎯 Weekly quota

Set a target and the bot tracks it automatically. **Every time a partnership is
approved**, it posts that staff member's progress in `[channels] quota`:

```
@Sam
✅ Partnership approved — 3/5 this week.
2 partnerships left to hit quota.

Progress · 3/5
██████░░░░  60%
```

And when they get there:

```
🎉 Weekly quota complete! 5 partnerships this week.
Everything from here is extra — it still counts toward the leaderboard.

Progress · 5/5
██████████  100%
```

```toml
[channels]
quota = 555555555555555555

[quota]
enabled           = true
target            = 5               # per staff member, per week
count             = "partnerships"  # or "points"
ping_member       = true
announce_complete = true            # false = channel goes quiet once they're done
```

| | |
|---|---|
| **When does it reset?** | With the weekly leaderboard — same clock, no second timer |
| **What counts?** | `partnerships` = approved partnerships you posted. `points` = points earned, so approving others also counts |
| **Who gets counted?** | The staff member who posted the link. Approvers are tracked separately |
| **Check anytime** | `/quota check` for yourself, `/quota list` for the whole staff roster |

`/quota list` splits your staff role into **✅ Hit quota** and **⏳ Still working**,
with each person's exact number — so chasing people at the end of the week is one command.

> The bot never punishes anyone for missing quota. It counts and reports; what you
> do about it is your call.

## ♻️ Duplicate links

Two people grabbing the same server is the most common way partnership channels go
wrong, so the bot dedupes by **target server**, not by invite code — `discord.gg/abc`
and `discord.gg/xyz` pointing at the same guild count as one partnership.

When a link already has an open thread:

| Who posted it | What they see | Their message |
|---|---|---|
| The original poster | ♻️ notice **with** a link to their own thread | kept |
| Anyone else | "already being handled by another staff member" — no link, no thread ID | **deleted** |

The deletion is deliberately narrow. It never touches your own re-post, and it never
touches a message that also contained a **new** link — otherwise one stale link in a
batch of three would throw away two real partnerships. Turn it off with:

```toml
[duplicates]
delete_duplicate_message = false
hide_after_seconds       = 15   # 0 = the notice never disappears
```

> Needs **Manage Messages**. The bot already asks for it, but if you stripped that
> permission the deletion silently no-ops — the notice still posts.

## 🛡️ Anti-abuse

Points are worth something, so people will try. These are the holes that were
found and closed — each one has a regression test.

| Hole | What it let someone do | Closed by |
|---|---|---|
| **Self co-credit** | Any staff member could credit *themselves* on anyone's pending partnership for free points | The whole co-credit feature was removed |
| **Proof-and-delete** | Upload any image to unlock **Approve**, delete it a second later, approve an empty thread | Deleting the proof message clears it, re-locks Approve, pings the poster in-thread and logs it |
| **Link as proof** | Paste a link to *someone else's* approved screenshot — it rendered as an embed and counted | `attachment_only = true`: only real uploads count |
| **Double approve** | Two approvers clicking at the same instant both passed the status check → points awarded twice | Approve/reject are a single atomic `UPDATE … WHERE status='pending'`; the loser gets "someone beat you to it" |
| **Reject after approve** | The reject modal never re-checked status, so submitting a stale one overwrote an approval | Same atomic claim, plus the modal re-checks the approver role on submit |
| **Open `/liveboard refresh`** | Anyone could spam board rebuilds | Staff only |
| **`guild_id = 0`** | Anyone who got the invite link could add the bot elsewhere and run it | Startup warning until you set your server ID |

### What is still possible, by design

- **Partnering with your own alt server.** The bot can't tell a real partner from
  one you made. The cooldown slows it to once per server per 24h; the approver is
  the actual check.
- **A forged screenshot.** No bot can verify a PNG. That's what human approval is for.
- **An unresolvable invite.** If Discord won't resolve an invite, dedupe falls back
  to the raw code — so two different codes for one server could both get threads.
  The cooldown still catches it later by server name.

## 🗑️ Cleanup after a decision

Partnership threads are temporary — once a decision is made they go away.

| | Approved | Rejected |
|---|---|---|
| Points | awarded | none |
| Thread | deleted after 15s | deleted after 15s |
| Original ad in the channel | **kept** | **deleted** |
| Partner cooldown | starts (24h) | not started |
| Record kept in `#logs` | yes | yes, with the reason |

The bot posts a `🗑️ This thread will be deleted in 15 seconds` countdown first so nobody
loses the result mid-read. On rejection the poster is **pinged in the log channel** with the
reason, because the thread they'd normally read it in is about to vanish.

> ⚠️ **Set `[channels] logs`.** Once threads are deleted, the log message is your only
> record. The bot warns you at startup and in `/diagnose` if you enable deletion without a
> log channel.

Needs **Manage Threads** (delete threads) and **Manage Messages** in the partnership channel
(delete the rejected ad). If either is missing, the bot says so instead of failing silently.

**Deleting the thread does not cancel the cooldown** — approved partnerships keep their
status, so a partner stays locked for the full 24h even though their thread is gone. If the
bot restarts during the grace period, a sweep finishes the deletion on the next tick.

Turn any of it off:

```toml
[on_decision]
delete_thread_on_approve = false   # keep approved threads as an archive
delete_thread_on_reject  = true
delete_thread_after_seconds = 60   # longer grace period
delete_ad_on_reject = true
```

## ⏳ Partner cooldown

When a partnership is **approved**, that partner server is locked for
`[cooldown] hours` (default 24).

If anyone posts their invite again during that window, the bot **deletes the message first**,
then replies with how long is left:

> ⏳ **Gaming Hub** was already partnered 3 hours ago.
> 🕒 You can partner with them again in 21 hours
> ⏱️ Time left: **21h**

Matching catches **all** of these, so people can't slip past it:

| Trick | Caught by |
|---|---|
| Same invite link | invite code |
| A **different** invite code for the same server | resolved target server ID |
| Invite expired / unresolvable | server name match |

It applies to **everyone** — the original poster and any other staff.

> ⚠️ Deletion needs **Manage Messages** in the partnership channel. The bot deletes as fast
> as it can, but it cannot un-send a ping Discord already delivered — if the message had
> `@everyone` in it, that ping still fires. The message itself is removed either way, and
> the notice says so if deletion failed.

`/partnership cooldowns` lists everyone currently locked.

## 💾 Storage

Built for free hosts with tiny disks. Five tables, no per-week files, nothing duplicated.

Measured with a full year of heavy use (1,040 approved partnerships, 30 staff, 600 point-log
entries):

| | Size |
|---|---|
| After 1 year | **220 KB** |
| After the automatic 90-day prune | **128 KB** |

Once a day the bot deletes finished partnership records older than
`keep_partnership_days` and point-log rows older than `keep_point_log_days`, then runs
`VACUUM` to actually reclaim the space. Pending partnerships, all-time points and the
cooldown window are never pruned. Set either to `0` to keep forever.

`/week status` shows the current database size.

---

## Deploying 24/7

> ⚠️ The database `data/partnership.db` holds all points and archives. Host it somewhere
> with **persistent disk**.

**Discloud / HeavenCloud / bot-hosting.net** (`discloud.config` included): upload the folder,
set `DISCORD_TOKEN` in the panel, leave `KEEP_ALIVE` unset, start with `python bot.py`.

**Oracle Cloud / VPS:**

```bash
sudo tee /etc/systemd/system/pbot.service <<'EOF'
[Unit]
Description=Partnership Bot
After=network.target

[Service]
WorkingDirectory=/home/ubuntu/partnership-bot
ExecStart=/home/ubuntu/partnership-bot/.venv/bin/python bot.py
EnvironmentFile=/home/ubuntu/partnership-bot/.env
Restart=always
RestartSec=10
User=ubuntu

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now pbot
journalctl -u pbot -f
```

**Render free:** the disk is wiped on every restart, so points and week archives are lost.
Only use it with an external database. If you must: `KEEP_ALIVE=true` + an UptimeRobot
monitor every 5–10 min.

### Backups

```bash
sqlite3 data/partnership.db ".backup 'backup-$(date +%F).db'"
```

---

## Tests

No Discord connection needed — invite parsing, config validation, points maths, weekly
scheduling across timezones, archive/reset cycles, button states, and command registration:

```bash
python -m tests.test_bot      # 333 checks
```

## Notes & limits

- Staff **can't approve their own** partnership.
- Invites pointing at **your own server** are ignored.
- Max **5 links processed per message**.
- A reposted link **never** leaks another staff member's thread.
- Anyone with **Manage Server** counts as an approver, as a fallback.
- The bot only acts in the server matching `guild_id`.
- Rejected and cancelled partnerships do **not** start a cooldown — only approvals do.
- Deleting a thread never cancels a cooldown; only *pending* partnerships are cancelled
  when their thread disappears.
- The bot itself **never** sends `@everyone` — all of its messages are posted with
  `everyone=False`, so it physically cannot mass-ping.
- `keep_partnership_days` is automatically raised if it would ever be shorter than your
  cooldown window.
