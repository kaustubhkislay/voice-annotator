// zotero-plugin/bootstrap.js
//
// Voice Annotator Bridge.
//
// Adds four endpoints to Zotero's local HTTP server (port 23119):
//   GET  /voiceannotator/current   -> {key, title, url, year, firstCreator}
//   GET  /voiceannotator/fulltext  -> {content, attachmentKey, parentKey}
//   POST /voiceannotator/highlight -> {annotationKey}
//   POST /voiceannotator/delete    -> {ok: true}
//
// See README.md for the source citations behind every reader internal used here.

var endpoints = {};

// Keep this below the Python client's 10s httpx timeout, so a slow find
// surfaces as a real 500 rather than a misleading "Is Zotero running?" error.
var FIND_TIMEOUT_MS = 8000;
var FIND_POLL_MS = 50;

function log(msg) {
  Zotero.debug("[voice-annotator] " + msg);
}

function sleep(ms) {
  return new Promise(function (resolve) {
    setTimeout(resolve, ms);
  });
}

// --- reader lookup -------------------------------------------------------

// Zotero.Reader._readers holds every open reader (reader.js:2459, 2753).
// Prefer the reader in the selected tab, then fall back to the newest reader.
function activeReader() {
  var reader = null;
  try {
    var win = Zotero.getMainWindow();
    if (win && win.Zotero_Tabs && win.Zotero_Tabs.selectedID) {
      reader = Zotero.Reader.getByTabID(win.Zotero_Tabs.selectedID);
    }
  } catch (e) {
    log("tab lookup failed: " + e);
  }
  if (!reader) {
    var readers = Zotero.Reader._readers || [];
    reader = readers[readers.length - 1];
  }
  if (!reader) throw new Error("No reader window open");
  return reader;
}

function readyReader() {
  var reader = activeReader();
  if (!reader._internalReader || !reader._iframeWindow) {
    throw new Error("Reader is still loading");
  }
  return reader;
}

// --- chrome <-> content object marshalling -------------------------------

// The reader runs in a content-principal iframe, so objects must cross the
// compartment boundary. reader.js does this with Components.utils.cloneInto
// (e.g. reader.js:714). A JSON round-trip through the iframe's own JSON object
// is equivalent for the plain data we exchange and needs no extra globals.
function intoContent(win, obj) {
  return win.wrappedJSObject.JSON.parse(JSON.stringify(obj));
}

function outOfContent(win, obj) {
  return JSON.parse(win.wrappedJSObject.JSON.stringify(obj));
}

// --- find-in-document ----------------------------------------------------

var INACTIVE_FIND_STATE = {
  popupOpen: false,
  active: false,
  query: "",
  highlightAll: true,
  caseSensitive: false,
  entireWord: false,
  index: null,
  result: null,
};

function setFindState(reader, state) {
  var internal = reader._internalReader;
  internal._updateState(
    intoContent(reader._iframeWindow, { primaryViewFindState: state })
  );
}

// Runs the reader's own find and returns the highlight annotation JSON that the
// find machinery builds for the first match:
//   {type, color, sortIndex, pageLabel, position, text}
async function findAnnotation(reader, text) {
  var internal = reader._internalReader;

  // Reset first so an identical repeat query still re-runs the search
  // (PDFView.setFindState short-circuits on an unchanged query).
  setFindState(reader, INACTIVE_FIND_STATE);

  setFindState(reader, {
    popupOpen: false,
    active: true,
    query: text,
    highlightAll: false,
    caseSensitive: false,
    entireWord: false,
    index: null,
    result: null,
  });

  var deadline = Date.now() + FIND_TIMEOUT_MS;
  var annotation = null;
  var lastResult = null;
  while (Date.now() < deadline) {
    var findState = internal._state.primaryViewFindState;
    var result = findState && findState.result;
    if (result) {
      lastResult = result;
      if (!result.total) break;
      // result.annotation is filled in asynchronously after the result object
      // is emitted, so poll for it rather than reading it once.
      if (result.annotation) {
        annotation = outOfContent(reader._iframeWindow, result.annotation);
        break;
      }
    }
    await sleep(FIND_POLL_MS);
  }

  setFindState(reader, INACTIVE_FIND_STATE);

  if (!annotation) {
    if (lastResult && !lastResult.total) {
      throw new Error("text not found in document");
    }
    throw new Error("timed out waiting for find results");
  }
  return annotation;
}

// --- endpoint registration ----------------------------------------------

function register(path, methods, handler) {
  endpoints[path] = function () {};
  endpoints[path].prototype = {
    supportedMethods: methods,
    supportedDataTypes: ["application/json"],
    // Zotero's server dispatches on init.length: a 1-arg init gets a request
    // object and returns [status, contentType, body] (server.js:459-484).
    init: async function (req) {
      try {
        var out = await handler((req && req.data) || {}, req || {});
        return [200, "application/json", JSON.stringify(out)];
      } catch (e) {
        log("error on " + path + ": " + (e && e.stack ? e.stack : e));
        return [500, "text/plain", String((e && e.message) || e)];
      }
    },
  };
  Zotero.Server.Endpoints[path] = endpoints[path];
}

function install() {}
function uninstall() {}

function startup() {
  register("/voiceannotator/current", ["GET"], async function () {
    var reader = activeReader();
    var item = Zotero.Items.get(reader.itemID);
    var parent = item.parentItem || item;
    var url = "";
    try {
      url = parent.getField("url") || "";
      if (!url) {
        var doi = parent.getField("DOI");
        if (doi) url = "https://doi.org/" + doi;
      }
    } catch (e) {
      url = "";
    }
    var date = "";
    try {
      date = parent.getField("date") || "";
    } catch (e) {
      date = "";
    }
    return {
      key: parent.key,
      title: parent.getDisplayTitle ? parent.getDisplayTitle() : parent.getField("title"),
      url: url,
      year: date.slice(0, 4),
      firstCreator: parent.firstCreator || "",
    };
  });

  // Serves the open attachment's text so the client never needs Zotero's read
  // API, which is off by default and keys off the attachment rather than the
  // parent item. Item.attachmentText (data/item.js:3871) reads the
  // .zotero-ft-cache file when the attachment is fully indexed, falls back to
  // the processor cache, and otherwise extracts on demand with PDFWorker.
  register("/voiceannotator/fulltext", ["GET"], async function (data, req) {
    var reader = activeReader();
    var attachment = Zotero.Items.get(reader.itemID);
    var parent = attachment.parentItem || attachment;

    // The client sends the key it got from /current. Treat a mismatch as a
    // caller error rather than silently returning text for a different paper.
    var wanted = req.searchParams && req.searchParams.get("key");
    if (wanted && wanted !== attachment.key && wanted !== parent.key) {
      throw new Error(
        "key '" + wanted + "' is not the open item (" + parent.key + ")"
      );
    }

    var content = await attachment.attachmentText;
    if (!content) throw new Error("No text available for the open attachment");
    return {
      content: content,
      attachmentKey: attachment.key,
      parentKey: parent.key,
    };
  });

  register("/voiceannotator/highlight", ["POST"], async function (data) {
    if (!data.text) throw new Error("'text' is required");
    var reader = readyReader();
    var found = await findAnnotation(reader, data.text);

    var attachment = Zotero.Items.get(reader.itemID);
    var json = {
      key: Zotero.DataObjectUtilities.generateKey(),
      type: "highlight",
      text: found.text || data.text,
      comment: data.comment || "",
      color: Zotero.Annotations.DEFAULT_COLOR,
      pageLabel: found.pageLabel || "",
      sortIndex: found.sortIndex,
      position: found.position,
    };
    var annotation = await Zotero.Annotations.saveFromJSON(attachment, json);
    try {
      await reader.navigate({ position: found.position });
    } catch (e) {
      log("navigate failed: " + e);
    }
    return { annotationKey: annotation.key };
  });

  register("/voiceannotator/delete", ["POST"], async function (data) {
    if (!data.key) throw new Error("'key' is required");
    var item = null;
    var libraryIDs = [Zotero.Libraries.userLibraryID];
    try {
      libraryIDs = Zotero.Libraries.getAll().map(function (l) {
        return l.libraryID;
      });
    } catch (e) {
      // fall back to the user library alone
    }
    for (var i = 0; i < libraryIDs.length; i++) {
      item = Zotero.Items.getByLibraryAndKey(libraryIDs[i], data.key);
      if (item) break;
    }
    if (item) await item.eraseTx();
    return { ok: true };
  });

  log("endpoints registered");
}

function shutdown() {
  for (var path in endpoints) delete Zotero.Server.Endpoints[path];
  endpoints = {};
}
