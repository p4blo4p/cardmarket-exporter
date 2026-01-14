
import os
import csv
import time
import argparse
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# --- CONFIGURACIÓN DE ARGUMENTOS ---
parser = argparse.ArgumentParser(description='Cardmarket Exporter Pro')
parser.add_argument('--year', help='Año filtro (ej. 2025)')
parser.add_argument('--include-purchases', action='store_true', help='Exportar Compras')
parser.add_argument('--include-sales', action='store_true', help='Exportar Ventas')
args = parser.parse_args()

# --- VARIABLES DE ENTORNO ---
# RECOMENDADO: Solo necesitas el valor de PHPSESSID (ej: 4h6g...)
CM_PHPSESSID = os.environ.get('CM_PHPSESSID')
# Opcional: Cookie completa
CM_COOKIE = os.environ.get('CM_COOKIE')
# IMPORTANTE: Este User-Agent debe ser similar al de tu navegador móvil
USER_AGENT = 'Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36'

CSV_FILE = 'cardmarket_export.csv'

HEADERS = {
    'User-Agent': USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
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
            print(f"[*] Datos previos: {len(existing_ids)} pedidos cargados.")
        except: pass
    return existing_ids, rows

def scrape_section(session, url, start_dt, existing_ids):
    print(f"[*] Accediendo a: {url}")
    new_data = []
    page_num = 1
    
    while True:
        paginated_url = f"{url}?site={page_num}"
        try:
            response = session.get(paginated_url, headers=HEADERS, timeout=15)
            if response.status_code != 200:
                print(f"[!] Error {response.status_code} en página {page_num}.")
                break
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Verificación de Logout (indicador de sesión activa)
            if 'Logout' not in response.text:
                print(f"[!] Sesión perdida en página {page_num}. Verifica tu cookie.")
                break

            table_body = soup.select_one('div.table-body')
            if not table_body:
                print("[*] Fin de resultados o sección vacía.")
                break
                
            rows = table_body.select('div.row')
            if not rows: break

            page_duplicates = 0
            for row in rows:
                id_el = row.select_one('.col-orderId')
                if not id_el: continue
                order_id = id_el.get_text(strip=True)

                if order_id in existing_ids:
                    page_duplicates += 1
                    continue

                date_el = row.select_one('.col-date')
                date_str = date_el.get_text(strip=True) if date_el else ""
                
                try:
                    row_dt = datetime.strptime(date_str.split(' ')[0], '%d.%m.%y')
                    if start_dt and row_dt < start_dt:
                        print(f"[*] Alcanzado límite de fecha ({date_str}). Parando.")
                        return new_data
                except: pass

                status = row.select_one('.col-status').get_text(strip=True) if row.select_one('.col-status') else ""
                user = row.select_one('.col-user').get_text(strip=True) if row.select_one('.col-user') else ""
                total = row.select_one('.col-total').get_text(strip=True) if row.select_one('.col-total') else ""

                new_data.append({
                    'Order ID': order_id,
                    'Date': date_str,
                    'User': user,
                    'Status': status,
                    'Total': total,
                    'Type': 'Purchase' if 'Received' in url else 'Sale'
                })
                existing_ids.add(order_id)

            print(f"[*] Página {page_num}: {len(new_data)} pedidos nuevos.")

            if page_duplicates == len(rows):
                print("[*] Todos los pedidos de esta página ya existen. Sincronización terminada.")
                break

            if not soup.select_one('a[aria-label="Next Page"]'):
                break
            
            page_num += 1
            time.sleep(2)
        except Exception as e:
            print(f"[!] Error crítico: {e}")
            break

    return new_data

def run():
    if not CM_PHPSESSID and not CM_COOKIE:
        print("[!] ERROR: Debes configurar CM_PHPSESSID o CM_COOKIE.")
        print("[!] Revisa la pestaña 'Guía de Sesión' en la web.")
        return

    existing_ids, all_rows = load_existing_data()
    start_dt = datetime(int(args.year), 1, 1) if args.year else None

    with requests.Session() as s:
        # Configurar cookies
        if CM_PHPSESSID:
            s.cookies.set('PHPSESSID', CM_PHPSESSID, domain='.cardmarket.com')
        elif CM_COOKIE:
            s.headers.update({'Cookie': CM_COOKIE})

        print("[*] Validando sesión...")
        try:
            # Visitamos la página principal de Magic para verificar login
            check = s.get("https://www.cardmarket.com/en/Magic", headers=HEADERS, timeout=10)
            soup = BeautifulSoup(check.text, 'html.parser')
            
            title = soup.title.string.strip() if soup.title else "Sin título"
            
            if 'Logout' in check.text:
                print(f"[+] SESIÓN CONFIRMADA. Bienvenido.")
            else:
                print(f"[!] SESIÓN NO ACTIVA.")
                print(f"[*] Título página: {title}")
                if "Attention Required" in title or "Cloudflare" in title:
                    print("[!] BLOQUEO: Cloudflare ha detectado el script. Prueba a usar DATOS MÓVILES en Termux.")
                else:
                    print("[!] ERROR: Tu PHPSESSID ha expirado o es incorrecto.")
                return
        except Exception as e:
            print(f"[!] Error de conexión: {e}")
            return

        new_items = []
        if args.include_purchases:
            new_items.extend(scrape_section(s, "https://www.cardmarket.com/en/Magic/Orders/Received", start_dt, existing_ids))
        if args.include_sales:
            new_items.extend(scrape_section(s, "https://www.cardmarket.com/en/Magic/Sales/Sent", start_dt, existing_ids))

        if new_items:
            all_rows.extend(new_items)
            keys = ['Order ID', 'Date', 'User', 'Status', 'Total', 'Type']
            with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(all_rows)
            print(f"[+] ÉXITO: {len(new_items)} pedidos nuevos guardados en {CSV_FILE}.")
        else:
            print("[*] No hay pedidos nuevos para añadir.")

if __name__ == "__main__":
    run()
