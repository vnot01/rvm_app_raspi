import serial
import time

SERIAL_PORT = '/dev/serial0' 
BAUD_RATE = 115200
ser = None 

try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1) # Timeout baca lebih pendek per read
    print(f"Berhasil terhubung ke port serial {SERIAL_PORT} dengan baud rate {BAUD_RATE}")
    print("Menunggu ESP32 siap (2 detik)...")
    time.sleep(2) 
    if ser.in_waiting > 0:
        print(f"Membersihkan {ser.in_waiting} bytes dari buffer input RPi...")
        ser.read(ser.in_waiting)
    print("Buffer serial input RPi dibersihkan.")

except serial.SerialException as e:
    print(f"Error: Tidak bisa membuka port serial {SERIAL_PORT}: {e}")
    exit()
except Exception as e_general:
    print(f"Terjadi error tak terduga saat inisialisasi serial: {e_general}")
    exit()


def send_command_and_get_response(command_to_send, expected_response=None, timeout_seconds=2.5): # Naikkan timeout sedikit
    """Mengirim perintah, membersihkan buffer, dan membaca respons yang diharapkan, mengabaikan log ESP32."""
    if not (ser and ser.isOpen()):
        print("Error: Koneksi serial tidak terbuka atau belum diinisialisasi.")
        return None

    if ser.in_waiting > 0:
        print(f"Membersihkan {ser.in_waiting} bytes sisa di buffer RPi sebelum kirim...")
        ser.read(ser.in_waiting)

    print(f"RPi Mengirim: [{command_to_send}]")
    ser.write((command_to_send + '\n').encode('utf-8'))
    
    start_time = time.time()
    received_lines = [] # Kumpulkan semua baris yang diterima
    
    while (time.time() - start_time) < timeout_seconds:
        if ser.in_waiting > 0:
            try:
                # Baca semua yang ada di buffer, lalu split per baris
                bytes_to_read = ser.in_waiting
                raw_data = ser.read(bytes_to_read)
                buffer_str = raw_data.decode('utf-8', errors='ignore')
                
                # Proses setiap baris yang mungkin ada dalam buffer_str
                current_lines = buffer_str.splitlines() # splitlines() akan menghapus \n dan \r
                for line in current_lines:
                    line = line.strip() # Hapus spasi ekstra
                    if line: # Hanya proses jika baris tidak kosong
                        print(f"RPi Menerima Mentah: [{line}]")
                        received_lines.append(line)
                        # Cek apakah baris ini adalah respons yang diharapkan (bukan log ESP32)
                        # Log ESP32 biasanya dimulai dengan "I (timestamp) TAG:"
                        # Respons kita (PONG, ACK) tidak memiliki format itu.
                        if expected_response and line == expected_response:
                            print(f"RESPONS DIHARAPKAN DITEMUKAN: [{line}]")
                            return line 
            except Exception as e_read:
                print(f"Error saat membaca serial: {e_read}")
                return None 
        time.sleep(0.05) # Cek berkala

    # Jika loop selesai tanpa menemukan expected_response
    print(f"RPi: Timeout atau respons '{expected_response}' tidak ditemukan. Semua baris diterima:")
    for r_line in received_lines:
        print(f"  - [{r_line}]")
    return None

if __name__ == "__main__":
    try:
        print("\n--- Tes PING-PONG ---")
        response = send_command_and_get_response("PING_FROM_RPI", expected_response="PONG_TO_RPI")
        if response == "PONG_TO_RPI":
            print("Tes PING-PONG BERHASIL!")
        else:
            print(f"Tes PING-PONG GAGAL.")

        print("\n--- Tes Perintah LED ---")
        print("Menyalakan LED...")
        response = send_command_and_get_response("LED_ON", expected_response="ACK_LED_ON")
        if response == "ACK_LED_ON":
            print("LED ON terkonfirmasi.")
            # Periksa LED fisik di ESP32 Anda, seharusnya menyala
        else:
            print(f"Konfirmasi LED ON gagal.")
        
        print("Tunggu 2 detik (LED harusnya menyala)...")
        time.sleep(2)

        print("Mematikan LED...")
        response = send_command_and_get_response("LED_OFF", expected_response="ACK_LED_OFF")
        if response == "ACK_LED_OFF":
            print("LED OFF terkonfirmasi.")
            # Periksa LED fisik di ESP32 Anda, seharusnya mati
        else:
            print(f"Konfirmasi LED OFF gagal.")

        time.sleep(0.5)
        print("\nMengirim perintah tidak dikenal...")
        response = send_command_and_get_response("TEST_UNKNOWN_COMMAND", expected_response="UNKNOWN_CMD")
        if response == "UNKNOWN_CMD":
            print("Respons perintah tidak dikenal diterima.")
        else:
            print(f"Tes perintah tidak dikenal gagal.")

    except KeyboardInterrupt:
        print("\nProgram dihentikan oleh pengguna.")
    except Exception as e_main:
        print(f"Terjadi error pada program utama: {e_main}")
    finally:
        if ser and ser.isOpen():
            ser.close()
            print("\nKoneksi serial ditutup.")