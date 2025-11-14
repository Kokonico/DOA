import classes
import ollama_model_interface
import chatcompletions_interface
import constants
import re

import discord
from discord import app_commands

conversations: dict[int, classes.Conversation] = {}

use_remote = True # Set to False for local model interface

def main() -> None:
    # Initialize Discord client
    intents = discord.Intents.default()
    intents.message_content = True
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
        if not isinstance(message.channel, discord.DMChannel) and client.user not in message.mentions and not message.reference:
            return # Ignore messages that don't mention the bot in guild channels or reply to it

        # replace the mention with username
        if not isinstance(message.channel, discord.DMChannel):
            mention_str = f'<@{client.user.id}>'
            message.content = message.content.replace(mention_str, 'DOA').strip()
            # grab all mentions of any kind and strip the userid's out
            # then lookup the username for each mention and replace it
            mention_pattern = r'<@?(\d+)>'
            mentions = re.findall(mention_pattern, message.content)
            for mention_id in mentions:
                user = await client.fetch_user(int(mention_id))
                if user:
                    mention_str = f'<@{mention_id}>'
                    message.content = message.content.replace(mention_str, f'@{user.name}').strip()

        if message.reference:
            # fetch the referenced message
            try:
                ref_message = await message.channel.fetch_message(message.reference.message_id)
                # prepend the content of the referenced message to the current message
                message.content = f"(replying to: {ref_message.author.name}: {ref_message.content}) {message.content}"
            except Exception as e:
                constants.MAIN_LOG.log(constants.Warn(f'Failed to fetch referenced message: {e}'))

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
        conversation.add_message(user_message)

        # Generate response from model
        # make bot begin typing
        async with message.channel.typing():
            anton_response = model.generate_response(conversation)
            conversation.add_message(anton_response)

        # because the AI model is stupid, sometimes it includes the username in the response, we have to strip it out (strip out all text at beginning that matches "Daughter of Anton: ")
        # keep in mind, sometimes it puts several (ex: "Daughter of Anton: Daughter of Anton: How can I help you?")
        while anton_response.content.startswith("Daughter of Anton: "):
            anton_response.content = anton_response.content[len("Daughter of Anton: "):].strip()

        # Send response back to Discord
        await message.channel.send(anton_response.content, reference=message)
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