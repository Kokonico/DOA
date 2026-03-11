"""SQL database management for Daughter of Anton"""

import sqlite3
from sqlite3 import Connection, Cursor

import constants
from classes import (
    Message,
    AntonMessage,
    Conversation,
    Person,
    ImageAttachment,
    TextAttachment,
    AudioAttachment,
    VideoAttachment,
    ModerationResult,
    UserProfile,
    UserMessageHistoryEntry,
    UserModerationHistoryEntry,
    UserHistoryBundle,
)
from objlog.LogMessages import Info, Error

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
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.cursor = self.connection.cursor()
            constants.MAIN_LOG.log(Info(f"Connected to database at {self.db_path}"))
            self.connected = True
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Database connection error: {e}"))
            raise e

    def initialize_tables(self) -> None:
        """Create necessary tables in the database. To be implemented by subclasses."""
        raise NotImplementedError("Subclasses must implement initialize_tables method.")

    def close(self) -> None:
        """Close the database connection."""
        if self.connection:
            self.connection.close()
            constants.MAIN_LOG.log(Info(f"Database connection closed: {self.db_path}"))
            self.connected = False


class UsersDatabaseManager(DatabaseManager):
    """Single source of truth for Discord user identity cache + profile metadata."""

    db_path = constants.USERS_DATABASE_FILE

    def initialize_tables(self) -> None:
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot initialize users tables.")
            )
            return
        try:
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users
                (
                    id                INTEGER PRIMARY KEY,
                    name              TEXT NOT NULL,
                    nick              TEXT,
                    notes             TEXT,
                    last_message_uuid TEXT,
                    last_seen_at      INTEGER
                )
                """
            )
            self.cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_users_name
                    ON users (name)
                """
            )
            self.connection.commit()
            constants.MAIN_LOG.log(Info("Users tables initialized successfully."))
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error initializing users tables: {e}"))
            raise e

    def upsert_user(
            self,
            user_id: int,
            user_name: str,
            nick: str | None = None,
            notes: str | None = None,
            last_message_uuid: str | None = None,
            last_seen_at: int | None = None,
    ) -> None:
        """Insert/update one user profile row in users.db."""
        if not self.connected:
            constants.MAIN_LOG.log(Error("Database not connected. Cannot upsert user."))
            return
        try:
            self.cursor.execute(
                """
                INSERT INTO users (id, name, nick, notes, last_message_uuid, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET name              = excluded.name,
                                              nick              = excluded.nick,
                                              notes             = COALESCE(excluded.notes, users.notes),
                                              last_message_uuid = COALESCE(excluded.last_message_uuid, users.last_message_uuid),
                                              last_seen_at      = COALESCE(excluded.last_seen_at, users.last_seen_at)
                """,
                (user_id, user_name, nick, notes, last_message_uuid, last_seen_at),
            )
            self.connection.commit()
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error upserting user: {e}"))
            raise e

    def get_user_by_id(self, user_id: int) -> str | None:
        """Get a Discord user's name by their ID from users.db."""
        if not self.connected:
            constants.MAIN_LOG.log(Error("Database not connected. Cannot get user."))
            return None
        try:
            self.cursor.execute("SELECT name FROM users WHERE id = ?", (user_id,))
            row = self.cursor.fetchone()
            return row[0] if row else None
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error getting user by ID: {e}"))
            raise e

    def get_user_by_name(self, user_name: str) -> int | None:
        """Get a Discord user's ID by username from users.db."""
        if not self.connected:
            constants.MAIN_LOG.log(Error("Database not connected. Cannot get user."))
            return None
        try:
            self.cursor.execute("SELECT id FROM users WHERE name = ?", (user_name,))
            row = self.cursor.fetchone()
            return row[0] if row else None
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error getting user by name: {e}"))
            raise e

    def cache_user(self, user_id: int, user_name: str) -> None:
        """Compatibility helper for the old DiscordDataCacher API."""
        self.upsert_user(user_id=user_id, user_name=user_name)

    def set_user_profile_notes(self, user_id: int, notes: str) -> None:
        """Update profile notes for one user."""
        if not self.connected:
            constants.MAIN_LOG.log(Error("Database not connected. Cannot update notes."))
            return
        try:
            self.cursor.execute(
                """
                UPDATE users
                SET notes = ?
                WHERE id = ?
                """,
                (notes, user_id),
            )
            self.connection.commit()
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error updating user notes: {e}"))
            raise e

    def get_user_profile(self, user_id: int) -> UserProfile | None:
        """Load a structured user profile."""
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot retrieve user profile.")
            )
            return None
        try:
            self.cursor.execute(
                """
                SELECT id, name, nick, notes, last_message_uuid, last_seen_at
                FROM users
                WHERE id = ?
                """,
                (user_id,),
            )
            row = self.cursor.fetchone()
            if not row:
                return None
            return UserProfile(
                user_id=row[0],
                name=row[1],
                nick=row[2],
                notes=row[3],
                last_message_uuid=row[4],
                last_seen_at=row[5],
            )
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error retrieving user profile: {e}"))
            raise e


class ConversationDatabaseManager(DatabaseManager):
    """Conversation history persistence for DOA.db with user linkage to users.db."""

    def __init__(
            self,
            db_path: str | None = None,
            users_manager: UsersDatabaseManager | None = None,
    ) -> None:
        self.users_manager = users_manager or UsersDatabaseManager(
            constants.USERS_DATABASE_FILE
        )
        super().__init__(db_path)

    def initialize_tables(self) -> None:
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot initialize tables.")
            )
            return
        try:
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations
                (
                    id INTEGER PRIMARY KEY
                )
                """
            )
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS messages
                (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    author_id       INTEGER,
                    author          TEXT    NOT NULL,
                    nick            TEXT,
                    reply_to        INTEGER,
                    content         TEXT    NOT NULL,
                    timestamp       INTEGER NOT NULL,
                    uuid            TEXT    NOT NULL,
                    UNIQUE (uuid) ON CONFLICT REPLACE,
                    FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE,
                    FOREIGN KEY (reply_to) REFERENCES messages (id) ON DELETE SET NULL
                )
                """
            )
            self.cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_conversation_timestamp
                    ON messages (conversation_id, timestamp)
                """
            )
            self.cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_author_id
                    ON messages (author_id)
                """
            )
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS attachments
                (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL,
                    type       TEXT    NOT NULL,
                    filename   TEXT    NOT NULL,
                    url        TEXT,
                    data       BLOB,
                    FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE
                )
                """
            )
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS moderations
                (
                    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id             INTEGER NOT NULL,
                    flagged                BOOLEAN NOT NULL,
                    moderated              BOOLEAN NOT NULL,
                    harassment             BOOLEAN NOT NULL,
                    harassment_threatening BOOLEAN NOT NULL,
                    sexual                 BOOLEAN NOT NULL,
                    hate                   BOOLEAN NOT NULL,
                    hate_threatening       BOOLEAN NOT NULL,
                    illicit                BOOLEAN NOT NULL,
                    illicit_violent        BOOLEAN NOT NULL,
                    self_harm_intent       BOOLEAN NOT NULL,
                    self_harm_instruction  BOOLEAN NOT NULL,
                    self_harm              BOOLEAN NOT NULL,
                    sexual_minors          BOOLEAN NOT NULL,
                    violence               BOOLEAN NOT NULL,
                    violence_graphic       BOOLEAN NOT NULL,
                    banned_word            TEXT,
                    FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE
                )
                """
            )
            self.connection.commit()
            constants.MAIN_LOG.log(Info("Conversation tables initialized successfully."))
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error initializing database tables: {e}"))
            raise e

    @staticmethod
    def _moderation_from_row(row: tuple) -> ModerationResult:
        (
            flagged,
            moderated,
            harassment,
            harassment_threatening,
            sexual,
            hate,
            hate_threatening,
            illicit,
            illicit_violent,
            self_harm_intent,
            self_harm_instruction,
            self_harm,
            sexual_minors,
            violence,
            violence_graphic,
            banned_word,
        ) = row
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
            banned_word=banned_word,
        )
        return ModerationResult(
            flagged=bool(flagged), moderated=bool(moderated), categories=categories
        )

    def resolve_moderations(self, message_id: int) -> ModerationResult | None:
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot retrieve moderation.")
            )
            return None
        try:
            self.cursor.execute(
                """
                SELECT flagged,
                       moderated,
                       harassment,
                       harassment_threatening,
                       sexual,
                       hate,
                       hate_threatening,
                       illicit,
                       illicit_violent,
                       self_harm_intent,
                       self_harm_instruction,
                       self_harm,
                       sexual_minors,
                       violence,
                       violence_graphic,
                       banned_word
                FROM moderations
                WHERE message_id = ?
                """,
                (message_id,),
            )
            row = self.cursor.fetchone()
            return self._moderation_from_row(row) if row else None
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error retrieving moderation: {e}"))
            raise e

    def resolve_attachments(self, message_id: int) -> list:
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot retrieve attachments.")
            )
            return []
        try:
            self.cursor.execute(
                """
                SELECT type, filename, url, data
                FROM attachments
                WHERE message_id = ?
                """,
                (message_id,),
            )
            rows = self.cursor.fetchall()
            attachments = []
            for attachment_type, filename, url, data in rows:
                file_format = filename.split(".")[-1].lower() if "." in filename else ""
                match attachment_type:
                    case ImageAttachment.__name__:
                        attachment = ImageAttachment(filename=filename, url=url, data=data)
                    case TextAttachment.__name__:
                        attachment = TextAttachment(filename=filename, data=data)
                    case AudioAttachment.__name__:
                        attachment = AudioAttachment(
                            filename=filename,
                            data=data,
                            file_format=file_format,
                        )
                    case VideoAttachment.__name__:
                        attachment = VideoAttachment(
                            filename=filename,
                            data=data,
                            file_format=file_format,
                        )
                    case _:
                        constants.MAIN_LOG.log(
                            Error(f"Unknown attachment type: {attachment_type}")
                        )
                        continue
                attachments.append(attachment)
            return attachments
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error retrieving attachments: {e}"))
            raise e

    def _create_message_from_row(self, row: tuple, message_id: int) -> Message:
        author_id, author, nick, content, timestamp, uuid_value = row
        if author == "Daughter of Anton":
            message = AntonMessage(content=content)
        else:
            message = Message(
                content,
                author=Person(name=author, nick=nick, user_id=str(author_id) if author_id else None),
                context=False,
            )
        message.uuid = uuid_value
        message.timestamp = timestamp
        message.attachments = self.resolve_attachments(message_id)
        message.moderation = self.resolve_moderations(message_id)
        return message

    def resolve_replies(self, initial_id: int | None) -> Message | None:
        if initial_id is None:
            return None
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot retrieve message.")
            )
            return None
        try:
            self.cursor.execute(
                """
                SELECT author_id, author, nick, content, timestamp, reply_to, uuid
                FROM messages
                WHERE id = ?
                """,
                (initial_id,),
            )
            row = self.cursor.fetchone()
            if not row:
                return None

            result = self._create_message_from_row(
                (row[0], row[1], row[2], row[3], row[4], row[6]), initial_id
            )
            next_to_retrieve = row[5]
            current = result
            while next_to_retrieve:
                self.cursor.execute(
                    """
                    SELECT author_id, author, nick, content, timestamp, reply_to, uuid
                    FROM messages
                    WHERE id = ?
                    """,
                    (next_to_retrieve,),
                )
                reply_row = self.cursor.fetchone()
                if not reply_row:
                    break
                reply_message = self._create_message_from_row(
                    (
                        reply_row[0],
                        reply_row[1],
                        reply_row[2],
                        reply_row[3],
                        reply_row[4],
                        reply_row[6],
                    ),
                    next_to_retrieve,
                )
                current.reference = reply_message
                current = reply_message
                next_to_retrieve = reply_row[5]
            return result
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error retrieving message by ID: {e}"))
            raise e

    def get_id_from_uuid(self, uuid: str) -> int | None:
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot retrieve message ID.")
            )
            return None
        try:
            self.cursor.execute(
                """
                SELECT id
                FROM messages
                WHERE uuid = ?
                """,
                (uuid,),
            )
            row = self.cursor.fetchone()
            return row[0] if row else None
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error retrieving message ID by UUID: {e}"))
            raise e

    def get_message_from_uuid(self, uuid: str) -> Message | None:
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

    @staticmethod
    def _extract_author_id(message: Message) -> int | None:
        if message.author.name == "Daughter of Anton":
            return None
        if not message.author.id:
            return None
        if isinstance(message.author.id, int):
            return message.author.id
        if str(message.author.id).isdigit():
            return int(message.author.id)
        return None

    def _save_message_moderation(self, message_id: int, moderation: ModerationResult) -> None:
        cat = moderation.categories
        self.cursor.execute(
            """
            INSERT INTO moderations (message_id, flagged, moderated, harassment, harassment_threatening,
                                     sexual, hate, hate_threatening, illicit, illicit_violent,
                                     self_harm_intent, self_harm_instruction, self_harm,
                                     sexual_minors, violence, violence_graphic, banned_word)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                int(moderation.flagged),
                int(moderation.moderated),
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
                str(cat.banned_word) if cat.banned_word else None,
            ),
        )

    def save_conversation(self, channel_id: int, conversation: Conversation) -> None:
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot save conversation.")
            )
            return
        try:
            self.cursor.execute("SELECT id FROM conversations WHERE id = ?", (channel_id,))
            row = self.cursor.fetchone()
            conversation_id = row[0] if row else channel_id
            if not row:
                self.cursor.execute(
                    "INSERT INTO conversations (id) VALUES (?)", (conversation_id,)
                )

            self.cursor.execute(
                "SELECT id FROM messages WHERE conversation_id = ?", (conversation_id,)
            )
            old_message_ids = [message_row[0] for message_row in self.cursor.fetchall()]
            for old_message_id in old_message_ids:
                self.cursor.execute("DELETE FROM attachments WHERE message_id = ?", (old_message_id,))
                self.cursor.execute("DELETE FROM moderations WHERE message_id = ?", (old_message_id,))
            self.cursor.execute(
                "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
            )

            uuid_to_id: dict[str, int] = {}
            pending_replies: list[tuple[int, str]] = []

            for message in conversation.messages:
                author_id = self._extract_author_id(message)
                if author_id is not None:
                    self.users_manager.upsert_user(
                        user_id=author_id,
                        user_name=message.author.name,
                        nick=message.author.nick,
                        last_message_uuid=message.uuid,
                        last_seen_at=int(message.timestamp),
                    )

                self.cursor.execute(
                    """
                    INSERT INTO messages (conversation_id, author_id, author, nick, reply_to, content, timestamp, uuid)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        conversation_id,
                        author_id,
                        message.author.name,
                        message.author.nick,
                        None,
                        message.content,
                        int(message.timestamp),
                        message.uuid,
                    ),
                )
                message_id = self.cursor.lastrowid
                uuid_to_id[message.uuid] = message_id

                if message.reference and message.reference.uuid:
                    pending_replies.append((message_id, message.reference.uuid))

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
                            getattr(attachment, "url", None),
                            getattr(attachment, "data", None),
                        ),
                    )

                if message.moderation:
                    self._save_message_moderation(message_id, message.moderation)

            for message_id, reference_uuid in pending_replies:
                reply_to_id = uuid_to_id.get(reference_uuid)
                if reply_to_id is None:
                    reply_to_id = self.get_id_from_uuid(reference_uuid)
                if reply_to_id is not None:
                    self.cursor.execute(
                        "UPDATE messages SET reply_to = ? WHERE id = ?",
                        (reply_to_id, message_id),
                    )

            self.connection.commit()
            constants.MAIN_LOG.log(Info(f"Conversation saved for channel {channel_id}"))
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error saving conversation: {e}"))
            raise e

    def load_conversation(self, channel_id: int) -> Conversation:
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot load conversation.")
            )
            return Conversation()
        try:
            self.cursor.execute("SELECT id FROM conversations WHERE id = ?", (channel_id,))
            row = self.cursor.fetchone()
            if not row:
                constants.MAIN_LOG.log(
                    Info(f"No conversation found for channel {channel_id}")
                )
                return Conversation()

            self.cursor.execute(
                """
                SELECT id
                FROM messages
                WHERE conversation_id = ?
                ORDER BY timestamp ASC
                """,
                (row[0],),
            )
            message_rows = self.cursor.fetchall()
            conversation = Conversation()
            for (message_id,) in message_rows:
                message = self.resolve_replies(message_id)
                if message:
                    conversation.add_message(message)
            constants.MAIN_LOG.log(Info(f"Conversation loaded for channel {channel_id}"))
            return conversation
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error loading conversation: {e}"))
            raise e

    def load_conversations(self) -> dict[int, Conversation]:
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot load conversations.")
            )
            return {}
        conversations_dict: dict[int, Conversation] = {}
        try:
            self.cursor.execute("SELECT id FROM conversations")
            conversation_rows = self.cursor.fetchall()
            for (conversation_id,) in conversation_rows:
                self.cursor.execute(
                    """
                    SELECT id
                    FROM messages
                    WHERE conversation_id = ?
                    ORDER BY timestamp
                    """,
                    (conversation_id,),
                )
                message_rows = self.cursor.fetchall()
                conversation = Conversation()
                for (message_id,) in message_rows:
                    message = self.resolve_replies(message_id)
                    if message:
                        conversation.add_message(message)
                conversations_dict[conversation_id] = conversation
            constants.MAIN_LOG.log(Info("All messages loaded from database."))
            return conversations_dict
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error loading conversations: {e}"))
            raise e

    def delete_conversation(self, channel_id: int) -> None:
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot delete conversation.")
            )
            return
        try:
            self.cursor.execute("SELECT id FROM conversations WHERE id = ?", (channel_id,))
            row = self.cursor.fetchone()
            if not row:
                constants.MAIN_LOG.log(
                    Info(f"No conversation found for channel {channel_id} to delete.")
                )
                return

            conversation_id = row[0]
            self.cursor.execute(
                "SELECT id FROM messages WHERE conversation_id = ?", (conversation_id,)
            )
            message_ids = [message_row[0] for message_row in self.cursor.fetchall()]
            for message_id in message_ids:
                self.cursor.execute("DELETE FROM attachments WHERE message_id = ?", (message_id,))
                self.cursor.execute("DELETE FROM moderations WHERE message_id = ?", (message_id,))
            self.cursor.execute(
                "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
            )
            self.cursor.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            self.connection.commit()
            constants.MAIN_LOG.log(Info(f"Conversation deleted for channel {channel_id}"))
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error deleting conversation: {e}"))
            raise e

    def get_all_message_history_for_user(
            self, user_id: int
    ) -> list[UserMessageHistoryEntry]:
        """Return all persisted conversation messages authored by one user ID."""
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot load user message history.")
            )
            return []
        try:
            self.cursor.execute(
                """
                SELECT id, conversation_id, uuid, content, timestamp, author, nick
                FROM messages
                WHERE author_id = ?
                ORDER BY timestamp ASC
                """,
                (user_id,),
            )
            rows = self.cursor.fetchall()
            return [
                UserMessageHistoryEntry(
                    message_id=row[0],
                    conversation_id=row[1],
                    uuid=row[2],
                    content=row[3],
                    timestamp=row[4],
                    author_name=row[5],
                    author_nick=row[6],
                )
                for row in rows
            ]
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Error loading user message history: {e}"))
            raise e

    def get_all_moderation_history_for_user(
            self, user_id: int
    ) -> list[UserModerationHistoryEntry]:
        """Return moderation records for every persisted message authored by one user ID."""
        if not self.connected:
            constants.MAIN_LOG.log(
                Error("Database not connected. Cannot load user moderation history.")
            )
            return []
        try:
            self.cursor.execute(
                """
                SELECT m.id,
                       m.conversation_id,
                       m.uuid,
                       m.timestamp,
                       md.flagged,
                       md.moderated,
                       md.harassment,
                       md.harassment_threatening,
                       md.sexual,
                       md.hate,
                       md.hate_threatening,
                       md.illicit,
                       md.illicit_violent,
                       md.self_harm_intent,
                       md.self_harm_instruction,
                       md.self_harm,
                       md.sexual_minors,
                       md.violence,
                       md.violence_graphic,
                       md.banned_word
                FROM messages m
                         INNER JOIN moderations md ON md.message_id = m.id
                WHERE m.author_id = ?
                ORDER BY m.timestamp ASC
                """,
                (user_id,),
            )
            rows = self.cursor.fetchall()
            history: list[UserModerationHistoryEntry] = []
            for row in rows:
                moderation = self._moderation_from_row(row[4:])
                history.append(
                    UserModerationHistoryEntry(
                        message_id=row[0],
                        conversation_id=row[1],
                        uuid=row[2],
                        timestamp=row[3],
                        moderation=moderation,
                    )
                )
            return history
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(
                Error(f"Error loading user moderation history: {e}")
            )
            raise e

    def get_user_history(self, user_id: int) -> UserHistoryBundle:
        """Return profile + full message/moderation history for one user ID."""
        return UserHistoryBundle(
            profile=self.users_manager.get_user_profile(user_id),
            messages=self.get_all_message_history_for_user(user_id),
            moderations=self.get_all_moderation_history_for_user(user_id),
        )


# Backward-compatible aliases while main code migrates to UsersDatabaseManager.
UserDataManager = UsersDatabaseManager
UserProfileManager = UsersDatabaseManager
DiscordDataCacher = UsersDatabaseManager
