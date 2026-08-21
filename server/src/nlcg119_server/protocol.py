"""Command IDs and response encoders for the first NLCG119 server slice."""

from __future__ import annotations

from dataclasses import dataclass

from .codec import PacketWriter
from .model import AnimalState, CharacterState, GroundItem, InventoryItem, MapObjectMetadata, MapState, NearbyPlayer, PlantMetadata, ShopOffer


class Command:
    """Numeric IDs with direction-specific names.

    The client reuses several IDs in both directions. The aliases at the end
    preserve the v0.x server API, but new code should use the explicit names.
    """

    C2S_HANDSHAKE = -27
    S2C_HANDSHAKE = -27
    C2S_LOGIN_REQUEST = -1
    S2C_LOGIN_BOOTSTRAP = -1
    S2C_FARM_SNAPSHOT = -2
    S2C_TEXT_DIALOG = -3
    C2S_FARM_ACTION = -4
    C2S_CREATE_CHARACTER = -5
    S2C_MAIN_BAG = -6
    C2S_WORLD_ACTION = -8
    S2C_WORLD_HANDOFF = -8
    C2S_ITEM_ACTION = -10
    S2C_ITEM_ACTION = -10
    C2S_NPC_ACTION = -9
    S2C_NPC_SHOP = -9
    C2S_SHOP_ACTION = -22
    S2C_SHOP_DATA = -22
    C2S_PLAYER_STATE = -11
    S2C_PLAYER_STATE = -11
    S2C_FARM_ACTION = -4
    C2S_ACCOUNT_MESSAGE = -12
    S2C_CHAT_MESSAGE = -13
    S2C_LINK_MESSAGE = -31
    S2C_WORLD_EVENT = -34
    C2S_INTERACTION = -36
    S2C_CONFIRMATION = -39
    S2C_ACCOUNT_STATUS = -45
    C2S_PROVIDER_LIST = -46
    C2S_POSITION = -52
    S2C_POSITION = -52

    # Compatibility aliases for existing v0.x callers/tests.
    HANDSHAKE = C2S_HANDSHAKE
    LOGIN = C2S_LOGIN_REQUEST
    FARM_SNAPSHOT = S2C_FARM_SNAPSHOT
    TEXT_ERROR = S2C_TEXT_DIALOG
    FARM_EVENT = C2S_FARM_ACTION
    CREATE_CHARACTER = C2S_CREATE_CHARACTER
    MAP_ACTION = C2S_WORLD_ACTION
    ITEM_EVENT = C2S_ITEM_ACTION
    NPC_EVENT = C2S_NPC_ACTION
    NPC_SHOP = S2C_NPC_SHOP
    SHOP_EVENT = C2S_SHOP_ACTION
    SHOP_DATA = S2C_SHOP_DATA
    CHARACTER_DELTA = S2C_PLAYER_STATE
    INVENTORY_SYNC = S2C_MAIN_BAG
    ACCOUNT_MESSAGE = C2S_ACCOUNT_MESSAGE
    LINK_MESSAGE = S2C_LINK_MESSAGE
    WORLD_ACTION = S2C_WORLD_EVENT
    INTERACTION = C2S_INTERACTION
    CONFIRMATION = S2C_CONFIRMATION
    ACCOUNT_STATUS = S2C_ACCOUNT_STATUS
    PROVIDER_LIST = C2S_PROVIDER_LIST
    POSITION = C2S_POSITION


@dataclass(frozen=True)
class LoginRequest:
    username: str
    password: str
    client_version: str
    screen_width: int
    screen_height: int
    mode: int


def parse_login_request(payload: bytes) -> LoginRequest:
    from .codec import PacketReader

    reader = PacketReader(payload)
    request = LoginRequest(
        username=reader.read_utf(),
        password=reader.read_utf(),
        client_version=reader.read_utf(),
        screen_width=reader.read_short(),
        screen_height=reader.read_short(),
        mode=reader.read_byte(),
    )
    if reader.remaining():
        raise ValueError(f"unexpected login trailing bytes: {reader.remaining()}")
    return request


def encode_shop_open(offers: list[ShopOffer], tab: int = 0) -> bytes:
    """Encode the JAR ``-22`` subcase 0 vending-machine catalog.

    ``so.w`` reads: subcase, tab, count, then for each offer the item type,
    an auxiliary int (stored in ``io.az``), the type-specific item body, and
    the displayed price/currency pair applied through ``rh.a(int,byte)``.
    Shop records intentionally omit inventory-only highlighted/value flags;
    the JAR constructors supply those values locally.
    """
    if len(offers) > 127:
        raise ValueError("shop catalog cannot contain more than 127 offers")
    writer = PacketWriter()
    writer.write_byte(0)
    writer.write_byte(tab)
    writer.write_byte(len(offers))
    for offer in offers:
        item = offer.item
        writer.write_byte(item.kind)
        writer.write_int(offer.auxiliary_value)
        _write_shop_record(writer, item)
        writer.write_int(offer.price)
        writer.write_byte(offer.currency)
    return writer.to_bytes()


def encode_npc_shop_open(name: str, offers: list[ShopOffer]) -> bytes:
    """Encode JAR inbound ``-9`` case 0 for a seed/fertilizer shop.

    The static ``ua`` interactable sends ``-9/0`` followed by its object ID.
    ``so.G`` then reads a shop title, count, and the JAR's NPC-offer records.
    Unlike ``-22`` case 0, several item fields are fixed to ``1`` by the JAR
    constructors; those fixed values are emitted here deliberately.
    """
    if len(offers) > 127:
        raise ValueError("NPC shop catalog cannot contain more than 127 offers")
    writer = PacketWriter()
    writer.write_byte(0)
    writer.write_utf(name)
    writer.write_byte(len(offers))
    for offer in offers:
        item = offer.item
        if item.kind not in (0, 1, 2, 3, 4):
            raise ValueError(f"unsupported JAR -9 shop record type: {item.kind}")
        writer.write_byte(item.kind)
        if item.kind == 0:
            writer.write_short(item.item_id)
            writer.write_short(item.detail_id)
            writer.write_utf(item.name)
            writer.write_byte(item.subtype)
            writer.write_byte(item.icon_type)
            writer.write_utf(item.label)
            writer.write_short(item.detail_short)
        elif item.kind == 1:
            writer.write_short(item.item_id)
            writer.write_utf(item.name)
            writer.write_byte(item.subtype)
            writer.write_byte(item.icon_type)
            writer.write_utf(item.label)
            writer.write_byte(item.growth_count)
            writer.write_byte(item.stack_value)
            writer.write_short(item.required_level)
        elif item.kind == 2:
            writer.write_short(item.item_id)
            writer.write_utf(item.name)
            writer.write_utf(item.description)
            _write_item_image(writer, item.image_data)
        elif item.kind == 3:
            writer.write_short(item.item_id)
            writer.write_utf(item.name)
            writer.write_utf(item.description)
        elif item.kind == 4:
            writer.write_short(item.item_id)
            writer.write_utf(item.name)
            writer.write_byte(item.subtype)
            writer.write_utf(item.description)
            _write_item_image(writer, item.image_data)
            writer.write_short(item.extra_short)
        writer.write_int(offer.price)
        writer.write_byte(offer.currency)
    return writer.to_bytes()


def encode_error(message: str, command: int = Command.S2C_TEXT_DIALOG) -> bytes:
    writer = PacketWriter()
    writer.write_utf(message)
    return writer.to_bytes()


def _encode_character_bootstrap_prefix(writer: PacketWriter, character: CharacterState, gender: int) -> None:
    """Write the common prefix consumed by so.java case -1."""
    writer.write_int(character.character_id)
    writer.write_utf(character.name)
    writer.write_utf(character.secondary_name)
    if character.secondary_name:
        writer.write_byte(0)  # pu.K
        writer.write_byte(0)  # pu.L
    writer.write_byte(gender)  # pu.w / APK Char.gender
    writer.write_short(character.level)
    writer.write_byte(character.id_ring)  # pu.q / APK Char.idRing
    writer.write_byte(character.v_default)  # pu.x / APK Char.vDefault
    # APK names these fields GameScr.suckhoe/maxSuckhoe and EXP/maxEXP.
    # Keep the two renderer divisors positive, but preserve configured values.
    writer.write_short(max(1, character.health))  # io.am / suckhoe
    writer.write_short(max(1, character.max_health))  # io.an / maxSuckhoe
    writer.write_int(max(0, character.exp))  # io.aj / EXP
    writer.write_int(max(1, character.max_exp))  # io.ak / maxEXP
    writer.write_int(max(0, character.gold))
    writer.write_int(max(0, character.premium))
    # io.aB is the total bag capacity; by3 is the number of populated
    # records. When by3 < aB, the client allocates by3+1 visible slots so the
    # last slot acts as the expansion/sentinel slot.
    capacity = max(1, min(127, character.inventory_capacity))
    current_count = max(0, min(capacity, len(character.inventory_items)))
    writer.write_byte(capacity)  # io.aB
    writer.write_byte(current_count)  # by3
    # The five records here are quick-item slots (io.aq[0..3] + io.at), not
    # the main bag io.au. Keep them empty; main-bag records are sent by -6.
    for _ in range(5):
        writer.write_byte(-1)
    writer.write_byte(character.leg)  # pu.y / APK Char.leg
    writer.write_byte(character.body)  # pu.z / APK Char.body
    writer.write_byte(character.hair)  # pu.A / APK Char.hair
    writer.write_byte(character.glasses)  # pu.B / APK Char.glasses
    status = list(character.status[:4])
    status.extend([0] * (4 - len(status)))
    for value in status:
        writer.write_byte(value)
    writer.write_boolean(False)  # no companion body follows


def encode_login_bootstrap(character: CharacterState) -> bytes:
    """Encode an existing playable character response for inbound ``-1``.

    This function intentionally has no no-character flag. The client’s
    ``w == -1`` branch is a different account state and is encoded by
    :func:`encode_no_character_bootstrap`.
    """
    writer = PacketWriter()
    _encode_character_bootstrap_prefix(writer, character, character.gender)
    return writer.to_bytes()


def encode_no_character_bootstrap(
    *,
    selection_values: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0),
) -> bytes:
    """Encode the no-character branch that opens m.e() in the client.

    The client still consumes the complete common prefix, but requires
    ``w=-1`` and then six shorts for ``m.n[2][3]``. It must not be followed by
    a map handoff until the client submits outbound ``-5``.
    """
    if len(selection_values) != 6:
        raise ValueError("selection_values must contain exactly six shorts")
    placeholder = CharacterState(character_id=0, name="", state_w=-1)
    writer = PacketWriter()
    _encode_character_bootstrap_prefix(writer, placeholder, -1)  # Char.gender=-1 selects creation UI
    for value in selection_values:
        writer.write_short(value)
    return writer.to_bytes()


def encode_map_snapshot(
    map_state: MapState,
    map_mode: int | None = None,
    *,
    default_empty_plot: bool = True,
) -> bytes:
    """Encode the complete inbound ``-2`` map/farm snapshot consumed by the JAR.

    ``map_mode`` is normally inferred from ``map_state.map_id``. It remains an
    optional override for callers that use a protocol mode separate from the
    logical map ID. Map 11 has no post-plot animal/tail fields; all other maps
    carry the three farm flags, animal records, conditional timer shorts, and
    the final ``rg.a`` boolean.
    """
    from .model import PlotState

    writer = PacketWriter()
    # so.java reads this as io.aI/userIDFarm and compares it with the local
    # character ID. It is not the world map ID carried by -8.
    writer.write_int(map_state.farm_id if map_state.farm_id is not None else map_state.map_id)
    writer.write_utf(map_state.name)

    plant_metadata = list(map_state.plant_metadata)
    if len(plant_metadata) > 127:
        raise ValueError("map snapshot cannot contain more than 127 plant metadata records")
    writer.write_byte(len(plant_metadata))
    for plant in plant_metadata:
        writer.write_short(plant.plant_id)
        writer.write_short(plant.growth_short_0)
        writer.write_short(plant.growth_short_1)
        writer.write_short(plant.growth_short_2)
        writer.write_byte(plant.crop_type)

    plots = list(map_state.plots)
    if not plots and default_empty_plot:
        plots = [PlotState(index=0, state=1, ready=True, entity_type=-1)]
    effective_mode = map_state.map_id if map_mode is None else map_mode
    max_plots = 74 if effective_mode == 11 else 108
    if len(plots) > max_plots:
        raise ValueError(f"map mode {effective_mode} supports at most {max_plots} plots")
    writer.write_byte(len(plots))
    for plot in plots:
        writer.write_byte(plot.state)
        if plot.state != 1:
            continue
        # PlotState.ready is the server's datkho flag: true means dry soil;
        # false means the client must consume the following soil timer short.
        writer.write_boolean(plot.ready)
        if not plot.ready:
            writer.write_short(plot.timer)
        writer.write_byte(plot.entity_type)
        if plot.entity_type < 0:
            continue
        writer.write_utf(plot.entity_name)
        writer.write_byte(plot.entity_state)
        writer.write_byte(plot.entity_flag)
        writer.write_boolean(bool(plot.fertilized))
        writer.write_short(plot.entity_level)

    # The original parser returns immediately after plots for map 11. Emitting
    # even one trailing byte here would become the first byte of the next frame
    # from the client's point of view.
    if effective_mode == 11:
        return writer.to_bytes()

    weather_flags = tuple(map_state.weather_flags)
    if len(weather_flags) != 3:
        raise ValueError("weather_flags must contain exactly three booleans")
    for value in weather_flags:
        writer.write_boolean(value)

    animals: list[AnimalState] = list(map_state.animal_states)
    if not animals:
        # npc_flags is the v0.10 compatibility representation. A legacy tuple
        # contains exactly the seven Vatnuoi constructor bytes; timer fields use
        # safe zero/-1 defaults and are still emitted where the JAR requires it.
        for values in map_state.npc_flags:
            if len(values) != 7:
                raise ValueError("legacy npc_flags entries must contain seven values")
            animals.append(
                AnimalState(
                    object_id=values[0],
                    image_id=values[1],
                    age_state=values[2],
                    condition=values[3],
                    sick=bool(values[4]),
                    animal_type=values[5],
                    index=values[6],
                    harvest_item_id=-1,
                )
            )
    if len(animals) > 127:
        raise ValueError("map snapshot cannot contain more than 127 animals")
    writer.write_byte(len(animals))
    for animal in animals:
        writer.write_byte(animal.object_id)
        writer.write_byte(animal.image_id)
        writer.write_byte(animal.age_state)
        writer.write_byte(animal.condition)
        writer.write_boolean(animal.sick)
        writer.write_byte(animal.animal_type)
        writer.write_byte(animal.index)
        writer.write_short(animal.death_timer)
        if animal.condition == 0:
            writer.write_short(animal.condition_timer)
        if animal.sick:
            writer.write_short(animal.illness_timer)
        if animal.age_state == 0:
            writer.write_short(animal.growth_timer)
        elif animal.age_state == 2:
            writer.write_short(animal.pregnancy_timer)
        elif animal.age_state == 1:
            writer.write_short(animal.production_timer)
        elif animal.age_state == 3:
            writer.write_short(animal.harvest_item_id)

    writer.write_boolean(map_state.map_tail_flag)
    return writer.to_bytes()


def encode_world_handoff(
    character: CharacterState,
    map_state: MapState,
    map_objects: list[MapObjectMetadata] | None = None,
    nearby_players: list[NearbyPlayer] | None = None,
) -> bytes:
    """Encode inbound ``-8`` helper L, including metadata for existing ua objects."""
    objects = list(map_objects or [])
    players = list(nearby_players or [])
    if len(objects) > 127:
        raise ValueError("world handoff cannot contain more than 127 map object records")
    if len(players) > 127:
        raise ValueError("world handoff cannot contain more than 127 nearby players")
    writer = PacketWriter()
    # L(is) reads local spawn first, then a byte K-record count. Zero is a
    # valid world state; nearby player entities are added only when authoritative
    # data exists. Map-object records below describe static ua objects already
    # loaded from data/mapN; they do not create entities.
    writer.write_short(character.x)
    writer.write_short(character.y)
    writer.write_byte(len(players))
    for nearby in players:
        remote = nearby.character
        writer.write_int(remote.character_id)
        writer.write_utf(remote.name)
        writer.write_utf(remote.secondary_name)
        if remote.secondary_name:
            writer.write_byte(0)
            writer.write_byte(0)
        writer.write_short(remote.level)
        writer.write_byte(remote.kind)
        writer.write_byte(remote.direction)
        writer.write_short(remote.x)
        writer.write_short(remote.y)
        writer.write_byte(remote.appearance_y)
        writer.write_byte(remote.appearance_z)
        writer.write_byte(remote.appearance_a)
        writer.write_byte(remote.appearance_b)
        writer.write_byte(remote.state_w)
        writer.write_byte(remote.state_u)
        writer.write_byte(remote.state_q)
        writer.write_byte(0)  # no companion/body effect
        writer.write_boolean(False)  # no companion object
    writer.write_int(map_state.map_id)
    writer.write_byte(map_state.map_type)
    writer.write_utf(map_state.name)
    writer.write_byte(map_state.auxiliary)
    writer.write_byte(len(objects))
    for obj in objects:
        writer.write_byte(obj.object_id)
        writer.write_utf(obj.name)
        writer.write_byte(obj.sprite_a)
        writer.write_byte(obj.sprite_b)
        writer.write_byte(obj.sprite_c)
        writer.write_byte(obj.collision_size)
        writer.write_utf(obj.chat)
    return writer.to_bytes()


def encode_text_dialog(message: str, command: int = Command.S2C_TEXT_DIALOG) -> bytes:
    writer = PacketWriter()
    writer.write_utf(message)
    return writer.to_bytes()


def encode_level_up(character: CharacterState, next_value: int = 0) -> bytes:
    writer = PacketWriter()
    writer.write_byte(18)
    writer.write_short(character.level)
    writer.write_short(character.x)
    writer.write_short(character.y)
    writer.write_int(next_value)
    return writer.to_bytes()


def encode_character_delta_exp(exp: int) -> bytes:
    writer = PacketWriter()
    writer.write_byte(2)
    writer.write_int(exp)
    return writer.to_bytes()


def encode_health_update(health: int, recovery_timer: int = 0) -> bytes:
    """Encode inbound -11 subcase 0: short health and recovery byte."""
    writer = PacketWriter()
    writer.write_byte(0)
    writer.write_short(max(0, health))
    writer.write_byte(recovery_timer)
    return writer.to_bytes()


def encode_item_use_response(slot: int, remove: bool = False) -> bytes:
    writer = PacketWriter()
    writer.write_byte(0)
    writer.write_byte(slot)
    writer.write_boolean(remove)
    return writer.to_bytes()


def encode_item_drop_response(slot: int, container: int = 0) -> bytes:
    writer = PacketWriter()
    writer.write_byte(1)
    writer.write_byte(slot)
    writer.write_byte(container)
    return writer.to_bytes()


def encode_item_unequip_response(slot: int) -> bytes:
    writer = PacketWriter()
    writer.write_byte(2)
    writer.write_byte(slot)
    return writer.to_bytes()


def encode_item_move_response(direction: int, quantity: int, source_slot: int, destination: tuple[int, int]) -> bytes:
    """Encode -10/3 as direction, moved quantity, source, then dest/qty pairs."""
    writer = PacketWriter()
    writer.write_byte(3)
    writer.write_byte(direction)
    writer.write_byte(quantity)
    writer.write_byte(source_slot)
    for slot, resulting_quantity in (destination,):
        writer.write_byte(slot)
        writer.write_byte(resulting_quantity)
    return writer.to_bytes()


def encode_item_appear_response(ground: GroundItem) -> bytes:
    """Encode -10/4, the ground-item appearance record parsed by the client."""
    writer = PacketWriter()
    writer.write_byte(4)
    writer.write_int(ground.object_id)
    writer.write_short(ground.item.item_id)
    writer.write_utf(ground.item.name)
    writer.write_byte(ground.x // 24)
    writer.write_byte(ground.y // 24)
    _write_item_image(writer, ground.item.image_data)
    return writer.to_bytes()


def encode_item_ground_remove_response(object_id: int | None = None) -> bytes:
    writer = PacketWriter()
    writer.write_byte(5)
    if object_id is not None:
        writer.write_int(object_id)
    return writer.to_bytes()


def encode_item_expiry_response(section: int, slot: int, expiry_short: int, marker: int = -1) -> bytes:
    writer = PacketWriter()
    writer.write_byte(6)
    writer.write_byte(section)
    writer.write_byte(slot)
    writer.write_int(marker)
    writer.write_short(expiry_short)
    return writer.to_bytes()


def encode_farm_actor_update(action: int, character_id: int, plot_index: int, *, crop_id: int = -1, crop_name: str = "", stars: int = 1) -> bytes:
    """Encode inbound -4 movement/action responses parsed by the JAR/APK client."""
    if action not in (0, 1, 2, 4, 5):
        raise ValueError("farm actor response action must be one of 0, 1, 2, 4, 5")
    writer = PacketWriter()
    writer.write_byte(action)
    writer.write_int(character_id)
    writer.write_byte(plot_index)
    if action == 2:
        writer.write_short(crop_id)
        writer.write_utf(crop_name)
        writer.write_byte(stars)
    elif action == 4:
        writer.write_short(-1)
        writer.write_byte(stars)
    return writer.to_bytes()


def encode_farm_plot_update(plot: object, exp: int, character_id: int) -> bytes:
    """Encode inbound -4/3 crop update: status, stars, timer, EXP, actor, plot."""
    writer = PacketWriter()
    writer.write_byte(3)
    writer.write_byte(getattr(plot, "entity_state", -1))
    writer.write_byte(getattr(plot, "entity_flag", 1))
    writer.write_short(getattr(plot, "entity_level", 0))
    writer.write_int(exp)
    writer.write_int(character_id)
    writer.write_byte(getattr(plot, "index", 0))
    return writer.to_bytes()


def encode_farm_harvest_update(character_id: int, plot_index: int, timer: int = -1, stars: int = 1) -> bytes:
    """Encode inbound -4/4, which the client uses to finish harvest/clear animation."""
    writer = PacketWriter()
    writer.write_byte(4)
    writer.write_int(character_id)
    writer.write_byte(plot_index)
    writer.write_short(timer)
    writer.write_byte(stars)
    return writer.to_bytes()


def encode_currency_update(kind: int, value: int) -> bytes:
    """Encode inbound -11 subcase 3 (gold) or 4 (premium currency).

    so.M reads one subcommand byte and one int for these two branches.
    """
    if kind not in (3, 4):
        raise ValueError("currency update kind must be 3 (gold) or 4 (premium)")
    writer = PacketWriter()
    writer.write_byte(kind)
    writer.write_int(max(0, value))
    return writer.to_bytes()


def encode_inventory_resize(item_count: int) -> bytes:
    """Encode inbound -6 subcase 3, which resizes io.au around aB."""
    if item_count < 0 or item_count > 127:
        raise ValueError("item_count must fit a signed Java byte")
    writer = PacketWriter()
    writer.write_byte(3)
    writer.write_byte(item_count)
    return writer.to_bytes()


_FALLBACK_ITEM_IMAGE = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000d000000050203000000e3d68e82"
    "00000009504c5445ffffffff0000ffffff9a2b24830000000174524e530040e6d866"
    "0000002249444154785e15c8310d00000c02c1975e130c18604065c37639da1e960e"
    "3953d8f191e50ae8dd81b3470000000049454e44ae426082"
)


def _write_item_image(writer: PacketWriter, image_data: bytes) -> None:
    """Write the ``short length + PNG bytes`` consumed by ``hm.a(is)``."""
    image = image_data or _FALLBACK_ITEM_IMAGE
    if len(image) > 32767:
        raise ValueError("inventory image blob must fit a signed Java short")
    writer.write_short(len(image))
    writer.write_bytes(image)


def _write_shop_record(writer: PacketWriter, item: InventoryItem) -> None:
    """Write one item body in the JAR ``so.w`` shop constructor order."""
    kind = item.kind
    if kind == 0:  # fe / Quanao; shop constructor fixes highlighted=false
        writer.write_short(item.item_id)
        writer.write_short(item.detail_id)
        writer.write_utf(item.name)
        writer.write_byte(item.subtype)
        writer.write_byte(item.icon_type)
        writer.write_utf(item.label)
        writer.write_short(item.detail_short)
        writer.write_byte(item.growth_count)
    elif kind == 1:  # td / Hatgiong
        writer.write_short(item.item_id)
        writer.write_utf(item.name)
        writer.write_byte(item.subtype)
        writer.write_byte(item.icon_type)
        writer.write_utf(item.label)
        writer.write_byte(item.growth_count)
        writer.write_byte(item.stack_value)
        writer.write_short(item.required_level)
        writer.write_byte(item.stars)
        writer.write_byte(item.quantity)
    elif kind in (2, 6):  # se / Monan, mx / ICa
        writer.write_short(item.item_id)
        writer.write_utf(item.name)
        writer.write_utf(item.description)
        writer.write_byte(item.value_byte_a)
        writer.write_byte(item.value_byte_b)
        _write_item_image(writer, item.image_data)
    elif kind == 3:  # in / Nongsan
        writer.write_short(item.item_id)
        writer.write_utf(item.name)
        writer.write_utf(item.description)
        writer.write_byte(item.value_byte_a)
        writer.write_byte(item.value_byte_b)
    elif kind == 4:  # rz / Items
        writer.write_short(item.item_id)
        writer.write_utf(item.name)
        writer.write_byte(item.subtype)
        writer.write_utf(item.description)
        writer.write_byte(item.value_byte_a)
        writer.write_byte(item.value_byte_b)
        _write_item_image(writer, item.image_data)
        writer.write_short(item.extra_short)
    else:
        raise ValueError(f"unsupported JAR shop record type: {kind}")


def _write_inventory_record(writer: PacketWriter, item: InventoryItem) -> None:
    """Write one record after its slot and type bytes, in ``so.H`` order."""
    kind = item.kind
    if kind == 0:  # fe / Quanao
        writer.write_short(item.item_id)
        writer.write_short(item.detail_id)
        writer.write_utf(item.name)
        writer.write_byte(item.subtype)
        writer.write_byte(item.icon_type)
        writer.write_utf(item.label)
        writer.write_short(item.detail_short)
        writer.write_byte(item.growth_count)
        writer.write_boolean(item.highlighted)
    elif kind == 1:  # td / Hatgiong
        writer.write_short(item.item_id)
        writer.write_utf(item.name)
        writer.write_byte(item.subtype)
        writer.write_byte(item.icon_type)
        writer.write_utf(item.label)
        writer.write_byte(item.growth_count)
        writer.write_byte(item.stack_value)
        writer.write_short(item.required_level)
        writer.write_byte(item.stars)
        writer.write_byte(item.quantity)
        writer.write_boolean(item.highlighted)
    elif kind in (2, 6):  # se / Monan, mx / ICa
        writer.write_short(item.item_id)
        writer.write_utf(item.name)
        writer.write_utf(item.description)
        writer.write_byte(item.value_byte_a)
        writer.write_byte(item.value_byte_b)
        writer.write_boolean(item.value_flag)
        _write_item_image(writer, item.image_data)
    elif kind == 3:  # in / Nongsan
        writer.write_short(item.item_id)
        writer.write_utf(item.name)
        writer.write_utf(item.description)
        writer.write_byte(item.value_byte_a)
        writer.write_byte(item.value_byte_b)
        writer.write_boolean(item.value_flag)
    elif kind == 4:  # rz / Items
        writer.write_short(item.item_id)
        writer.write_utf(item.name)
        writer.write_byte(item.subtype)
        writer.write_utf(item.description)
        writer.write_byte(item.value_byte_a)
        writer.write_byte(item.value_byte_b)
        writer.write_boolean(item.value_flag)
        _write_item_image(writer, item.image_data)
        writer.write_short(item.extra_short)
    else:
        raise ValueError(f"unsupported JAR/APK inventory record type: {kind}")


def encode_inventory_snapshot(items: list[InventoryItem]) -> bytes:
    """Encode inbound -6 case 0 while preserving client slot indices.

    The client clears every existing entry before applying records. Empty
    server-side tombstones are therefore intentionally omitted, but their
    positions are retained by emitting the original slot number for every
    non-empty record. This prevents a consumed slot from shifting later items.
    """
    if len(items) > 127:
        raise ValueError("inventory snapshot cannot contain more than 127 slots")
    writer = PacketWriter()
    writer.write_byte(0)
    for slot, item in enumerate(items):
        if item.quantity <= 0:
            continue
        writer.write_byte(slot)
        writer.write_byte(item.kind)
        _write_inventory_record(writer, item)
    return writer.to_bytes()


def encode_inventory_snapshot_empty() -> bytes:
    """Encode a full empty main-bag snapshot."""
    return encode_inventory_snapshot([])


def encode_inventory_harvest_reward(slot: int, item: InventoryItem, exp: int, timer: int, stars: int) -> bytes:
    """Encode inbound -6/4, the JAR's harvest reward and crop update packet."""
    if item.kind != 3:
        raise ValueError("harvest reward must be a Nongsan (kind 3) item")
    writer = PacketWriter()
    writer.write_byte(4)
    writer.write_byte(slot)
    writer.write_short(item.item_id)
    writer.write_utf(item.name)
    writer.write_utf(item.description)
    writer.write_byte(item.value_byte_a)
    writer.write_byte(item.value_byte_b)
    writer.write_boolean(item.value_flag)
    writer.write_int(exp)
    writer.write_short(timer)
    writer.write_byte(stars)
    return writer.to_bytes()


def encode_character_delta_gold(gold: int) -> bytes:
    writer = PacketWriter()
    writer.write_byte(3)
    writer.write_int(gold)
    return writer.to_bytes()


def encode_position(entity_id: int, position: int) -> bytes:
    writer = PacketWriter()
    writer.write_int(entity_id)
    writer.write_short(position)
    return writer.to_bytes()
