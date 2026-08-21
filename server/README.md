# NLCG119 Python Server

Đây là server Python thử nghiệm tương thích với client `NLCG119-TI.jar`, được xây dựng lại từ source decompile của client. Bản hiện tại tập trung vào **TCP framing**, **handshake `-27`**, **rolling XOR stateful**, **Java modified UTF**, và state machine login thực tế gồm **no-character `-1` → create `-5` → existing-character `-1` → world handoff `-8`**.

> Mã nguồn này chỉ triển khai protocol tương thích cho hệ thống mà người dùng có quyền vận hành. Nó không bao gồm cơ chế vượt DRM, vượt xác thực hoặc truy cập máy chủ không được phép.

## Kiến trúc giai đoạn đầu

```text
nlcg119_server/
  codec.py       Java DataInput/DataOutput primitives, frame codec, XOR cursor
  model.py       Session, account, character, map/world state
  protocol.py    command constants, packet schemas, response encoders
  handlers.py    handshake/login/character/map/shop dispatch
  server.py      asyncio TCP accept loop and per-client lifecycle
  main.py        CLI entry point

tests/
  test_codec.py
  test_protocol.py
```

## Wire assumptions

Mỗi frame có dạng `command: 1 byte | length: 2 byte big-endian | payload: N bytes`. Trước handshake, frame plaintext. Client gửi `-27` với payload rỗng; server trả `-27` với `keyLength: 1 byte` và raw key bytes. Client biến đổi key theo cumulative XOR, sau đó bật XOR cho cả command, hai byte length và payload.

Sau handshake, hai chiều sử dụng cursor độc lập. Cursor không reset giữa các packet và wrap theo độ dài key:

```text
encodedByte = key[cursor] XOR plainByte
cursor = (cursor + 1) mod len(key)
```

`DataOutputStream.writeUTF` dùng Java modified UTF-8 và prefix length 2 byte. Codec sẽ triển khai tương thích cho các string thông thường và kiểm tra giới hạn 65.535 byte.

## State machine dự kiến

| Server state | Chấp nhận | Gửi |
|---|---|---|
| `CONNECTED` | `-27` plaintext | `-27` handshake |
| `HANDSHAKE_DONE` | `-1` login | no-character `-1` hoặc existing-character `-1` |
| `AUTHENTICATED` without character | `-5` | không gửi `-8`/`-2` trước khi tạo nhân vật |
| `CHARACTER_SELECTED` | `-8` và gameplay actions | world handoff `-8`, farm snapshot `-2` |
| `IN_WORLD` | movement/action commands | chỉ gửi response có schema client-derived |

> Cùng một numeric opcode có thể có schema khác nhau theo hướng truyền. Ví dụ, client gửi `-1` là login request, còn server gửi `-1` là character bootstrap; client gửi `-8` là map request, còn server gửi `-8` là world handoff. Không được dùng chung encoder cho hai hướng.

## Giới hạn hiện tại

JAR chỉ chứa client; server cũ, database và golden packets không có trong artifact. Vì vậy, các response lớn như `-2` farm snapshot và các helper `L/K` vẫn cần kiểm thử với client thực tế trước khi coi là hoàn chỉnh. Bản hiện tại đã tách rõ hai nhánh `-1`: `encode_no_character_bootstrap()` ghi `w=-1` và sáu short selection; `encode_login_bootstrap()` chỉ dành cho existing character. Account storage vẫn là in-memory demo; không dùng cho production.

## Chạy kiểm thử

Từ thư mục `server`:

```bash
python3 -m unittest discover -s tests -v
```

## Chạy server thử nghiệm

```bash
PYTHONPATH=src python3 -m nlcg119_server.main --host 0.0.0.0 --port 9001
```

Mặc định server chỉ nên bind localhost trong môi trường phát triển. Không mở cổng Internet trước khi bổ sung authentication, persistence, rate limiting, logging policy và golden-packet validation.


## Gameplay opcodes implemented

The server now applies validated state mutations for the JAR outbound item-action family `-10` and farm-action family `-4`. Item actions support use (`0`), drop (`1`), unequip (`2`), transfers between pocket/warehouse/equipment (`3`), ground-item pickup (`4`), and expiry renewal (`6`). Successful operations persist the character's pocket, warehouse, equipment, expiry fields, and ground-item list; the server emits only the corresponding client-parsable `-10`, `-6`, and `-11` responses.

Farm actions support cultivation/clearing (`0`), watering (`1`), sowing (`2`), fertilizing (`3`), harvesting (`4`), and crop destruction (`5`). The handler validates plot indices, item kinds, quantities, capacity, crop maturity, and available health before mutation. Harvesting creates a `Nongsan` reward through the exact `-6/4` reward packet, updates absolute EXP, and sends the corresponding `-4/4` crop reset. Farm plot, fertilizer, crop timer, NPC, and ground-item state are persisted through SQLite.

The JAR movement writer `sq.e()` sends C→S `-52` as one signed short: a positive `x` value when x changed, or `-y` when y changed. On farm-like map modes (`0`, `4`, `6`, `7`, `9`, `11`) it deliberately returns without writing a packet when `io.u.size()==0`. `io.u` contains only remote `pu` records created from the K-record section of the preceding `-8` world handoff; the local player is not inserted into `io.u`. Therefore a single-player server handoff with K-count zero causes the client itself to suppress movement uploads. The server does not fabricate a shadow character. When other authenticated sessions are actually online on the same map, their real characters are encoded as JAR-compatible K records, allowing the client movement writer to activate without a duplicate fake entity. The server already accepts a genuine inbound `-52` and updates the corresponding x/y axis.

The C→S `-8` map request is now parsed instead of ignored. Targets `0`, `4`, `6`, and `9` consume an owner integer; target `11` consumes a destination integer; other supported target modes consume only the map byte. The response handoff updates the map mode and preserves the farm-owner field separately from the logical map ID. The extracted `data/map0` trigger table confirms that map transitions are driven locally by `fi.h` rectangles, with destination codes such as `1`, `2`, `4`, `5`, and `6`; the server only receives `-8` after the client has selected the transition.

The bootstrap now follows the JAR lifecycle: S→C `-8` is sent first, then a map-aware `-2` snapshot. Login/character creation additionally sends initial inventory and currency frames; later map transitions do not resend the bag/HUD baseline. Farm-like modes (`0,4,6,7,9,11`) retain farm plots/animals/ground objects, while town/special modes receive a valid zero-plot `-2` shape instead of inherited farm state. Static `ua` metadata is selected by map mode; the verified map0 vending object is no longer emitted on unrelated maps.

The farm seed/fertilizer vending machine is the static `data/map0` ua object with ID `21`, not the separate free-trade/market flow. Its `ua.b()` fallback sends C→S `-9` with payload `byte subcase=0, byte objectID=21`; the server replies with S→C `-9` case 0 as parsed by JAR `so.G`: shop title, offer count, type-specific records, and price/currency fields. The `-8` handoff includes metadata for the existing map object so `ua.d=true` makes it selectable without creating a fake entity. The default catalog contains carrot seed and fertilizer offers and can be replaced through `ServerConfig.vending_shop`. The separate JAR `-22` path remains available for its own ID-0 menu flow.

Invalid payloads, unavailable slots, insufficient quantities, full inventory, immature crops, and unsupported subcommands are logged and ignored without synthetic error frames. This preserves the client's rolling-XOR stream and follows the JAR-first requirement that an unknown response must not be invented.

The regression suite currently covers codec, protocol, SQLite restart persistence, item mutations, farm lifecycle mutations, exact harvest reward framing, JAR -9 NPC-shop serialization, -8 static vending-object metadata, exact so.K nearby-player records, target-zero map transitions, map-aware handoff sequencing, vending-machine open integration, and unsupported-command behavior.
