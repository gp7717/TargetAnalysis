import re
import json
import time
import random
import argparse
from urllib.parse import urljoin, urlparse

from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


CATALOG_URL = "https://www.target.com/c/handbags-purses-accessories/-/N-5xtbo"

# Only scrape products that are present in the initially loaded catalog HTML
# (i.e., no scrolling / no pagination / no infinite-load).
DEFAULT_MAX_PRODUCTS = 10

# Working proxies (tested and verified)
PROXY_IPS = [
    "http://195.158.8.123:3128",
    "http://136.49.32.180:8888",
    "http://72.56.59.17:61931",
    "http://104.238.30.58:63744",
    "http://72.56.59.62:63133",
    "http://72.56.59.23:61937",
    "http://104.238.30.86:63900",
]

DEFAULT_SOCKS_PORTS = [4145, 1080, 5678]
DEFAULT_HTTP_PORTS = [8080, 3128, 80]

# Random delay range between requests (seconds)
DEFAULT_DELAY_MIN_S = 1.0
DEFAULT_DELAY_MAX_S = 3.5


def _parse_proxy_entry(entry: str) -> list[dict]:
    """Return a list of Playwright proxy dicts for a given entry.

    Supported input formats:
    - "ip" (we will expand with common ports/schemes)
    - "ip:port"
    - "scheme://ip:port" where scheme in {http, https, socks5}
    """
    entry = entry.strip()
    if not entry:
        return []

    if "://" in entry:
        return [{"server": entry}]

    if ":" in entry:
        host, port_str = entry.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            return []

        # Heuristic: avoid trying HTTP on common SOCKS ports (and vice-versa).
        if port in DEFAULT_SOCKS_PORTS:
            schemes = ["socks5"]
        else:
            schemes = ["http"]
        return [{"server": f"{scheme}://{host}:{port}"} for scheme in schemes]

    # IP only
    candidates: list[dict] = []
    for port in DEFAULT_SOCKS_PORTS:
        candidates.append({"server": f"socks5://{entry}:{port}"})
    for port in DEFAULT_HTTP_PORTS:
        candidates.append({"server": f"http://{entry}:{port}"})
    return candidates


def load_proxy_entries_from_file(path: str) -> list[str]:
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"Proxy file not found: {path}")

    entries: list[str] = []
    for raw in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Support CSV or whitespace separated formats
        for token in re.split(r"[\s,]+", line):
            token = token.strip()
            if token:
                entries.append(token)
    return entries


def build_proxy_pool(entries: list[str]) -> list[dict]:
    pool: list[dict] = []
    for e in entries:
        pool.extend(_parse_proxy_entry(e))
    # de-dupe while preserving order
    seen = set()
    uniq: list[dict] = []
    for pxy in pool:
        key = pxy.get("server")
        if not key or key in seen:
            continue
        seen.add(key)
        uniq.append(pxy)
    return uniq


def random_delay(delay_min_s: float, delay_max_s: float):
    if delay_max_s <= 0:
        return
    lo = max(0.0, float(delay_min_s))
    hi = max(lo, float(delay_max_s))
    time.sleep(random.uniform(lo, hi))


def is_product_url(url: str) -> bool:
    # Example product: https://www.target.com/p/.../-/A-94337711?preselect=...
    # We only want /p/ URLs that contain "/-/A-<digits>"
    return bool(re.search(r"^https?://www\.target\.com/p/.+/-/A-\d+", url))


def normalize_url(url: str) -> str:
    # Remove fragments; keep query (sometimes preselect matters)
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl()


def extract_product_links_from_catalog(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.select("a[href]"):
        href = a.get("href", "").strip()
        if not href:
            continue
        full = urljoin("https://www.target.com", href)
        full = normalize_url(full)
        if is_product_url(full):
            links.append(full)

    # de-dupe while preserving order
    seen = set()
    uniq = []
    for u in links:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def extract_next_data_json(html: str) -> dict | None:
    """
    Target pages are often Next.js and include a <script id="__NEXT_DATA__"> JSON blob.
    If present, this is the cleanest way to parse product data.
    """
    soup = BeautifulSoup(html, "lxml")
    tag = soup.select_one('script#__NEXT_DATA__')
    if not tag or not tag.string:
        return None
    try:
        return json.loads(tag.string)
    except Exception:
        return None


def pick_first(d: dict, paths: list[list[str]]):
    """
    Try multiple nested key paths; return the first match.
    """
    for path in paths:
        cur = d
        ok = True
        for k in path:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                ok = False
                break
        if ok:
            return cur
    return None


def parse_product_fields(html: str, url: str) -> dict:
    """
    Best-effort extraction:
    - Title is typically in <h1> or in __NEXT_DATA__
    - Price may be in page text or __NEXT_DATA__
    - TCIN can be pulled from /-/A-<id>
    """
    tcin_match = re.search(r"/-/A-(\d+)", url)
    tcin = tcin_match.group(1) if tcin_match else None

    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    title_from_h1 = h1.get_text(strip=True) if h1 else None

    next_data = extract_next_data_json(html)

    # Because Target’s internal JSON shape can vary, we keep this flexible.
    title_from_next = None
    price_from_next = None
    rating_from_next = None
    review_count_from_next = None

    if next_data:
        # These paths are “best guess” and can change. Keep fallbacks.
        title_from_next = pick_first(next_data, [
            ["props", "pageProps", "dehydratedState", "queries", "0", "state", "data", "product", "item", "product_description", "title"],
            ["props", "pageProps", "product", "title"],
        ])

        # price example paths (varies a lot)
        price_from_next = pick_first(next_data, [
            ["props", "pageProps", "dehydratedState", "queries", "0", "state", "data", "product", "price", "formatted_current_price"],
            ["props", "pageProps", "product", "price", "formatted_current_price"],
        ])

        rating_from_next = pick_first(next_data, [
            ["props", "pageProps", "dehydratedState", "queries", "0", "state", "data", "product", "ratings_and_reviews", "statistics", "rating", "average"],
        ])
        review_count_from_next = pick_first(next_data, [
            ["props", "pageProps", "dehydratedState", "queries", "0", "state", "data", "product", "ratings_and_reviews", "statistics", "rating", "count"],
        ])

    # Fallback price extraction from visible text (imperfect)
    price_text = None
    m = re.search(r"\$\d+(?:\.\d{2})?", soup.get_text(" ", strip=True))
    if m:
        price_text = m.group(0)

    return {
        "url": url,
        "tcin": tcin,
        "title": title_from_next or title_from_h1,
        "price": price_from_next or price_text,
        "rating_avg": rating_from_next,
        "review_count": review_count_from_next,
    }


def fetch_html_with_proxy_rotation(
    browser,
    url: str,
    proxy_pool: list[dict],
    *,
    timeout_ms: int = 30000,
    max_attempts: int = 6,
    delay_min_s: float = DEFAULT_DELAY_MIN_S,
    delay_max_s: float = DEFAULT_DELAY_MAX_S,
    verbose: bool = False,
) -> tuple[str, str | None]:
    """Fetch page HTML, rotating proxies on failure.

    Returns (html, proxy_server_used).
    """
    if not proxy_pool:
        proxy_pool = [{"server": None}]

    last_err: Exception | None = None
    candidates = proxy_pool[:]
    random.shuffle(candidates)

    attempts = 0
    last_server: str | None = None
    while attempts < max_attempts:
        proxy = candidates[attempts % len(candidates)]
        proxy_server = proxy.get("server")
        # Avoid hammering the same proxy twice in a row if we have >1 choice.
        if len(candidates) > 1 and proxy_server == last_server:
            attempts += 1
            continue

        context = None
        try:
            # Random delay before each fetch attempt (helps reduce burstiness).
            random_delay(delay_min_s, delay_max_s)
            if verbose:
                proxy_label = proxy_server or "(no proxy)"
                print(f"  Attempt {attempts + 1}/{max_attempts}: trying {proxy_label}")
            context = browser.new_context(
                proxy={"server": proxy_server} if proxy_server else None,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"
                ),
                ignore_https_errors=True,
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            html = page.content()
            if verbose:
                print(f"  ✓ Success with {proxy_server or '(no proxy)'}")
            return html, proxy_server
        except Exception as e:
            last_err = e
            last_server = proxy_server
            if verbose:
                print(f"  ✗ Failed: {type(e).__name__}: {str(e)[:80]}")
        finally:
            try:
                if context:
                    context.close()
            except Exception:
                pass
        attempts += 1

    raise RuntimeError(f"Failed to fetch {url} after {attempts} attempts") from last_err


def crawl_target_handbags(
    *,
    max_products: int = DEFAULT_MAX_PRODUCTS,
    delay_min_s: float = DEFAULT_DELAY_MIN_S,
    delay_max_s: float = DEFAULT_DELAY_MAX_S,
    proxy_entries: list[str] | None = None,
    timeout_ms: int = 30000,
    max_attempts: int = 6,
    verbose: bool = False,
    no_proxy: bool = False,
    fallback_no_proxy: bool = False,
):
    results = []
    if no_proxy:
        proxy_pool = [{"server": None}]
    else:
        proxy_entries = proxy_entries or PROXY_IPS
        proxy_pool = build_proxy_pool(proxy_entries)
        if verbose:
            print(f"Built proxy pool with {len(proxy_pool)} entries:")
            for p in proxy_pool[:5]:
                print(f"  - {p.get('server')}")
            if len(proxy_pool) > 5:
                print(f"  ... and {len(proxy_pool) - 5} more")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # 1) Load catalog (first page only: no scrolling)
        try:
            catalog_html, catalog_proxy = fetch_html_with_proxy_rotation(
                browser,
                CATALOG_URL,
                proxy_pool,
                timeout_ms=timeout_ms,
                max_attempts=max_attempts,
                delay_min_s=delay_min_s,
                delay_max_s=delay_max_s,
                verbose=verbose,
            )
        except Exception as e:
            if fallback_no_proxy and not no_proxy:
                print(f"\n⚠ All proxies failed, falling back to direct connection...")
                proxy_pool = [{"server": None}]
                catalog_html, catalog_proxy = fetch_html_with_proxy_rotation(
                    browser,
                    CATALOG_URL,
                    proxy_pool,
                    timeout_ms=timeout_ms,
                    max_attempts=2,
                    delay_min_s=delay_min_s,
                    delay_max_s=delay_max_s,
                    verbose=verbose,
                )
            else:
                raise
        if catalog_proxy:
            print(f"Catalog fetched via proxy: {catalog_proxy}")
        product_links = extract_product_links_from_catalog(catalog_html)
        if max_products > 0:
            product_links = product_links[:max_products]

        # 2) Visit products (rotate proxies per product)
        total = len(product_links)
        for i, link in enumerate(product_links, start=1):
            print(f"[{i}/{total}] {link}")
            html, used_proxy = fetch_html_with_proxy_rotation(
                browser,
                link,
                proxy_pool,
                timeout_ms=timeout_ms,
                max_attempts=max_attempts,
                delay_min_s=delay_min_s,
                delay_max_s=delay_max_s,
                verbose=verbose,
            )
            if used_proxy:
                print(f"  -> proxy: {used_proxy}")
            data = parse_product_fields(html, link)
            results.append(data)

            # random delay between products
            random_delay(delay_min_s, delay_max_s)

        try:
            browser.close()
        except Exception:
            pass

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Target handbags (first catalog page only)")
    parser.add_argument("--max-products", type=int, default=DEFAULT_MAX_PRODUCTS)
    parser.add_argument("--delay-min", type=float, default=DEFAULT_DELAY_MIN_S)
    parser.add_argument("--delay-max", type=float, default=DEFAULT_DELAY_MAX_S)
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument("--max-attempts", type=int, default=6)
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    parser.add_argument("--no-proxy", action="store_true", help="Disable proxy usage (direct connection)")
    parser.add_argument(
        "--fallback-no-proxy",
        action="store_true",
        help="If all proxies fail, automatically fallback to direct connection",
    )
    parser.add_argument(
        "--proxies-file",
        type=str,
        default=None,
        help="Optional file containing proxies (one per line; supports ip, ip:port, scheme://ip:port)",
    )
    parser.add_argument(
        "--proxy",
        action="append",
        default=None,
        help="Add a proxy entry (repeatable). Overrides default proxy list when provided.",
    )
    args = parser.parse_args()

    proxy_entries = None
    if args.proxies_file:
        proxy_entries = load_proxy_entries_from_file(args.proxies_file)
    if args.proxy:
        proxy_entries = (proxy_entries or []) + list(args.proxy)

    try:
        data = crawl_target_handbags(
            max_products=args.max_products,
            delay_min_s=args.delay_min,
            delay_max_s=args.delay_max,
            fallback_no_proxy=args.fallback_no_proxy,
            timeout_ms=args.timeout_ms,
            max_attempts=args.max_attempts,
            proxy_entries=proxy_entries,
            verbose=args.verbose,
            no_proxy=args.no_proxy,
        )
        print(json.dumps(data, indent=2))
    except (BrokenPipeError, ValueError):
        # Downstream consumer (e.g. `head`) closed the pipe early.
        try:
            import sys

            sys.stdout.close()
        except Exception:
            pass
        raise SystemExit(0)