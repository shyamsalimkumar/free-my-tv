#!/usr/bin/env python3
"""Sends a note to Free My TV on an LG TV (a picture, a message, or both; it opens on the TV at once), or gets the
last one left on the TV.

    python3 webos/note.py <TV IP> drawing.png "See you at 8!"
    python3 webos/note.py <TV IP> "Just a message"
    python3 webos/note.py <TV IP> drawing.png
    python3 webos/note.py <TV IP> --get

The picture can be a PNG, JPEG or WebP, up to 8 MB. --get saves the TV's drawing in ~/.freemytv/notes and shows it
with its message. Install Free My TV first (webos/install.py): this uses its key.
On the TV, Notes (in the drawer) shows the last note, draws on it and saves a new one.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from install import APP_ID, SSH_OPTS, fetch_key, luna, ssh   # noqa: E402

LIMIT = 8 * 1024 * 1024
DIR = '/tmp/freemytv-note/'
NOTES = os.path.join(os.path.expanduser('~'), '.freemytv', 'notes')   # where --get keeps the drawings
UNREACHABLE = "Couldn't reach the TV. Is it on, and Developer Mode still on?"


def send(ip, image, text):
    key = fetch_key(ip)
    # The app's service takes them from there (webos/service says why there): the page itself can't read files.
    for name, data in (('image', image and open(image, 'rb').read()), ('text', text.encode('utf-8'))):
        if not data:
            continue
        command = 'mkdir -p %s && chmod 777 %s && cat > %s%s && chmod 666 %s%s' % (DIR, DIR, DIR, name, DIR, name)
        with tempfile.TemporaryFile() as f:   # ssh reads its input from a real file
            f.write(data)
            f.seek(0)
            if ssh(ip, key, command, stdin=f).returncode != 0:
                sys.exit(UNREACHABLE)
    luna(ip, key, 'luna://com.webos.applicationManager/launch', {'id': APP_ID})
    print('Sent. It shows on the TV now.')


def get(ip):
    """The note last saved on the TV, which the app leaves in DIR (reply.json, reply.png) when it starts or saves."""
    key = fetch_key(ip)

    def read(name):
        command = 'cat %s%s 2>/dev/null || true' % (DIR, name)
        out = subprocess.run(['ssh'] + SSH_OPTS + ['-i', key, 'prisoner@' + ip, command], capture_output=True)
        if out.returncode != 0:
            sys.exit(UNREACHABLE)
        return out.stdout

    try:
        note = json.loads(read('reply.json').decode('utf-8'))
    except ValueError:
        sys.exit('No note saved on the TV. (Open Free My TV on the TV once if it was just turned on.)')
    when = time.strftime('%a %d %b, %H:%M', time.localtime(note.get('at', 0) / 1000))
    # Read here: it needn't open by itself on the TV any more (the app takes this with the notes it's sent).
    seen = 'mkdir -p {0} && chmod 777 {0} && cat > {0}seen && chmod 666 {0}seen'.format(DIR)
    with tempfile.TemporaryFile() as f:
        f.write(str(note.get('at', '')).encode())
        f.seek(0)
        ssh(ip, key, seen, stdin=f)
    print('Note saved on the TV on %s.' % when)
    print('Message: %s' % (note.get('text') or '(none)'))
    image = read('reply.png') if note.get('image') else b''
    path = None
    if image:
        os.makedirs(NOTES, exist_ok=True)
        stamp = time.strftime('%Y-%m-%d-%H%M', time.localtime(note.get('at', 0) / 1000))
        path = os.path.join(NOTES, 'note-from-tv-%s.png' % stamp)
        with open(path, 'wb') as f:
            f.write(image)
        print('Drawing: %s' % path)
    else:
        print('Drawing: (none)')
    if sys.platform == 'darwin' and shutil.which('swift'):
        # A card with the drawing and the message (note_popup.swift); it stays up after this ends.
        popup = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'note_popup.swift')
        subprocess.Popen(['swift', popup, path or '', 'Note from the TV', when, note.get('text') or ''],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def main():
    args = sys.argv[1:]
    if not args or not re.match(r'^\d{1,3}(\.\d{1,3}){3}$', args[0]):
        sys.exit(__doc__)
    ip, rest = args[0], args[1:]
    if rest == ['--get']:
        get(ip)
        return
    if any(a.startswith('--') for a in rest):
        sys.exit(__doc__)   # an unknown option mustn't go to the TV as the message
    image = rest.pop(0) if rest and re.search(r'\.(png|jpe?g|webp)$', rest[0], re.I) else None
    if image and not os.path.isfile(image):
        sys.exit("Can't find the picture %s. Check its name and folder." % image)
    text = ' '.join(rest).strip()
    if not image and not text:
        sys.exit(__doc__)
    if image and os.path.getsize(image) > LIMIT:
        sys.exit('The picture is over 8 MB: save it smaller and try again.')
    send(ip, image, text)


if __name__ == '__main__':
    main()
