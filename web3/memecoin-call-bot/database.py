import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any


@dataclass
class Signal:
    ca: str
    symbol: str
    name: str
    chain: str
    creator_id: int
    status: str = "ACTIVE"
    message_id: Optional[int] = None
    alert_channel_id: Optional[int] = None
    callers: list[dict] = field(default_factory=list)
    market_cap: Optional[float] = None
    price: Optional[float] = None
    volume_24h: Optional[float] = None
    liquidity: Optional[float] = None
    gmgn_score: Optional[float] = None
    pump_score: Optional[float] = None
    fomo_score: Optional[float] = None
    gmgn_count: int = 0
    pump_count: int = 0
    fomo_count: int = 0
    website_url: Optional[str] = None
    twitter_url: Optional[str] = None
    telegram_url: Optional[str] = None
    chart_url: Optional[str] = None
    launchpad: Optional[str] = None
    image_url: Optional[str] = None
    last_error: Optional[str] = None
    discord_call_timestamp: Optional[float] = None  # Unix timestamp when Discord call was created

    # Provider caller lists (not stored in DB, set by signal_manager)
    _gmgn_callers: list[dict] = field(default_factory=list, repr=False)
    _pump_callers: list[dict] = field(default_factory=list, repr=False)
    _fomo_callers: list[dict] = field(default_factory=list, repr=False)
    _historical_smart_callers: list[dict] = field(default_factory=list, repr=False)


class Database:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS signals (
                ca TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                chain TEXT NOT NULL,
                creator_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                message_id INTEGER,
                alert_channel_id INTEGER,
                callers_json TEXT NOT NULL DEFAULT '[]',
                market_cap REAL,
                price REAL,
                volume_24h REAL,
                liquidity REAL,
                gmgn_score REAL,
                pump_score REAL,
                fomo_score REAL,
                gmgn_count INTEGER NOT NULL DEFAULT 0,
                pump_count INTEGER NOT NULL DEFAULT 0,
                fomo_count INTEGER NOT NULL DEFAULT 0,
                website_url TEXT,
                twitter_url TEXT,
                telegram_url TEXT,
                chart_url TEXT,
                launchpad TEXT,
                image_url TEXT,
                last_error TEXT,
                discord_call_timestamp REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        self.conn.commit()

        # Forward migrations
        existing = {row[1] for row in self.conn.execute("PRAGMA table_info(signals)").fetchall()}
        migrations = {
            "website_url": "TEXT",
            "twitter_url": "TEXT",
            "telegram_url": "TEXT",
            "chart_url": "TEXT",
            "launchpad": "TEXT",
            "image_url": "TEXT",
            "discord_call_timestamp": "REAL",
        }
        for col, col_type in migrations.items():
            if col not in existing:
                self.conn.execute(f"ALTER TABLE signals ADD COLUMN {col} {col_type}")
        self.conn.commit()

    def _row_to_signal(self, row: sqlite3.Row) -> Signal:
        return Signal(
            ca=row["ca"],
            symbol=row["symbol"],
            name=row["name"],
            chain=row["chain"],
            creator_id=row["creator_id"],
            status=row["status"],
            message_id=row["message_id"],
            alert_channel_id=row["alert_channel_id"],
            callers=json.loads(row["callers_json"] or "[]"),
            market_cap=row["market_cap"],
            price=row["price"],
            volume_24h=row["volume_24h"],
            liquidity=row["liquidity"],
            gmgn_score=row["gmgn_score"],
            pump_score=row["pump_score"],
            fomo_score=row["fomo_score"],
            gmgn_count=row["gmgn_count"],
            pump_count=row["pump_count"],
            fomo_count=row["fomo_count"],
            website_url=row["website_url"],
            twitter_url=row["twitter_url"],
            telegram_url=row["telegram_url"],
            chart_url=row["chart_url"],
            launchpad=row["launchpad"],
            image_url=row["image_url"],
            last_error=row["last_error"],
            discord_call_timestamp=row["discord_call_timestamp"],
        )

    def get_signal(self, ca: str) -> Optional[Signal]:
        row = self.conn.execute("SELECT * FROM signals WHERE ca = ?", (ca,)).fetchone()
        return self._row_to_signal(row) if row else None

    def get_active_signals(self) -> list[Signal]:
        rows = self.conn.execute("SELECT * FROM signals WHERE status = 'ACTIVE'").fetchall()
        return [self._row_to_signal(r) for r in rows]

    def insert_signal(self, signal: Signal):
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT INTO signals (
                ca, symbol, name, chain, creator_id, status, message_id, alert_channel_id,
                callers_json, market_cap, price, volume_24h, liquidity,
                gmgn_score, pump_score, fomo_score, gmgn_count, pump_count, fomo_count,
                website_url, twitter_url, telegram_url, chart_url, launchpad, image_url,
                last_error, discord_call_timestamp, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.ca, signal.symbol, signal.name, signal.chain, signal.creator_id,
                signal.status, signal.message_id, signal.alert_channel_id,
                json.dumps(signal.callers), signal.market_cap, signal.price,
                signal.volume_24h, signal.liquidity, signal.gmgn_score,
                signal.pump_score, signal.fomo_score, signal.gmgn_count,
                signal.pump_count, signal.fomo_count, signal.website_url,
                signal.twitter_url, signal.telegram_url, signal.chart_url,
                signal.launchpad, signal.image_url, signal.last_error, signal.discord_call_timestamp, now, now,
            ),
        )
        self.conn.commit()

    def update_signal(self, signal: Signal):
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            UPDATE signals SET
                symbol=?, name=?, chain=?, creator_id=?, status=?, message_id=?, alert_channel_id=?,
                callers_json=?, market_cap=?, price=?, volume_24h=?, liquidity=?,
                gmgn_score=?, pump_score=?, fomo_score=?, gmgn_count=?, pump_count=?, fomo_count=?,
                website_url=?, twitter_url=?, telegram_url=?, chart_url=?, launchpad=?, image_url=?,
                last_error=?, discord_call_timestamp=?, updated_at=?
            WHERE ca=?
            """,
            (
                signal.symbol, signal.name, signal.chain, signal.creator_id, signal.status,
                signal.message_id, signal.alert_channel_id, json.dumps(signal.callers),
                signal.market_cap, signal.price, signal.volume_24h, signal.liquidity,
                signal.gmgn_score, signal.pump_score, signal.fomo_score,
                signal.gmgn_count, signal.pump_count, signal.fomo_count,
                signal.website_url, signal.twitter_url, signal.telegram_url, signal.chart_url,
                signal.launchpad, signal.image_url, signal.last_error, signal.discord_call_timestamp, now, signal.ca,
            ),
        )
        self.conn.commit()

    def add_caller(self, ca: str, user_id: int, username: str) -> Optional[Signal]:
        signal = self.get_signal(ca)
        if not signal:
            return None
        if not any(int(c["user_id"]) == user_id for c in signal.callers):
            signal.callers.append({"user_id": user_id, "username": username})
        self.update_signal(signal)
        return signal

    def stop_signal(self, ca: str) -> Optional[Signal]:
        signal = self.get_signal(ca)
        if not signal:
            return None
        signal.status = "STOPPED"
        self.update_signal(signal)
        return signal

    def update_social_metrics(self, ca: str, metrics: dict):
        signal = self.get_signal(ca)
        if not signal:
            return None
        for attr in (
            "gmgn_score", "pump_score", "fomo_score", "gmgn_count",
            "pump_count", "fomo_count", "market_cap", "price", "volume_24h", "liquidity",
            "website_url", "twitter_url", "telegram_url", "chart_url", "launchpad", "image_url", "chain"
        ):
            if attr in metrics:
                setattr(signal, attr, metrics[attr])
        signal.last_error = metrics.get("last_error")
        self.update_signal(signal)
        return signal

    def close(self):
        self.conn.close()