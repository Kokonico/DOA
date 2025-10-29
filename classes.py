"""classes for daughter of anton"""
import uuid

import constants


# conversational classes

class Person:
    """A person who wrote a message."""
    name: str
    id: str
    def __init__(self, name: str) -> None:
        self.name = name
        self.id = str(uuid.uuid4())

class DaughterOfAnton(Person):
    """Daughter of anton's specific class."""
    def __init__(self) -> None:
        super().__init__(name="Daughter of Anton")

class Message:
    """A message written by a person."""
    content: str
    author: Person

class AntonMessage(Message):
    """A message written by Daughter of Anton."""
    def __init__(self, content: str) -> None:
        super().__init__()
        self.content = content
        self.author = DaughterOfAnton()

class Conversation:
    """A conversation consisting of multiple messages."""

    messages: list[Message]
    def __init__(self) -> None:
        self.messages = []

    def add_message(self, message: Message) -> None:
        self.messages.append(message)

class Model:
    """A language model, base class for specific implementations."""
    name: str
    system_prompt: str = constants.SYSTEM_PROMPT
    def __init__(self, name: str, system_prompt: str | None) -> None:
        self.name = name
        if system_prompt:
            self.system_prompt = system_prompt

    def generate_response(self, conversation: Conversation) -> AntonMessage:
        raise NotImplementedError("Subclasses must implement this method.")
