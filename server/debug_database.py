from __future__ import annotations

import tempfile
from pathlib import Path

from nlcg119_server.database import GameDatabase
from nlcg119_server.model import Account, CharacterState, InventoryItem, MapState


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "game.db")
        print("open", path, flush=True)
        db = GameDatabase(path)
        account = db.ensure_account(Account("existing", "pw", character=CharacterState(character_id=42, name="existing", inventory_items=[InventoryItem()])))
        print("ensure", account.username, account.character, flush=True)
        character = CharacterState(character_id=42, name="existing", gold=1000, premium=100, inventory_items=[InventoryItem()])
        print("save character", flush=True)
        db.save_character("existing", character)
        print("saved character", flush=True)
        print("get", db.get_account("existing"), flush=True)
        print("save farm", flush=True)
        db.save_farm(42, MapState())
        print("saved farm", db.load_farm(42), flush=True)
        db.close()
        print("closed", flush=True)


if __name__ == "__main__":
    main()
