# Báo cáo mô phỏng người chơi NLCG119

**Ngày kiểm thử:** 21 tháng 8 năm 2026  
**Server:** NLCG119 Python v0.17  
**Client:** NLCG119-TI Java ME CLDC/MIDP  
**Emulator:** FreeJ2ME-Plus với TCP `SocketConnection` adapter

## Kết quả tổng quan

Phiên mô phỏng đã kết nối player bot tới server TCP thật trên port `9011`, sau đó thực hiện các luồng login, farm, inventory, currency, NPC vending machine, shop và chuyển map. Toàn bộ chuỗi kiểm thử protocol hoàn tất thành công. Regression suite hiện tại đạt **42/42 tests passed**.

| Luồng | Kết quả | Packet/ghi chú |
|---|---:|---|
| Handshake và login | PASS | `-27`, `-1` |
| World/map bootstrap | PASS | `-8`, `-2` |
| Inventory và currency | PASS | `-6`, `-11` |
| Sow seed | PASS | request `-4`; seed giảm đúng |
| Fertilize | PASS | `-4` và health `-11`; fertilizer giảm đúng |
| Water | PASS | `-4` và health `-11` |
| Harvest crop mature | PASS | `-4` và reward `-6` |
| Destroy crop | PASS | `-4` và health `-11` |
| NPC vending machine | PASS | request `-9 [0,21]`, response `-9` |
| Shop catalog | PASS | request `-22 [0,false]`, response `-22` |
| Map transition | PASS | `map0 → map1 → map0`, mỗi chiều nhận `-8/-2` |
| Persistence/reconnect | PASS | inventory và plot state được lưu lại |

## Packet evidence

Bootstrap của một player có character trả về các frame theo thứ tự:

```text
-1 payload=58
-8 payload=54
-2 payload=56
-6 payload=2
-6 payload=178
-11 payload=5
-11 payload=5
```

Farm lifecycle đã nhận được:

```text
sow:       -4 payload=20
fertilize: -4 payload=14, -11 payload=4
water:     -4 payload=6,  -11 payload=4
harvest:   -4 payload=9,  -6 payload=22
destroy:   -4 payload=6,  -11 payload=4
```

NPC và shop đã nhận được:

```text
NPC vending machine object 21: -9 payload=275
Shop catalog tab 0:             -22 payload=261
```

Chuyển map đã nhận được:

```text
map0 → map1: -8 payload=17, -2 payload=16
map1 → map0: -8 payload=54, -2 payload=43
```

## Vấn đề phát hiện và xử lý

Trong lần chạy đầu, một phiên JAR cũ còn giữ kết nối và ghi đè database khi đóng. Sau khi cô lập các session, nguyên nhân thứ hai được xác định là fixture test chứa các field không thuộc `PlotState`. `load_farm()` do đó fallback về plot mặc định duy nhất, khiến bot gửi harvest tới plot không tồn tại và chờ response vô thời hạn.

Fixture đã được sửa để chỉ dùng đúng field của `PlotState`; bot cũng được bổ sung timeout và chỉ thực hiện harvest trên plot đã mature. Sau khi restart server để loại cache account cũ, toàn bộ chuỗi farm chạy thành công. Đây là lỗi của test fixture/session isolation, không phải lỗi wire protocol của server.

Movement trong farm đơn không tạo `-52` vì JAR chỉ gửi position khi vector nearby/K-record phù hợp tồn tại. Đây là movement gate đã được xác nhận từ client JAR, không được thay đổi thành entity giả.

## Cách chạy lại

Từ thư mục server, khởi động server:

```bash
PYTHONPATH=src python3 -m nlcg119_server.main \
  --host 0.0.0.0 --port 9011 --database /tmp/nlcg199-player.sqlite \
  --log-level DEBUG
```

Sau đó chạy các bot trong `tools/player_simulation/` theo thứ tự mong muốn. Các bot yêu cầu account `smokeuser`, password `pw` và character đã tồn tại. Script `seed_player_gameplay_state.py` tạo fixture inventory/farm cho database test riêng; không dùng database production.

`NLCG119-TI-localhost.jar` là bản tùy chọn đã đổi server profile sang `127.0.0.1`. JAR gốc `NLCG119-TI.jar` vẫn được giữ nguyên; với FreeJ2ME, có thể dùng RMS server-list tương ứng để route endpoint mà không patch bytecode.
