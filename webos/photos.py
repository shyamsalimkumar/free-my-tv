#!/usr/bin/env python3
"""Sends an album from the Mac's Photos app to Free My TV on an LG TV, for its screensaver (instead of the picks').

    python3 webos/photos.py <TV IP> Favorites
    python3 webos/photos.py <TV IP> "Summer 2026"
    python3 webos/photos.py <TV IP> --clear

Each time, the album sent replaces the one on the TV; --clear takes them off (the picks come back). Up to 60 photos
(the album's first; videos are left out), fitted to the TV's screen (webos/photo_fit.swift). Home Settings >
My Photos turns them off and on.
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

# Exports the album's first photos (`using originals` off: JPEG, HEIC turned into JPEG) into a folder.
EXPORT = '''
on run argv
  set destination to POSIX file (item 1 of argv)
  set wanted to item 2 of argv
  set limit to (item 3 of argv) as integer
  tell application "Photos"
    if wanted is "Favorites" then
      set chosen to favorites album
    else
      set found to (every album whose name is wanted)
      if found is {} then error "No album called " & wanted
      set chosen to item 1 of found
    end if
    set picked to media items of chosen
    if (count of picked) > limit then set picked to items 1 thru limit of picked
    export picked to (destination as alias) without using originals
    return count of picked
  end tell
end run
'''


def export(album, folder):
    out = subprocess.run(['osascript', '-e', EXPORT, folder, album, str(MOST)], capture_output=True, text=True)
    if out.returncode != 0:
        why = out.stderr.strip()
        if 'No album called' in why:
            sys.exit('There\'s no album called "%s" in Photos. Check its name (capitals count).' % album)
        if 'Not authorized' in why or '-1743' in why:
            sys.exit('macOS didn\'t allow controlling Photos. Allow it in System Settings > Privacy & Security > '
                     'Automation, then try again.')
        sys.exit('Photos couldn\'t export the album: ' + why)


def fit(folder, into):
    """The album's photos (not its videos) fitted to the TV's 1920 x 1080, named 001.jpg on: their names."""
    photos = [os.path.join(folder, n) for n in sorted(os.listdir(folder))
              if re.search(r'\.(jpe?g|heic|png|tiff?)$', n, re.I)]
    if not photos:
        return []
    fitter = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'photo_fit.swift')
    made = subprocess.run(['swift', fitter, into] + photos, capture_output=True, text=True)
    return made.stdout.split()


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
