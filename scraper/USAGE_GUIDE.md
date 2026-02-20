# Comprehensive Scraper - Usage Guide

## Quick Start

### 1. Test with 5 Products (Complete Data)
```bash
python target_handbags_comprehensive.py --max-products 5 --verbose
```
**Time:** 2-3 minutes
**Output:** Full product details with dimensions, materials, features

### 2. Scrape First 50 Products (Details)
```bash
python target_handbags_comprehensive.py --max-products 50
```
**Time:** 5-10 minutes
**Output:** Complete dataset with all fields

### 3. Quick Listing-Only Scrape (No Details)
```bash
python target_handbags_comprehensive.py --max-products 100 --quick
```
**Time:** 3-4 minutes
**Output:** Basic product info (name, price, rating, URL)

### 4. Slow Safe Scrape (Avoid Rate Limiting)
```bash
python target_handbags_comprehensive.py --max-products 50 --delay 5
```
**Time:** 15-20 minutes
**Output:** Same as #2, but safer for server

## Command Line Options

```
--max-products INT       Limit number of products (default: all)
--delay FLOAT            Seconds between requests (default: 2.0)
--verbose                Show detailed logging
--quick                  Skip detail pages (listings only)
--output-dir PATH        Output directory (default: ../output)
```

## Data Output

All runs create in `../output/`:
- `products.json` - Complete structured data
- `products.csv` - Spreadsheet format
- `products_comprehensive_[timestamp].json` - Timestamped backup
- `products_comprehensive_[timestamp].csv` - Timestamped backup

## Extraction Capability

### With `--quick` Flag (Fast)
```
✓ Product name, ID, URL
✓ Current price, regular price
✓ Rating, review count
✓ Basic colors
✓ Image URLs
✓ Stock status

✗ Detailed specifications
✗ Dimensions
✗ Material info
✗ Feature bullets
✗ All color variants
```

### Without `--quick` Flag (Complete)
```
✓ Everything from above
✓ Detailed specifications
✓ Dimensions (height, width, depth)
✓ Material composition
✓ Feature bullets (interior/exterior features, closures, handles, care)
✓ All color variants
✓ Category breadcrumb path
✓ TCIN, UPC codes
✓ Up to 10 product images
```

## Performance Expectations

### Mode Comparison

| Mode | Prod/Min | Time for 50 | Detail Level |
|------|----------|-----------|--------------|
| Listing Only (`--quick`) | 15-20 | 3-4 min | Basic |
| With Details | 5-10 | 5-10 min | Complete |
| Slow/Safe (delay=5) | 2-3 | 15-25 min | Complete |

## Example Workflows

### Workflow 1: Get Initial Dataset
```bash
# Step 1: Test with small sample
python target_handbags_comprehensive.py --max-products 10 --verbose

# Step 2: Full scrape if test successful
python target_handbags_comprehensive.py --max-products 500

# Step 3: Review output
type ..\output\products.csv | head -n 20
```

### Workflow 2: Incremental Collection
```bash
# Day 1: Get first batch
python target_handbags_comprehensive.py --max-products 200 --quick

# Day 2: Get detailed data for analysis
python target_handbags_comprehensive.py --max-products 50

# Day 3: Monitor for price changes
python target_handbags_comprehensive.py --max-products 50 --delay 3
```

### Workflow 3: Database Integration
```bash
# Step 1: Scrape data
python target_handbags_comprehensive.py --max-products 100

# Step 2: Load to database (Python script)
# import json
# from pymongo import MongoClient
# 
# with open('../output/products.json') as f:
#     data = json.load(f)
# 
# client = MongoClient('mongodb://localhost')
# db = client['target']
# db.products.insert_many(data)
```

## Data Fields Extracted

### Pricing
- `current_price` - What you pay now
- `regular_price` - Regular price
- `sale_price` - Sale amount (if on sale)
- `discount_percent` - % off

### Product Info
- `product_name` - Full title
- `brand` - Manufacturer
- `product_id` / `tcin` - Unique ID
- `category_breadcrumb` - Category path

### Details
- `dimensions` - Size specs
- `material_text` - Material type
- `feature_bullets` - Key features
- `colors` - Available colors

### Content
- `image_url` - Primary image
- `all_images` - All images (up to 10)
- `product_url` - Direct link

### Reviews
- `rating` - Star rating
- `review_count` - Number of reviews

### Status
- `is_sale` - On sale?
- `is_new` - New product?
- `in_stock` - In stock?

## Viewing Results

### View as JSON (Pretty Print)
```bash
python -m json.tool ..\output\products.json | more
```

### View as CSV (Excel)
```bash
start ..\output\products.csv
```

### Count Products
```bash
python -c "import json; f=open('../output/products.json'); data=json.load(f); print(f'Total: {len(data)}')"
```

### Find Sale Items
```bash
python
import pandas as pd
df = pd.read_csv('../output/products.csv')
print(df[df['is_sale'] == True][['product_name', 'current_price', 'discount_percent']])
```

### Get Average Price
```bash
python -c "import pandas as pd; df = pd.read_csv('../output/products.csv'); print(f'Avg Price: ${df[\"current_price\"].mean():.2f}')"
```

## Troubleshooting

### Issue: Timeout errors
**Solution:** Increase delay
```bash
python target_handbags_comprehensive.py --max-products 20 --delay 5
```

### Issue: Missing specifications
**Use:** Quick mode (no detail pages)
```bash
python target_handbags_comprehensive.py --quick --max-products 50
```

### Issue: Too slow
**Use:** Quick mode or reduce max-products
```bash
python target_handbags_comprehensive.py --quick --max-products 100
```

### Issue: Memory problems
**Try:** Smaller batches
```bash
python target_handbags_comprehensive.py --max-products 50  # Run multiple times
```

## Advanced Usage

### Save with Custom Delay
```bash
python target_handbags_comprehensive.py --max-products 50 --delay 3 --verbose
```

### Background Execution
```bash
# Windows
start /B python target_handbags_comprehensive.py --max-products 500 > scrape.log

# PowerShell
Start-Process python -ArgumentList "target_handbags_comprehensive.py --max-products 500" -NoNewWindow
```

### Scheduled Daily Scrape
Create `scrape_daily.ps1`:
```powershell
cd C:\SpacePeppers\SpacePeppers\Target\scraper
python target_handbags_comprehensive.py --max-products 50 --delay 3
```

Then schedule with Windows Task Scheduler

## Data Export Options

### To SQL Database
```python
import pandas as pd
from sqlalchemy import create_engine

df = pd.read_csv('../output/products.csv')
engine = create_engine('sqlite:///target_products.db')
df.to_sql('handbags', engine, if_exists='replace')
```

### To Excel with Formatting
```python
import pandas as pd
df = pd.read_csv('../output/products.csv')
df.to_excel('../output/products.xlsx', index=False)
```

### To Google Sheets
```python
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import gspread

# Use gspread library to upload
```

## Performance Tips

1. **Use `--quick` flag** if you only need basic product info
2. **Increase delays** if getting 429 rate limit errors
3. **Run during off-peak hours** (late night, early morning)
4. **Monitor memory** for large batches (1000+ products)
5. **Batch requests** - scrape in 50-100 product chunks

## Next Steps

1. Review output files
2. Verify data quality
3. Load to database if needed
4. Set up scheduled scraping
5. Monitor for price changes
