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


class Message:
    """A message written by a person."""

    content: str
    author: Person
    timestamp: float
    context: bool


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
    system_prompt: str = constants.SYSTEM_PROMPT

    def __init__(self, name: str, system_prompt: str | None) -> None:
        self.name = name if name else self.name
        if system_prompt:
            self.system_prompt = system_prompt

    def generate_response(self, conversation: Conversation) -> AntonMessage:
        raise NotImplementedError("Subclasses must implement this method.")
