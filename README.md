# Daughter of Anton
> stupid ai bot for discord

## Features
- Talking to people

## How to set up
1. Install [Python and pip](https://www.python.org/downloads/)
2. Install [Ollama](https://ollama.com/download) and run the `ollama serve` command to start the local API server.
3. Install poetry
4. Install dependencies
    ```bash
    poetry install
    ```
5. Create a Discord bot and get its token from the [Discord Developer Portal](https://discord.com/developers/applications)
6. Create a `.env` file in the project root with the following content:
   ```env
   DOA_DISCORD_BOT_TOKEN=your_bot_token_here
   DOA_REMOTE_API_KEY=your_openai_api_key_here
    ```
7. edit constants.py to set your bot's command prefix, model type, remote URL, and other settings.
8. apply the .env and run the bot
    ```bash
    poetry run python main.py
    ```
9. Invite the bot to your Discord server using the OAuth2 URL generated in the Discord Developer Portal.
10. Enjoy chatting with your new bot!

## Commands
`/induce_dementia` - Resets the bot's knowledge
`/nuke_bot_messages` - Deletes all messages sent by the bot in the current channel
