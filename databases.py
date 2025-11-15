"""SQL database management for Daughter of Anton"""
import sqlite3
from sqlite3 import Connection, Cursor
import constants
from classes import Message, AntonMessage, Conversation, Person
from objlog.LogMessages import Info, Error, Debug
DB_FILE = 'daughter_of_anton.db'

class DatabaseManager:
    """
    Manages the SQLite database for Daughter of Anton.
    """

    db_path: str = DB_FILE
    connection: Connection | None = None
    cursor: Cursor | None = None
    connected : bool = False

    def __init__(self, db_path: str | None = None) -> None:
        if db_path:
            self.db_path = db_path
        self.connect()
        self.initialize_tables()

    def connect(self) -> None:
        """Establish a connection to the SQLite database."""
        try:
            self.connection = sqlite3.connect(self.db_path)
            self.cursor = self.connection.cursor()
            constants.MAIN_LOG.log(Info(f"Connected to database at {self.db_path}"))
            self.connected = True
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Database connection error: {e}"))
            raise e
    def initialize_tables(self) -> None:
        """Create necessary tables if they do not exist."""
        # how conversations work:
        # each conversation has a bunch of messages and a channel id (use the channel ID as the conversation ID)
        # each message has an author and content
        if not self.connected:
            constants.MAIN_LOG.log(Error("Database not connected. Cannot initialize tables."))
            return
        try:
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY
            )
            """)
            # note: don't worry about context bool, no context messages will be saved.
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER,
                author TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
            """)
            self.connection.commit()
            constants.MAIN_LOG.log(Info("Database tables initialized successfully."))
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error initializing database tables: {e}"))
            raise e

    def save_conversation(self, channel_id: int, conversation: Conversation) -> None:
        """Save a conversation to the database."""
        if not self.connected:
            constants.MAIN_LOG.log(Error("Database not connected. Cannot save conversation."))
            return
        try:
            # insert new message data (channel ID won't change) (if already exists, just use that)
            self.cursor.execute("""
            SELECT id FROM conversations
            WHERE id = ?
            """, (channel_id,))
            row = self.cursor.fetchone()
            if row:
                conversation_id = row[0]
            else:
                self.cursor.execute("INSERT INTO conversations (id) VALUES (?)", (channel_id,))
                conversation_id = self.cursor.lastrowid
            # delete old messages
            self.cursor.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            # insert new messages
            for message in conversation.messages:
                self.cursor.execute("""
                INSERT INTO messages (conversation_id, author, content, timestamp)
                VALUES (?, ?, ?, ?)
                """, (conversation_id, message.author.name, message.content, int(message.timestamp)))
            self.connection.commit()
            constants.MAIN_LOG.log(Info(f"Conversation saved for channel {channel_id}"))
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error saving conversation: {e}"))
            raise e

    def load_conversation(self, channel_id: int) -> Conversation:
        """Load a conversation from the database."""
        if not self.connected:
            constants.MAIN_LOG.log(Error("Database not connected. Cannot load conversation."))
            return Conversation()
        try:
            self.cursor.execute("""
            SELECT c.id FROM conversations c
            WHERE c.id = ?
            ORDER BY c.id DESC LIMIT 1
            """, (channel_id,))
            row = self.cursor.fetchone()
            if not row:
                constants.MAIN_LOG.log(Info(f"No conversation found for channel {channel_id}"))
                return Conversation()
            conversation_id = row[0]
            self.cursor.execute("""
            SELECT author, content, timestamp FROM messages
            WHERE conversation_id = ?
            ORDER BY timestamp ASC
            """, (conversation_id,))
            rows = self.cursor.fetchall()
            conversation = Conversation()
            for author, content, timestamp in rows:
                if author == "Daughter of Anton":
                    message = AntonMessage(content=content)
                else:
                    message = Message()
                    message.content = content
                    message.author = Person(name=author)
                    message.timestamp = timestamp
                    message.context = False
                conversation.add_message(message)
            constants.MAIN_LOG.log(Info(f"Conversation loaded for channel {channel_id}"))
            return conversation
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error loading conversation: {e}"))
            raise e

    def load_conversations(self) -> dict[int, Conversation]:
        """Load all conversations from the database."""
        if not self.connected:
            constants.MAIN_LOG.log(Error("Database not connected. Cannot load conversations."))
            return {}
        conversations_dict: dict[int, Conversation] = {}
        try:
            self.cursor.execute("SELECT id FROM conversations")
            conversation_rows = self.cursor.fetchall()
            for result in conversation_rows:
                conversation_id = result[0]
                self.cursor.execute("""
                SELECT author, content, timestamp FROM messages
                WHERE conversation_id = ?
                ORDER BY timestamp ASC
                """, result)
                message_rows = self.cursor.fetchall()
                conversation = Conversation()
                for author, content, timestamp in message_rows:
                    if author == "Daughter of Anton":
                        message = AntonMessage(content=content)
                    else:
                        message = Message()
                        message.content = content
                        message.author = Person(name=author)
                        message.timestamp = timestamp
                        message.context = False
                    conversation.add_message(message)
                conversations_dict[conversation_id] = conversation
            constants.MAIN_LOG.log(Info("All conversations loaded from database."))
            return conversations_dict
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error loading conversations: {e}"))
            raise e

    def delete_conversation(self, channel_id: int) -> None:
        """Delete a conversation from the database."""
        if not self.connected:
            constants.MAIN_LOG.log(Error("Database not connected. Cannot delete conversation."))
            return
        try:
            self.cursor.execute("""
            SELECT id FROM conversations
            WHERE channel_id = ?
            """, (channel_id,))
            row = self.cursor.fetchone()
            if not row:
                constants.MAIN_LOG.log(Info(f"No conversation found for channel {channel_id} to delete."))
                return
            conversation_id = row[0]
            self.cursor.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            self.cursor.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            self.connection.commit()
            constants.MAIN_LOG.log(Info(f"Conversation deleted for channel {channel_id}"))
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error deleting conversation: {e}"))
            raise e

    def close(self) -> None:
        """Close the database connection."""
        if self.connection:
            self.connection.close()
            constants.MAIN_LOG.log(Info("Database connection closed."))
            self.connected = False
