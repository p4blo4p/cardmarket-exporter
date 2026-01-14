
import os
import csv
import time
import argparse
import requests
import re
from bs4 import BeautifulSoup
from datetime import datetime

# --- CONFIGURACIÓN ---
parser = argparse.ArgumentParser(description='Cardmarket Exporter Pro v3.1')
parser.add_argument('--year', help='Año filtro (ej. 2025)')
parser.add_argument('--include-purchases', action='store_true', help='Exportar Compras')
parser.add_argument('--include-sales', action='store_true', help='Exportar Ventas')
parser.add_argument('--debug', action='store_true', help='Mostrar cabeceras enviadas')
args = parser.parse_args()

CM_COOKIE = os.environ.get('CM_COOKIE', '').strip()
CM_PHPSESSID = os.environ.get('CM_PHPSESSID', '').strip()
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
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
    }

def print_debug_log(response):
    """Imprime un diagnóstico detallado en la terminal"""
    print("-" * 50)
    print("DEBUG LOG - DETALLES DE LA RESPUESTA")
    print("-" * 50)
    print(f"URL: {response.url}")
    print(f"Estado HTTP: {response.status_code}")
    
    # Extraer Título de la página
    title = "No encontrado"
    soup = BeautifulSoup(response.text, 'html.parser')
    if soup.title:
        title = soup.title.string.strip()
    print(f"Título HTML: {title}")

    # Detectar Cloudflare o Bloqueos
    content_lower = response.text.lower()
    if "cloudflare" in content_lower:
        print("Detección: [!] CLOUDFLARE DETECTADO")
    if "attention required" in content_lower:
        print("Detección: [!] CAPTCHA O ATENCIÓN REQUERIDA")
    if "logout" in content_lower:
        print("Sesión: [OK] El botón de Logout está presente.")
    else:
        print("Sesión: [X] NO LOGUEADO.")

    # Mostrar fragmento del cuerpo si no hay login
    if 'Logout' not in response.text:
        print("
Fragmento del cuerpo (primeros 300 caracteres):")
        clean_text = re.sub(r'\s+', ' ', response.text[:300]).strip()
        print(f"--- {clean_text} ---")
    
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
    print(f"[*] Escaneando: {url}")
    new_data = []
    page_num = 1
    
    while True:
        paginated_url = f"{url}?site={page_num}"
        headers = get_headers(ua, cookie_str)
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

        print(f"[*] Página {page_num}: {len(new_data)} pedidos nuevos.")
        if not soup.select_one('a[aria-label="Next Page"]'): break
        page_num += 1
        time.sleep(2)
        
    return new_data

def run():
    cookie_to_use = CM_COOKIE if CM_COOKIE else f"PHPSESSID={CM_PHPSESSID}"
    ua_to_use = CM_USER_AGENT
    
    if not CM_PHPSESSID and not CM_COOKIE:
        print("[!] ERROR: No has definido CM_COOKIE ni CM_PHPSESSID.")
        return
    if not ua_to_use:
        print("[!] ERROR: CM_USER_AGENT es obligatorio.")
        return

    if args.debug:
        print(f"DEBUG: User-Agent usado: {ua_to_use}")
        print(f"DEBUG: Cookies usadas: {cookie_to_use[:50]}...")

    existing_ids, all_rows = load_existing_data()
    start_dt = datetime(int(args.year), 1, 1) if args.year else None

    with requests.Session() as s:
        print("[*] Verificando conexión...")
        headers = get_headers(ua_to_use, cookie_to_use)
        
        try:
            check = s.get("https://www.cardmarket.com/en/Magic/Orders/Received", headers=headers, timeout=10)
            
            if 'Logout' in check.text:
                print("[+] ACCESO CONCEDIDO.")
            else:
                print("[!] FALLO DE VALIDACIÓN")
                print_debug_log(check)
                return
        except Exception as e:
            print(f"[!] Error de red: {e}")
            return

        new_items = []
        if args.include_purchases:
            new_items.extend(scrape_section(s, "https://www.cardmarket.com/en/Magic/Orders/Received", start_dt, existing_ids, ua_to_use, cookie_to_use))
        if args.include_sales:
            new_items.extend(scrape_section(s, "https://www.cardmarket.com/en/Magic/Sales/Sent", start_dt, existing_ids, ua_to_use, cookie_to_use))

        if new_items:
            all_rows.extend(new_items)
            keys = ['Order ID', 'Date', 'User', 'Status', 'Total', 'Type']
            with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(all_rows)
            print(f"[+] ÉXITO: {len(new_items)} pedidos nuevos guardados.")
        else:
            print("[*] No hay pedidos nuevos.")

if __name__ == "__main__":
    run()
