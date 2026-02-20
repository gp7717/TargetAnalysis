#!/usr/bin/env python3
"""
Target Handbags Comprehensive Scraper
Extracts complete product metadata matching enterprise data requirements
"""

import requests
import json
import csv
import logging
import time
import re
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ComprehensiveTargetScraper:
    """Comprehensive scraper extracting all required metadata"""
    
    BASE_URL = "https://www.target.com/c/handbags-purses-accessories/-/N-5xtbo"
    
    def __init__(self, delay: float = 2.0, verbose: bool = False):
        self.delay = delay
        self.products = []
        
        if verbose:
            logger.setLevel(logging.DEBUG)
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch and parse a page"""
        try:
            logger.info(f"Fetching: {url}")
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'lxml')
            logger.debug(f"Page size: {len(response.content)} bytes")
            return soup
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
    
    def extract_price(self, text: str) -> Optional[float]:
        """Extract price from text"""
        if not text:
            return None
        text = str(text).replace(',', '')
        match = re.search(r'[\d.]+', text)
        if match:
            try:
                return float(match.group())
            except:
                return None
        return None
    
    def _extract_product_id(self, url: str) -> str:
        """Extract product ID from URL"""
        match = re.search(r'/A-(\d+)', url)
        if match:
            return match.group(1)
        return 'N/A'
    
    def extract_breadcrumbs(self, soup: BeautifulSoup) -> str:
        """Extract category breadcrumb navigation using ProductDetailBreadcrumbs selectors."""
        breadcrumbs = []
        breadcrumb_module = soup.find('div', {'data-module-type': 'ProductDetailBreadcrumbs'})
        nav = soup.find('nav', {'aria-label': 'Breadcrumbs'}) if not breadcrumb_module else breadcrumb_module.find('nav', {'aria-label': 'Breadcrumbs'})
        if not nav:
            nav = soup.find('nav', {'data-test': '@web/Breadcrumbs/BreadcrumbNav'})
        if nav:
            links = nav.find_all('a', {'data-test': '@web/Breadcrumbs/BreadcrumbLink'})
            if not links:
                links = nav.find_all('a')
            for link in links:
                text = link.get_text(strip=True)
                if text:
                    breadcrumbs.append(text)
        return ' > '.join(breadcrumbs) if breadcrumbs else 'N/A'
    
    def extract_specifications(self, soup: BeautifulSoup) -> Dict:
        """Extract specifications from product detail page"""
        specs = {}
        
        # Find specifications section
        specs_button = soup.find('button', {'data-test': re.compile('ProductDetailCollapsible-Specifications')})
        if specs_button:
            # Find the disclosure content
            disclosure = specs_button.find_next('div', {'data-test': 'collapsibleContentDiv'})
            if disclosure:
                spec_items = disclosure.find_all('div')
                for item in spec_items:
                    text = item.get_text(strip=True)
                    if ':' in text:
                        key, value = text.split(':', 1)
                        specs[key.strip()] = value.strip()
        
        return specs
    
    def extract_dimensions(self, specs: Dict) -> Optional[str]:
        """Extract dimensions from specifications"""
        for key in specs:
            if 'dimensions' in key.lower():
                return specs[key]
        return None
    
    def extract_material(self, specs: Dict) -> Optional[str]:
        """Extract material from specifications"""
        for key in specs:
            if 'material' in key.lower():
                return specs[key]
        return None
    
    def extract_features_from_specs(self, specs: Dict) -> List[str]:
        """Extract feature bullets from specifications"""
        features = []
        excluded_keys = {'dimensions', 'material', 'tcin', 'upc', 'item number', 'origin'}
        
        for key, value in specs.items():
            key_lower = key.lower()
            if not any(exclude in key_lower for exclude in excluded_keys):
                # Format as feature: "Key: Value"
                features.append(f"{key.strip()}: {value.strip()}")
        
        return features
    
    def extract_product_title(self, soup: BeautifulSoup) -> str:
        """Extract product title from detail page"""
        title_elem = soup.find('h1', {'data-test': 'product-title'})
        if title_elem:
            return title_elem.get_text(strip=True)
        return 'N/A'
    
    def extract_price_from_detail(self, soup: BeautifulSoup) -> Tuple[Optional[float], Optional[float]]:
        """Extract current and regular price from detail page"""
        current_price = None
        regular_price = None
        
        # Current price
        price_span = soup.find('span', {'data-test': 'product-price'})
        if price_span:
            current_price = self.extract_price(price_span.get_text())
        
        # Regular price (often in strikethrough)
        regular_price_elem = soup.find('span', {'data-test': re.compile('original-price|regular-price')})
        if regular_price_elem:
            regular_price = self.extract_price(regular_price_elem.get_text())
        
        if regular_price is None and current_price:
            regular_price = current_price
        
        return current_price, regular_price
    
    def extract_rating(self, soup: BeautifulSoup) -> Tuple[float, int]:
        """Extract rating and review count"""
        rating = 0.0
        review_count = 0
        
        rating_elem = soup.find('span', {'aria-label': re.compile(r'\d+ out of 5 stars')})
        if rating_elem:
            aria_label = rating_elem.get('aria-label', '')
            rating_match = re.search(r'([\d.]+) out of 5', aria_label)
            if rating_match:
                rating = float(rating_match.group(1))
            
            count_span = rating_elem.find_next('span')
            if count_span:
                count_text = count_span.get_text(strip=True)
                try:
                    review_count = int(count_text)
                except:
                    pass
        
        return rating, review_count
    
    def extract_images(self, soup: BeautifulSoup) -> List[str]:
        """Extract all product images"""
        images = []
        
        # Find image gallery
        gallery = soup.find('section', {'aria-label': 'Image gallery'})
        if gallery:
            imgs = gallery.find_all('img')
            for img in imgs:
                src = img.get('src', '')
                if src and 'target.scene7.com' in src:
                    # Clean up URL to get high quality version
                    src_clean = re.sub(r'\?.*', '', src)
                    if src_clean and src_clean not in images:
                        images.append(src_clean)
        
        return images[:10]  # Limit to 10 images
    
    def extract_color_variants(self, soup: BeautifulSoup) -> List[str]:
        """Extract available color variants"""
        colors = []
        
        # Find color variation section
        variation_section = soup.find('div', {'data-test': re.compile('@web/VariationComponent')})
        if variation_section:
            color_buttons = variation_section.find_all('a')
            for btn in color_buttons:
                color_name = btn.get('aria-label', '')
                if 'Color' in color_name:
                    # Extract color name from aria-label like "Color, Pink Vertical Stripe"
                    color_name = color_name.replace('Color, ', '').split(',')[0].strip()
                    if color_name and color_name not in colors:
                        colors.append(color_name)
        
        return colors
    
    def extract_tcin(self, specs: Dict) -> Optional[str]:
        """Extract TCIN from specifications"""
        for key, value in specs.items():
            if 'tcin' in key.lower():
                return value
        return None
    
    def extract_upc(self, specs: Dict) -> Optional[str]:
        """Extract UPC from specifications"""
        for key, value in specs.items():
            if 'upc' in key.lower():
                return value
        return None
    
    def parse_product_card(self, card) -> Optional[Dict]:
        """Parse product card from listing page"""
        try:
            # Basic listing data
            product_id = card.get('data-focusid', '').split('_')[0] or 'N/A'
            
            title_elem = card.find('a', {'data-test': re.compile('@web/ProductCard/title')})
            title = title_elem.text.strip() if title_elem else 'N/A'
            url = urljoin(self.BASE_URL, title_elem.get('href', '')) if title_elem else ''
            
            # Price
            price_elem = card.find('span', {'data-test': 'current-price'})
            current_price = self.extract_price(price_elem.text if price_elem else '0')
            regular_price_elem = card.find('span', {'data-test': re.compile('original-price|regular-price')})
            regular_price = self.extract_price(regular_price_elem.text if regular_price_elem else None) or current_price
            
            # Rating
            rating = 0
            review_count = 0
            rating_elem = card.find('span', {'aria-label': re.compile(r'\d+ ratings')})
            if rating_elem:
                aria_label = rating_elem.get('aria-label', '')
                rating_match = re.search(r'([\d.]+)', aria_label)
                if rating_match:
                    rating = float(rating_match.group(1))
                count_match = re.search(r'(\d+)\s*ratings?', aria_label, re.IGNORECASE)
                if count_match:
                    review_count = int(count_match.group(1))
            
            # Colors
            colors = []
            color_swatches = card.find_all('button', {'title': re.compile(r'Color')})
            for swatch in color_swatches:
                color_name = swatch.get('title', '').replace('Color: ', '').strip()
                if color_name:
                    colors.append(color_name)
            
            # Image
            img_elem = card.find('img', {'role': 'presentation'})
            image_url = img_elem.get('src', '') if img_elem else ''
            
            # Availability
            unavailable = card.find('span', text=re.compile('Out of Stock|Unavailable'))
            in_stock = unavailable is None
            
            # Sale status
            sale_elem = card.find('span', {'aria-label': re.compile('Sale|Clearance', re.IGNORECASE)})
            is_sale = sale_elem is not None
            
            # New badge
            new_elem = card.find('span', {'aria-label': re.compile('new|New', re.IGNORECASE)})
            is_new = new_elem is not None
            
            # Calculate discount
            discount_pct = 0
            discount_amt = 0
            if current_price and regular_price and regular_price > current_price:
                discount_amt = regular_price - current_price
                discount_pct = round((discount_amt / regular_price) * 100, 1)
            
            product = {
                'product_id': product_id,
                'product_name': title,
                'product_url': url,
                'current_price': current_price,
                'sale_price': current_price if is_sale else None,
                'regular_price': regular_price,
                'discount_percent': discount_pct,
                'discount_amount': discount_amt,
                'rating': rating,
                'review_count': review_count,
                'colors': '|'.join(colors) if colors else 'N/A',
                'image_url': image_url,
                'in_stock': in_stock,
                'is_sale': is_sale,
                'is_new': is_new,
                # Will be populated from detail page
                'category_breadcrumb': 'N/A',
                'material_text': 'N/A',
                'description': 'N/A',
                'feature_bullets': 'N/A',
                'dimensions': 'N/A',
                'all_images': '|'.join([image_url]) if image_url else 'N/A',
                'tcin': 'N/A',
                'upc': 'N/A',
                'best_seller': False,
                'brand': 'N/A',
                'scraped_at': datetime.now().isoformat()
            }
            
            return product
            
        except Exception as e:
            logger.debug(f"Error parsing card: {e}")
            return None
    
    def extract_product_details(self, product: Dict) -> Dict:
        """Fetch and extract detailed product information"""
        try:
            soup = self.fetch_page(product['product_url'])
            if not soup:
                return product
            
            # Extract detail information
            product['product_name'] = self.extract_product_title(soup)
            product['category_breadcrumb'] = self.extract_breadcrumbs(soup)
            
            # Price from detail page
            current_price, regular_price = self.extract_price_from_detail(soup)
            if current_price:
                product['current_price'] = current_price
            if regular_price:
                product['regular_price'] = regular_price
            
            # Rating
            rating, review_count = self.extract_rating(soup)
            if rating > 0:
                product['rating'] = rating
            if review_count > 0:
                product['review_count'] = review_count
            
            # Images
            images = self.extract_images(soup)
            if images:
                product['all_images'] = '|'.join(images)
            
            # Colors
            colors = self.extract_color_variants(soup)
            if colors:
                product['colors'] = '|'.join(colors)
            
            # Specifications
            specs = self.extract_specifications(soup)
            if specs:
                product['material_text'] = self.extract_material(specs) or 'N/A'
                product['dimensions'] = self.extract_dimensions(specs) or 'N/A'
                
                features = self.extract_features_from_specs(specs)
                if features:
                    product['feature_bullets'] = '|'.join(features)
                
                product['tcin'] = self.extract_tcin(specs) or 'N/A'
                product['upc'] = self.extract_upc(specs) or 'N/A'
            
            logger.debug(f"Extracted details for {product['product_name']}")
            
        except Exception as e:
            logger.error(f"Error extracting details: {e}")
        
        return product
    
    def scrape_category_page(self, url: str, page: int) -> Tuple[List[Dict], Optional[str]]:
        """Scrape a category page"""
        page_url = f"{url}?page={page}" if page > 1 else url
        soup = self.fetch_page(page_url)
        if not soup:
            return [], None
        
        # Use proven selector from working advanced scraper
        cards = soup.find_all('div', {'data-test': '@web/site-top-of-funnel/ProductCardWrapper'})
        logger.info(f"Found {len(cards)} products on page {page}")
        
        products = []
        for card in cards:
            product = self.parse_product_card(card)
            if product:
                products.append(product)
        
        next_page = None
        next_button = soup.find('a', {'aria-label': 'Go to next page'})
        if next_button:
            next_page = urljoin(self.BASE_URL, next_button.get('href', ''))
        
        return products, next_page
    
    def scrape(self, max_products: int = None, include_details: bool = True) -> List[Dict]:
        """Scrape products with optional detail extraction"""
        page = 1
        next_url = self.BASE_URL
        
        while next_url and (max_products is None or len(self.products) < max_products):
            products, next_url = self.scrape_category_page(next_url, page)
            
            for product in products:
                if include_details:
                    product = self.extract_product_details(product)
                    time.sleep(self.delay)
                
                self.products.append(product)
                
                if max_products and len(self.products) >= max_products:
                    self.products = self.products[:max_products]
                    return self.products
            
            logger.info(f"Total products: {len(self.products)}")
            
            if next_url:
                logger.info(f"Waiting {self.delay}s before next page...")
                time.sleep(self.delay)
            
            page += 1
        
        logger.info(f"Scraping complete! Total: {len(self.products)}")
        return self.products
    
    def save_json(self, filepath: str):
        """Save as JSON"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.products, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved: {filepath}")
    
    def save_csv(self, filepath: str):
        """Save as CSV"""
        if not self.products:
            logger.warning("No products to save")
            return
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=self.products[0].keys())
            writer.writeheader()
            writer.writerows(self.products)
        logger.info(f"Saved: {filepath}")
    
    def save_all(self, output_dir: str = '../output'):
        """Save in all formats"""
        import os
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.save_json(f'{output_dir}/products_comprehensive_{timestamp}.json')
        self.save_csv(f'{output_dir}/products_comprehensive_{timestamp}.csv')
        
        # Also save without timestamp
        self.save_json(f'{output_dir}/products.json')
        self.save_csv(f'{output_dir}/products.csv')


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Comprehensive Target Scraper')
    parser.add_argument('--max-products', type=int, help='Max products')
    parser.add_argument('--delay', type=float, default=2.0, help='Delay between requests')
    parser.add_argument('--verbose', action='store_true', help='Verbose logging')
    parser.add_argument('--quick', action='store_true', help='Skip detail pages (listings only)')
    parser.add_argument('--output-dir', default='../output', help='Output directory')
    
    args = parser.parse_args()
    
    scraper = ComprehensiveTargetScraper(
        delay=args.delay,
        verbose=args.verbose
    )
    
    logger.info("Starting comprehensive scrape...")
    scraper.scrape(
        max_products=args.max_products,
        include_details=not args.quick
    )
    logger.info(f"Scraped {len(scraper.products)} products")
    
    if scraper.products:
        scraper.save_all(args.output_dir)
        logger.info(f"✓ Saved to {args.output_dir}/")
    else:
        logger.error("No products scraped!")
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except (BrokenPipeError, ValueError):
        # Downstream consumer (e.g. `head`) closed the pipe early.
        try:
            sys.stdout.close()
            sys.stderr.close()
        except Exception:
            pass
        raise SystemExit(0)
