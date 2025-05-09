import serial
import time

# Sesuaikan port serial dengan konfigurasi RPi Anda
# Biasanya /dev/ttyS0 atau /dev/serial0 untuk primary UART hardware
# Atau /dev/ttyAMA0 tergantung konfigurasi dan model RPi
SERIAL_PORT = '/dev/serial0' 
BAUD_RATE = 115200

try:
    # Inisialisasi koneksi serial
    # Tambahkan timeout agar read() tidak block selamanya
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) 
    print(f"Berhasil terhubung ke port serial {SERIAL_PORT} dengan baud rate {BAUD_RATE}")
except serial.SerialException as e:
    print(f"Error: Tidak bisa membuka port serial {SERIAL_PORT}: {e}")
    exit()

def send_command_to_esp32(command):
    """Mengirim perintah ke ESP32 dan menunggu respons."""
    if ser.isOpen():
        print(f"RPi Mengirim: {command}")
        ser.write((command + '\n').encode('utf-8')) # Kirim perintah dengan newline
        time.sleep(0.1) # Beri sedikit waktu untuk ESP32 memproses

        # Coba baca beberapa baris respons (ESP32 mungkin mengirim beberapa Serial.println)
        responses = []
        max_lines = 5 # Baca maksimal 5 baris atau sampai timeout
        lines_read = 0
        while lines_read < max_lines:
            if ser.in_waiting > 0:
                response_line = ser.readline().decode('utf-8').strip()
                if response_line: # Hanya proses jika ada data
                    print(f"RPi Menerima: {response_line}")
                    responses.append(response_line)
                    lines_read += 1
                else: # Jika readline mengembalikan string kosong (bisa terjadi pada timeout)
                    break 
            else:
                # Jika tidak ada data lagi setelah beberapa saat, keluar dari loop baca
                # Ini untuk menangani jika ESP32 hanya mengirim satu baris atau tidak merespons
                time.sleep(0.05) # Tunggu sebentar lagi
                if ser.in_waiting == 0: # Cek lagi
                    break
        return responses
    else:
        print("Error: Koneksi serial tidak terbuka.")
        return []

if __name__ == "__main__":
    try:
        # Uji PING-PONG
        print("\n--- Tes PING-PONG ---")
        responses = send_command_to_esp32("PING_FROM_RPI")
        if "PONG_TO_RPI" in responses:
            print("Tes PING-PONG BERHASIL!")
        else:
            print("Tes PING-PONG GAGAL atau tidak ada respons PONG.")

        # Uji Perintah LED (Simulasi)
        print("\n--- Tes Perintah LED ---")
        send_command_to_esp32("LED_ON_SIM_RPI")
        time.sleep(1) # Jeda
        send_command_to_esp32("LED_OFF_SIM_RPI")
        time.sleep(0.5)
        send_command_to_esp32("UNKNOWN_COMMAND_TEST")


    except KeyboardInterrupt:
        print("\nProgram dihentikan oleh pengguna.")
    finally:
        if ser.isOpen():
            ser.close()
            print("\nKoneksi serial ditutup.")