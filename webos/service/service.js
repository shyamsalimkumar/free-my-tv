/*
 * Free My TV's service on LG webOS: one call to the TV's remote control API (127.0.0.1:3000) for the web app, and
 * the notes a computer sends (webos/note.py).
 * Newer webOS gives each app's page its own origin (file://io.freemytv-webos), and the API closes any connection
 * that isn't from file:// ("invalid origin"); from here the handshake says file://.
 * Plain ES5 with Node's net only: older webOS ships an old Node.
 */
var fs = require('fs');
var net = require('net');
var Service = require('webos-service');

var service = new Service(require('./package.json').name);

function buffer(x, encoding) {   // Buffer.from is missing before Node 4.5
  return Buffer.from ? Buffer.from(x, encoding) : new Buffer(x, encoding);
}

/** A client's text frame: masked, as the protocol asks. */
function frame(text) {
  var data = buffer(text), n = data.length;
  var mask = buffer([Math.random() * 256 | 0, Math.random() * 256 | 0, Math.random() * 256 | 0, Math.random() * 256 | 0]);
  for (var i = 0; i < n; i++) data[i] ^= mask[i % 4];
  return Buffer.concat([buffer(n < 126 ? [0x81, 0x80 | n] : [0x81, 0xfe, n >> 8, n & 0xff]), mask, data]);
}

/** done({clientKey, payload}), {refused: true} when the person said no on the TV, or null. */
function call(uri, clientKey, done) {
  var socket = net.connect(3000, '127.0.0.1'), buf = buffer([]), open = false, text = '', finished = false;
  var timer = setTimeout(function () { finish(null); }, 90000);   // time to answer the TV's prompt
  function finish(result) {
    if (finished) return;
    finished = true;
    clearTimeout(timer);
    socket.destroy();
    done(result);
  }
  function send(obj) {
    socket.write(frame(JSON.stringify(obj)));
  }
  function onMessage(m) {
    if (m.type === 'registered') {
      clientKey = m.payload['client-key'];
      send({type: 'request', id: 'call', uri: 'ssap://' + uri});
    } else if (m.id === 'call') {
      finish(m.type === 'error' ? null : {clientKey: clientKey, payload: m.payload});
    } else if (m.type === 'error') {
      finish(m.id === 'register' ? {refused: true} : null);
    }
  }
  socket.on('connect', function () {
    socket.write('GET / HTTP/1.1\r\nHost: 127.0.0.1:3000\r\nOrigin: file://\r\nUpgrade: websocket\r\n' +
        'Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: ZnJlZW15dHYtd2Vib3MtYXBp\r\n\r\n');
  });
  socket.on('data', function (chunk) {
    buf = Buffer.concat([buf, chunk]);
    if (!open) {
      var end = buf.toString('binary').indexOf('\r\n\r\n');
      if (end < 0) return;
      if (!/^HTTP\/1\.1 101/.test(buf.toString('utf8', 0, 12))) { finish(null); return; }
      open = true;
      buf = buf.slice(end + 4);
      var payload = {forcePairing: false, pairingType: 'PROMPT',
        manifest: {manifestVersion: 1, appVersion: '1.0', permissions: ['READ_INSTALLED_APPS']}};
      if (clientKey) payload['client-key'] = clientKey;
      send({type: 'register', id: 'register', payload: payload});
    }
    // The server's frames: unmasked, a message possibly in several (continuation frames until FIN).
    while (buf.length >= 2) {
      var fin = buf[0] & 0x80, op = buf[0] & 0x0f, n = buf[1] & 0x7f, off = 2;
      if (n === 126) {
        if (buf.length < 4) return;
        n = buf.readUInt16BE(2);
        off = 4;
      } else if (n === 127) {
        if (buf.length < 10) return;
        n = buf.readUInt32BE(6);
        off = 10;
      }
      if (buf.length < off + n) return;
      var data = buf.slice(off, off + n);
      buf = buf.slice(off + n);
      if (op === 8) { finish(null); return; }
      if (op !== 1 && op !== 0) continue;
      text += data.toString('utf8');
      if (!fin) continue;
      var m = null;
      try { m = JSON.parse(text); } catch (e) {}
      text = '';
      if (m) onMessage(m);
    }
  });
  socket.on('error', function () { finish(null); });
  socket.on('close', function () { finish(null); });
}

// A note sent from a computer (webos/note.py) waits in /tmp: the page can't read files, and this jailed service sees
// no other folder that the computer's SSH login can write to. In a folder of its own that anyone may write to, since
// /tmp lets only a file's owner delete it, and a note left there would come back every time.
var NOTE_DIR = '/tmp/freemytv-note/';

/** The file's content, once: it's deleted as it's read. */
function take(path, encoding) {
  var data = '';
  try {
    if (fs.statSync(path).size <= 8 * 1024 * 1024) data = fs.readFileSync(path, encoding);
  } catch (e) {
    return '';
  }
  try { fs.unlinkSync(path); } catch (e) { return ''; }
  return data;
}

service.register('note', function (message) {
  // seen: the time of the TV's note that note.py --get read, which then needn't open by itself on the TV.
  var image = take(NOTE_DIR + 'image', 'base64'), text = take(NOTE_DIR + 'text', 'utf8');
  message.respond({returnValue: true, image: image, text: text, seen: take(NOTE_DIR + 'seen', 'utf8')});
});

/** The note last saved on the TV, for the computer (note.py --get): {text, at, image: base64 PNG}, or {} for none. */
service.register('reply', function (message) {
  var p = message.payload || {}, image = typeof p.image === 'string' ? p.image : '';
  try {
    try { fs.mkdirSync(NOTE_DIR); fs.chmodSync(NOTE_DIR, 511); } catch (e) {}   // 0777: note.py writes there too
    try { fs.unlinkSync(NOTE_DIR + 'reply.png'); } catch (e) {}
    if (typeof p.at !== 'number') {
      try { fs.unlinkSync(NOTE_DIR + 'reply.json'); } catch (e) {}
    } else {
      if (image) fs.writeFileSync(NOTE_DIR + 'reply.png', buffer(image, 'base64'));
      fs.writeFileSync(NOTE_DIR + 'reply.json', JSON.stringify({text: String(p.text || ''), at: p.at, image: !!image}));
    }
    message.respond({returnValue: true});
  } catch (e) {
    message.respond({returnValue: false, errorText: String(e)});
  }
});

// Photos for the screensaver, sent from a computer (webos/photos.py) the same way: the JPEGs and set.txt, their names
// (empty: none). The page copies them into its own storage, a piece at a time: one Luna reply holds only so much
// (a multiple of 3 bytes, so the pieces' base64 joins into the whole's).
var PHOTO_DIR = '/tmp/freemytv-photos/', PHOTO_NAME = /^[\w.-]+\.jpg$/, PIECE = 192 * 1024;

/** The set just sent ({names: [...]}, once), or {} when nothing came. */
service.register('photos', function (message) {
  if (!fs.existsSync(PHOTO_DIR + 'set.txt')) { message.respond({returnValue: true}); return; }
  var names = take(PHOTO_DIR + 'set.txt', 'utf8');
  message.respond({returnValue: true, names: names.split('\n').filter(function (n) { return PHOTO_NAME.test(n); })});
});

/** {name, part}: that piece of the photo, base64, and whether more follow; the file goes after its last piece. */
service.register('photo', function (message) {
  var p = message.payload || {}, name = String(p.name || ''), part = p.part | 0;
  if (!PHOTO_NAME.test(name)) { message.respond({returnValue: false, errorText: 'Bad name'}); return; }
  try {
    var data = fs.readFileSync(PHOTO_DIR + name), more = (part + 1) * PIECE < data.length;
    if (!more) fs.unlinkSync(PHOTO_DIR + name);
    var piece = data.slice(part * PIECE, (part + 1) * PIECE).toString('base64');
    message.respond({returnValue: true, data: piece, more: more});
  } catch (e) {
    message.respond({returnValue: false, errorText: String(e)});
  }
});

service.register('ssap', function (message) {
  var p = message.payload || {};
  // Only the app list, the one call the page makes: nothing else goes to the TV's API, nor gets its client key.
  if (p.uri !== 'com.webos.applicationManager/listLaunchPoints') {
    message.respond({returnValue: false, errorText: 'Only listLaunchPoints'});
    return;
  }
  call(p.uri, p.clientKey, function (result) {
    if (!result) message.respond({returnValue: false, errorText: 'No answer from the remote control API'});
    else {
      result.returnValue = true;
      message.respond(result);
    }
  });
});
