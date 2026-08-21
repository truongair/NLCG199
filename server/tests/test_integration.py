import asyncio
import unittest

from nlcg119_server.codec import PacketReader, PacketWriter, XorCursor, build_frame, derive_xor_key, read_frame
from nlcg119_server.handlers import ServerConfig, serve_session
from nlcg119_server.model import Account, CharacterState, GroundItem, InventoryItem, MapState, PlotState
from nlcg119_server.protocol import Command


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def _connect(self, config: ServerConfig):
        server = await asyncio.start_server(
            lambda reader, writer: serve_session(reader, writer, config),
            "127.0.0.1",
            0,
        )
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(build_frame(Command.HANDSHAKE, b""))
        await writer.drain()
        command, handshake = await read_frame(reader)
        self.assertEqual(command, Command.HANDSHAKE)
        self.assertEqual(handshake[0], 3)
        key = derive_xor_key(handshake[1:])
        return server, reader, writer, XorCursor(key), XorCursor(key)

    def _login_payload(self, username: str, password: str) -> bytes:
        login = PacketWriter()
        login.write_utf(username)
        login.write_utf(password)
        login.write_utf("1.0")
        login.write_short(240)
        login.write_short(320)
        login.write_byte(1)
        return login.to_bytes()

    async def _assert_post_world_sync(self, reader, rx, gold: int, premium: int, expected_item_count: int, expected_farm_id: int):
        command, snapshot = await read_frame(reader, rx)
        self.assertEqual(command, Command.FARM_SNAPSHOT)
        self.assertGreater(len(snapshot), 0)
        map_reader = PacketReader(snapshot)
        self.assertEqual(map_reader.read_int(), expected_farm_id)
        self.assertEqual(map_reader.read_utf(), "map")

        command, resize = await read_frame(reader, rx)
        self.assertEqual(command, Command.INVENTORY_SYNC)
        resize_reader = PacketReader(resize)
        self.assertEqual(resize_reader.read_byte(), 3)
        self.assertEqual(resize_reader.read_byte(), expected_item_count)
        self.assertEqual(resize_reader.remaining(), 0)

        command, snapshot_payload = await read_frame(reader, rx)
        self.assertEqual(command, Command.INVENTORY_SYNC)
        snapshot_reader = PacketReader(snapshot_payload)
        self.assertEqual(snapshot_reader.read_byte(), 0)
        if expected_item_count:
            self.assertEqual(snapshot_reader.read_byte(), 0)
            self.assertEqual(snapshot_reader.read_byte(), 1)
            self.assertEqual(snapshot_reader.read_short(), 0)
            self.assertEqual(snapshot_reader.read_utf(), "Cà rốt")
            self.assertEqual(snapshot_reader.read_byte(), 0)
            self.assertEqual(snapshot_reader.read_byte(), 4)
            self.assertEqual(snapshot_reader.read_utf(), "Hạt giống")
            self.assertEqual(snapshot_reader.read_byte(), 1)
            self.assertEqual(snapshot_reader.read_byte(), 1)
            self.assertEqual(snapshot_reader.read_short(), 1)
            self.assertEqual(snapshot_reader.read_byte(), 1)
            self.assertEqual(snapshot_reader.read_byte(), 1)
            self.assertEqual(snapshot_reader.read_boolean(), False)
        self.assertEqual(snapshot_reader.remaining(), 0)

        command, gold_payload = await read_frame(reader, rx)
        self.assertEqual(command, Command.CHARACTER_DELTA)
        gold_reader = PacketReader(gold_payload)
        self.assertEqual(gold_reader.read_byte(), 3)
        self.assertEqual(gold_reader.read_int(), gold)
        self.assertEqual(gold_reader.remaining(), 0)

        command, premium_payload = await read_frame(reader, rx)
        self.assertEqual(command, Command.CHARACTER_DELTA)
        premium_reader = PacketReader(premium_payload)
        self.assertEqual(premium_reader.read_byte(), 4)
        self.assertEqual(premium_reader.read_int(), premium)
        self.assertEqual(premium_reader.remaining(), 0)

    async def test_new_account_stops_at_no_character_then_create(self):
        config = ServerConfig(handshake_raw_key=b"KEY")
        server, reader, writer, tx, rx = await self._connect(config)
        async with server:
            writer.write(build_frame(Command.LOGIN, self._login_payload("newuser", "pw"), tx))
            await writer.drain()
            command, bootstrap = await read_frame(reader, rx)
            self.assertEqual(command, Command.LOGIN)
            bootstrap_reader = PacketReader(bootstrap)
            self.assertEqual(bootstrap_reader.read_int(), 0)
            self.assertEqual(bootstrap_reader.read_utf(), "")
            self.assertEqual(bootstrap_reader.read_utf(), "")
            self.assertEqual(bootstrap_reader.read_byte(), -1)
            bootstrap_reader.read_short()
            bootstrap_reader.read_byte()
            bootstrap_reader.read_byte()
            bootstrap_reader.read_short()
            bootstrap_reader.read_short()
            for _ in range(4):
                bootstrap_reader.read_int()
            bootstrap_reader.read_byte()
            bootstrap_reader.read_byte()
            for _ in range(5):
                self.assertEqual(bootstrap_reader.read_byte(), -1)
            for _ in range(8):
                bootstrap_reader.read_byte()
            self.assertFalse(bootstrap_reader.read_boolean())
            self.assertEqual(tuple(bootstrap_reader.read_short() for _ in range(6)), (0, 0, 0, 0, 0, 0))
            self.assertEqual(bootstrap_reader.remaining(), 0)

            create = PacketWriter()
            create.write_byte(1)
            create.write_byte(15)
            create.write_byte(2)
            writer.write(build_frame(Command.CREATE_CHARACTER, create.to_bytes(), tx))
            await writer.drain()
            command, _ = await read_frame(reader, rx)
            self.assertEqual(command, Command.LOGIN)
            command, handoff = await read_frame(reader, rx)
            self.assertEqual(command, Command.MAP_ACTION)
            handoff_reader = PacketReader(handoff)
            self.assertEqual((handoff_reader.read_short(), handoff_reader.read_short()), (120, 216))
            self.assertEqual(handoff_reader.read_byte(), 0)
            self.assertEqual(handoff_reader.read_int(), 1)
            self.assertEqual(handoff_reader.read_byte(), 0)
            self.assertEqual(handoff_reader.read_utf(), "map")
            self.assertEqual(handoff_reader.read_byte(), 0)
            self.assertEqual(handoff_reader.read_byte(), 1)
            self.assertEqual(handoff_reader.read_byte(), 21)
            self.assertEqual(handoff_reader.read_utf(), "Máy bán hàng tự động")
            self.assertEqual([handoff_reader.read_byte() for _ in range(4)], [-1, -1, -1, 50])
            self.assertEqual(handoff_reader.read_utf(), "")
            self.assertEqual(handoff_reader.remaining(), 0)
            await self._assert_post_world_sync(
                reader,
                rx,
                1000,
                100,
                1,
                config.accounts["newuser"].character.character_id,
            )
            writer.close()
            await writer.wait_closed()

    async def test_existing_character_receives_login_then_world(self):
        character = CharacterState(character_id=42, name="existing", x=120, y=216, gold=1000, premium=100, inventory_items=[InventoryItem()], inventory_count=1)
        config = ServerConfig(
            handshake_raw_key=b"KEY",
            accounts={"existing": Account("existing", "pw", character=character)},
        )
        server, reader, writer, tx, rx = await self._connect(config)
        async with server:
            writer.write(build_frame(Command.LOGIN, self._login_payload("existing", "pw"), tx))
            await writer.drain()
            command, bootstrap = await read_frame(reader, rx)
            self.assertEqual(command, Command.LOGIN)
            self.assertGreater(len(bootstrap), 20)
            command, handoff = await read_frame(reader, rx)
            self.assertEqual(command, Command.MAP_ACTION)
            handoff_reader = PacketReader(handoff)
            self.assertEqual((handoff_reader.read_short(), handoff_reader.read_short()), (120, 216))
            self.assertEqual(handoff_reader.read_byte(), 0)
            self.assertEqual(handoff_reader.read_int(), 1)
            self.assertEqual(handoff_reader.read_byte(), 0)
            self.assertEqual(handoff_reader.read_utf(), "map")
            self.assertEqual(handoff_reader.read_byte(), 0)
            self.assertEqual(handoff_reader.read_byte(), 1)
            self.assertEqual(handoff_reader.read_byte(), 21)
            self.assertEqual(handoff_reader.read_utf(), "Máy bán hàng tự động")
            self.assertEqual([handoff_reader.read_byte() for _ in range(4)], [-1, -1, -1, 50])
            self.assertEqual(handoff_reader.read_utf(), "")
            self.assertEqual(handoff_reader.remaining(), 0)
            await self._assert_post_world_sync(reader, rx, character.gold, character.premium, 1, character.character_id)
            movement = PacketWriter()
            movement.write_short(144)
            writer.write(build_frame(Command.POSITION, movement.to_bytes(), tx))
            await writer.drain()
            await asyncio.sleep(0.01)
            self.assertEqual(character.x, 144)
            writer.close()
            await writer.wait_closed()

    async def test_map_transition_target_zero_uses_owner_int(self):
        character = CharacterState(character_id=42, name="traveler", x=120, y=216, gold=1000, premium=100, inventory_items=[InventoryItem()], inventory_count=1)
        config = ServerConfig(
            handshake_raw_key=b"KEY",
            accounts={"traveler": Account("traveler", "pw", character=character)},
        )
        server, reader, writer, tx, rx = await self._connect(config)
        async with server:
            writer.write(build_frame(Command.LOGIN, self._login_payload("traveler", "pw"), tx))
            await writer.drain()
            for _ in range(7):
                await read_frame(reader, rx)
            transition = PacketWriter()
            transition.write_byte(0)
            transition.write_int(character.character_id)
            writer.write(build_frame(Command.MAP_ACTION, transition.to_bytes(), tx))
            await writer.drain()
            command, handoff = await read_frame(reader, rx)
            self.assertEqual(command, Command.MAP_ACTION)
            handoff_reader = PacketReader(handoff)
            self.assertEqual((handoff_reader.read_short(), handoff_reader.read_short()), (120, 216))
            self.assertEqual(handoff_reader.read_byte(), 0)
            self.assertEqual(handoff_reader.read_int(), 1)
            self.assertEqual(handoff_reader.read_byte(), 0)
            self.assertEqual(handoff_reader.read_utf(), "map")
            self.assertEqual(handoff_reader.read_byte(), 0)
            self.assertEqual(handoff_reader.read_byte(), 1)
            self.assertEqual(handoff_reader.read_byte(), 21)
            self.assertEqual(handoff_reader.read_utf(), "Máy bán hàng tự động")
            self.assertEqual([handoff_reader.read_byte() for _ in range(4)], [-1, -1, -1, 50])
            self.assertEqual(handoff_reader.read_utf(), "")
            self.assertEqual(handoff_reader.remaining(), 0)
            command, snapshot = await read_frame(reader, rx)
            self.assertEqual(command, Command.FARM_SNAPSHOT)
            self.assertGreater(len(snapshot), 0)
            snapshot_reader = PacketReader(snapshot)
            self.assertEqual(snapshot_reader.read_int(), character.character_id)
            self.assertEqual(snapshot_reader.read_utf(), "map")
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(reader.read(1), timeout=0.05)
            writer.close()
            await writer.wait_closed()

    async def test_map_transition_to_map_one_uses_visible_interior_spawn(self):
        character = CharacterState(character_id=43, name="traveler2", x=120, y=216, gold=1000, premium=100, inventory_items=[InventoryItem()], inventory_count=1)
        config = ServerConfig(
            handshake_raw_key=b"KEY",
            accounts={"traveler2": Account("traveler2", "pw", character=character)},
        )
        server, reader, writer, tx, rx = await self._connect(config)
        async with server:
            writer.write(build_frame(Command.LOGIN, self._login_payload("traveler2", "pw"), tx))
            await writer.drain()
            for _ in range(7):
                await read_frame(reader, rx)
            transition = PacketWriter()
            transition.write_byte(1)
            writer.write(build_frame(Command.MAP_ACTION, transition.to_bytes(), tx))
            await writer.drain()
            command, handoff = await read_frame(reader, rx)
            self.assertEqual(command, Command.MAP_ACTION)
            handoff_reader = PacketReader(handoff)
            self.assertEqual((handoff_reader.read_short(), handoff_reader.read_short()), (960, 264))
            self.assertEqual(handoff_reader.read_byte(), 0)
            self.assertEqual(handoff_reader.read_int(), 1)
            self.assertEqual(handoff_reader.read_byte(), 1)
            self.assertEqual(handoff_reader.read_utf(), "map")
            self.assertEqual(handoff_reader.read_byte(), 0)
            self.assertEqual(handoff_reader.read_byte(), 0)
            self.assertEqual(handoff_reader.remaining(), 0)
            command, snapshot = await read_frame(reader, rx)
            self.assertEqual(command, Command.FARM_SNAPSHOT)
            snapshot_reader = PacketReader(snapshot)
            self.assertEqual(snapshot_reader.read_int(), character.character_id)
            self.assertEqual(snapshot_reader.read_utf(), "map")
            self.assertEqual(snapshot_reader.read_byte(), 0)
            self.assertEqual(snapshot_reader.read_byte(), 0)
            self.assertEqual(snapshot_reader.read_boolean(), False)
            self.assertEqual(snapshot_reader.read_boolean(), False)
            self.assertEqual(snapshot_reader.read_boolean(), False)
            self.assertEqual(snapshot_reader.read_byte(), 0)
            self.assertEqual(snapshot_reader.read_boolean(), False)
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(reader.read(1), timeout=0.05)
            writer.close()
            await writer.wait_closed()

    async def test_vending_machine_shop_open_returns_jar_npc_catalog(self):
        character = CharacterState(character_id=47, name="shopper", x=120, y=216)
        config = ServerConfig(
            handshake_raw_key=b"KEY",
            accounts={"shopper": Account("shopper", "pw", character=character)},
        )
        server, reader, writer, tx, rx = await self._connect(config)
        async with server:
            writer.write(build_frame(Command.LOGIN, self._login_payload("shopper", "pw"), tx))
            await writer.drain()
            for _ in range(7):
                await read_frame(reader, rx)

            open_shop = PacketWriter()
            open_shop.write_byte(0)  # JAR ua ID 21 -> sq.a(byte,int): -9 subcase 0
            open_shop.write_byte(21)  # static data/map0 ua object ID
            writer.write(build_frame(Command.NPC_EVENT, open_shop.to_bytes(), tx))
            await writer.drain()

            command, payload = await read_frame(reader, rx)
            self.assertEqual(command, Command.NPC_SHOP)
            shop = PacketReader(payload)
            self.assertEqual(shop.read_byte(), 0)
            self.assertEqual(shop.read_utf(), "Cửa hàng hạt giống")
            self.assertEqual(shop.read_byte(), 2)
            self.assertEqual(shop.read_byte(), 1)
            self.assertEqual(shop.read_short(), 0)
            self.assertEqual(shop.read_utf(), "Cà rốt")
            self.assertEqual([shop.read_byte(), shop.read_byte()], [0, 4])
            self.assertEqual(shop.read_utf(), "Hạt giống")
            self.assertEqual([shop.read_byte(), shop.read_byte()], [1, 1])
            self.assertEqual(shop.read_short(), 1)
            self.assertEqual((shop.read_int(), shop.read_byte()), (10, 0))
            self.assertEqual(shop.read_byte(), 4)
            self.assertEqual(shop.read_short(), 1)
            self.assertEqual(shop.read_utf(), "Phân bón")
            self.assertEqual(shop.read_byte(), 0)
            self.assertEqual(shop.read_utf(), "Dùng để tăng tốc độ phát triển của cây")
            image_length = shop.read_short()
            self.assertGreater(image_length, 0)
            self.assertEqual(len(shop.read_bytes(image_length)), image_length)
            self.assertEqual(shop.read_short(), 0)  # rz.p / extra short
            self.assertEqual((shop.read_int(), shop.read_byte()), (5, 0))
            self.assertEqual(shop.remaining(), 0)
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(reader.read(1), timeout=0.05)
            writer.close()
            await writer.wait_closed()

    async def test_item_and_farm_actions_are_ignored_without_error_response(self):
        character = CharacterState(
            character_id=43,
            name="farmer",
            x=120,
            y=216,
            gold=1000,
            premium=100,
            inventory_items=[InventoryItem()],
            inventory_count=1,
        )
        config = ServerConfig(
            handshake_raw_key=b"KEY",
            accounts={"farmer": Account("farmer", "pw", character=character)},
        )
        server, reader, writer, tx, rx = await self._connect(config)
        async with server:
            writer.write(build_frame(Command.LOGIN, self._login_payload("farmer", "pw"), tx))
            await writer.drain()
            for _ in range(7):
                await read_frame(reader, rx)

            item_action = PacketWriter()
            item_action.write_byte(1)  # Unimplemented item-action subcommand.
            item_action.write_byte(0)
            item_action.write_short(7)
            writer.write(build_frame(Command.ITEM_EVENT, item_action.to_bytes(), tx))

            farm_action = PacketWriter()
            farm_action.write_byte(0)  # Unimplemented farm-action subcommand.
            farm_action.write_byte(1)
            farm_action.write_byte(2)
            writer.write(build_frame(Command.FARM_EVENT, farm_action.to_bytes(), tx))
            await writer.drain()
            await asyncio.sleep(0.05)

            # Unsupported gameplay commands are logged and ignored. They must
            # not produce -3 or any other synthetic response that desynchronizes
            # the JAR client.
            try:
                response = await asyncio.wait_for(reader.read(1), timeout=0.1)
            except asyncio.TimeoutError:
                response = None
            self.assertIsNone(response)
            self.assertFalse(reader.at_eof())
            writer.close()
            await writer.wait_closed()


    async def test_item_action_mutates_inventory_and_emits_client_responses(self):
        item = InventoryItem(kind=1, item_id=10, name="Hat giong", quantity=2)
        renewable = InventoryItem(kind=4, item_id=20, name="Bua", subtype=6, quantity=1)
        character = CharacterState(
            character_id=44,
            name="itemuser",
            x=120,
            y=216,
            gold=1000,
            premium=100,
            inventory_items=[item, renewable],
            inventory_count=2,
        )
        config = ServerConfig(
            handshake_raw_key=b"KEY",
            accounts={"itemuser": Account("itemuser", "pw", character=character)},
            item_renewal_duration_short=240,
        )
        server, reader, writer, tx, rx = await self._connect(config)
        async with server:
            writer.write(build_frame(Command.LOGIN, self._login_payload("itemuser", "pw"), tx))
            await writer.drain()
            for _ in range(7):
                await read_frame(reader, rx)

            use = PacketWriter()
            use.write_byte(0)
            use.write_byte(0)
            writer.write(build_frame(Command.ITEM_EVENT, use.to_bytes(), tx))
            await writer.drain()
            command, payload = await read_frame(reader, rx)
            self.assertEqual(command, Command.S2C_ITEM_ACTION)
            use_reader = PacketReader(payload)
            self.assertEqual((use_reader.read_byte(), use_reader.read_byte()), (0, 0))
            self.assertFalse(use_reader.read_boolean())
            self.assertEqual(use_reader.remaining(), 0)
            for _ in range(2):
                await read_frame(reader, rx)
            self.assertEqual(character.inventory_items[0].quantity, 1)

            move = PacketWriter()
            move.write_byte(3)
            move.write_byte(1)  # pocket -> warehouse
            move.write_byte(0)
            move.write_byte(1)
            writer.write(build_frame(Command.ITEM_EVENT, move.to_bytes(), tx))
            await writer.drain()
            command, payload = await read_frame(reader, rx)
            self.assertEqual(command, Command.S2C_ITEM_ACTION)
            move_reader = PacketReader(payload)
            self.assertEqual([move_reader.read_byte() for _ in range(4)], [3, 1, 1, 0])
            self.assertEqual([move_reader.read_byte(), move_reader.read_byte()], [0, 1])
            self.assertEqual(move_reader.remaining(), 0)
            self.assertEqual(character.inventory_items[0].quantity, 0)
            self.assertEqual(character.inventory_items[1].item_id, 20)
            self.assertEqual(character.storage_items[0].item_id, 10)

            drop = PacketWriter()
            drop.write_byte(1)
            drop.write_byte(0)
            drop.write_byte(1)  # warehouse
            writer.write(build_frame(Command.ITEM_EVENT, drop.to_bytes(), tx))
            await writer.drain()
            command, payload = await read_frame(reader, rx)
            self.assertEqual(command, Command.S2C_ITEM_ACTION)
            drop_reader = PacketReader(payload)
            self.assertEqual([drop_reader.read_byte() for _ in range(3)], [1, 0, 1])
            self.assertEqual(drop_reader.remaining(), 0)
            self.assertEqual(len(character.storage_items), 1)
            self.assertEqual(character.storage_items[0].quantity, 0)

            renew = PacketWriter()
            renew.write_byte(6)
            renew.write_byte(0)
            renew.write_byte(1)
            writer.write(build_frame(Command.ITEM_EVENT, renew.to_bytes(), tx))
            await writer.drain()
            command, payload = await read_frame(reader, rx)
            self.assertEqual(command, Command.S2C_ITEM_ACTION)
            renew_reader = PacketReader(payload)
            self.assertEqual([renew_reader.read_byte() for _ in range(3)], [6, 0, 1])
            self.assertEqual(renew_reader.read_int(), -1)
            self.assertEqual(renew_reader.read_short(), 240)
            self.assertEqual(renew_reader.remaining(), 0)
            self.assertEqual(character.inventory_items[1].expiry_short, 240)
            writer.close()
            await writer.wait_closed()

    async def test_item_pickup_removes_ground_object_and_adds_inventory_item(self):
        ground = GroundItem(
            object_id=7001,
            item=InventoryItem(kind=3, item_id=77, name="Lua vang", quantity=1),
            x=144,
            y=216,
        )
        character = CharacterState(
            character_id=45,
            name="picker",
            x=120,
            y=216,
            inventory_capacity=5,
            inventory_items=[],
            inventory_count=0,
        )
        config = ServerConfig(
            handshake_raw_key=b"KEY",
            accounts={"picker": Account("picker", "pw", character=character)},
            default_map_state=MapState(map_id=1, name="map", ground_items=[ground]),
        )
        server, reader, writer, tx, rx = await self._connect(config)
        async with server:
            writer.write(build_frame(Command.LOGIN, self._login_payload("picker", "pw"), tx))
            await writer.drain()
            for _ in range(3):
                await read_frame(reader, rx)
            command, appearance = await read_frame(reader, rx)
            self.assertEqual(command, Command.S2C_ITEM_ACTION)
            appearance_reader = PacketReader(appearance)
            self.assertEqual(appearance_reader.read_byte(), 4)
            self.assertEqual(appearance_reader.read_int(), 7001)
            self.assertEqual(appearance_reader.read_short(), 77)
            self.assertEqual(appearance_reader.read_utf(), "Lua vang")
            self.assertEqual((appearance_reader.read_byte(), appearance_reader.read_byte()), (6, 9))
            image_len = appearance_reader.read_short()
            appearance_reader.read_bytes(image_len)
            self.assertEqual(appearance_reader.remaining(), 0)
            for _ in range(4):
                await read_frame(reader, rx)

            pickup = PacketWriter()
            pickup.write_byte(4)
            pickup.write_int(7001)
            writer.write(build_frame(Command.ITEM_EVENT, pickup.to_bytes(), tx))
            await writer.drain()
            command, payload = await read_frame(reader, rx)
            self.assertEqual(command, Command.S2C_ITEM_ACTION)
            remove_reader = PacketReader(payload)
            self.assertEqual(remove_reader.read_byte(), 5)
            self.assertEqual(remove_reader.read_int(), 7001)
            self.assertEqual(remove_reader.remaining(), 0)
            for _ in range(2):
                await read_frame(reader, rx)
            self.assertEqual([(item.kind, item.item_id) for item in character.inventory_items], [(3, 77)])
            writer.write(build_frame(Command.ITEM_EVENT, pickup.to_bytes(), tx))
            await writer.drain()
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(reader.read(1), timeout=0.05)
            writer.close()
            await writer.wait_closed()

    async def test_farm_actions_mutate_crop_soil_health_exp_and_inventory(self):
        seed = InventoryItem(kind=1, item_id=31, name="Cà rốt", stars=2, quantity=1)
        fertilizer = InventoryItem(kind=4, item_id=90, name="Phân bón", subtype=4, quantity=1)
        character = CharacterState(
            character_id=46,
            name="farmer2",
            x=120,
            y=216,
            health=10,
            exp=0,
            inventory_capacity=8,
            inventory_items=[seed, fertilizer],
            inventory_count=2,
        )
        farm = MapState(
            map_id=1,
            name="map",
            plots=[
                PlotState(index=0, state=1, ready=True),
                PlotState(index=1, state=1, ready=False, entity_type=32, entity_name="Lúa", entity_state=4, entity_flag=1),
                PlotState(index=2, state=1, ready=True, entity_type=33, entity_name="Cây hỏng", entity_state=1, entity_flag=1),
            ],
        )
        config = ServerConfig(
            handshake_raw_key=b"KEY",
            accounts={"farmer2": Account("farmer2", "pw", character=character)},
            default_map_state=farm,
            harvest_exp=5,
        )
        server, reader, writer, tx, rx = await self._connect(config)
        async with server:
            writer.write(build_frame(Command.LOGIN, self._login_payload("farmer2", "pw"), tx))
            await writer.drain()
            for _ in range(7):
                await read_frame(reader, rx)

            sow = PacketWriter()
            sow.write_byte(0)
            sow.write_byte(2)
            sow.write_byte(0)
            writer.write(build_frame(Command.FARM_EVENT, sow.to_bytes(), tx))
            await writer.drain()
            command, payload = await read_frame(reader, rx)
            self.assertEqual(command, Command.S2C_FARM_ACTION)
            sow_reader = PacketReader(payload)
            self.assertEqual(sow_reader.read_byte(), 2)
            self.assertEqual(sow_reader.read_int(), 0)  # absent actor sentinel
            self.assertEqual(sow_reader.read_byte(), 0)
            self.assertEqual(sow_reader.read_short(), 31)
            self.assertEqual(sow_reader.read_utf(), "Cà rốt")
            self.assertEqual(sow_reader.read_byte(), 2)
            self.assertEqual(sow_reader.remaining(), 0)
            # The Android/JAR client decrements the seed locally before -4/2;
            # no trailing -6 inventory sync is expected.
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(reader.read(1), timeout=0.05)
            self.assertEqual(seed.quantity, 0)
            self.assertEqual(character.inventory_items[1].item_id, 90)

            fertilize = PacketWriter()
            fertilize.write_byte(0)
            fertilize.write_byte(3)
            fertilize.write_byte(1)
            writer.write(build_frame(Command.FARM_EVENT, fertilize.to_bytes(), tx))
            await writer.drain()
            command, payload = await read_frame(reader, rx)
            self.assertEqual(command, Command.S2C_FARM_ACTION)
            update_reader = PacketReader(payload)
            self.assertEqual([update_reader.read_byte() for _ in range(3)], [3, 0, 2])
            self.assertEqual(update_reader.read_short(), 0)
            self.assertEqual(update_reader.read_int(), 0)
            self.assertEqual(update_reader.read_int(), 0)
            self.assertEqual(update_reader.read_byte(), 0)
            self.assertEqual(update_reader.remaining(), 0)
            command, payload = await read_frame(reader, rx)
            self.assertEqual(command, Command.S2C_PLAYER_STATE)
            health_reader = PacketReader(payload)
            health_kind = health_reader.read_byte()
            health_value = health_reader.read_short()
            health_timer = health_reader.read_byte()
            self.assertEqual((health_kind, health_value), (0, 9))
            self.assertEqual(health_timer, 0)
            self.assertEqual(fertilizer.quantity, 0)

            water = PacketWriter()
            water.write_byte(0)
            water.write_byte(1)
            writer.write(build_frame(Command.FARM_EVENT, water.to_bytes(), tx))
            await writer.drain()
            command, payload = await read_frame(reader, rx)
            self.assertEqual(command, Command.S2C_FARM_ACTION)
            water_reader = PacketReader(payload)
            self.assertEqual(water_reader.read_byte(), 1)
            self.assertEqual(water_reader.read_int(), 0)
            self.assertEqual(water_reader.read_byte(), 0)
            command, payload = await read_frame(reader, rx)
            self.assertEqual(command, Command.S2C_PLAYER_STATE)
            health_after_water = PacketReader(payload)
            self.assertEqual((health_after_water.read_byte(), health_after_water.read_short()), (0, 8))
            self.assertEqual(health_after_water.read_byte(), 0)

            harvest = PacketWriter()
            harvest.write_byte(1)
            harvest.write_byte(4)
            writer.write(build_frame(Command.FARM_EVENT, harvest.to_bytes(), tx))
            await writer.drain()
            command, payload = await read_frame(reader, rx)
            self.assertEqual(command, Command.S2C_FARM_ACTION)
            harvest_reader = PacketReader(payload)
            self.assertEqual(harvest_reader.read_byte(), 4)
            self.assertEqual(harvest_reader.read_int(), 0)
            self.assertEqual(harvest_reader.read_byte(), 1)
            self.assertEqual(harvest_reader.read_short(), -1)
            self.assertEqual(harvest_reader.read_byte(), 1)
            command, payload = await read_frame(reader, rx)
            self.assertEqual(command, Command.S2C_MAIN_BAG)
            reward_reader = PacketReader(payload)
            self.assertEqual(reward_reader.read_byte(), 4)
            self.assertEqual(reward_reader.read_byte(), 0)
            self.assertEqual(reward_reader.read_short(), 32)
            self.assertEqual(reward_reader.read_utf(), "Lúa")
            self.assertEqual(reward_reader.read_utf(), "")
            self.assertEqual((reward_reader.read_byte(), reward_reader.read_byte()), (0, 0))
            self.assertFalse(reward_reader.read_boolean())
            self.assertEqual(reward_reader.read_int(), 5)
            self.assertEqual(reward_reader.read_short(), -1)
            self.assertEqual(reward_reader.read_byte(), 1)
            self.assertEqual(reward_reader.remaining(), 0)
            self.assertEqual(character.exp, 5)
            self.assertEqual([(item.kind, item.item_id, item.quantity) for item in character.inventory_items], [(3, 32, 1), (4, 90, 0)])

            destroy = PacketWriter()
            destroy.write_byte(2)
            destroy.write_byte(5)
            writer.write(build_frame(Command.FARM_EVENT, destroy.to_bytes(), tx))
            await writer.drain()
            command, payload = await read_frame(reader, rx)
            self.assertEqual(command, Command.S2C_FARM_ACTION)
            destroy_reader = PacketReader(payload)
            self.assertEqual(destroy_reader.read_byte(), 5)
            self.assertEqual(destroy_reader.read_int(), 0)
            self.assertEqual(destroy_reader.read_byte(), 2)
            command, payload = await read_frame(reader, rx)
            self.assertEqual(command, Command.S2C_PLAYER_STATE)
            destroy_health = PacketReader(payload)
            self.assertEqual((destroy_health.read_byte(), destroy_health.read_short()), (0, 7))
            self.assertEqual(destroy_health.read_byte(), 0)
            self.assertEqual(character.health, 7)
            writer.close()
            await writer.wait_closed()
