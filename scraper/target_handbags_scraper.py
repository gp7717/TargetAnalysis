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
    """Product data structure – core identifiers + enriched PDP fields."""
    # ── Identifiers ──────────────────────────────────────────────────────────
    tcin: str
    title: str
    url: str

    # ── Brand / category ─────────────────────────────────────────────────────
    brand: str = ""
    breadcrumb: str = ""          # e.g. "Target > Accessories > Handbags"
    leaf_category: str = ""       # last crumb, e.g. "Shoulder Bags"

    # ── Pricing ──────────────────────────────────────────────────────────────
    price: float = 0.0
    original_price: float = 0.0
    discount_percent: float = 0.0
    is_on_sale: bool = False

    # ── Ratings ──────────────────────────────────────────────────────────────
    rating: float = 0.0
    review_count: int = 0

    # ── Engagement signals ───────────────────────────────────────────────────
    bought_recently: str = ""     # e.g. "50+ bought in past week"
    is_new: bool = False

    # ── Variants / colors ────────────────────────────────────────────────────
    colors: List[str] = field(default_factory=list)
    selected_color: str = ""

    # ── Media ────────────────────────────────────────────────────────────────
    images: List[str] = field(default_factory=list)

    # ── Content ──────────────────────────────────────────────────────────────
    description: str = ""
    feature_bullets: List[str] = field(default_factory=list)  # highlight bullets

    # ── Derived spec fields (quick-access) ───────────────────────────────────
    material: str = ""            # Shell Material
    dimensions: Dict[str, str] = field(default_factory=dict)  # parsed dim map
    dimensions_raw: str = ""      # e.g. "5.59 Inches (H) x 9.76 Inches (W) x 2.16 Inches (D)"
    bag_structure: str = ""       # Structured / Unstructured
    interior_features: str = ""
    exterior_features: str = ""
    closure_type: str = ""        # Flap Closure, Zipper, etc.
    handle_type: str = ""         # Shoulder Strap, Single handle, etc.
    fabric_name: str = ""         # Jacquard Weave, Canvas, etc.
    care_instructions: str = ""   # Spot or Wipe Clean, etc.
    origin: str = ""              # Imported / Domestic

    # ── Administrative ───────────────────────────────────────────────────────
    upc: str = ""
    dpci: str = ""                # Target item number (e.g. 024-06-6038)
    specs: Dict[str, str] = field(default_factory=dict)  # full raw spec map
    in_stock: bool = True
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['colors'] = ' | '.join(self.colors)
        d['images'] = ' | '.join(self.images[:10])
        d['feature_bullets'] = ' | '.join(self.feature_bullets)
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

                // Current price
                const priceEl = card.querySelector('[data-test="current-price"]');
                const price = priceEl?.textContent?.trim() || '';

                // Original / regular price (shown when on sale)
                const origEl = card.querySelector('[data-test="regular-price"]') ||
                               card.querySelector('s') ||
                               card.querySelector('[class*="regular"]');
                const originalPrice = origEl?.textContent?.trim() || '';

                // Sale / badge signals
                const isSale = !!card.querySelector(
                    '[data-test="sale-badge"], [class*="saleBadge"], [data-test*="strikethrough"]'
                );
                const isNew = !!card.querySelector('[data-test*="new-badge"], [class*="newBadge"]');

                // Bought-recently badge
                const boughtEl = card.querySelector('[class*="boughtRecently"], [data-test*="boughtRecently"]');
                const boughtRecently = boughtEl?.textContent?.trim() || '';

                // Rating & review count if visible on card
                const ratingEl = card.querySelector('[data-test="ratings"], [class*="ratingCount"]');
                const ratingText = ratingEl?.textContent?.trim() || '';

                // Brand on card
                const brandEl = card.querySelector('[data-test*="brand"], [class*="BrandName"], [class*="brandName"]');
                const brand = brandEl?.textContent?.trim() || '';

                return { href, title, price, originalPrice, isSale, isNew, boughtRecently, ratingText, brand };
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
                price=self._parse_price(item['price']),
                original_price=self._parse_price(item.get('originalPrice', '')),
                is_on_sale=bool(item.get('isSale')),
                is_new=bool(item.get('isNew')),
                bought_recently=item.get('boughtRecently', ''),
                brand=item.get('brand', ''),
            )
            # Parse rating/review from card text "X out of 5 stars with Y reviews"
            card_rating = item.get('ratingText', '')
            if card_rating:
                rm = re.search(r'([\d.]+)\s+out of\s+5', card_rating, re.I)
                if rm:
                    try:
                        prod.rating = float(rm.group(1))
                    except ValueError:
                        pass
                rv = re.search(r'with\s+([\d,]+)\s+(?:rating|review)', card_rating, re.I)
                if rv:
                    try:
                        prod.review_count = int(rv.group(1).replace(',', ''))
                    except ValueError:
                        pass
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

    def _parse_specs_text(self, spec_el) -> Dict[str, str]:
        """
        Parse spec section text into key/value pairs.

        Target uses two layouts:
          1. Key ends with colon, value is on next line:
               "Dimensions (Overall):\n5.59 Inches..."
          2. Key has no colon, value starts with ": " on next line (TCIN, UPC):
               "TCIN\n: 94780342"
        """
        if not spec_el:
            return {}
        raw = spec_el.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        parsed: Dict[str, str] = {}
        i = 0
        while i < len(lines):
            line = lines[i]
            # Layout 1: "Key:"
            if line.endswith(":"):
                key = line[:-1].strip()
                if key and i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # make sure next line isn't itself a key
                    if not next_line.endswith(":") and not next_line.startswith(": "):
                        parsed[key] = next_line
                        i += 2
                        continue
            # Layout 2: value on next line starts with ": "
            elif i + 1 < len(lines) and lines[i + 1].startswith(": "):
                key = line.strip()
                val = lines[i + 1][2:].strip()   # strip leading ": "
                if key and val:
                    parsed[key] = val
                i += 2
                continue
            # Layout 3: "Key: Value" on a single line
            elif ":" in line:
                parts = line.split(":", 1)
                key, val = parts[0].strip(), parts[1].strip()
                if key and val:
                    parsed[key] = val
            i += 1
        return parsed

    def _apply_specs(self, product: Product, specs: Dict[str, str]):
        """
        Populate structured fields from the raw spec dict and store the full map.
        """
        product.specs.update(specs)
        for key, value in specs.items():
            kl = key.lower()
            if not value:
                continue
            # Material — must say "material" in the key ("shell" alone is too
            # broad; "Shell Color", "Outer Shell" etc. are different specs)
            if "material" in kl:
                product.material = value
            # Dimensions – store raw string AND per-axis dict
            if "dimension" in kl:
                product.dimensions_raw = value
                # parse "5.59 Inches (H) x 9.76 Inches (W) x 2.16 Inches (D)"
                for axis_match in re.finditer(
                    r'([\d.]+)\s+\w+\s*\(([^)]+)\)', value
                ):
                    product.dimensions[axis_match.group(2).upper()] = axis_match.group(1)
            elif any(d in kl for d in ["height", "width", "depth", "length"]):
                product.dimensions[key] = value
            # Bag structure — require "bag structure" exactly so that
            # "Interior Structure", "Frame Structure" etc. are not captured
            if "bag structure" in kl:
                product.bag_structure = value
            if "interior feature" in kl:
                product.interior_features = value
            if "exterior feature" in kl:
                product.exterior_features = value
            if "closure" in kl:
                product.closure_type = value
            if "handle" in kl:
                product.handle_type = value
            if "fabric" in kl:
                product.fabric_name = value
            if "care" in kl or "cleaning" in kl:
                product.care_instructions = value
            if "origin" in kl:
                product.origin = value
            if kl == "upc":
                product.upc = value
            if "dpci" in kl or "item number" in kl:
                product.dpci = value
            if kl == "tcin" and not product.tcin:
                product.tcin = value

    async def _enrich_with_details(self, page: Page, product: Product):
        try:
            await self._bring_to_front(page, "detail")
            # "load" ensures all scripts are executed before we look for
            # product title, specs, and images.
            await page.goto(product.url, wait_until="load", timeout=60000)
            await page.wait_for_selector('h1[data-test="product-title"]', timeout=20000)

            # Expand accordion sections if collapsed, scrolling them into
            # view first so Playwright can interact with them reliably.
            for label in ["Specifications", "About this item", "Highlights", "Details"]:
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
            detail_sections = [
                '[data-test="product-title"]',
                '[data-test="product-price"]',
                '[data-test="item-details-description"]',
                '[data-test="item-details-specifications"]',
                '[data-test="item-details-highlights"]',
            ]
            for sel in detail_sections:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.scroll_into_view_if_needed(timeout=3000)
                        await asyncio.sleep(0.15)
                except Exception:
                    pass

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            # ── Title ───────────────────────────────────────────────────────
            title_el = soup.select_one('h1[data-test="product-title"]')
            if title_el:
                product.title = title_el.get_text(strip=True)

            # ── Brand ───────────────────────────────────────────────────────
            brand_el = soup.select_one('a[data-test="shopAllBrandLink"]')
            if brand_el:
                raw_brand = brand_el.get_text(strip=True)
                # Remove "Shop all" prefix that Target prepends ("Shop allA New Day")
                product.brand = re.sub(r'^Shop\s+all\s*', '', raw_brand, flags=re.I).strip()

            # ── Breadcrumb / category ────────────────────────────────────────
            bc_els = soup.select('[data-test="@web/Breadcrumbs/BreadcrumbLink"]')
            if bc_els:
                crumbs = [el.get_text(strip=True) for el in bc_els]
                product.breadcrumb = " > ".join(crumbs)
                # Leaf crumb is the most specific category (skip "Target" root)
                product.leaf_category = crumbs[-1] if len(crumbs) > 1 else ""

            # ── Current price ────────────────────────────────────────────────
            price_el = soup.select_one('[data-test="product-price"]')
            if price_el:
                product.price = self._parse_price(price_el.get_text(strip=True))

            # ── Original / sale price ────────────────────────────────────────
            # Target shows original price in a strikethrough when on sale
            orig_candidates = [
                soup.select_one('[data-test="product-regular-price"]'),
                soup.select_one('[data-test="regular-price"]'),
            ]
            for cand in orig_candidates:
                if cand:
                    v = self._parse_price(cand.get_text(strip=True))
                    if v > 0:
                        product.original_price = v
                        break
            # Also look for displayed strikethrough price in the same price block.
            # Target uses data-test="strikethroughPriceMessage" (caught by *="strikethrough")
            # as well as plain <s>/<del> elements; scope to the price block parent so
            # we never accidentally pick up related-product carousels further down the page.
            if not product.original_price:
                price_block = soup.select_one('[data-test="product-price"]')
                if price_block:
                    parent = price_block.find_parent() or price_block
                    strike = parent.select_one(
                        "s, del, "
                        "[data-test*='strikethrough'], "
                        "[data-test*='was-price'], "
                        "[data-test*='regular-price'], "
                        "[class*=strike], [class*=Strike]"
                    )
                    if strike:
                        v = self._parse_price(strike.get_text(strip=True))
                        if v > 0:
                            product.original_price = v
            # Sale flag
            if product.original_price > 0 and product.price < product.original_price:
                product.is_on_sale = True
                if product.original_price:
                    product.discount_percent = round(
                        (product.original_price - product.price) / product.original_price * 100, 1
                    )

            # ── Rating & review count ────────────────────────────────────────
            # Primary: data-test="ratings" has full text like
            # "4.6 out of 5 stars with 31 ratings"
            for rating_sel in [
                '[data-test="ratings"]',
                '[data-test*="rating"]',
                '[aria-label*="out of 5"]',
            ]:
                rating_el = soup.select_one(rating_sel)
                if rating_el:
                    rt = rating_el.get_text(strip=True)
                    rm = re.search(r'([\d.]+)\s+out of\s+5', rt, re.I)
                    if rm:
                        try:
                            product.rating = float(rm.group(1))
                        except ValueError:
                            pass
                    rv = re.search(r'with\s+([\d,]+)\s+(?:rating|review)', rt, re.I)
                    if rv:
                        try:
                            product.review_count = int(rv.group(1).replace(',', ''))
                        except ValueError:
                            pass
                    if product.rating:
                        break

            # ── Feature bullets (highlights accordion) ───────────────────────
            highlight_sel = (
                soup.select_one('[data-test="item-details-highlights"]') or
                soup.select_one('[data-test*="highlights"]') or
                soup.select_one('[class*="highlights"]')
            )
            if highlight_sel:
                bullets = [li.get_text(strip=True) for li in highlight_sel.select("li") if li.get_text(strip=True)]
                product.feature_bullets = bullets

            # ── Images ──────────────────────────────────────────────────────
            seen_imgs: set = set()
            # Strategy A: <img> tags pointing to scene7     
            for img in soup.select('img[src*="scene7.com"]'):
                src = img.get("src", "")
                if src and "scene7.com" in src:
                    clean = re.sub(r'\?.*', '?wid=1200&hei=1200&qlt=85', src)
                    if clean not in seen_imgs:
                        seen_imgs.add(clean)
                        product.images.append(clean)
            # Strategy B: <source srcset> elements
            for src_el in soup.select('source[srcset*="scene7.com"]'):
                for part in src_el.get("srcset", "").split(","):
                    url_part = part.strip().split()[0]
                    if "scene7.com" in url_part:
                        clean = re.sub(r'\?.*', '?wid=1200&hei=1200&qlt=85', url_part)
                        if clean not in seen_imgs:
                            seen_imgs.add(clean)
                            product.images.append(clean)

            # ── Description ──────────────────────────────────────────────────
            desc = soup.select_one('[data-test="item-details-description"]')
            if desc:
                product.description = " ".join(desc.stripped_strings)[:1500].strip()

            # ── Specs ────────────────────────────────────────────────────────
            # Primary: parse the rendered text right from BeautifulSoup
            spec_el = soup.select_one('[data-test="item-details-specifications"]')
            parsed_specs = self._parse_specs_text(spec_el)

            # Fallback JS extraction for structured dt/dd or table layouts
            if not parsed_specs:
                raw_specs = await page.evaluate("""
                () => {
                    const results = {};
                    let panel = document.querySelector('[data-test="item-details-specifications"]');
                    if (!panel) return results;

                    // dl/dt+dd
                    panel.querySelectorAll('dt').forEach(dt => {
                        const dd = dt.nextElementSibling;
                        if (dd && dd.tagName === 'DD') {
                            const k = dt.innerText.trim().replace(/:$/, '');
                            const v = dd.innerText.trim();
                            if (k && v) results[k] = v;
                        }
                    });
                    // tr/td table
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
                    // Sibling-div pattern
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
                parsed_specs = raw_specs or {}

            self._apply_specs(product, parsed_specs)

            # ── Color swatches ───────────────────────────────────────────────
            color_set: set = set()
            for swatch in soup.select(
                'button[aria-label*="color"], '
                '[data-test*="colorSwatch"] button, '
                '[class*="SwatchChip"] button, '
                'button[data-variant-id]'
            ):
                label = swatch.get("aria-label", "").strip()
                # Typical label: "Red, select to change color"
                if label:
                    color_name = re.split(r',\s*select', label, flags=re.I)[0].strip()
                    if color_name and len(color_name) < 50:
                        color_set.add(color_name)
            if color_set and not product.colors:
                product.colors = sorted(color_set)

            # ── is_new badge ─────────────────────────────────────────────────
            if not product.is_new:
                new_badge = soup.select_one(
                    '[data-test*="new-badge"], [class*="newBadge"], [class*="NewBadge"]'
                )
                product.is_new = new_badge is not None

            # ── In-stock / availability ──────────────────────────────────────
            add_to_cart = soup.select_one('[data-test*="AddToCart"], [data-test*="fulfillment"]')
            if add_to_cart:
                atc_text = add_to_cart.get_text(strip=True).lower()
                product.in_stock = "out of stock" not in atc_text and "unavailable" not in atc_text

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
        import csv
        self.output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        rows = [p.to_dict() for p in self.products]

        if not rows:
            logger.warning("No products to save.")
            return

        # JSON
        path_json = self.output_dir / f"target_handbags_{ts}.json"
        with open(path_json, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved JSON:  {path_json}")

        # JSONL
        path_jsonl = self.output_dir / f"target_handbags_{ts}.jsonl"
        with open(path_jsonl, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        logger.info(f"Saved JSONL: {path_jsonl}")

        # CSV
        path_csv = self.output_dir / f"target_handbags_{ts}.csv"
        fieldnames = list(rows[0].keys())
        with open(path_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        logger.info(f"Saved CSV:   {path_csv}")


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