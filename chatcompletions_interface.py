import base64

import objlog.utils

import classes
import constants
import requests

from objlog.LogMessages import Info, Debug, Error, Warn

from classes import PDFAttachment
from constants import MAIN_LOG, REMOTE_LOG


class ChatCompletions(classes.Model):
    """A language model that uses chat/completions interface for generating responses."""

    name: str = constants.REMOTE_MODEL_NAME
    source_url: str = constants.REMOTE_SOURCE_URL
    api_key: str | None = None

    def __init__(
            self,
            api_key: str | None,
            name: str | None = None,
            system_prompt: str | None = None,
            api_source: str | None = None,
    ) -> None:
        super().__init__(name, system_prompt)
        self.api_key = api_key
        self.source_url = api_source if api_source else self.source_url

    # @objlog.utils.monitor(REMOTE_LOG, True, True)
    def generate_response(
            self, conversation: classes.Conversation
    ) -> classes.AntonMessage:
        """Generate a response using the chat/completions interface based on the conversation history."""
        constants.REMOTE_LOG.log(
            Info("Generating response using Chat Completions interface.")
        )

        # prepare headers
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # anti-goon technology

        if constants.ENABLE_MODERATION:
            constants.REMOTE_LOG.log(Info("Starting moderation check for conversation."))
            # run messages through moderation endpoint
            # message.moderation is only set for messages that have already been moderated, don't re-moderate those
            messages_to_moderate = [msg for msg in conversation.messages if not isinstance(msg, classes.AntonMessage) and not msg.moderation.flagged]
            # rest of types are ignored for moderation for now (unsupported)

            # look for words in the wordlist first
            for word in constants.MODERATION_WORDLIST:
                for msg in messages_to_moderate:
                    if word in msg.content.lower():
                        constants.REMOTE_LOG.log(
                            Warn("Message flagged by wordlist moderation."),
                            Warn(f"Flagged word: {word}")
                        )
                        msg.moderation.flagged = True
                        msg.moderation.Categories.banned_word = word

            # jsonify!
            jsonfied_messages = []
            message_sizes = []

            constants.REMOTE_LOG.log(Info(f"Moderating {len(messages_to_moderate)} messages."))

            for msg in messages_to_moderate:
                size = 1
                if not msg.moderation.flagged:
                    msg_json = {
                        "type": "text",
                        "text": msg.content
                    }
                    messages_to_moderate_json = [msg_json]
                    for attachment in msg.attachments:
                        # only text attachments are supported for moderation for now
                        if isinstance(attachment, classes.TextAttachment):
                            messages_to_moderate_json.append({
                                "type": "text",
                                "text": attachment.data.decode('utf-8')
                            })
                            size += 1  # each text attachment counts as 1 extra unit
                        elif isinstance(attachment, classes.ImageAttachment):
                            messages_to_moderate_json.append({
                                "type": "image_url",
                                "image_url": {"url": attachment.url}
                            })
                            size += 1  # images count as 1 extra unit
                    for _ in range(size):
                        message_sizes.append(msg)

                    jsonfied_messages.append(messages_to_moderate_json)

            # flatten the list
            # each attachment is a separate input to moderation endpoint
            new_messages_to_moderate = []
            for msg_list in jsonfied_messages:
                for msg in msg_list:
                    new_messages_to_moderate.append(msg)

            REMOTE_LOG.log(Info(f"Sending {len(new_messages_to_moderate)} items to Moderations API for moderation."))

            response = requests.post(
                self.source_url + "/v1/moderations",
                headers=headers,
                json={"input": new_messages_to_moderate},
                timeout=constants.REMOTE_TIMEOUT_SECONDS
            )
            constants.REMOTE_LOG.log(Info("Sent moderation request to Moderations API."))
            if response.status_code != 200:
                constants.REMOTE_LOG.log(
                    Error(
                        f"Error from Moderations API: {response.status_code} - {response.text}"
                    )
                )
                raise Exception(f"Moderations API error: {response.status_code}")
            constants.REMOTE_LOG.log(Info("Received response from Moderations API."))
            results = response.json()["results"]
            MAIN_LOG.log(Debug(f"Moderation results: {results}"))
            for index, result in enumerate(results):
                msg = message_sizes[index]
                # note: only override if false, if true but new result is false, keep true
                if result["flagged"]:
                    msg.moderation.flagged = True
                    msg.moderation.categories.harassment = result["categories"]["harassment"] if not msg.moderation.categories.harassment else True
                    msg.moderation.categories.harassment_threats = result["categories"]["harassment/threatening"] if not msg.moderation.categories.harassment_threats else True
                    msg.moderation.categories.sexual_content = result["categories"]["sexual"] if not msg.moderation.categories.sexual_content else True
                    msg.moderation.categories.hate = result["categories"]["hate"] if not msg.moderation.categories.hate else True
                    msg.moderation.categories.hate_threat = result["categories"]["hate/threatening"] if not msg.moderation.categories.hate_threat else True
                    msg.moderation.categories.illicit = result["categories"]["illicit"] if not msg.moderation.categories.illicit else True
                    msg.moderation.categories.illicit_violent = result["categories"]["illicit/violent"] if not msg.moderation.categories.illicit_violent else True
                    msg.moderation.categories.self_harm_intent = result["categories"]["self-harm/intent"] if not msg.moderation.categories.self_harm_intent else True
                    msg.moderation.categories.self_harm_instruction = result["categories"]["self-harm/instructions"] if not msg.moderation.categories.self_harm_instruction else True
                    msg.moderation.categories.self_harm = result["categories"]["self-harm"] if not msg.moderation.categories.self_harm else True
                    msg.moderation.categories.sexual_minors = result["categories"]["sexual/minors"] if not msg.moderation.categories.sexual_minors else True
                    msg.moderation.categories.violence = result["categories"]["violence"] if not msg.moderation.categories.violence else True
                    msg.moderation.categories.violence_graphic = result["categories"]["violence/graphic"] if not msg.moderation.categories.violence_graphic else True
                    constants.REMOTE_LOG.log(
                        Warn("Message flagged by Moderations API."),
                        Warn(f"Flagged categories: {msg.moderation.categories.get_flagged_categories()}")
                    )
                else:
                    constants.REMOTE_LOG.log(Info("No moderation flags detected, clear to proceed."))

        message_history = []
        for message in conversation.messages:
            if len(message.attachments) > 0:
                MAIN_LOG.log(Debug(f"MESSAGE ATTACHMENTS: {message.attachments}"))
            role = "assistant" if isinstance(message, classes.AntonMessage) else "user"
            message_to_add = {"role": role, "content": [{"type": "text", "text": str(message)}]}
            # Handle attachments (if is the last message in the conversation)
            if message == conversation.messages[-1] and not isinstance(message, classes.AntonMessage):
                for attachment in message.attachments:
                    type = None
                    data_format = None
                    if isinstance(attachment, classes.ImageAttachment):
                        type = "image_url"
                    elif isinstance(attachment, classes.TextAttachment):
                        type = "text"
                    elif isinstance(attachment, classes.AudioAttachment):
                        type = "input_audio"
                        data_format = attachment.format.split("/")[-1]  # get format without "audio/"
                    elif isinstance(attachment, classes.VideoAttachment):
                        type = "input_video"
                        data_format = attachment.format.split("/")[-1]  # get format without "video/"
                    elif isinstance(attachment, PDFAttachment):
                        type = "file"

                    if type:
                        match type:
                            case "image_url":
                                if not constants.DOA_FEATURE_FLAGS["image_support"]:
                                    constants.REMOTE_LOG.log(
                                        Warn("Image attachments are not supported, skipping image attachment.")
                                    )
                                    continue
                                message_to_add["content"].append(
                                    {"type": "image_url", "image_url": {"url": attachment.url}}
                                )
                            case "text":
                                message_to_add["content"].append(
                                    {"type": "text", "text": attachment.data.decode('utf-8')}
                                )
                            case "input_audio":
                                if not constants.DOA_FEATURE_FLAGS["audio_support"]:
                                    constants.REMOTE_LOG.log(
                                        Warn("Audio attachments are not supported, skipping audio attachment.")
                                    )
                                    continue
                                message_to_add["content"].append(
                                    {"type": "file", "file": {
                                        # convert to base64
                                        "file_data": base64.b64encode(attachment.data).decode('utf-8'),
                                        "filename": attachment.filename,
                                    }}
                                )
                            case "input_video":
                                if not constants.DOA_FEATURE_FLAGS["video_support"]:
                                    constants.REMOTE_LOG.log(
                                        Warn("Video attachments are not supported, skipping video attachment.")
                                    )
                                    continue
                                message_to_add["content"].append(
                                    {"type": "file", "file": {
                                        # convert to base64
                                        "file_data": base64.b64encode(attachment.data).decode('utf-8'),
                                        "filename": attachment.filename,
                                    }}
                                )
                            case "file":
                                if not constants.DOA_FEATURE_FLAGS["pdf_support"]:
                                    constants.REMOTE_LOG.log(
                                        Warn("PDF attachments are not supported, skipping PDF attachment.")
                                    )
                                    continue
                                message_to_add["content"].append(
                                    {"type": "file", "file": {
                                        # convert to base64
                                        "file_data": base64.b64encode(attachment.data).decode('utf-8'),
                                        "filename": attachment.filename,
                                    }}
                                )
                            case _:
                                constants.REMOTE_LOG.log(
                                    Warn(f"Unsupported attachment type: {type}, assuming text.")
                                )
                                message_to_add["content"].append(
                                    {"type": "text", "text": attachment.data.decode('utf-8')}
                                )

            message_history.append(message_to_add)

        MAIN_LOG.log(Debug(f"Built message payload."))

        payload = {
            "model": self.name,
            "messages": [{"role": "system", "content": constants.system_prompt()}]
                        + message_history,
        }

        constants.REMOTE_LOG.log(Debug(f"Chat Completions request payload: {payload}"))
        # remove any system messages from the debug log for readability
        constants.REMOTE_LOG.log(Debug(f"No system prompt: {message_history}"))
        constants.REMOTE_LOG.log(
            Info(f"Sending request to Chat Completions API at {self.source_url}")
        )
        response = requests.post(
            self.source_url + "/v1/chat/completions", headers=headers, json=payload, timeout=constants.REMOTE_TIMEOUT_SECONDS
        )
        if response.status_code != 200:
            constants.REMOTE_LOG.log(
                Error(
                    f"Error from Chat Completions API: {response.status_code} - {response.text}"
                )
            )
            raise Exception(f"Chat Completions API error: {response.status_code}")
        response_data = response.json()

        constants.REMOTE_LOG.log(
            Info("Received response from Chat Completions interface.")
        )
        constants.REMOTE_LOG.log(
            Debug(f"Chat Completions response content: {response_data}")
        )

        return classes.AntonMessage(
            content=response_data["choices"][0]["message"]["content"]
        )
