# Voice Annotator Bridge (Zotero plugin)

A bootstrap plugin that adds three endpoints to Zotero's local HTTP server
(`http://localhost:23119`). The Python client in `src/annotator/zotero.py`
consumes them.

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| GET | `/voiceannotator/current` | – | `{key, title, url, year, firstCreator}` |
| POST | `/voiceannotator/highlight` | `{text, comment}` | `{annotationKey}` |
| POST | `/voiceannotator/delete` | `{key}` | `{ok: true}` |

Errors return HTTP 500 with a plain-text message.

## Build

```bash
cd zotero-plugin && zip -r ../voice-annotator.xpi manifest.json bootstrap.js
```

## Install

Normal install: Tools -> Plugins -> gear -> Install Plugin From File, then
restart Zotero.

Headless dev install (what this task used):

1. Quit Zotero.
2. Create `<profile>/extensions/` if it does not exist. On macOS the profile is
   `~/Library/Application Support/Zotero/Profiles/<random>.default`.
3. Write a pointer file named exactly `voice-annotator@kaustubh.local` whose
   single line is the absolute path of this `zotero-plugin` directory. A copy of
   `voice-annotator@kaustubh.local.xpi` works too.
4. Zotero ships two prefs that block this by default (see
   `defaults/preferences/zotero.js:22-23` in `omni.ja`):
   `extensions.startupScanScopes` is `0`, so the profile extensions directory is
   never scanned, and `extensions.autoDisableScopes` is `15`, so anything found
   there is installed disabled. Set `extensions.startupScanScopes` to `1` and
   `extensions.autoDisableScopes` to `0` in `prefs.js` for the install run, then
   remove both lines afterwards. The plugin stays installed and enabled.
5. Start Zotero: `open -a Zotero --args -purgecaches`.

If a scan already recorded the plugin as `enabled: false` (for example after a
failed manifest parse), delete `addonStartup.json.lz4` and `extensions.json`
from the profile before the next start. Otherwise
`XPIDatabase.sys.mjs:3984-4001` restores the stale disabled state and marks the
plugin `userDisabled`.

## Research findings

Verified against the installed Zotero 9.0.6 at
`/Applications/Zotero.app`. Two archives were extracted and read:
the app archive `Contents/Resources/app/omni.ja` (Zotero's own code, prefix
`app:` below) and the platform archive `Contents/Resources/omni.ja`
(Gecko/AddonManager, prefix `gre:`).

### Manifest requirements — the brief's manifest was rejected

`gre:modules/Extension.sys.mjs:1870-1878` makes three manifest keys mandatory
for a Zotero extension:

```js
if (!manifest.applications?.zotero?.id) {
  this.manifestError("applications.zotero.id not provided");
}
if (!manifest.applications?.zotero?.update_url) {
  this.manifestError("applications.zotero.update_url not provided");
}
if (!manifest.applications?.zotero?.strict_max_version) {
  this.manifestError("applications.zotero.strict_max_version not provided");
}
```

The check is truthiness, so the brief's `"update_url": ""` fails exactly like a
missing key. A failed manifest parse is silent from the outside: the plugin
appears in `addonStartup.json.lz4` with no version and never reaches the add-on
database. `manifest.json` now carries a dummy `update_url` on the `.invalid`
TLD, which never resolves, so no update check can reach a real host.

`gre:modules/addons/XPIInstall.sys.mjs:492-497` also rejects a `*` inside
`strict_min_version`, and `applications.zotero` survives schema normalization
only because `DeprecatedApplications` in
`gre:chrome/toolkit/content/extensions/schemas/manifest.json` sets
`"additionalProperties": {"type": "any"}`.

### Endpoint registration — brief confirmed correct

`app:chrome/content/zotero/xpcom/server/server.js:342-343` looks the path up in
`Zotero.Server.Endpoints` (declared at `server.js:652`), and
`server.js:394` does `new this.endpoint()`, so each value must be a constructor
whose prototype supplies `supportedMethods`, `supportedDataTypes` and `init`.
`server.js:459-484` dispatches on `endpoint.init.length`: a one-argument `init`
receives `{method, pathname, pathParams, searchParams, headers, data}` and
returns `[status, contentType, body]` or a promise for it. `server.js:430-436`
parses `application/json` bodies into `data`. `server.js:397-416` rejects
requests that look like they came from a web page, which is why a `Mozilla/`
user-agent or an `Origin` header would be blocked; curl and httpx are fine.

### Reader lookup — brief mostly correct

`Zotero.Reader._readers` is real (`app:xpcom/reader.js:2459`, pushed at
`reader.js:2753`), and `Zotero.Reader.getByTabID` exists at `reader.js:2676`.
`bootstrap.js` prefers the reader in the selected tab and falls back to the
newest reader. `reader.itemID` (`reader.js:686`) is the **attachment** item id;
`item.parentItem` gives the bibliographic item.

### Text lookup and position — brief was wrong, replaced

There is no `findInDocument`. The reader runs in a content-principal iframe;
`reader._internalReader` is the raw content-side `Reader` instance created at
`reader.js:220`, and chrome code must marshal objects across the boundary
(`reader.js:714` uses `Components.utils.cloneInto`). `bootstrap.js` uses a JSON
round-trip through the iframe's own `JSON` object, which needs no extra
sandbox globals.

The working primitive is the reader's own find machinery:

- `app:resource/reader/reader.js:73593` — `Reader._updateState(state)`. Setting
  `primaryViewFindState` to a new object makes `_updateState` (line 73717) call
  `this._primaryView.setFindState(...)`, the same path the find popup uses. The
  full state shape is at `reader.js:73321`:
  `{popupOpen, active, query, highlightAll, caseSensitive, entireWord, index, result}`.
- `app:resource/reader/reader.js:68999` — `PDFView.setFindState`. It
  short-circuits when the query is unchanged, so `bootstrap.js` writes an
  inactive state first and the active state second.
- `app:resource/reader/reader.js:68106-68180` — the find controller callbacks
  build `result.annotation` with
  `this._getAnnotationFromSelectionRanges(selectionRanges, 'highlight')`. The
  comment in the source warns that this happens **after** the result object is
  emitted, so the code polls `result.annotation` rather than reading it once.
- `app:resource/reader/reader.js:70462-70484` —
  `_getAnnotationFromSelectionRanges` returns
  `{type, color, sortIndex, pageLabel, position, text}`, and `position` is
  `{pageIndex, rects[, nextPageRects]}`. That is the real position shape; the
  brief's placeholder `"00000|000000|00000"` sort index is not needed because
  the reader computes a correct one (`getSortIndex`, `reader.js:38860`).
- EPUB and snapshot views produce the same `result.annotation` shape
  (`app:resource/reader/reader.js:62279`), so the code is not PDF-only in
  principle, though only PDF was tested.

### Annotation creation — brief replaced with the documented API

Rather than hand-building a `Zotero.Item('annotation')`, `bootstrap.js` calls
`Zotero.Annotations.saveFromJSON(attachment, json)`
(`app:xpcom/annotations.js:199-250`), which is what the reader itself uses when
the user drags a highlight (`app:xpcom/reader.js:297`). It requires
`json.key`; `Zotero.DataObjectUtilities.generateKey()`
(`app:xpcom/data/dataObjectUtilities.js:72`) supplies one. It is awaited, so
the returned item's key is safe to hand back immediately, and the reader picks
the new annotation up through the notifier (`app:xpcom/reader.js:2620-2670`).
The default highlight colour is `Zotero.Annotations.DEFAULT_COLOR`
(`app:xpcom/annotations.js:38`, `#ffd400`).

`reader.navigate({position})` (`app:xpcom/reader.js:713`) scrolls the view to
the new highlight and does its own `cloneInto`.

## Manual test checklist

Run against Zotero 9.0.6 on 2026-08-02, with
"The Economics of Recursive Self-Improvement" open in a reader tab.

- [x] `GET /voiceannotator/current` with a PDF open. Returned
  `{"key":"RLTTLK9V","title":"The Economics of Recursive Self-Improvement","url":"","year":"","firstCreator":"Cunningham et al."}`.
  `url` and `year` are empty because that item has no URL, DOI or date.
- [ ] `GET /voiceannotator/current` with no reader open. **Not run.** It needs
  the user's reader tab closed, and the task forbids changing their open tabs.
  The 500 path itself is proven by the not-found case below.
- [x] `POST /voiceannotator/highlight` with an exact sentence. Returned
  `{"annotationKey":"RML7UFNJ"}`. The database write confirms real geometry:
  `REPLACE INTO itemAnnotations (...) VALUES [70, 68, 1, 'We model the economics of recursive self-improvement', 'smoke test from task 9', '#ffd400', '1', '00000|000171|00325', '{"pageIndex":0,"rects":[[117.629,455.484,409.073,466.985]]}', 0]`.
  Page label, sort index, colour, comment and rects are all correct.
- [ ] "View scrolls to the highlight." **Not visually confirmed** — no GUI
  access. `reader.navigate()` ran without error, and errors there are logged.
- [x] Repeat requests. The same sentence twice, then a different sentence, each
  produced a distinct key (`YYJLC555`, `QZ5M3XSG`). The find-state reset works.
- [x] Text that is absent. Returned `500` with body `text not found in document`.
- [x] `POST /voiceannotator/delete` with each key. Returned `200 {"ok": true}`,
  and the log shows `DELETE FROM items WHERE itemID=?` for items 70, 71 and 72.
- [x] Delete with an unknown key. Returned `200` (no-op), which matches the
  Python client's expectation.
- [x] The plugin survives restoring the two install prefs to their defaults and
  a plain `open -a Zotero`.
- [x] End-to-end through the real client:
  `ZoteroClient().current_item()`, `.create_highlight(...)`, `.delete_annotation(...)`
  all succeeded.

## Known gap outside this plugin

`ZoteroClient.fulltext()` calls `/api/users/0/items/{key}/fulltext`. That
endpoint currently answers `403 Local API is not enabled`. The user must turn on
Settings -> Advanced -> "Allow other applications on this computer to
communicate with Zotero". Note also that `/voiceannotator/current` returns the
**parent** item key, while the local API's fulltext endpoint expects the
**attachment** key.
