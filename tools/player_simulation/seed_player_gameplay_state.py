#!/usr/bin/env python3
import json
import sqlite3
import hashlib

DB = "/tmp/nlcg199-player.sqlite"
username = "smokeuser"
character_id = 1000 + int.from_bytes(hashlib.sha256(username.encode("utf-8")).digest()[:2], "big")

inventory = [
    {
        "slot": 0,
        "kind": 1,
        "item_id": 31,
        "name": "Cà rốt",
        "subtype": 0,
        "icon_type": 0,
        "label": "",
        "growth_count": 0,
        "stack_value": 0,
        "required_level": 0,
        "stars": 2,
        "quantity": 1,
        "highlighted": 0,
        "description": "",
        "detail_id": 0,
        "detail_byte_a": 0,
        "detail_byte_b": 0,
        "detail_short": 0,
        "detail_byte_c": 0,
        "value_byte_a": 0,
        "value_byte_b": 0,
        "value_flag": 0,
        "image_data": b"",
        "extra_short": 0,
        "expiry_short": 0,
    },
    {
        "slot": 1,
        "kind": 4,
        "item_id": 90,
        "name": "Phân bón",
        "subtype": 4,
        "icon_type": 0,
        "label": "",
        "growth_count": 0,
        "stack_value": 0,
        "required_level": 0,
        "stars": 0,
        "quantity": 1,
        "highlighted": 0,
        "description": "",
        "detail_id": 0,
        "detail_byte_a": 0,
        "detail_byte_b": 0,
        "detail_short": 0,
        "detail_byte_c": 0,
        "value_byte_a": 0,
        "value_byte_b": 0,
        "value_flag": 0,
        "image_data": b"",
        "extra_short": 0,
        "expiry_short": 0,
    },
]
plots = [
    {"index": 0, "state": 1, "ready": True, "timer": 0, "entity_type": -1, "entity_name": "", "entity_state": 0, "entity_flag": 0},
    {"index": 1, "state": 1, "ready": False, "timer": 0, "entity_type": 32, "entity_name": "Lúa", "entity_state": 4, "entity_flag": 1},
    {"index": 2, "state": 1, "ready": True, "timer": 0, "entity_type": 33, "entity_name": "Cây hỏng", "entity_state": 1, "entity_flag": 1},
]

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM inventory_items WHERE character_id = ?", (character_id,))
    columns = [
        "character_id", "slot", "kind", "item_id", "name", "subtype", "icon_type", "label",
        "growth_count", "stack_value", "required_level", "stars", "quantity", "highlighted",
        "description", "detail_id", "detail_byte_a", "detail_byte_b", "detail_short", "detail_byte_c",
        "value_byte_a", "value_byte_b", "value_flag", "image_data", "extra_short", "expiry_short",
    ]
    placeholders = ",".join("?" for _ in columns)
    for item in inventory:
        conn.execute(
            f"INSERT INTO inventory_items ({','.join(columns)}) VALUES ({placeholders})",
            tuple([character_id] + [item[column] for column in columns[1:]]),
        )
    conn.execute(
        "UPDATE characters SET inventory_count = 2, inventory_capacity = 8, health = 10, exp = 0, gold = 1000, premium = 100 WHERE character_id = ?",
        (character_id,),
    )
    conn.execute(
        "UPDATE farm_states SET map_id = 1, map_type = 0, farm_id = ?, name = 'map', plots_json = ?, npc_flags_json = '[]', plant_metadata_json = '[]', animal_states_json = '[]', weather_flags_json = '[false,false,false]', map_tail_flag = 0, ground_items_json = '[]' WHERE character_id = ?",
        (character_id, json.dumps(plots, ensure_ascii=False), character_id),
    )
    conn.commit()
print(f"seeded character_id={character_id} inventory=2 plots=3")
