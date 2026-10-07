"""Kumpulkan berita + media sosial tentang Kabupaten Bandung, nilai sentimen dengan Claude, tulis data.json."""
import os, re, json, html, datetime as dt, urllib.parse
from concurrent.futures import ThreadPoolExecutor
import feedparser, requests

TOPICS = {
 "Pemkab": ("Pemerintah Kabupaten Bandung", ["Pemkab Bandung", "Bupati Bandung", "Pemerintah Kabupaten Bandung"], ["pelayanan publik", "APBD", "bupati", "ASN"]),
 "Politik": ("Situasi politik", ["DPRD Kabupaten Bandung", "politik Kabupaten Bandung"], ["DPRD", "partai", "pilkada"]),
 "Ekonomi": ("Situasi ekonomi", ["ekonomi Kabupaten Bandung", "UMKM Kabupaten Bandung", "industri Kabupaten Bandung"], ["UMKM", "inflasi", "investasi"]),
 "Hukum": ("Situasi hukum", ["hukum Kabupaten Bandung", "korupsi Kabupaten Bandung", "Kejari Soreang"], ["korupsi", "kejaksaan", "pungli"]),
 "Infrastruktur": ("Jalan, banjir, transportasi", ["banjir Kabupaten Bandung", "jalan rusak Kabupaten Bandung"], ["banjir", "jalan rusak", "Baleendah"]),
 "Sosial": ("Pendidikan, kesehatan, kebencanaan", ["pendidikan Kabupaten Bandung", "stunting Kabupaten Bandung", "kesehatan Kabupaten Bandung"], ["pendidikan", "stunting", "bansos"]),
}
HARI = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
WIB = dt.timezone(dt.timedelta(hours=7))
MODEL = "claude-haiku-4-5-20251001"  # hanya dipakai bila USE_CLAUDE=1
LOCAL_MODEL = "w11wo/indonesian-roberta-base-sentiment-classifier"  # gratis, jalan di GitHub Actions
CACHE = "cache.json"
SOCIAL_EVERY_HOURS = int(os.getenv("SOCIAL_EVERY_HOURS", "4"))  # hemat kuota YouTube
_client = None
_warned = False


def claude():
    global _client
    import anthropic
    _client = _client or anthropic.Anthropic()
    return _client


def fetch_rss(q):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": f'"{q}" when:7d', "hl": "id", "gl": "ID", "ceid": "ID:id"})
    out = []
    for e in feedparser.parse(url).entries:
        if getattr(e, "published_parsed", None):
            d = dt.datetime(*e.published_parsed[:6], tzinfo=dt.timezone.utc).astimezone(WIB)
            out.append({"t": e.title, "x": "", "u": e.link, "r": e.get("source", {}).get("title", ""),
                        "date": str(d.date()), "ts": d.isoformat()})
    return out


def excerpt(url):
    """Ambil isi artikel asli (tautan Google News dibuka dulu). Gagal -> kosong, sentimen pakai judul."""
    try:
        from googlenewsdecoder import gnewsdecoder
        import trafilatura
        real = gnewsdecoder(url, interval=1).get("decoded_url")
        return (trafilatura.extract(trafilatura.fetch_url(real)) or "")[:1200]
    except Exception as ex:
        global _warned
        if not _warned:  # cukup sekali, agar log tidak penuh
            print("isi artikel gagal (hanya pesan pertama ditampilkan):", ex)
            _warned = True
        return ""


def youtube(q, key):
    after = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = requests.get("https://www.googleapis.com/youtube/v3/search", timeout=30, params={
        "part": "snippet", "q": q, "type": "video", "order": "date", "maxResults": 25, "regionCode": "ID",
        "relevanceLanguage": "id", "publishedAfter": after, "key": key}).json()
    return [{"t": html.unescape(i["snippet"]["title"]), "x": html.unescape(i["snippet"]["description"])[:400],
             "u": "https://www.youtube.com/watch?v=" + i["id"]["videoId"],
             "r": "YouTube " + html.unescape(i["snippet"]["channelTitle"]), "date": i["snippet"]["publishedAt"][:10]}
            for i in r.get("items", [])]


def x_posts(q, token):
    r = requests.get("https://api.twitter.com/2/tweets/search/recent", timeout=30,
                     headers={"Authorization": "Bearer " + token},
                     params={"query": f'"{q}" lang:id -is:retweet', "max_results": 30, "tweet.fields": "created_at"}).json()
    return [{"t": d["text"][:280], "x": "", "u": "https://x.com/i/web/status/" + d["id"], "r": "X",
             "date": d["created_at"][:10]} for d in r.get("data", [])]


def safe(fn, *a):
    try:
        return fn(*a)
    except Exception as ex:
        print(fn.__name__, "gagal:", ex)
        return []


def label_claude(items):
    """Isi it['s'] (pos/neu/neg) dan it['rel'] (benar-benar tentang Kab. Bandung) untuk tiap item."""
    for i in range(0, len(items), 20):
        chunk = items[i:i + 20]
        lines = "\n".join(f"{j}. {it['t']} | {it['x'][:600]}" for j, it in enumerate(chunk))
        prompt = ("Nilai tiap berita atau unggahan (format: judul | kutipan isi). 's' = sentimen terhadap "
                  "Kabupaten Bandung atau pemerintahnya: 'pos', 'neu', atau 'neg'. 'rel' = true hanya jika benar-benar "
                  "tentang Kabupaten Bandung (bukan Kota Bandung atau Bandung Barat). Balas HANYA JSON array: "
                  '[{"i":0,"s":"pos","rel":true}]\n\n' + lines)
        try:
            r = claude().messages.create(model=MODEL, max_tokens=2000, messages=[{"role": "user", "content": prompt}])
            res = {x["i"]: x for x in json.loads(re.search(r"\[.*\]", r.content[0].text, re.S).group(0))}
        except Exception as ex:
            print("penilaian gagal:", ex)
            continue
        for j, it in enumerate(chunk):
            x = res.get(j)
            if x and x.get("s") in ("pos", "neu", "neg"):
                it["s"], it["rel"] = x["s"], bool(x.get("rel"))


# ---------- Penilai gratis: model IndoRoBERTa + aturan tambahan ----------
STRONG = re.compile(r"kabupaten bandung(?! barat)|kab\.? bandung(?! barat)|pemkab bandung(?! barat)|bupati bandung(?! barat)|kejari soreang|polresta bandung", re.I)
WEAK = re.compile(r"soreang|baleendah|dayeuhkolot|banjaran|majalaya|ciparay|pangalengan|rancaekek|cileunyi|margahayu|katapang|cicalengka|bojongsoang|ciwidey|pasirjambu|kutawaringin|cangkuang|arjasari|pameungpeuk|paseh|kertasari|nagreg|cimenyan|cilengkrang|rancabali|margaasih|solokanjeruk|cimaung|cikancung", re.I)
OTHER = re.compile(r"kota bandung|bandung barat|cimahi", re.I)
NEG_CUE = re.compile(r"korupsi|tersangka|ditangkap|ditahan|tewas|meninggal|banjir|longsor|kecelakaan|pungli|protes|demo\b|keluhkan|mengeluh|rusak|macet|kebakaran|ricuh|penipuan|dugaan|kritik|kemiskinan", re.I)
POS_CUE = re.compile(r"apresiasi|penghargaan|prestasi|juara|meningkat|sukses|diresmikan|meresmikan|berhasil|inovasi|terbaik|dukung|lancar|pulih", re.I)
_clf = None


def is_rel(it):
    text = it["t"] + " " + it["x"]
    if STRONG.search(text):
        return True
    if WEAK.search(text):
        return not OTHER.search(text)
    # tanpa isi artikel: percayai kata kunci pencarian, kecuali jelas menyebut wilayah lain
    return not it["x"] and not OTHER.search(text)


def label_local(items):
    global _clf
    if not items:
        return
    if _clf is None:
        from transformers import pipeline
        _clf = pipeline("text-classification", model=LOCAL_MODEL, truncation=True, max_length=256)
    texts = [(it["t"] + ". " + it["x"])[:1000] for it in items]
    for it, res in zip(items, _clf(texts, batch_size=16)):
        l = res["label"].lower()
        s = "pos" if ("pos" in l or l == "label_0") else "neg" if ("neg" in l or l == "label_2") else "neu"
        if s == "neu":  # judul berita cenderung dianggap netral oleh model; pakai kata penanda
            n, p = len(NEG_CUE.findall(it["t"])), len(POS_CUE.findall(it["t"]))
            s = "neg" if n > p else "pos" if p > n else "neu"
        it["s"], it["rel"] = s, is_rel(it)


def use_claude():
    return os.getenv("USE_CLAUDE") == "1" and bool(os.getenv("ANTHROPIC_API_KEY"))


def label(items):
    (label_claude if use_claude() else label_local)(items)


def agg(items, days, limit):
    ds = [str(d) for d in days]
    cnt, tp, tg, heads = {"pos": 0, "neu": 0, "neg": 0}, [0] * 7, [0] * 7, []
    for it in items:
        if not it.get("rel") or it.get("s") not in cnt or it["date"] not in ds:
            continue
        cnt[it["s"]] += 1
        if it["s"] != "neu":
            (tp if it["s"] == "pos" else tg)[ds.index(it["date"])] += 1
        if len(heads) < limit:
            heads.append({"t": it["t"], "s": it["s"], "u": it["u"], "r": it["r"]})
    return cnt, tp, tg, heads


def main():
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    labels, social = cache.setdefault("labels", {}), cache.setdefault("social", {})
    now = dt.datetime.now(WIB)
    days = [now.date() - dt.timedelta(days=6 - i) for i in range(7)]
    yt, xt = os.getenv("YOUTUBE_API_KEY"), os.getenv("X_BEARER_TOKEN")
    last = cache.get("social_at")
    do_social = bool(yt or xt) and (not last or (now - dt.datetime.fromisoformat(last)).total_seconds() >= SOCIAL_EVERY_HOURS * 3600 - 300)
    topics = []
    for name, (desc, qs, kw) in TOPICS.items():
        seen = {}
        for q in qs:
            for it in safe(fetch_rss, q):
                seen.setdefault(it["u"], it)
        web = sorted(seen.values(), key=lambda i: i["ts"], reverse=True)[:60]
        new = [i for i in web if i["u"] not in labels][:20]  # hanya yang baru, agar hemat biaya
        with ThreadPoolExecutor(4) as ex:
            for it, x in zip(new, ex.map(lambda i: excerpt(i["u"]), new)):
                it["x"] = x
        label(new)
        for it in new:
            if "s" in it:
                labels[it["u"]] = {"s": it["s"], "rel": it["rel"]}
        for it in web:
            it.update(labels.get(it["u"], {}))
        if do_social:
            posts = (safe(youtube, qs[0], yt) if yt else []) + (safe(x_posts, qs[0], xt) if xt else [])
            label(posts)
            posts = sorted((p for p in posts if "s" in p), key=lambda p: p["date"], reverse=True)
            if posts:
                social[name] = posts
        cw, pw, gw, hw = agg(web, days, 3)
        cs, ps, gs, hs = agg(social.get(name, []), days, 2)
        topics.append({"n": name, "d": desc, "k": kw, "h": hw + hs,
                       "v": {"s": [cs["pos"], cs["neu"], cs["neg"]], "w": [cw["pos"], cw["neu"], cw["neg"]]},
                       "trend": {"d": [HARI[x.weekday()] for x in days],
                                 "p": [a + b for a, b in zip(pw, ps)], "g": [a + b for a, b in zip(gw, gs)]}})
    if do_social:
        cache["social_at"] = now.isoformat()
    if len(labels) > 3000:
        for k in list(labels)[:len(labels) - 3000]:
            del labels[k]
    sources = ["Google News RSS"] + sorted({p["r"].split()[0] for ps in social.values() for p in ps})
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"updated": now.isoformat(), "sources": sources, "method": "Claude" if use_claude() else "model IndoRoBERTa, gratis", "topics": topics},
              open("data.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
