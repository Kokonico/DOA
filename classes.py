from __future__ import annotations

"""classes for daughter of anton"""

import datetime
import uuid
import requests

import constants
from constants import MAIN_LOG, REMOTE_LOG, Info, Warn, Error, Debug


# conversational classes

class Person:
    """A person who wrote a message."""

    name: str
    id: str
    nick: str | None = None

    def __init__(self, name: str, nick: str | None = None) -> None:
        self.name = name
        self.nick = nick
        self.id = str(uuid.uuid4())


class DaughterOfAnton(Person):
    """Daughter of anton's specific class."""

    def __init__(self) -> None:
        super().__init__(name="Daughter of Anton")


# attachments

class Attachment:
    """An attachment to a message."""

    filename: str
    data: bytes

    def __init__(self, filename: str, data: bytes) -> None:
        self.filename = filename
        self.data = data


class ImageAttachment(Attachment):
    """An image attachment to a message."""

    url: str

    def __init__(self, filename: str, data: bytes, url: str) -> None:
        super().__init__(filename, data)
        self.url = url


class VideoAttachment(Attachment):
    """A video attachment to a message."""

    def __init__(self, filename: str, data: bytes, file_format: str) -> None:
        super().__init__(filename, data)
        self.format = file_format


class TextAttachment(Attachment):
    """A text attachment to a message."""

    mime: str

    def __init__(self, filename: str, data: bytes, mime: str = "text/plain") -> None:
        super().__init__(filename, data)
        self.mime = mime


class AudioAttachment(Attachment):
    """An audio attachment to a message."""

    def __init__(self, filename: str, data: bytes, file_format: str) -> None:
        super().__init__(filename, data)
        self.format = file_format


class PDFAttachment(Attachment):
    """A PDF attachment to a message."""

    def __init__(self, filename: str, data: bytes) -> None:
        super().__init__(filename, data)


class ModerationResult:
    """A moderation result for a message."""

    flagged: bool
    moderated: bool = False  # if the message has even been moderated yet

    class Categories:
        harassment: bool
        harassment_threats: bool
        sexual_content: bool
        hate: bool
        hate_threat: bool
        illicit: bool
        illicit_violent: bool
        self_harm_intent: bool
        self_harm_instruction: bool
        self_harm: bool
        sexual_minors: bool
        violence: bool
        violence_graphic: bool
        banned_word: str | None = None

        def __init__(self, harassment: bool = False, harassment_threats: bool = False, sexual_content: bool = False,
                     hate: bool = False, hate_threat: bool = False, illicit: bool = False,
                     illicit_violent: bool = False, self_harm_intent: bool = False,
                     self_harm_instruction: bool = False, self_harm: bool = False,
                     sexual_minors: bool = False, violence: bool = False,
                     violence_graphic: bool = False, banned_word: str | None = None) -> None:
            self.harassment = harassment
            self.harassment_threats = harassment_threats
            self.sexual_content = sexual_content
            self.hate = hate
            self.hate_threat = hate_threat
            self.illicit = illicit
            self.illicit_violent = illicit_violent
            self.self_harm_intent = self_harm_intent
            self.self_harm_instruction = self_harm_instruction
            self.self_harm = self_harm
            self.sexual_minors = sexual_minors
            self.violence = violence
            self.violence_graphic = violence_graphic
            self.banned_word = banned_word

        def get_flagged_categories(self) -> list[str]:
            flagged = []
            for category, value in vars(self).items():
                if value is True:
                    flagged.append(category)
            return flagged


    categories: Categories

    def __init__(self, flagged: bool, categories: Categories, moderated: bool = False) -> None:
        self.flagged = flagged
        self.moderated = moderated
        self.categories = categories

    def reasons_as_string(self) -> str:
        return ", ".join(self.categories.get_flagged_categories())


class Message:
    """A message written by a person."""

    content: str
    author: Person
    timestamp: float
    context: bool
    moderation: ModerationResult | None = None
    reference: Message | None = None
    attachments: list[Attachment] = []
    uuid: str

    def __init__(self, content: str = "", author: Person | None = None, context: bool = False,
                 reference: Message | None = None) -> None:
        self.content = content
        self.author = author if author else Person(name="Unknown")
        self.timestamp = datetime.datetime.timestamp(datetime.datetime.now())
        self.context = context
        self.reference = reference
        self.uuid = str(uuid.uuid4())
        self.attachments = []  # initialize attachments as empty list (prevent shared mutable default,
        # i'm so stupid for not catching this earlier)
        self.moderation = ModerationResult(flagged=False, moderated=False,
                                         categories=ModerationResult.Categories())  # default moderation result

    def string_no_reply(self):
        nick = f"\\/\\{self.author.nick}" if self.author.nick else ""
        if not self.moderation.flagged:
            return f"{self.author.name}{nick}: {self.content} " + "".join(
                [f" [Attachment (type: {type(attachment).__name__}, filename: {attachment.filename})]" for attachment in
                 self.attachments])
        else:
            return f"{self.author.name}{nick}: [Message moderated for: {self.moderation.reasons_as_string()}]"

    def __repr__(self):
        return f"<Message author={self.author.name} timestamp={self.timestamp} context={self.context} content={self.content}>"

    def __str__(self):
        return (
            f"(replying to: {self.reference.string_no_reply()}) " if self.reference else "") + self.string_no_reply()


class AntonMessage(Message):
    """A message written by Daughter of Anton."""

    def __init__(self, content: str) -> None:
        super().__init__()
        self.content = content
        self.timestamp = datetime.datetime.timestamp(datetime.datetime.now())
        self.context = False
        self.author = DaughterOfAnton()


class Conversation:
    """A conversation consisting of multiple messages."""

    messages: list[Message]

    def __init__(self) -> None:
        self.messages = []

    def add_message(self, message: Message) -> None:
        """add a message and automatically place it according to timestamp"""
        self.messages.append(message)
        self.messages.sort(key=lambda msg: msg.timestamp)

    def clear_context(self) -> None:
        """clear all messages marked as context"""
        self.messages = [msg for msg in self.messages if not msg.context]

    def run_moderations(self, api_key: str, moderation_url: str) -> None:
        """run moderation on all messages in the conversation IF they haven't been moderated yet"""
        if constants.ENABLE_MODERATION:
            constants.REMOTE_LOG.log(Info("Starting moderation check for conversation."))
            # run messages through moderation endpoint
            # message.moderation is only set for messages that have already been moderated, don't re-moderate those
            # messages_to_moderate contains the self.messages's indexes that need moderation
            messages_to_moderate = []
            for i, msg in enumerate(self.messages):
                if not msg.moderation.moderated and not isinstance(msg, AntonMessage):
                    msg.moderation.moderated = True  # mark as moderated to prevent re-moderation
                    messages_to_moderate.append(i) # store index for later use, so we can modify the original messages later
            # rest of types are ignored for moderation for now (unsupported)

            # look for words in the wordlist first
            for word in constants.MODERATION_WORDLIST:
                for msg_index in messages_to_moderate:
                    if word in self.messages[msg_index].content.lower():
                        constants.REMOTE_LOG.log(
                            Warn("Message flagged by wordlist moderation."),
                            Warn(f"Flagged word: {word}")
                        )
                        self.messages[msg_index].moderation.flagged = True
                        self.messages[msg_index].moderation.Categories.banned_word = word

            # jsonify!
            jsonfied_messages = []
            message_sizes = []

            constants.REMOTE_LOG.log(Info(f"Moderating {len(messages_to_moderate)} messages."))

            for msg_index in messages_to_moderate:
                size = 1
                if not self.messages[msg_index].moderation.flagged:
                    msg_json = {
                        "type": "text",
                        "text": self.messages[msg_index].content
                    }
                    messages_to_moderate_json = [msg_json]
                    for attachment in self.messages[msg_index].attachments:
                        # only text attachments are supported for moderation for now
                        if isinstance(attachment, TextAttachment):
                            messages_to_moderate_json.append({
                                "type": "text",
                                "text": attachment.data.decode('utf-8')
                            })
                        elif isinstance(attachment, ImageAttachment):
                            messages_to_moderate_json.append({
                                "type": "image_url",
                                "image_url": {"url": attachment.url}
                            })
                        size += 1  # attachments also count towards size
                    for _ in range(size):
                        message_sizes.append(msg_index)

                    jsonfied_messages.append(messages_to_moderate_json)

            # flatten the list
            # each attachment is a separate input to moderation endpoint
            new_messages_to_moderate = []
            for msg_list in jsonfied_messages:
                for msg in msg_list:
                    new_messages_to_moderate.append(msg)

            REMOTE_LOG.log(Info(f"Sending {len(new_messages_to_moderate)} items to Moderations API for moderation."))

            response = requests.post(
                moderation_url + "/v1/moderations",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
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
                msg_index = message_sizes[index]
                # note: only override if false, if true but new result is false, keep true
                if result["flagged"]:
                    self.messages[msg_index].moderation.flagged = True
                    self.messages[msg_index].moderation.categories.harassment = result["categories"]["harassment"] if not self.messages[msg_index].moderation.categories.harassment else True
                    self.messages[msg_index].moderation.categories.harassment_threats = result["categories"]["harassment/threatening"] if not self.messages[msg_index].moderation.categories.harassment_threats else True
                    self.messages[msg_index].moderation.categories.sexual_content = result["categories"]["sexual"] if not self.messages[msg_index].moderation.categories.sexual_content else True
                    self.messages[msg_index].moderation.categories.hate = result["categories"]["hate"] if not self.messages[msg_index].moderation.categories.hate else True
                    self.messages[msg_index].moderation.categories.hate_threat = result["categories"]["hate/threatening"] if not self.messages[msg_index].moderation.categories.hate_threat else True
                    self.messages[msg_index].moderation.categories.illicit = result["categories"]["illicit"] if not self.messages[msg_index].moderation.categories.illicit else True
                    self.messages[msg_index].moderation.categories.illicit_violent = result["categories"]["illicit/violent"] if not self.messages[msg_index].moderation.categories.illicit_violent else True
                    self.messages[msg_index].moderation.categories.self_harm_intent = result["categories"]["self-harm/intent"] if not self.messages[msg_index].moderation.categories.self_harm_intent else True
                    self.messages[msg_index].moderation.categories.self_harm_instruction = result["categories"]["self-harm/instructions"] if not self.messages[msg_index].moderation.categories.self_harm_instruction else True
                    self.messages[msg_index].moderation.categories.self_harm = result["categories"]["self-harm"] if not self.messages[msg_index].moderation.categories.self_harm else True
                    self.messages[msg_index].moderation.categories.sexual_minors = result["categories"]["sexual/minors"] if not self.messages[msg_index].moderation.categories.sexual_minors else True
                    self.messages[msg_index].moderation.categories.violence = result["categories"]["violence"] if not self.messages[msg_index].moderation.categories.violence else True
                    self.messages[msg_index].moderation.categories.violence_graphic = result["categories"]["violence/graphic"] if not self.messages[msg_index].moderation.categories.violence_graphic else True
                    constants.REMOTE_LOG.log(
                        Warn("Message flagged by Moderations API."),
                        Warn(f"Flagged categories: {self.messages[msg_index].moderation.categories.get_flagged_categories()}")
                    )
                else:
                    constants.REMOTE_LOG.log(Info("No moderation flags detected, clear to proceed."))


class Model:
    """A language model, base class for specific implementations."""

    name: str

    def __init__(self, name: str, system_prompt: str | None) -> None:
        self.name = name if name else self.name
        if system_prompt:
            self.system_prompt = system_prompt

    def generate_response(self, conversation: Conversation) -> AntonMessage:
        raise NotImplementedError("Subclasses must implement this method.")
