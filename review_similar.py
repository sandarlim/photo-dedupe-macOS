"""
review_similar.py - review Czkawka's similar_photos.txt side by side in your browser,
tick the copies you don't want, and move them into _duplicates with one click.

It only reads the text file Czkawka already made. Nothing is rescanned.

Run:
    python3 review_similar.py ~/Desktop/similar_photos.txt "/path/to/Photos"

Your browser opens the review page. Leave the Terminal window open while you review
(it is what shows the photos to the browser). Press Control+C in Terminal when you're done.

What gets pre-ticked in each group:
  - files with a SMALLER resolution than the biggest one (resized copies)
  - exact copies (byte-identical files) of a biggest-size photo, all but one; the one kept is
    the one with the shorter path
  - any other biggest-size photos (e.g. burst shots): all but one "Suggested keep" (the biggest
    file). Use "Keep only this one" on the page to pick another.
So every group keeps exactly one photo by default.
Photos in the _duplicates folder are left out.
Nothing is deleted: ticked photos are moved into <Photos folder>/_duplicates.
"""

import hashlib
import html
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# One photo line in Czkawka's report looks like:
#   "/path/to/Photos/2015-07/IMG_0001.jpg" - 4032x3024 - 2.31 MiB - High
LINE = re.compile(r'^"?(?P<path>/.+?)"?\s+-\s+(?P<w>\d+)\s*x\s*(?P<h>\d+)\s+-\s+(?P<size>.+?)(\s+-\s+(?P<sim>.*))?$')

EXTRA_TYPES = {".heic": "image/heic", ".heif": "image/heif", ".webp": "image/webp"}

# Folders directly inside the photo folder that are left out of the review
SKIP_FOLDERS = {"_duplicates"}

GROUPS = []         # every group from the report
PHOTOS = {}         # photo id -> path; the browser may only see/move these files
ROOT = None         # the Photos folder
FINGERPRINTS = {}   # remembered file fingerprints


# ---------------------------------------------------------------- reading the report

def read_report(report_path):
    """Return a list of groups; each group is a list of photos (dicts).
    A blank line or a 'Found N images...' heading ends a group."""
    groups, current = [], []
    for raw in report_path.read_text(errors="replace").splitlines():
        match = LINE.match(raw.strip())
        if match:
            current.append({
                "id": len(PHOTOS),
                "path": Path(match["path"]),
                "w": int(match["w"]),
                "h": int(match["h"]),
                "size": match["size"].strip(),
            })
            PHOTOS[current[-1]["id"]] = current[-1]["path"]
        else:
            if len(current) > 1:
                groups.append(current)
            current = []
    if len(current) > 1:
        groups.append(current)
    return groups


def fingerprint(path):
    """MD5 of the file's contents (remembered, so reloading the page doesn't re-read files)."""
    info = path.stat()
    key = (str(path), info.st_size, info.st_mtime)
    if key not in FINGERPRINTS:
        md5 = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                md5.update(chunk)
        FINGERPRINTS[key] = md5.hexdigest()
    return FINGERPRINTS[key]


def keep_order(photo):
    """Which exact copy to keep: the shorter path, then alphabetical order."""
    return (len(str(photo["path"])), str(photo["path"]))


def mark_exact_copies(largest):
    """Among the largest-size photos of a group, find byte-identical files and mark all but one."""
    by_size = defaultdict(list)
    for p in largest:
        by_size[p["path"].stat().st_size].append(p)
    for same_size in by_size.values():
        if len(same_size) < 2:
            continue
        by_fingerprint = defaultdict(list)
        for p in same_size:
            try:
                by_fingerprint[fingerprint(p["path"])].append(p)
            except OSError:
                pass
        for copies in by_fingerprint.values():
            copies.sort(key=keep_order)
            for p in copies[1:]:
                p["exact"] = True


def in_skipped_folder(path):
    """True for files inside a top-level folder listed in SKIP_FOLDERS (i.e. _duplicates)."""
    try:
        parts = path.relative_to(ROOT).parts
    except ValueError:
        return False
    return len(parts) > 1 and parts[0] in SKIP_FOLDERS


def similar_keep_order(photo):
    """Which of several same-size, merely similar photos to suggest keeping:
    the biggest file (more detail), then the shorter path."""
    return (-photo["path"].stat().st_size,) + keep_order(photo)


def current_groups():
    """Groups as they are right now: skip files already moved, biggest first, and decide
    what to pre-tick so that every group keeps exactly one photo by default:
      1. smaller copies
      2. exact copies of a largest-size photo (all but one)
      3. whatever largest-size photos are still left (e.g. bursts): all but one suggested keep"""
    ready = []
    for group in GROUPS:
        photos = [p for p in group if p["path"].is_file() and not in_skipped_folder(p["path"])]
        if len(photos) < 2:
            continue
        photos.sort(key=lambda p: (-(p["w"] * p["h"]), str(p["path"])))
        biggest = photos[0]["w"] * photos[0]["h"]
        for p in photos:
            p["smaller"] = p["w"] * p["h"] < biggest
            p["exact"] = False
            p["similar"] = False
            p["keep"] = False
        largest = [p for p in photos if not p["smaller"]]
        if len(largest) > 1:
            mark_exact_copies(largest)
        remaining = sorted((p for p in largest if not p["exact"]), key=similar_keep_order)
        remaining[0]["keep"] = True
        for p in remaining[1:]:
            p["similar"] = True
        ready.append(photos)
    return ready


# ---------------------------------------------------------------- moving files

def move_to_duplicates(paths):
    """Move each file into ROOT/_duplicates, keeping its subfolder. Returns (moved, problems)."""
    duplicates_folder = ROOT / "_duplicates"
    moved, problems = 0, []
    for source in paths:
        if not source.is_file():
            problems.append(f"Not found (already moved?): {source.name}")
            continue
        try:
            relative = source.relative_to(ROOT)
        except ValueError:
            problems.append(f"Outside the photo folder: {source}")
            continue
        destination = duplicates_folder / relative
        if destination.exists():
            problems.append(f"Already in _duplicates: {relative}")
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
            moved += 1
        except OSError as error:
            problems.append(f"Couldn't move {source.name}: {error}")
    return moved, problems


# ---------------------------------------------------------------- the page

def photo_html(photo):
    path = photo["path"]
    try:
        folder = str(path.parent.relative_to(ROOT)) or "."
    except ValueError:
        folder = str(path.parent)
    url = f"/photo/{photo['id']}/{html.escape(path.name)}"
    suggested = photo["smaller"] or photo["exact"] or photo["similar"]
    if photo["smaller"]:
        label = "Smaller copy"
    elif photo["exact"]:
        label = "Exact copy"
    elif photo["similar"]:
        label = "Similar, same size"
    else:
        label = "Suggested keep"
    badge = "small" if suggested else "big"
    checked = " checked" if suggested else ""
    return f"""
      <figure>
        <a href="{url}" target="_blank" title="Open full size">
          <img src="{url}" loading="lazy" alt="" onerror="this.classList.add('broken')">
        </a>
        <figcaption>
          <div class="name">{html.escape(path.name)}</div>
          <div class="muted">{html.escape(folder)}</div>
          <div><b>{photo['w']} × {photo['h']}</b> · {html.escape(photo['size'])}
               <span class="badge {badge}">{label}</span></div>
          <label class="tick"><input type="checkbox" data-id="{photo['id']}"
                 data-suggested="{1 if suggested else 0}"{checked}> Move to _duplicates</label>
          <button type="button" class="keep-only">Keep only this one</button>
        </figcaption>
      </figure>"""


def build_page(groups):
    sections = []
    for number, photos in enumerate(groups, 1):
        sections.append(f"""
    <section class="group">
      <h2>Group {number} <span class="muted">· {len(photos)} photos</span>
          <span class="warn">Every photo in this group is ticked</span></h2>
      <div class="row">{"".join(photo_html(p) for p in photos)}</div>
    </section>""")
    if not sections:
        sections.append('<p class="help"><b>Nothing left to review.</b> You can close this tab and press Control+C in Terminal.</p>')

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Similar Photos Review</title>
<style>
  :root {{ color-scheme: light dark; --bg:#f5f5f3; --card:#fff; --ink:#1d1d1f; --muted:#6e6e73;
           --line:#e2e2df; --tick:#c2410c; --big:#15803d; --warn:#b91c1c; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#141414; --card:#1f1f1f; --ink:#f2f2f2; --muted:#a1a1a6; --line:#333;
             --tick:#fb923c; --big:#4ade80; --warn:#f87171; }} }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
          font:14px/1.45 -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif; }}
  header {{ position:sticky; top:0; z-index:5; background:var(--card); border-bottom:1px solid var(--line);
            padding:12px 20px; display:flex; flex-wrap:wrap; gap:10px 18px; align-items:center; }}
  header h1 {{ font-size:16px; margin:0; }}
  button {{ font:inherit; padding:6px 12px; border-radius:7px; border:1px solid var(--line);
            background:var(--bg); color:var(--ink); cursor:pointer; }}
  button.primary {{ background:var(--tick); border-color:var(--tick); color:#fff; font-weight:600; }}
  button:disabled {{ opacity:.5; cursor:default; }}
  .muted {{ color:var(--muted); font-weight:normal; }}
  .help {{ margin:14px 20px 0; color:var(--muted); max-width:900px; }}
  .group {{ background:var(--card); border:1px solid var(--line); border-radius:12px; margin:16px 20px; padding:12px 14px; }}
  .group h2 {{ font-size:14px; margin:0 0 10px; }}
  .warn {{ display:none; color:var(--warn); margin-left:10px; }}
  .group.all-ticked {{ border-color:var(--warn); }}
  .group.all-ticked .warn {{ display:inline; }}
  .row {{ display:flex; gap:12px; overflow-x:auto; padding-bottom:4px; }}
  figure {{ margin:0; flex:0 0 280px; border:2px solid transparent; border-radius:10px; padding:6px; }}
  figure.ticked {{ border-color:var(--tick); }}
  figure.ticked img {{ opacity:.55; }}
  img {{ display:block; width:100%; height:240px; object-fit:contain; background:rgba(127,127,127,.12); border-radius:6px; }}
  img.broken {{ visibility:hidden; }}
  a:has(img.broken)::before {{ content:"Can't show this format here - click to open"; display:block; height:240px;
                              line-height:240px; text-align:center; color:var(--muted); font-size:12px;
                              background:rgba(127,127,127,.12); border-radius:6px; }}
  a:has(img.broken) img {{ display:none; }}
  figcaption {{ margin-top:6px; font-size:13px; }}
  .name {{ font-weight:600; word-break:break-all; }}
  .badge {{ font-size:11px; padding:1px 6px; border-radius:999px; margin-left:4px; white-space:nowrap; }}
  .badge.small {{ color:var(--tick); border:1px solid var(--tick); }}
  .badge.big {{ color:var(--big); border:1px solid var(--big); }}
  .tick {{ display:block; margin-top:4px; cursor:pointer; }}
  .keep-only {{ margin-top:6px; padding:3px 9px; font-size:12px; }}
</style></head>
<body>
<header>
  <h1>Similar photos · {len(groups)} groups</h1>
  <span><b id="count">0</b> ticked</span>
  <button id="suggested">Reset to suggested</button>
  <button id="none">Untick all</button>
  <button id="move" class="primary">Move ticked to _duplicates</button>
</header>
<p class="help">Every group keeps one photo by default (green <b>Suggested keep</b>); the rest are ticked.
For bursts, the suggestion is just the biggest file, so check for closed eyes and use <b>Keep only this one</b>
on the photo you prefer. Click a photo to open it full size. Nothing is deleted; ticked photos
are moved into the <b>_duplicates</b> folder. Keep the Terminal window open while you use this page.</p>
{"".join(sections)}
<script>
  const boxes = [...document.querySelectorAll('input[type=checkbox]')];
  function update() {{
    let n = 0;
    boxes.forEach(b => {{ b.closest('figure').classList.toggle('ticked', b.checked); if (b.checked) n++; }});
    document.querySelectorAll('.group').forEach(g => {{
      const bs = [...g.querySelectorAll('input[type=checkbox]')];
      g.classList.toggle('all-ticked', bs.length > 0 && bs.every(b => b.checked));
    }});
    document.getElementById('count').textContent = n;
  }}
  boxes.forEach(b => b.addEventListener('change', update));
  document.querySelectorAll('.keep-only').forEach(button => button.onclick = () => {{
    const mine = button.closest('figure').querySelector('input[type=checkbox]');
    button.closest('.group').querySelectorAll('input[type=checkbox]').forEach(b => b.checked = (b !== mine));
    update();
  }});
  document.getElementById('suggested').onclick = () => {{ boxes.forEach(b => b.checked = b.dataset.suggested === '1'); update(); }};
  document.getElementById('none').onclick = () => {{ boxes.forEach(b => b.checked = false); update(); }};
  document.getElementById('move').onclick = async (event) => {{
    const ids = boxes.filter(b => b.checked).map(b => Number(b.dataset.id));
    if (!ids.length) {{ alert('Nothing is ticked.'); return; }}
    const allTicked = document.querySelectorAll('.group.all-ticked').length;
    let question = 'Move ' + ids.length + ' photo(s) into _duplicates?';
    if (allTicked) question += '\\n\\nWarning: in ' + allTicked + ' group(s) every photo is ticked, so nothing from them stays in place.';
    if (!confirm(question)) return;
    event.target.disabled = true;
    try {{
      const response = await fetch('/move', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(ids) }});
      const result = await response.json();
      let message = 'Moved ' + result.moved + ' photo(s) into _duplicates.';
      if (result.problems.length) message += '\\n\\n' + result.problems.slice(0, 15).join('\\n');
      alert(message);
      location.reload();
    }} catch (error) {{
      alert("Couldn't reach the script. Is the Terminal window still running it?");
      event.target.disabled = false;
    }}
  }};
  update();
</script>
</body></html>
"""


# ---------------------------------------------------------------- the little local web server

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # keep Terminal quiet

    def send_body(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            if self.path in ("/", "/index.html"):
                page = build_page(current_groups()).encode("utf-8")
                self.send_body(200, "text/html; charset=utf-8", page)
            elif self.path.startswith("/photo/"):
                self.send_photo()
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the browser stopped loading something; harmless

    def send_photo(self):
        try:
            path = PHOTOS[int(self.path.split("/")[2])]
        except (ValueError, IndexError, KeyError):
            return self.send_error(404)
        if not path.is_file():
            return self.send_error(404)
        content_type = EXTRA_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile)

    def do_POST(self):
        if self.path != "/move":
            return self.send_error(404)
        length = int(self.headers.get("Content-Length", 0))
        ids = json.loads(self.rfile.read(length) or b"[]")
        paths = [PHOTOS[i] for i in ids if isinstance(i, int) and i in PHOTOS]
        moved, problems = move_to_duplicates(paths)
        print(f"Moved {moved} photo(s) into {ROOT / '_duplicates'}")
        self.send_body(200, "application/json", json.dumps({"moved": moved, "problems": problems}).encode())


def start_server():
    for port in range(8765, 8785):
        try:
            return ThreadingHTTPServer(("127.0.0.1", port), Handler)
        except OSError:
            continue
    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def main():
    global GROUPS, ROOT
    args = sys.argv[1:]
    if not 1 <= len(args) <= 2:
        print(__doc__)
        return
    report = Path(args[0]).expanduser()
    if not report.is_file():
        sys.exit(f"Report not found: {report}")
    GROUPS = read_report(report)
    if not GROUPS:
        sys.exit("No groups found in the report. Paste a few lines of it to Claude so the script can be adjusted.")
    if len(args) == 2:
        ROOT = Path(args[1]).expanduser()
    else:
        ROOT = Path(os.path.commonpath([str(p.parent) for p in PHOTOS.values()]))

    print("Checking for exact copies...")
    groups = current_groups()
    smaller = sum(p["smaller"] for g in groups for p in g)
    exact = sum(p["exact"] for g in groups for p in g)
    similar = sum(p["similar"] for g in groups for p in g)
    server = start_server()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"{len(groups)} groups. Pre-ticked: {smaller} smaller copies, {exact} exact copies, "
          f"{similar} similar same-size photos.")
    print(f"Review page: {url}")
    print("Leave this window open while you review. Press Control+C here when you're done.")
    try:
        # Open in Google Chrome; if Chrome isn't installed, use the default browser.
        if subprocess.run(["open", "-a", "Google Chrome", url], check=False).returncode != 0:
            subprocess.run(["open", url], check=False)
    except OSError:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
