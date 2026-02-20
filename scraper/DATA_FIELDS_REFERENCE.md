# Data Fields Reference

## Extracted Fields

The comprehensive scraper extracts all required metadata from Target product pages:

### Core Product Information
- `product_id` - Unique product identifier (TCIN)
- `product_name` - Full product title
- `product_url` - Direct link to product page
- `brand` - Product brand/manufacturer
- `category_breadcrumb` - Category path (e.g., "Target > Clothing > Accessories > Handbags")

### Pricing Information
- `current_price` - Current selling price ($)
- `regular_price` - Regular/original price ($)
- `sale_price` - Sale price if on sale (same as current if sale, null otherwise)
- `discount_amount` - Dollar amount off ($)
- `discount_percent` - Discount percentage (%)
- `is_sale` - Boolean: Is product on sale?

### Product Details
- `material_text` - Material composition (e.g., "Canvas", "Faux Leather")
- `dimensions` - Product dimensions (e.g., "14 x 14 x 5 inches")
- `description` - Full product description
- `feature_bullets` - Key features separated by `|`
  - Extracted from specifications section
  - Includes: color options, interior/exterior features, closures, handles, care instructions

### Visual Content
- `image_url` - Primary product image
- `all_images` - All product images separated by `|` (up to 10)

### Product Classification
- `colors` - Available color variants separated by `|`
- `is_new` - Boolean: Is it a new product?
- `is_sale` - Boolean: Is it on sale?
- `in_stock` - Boolean: In stock status

### Ratings & Reviews
- `rating` - Star rating (0.0 to 5.0)
- `review_count` - Number of reviews

### Administrative Fields
- `tcin` - Target product code
- `upc` - Universal product code
- `best_seller` - Boolean: Bestseller badge
- `scraped_at` - Timestamp of data collection

## Usage Examples

### Extract Listing Pages Only (Fast)
```bash
python target_handbags_comprehensive.py --max-products 50 --quick
```
**Speed:** ~2-3 minutes for 50 products
**Data:** Listings + reviews (no detailed specs)

### Extract With Full Details (Complete)
```bash
python target_handbags_comprehensive.py --max-products 50 --delay 2
```
**Speed:** ~10-15 minutes for 50 products
**Data:** Full everything (specs, dimensions, all features)

### Extract All Products
```bash
python target_handbags_comprehensive.py
```
**Speed:** 1-3 hours depending on catalog size
**Data:** Complete dataset

## Output Formats

### CSV Format
```
product_id,product_name,product_url,current_price,regular_price,sale_price,discount_percent,...
94835136,"Champion Handbag...",https://target.com/p/...,19.99,19.99,,0,...
```

### JSON Format
```json
{
  "product_id": "94835136",
  "product_name": "Champion Handbag Unstructured Tote Bag",
  "current_price": 19.99,
  "regular_price": 19.99,
  "dimensions": "14 Inches (H) x 14 Inches (W) x 5 Inches (D)",
  "material_text": "Canvas",
  "feature_bullets": "Unstructured|Double Strap|No Compartments",
  "colors": "Pink Vertical Stripe|Black|Blue",
  "all_images": "https://target.scene7.com/...|https://target.scene7.com/...",
  "rating": 5.0,
  "review_count": 1,
  "is_sale": false,
  "is_new": true,
  "in_stock": true,
  "scraped_at": "2026-02-20T14:30:45.123456"
}
```

## Data Quality Notes

### Field Completeness
- **Always Available:** product_id, product_name, product_url, current_price, colors, image_url
- **Usually Available:** rating, review_count, dimensions, material_text
- **Sometimes Missing:** regular_price, description (if not on detail page), some features

### Handling Missing Data
- Empty fields are marked as "N/A"
- Multiple values are separated by `|`
- Prices are converted to floats
- URLs are normalized

## Integration With Database

### Import to SQL Example
```sql
INSERT INTO products (
  product_id, product_name, current_price, 
  regular_price, dimensions, material, 
  colors, rating, scraped_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
```

### Import to MongoDB Example
```python
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017')
db = client['target_products']
collection = db['handbags']

with open('products.json') as f:
    products = json.load(f)
    collection.insert_many(products)
```

## Performance Metrics

| Metric | Value |
|--------|-------|
| Products per page | 20-30 |
| Listing page time | 5-10 seconds |
| Detail page time | 10-30 seconds |
| Network timeouts | Handled with retry |
| Memory per 1000 products | ~50-100 MB |

## Filtering & Analysis

### Find Sale Items
```python
import pandas as pd
df = pd.read_csv('products.csv')
sales = df[df['is_sale'] == True]
```

### Find High-Rated Products
```python
df = df[df['rating'] >= 4.5]
```

### Find New Items
```python
new_items = df[df['is_new'] == True]
```

### Average Price by Material
```python
df.groupby('material_text')['current_price'].mean()
```

## Data Validation Checklist

- [ ] All product_ids are unique
- [ ] Prices are numeric and > 0
- [ ] Rating is between 0 and 5
- [ ] URLs are valid and start with https://
- [ ] Timestamps are ISO 8601 format
- [ ] No duplicate rows
- [ ] Category breadcrumbs follow hierarchy

## Troubleshooting

### Missing Dimensions
- Some products may not have detailed specs
- Check detail page HTML for specification accordion

### Incorrect Prices
- Sometimes listing price differs from detail page
- Detail page is authoritative

### Incomplete Colors
- Color variants may require page interaction
- All visible colors are extracted

### Missing Images
- Limited to first 10 images
- Scene7 URLs are preferred
