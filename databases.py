"""SQL database management for Daughter of Anton"""

import sqlite3
from sqlite3 import Connection, Cursor
import constants
from classes import Message, AntonMessage, Conversation, Person, ImageAttachment, TextAttachment, AudioAttachment, VideoAttachment, ModerationResult
from objlog.LogMessages import Info, Error, Debug

DB_FILE = constants.DATABASE_FILE


class DatabaseManager:
    db_path: str = DB_FILE
    connection: Connection | None = None
    cursor: Cursor | None = None
    connected: bool = False

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
        """Create necessary tables in the database. To be implemented by subclasses."""
        raise NotImplementedError("Subclasses must implement initialize_tables method.")


class ConversationDatabaseManager(DatabaseManager):
    """
    Manages the SQLite database for Daughter of Anton.
    """

    def initialize_tables(self) -> None:
        """Create necessary tables if they do not exist."""
        # how conversations work:
        # each conversation has a bunch of messages and a channel id (use the channel ID as the conversation ID)
        # each message has an author, nick, uuid, reply_to and content
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot initialize tables.")
            )
            return
        try:
            self.cursor.execute(
                """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY
            )
            """
            )

            self.cursor.execute(
                """
            CREATE TABLE IF NOT EXISTS attachments
            (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                type       TEXT NOT NULL,
                filename   TEXT NOT NULL,
                url        TEXT,
                data       BLOB,
                FOREIGN KEY (message_id) REFERENCES messages (id)
            )
            """
            )

            # note: don't worry about context bool, no context messages will be saved.
            # also add key | none to "reply to" message ID later if needed
            self.cursor.execute(
                """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER,
                author TEXT NOT NULL,
                nick TEXT,
                reply_to INTEGER,
                content TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                uuid TEXT NOT NULL,
                UNIQUE (uuid) ON CONFLICT REPLACE,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
            """
            )

            # initialize moderations/flags table
            self.cursor.execute(
                """
            CREATE TABLE IF NOT EXISTS moderations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER,
            flagged BOOLEAN NOT NULL,
            moderated BOOLEAN NOT NULL,
            harassment BOOLEAN NOT NULL,
            harassment_threatening BOOLEAN NOT NULL,
            sexual BOOLEAN NOT NULL,
            hate BOOLEAN NOT NULL,
            hate_threatening BOOLEAN NOT NULL,
            illicit BOOLEAN NOT NULL,
            illicit_violent BOOLEAN NOT NULL,
            self_harm_intent BOOLEAN NOT NULL,
            self_harm_instruction BOOLEAN NOT NULL,
            self_harm BOOLEAN NOT NULL,
            sexual_minors BOOLEAN NOT NULL,
            violence BOOLEAN NOT NULL,
            violence_graphic BOOLEAN NOT NULL,
            banned_word TEXT,
            FOREIGN KEY (message_id) REFERENCES messages(id)
            )
                """
            )

            self.connection.commit()
            constants.MAIN_LOG.log(Info("Database tables initialized successfully."))
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error initializing database tables: {e}"))
            raise e

    def resolve_moderations(self, message_id: int) -> ModerationResult | None:
        """Retrieve moderation result for a given message ID."""
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot retrieve moderation.")
            )
            return None
        try:
            self.cursor.execute(
                """
            SELECT flagged, moderated, harassment, harassment_threatening, sexual, hate,
                   hate_threatening, illicit, illicit_violent, self_harm_intent,
                   self_harm_instruction, self_harm, sexual_minors, violence,
                   violence_graphic, banned_word
            FROM moderations
            WHERE message_id = ?
            """,
                (message_id,),
            )
            row = self.cursor.fetchone()
            if row:
                (flagged, moderated, harassment, harassment_threatening, sexual, hate,
                 hate_threatening, illicit, illicit_violent, self_harm_intent,
                 self_harm_instruction, self_harm, sexual_minors, violence,
                 violence_graphic, banned_word) = row
                categories = ModerationResult.Categories(
                    harassment=bool(harassment),
                    harassment_threats=bool(harassment_threatening),
                    sexual_content=bool(sexual),
                    hate=bool(hate),
                    hate_threat=bool(hate_threatening),
                    illicit=bool(illicit),
                    illicit_violent=bool(illicit_violent),
                    self_harm_intent=bool(self_harm_intent),
                    self_harm_instruction=bool(self_harm_instruction),
                    self_harm=bool(self_harm),
                    sexual_minors=bool(sexual_minors),
                    violence=bool(violence),
                    violence_graphic=bool(violence_graphic),
                    banned_word=banned_word
                )
                return ModerationResult(flagged=bool(flagged), moderated=bool(moderated), categories=categories)
            return None
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error retrieving moderation: {e}"))
            raise e

    def resolve_attachments(self, message_id: int) -> list:
        """Retrieve attachments for a given message ID."""
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot retrieve attachments.")
            )
            return []
        try:
            self.cursor.execute(
                """
            SELECT type, filename, url, data FROM attachments
            WHERE message_id = ?
            """,
                (message_id,),
            )
            rows = self.cursor.fetchall()
            attachments = []
            for row in rows:
                attachment_type, filename, url, data = row
                match attachment_type:
                    case ImageAttachment.__name__:
                        attachment = ImageAttachment(filename=filename, url=url, data=data)
                    case TextAttachment.__name__:
                        attachment = TextAttachment(filename=filename, data=data)
                    case AudioAttachment.__name__:
                        attachment = AudioAttachment(filename=filename, data=data)
                    case VideoAttachment.__name__:
                        attachment = VideoAttachment(filename=filename, data=data)
                    case _:
                        constants.MAIN_LOG.log(Error(f"Unknown attachment type: {attachment_type}"))
                        continue

                if attachment:
                    attachments.append(attachment)
            return attachments
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error retrieving attachments: {e}"))
            raise e

    def resolve_replies(self, initial_id: int) -> Message:
        # Retrieve a message and its reply chain from the database by its ID.
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot retrieve message.")
            )
            return None
        try:
            self.cursor.execute(
                """
            SELECT author, nick, content, timestamp, reply_to, uuid FROM messages
            WHERE id = ?
            """,
                (initial_id,),
            )
            row = self.cursor.fetchone()
            if row:
                next_to_retrieve = row[4]
                if row[0] == "Daughter of Anton":
                    result = AntonMessage(content=row[2])
                else:
                    result = Message(row[2], author=Person(name=row[0], nick=row[1]), context=False)
                result.uuid = row[5]
                result.timestamp = row[3]
                result.attachments = self.resolve_attachments(initial_id)
                result.moderation = self.resolve_moderations(initial_id)
                while next_to_retrieve:
                    self.cursor.execute(
                        """
                    SELECT author, nick, content, timestamp, reply_to, uuid FROM messages
                    WHERE id = ?
                    """,
                        (next_to_retrieve,),
                    )
                    reply_row = self.cursor.fetchone()
                    if reply_row:
                        if reply_row[0] == "Daughter of Anton":
                            reply_message = AntonMessage(content=reply_row[2])
                        else:
                            reply_message = Message(reply_row[2], author=Person(name=reply_row[0], nick=reply_row[1]), context=False)
                        reply_message.uuid = reply_row[5]
                        reply_message.timestamp = reply_row[3]
                        reply_message.moderation = self.resolve_moderations(next_to_retrieve)
                        reply_message.attachments = self.resolve_attachments(next_to_retrieve)
                        result.reference = reply_message
                        next_to_retrieve = reply_row[4]
                    else:
                        break
                return result
            return None
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error retrieving message by ID: {e}"))
            raise e

    def get_id_from_uuid(self, uuid: str) -> int | None:
        """Retrieve a message ID from the database by its UUID."""
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot retrieve message ID.")
            )
            return None
        try:
            self.cursor.execute(
                """
            SELECT id FROM messages
            WHERE uuid = ?
            """,
                (uuid,),
            )
            row = self.cursor.fetchone()
            if row:
                return row[0]
            return None
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error retrieving message ID by UUID: {e}"))
            raise e

    def get_message_from_uuid(self, uuid: str) -> Message | None:
        """Retrieve a message from the database by its UUID."""
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot retrieve message.")
            )
            return None
        try:
            return self.resolve_replies(self.get_id_from_uuid(uuid))
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error retrieving message by UUID: {e}"))
            raise e

    def save_conversation(self, channel_id: int, conversation: Conversation) -> None:
        """Save a conversation to the database."""
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot save conversation.")
            )
            return
        try:
            # insert new message data (channel ID won't change) (if already exists, just use that)
            self.cursor.execute(
                """
            SELECT id FROM conversations
            WHERE id = ?
            """,
                (channel_id,),
            )
            row = self.cursor.fetchone()
            if row:
                conversation_id = row[0]
            else:
                self.cursor.execute(
                    "INSERT INTO conversations (id) VALUES (?)", (channel_id,)
                )
                conversation_id = self.cursor.lastrowid
            # delete old messages
            self.cursor.execute(
                "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
            )
            # insert new messages
            for message in conversation.messages:
                self.cursor.execute(
                    """
                INSERT INTO messages (conversation_id, author, nick, reply_to, content, timestamp, uuid)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        conversation_id,
                        message.author.name,
                        message.author.nick,
                        self.get_id_from_uuid(message.reference.uuid) if message.reference else None,
                        message.content,
                        int(message.timestamp),
                        message.uuid
                    ),
                )
                # insert attachments if any
                message_id = self.cursor.lastrowid
                for attachment in message.attachments:
                    self.cursor.execute(
                        """
                    INSERT INTO attachments (message_id, type, filename, url, data)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                        (
                            message_id,
                            type(attachment).__name__,
                            attachment.filename,
                            getattr(attachment, 'url', None),
                            getattr(attachment, 'data', None),
                        ),
                    )
                # insert moderation if any
                if message.moderation:
                    mod = message.moderation
                    cat = mod.categories
                    self.cursor.execute(
                        """
                    INSERT INTO moderations (message_id, flagged, harassment, harassment_threatening,
                                             sexual, hate, hate_threatening, illicit, illicit_violent,
                                             self_harm_intent, self_harm_instruction, self_harm,
                                             sexual_minors, violence, violence_graphic, banned_word)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            message_id,
                            int(mod.flagged),
                            int(cat.harassment),
                            int(cat.harassment_threats),
                            int(cat.sexual_content),
                            int(cat.hate),
                            int(cat.hate_threat),
                            int(cat.illicit),
                            int(cat.illicit_violent),
                            int(cat.self_harm_intent),
                            int(cat.self_harm_instruction),
                            int(cat.self_harm),
                            int(cat.sexual_minors),
                            int(cat.violence),
                            int(cat.violence_graphic),
                            str(mod.categories.banned_word) if mod.categories.banned_word else None
                        ),
                    )
            self.connection.commit()
            constants.MAIN_LOG.log(Info(f"Conversation saved for channel {channel_id}"))
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error saving conversation: {e}"))
            raise e

    def load_conversation(self, channel_id: int) -> Conversation:
        """Load a conversation from the database."""
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot load conversation.")
            )
            return Conversation()
        try:
            self.cursor.execute(
                """
            SELECT c.id FROM conversations c
            WHERE c.id = ?
            ORDER BY c.id DESC LIMIT 1
            """,
                (channel_id,),
            )
            row = self.cursor.fetchone()
            if not row:
                constants.MAIN_LOG.log(
                    Info(f"No conversation found for channel {channel_id}")
                )
                return Conversation()
            conversation_id = row[0]
            self.cursor.execute(
                """
            SELECT id FROM messages
            WHERE conversation_id = ?
            ORDER BY timestamp ASC
            """,
                (conversation_id,),
            )
            message_rows = self.cursor.fetchall()
            conversation = Conversation()
            for (message_id,) in message_rows:
                # resolve replies
                message = self.resolve_replies(message_id)
                conversation.add_message(message)
            constants.MAIN_LOG.log(
                Info(f"Conversation loaded for channel {channel_id}")
            )
            return conversation
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error loading conversation: {e}"))
            raise e

    def load_conversations(self) -> dict[int, Conversation]:
        """Load all conversations from the database."""
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot load conversations.")
            )
            return {}
        conversations_dict: dict[int, Conversation] = {}
        try:
            self.cursor.execute("SELECT id FROM conversations")
            conversation_rows = self.cursor.fetchall()
            for result in conversation_rows:
                conversation_id = result[0]
                self.cursor.execute(
                    """
                    SELECT id
                    FROM messages
                    WHERE conversation_id = ?
                    ORDER BY timestamp
                    """,
                    result,
                )
                message_rows = self.cursor.fetchall()
                conversation = Conversation()
                for (message_id,) in message_rows:
                    message = self.resolve_replies(message_id)
                    conversation.add_message(message)
                conversations_dict[conversation_id] = conversation
            constants.MAIN_LOG.log(Info("All messages loaded from database."))
            return conversations_dict
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error loading conversations: {e}"))
            raise e

    def delete_conversation(self, channel_id: int) -> None:
        """Delete a conversation from the database."""
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot delete conversation.")
            )
            return
        try:
            self.cursor.execute(
                """
            SELECT id FROM conversations
            WHERE id = ?
            """,
                (channel_id,),
            )
            row = self.cursor.fetchone()
            if not row:
                constants.MAIN_LOG.log(
                    Info(f"No conversation found for channel {channel_id} to delete.")
                )
                return
            conversation_id = row[0]
            self.cursor.execute(
                "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
            )
            self.cursor.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )
            self.connection.commit()
            constants.MAIN_LOG.log(
                Info(f"Conversation deleted for channel {channel_id}")
            )
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error deleting conversation: {e}"))
            raise e

    def close(self) -> None:
        """Close the database connection."""
        if self.connection:
            self.connection.close()
            constants.MAIN_LOG.log(Info("Database connection closed."))
            self.connected = False

class DiscordDataCacher(DatabaseManager):
    """
    Manages caching of Discord data in the SQLite database.
    """

    db_path = constants.CACHE_DATABASE_FILE

    connection: Connection | None = None
    cursor: Cursor | None = None
    connected: bool = False

    def initialize_tables(self) -> None:
        """Create necessary tables for Discord data caching."""
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot initialize Discord tables.")
            )
            return
        try:
            # cache ID to name mapping (or vice versa) for Discord users
            self.cursor.execute(
                """
            CREATE TABLE IF NOT EXISTS discord_users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            )
            """
            )
            self.connection.commit()
            constants.MAIN_LOG.log(
                Info("Discord data tables initialized successfully.")
            )
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(
                Error(f"Error initializing Discord data tables: {e}")
            )
            raise e

    def get_user_by_id(self, user_id: int) -> str | None:
        """Get a Discord user's name by their ID from the cache."""
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot get Discord user.")
            )
            return None
        try:
            self.cursor.execute(
                "SELECT name FROM discord_users WHERE id = ?", (user_id,)
            )
            row = self.cursor.fetchone()
            if row:
                return row[0]
            return None
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error getting Discord user: {e}"))
            raise e

    def get_user_by_name(self, user_name: str) -> int | None:
        """Get a Discord user's ID by their name from the cache."""
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot get Discord user.")
            )
            return None
        try:
            self.cursor.execute(
                "SELECT id FROM discord_users WHERE name = ?", (user_name,)
            )
            row = self.cursor.fetchone()
            if row:
                return row[0]
            return None
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error getting Discord user: {e}"))
            raise e

    def cache_user(self, user_id: int, user_name: str) -> None:
        """Cache a Discord user's ID and name."""
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot cache Discord user.")
            )
            return
        try:
            self.cursor.execute(
                """
            INSERT OR REPLACE INTO discord_users (id, name)
            VALUES (?, ?)
            """,
                (user_id, user_name),
            )
            self.connection.commit()
            constants.MAIN_LOG.log(
                Info(f"Cached Discord user: {user_name} (ID: {user_id})")
            )
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error caching Discord user: {e}"))
            raise e
