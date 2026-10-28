#!/usr/bin/env python3
"""Sends an album from the Mac's Photos app to Free My TV on an LG TV, for its screensaver (instead of the picks').

    python3 webos/photos.py <TV IP> Favorites
    python3 webos/photos.py <TV IP> "Summer 2026"
    python3 webos/photos.py <TV IP> --clear

Each time, the album sent replaces the one on the TV; --clear takes them off (the picks come back). Up to 60 photos,
the newest first (videos, repeats and near copies are left out, and listed), fitted to the TV's screen
(webos/photo_fit.swift). Home Settings > My Photos turns them off and on.
macOS only (it asks the Photos app); the first time, macOS asks to allow controlling Photos. Install Free My TV first
(webos/install.py): this uses its key.
"""
import os
import re
import subprocess
import sys
import tarfile
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from install import APP_ID, fetch_key, luna, ssh   # noqa: E402

DIR = '/tmp/freemytv-photos/'   # where the app's service takes them from (webos/service)
MOST = 60
EXPORTED = 100   # more than MOST, so the repeats left out leave room for others

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
  tell application "Photos"
    repeat with i from 1 to (count of argv) by 2
      set destination to POSIX file (item i of argv)
      export {media item id (item (i + 1) of argv)} to (destination as alias) without using originals
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


def export(album, folder):
    """The album's newest EXPORTED photos, each in its own folder (000, 001...), the newest first."""
    listed = [line.split('\t') for line in photos_app(LIST, [album]).splitlines() if line.count('\t') == 2]
    newest = sorted(listed, key=lambda x: (int(x[0]), int(float(x[1]))), reverse=True)[:EXPORTED]
    args = []
    for i, (_, _, photo) in enumerate(newest):
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
    luna(ip, key, 'luna://com.webos.applicationManager/launch', {'id': APP_ID})


def main():
    args = sys.argv[1:]
    if len(args) != 2 or not re.match(r'^\d{1,3}(\.\d{1,3}){3}$', args[0]):
        sys.exit(__doc__)
    ip, album = args
    with tempfile.TemporaryDirectory() as work:
        into = os.path.join(work, 'tv')
        os.mkdir(into)
        if album == '--clear':
            send(ip, into, [])
            print('Sent. The TV takes your photos off its screensaver now.')
            return
        if album.startswith('--'):
            sys.exit(__doc__)
        if sys.platform != 'darwin':
            sys.exit('This takes the album from the Photos app, so it runs on a Mac.')
        exported = os.path.join(work, 'photos')
        os.mkdir(exported)
        print('Getting "%s" from Photos (photos in iCloud may take a while to download) ...' % album)
        export(album, exported)
        print('Fitting them to the TV ...')
        names = fit(exported, into)
        if not names:
            sys.exit('The album has no photos (videos are left out).')
        print('Sending %d photos to the TV ...' % len(names))
        send(ip, into, names)
        print('Sent. The TV shows how far it got; then they are on its screensaver.')


if __name__ == '__main__':
    main()
