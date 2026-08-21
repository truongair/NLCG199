# Debug note: bootstrap/map renderer crash

## Observed log

The client completed the transport sequence and decoded `-27`, then logged `onMessage ERROR=-1`, `onMessage ERROR=-2`, and finally repeated `ArithmeticException: / by zero` from the renderer.

## Diagnosis

The original server skeleton emitted an empty optional entity array in `-1` and a zero-length plot array in `-2`:

```text
-1: slot/entity sizing = 0
-2: plot count = 0
```

The client’s `so` handler calls `io.f(io.au.length)` during `-1`; later rendering assumes a valid first entity/plot slot. The `-2` handler creates `fi.p = new je[plotCount]`, and the renderer/map-object path can reach calculations using `fi.b` and plot indices before the world state is fully populated. The first implementation therefore exposed an invalid “empty world” state even though the frame codec and XOR handshake were correct.

## Fix applied

The Python encoder now guarantees:

| Response | Minimum state |
|---|---|
| `-1` bootstrap | character slot/entity capacity at least `1` |
| `-2` snapshot | one inert plot with state `0`, even if caller passes an empty list |
| `-8` handoff | valid map id/type/name and zero nearby entities |

The map type remains `0`, which matches the embedded `data/map0` resource observed in the client. The fix is intentionally conservative: it prevents zero-length arrays but does not yet fabricate full farm/entity records.

## Verification

The Python test suite passes **13 tests**, including an end-to-end handshake/login/bootstrap flow. Please restart the server and rerun the Java ME client from a fresh client session so stale renderer state from the previous malformed packets is not reused.

If the next run still reports `onMessage ERROR=-1` or `-2`, capture the first exception stack trace immediately after each `onMessage ERROR` and the exact `read/send` sequence; the next likely layer is a record-type/appearance schema mismatch rather than transport framing.

## Follow-up diagnosis from second client run

The second run no longer reports `onMessage ERROR=-1`, proving the nonzero bootstrap slot fix worked. It still reports `onMessage ERROR=-2` before the client loads `data/map0`. This establishes that the previous order was wrong: the server sent `-2` before inbound `-8` helper `L` initialized `fi.a` and map resources. The server has now been changed to send:

```text
-1 bootstrap
-8 world handoff / map initialization
-2 farm snapshot
```

The integration test now asserts this order.

## Follow-up diagnosis from the third client run

The client now receives `-8` before `-2`, loads `data/map0`, and the `-1` error is gone. The remaining `onMessage ERROR=-2` occurs immediately after `userIDFarm=1, userID=56366`.

The exact parser order in `so.java` is:

```text
int farmId
UTF farmName
byte plantMetadataCount
repeat plant metadata records
byte plotCount
repeat plot records
boolean io.bo
boolean io.aE
boolean io.aF
byte dynamicNpcCount
repeat dynamic NPC records
boolean rg.a
```

The server omitted `plantMetadataCount`, so the client interpreted plot count `1` as a plant-metadata count, then interpreted the plot state as the plot count and eventually read beyond the payload. The encoder now inserts `byte 0` before the plot count. The test suite remains green with 13 tests passed.

## Follow-up diagnosis from the fourth client run

The corrected `-2` packet is now accepted: the log has no `onMessage ERROR=-2`. The remaining ArithmeticException is caused by the login HUD fields, not the map tile size. In `so.java` command `-1`, the two shorts after `q/x` populate `io.am/io.an`, and the next two ints populate `io.aj/io.ak`. `io.paint` computes `am * 38 / an` and `aj * 52 / ak`. The previous encoder wrote world `x/y` into the two shorts and zeros into the int fields, leaving `io.ak == 0`.

The encoder now writes positive HUD current/max values (`100/100`) and a positive `io.ak` fallback (`resource >= 1`). World x/y remain exclusively in `-8`.

Movement was also blocked independently: `sq.e()` sends a single short per `-52` packet and refuses to send while `io.u.size() == 0`. The `-8` handoff now includes one valid nearby `K` entity, making `io.u` nonempty. The server accepts the actual one-short `-52` request form and updates x or y without expecting a four-byte pair.
