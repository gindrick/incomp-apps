/* Semafor Provozu: platformní adaptér pro interní nasazení.
 *
 * Aplikace je napsaná proti API Claude artefaktu (window.claude.use('db'|'user'|'assets'|'downloads')).
 * Tento soubor poskytuje totéž API nad backendem Semafor (REST + Server-Sent Events), takže logika
 * aplikace zůstává beze změny. Popis rozhraní: docs/ARCHITEKTURA.md, kapitola "Platformní adaptér".
 *
 *  db        doc(path) / collection(path): get, set, update (hluboké sloučení), delete, acquire (lease),
 *            onSnapshot (živé změny), where (filtr na klientu), add
 *  user      me, id, isOwner, canEdit, profiles, search
 *  assets    upload(file, {type})
 *  downloads save({filename, data})
 */
(function () {
  'use strict';

  var CFG = window.SP_CONFIG || {};
  var BASE = (CFG.basePath || '').replace(/\/+$/, '');
  var POLL_MS = 5000;              // záložní dotazování, když proud změn (SSE) nejde
  var SSE_MAX_FAILS = 3;           // po tolika chybách proudu za sebou přejít na dotazování
  var SSE_RETRY_MS = 60000;        // jak často zkusit proud znovu během dotazování
  window.SP_BASE_PATH = BASE;

  // ------------------------------------------------------------------ HTTP
  function apiError(code, message, status) { return { code: code, message: message || code, status: status || 0 }; }

  function showSessionExpired() {
    if (document.getElementById('sp-session-expired')) return;
    var bar = document.createElement('div');
    bar.id = 'sp-session-expired';
    bar.setAttribute('role', 'alert');
    bar.style.cssText = 'position:fixed;left:0;right:0;top:0;z-index:9999;background:#ed1b34;color:#fff;padding:10px 16px;font:14px Arial,sans-serif;text-align:center';
    bar.innerHTML = 'Přihlášení vypršelo. Rozepsané změny si zkopíruj a <a href="" style="color:#fff;font-weight:bold">načti stránku znovu</a>.';
    document.body.appendChild(bar);
  }

  function request(method, path, body, opts) {
    opts = opts || {};
    var init = { method: method, credentials: 'same-origin', headers: { 'Accept': 'application/json' } };
    if (method !== 'GET') init.headers['X-Semafor-Request'] = '1';
    if (body instanceof FormData) { init.body = body; }
    else if (body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
    return fetch(BASE + path, init).then(function (res) {
      if (res.status === 401) { showSessionExpired(); throw apiError('upstream_auth', 'přihlášení vypršelo', 401); }
      return res.text().then(function (txt) {
        var json = null;
        try { json = txt ? JSON.parse(txt) : null; } catch (e) { json = null; }
        if (!res.ok) throw apiError((json && json.code) || (res.status >= 500 ? 'unavailable' : 'invalid_argument'), json && json.message, res.status);
        return json;
      });
    }, function (err) {
      throw apiError('unavailable', (err && err.message) || 'síť není dostupná');
    });
  }

  function enc(path) { return String(path).split('/').map(encodeURIComponent).join('/'); }
  function clone(v) { return v === undefined ? undefined : JSON.parse(JSON.stringify(v)); }
  function randomId() {
    var a = new Uint8Array(15), s = '', abc = 'abcdefghijklmnopqrstuvwxyz0123456789';
    (window.crypto || window.msCrypto).getRandomValues(a);
    for (var i = 0; i < a.length; i++) s += abc.charAt(a[i] % abc.length);
    return s + Date.now().toString(36).slice(-5);
  }
  function parentOf(path) { var a = path.split('/'); a.pop(); return a.join('/'); }
  function lastOf(path) { var a = path.split('/'); return a[a.length - 1]; }

  // ------------------------------------------------------------------ cache a živé změny
  // collections: path -> { loaded:bool, loading:Promise, docs:{id:{data,version}}, listeners:[] }
  // docWatch:    path -> { listeners:[], data, version, exists }
  var collections = {}, docWatch = {}, seq = 0, started = false;

  function docSnap(id, entry) {
    var data = entry ? entry.data : undefined;
    return { id: id, exists: !!entry, data: function () { return clone(data); }, metadata: { fromCache: false, hasPendingWrites: false } };
  }
  function querySnap(col, filters) {
    var ids = Object.keys(col.docs).sort(), docs = [];
    ids.forEach(function (id) { var e = col.docs[id]; if (matches(e.data, filters)) docs.push(docSnap(id, e)); });
    return { docs: docs, size: docs.length, empty: !docs.length, docChanges: function () { return []; }, metadata: { fromCache: false, hasPendingWrites: false } };
  }
  function matches(data, filters) {
    return (filters || []).every(function (f) {
      var x = data ? data[f[0]] : undefined, op = f[1], v = f[2];
      if (op === '==' || op === 'eq') return x === v;
      if (op === '!=' || op === 'ne') return x !== v;
      if (op === '<') return x < v; if (op === '<=') return x <= v;
      if (op === '>') return x > v; if (op === '>=') return x >= v;
      if (op === 'in') return Array.isArray(v) && v.indexOf(x) >= 0;
      if (op === 'array-contains') return Array.isArray(x) && x.indexOf(v) >= 0;
      return true;
    });
  }
  function emitCollection(path) {
    var col = collections[path]; if (!col || !col.loaded) return;
    col.listeners.slice().forEach(function (l) { try { l.next(querySnap(col, l.filters)); } catch (e) { console.error(e); } });
  }
  function emitDoc(path) {
    var w = docWatch[path]; if (!w) return;
    var entry = w.exists ? { data: w.data, version: w.version } : null;
    w.listeners.slice().forEach(function (l) { try { l.next(docSnap(lastOf(path), entry)); } catch (e) { console.error(e); } });
  }

  function loadCollection(path) {
    var col = collections[path] || (collections[path] = { loaded: false, loading: null, docs: {}, tomb: {}, listeners: [] });
    if (col.loaded) return Promise.resolve(col);
    if (col.loading) return col.loading;
    col.loading = request('GET', '/api/collections/' + enc(path)).then(function (res) {
      var docs = {};
      res.docs.forEach(function (d) { docs[d.id] = { data: d.data, version: d.version }; });
      // změny, které mezitím přišly proudem a jsou novější, se nepřepíšou
      Object.keys(col.docs).forEach(function (id) { var c = col.docs[id]; if (!docs[id] || docs[id].version < c.version) docs[id] = c; });
      Object.keys(col.tomb).forEach(function (id) { if (docs[id] && docs[id].version <= col.tomb[id]) delete docs[id]; });
      col.docs = docs; col.tomb = {}; col.loaded = true; col.loading = null;
      if (!started) {
        if (!seq || res.seq < seq) seq = res.seq;  // proud změn začne od nejstaršího načtení
        ensureStream();
        return col;
      }
      // proud už běží od jiného seq: změny mezi snímkem této kolekce a začátkem proudu dobrat zvlášť
      return request('GET', '/api/changes?since=' + res.seq).then(function (ch) { applyChanges(ch); return col; }, function () { return col; });
    }, function (e) { col.loading = null; throw e; });
    return col.loading;
  }

  function applyChanges(res) {
    var touchedCols = {}, touchedDocs = {};
    (res.changes || []).forEach(function (ch) {
      var col = collections[ch.collection];
      if (col) {
        var cur = col.docs[ch.id];
        if (!cur || ch.version >= cur.version) {
          if (ch.deleted) {
            if (cur) { delete col.docs[ch.id]; touchedCols[ch.collection] = 1; }
            if (!col.loaded) col.tomb[ch.id] = ch.version;   // smazání během načítání kolekce
          }
          else { col.docs[ch.id] = { data: ch.data, version: ch.version }; touchedCols[ch.collection] = 1; }
        }
      }
      var w = docWatch[ch.path];
      if (w && (!w.version || ch.version >= w.version)) {
        w.exists = !ch.deleted; w.data = ch.data; w.version = ch.version; touchedDocs[ch.path] = 1;
      }
    });
    if (res.seq > seq) seq = res.seq;
    Object.keys(touchedCols).forEach(emitCollection);
    Object.keys(touchedDocs).forEach(emitDoc);
  }

  var es = null, sseFails = 0, pollTimer = null, polling = false, pollInFlight = null;
  function pollOnce() {
    if (pollInFlight) return pollInFlight;
    pollInFlight = request('GET', '/api/changes?since=' + seq).then(function (res) { applyChanges(res); }, function () { /* další kolo */ })
      .then(function () { pollInFlight = null; });
    return pollInFlight;
  }
  function startPolling() {
    if (polling) return; polling = true;
    pollTimer = setInterval(pollOnce, POLL_MS);
    setTimeout(function () { stopPolling(); sseFails = 0; openStream(); }, SSE_RETRY_MS);
  }
  function stopPolling() { polling = false; if (pollTimer) clearInterval(pollTimer); pollTimer = null; }
  function openStream() {
    if (es) { es.close(); es = null; }
    if (typeof EventSource !== 'function') { startPolling(); return; }
    es = new EventSource(BASE + '/api/stream?since=' + seq, { withCredentials: true });
    es.onopen = function () { sseFails = 0; };   // pravidelné ukončení proudu serverem není chyba
    es.addEventListener('changes', function (ev) {
      sseFails = 0;
      try { applyChanges(JSON.parse(ev.data)); } catch (e) { console.error('stream', e); }
    });
    es.onerror = function () {
      // vlastní obnovení s aktuálním seq (vestavěné by začalo od původního "since")
      if (es) { es.close(); es = null; }
      sseFails++;
      pollOnce();
      if (sseFails >= SSE_MAX_FAILS) { startPolling(); return; }
      setTimeout(openStream, 1000 * sseFails);
    };
  }
  function ensureStream() { if (started) return; started = true; openStream(); }
  document.addEventListener('visibilitychange', function () { if (!document.hidden) pollOnce(); });

  // po vlastním zápisu se změny vyzvednou hned (nečeká se na proud, který může proxy zdržet)
  function afterWrite(result) { pollOnce(); return result; }

  // ------------------------------------------------------------------ db
  function docRef(path) {
    return {
      id: lastOf(path), path: path,
      get: function () {
        return request('GET', '/api/docs/' + enc(path)).then(function (d) { return docSnap(d.id, d.exists ? { data: d.data, version: d.version } : null); });
      },
      set: function (data) { return request('PUT', '/api/docs/' + enc(path), { data: clone(data) }).then(afterWrite).then(function () {}); },
      update: function (patch) { return request('PATCH', '/api/docs/' + enc(path), { patch: clone(patch) }).then(afterWrite).then(function () {}); },
      'delete': function () { return request('DELETE', '/api/docs/' + enc(path)).then(afterWrite).then(function () {}); },
      acquire: function (o) { o = o || {}; return request('POST', '/api/leases/' + enc(path), { holder: String(o.holder || ''), ttlMs: o.ttlMs || 30000 }); },
      onSnapshot: function (next, err) {
        var w = docWatch[path] || (docWatch[path] = { listeners: [], data: undefined, version: 0, exists: false });
        var l = { next: next, err: err }; w.listeners.push(l);
        this.get().then(function (snap) {
          if (snap.exists) { w.exists = true; w.data = snap.data(); } else { w.exists = false; w.data = undefined; }
          ensureStream(); next(snap);
        }, function (e) { if (err) err(e); });
        return function () { w.listeners = w.listeners.filter(function (x) { return x !== l; }); };
      },
      collection: function (sub) { return colRef(path + '/' + sub); }
    };
  }

  function colRef(path, filters) {
    filters = filters || [];
    var q = {
      path: path,
      where: function (f, op, v) { return colRef(path, filters.concat([[f, op, v]])); },
      orderBy: function () { return q; },
      limit: function () { return q; },
      get: function () { return loadCollection(path).then(function (col) { return querySnap(col, filters); }); },
      onSnapshot: function (next, err) {
        var l = { next: next, err: err, filters: filters };
        var col = collections[path] || (collections[path] = { loaded: false, loading: null, docs: {}, tomb: {}, listeners: [] });
        col.listeners.push(l);
        loadCollection(path).then(function (c) { next(querySnap(c, filters)); }, function (e) { if (err) err(e); });
        return function () { col.listeners = col.listeners.filter(function (x) { return x !== l; }); };
      },
      doc: function (id) { return docRef(path + '/' + (id || randomId())); },
      add: function (data) { var r = q.doc(); return r.set(data).then(function () { return r; }); }
    };
    return q;
  }

  var DB = { doc: function (p) { return docRef(p); }, collection: function (p) { return colRef(p); } };

  // ------------------------------------------------------------------ user
  var mePromise = null;
  function loadMe() { return mePromise || (mePromise = request('GET', '/api/me')); }
  var USER = {
    me: function () { return loadMe().then(clone); },
    id: function () { return loadMe().then(function (m) { return m.id; }); },
    isOwner: function () { return loadMe().then(function (m) { return !!m.isOwner; }); },
    canEdit: function () { return loadMe().then(function (m) { return !!m.canEdit; }); },
    profiles: function (ids) { return request('POST', '/api/users/profiles', { ids: Array.isArray(ids) ? ids : [ids] }); },
    search: function (q) { return request('GET', '/api/users/search?q=' + encodeURIComponent(q || '')); }
  };

  // ------------------------------------------------------------------ assets
  var ASSETS = {
    upload: function (file, opts) {
      var fd = new FormData();
      fd.append('file', file, file.name || 'soubor');
      fd.append('type', (opts && opts.type) || file.type || '');
      return request('POST', '/api/assets', fd);
    }
  };

  // ------------------------------------------------------------------ downloads
  var DOWNLOADS = {
    save: function (o) {
      return new Promise(function (resolve) {
        var blob = o.data instanceof Blob ? o.data : new Blob([o.data], { type: /\.html?$/i.test(o.filename || '') ? 'text/html;charset=utf-8' : 'application/octet-stream' });
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob); a.download = o.filename || 'soubor';
        document.body.appendChild(a); a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); resolve(); }, 1500);
      });
    }
  };

  var SERVICES = { db: DB, user: USER, assets: ASSETS, downloads: DOWNLOADS };
  window.claude = {
    use: function (name) {
      if (name === 'db') return loadMe().then(function () { return DB; });   // bez přihlášení žádná databáze
      return Promise.resolve(SERVICES[name] || null);
    }
  };
})();
