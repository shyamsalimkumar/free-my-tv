#!/usr/bin/env python3
"""Sends an album from the Mac's Photos app to Free My TV on an LG TV, for its screensaver (instead of the picks').

    python3 webos/photos.py <TV IP> Favorites
    python3 webos/photos.py <TV IP> "Summer 2026"
    python3 webos/photos.py <TV IP> --clear
    python3 webos/photos.py <TV IP> Favorites --auto

--auto is for a schedule (launchd, every few hours): once a week it looks at the album, and when its newest photos
changed, it makes the new set and keeps it on the Mac (~/.freemytv/photos) until the TV has taken it: it tries again
while the TV is off, and sends again if the TV restarted before the app took them.

Each time, the album sent replaces the one on the TV, without opening the app (Free My TV takes them within 30
seconds while it's open, or when it opens); --clear takes them off (the picks come back). Up to 60 photos,
the newest first (videos, repeats and near copies are left out, and listed), fitted to the TV's screen
(webos/photo_fit.swift). Home Settings > My Photos turns them off and on.
macOS only (it asks the Photos app); the first time, macOS asks to allow controlling Photos. Install Free My TV first
(webos/install.py): this uses its key.
"""
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from install import fetch_key, ssh   # noqa: E402

DIR = '/tmp/freemytv-photos/'   # where the app's service takes them from (webos/service)
MOST = 60
EXPORTED = 100   # more than MOST, so the repeats left out leave room for others
WEEK = 7 * 24 * 3600   # how often --auto looks at the album

# Every photo in the album, a line each: the day it was taken (yyyymmdd), the second of that day, and its id. Photos
# lists an album oldest first and can't sort, so the newest are picked from this. (Seconds since 1970 overflow
# AppleScript's integers.)
LIST = '''
on run argv
  set wanted to item 1 of argv
  tell application "Photos"
    if wanted is "Favorites" then
      set chosen to favorites album
    else
      set found to (every album whose name is wanted)
      if found is {} then error "No album called " & wanted
      set chosen to item 1 of found
    end if
    set ids to id of every media item of chosen
    set taken to date of every media item of chosen
  end tell
  set out to {}
  repeat with i from 1 to count of ids
    set d to item i of taken
    if d is missing value then
      set end of out to "0" & tab & "0" & tab & item i of ids
    else
      set day_ to (year of d) * 10000 + (month of d as integer) * 100 + (day of d)
      set end of out to (day_ as text) & tab & ((time of d) as text) & tab & item i of ids
    end if
  end repeat
  set AppleScript's text item delimiters to linefeed
  return out as text
end run
'''

# Exports each photo into its own folder (the arguments: folder, id, folder, id...), so their order stays the
# newest first. `using originals` off: JPEG, HEIC turned into JPEG.
EXPORT = '''
on run argv
  set destinations to {}
  set ids to {}
  repeat with i from 1 to (count of argv) by 2
    set end of destinations to (POSIX file (item i of argv)) as alias   -- here: inside the tell, Photos can't
    set end of ids to item (i + 1) of argv
  end repeat
  tell application "Photos"
    repeat with i from 1 to count of ids
      export {media item id (item i of ids)} to (item i of destinations) without using originals
    end repeat
  end tell
end run
'''


def photos_app(script, args):
    out = subprocess.run(['osascript', '-e', script] + args, capture_output=True, text=True)
    if out.returncode != 0:
        why = out.stderr.strip()
        if 'No album called' in why:
            sys.exit('There\'s no album called "%s" in Photos. Check its name (capitals count).' % args[0])
        if 'Not authorized' in why or '-1743' in why:
            sys.exit('macOS didn\'t allow controlling Photos. Allow it in System Settings > Privacy & Security > '
                     'Automation, then try again.')
        sys.exit('Photos couldn\'t export the album: ' + why)
    return out.stdout


def newest(album):
    """The ids of the album's newest EXPORTED photos, the newest first."""
    listed = [line.split('\t') for line in photos_app(LIST, [album]).splitlines() if line.count('\t') == 2]
    return [x[2] for x in sorted(listed, key=lambda x: (int(x[0]), int(float(x[1]))), reverse=True)[:EXPORTED]]


def export(ids, folder):
    """Each photo in its own folder (000, 001...), in the order given."""
    args = []
    for i, photo in enumerate(ids):
        os.mkdir(os.path.join(folder, '%03d' % i))
        args += [os.path.join(folder, '%03d' % i), photo]
    if args:
        photos_app(EXPORT, args)


def fit(folder, into):
    """The album's photos (not its videos, nor repeats) fitted to the TV's 1920 x 1080, as 001.jpg on: their names."""
    photos = [os.path.join(folder, d, n) for d in sorted(os.listdir(folder))
              for n in sorted(os.listdir(os.path.join(folder, d))) if re.search(r'\.(jpe?g|heic|png|tiff?)$', n, re.I)]
    if not photos:
        return []
    fitter = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'photo_fit.swift')
    made = subprocess.run(['swift', fitter, into, str(MOST)] + photos, capture_output=True, text=True)
    names, skipped = [], []
    for line in made.stdout.splitlines():
        if line.startswith('skip\t'):
            skipped.append(line.split('\t')[1:])
        elif line:
            names.append(line)
    if skipped:
        print('Left out %d %s:' % (len(skipped), 'repeat' if len(skipped) == 1 else 'repeats'))
        for photo, like in skipped:
            print('  %s (like %s)' % (photo, like))
    return names


def send(ip, into, names):
    """Puts the photos where the app's service takes them: within 30 seconds while it's open, or when it opens next.
    It isn't opened for them: that would close the screensaver, or whatever the TV is showing."""
    key = fetch_key(ip)
    with open(os.path.join(into, 'set.txt'), 'w') as f:
        f.write('\n'.join(names))
    with tempfile.TemporaryFile() as bundle:   # one connection for them all
        with tarfile.open(fileobj=bundle, mode='w', format=tarfile.USTAR_FORMAT) as tar:
            for name in names + ['set.txt']:
                tar.add(os.path.join(into, name), arcname=name)
        bundle.seek(0)
        command = 'rm -rf {0} && mkdir -p {0} && chmod 777 {0} && tar -xf - -C {0} && chmod 666 {0}*'.format(DIR)
        if ssh(ip, key, command, stdin=bundle).returncode != 0:
            sys.exit("Couldn't reach the TV. Is it on, and Developer Mode still on?")


def make(album, ids, into):
    """The album's photos (ids, the newest first) exported and fitted into `into`: their names."""
    with tempfile.TemporaryDirectory() as exported:
        print('Getting %d photos of "%s" from Photos (photos in iCloud may take a while to download) ...'
              % (len(ids), album))
        export(ids, exported)
        print('Fitting them to the TV ...')
        return fit(exported, into)


# MARK: - --auto: run by launchd every few hours. The album is looked at once a week, and a new set waits on the Mac
# until the TV has taken it.

def state_dir(album):
    path = os.path.join(os.path.expanduser('~'), '.freemytv', 'photos', re.sub(r'[^\w.-]+', '_', album))
    os.makedirs(path, exist_ok=True)
    return path


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def write(path, text):
    with open(path, 'w') as f:
        f.write(text)


def reachable(ip):
    try:
        socket.create_connection((ip, 9922), timeout=3).close()
        return True
    except OSError:
        return False


def on_tv(ip):
    """'waiting' (sent, the app hasn't taken it yet), 'taken', or 'none' (never sent, or lost: /tmp empties at a
    restart)."""
    command = 'if [ -f {0}set.txt ]; then echo waiting; elif [ -d {0} ]; then echo taken; else echo none; fi'
    return (ssh(ip, fetch_key(ip), command.format(DIR)).stdout or '').strip()


def deliver(ip, album, pending):
    """Sends the set waiting on the Mac, quietly, until the TV has taken it."""
    if not reachable(ip):
        print('The TV is off: trying again later.')
        return
    sent = os.path.join(pending, 'sent')   # what's on the TV is this set (not another one sent by hand)
    tv = on_tv(ip) if os.path.exists(sent) else 'none'
    if tv == 'taken':
        os.replace(os.path.join(pending, 'ids.txt'), os.path.join(state_dir(album), 'sent.txt'))
        shutil.rmtree(pending)
        print('The TV took the new photos.')
    elif tv == 'waiting':
        print('On the TV: Free My TV takes them when it opens.')
    else:
        names = (read(os.path.join(pending, 'set.txt')) or '').split()
        send(ip, pending, names)
        write(sent, '')
        print('Sent %d photos: Free My TV takes them when it opens (within 30 seconds if it is open).' % len(names))


def auto(ip, album):
    state = state_dir(album)
    pending = os.path.join(state, 'pending')
    print(time.strftime('%Y-%m-%d %H:%M'), end=': ')
    if os.path.isdir(pending):
        deliver(ip, album, pending)
        return
    checked = os.path.join(state, 'checked')
    if os.path.exists(checked) and time.time() - os.path.getmtime(checked) < WEEK:
        print('Looked at "%s" less than a week ago.' % album)
        return
    was_open = subprocess.run(['pgrep', '-xq', 'Photos']).returncode == 0
    try:
        ids = newest(album)
        write(checked, '')
        if '\n'.join(ids) == read(os.path.join(state, 'sent.txt')):
            print('"%s" hasn\'t changed.' % album)
            return
        os.mkdir(pending)
        names = make(album, ids, pending)
    finally:
        if not was_open:   # it opened only for this
            subprocess.run(['osascript', '-e', 'tell application "Photos" to quit'], capture_output=True)
    write(os.path.join(pending, 'set.txt'), '\n'.join(names))
    write(os.path.join(pending, 'ids.txt'), '\n'.join(ids))
    deliver(ip, album, pending)


def main():
    args = sys.argv[1:]
    if len(args) not in (2, 3) or not re.match(r'^\d{1,3}(\.\d{1,3}){3}$', args[0]):
        sys.exit(__doc__)
    ip, album = args[:2]
    if len(args) == 3 and args[2] != '--auto' or album.startswith('--') and album != '--clear':
        sys.exit(__doc__)
    if album != '--clear' and sys.platform != 'darwin':
        sys.exit('This takes the album from the Photos app, so it runs on a Mac.')
    if len(args) == 3:
        auto(ip, album)
        return
    with tempfile.TemporaryDirectory() as into:
        if album == '--clear':
            send(ip, into, [])
            print('Sent. Free My TV takes your photos off the screensaver within 30 seconds if it is open, '
                  'or when it opens.')
            return
        ids = newest(album)
        names = make(album, ids, into)
        if not names:
            sys.exit('The album has no photos (videos are left out).')
        print('Sending %d photos to the TV ...' % len(names))
        send(ip, into, names)
        # --auto needn't send these again, and a set it had waiting is older.
        state = state_dir(album)
        write(os.path.join(state, 'sent.txt'), '\n'.join(ids))
        shutil.rmtree(os.path.join(state, 'pending'), ignore_errors=True)
        print('Sent. Free My TV takes them within 30 seconds if it is open, or when it opens: '
              'the old ones show until then.')


if __name__ == '__main__':
    main()
