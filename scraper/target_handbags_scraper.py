#!/usr/bin/env python3
"""
Simplified & cleaned Target Handbags Scraper

Extracts product data from Target's handbags category with pagination support.
Optionally visits detail pages for richer metadata.

Usage:
    python target_handbags_scraper.py --max-products 60 --details --output-dir ./data
"""

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from playwright.async_api import async_playwright, Page, BrowserContext
from bs4 import BeautifulSoup

# ────────────────────────────────────────────────
# Logging
# ────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("target-scraper")


# ────────────────────────────────────────────────
# Data model
# ────────────────────────────────────────────────

@dataclass
class Product:
    """Minimal but useful product data structure"""
    tcin: str
    title: str
    url: str
    brand: str = ""
    price: float = 0.0
    original_price: float = 0.0
    rating: float = 0.0
    review_count: int = 0
    bought_recently: str = ""
    colors: List[str] = field(default_factory=list)
    selected_color: str = ""
    images: List[str] = field(default_factory=list)
    description: str = ""
    material: str = ""
    dimensions: Dict[str, str] = field(default_factory=dict)
    specs: Dict[str, str] = field(default_factory=dict)
    is_on_sale: bool = False
    in_stock: bool = True
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['colors'] = ', '.join(self.colors)
        d['images'] = ', '.join(self.images[:8])   # limit for CSV readability
        d['dimensions'] = json.dumps(self.dimensions, ensure_ascii=False)
        d['specs'] = json.dumps(self.specs, ensure_ascii=False)
        return d


# ────────────────────────────────────────────────
# Scraper core
# ────────────────────────────────────────────────

class TargetHandbagsScraper:
    def __init__(
        self,
        max_products: Optional[int] = None,
        delay_range: tuple[float, float] = (1.2, 3.1),
        headless: bool = True,
        devtools: bool = False,
        slow_mo: int = 0,
        verbose: bool = False,
        get_details: bool = False,
        output_dir: str = "./data",
        proxy: Optional[str] = None,
    ):
        self.max_products = max_products
        self.delay_min, self.delay_max = delay_range
        self.headless = headless
        self.devtools = devtools
        self.slow_mo = slow_mo
        self.verbose = verbose
        self.get_details = get_details
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.proxy = proxy  # e.g. "http://195.158.8.123:3128"

        if verbose:
            logger.setLevel(logging.DEBUG)

        self.products: List[Product] = []
        self.base_url = "https://www.target.com/c/handbags-purses-accessories/-/N-5xtbo"
        self._pw = None
        self._browser = None

    async def _delay(self):
        await asyncio.sleep(random.uniform(self.delay_min, self.delay_max))

    async def _bring_to_front(self, page: Page, label: str):
        try:
            await page.bring_to_front()
        except Exception:
            logger.debug(f"Could not bring page to front ({label})")

    async def _init_browser(self) -> tuple[BrowserContext, Page]:
        self._pw = await async_playwright().start()

        # Debug mode: DevTools requires a headed browser.
        launch_headless = False if self.devtools else self.headless

        launch_kwargs: dict = {
            "headless": launch_headless,
            "devtools": self.devtools,
            "slow_mo": self.slow_mo or 0,
        }
        if self.proxy:
            # Playwright requires credentials as separate fields, NOT embedded
            # in the URL (http://user:pass@host:port causes ERR_INVALID_AUTH_CREDENTIALS).
            from urllib.parse import urlparse
            raw = self.proxy if "://" in self.proxy else f"http://{self.proxy}"
            parsed = urlparse(raw)
            server = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
            proxy_dict: dict = {"server": server}
            if parsed.username:
                proxy_dict["username"] = parsed.username
            if parsed.password:
                proxy_dict["password"] = parsed.password
            launch_kwargs["proxy"] = proxy_dict
            logger.info(f"Using proxy: {server}" + (f" (authenticated as {parsed.username})" if parsed.username else ""))
        self._browser = await self._pw.chromium.launch(**launch_kwargs)

        context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            ignore_https_errors=True,
            java_script_enabled=True,
            extra_http_headers={
                # Only set headers that are safe to send on EVERY request
                # (including cross-origin sub-resources).
                # Sec-Fetch-*, Upgrade-Insecure-Requests are navigation-only
                # headers; sending them on XHR/CSS/JS triggers CORS preflight
                # failures on Target's CDN (assets.targetimg1.com) which
                # blocks all Next.js bundles and prevents React from hydrating.
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
            },
        )
        page = await context.new_page()

        if self.verbose or self.devtools:
            page.on("console", lambda msg: logger.info(f"PAGE CONSOLE: {msg.type}: {msg.text}"))
            page.on("pageerror", lambda err: logger.error(f"PAGE ERROR: {err}"))
        return context, page

    # ─── Listing page helpers ────────────────────────────────────────────────

    async def _dismiss_modals(self, page: Page):
        """Close sign-in popups, location prompts, or cookie banners if present."""
        dismissals = [
            # Sign-in tooltip close button
            'button[aria-label="close"]',
            'button[data-test="closeButton"]',
            # Generic close / dismiss
            '[aria-label="Close"]',
            '[data-test="modal-close"]',
        ]
        for sel in dismissals:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=800):
                    await btn.click()
                    logger.debug(f"Dismissed modal via: {sel}")
                    await asyncio.sleep(0.3)
            except Exception:
                pass

    async def _screenshot_debug(self, page: Page, label: str):
        """Save a screenshot to output_dir when something goes wrong."""
        try:
            dest = self.output_dir / f"debug_{label}_{datetime.now().strftime('%H%M%S')}.png"
            await page.screenshot(path=str(dest), full_page=False)
            logger.info(f"Debug screenshot saved → {dest}")
        except Exception as e:
            logger.debug(f"Could not save debug screenshot: {e}")

    async def _wait_for_products(self, page: Page, timeout: int = 28000) -> bool:
        """Wait for product cards, retrying once if we hit a bot-challenge render."""
        selector = '[data-test="@web/ProductCard/title"]'
        try:
            await page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception:
            pass

        # Check for bot challenge indicators
        challenge = await page.evaluate("""
        () => {
            const text = document.body?.innerText || '';
            return text.includes('Access Denied') ||
                   text.includes('verify you are human') ||
                   document.querySelector('#px-captcha') !== null;
        }
        """)
        if challenge:
            logger.warning("Bot challenge detected – waiting 8 s before retry")
            await asyncio.sleep(8)
        else:
            # React might still be hydrating; give it a few more seconds
            logger.debug("Products not yet in DOM, waiting 5 s for late render…")
            await asyncio.sleep(5)

        # One retry
        try:
            await page.wait_for_selector(selector, timeout=15000)
            return True
        except Exception:
            return False

    async def _scrape_listing_page(self, page: Page, url: str) -> List[Product]:
        logger.info(f"Scraping → {url}")
        await self._bring_to_front(page, "listing")
        # "load" waits for the full load event (all scripts & stylesheets
        # referenced in HTML), giving React time to fully hydrate before we
        # check for product cards.
        await page.goto(url, wait_until="load", timeout=60000)

        # Dismiss any sign-in / location / cookie modals that block the grid
        await self._dismiss_modals(page)

        found = await self._wait_for_products(page)
        if not found:
            logger.warning("No product cards found on this page")
            await self._screenshot_debug(page, "no_products")
            return []

        # Scroll all the way to the bottom so every lazy-loaded card appears
        await self._scroll_to_bottom(
            page,
            card_selector='[data-test="@web/ProductCard/title"]',
        )

        items = await page.evaluate("""
        () => {
            const cards = document.querySelectorAll('[data-test="@web/site-top-of-funnel/ProductCardWrapper"]');
            return Array.from(cards).map(card => {
                const link = card.querySelector('a[data-test="@web/ProductCard/title"]');
                if (!link) return null;
                const href = link.getAttribute('href') || '';
                const title = link.textContent?.trim() || '';
                const priceEl = card.querySelector('[data-test="current-price"]');
                const price = priceEl?.textContent?.trim() || '';
                return { href, title, price };
            }).filter(Boolean);
        }
        """)

        products = []
        for item in items:
            if not item['href']:
                continue
            full_url = "https://www.target.com" + item['href'] if item['href'].startswith("/") else item['href']
            tcin = re.search(r'/A-(\d+)', full_url)
            tcin = tcin.group(1) if tcin else ""

            prod = Product(
                tcin=tcin,
                title=item['title'],
                url=full_url,
                price=self._parse_price(item['price'])
            )
            products.append(prod)

            if self.max_products and len(self.products) + len(products) >= self.max_products:
                break

        logger.info(f"   → found {len(products)} products")
        return products

    async def _scroll_to_bottom(
        self,
        page: Page,
        card_selector: str = "",
        max_attempts: int = 30,
        network_wait_ms: int = 2000,
    ):
        """
        Scroll to the bottom, waiting just long enough for lazy-loaded DOM to
        appear.

        network_wait_ms:

          > 0  – used on listing pages; waits briefly for the XHR that an
                 infinite-scroll trigger fires after each scroll step.
          0    – used on static detail pages; skips the network wait entirely
                 (the page is already fully loaded; we only need images/specs
                 that are below-the-fold to enter the viewport and render).
        """
        prev_height = -1
        stable = 0

        for attempt in range(max_attempts):
            cur_height = await page.evaluate("""
                () => {
                    window.scrollTo({ top: document.body.scrollHeight, behavior: 'instant' });
                    return document.body.scrollHeight;
                }
            """)

            if network_wait_ms > 0:
                # Short pause so the scroll-triggered XHR can fire, then wait
                # for it to settle (best-effort; don't block long).
                await asyncio.sleep(0.4)
                try:
                    await page.wait_for_load_state("networkidle", timeout=network_wait_ms)
                except Exception:
                    pass
            else:
                # Detail page: already loaded – just let the browser paint the
                # newly-visible section before we re-check height.
                await asyncio.sleep(0.25)

            new_height = await page.evaluate("() => document.body.scrollHeight")

            if new_height == prev_height:
                stable += 1
                if stable >= 3:
                    logger.debug(f"Scroll stable after {attempt + 1} steps (height={new_height})")
                    break
            else:
                stable = 0
                prev_height = new_height
                if card_selector:
                    count = await page.evaluate(
                        f"""() => document.querySelectorAll('{card_selector}').length"""
                    )
                    logger.debug(f"  scroll {attempt + 1}: height={new_height}, cards={count}")
                    if self.max_products and count >= self.max_products:
                        break
                else:
                    logger.debug(f"  scroll {attempt + 1}: height={new_height}")

        # Return to top so pagination buttons / next-page logic can find them
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.2)

    # ─── Detail page helpers ─────────────────────────────────────────────────

    async def _enrich_with_details(self, page: Page, product: Product):
        try:
            await self._bring_to_front(page, "detail")
            # "load" ensures all scripts are executed before we look for
            # product title, specs, and images.
            await page.goto(product.url, wait_until="load", timeout=60000)
            await page.wait_for_selector('h1[data-test="product-title"]', timeout=20000)

            # Expand accordion sections if collapsed, scrolling them into
            # view first so Playwright can interact with them reliably.
            for label in ["Specifications", "About this item"]:
                try:
                    btn = page.locator(f'button:has-text("{label}")').first
                    if await btn.count() > 0:
                        await btn.scroll_into_view_if_needed(timeout=3000)
                        await asyncio.sleep(0.2)
                        expanded = await btn.get_attribute("aria-expanded")
                        if expanded != "true":
                            await btn.click()
                            await asyncio.sleep(0.5)
                except Exception:
                    pass

            # Scroll each product-data section into view in sequence so
            # lazy-loaded content renders without going past the product area.
            # This avoids triggering footer / recommendations loading.
            detail_sections = [
                '[data-test="product-title"]',
                '[data-test="product-price"]',
                '[data-test="item-details-description"]',
                '[data-test="item-details-specifications"]',
                # Image gallery is near the top; scrolling to specs is enough
                # to trigger all above-fold image lazy-loads too.
            ]
            for sel in detail_sections:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.scroll_into_view_if_needed(timeout=3000)
                        await asyncio.sleep(0.2)
                except Exception:
                    pass

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Title (double-check)
            title_el = soup.select_one('h1[data-test="product-title"]')
            if title_el:
                product.title = title_el.get_text(strip=True)

            # Brand
            brand_el = soup.select_one('a[data-test="shopAllBrandLink"]')
            if brand_el:
                product.brand = brand_el.get_text(strip=True).replace("Shop all ", "").strip()

            # Price
            price_el = soup.select_one('[data-test="product-price"]')
            if price_el:
                product.price = self._parse_price(price_el.get_text(strip=True))

            # Rating
            rating_el = soup.select_one('div.styles_ndsRatingStars__uEZcs span[aria-hidden="true"]')
            if rating_el:
                try:
                    product.rating = float(rating_el.get_text(strip=True))
                except:
                    pass

            review_el = soup.select_one('span.styles_ratingCount__QDWQY')
            if review_el:
                txt = review_el.get_text(strip=True).strip("()")
                try:
                    product.review_count = int(txt.replace(",", ""))
                except:
                    pass

            # Images
            for pic in soup.select('picture[data-test*="ProductCardImage"], picture img[src*="scene7.com"]'):
                src = pic.find("img").get("src") if pic.find("img") else ""
                if not src and pic.find("source"):
                    src = pic.find("source").get("srcset", "").split()[0]
                if src and "scene7.com" in src and src not in product.images:
                    product.images.append(re.sub(r'\?.*', '?wid=1200&hei=1200&qlt=85', src))

            # Description
            desc = soup.select_one('[data-test="item-details-description"]')
            if desc:
                product.description = " ".join(desc.stripped_strings)[:800].strip()

            # Material & specs — extracted directly from live DOM via JS so
            # we read the actual rendered key/value pairs regardless of the
            # HTML tag structure Target uses inside the accordion panel.
            raw_specs = await page.evaluate("""
            () => {
                const results = {};

                // Strategy 1: accordion panel via the button's href anchor
                const btn = document.querySelector(
                    'button[href*="Specifications-accordion"], '
                    + 'button[href*="specifications-accordion"]'
                );
                let panel = null;
                if (btn) {
                    const anchorId = (btn.getAttribute('href') || '').replace('#', '');
                    panel = anchorId ? document.getElementById(anchorId) : null;
                }

                // Strategy 2: data-test attribute fallback
                if (!panel) {
                    panel = document.querySelector('[data-test="item-details-specifications"]');
                }

                if (!panel) return results;

                // Walk every element looking for label:value pairs.
                // Target uses multiple layouts: dl/dt/dd, tr/td, or
                // sibling divs where one has bold/label text.
                
                // dl/dt+dd pattern
                panel.querySelectorAll('dt').forEach(dt => {
                    const dd = dt.nextElementSibling;
                    if (dd && dd.tagName === 'DD') {
                        const k = dt.innerText.trim().replace(/:$/, '');
                        const v = dd.innerText.trim();
                        if (k && v) results[k] = v;
                    }
                });

                // tr/td pattern (two-column table rows)
                if (Object.keys(results).length === 0) {
                    panel.querySelectorAll('tr').forEach(tr => {
                        const cells = tr.querySelectorAll('td, th');
                        if (cells.length >= 2) {
                            const k = cells[0].innerText.trim().replace(/:$/, '');
                            const v = cells[1].innerText.trim();
                            if (k && v) results[k] = v;
                        }
                    });
                }

                // Sibling-div pattern: look for divs that contain a
                // visually-bold/label child followed by a value child.
                if (Object.keys(results).length === 0) {
                    panel.querySelectorAll('div').forEach(row => {
                        const children = Array.from(row.children).filter(
                            c => c.children.length === 0 && c.innerText?.trim()
                        );
                        if (children.length === 2) {
                            const k = children[0].innerText.trim().replace(/:$/, '');
                            const v = children[1].innerText.trim();
                            if (k && v) results[k] = v;
                        }
                    });
                }

                return results;
            }
            """)

            for key, value in (raw_specs or {}).items():
                if key and value:
                    product.specs[key] = value
                    if "material" in key.lower():
                        product.material = value
                    if "dimension" in key.lower() or any(
                        d in key.lower() for d in ["height", "width", "depth"]
                    ):
                        product.dimensions[key] = value

            # Sale flag
            if product.original_price > 0 and product.price < product.original_price:
                product.is_on_sale = True

        except Exception as e:
            logger.debug(f"Detail enrichment failed for {product.tcin}: {e}")

    def _parse_price(self, s: str) -> float:
        if not s:
            return 0.0
        try:
            cleaned = re.sub(r'[^\d.]', '', s)
            return float(cleaned) if cleaned else 0.0
        except:
            return 0.0

    # ─── Main flow ───────────────────────────────────────────────────────────

    async def run(self):
        context, listing_page = await self._init_browser()

        try:
            url = self.base_url
            page_num = 1

            while url and (not self.max_products or len(self.products) < self.max_products):
                logger.info(f"Page {page_num}  ──  {url}")

                new_products = await self._scrape_listing_page(listing_page, url)
                self.products.extend(new_products)

                if len(new_products) == 0:
                    logger.warning("No products found → likely end of results or block")
                    break

                # Enrich with detail pages if requested.
                # Each product gets its own fresh tab so it loads completely
                # without interference from the previous page's JS/state.
                if self.get_details:
                    for prod in new_products:
                        if not prod.url:
                            continue
                        detail_page = await context.new_page()
                        try:
                            await self._enrich_with_details(detail_page, prod)
                        finally:
                            await detail_page.close()
                            detail_page = None
                        await self._delay()

                        if self.max_products and len(self.products) >= self.max_products:
                            break

                # Try to go to next page
                next_url = await self._get_next_page_url(listing_page)
                if not next_url:
                    logger.info("No more pages")
                    break

                url = next_url
                page_num += 1
                await self._delay()

            logger.info(f"Finished. Total products collected: {len(self.products)}")

        finally:
            try:
                await context.close()
            finally:
                if self._browser is not None:
                    await self._browser.close()
                if self._pw is not None:
                    await self._pw.stop()

        self._save_results()

    async def _get_next_page_url(self, page: Page) -> Optional[str]:
        try:
            next_btn = page.locator('button[data-test="next"]:not([disabled])')
            if await next_btn.count() == 0:
                return None

            current_url = page.url
            await next_btn.first.click()
            await asyncio.sleep(1.2)

            # Wait until URL changes or new products appear
            for _ in range(12):
                if page.url != current_url:
                    return page.url
                await asyncio.sleep(0.4)

            return None
        except:
            return None

    def _save_results(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # JSON
        path_json = self.output_dir / f"target_handbags_{ts}.json"
        with open(path_json, "w", encoding="utf-8") as f:
            json.dump([p.to_dict() for p in self.products], f, indent=2, ensure_ascii=False)
        logger.info(f"Saved JSON:  {path_json}")

        # JSONL
        path_jsonl = self.output_dir / f"target_handbags_{ts}.jsonl"
        with open(path_jsonl, "w", encoding="utf-8") as f:
            for p in self.products:
                f.write(json.dumps(p.to_dict(), ensure_ascii=False) + "\n")
        logger.info(f"Saved JSONL: {path_jsonl}")


# ────────────────────────────────────────────────
# CLI entry point
# ────────────────────────────────────────────────

def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="Target Handbags Scraper (simplified)")
    parser.add_argument("--max-products", type=int, default=None, help="Stop after N products")
    parser.add_argument("--details", action="store_true", help="Also scrape detail pages")
    parser.add_argument("--output-dir", default="./data", help="Where to save results")
    parser.add_argument("--headless", action="store_true", default=True, help="Run headless (default)")
    parser.add_argument("--headed", action="store_true", help="Show browser window")
    parser.add_argument("--devtools", action="store_true", help="Open Chromium DevTools (forces headed)")
    parser.add_argument("--slow-mo", type=int, default=0, help="Slow down Playwright actions in ms")
    parser.add_argument("--proxy", default=None, help="Proxy to use, e.g. 50.203.147.152:80 or http://user:pass@host:port")
    parser.add_argument("--verbose", action="store_true", help="More logging")
    return parser.parse_args()


async def main():
    args = parse_args()

    scraper = TargetHandbagsScraper(
        max_products=args.max_products,
        get_details=args.details,
        output_dir=args.output_dir,
        headless=not args.headed,
        devtools=args.devtools,
        slow_mo=args.slow_mo,
        verbose=args.verbose,
        proxy=args.proxy,
    )

    await scraper.run()


if __name__ == "__main__":
    asyncio.run(main())