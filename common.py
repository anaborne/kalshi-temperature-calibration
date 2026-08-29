"""Shared plumbing: polite HTTP with retries, raw-first caching, paths.

Rule from PREREGISTRATION.md: raw responses land on disk before any parsing,
and everything downstream is reproducible from cache.
"""
import concurrent.futures
import json
import os
import random
import threading
import time

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(DATA, "raw")



def short(path):
    """Render a path relative to the repo root.

    Run logs are committed, so anything printed here is published. An absolute
    path publishes the operator's home directory along with it; nothing
    downstream needs that, so paths are logged relative to ROOT.
    """
    try:
        return os.path.relpath(path, ROOT)
    except ValueError:              # different volume on Windows
        return path


KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
IEM = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"

USER_AGENT = "kalshi-temperature-calibration/0.1 (offline backtest; contact via github)"

# Politeness floor between requests to the same host, seconds. Raised via
# TV_MIN_INTERVAL when two pulls run against the same host concurrently, so the
# combined rate stays where a single pull would have put it.
MIN_INTERVAL = float(os.environ.get("TV_MIN_INTERVAL", "0.30"))

# Bounded concurrency. The politeness floor is enforced across all workers by a
# shared lock, so WORKERS threads at MIN_INTERVAL still produce one request per
# MIN_INTERVAL to a host. Concurrency hides latency, it does not raise the
# request rate. Raise TV_RATE to actually go faster.
WORKERS = int(os.environ.get("TV_WORKERS", "1"))
RATE = float(os.environ.get("TV_RATE", "0")) or None  # requests/sec, host-wide

_last_call = {}
_rate_lock = threading.Lock()


def ensure(path):
    os.makedirs(path, exist_ok=True)
    return path


def _throttle(host):
    """Serialise the inter-request gap across every worker thread."""
    interval = (1.0 / RATE) if RATE else MIN_INTERVAL
    with _rate_lock:
        now = time.monotonic()
        wait = interval - (now - _last_call.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()


def parallel_map(fn, items, workers=None, on_result=None):
    """Run fn over items with bounded concurrency, preserving throttle order.

    Results are surfaced as they complete via on_result(index, item, value,
    error) so a long pull can report progress and keep going past a single
    failure rather than losing the whole run to one bad ticker.
    """
    workers = workers or WORKERS
    if workers <= 1:
        for i, item in enumerate(items):
            try:
                v, e = fn(item), None
            except Exception as exc:                      # noqa: BLE001
                v, e = None, exc
            if on_result:
                on_result(i, item, v, e)
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn, item): (i, item) for i, item in enumerate(items)}
        for fut in concurrent.futures.as_completed(futures):
            i, item = futures[fut]
            try:
                v, e = fut.result(), None
            except Exception as exc:                      # noqa: BLE001
                v, e = None, exc
            if on_result:
                on_result(i, item, v, e)


_local = threading.local()


def new_session():
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    s.headers["Accept"] = "application/json"
    a = requests.adapters.HTTPAdapter(pool_connections=32, pool_maxsize=32)
    s.mount("https://", a)
    return s


def thread_session():
    """One Session per worker thread; Session is not documented thread-safe."""
    if not hasattr(_local, "session"):
        _local.session = new_session()
    return _local.session


def get(session, url, params=None, timeout=60, tries=6):
    """GET with throttling and exponential backoff. Returns a Response."""
    host = url.split("/")[2]
    last = None
    for attempt in range(tries):
        _throttle(host)
        try:
            r = session.get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            last = e
        else:
            if r.status_code == 200:
                return r
            # 429 and 5xx are worth retrying; 4xx otherwise is not.
            if r.status_code != 429 and r.status_code < 500:
                r.raise_for_status()
            last = requests.HTTPError(f"{r.status_code} {r.text[:200]}")
        sleep = min(60.0, (2 ** attempt)) + random.uniform(0, 0.5)
        time.sleep(sleep)
    raise RuntimeError(f"GET failed after {tries} tries: {url} {params} :: {last}")


def write_raw(path, text):
    """Write a raw response body to disk unmodified (atomic)."""
    ensure(os.path.dirname(path))
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return path


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    ensure(os.path.dirname(path))
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
    os.replace(tmp, path)
    return path
