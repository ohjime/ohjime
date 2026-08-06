# telegram-dump-summarizer

A private Telegram bot inbox for thoughts and actions, backed by SQLite and
summarized once a day by a local Google ADK/vLLM agent.

```text
Telegram client
    │  t: a thought     a: an action
    ▼
private bot chat
    │  continuous Bot API long polling
    ▼
telegram_collector.py ──► /var/lib/ohjime/messages.db
                                  │
                                  │  10:00 PM America/Edmonton
                                  ▼
                            summarize.py
                                  │
                                  ▼
                    ADK → LiteLLM → local vLLM
```

Collection is continuous because Telegram does not expose arbitrary bot-chat
history and queued updates are not a durable archive. Processing is separate:
the systemd timer wakes the summarizer at 10:00 PM and the collector keeps
accepting messages while it runs.

## Message format

Send messages directly to the private bot using any of these forms:

```text
t: Maybe this design should use SQLite
thought: Maybe this design should use SQLite
/thought Maybe this design should use SQLite

a: Implement the Telegram collector
action: Implement the Telegram collector
/action Implement the Telegram collector
```

`/t` and `/a`, including commands addressed as `/t@YourBot`, work too. Prefixes
are removed before text reaches the agent.

Private-chat topic IDs are optional. If `THOUGHT_THREAD_ID` and
`ACTION_THREAD_ID` are configured, the topic decides the type and a prefix is
not required. Topic classification takes precedence over a conflicting prefix.
Messages without a recognized prefix or topic are retained as `unknown`, so
they are not lost.

Only the configured numeric user ID in the configured numeric chat ID is
stored. Usernames are intentionally not used because they can change.

## Ubuntu installation

The installer uses the existing Ubuntu/systemd stack and runs services as the
normal user who invokes `sudo`:

```bash
git clone <this-repo> ohjime
cd ohjime
make setup
```

On the first run it installs FFmpeg (required by TorchCodec), the Python
environments, vLLM service, collector, and daily processor units. It creates
`/etc/ohjime/telegram.env` with
placeholders, then leaves the collector and timer disabled so invalid
credentials cannot enter a restart loop.

Create a bot with [BotFather](https://t.me/BotFather) on your Mac and copy the
token it gives you. Then run the interactive Ubuntu configuration command:

```bash
make telegram-env
```

It securely prompts for the token, asks you to send a test message to the bot
from your Mac containing a generated one-time phrase, discovers the numeric
user and chat IDs from that exact message, asks for confirmation, and writes
`/etc/ohjime/telegram.env` as `root:root` with mode `0600`. The token is not
echoed or placed in shell history. Run this before sending real notes: older
pending setup-era updates are acknowledged while it searches for the one-time
phrase. On later reconfiguration it pauses an active collector to avoid
competing Bot API pollers, restoring it automatically if configuration is
cancelled or fails.

Activate Telegram ingestion after the command succeeds:

```bash
make run
```

The activation command validates the token shape and numeric IDs, enables the
collector, and enables the 10:00 PM timer without restarting the model server.
It also registers `/thought` and `/action` in the configured chat's Telegram
command menu. Each command and its content belong in one message, for example
`/thought Consider grouping related notes`. To refresh only the command menu,
run `make telegram-commands`. The menu uses ✍ and 👍 labels, and the collector
reacts to each stored thought with ✍ and each stored action with 👍. Reactions
are cosmetic: an unavailable reaction never prevents SQLite storage.
The collector calls `deleteWebhook` with
`drop_pending_updates=false` at startup because Bot API webhooks and long
polling are mutually exclusive.

Installed components:

| Component | Location or unit |
| --- | --- |
| Telegram secrets/config | `/etc/ohjime/telegram.env` (root-only, mode `0600`) |
| SQLite database | `/var/lib/ohjime/messages.db` |
| Continuous collector | `ohjime-telegram-collector.service` |
| Daily processor | `ohjime-summarizer.service` |
| 10 PM Edmonton schedule | `ohjime-summarizer.timer` |
| Model server | `ohjime-vllm.service` |
| Model server config | `/etc/ohjime/vllm.env` |

Validate and inspect the deployment with:

```bash
systemd-analyze calendar '*-*-* 22:00:00 America/Edmonton'
systemctl status ohjime-telegram-collector
systemctl list-timers ohjime-summarizer.timer
journalctl -u ohjime-telegram-collector -f
journalctl -u ohjime-summarizer -f
```

Run the daily processor immediately with:

```bash
sudo systemctl start ohjime-summarizer
```

Uninstall units while retaining configuration, model environments, and the
message database:

```bash
sudo ./deploy/uninstall.sh
```

`--purge` additionally removes `/etc/ohjime` and the vLLM environment, but the
personal database under `/var/lib/ohjime` is deliberately still preserved.

## Configuration

`/etc/ohjime/telegram.env` contains:

| Variable | Default | Meaning |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | required | Token issued by BotFather. |
| `ALLOWED_USER_ID` | required | Only this numeric sender is accepted. |
| `ALLOWED_CHAT_ID` | required | Only this numeric private chat/group is accepted. |
| `DB_PATH` | `/var/lib/ohjime/messages.db` | Shared collector/processor SQLite file. |
| `LOCAL_TIMEZONE` | `America/Edmonton` | Timezone used in the agent payload. |
| `MAX_BATCH_BYTES` | `12000` | Model/batch input limit in bytes (minimum `512`). |
| `THOUGHT_THREAD_ID` | unset | Optional Thoughts topic ID. |
| `ACTION_THREAD_ID` | unset | Optional Actions topic ID. |

For testing against a local Bot API server, `TELEGRAM_API_ROOT` can replace
`https://api.telegram.org`. `TELEGRAM_POLL_TIMEOUT` and
`TELEGRAM_REQUEST_TIMEOUT` default to 50 and 65 seconds respectively.

The model client settings remain in the project `.env`:

| Variable | Default |
| --- | --- |
| `VLLM_API_BASE` | `http://localhost:8000/v1` |
| `VLLM_MODEL` | `Qwen/Qwen3-8B-AWQ` |
| `VLLM_API_KEY` | `EMPTY` |
| `VLLM_ENABLE_THINKING` | `false` |

The installed vLLM server binds to `127.0.0.1` by default. If you change its
port in `/etc/ohjime/vllm.env`, update `VLLM_API_BASE` in the project `.env` as
well; both the readiness check and ADK client use that project value.

## Manual development

Install the app and development dependencies:

```bash
cd manage/src
cp .env.example .env
uv sync
```

Run the collector with a local database:

```bash
export TELEGRAM_BOT_TOKEN='123456789:replace_with_real_token'
export ALLOWED_USER_ID='123456789'
export ALLOWED_CHAT_ID='123456789'
export DB_PATH="$PWD/messages.db"
uv run telegram_collector.py
```

In another shell, drain the queue (the local vLLM endpoint must be running):

```bash
DB_PATH="$PWD/messages.db" uv run summarize.py
DB_PATH="$PWD/messages.db" uv run summarize.py --dry-run
```

`--dry-run` calls the model but intentionally leaves the stable batch queued.
The next real run receives the same messages and batch ID.

## Delivery and retry semantics

The SQLite schema stores the complete raw Telegram message alongside normalized
text, content type, IDs, timestamps, batch state, and processing state.

- An authorized insert and `next_offset = update_id + 1` commit atomically.
- Ignored updates still advance the offset, so they cannot block polling.
- `(chat_id, message_id)` is unique, making duplicate delivery harmless.
- Edits update only unclaimed, unprocessed messages.
- A daily run first resumes an incomplete batch; otherwise it claims a
  chronological slice capped by `MAX_BATCH_BYTES`. At least one message is
  always claimed, so an individual entry cannot permanently stall the queue.
- If that individual normalized input exceeds the conservative model chunk
  size, it is summarized in UTF-8-safe pieces and those partials are synthesized
  into one stored batch result; the complete original remains in SQLite.
- The same run keeps claiming context-sized chunks until its startup snapshot
  is empty. If a chunk fails, that stable batch remains queued and the run
  stops; already completed chunks stay complete.
- The processor snapshots the highest pending SQLite row at startup. Messages
  arriving while it runs remain unclaimed for the next scheduled or manual run.
- Rows receive `processed_at` only after the ADK function returns successfully.

Each validated summary and its tags are stored in the `batches` table in the
same transaction that marks its messages processed. They are also written to
stdout, which systemd retains in the `ohjime-summarizer` journal. For example:

```bash
sqlite3 /var/lib/ohjime/messages.db \
  'SELECT batch_id, summary, tags_json, processed_at FROM batches ORDER BY created_at DESC;'
```

Sending the result back through `sendMessage` can be added later without
changing ingestion; use the stable `batch_id` as an idempotency key for any
future external side effect.

Photos, voice notes, documents, and other media are retained in `raw_json` with
their content type. The current text-only agent sees their caption, or an
attachment placeholder when no caption exists; downloading or transcribing
media is intentionally outside this first version.

## Security boundary

This bot can collect messages sent directly to it or messages it is allowed to
see in a group. It cannot read Telegram Saved Messages or unrelated private
conversations. A group bot must be an administrator or have privacy mode
disabled to receive ordinary group messages.

The database contains personal message bodies and raw Telegram metadata. Its
directory is mode `0700`, service-created files use a restrictive umask, and
the bot token remains in a root-only environment file. The unauthenticated
vLLM endpoint is loopback-only by default rather than exposed to the LAN.

## Tests and layout

```bash
uv run pytest -q
uv run ruff check .
bash -n deploy/install.sh deploy/uninstall.sh
```

```text
manage/src/
├── ubuntu_commands.py         # reliable setup/configure/run command dispatcher
├── configure_telegram_env.py  # interactive token/ID discovery and protected config
├── register_telegram_commands.py # install /thought and /action in Telegram
├── telegram_collector.py       # continuous Bot API long poller
├── telegram_store.py           # SQLite schema, ingestion, batches, payloads
├── summarize.py                # scheduled SQLite batch → ADK orchestration
├── wait_for_vllm.py            # cold-boot readiness using the ADK endpoint config
├── vllm_agent/agent.py         # local LiteLLM/vLLM summarizer agent
├── deploy/
│   ├── install.sh
│   ├── telegram.env.example
│   ├── ohjime-telegram-collector.service
│   ├── ohjime-summarizer.service
│   ├── ohjime-summarizer.timer
│   └── ohjime-vllm.service
└── tests/
```

The default `Qwen/Qwen3-8B-AWQ` configuration remains tuned for the existing
11 GB RTX 2080 Ti: Python 3.12, `vllm==0.25.0`, float16, eager mode, and a 16K
model context. Summarization is text-in/text-out and does not require vLLM tool
calling flags.
