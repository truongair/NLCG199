# NLCG119 Python Server v0.17 — Local Player Visibility After Map Transition

## Diagnosis

The JAR parser `so.L(is)` uses the first two shorts of S→C `-8` as `pu.d().am` and `pu.d().an`, the local player’s render coordinates. After `io.aN()` tears down the old world, `L(is)` resets the gameplay screen with `io.aU()` and immediately renders the local player at those two coordinates.

The previous server reused the character’s last coordinates for every destination map. A coordinate valid in the source map can be outside the destination map or inside a destination `fi.h` trigger. The JAR’s render/collision code then clamps or transitions the player again, which can make the character appear to disappear after the map itself has changed.

## Fix

The server now has safe interior spawn coordinates per map mode and applies them only after an explicit C→S `-8` map transition. Login preserves the persisted character coordinates. The transition spawn is also persisted through `save_character`, so reconnecting does not immediately restore the invalid source-map coordinate.

Map transitions now use these default spawn points:

```text
map0   (120,216)     map1   (960,264)
map2   (432,552)     map3   (480,264)
map4   (240,384)     map5   (120,216)
map6   (216,192)     map7   (360,240)
map8   (360,384)     map9   (216,192)
map10  (960,168)     map11  (324,216)
map12  (168,192)     map13  (120,168)
map14  (360,264)     map15  (552,192)
map100 (360,240)
```

The points are kept away from map edges and all decoded transition trigger rectangles. They are configuration values and can later be replaced with exact directional spawn points once server-side map direction semantics are fully reconstructed.

## Existing protocol behavior retained

The server still sends `-8` before `-2`. Login sends the inventory/currency baseline after the map bootstrap; a later map transition does not resend those frames. Static map-object metadata remains map-aware, and only real authenticated nearby players are placed in K records. No fake visible entity is created.

Inbound `-52` movement updates continue to update the changed x or y axis and are persisted in the character row. With one client on farm-like maps, the JAR may still suppress `-52` locally when `io.u` is empty; that is a separate client-side gate.

## Validation

The complete suite passes:

```text
Ran 42 tests in 0.628s
OK
```

New integration coverage verifies that transition to map1 sends spawn `(960,264)`, sends map1 metadata without the map0 vending record, emits a zero-plot non-farm snapshot, and does not send duplicate inventory/currency frames.

## Real-client test

After installing this build, transition from map0 to map1 and inspect the first two response frames:

```text
S→C -8: first shorts should be 960, 264 for target map1
S→C -2: map mode should be 1, plot count should be 0
```

The character should be visible inside map1. Returning to map0 should receive the configured map0 spawn `(120,216)` and map0 static vending metadata ID 21.

## Archive

`NLCG119-python-server-v0.17-player-visibility.zip`

SHA-256 is generated after packaging.
