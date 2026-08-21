import io
import unittest

from PIL import Image

from nlcg119_server.codec import PacketReader, PacketWriter
from nlcg119_server.model import AnimalState, CharacterState, GroundItem, InventoryItem, MapObjectMetadata, MapState, NearbyPlayer, PlantMetadata, PlotState, ShopOffer
from nlcg119_server.protocol import (
    Command,
    encode_character_delta_exp,
    encode_currency_update,
    encode_inventory_harvest_reward,
    encode_inventory_snapshot,
    encode_login_bootstrap,
    encode_no_character_bootstrap,
    encode_map_snapshot,
    encode_item_appear_response,
    encode_npc_shop_open,
    encode_shop_open,
    encode_world_handoff,
    parse_login_request,
)


class ProtocolTests(unittest.TestCase):
    def test_shop_open_type_one_matches_jar_case_zero(self):
        item = InventoryItem(
            kind=1,
            item_id=31,
            name="Cà rốt",
            subtype=2,
            icon_type=4,
            label="Hạt giống",
            growth_count=3,
            stack_value=5,
            required_level=7,
            stars=2,
            quantity=9,
        )
        reader = PacketReader(encode_shop_open([ShopOffer(item, auxiliary_value=1234, price=250, currency=0)], tab=1))
        self.assertEqual((reader.read_byte(), reader.read_byte(), reader.read_byte()), (0, 1, 1))
        self.assertEqual(reader.read_byte(), 1)
        self.assertEqual(reader.read_int(), 1234)
        self.assertEqual(reader.read_short(), 31)
        self.assertEqual(reader.read_utf(), "Cà rốt")
        self.assertEqual([reader.read_byte() for _ in range(2)], [2, 4])
        self.assertEqual(reader.read_utf(), "Hạt giống")
        self.assertEqual([reader.read_byte() for _ in range(2)], [3, 5])
        self.assertEqual(reader.read_short(), 7)
        self.assertEqual([reader.read_byte(), reader.read_byte()], [2, 9])
        self.assertEqual(reader.read_int(), 250)
        self.assertEqual(reader.read_byte(), 0)
        self.assertEqual(reader.remaining(), 0)

    def test_shop_open_supports_all_jar_case_zero_item_types(self):
        offers = [
            ShopOffer(InventoryItem(kind=0, item_id=10, detail_id=11, name="Ao", subtype=1, icon_type=2, label="Trang phuc", detail_short=12, growth_count=3), price=100),
            ShopOffer(InventoryItem(kind=1, item_id=20, name="Hat", subtype=1, icon_type=2, label="Hat giong", growth_count=3, stack_value=4, required_level=5, stars=2, quantity=9), price=101),
            ShopOffer(InventoryItem(kind=2, item_id=30, name="Mon", description="Ngon", value_byte_a=1, value_byte_b=2, image_data=b"img2"), price=102),
            ShopOffer(InventoryItem(kind=3, item_id=40, name="Nong", description="Thu hoach", value_byte_a=3, value_byte_b=4), price=103),
            ShopOffer(InventoryItem(kind=4, item_id=50, name="Vat", subtype=5, description="Dung cu", value_byte_a=6, value_byte_b=7, image_data=b"img4", extra_short=8), price=104),
            ShopOffer(InventoryItem(kind=6, item_id=60, name="Ca", description="Ca", value_byte_a=9, value_byte_b=10, image_data=b"img6"), price=105),
        ]
        reader = PacketReader(encode_shop_open(offers))
        self.assertEqual((reader.read_byte(), reader.read_byte(), reader.read_byte()), (0, 0, 6))
        for offer in offers:
            item = offer.item
            self.assertEqual(reader.read_byte(), item.kind)
            self.assertEqual(reader.read_int(), offer.auxiliary_value)
            self.assertEqual(reader.read_short(), item.item_id)
            if item.kind == 0:
                self.assertEqual(reader.read_short(), item.detail_id)
                self.assertEqual(reader.read_utf(), item.name)
                self.assertEqual([reader.read_byte(), reader.read_byte()], [item.subtype, item.icon_type])
                self.assertEqual(reader.read_utf(), item.label)
                self.assertEqual(reader.read_short(), item.detail_short)
                self.assertEqual(reader.read_byte(), item.growth_count)
            elif item.kind == 1:
                self.assertEqual(reader.read_utf(), item.name)
                self.assertEqual([reader.read_byte(), reader.read_byte()], [item.subtype, item.icon_type])
                self.assertEqual(reader.read_utf(), item.label)
                self.assertEqual([reader.read_byte(), reader.read_byte()], [item.growth_count, item.stack_value])
                self.assertEqual(reader.read_short(), item.required_level)
                self.assertEqual([reader.read_byte(), reader.read_byte()], [item.stars, item.quantity])
            elif item.kind in (2, 6):
                self.assertEqual(reader.read_utf(), item.name)
                self.assertEqual(reader.read_utf(), item.description)
                self.assertEqual([reader.read_byte(), reader.read_byte()], [item.value_byte_a, item.value_byte_b])
                image_len = reader.read_short()
                self.assertEqual(reader.read_bytes(image_len), item.image_data)
            elif item.kind == 3:
                self.assertEqual(reader.read_utf(), item.name)
                self.assertEqual(reader.read_utf(), item.description)
                self.assertEqual([reader.read_byte(), reader.read_byte()], [item.value_byte_a, item.value_byte_b])
            elif item.kind == 4:
                self.assertEqual(reader.read_utf(), item.name)
                self.assertEqual(reader.read_byte(), item.subtype)
                self.assertEqual(reader.read_utf(), item.description)
                self.assertEqual([reader.read_byte(), reader.read_byte()], [item.value_byte_a, item.value_byte_b])
                image_len = reader.read_short()
                self.assertEqual(reader.read_bytes(image_len), item.image_data)
                self.assertEqual(reader.read_short(), item.extra_short)
            self.assertEqual((reader.read_int(), reader.read_byte()), (offer.price, offer.currency))
        self.assertEqual(reader.remaining(), 0)

    def test_npc_shop_fallback_image_is_valid_png(self):
        offer = ShopOffer(
            InventoryItem(
                kind=4,
                item_id=1,
                name="Phân bón",
                subtype=0,
                description="Dùng để tăng tốc độ phát triển của cây",
                image_data=b"",
                extra_short=0,
            ),
            price=5,
        )
        reader = PacketReader(encode_npc_shop_open("Cửa hàng hạt giống", [offer]))
        self.assertEqual(reader.read_byte(), 0)
        self.assertEqual(reader.read_utf(), "Cửa hàng hạt giống")
        self.assertEqual(reader.read_byte(), 1)
        self.assertEqual(reader.read_byte(), 4)
        reader.read_short()
        reader.read_utf()
        reader.read_byte()
        reader.read_utf()
        image = reader.read_bytes(reader.read_short())
        with Image.open(io.BytesIO(image)) as decoded:
            decoded.verify()
        self.assertEqual(reader.read_short(), 0)
        self.assertEqual((reader.read_int(), reader.read_byte()), (5, 0))
        self.assertEqual(reader.remaining(), 0)

    def test_parse_login_request(self):
        writer = PacketWriter()
        writer.write_utf("demo")
        writer.write_utf("demo")
        writer.write_utf("1.0")
        writer.write_short(240)
        writer.write_short(320)
        writer.write_byte(1)
        request = parse_login_request(writer.to_bytes())
        self.assertEqual(request.username, "demo")
        self.assertEqual(request.password, "demo")
        self.assertEqual(request.client_version, "1.0")
        self.assertEqual((request.screen_width, request.screen_height, request.mode), (240, 320, 1))

    def test_login_bootstrap_matches_existing_character_parser(self):
        character = CharacterState(character_id=42, name="demo", x=120, y=216)
        payload = encode_login_bootstrap(character)
        reader = PacketReader(payload)
        self.assertEqual(reader.read_int(), 42)
        self.assertEqual(reader.read_utf(), "demo")
        self.assertEqual(reader.read_utf(), "")
        self.assertEqual(reader.read_byte(), 0)  # w: existing-character branch
        self.assertEqual(reader.read_short(), 1)  # C
        self.assertEqual(reader.read_byte(), -1)  # q / APK Char.idRing
        self.assertEqual(reader.read_byte(), 5)   # x / APK Char.vDefault
        self.assertEqual((reader.read_short(), reader.read_short()), (10, 10))
        self.assertEqual(reader.read_int(), 0)    # aj / EXP
        self.assertEqual(reader.read_int(), 10)   # ak / maxEXP
        self.assertEqual(reader.read_int(), 0)    # al[0]
        self.assertEqual(reader.read_int(), 0)    # al[1]
        self.assertEqual(reader.read_byte(), 30)  # aB capacity
        self.assertEqual(reader.read_byte(), 0)   # by3
        self.assertEqual([reader.read_byte() for _ in range(5)], [-1] * 5)
        self.assertEqual([reader.read_byte() for _ in range(4)], [1, 0, 0, -1])
        self.assertEqual([reader.read_byte() for _ in range(4)], [0, 0, 0, 0])
        self.assertFalse(reader.read_boolean())
        self.assertEqual(reader.remaining(), 0)

    def test_login_bootstrap_uses_jar_pu_io_defaults(self):
        character = CharacterState(character_id=7, name="newchar", state_w=1)
        reader = PacketReader(encode_login_bootstrap(character))
        reader.read_int()
        reader.read_utf()
        reader.read_utf()
        self.assertEqual(reader.read_byte(), 1)   # pu.w / Char.gender
        self.assertEqual(reader.read_short(), 1)  # pu.C / Char.lv
        self.assertEqual(reader.read_byte(), -1)  # pu.q / Char.idRing
        self.assertEqual(reader.read_byte(), 5)   # pu.x / Char.vDefault
        self.assertEqual(reader.read_short(), 10) # io.am / suckhoe
        self.assertEqual(reader.read_short(), 10) # io.an / maxSuckhoe
        self.assertEqual(reader.read_int(), 0)    # io.aj / EXP
        self.assertEqual(reader.read_int(), 10)   # io.ak / maxEXP
        self.assertEqual(reader.read_int(), 0)    # io.al[0] / money[0]
        self.assertEqual(reader.read_int(), 0)    # io.al[1] / money[1]
        reader.read_byte()
        reader.read_byte()
        for _ in range(5):
            self.assertEqual(reader.read_byte(), -1)
        self.assertEqual([reader.read_byte() for _ in range(4)], [1, 0, 0, -1])
        self.assertEqual(reader.remaining(), 5)  # four status bytes + companion flag

    def test_login_bootstrap_no_character_branch_has_six_selection_shorts(self):
        character = CharacterState(character_id=42, name="demo")
        values = (1, 2, 3, 4, 5, 6)
        reader = PacketReader(encode_no_character_bootstrap(selection_values=values))
        reader.read_int()
        reader.read_utf()
        reader.read_utf()
        self.assertEqual(reader.read_byte(), -1)
        reader.read_short()
        reader.read_byte()
        reader.read_byte()
        reader.read_short()
        reader.read_short()
        reader.read_int()
        reader.read_int()
        reader.read_int()
        reader.read_int()
        reader.read_byte()
        reader.read_byte()
        for _ in range(5):
            self.assertEqual(reader.read_byte(), -1)
        for _ in range(4):
            reader.read_byte()  # appearance y/z/A/B
        for _ in range(4):
            reader.read_byte()  # status bj[0..3]
        self.assertFalse(reader.read_boolean())
        self.assertEqual(tuple(reader.read_short() for _ in range(6)), values)
        self.assertEqual(reader.remaining(), 0)

    def test_login_bootstrap_pads_short_status(self):
        character = CharacterState(character_id=42, name="demo", status=[7])
        reader = PacketReader(encode_login_bootstrap(character))
        reader.read_int()
        reader.read_utf()
        reader.read_utf()
        reader.read_byte()  # w
        reader.read_short()  # C
        reader.read_byte()  # q
        reader.read_byte()  # x
        reader.read_short()  # am
        reader.read_short()  # an
        for _ in range(4):
            reader.read_int()
        reader.read_byte()  # aB
        reader.read_byte()  # by3
        for _ in range(5):
            reader.read_byte()
        for _ in range(4):
            reader.read_byte()
        self.assertEqual([reader.read_byte() for _ in range(4)], [7, 0, 0, 0])
        self.assertFalse(reader.read_boolean())
        self.assertEqual(reader.remaining(), 0)

    def test_empty_map_snapshot(self):
        payload = encode_map_snapshot(MapState(map_id=7, name="map"))
        reader = PacketReader(payload)
        self.assertEqual(reader.read_int(), 7)
        self.assertEqual(reader.read_utf(), "map")
        self.assertEqual(reader.read_byte(), 0)  # plant metadata count
        self.assertEqual(reader.read_byte(), 1)  # one empty plot, not zero plots
        self.assertEqual(reader.read_byte(), 1)  # active empty plot
        self.assertTrue(reader.read_boolean())  # datkho
        self.assertEqual(reader.read_byte(), -1)  # no crop entity
        self.assertFalse(reader.read_boolean())  # io.bo
        self.assertFalse(reader.read_boolean())  # io.aE
        self.assertFalse(reader.read_boolean())  # io.aF
        self.assertEqual(reader.read_byte(), 0)  # dynamic NPC count
        self.assertFalse(reader.read_boolean())  # rg.a
        self.assertEqual(reader.remaining(), 0)

    def test_world_handoff_nearby_player_matches_jar_so_k(self):
        local = CharacterState(character_id=42, name="local", x=120, y=216)
        remote = CharacterState(
            character_id=77,
            name="remote",
            secondary_name="title",
            level=3,
            kind=2,
            direction=5,
            x=144,
            y=216,
            appearance_y=1,
            appearance_z=2,
            appearance_a=3,
            appearance_b=4,
            state_w=0,
            state_u=8,
            state_q=-1,
        )
        reader = PacketReader(encode_world_handoff(local, MapState(map_id=1, map_type=0), nearby_players=[NearbyPlayer(remote)]))
        self.assertEqual((reader.read_short(), reader.read_short()), (120, 216))
        self.assertEqual(reader.read_byte(), 1)
        self.assertEqual(reader.read_int(), 77)
        self.assertEqual(reader.read_utf(), "remote")
        self.assertEqual(reader.read_utf(), "title")
        self.assertEqual([reader.read_byte(), reader.read_byte()], [0, 0])
        self.assertEqual(reader.read_short(), 3)
        self.assertEqual([reader.read_byte(), reader.read_byte()], [2, 5])
        self.assertEqual((reader.read_short(), reader.read_short()), (144, 216))
        self.assertEqual([reader.read_byte() for _ in range(7)], [1, 2, 3, 4, 0, 8, -1])
        self.assertEqual(reader.read_byte(), 0)
        self.assertFalse(reader.read_boolean())
        self.assertEqual(reader.read_int(), 1)
        self.assertEqual(reader.read_byte(), 0)
        self.assertEqual(reader.read_utf(), "map")
        self.assertEqual(reader.read_byte(), 0)
        self.assertEqual(reader.read_byte(), 0)
        self.assertEqual(reader.remaining(), 0)

    def test_world_handoff_includes_existing_static_vending_object_metadata(self):
        character = CharacterState(character_id=42, name="demo", x=120, y=216)
        payload = encode_world_handoff(
            character,
            MapState(map_id=1, map_type=0, name="map"),
            [MapObjectMetadata(21, "Máy bán hàng tự động", -1, -1, -1, 50, "")],
        )
        reader = PacketReader(payload)
        self.assertEqual((reader.read_short(), reader.read_short()), (120, 216))
        self.assertEqual(reader.read_byte(), 0)
        self.assertEqual(reader.read_int(), 1)
        self.assertEqual(reader.read_byte(), 0)
        self.assertEqual(reader.read_utf(), "map")
        self.assertEqual(reader.read_byte(), 0)
        self.assertEqual(reader.read_byte(), 1)
        self.assertEqual(reader.read_byte(), 21)
        self.assertEqual(reader.read_utf(), "Máy bán hàng tự động")
        self.assertEqual([reader.read_byte() for _ in range(4)], [-1, -1, -1, 50])
        self.assertEqual(reader.read_utf(), "")
        self.assertEqual(reader.remaining(), 0)

    def test_world_handoff(self):
        character = CharacterState(character_id=42, name="demo", x=120, y=216)
        payload = encode_world_handoff(character, MapState(map_id=7, map_type=0, name="map"))
        reader = PacketReader(payload)
        self.assertEqual((reader.read_short(), reader.read_short()), (120, 216))
        self.assertEqual(reader.read_byte(), 0)
        self.assertEqual(reader.read_int(), 7)
        self.assertEqual(reader.read_byte(), 0)
        self.assertEqual(reader.read_utf(), "map")
        self.assertEqual(reader.read_byte(), 0)
        self.assertEqual(reader.read_byte(), 0)
        self.assertEqual(reader.remaining(), 0)

    def test_delta_exp(self):
        reader = PacketReader(encode_character_delta_exp(123))
        self.assertEqual(reader.read_byte(), 2)
        self.assertEqual(reader.read_int(), 123)

    def test_currency_updates(self):
        gold = PacketReader(encode_currency_update(3, 1000))
        self.assertEqual((gold.read_byte(), gold.read_int()), (3, 1000))
        self.assertEqual(gold.remaining(), 0)
        premium = PacketReader(encode_currency_update(4, 100))
        self.assertEqual((premium.read_byte(), premium.read_int()), (4, 100))
        self.assertEqual(premium.remaining(), 0)

    def test_inventory_snapshot_all_supported_record_types(self):
        items = [
            InventoryItem(kind=0, item_id=10, detail_id=11, name="Ao", subtype=2, icon_type=3, label="Mo ta", detail_short=12, growth_count=4, highlighted=True),
            InventoryItem(kind=2, item_id=20, name="Mon an", description="Huong dan", value_byte_a=1, value_byte_b=2, value_flag=True),
            InventoryItem(kind=3, item_id=30, name="Nong san", description="Mo ta NS", value_byte_a=3, value_byte_b=4, value_flag=True),
            InventoryItem(kind=4, item_id=40, name="Vat pham", subtype=5, description="Mo ta VP", value_byte_a=6, value_byte_b=7, value_flag=True, extra_short=8),
            InventoryItem(kind=6, item_id=60, name="Ca", description="Mo ta ca", value_byte_a=9, value_byte_b=10, value_flag=True),
        ]
        reader = PacketReader(encode_inventory_snapshot(items))
        self.assertEqual(reader.read_byte(), 0)

        self.assertEqual((reader.read_byte(), reader.read_byte()), (0, 0))
        self.assertEqual((reader.read_short(), reader.read_short()), (10, 11))
        self.assertEqual(reader.read_utf(), "Ao")
        self.assertEqual((reader.read_byte(), reader.read_byte()), (2, 3))
        self.assertEqual(reader.read_utf(), "Mo ta")
        self.assertEqual((reader.read_short(), reader.read_byte()), (12, 4))
        self.assertTrue(reader.read_boolean())

        self.assertEqual((reader.read_byte(), reader.read_byte()), (1, 2))
        self.assertEqual(reader.read_short(), 20)
        self.assertEqual(reader.read_utf(), "Mon an")
        self.assertEqual(reader.read_utf(), "Huong dan")
        self.assertEqual((reader.read_byte(), reader.read_byte()), (1, 2))
        self.assertTrue(reader.read_boolean())
        image_len = reader.read_short()
        self.assertGreater(image_len, 0)
        reader._read(image_len, "type-2 image")

        self.assertEqual((reader.read_byte(), reader.read_byte()), (2, 3))
        self.assertEqual(reader.read_short(), 30)
        self.assertEqual(reader.read_utf(), "Nong san")
        self.assertEqual(reader.read_utf(), "Mo ta NS")
        self.assertEqual((reader.read_byte(), reader.read_byte()), (3, 4))
        self.assertTrue(reader.read_boolean())

        self.assertEqual((reader.read_byte(), reader.read_byte()), (3, 4))
        self.assertEqual(reader.read_short(), 40)
        self.assertEqual(reader.read_utf(), "Vat pham")
        self.assertEqual(reader.read_byte(), 5)
        self.assertEqual(reader.read_utf(), "Mo ta VP")
        self.assertEqual((reader.read_byte(), reader.read_byte()), (6, 7))
        self.assertTrue(reader.read_boolean())
        image_len = reader.read_short()
        self.assertGreater(image_len, 0)
        reader._read(image_len, "type-4 image")
        self.assertEqual(reader.read_short(), 8)

        self.assertEqual((reader.read_byte(), reader.read_byte()), (4, 6))
        self.assertEqual(reader.read_short(), 60)
        self.assertEqual(reader.read_utf(), "Ca")
        self.assertEqual(reader.read_utf(), "Mo ta ca")
        self.assertEqual((reader.read_byte(), reader.read_byte()), (9, 10))
        self.assertTrue(reader.read_boolean())
        image_len = reader.read_short()
        self.assertGreater(image_len, 0)
        reader._read(image_len, "type-6 image")
        self.assertEqual(reader.remaining(), 0)

    def test_inventory_snapshot_type_one_record(self):
        reader = PacketReader(encode_inventory_snapshot([InventoryItem()]))
        self.assertEqual(reader.read_byte(), 0)
        self.assertEqual(reader.read_byte(), 0)
        self.assertEqual(reader.read_byte(), 1)
        self.assertEqual(reader.read_short(), 0)
        self.assertEqual(reader.read_utf(), "Cà rốt")
        self.assertEqual(reader.read_byte(), 0)
        self.assertEqual(reader.read_byte(), 4)
        self.assertEqual(reader.read_utf(), "Hạt giống")
        self.assertEqual(reader.read_byte(), 1)
        self.assertEqual(reader.read_byte(), 1)
        self.assertEqual(reader.read_short(), 1)
        self.assertEqual(reader.read_byte(), 1)
        self.assertEqual(reader.read_byte(), 1)
        self.assertFalse(reader.read_boolean())
        self.assertEqual(reader.remaining(), 0)

    def test_command_values(self):
        self.assertEqual(Command.HANDSHAKE, -27)
        self.assertEqual(Command.LOGIN, -1)
        self.assertEqual(Command.CHARACTER_DELTA, -11)
        self.assertEqual(Command.INVENTORY_SYNC, -6)

    def test_upgraded_farm_snapshot_preserves_plot_and_npc_state(self):
        farm = MapState(
            map_id=2,
            map_type=1,
            name="farm-upgraded",
            auxiliary=3,
            plots=[
                PlotState(index=0, state=1, ready=True, timer=0, entity_type=7, entity_name="Cà rốt", entity_state=2, entity_flag=1, entity_level=3),
                PlotState(index=1, state=1, ready=False, timer=120, entity_type=-1),
            ],
            npc_flags=[(1, 2, 3, 4, True, 5, 6)],
        )
        reader = PacketReader(encode_map_snapshot(farm))
        self.assertEqual(reader.read_int(), 2)
        self.assertEqual(reader.read_utf(), "farm-upgraded")
        self.assertEqual(reader.read_byte(), 0)  # plant metadata count
        self.assertEqual(reader.read_byte(), 2)  # plot count

        self.assertEqual(reader.read_byte(), 1)  # plot 0 state
        self.assertTrue(reader.read_boolean())
        self.assertEqual(reader.read_byte(), 7)
        self.assertEqual(reader.read_utf(), "Cà rốt")
        self.assertEqual(reader.read_byte(), 2)
        self.assertEqual(reader.read_byte(), 1)
        self.assertFalse(reader.read_boolean())
        self.assertEqual(reader.read_short(), 3)

        self.assertEqual(reader.read_byte(), 1)  # plot 1 state
        self.assertFalse(reader.read_boolean())
        self.assertEqual(reader.read_short(), 120)
        self.assertEqual(reader.read_byte(), -1)

        self.assertFalse(reader.read_boolean())  # io.bo
        self.assertFalse(reader.read_boolean())  # io.aE
        self.assertFalse(reader.read_boolean())  # io.aF
        self.assertEqual(reader.read_byte(), 1)  # dynamic NPC count
        self.assertEqual([reader.read_byte() for _ in range(4)], [1, 2, 3, 4])
        self.assertTrue(reader.read_boolean())
        self.assertEqual((reader.read_byte(), reader.read_byte()), (5, 6))
        self.assertEqual(reader.read_short(), 0)  # timeChet
        self.assertEqual(reader.read_short(), 0)  # timeBenh for bibenh=true
        self.assertEqual(reader.read_short(), -1)  # idThuhoach for tuoi=3
        self.assertFalse(reader.read_boolean())  # rg.a
        self.assertEqual(reader.remaining(), 0)


    def test_item_appearance_and_harvest_reward_wire_contracts(self):
        ground = GroundItem(7001, InventoryItem(kind=3, item_id=77, name="Lua vang", image_data=b"ignored"), x=144, y=216)
        reader = PacketReader(encode_item_appear_response(ground))
        self.assertEqual(reader.read_byte(), 4)
        self.assertEqual(reader.read_int(), 7001)
        self.assertEqual(reader.read_short(), 77)
        self.assertEqual(reader.read_utf(), "Lua vang")
        self.assertEqual((reader.read_byte(), reader.read_byte()), (6, 9))
        image_len = reader.read_short()
        self.assertGreater(image_len, 0)
        reader.read_bytes(image_len)
        self.assertEqual(reader.remaining(), 0)

        reward = InventoryItem(kind=3, item_id=88, name="Lua", description="Nong san")
        reward_reader = PacketReader(encode_inventory_harvest_reward(2, reward, 123, -1, 2))
        self.assertEqual((reward_reader.read_byte(), reward_reader.read_byte()), (4, 2))
        self.assertEqual(reward_reader.read_short(), 88)
        self.assertEqual((reward_reader.read_utf(), reward_reader.read_utf()), ("Lua", "Nong san"))
        self.assertEqual((reward_reader.read_byte(), reward_reader.read_byte()), (0, 0))
        self.assertFalse(reward_reader.read_boolean())
        self.assertEqual((reward_reader.read_int(), reward_reader.read_short(), reward_reader.read_byte()), (123, -1, 2))
        self.assertEqual(reward_reader.remaining(), 0)


    def test_map_snapshot_full_metadata_animal_timers_and_map11_branch(self):
        farm = MapState(
            map_id=0,
            name="farm",
            plant_metadata=[PlantMetadata(7, 10, 20, 30, 1)],
            plots=[PlotState(index=0, state=1, ready=False, timer=90, entity_type=7, entity_name="Cà rốt", entity_state=4, entity_flag=2, fertilized=True, entity_level=30)],
            animal_states=[
                AnimalState(
                    object_id=1,
                    image_id=2,
                    age_state=0,
                    condition=0,
                    sick=True,
                    animal_type=0,
                    index=7,
                    death_timer=60,
                    condition_timer=120,
                    illness_timer=180,
                    growth_timer=240,
                )
            ],
            weather_flags=(True, False, True),
            map_tail_flag=True,
        )
        reader = PacketReader(encode_map_snapshot(farm))
        self.assertEqual((reader.read_int(), reader.read_utf()), (0, "farm"))
        self.assertEqual(reader.read_byte(), 1)
        self.assertEqual((reader.read_short(), reader.read_short(), reader.read_short(), reader.read_short(), reader.read_byte()), (7, 10, 20, 30, 1))
        self.assertEqual(reader.read_byte(), 1)
        self.assertEqual(reader.read_byte(), 1)
        self.assertFalse(reader.read_boolean())
        self.assertEqual(reader.read_short(), 90)
        self.assertEqual(reader.read_byte(), 7)
        self.assertEqual(reader.read_utf(), "Cà rốt")
        self.assertEqual((reader.read_byte(), reader.read_byte()), (4, 2))
        self.assertTrue(reader.read_boolean())
        self.assertEqual(reader.read_short(), 30)
        self.assertEqual([reader.read_boolean() for _ in range(3)], [True, False, True])
        self.assertEqual(reader.read_byte(), 1)
        self.assertEqual([reader.read_byte() for _ in range(4)], [1, 2, 0, 0])
        self.assertTrue(reader.read_boolean())
        self.assertEqual((reader.read_byte(), reader.read_byte()), (0, 7))
        self.assertEqual((reader.read_short(), reader.read_short(), reader.read_short(), reader.read_short()), (60, 120, 180, 240))
        self.assertTrue(reader.read_boolean())
        self.assertEqual(reader.remaining(), 0)

        map11_reader = PacketReader(encode_map_snapshot(MapState(map_id=11, name="love", plots=[PlotState(index=0, state=0)])))
        self.assertEqual((map11_reader.read_int(), map11_reader.read_utf()), (11, "love"))
        self.assertEqual((map11_reader.read_byte(), map11_reader.read_byte(), map11_reader.read_byte()), (0, 1, 0))
        self.assertEqual(map11_reader.remaining(), 0)


    def test_inventory_snapshot_preserves_empty_slot_indices(self):
        empty_seed = InventoryItem(kind=1, item_id=31, quantity=0)
        remaining = InventoryItem(kind=3, item_id=88, name="Lua vang", description="Nong san", quantity=1)
        reader = PacketReader(encode_inventory_snapshot([empty_seed, remaining]))
        self.assertEqual(reader.read_byte(), 0)
        self.assertEqual((reader.read_byte(), reader.read_byte()), (1, 3))
        self.assertEqual(reader.read_short(), 88)
        self.assertEqual(reader.read_utf(), "Lua vang")
        self.assertEqual(reader.read_utf(), "Nong san")
        self.assertEqual((reader.read_byte(), reader.read_byte()), (0, 0))
        self.assertFalse(reader.read_boolean())
        self.assertEqual(reader.remaining(), 0)
