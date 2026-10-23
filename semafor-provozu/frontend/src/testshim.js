/* Testovací náhrada platformy pro Playwright: sdílená "databáze" v localStorage
   (dvě záložky = dva klienti), identita z ?u=a|b, kooperativní zámek přes localStorage.
   Testuje logiku aplikace, NE platformní pravidla soukromí — ta se ověřují na ostrém úložišti. */
(function(){
  var MEMBER = (window.__MEMBER && typeof window.__MEMBER==='object') ? window.__MEMBER : null;
  var KEY = MEMBER ? 'sp_member_'+MEMBER.slug+'_'+MEMBER.snapshotId : 'sp_test_db_v2';
  var params=new URLSearchParams(location.search);
  var who=params.get('u')||'a';
  var USERS={ a:{id:'u_alice',name:'Alice Testová',email:'alice@hranipex.com',isOwner:true,canEdit:true},
              b:{id:'u_bob',name:'Bob Zkušební',email:'bob@hranipex.com',isOwner:false,canEdit:true},
              c:{id:'u_cyril',name:'Cyril Třetí',email:null,isOwner:false,canEdit:true} };
  // DOČASNÝ REŽIM ÚTVARŮ: identita je napevno v souboru (žádné přihlášení), nikdy vlastník aplikace
  var me = MEMBER ? { id:'m_'+MEMBER.slug, name:MEMBER.name, email:MEMBER.email, isOwner:false, canEdit:true } : USERS[who];
  // v členském souboru je adresář = lidé z members.json (žádní testovací uživatelé); ostatní jména se berou z dat
  if(MEMBER){ USERS={}; (MEMBER.directory||[]).forEach(function(u){ USERS['m_'+u.slug]={id:'m_'+u.slug,name:u.name,email:u.email,isOwner:false,canEdit:true}; }); USERS[me.id]=me; }
  function load(){ try{ return JSON.parse(localStorage.getItem(KEY)||'{}'); }catch(e){ return {}; } }
  function save(d){ localStorage.setItem(KEY, JSON.stringify(d)); }
  // Členský soubor nese: __BASE (snímek od správce), __SAVED (změny uložené do souboru tlačítkem „Uložit soubor s daty“),
  // __TPL (gzip+base64 této stránky bez dat — z něj se skládá nový soubor). __SEED používají jen testy.
  if(MEMBER && window.__BASE && !window.__SEED){ window.__SEED = window.__BASE; }
  var SAVED = (MEMBER && window.__SAVED && typeof window.__SAVED==='object') ? window.__SAVED : null;
  if(MEMBER && !window.__TPL){ var tplEl=document.getElementById('sp-tpl'); if(tplEl) window.__TPL=(tplEl.textContent||'').trim(); }
  function normEv(ev){ if(Array.isArray(ev)){ var o={}; ev.forEach(function(e,i){ o[(e&&e.id)||String(i)]=e; }); return o; } return (ev&&typeof ev==='object')?ev:{}; }
  // porovnání bez místních identit (m_… se při sloučení nahrazují) a bez rev
  function normId(o){ if(!o||typeof o!=='object') return JSON.stringify(o); var c=JSON.parse(JSON.stringify(o)); ['ownerUserId','createdById','updatedById','confirmedById','archivedById','rev'].forEach(function(f){ delete c[f]; }); return JSON.stringify(c); }
  function sharedPath(k){ return !(k.indexOf('_lease/')===0||k==='_meta'||k.indexOf('data/users/')===0||k.indexOf('_conflict/')===0); }
  if(window.__SEED && !localStorage.getItem(KEY)){
    var seed=JSON.parse(JSON.stringify(window.__SEED));
    seed._meta={ openedAt:Date.now(), snapshotId:MEMBER?MEMBER.snapshotId:'', lastSentAt:0, savedAt:0, dirty:{}, sentDocs:{} };
    // nový snímek: soukromé To-Do (data/users/…) se převezme z předchozího snímku téhož člověka — JEN z tohoto prohlížeče
    // (v souboru ani v exportu soukromé To-Do není); zároveň se zkontroluje, zda ve starém snímku nezůstaly neuložené změny
    if(MEMBER){ var prefix='sp_member_'+MEMBER.slug+'_', best=null, bestAt=0, bestKey='';
      for(var i=0;i<localStorage.length;i++){ var k=localStorage.key(i); if(k&&k.indexOf(prefix)===0&&k!==KEY){ try{ var m=JSON.parse(localStorage.getItem(k)||'{}'); var at=(m._meta&&m._meta.openedAt)||0; if(at>=bestAt){ bestAt=at; best=m; bestKey=k; } }catch(e){} } }
      if(best){ Object.keys(best).forEach(function(k){ if(k.indexOf('data/users/')===0) seed[k]=best[k]; });
        var dirty=(best._meta&&best._meta.dirty)||{}, dp=Object.keys(dirty).filter(function(k){ return !!best[k]; });
        // odeslané/uložené změny ze starého snímku, které v novém snímku nejsou (nepřijaty při sloučení, nebo je někdo přepsal)
        var sent=(best._meta&&best._meta.sentDocs)||{}, np=Object.keys(sent).filter(function(k){ if(!sharedPath(k)||k.indexOf('history/')===0) return false; try{ return normId(JSON.parse(sent[k]))!==normId(seed[k]); }catch(e){ return true; } });
        if(dp.length||np.length) seed._meta.prevUnsaved={ snapshotId:(best._meta&&best._meta.snapshotId)||'', snapshotDate:(best._meta&&best._meta.snapshotDate)||'', paths:dp, titles:dp.map(function(k){ return (best[k]&&(best[k].title||k))||k; }),
          notInSnapshot:np, notInSnapshotTitles:np.map(function(k){ try{ var o=JSON.parse(sent[k]); return (o&&o.title)||k; }catch(e){ return k; } }) }; }
      seed._meta.snapshotDate=MEMBER.snapshotDate||'';
      if(SAVED && SAVED.docs){ Object.keys(SAVED.docs).forEach(function(k){ seed[k]=SAVED.docs[k]; seed._meta.sentDocs[k]=JSON.stringify(SAVED.docs[k]); }); seed._meta.savedAt=SAVED.savedAt||0; seed._meta.lastSentAt=SAVED.savedAt||0; } }
    save(seed);
  }
  if(MEMBER){ (function(){ var d=load(); d._meta=d._meta||{}; d._meta.dirty=d._meta.dirty||{}; d._meta.sentDocs=d._meta.sentDocs||{}; var seed0=window.__SEED||{};
    // Otevřen soubor uložený později než stav v tomto prohlížeči (např. uložen na jiném počítači). Nic se tiše nepřepíše:
    //  - položka bez rozpracované lokální práce → platí soubor;
    //  - položka, kterou jsem tu změnil a NEuložil (a soubor nemá právě tuto podobu) → zůstává moje práce, verze ze souboru
    //    se odloží do _conflict/… a rozhodnu v postranním panelu (Nechat moji / Vzít ze souboru).
    if(SAVED && SAVED.docs && (SAVED.savedAt||0) > (d._meta.savedAt||0)){
      Object.keys(SAVED.docs).forEach(function(k){ var fileJ=JSON.stringify(SAVED.docs[k]), localJ=JSON.stringify(d[k]);
        if(localJ===fileJ){ d._meta.sentDocs[k]=fileJ; return; }
        if(k.indexOf('history/')===0){ // historie je přírůstková: sjednocení událostí podle id, nikdy konflikt
          var L=d[k]||{itemId:k.slice(8),archivedChunks:0,converted:false,events:{}}, F=SAVED.docs[k]||{}; var le=normEv(L.events), fe=normEv(F.events); Object.keys(fe).forEach(function(id){ if(!le[id]) le[id]=fe[id]; });
          L.events=le; L.updatedAt=Math.max(L.updatedAt||0,F.updatedAt||0); d[k]=L; if(JSON.stringify(L)!==localJ) d._meta.dirty[k]=d._meta.dirty[k]||Date.now(); return; }
        var localUnsaved = d[k]!==undefined && !!d._meta.dirty[k] && localJ!==d._meta.sentDocs[k] && localJ!==JSON.stringify(seed0[k]);
        if(localUnsaved && fileJ!==d._meta.sentDocs[k]){ d['_conflict/'+k]={ file:SAVED.docs[k], savedAt:SAVED.savedAt, foundAt:Date.now() }; return; }
        if(localUnsaved) return;   // soubor = moje poslední uložení, lokálně mám novější práci → nechat
        d[k]=SAVED.docs[k]; d._meta.sentDocs[k]=fileJ; delete d._meta.dirty[k]; });
      d._meta.savedAt=SAVED.savedAt; d._meta.lastSentAt=Math.max(d._meta.lastSentAt||0, SAVED.savedAt); }
    d._meta.openedAt=Date.now(); save(d); })(); }
  function b64gunzip(b64){ var bin=atob(b64), u8=new Uint8Array(bin.length); for(var i=0;i<bin.length;i++) u8[i]=bin.charCodeAt(i); var ds=new DecompressionStream('gzip'); var w=ds.writable.getWriter(); w.write(u8); w.close(); return new Response(ds.readable).text(); }
  function jsonForScript(o){ return JSON.stringify(o).replace(/</g,'\\u003c'); }
  // Změny proti snímku = vše, co se liší od snímku (do souboru i do JSON exportu jde VŽDY všechno — tentýž export jde
  // stáhnout znovu; sloučení shodné položky přeskočí). „Uloženo do souboru“ ≠ „přijato do společných dat“ — přijetí je
  // vidět až v novém snímku. Neuložené = položky změněné od posledního uložení/odeslání (dirty).
  function changedPaths(){ var d=load(), seed=window.__SEED||{}, out=[]; Object.keys(d).forEach(function(k){ if(!sharedPath(k)) return; if(JSON.stringify(d[k])!==JSON.stringify(seed[k])) out.push(k); }); return out; }
  function conflicts(){ var d=load(); return Object.keys(d).filter(function(k){ return k.indexOf('_conflict/')===0; }).map(function(k){ var p=k.slice(10), c=d[k]||{}; return { path:p, title:(d[p]&&d[p].title)||p, fileTitle:(c.file&&c.file.title)||'', savedAt:c.savedAt||0, localAt:(d[p]&&d[p].updatedAt)||0, fileAt:(c.file&&c.file.updatedAt)||0 }; }); }
  window.__memberStore = MEMBER ? {
    status:function(){ var d=load(), ch=changedPaths(), m=d._meta||{}, dirty=Object.keys(m.dirty||{}), oldest=0; dirty.forEach(function(k){ var u=d[k]&&d[k].updatedAt; if(u&&(!oldest||u<oldest)) oldest=u; });
      return { changed:ch.length, unsaved:dirty.length, lastSentAt:m.lastSentAt||0, savedAt:m.savedAt||0, oldest:oldest, conflicts:conflicts(), prevUnsaved:m.prevUnsaved||null }; },
    resolveConflict:function(path, take){ var d=load(), c=d['_conflict/'+path]; if(!c) return; if(take==='file'){ d[path]=c.file; d._meta.sentDocs[path]=JSON.stringify(c.file); delete d._meta.dirty[path]; } delete d['_conflict/'+path]; save(d); fire(); },
    ackPrev:function(){ var d=load(); d._meta=d._meta||{}; d._meta.prevUnsaved=null; save(d); },
    exportChanges:function(info){ var d=load(), ch=changedPaths(), docs={}; ch.forEach(function(k){ docs[k]=d[k]; });
      return { count:ch.length, file:{ format:'semafor-export-1', member:{ slug:MEMBER.slug, name:MEMBER.name, email:MEMBER.email, depts:MEMBER.depts }, snapshotId:MEMBER.snapshotId, snapshotDate:MEMBER.snapshotDate, exportedAt:new Date().toISOString(), appVersion:info&&info.appVersion, docs:docs } }; },
    markSent:function(){ var d=load(); d._meta=d._meta||{}; d._meta.lastSentAt=Date.now(); d._meta.sentDocs={}; changedPaths().forEach(function(k){ d._meta.sentDocs[k]=JSON.stringify(d[k]); }); d._meta.dirty={}; save(d); },
    // celý soubor s daty: stejná stránka + snímek + VŠECHNY změny proti snímku (i dříve uložené) → nahrát do složky
    canSaveFile:function(){ return !!(window.__TPL && typeof DecompressionStream==='function'); },
    saveFile:function(){ if(!window.__TPL) return Promise.reject({code:'bez šablony'});
      var d=load(), docs={}, n=0; changedPaths().forEach(function(k){ docs[k]=d[k]; n++; });
      var now=Date.now(), saved={ savedAt:now, member:MEMBER.slug, docs:docs };
      return b64gunzip(window.__TPL).then(function(tpl){
        var html='<!doctype html><html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Semafor Provozu — '+(MEMBER.name||'')+' (dočasný režim)</title></head><body>'+
          '<script id="sp-data">window.__MEMBER='+jsonForScript(MEMBER)+';window.__BASE='+jsonForScript(window.__BASE||window.__SEED||{})+';window.__SAVED='+jsonForScript(saved)+';<\/script>'+
          '<script id="sp-tpl" type="text/plain">'+window.__TPL+'<\/script>'+tpl;
        var d2=load(); d2._meta=d2._meta||{}; d2._meta.savedAt=now; d2._meta.lastSentAt=now; d2._meta.sentDocs={}; Object.keys(docs).forEach(function(k){ d2._meta.sentDocs[k]=JSON.stringify(docs[k]); }); d2._meta.dirty={}; save(d2);
        return { html:html, count:n, savedAt:now };
      }); }
  } : null;
  var listeners=[];
  function fire(){ listeners.slice().forEach(function(l){ try{ l(); }catch(e){ console.error(e); } }); }
  window.addEventListener('storage', function(e){ if(e.key===KEY) fire(); });
  function split(path){ return path.split('/'); }
  function isObj(v){ return v && typeof v==='object' && !Array.isArray(v); }
  function deepMerge(target, patch){ Object.keys(patch).forEach(function(k){ if(isObj(patch[k]) && isObj(target[k])) deepMerge(target[k], patch[k]); else target[k]=patch[k]; }); }
  // simulace pravidla úložiště { path:'people', write:'owner' } — jen NÁHRADA, skutečné pravidlo ověřuje platforma
  // + hák pro testy selhání: window.__failNext = { match:/history\//, op:'set'|'acquire'|'update'|'*', code:'unavailable', times:1 }
  // zpomalení pro testy: window.__slow = { match:/^history\//, op:'get'|'set', ms:3000, times:1 }
  function slowFor(path, op){ var f=window.__slow; if(f && f.times>0 && f.op===op && f.match.test(path)){ f.times--; return f.ms; } return 0; }
  function failFor(path, op){
    if(path.indexOf('people/')===0 && !me.isOwner) return {code:'invalid_argument', message:'rule: people write=owner (shim)'};
    if(path.indexOf('settings/')===0 && op!=='get' && !me.isOwner) return {code:'invalid_argument', message:'rule: settings write=owner (shim)'};
    var f=window.__failNext; if(f && f.times>0 && (f.op==='*'||f.op===op) && f.match.test(path)){ f.times--; return {code:f.code||'unavailable', message:'injected failure'}; }
    return null;
  }
  function markDirty(d,path){ if(!MEMBER||!sharedPath(path)) return; d._meta=d._meta||{}; d._meta.dirty=d._meta.dirty||{}; d._meta.dirty[path]=Date.now(); }
  function colOf(path){ var a=split(path); a.pop(); return a.join('/'); }
  function snapDoc(path){ var d=load(); var body=d[path]; return { id:split(path).pop(), exists:!!body, data:function(){ return body?JSON.parse(JSON.stringify(body)):undefined; }, metadata:{fromCache:false,hasPendingWrites:false} }; }
  window.__wlog=[];
  function wlog(op,path,extra){ if(window.__wlog.length>800) window.__wlog.shift(); window.__wlog.push({t:Date.now(),op:op,path:path,x:extra||''}); }
  function docRef(path){
    return { id:split(path).pop(), path:path,
      get:function(){ var f=failFor(path,'get'); if(f) return Promise.reject(f); var sl=slowFor(path,'get'); var mk=function(){ var s=snapDoc(path); wlog('get',path,s.exists?'exists':'missing'); return s; }; return sl ? new Promise(function(r){ setTimeout(function(){ r(mk()); }, sl); }) : Promise.resolve(mk()); },
      set:function(data){ var f=failFor(path,'set'); if(f) return Promise.reject(f); var sl=slowFor(path,'set'); var doSet=function(){ var d=load(); d[path]=JSON.parse(JSON.stringify(data)); markDirty(d,path); save(d); wlog('set',path,Object.keys((data&&data.events)||{}).join('+')); fire(); }; if(sl) return new Promise(function(r){ setTimeout(function(){ doSet(); r(); }, sl); }); doSet(); return Promise.resolve(); },
      // update = rekurzivní sloučení vnořených objektů, pole a skaláry se nahrazují celé (jako platforma)
      update:function(patch){ var f=failFor(path,'update'); if(f) return Promise.reject(f); var sl=slowFor(path,'update'); var doIt=function(){ var d=load(); if(!d[path]) throw {code:'invalid_argument',message:'missing'}; deepMerge(d[path], JSON.parse(JSON.stringify(patch))); markDirty(d,path); save(d); wlog('update',path,Object.keys((patch&&patch.events)||{}).join('+')); fire(); }; if(sl) return new Promise(function(r,j){ setTimeout(function(){ try{ doIt(); r(); }catch(e){ j(e); } }, sl); }); try{ doIt(); }catch(e){ return Promise.reject(e); } return Promise.resolve(); },
      "delete":function(){ var d=load(); delete d[path]; markDirty(d,path); save(d); fire(); return Promise.resolve(); },
      acquire:function(o){ var f=failFor(path,'acquire'); if(f) return Promise.reject(f);
        if(window.__leaseDelayMs){ var self=this; var ms=window.__leaseDelayMs; window.__leaseDelayMs=0; return new Promise(function(r){ setTimeout(function(){ r(self.acquire(o)); }, ms); }); }
        // Platformní acquire je set-if-not-busy, tj. atomický na serveru. localStorage mezi záložkami atomický NENÍ
        // (zápis se do druhé záložky propíše se zpožděním), takže by obě relace mohly „získat“ lease naráz.
        // Náhrada proto po zápisu ještě po tiku ověří, že lease drží opravdu ona — vyhraje poslední zapisující,
        // druhá dostane acquired:false. Je to MODEL atomicity, ne důkaz; skutečnou atomicitu garantuje platforma.
        var d=load(); var lk='_lease/'+path; var now=Date.now(); var cur=d[lk];
        if(cur && cur.exp>now && cur.holder!==o.holder){ wlog('acq-busy',path,o.holder); return Promise.resolve({acquired:false, expiresAt:new Date(cur.exp).toISOString()}); }
        var exp=now+(o.ttlMs||30000); d[lk]={holder:o.holder, exp:exp}; save(d);
        return new Promise(function(r){ setTimeout(function(){
          var d2=load(), c2=d2['_lease/'+path];
          if(c2 && c2.holder===o.holder){ wlog('acq-ok',path,o.holder+' ttl'+(o.ttlMs||30000)); r({acquired:true, holder:o.holder, expiresAt:new Date(c2.exp).toISOString()}); }
          else { wlog('acq-busy',path,o.holder+' (prohrál souběh)'); r({acquired:false, expiresAt:new Date((c2&&c2.exp)||exp).toISOString()}); }
        }, 60); }); },
      onSnapshot:function(next,err){ var l=function(){ next(snapDoc(path)); }; listeners.push(l); setTimeout(l,0); return function(){ listeners=listeners.filter(function(x){return x!==l;}); }; },
      collection:function(sub){ return colRef(path+'/'+sub); } };
  }
  function colRef(path){
    var filters=[];
    var q={ path:path,
      where:function(f,op,v){ var n=colRef(path); n._filters=filters.concat([[f,op,v]]); return n; },
      orderBy:function(){ return q; }, limit:function(){ return q; },
      _match:function(body){ return (q._filters||[]).every(function(fl){ var x=body[fl[0]]; if(fl[1]==='=='||fl[1]==='eq') return x===fl[2]; if(fl[1]==='!='||fl[1]==='ne') return x!==fl[2]; return true; }); },
      _docs:function(){ var d=load(); return Object.keys(d).filter(function(k){ return colOf(k)===path && k.indexOf('_lease/')!==0 && k.indexOf('_conflict/')!==0 && k!=='_meta' && q._match(d[k]); }).sort().map(function(k){ return snapDoc(k); }); },
      get:function(){ var docs=q._docs(); return Promise.resolve({docs:docs,size:docs.length,empty:!docs.length,docChanges:function(){return [];},metadata:{fromCache:false,hasPendingWrites:false}}); },
      onSnapshot:function(next,err){ var l=function(){ var docs=q._docs(); next({docs:docs,size:docs.length,empty:!docs.length,docChanges:function(){return [];},metadata:{fromCache:false,hasPendingWrites:false}}); }; listeners.push(l); setTimeout(l,0); return function(){ listeners=listeners.filter(function(x){return x!==l;}); }; },
      doc:function(id){ return docRef(path+'/'+(id||Math.random().toString(36).slice(2,22))); },
      add:function(data){ var r=q.doc(); return r.set(data).then(function(){ return r; }); } };
    return q;
  }
  var DB={ doc:function(p){ return docRef(p); }, collection:function(p){ return colRef(p); } };
  var USER={ isOwner:function(){return Promise.resolve(me.isOwner);}, canEdit:function(){return Promise.resolve(me.canEdit);},
    me:function(){ return Promise.resolve({id:me.id,name:me.name,email:me.email,avatarUrl:'',color:'#888',isOwner:me.isOwner,canEdit:me.canEdit}); },
    id:function(){return Promise.resolve(me.id);},
    profiles:function(ids){ var out={}; (Array.isArray(ids)?ids:[ids]).forEach(function(i){ var u=Object.keys(USERS).map(function(k){return USERS[k];}).find(function(x){return x.id===i;}); out[i]=u?{id:i,name:u.name,avatarUrl:'',color:'#888',email:MEMBER?u.email:null,isMe:i===me.id}:{id:i,name:'',avatarUrl:'',color:'#888',email:null,isMe:false}; }); return Promise.resolve(out); },
    // v členském souboru se lidé vedou e-mailem (id m_… je jen místní), proto hledání vrací e-mail a žádné id
    search:function(q){ q=(q||'').toLowerCase(); return Promise.resolve(Object.keys(USERS).map(function(k){return USERS[k];}).filter(function(u){return !q||u.name.toLowerCase().indexOf(q)>=0||(MEMBER&&(u.email||'').toLowerCase().indexOf(q)>=0);}).map(function(u){return {id:MEMBER?'':u.id,name:u.name,avatarUrl:'',color:'#888',email:MEMBER?u.email:null,isMe:u.id===me.id};})); } };
  window.claude={ use:function(n){ if(n==='db') return Promise.resolve(DB); if(n==='user') return Promise.resolve(USER); return Promise.resolve(null); } };
  window.__resetTestDb=function(){ localStorage.removeItem(KEY); if(window.__SEED) save(window.__SEED); fire(); };
})();
