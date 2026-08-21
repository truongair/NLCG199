"""Connection lifecycle and command handlers for the initial server slice."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from copy import copy, deepcopy
from dataclasses import dataclass, field

from .database import GameDatabase
from .codec import (
    PacketReader,
    ProtocolError,
    XorCursor,
    build_frame,
    derive_xor_key,
    read_frame,
)
from .model import Account, CharacterState, InventoryItem, MapObjectMetadata, MapState, NearbyPlayer, Session, SessionState, ShopOffer

from .protocol import (
    Command,
    encode_character_delta_exp,
    encode_currency_update,
    encode_farm_actor_update,
    encode_farm_harvest_update,
    encode_farm_plot_update,
    encode_error,
    encode_health_update,
    encode_inventory_harvest_reward,
    encode_inventory_resize,
    encode_inventory_snapshot,
    encode_item_appear_response,
    encode_item_drop_response,
    encode_item_expiry_response,
    encode_item_ground_remove_response,
    encode_item_move_response,
    encode_item_unequip_response,
    encode_item_use_response,
    encode_login_bootstrap,
    encode_no_character_bootstrap,
    encode_map_snapshot,
    encode_npc_shop_open,
    encode_position,
    encode_shop_open,
    encode_world_handoff,
    parse_login_request,
)

log = logging.getLogger(__name__)


@dataclass
class ServerConfig:
    handshake_raw_key: bytes = b"NLCG119K"
    allow_dev_accounts: bool = True
    accounts: dict[str, Account] = field(default_factory=dict)
    default_map_id: int = 1
    default_map_name: str = "map"
    starter_gold: int = 1000
    starter_premium: int = 100
    starter_inventory_capacity: int = 30
    starter_inventory: list[InventoryItem] = field(default_factory=lambda: [InventoryItem()])
    item_renewal_duration_short: int = 1440
    harvest_exp: int = 1
    default_map_state: MapState | None = None
    # Safe interior spawn points, kept away from map borders and fi.h trigger
    # rectangles. They are used only after an explicit map transition; login
    # preserves the persisted character coordinates.
    map_spawns: dict[int, tuple[int, int]] = field(
        default_factory=lambda: {
            0: (120, 216),
            1: (960, 264),
            2: (432, 552),
            3: (480, 264),
            4: (240, 384),
            5: (120, 216),
            6: (216, 192),
            7: (360, 240),
            8: (360, 384),
            9: (216, 192),
            10: (960, 168),
            11: (324, 216),
            12: (168, 192),
            13: (120, 168),
            14: (360, 264),
            15: (552, 192),
            100: (360, 240),
        }
    )
    vending_object_id: int = 21
    # map0/data contains an existing ua object ID 21 at the vending-machine
    # location. d=true is what makes it selectable; -1 sprite fields preserve
    # the map's own static machine art and do not create a fake NPC/entity.
    static_map_objects: list[MapObjectMetadata] = field(
        default_factory=lambda: [
            MapObjectMetadata(
                object_id=21,
                name="Máy bán hàng tự động",
                sprite_a=-1,
                sprite_b=-1,
                sprite_c=-1,
                collision_size=50,
            )
        ]
    )
    # Optional metadata for other map resources. The default intentionally
    # contains only the verified map0 record; unknown map object semantics are
    # not fabricated.
    static_map_objects_by_map: dict[int, list[MapObjectMetadata]] = field(default_factory=dict)
    vending_shop_tab: int = 0
    vending_shop: list[ShopOffer] = field(
        default_factory=lambda: [
            ShopOffer(
                InventoryItem(
                    kind=1,
                    item_id=0,
                    name="Cà rốt",
                    subtype=0,
                    icon_type=4,
                    label="Hạt giống",
                    growth_count=1,
                    stack_value=1,
                    required_level=1,
                    stars=1,
                    quantity=1,
                ),
                auxiliary_value=0,
                price=10,
                currency=0,
            ),
            ShopOffer(
                InventoryItem(
                    kind=4,
                    item_id=1,
                    name="Phân bón",
                    subtype=0,
                    description="Dùng để tăng tốc độ phát triển của cây",
                    image_data=b"",
                    extra_short=0,
                ),
                auxiliary_value=0,
                price=5,
                currency=0,
            ),
        ]
    )
    # Only live sessions are used for K records; no offline or synthetic
    # character is injected merely to bypass the JAR movement gate.
    active_sessions: list[Session] = field(default_factory=list, init=False, repr=False)
    # ``None`` keeps unit tests isolated in-memory; the CLI supplies a file path.
    database_path: str | None = None

    def map_objects_for_type(self, map_type: int) -> list[MapObjectMetadata]:
        if map_type == 0:
            return list(self.static_map_objects)
        return list(self.static_map_objects_by_map.get(map_type, []))

    def spawn_for_map(self, map_type: int) -> tuple[int, int]:
        return self.map_spawns.get(map_type, (120, 216))

    def __post_init__(self) -> None:
        if not self.accounts and self.allow_dev_accounts:
            self.accounts["demo"] = Account("demo", "demo")


class CommandDispatcher:
    def __init__(self, config: ServerConfig):
        self.config = config
        self.database = GameDatabase(config.database_path or ":memory:")
        # Configuration accounts seed a fresh database but never overwrite
        # characters already persisted on disk.
        configured_accounts = dict(config.accounts)
        for account in configured_accounts.values():
            self.database.ensure_account(account)
        persisted_accounts = {account.username: account for account in self.database.all_accounts()}
        # Keep explicitly supplied Account/Character objects live (tests and
        # embedding applications may hold references to them), while loading
        # accounts that exist only in the persistent database.
        merged_accounts = {
            username: configured_accounts.get(username, persisted)
            for username, persisted in persisted_accounts.items()
        }
        config.accounts.clear()
        config.accounts.update(merged_accounts)
        self._next_character_id = 1000

    async def send_packet(self, session: Session, command: int, payload: bytes = b"") -> None:
        cursor = session.tx_cursor if session.state != SessionState.CONNECTED else None
        session.writer.write(build_frame(command, payload, cursor))
        await session.writer.drain()
        log.debug("send peer=%s command=%s payload=%d", session.peer, command, len(payload))

    async def send_handshake(self, session: Session) -> None:
        raw_key = self.config.handshake_raw_key
        if not raw_key or len(raw_key) > 127:
            raise ProtocolError("handshake raw key must contain 1..127 bytes")
        payload = bytes((len(raw_key),)) + raw_key
        session.writer.write(build_frame(Command.S2C_HANDSHAKE, payload))
        await session.writer.drain()
        derived = derive_xor_key(raw_key)
        session.xor_key = derived
        session.rx_cursor = XorCursor(derived)
        session.tx_cursor = XorCursor(derived)
        session.handshake_received = True
        session.state = SessionState.HANDSHAKE_DONE
        log.debug("handshake complete peer=%s key_length=%d", session.peer, len(raw_key))

    def _character_for_username(
        self,
        username: str,
        *,
        state_w: int = 0,
        birth_day: int = 1,
        birth_season: int = 0,
    ) -> CharacterState:
        digest = hashlib.sha256(username.encode("utf-8")).digest()
        character_id = 1000 + int.from_bytes(digest[:2], "big")
        return CharacterState(
            character_id=character_id,
            name=username[:15],
            x=120,
            # data/map0 plane w==0 at y=216; y=192 is a collision tile.
            y=216,
            level=1,
            exp=0,
            gold=self.config.starter_gold,
            premium=self.config.starter_premium,
            inventory_capacity=self.config.starter_inventory_capacity,
            inventory_items=list(self.config.starter_inventory),
            inventory_count=len(self.config.starter_inventory),
            state_w=state_w,
            birth_day=birth_day,
            birth_season=birth_season,
        )

    async def handle_login(self, session: Session, payload: bytes) -> None:
        try:
            request = parse_login_request(payload)
        except (ValueError, ProtocolError) as exc:
            await self.send_packet(session, Command.S2C_TEXT_DIALOG, encode_error("Login packet không hợp lệ"))
            log.info("invalid login packet peer=%s error=%s", session.peer, exc)
            return
        if not request.username or not request.password:
            await self.send_packet(session, Command.S2C_TEXT_DIALOG, encode_error("Xin điền đầy đủ thông tin!"))
            return
        account = self.config.accounts.get(request.username)
        if account is None:
            account = self.database.get_account(request.username)
        if account is None:
            if not self.config.allow_dev_accounts:
                await self.send_packet(session, Command.S2C_TEXT_DIALOG, encode_error("Tài khoản không tồn tại"))
                return
            account = self.database.create_account(Account(request.username, request.password))
            self.config.accounts[request.username] = account
        if account.password != request.password:
            await self.send_packet(session, Command.S2C_TEXT_DIALOG, encode_error("Mật khẩu không chính xác"))
            return
        session.account = account
        session.character = account.character
        if session.character is not None:
            persisted_farm = self.database.load_farm(session.character.character_id)
            if persisted_farm is not None:
                session.map_state = persisted_farm
            elif self.config.default_map_state is not None:
                session.map_state = deepcopy(self.config.default_map_state)
        session.state = SessionState.AUTHENTICATED
        if session.character is None:
            # so.java case -1 with w=-1 opens m.e() and consumes six selection
            # shorts. Do not push -8/-2 before the client submits -5.
            await self.send_packet(session, Command.S2C_LOGIN_BOOTSTRAP, encode_no_character_bootstrap())
            log.debug("login peer=%s account=%s has no character; creation UI opened", session.peer, request.username)
            return
        await self.send_packet(session, Command.S2C_LOGIN_BOOTSTRAP, encode_login_bootstrap(session.character))
        await self.send_map_bootstrap(session, initial=True)

    async def send_map_bootstrap(self, session: Session, *, initial: bool = True) -> None:
        if session.character is None:
            raise ProtocolError("cannot send map bootstrap without character")
        session.state = SessionState.MAP_LOADING
        if self.database.load_farm(session.character.character_id) is None:
            session.map_state.map_id = self.config.default_map_id
            session.map_state.name = self.config.default_map_name
        if session.map_state.farm_id is None:
            # -2/io.aI is userIDFarm. Equaling the local character ID prevents
            # the client from creating the "return to my farm" house marker.
            session.map_state.farm_id = session.character.character_id
        # The client helper L for inbound -8 sets fi.a, loads data/mapN and
        # initializes map/entity state. The -2 snapshot must follow it; sending
        # -2 first leaves fi.a at login mode 100 and causes onMessage ERROR=-2.
        self.database.save_session_state(session.account, session.map_state)
        nearby_players = [
            NearbyPlayer(other.character)
            for other in self.config.active_sessions
            if other is not session
            and other.character is not None
            and other.state == SessionState.IN_WORLD
            and other.map_state.map_type == session.map_state.map_type
            and other.map_state.map_id == session.map_state.map_id
        ]
        await self.send_packet(
            session,
            Command.S2C_WORLD_HANDOFF,
            encode_world_handoff(
                session.character,
                session.map_state,
                self.config.map_objects_for_type(session.map_state.map_type),
                nearby_players,
            ),
        )
        farm_like = session.map_state.map_type in (0, 4, 6, 7, 9, 11)
        snapshot_state = copy(session.map_state)
        if not farm_like:
            # The JAR -2 parser still consumes its common shape, but town and
            # special maps must not inherit persisted farm objects.
            snapshot_state.plant_metadata = []
            snapshot_state.plots = []
            snapshot_state.npc_flags = []
            snapshot_state.animal_states = []
            snapshot_state.weather_flags = (False, False, False)
            snapshot_state.ground_items = []
        await self.send_packet(
            session,
            Command.S2C_FARM_SNAPSHOT,
            encode_map_snapshot(
                snapshot_state,
                map_mode=session.map_state.map_type,
                default_empty_plot=farm_like,
            ),
        )
        if farm_like:
            for ground_item in session.map_state.ground_items:
                await self.send_packet(session, Command.S2C_ITEM_ACTION, encode_item_appear_response(ground_item))
        # The client has separate post-bootstrap parsers for the main bag and
        # currency. Send these only during login/character creation; map
        # transitions preserve the already loaded inventory and HUD state.
        if initial:
            items = session.character.inventory_items[:session.character.inventory_capacity]
            await self.send_packet(session, Command.S2C_MAIN_BAG, encode_inventory_resize(len(items)))
            await self.send_packet(session, Command.S2C_MAIN_BAG, encode_inventory_snapshot(items))
            await self.send_packet(session, Command.S2C_PLAYER_STATE, encode_currency_update(3, session.character.gold))
            await self.send_packet(session, Command.S2C_PLAYER_STATE, encode_currency_update(4, session.character.premium))
        session.state = SessionState.IN_WORLD

    async def _send_inventory_sync(self, session: Session) -> None:
        if session.character is None:
            return
        items = session.character.inventory_items[: session.character.inventory_capacity]
        await self.send_packet(session, Command.S2C_MAIN_BAG, encode_inventory_resize(len(items)))
        await self.send_packet(session, Command.S2C_MAIN_BAG, encode_inventory_snapshot(items))

    def _persist(self, session: Session) -> None:
        if session.account is not None and session.character is not None:
            self.database.save_session_state(session.account, session.map_state)

    @staticmethod
    def _container_items(character: CharacterState, section: int) -> list[InventoryItem] | None:
        if section == 0:
            return character.inventory_items
        if section == 1:
            return character.storage_items
        return None

    @staticmethod
    def _get_container_item(character: CharacterState, section: int, slot: int) -> InventoryItem | None:
        if section in (0, 1):
            items = CommandDispatcher._container_items(character, section)
            if items is not None and 0 <= slot < len(items):
                return items[slot]
        elif section == 2:
            return character.equipment.get(slot)
        return None

    @staticmethod
    def _remove_quantity(items: list[InventoryItem], slot: int, quantity: int) -> InventoryItem | None:
        if not 0 <= slot < len(items) or quantity <= 0:
            return None
        item = items[slot]
        if item.quantity <= 0 or item.quantity < quantity:
            return None
        moved = copy(item)
        moved.quantity = quantity
        item.quantity -= quantity
        # The Java client resets an entry in place; it does not shift later
        # entries. Keep a zero-quantity tombstone so subsequent client slot
        # numbers still address the same pocket/warehouse positions.
        return moved

    @staticmethod
    def _can_append_or_stack(items: list[InventoryItem], item: InventoryItem, capacity: int | None = None) -> bool:
        if any(current.quantity > 0 and current.kind == item.kind and current.item_id == item.item_id for current in items):
            return True
        if any(current.quantity <= 0 for current in items):
            return True
        return capacity is None or len(items) < capacity

    @staticmethod
    def _append_or_stack(items: list[InventoryItem], item: InventoryItem) -> int:
        for slot, current in enumerate(items):
            if current.quantity > 0 and current.kind == item.kind and current.item_id == item.item_id:
                current.quantity += item.quantity
                return slot
        for slot, current in enumerate(items):
            if current.quantity <= 0:
                items[slot] = copy(item)
                return slot
        items.append(copy(item))
        return len(items) - 1

    async def handle_item_action(self, session: Session, payload: bytes) -> None:
        """Handle the JAR -10 request family without fabricating error packets."""
        character = session.character
        if character is None or session.state != SessionState.IN_WORLD:
            log.debug("ignore item action outside world peer=%s", session.peer)
            return
        reader = PacketReader(payload)
        try:
            subcommand = reader.read_byte()
            if subcommand == 0:  # use item: [0, pocket slot]
                slot = reader.read_byte()
                if reader.remaining() or not 0 <= slot < len(character.inventory_items):
                    return
                item = character.inventory_items[slot]
                remove = False
                if item.kind == 0:
                    equipment_slot = max(0, item.subtype)
                    previous = character.equipment.get(equipment_slot)
                    character.equipment[equipment_slot] = copy(item)
                    if previous is None:
                        item.quantity = 0
                        remove = True
                    else:
                        character.inventory_items[slot] = previous
                else:
                    health_cost = 1 if item.kind == 4 and item.subtype in (6, 7) else 0
                    if item.quantity <= 0:
                        return
                    item.quantity -= 1
                    if item.quantity == 0:
                        # Keep the slot index stable; -10/0 tells the client to
                        # reset that slot in place.
                        remove = True
                    if health_cost:
                        character.health = max(0, character.health - health_cost)
                self._persist(session)
                await self.send_packet(session, Command.S2C_ITEM_ACTION, encode_item_use_response(slot, remove))
                if item.kind == 4 and item.subtype in (6, 7):
                    await self.send_packet(session, Command.S2C_PLAYER_STATE, encode_health_update(character.health))
                await self._send_inventory_sync(session)
                return

            if subcommand == 1:  # drop item: [1, slot, container]
                slot = reader.read_byte()
                container = reader.read_byte()
                if reader.remaining() or not 0 <= slot < 128 or container not in (0, 1, 2):
                    return
                if container in (0, 1):
                    items = self._container_items(character, container)
                    if items is None or not 0 <= slot < len(items):
                        return
                    items[slot].quantity = 0
                else:
                    if slot not in character.equipment:
                        return
                    del character.equipment[slot]
                self._persist(session)
                await self.send_packet(session, Command.S2C_ITEM_ACTION, encode_item_drop_response(slot, container))
                if container == 0:
                    await self._send_inventory_sync(session)
                return

            if subcommand == 2:  # unequip costume slot 3 into the requested pocket slot
                pocket_slot = reader.read_byte()
                if reader.remaining() or not 0 <= pocket_slot < len(character.inventory_items):
                    return
                equipped = character.equipment.pop(3, None)
                if equipped is None:
                    return
                character.inventory_items[pocket_slot] = equipped
                self._persist(session)
                await self.send_packet(session, Command.S2C_ITEM_ACTION, encode_item_unequip_response(pocket_slot))
                await self._send_inventory_sync(session)
                return

            if subcommand == 3:  # move: [3, direction, source slot, quantity]
                direction = reader.read_byte()
                source_slot = reader.read_byte()
                quantity = reader.read_byte()
                if reader.remaining() or direction not in (0, 1, 2, 3) or quantity <= 0:
                    return
                source_section = {0: 1, 1: 0, 2: 0, 3: 2}[direction]
                source_items = self._container_items(character, source_section)
                if source_section == 2:
                    source = character.equipment.get(source_slot)
                    if source is None or source.quantity < quantity:
                        return
                    moved = copy(source)
                    moved.quantity = quantity
                    source.quantity -= quantity
                    if source.quantity == 0:
                        del character.equipment[source_slot]
                else:
                    if source_items is None:
                        return
                    moved = self._remove_quantity(source_items, source_slot, quantity)
                    if moved is None:
                        return
                if direction == 0:
                    if not self._can_append_or_stack(character.inventory_items, moved, character.inventory_capacity):
                        return
                    destination_slot = self._append_or_stack(character.inventory_items, moved)
                    destination_quantity = character.inventory_items[destination_slot].quantity
                elif direction == 1:
                    destination_slot = self._append_or_stack(character.storage_items, moved)
                    destination_quantity = character.storage_items[destination_slot].quantity
                elif direction == 2:
                    if moved.kind != 0:
                        return
                    destination_slot = max(0, moved.subtype)
                    existing = character.equipment.get(destination_slot)
                    if existing is not None and (existing.kind != moved.kind or existing.item_id != moved.item_id):
                        return
                    if existing is None:
                        character.equipment[destination_slot] = moved
                    else:
                        existing.quantity += moved.quantity
                    destination_quantity = character.equipment[destination_slot].quantity
                else:
                    if not self._can_append_or_stack(character.inventory_items, moved, character.inventory_capacity):
                        return
                    destination_slot = self._append_or_stack(character.inventory_items, moved)
                    destination_quantity = character.inventory_items[destination_slot].quantity
                self._persist(session)
                await self.send_packet(
                    session,
                    Command.S2C_ITEM_ACTION,
                    encode_item_move_response(direction, quantity, source_slot, (destination_slot, destination_quantity)),
                )
                if direction in (0, 3):
                    await self._send_inventory_sync(session)
                return

            if subcommand == 4:  # pickup ground object: [4, int object id]
                object_id = reader.read_int()
                if reader.remaining():
                    return
                ground = next((item for item in session.map_state.ground_items if item.object_id == object_id), None)
                if ground is None or not self._can_append_or_stack(character.inventory_items, ground.item, character.inventory_capacity):
                    return
                self._append_or_stack(character.inventory_items, ground.item)
                session.map_state.ground_items.remove(ground)
                self._persist(session)
                await self.send_packet(session, Command.S2C_ITEM_ACTION, encode_item_ground_remove_response(object_id))
                await self._send_inventory_sync(session)
                return

            if subcommand == 6:  # renew expiry: [6, section, slot] (JAR/APK common form)
                section = reader.read_byte()
                slot = reader.read_byte()
                if reader.remaining() or section not in (0, 1, 2):
                    return
                item = self._get_container_item(character, section, slot)
                if item is None or item.quantity <= 0:
                    return
                item.expiry_short = max(item.expiry_short, self.config.item_renewal_duration_short)
                self._persist(session)
                await self.send_packet(
                    session,
                    Command.S2C_ITEM_ACTION,
                    encode_item_expiry_response(section, slot, item.expiry_short, -1),
                )
                return

            log.debug("ignore unsupported item subcommand peer=%s sub=%s", session.peer, subcommand)
        except ProtocolError:
            log.debug("invalid item action peer=%s payload=%d", session.peer, len(payload))

    async def handle_farm_action(self, session: Session, payload: bytes) -> None:
        """Apply the JAR farm action lifecycle to the authoritative farm state."""
        character = session.character
        if character is None or session.state != SessionState.IN_WORLD:
            log.debug("ignore farm action outside world peer=%s", session.peer)
            return
        reader = PacketReader(payload)
        try:
            plot_index = reader.read_byte()
            action = reader.read_byte()
            item_slot = reader.read_byte() if action in (2, 3) else -1
            requested_actor_id = reader.read_int() if reader.remaining() == 4 else character.character_id
            if reader.remaining() or not 0 <= plot_index < len(session.map_state.plots) or action not in range(6):
                return
            if action in (0, 1, 3, 5) and character.health < 1:
                return
            plot = session.map_state.plots[plot_index]
            if plot.state != 1:
                # state 0 is an unavailable/unlocked plot in the JAR snapshot;
                # never create a crop object for it implicitly.
                return
            plot.index = plot_index
            # The JAR applies animation to io.e(actorId). The local player is
            # not registered there with an initialized animation Vector (pu.E),
            # so echoing its ID makes cases 0/1/2/5 throw in the client parser.
            # This server has no remote-actor broadcast yet; use the absent
            # actor sentinel and let the JAR safely skip animation.
            response_actor_id = 0
            health_cost = 1 if action in (0, 1, 3, 5) else 0
            if action == 0:  # cultivate soil / clear a crop
                plot.entity_type = -1
                plot.entity_name = ""
                plot.entity_state = 0
                plot.entity_flag = 1
                plot.entity_level = 0
                plot.fertilized = False
                # The client represents freshly cultivated soil as a dry plot;
                # ``ready`` is the datkho flag, so watering is allowed next.
                plot.ready = True
                plot.timer = 0
            elif action == 1:  # water soil
                if plot.state != 1 or not plot.ready:
                    return
                plot.ready = False
                plot.timer = 0
            elif action == 2:  # sow a seed from the pocket
                if not 0 <= item_slot < len(character.inventory_items):
                    return
                seed = character.inventory_items[item_slot]
                if seed.kind != 1 or seed.quantity <= 0 or plot.entity_type >= 0:
                    return
                plot.entity_type = seed.item_id
                plot.entity_name = seed.name
                plot.entity_state = 0
                plot.entity_flag = max(1, seed.stars)
                plot.entity_level = 0
                plot.fertilized = False
                seed.quantity -= 1
            elif action == 3:  # fertilize
                if plot.entity_type < 0 or not 0 <= item_slot < len(character.inventory_items):
                    return
                fertilizer = character.inventory_items[item_slot]
                if fertilizer.kind != 4 or fertilizer.quantity <= 0:
                    return
                fertilizer.quantity -= 1
                plot.fertilized = True
            elif action == 4:  # harvest a mature crop
                if plot.entity_type < 0 or plot.entity_state < 4:
                    return
                reward = InventoryItem(kind=3, item_id=plot.entity_type, name=plot.entity_name or "Nông sản", description="", quantity=1)
                if not self._can_append_or_stack(character.inventory_items, reward, character.inventory_capacity):
                    return
                reward_slot = self._append_or_stack(character.inventory_items, reward)
                character.exp += max(0, self.config.harvest_exp)
                plot.entity_type = -1
                plot.entity_name = ""
                plot.entity_state = 0
                plot.entity_flag = 1
                plot.entity_level = 0
                plot.fertilized = False
                plot.ready = True
                plot.timer = 0
            elif action == 5:  # destroy crop
                if plot.entity_type < 0:
                    return
                plot.entity_type = -1
                plot.entity_name = ""
                plot.entity_state = 0
                plot.entity_flag = 1
                plot.entity_level = 0
                plot.fertilized = False
            if health_cost:
                character.health = max(0, character.health - health_cost)
            self._persist(session)
            if action == 0:
                await self.send_packet(session, Command.S2C_FARM_ACTION, encode_farm_actor_update(0, response_actor_id, plot_index))
            elif action == 1:
                await self.send_packet(session, Command.S2C_FARM_ACTION, encode_farm_actor_update(1, response_actor_id, plot_index))
            elif action == 2:
                await self.send_packet(
                    session,
                    Command.S2C_FARM_ACTION,
                    encode_farm_actor_update(2, response_actor_id, plot_index, crop_id=plot.entity_type, crop_name=plot.entity_name, stars=plot.entity_flag),
                )
            elif action == 3:
                await self.send_packet(session, Command.S2C_FARM_ACTION, encode_farm_plot_update(plot, character.exp, response_actor_id))
            elif action == 4:
                await self.send_packet(session, Command.S2C_FARM_ACTION, encode_farm_harvest_update(response_actor_id, plot_index, -1, plot.entity_flag))
                await self.send_packet(
                    session,
                    Command.S2C_MAIN_BAG,
                    encode_inventory_harvest_reward(reward_slot, reward, character.exp, -1, plot.entity_flag),
                )
            elif action == 5:
                await self.send_packet(session, Command.S2C_FARM_ACTION, encode_farm_actor_update(5, response_actor_id, plot_index))
            if health_cost:
                await self.send_packet(session, Command.S2C_PLAYER_STATE, encode_health_update(character.health))
            # doGieoHat() decrements the local seed stack before sending -4/2;
            # do not emit a second -6 snapshot that would race/double-apply it.
        except ProtocolError:
            log.debug("invalid farm action peer=%s payload=%d", session.peer, len(payload))

    async def handle_create_character(self, session: Session, payload: bytes) -> None:
        if session.account is None:
            log.debug("ignore create-character before login peer=%s", session.peer)
            return
        reader = PacketReader(payload)
        try:
            # jo.java calls sq.a(pu.w, Integer.parseInt(day), season), while
            # sq.java writes all three values with writeByte().
            state_w = reader.read_byte()
            birth_day = reader.read_byte()
            birth_season = reader.read_byte()
        except ProtocolError:
            log.debug("invalid create-character payload peer=%s length=%d", session.peer, len(payload))
            return
        if reader.remaining() or state_w not in (0, 1) or not 1 <= birth_day <= 31 or not 0 <= birth_season <= 3:
            log.debug("reject create-character fields peer=%s w=%d day=%d season=%d trailing=%d", session.peer, state_w, birth_day, birth_season, reader.remaining())
            return
        character = self._character_for_username(
            session.account.username,
            state_w=state_w,
            birth_day=birth_day,
            birth_season=birth_season,
        )
        session.account.character = character
        self.database.save_character(session.account.username, character)
        session.character = character
        session.state = SessionState.CHARACTER_SELECTED
        await self.send_packet(session, Command.S2C_LOGIN_BOOTSTRAP, encode_login_bootstrap(character))
        await self.send_map_bootstrap(session, initial=True)

    async def handle_map_action(self, session: Session, payload: bytes) -> None:
        if session.character is None:
            log.debug("ignore map action without character peer=%s", session.peer)
            return
        reader = PacketReader(payload)
        try:
            target_map = reader.read_byte()
            owner_or_map_id: int | None = None
            if target_map in (0, 4, 6, 9):
                owner_or_map_id = reader.read_int()
                # sq.a(int) sends io.aI for these farm-like targets. Keep it
                # as farm owner metadata; it is not the -8 map integer.
                session.map_state.farm_id = owner_or_map_id
            elif target_map == 11:
                owner_or_map_id = reader.read_int()
                # sq.b(11, characterId) is the special map-11 request. The
                # integer identifies the destination owner/instance.
                session.map_state.map_id = owner_or_map_id
            elif target_map in (1, 2, 3, 5, 7, 8, 10, 12, 13, 14, 15):
                # sq.a(int) writes only the target byte for these maps.
                pass
            else:
                log.debug("ignore unsupported map target peer=%s target=%d", session.peer, target_map)
                return
            if reader.remaining():
                log.debug("invalid map action trailing bytes peer=%s trailing=%d", session.peer, reader.remaining())
                return
            session.map_state.map_type = target_map
            # L(is) overwrites pu.d().am/an from the first two -8 shorts.
            # A character can otherwise arrive outside the destination map or
            # inside its edge trigger, which makes it appear to vanish. Keep
            # persisted login coordinates intact, but place explicit map
            # transitions at a safe interior point for the destination map.
            session.character.x, session.character.y = self.config.spawn_for_map(target_map)
            if session.account is not None:
                self.database.save_character(session.account.username, session.character)
            log.debug(
                "map transition request peer=%s target=%d owner_or_map_id=%s",
                session.peer,
                target_map,
                owner_or_map_id,
            )
        except ProtocolError:
            log.debug("invalid map action peer=%s payload=%d", session.peer, len(payload))
            return
        await self.send_map_bootstrap(session, initial=False)

    async def handle_position(self, session: Session, payload: bytes) -> None:
        if session.character is None or session.state != SessionState.IN_WORLD:
            return
        reader = PacketReader(payload)
        try:
            if reader.remaining() == 2:
                # sq.e() sends one short per request: x when x changed, then
                # -y when y changed. It does not send an x/y pair.
                wire_position = reader.read_short()
                if wire_position >= 0:
                    session.character.x = wire_position
                else:
                    session.character.y = -wire_position
            elif reader.remaining() == 4:
                # Accept the pair form as a diagnostic/tooling convenience.
                session.character.x = reader.read_short()
                session.character.y = reader.read_short()
            else:
                log.debug("invalid movement payload peer=%s length=%d", session.peer, reader.remaining())
                return
        except ProtocolError:
            return
        if session.account is not None:
            self.database.save_session_state(session.account, session.map_state)
        log.debug("movement peer=%s x=%d y=%d", session.peer, session.character.x, session.character.y)
        # The client already applies local movement. For a single-player
        # session no -52 acknowledgement is required; later multiplayer code
        # can broadcast the corresponding inbound -52 effect to other entities.

    async def handle_npc_action(self, session: Session, payload: bytes) -> None:
        """Handle the JAR static-map-object request ``-9/0 + object ID``."""
        if session.character is None or session.state != SessionState.IN_WORLD:
            log.debug("ignore NPC action outside world peer=%s", session.peer)
            return
        reader = PacketReader(payload)
        try:
            subcommand = reader.read_byte()
            if subcommand != 0:
                log.debug("ignore unsupported NPC action peer=%s sub=%s", session.peer, subcommand)
                return
            object_id = reader.read_byte()
            if reader.remaining():
                log.debug("invalid NPC action trailing bytes peer=%s trailing=%d", session.peer, reader.remaining())
                return
            if object_id != self.config.vending_object_id:
                log.debug("ignore non-shop NPC action peer=%s object_id=%d", session.peer, object_id)
                return
            # ua.b() emits this exact request for low-ID static interactables.
            # The map0 seed/fertilizer machine is one such object (ID 21). Do
            # not invent a world entity; reply only after the client requests
            # the object interaction, and keep the object ID for diagnostics.
            await self.send_packet(
                session,
                Command.S2C_NPC_SHOP,
                encode_npc_shop_open("Cửa hàng hạt giống", self.config.vending_shop),
            )
            log.debug("NPC shop opened peer=%s object_id=%d offers=%d", session.peer, object_id, len(self.config.vending_shop))
        except ProtocolError:
            log.debug("invalid NPC action peer=%s payload=%d", session.peer, len(payload))

    async def handle_shop_action(self, session: Session, payload: bytes) -> None:
        """Handle the JAR vending-machine request ``-22/0 + boolean``."""
        if session.character is None or session.state != SessionState.IN_WORLD:
            log.debug("ignore shop action outside world peer=%s", session.peer)
            return
        reader = PacketReader(payload)
        try:
            subcommand = reader.read_byte()
            if subcommand != 0:
                log.debug("ignore unsupported shop action peer=%s sub=%s", session.peer, subcommand)
                return
            # The JAR writer calls this flag ``boolean``; both false (open the
            # vending machine) and true (refresh/detail mode) use the same
            # response parser in so.w case 0.
            reader.read_boolean()
            if reader.remaining():
                log.debug("invalid shop action trailing bytes peer=%s trailing=%d", session.peer, reader.remaining())
                return
            await self.send_packet(
                session,
                Command.S2C_SHOP_DATA,
                encode_shop_open(self.config.vending_shop, self.config.vending_shop_tab),
            )
            log.debug("shop opened peer=%s offers=%d", session.peer, len(self.config.vending_shop))
        except ProtocolError:
            log.debug("invalid shop action peer=%s payload=%d", session.peer, len(payload))

    async def handle_character_delta_request(self, session: Session, payload: bytes) -> None:
        # Keep this handler intentionally conservative. The client has many
        # -11 request subcommands; unsupported mutations must not be accepted
        # silently as authoritative state changes.
        if not payload:
            return
        subcommand = PacketReader(payload).read_byte()
        log.debug("character delta request peer=%s subcommand=%s", session.peer, subcommand)

    async def dispatch(self, session: Session, command: int, payload: bytes) -> None:
        session.last_command = command
        if command == Command.C2S_LOGIN_REQUEST:
            await self.handle_login(session, payload)
        elif command == Command.C2S_CREATE_CHARACTER:
            await self.handle_create_character(session, payload)
        elif command == Command.C2S_WORLD_ACTION:
            await self.handle_map_action(session, payload)
        elif command == Command.C2S_POSITION:
            await self.handle_position(session, payload)
        elif command == Command.C2S_ITEM_ACTION:
            await self.handle_item_action(session, payload)
        elif command == Command.C2S_NPC_ACTION:
            await self.handle_npc_action(session, payload)
        elif command == Command.C2S_SHOP_ACTION:
            await self.handle_shop_action(session, payload)
        elif command == Command.C2S_FARM_ACTION:
            await self.handle_farm_action(session, payload)
        elif command == Command.C2S_PLAYER_STATE:
            await self.handle_character_delta_request(session, payload)
        else:
            # Unsupported opcodes are protocol observations, not errors. The
            # client has many valid commands whose gameplay schemas are not
            # implemented yet; sending -3 here desynchronizes its UI/state.
            log.debug("ignore unsupported command peer=%s command=%s payload=%d", session.peer, command, len(payload))


async def serve_session(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, config: ServerConfig) -> None:
    peer_info = writer.get_extra_info("peername")
    peer = str(peer_info)
    session = Session(reader=reader, writer=writer, peer=peer)
    config.active_sessions.append(session)
    dispatcher = CommandDispatcher(config)
    try:
        command, payload = await read_frame(reader)
        if command != Command.C2S_HANDSHAKE or payload:
            raise ProtocolError("first client frame must be plaintext -27 with empty payload")
        session.handshake_received = True
        await dispatcher.send_handshake(session)
        while not reader.at_eof() and session.state != SessionState.CLOSED:
            command, payload = await read_frame(reader, session.rx_cursor)
            await dispatcher.dispatch(session, command, payload)
    except (asyncio.IncompleteReadError, ConnectionError):
        log.info("connection closed peer=%s", peer)
    except (ProtocolError, ValueError) as exc:
        log.info("protocol error peer=%s error=%s", peer, exc)
        try:
            if session.handshake_received:
                await dispatcher.send_packet(session, Command.S2C_TEXT_DIALOG, encode_error("Gói tin không hợp lệ"))
        except Exception:
            log.debug("unable to send protocol error peer=%s", peer, exc_info=True)
    except Exception:
        log.exception("unexpected session failure peer=%s", peer)
    finally:
        session.state = SessionState.CLOSED
        config.active_sessions[:] = [active for active in config.active_sessions if active is not session]
        dispatcher.database.close()
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
