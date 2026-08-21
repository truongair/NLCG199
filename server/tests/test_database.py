from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from nlcg119_server.database import GameDatabase
from nlcg119_server.model import Account, CharacterState, GroundItem, InventoryItem, MapState, PlotState


class DatabaseTransactionTests(unittest.TestCase):
    def _character(self) -> CharacterState:
        return CharacterState(
            character_id=42,
            name="farmer",
            gold=1000,
            premium=75,
            inventory_capacity=6,
            inventory_items=[],
            inventory_count=0,
        )

    def _account_with_character(self) -> Account:
        return Account("farmer", "pw", character=self._character())

    def _starter_item(self, quantity: int = 3) -> InventoryItem:
        return InventoryItem(
            kind=1,
            item_id=7,
            name="Cà rốt",
            subtype=0,
            icon_type=4,
            label="Hạt giống",
            growth_count=2,
            stack_value=5,
            required_level=1,
            stars=2,
            quantity=quantity,
            highlighted=True,
        )

    def _purchased_item(self) -> InventoryItem:
        return InventoryItem(
            kind=4,
            item_id=91,
            name="Bình tưới",
            subtype=3,
            description="Tăng tốc độ chăm sóc",
            value_byte_a=4,
            value_byte_b=8,
            value_flag=True,
            image_data=b"custom-item-image",
            extra_short=12,
        )

    def test_legacy_empty_farm_plot_is_migrated_to_active_empty_plot(self) -> None:
        db = GameDatabase(":memory:")
        try:
            db.ensure_account(self._account_with_character())
            db.connection.execute(
                "INSERT INTO farm_states(character_id, plots_json) VALUES (?, ?)",
                (42, '[{"index":0,"state":0,"ready":false,"timer":0,"entity_type":-1,"entity_name":"","entity_state":0,"entity_flag":0,"entity_level":0,"fertilized":false}]'),
            )
            db.connection.commit()
            farm = db.load_farm(42)
            self.assertIsNotNone(farm)
            self.assertEqual(len(farm.plots), 1)
            self.assertEqual((farm.plots[0].state, farm.plots[0].ready, farm.plots[0].entity_type), (1, True, -1))
        finally:
            db.close()

    def test_item_purchase_and_sale_replace_inventory_snapshot_and_currency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = GameDatabase(str(Path(tmp) / "game.db"))
            account = self._account_with_character()
            db.ensure_account(account)

            purchased = self._purchased_item()
            account.character.inventory_items = [self._starter_item(), purchased]
            account.character.inventory_count = 2
            account.character.gold = 850
            db.save_session_state(account, MapState())

            after_purchase = db.get_account("farmer")
            self.assertIsNotNone(after_purchase)
            self.assertIsNotNone(after_purchase.character)
            self.assertEqual(after_purchase.character.gold, 850)
            self.assertEqual([item.item_id for item in after_purchase.character.inventory_items], [7, 91])
            self.assertEqual(after_purchase.character.inventory_items[1].image_data, b"custom-item-image")
            self.assertEqual(after_purchase.character.inventory_items[1].extra_short, 12)

            # Selling the purchased item removes its slot and credits gold.
            after_purchase.character.inventory_items = after_purchase.character.inventory_items[:1]
            after_purchase.character.inventory_count = 1
            after_purchase.character.gold = 1000
            db.save_session_state(after_purchase, MapState())

            after_sale = db.get_account("farmer")
            self.assertIsNotNone(after_sale)
            self.assertIsNotNone(after_sale.character)
            self.assertEqual(after_sale.character.gold, 1000)
            self.assertEqual(after_sale.character.inventory_count, 1)
            self.assertEqual([item.item_id for item in after_sale.character.inventory_items], [7])
            db.close()

    def test_item_quantity_update_persists_without_losing_type_specific_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = GameDatabase(str(Path(tmp) / "game.db"))
            account = self._account_with_character()
            account.character.inventory_items = [self._starter_item(quantity=9)]
            account.character.inventory_count = 1
            db.ensure_account(account)
            db.save_character(account.username, account.character)

            account.character.inventory_items[0].quantity = 4
            account.character.inventory_items[0].growth_count = 5
            account.character.inventory_items[0].highlighted = False
            db.save_character(account.username, account.character)

            loaded = db.get_account("farmer")
            self.assertIsNotNone(loaded)
            item = loaded.character.inventory_items[0]
            self.assertEqual(item.quantity, 4)
            self.assertEqual(item.growth_count, 5)
            self.assertEqual(item.stack_value, 5)
            self.assertEqual(item.required_level, 1)
            self.assertFalse(item.highlighted)
            db.close()

    def test_inventory_snapshot_removes_stale_slot_after_sale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = GameDatabase(str(Path(tmp) / "game.db"))
            account = self._account_with_character()
            account.character.inventory_items = [self._starter_item(), self._purchased_item()]
            account.character.inventory_count = 2
            db.ensure_account(account)
            db.save_character(account.username, account.character)

            account.character.inventory_items = [self._starter_item(quantity=1)]
            account.character.inventory_count = 1
            db.save_character(account.username, account.character)

            rows = db.connection.execute(
                "SELECT slot, item_id FROM inventory_items WHERE character_id = ? ORDER BY slot",
                (42,),
            ).fetchall()
            self.assertEqual([(row["slot"], row["item_id"]) for row in rows], [(0, 7)])
            db.close()

    def test_item_and_farm_transaction_survives_database_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "game.db")
            account = self._account_with_character()
            account.character.inventory_items = [self._starter_item(quantity=2), self._purchased_item()]
            account.character.inventory_count = 2
            account.character.gold = 640
            upgraded_farm = MapState(
                map_id=2,
                map_type=1,
                name="farm-upgraded",
                auxiliary=3,
                plots=[
                    PlotState(index=0, state=1, ready=True, timer=0, entity_type=7, entity_name="Cà rốt", entity_state=2, entity_flag=1, entity_level=3),
                    PlotState(index=1, state=2, ready=False, timer=120, entity_type=-1),
                ],
                npc_flags=[(1, 2, 3, 4, True, 5, 6)],
            )

            first = GameDatabase(path)
            first.ensure_account(account)
            first.save_session_state(account, upgraded_farm)
            first.close()

            second = GameDatabase(path)
            restored = second.get_account("farmer")
            restored_farm = second.load_farm(42)
            self.assertIsNotNone(restored)
            self.assertIsNotNone(restored.character)
            self.assertEqual(restored.character.gold, 640)
            self.assertEqual([item.item_id for item in restored.character.inventory_items], [7, 91])
            self.assertEqual(restored.character.inventory_items[0].quantity, 2)
            self.assertEqual(restored.character.inventory_items[1].image_data, b"custom-item-image")
            self.assertIsNotNone(restored_farm)
            self.assertEqual(restored_farm.map_id, 2)
            self.assertEqual(restored_farm.map_type, 1)
            self.assertEqual(restored_farm.name, "farm-upgraded")
            self.assertEqual(restored_farm.auxiliary, 3)
            self.assertEqual(restored_farm.plots[0].entity_name, "Cà rốt")
            self.assertTrue(restored_farm.plots[0].ready)
            self.assertEqual(restored_farm.plots[1].timer, 120)
            self.assertEqual(restored_farm.npc_flags, [(1, 2, 3, 4, True, 5, 6)])
            second.close()


    def test_item_containers_expiry_and_ground_items_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "containers.db")
            account = self._account_with_character()
            pocket = self._starter_item(quantity=2)
            pocket.expiry_short = 120
            warehouse = self._purchased_item()
            equipped = InventoryItem(kind=0, item_id=55, name="Ao choang", subtype=3, quantity=1)
            account.character.inventory_items = [pocket]
            account.character.storage_items = [warehouse]
            account.character.equipment = {3: equipped}
            farm = MapState(
                plots=[PlotState(index=0, state=1, ready=False, entity_type=7, entity_name="Cà rốt", fertilized=True)],
                ground_items=[GroundItem(9001, InventoryItem(kind=3, item_id=88, name="Lua vang", quantity=2), x=144, y=216)],
            )
            first = GameDatabase(path)
            first.ensure_account(account)
            first.save_session_state(account, farm)
            first.close()

            second = GameDatabase(path)
            restored = second.get_account("farmer")
            restored_farm = second.load_farm(42)
            self.assertIsNotNone(restored)
            self.assertIsNotNone(restored.character)
            self.assertEqual(restored.character.inventory_items[0].expiry_short, 120)
            self.assertEqual(restored.character.storage_items[0].item_id, 91)
            self.assertEqual(restored.character.equipment[3].item_id, 55)
            self.assertIsNotNone(restored_farm)
            self.assertEqual([(item.object_id, item.item.item_id, item.item.quantity) for item in restored_farm.ground_items], [(9001, 88, 2)])
            self.assertTrue(restored_farm.plots[0].fertilized)
            second.close()


if __name__ == "__main__":
    unittest.main()
