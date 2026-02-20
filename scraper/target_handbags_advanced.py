#!/usr/bin/env python
"""
Advanced Target Handbags Scraper with robust metadata extraction and pagination support.
Extracts comprehensive product information from listing and detail pages.
"""

import asyncio
import json
import logging
import re
import csv
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict, field
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
import random

from playwright.async_api import async_playwright, Page, Browser, BrowserContext, Playwright
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class ProductMetadata:
    """Data class for product metadata"""
    product_id: str
    title: str
    url: str
    brand: str = ""
    price_current: float = 0.0
    price_regular: float = 0.0
    sale_price: float = 0.0
    discount_percent: int = 0
    discount_amount: float = 0.0
    rating: float = 0.0
    rating_count: int = 0
    bought_last_month: str = ""
    colors: List[str] = field(default_factory=list)
    color_selected: str = ""
    category_breadcrumb: str = ""
    description: str = ""
    material_text: str = ""
    highlights: List[str] = field(default_factory=list)
    feature_bullets: List[str] = field(default_factory=list)
    images: List[str] = field(default_factory=list)
    dimensions: Dict[str, str] = field(default_factory=dict)
    dimensions_table: Dict[str, str] = field(default_factory=dict)
    specifications: Dict[str, str] = field(default_factory=dict)
    is_sale: bool = False
    is_clearance: bool = False
    is_new: bool = False
    best_seller: bool = False
    seller: str = ""
    fulfillment_info: str = ""
    in_stock: bool = True
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        data['colors'] = '|'.join(self.colors) if self.colors else ""
        data['highlights'] = '|'.join(self.highlights) if self.highlights else ""
        data['feature_bullets'] = '|'.join(self.feature_bullets) if self.feature_bullets else ""
        data['images'] = '|'.join(self.images) if self.images else ""
        data['dimensions'] = json.dumps(self.dimensions) if self.dimensions else "{}"
        data['dimensions_table'] = json.dumps(self.dimensions_table) if self.dimensions_table else "{}"
        data['specifications'] = json.dumps(self.specifications) if self.specifications else "{}"
        return data


class TargetHandbagsScraper:
    """Advanced scraper for Target handbags with pagination and detail extraction"""

    def __init__(self, max_products: Optional[int] = None, delay_min: float = 1.0, 
                 delay_max: float = 3.0, headless: bool = True, verbose: bool = False):
        """
        Initialize the scraper.

        Args:
            max_products: Maximum number of products to scrape (None for all)
            delay_min: Minimum delay between requests in seconds
            delay_max: Maximum delay between requests in seconds
            headless: Run browser in headless mode
            verbose: Enable verbose logging
        """
        self.max_products = max_products
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.headless = headless
        self.verbose = verbose
        self.products: List[ProductMetadata] = []
        self.base_url = "https://www.target.com/c/handbags-purses-accessories/-/N-5xtbo"
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None

        if verbose:
            logger.setLevel(logging.DEBUG)

    async def setup(self):
        """Setup browser and context"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context(
            ignore_https_errors=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        logger.info("Browser setup complete")

    async def cleanup(self):
        """Cleanup browser resources (order matters on Windows to avoid closed-pipe errors)."""
        try:
            if self.context:
                await self.context.close()
                self.context = None
            if self.browser:
                await self.browser.close()
                self.browser = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
            await asyncio.sleep(0.25)  # let event loop finish transports on Windows
        except Exception as e:
            logger.debug(f"Cleanup: {e}")
        logger.info("Browser cleanup complete")

    async def _random_delay(self):
        """Add random delay between requests"""
        delay = random.uniform(self.delay_min, self.delay_max)
        await asyncio.sleep(delay)

    async def _extract_product_card_data(self, card_html: str) -> Optional[ProductMetadata]:
        """Extract product data from a product card HTML"""
        try:
            soup = BeautifulSoup(card_html, 'html.parser')
            
            # Extract product ID and URL (multiple fallbacks for different card layouts)
            title_link = soup.find('a', {'data-test': '@web/ProductCard/title'})
            if not title_link:
                title_link = soup.select_one('a[href*="/p/"][href*="/A-"]')
            if not title_link:
                title_link = soup.find('a', href=re.compile(r'/p/.*/A-\d+'))
            if not title_link:
                title_link = soup.find('a', href=re.compile(r'/A-\d+'))
            if not title_link:
                return None

            product_url = (title_link.get('href') or '').strip()
            if not product_url or '/A-' not in product_url:
                return None
            product_id = self._extract_product_id(product_url)
            title = title_link.get_text(strip=True) or title_link.get('aria-label') or title_link.get('title') or ""
            if not title:
                title = ""
                for tag in soup.find_all(['h2', 'h3', 'span', 'div']):
                    t = tag.get_text(strip=True)
                    if t and len(t) > 3 and len(t) < 200 and not re.match(r'^\$[\d,.]+$', t):
                        title = t
                        break
            if not title:
                return None
            
            # Extract brand
            brand_link = soup.find('a', {'data-test': '@web/ProductCard/ProductCardBrandAndRibbonMessage/brand'})
            brand = brand_link.get_text(strip=True) if brand_link else ""
            if not brand:
                brand_link = soup.find('a', attrs={'data-test': re.compile(r'brand', re.I)})
                brand = brand_link.get_text(strip=True) if brand_link else brand
            
            # Extract pricing
            current_price_elem = soup.find('span', {'data-test': 'current-price'})
            current_price = self._parse_price(current_price_elem.get_text(strip=True) if current_price_elem else "0")
            if current_price == 0.0:
                # Fallback for variants where price is not tagged as current-price
                price_like = soup.find(string=re.compile(r'\$\s*\d'))
                if price_like:
                    current_price = self._parse_price(str(price_like))
            
            # Extract regular price
            regular_price_elem = soup.find('span', {'data-test': 'comparison-price'})
            regular_price = 0.0
            if regular_price_elem:
                price_text = regular_price_elem.get_text(strip=True)
                match = re.search(r'\$([0-9,.]+)', price_text)
                if match:
                    regular_price = self._parse_price(match.group(1))
            
            # Calculate discount
            discount_percent = 0
            discount_amount = 0.0
            if regular_price > current_price:
                discount_amount = regular_price - current_price
                discount_percent = int((discount_amount / regular_price) * 100)
            
            # Extract rating - look for aria-hidden="true" span that contains numeric rating
            rating = 0.0
            rating_count = 0
            # Find rating stars container first
            rating_container = soup.find('div', class_='styles_ndsRatingStars__uEZcs')
            if rating_container:
                # Find the aria-hidden span that contains the rating number
                rating_spans = rating_container.find_all('span', {'aria-hidden': 'true'})
                for span in rating_spans:
                    text = span.get_text(strip=True)
                    try:
                        rating_val = float(text)
                        if 0 <= rating_val <= 5:  # Valid rating range
                            rating = rating_val
                            break
                    except (ValueError, AttributeError):
                        continue
                # Find rating count
                rating_count_elem = rating_container.find('span', class_='styles_ratingCount__QDWQY')
                if not rating_count_elem:
                    rating_count_elem = rating_container.find('span', {'aria-label': re.compile(r'\d+\s+ratings?', re.I)})
                if rating_count_elem:
                    try:
                        count_text = rating_count_elem.get_text(strip=True)
                        # Extract number from text like "(53)" or "53 ratings"
                        match = re.search(r'(\d+)', count_text)
                        if match:
                            rating_count = int(match.group(1))
                    except (ValueError, AttributeError):
                        pass
            else:
                # Fallback: look for any aria-hidden span with rating
                rating_elem = soup.find('span', {'aria-hidden': 'true'})
                if rating_elem:
                    try:
                        rating = float(rating_elem.get_text(strip=True))
                    except (ValueError, AttributeError):
                        pass
                
                rating_count_elem = soup.find('span', class_='styles_ratingCount__QDWQY')
                if rating_count_elem:
                    try:
                        count_text = rating_count_elem.get_text(strip=True)
                        match = re.search(r'(\d+)', count_text)
                        if match:
                            rating_count = int(match.group(1))
                    except (ValueError, AttributeError):
                        pass
            
            # Extract "bought in last month" info
            bought_text = ""
            strong_tags = soup.find_all('strong')
            if strong_tags and len(strong_tags) > 0:
                bought_text = strong_tags[0].get_text(strip=True)
            
            # Extract colors
            colors = []
            color_swatches = soup.find('span', {'data-test': '@web/ProductCard/ProductCardSwatches'})
            if color_swatches:
                color_aria = color_swatches.get('aria-label', '')
                if color_aria:
                    colors = [c.strip() for c in color_aria.split(',')]

            # Primary image URL from card
            card_images: List[str] = []
            primary_picture = soup.find('picture', {'data-test': '@web/ProductCard/ProductCardImage/primary'})
            if primary_picture:
                img = primary_picture.find('img', src=True)
                if img and img.get('src'):
                    card_images.append(img['src'].split('?')[0] + '?wid=800&hei=800&qlt=80&fmt=pjpeg')
                else:
                    first_source = primary_picture.find('source', srcset=True)
                    if first_source and first_source.get('srcset'):
                        srcset = first_source['srcset'].split(',')[0].strip().split()[0]
                        if srcset:
                            card_images.append(srcset)

            # Best-seller flag: stable selector
            best_seller = False
            bestseller_elem = soup.find(attrs={'aria-label': lambda x: x and 'bestseller' in (x or '').lower()})
            if bestseller_elem or (soup.find(string=re.compile(r'Bestseller', re.I))):
                best_seller = True

            # New-arrival flag: "New at target" in brand/ribbon area
            is_new = False
            brand_ribbon = soup.find('div', class_=lambda c: c and 'brandAndRibbonWrapper' in str(c))
            if brand_ribbon and 'new at' in (brand_ribbon.get_text() or '').lower():
                is_new = True
            if not is_new and re.search(r'New at\s+target', card_html, re.I):
                is_new = True

            # Sale/clearance
            is_sale = bool(soup.find('span', {'data-test': 'current-price'}) and 'sale' in card_html.lower())
            is_clearance = 'clearance' in card_html.lower()
            if not is_sale and regular_price > 0 and current_price < regular_price:
                is_sale = True

            return ProductMetadata(
                product_id=product_id,
                title=title,
                url=f"https://www.target.com{product_url}" if product_url.startswith('/') else product_url,
                brand=brand,
                price_current=current_price,
                price_regular=regular_price,
                discount_percent=discount_percent,
                discount_amount=discount_amount,
                rating=rating,
                rating_count=rating_count,
                bought_last_month=bought_text,
                colors=colors,
                images=card_images,
                is_sale=is_sale,
                is_clearance=is_clearance,
                is_new=is_new,
                best_seller=best_seller
            )
        except Exception as e:
            logger.error(f"Error extracting product card data: {e}")
            return None

    async def _expand_specifications_if_present(self, page: Page) -> None:
        """Expand 'About this item' if needed, then Specifications, and wait for spec content in the DOM."""
        try:
            # Some pages nest Specifications inside "About this item"; expand it first so the Specs section exists
            about_section = await page.query_selector('[data-test*="ProductDetailCollapsible-AboutThisItem"], [data-test*="AboutThisItem"]')
            if about_section:
                about_btn = await about_section.query_selector('button')
                if about_btn:
                    expanded = await about_btn.get_attribute('aria-expanded')
                    if expanded != 'true':
                        await about_btn.scroll_into_view_if_needed()
                        await about_btn.click()
                        await asyncio.sleep(0.4)

            # data-test is on parent (e.g. @web/.../ProductDetailCollapsible-Specifications), not on button
            spec_section = await page.query_selector('[data-test*="ProductDetailCollapsible-Specifications"]')
            if not spec_section:
                # Fallback: click button that contains "Specifications" text (works when data-test varies)
                try:
                    spec_locator = page.locator('button').filter(has_text=re.compile(r'Specifications', re.I))
                    if await spec_locator.count() > 0:
                        first_btn = spec_locator.first
                        expanded = await first_btn.get_attribute('aria-expanded')
                        if expanded != 'true':
                            await first_btn.scroll_into_view_if_needed()
                            await first_btn.click()
                            await asyncio.sleep(0.5)
                except Exception:
                    pass
            else:
                spec_btn = await spec_section.query_selector('button')
                if spec_btn:
                    expanded = await spec_btn.get_attribute('aria-expanded')
                    if expanded != 'true':
                        await spec_btn.scroll_into_view_if_needed()
                        await spec_btn.click()
                        await asyncio.sleep(0.5)
            # Wait for spec content to be visible before we capture HTML
            try:
                await page.wait_for_selector(
                    'div[data-test="item-details-specifications"]',
                    state='visible',
                    timeout=5000
                )
                await asyncio.sleep(0.3)
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"Could not expand Specifications: {e}")

    def _parse_specifications_section(self, soup: BeautifulSoup) -> Tuple[Dict[str, str], Dict[str, str], str]:
        """Parse Specifications from div[data-test='item-details-specifications'].
        Each item is a div with <b>Key:</b> value or <b>Key</b>: value; stop at itemDetailsTabMarketplaceMessage.
        """
        dimensions_table: Dict[str, str] = {}
        specifications: Dict[str, str] = {}
        material_text = ""

        # Target the Specifications content container (inside collapsible)
        spec_container = soup.find('div', {'data-test': 'item-details-specifications'})
        if not spec_container:
            # Fallback 1: find via ProductDetailCollapsible-Specifications then collapsibleContentDiv
            collapsible = soup.find(attrs={'data-test': re.compile(r'ProductDetailCollapsible-Specifications')})
            if collapsible:
                content_div = collapsible.find('div', {'data-test': 'collapsibleContentDiv'})
                if content_div:
                    spec_container = content_div.find('div', {'data-test': 'item-details-specifications'})
        if not spec_container:
            # Fallback 2: find smallest div that has spec-like content (Dimensions (Overall): / TCIN:) and multiple <b>
            candidates = [
                d for d in soup.find_all('div')
                if ('Dimensions (Overall):' in d.get_text() or 'TCIN:' in d.get_text())
                and len(d.find_all('b')) >= 2
            ]
            if candidates:
                spec_container = min(candidates, key=lambda d: len(d.get_text()))
        if not spec_container:
            return dimensions_table, specifications, material_text

        def _parse_spec_row(block) -> None:
            """Parse a single row: <b>Key:</b> value or <b>Key</b>: value; skip if no colon or empty value."""
            b = block.find('b')
            if not b:
                return
            key = b.get_text(strip=True).rstrip(':').strip()
            if not key:
                return
            full_text = block.get_text(separator=' ', strip=True)
            if ':' not in full_text:
                return
            value = full_text.split(':', 1)[1].strip()
            if not value or len(value) > 1000:
                return
            specifications[key] = value

        # Iterate direct child divs; stop at disclaimer
        for div in spec_container.find_all('div', recursive=False):
            if div.get('data-test') == 'itemDetailsTabMarketplaceMessage':
                break
            _parse_spec_row(div)

        # If direct-child parsing got nothing, try any div inside (nested: <div><div><b>Key:</b> value</div><hr></div>)
        if not specifications:
            for block in spec_container.find_all('div'):
                if block is spec_container:
                    continue
                if block.get('data-test') == 'itemDetailsTabMarketplaceMessage':
                    break
                _parse_spec_row(block)

        # dimensions_table: map Dimension-like keys to a simple dict for structured use
        for key, value in list(specifications.items()):
            key_lower = key.lower()
            if 'dimensions' in key_lower and 'overall' in key_lower:
                dimensions_table['dimensions_overall'] = value
            elif 'height' in key_lower:
                dimensions_table['height'] = value
            elif 'width' in key_lower:
                dimensions_table['width'] = value
            elif 'depth' in key_lower:
                dimensions_table['depth'] = value
            elif 'material' in key_lower or 'shell' in key_lower:
                material_text = value
        if not material_text:
            for k, v in specifications.items():
                if 'material' in k.lower():
                    material_text = v
                    break

        return dimensions_table, specifications, material_text

    async def _extract_product_detail(self, page: Page, product_url: str) -> Optional[ProductMetadata]:
        """Extract detailed product information from product detail page."""
        last_error = None
        for attempt in range(2):  # initial + 1 retry on timeout
            try:
                await self._random_delay()
                # Use longer timeout for slow product pages; avoid 'networkidle' (unreliable on SPAs)
                page.set_default_timeout(60000)
                await page.goto(product_url, wait_until='domcontentloaded', timeout=60000)
                # Wait for main content instead of networkidle (which often times out at 30s on Target)
                await page.wait_for_selector('h1[data-test="product-title"]', timeout=60000)

                # Expand Specifications so we can parse them
                await self._expand_specifications_if_present(page)

                html = await page.content()
                soup = BeautifulSoup(html, 'html.parser')

                title_elem = soup.find('h1', {'data-test': 'product-title'})
                title = title_elem.get_text(strip=True) if title_elem else ""
                product_id = self._extract_product_id(product_url)

                price_elem = soup.find('span', {'data-test': 'product-price'})
                current_price = self._parse_price(price_elem.get_text(strip=True) if price_elem else "0")
                regular_price_elem = soup.find('span', {'data-test': 'product-regular-price'})
                regular_price = 0.0
                if regular_price_elem:
                    match = re.search(r'\$([0-9,.]+)', regular_price_elem.get_text(strip=True))
                    if match:
                        regular_price = self._parse_price(match.group(1))
                sale_price = current_price if (regular_price > 0 and current_price < regular_price) else 0.0

                # Category breadcrumb (ProductDetailBreadcrumbs: nav[aria-label=Breadcrumbs], a[data-test=@web/Breadcrumbs/BreadcrumbLink])
                category_breadcrumb = ""
                breadcrumb_module = soup.find('div', {'data-module-type': 'ProductDetailBreadcrumbs'})
                nav = soup.find('nav', {'aria-label': 'Breadcrumbs'}) if not breadcrumb_module else breadcrumb_module.find('nav', {'aria-label': 'Breadcrumbs'})
                if not nav:
                    nav = soup.find('nav', {'data-test': '@web/Breadcrumbs/BreadcrumbNav'})
                if nav:
                    links = nav.find_all('a', {'data-test': '@web/Breadcrumbs/BreadcrumbLink'})
                    if not links:
                        links = nav.find_all('a')
                    category_breadcrumb = ' > '.join(a.get_text(strip=True) for a in links if a.get_text(strip=True))

                # All gallery images (no alt filter)
                images: List[str] = []
                gallery = soup.find('section', {'aria-label': 'Image gallery'})
                if gallery:
                    for img in gallery.find_all('img', src=True):
                        src = img.get('src')
                        if src and 'target.scene7.com' in src:
                            if src not in images:
                                images.append(src)
                if not images:
                    for elem in soup.find_all(attrs={'data-test': re.compile(r'image-gallery-item')}):
                        img = elem.find('img', src=True)
                        if img and img.get('src') and 'target.scene7.com' in img.get('src', ''):
                            src = img['src']
                            if src not in images:
                                images.append(src)
                images = images[:15]

                # Highlights: bullet list under product (PdpHighlightsSection). Single source for bullets.
                highlights: List[str] = []
                highlights_section = soup.find('div', {'id': 'PdpHighlightsSection'})
                if highlights_section:
                    for li in highlights_section.find_all('li'):
                        t = li.get_text(strip=True)
                        if t:
                            highlights.append(t)
                feature_bullets = list(highlights)  # same content, kept for output schema

                # Specifications: structured key/value (Dimensions, Shell Material, TCIN, etc.) – different from highlights
                dimensions_table, specifications, material_text = self._parse_specifications_section(soup)
                dimensions: Dict[str, str] = {}
                for highlight in highlights:
                    if 'measurements' in highlight.lower():
                        dimensions['measurements'] = highlight
                    elif 'drop' in highlight.lower():
                        dimensions['handle_drop'] = highlight
                for k, v in dimensions_table.items():
                    dimensions[k] = v
                if not material_text and specifications:
                    for k, v in specifications.items():
                        if 'material' in k.lower():
                            material_text = v
                            break

                # Description: "Fit & style" block. Often the same bullets as PdpHighlightsSection – avoid duplicating.
                description = ""
                desc_heading = soup.find('h2', string=lambda s: s and 'Fit & style' in (s or ''))
                if desc_heading:
                    parent = desc_heading.find_parent()
                    if parent:
                        raw_desc = parent.get_text(strip=True)[:500]
                        if highlights:
                            body_after_heading = raw_desc.replace("Fit & style", "", 1).strip().lower()
                            highlights_joined = " ".join(h.strip().lower() for h in highlights)
                            # If the body is essentially the highlights list, keep only the heading
                            if len(body_after_heading) > 15 and (
                                highlights_joined in body_after_heading or body_after_heading in highlights_joined
                            ):
                                description = "Fit & style"
                            else:
                                description = raw_desc
                        else:
                            description = raw_desc

                seller = ""
                seller_link = soup.find('a', {'data-test': 'targetPlusExtraInfoSection'})
                if seller_link:
                    seller = seller_link.get_text(strip=True)

                colors = []
                color_carousel = soup.find('div', class_='styles_ndsCarousel__yMTV9')
                if color_carousel:
                    color_links = color_carousel.find_all('a', class_='styles_ndsChip__lwwR_')
                    colors = [link.get_text(strip=True) for link in color_links]
                color_selected = ""
                for part in product_url.split('/'):
                    if part and part in [c.lower() for c in colors]:
                        color_selected = part
                        break

                return ProductMetadata(
                    product_id=product_id,
                    title=title,
                    url=product_url,
                    price_current=current_price,
                    price_regular=regular_price,
                    sale_price=sale_price,
                    category_breadcrumb=category_breadcrumb,
                    description=description,
                    material_text=material_text,
                    highlights=highlights,
                    feature_bullets=feature_bullets,
                    images=images,
                    dimensions=dimensions,
                    dimensions_table=dimensions_table,
                    specifications=specifications,
                    seller=seller,
                    colors=colors,
                    color_selected=color_selected
                )
            except Exception as e:
                last_error = e
                if "Timeout" in str(e) and attempt == 0:
                    logger.warning(f"Timeout on {product_url}, retrying once...")
                    continue
                break
        if last_error:
            logger.error(f"Error extracting product detail from {product_url}: {last_error}")
        return None

    async def _get_listing_page(self, page: Page, url: str) -> str:
        """Get a listing page and return HTML content"""
        try:
            logger.info(f"Fetching: {url}")
            await page.goto(url, wait_until='domcontentloaded', timeout=60000)
            
            # Wait for product cards to load (60s for slow loads)
            await page.wait_for_selector('[data-test="@web/site-top-of-funnel/ProductCardWrapper"]', timeout=60000)
            
            # Scroll to load lazy-loaded images
            await page.evaluate('window.scrollBy(0, window.innerHeight)')
            await asyncio.sleep(1)
            
            html = await page.content()
            return html
        except Exception as e:
            logger.error(f"Error fetching listing page: {e}")
            return ""

    async def scrape_listing_page(self, page: Page, url: str) -> List[ProductMetadata]:
        """Scrape all products from a listing page"""
        products = []
        
        try:
            html = await self._get_listing_page(page, url)
            if not html:
                return products
            
            soup = BeautifulSoup(html, 'html.parser')
            
            # Find all product cards
            product_cards = soup.find_all('div', {'data-test': '@web/site-top-of-funnel/ProductCardWrapper'})
            logger.info(f"Found {len(product_cards)} product cards on page")
            
            for card in product_cards:
                if self.max_products and len(self.products) + len(products) >= self.max_products:
                    break
                
                # Convert card back to HTML string for extraction
                card_html = str(card)
                product = await self._extract_product_card_data(card_html)
                
                if product:
                    products.append(product)
                    logger.info(f"Extracted: {product.title[:50]}...")
                
                await self._random_delay()
            
            return products
        except Exception as e:
            logger.error(f"Error scraping listing page: {e}")
            return products

    async def get_next_page_url(self, page: Page) -> Optional[str]:
        """Get the next page URL from pagination. Scroll to bottom first so pagination is in DOM.
        
        Target uses button-based pagination that triggers JS navigation. We need to:
        1. Check if next button exists and is enabled
        2. Extract the page number from the pagination selector
        3. Construct the URL with page parameter or use Nao= offset
        """
        try:
            # Scroll to bottom so pagination / "Next" is visible and in DOM
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.8)
            
            # Check pagination container exists
            pagination_container = await page.query_selector('div[data-test="listing-page-pagination"]')
            if not pagination_container:
                logger.debug("No pagination container found")
                return None
            
            # Method 1: Try to find the next button (button[data-test="next"])
            next_button = await page.query_selector('button[data-test="next"]')
            if next_button:
                disabled = await next_button.get_attribute('disabled')
                if disabled is None:  # Button is enabled
                    # Get current URL to construct next page URL
                    current_url = page.url
                    
                    # Try to extract current page number from the page selector
                    page_selector_text = await page.query_selector('span.styles_span__c6JxQ')
                    if page_selector_text:
                        text = await page_selector_text.inner_text()
                        # Extract "page X of Y" pattern
                        match = re.search(r'page\s+(\d+)\s+of\s+(\d+)', text, re.I)
                        if match:
                            current_page = int(match.group(1))
                            total_pages = int(match.group(2))
                            if current_page < total_pages:
                                next_page_num = current_page + 1
                                # Construct URL with page parameter
                                if '?' in current_url:
                                    # Remove existing page parameter if present
                                    base_url = current_url.split('?')[0]
                                    params = current_url.split('?')[1]
                                    # Parse and update params
                                    parsed = urlparse(current_url)
                                    query_params = parse_qs(parsed.query)
                                    query_params['Nao'] = [str((next_page_num - 1) * 24)]  # Target uses 24 items per page typically
                                    new_query = urlencode(query_params, doseq=True)
                                    new_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
                                    return new_url
                                else:
                                    # Add page parameter
                                    return f"{current_url}?Nao={(next_page_num - 1) * 24}"
                    
                    # Fallback: Click button and get new URL (but this navigates, so we need different approach)
                    # Instead, try to find URL pattern from page structure
                    # Target typically uses Nao= parameter for pagination (offset-based)
                    # Each page shows ~24 products, so Nao increments by 24
                    if 'Nao=' in current_url:
                        match = re.search(r'Nao=(\d+)', current_url)
                        if match:
                            current_offset = int(match.group(1))
                            next_offset = current_offset + 24
                            return current_url.replace(f'Nao={current_offset}', f'Nao={next_offset}')
                    else:
                        # First page, add Nao=24 for page 2
                        return f"{current_url}?Nao=24" if '?' not in current_url else f"{current_url}&Nao=24"
            
            # Method 2: Try link-based pagination (fallback for older pages)
            selectors = [
                'a[aria-label="Go to next page"]',
                'a[aria-label*="next" i]',
                'nav[aria-label*="pagination" i] a[rel="next"]',
                'a[data-test*="pagination" i][href*="page"]',
                'a[href*="Ntt="][href*="page="]',
            ]
            for sel in selectors:
                next_el = await page.query_selector(sel)
                if next_el:
                    href = await next_el.get_attribute('href')
                    if href and ('page' in href or 'Nao=' in href or 'next' in href.lower()):
                        return f"https://www.target.com{href}" if href.startswith('/') else href
            
            # Method 3: Extract from page selector dropdown (if it exists)
            # The page selector shows "page 1 of 50", we can increment
            page_text_elem = await page.query_selector('button[data-test="select"] span.styles_span__c6JxQ')
            if page_text_elem:
                text = await page_text_elem.inner_text()
                match = re.search(r'page\s+(\d+)\s+of\s+(\d+)', text, re.I)
                if match:
                    current_page = int(match.group(1))
                    total_pages = int(match.group(2))
                    if current_page < total_pages:
                        current_url = page.url
                        next_offset = current_page * 24  # Assuming 24 items per page
                        if 'Nao=' in current_url:
                            return current_url.replace(re.search(r'Nao=\d+', current_url).group(), f'Nao={next_offset}')
                        else:
                            sep = '&' if '?' in current_url else '?'
                            return f"{current_url}{sep}Nao={next_offset}"
            
            return None
        except Exception as e:
            logger.error(f"Error getting next page URL: {e}")
            return None

    def _extract_product_id(self, url: str) -> str:
        """Extract product ID from URL"""
        import re
        match = re.search(r'/A-(\d+)', url)
        if match:
            return match.group(1)
        return ""

    def _parse_price(self, price_str: str) -> float:
        """Parse price string to float"""
        try:
            import re
            match = re.search(r'[\d,.]+', price_str.replace(',', ''))
            if match:
                return float(match.group())
        except (ValueError, AttributeError):
            pass
        return 0.0

    async def scrape(self, include_details: bool = False):
        """
        Scrape Target handbags with optional detail extraction.

        Args:
            include_details: If True, fetch detailed info for each product
        """
        try:
            await self.setup()
            listing_page = await self.context.new_page()
            detail_page = await self.context.new_page() if include_details else None
            
            current_url = self.base_url
            page_num = 1
            
            while current_url and (not self.max_products or len(self.products) < self.max_products):
                logger.info(f"Scraping page {page_num}...")
                
                products = await self.scrape_listing_page(listing_page, current_url)
                self.products.extend(products)
                
                # If include_details is True, fetch detail pages and merge
                if include_details:
                    for product in products:
                        if not product.url:
                            continue
                        # Use a dedicated page so listing pagination stays on the listing URL.
                        detail = await self._extract_product_detail(detail_page, product.url) if detail_page else None
                        if detail:
                            product.images = detail.images or product.images
                            product.highlights = detail.highlights or product.highlights
                            product.feature_bullets = detail.feature_bullets or product.feature_bullets
                            product.dimensions = detail.dimensions or product.dimensions
                            product.dimensions_table = detail.dimensions_table or product.dimensions_table
                            product.specifications = detail.specifications or product.specifications
                            product.description = detail.description or product.description
                            product.seller = detail.seller or product.seller
                            product.category_breadcrumb = detail.category_breadcrumb or product.category_breadcrumb
                            product.material_text = detail.material_text or product.material_text
                            if detail.sale_price > 0:
                                product.sale_price = detail.sale_price
                            if detail.colors:
                                product.colors = detail.colors
                            if detail.price_current > 0:
                                product.price_current = detail.price_current
                            if detail.price_regular > 0:
                                product.price_regular = detail.price_regular
                            if detail.color_selected:
                                product.color_selected = detail.color_selected
                        await self._random_delay()
                
                # Check for next page
                current_url = await self.get_next_page_url(listing_page)
                if current_url:
                    page_num += 1
                    logger.info(f"Next page available: {current_url}")
                else:
                    logger.info("No more pages available")
                    break
            
            logger.info(f"Scraping complete. Total products: {len(self.products)}")
            await listing_page.close()
            if detail_page:
                await detail_page.close()
            
        except Exception as e:
            logger.error(f"Error during scraping: {e}")
        finally:
            await self.cleanup()

    def save_json(self, output_path: str = "../output/target_handbags_scraped.json"):
        """Save products as JSON"""
        try:
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                data = [product.to_dict() for product in self.products]
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved {len(self.products)} products to {output_path}")
        except Exception as e:
            logger.error(f"Error saving JSON: {e}")

    def save_jsonl(self, output_path: str = "../output/target_handbags.jsonl"):
        """Save products as JSONL"""
        try:
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                for product in self.products:
                    f.write(json.dumps(product.to_dict(), ensure_ascii=False) + '\n')
            
            logger.info(f"Saved {len(self.products)} products to {output_path}")
        except Exception as e:
            logger.error(f"Error saving JSONL: {e}")

    def save_csv(self, output_path: str = "../output/target_handbags.csv"):
        """Save products as CSV"""
        try:
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)
            
            if not self.products:
                logger.warning("No products to save")
                return
            
            data = [product.to_dict() for product in self.products]
            fieldnames = list(data[0].keys())
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(data)
            
            logger.info(f"Saved {len(self.products)} products to {output_path}")
        except Exception as e:
            logger.error(f"Error saving CSV: {e}")

    def save_all(self, output_dir: str = "../output"):
        """Save products in all formats"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.save_json(f"{output_dir}/target_handbags_{timestamp}.json")
        self.save_jsonl(f"{output_dir}/target_handbags_{timestamp}.jsonl")
        self.save_csv(f"{output_dir}/target_handbags_{timestamp}.csv")


async def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Scrape Target handbags')
    parser.add_argument('--max-products', type=int, default=None, help='Maximum products to scrape')
    parser.add_argument('--delay-min', type=float, default=1.5, help='Minimum delay between requests')
    parser.add_argument('--delay-max', type=float, default=3.0, help='Maximum delay between requests')
    parser.add_argument('--headless', action='store_true', default=True, help='Run in headless mode')
    parser.add_argument('--verbose', action='store_true', help='Verbose logging')
    parser.add_argument('--details', action='store_true', help='Extract detailed product info')
    parser.add_argument('--output-dir', default='../output', help='Output directory')
    
    args = parser.parse_args()
    
    scraper = TargetHandbagsScraper(
        max_products=args.max_products,
        delay_min=args.delay_min,
        delay_max=args.delay_max,
        headless=args.headless,
        verbose=args.verbose
    )
    
    await scraper.scrape(include_details=args.details)
    scraper.save_all(args.output_dir)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (BrokenPipeError, ValueError):
        try:
            import sys
            sys.stdout.close()
            sys.stderr.close()
        except Exception:
            pass
        raise SystemExit(0)
