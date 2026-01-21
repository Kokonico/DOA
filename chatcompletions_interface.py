import base64

# import objlog.utils

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
                                    {"type": "input_audio", "input_audio": {
                                        # convert to base64
                                        "data": base64.b64encode(attachment.data).decode('utf-8'),
                                        "format": data_format,
                                    }}
                                )
                            case "input_video":
                                if not constants.DOA_FEATURE_FLAGS["video_support"]:
                                    constants.REMOTE_LOG.log(
                                        Warn("Video attachments are not supported, skipping video attachment.")
                                    )
                                    continue
                                message_to_add["content"].append(
                                    {"type": "video_url", "video_url": {
                                        # convert to base64
                                        "url": f"data:video/{data_format};base64,{base64.b64encode(attachment.data).decode('utf-8')}"
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
