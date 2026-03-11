# AGENTS.md

## Big picture
- `main.py` is the runtime entrypoint. It creates global SQLite managers for `DOA.db` and `cache.db`, picks the model backend from `constants.use_remote`, and wires Discord events plus slash commands.
- Request flow in `main.py`: `on_message()` -> `swap_mentions()` -> `convert_message()` -> `ConversationDatabaseManager.load_conversation()` -> add up to 10 prior non-bot/non-mention channel messages as transient context -> optional `Conversation.run_moderations()` -> backend `generate_response()` -> strip accidental `"Daughter of Anton: "` prefixes -> `split_message()` for Discord’s 2000-char limit -> send chained replies -> `conversation.clear_context()` -> save back to SQLite.
- `classes.py` defines the internal message graph: `Conversation` stores sorted `Message` / `AntonMessage` objects, and `Message.__str__()` is the canonical prompt serialization format, including reply chains as `(replying to: ...) author\\/\\nick: content`.
- Persistence is channel-scoped in `databases.py`: the Discord channel ID is the conversation ID. Context messages are never persisted; attachments and moderation rows are persisted alongside messages.
- `cache.db` is not conversation history: `DiscordDataCacher` only caches Discord user ID <-> username mappings so mention swapping can work without always refetching users.

## Backends and integrations
- Default backend is remote: `constants.use_remote = True`, so `chatcompletions_interface.ChatCompletions` sends to `${REMOTE_SOURCE_URL}/v1/chat/completions` and moderation goes to `${REMOTE_SOURCE_URL}/v1/moderations`.
- Local backend is `ollama_model_interface.OllamaModel`; switch by setting `constants.use_remote = False`. It talks to a local `ollama.Client()` and expects `ollama serve` plus the model named by `constants.OLLAMA_MODEL_NAME`.
- `responses_interface.py` exists but is explicitly marked `# TODO: very broken!` and is not wired into `main.py`; do not treat it as a supported path unless you are fixing that adapter.
- Attachment handling is intentionally asymmetric: `convert_message()` reads every Discord attachment into typed classes, but only the newest user message’s attachments are serialized to the remote API. Older/history attachments are represented only by the `[Attachment (type: ..., filename: ...)]` text marker from `Message.string_no_reply()`.

## Configuration and conventions
- Most runtime config lives in `constants.py`, not `.env`. `.env` is only for `DOA_DISCORD_BOT_TOKEN` and `DOA_REMOTE_API_KEY`; model names, feature flags, remote URL, moderation toggle, and prompt behavior are hard-coded in `constants.py`.
- Importing `constants.py` exits the process if `DOA_DISCORD_BOT_TOKEN` is unset. Any script or smoke test that imports project modules needs that env var present.
- `constants.system_prompt()` is dynamic: it embeds uptime, current date/time, platform info, Python version, model name, and behavior rules. Editing it changes both remote and Ollama behavior immediately.
- Respect `constants.DOA_FEATURE_FLAGS` when changing attachment handling; both `chatcompletions_interface.py` and `responses_interface.py` gate multimodal payload pieces through those flags.
- Logging is centralized through `constants.MAIN_LOG`, `constants.REMOTE_LOG`, and `constants.OLLAMA_LOG` via `objlog`; follow that pattern instead of adding ad-hoc prints.

## Working in this repo
- Setup/run flow from `README.md`:
  ```bash
  poetry install
  poetry run python main.py
  ```
- For local-model work, also run:
  ```bash
  ollama serve
  ```
- No automated test suite was found. Validate changes with targeted smoke checks and, for behavior changes, a manual Discord bot run.
- Keep raw Discord objects at the edge (`main.py`). Downstream code expects the internal `classes.Message` / `Conversation` model, not `discord.Message` instances.
- Mention formatting is fragile and important: prompts use `<@username>` text, Discord delivery uses numeric mentions, and `swap_mentions()` + `DiscordDataCacher` bridge the two. Changes there affect both prompt quality and outbound pings.
- Preserve the channel-history contract: `/induce_dementia` clears stored conversation for one channel, `/nuke_bot_messages` also purges the bot’s sent messages in that channel, and `clear_context()` prevents the transient 10-message context window from being saved.
- Preserve `split_message()` behavior if you touch outbound formatting; it is the only place handling Discord’s 2000-character message limit while keeping multi-part replies threaded.

