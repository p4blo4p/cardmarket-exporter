
import os
import csv
import time
import argparse
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# Configuración de argumentos
parser = argparse.ArgumentParser(description='Cardmarket Exporter para Termux')
parser.add_argument('--year', help='Año (ej. 2025)')
parser.add_argument('--include-purchases', action='store_true', help='Exportar Compras')
parser.add_argument('--include-sales', action='store_true', help='Exportar Ventas')
args = parser.parse_args()

USER_NAME = os.environ.get('CM_USERNAME')
PASSWORD = os.environ.get('CM_PASSWORD')
CSV_FILE = 'cardmarket_export.csv'

# User-Agent consistente de navegador moderno
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

HEADERS = {
    'User-Agent': UA,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
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
            print(f"[*] Registros previos cargados: {len(existing_ids)}")
        except: pass
    return existing_ids, rows

def scrape_section(session, url, start_dt, existing_ids):
    print(f"[*] Accediendo a: {url}")
    new_data = []
    page_num = 1
    
    while True:
        paginated_url = f"{url}?site={page_num}"
        scrape_headers = HEADERS.copy()
        scrape_headers['Referer'] = "https://www.cardmarket.com/en/Magic"
        
        response = session.get(paginated_url, headers=scrape_headers)
        
        if response.status_code == 401:
            print("[!] Error 401: Sesión no válida.")
            return new_data
            
        if response.status_code != 200:
            print(f"[!] Error {response.status_code} en página {page_num}.")
            break
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        if not any('Logout' in a.get('href', '') for a in soup.find_all('a', href=True)):
            print("[!] La sesión parece haberse cerrado.")
            break

        table_body = soup.select_one('div.table-body')
        if not table_body:
            print("[*] No se encontraron datos en esta sección.")
            break
            
        rows = table_body.select('div.row')
        if not rows: break

        page_duplicates = 0
        for row in rows:
            try:
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
                        print(f"[*] Pedido antiguo detectado ({date_str}). Parando.")
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
            except Exception as e:
                print(f"[!] Error procesando pedido: {e}")

        print(f"[*] Página {page_num}: {len(new_data)} nuevos pedidos acumulados.")

        if page_duplicates == len(rows):
            print("[*] Sincronización completa alcanzada en esta página.")
            break

        if not soup.select_one('a[aria-label="Next Page"]'):
            break
        
        page_num += 1
        time.sleep(2)

    return new_data

def run():
    if not USER_NAME or not PASSWORD:
        print("[!] CM_USERNAME y CM_PASSWORD no están configurados.")
        return

    existing_ids, all_rows = load_existing_data()
    start_dt = datetime(int(args.year), 1, 1) if args.year else None

    with requests.Session() as s:
        print("[*] Preparando sesión...")
        login_page_url = "https://www.cardmarket.com/en/Magic/MainPage/Login"
        
        # 1. Obtener la página de login
        r_init = s.get(login_page_url, headers=HEADERS)
        soup_init = BeautifulSoup(r_init.text, 'html.parser')
        
        # 2. Capturar TODOS los campos del formulario de login de forma dinámica
        login_form = soup_init.find('form')
        if not login_form:
            print("[!] No se pudo encontrar el formulario de login. ¿Estás bloqueado por IP?")
            return

        payload = {}
        for input_tag in login_form.find_all('input'):
            name = input_tag.get('name')
            value = input_tag.get('value', '')
            if name:
                payload[name] = value

        # 3. Sobrescribir con nuestras credenciales
        payload['_username'] = USER_NAME
        payload['_password'] = PASSWORD
        # Asegurar que el botón de submit esté presente si existe en el HTML
        submit_btn = login_form.find('button', {'type': 'submit'}) or login_form.find('input', {'type': 'submit'})
        if submit_btn and submit_btn.get('name'):
            payload[submit_btn.get('name')] = submit_btn.get('value', 'Login')

        action_url = login_form.get('action', login_page_url)
        if not action_url.startswith('http'):
            action_url = "https://www.cardmarket.com" + (action_url if action_url.startswith('/') else '/' + action_url)

        # 4. Enviar Login
        print("[*] Enviando credenciales...")
        login_headers = HEADERS.copy()
        login_headers['Referer'] = login_page_url
        login_headers['Content-Type'] = 'application/x-www-form-urlencoded'
        
        res = s.post(action_url, data=payload, headers=login_headers, allow_redirects=True)
        
        # 5. Verificación de seguridad (Captcha / Bloqueo)
        if "captcha" in res.text.lower():
            print("[!] Cardmarket ha solicitado un CAPTCHA. Intenta loguearte manualmente en tu móvil primero.")
            return

        # 6. Validar si el login fue exitoso buscando indicios de la cuenta
        soup_res = BeautifulSoup(res.text, 'html.parser')
        is_logged = any('Logout' in a.get('href', '') for a in soup_res.find_all('a', href=True))
        
        # A veces el POST redirige y BS4 no ve el logout en el primer frame, forzamos visita a home
        if not is_logged:
            home = s.get("https://www.cardmarket.com/en/Magic", headers=HEADERS)
            soup_res = BeautifulSoup(home.text, 'html.parser')
            is_logged = any('Logout' in a.get('href', '') for a in soup_res.find_all('a', href=True))

        if is_logged:
            print("[+] Login exitoso. Sesión confirmada.")
        else:
            # Detectar errores comunes
            if "invalid" in res.text.lower() or "wrong" in res.text.lower():
                print("[!] Error: Usuario o contraseña incorrectos.")
            else:
                print("[!] Fallo de autenticación desconocido. Verifica tus credenciales.")
            return

        new_items = []
        if args.include_purchases:
            new_items.extend(scrape_section(s, "https://www.cardmarket.com/en/Magic/Orders/Received", start_dt, existing_ids))
        if args.include_sales:
            new_items.extend(scrape_section(s, "https://www.cardmarket.com/en/Magic/Sales/Sent", start_dt, existing_ids))

        if new_items:
            # Fusionar y guardar
            # Nota: para evitar duplicados si algo falló, podrías usar un diccionario por ID
            all_rows.extend(new_items)
            
            keys = ['Order ID', 'Date', 'User', 'Status', 'Total', 'Type']
            with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(all_rows)
            print(f"[+] Finalizado. {len(new_items)} pedidos nuevos guardados en {CSV_FILE}.")
        else:
            print("[*] No se encontraron pedidos nuevos.")

if __name__ == "__main__":
    run()
