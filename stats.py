import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).with_name("poker_stats.db")
STREETS = ("pre-flop", "flop", "turn", "river")
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
    raise_pct REAL,
    allin_pct REAL,
    input_tokens INTEGER,
    avg_input_tokens REAL
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
    input_tokens INTEGER
);
"""


def summarize(hands, decisions):
    """Turn the batch's hands and decisions into its statistics.

    hands: list of (seat, ended_street, net_chips).
    decisions: list of (hand_number, street, move, input_tokens).

    Win percentages are out of all hands, so the per-street ones add up to the
    overall one. A split pot is not a win. Move percentages are out of all of
    Jev's decisions.
    """
    count = len(hands)
    wins = [street for _, street, net in hands if net > 0]
    moves = [move.split()[0] for _, _, move, _ in decisions]
    tokens = sum(t or 0 for *_, t in decisions)
    net_chips = sum(net for _, _, net in hands)
    stats = {
        "hands": count,
        "won_pct": 100 * len(wins) / count,
        "net_chips": net_chips,
        "avg_net_chips": net_chips / count,
        "decisions": len(moves),
        "input_tokens": tokens,
        "avg_input_tokens": tokens / (len(moves) or 1),
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


def save_batch(jev_version, improvement, opponent, hands, decisions):
    stats = summarize(hands, decisions)
    connection = sqlite3.connect(DB_PATH)
    with connection:
        connection.executescript(SCHEMA)
        add_missing_columns(connection)
        connection.execute(
            "INSERT OR REPLACE INTO jev_versions VALUES (?, ?)", (jev_version, improvement)
        )
        columns = ", ".join(stats)
        placeholders = ", ".join("?" * len(stats))
        batch_id = connection.execute(
            f"INSERT INTO batches (played_at, jev_version, opponent, {columns}) "
            f"VALUES (?, ?, ?, {placeholders})",
            (datetime.now().isoformat(timespec="seconds"), jev_version, opponent, *stats.values()),
        ).lastrowid
        connection.executemany(
            "INSERT INTO hands VALUES (?, ?, ?, ?, ?)",
            [(batch_id, number, *hand) for number, hand in enumerate(hands, 1)],
        )
        connection.executemany(
            "INSERT INTO decisions VALUES (?, ?, ?, ?, ?)",
            [(batch_id, *decision) for decision in decisions],
        )
    connection.close()
    return batch_id, stats
