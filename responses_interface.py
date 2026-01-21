import base64

from sympy import true

# import objlog.utils

import classes
import constants
import requests

from objlog.LogMessages import Info, Debug, Error, Warn

from classes import PDFAttachment
from constants import MAIN_LOG, REMOTE_LOG


class Responses(classes.Model):
    """A language model that uses responses API for generating responses."""

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

    # python
    def generate_response(
            self, conversation: classes.Conversation
    ) -> classes.AntonMessage:
        """Generate a response using the responses API based on the conversation history."""
        # TODO: very broken! fix someday lmao (not today)
        constants.REMOTE_LOG.log(
            Info("Generating response using Responses API.")
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
            # use API-expected content type discriminator
            content_item_type = "output" if isinstance(message, classes.AntonMessage) else "input"
            message_to_add = {"role": role, "type": "message",
                              "content": [{"type": content_item_type + "_text", "text": str(message)}]}
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
                        data_format = attachment.format.split("/")[-1].lower()  # get format without "audio/"
                    elif isinstance(attachment, classes.VideoAttachment):
                        type = "input_video"
                        data_format = attachment.format.split("/")[-1].lower()  # get format without "video/"
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
                                    {"type": content_item_type+"_image", "image_url": f"data:image/{data_format};base64,{base64.b64encode(attachment.data).decode('utf-8')}"}
                                )
                            case "text":
                                # keep as input_text for text attachments on user messages
                                message_to_add["content"].append(
                                    {"type": content_item_type+"_text", "text": attachment.data.decode('utf-8')}
                                )
                            case "input_audio":
                                if not constants.DOA_FEATURE_FLAGS["audio_support"] or true:  # temporarily disable audio support as responses API does not support it yet
                                    constants.REMOTE_LOG.log(
                                        Warn("Audio attachments are not supported, skipping audio attachment.") # TODO support audio attachments when r
                                    )
                                    continue
                                message_to_add["content"].append(
                                    {"type": content_item_type+"_audio", "audio": {
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
                                    {"type": content_item_type+"_video", "video": {
                                        "data": base64.b64encode(attachment.data).decode('utf-8'),
                                        "format": data_format,
                                    }}
                                )
                            case "file":
                                if not constants.DOA_FEATURE_FLAGS["pdf_support"]:
                                    constants.REMOTE_LOG.log(
                                        Warn("PDF attachments are not supported, skipping PDF attachment.")
                                    )
                                    continue
                                message_to_add["content"].append(
                                    {"type": content_item_type+"_file", "file_data": f"data:application/pdf;base64,{base64.b64encode(attachment.data).decode('utf-8')}"}
                                )
                            case _:
                                constants.REMOTE_LOG.log(
                                    Warn(f"Unsupported attachment type: {type}, assuming text.")
                                )
                                message_to_add["content"].append(
                                    {"type": content_item_type+"_text", "text": attachment.data.decode('utf-8')}
                                )

            message_history.append(message_to_add)

        MAIN_LOG.log(Debug(f"Built message payload."))

        payload = {
            "model": self.name,
            "input": [{"type": "message", "role": "system", "content": [{"type": "input_text",
                                                                         "text": constants.system_prompt() if self.system_prompt is None else self.system_prompt}]}]
                     + message_history,
        }

        constants.REMOTE_LOG.log(Debug(f"Responses API request payload: {payload}"))
        # remove any system messages from the debug log for readability
        constants.REMOTE_LOG.log(Debug(f"No system prompt: {message_history}"))
        constants.REMOTE_LOG.log(
            Info(f"Sending request to Responses API at {self.source_url}")
        )
        response = requests.post(
            self.source_url + "/v1/responses", headers=headers, json=payload, timeout=constants.REMOTE_TIMEOUT_SECONDS
        )
        if response.status_code != 200:
            constants.REMOTE_LOG.log(
                Error(
                    f"Error from CResponses API: {response.status_code} - {response.text}"
                )
            )
            raise Exception(f"Responses API error: {response.status_code}")
        response_data = response.json()

        constants.REMOTE_LOG.log(
            Info("Received response from Responses API.")
        )
        constants.REMOTE_LOG.log(
            Debug(f"Responses API response content: {response_data}")
        )

        return classes.AntonMessage(
            content=response_data["output"][0]["content"][0]["text"]
        )
