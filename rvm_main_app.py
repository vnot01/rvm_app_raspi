import time
import serial
import requests # Untuk API call
import json     # Untuk API call
import cv2      # Untuk OpenCV (kamera)
import os       # Untuk membuat direktori jika perlu
from datetime import datetime # Untuk nama file unik
import logging
from logging.handlers import TimedRotatingFileHandler
from pyzbar.pyzbar import decode as pyzbar_decode # Untuk membaca QR Code
import traceback # Untuk logging traceback lengkap

# --- Konfigurasi Aplikasi RVM ---
RVM_ID_NAME = "1" # Dapatnya dari mana?
RVM_NAME = "RVM Kantin Pusat Gedung A" # Dapatnya dari mana?
RVM_API_KEY = "RVM001-TSZ3UvnJZrBotBsWkZtmFMB8PZ7FPP96" # GANTI DENGAN YANG VALID
BACKEND_API_BASE_URL = "https://precious-puma-smoothly.ngrok-free.app/api" # URL NGROK ANDA

SERIAL_PORT = '/dev/serial0' 
BAUD_RATE = 115200
SERIAL_TIMEOUT = 1 # Detik | # Kurangi timeout serial read individu agar lebih responsif
SERIAL_READ_TIMEOUT_TOTAL = 3.0 # Timeout total untuk menunggu ACK dari ESP32

# Header untuk request ke ngrok
NGROK_SKIP_WARNING_HEADER = {'ngrok-skip-browser-warning': 'true'}
IMAGE_SAVE_DIR = "captured_images" # Direktori untuk menyimpan gambar
QR_SCAN_TIMEOUT_SECONDS = 30 # Berapa lama mencoba scan QR sebelum kembali ke IDLE
ITEM_INSERT_TIMEOUT_SECONDS = 60 # Berapa lama menunggu item setelah user login
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
# --- MODIFIKASI FORMATTER DI SINI ---
# Format lama:
# formatter = logging.Formatter(f'%(asctime)s - RVM_ID:{RVM_ID_FROM_CONFIG} - RVM_NAME:{RVM_NAME_FROM_CONFIG} - %(levelname)s - %(message)s')

# Format baru yang Anda inginkan: [DD Month YYYY HH:MM] LEVEL: Message
# Untuk nama bulan, kita bisa menggunakan '%d %b %Y %H:%M' (misal: 10 May 2025 17:58)
# atau '%d %B %Y %H:%M' (misal: 10 May 2025 17:58)
# Kita akan gunakan '%d %b %Y %H:%M' untuk nama bulan singkat (May, Jun, Jul)
# atau jika ingin nama bulan penuh: '%d %B %Y %H:%M'

# Format string untuk formatter:
# %(asctime)s akan digantikan dengan waktu. Kita perlu mengatur format waktu asctime.
# Sayangnya, logging.Formatter tidak secara langsung mengubah format asctime menjadi nama bulan.
# Cara termudah adalah menggunakan format numerik atau membuat custom Formatter.

# Opsi 1: Menggunakan format tanggal numerik yang lebih pendek dengan asctime standar
# formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
# Hasil: [2025-05-10 17:58:00] INFO: Pesan log

# Opsi 2: Format yang paling mendekati permintaan Anda dengan asctime standar (tanpa nama bulan teks)
# formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%d/%m/%Y %H:%M')
# Hasil: [10/05/2025 17:58] INFO: Pesan log

# Opsi 3: Untuk mendapatkan format [10 May 2025 17:58] LEVEL: Pesan,
# kita perlu sedikit trik atau custom formatter. Cara paling mudah adalah dengan
# sedikit memodifikasi apa yang kita log sebagai 'message' jika kita tidak mau membuat custom Formatter.
# Alternatifnya, kita buat custom Formatter:

class CustomFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created)
        if datefmt:
            s = dt.strftime(datefmt)
        else:
            # Format yang Anda inginkan: [10 May 2025 17:58]
            s = dt.strftime("%d %b %Y %H:%M") 
        return s
# Gunakan CustomFormatter
# Formatnya akan menjadi: [WaktuKustom] LEVELNAME: message
formatter = CustomFormatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%d %b %Y %H:%M')
# datefmt di sini akan diteruskan ke metode formatTime di CustomFormatter kita
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)    
# Format log: Timestamp - RVM_ID - RVM_NAME - Level - Pesan
# formatter = logging.Formatter(f'%(asctime)s - %(levelname)s - %(message)s')
# file_handler.setFormatter(formatter)
# logger.addHandler(file_handler)

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
        last_error_message = "Koneksi serial ke ESP32 tidak aktif."
        logger.error(f"SERIAL_SEND_FAIL: [{command}] - {last_error_message}")
        print(f"SERIAL ERROR: {last_error_message}")
        return None
    try:
        if ser.in_waiting > 0:
            bytes_cleared = ser.in_waiting; ser.read(bytes_cleared)
            logger.debug(f"SERIAL: Membersihkan {bytes_cleared} bytes sisa sebelum kirim [{command}].")
            # print(f"SERIAL: Membersihkan {ser.in_waiting} bytes sisa di buffer RPi sebelum kirim [{command}]...")
            # ser.read(ser.in_waiting)

        logger.info(f"SERIAL TX: [{command}]")
        print(f"SERIAL TX: [{command}]")
        ser.write((command + '\n').encode('utf-8'))
        start_time = time.time(); 
        buffer = ""; 
        received_lines = []
        while (time.time() - start_time) < read_timeout:
            if ser.in_waiting > 0:
                byte = ser.read(1)
                if not byte: continue
                char = byte.decode('utf-8', errors='ignore')
                if char == '\n':
                    line = buffer.strip(); buffer = ""
                    if line: logger.debug(f"SERIAL RX (line): [{line}]"); print(f"SERIAL RX: [{line}]"); received_lines.append(line)
                    if expected_ack and line == expected_ack: logger.info(f"SERIAL: ACK '{expected_ack}' diterima untuk [{command}]."); return line
                else: buffer += char
            time.sleep(0.01)
        
        # Jika timeout dan expected_ack belum ditemukan, tapi ada respons lain
        if expected_ack: last_error_message = f"Timeout menunggu ACK '{expected_ack}' untuk [{command}]."; logger.warning(f"SERIAL: {last_error_message} Respons diterima: {received_lines}"); print(f"SERIAL WARN: {last_error_message}")
        elif not received_lines: last_error_message = f"Tidak ada respons untuk [{command}]."; logger.warning(f"SERIAL: {last_error_message}"); print(f"SERIAL WARN: {last_error_message}")
        return received_lines[-1] if not expected_ack and received_lines else None
    except Exception as e_serial_comm:
        last_error_message = f"Error komunikasi serial saat kirim/terima [{command}]: {e_serial_comm}"
    logger.error(f"SERIAL_COMM_ERROR: {last_error_message}", exc_info=True)
    print(f"SERIAL COMM ERROR: {last_error_message}")
    return None

# --- Fungsi Utilitas API Backend ---
def make_api_request(method, endpoint, data=None, files=None, params=None, requires_rvm_auth=False):
    global RVM_API_KEY, last_error_message, BACKEND_API_BASE_URL
    url = f"{BACKEND_API_BASE_URL}{endpoint}"
    headers = NGROK_SKIP_WARNING_HEADER.copy(); headers['Accept'] = 'application/json'
    if requires_rvm_auth: headers['X-RVM-ApiKey'] = RVM_API_KEY
    logger.info(f"API REQ: {method.upper()} {url}")
    print(f"API REQ: {method.upper()} {url}")

    try:
        if method.upper() == 'POST':
            if files: response = requests.post(url, headers=headers, data=data, files=files, params=params, timeout=30)
            else: headers['Content-Type'] = 'application/json'; response = requests.post(url, headers=headers, json=data, params=params, timeout=30)
        elif method.upper() == 'GET': response = requests.get(url, headers=headers, params=params, timeout=30)
        else: last_error_message = f"Metode API {method} tidak didukung."; logger.error(f"API: {last_error_message}"); return None
        logger.info(f"API RESP STATUS: {response.status_code} untuk {url}")
        print(f"API RESP STATUS: {response.status_code}")
        # Log body respons jika ada error untuk debugging
        if not response.ok: # response.ok adalah True untuk status 2xx
             logger.error(f"API ERROR BODY ({url}): {response.text[:500]}"); print(f"API ERROR BODY: {response.text[:500]}") # Tampilkan sebagian body error
             response.raise_for_status() 
        
        if 'application/json' in response.headers.get('Content-Type', ''):
            # print(f"API RESP JSON: {response.json()}") # Hati-hati jika respons besar
            return response.json()
        else:
            # print(f"API RESP TEXT: Non-JSON - {response.text[:200]}")
            last_error_message = "Backend API tidak mengembalikan JSON."; logger.warning(f"API: {last_error_message} dari {url}"); return {'status': 'error', 'message': last_error_message, 'raw_content': response.text[:200]}
        
    except requests.exceptions.HTTPError as http_err: 
        last_error_message = f"HTTP error: {http_err}"; logger.error(f"API HTTP_ERR: {last_error_message} - URL: {url}", exc_info=True); print(f"API ERROR: {last_error_message}")
    
    # Ini menangkap ConnectionError, Timeout, dll.
    except requests.exceptions.RequestException as req_err: 
        last_error_message = f"Request/Connection error: {req_err}"; logger.error(f"API REQ_ERR: {last_error_message} - URL: {url}", exc_info=True); print(f"API ERROR: {last_error_message}")

    except Exception as e_api: 
        last_error_message = f"General API request error: {e_api}"; logger.error(f"API GENERAL_ERR: {last_error_message} - URL: {url}", exc_info=True); print(f"API ERROR: {last_error_message}")
    return None

def authenticate_rvm_with_backend():
    global current_state, last_error_message
    logger.info("API: Mencoba otentikasi RVM dengan backend...")
    print("API: Mencoba otentikasi RVM dengan backend...")
    payload = {'api_key': RVM_API_KEY}
    response_data = make_api_request('POST', '/rvm/authenticate', data=payload)
    if response_data and response_data.get('status') == 'success':
        rvm_id_api = response_data.get('rvm_id', 'N/A')
        logger.info(f"API: RVM (Config ID: {RVM_ID_NAME}, API ID: {rvm_id_api}) berhasil terotentikasi.")
        print(f"API: RVM '{RVM_NAME}' berhasil terotentikasi.")
        return True
    else:
        detail = response_data.get('message', 'Detail tidak tersedia') if response_data else 'Tidak ada respons dari server'
        last_error_message = f"Gagal otentikasi RVM: {detail}"
        logger.error(f"API AUTH_FAIL: {last_error_message}. Detail API: {response_data if response_data else 'No response'}")
        print(f"API ERROR: {last_error_message}")
        # last_error_message = f"Gagal otentikasi RVM: {response_data.get('message', 'Tidak ada pesan error spesifik') if response_data else 'Tidak ada respons API'}"
        return False

# --- Fungsi Kamera ---
def initialize_camera(camera_index=0):
    global cap, last_error_message
    logger.info(f"CAMERA: Mencoba menginisialisasi kamera pada @ indeks {camera_index}...")
    print(f"CAMERA: Mencoba menginisialisasi kamera pada @ indeks {camera_index}...")
    cap = cv2.VideoCapture(camera_index)
    time.sleep(1) # Beri waktu kamera untuk inisialisasi
    if not cap.isOpened():
        last_error_message = f"Kamera @ indeks {camera_index} tidak bisa dibuka."
        logger.error(f"CAMERA_INIT_FAIL: {last_error_message}")
        print(f"CAMERA ERROR: {last_error_message} / Tidak bisa membuka kamera pada @ indeks {camera_index}")
        return False
    logger.info(f"CAMERA: Kamera pada @ indeks {camera_index} berhasil dibuka.")
    print(f"CAMERA: Kamera pada @ indeks {camera_index} berhasil dibuka.")
    return True

def capture_image_from_camera(filename_base="item_capture"):
    global cap, last_error_message, IMAGE_SAVE_DIR
    if not (cap and cap.isOpened()):
        last_error_message = "Kamera tidak tersedia atau tidak terbuka untuk capture."
        logger.warning(f"CAMERA_CAPTURE: {last_error_message}")
        print(f"CAMERA ERROR: {last_error_message} / Kamera tidak tersedia atau tidak terbuka untuk capture.")
        return None
    
    logger.info("CAMERA: Mengambil frame...")
    print("CAMERA: Mengambil frame...")
    ret, frame = cap.read()
    if not ret or frame is None:
        last_error_message = "Gagal membaca frame dari kamera."
        logger.error(f"CAMERA_CAPTURE_FAIL: {last_error_message}")
        print(f"CAMERA ERROR: {last_error_message}")
        return None
    
    try:
        # Buat direktori jika belum ada
        if not os.path.exists(IMAGE_SAVE_DIR):
            os.makedirs(IMAGE_SAVE_DIR)
            logger.info(f"CAMERA: Direktori '{IMAGE_SAVE_DIR}' dibuat.")
            print(f"CAMERA: Direktori '{IMAGE_SAVE_DIR}' dibuat.")

        # Buat nama file unik dengan timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f") # Tambah microsecond untuk keunikan
        filename = f"{filename_base}_{timestamp}.jpg"
        save_path = os.path.join(IMAGE_SAVE_DIR, filename)
        cv2.imwrite(save_path, frame)
        logger.info(f"CAMERA: Gambar disimpan ke {save_path}")
        print(f"CAMERA: Gambar disimpan ke {save_path}")
        return save_path
    except Exception as e:
        last_error_message = f"Gagal menyimpan gambar: {e}"
        logger.error(f"CAMERA_SAVE_FAIL: {last_error_message}", exc_info=True)
        print(f"CAMERA ERROR: {last_error_message}")
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
        logger.critical(f"FATAL_SETUP: Gagal setup serial. RVM berhenti. Pesan: {last_error_message}")
        print(f"CRITICAL ERROR SETUP: Gagal setup koneksi serial dengan ESP32. Program berhenti.")
        return # Keluar jika serial gagal total di awal
    
    if not initialize_camera(camera_index):
        logger.critical(f"FATAL_SETUP: Gagal inisialisasi kamera. RVM berhenti. Pesan: {last_error_message}")
        print(f"CRITICAL ERROR Initialize Camera: {last_error_message}. Program berhenti.")
        # Pastikan cap dilepas jika sempat terbuka sebagian
        if 'ser' in globals() and ser and ser.isOpen(): 
            ser.close() 
        return # Keluar jika kamera gagal total di awal
    # Set state awal ke STARTUP jika belum ERROR dari inisialisasi di atas
    # if current_state != STATE_ERROR:
    #     current_state = STATE_STARTUP
    # Mulai dengan startup untuk otentikasi RVM dll.
    current_state = STATE_STARTUP

    while True:
        logger.info(f"STATE_TRANSITION: Memasuki state '{current_state}'")
        print(f"\n--- Loop Utama Memasuki State: {current_state} ---")

        # Di sini Anda bisa mengirim state saat ini ke ESP32 untuk ditampilkan di LCD
        # send_to_esp32(f"DISPLAY_STATE:{current_state}")

        if current_state == STATE_STARTUP:
            # Reset pesan error setiap kali masuk startup
            last_error_message = "" 
            logger.info(f"STATE: Memasuki {STATE_STARTUP}")
            print("RVM Startup: Melakukan inisialisasi ulang atau pemeriksaan...")

            # # 1. Cek/Re-init Serial jika perlu (misalnya, jika sebelumnya error)
            # if not (ser and ser.isOpen()):
            #         logger.warning("STARTUP: Serial atau Kamera tidak siap, mencoba re-init parsial di startup (seharusnya sudah OK).")
            #         last_error_message = "STARTUP: Serial atau Kamera tidak siap, mencoba re-init parsial di startup (seharusnya sudah OK)."
            #         current_state = STATE_ERROR
            #         time.sleep(5) # Beri jeda sebelum loop error berikutnya
            #         continue # Lanjut ke iterasi berikutnya untuk menangani STATE_ERROR

            # # 2. Cek/Re-init Kamera jika perlu
            # if not (cap and cap.isOpened()):
            #     if not initialize_camera(camera_index):
            #         # last_error_message sudah diset
            #         current_state = STATE_ERROR
            #         time.sleep(5)
            #         continue

            # 3. Otentikasi RVM dengan Backend
            if not authenticate_rvm_with_backend():
                # last_error_message sudah diset
                current_state = STATE_ERROR
                time.sleep(5)
                continue
            # 4. Ping ESP32
            response = send_to_esp32("PING_RPI", expected_ack="PONG_ESP32")

            if response == "PONG_ESP32":
                logger.info(f"STARTUP: ESP32 PING OK.")
                send_to_esp32("INDICATE_STATUS_IDLE", expected_ack="ACK_STATUS_INDICATED")
                # Semua inisialisasi OK, siap beroperasi
                current_state = STATE_IDLE
            else:
                # continue tidak perlu, akan ditangani oleh blok STATE_ERROR di iterasi ini atau berikutnya
                last_error_message = "STARTUP: ESP32 tidak merespons PING."; logger.error(f"ERROR PING_PONG_ESP32: {last_error_message}")
                current_state = STATE_ERROR; 
                time.sleep(10)

        elif current_state == STATE_IDLE:
            # Reset info user dari sesi sebelumnya
            current_user_id = None; current_user_name = None; deposit_user_identifier = None; scanned_qr_token_global = None
            
            logger.info(f"IDLE: {STATE_IDLE} Menunggu aksi. Info user direset.")
            print(f"RVM {STATE_IDLE}: Menunggu interaksi.")
            # send_to_esp32("DISPLAY:IDLE", expected_ack="ACK_DISPLAY")
            send_to_esp32("INDICATE_STATUS_IDLE", expected_ack="ACK_STATUS_INDICATED")
            action = input("Aksi (ketik 'qr' untuk scan, 'item' untuk deposit sebagai tamu (tanpa login), 'exit'): ").strip().lower()
            if action == "qr":
                logger.info(f"IDLE: Aksi '{action}' dipilih.")
                current_state = STATE_WAITING_FOR_USER_QR
            elif action == "item":
                logger.info(f"IDLE: Aksi '{action}' (deposit tamu) dipilih.")
                deposit_user_identifier = "guest" 
                current_user_name = "Guest"
                print("Mode Tamu. Membuka slot...")
                # send_to_esp32("SLOT:OPEN", expected_ack="ACK_SLOT_OPEN")
                if send_to_esp32("SLOT_OPEN", expected_ack="ACK_SLOT_OPEN"):
                    # Tunggu item setelah slot terbuka
                    current_state = STATE_WAITING_FOR_ITEM 
                else:
                    last_error_message = "IDLE: ESP32 gagal buka slot untuk tamu."; 
                    logger.error(f"ERROR SLOT_OPEN_ESP32: {last_error_message}")
                    current_state = STATE_ERROR
                # current_state = STATE_CAPTURING_IMAGE 
            elif action == "exit":
                logger.info(f"IDLE: Aksi '{action}' dipilih. Menghentikan aplikasi.")
                print(f"IDLE: Aksi '{action}' dipilih. Menghentikan aplikasi.")
                break # Keluar dari loop utama
            else:
                logger.warning(f"ACTION: Aksi tidak dikenal '{action}'.")
                print("Aksi tidak dikenal.")

        elif current_state == STATE_WAITING_FOR_USER_QR:
            logger.info(f"STATE: {STATE_WAITING_FOR_USER_QR}")
            print("Menunggu pemindaian QR Code pengguna...")
            # send_to_esp32("DISPLAY:SCAN_QR", expected_ack="ACK_DISPLAY")
            send_to_esp32("INDICATE_STATUS_PROCESSING", expected_ack="ACK_STATUS_INDICATED")
            
            # --- Implementasi Pembacaan QR Code Nyata ---
            qr_data = None
            qr_scan_start_time = time.time()
            print("CAMERA: Arahkan QR Code ke kamera...")
            while (time.time() - qr_scan_start_time) < QR_SCAN_TIMEOUT_SECONDS:
                if not (cap and cap.isOpened()):
                    last_error_message = "Kamera tidak tersedia saat scan QR."; logger.error(last_error_message)
                    current_state = STATE_ERROR; break 
                ret, frame = cap.read()
                if not ret or frame is None:
                    logger.warning("QR_SCAN: Gagal ambil frame saat scan QR.")
                    time.sleep(0.1); continue
                
                # (Opsional) Tampilkan frame di window jika RPi punya desktop & monitor
                # cv2.imshow("QR Scanner", frame)
                # if cv2.waitKey(1) & 0xFF == ord('q'): break # Keluar jika 'q' ditekan

                decoded_objects = pyzbar_decode(frame)
                if decoded_objects:
                    qr_data = decoded_objects[0].data.decode("utf-8").strip()
                    logger.info(f"QR_SCAN: QR Code terdeteksi! Data: [{qr_data}]")
                    print(f"QR Code terdeteksi: {qr_data}")
                    break # Keluar dari loop scan
                time.sleep(0.1) # Jeda antar frame
            # cv2.destroyAllWindows() # Tutup window jika ada

            if qr_data:
                scanned_qr_token_global = qr_data
                current_state = STATE_VALIDATING_USER_TOKEN
            else:
                logger.info(f"QR_SCAN: Timeout atau tidak ada QR Code terdeteksi setelah {QR_SCAN_TIMEOUT_SECONDS} detik.")
                print("Tidak ada QR Code terdeteksi. Kembali ke IDLE.")
                send_to_esp32("INDICATE_STATUS_IDLE", expected_ack="ACK_STATUS_INDICATED")
                current_state = STATE_IDLE

            # # --- SIMULASI Pembacaan QR Code Nyata ---
            # scanned_qr_token_global = input("SIMULASI: Masukkan token dari QR Code: ").strip()
            # if scanned_qr_token_global:
            #     current_state = STATE_VALIDATING_USER_TOKEN
            # else:
            #     print("Tidak ada token QR diterima, kembali ke IDLE.")
            #     current_state = STATE_IDLE
        
        elif current_state == STATE_VALIDATING_USER_TOKEN:
            if not scanned_qr_token_global: 
                logger.error("VALIDATE_TOKEN: Masuk state tanpa token."); current_state = STATE_IDLE; 
                continue
            logger.info(f"VALIDATE_TOKEN: Memvalidasi token QR: {scanned_qr_token_global}")
            print(f"API: Memvalidasi user token QR: {scanned_qr_token_global}")
            payload = {'user_token': scanned_qr_token_global}
            response_data = make_api_request('POST', '/rvm/validate-user-token', data=payload)
            current_user_id = None; 
            current_user_name = None; 
            deposit_user_identifier = None
            if response_data and response_data.get('status') == 'success':
                # current_user_id = None; 
                # current_user_name = None; 
                # deposit_user_identifier = None
                # ... (set current_user_id, dll.)
                current_user_id = response_data.get('data', {}).get('user_id')
                current_user_name = response_data.get('data', {}).get('user_name')
                if current_user_id:
                    deposit_user_identifier = str(current_user_id)
                    logger.info(f"API: User token valid. User: {current_user_name} (ID: {current_user_id})")
                    print(f"Halo, {current_user_name}! Silakan masukkan item Anda.")
                    send_to_esp32("SLOT_OPEN", expected_ack="ACK_SLOT_OPEN")
                    current_state = STATE_WAITING_FOR_ITEM 
                else:
                    last_error_message = "API sukses validasi token tapi tidak ada user_id."; logger.error(f"VALIDATE_TOKEN: {last_error_message}")
                    print(f"Halo, {current_user_name}! Silakan masukkan item Anda.")
                    send_to_esp32("INDICATE_STATUS_ERROR", expected_ack="ACK_STATUS_INDICATED"); current_state = STATE_IDLE 
                    
            else:
                last_error_message = response_data.get('message', 'Gagal validasi token QR.') if response_data else "Tidak ada respons API validasi token."
                logger.error(f"VALIDATE_TOKEN: {last_error_message}")
                print(f"ERROR VALIDATE_TOKEN: {last_error_message}")
                send_to_esp32("INDICATE_STATUS_ERROR", expected_ack="ACK_STATUS_INDICATED"); 
                current_state = STATE_IDLE
            scanned_qr_token_global = None

        elif current_state == STATE_WAITING_FOR_ITEM:
            print(f"User {current_user_name or 'Guest'} siap. Menunggu item dimasukkan (Timeout: {ITEM_INSERT_TIMEOUT_SECONDS}s)...")
            logger.info(f"WAIT_ITEM: Menunggu item dari user: {current_user_name or 'Guest'}")
            # send_to_esp32("DISPLAY:INSERT_ITEM", expected_ack="ACK_DISPLAY")
            # TODO: Di sini akan menunggu sinyal dari sensor ESP32 (misal, sensor proksimitas)
            item_inserted = False
            wait_item_start_time = time.time()
            while (time.time() - wait_item_start_time) < ITEM_INSERT_TIMEOUT_SECONDS:
                # Di sini bisa cek input non-blocking dari ESP32 (SENSOR:ITEM_DETECTED)
                # Untuk simulasi, kita bisa cek input keyboard non-blocking atau langsung timeout
                # Untuk input keyboard, kita bisa pakai 'select' atau threading, tapi untuk sederhana:
                # Jika Anda ingin simulasi input di sini, perlu cara non-blocking atau modifikasi alur.
                # Kita anggap saja setelah timeout, jika tidak ada item, kita batal.
                # Untuk sekarang, kita langsung ke simulasi input 'y'/'n' setelah pesan.
                # Ini akan membuat RVM menunggu input manual di konsol.
                # Jika ingin otomatis timeout, hapus input() di bawah dan biarkan loop berjalan.
                sim_input = input(f"SIMULASI (Menunggu item... sisa {int(ITEM_INSERT_TIMEOUT_SECONDS - (time.time() - wait_item_start_time))}s): Item masuk? (y/n/batal): ").strip().lower()
                if sim_input == 'y': item_inserted = True; break
                if sim_input == 'batal': logger.info("WAIT_ITEM: User membatalkan."); break
                time.sleep(0.2) # Cek lagi
            
            if item_inserted:
                logger.info("WAIT_ITEM: Item terdeteksi (simulasi).")
                print(f"WAIT_ITEM: Item terdeteksi {item_inserted} (simulasi)")
                current_state = STATE_CAPTURING_IMAGE
            else: # Timeout atau batal
                print(f"WAIT_ITEM: Timeout atau dibatalkan. Kembali ke IDLE.")
                logger.info(f"WAIT_ITEM: Timeout atau dibatalkan. Kembali ke IDLE.")
                send_to_esp32("SLOT_CLOSE", expected_ack="ACK_SLOT_CLOSED") 
                current_state = STATE_IDLE 
                current_user_id = None; current_user_name = None; deposit_user_identifier = None

        elif current_state == STATE_CAPTURING_IMAGE:
            logger.info(f"CAPTURE_IMAGE: Memulai pengambilan gambar. User: {current_user_name or 'Guest'}")
            print("Mengambil gambar item...")
            # Nyalakan lampu
            send_to_esp32("INTERNAL_LIGHT_ON", expected_ack="ACK_LIGHT_ON") 
            # Waktu untuk stabilisasi/pencahayaan
            time.sleep(1) # DELAY persiapan menyalakan lampu 
            captured_image_path = capture_image_from_camera() 
            # Matikan lampu
            send_to_esp32("INTERNAL_LIGHT_OFF", expected_ack="ACK_LIGHT_OFF")
            if captured_image_path:
                current_state = STATE_PROCESSING_IMAGE_WITH_AI
            else:
                print(f"ERROR CAPTURE_IMAGE: {last_error_message} (saat capture)")
                logger.error(f"CAPTURE_IMAGE: Gagal capture - {last_error_message}")
                send_to_esp32("INDICATE_STATUS_ERROR", expected_ack="ACK_STATUS_INDICATED")
                if current_user_id: # User sedang dalam sesi
                    logger.info("CAPTURE_IMAGE: Gagal capture, user masih login, kembali ke WAITING_FOR_ITEM.")
                    current_state = STATE_WAITING_FOR_ITEM # Beri kesempatan user coba lagi
                else: # Tamu
                    logger.info("CAPTURE_IMAGE: Gagal capture (tamu), kembali ke IDLE.")
                    current_state = STATE_IDLE
                # deposit_user_identifier tidak perlu direset di sini karena belum dipakai

        elif current_state == STATE_PROCESSING_IMAGE_WITH_AI:
            if not captured_image_path:
                last_error_message = "STATE {STATE_PROCESSING_IMAGE_WITH_AI}"; 
                logger.critical(f"FATAL_PROCESSING:Tidak ada gambar untuk diproses. Pesan: {last_error_message}.Kembali ke IDLE.")
                print("CRITICAL: Tidak ada gambar untuk diproses. Kembali ke IDLE.")
                current_state = STATE_IDLE
            else:
                # last_error_message = "STATE {STATE_PROCESSING_IMAGE_WITH_AI}"; 
                logger.info(f"API: Mengirim gambar {captured_image_path} ke backend untuk analisis...")
                print(f"API: Mengirim gambar {captured_image_path} ke backend untuk analisis...")
                if not deposit_user_identifier:  # Pengaman jika alur tamu terlewat
                    # last_error_message = "STATE {STATE_PROCESSING_IMAGE_WITH_AI}"; 
                    deposit_user_identifier = "guest_processing_fallback" 
                    print("WARNING: deposit_user_identifier tidak diset saat proses, menggunakan fallback.")
                    logger.warning(f"WARNING: deposit_user_identifier = {deposit_user_identifier} / tidak diset saat proses, menggunakan fallback")
                try:
                    with open(captured_image_path, 'rb') as img_file:
                        # Ambil nama file saja dari path untuk payload 'files'
                        img_filename = os.path.basename(captured_image_path)
                        files_payload = {'image': (img_filename, img_file, 'image/jpeg')}
                        data_payload = {'user_identifier': deposit_user_identifier}
                        response_data = make_api_request('POST', '/rvm/deposit', data=data_payload, files=files_payload, requires_rvm_auth=True)
                except FileNotFoundError:
                    last_error_message = f"File gambar tidak ditemukan saat akan dikirim: {captured_image_path}"
                    # last_error_message = "STATE {STATE_PROCESSING_IMAGE_WITH_AI}"; 
                    logger.error(f"ERROR: {last_error_message}")
                    print(f"ERROR: {last_error_message}")
                    current_state = STATE_ERROR
                except Exception as e_api_call:
                    last_error_message = f"Error saat persiapan panggilan API deposit: {e_api_call}"
                    # last_error_message = "STATE {STATE_PROCESSING_IMAGE_WITH_AI}"; 
                    logger.error(f"ERROR: {last_error_message}")
                    print(f"ERROR: {last_error_message}")
                    current_state = STATE_ERROR
                
                if current_state != STATE_ERROR: 
                    # Hanya proses jika tidak ada error file/persiapan
                    last_error_message = "STATE {STATE_ERROR}: Hanya proses jika tidak ada error file/persiapan"; 
                    logger.info(f"INFO: {last_error_message}")
                    if response_data:
                        if response_data.get('status') == 'success':
                            last_error_message = f"Item diterima! Jenis: {response_data.get('item_type')}, Poin: {response_data.get('points_awarded')}"; 
                            logger.info(f"API: {last_error_message}")
                            print(f"API: Item diterima! Jenis: {response_data.get('item_type')}, Poin: {response_data.get('points_awarded')}")
                            send_to_esp32(f"DISPLAY:SUCCESS:{response_data.get('item_type')}", expected_ack="ACK_DISPLAY")
                            current_state = STATE_ITEM_ACCEPTED
                        elif response_data.get('status') == 'rejected':
                            last_error_message = f"Item ditolak. Alasan: {response_data.get('reason')}"; 
                            logger.info(f"API: {last_error_message}")
                            print(f"API: Item ditolak. Alasan: {response_data.get('reason')}")
                            send_to_esp32(f"DISPLAY:REJECTED:{response_data.get('reason')}", expected_ack="ACK_DISPLAY")
                            current_state = STATE_ITEM_REJECTED
                        else:
                            last_error_message = response_data.get('message', "Respons API tidak dikenal setelah deposit.")
                            logger.error(f"API ERROR: {last_error_message}")
                            print(f"ERROR API: {last_error_message}")
                            current_state = STATE_ERROR
                    else:
                        last_error_message = "Tidak ada respons dari API deposit atau error koneksi."
                        logger.error(f"ERROR: {last_error_message}")
                        print(f"ERROR: {last_error_message}")
                        current_state = STATE_ERROR
            
                # Reset setelah proses
                if os.path.exists(captured_image_path or ""): 
                    # Hapus gambar setelah dikirim
                    # os.remove(captured_image_path)
                    print(f"DEBUG: Gambar {captured_image_path} akan dihapus (saat ini tidak dihapus).")
                captured_image_path = None 
                deposit_user_identifier = None 
                current_user_id = None 
                current_user_name = None

        elif current_state == STATE_ITEM_ACCEPTED:
            # current_user_name mungkin sudah None
            logger.info(f"ITEM_ACCEPTED: Item diterima. User: {current_user_name or 'Guest'}") 
            print(f"Item User: {current_user_name or 'Guest'} Diterima. Mengoperasikan mekanisme pemilah...")
            if not send_to_esp32("SORT_VALID_ITEM", expected_ack="ACK_SORTED"):
                logger.warning("ESP32 tidak konfirmasi SORT_VALID_ITEM, tapi tetap lanjut.")
            time.sleep(2) 
            print("Mekanisme selesai. Kembali ke IDLE.")
            send_to_esp32("INDICATE_STATUS_IDLE", expected_ack="ACK_STATUS_INDICATED")
            current_state = STATE_IDLE
            # send_to_esp32("DISPLAY:THANK_YOU", expected_ack="ACK_DISPLAY")

        elif current_state == STATE_ITEM_REJECTED:
            logger.info(f"ITEM_REJECTED: Item ditolak. User: {current_user_name or 'Guest'}")
            print(f"Item Ditolak. Meminta {current_user_name or 'Guest'} mengambil kembali item.")
            if not send_to_esp32("RETURN_REJECTED_ITEM", expected_ack="ACK_ITEM_RETURNED"): 
                logger.warning("ESP32 tidak konfirmasi RETURN_REJECTED_ITEM, tapi tetap lanjut.")
            time.sleep(2) 
            print("Proses penolakan selesai. Kembali ke IDLE.")
            send_to_esp32("INDICATE_STATUS_IDLE", expected_ack="ACK_STATUS_INDICATED")
            current_state = STATE_IDLE
            
        elif current_state == STATE_ERROR:
            logger.error(f"ERROR_STATE: Pesan: {last_error_message}")
            print(f"RVM dalam status ERROR: {last_error_message}")
            send_to_esp32("INDICATE_STATUS_ERROR", expected_ack="ACK_STATUS_INDICATED")
            print("Mencoba restart alur (kembali ke STARTUP) dalam 10 detik...")
            time.sleep(10)
            current_state = STATE_STARTUP 

        else:
            logger.critical(f"UNKNOWN_STATE: State '{current_state}' tidak dikenal. Masuk ke mode ERROR.")
            print(f"FATAL: State TIDAK DIKENAL: {current_state}. Masuk ke mode ERROR.")
            last_error_message = f"Masuk ke state tidak dikenal fatal: {current_state}"
            current_state = STATE_ERROR

        time.sleep(0.2) # Kurangi delay loop utama, tapi jangan terlalu cepat
    logger.info("================ RVM BLACKBOX SESSION END ================")
    print("Aplikasi RVM dihentikan.")

# --- Main execution ---
if __name__ == "__main__":
    camera_to_use = 0 
    try:
        # Pastikan semua direktori penyimpanan ada
        if not os.path.exists(LOG_DIR): 
            os.makedirs(LOG_DIR)
        if not os.path.exists(IMAGE_SAVE_DIR):
            os.makedirs(IMAGE_SAVE_DIR)
        run_rvm(camera_index=camera_to_use)
    except KeyboardInterrupt:
        logger.info("Program dihentikan oleh pengguna (Ctrl+C).")
        print("\nProgram dihentikan oleh pengguna (Ctrl+C).")
    except Exception as e_main:
        logger.critical(f"Terjadi error tidak terduga di level utama: {e_main}", exc_info=True)
        print(f"\nTerjadi error tidak terduga di level utama: {e_main}")
        traceback.print_exc()
    finally:
        logger.info("Membersihkan sumber daya akhir...")
        print("Membersihkan sumber daya...")
        if 'ser' in globals() and ser and ser.isOpen():
            ser.close(); logger.info("SERIAL: Koneksi ditutup (finally)."); print("SERIAL: Koneksi ditutup (finally).")
        if 'cap' in globals() and cap and cap.isOpened():
            cap.release(); logger.info("CAMERA: Kamera dilepas (finally)."); print("CAMERA: Kamera dilepas (finally).")
        # cv2.destroyAllWindows() # Hanya jika Anda menampilkan window OpenCV