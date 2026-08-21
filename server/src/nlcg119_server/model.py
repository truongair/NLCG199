"""Authoritative server-side state models for the first protocol slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SessionState(str, Enum):
    CONNECTED = "connected"
    HANDSHAKE_DONE = "handshake_done"
    AUTHENTICATED = "authenticated"
    CHARACTER_SELECTED = "character_selected"
    MAP_LOADING = "map_loading"
    IN_WORLD = "in_world"
    CLOSED = "closed"


@dataclass
class Account:
    username: str
    password: str
    provider: str = "UNKNOW"
    # A successful login does not imply that a playable character exists.
    # The client explicitly uses inbound -1 with w=-1 to enter creation UI.
    character: Optional["CharacterState"] = None


@dataclass
class InventoryItem:
    """Wire-neutral model for one ``-6/0`` main-bag record.

    The common fields map to the six JAR/APK constructors as follows:
    type 0=fe/Quanao, 1=td/Hatgiong, 2=se/Monan, 3=in/Nongsan,
    4=rz/Items, and 6=mx/ICa. Type-specific fields are intentionally
    optional/defaulted so existing type-1 starter records remain compatible.
    """
    kind: int = 1
    item_id: int = 0
    name: str = "Cà rốt"
    subtype: int = 0
    icon_type: int = 4
    label: str = "Hạt giống"
    growth_count: int = 1
    stack_value: int = 1
    required_level: int = 1
    stars: int = 1
    quantity: int = 1
    highlighted: bool = False
    # Types 0, 2, 3, 4, and 6 use a second descriptive UTF field.
    description: str = ""
    # Type 0 (fe/Quanao): short detail id, plus four byte/short fields.
    detail_id: int = 0
    detail_byte_a: int = 0
    detail_byte_b: int = 0
    detail_short: int = 0
    detail_byte_c: int = 0
    # Types 2/3/4/6 use two generic bytes and a boolean after their strings.
    value_byte_a: int = 0
    value_byte_b: int = 0
    value_flag: bool = False
    # Types 2, 4, and 6 carry a Java image blob (short length + bytes).
    image_data: bytes = b""
    # Type 4 (rz/Items) has one additional short named hsd in the APK.
    extra_short: int = 0
    # Type 0/type 4 renewal responses (-10/6) update this short-valued field.
    expiry_short: int = 0


@dataclass(frozen=True)
class MapObjectMetadata:
    """Server-supplied appearance/name data for an existing static ``ua`` map object."""

    object_id: int
    name: str = ""
    sprite_a: int = -1
    sprite_b: int = -1
    sprite_c: int = -1
    collision_size: int = 10
    chat: str = ""


@dataclass(frozen=True)
class ShopOffer:
    """One item offered by the JAR vending-machine catalog.

    ``auxiliary_value`` is the first int stored by the JAR in ``io.az``. The
    current client does not render it, but it remains part of the wire contract.
    ``price`` and ``currency`` are the values applied through ``rh.a(int,byte)``.
    """

    item: InventoryItem
    auxiliary_value: int = 0
    price: int = 10
    currency: int = 0


@dataclass
class CharacterState:
    character_id: int
    name: str
    secondary_name: str = ""
    # The client calls io.f(io.au.length) after -1; a zero-length au array
    # reaches au[0] and fails. The minimal valid bootstrap therefore exposes
    # one character/entity slot.
    slot: int = 1
    level: int = 1
    # JAR pu defaults: q=-1 (APK Char.idRing), x=5 (APK Char.vDefault).
    kind: int = -1
    direction: int = 5
    x: int = 120
    # data/map0 collision plane marks (120,192) as blocked and (120,216) as walkable.
    y: int = 216
    # JAR io defaults: aj=10, ak=10, am=10, an=10.
    exp: int = 0
    max_exp: int = 10
    health: int = 10
    max_health: int = 10
    gold: int = 0
    premium: int = 0
    # JAR pu defaults: y=1, z=0, A=0, B=-1.
    appearance_y: int = 1
    appearance_z: int = 0
    appearance_a: int = 0
    appearance_b: int = -1
    state_u: int = 8
    state_w: int = 0
    state_q: int = 0
    # These are the three values submitted by the client in outbound -5:
    # gender/body state, birth day, and birth season.
    birth_day: int = 1
    birth_season: int = 0
    # Server-visible capacity and currently populated main-bag records.
    # The client keeps aB (capacity) separate from au.length (visible slots).
    inventory_capacity: int = 30
    inventory_items: list[InventoryItem] = field(default_factory=list)
    inventory_count: int = 0
    # The JAR exposes three item containers through -10/3: warehouse, pocket,
    # and costume/equipment. Keep them explicit instead of silently dropping
    # transfers that the client can request.
    storage_items: list[InventoryItem] = field(default_factory=list)
    equipment: dict[int, InventoryItem] = field(default_factory=dict)
    status: list[int] = field(default_factory=lambda: [0, 0, 0, 0])

    # Semantic aliases recovered from the Android APK. The underlying fields
    # remain available for compatibility with the earlier server revisions.
    @property
    def gender(self) -> int:
        return self.state_w

    @gender.setter
    def gender(self, value: int) -> None:
        self.state_w = value

    @property
    def id_ring(self) -> int:
        return self.kind

    @id_ring.setter
    def id_ring(self, value: int) -> None:
        self.kind = value

    @property
    def v_default(self) -> int:
        return self.direction

    @v_default.setter
    def v_default(self, value: int) -> None:
        self.direction = value

    @property
    def leg(self) -> int:
        return self.appearance_y

    @leg.setter
    def leg(self, value: int) -> None:
        self.appearance_y = value

    @property
    def body(self) -> int:
        return self.appearance_z

    @body.setter
    def body(self, value: int) -> None:
        self.appearance_z = value

    @property
    def hair(self) -> int:
        return self.appearance_a

    @hair.setter
    def hair(self, value: int) -> None:
        self.appearance_a = value

    @property
    def glasses(self) -> int:
        return self.appearance_b

    @glasses.setter
    def glasses(self, value: int) -> None:
        self.appearance_b = value

    @property
    def dina(self) -> int:
        return self.premium

    @dina.setter
    def dina(self, value: int) -> None:
        self.premium = value


@dataclass(frozen=True)
class NearbyPlayer:
    """One authenticated remote player encoded by the JAR ``so.K`` parser."""

    character: CharacterState


@dataclass
class PlantMetadata:
    """The five-field plant definition record prefixed to a JAR -2 snapshot."""

    plant_id: int
    growth_short_0: int = 0
    growth_short_1: int = 0
    growth_short_2: int = 0
    crop_type: int = 0


@dataclass
class AnimalState:
    """One JAR ``Vatnuoi`` header plus the conditional timer tail."""

    object_id: int = 0
    image_id: int = 0
    age_state: int = 0
    condition: int = 0
    sick: bool = False
    animal_type: int = 0
    index: int = 0
    death_timer: int = 0
    condition_timer: int = 0
    illness_timer: int = 0
    growth_timer: int = 0
    pregnancy_timer: int = 0
    production_timer: int = 0
    harvest_item_id: int = -1


@dataclass
class PlotState:
    index: int
    state: int = 0
    ready: bool = False
    timer: int = 0
    entity_type: int = -1
    entity_name: str = ""
    entity_state: int = 0
    entity_flag: int = 0
    entity_level: int = 0
    fertilized: bool = False


@dataclass
class GroundItem:
    object_id: int
    item: InventoryItem
    x: int = 0
    y: int = 0


@dataclass
class MapState:
    # ``-2`` starts with the farm owner's character ID, not the logical map ID.
    # A null value keeps standalone protocol fixtures backward-compatible; the
    # session sender supplies the authenticated character ID explicitly.
    farm_id: int | None = None
    map_id: int = 1
    map_type: int = 0
    name: str = "map"
    auxiliary: int = 0
    # The client later accesses the first plot during map rendering. Keep one
    # empty plot in the minimal snapshot instead of sending a zero-length array.
    plots: list[PlotState] = field(
        default_factory=lambda: [PlotState(index=0, state=1, ready=True, entity_type=-1)]
    )
    plant_metadata: list[PlantMetadata] = field(default_factory=list)
    npc_flags: list[tuple[int, int, int, int, bool, int, int]] = field(default_factory=list)
    animal_states: list[AnimalState] = field(default_factory=list)
    weather_flags: tuple[bool, bool, bool] = (False, False, False)
    map_tail_flag: bool = False
    ground_items: list[GroundItem] = field(default_factory=list)


@dataclass
class Session:
    reader: object
    writer: object
    peer: str
    state: SessionState = SessionState.CONNECTED
    xor_key: Optional[bytes] = None
    rx_cursor: object | None = None
    tx_cursor: object | None = None
    account: Optional[Account] = None
    character: Optional[CharacterState] = None
    map_state: MapState = field(default_factory=MapState)
    handshake_received: bool = False
    last_command: Optional[int] = None

    @property
    def authenticated(self) -> bool:
        # The client is authenticated even while it is on the no-character
        # creation screen; character existence is represented separately.
        return self.account is not None
