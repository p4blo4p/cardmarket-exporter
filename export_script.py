
import os
import csv
import time
import argparse
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# --- CONFIGURACIÓN ---
parser = argparse.ArgumentParser(description='Cardmarket Exporter Pro v3.0')
parser.add_argument('--year', help='Año filtro (ej. 2025)')
parser.add_argument('--include-purchases', action='store_true', help='Exportar Compras')
parser.add_argument('--include-sales', action='store_true', help='Exportar Ventas')
args = parser.parse_args()

# --- VARIABLES DE ENTORNO ---
# RECOMENDADO: Toda la cadena de document.cookie
CM_COOKIE = os.environ.get('CM_COOKIE', '').strip()
# OPCIONAL: Solo el PHPSESSID
CM_PHPSESSID = os.environ.get('CM_PHPSESSID', '').strip()
# CRÍTICO: Debe ser el de tu navegador actual
CM_USER_AGENT = os.environ.get('CM_USER_AGENT', '').strip()

CSV_FILE = 'cardmarket_export.csv'

def get_headers(ua, cookie_str):
    return {
        'User-Agent': ua,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,video/webm,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.8,en-US;q=0.5,en;q=0.3',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Cookie': cookie_str,
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Priority': 'u=1',
    }

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
        try:
            headers = get_headers(ua, cookie_str)
            response = session.get(paginated_url, headers=headers, timeout=15)
            
            if 'Logout' not in response.text:
                print(f"[!] ERROR: Sesión perdida en página {page_num}.")
                return new_data

            soup = BeautifulSoup(response.text, 'html.parser')
            table_body = soup.select_one('div.table-body')
            if not table_body:
                print(f"[*] Fin de datos en página {page_num}.")
                break
                
            rows = table_body.select('div.row')
            if not rows: break

            for row in rows:
                id_el = row.select_one('.col-orderId')
                if not id_el: continue
                order_id = id_el.get_text(strip=True)

                if order_id in existing_ids:
                    print("[*] Pedidos antiguos alcanzados. Sincronización completa.")
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
        except Exception as e:
            print(f"[!] Error: {e}")
            break
    return new_data

def run():
    cookie_to_use = CM_COOKIE if CM_COOKIE else f"PHPSESSID={CM_PHPSESSID}"
    ua_to_use = CM_USER_AGENT
    
    if not CM_PHPSESSID and not CM_COOKIE:
        print("[!] ERROR: No has definido CM_COOKIE ni CM_PHPSESSID.")
        return
    if not ua_to_use:
        print("[!] ERROR: CM_USER_AGENT es obligatorio en la v3.0.")
        return

    existing_ids, all_rows = load_existing_data()
    start_dt = datetime(int(args.year), 1, 1) if args.year else None

    with requests.Session() as s:
        print("[*] Validando identidad con Cloudflare...")
        headers = get_headers(ua_to_use, cookie_to_use)
        
        try:
            # Intentamos acceder a una página que requiere login
            check = s.get("https://www.cardmarket.com/en/Magic/Orders/Received", headers=headers, timeout=10)
            
            if 'Logout' in check.text:
                print("[+] ACCESO CONCEDIDO. La cookie es válida.")
            else:
                print("[!] ERROR DE VALIDACIÓN.")
                print(f"[*] Código de respuesta: {check.status_code}")
                # Guardamos lo que ha pasado para inspeccionar
                with open('error_log.html', 'w', encoding='utf-8') as f:
                    f.write(check.text)
                print("[*] Se ha guardado 'error_log.html'. Si ves un captcha, usa Datos Móviles.")
                
                if "attention required" in check.text.lower() or "cloudflare" in check.text.lower():
                    print("[!] BLOQUEO: Cloudflare ha detectado el script. SOLUCIÓN:")
                    print("1. Activa el MODO AVIÓN 5 segundos.")
                    print("2. Usa DATOS MÓVILES (no WiFi).")
                    print("3. Genera el comando de cookies DE NUEVO.")
                return
        except Exception as e:
            print(f"[!] Error crítico: {e}")
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
            print("[*] No se encontraron pedidos nuevos.")

if __name__ == "__main__":
    run()
