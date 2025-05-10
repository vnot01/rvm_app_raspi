


import time
import serial
import requests # Untuk API call
import json     # Untuk API call
import cv2      # Untuk OpenCV (kamera)
import os       # Untuk membuat direktori jika perlu
from datetime import datetime # Untuk nama file unik
import logging
from logging.handlers import TimedRotatingFileHandler
# from pyzbar.pyzbar import decode # Untuk QR Code nanti, bisa di-uncomment jika sudah siap

# --- Konfigurasi Aplikasi RVM ---
RVM_ID_NAME = "1" # Dapatnya dari mana?
RVM_NAME = "RVM Kantin Pusat Gedung A" # Dapatnya dari mana?
RVM_API_KEY = "RVM001-VfAbiZSp29OUXLEhvFaa4Oi7UposHFGW" # GANTI DENGAN YANG VALID
BACKEND_API_BASE_URL = "https://precious-puma-smoothly.ngrok-free.app/api" # URL NGROK ANDA

SERIAL_PORT = '/dev/serial0' 
BAUD_RATE = 115200
SERIAL_TIMEOUT = 1 # Detik

# Header untuk request ke ngrok
NGROK_SKIP_WARNING_HEADER = {'ngrok-skip-browser-warning': 'true'}
IMAGE_SAVE_DIR = "captured_images" # Direktori untuk menyimpan gambar
# --- Konfigurasi Logging Lokal ---
LOG_DIR = "rvm_logs" # Direktori untuk semua file log
LOG_FILENAME_BASE = f"rvm_{RVM_ID_NAME}_{RVM_NAME.replace(' ', '_')}.log" # Nama file log aktif
# Buat direktori log jika belum ada
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)
log_file_path = os.path.join(LOG_DIR, LOG_FILENAME_BASE)

logger = logging.getLogger('RVMBlackbox')
logger.setLevel(logging.INFO) # Tangkap INFO dan level yang lebih tinggi

# Handler untuk menulis ke file dengan rotasi harian, simpan 7 file lama
# File yang dirotasi akan memiliki suffix tanggal, misal: rvm_1_RVM-KAMPUS-A01.log.2025-05-10
file_handler = TimedRotatingFileHandler(
    log_file_path,
    when="midnight", # Rotasi setiap tengah malam
    interval=1,      # Interval 1 hari
    backupCount=7    # Simpan 7 file backup
)
# Format log: Timestamp - RVM_ID - RVM_NAME - Level - Pesan
formatter = logging.Formatter(f'%(asctime)s - RVM_ID:{RVM_ID_NAME} - RVM_NAME:{RVM_NAME} - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# (Opsional) Handler untuk konsol (untuk debugging langsung)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter) # Gunakan format yang sama
console_handler.setLevel(logging.DEBUG) # Tampilkan DEBUG ke konsol jika perlu
# logger.addHandler(console_handler) # Uncomment jika ingin log juga ke konsol via logger

print(f"BLACKBOX: Logging lokal diaktifkan. File utama: {log_file_path}")
logger.info("================ RVM BLACKBOX SESSION START ================")
logger.info(f"RVM ID: {RVM_ID_NAME}, RVM Name: {RVM_NAME}")

# --- Definisi State RVM ---
STATE_STARTUP = "STARTUP"
STATE_IDLE = "IDLE"
STATE_WAITING_FOR_USER_QR = "WAITING_FOR_USER_QR"
STATE_VALIDATING_USER_TOKEN = "VALIDATING_USER_TOKEN"
STATE_USER_AUTHENTICATED = "USER_AUTHENTICATED"
STATE_WAITING_FOR_ITEM = "WAITING_FOR_ITEM" # Ditambahkan untuk kejelasan
STATE_CAPTURING_IMAGE = "CAPTURING_IMAGE"
STATE_PROCESSING_IMAGE_WITH_AI = "PROCESSING_IMAGE_WITH_AI"
STATE_ITEM_ACCEPTED = "ITEM_ACCEPTED"
STATE_ITEM_REJECTED = "ITEM_REJECTED"
STATE_OPERATING_MECHANISM = "OPERATING_MECHANISM"
STATE_ERROR = "ERROR"
STATE_MAINTENANCE = "MAINTENANCE"

# --- Variabel Global Aplikasi ---
current_state = STATE_STARTUP
ser = None 
cap = None # Objek kamera OpenCV
current_user_id = None
current_user_name = None
last_error_message = ""
captured_image_path = None 
deposit_user_identifier = None 
scanned_qr_token_global = None # Untuk menyimpan token QR antar state

# --- Fungsi Utilitas Serial ---
def setup_serial():
    global ser
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=SERIAL_TIMEOUT)
        print(f"SERIAL: Terhubung ke {SERIAL_PORT} pada baudrate {BAUD_RATE}")
        logger.info(f"SERIAL: Terhubung ke {SERIAL_PORT} pada baudrate {BAUD_RATE}")
        time.sleep(2) 
        if ser.in_waiting > 0:
            bytes_cleared = ser.in_waiting
            print(f"SERIAL: Membersihkan {ser.in_waiting} bytes dari buffer input...")
            ser.read(bytes_cleared)
            logger.info(f"SERIAL: Membersihkan {bytes_cleared} bytes dari buffer input.")
        logger.info("SERIAL: Koneksi serial siap.")
        print("SERIAL: Koneksi serial siap.")
        return True
    except serial.SerialException as e:
        last_error_message = f"Tidak bisa membuka port serial {SERIAL_PORT}: {e}"
        print(f"SERIAL ERROR: Tidak bisa membuka port serial {SERIAL_PORT}: {e}")
        logger.error(f"SERIAL ERROR: {last_error_message}")
        return False
    except Exception as e_gen:
        last_error_message = f"Terjadi error tak terduga saat setup serial: {e_gen}"
        logger.error(f"SERIAL ERROR: {last_error_message}")
        print(f"SERIAL ERROR: Terjadi error tak terduga saat setup: {e_gen}")
        return False

def send_to_esp32(command, expected_ack=None, read_timeout=2.5):
    global ser
    if not (ser and ser.isOpen()):
        print("SERIAL ERROR: Koneksi serial tidak terbuka.")
        return None

    if ser.in_waiting > 0:
        print(f"SERIAL: Membersihkan {ser.in_waiting} bytes sisa di buffer RPi sebelum kirim [{command}]...")
        ser.read(ser.in_waiting)

    print(f"SERIAL TX: [{command}]")
    ser.write((command + '\n').encode('utf-8'))
    
    start_time = time.time()
    buffer = ""
    full_response_lines = []
    while (time.time() - start_time) < read_timeout:
        if ser.in_waiting > 0:
            try:
                byte = ser.read(1)
                if not byte: continue
                char = byte.decode('utf-8', errors='ignore')
                if char == '\n':
                    line = buffer.strip()
                    buffer = ""
                    if line: # Hanya proses jika baris tidak kosong
                        print(f"SERIAL RX: [{line}]")
                        full_response_lines.append(line)
                        if expected_ack and line == expected_ack: # Perbandingan eksak
                            return line # Respons yang diharapkan ditemukan
                else:
                    buffer += char
            except Exception as e_read:
                print(f"SERIAL ERROR saat membaca: {e_read}")
                return None # Error saat membaca
        time.sleep(0.01)
    
    # Jika timeout dan expected_ack belum ditemukan, tapi ada respons lain
    if expected_ack and full_response_lines:
        print(f"SERIAL: Timeout menunggu respons spesifik '{expected_ack}' untuk [{command}]. Respons diterima:")
        for r_line in full_response_lines: print(f"  - [{r_line}]")
        return None # Atau kembalikan baris terakhir jika logikanya berbeda
    elif not expected_ack and full_response_lines: # Jika tidak ada ack spesifik, kembalikan baris terakhir yang valid
        return full_response_lines[-1]
    
    print(f"SERIAL: Timeout menunggu respons '{expected_ack}' untuk perintah [{command}]. Tidak ada data atau buffer terakhir: [{buffer.strip()}]")
    return None

# --- Fungsi Utilitas API Backend ---
def make_api_request(method, endpoint, data=None, files=None, params=None, requires_rvm_auth=False):
    global RVM_API_KEY, last_error_message, BACKEND_API_BASE_URL
    
    url = f"{BACKEND_API_BASE_URL}{endpoint}"
    headers = NGROK_SKIP_WARNING_HEADER.copy()
    headers['Accept'] = 'application/json'

    if requires_rvm_auth:
        headers['X-RVM-ApiKey'] = RVM_API_KEY
    
    print(f"API REQ: {method.upper()} {url}")
    # if data: print(f"API REQ DATA: {data}") # Hati-hati jika ada data sensitif
    # if files: print(f"API REQ FILES: {list(files.keys())}")

    try:
        if method.upper() == 'POST':
            if files:
                response = requests.post(url, headers=headers, data=data, files=files, params=params, timeout=30)
            else:
                headers['Content-Type'] = 'application/json'
                response = requests.post(url, headers=headers, json=data, params=params, timeout=30)
        elif method.upper() == 'GET':
            response = requests.get(url, headers=headers, params=params, timeout=30)
        else:
            last_error_message = f"Metode API tidak didukung: {method}"
            print(f"API ERROR: {last_error_message}")
            return None

        print(f"API RESP STATUS: {response.status_code}")
        # Log body respons jika ada error untuk debugging
        if not response.ok: # response.ok adalah True untuk status 2xx
             print(f"API ERROR BODY: {response.text[:500]}") # Tampilkan sebagian body error

        response.raise_for_status() 
        
        if 'application/json' in response.headers.get('Content-Type', ''):
            # print(f"API RESP JSON: {response.json()}") # Hati-hati jika respons besar
            return response.json()
        else:
            # print(f"API RESP TEXT: Non-JSON - {response.text[:200]}")
            last_error_message = "Backend tidak mengembalikan JSON yang valid."
            return {'status': 'error', 'message': last_error_message, 'raw_content': response.text[:200]}
    except requests.exceptions.HTTPError as http_err:
        last_error_message = f"HTTP error: {http_err} - Response: {http_err.response.text[:500] if http_err.response else 'No response body'}"
        logger.error(f"API CALL FAIL (HTTP): {method} {url} - {last_error_message}") # Log error API
        print(f"API ERROR: {last_error_message}")
    except requests.exceptions.RequestException as req_err: # Ini menangkap ConnectionError, Timeout, dll.
        last_error_message = f"Request/Connection error: {req_err}"
        print(f"API ERROR: {last_error_message}")
    except Exception as e:
        last_error_message = f"General API request error: {e}"
        print(f"API ERROR: {last_error_message}")
    return None

def authenticate_rvm_with_backend():
    global current_state, last_error_message
    logger.info("API: Mencoba otentikasi RVM dengan backend...")
    print("API: Mencoba otentikasi RVM dengan backend...")
    payload = {'api_key': RVM_API_KEY}
    response_data = make_api_request('POST', '/rvm/authenticate', data=payload)
    if response_data and response_data.get('status') == 'success':
        rvm_id_from_api = response_data.get('rvm_id', 'N/A')
        logger.info(f"API: RVM (ID Config: {RVM_ID_NAME}, ID API: {rvm_id_from_api}) berhasil terotentikasi.")
        print(f"API: RVM '{RVM_ID_NAME}' (ID: {rvm_id_from_api}) berhasil terotentikasi.")
        return True
    else:
        detail_error = response_data.get('message', 'Tidak ada pesan error spesifik') if response_data else 'Tidak ada respons API'
        last_error_message = f"Gagal otentikasi RVM: {detail_error}"
        logger.error(f"API: Gagal otentikasi RVM. Detail: {response_data if response_data else 'No response'}")
        print(f"API: Gagal otentikasi RVM. Detail: {response_data}")
        # last_error_message = f"Gagal otentikasi RVM: {response_data.get('message', 'Tidak ada pesan error spesifik') if response_data else 'Tidak ada respons API'}"
        return False

# --- Fungsi Kamera ---
def initialize_camera(camera_index=0):
    global cap, last_error_message
    logger.info(f"CAMERA: Mencoba menginisialisasi kamera pada indeks {camera_index}...")
    print(f"CAMERA: Mencoba menginisialisasi kamera pada indeks {camera_index}...")
    cap = cv2.VideoCapture(camera_index)
    time.sleep(1) # Beri waktu kamera untuk inisialisasi
    if not cap.isOpened():
        last_error_message = f"Kamera indeks {camera_index} tidak bisa dibuka."
        logger.error(f"CAMERA ERROR: {last_error_message}")
        print(f"CAMERA ERROR: Tidak bisa membuka kamera pada indeks {camera_index}")
        return False
    logger.info(f"CAMERA: Kamera pada indeks {camera_index} berhasil dibuka.")
    print(f"CAMERA: Kamera pada indeks {camera_index} berhasil dibuka.")
    return True

def capture_image_from_camera(filename_base="item_capture"):
    global cap, last_error_message, IMAGE_SAVE_DIR
    if not (cap and cap.isOpened()):
        last_error_message = "Kamera tidak tersedia atau tidak terbuka untuk capture."
        logger.warning(f"CAMERA: {last_error_message}")
        print("CAMERA ERROR: Kamera tidak tersedia atau tidak terbuka untuk capture.")
        return None
    
    ret, frame = cap.read()
    if not ret or frame is None:
        last_error_message = "Gagal membaca frame dari kamera."
        logger.error(f"CAMERA ERROR: {last_error_message}")
        print("CAMERA ERROR: Gagal mengambil frame dari kamera.")
        return None
    
    try:
        # Buat direktori jika belum ada
        if not os.path.exists(IMAGE_SAVE_DIR):
            os.makedirs(IMAGE_SAVE_DIR)
            logger.info(f"CAMERA: Direktori '{IMAGE_SAVE_DIR}' dibuat.")
            print(f"CAMERA: Direktori '{IMAGE_SAVE_DIR}' dibuat.")

        # Buat nama file unik dengan timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{filename_base}_{timestamp}.jpg"
        save_path = os.path.join(IMAGE_SAVE_DIR, filename)
        cv2.imwrite(save_path, frame)
        logger.info(f"CAMERA: Gambar berhasil diambil dan disimpan ke {save_path}")
        print(f"CAMERA: Gambar berhasil diambil dan disimpan ke {save_path}")
        return save_path
    except Exception as e:
        last_error_message = f"Gagal menyimpan gambar: {e}"
        logger.error(f"CAMERA ERROR: {last_error_message}")
        print(f"CAMERA ERROR: Gagal menyimpan gambar: {e}")
        return None

# --- Logika State Machine ---
def run_rvm(camera_index=0):
    global current_state, ser, cap, current_user_id, current_user_name, last_error_message
    global captured_image_path, deposit_user_identifier, scanned_qr_token_global

    # Tahap inisialisasi awal, dijalankan sekali sebelum loop utama
    # Jika salah satu gagal, current_state akan menjadi STATE_ERROR
    # if not setup_serial():
    #     print(f"CRITICAL ERROR: Gagal setup koneksi serial dengan ESP32. Program berhenti.")
    #     current_state = STATE_ERROR
    #     last_error_message = "Gagal setup koneksi serial dengan ESP32."
    # elif not initialize_camera(camera_index):
    #     current_state = STATE_ERROR
    #     # last_error_message sudah diset oleh initialize_camera()
    # else:
    #     # Jika serial dan kamera OK, baru coba otentikasi RVM dan PING ESP32
    #     # Ini akan dijalankan lagi jika kita masuk ke STATE_STARTUP dari STATE_ERROR
    #     pass # Biarkan STATE_STARTUP menangani ini di loop utama

    # Inisialisasi awal di luar loop utama
    # Jika gagal di sini, program akan berhenti lebih awal atau masuk ke loop error khusus
    # sebelum state machine utama dimulai.
    if not setup_serial():
        logger.critical(f"FATAL: Gagal setup serial. RVM tidak bisa beroperasi. Pesan: {last_error_message}")
        print(f"CRITICAL ERROR: Gagal setup koneksi serial dengan ESP32. Program berhenti.")
        return # Keluar jika serial gagal total di awal
    
    if not initialize_camera(camera_index):
        logger.critical(f"FATAL: Gagal inisialisasi kamera. RVM tidak bisa beroperasi. Pesan: {last_error_message}")
        print(f"CRITICAL ERROR: {last_error_message}. Program berhenti.")
        if cap and cap.isOpened(): # Pastikan cap dilepas jika sempat terbuka sebagian
            cap.release()
        return # Keluar jika kamera gagal total di awal
    
    # Set state awal ke STARTUP jika belum ERROR dari inisialisasi di atas
    # if current_state != STATE_ERROR:
    #     current_state = STATE_STARTUP
    current_state = STATE_STARTUP # Mulai dengan startup untuk otentikasi RVM dll.
    while True:
        logger.debug(f"Loop Utama - Current State: {current_state}")
        print(f"\n--- Current State: {current_state} ---")
        # Di sini Anda bisa mengirim state saat ini ke ESP32 untuk ditampilkan di LCD
        # send_to_esp32(f"DISPLAY_STATE:{current_state}")

        if current_state == STATE_STARTUP:
            last_error_message = "" 
            logger.info(f"STATE: Memasuki {STATE_STARTUP}")
            print("RVM Startup: Melakukan inisialisasi ulang atau pemeriksaan...")
            last_error_message = "" # Reset pesan error setiap kali masuk startup

            # 1. Cek/Re-init Serial jika perlu (misalnya, jika sebelumnya error)
            if not (ser and ser.isOpen()):
                    logger.warning("STARTUP: Serial atau Kamera tidak siap, mencoba re-init parsial di startup (seharusnya sudah OK).")
                    last_error_message = "STARTUP: Serial atau Kamera tidak siap, mencoba re-init parsial di startup (seharusnya sudah OK)."
                    current_state = STATE_ERROR
                    time.sleep(5) # Beri jeda sebelum loop error berikutnya
                    continue # Lanjut ke iterasi berikutnya untuk menangani STATE_ERROR

            # 2. Cek/Re-init Kamera jika perlu
            if not (cap and cap.isOpened()):
                if not initialize_camera(camera_index):
                    # last_error_message sudah diset
                    current_state = STATE_ERROR
                    time.sleep(5)
                    continue

            # 3. Otentikasi RVM dengan Backend
            if not authenticate_rvm_with_backend():
                # last_error_message sudah diset
                current_state = STATE_ERROR
                time.sleep(5)
                continue
            
            # 4. Ping ESP32
            response = send_to_esp32("PING_FROM_RPI", expected_ack="PONG_TO_RPI")
            if response == "PONG_TO_RPI":
                logger.info("STARTUP: ESP32 terhubung dan merespons PING.")
                print("STARTUP: ESP32 terhubung dan merespons PING.")
                current_state = STATE_IDLE # Semua inisialisasi OK, siap beroperasi
            else:
                last_error_message = "STARTUP: ESP32 tidak merespons PING."
                logger.error(last_error_message)
                current_state = STATE_ERROR
                time.sleep(5)
                # continue tidak perlu, akan ditangani oleh blok STATE_ERROR di iterasi ini atau berikutnya

        elif current_state == STATE_IDLE:
            logger.info(f"STATE: {STATE_IDLE}. Menunggu aksi pengguna.")
            print("RVM Idle: Menunggu interaksi.")
            # send_to_esp32("DISPLAY:IDLE", expected_ack="ACK_DISPLAY")
            action = input("Aksi (ketik 'qr', 'item', atau 'exit'): ").strip().lower()
            if action == "qr":
                logger.info(f"ACTION: Pengguna memilih 'qr'.")
                current_state = STATE_WAITING_FOR_USER_QR
            elif action == "item":
                logger.info(f"ACTION: Pengguna memilih 'item' (deposit tamu).")
                deposit_user_identifier = "guest" 
                current_user_name = "Guest"
                print("Item terdeteksi (mode tamu). Lanjut ke pengambilan gambar.")
                # send_to_esp32("SLOT:OPEN", expected_ack="ACK_SLOT_OPEN")
                current_state = STATE_CAPTURING_IMAGE 
            elif action == "exit":
                logger.info("ACTION: Pengguna memilih 'exit'. Menghentikan aplikasi.")
                break # Keluar dari loop utama
            else:
                logger.warning(f"ACTION: Aksi tidak dikenal '{action}'.")
                print("Aksi tidak dikenal.")

        elif current_state == STATE_WAITING_FOR_USER_QR:
            print("Menunggu pemindaian QR Code pengguna...")
            # send_to_esp32("DISPLAY:SCAN_QR", expected_ack="ACK_DISPLAY")
            # TODO: Implementasi pembacaan QR Code nyata dari kamera (OpenCV & pyzbar)
            scanned_qr_token_global = input("SIMULASI: Masukkan token dari QR Code: ").strip()
            if scanned_qr_token_global:
                current_state = STATE_VALIDATING_USER_TOKEN
            else:
                print("Tidak ada token QR diterima, kembali ke IDLE.")
                current_state = STATE_IDLE
        
        elif current_state == STATE_VALIDATING_USER_TOKEN:
            if not scanned_qr_token_global:
                print("ERROR: Tidak ada token QR untuk divalidasi. Kembali ke IDLE.")
                current_state = STATE_IDLE

            else:
                print(f"API: Memvalidasi user token QR: {scanned_qr_token_global}")
                payload = {'user_token': scanned_qr_token_global}
                response_data = make_api_request('POST', '/rvm/validate-user-token', data=payload)
                if response_data and response_data.get('status') == 'success':
                    api_user_data = response_data.get('data', {})
                    current_user_id = api_user_data.get('user_id')
                    current_user_name = api_user_data.get('user_name')
                    if current_user_id:
                        deposit_user_identifier = str(current_user_id)
                        print(f"API: User token valid. User: {current_user_name} (ID: {current_user_id})")
                        # send_to_esp32(f"DISPLAY:USER_OK:{current_user_name}", expected_ack="ACK_DISPLAY")
                        # send_to_esp32("SLOT:OPEN", expected_ack="ACK_SLOT_OPEN")
                        current_state = STATE_WAITING_FOR_ITEM # Tunggu item setelah user login
                    else:
                        # send_to_esp32("DISPLAY:TOKEN_ERR", expected_ack="ACK_DISPLAY")
                        last_error_message = "API sukses tapi tidak ada user_id dari validasi token."
                        print(f"ERROR: {last_error_message}")
                        current_state = STATE_IDLE 
                else:
                    # send_to_esp32("DISPLAY:TOKEN_ERR", expected_ack="ACK_DISPLAY")
                    last_error_message = response_data.get('message', 'Gagal validasi token QR.') if response_data else "Tidak ada respons API validasi token."
                    print(f"ERROR: {last_error_message}")
                    current_state = STATE_IDLE
                scanned_qr_token_global = None

        elif current_state == STATE_WAITING_FOR_ITEM:
            print(f"User {current_user_name or 'Guest'} terotentikasi/siap. Menunggu item dimasukkan.")
            # send_to_esp32("DISPLAY:INSERT_ITEM", expected_ack="ACK_DISPLAY")
            # TODO: Di sini akan menunggu sinyal dari sensor ESP32 (misal, sensor proksimitas)
            item_inserted_sim = input("SIMULASI: Apakah item sudah dimasukkan? (y/n): ").strip().lower()
            if item_inserted_sim == 'y':
                current_state = STATE_CAPTURING_IMAGE
            else:
                # Pertimbangkan timeout di sini, jika tidak ada item, kembali ke IDLE
                print("Item tidak dimasukkan. Kembali ke IDLE untuk user ini atau timeout.")
                # TODO: Logika timeout atau opsi batal untuk user
                current_state = STATE_IDLE # Atau state khusus 'USER_CANCELLED'
                # Reset user info jika kembali ke IDLE umum
                current_user_id = None
                current_user_name = None
                deposit_user_identifier = None

        elif current_state == STATE_CAPTURING_IMAGE:
            print("Mengambil gambar item...")
            # Cek lagi apakah kamera masih valid sebelum capture, terutama jika ada error sebelumnya
            if not (cap and cap.isOpened()):
                last_error_message = "Kamera tidak siap/terbuka sebelum capture."
                print(f"ERROR: {last_error_message}")
                # Jika user sudah login, mungkin kembali ke waiting for item atau error khusus
                # Jika tamu, kembali ke IDLE
                current_state = STATE_IDLE if not current_user_id else STATE_WAITING_FOR_ITEM
                # Reset user jika kembali ke IDLE dari sini karena gagal kamera
                if not current_user_id:
                    deposit_user_identifier = None
                    current_user_name = None
                continue # Lanjut ke iterasi berikutnya
            # send_to_esp32("SLOT:CLOSE", expected_ack="ACK_SLOT_CLOSED") # Tutup slot jika ada
            # send_to_esp32("LIGHT:ON", expected_ack="ACK_LIGHT_ON") # Nyalakan lampu
            time.sleep(0.5) # Waktu untuk stabilisasi/pencahayaan
            captured_image_path = capture_image_from_camera() # Menggunakan nama file default dengan timestamp
            # send_to_esp32("LIGHT:OFF", expected_ack="ACK_LIGHT_OFF") # Matikan lampu
            if captured_image_path:
                current_state = STATE_PROCESSING_IMAGE_WITH_AI
            else:
                # last_error_message sudah diset oleh capture_image_from_camera()
                print(f"ERROR: {last_error_message} (saat capture)")
                # send_to_esp32("DISPLAY:IMG_ERR", expected_ack="ACK_DISPLAY")
                # send_to_esp32("SLOT:OPEN", expected_ack="ACK_SLOT_OPEN") # Buka slot lagi
                current_state = STATE_IDLE if not current_user_id else STATE_WAITING_FOR_ITEM
                if not current_user_id:
                    deposit_user_identifier = None
                    current_user_name = None

        elif current_state == STATE_PROCESSING_IMAGE_WITH_AI:
            if not captured_image_path:
                print("ERROR: Tidak ada gambar untuk diproses. Kembali ke IDLE.")
                current_state = STATE_IDLE
            else:
                print(f"API: Mengirim gambar {captured_image_path} ke backend untuk analisis...")
                if not deposit_user_identifier:  # Pengaman jika alur tamu terlewat
                    deposit_user_identifier = "guest_processing_fallback" 
                    print("WARNING: deposit_user_identifier tidak diset saat proses, menggunakan fallback.")
                try:
                    with open(captured_image_path, 'rb') as img_file:
                        # Ambil nama file saja dari path untuk payload 'files'
                        img_filename = os.path.basename(captured_image_path)
                        files_payload = {'image': (img_filename, img_file, 'image/jpeg')}
                        data_payload = {'user_identifier': deposit_user_identifier}
                        response_data = make_api_request('POST', '/rvm/deposit', data=data_payload, files=files_payload, requires_rvm_auth=True)
                except FileNotFoundError:
                    last_error_message = f"File gambar tidak ditemukan saat akan dikirim: {captured_image_path}"
                    # print(f"ERROR: {last_error_message}")
                    current_state = STATE_ERROR
                except Exception as e_api_call:
                    last_error_message = f"Error saat persiapan panggilan API deposit: {e_api_call}"
                    # print(f"ERROR: {last_error_message}")
                    current_state = STATE_ERROR
                
                if current_state != STATE_ERROR: # Hanya proses jika tidak ada error file/persiapan
                    if response_data:
                        if response_data.get('status') == 'success':
                            print(f"API: Item diterima! Jenis: {response_data.get('item_type')}, Poin: {response_data.get('points_awarded')}")
                            # send_to_esp32(f"DISPLAY:SUCCESS:{response_data.get('item_type')}", expected_ack="ACK_DISPLAY")
                            current_state = STATE_ITEM_ACCEPTED
                        elif response_data.get('status') == 'rejected':
                            print(f"API: Item ditolak. Alasan: {response_data.get('reason')}")
                            # send_to_esp32(f"DISPLAY:REJECTED:{response_data.get('reason')}", expected_ack="ACK_DISPLAY")
                            current_state = STATE_ITEM_REJECTED
                        else:
                            last_error_message = response_data.get('message', "Respons API tidak dikenal setelah deposit.")
                            # print(f"ERROR: {last_error_message}")
                            current_state = STATE_ERROR
                    else:
                        last_error_message = "Tidak ada respons dari API deposit atau error koneksi."
                        # print(f"ERROR: {last_error_message}")
                        current_state = STATE_ERROR
            
                # Reset setelah proses
                if os.path.exists(captured_image_path or ""): # Hapus gambar setelah dikirim
                    # os.remove(captured_image_path)
                    print(f"DEBUG: Gambar {captured_image_path} akan dihapus (saat ini tidak dihapus).")
                captured_image_path = None 
                deposit_user_identifier = None 
                current_user_id = None 
                current_user_name = None

        elif current_state == STATE_ITEM_ACCEPTED:
            print("Item Diterima. Mengoperasikan mekanisme pemilah...")
            # send_to_esp32("MECHANISM:SORT_VALID", expected_ack="ACK_SORTED")
            time.sleep(2) 
            print("Mekanisme selesai. Kembali ke IDLE.")
            # send_to_esp32("DISPLAY:THANK_YOU", expected_ack="ACK_DISPLAY")
            current_state = STATE_IDLE

        elif current_state == STATE_ITEM_REJECTED:
            print("Item Ditolak. Meminta pengguna mengambil kembali item.")
            # send_to_esp32("MECHANISM:RETURN_ITEM", expected_ack="ACK_ITEM_RETURNED")
            time.sleep(2) 
            print("Proses penolakan selesai. Kembali ke IDLE.")
            current_state = STATE_IDLE
            
        elif current_state == STATE_ERROR:
            print(f"RVM dalam status ERROR: {last_error_message}")
            print("Mencoba restart alur (kembali ke STARTUP) dalam 10 detik...")
            # TODO: Mungkin ada notifikasi ke backend atau tindakan lain di sini
            # send_to_esp32("DISPLAY:SYSTEM_ERROR", expected_ack="ACK_DISPLAY")
            time.sleep(10)
            current_state = STATE_STARTUP 
            # Set untuk iterasi berikutnya memulai dari awal
            # JANGAN langsung 'continue' atau 'pass' di sini, biarkan loop selesai dan 
            # kondisi STATE_STARTUP dievaluasi di awal iterasi berikutnya.  

        # Jika ingin memastikan semua state terdefinisi punya blok elif:
        # elif current_state == STATE_STARTUP:
        #     # State ini seharusnya sudah ditangani di awal loop pada iterasi berikutnya
        #     # setelah diset dari STATE_ERROR atau saat pertama kali.
        #     # Jika sampai sini berarti ada loop aneh, atau ini adalah akhir dari
        #     # pemrosesan state lain dan kita tidak ingin langsung ke time.sleep(0.2)
        #     pass # Biarkan saja, akan diproses di awal loop berikutnya.

        else: # Untuk state yang benar-benar tidak ada di definisi kita
            print(f"FATAL: State TIDAK DIKENAL SAMA SEKALI: {current_state}. Masuk ke mode ERROR.")
            last_error_message = f"Masuk ke state tidak dikenal fatal: {current_state}"
            current_state = STATE_ERROR
            
        time.sleep(0.2) # Kurangi delay loop utama, tapi jangan terlalu cepat

    print("Aplikasi RVM dihentikan.")
    # Cleanup di sini sudah ditangani oleh finally block utama

# --- Main execution ---
if __name__ == "__main__":
    camera_to_use = 0 
    try:
        # Pastikan direktori penyimpanan gambar ada
        if not os.path.exists(IMAGE_SAVE_DIR):
            os.makedirs(IMAGE_SAVE_DIR)
            
        run_rvm(camera_index=camera_to_use)
    except KeyboardInterrupt:
        print("\nProgram dihentikan oleh pengguna (Ctrl+C).")
    except Exception as e_main:
        print(f"\nTerjadi error tidak terduga di level utama: {e_main}")
        import traceback
        traceback.print_exc()
    finally:
        print("Membersihkan sumber daya...")
        if 'ser' in globals() and ser and ser.isOpen():
            ser.close()
            print("SERIAL: Koneksi serial ditutup pada finally block utama.")
        if 'cap' in globals() and cap and cap.isOpened():
            cap.release() # Pastikan cap dilepas
            print("CAMERA: Kamera dilepas pada finally block utama.")
        # cv2.destroyAllWindows() # Hanya jika Anda menampilkan window OpenCV