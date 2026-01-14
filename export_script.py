
import os
import csv
import time
import argparse
import requests
import re
from bs4 import BeautifulSoup
from datetime import datetime

# --- CONFIGURACIÓN ---
parser = argparse.ArgumentParser(description='Cardmarket Exporter Pro v3.2')
parser.add_argument('--year', help='Año filtro (ej. 2025)')
parser.add_argument('--include-purchases', action='store_true', help='Exportar Compras')
parser.add_argument('--include-sales', action='store_true', help='Exportar Ventas')
parser.add_argument('--debug', action='store_true', help='Mostrar cabeceras enviadas')
args = parser.parse_args()

CM_COOKIE = os.environ.get('CM_COOKIE', '').strip()
CM_USER_AGENT = os.environ.get('CM_USER_AGENT', '').strip()

CSV_FILE = 'cardmarket_export.csv'

def get_headers(ua, cookie_str):
    return {
        'User-Agent': ua,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.8,en-US;q=0.5,en;q=0.3',
        'Connection': 'keep-alive',
        'Cookie': cookie_str,
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'max-age=0',
    }

def print_debug_log(response):
    print("-" * 50)
    print("DIAGNÓSTICO DE ERROR (v3.2)")
    print("-" * 50)
    print(f"Estado HTTP: {response.status_code}")
    
    soup = BeautifulSoup(response.text, 'html.parser')
    title = soup.title.string.strip() if soup.title else "Sin título"
    print(f"Título de la página: {title}")

    if response.status_code == 401 or "Login" in title:
        print("[!] MOTIVO: SESIÓN NO VÁLIDA (401)")
        print("    Tus cookies no tienen el PHPSESSID o ha caducado.")
        if "PHPSESSID" not in CM_COOKIE:
            print("    FALLO DETECTADO: La variable CM_COOKIE no contiene 'PHPSESSID'.")
    
    if "cloudflare" in response.text.lower() or response.status_code == 403:
        print("[!] MOTIVO: BLOQUEO DE CLOUDFLARE (403)")
        print("    La IP o el User-Agent no coinciden con la cookie.")

    print("
Cabeceras enviadas (Resumen):")
    print(f"UA: {CM_USER_AGENT[:50]}...")
    print(f"Cookie (inicio): {CM_COOKIE[:40]}...")
    print("-" * 50)

def load_existing_data():
    existing_ids = set()
    rows = []
    if os.path.exists(CSV_FILE):
        try:
            with open(CSV_FILE, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('Order ID'):
                        existing_ids.add(row.get('Order ID'))
                        rows.append(row)
        except: pass
    return existing_ids, rows

def scrape_section(session, url, start_dt, existing_ids, ua, cookie_str):
    print(f"[*] Accediendo a: {url}")
    new_data = []
    page_num = 1
    
    while True:
        paginated_url = f"{url}?site={page_num}"
        headers = get_headers(ua, cookie_str)
        try:
            response = session.get(paginated_url, headers=headers, timeout=15)
            
            if 'Logout' not in response.text:
                print(f"[!] ERROR: Sesión perdida en página {page_num}.")
                print_debug_log(response)
                return new_data

            soup = BeautifulSoup(response.text, 'html.parser')
            table_body = soup.select_one('div.table-body')
            if not table_body: break
                
            rows = table_body.select('div.row')
            if not rows: break

            for row in rows:
                id_el = row.select_one('.col-orderId')
                if not id_el: continue
                order_id = id_el.get_text(strip=True)

                if order_id in existing_ids:
                    return new_data

                date_el = row.select_one('.col-date')
                date_str = date_el.get_text(strip=True) if date_el else ""
                
                try:
                    row_dt = datetime.strptime(date_str.split(' ')[0], '%d.%m.%y')
                    if start_dt and row_dt < start_dt:
                        return new_data
                except: pass

                status = row.select_one('.col-status').get_text(strip=True) if row.select_one('.col-status') else ""
                user = row.select_one('.col-user').get_text(strip=True) if row.select_one('.col-user') else ""
                total = row.select_one('.col-total').get_text(strip=True) if row.select_one('.col-total') else ""

                new_data.append({
                    'Order ID': order_id, 'Date': date_str, 'User': user, 
                    'Status': status, 'Total': total, 
                    'Type': 'Purchase' if 'Received' in url else 'Sale'
                })
                existing_ids.add(order_id)

            print(f"[*] Página {page_num}: {len(new_data)} nuevos.")
            if not soup.select_one('a[aria-label="Next Page"]'): break
            page_num += 1
            time.sleep(2)
        except Exception as e:
            print(f"[!] Error: {e}")
            break
            
    return new_data

def run():
    if not CM_COOKIE or not CM_USER_AGENT:
        print("[!] ERROR: Faltan variables CM_COOKIE o CM_USER_AGENT.")
        return

    if "PHPSESSID" not in CM_COOKIE:
        print("[!] ATENCIÓN: No se detecta PHPSESSID en la cookie.")
        print("    Tu navegador móvil podría estar ocultando la cookie de sesión.")
        print("    Prueba a copiarla manualmente desde las herramientas de desarrollador o usa otro navegador (ej. Kiwi Browser).")

    existing_ids, all_rows = load_existing_data()
    start_dt = datetime(int(args.year), 1, 1) if args.year else None

    with requests.Session() as s:
        print("[*] Verificando sesión...")
        headers = get_headers(CM_USER_AGENT, CM_COOKIE)
        
        try:
            check = s.get("https://www.cardmarket.com/en/Magic/Orders/Received", headers=headers, timeout=10)
            if 'Logout' in check.text:
                print("[+] SESIÓN ACTIVA. Iniciando exportación...")
            else:
                print_debug_log(check)
                return
        except Exception as e:
            print(f"[!] Error conexión: {e}")
            return

        new_items = []
        if args.include_purchases:
            new_items.extend(scrape_section(s, "https://www.cardmarket.com/en/Magic/Orders/Received", start_dt, existing_ids, CM_USER_AGENT, CM_COOKIE))
        if args.include_sales:
            new_items.extend(scrape_section(s, "https://www.cardmarket.com/en/Magic/Sales/Sent", start_dt, existing_ids, CM_USER_AGENT, CM_COOKIE))

        if new_items:
            all_rows.extend(new_items)
            keys = ['Order ID', 'Date', 'User', 'Status', 'Total', 'Type']
            with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(all_rows)
            print(f"[+] Exportación finalizada con {len(new_items)} nuevos registros.")
        else:
            print("[*] No hay datos nuevos que exportar.")

if __name__ == "__main__":
    run()
