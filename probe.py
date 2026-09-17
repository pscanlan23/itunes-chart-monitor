import json, urllib.request
out = []
def get(url):
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return r.status, r.read(1200).decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", "ERR"), str(e)[:200]

out.append("### movies chart feed, various limits")
for lim in (10, 25, 50, 100, 200):
    s, _ = get(f"https://rss.marketingtools.apple.com/api/v2/us/movies/top-movies/{lim}/movies.json")
    out.append(f"  limit={lim:<4} -> {s}")

out.append("\n### is the RSS API alive at all? other media types")
for p in ("apple-music/most-played/10/albums.json",
          "books/top-free/10/books.json",
          "podcasts/top/10/podcasts.json",
          "movies/top-movies/10/movies.json"):
    s, _ = get("https://rss.marketingtools.apple.com/api/v2/us/" + p)
    out.append(f"  {p:<42} -> {s}")

out.append("\n### iTunes search for the film")
for term in ("Nimrods", "Nimrods+Lee+Kirk", "Nimrods+Green+Day"):
    s, body = get(f"https://itunes.apple.com/search?term={term}&country=us&entity=movie&limit=5")
    try:
        d = json.loads(body); names = [r.get("trackName") for r in d.get("results", [])]
        out.append(f"  entity=movie term={term:<18} -> count={d.get('resultCount')} {names}")
    except Exception:
        out.append(f"  term={term} -> unparseable {body[:80]}")

s, body = get("https://itunes.apple.com/search?term=Nimrods&country=us&limit=15")
try:
    d = json.loads(body)
    out.append(f"\n### no entity filter -> count={d.get('resultCount')}")
    for r in d.get("results", [])[:15]:
        out.append(f"   {r.get('wrapperType')} | {r.get('kind')} | {r.get('trackName') or r.get('collectionName')} | {r.get('artistName')}")
except Exception:
    out.append("  unparseable")

out.append("\n### lookup of the two IDs we guessed")
for i in ("6797577735", "1474535185"):
    s, body = get(f"https://itunes.apple.com/lookup?id={i}")
    try:
        d = json.loads(body)
        if d.get("resultCount"):
            r = d["results"][0]
            out.append(f"  {i} -> {r.get('wrapperType')} | {r.get('kind')} | {r.get('trackName') or r.get('collectionName')} | {r.get('artistName')}")
        else:
            out.append(f"  {i} -> no result")
    except Exception:
        out.append(f"  {i} -> unparseable")

open("diag.txt", "w").write("\n".join(out) + "\n")
print("\n".join(out))
