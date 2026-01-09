
import os
import csv
import time
import argparse
from datetime import datetime
from playwright.sync_api import sync_playwright

# Configuration from CLI
parser = argparse.ArgumentParser(description='Cardmarket Order Exporter')
parser.add_argument('--start-date', help='Format: YYYY-MM-DD')
parser.add_argument('--end-date', help='Format: YYYY-MM-DD')
parser.add_argument('--year', help='Full year e.g. 2025')
args = parser.parse_argument_group().parser.parse_args()

USER_NAME = os.environ.get('CM_USERNAME')
PASSWORD = os.environ.get('CM_PASSWORD')

if not USER_NAME or not PASSWORD:
    print("Error: CM_USERNAME and CM_PASSWORD environment variables are required.")
    exit(1)

def parse_date_range():
    start_dt = None
    end_dt = datetime.now()
    
    if args.year:
        start_dt = datetime(int(args.year), 1, 1)
        end_dt = datetime(int(args.year), 12, 31)
    elif args.start_date:
        start_dt = datetime.strptime(args.start_date, '%Y-%m-%d')
        if args.end_date:
            end_dt = datetime.strptime(args.end_date, '%Y-%m-%d')
            
    return start_dt, end_dt

def scrape_table(page, url, filename, start_dt, end_dt):
    print(f"Scraping {url}...")
    page.goto(url)
    
    # Handle cookie banner if present
    if page.query_selector('#cookie-allow-all-button'):
        page.click('#cookie-allow-all-button')

    all_data = []
    has_next = True
    page_num = 1

    while has_next:
        print(f"Processing page {page_num}...")
        rows = page.query_selector_all('div.table-body > div.row')
        
        if not rows:
            print("No rows found on this page.")
            break

        for row in rows:
            try:
                # Basic selectors based on Cardmarket structure
                # Note: Cardmarket HTML classes change, these are generic targets
                order_id = row.query_selector('.col-orderId').inner_text().strip() if row.query_selector('.col-orderId') else "N/A"
                date_str = row.query_selector('.col-date').inner_text().strip() if row.query_selector('.col-date') else ""
                # Attempt to parse date
                row_date = None
                try:
                    # Cardmarket uses various formats, common is DD.MM.YY HH:mm
                    row_date = datetime.strptime(date_str.split(' ')[0], '%d.%m.%y')
                except:
                    pass

                # Filter by date
                if start_dt and row_date and row_date < start_dt:
                    has_next = False # Since orders are usually sorted by date descending
                    continue
                if end_dt and row_date and row_date > end_dt:
                    continue

                status = row.query_selector('.col-status').inner_text().strip() if row.query_selector('.col-status') else "N/A"
                user = row.query_selector('.col-user').inner_text().strip() if row.query_selector('.col-user') else "N/A"
                total = row.query_selector('.col-total').inner_text().strip() if row.query_selector('.col-total') else "N/A"

                all_data.append({
                    'Order ID': order_id,
                    'Date': date_str,
                    'User': user,
                    'Status': status,
                    'Total': total,
                    'Source': url
                })
            except Exception as e:
                print(f"Error parsing row: {e}")

        # Check for next page
        next_btn = page.query_selector('a[aria-label="Next Page"]')
        if next_btn and has_next:
            next_btn.click()
            page.wait_for_load_state('networkidle')
            page_num += 1
            time.sleep(2) # Rate limit protection
        else:
            has_next = False

    return all_data

def run():
    start_dt, end_dt = parse_date_range()
    print(f"Exporting from {start_dt or 'beginning'} to {end_dt}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36")
        page = context.new_page()

        # Login
        print("Logging in...")
        page.goto("https://www.cardmarket.com/en/Magic/MainPage/Login")
        page.fill('input[name="_username"]', USER_NAME)
        page.fill('input[name="_password"]', PASSWORD)
        page.click('input[type="submit"]')
        page.wait_for_load_state('networkidle')

        if "Login" in page.title():
            print("Login failed. Check credentials or CAPTCHA.")
            browser.close()
            return

        final_results = []
        
        # Targets
        targets = []
        if true: targets.append("https://www.cardmarket.com/en/Magic/Orders/Received")
        if true: targets.append("https://www.cardmarket.com/en/Magic/Sales/Arrived")

        for target in targets:
            data = scrape_table(page, target, "export.csv", start_dt, end_dt)
            final_results.extend(data)

        # Write CSV
        if final_results:
            keys = final_results[0].keys()
            with open('cardmarket_export.csv', 'w', newline='', encoding='utf-8') as f:
                dict_writer = csv.DictWriter(f, fieldnames=keys)
                dict_writer.writeheader()
                dict_writer.writerows(final_results)
            print(f"Successfully exported {len(final_results)} records to cardmarket_export.csv")
        else:
            print("No data found for the selected range.")

        browser.close()

if __name__ == "__main__":
    run()
