from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterable

from .model import AnimalState, Account, CharacterState, GroundItem, InventoryItem, MapState, PlantMetadata, PlotState


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'UNKNOW',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS characters (
    character_id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL UNIQUE REFERENCES accounts(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    secondary_name TEXT NOT NULL DEFAULT '',
    slot INTEGER NOT NULL DEFAULT 1,
    level INTEGER NOT NULL DEFAULT 1,
    kind INTEGER NOT NULL DEFAULT -1,
    direction INTEGER NOT NULL DEFAULT 5,
    x INTEGER NOT NULL DEFAULT 120,
    y INTEGER NOT NULL DEFAULT 216,
    exp INTEGER NOT NULL DEFAULT 0,
    max_exp INTEGER NOT NULL DEFAULT 10,
    health INTEGER NOT NULL DEFAULT 10,
    max_health INTEGER NOT NULL DEFAULT 10,
    gold INTEGER NOT NULL DEFAULT 0,
    premium INTEGER NOT NULL DEFAULT 0,
    appearance_y INTEGER NOT NULL DEFAULT 1,
    appearance_z INTEGER NOT NULL DEFAULT 0,
    appearance_a INTEGER NOT NULL DEFAULT 0,
    appearance_b INTEGER NOT NULL DEFAULT -1,
    state_u INTEGER NOT NULL DEFAULT 8,
    state_w INTEGER NOT NULL DEFAULT 0,
    state_q INTEGER NOT NULL DEFAULT 0,
    birth_day INTEGER NOT NULL DEFAULT 1,
    birth_season INTEGER NOT NULL DEFAULT 0,
    inventory_capacity INTEGER NOT NULL DEFAULT 30,
    inventory_count INTEGER NOT NULL DEFAULT 0,
    status_json TEXT NOT NULL DEFAULT '[0,0,0,0]',
    storage_json TEXT NOT NULL DEFAULT '[]',
    equipment_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inventory_items (
    character_id INTEGER NOT NULL REFERENCES characters(character_id) ON DELETE CASCADE,
    slot INTEGER NOT NULL,
    kind INTEGER NOT NULL,
    item_id INTEGER NOT NULL DEFAULT 0,
    name TEXT NOT NULL DEFAULT '',
    subtype INTEGER NOT NULL DEFAULT 0,
    icon_type INTEGER NOT NULL DEFAULT 0,
    label TEXT NOT NULL DEFAULT '',
    growth_count INTEGER NOT NULL DEFAULT 0,
    stack_value INTEGER NOT NULL DEFAULT 0,
    required_level INTEGER NOT NULL DEFAULT 0,
    stars INTEGER NOT NULL DEFAULT 0,
    quantity INTEGER NOT NULL DEFAULT 0,
    highlighted INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '',
    detail_id INTEGER NOT NULL DEFAULT 0,
    detail_byte_a INTEGER NOT NULL DEFAULT 0,
    detail_byte_b INTEGER NOT NULL DEFAULT 0,
    detail_short INTEGER NOT NULL DEFAULT 0,
    detail_byte_c INTEGER NOT NULL DEFAULT 0,
    value_byte_a INTEGER NOT NULL DEFAULT 0,
    value_byte_b INTEGER NOT NULL DEFAULT 0,
    value_flag INTEGER NOT NULL DEFAULT 0,
    image_data BLOB NOT NULL DEFAULT X'',
    extra_short INTEGER NOT NULL DEFAULT 0,
    expiry_short INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (character_id, slot)
);

CREATE TABLE IF NOT EXISTS farm_states (
    character_id INTEGER PRIMARY KEY REFERENCES characters(character_id) ON DELETE CASCADE,
    farm_id INTEGER,
    map_id INTEGER NOT NULL DEFAULT 1,
    map_type INTEGER NOT NULL DEFAULT 0,
    name TEXT NOT NULL DEFAULT 'map',
    auxiliary INTEGER NOT NULL DEFAULT 0,
    plots_json TEXT NOT NULL DEFAULT '[]',
    npc_flags_json TEXT NOT NULL DEFAULT '[]',
    plant_metadata_json TEXT NOT NULL DEFAULT '[]',
    animal_states_json TEXT NOT NULL DEFAULT '[]',
    weather_flags_json TEXT NOT NULL DEFAULT '[false,false,false]',
    map_tail_flag INTEGER NOT NULL DEFAULT 0,
    ground_items_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_inventory_character ON inventory_items(character_id);
"""


class GameDatabase:
    """Small synchronous SQLite repository used by the asyncio game server.

    SQLite is kept behind this class so the protocol handlers do not depend on
    SQL details. A file path enables restart persistence; ``:memory:`` keeps
    unit tests isolated.
    """

    def __init__(self, path: str = "data/nlcg119.db") -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=10.0)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 10000")
        if path != ":memory:":
            self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript(SCHEMA)
        self._ensure_schema_compatibility()
        self.connection.commit()

    def _ensure_schema_compatibility(self) -> None:
        """Migrate databases created by v0.10 before gameplay persistence."""
        additions = {
            "characters": {
                "storage_json": "TEXT NOT NULL DEFAULT '[]'",
                "equipment_json": "TEXT NOT NULL DEFAULT '{}'",
            },
            "inventory_items": {"expiry_short": "INTEGER NOT NULL DEFAULT 0"},
            "farm_states": {
                "farm_id": "INTEGER",
                "plant_metadata_json": "TEXT NOT NULL DEFAULT '[]'",
                "animal_states_json": "TEXT NOT NULL DEFAULT '[]'",
                "weather_flags_json": "TEXT NOT NULL DEFAULT '[false,false,false]'",
                "map_tail_flag": "INTEGER NOT NULL DEFAULT 0",
                "ground_items_json": "TEXT NOT NULL DEFAULT '[]'",
            },
        }
        for table, columns in additions.items():
            existing = {
                row["name"]
                for row in self.connection.execute(f"PRAGMA table_info({table})")
            }
            for column, definition in columns.items():
                if column not in existing:
                    self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def close(self) -> None:
        self.connection.close()

    def _row_to_item(self, row: sqlite3.Row) -> InventoryItem:
        return InventoryItem(
            kind=row["kind"],
            item_id=row["item_id"],
            name=row["name"],
            subtype=row["subtype"],
            icon_type=row["icon_type"],
            label=row["label"],
            growth_count=row["growth_count"],
            stack_value=row["stack_value"],
            required_level=row["required_level"],
            stars=row["stars"],
            quantity=row["quantity"],
            highlighted=bool(row["highlighted"]),
            description=row["description"],
            detail_id=row["detail_id"],
            detail_byte_a=row["detail_byte_a"],
            detail_byte_b=row["detail_byte_b"],
            detail_short=row["detail_short"],
            detail_byte_c=row["detail_byte_c"],
            value_byte_a=row["value_byte_a"],
            value_byte_b=row["value_byte_b"],
            value_flag=bool(row["value_flag"]),
            image_data=bytes(row["image_data"]),
            extra_short=row["extra_short"],
            expiry_short=row["expiry_short"] if "expiry_short" in row.keys() else 0,
        )

    @staticmethod
    def _item_to_dict(item: InventoryItem) -> dict:
        values = {
            key: getattr(item, key)
            for key in InventoryItem.__dataclass_fields__
        }
        values["image_data"] = item.image_data.hex()
        return values

    @staticmethod
    def _item_from_dict(values: dict) -> InventoryItem:
        data = dict(values)
        try:
            data["image_data"] = bytes.fromhex(str(data.get("image_data", "")))
        except ValueError:
            data["image_data"] = b""
        allowed = set(InventoryItem.__dataclass_fields__)
        return InventoryItem(**{key: value for key, value in data.items() if key in allowed})

    @classmethod
    def _items_from_json(cls, raw: str | None) -> list[InventoryItem]:
        try:
            values = json.loads(raw or "[]")
            return [cls._item_from_dict(value) for value in values if isinstance(value, dict)]
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    def _row_to_character(self, row: sqlite3.Row) -> CharacterState:
        items = [
            self._row_to_item(item_row)
            for item_row in self.connection.execute(
                "SELECT * FROM inventory_items WHERE character_id = ? ORDER BY slot",
                (row["character_id"],),
            )
        ]
        try:
            status = [int(value) for value in json.loads(row["status_json"])]
        except (TypeError, ValueError, json.JSONDecodeError):
            status = [0, 0, 0, 0]
        storage_items = self._items_from_json(row["storage_json"] if "storage_json" in row.keys() else "[]")
        try:
            equipment_values = json.loads(row["equipment_json"] if "equipment_json" in row.keys() else "{}")
            equipment = {
                int(slot): self._item_from_dict(item)
                for slot, item in equipment_values.items()
                if isinstance(item, dict)
            }
        except (TypeError, ValueError, json.JSONDecodeError):
            equipment = {}
        return CharacterState(
            character_id=row["character_id"],
            name=row["name"],
            secondary_name=row["secondary_name"],
            slot=row["slot"],
            level=row["level"],
            kind=row["kind"],
            direction=row["direction"],
            x=row["x"],
            y=row["y"],
            exp=row["exp"],
            max_exp=row["max_exp"],
            health=row["health"],
            max_health=row["max_health"],
            gold=row["gold"],
            premium=row["premium"],
            appearance_y=row["appearance_y"],
            appearance_z=row["appearance_z"],
            appearance_a=row["appearance_a"],
            appearance_b=row["appearance_b"],
            state_u=row["state_u"],
            state_w=row["state_w"],
            state_q=row["state_q"],
            birth_day=row["birth_day"],
            birth_season=row["birth_season"],
            inventory_capacity=row["inventory_capacity"],
            inventory_items=items,
            inventory_count=row["inventory_count"],
            storage_items=storage_items,
            equipment=equipment,
            status=status,
        )

    def _row_to_account(self, row: sqlite3.Row) -> Account:
        character_row = self.connection.execute(
            "SELECT * FROM characters WHERE account_id = ?",
            (row["id"],),
        ).fetchone()
        character = self._row_to_character(character_row) if character_row else None
        return Account(
            username=row["username"],
            password=row["password"],
            provider=row["provider"],
            character=character,
        )

    def get_account(self, username: str) -> Account | None:
        row = self.connection.execute(
            "SELECT * FROM accounts WHERE username = ?",
            (username,),
        ).fetchone()
        return self._row_to_account(row) if row else None

    def all_accounts(self) -> list[Account]:
        rows = self.connection.execute("SELECT * FROM accounts ORDER BY id").fetchall()
        return [self._row_to_account(row) for row in rows]

    def ensure_account(self, account: Account) -> Account:
        """Insert a configuration account only when it is not already persisted."""
        self.connection.execute(
            "INSERT OR IGNORE INTO accounts(username, password, provider) VALUES (?, ?, ?)",
            (account.username, account.password, account.provider),
        )
        self.connection.commit()
        persisted = self.get_account(account.username)
        if persisted is None:
            raise RuntimeError("failed to persist account")
        if persisted.character is None and account.character is not None:
            self.save_character(persisted.username, account.character)
            persisted = self.get_account(account.username) or persisted
        return persisted

    def create_account(self, account: Account) -> Account:
        self.connection.execute(
            "INSERT INTO accounts(username, password, provider) VALUES (?, ?, ?)",
            (account.username, account.password, account.provider),
        )
        self.connection.commit()
        return self.get_account(account.username) or account

    def save_character(self, username: str, character: CharacterState) -> None:
        account_row = self.connection.execute(
            "SELECT id FROM accounts WHERE username = ?",
            (username,),
        ).fetchone()
        if account_row is None:
            raise ValueError(f"account does not exist: {username}")
        account_id = account_row["id"]
        status_json = json.dumps(list(character.status[:4]), separators=(",", ":"))
        with self.connection:
            self.connection.execute(
                """INSERT INTO characters(
                    character_id, account_id, name, secondary_name, slot, level,
                    kind, direction, x, y, exp, max_exp, health, max_health,
                    gold, premium, appearance_y, appearance_z, appearance_a,
                    appearance_b, state_u, state_w, state_q, birth_day,
                    birth_season, inventory_capacity, inventory_count, status_json,
                    storage_json, equipment_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(character_id) DO UPDATE SET
                    account_id=excluded.account_id, name=excluded.name,
                    secondary_name=excluded.secondary_name, slot=excluded.slot,
                    level=excluded.level, kind=excluded.kind,
                    direction=excluded.direction, x=excluded.x, y=excluded.y,
                    exp=excluded.exp, max_exp=excluded.max_exp,
                    health=excluded.health, max_health=excluded.max_health,
                    gold=excluded.gold, premium=excluded.premium,
                    appearance_y=excluded.appearance_y,
                    appearance_z=excluded.appearance_z,
                    appearance_a=excluded.appearance_a,
                    appearance_b=excluded.appearance_b, state_u=excluded.state_u,
                    state_w=excluded.state_w, state_q=excluded.state_q,
                    birth_day=excluded.birth_day, birth_season=excluded.birth_season,
                    inventory_capacity=excluded.inventory_capacity,
                    inventory_count=excluded.inventory_count,
                    status_json=excluded.status_json,
                    storage_json=excluded.storage_json,
                    equipment_json=excluded.equipment_json,
                    updated_at=CURRENT_TIMESTAMP""",
                (
                    character.character_id,
                    account_id,
                    character.name,
                    character.secondary_name,
                    character.slot,
                    character.level,
                    character.kind,
                    character.direction,
                    character.x,
                    character.y,
                    character.exp,
                    character.max_exp,
                    character.health,
                    character.max_health,
                    character.gold,
                    character.premium,
                    character.appearance_y,
                    character.appearance_z,
                    character.appearance_a,
                    character.appearance_b,
                    character.state_u,
                    character.state_w,
                    character.state_q,
                    character.birth_day,
                    character.birth_season,
                    character.inventory_capacity,
                    len(character.inventory_items),
                    status_json,
                    json.dumps([self._item_to_dict(item) for item in character.storage_items], separators=(",", ":")),
                    json.dumps({str(slot): self._item_to_dict(item) for slot, item in character.equipment.items()}, separators=(",", ":")),
                ),
            )
            self.connection.execute(
                "DELETE FROM inventory_items WHERE character_id = ?",
                (character.character_id,),
            )
            for slot, item in enumerate(character.inventory_items[: character.inventory_capacity]):
                self.connection.execute(
                    """INSERT INTO inventory_items(
                        character_id, slot, kind, item_id, name, subtype, icon_type,
                        label, growth_count, stack_value, required_level, stars,
                        quantity, highlighted, description, detail_id, detail_byte_a,
                        detail_byte_b, detail_short, detail_byte_c, value_byte_a,
                        value_byte_b, value_flag, image_data, extra_short, expiry_short
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        character.character_id,
                        slot,
                        item.kind,
                        item.item_id,
                        item.name,
                        item.subtype,
                        item.icon_type,
                        item.label,
                        item.growth_count,
                        item.stack_value,
                        item.required_level,
                        item.stars,
                        item.quantity,
                        int(item.highlighted),
                        item.description,
                        item.detail_id,
                        item.detail_byte_a,
                        item.detail_byte_b,
                        item.detail_short,
                        item.detail_byte_c,
                        item.value_byte_a,
                        item.value_byte_b,
                        int(item.value_flag),
                        sqlite3.Binary(item.image_data),
                        item.extra_short,
                        item.expiry_short,
                    ),
                )

    def save_farm(self, character_id: int, map_state: MapState) -> None:
        plots = [plot.__dict__ for plot in map_state.plots]
        plant_metadata = [plant.__dict__ for plant in map_state.plant_metadata]
        animal_states = [animal.__dict__ for animal in map_state.animal_states]
        ground_items = [
            {
                "object_id": ground.object_id,
                "item": self._item_to_dict(ground.item),
                "x": ground.x,
                "y": ground.y,
            }
            for ground in map_state.ground_items
        ]
        with self.connection:
            self.connection.execute(
                """INSERT INTO farm_states(character_id, farm_id, map_id, map_type, name, auxiliary,
                    plots_json, npc_flags_json, plant_metadata_json, animal_states_json,
                    weather_flags_json, map_tail_flag, ground_items_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(character_id) DO UPDATE SET
                    farm_id=excluded.farm_id, map_id=excluded.map_id, map_type=excluded.map_type,
                    name=excluded.name, auxiliary=excluded.auxiliary,
                    plots_json=excluded.plots_json,
                    npc_flags_json=excluded.npc_flags_json,
                    plant_metadata_json=excluded.plant_metadata_json,
                    animal_states_json=excluded.animal_states_json,
                    weather_flags_json=excluded.weather_flags_json,
                    map_tail_flag=excluded.map_tail_flag,
                    ground_items_json=excluded.ground_items_json,
                    updated_at=CURRENT_TIMESTAMP""",
                (
                    character_id,
                    map_state.farm_id,
                    map_state.map_id,
                    map_state.map_type,
                    map_state.name,
                    map_state.auxiliary,
                    json.dumps(plots, separators=(",", ":")),
                    json.dumps(map_state.npc_flags, separators=(",", ":")),
                    json.dumps(plant_metadata, separators=(",", ":")),
                    json.dumps(animal_states, separators=(",", ":")),
                    json.dumps(list(map_state.weather_flags), separators=(",", ":")),
                    int(map_state.map_tail_flag),
                    json.dumps(ground_items, separators=(",", ":")),
                ),
            )

    def load_farm(self, character_id: int) -> MapState | None:
        row = self.connection.execute(
            "SELECT * FROM farm_states WHERE character_id = ?",
            (character_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            plot_values = json.loads(row["plots_json"])
            plots = [PlotState(**plot) for plot in plot_values]
        except (TypeError, ValueError, json.JSONDecodeError):
            plots = []
        if not plots:
            # Databases created before farm plot persistence used an empty JSON
            # array; the JAR requires an active empty plot object at index 0.
            plots = [PlotState(index=0, state=1, ready=True, entity_type=-1)]
        elif (
            len(plots) == 1
            and plots[0].index == 0
            and plots[0].state == 0
            and plots[0].entity_type < 0
            and not plots[0].entity_name
            and plots[0].timer == 0
        ):
            # Migrate the v0.10 default row only. Do not touch locked plots or
            # any plot carrying crop state.
            plots[0].state = 1
            plots[0].ready = True
        try:
            npc_flags = [tuple(value) for value in json.loads(row["npc_flags_json"])]
        except (TypeError, ValueError, json.JSONDecodeError):
            npc_flags = []
        try:
            plant_metadata = [
                PlantMetadata(**value)
                for value in json.loads(row["plant_metadata_json"] if "plant_metadata_json" in row.keys() else "[]")
                if isinstance(value, dict)
            ]
        except (TypeError, ValueError, json.JSONDecodeError):
            plant_metadata = []
        try:
            animal_states = [
                AnimalState(**value)
                for value in json.loads(row["animal_states_json"] if "animal_states_json" in row.keys() else "[]")
                if isinstance(value, dict)
            ]
        except (TypeError, ValueError, json.JSONDecodeError):
            animal_states = []
        try:
            weather_values = json.loads(row["weather_flags_json"] if "weather_flags_json" in row.keys() else "[false,false,false]")
            weather_flags = tuple(bool(value) for value in weather_values)
            if len(weather_flags) != 3:
                raise ValueError("weather_flags must contain three values")
        except (TypeError, ValueError, json.JSONDecodeError):
            weather_flags = (False, False, False)
        ground_items: list[GroundItem] = []
        try:
            for value in json.loads(row["ground_items_json"] if "ground_items_json" in row.keys() else "[]"):
                if isinstance(value, dict) and isinstance(value.get("item"), dict):
                    ground_items.append(
                        GroundItem(
                            object_id=int(value["object_id"]),
                            item=self._item_from_dict(value["item"]),
                            x=int(value.get("x", 0)),
                            y=int(value.get("y", 0)),
                        )
                    )
        except (TypeError, ValueError, json.JSONDecodeError):
            ground_items = []
        return MapState(
            farm_id=(row["farm_id"] if "farm_id" in row.keys() else None),
            map_id=row["map_id"],
            map_type=row["map_type"],
            name=row["name"],
            auxiliary=row["auxiliary"],
            plots=plots,
            plant_metadata=plant_metadata,
            npc_flags=npc_flags,
            animal_states=animal_states,
            weather_flags=weather_flags,
            map_tail_flag=bool(row["map_tail_flag"] if "map_tail_flag" in row.keys() else 0),
            ground_items=ground_items,
        )

    def save_session_state(self, account: Account, map_state: MapState) -> None:
        if account.character is None:
            return
        self.save_character(account.username, account.character)
        self.save_farm(account.character.character_id, map_state)
