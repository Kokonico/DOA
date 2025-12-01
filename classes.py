"""classes for daughter of anton"""

import datetime
import uuid
import time

import constants

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

    def __init__(self, filename: str, data: bytes) -> None:
        super().__init__(filename, data)

class TextAttachment(Attachment):
    """A text attachment to a message."""

    mime: str
    def __init__(self, filename: str, data: bytes, mime: str = "text/plain") -> None:
        super().__init__(filename, data)
        self.mime = mime

class AudioAttachment(Attachment):
    """An audio attachment to a message."""

    def __init__(self, filename: str, data: bytes) -> None:
        super().__init__(filename, data)

class Message:
    """A message written by a person."""

    content: str
    author: Person
    timestamp: float
    context: bool
    reference: Message | None = None
    attachments: list[Attachment] = []
    uuid: str

    def __init__(self, content: str = "", author: Person | None = None, context: bool = False, reference: Message | None = None) -> None:
        self.content = content
        self.author = author if author else Person(name="Unknown")
        self.timestamp = datetime.datetime.timestamp(datetime.datetime.now())
        self.context = context
        self.reference = reference
        self.uuid = str(uuid.uuid4())

    def string_no_reply(self):
        nick = f"\\/\\{self.author.nick}" if self.author.nick else ""
        return f"{self.author.name}{nick}: {self.content} " + "".join([f" [Attachment (type: {type(attachment).__name__}, filename: {attachment.filename})]" for attachment in self.attachments])

    def __repr__(self):
        return f"<Message author={self.author.name} timestamp={self.timestamp} context={self.context} content={self.content}>"

    def __str__(self):
        return (f"(replying to: {self.reference.string_no_reply()}) " if self.reference else "") + self.string_no_reply()


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


class Model:
    """A language model, base class for specific implementations."""

    name: str

    def __init__(self, name: str, system_prompt: str | None) -> None:
        self.name = name if name else self.name
        if system_prompt:
            self.system_prompt = system_prompt

    def generate_response(self, conversation: Conversation) -> AntonMessage:
        raise NotImplementedError("Subclasses must implement this method.")
