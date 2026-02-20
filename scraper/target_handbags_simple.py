#!/usr/bin/env python3
"""
Simple Target Handbags Scraper - Lightweight version for quick testing
Uses requests + BeautifulSoup instead of Playwright
Faster setup, but may miss some JavaScript-rendered content
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

class SimpleTargetScraper:
    """Lightweight scraper for Target handbags using requests + BeautifulSoup"""
    
    BASE_URL = "https://www.target.com/c/handbags-purses-accessories/-/N-5xtbo"
    
    def __init__(self, delay: float = 2.0, verbose: bool = False, max_pages: int = None):
        """
        Initialize scraper
        
        Args:
            delay: Seconds to wait between requests
            verbose: Enable verbose logging
            max_pages: Maximum pages to scrape (None = all)
        """
        self.delay = delay
        self.max_pages = max_pages
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
            return BeautifulSoup(response.content, 'lxml')
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
    
    def extract_price(self, text: str) -> Optional[float]:
        """Extract price from text"""
        if not text:
            return None
        match = re.search(r'\$?([\d,]+\.?\d*)', text.replace(',', ''))
        if match:
            try:
                return float(match.group(1))
            except:
                return None
        return None
    
    def parse_product_card(self, card) -> Optional[Dict]:
        """Parse individual product card"""
        try:
            # Extract product ID
            product_id = card.get('data-focusid', '').split('_')[0] or 'N/A'
            
            # Title
            title_elem = card.find('a', {'data-test': re.compile('@web/ProductCard/title')})
            title = title_elem.text.strip() if title_elem else 'N/A'
            
            # URL
            url = urljoin(self.BASE_URL, title_elem.get('href', '')) if title_elem else ''
            
            # Price
            price_elem = card.find('span', {'data-test': 'current-price'})
            current_price = self.extract_price(price_elem.text if price_elem else '0')
            
            # Regular price (often in strikethrough)
            regular_price_elem = card.find('span', {'data-test': re.compile('original-price|regular-price')})
            regular_price = self.extract_price(regular_price_elem.text if regular_price_elem else None) or current_price
            
            # Rating - look for aria-label with ratings
            rating = 0
            review_count = 0
            rating_elem = card.find('span', {'aria-label': re.compile(r'\d+ ratings')})
            if rating_elem:
                # Extract "X ratings" or "X out of 5 stars"
                aria_label = rating_elem.get('aria-label', '')
                rating_match = re.search(r'([\d.]+)', aria_label)
                if rating_match:
                    rating = float(rating_match.group(1))
                count_match = re.search(r'(\d+)\s*ratings?', aria_label, re.IGNORECASE)
                if count_match:
                    review_count = int(count_match.group(1))
            
            # Colors available
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
            
            # Calculate discount
            discount_pct = 0
            discount_amt = 0
            if current_price and regular_price and regular_price > current_price:
                discount_amt = regular_price - current_price
                discount_pct = round((discount_amt / regular_price) * 100, 1)
            
            product = {
                'product_id': product_id,
                'title': title,
                'url': url,
                'current_price': current_price,
                'regular_price': regular_price,
                'discount_amount': discount_amt,
                'discount_percent': discount_pct,
                'rating': rating,
                'review_count': review_count,
                'colors': '|'.join(colors) if colors else 'N/A',
                'image_url': image_url,
                'in_stock': in_stock,
                'is_sale': is_sale,
                'scraped_at': datetime.now().isoformat()
            }
            
            return product
            
        except Exception as e:
            logger.debug(f"Error parsing card: {e}")
            return None
    
    def scrape_category_page(self, url: str, page: int) -> Tuple[List[Dict], Optional[str]]:
        """
        Scrape a category page and return products and next page URL
        
        Returns:
            Tuple of (products list, next_page_url)
        """
        # Add page parameter
        page_url = f"{url}?page={page}" if page > 1 else url
        soup = self.fetch_page(page_url)
        if not soup:
            return [], None
        
        # Find all product cards
        cards = soup.find_all(attrs={'data-focusid': re.compile('_product_card')})
        logger.info(f"Found {len(cards)} products on page {page}")
        
        products = []
        for card in cards:
            product = self.parse_product_card(card)
            if product:
                products.append(product)
        
        # Find next page link
        next_page = None
        next_button = soup.find('a', {'aria-label': 'Go to next page'})
        if next_button:
            next_page = urljoin(self.BASE_URL, next_button.get('href', ''))
        
        return products, next_page
    
    def scrape(self, max_products: int = None) -> List[Dict]:
        """
        Scrape all products
        
        Args:
            max_products: Stop after collecting this many products
        
        Returns:
            List of product dictionaries
        """
        page = 1
        next_url = self.BASE_URL
        
        while next_url and (max_products is None or len(self.products) < max_products):
            if self.max_pages and page > self.max_pages:
                logger.info(f"Reached max pages limit: {self.max_pages}")
                break
            
            products, next_url = self.scrape_category_page(next_url, page)
            self.products.extend(products)
            
            logger.info(f"Total products collected: {len(self.products)}")
            
            if max_products and len(self.products) >= max_products:
                self.products = self.products[:max_products]
                break
            
            if next_url:
                logger.info(f"Found next page, waiting {self.delay}s...")
                time.sleep(self.delay)
            
            page += 1
        
        logger.info(f"Scraping complete! Total products: {len(self.products)}")
        return self.products
    
    def save_json(self, filepath: str):
        """Save products as JSON"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.products, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved JSON to {filepath}")
    
    def save_csv(self, filepath: str):
        """Save products as CSV"""
        if not self.products:
            logger.warning("No products to save")
            return
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=self.products[0].keys())
            writer.writeheader()
            writer.writerows(self.products)
        logger.info(f"Saved CSV to {filepath}")
    
    def save_jsonl(self, filepath: str):
        """Save products as JSONL (line-delimited JSON)"""
        with open(filepath, 'w', encoding='utf-8') as f:
            for product in self.products:
                f.write(json.dumps(product, ensure_ascii=False) + '\n')
        logger.info(f"Saved JSONL to {filepath}")
    
    def save_all(self, output_dir: str = '../output'):
        """Save in all formats"""
        import os
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.save_json(f'{output_dir}/products_{timestamp}.json')
        self.save_csv(f'{output_dir}/products_{timestamp}.csv')
        self.save_jsonl(f'{output_dir}/products_{timestamp}.jsonl')
        
        # Also save without timestamp for convenience
        self.save_json(f'{output_dir}/products.json')
        self.save_csv(f'{output_dir}/products.csv')
        self.save_jsonl(f'{output_dir}/products.jsonl')


def main():
    """CLI interface"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Simple Target Handbags Scraper')
    parser.add_argument('--max-products', type=int, help='Maximum products to scrape')
    parser.add_argument('--max-pages', type=int, help='Maximum pages to scrape')
    parser.add_argument('--delay', type=float, default=2.0, help='Delay between requests (seconds)')
    parser.add_argument('--verbose', action='store_true', help='Verbose logging')
    parser.add_argument('--output-dir', default='../output', help='Output directory')
    
    args = parser.parse_args()
    
    scraper = SimpleTargetScraper(
        delay=args.delay,
        verbose=args.verbose,
        max_pages=args.max_pages
    )
    
    logger.info("Starting scrape...")
    scraper.scrape(max_products=args.max_products)
    logger.info(f"Scraped {len(scraper.products)} products")
    
    if scraper.products:
        scraper.save_all(args.output_dir)
        logger.info(f"✓ Data saved to {args.output_dir}/")
    else:
        logger.error("No products scraped!")
        sys.exit(1)


if __name__ == '__main__':
    main()
