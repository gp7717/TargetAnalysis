"""Quick proxy connectivity test utility.

Supports testing proxies passed on the CLI and/or loaded from a proxies file (csv/whitespace).

Examples:
  python scraper/test_proxies.py --file output/proxies.csv --timeout-ms 6000 --write-back
  python scraper/test_proxies.py http://1.2.3.4:8080 socks5://5.6.7.8:1080
"""

from __future__ import annotations

import argparse
import csv
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


_DEFAULT_SOCKS_PORTS = (4145, 1080, 5678)
_DEFAULT_HTTP_PORTS = (8080, 3128, 80)


def _load_proxy_entries_from_file(path: Path) -> List[str]:
    entries: List[str] = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for token in re.split(r"[\s,]+", line):
            token = token.strip()
            if token:
                entries.append(token)
    return entries


def _parse_proxy_entry(entry: str) -> List[str]:
    entry = (entry or "").strip()
    if not entry:
        return []

    # Already Playwright-compatible with explicit scheme
    if "://" in entry:
        return [entry]

    # host:port - infer scheme like the scraper does
    if ":" in entry:
        host, port_str = entry.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            return []
        schemes = ["socks5"] if port in _DEFAULT_SOCKS_PORTS else ["http"]
        return [f"{scheme}://{host}:{port}" for scheme in schemes]

    # host only - generate common candidates
    candidates: List[str] = []
    for port in _DEFAULT_SOCKS_PORTS:
        candidates.append(f"socks5://{entry}:{port}")
    for port in _DEFAULT_HTTP_PORTS:
        candidates.append(f"http://{entry}:{port}")
    return candidates


@dataclass
class ProxyTestResult:
    proxy: str
    ok: bool
    latency_ms: Optional[int]
    error: str
    checked_at: str


def _test_proxy(browser, proxy_server: str, url: str, timeout_ms: int) -> ProxyTestResult:
    checked_at = datetime.now().isoformat(timespec="seconds")
    context = None
    start = time.perf_counter()
    try:
        context = browser.new_context(
            proxy={"server": proxy_server},
            ignore_https_errors=True,
        )
        page = context.new_page()
        page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        _ = page.title()
        latency_ms = int((time.perf_counter() - start) * 1000)
        return ProxyTestResult(proxy=proxy_server, ok=True, latency_ms=latency_ms, error="", checked_at=checked_at)
    except (PlaywrightTimeoutError, Exception) as e:
        latency_ms = int((time.perf_counter() - start) * 1000)
        msg = f"{type(e).__name__}: {str(e).strip()}"[:300]
        return ProxyTestResult(proxy=proxy_server, ok=False, latency_ms=latency_ms, error=msg, checked_at=checked_at)
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass


def _dedupe_keep_order(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for it in items:
        if not it or it in seen:
            continue
        seen.add(it)
        out.append(it)
    return out


def _default_paths() -> Tuple[Path, Path]:
    # script is scraper/test_proxies.py; default files live in ../output
    root = Path(__file__).resolve().parent.parent
    output_dir = root / "output"
    return output_dir / "proxies.csv", output_dir


def main() -> int:
    default_file, default_out_dir = _default_paths()

    parser = argparse.ArgumentParser(description="Test proxy connectivity via Playwright")
    parser.add_argument("proxies", nargs="*", help="Proxy entries (e.g., 1.2.3.4:8080 or http://1.2.3.4:8080)")
    parser.add_argument("--file", dest="file", default=str(default_file), help="Proxy list file (csv/whitespace)")
    parser.add_argument("--url", dest="url", default="https://httpbin.org/ip", help="URL to request through the proxy")
    parser.add_argument("--timeout-ms", dest="timeout_ms", type=int, default=8000, help="Per-proxy timeout")
    parser.add_argument(
        "--write-back",
        action="store_true",
        help="Overwrite --file with working proxies only (creates a timestamped .bak first)",
    )
    parser.add_argument(
        "--working-out",
        default=str(default_out_dir / "proxies_working.csv"),
        help="Write working proxies to this file (one per line)",
    )
    parser.add_argument(
        "--results-out",
        default="",
        help="Write a detailed results CSV (default: output/proxy_test_results_<ts>.csv)",
    )
    args = parser.parse_args()

    proxies: List[str] = []
    file_path = Path(args.file)
    if file_path.exists() and file_path.is_file():
        proxies.extend(_load_proxy_entries_from_file(file_path))
    proxies.extend([p.strip() for p in (args.proxies or []) if p and p.strip()])

    if not proxies:
        print(f"No proxies to test (file not found/empty and no CLI proxies). Looked at: {file_path}")
        return 2

    # Expand entries into explicit proxy server URLs (http:// / socks5:// etc)
    expanded: List[str] = []
    for entry in proxies:
        expanded.extend(_parse_proxy_entry(entry))
    expanded = _dedupe_keep_order(expanded)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.working_out).resolve().parent
    out_dir.mkdir(parents=True, exist_ok=True)
    results_out = Path(args.results_out) if args.results_out else (out_dir / f"proxy_test_results_{ts}.csv")

    print(f"Testing {len(expanded)} proxy configurations via {args.url} (timeout {args.timeout_ms}ms)...\n")

    results: List[ProxyTestResult] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for proxy_server in expanded:
                r = _test_proxy(browser, proxy_server, args.url, args.timeout_ms)
                results.append(r)
                if r.ok:
                    print(f"✓ {proxy_server:45s}  {r.latency_ms}ms")
                else:
                    print(f"✗ {proxy_server:45s}  {r.error[:80]}")
        finally:
            try:
                browser.close()
            except Exception:
                pass

    working = [r.proxy for r in results if r.ok]
    failed = [r.proxy for r in results if not r.ok]

    # Write detailed results
    with results_out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["proxy", "ok", "latency_ms", "error", "checked_at"],
        )
        writer.writeheader()
        for r in results:
            writer.writerow(
                {
                    "proxy": r.proxy,
                    "ok": "1" if r.ok else "0",
                    "latency_ms": "" if r.latency_ms is None else str(r.latency_ms),
                    "error": r.error,
                    "checked_at": r.checked_at,
                }
            )

    # Write working list
    working_out = Path(args.working_out)
    working_out.write_text("\n".join(working) + ("\n" if working else ""), encoding="utf-8")

    # Optionally overwrite input file
    if args.write_back:
        if not file_path.exists() or not file_path.is_file():
            print(f"\n--write-back requested but file does not exist: {file_path}")
        elif not working:
            print(f"\n--write-back requested but 0 working proxies found; not overwriting {file_path}")
        else:
            backup = file_path.with_suffix(file_path.suffix + f".{ts}.bak")
            backup.write_text(file_path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
            file_path.write_text("\n".join(working) + "\n", encoding="utf-8")
            print(f"\nWrote working-only proxies back to {file_path} (backup: {backup.name})")

    print("\n" + "=" * 70)
    print(f"Results: {len(working)} working, {len(failed)} failed")
    print(f"Working list: {working_out}")
    print(f"Results CSV:  {results_out}")
    return 0 if working else 1


if __name__ == "__main__":
    raise SystemExit(main())
