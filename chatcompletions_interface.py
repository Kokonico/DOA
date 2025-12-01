import classes
import constants
import requests

from objlog.LogMessages import Info, Debug, Error

from constants import MAIN_LOG


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

    def generate_response(
        self, conversation: classes.Conversation
    ) -> classes.AntonMessage:
        """Generate a response using the chat/completions interface based on the conversation history."""
        constants.REMOTE_LOG.log(
            Info("Generating response using Chat Completions interface.")
        )
        message_history = []
        for message in conversation.messages:
            MAIN_LOG.log(Debug(f"MESSAGE ATTACHMENTS: {message.attachments}"))
            role = "assistant" if isinstance(message, classes.AntonMessage) else "user"
            message_to_add = {"role": role, "content": [{"type": "text", "text": str(message)}]}
            # Handle attachments (if is the last message in the conversation)
            if message == conversation.messages[-1] and not isinstance(message, classes.AntonMessage):
                for attachment in message.attachments:
                    type = None
                    if isinstance(attachment, classes.ImageAttachment):
                        type = "image_url"
                    elif isinstance(attachment, classes.TextAttachment):
                        type = "text"

                    if type:
                        message_to_add["content"].append(
                            {"type": type, ("text" if type == "text" else "image_url"): ({"url": attachment.url} if type == "image_url" else attachment.data.decode('utf-8'))}
                        )

            message_history.append(message_to_add)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

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
            self.source_url, headers=headers, json=payload, timeout=60
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
