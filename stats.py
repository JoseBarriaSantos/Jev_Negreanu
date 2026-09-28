import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

# Online, DB_PATH points at Render's disk so the database survives updates.
DB_PATH = Path(os.environ.get("DB_PATH") or Path(__file__).with_name("poker_stats.db"))
STREET_COLUMNS = {
    "pre-flop": "won_preflop_pct",
    "flop": "won_flop_pct",
    "turn": "won_turn_pct",
    "river": "won_river_pct",
}
MOVE_COLUMNS = {
    "fold": "fold_pct",
    "check": "check_pct",
    "call": "call_pct",
    "bet": "bet_pct",
    "raise": "raise_pct",
    "all-in": "allin_pct",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY,
    played_at TEXT,
    jev_version TEXT,
    opponent TEXT,
    hands INTEGER,
    won_pct REAL,
    won_preflop_pct REAL,
    won_flop_pct REAL,
    won_turn_pct REAL,
    won_river_pct REAL,
    net_chips INTEGER,
    avg_net_chips REAL,
    decisions INTEGER,
    fold_pct REAL,
    check_pct REAL,
    call_pct REAL,
    bet_pct REAL,
    raise_pct REAL,
    allin_pct REAL,
    input_tokens INTEGER,
    avg_input_tokens REAL,
    seconds REAL,
    jev_api_seconds REAL,
    jev_strength_seconds REAL,
    opponent_seconds REAL
);
CREATE TABLE IF NOT EXISTS jev_versions (
    version TEXT PRIMARY KEY,
    improvement TEXT
);
CREATE TABLE IF NOT EXISTS hands (
    batch_id INTEGER REFERENCES batches(id),
    hand_number INTEGER,
    seat INTEGER,
    ended_street TEXT,
    net_chips INTEGER
);
CREATE TABLE IF NOT EXISTS decisions (
    batch_id INTEGER REFERENCES batches(id),
    hand_number INTEGER,
    street TEXT,
    move TEXT,
    input_tokens INTEGER,
    strength_seconds REAL,
    api_seconds REAL
);
"""


def summarize(hands, decisions):
    """Turn the batch's hands and decisions into its statistics.

    hands: list of (seat, ended_street, net_chips).
    decisions: list of (hand_number, street, move, input_tokens,
        strength_seconds, api_seconds).

    Win percentages are out of all hands, so the per-street ones add up to the
    overall one. A split pot is not a win. Move percentages are out of all of
    Jev's decisions.
    """
    count = len(hands)
    wins = [street for _, street, net in hands if net > 0]
    moves = [decision[2].split()[0] for decision in decisions]
    tokens = sum(decision[3] or 0 for decision in decisions)
    net_chips = sum(net for _, _, net in hands)
    stats = {
        "hands": count,
        "won_pct": 100 * len(wins) / count,
        "net_chips": net_chips,
        "avg_net_chips": net_chips / count,
        "decisions": len(moves),
        "input_tokens": tokens,
        "avg_input_tokens": tokens / (len(moves) or 1),
        "jev_strength_seconds": sum(decision[4] for decision in decisions),
        "jev_api_seconds": sum(decision[5] for decision in decisions),
    }
    for street, column in STREET_COLUMNS.items():
        stats[column] = 100 * wins.count(street) / count
    for move, column in MOVE_COLUMNS.items():
        stats[column] = 100 * moves.count(move) / (len(moves) or 1)
    return stats


def add_missing_columns(connection):
    """Add columns that were added to SCHEMA after the database file was created.

    Builds a blank copy of SCHEMA in memory and adds any column it has that the
    real database is missing. Old rows get an empty value in the new columns.
    """
    fresh = sqlite3.connect(":memory:")
    fresh.executescript(SCHEMA)
    for (table,) in fresh.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
        existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        for _, name, column_type, *_ in fresh.execute(f"PRAGMA table_info({table})"):
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}")
    fresh.close()


def connect():
    connection = sqlite3.connect(DB_PATH)
    with connection:
        connection.executescript(SCHEMA)
        add_missing_columns(connection)
    return connection


def start_batch(connection, jev_version, improvement, opponent, played_at=None):
    """Create an empty batch row; its stats are filled in by update_summary."""
    connection.execute("INSERT OR REPLACE INTO jev_versions VALUES (?, ?)", (jev_version, improvement))
    return connection.execute(
        "INSERT INTO batches (played_at, jev_version, opponent) VALUES (?, ?, ?)",
        ((played_at or datetime.now()).isoformat(timespec="seconds"), jev_version, opponent),
    ).lastrowid


def add_hand(connection, batch_id, hand_number, hand, decisions):
    """Save one hand, (seat, ended_street, net_chips), and Jev's decisions in it."""
    connection.execute("INSERT INTO hands VALUES (?, ?, ?, ?, ?)", (batch_id, hand_number, *hand))
    connection.executemany(
        "INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(batch_id, *decision) for decision in decisions],
    )


def update_summary(connection, batch_id, hands, decisions, timings):
    stats = summarize(hands, decisions) | timings
    assignments = ", ".join(f"{column} = ?" for column in stats)
    connection.execute(f"UPDATE batches SET {assignments} WHERE id = ?", (*stats.values(), batch_id))
    return stats


def save_batch(jev_version, improvement, opponent, hands, decisions, timings):
    """Save a whole batch at once (the bot-vs-bot runs in bot.py)."""
    with closing(connect()) as connection, connection:
        batch_id = start_batch(connection, jev_version, improvement, opponent)
        for number, hand in enumerate(hands, 1):
            add_hand(connection, batch_id, number, hand, [d for d in decisions if d[0] == number])
        stats = update_summary(connection, batch_id, hands, decisions, timings)
    return batch_id, stats
