#!/usr/bin/env python3
"""
Target Handbags Scraper – 2025 edition
Hardcoded proxy + anti-bot hardening + debug output
"""

import asyncio
import json
import logging
import random
import re
from contextlib import suppress
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from playwright.async_api import async_playwright, Page, BrowserContext
from bs4 import BeautifulSoup

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("target-scraper")


@dataclass
class Product:
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
        d['images'] = ', '.join(self.images[:8])
        d['dimensions'] = json.dumps(self.dimensions, ensure_ascii=False)
        d['specs'] = json.dumps(self.specs, ensure_ascii=False)
        return d


class TargetHandbagsScraper:
    def __init__(
        self,
        max_products: Optional[int] = None,
        delay_range: tuple[float, float] = (2.5, 6.0),
        headless: bool = True,
        verbose: bool = False,
        get_details: bool = False,
        output_dir: str = "./output"
    ):
        self.max_products = max_products
        self.delay_min, self.delay_max = delay_range
        self.headless = headless
        self.verbose = verbose
        self.get_details = get_details
        self.output_dir = Path(output_dir).expanduser().resolve()

        if verbose:
            logger.setLevel(logging.DEBUG)

        self.products: List[Product] = []
        self.base_url = "https://www.target.com/c/handbags-purses-accessories/-/N-5xtbo"

        # ─── HARDCODED PROXY ────────────────────────────────────────────────
        self.proxy_host_port = "104.238.30.50:59741"
        self.proxy = f"http://{self.proxy_host_port}"
        logger.info(f"Proxy hardcoded: {self.proxy}")

    async def _delay(self):
        await asyncio.sleep(random.uniform(self.delay_min, self.delay_max))

    async def _init_browser(self) -> tuple[BrowserContext, Page]:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=self.headless)

        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ]

        context = await browser.new_context(
            user_agent=random.choice(user_agents),
            viewport={"width": 1366, "height": 768},
            proxy={"server": self.proxy}
        )

        page = await context.new_page()

        logger.info("Browser initialized with proxy")
        return context, page

    async def _shutdown_browser(self, context: BrowserContext, listing_page: Page, detail_page: Optional[Page]):
        with suppress(Exception):
            if detail_page:
                await detail_page.close()
        with suppress(Exception):
            await listing_page.close()
        with suppress(Exception):
            await context.close()
        with suppress(Exception):
            await context.browser.close()
        with suppress(Exception):
            await context.playwright.stop()
        logger.debug("Browser resources cleaned up")

    # ─── Listing page ────────────────────────────────────────────────────────

    async def _scrape_listing_page(self, page: Page, url: str) -> List[Product]:
        logger.info(f"Scraping → {url}")

        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(5)               # Give anti-bot / proxy time
        await page.wait_for_load_state("networkidle", timeout=40000)

        # ─── DEBUG: Save raw HTML ────────────────────────────────────────
        html = await page.content()
        debug_path = Path("debug_listing.html")
        debug_path.write_text(html, encoding="utf-8")
        logger.info(f"Raw page saved for debug → {debug_path.absolute()}")

        products: List[Product] = []

        # Try DOM method first
        try:
            await page.wait_for_selector('[data-test="@web/ProductCard/title"]', timeout=18000)
            logger.info("Product cards detected in DOM → using DOM scraping")
            await self._scroll_until_stable(page)

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

            for item in items:
                if not item['href']:
                    continue
                full_url = "https://www.target.com" + item['href'] if item['href'].startswith("/") else item['href']
                tcin_match = re.search(r'/A-(\d+)', full_url)
                tcin = tcin_match.group(1) if tcin_match else ""

                prod = Product(
                    tcin=tcin,
                    title=item['title'],
                    url=full_url,
                    price=self._parse_price(item['price'])
                )
                products.append(prod)

                if self.max_products and len(self.products) + len(products) >= self.max_products:
                    break

        except Exception as e:
            logger.warning(f"DOM method failed: {e}. Trying fallback...")

        if not products:
            title = await page.title()
            logger.warning(f"No cards found. Page title = {title!r}")
            if "Access Denied" in title or "403" in title or "Just a moment" in title:
                logger.error("Likely blocked by Target / Cloudflare. Try different proxy.")

        logger.info(f"   → found {len(products)} products")
        return products

    async def _scroll_until_stable(self, page: Page, max_attempts=22):
        prev_count = -1
        stable = 0
        for _ in range(max_attempts):
            count = await page.evaluate(
                """() => document.querySelectorAll('[data-test="@web/ProductCard/title"]').length"""
            )
            if count == prev_count:
                stable += 1
                if stable >= 5:
                    break
            else:
                stable = 0
                prev_count = count
            await page.evaluate("window.scrollBy(0, window.innerHeight * 1.6)")
            await asyncio.sleep(1.1)

    # ─── Detail enrichment (unchanged but with extra wait) ────────────────

    async def _enrich_with_details(self, page: Page, product: Product):
        try:
            await page.goto(product.url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(4)
            await page.wait_for_selector('h1[data-test="product-title"]', timeout=30000)

            for text in ["Specifications", "About this item"]:
                try:
                    btn = page.locator(f'button:has-text("{text}")')
                    if await btn.count() > 0 and await btn.get_attribute("aria-expanded") != "true":
                        await btn.first.click()
                        await asyncio.sleep(0.7)
                except:
                    pass

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            title_el = soup.select_one('h1[data-test="product-title"]')
            if title_el:
                product.title = title_el.get_text(strip=True)

            brand_el = soup.select_one('a[data-test="shopAllBrandLink"]')
            if brand_el:
                product.brand = brand_el.get_text(strip=True).replace("Shop all ", "").strip()

            price_el = soup.select_one('[data-test="product-price"]')
            if price_el:
                product.price = self._parse_price(price_el.get_text(strip=True))

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

            for pic in soup.select('picture img[src*="scene7.com"]'):
                src = pic.get("src") or ""
                if "scene7.com" in src and src not in product.images:
                    clean_src = re.sub(r'\?.*', '?wid=1200&hei=1200&qlt=85', src)
                    product.images.append(clean_src)

            desc = soup.select_one('[data-test="item-details-description"]')
            if desc:
                product.description = " ".join(desc.stripped_strings)[:800].strip()

            specs_block = soup.select_one('[data-test="item-details-specifications"]')
            if specs_block:
                for row in specs_block.find_all("div"):
                    b = row.find("b")
                    if not b:
                        continue
                    key = b.get_text(strip=True).rstrip(":").strip()
                    value = row.get_text(strip=True).split(":", 1)[-1].strip()
                    if key and value:
                        product.specs[key] = value
                        if "material" in key.lower():
                            product.material = value
                        if any(kw in key.lower() for kw in ["dimension", "height", "width", "depth"]):
                            product.dimensions[key] = value

        except Exception as e:
            logger.debug(f"Detail failed for {product.tcin}: {e}")

    def _parse_price(self, s: str) -> float:
        if not s:
            return 0.0
        try:
            cleaned = re.sub(r'[^\d.]', '', s)
            return float(cleaned) if cleaned else 0.0
        except:
            return 0.0

    # ─── Main run ───────────────────────────────────────────────────────────

    async def run(self):
        context, listing_page = await self._init_browser()
        detail_page = await context.new_page() if self.get_details else None

        try:
            url = self.base_url
            page_num = 1

            while url and (not self.max_products or len(self.products) < self.max_products):
                logger.info(f"Page {page_num}  ──  {url}")

                new_products = await self._scrape_listing_page(listing_page, url)
                self.products.extend(new_products)

                if len(new_products) == 0:
                    logger.warning("Zero products → possible block / geo-restriction / bad proxy")
                    break

                if self.get_details and detail_page:
                    for prod in new_products:
                        if not prod.url:
                            continue
                        await self._enrich_with_details(detail_page, prod)
                        await self._delay()

                        if self.max_products and len(self.products) >= self.max_products:
                            break

                next_url = await self._get_next_page_url(listing_page)
                if not next_url:
                    logger.info("No more pages")
                    break

                url = next_url
                page_num += 1
                await self._delay()

            logger.info(f"Finished. Total products collected: {len(self.products)}")

        finally:
            await self._shutdown_browser(context, listing_page, detail_page)

        self._save_results()

    async def _get_next_page_url(self, page: Page) -> Optional[str]:
        try:
            next_btn = page.locator('button[data-test="next"]:not([disabled])')
            if await next_btn.count() == 0:
                return None

            current_url = page.url
            await next_btn.first.click()
            await asyncio.sleep(2.5)

            for _ in range(15):
                if page.url != current_url:
                    return page.url
                await asyncio.sleep(0.6)

            return None
        except:
            return None

    def _save_results(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        path_json = self.output_dir / f"target_handbags_{ts}.json"
        with open(path_json, "w", encoding="utf-8") as f:
            json.dump([p.to_dict() for p in self.products], f, indent=2, ensure_ascii=False)
        logger.info(f"Saved JSON → {path_json}")

        path_jsonl = self.output_dir / f"target_handbags_{ts}.jsonl"
        with open(path_jsonl, "w", encoding="utf-8") as f:
            for p in self.products:
                f.write(json.dumps(p.to_dict(), ensure_ascii=False) + "\n")
        logger.info(f"Saved JSONL → {path_jsonl}")


# ─── CLI ─────────────────────────────────────────────────────────────────

def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="Target Handbags Scraper – Proxy Hardcoded")
    parser.add_argument("--max-products", type=int, default=None, help="Max products to scrape")
    parser.add_argument("--details", action="store_true", help="Scrape detail pages")
    parser.add_argument("--output-dir", default="./output", help="Output folder")
    parser.add_argument("--headless", action="store_true", default=True, help="Run headless")
    parser.add_argument("--headed", action="store_true", help="Show browser")
    parser.add_argument("--verbose", action="store_true", help="Verbose logs")
    args = parser.parse_args()
    if args.headed:
        args.headless = False
    return args


async def main():
    args = parse_args()

    scraper = TargetHandbagsScraper(
        max_products=args.max_products,
        get_details=args.details,
        output_dir=args.output_dir,
        headless=args.headless,
        verbose=args.verbose
    )

    await scraper.run()


if __name__ == "__main__":
    asyncio.run(main())