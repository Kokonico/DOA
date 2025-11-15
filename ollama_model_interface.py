"""ollama interface module, talks to ollama so the rest of the code doesn't have to"""

import ollama
import classes
import constants

from objlog.LogMessages import Info, Debug

client = ollama.Client()


class OllamaModel(classes.Model):
    """A language model that uses Ollama for generating responses."""

    name: str = "dolphin3"

    def generate_response(
        self, conversation: classes.Conversation
    ) -> classes.AntonMessage:
        """Generate a response using the Ollama model based on the conversation history."""
        constants.OLLAMA_LOG.log(Info("Generating response using Ollama model."))
        message_history = []
        for message in conversation.messages:
            role = "assistant" if isinstance(message, classes.AntonMessage) else "user"
            message_history.append(
                {"role": role, "content": f"{message.author.name}: {message.content}"}
            )

        response = client.chat(
            model=self.name,
            messages=[{"role": "system", "content": self.system_prompt}]
            + message_history,
        )
        constants.OLLAMA_LOG.log(Info("Received response from Ollama model."))
        constants.OLLAMA_LOG.log(Debug(f"Ollama response content: {response}"))
        return classes.AntonMessage(content=response["message"]["content"])
