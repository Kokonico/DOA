import classes
import ollama_model_interface
import chatcompletions_interface
import constants
import re
import asyncio

import discord
from discord import app_commands

conversations: dict[int, classes.Conversation] = {}

use_remote = constants.use_remote

async def swap_mentions(content: str, client: discord.Client, message: discord.Message) -> str:
    # find all mentions of the form <@username> into proper mention format, and proper mention format into <@username>
    # main difference is prop. mentions are only integers, while the other form is username (alphanumeric)
    # just find all mentions (both forms) and swap them
    mention_pattern_generic = r'<@!?(\d+|[a-zA-Z0-9_]+)>'
    mentions = re.findall(mention_pattern_generic, content)
    if mentions:
        constants.MAIN_LOG.log(constants.Debug(f'Found mentions to swap: {mentions}'))
    for mention in mentions:

        # check if it's a DOA mention, if so, replace with <@DOA>
        if mention == str(client.user.id):
            content = content.replace(f'<@{client.user.id}>', f'<@{client.user.name}>').strip()
            continue

        if mention.isdigit():
            # proper mention format, swap to username
            try:
                user = await client.fetch_user(int(mention))
                if user:
                    mention_str = f'<@{mention}>'
                    content = content.replace(mention_str, f'<@{user.name}>').strip()
            except discord.errors.NotFound:
                constants.MAIN_LOG.log(constants.Warn(f'User with ID {mention} not found for mention swap.'))
                continue
        else:
            # username format, swap to proper mention
            if isinstance(message.channel, discord.DMChannel):
                user = None
                for member in client.users:
                    if member.name == mention:
                        user = member
                        break
            else:
                user = discord.utils.get(message.guild.members, name=mention)
            if user:
                mention_str = f'<@{mention}>'
                content = content.replace(mention_str, f'<@{user.id}>').strip()
    return content


def split_message(content: str, max_length: int = 2000) -> list[str]:
    if len(content) <= max_length:
        return [content]

    parts: list[str] = []
    first = True
    remaining = content

    while remaining:
        prefix = "" if first else "..."
        # if the rest fits with the prefix, it's the last chunk
        if len(remaining) <= max_length - len(prefix):
            parts.append(prefix + remaining)
            break

        # reserve space for prefix and trailing "..."
        suffix = "..."
        body_max = max_length - len(prefix) - len(suffix)
        # try to split at the last space within body_max
        cut = remaining.rfind(' ', 0, body_max + 1)
        if cut == -1:
            cut = body_max
        chunk_body = remaining[:cut].rstrip()
        parts.append(prefix + chunk_body + suffix)
        remaining = remaining[cut:].lstrip()
        first = False
    return parts

def main() -> None:
    # Initialize Discord client
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    model = ollama_model_interface.OllamaModel(name=constants.OLLAMA_MODEL_NAME, system_prompt=None) if not use_remote else chatcompletions_interface.ChatCompletions(system_prompt=None, api_key=constants.REMOTE_AUTH_API_KEY)

    @client.event
    async def on_ready():
        constants.MAIN_LOG.log(constants.Info('Bot is ready. Syncing commands...'))
        await tree.sync()
        constants.MAIN_LOG.log(constants.Info(f'Logged in as {client.user}'))

    @client.event
    async def on_message(message: discord.Message):
        if message.author == client.user:
            return  # Ignore messages from the bot itself
        # Only respond to messages that mention the bot in guild channels, or any message in DMs, or replies to the bot SPECIFICALLY
        replies_to_bot = False
        ref_message = None
        if message.reference:
            try:
                ref_message = await message.channel.fetch_message(message.reference.message_id)
                if ref_message.author == client.user:
                    replies_to_bot = True
            except Exception as e:
                constants.MAIN_LOG.log(constants.Warn(f'Failed to fetch referenced message: {e}'))
        if not isinstance(message.channel, discord.DMChannel) and client.user not in message.mentions and not replies_to_bot:
            return # Ignore messages that don't mention the bot in guild channels or reply to it

        # swap mentions in message content
        message.content = await swap_mentions(message.content, client, message)

        constants.reload_system_prompt()

        if ref_message:
                message.content = f"(replying to: {ref_message.author.name}: {ref_message.content}) {message.content}"
        # Get or create conversation for the channel
        if message.channel.id not in conversations:
            conversations[message.channel.id] = classes.Conversation()
        conversation = conversations[message.channel.id]

        constants.MAIN_LOG.log(constants.Info(f'Received message from {message.author}: {message.content}'))

        # Add user message to conversation
        user_person = classes.Person(name=message.author.name)
        user_message = classes.Message()
        user_message.content = message.content
        user_message.author = user_person
        user_message.timestamp = message.created_at.timestamp()
        user_message.context = False
        temp_conv = classes.Conversation()
        temp_conv.messages = conversation.messages.copy()
        temp_conv.add_message(user_message)

        if not isinstance(message.channel, discord.DMChannel):
            # pull context messages (past 5 messages in the channel not mentioning or involving the bot)
            async for msg in message.channel.history(limit=10, before=message.created_at):
                if msg.author == client.user:
                    continue
                if client.user in msg.mentions:
                    continue
                if msg == message:
                    continue
                # add to conversation history
                if msg.reference:
                    try:
                        ref_msg = await message.channel.fetch_message(msg.reference.message_id)
                        msg.content = f"(replying to: {ref_msg.author.name}: {ref_msg.content}) {msg.content}"
                    except Exception as e:
                        constants.MAIN_LOG.log(constants.Warn(f'Failed to fetch referenced message for context: {e}'))
                context_person = classes.Person(name=msg.author.name)
                context_message = classes.Message()
                msg.content = await swap_mentions(msg.content, client, message)
                context_message.content = msg.content
                context_message.author = context_person
                context_message.timestamp = msg.created_at.timestamp()
                context_message.context = True
                temp_conv.add_message(context_message)

        # Generate response from model
        # make bot begin typing
        async with message.channel.typing():
            try:
                anton_response = await asyncio.to_thread(model.generate_response, temp_conv)
                # add both user message and bot response to conversation
                conversation.add_message(user_message)
                conversation.add_message(anton_response)
            except Exception as e:
                constants.MAIN_LOG.log(constants.Error(f'Error generating response: {e}'))
                await message.channel.send("I unfortunately encountered an error while trying to respond :(", reference=message if not isinstance(message.channel, discord.DMChannel) else None)
                return

        # because the AI model is stupid, sometimes it includes the username in the response, we have to strip it out (strip out all text at beginning that matches "Daughter of Anton: ")
        # keep in mind, sometimes it puts several (ex: "Daughter of Anton: Daughter of Anton: How can I help you?")
        while anton_response.content.startswith("Daughter of Anton: "):
            anton_response.content = anton_response.content[len("Daughter of Anton: "):].strip()

        anton_response.content = await swap_mentions(anton_response.content, client, message)
        # verify anton_response is under 2000 characters, if not, send multiple messages, each chain-responded (also add "..." at the end of each message except the last, as well as "..." at the beginning of each message except the first)
        # split into chunks of 2000 characters or fewer
        max_length = 2000
        messages = split_message(anton_response.content, max_length)

        # Send response(s) back to Discord
        prev = message
        for content in messages:
            content = "." if content == "" else content
            prev = await message.channel.send(content, reference=prev if not isinstance(message.channel, discord.DMChannel) else None)

        # clear context messages
        conversation.clear_context()

        constants.MAIN_LOG.log(constants.Info(f'Sent response: {anton_response.content}'))
        constants.MAIN_LOG.log(constants.Debug(f'Current conversation state: {[{"author": msg.author.name, "content": msg.content} for msg in conversation.messages]}'))

    @tree.command(name="induce_dementia", description="Make DOA forget the conversation history for this channel.")
    async def i_forgot(interaction: discord.Interaction):
        if interaction.channel_id in conversations:
            del conversations[interaction.channel_id]
        await interaction.response.send_message("I've forgotten our conversation history. Let's start fresh!", ephemeral=True)

    @tree.command(name="nuke_bot_messages", description="Completely delete the bot's conversation history and messages for this channel.")
    async def nuke_bot_messages(interaction: discord.Interaction):
        # check if i have manage_messages permission in this channel
        if isinstance(interaction.channel, discord.DMChannel):
            await interaction.response.send_message("This command cannot be used in direct messages.", ephemeral=True)
            return

        permissions = interaction.channel.permissions_for(interaction.guild.me)
        if not permissions.manage_messages:
            await interaction.response.send_message("I don't have permission to manage messages in this channel.", ephemeral=True)
            return
        if interaction.channel_id in conversations:
            del conversations[interaction.channel_id]
        # Delete bot messages in the channel
        def is_bot_message(msg: discord.Message) -> bool:
            return msg.author == client.user

        deleted = await interaction.channel.purge(check=is_bot_message)
        # no confirmation message, just silently delete, it'll be obvious
        constants.MAIN_LOG.log(constants.Info(f'Nuked {len(deleted)} bot messages'))


    # Run the Discord bot
    client.run(constants.DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    main()