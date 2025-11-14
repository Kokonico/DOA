"""SQL database management for Daughter of Anton"""
import sqlite3
from sqlite3 import Connection, Cursor
import constants
from objlog.LogMessages import Info, Error, Debug
DB_FILE = 'daughter_of_anton.db'

class DatabaseManager:
    """
    Manages the SQLite database for Daughter of Anton.
    """

    db_path: str = DB_FILE
    connection: Connection | None = None
    cursor: Cursor | None = None

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
        except sqlite3.Error as e:
            constants.MAIN_LOG.log(Error(f"Database connection error: {e}"))
            raise e
    def initialize_tables(self) -> None:
        """Create necessary tables if they do not exist."""
        # how conversations work:
        # each conversation has a bunch of messages
        # each message has an author and content