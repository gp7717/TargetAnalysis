"""Quick proxy connectivity test utility."""
import sys
from playwright.sync_api import sync_playwright


def test_proxy(proxy_server: str, timeout_ms: int = 10000) -> bool:
    """Test if a proxy can connect to a simple endpoint."""
    test_url = "https://httpbin.org/ip"
    
    with sync_playwright() as p:
        browser = None
        context = None
        try:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                proxy={"server": proxy_server},
                ignore_https_errors=True,
            )
            page = context.new_page()
            page.goto(test_url, timeout=timeout_ms)
            content = page.content()
            print(f"✓ {proxy_server:40s} - Working")
            return True
        except Exception as e:
            print(f"✗ {proxy_server:40s} - {type(e).__name__}: {str(e)[:50]}")
            return False
        finally:
            if context:
                try:
                    context.close()
                except:
                    pass
            if browser:
                try:
                    browser.close()
                except:
                    pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_proxies.py <proxy1> [proxy2] ...")
        print("Example: python test_proxies.py socks5://184.178.172.11:1080 http://184.178.172.11:8080")
        sys.exit(1)
    
    proxies = sys.argv[1:]
    working = []
    failed = []
    
    print(f"Testing {len(proxies)} proxy configurations...\n")
    for proxy in proxies:
        if test_proxy(proxy):
            working.append(proxy)
        else:
            failed.append(proxy)
    
    print(f"\n{'='*70}")
    print(f"Results: {len(working)} working, {len(failed)} failed")
    if working:
        print("\nWorking proxies:")
        for p in working:
            print(f"  {p}")
