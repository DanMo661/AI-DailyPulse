import requests, io, zipfile, json, os

GH_USER = "DanMo661"
GH_REPO = "AI-DailyPulse"
GH_TOKEN = os.environ.get("GH_PAT", "")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output_cloud")

if not GH_TOKEN:
    print("Error: GH_PAT environment variable not set")
    exit(1)

auth = (GH_USER, GH_TOKEN)
r = requests.get(f'https://api.github.com/repos/{GH_USER}/{GH_REPO}/actions/artifacts',
    headers={'Accept': 'application/vnd.github+json'},
    auth=auth)
arts = r.json().get('artifacts', [])

if arts:
    a = arts[0]
    dl = requests.get(a['archive_download_url'], auth=auth)
    z = zipfile.ZipFile(io.BytesIO(dl.content))
    for f in z.namelist():
        out_path = os.path.join(OUTPUT_DIR, f)
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        if f.endswith('.md'):
            with open(out_path, 'w', encoding='utf-8') as fout:
                text = z.read(f).decode('utf-8')
                fout.write(text)
                print(f'Wrote {f} ({len(text)} chars)')
        else:
            print(f'Skipped {f}')
    print('Done')
else:
    print('No artifacts')
