MANTAP! Ini progres yang sangat signifikan!

Mari kita analisis outputnya:

**Hasil Loopback Test di Raspberry Pi:**
```bash
(.venv) raspi1@raspi1:~/rvm_app $ sudo python3 loopback_test.py
Port /dev/serial0 terbuka untuk loopback test.
Mengirim: RPi Loopback Test!
LOOPBACK TEST GAGAL: Tidak ada data diterima.
(.venv) raspi1@raspi1:~/rvm_app $ sudo python3 loopback_test.py
Port /dev/serial0 terbuka untuk loopback test.
Mengirim: RPi Loopback Test!
Menerima: RPi Loopback Test!
LOOPBACK TEST BERHASIL!
```
*   Percobaan pertama gagal, percobaan kedua **BERHASIL!** Ini sangat penting. Kegagalan pertama mungkin karena ada sisa state atau port belum sepenuhnya siap setelah reboot/konfigurasi. Keberhasilan kedua menunjukkan bahwa port serial `/dev/serial0` di Raspberry Pi Anda **berfungsi dengan baik** untuk mengirim dan menerima data ke dirinya sendiri. Ini mengeliminasi masalah hardware atau konfigurasi dasar di sisi RPi.

**Hasil Eksekusi `rpi_serial_master.py` (Interaksi dengan ESP32):**

Log dari RPi:
```bash
--- Tes PING-PONG ---
RPi Mengirim: [PING_FROM_RPI]
RPi Menerima: [I (55544) ESP32_RVM_LED_COMM: Diterima dari RPi: [PING_FROM_RPI]
RPi Menerima: [] (len: 14)]  <-- Ini adalah newline dari perintah asli
RPi Menerima: [I (55544) ESP32_RVM_LED_COMM: Perintah setelah diproses: [PING_FROM_RPI]]
RPi Menerima: [PONG_TO_RPI]
Tes PING-PONG BERHASIL!

--- Tes Perintah LED ---
Menyalakan LED...
RPi Mengirim: [LED_ON]
RPi Menerima: [I (55554) ESP32_RVM_LED_COMM: Mengirim ke RPi: PONG_TO_RPI] <--- MASALAH 1: Respons tidak sesuai
Konfirmasi LED ON gagal.
Tunggu 2 detik (LED harusnya menyala)...
Mematikan LED...
RPi Mengirim: [LED_OFF]
RPi Menerima: [I (55764) ESP32_RVM_LED_COMM: Diterima dari RPi: [LED_ON] <--- MASALAH 2: Menerima log perintah sebelumnya
RPi Menerima: [] (len: 7)]
RPi Menerima: [I (55764) ESP32_RVM_LED_COMM: Perintah setelah diproses: [LED_ON]]
RPi Menerima: [I (55764) ESP32_RVM_LED_COMM: LED Menyala (diperintahkan RPi)]
RPi Menerima: [ACK_LED_ON] <--- MASALAH 3: Seharusnya ACK_LED_OFF
Konfirmasi LED OFF gagal.
... (dst untuk UNKNOWN_COMMAND)
```

Log dari Serial Monitor ESP32:
```bash
I (55544) ESP32_RVM_LED_COMM: Diterima dari RPi: [PING_FROM_RPI
] (len: 14)
I (55544) ESP32_RVM_LED_COMM: Perintah setelah diproses: [PING_FROM_RPI]
PONG_TO_RPI  <-- ESP32 mengirim PONG_TO_RPI (kemudian ada newline implisit dari println/printf)
I (55554) ESP32_RVM_LED_COMM: Mengirim ke RPi: PONG_TO_RPI  <-- Ini adalah log internal ESP32

I (55764) ESP32_RVM_LED_COMM: Diterima dari RPi: [LED_ON
] (len: 7)
I (55764) ESP32_RVM_LED_COMM: Perintah setelah diproses: [LED_ON]
I (55764) ESP32_RVM_LED_COMM: LED Menyala (diperintahkan RPi)
ACK_LED_ON <-- ESP32 mengirim ACK_LED_ON

I (57974) ESP32_RVM_LED_COMM: Diterima dari RPi: [LED_OFF
] (len: 8)
I (57974) ESP32_RVM_LED_COMM: Perintah setelah diproses: [LED_OFF]
I (57974) ESP32_RVM_LED_COMM: LED Mati (diperintahkan RPi)
ACK_LED_OFF <-- ESP32 mengirim ACK_LED_OFF
```

**Analisis Masalah Komunikasi RPi <-> ESP32:**

1.  **PING-PONG BERHASIL!** Ini menunjukkan koneksi dasar dua arah bekerja. RPi mengirim "PING_FROM_RPI", ESP32 menerimanya, memprosesnya, dan mengirim kembali "PONG_TO_RPI" yang diterima oleh RPi.
2.  **MASALAH SINKRONISASI atau BUFFERING pada Perintah Berikutnya (LED_ON, LED_OFF):**
    *   **Masalah 1:** Saat RPi mengirim `LED_ON`, ia menerima log dari ESP32 yang menyatakan bahwa ESP32 *mengirim* `PONG_TO_RPI`. Ini adalah sisa dari perintah sebelumnya atau log internal ESP32 yang ikut terkirim/terbaca.
    *   **Masalah 2 & 3:** Saat RPi mengirim `LED_OFF`, ia malah menerima log pemrosesan `LED_ON` dari ESP32 dan kemudian `ACK_LED_ON`. Ini jelas menunjukkan ada ketidaksesuaian timing atau data yang tertinggal di buffer serial. RPi membaca respons yang seharusnya untuk perintah `LED_ON` ketika ia mengharapkan respons untuk `LED_OFF`.

**Penyebab Kemungkinan Masalah Sinkronisasi/Buffering:**

*   **RPi Membaca Terlalu Cepat atau Terlalu Banyak:** Skrip Python mungkin membaca semua yang ada di buffer serial RPi, termasuk log internal ESP32 yang juga dikirim melalui UART0 (karena kita menggunakan UART0 untuk komunikasi *dan* ESP_LOGI).
*   **ESP_LOGI Menggunakan UART yang Sama:** `ESP_LOGI` di ESP32 secara default akan mencetak ke UART0. Jika komunikasi juga menggunakan UART0, maka log ini akan tercampur dengan data respons yang sebenarnya ingin kita kirim.
*   **Timing `time.sleep()` di Python:** Penundaan mungkin tidak cukup atau ditempatkan kurang tepat, menyebabkan RPi membaca sebelum ESP32 selesai mengirim respons yang relevan.
*   **RPi `readline()` Menangkap Log ESP32:** Karena `ESP_LOGI` juga mengirim newline, `readline()` di Python akan menangkap baris log ESP32 sebagai baris data yang valid.

**Solusi yang Disarankan:**

**Opsi A: Memisahkan UART Komunikasi dari UART Logging di ESP32 (Paling Bersih)**
   Ini akan menjadi solusi paling robust jangka panjang.
   1.  **ESP32:** Konfigurasi ESP-IDF untuk menggunakan UART lain (misalnya, UART1 dengan pin GPIO10 TX, GPIO9 RX seperti yang kita diskusikan sebelumnya) **KHUSUS** untuk komunikasi data dengan RPi.
   2.  **ESP32:** Biarkan `ESP_LOGI` tetap menggunakan UART0 (default) untuk debugging melalui Serial Monitor PlatformIO (terhubung ke PC via USB).
   3.  **Kabel Fisik:** RPi akan terhubung ke pin UART1 ESP32, bukan UART0.
   4.  Ini akan memastikan data komunikasi tidak tercampur dengan log.

**Opsi B: Memfilter Respons di Sisi Python (Workaround jika tetap ingin pakai UART0 untuk semua)**
   Jika Anda *harus* menggunakan UART0 untuk komunikasi dan logging di ESP32:
   1.  **ESP32:** Pastikan format respons Anda (seperti "PONG_TO_RPI\n", "ACK_LED_ON\n") **unik** dan mudah dibedakan dari format log `ESP_LOGI`.
   2.  **Python:** Setelah `ser.readline()`, periksa apakah baris yang diterima adalah format log ESP32 (misalnya, dimulai dengan "I (timestamp) TAG:") atau format respons yang Anda harapkan. Abaikan baris log.
   3.  Ini lebih rumit dan kurang ideal.

**Mari kita coba perbaiki dengan asumsi kita masih menggunakan UART0 untuk sementara, dan fokus pada pembersihan buffer dan timing yang lebih baik di Python.**

**Penyesuaian Kode `rpi_serial_master.py` (Mencoba Mengatasi Masalah Sinkronisasi):**

```python
import serial
import time

SERIAL_PORT = '/dev/serial0' 
BAUD_RATE = 115200
ser = None 

try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.5) # Timeout baca sedikit lebih lama
    print(f"Berhasil terhubung ke port serial {SERIAL_PORT} dengan baud rate {BAUD_RATE}")
    print("Menunggu ESP32 siap (2 detik)...")
    time.sleep(2) 
    # Membersihkan buffer serial SETELAH sleep, untuk menangkap output startup ESP32
    if ser.in_waiting > 0:
        print(f"Membersihkan {ser.in_waiting} bytes dari buffer input RPi...")
        ser.read(ser.in_waiting) # Baca dan buang semua yang ada di buffer
    print("Buffer serial input RPi dibersihkan.")

except serial.SerialException as e:
    print(f"Error: Tidak bisa membuka port serial {SERIAL_PORT}: {e}")
    exit()
except Exception as e_general:
    print(f"Terjadi error tak terduga saat inisialisasi serial: {e_general}")
    exit()


def send_command_and_get_response(command_to_send, expected_ack_prefix=None, timeout_seconds=2.0):
    """Mengirim perintah, membersihkan buffer, dan membaca respons yang diharapkan."""
    if not (ser and ser.isOpen()):
        print("Error: Koneksi serial tidak terbuka atau belum diinisialisasi.")
        return None

    # 1. Bersihkan buffer input RPi sebelum mengirim (untuk sisa data sebelumnya)
    if ser.in_waiting > 0:
        print(f"Membersihkan {ser.in_waiting} bytes sisa di buffer RPi sebelum kirim...")
        ser.read(ser.in_waiting)

    print(f"RPi Mengirim: [{command_to_send}]")
    ser.write((command_to_send + '\n').encode('utf-8'))
    
    # 2. Tunggu respons spesifik atau timeout
    start_time = time.time()
    buffer = ""
    while (time.time() - start_time) < timeout_seconds:
        if ser.in_waiting > 0:
            try:
                byte = ser.read(1)
                if not byte: # Timeout pada read byte
                    continue
                char = byte.decode('utf-8', errors='ignore')
                if char == '\n': # Akhir baris
                    line = buffer.strip()
                    buffer = "" # Reset buffer untuk baris berikutnya
                    print(f"RPi Menerima Baris: [{line}]")
                    if expected_ack_prefix and line.startswith(expected_ack_prefix):
                        return line # Respons yang diharapkan ditemukan
                    elif not expected_ack_prefix and line: # Jika tidak ada ack spesifik, kembalikan baris pertama non-kosong
                        return line
                else:
                    buffer += char
            except Exception as e_read:
                print(f"Error saat membaca serial: {e_read}")
                return None # Error saat membaca
        time.sleep(0.01) # Cek berkala kecil

    print(f"RPi: Timeout menunggu respons yang diharapkan untuk [{command_to_send}]. Buffer terakhir: [{buffer.strip()}]")
    return None # Timeout atau tidak ada respons yang diharapkan

if __name__ == "__main__":
    try:
        print("\n--- Tes PING-PONG ---")
        response = send_command_and_get_response("PING_FROM_RPI", expected_ack_prefix="PONG_TO_RPI")
        if response == "PONG_TO_RPI":
            print("Tes PING-PONG BERHASIL!")
        else:
            print(f"Tes PING-PONG GAGAL. Respons diterima: {response}")

        print("\n--- Tes Perintah LED ---")
        print("Menyalakan LED...")
        response = send_command_and_get_response("LED_ON", expected_ack_prefix="ACK_LED_ON")
        if response == "ACK_LED_ON":
            print("LED ON terkonfirmasi.")
        else:
            print(f"Konfirmasi LED ON gagal. Respons diterima: {response}")
        
        print("Tunggu 2 detik (LED harusnya menyala)...")
        time.sleep(2)

        print("Mematikan LED...")
        response = send_command_and_get_response("LED_OFF", expected_ack_prefix="ACK_LED_OFF")
        if response == "ACK_LED_OFF":
            print("LED OFF terkonfirmasi.")
        else:
            print(f"Konfirmasi LED OFF gagal. Respons diterima: {response}")

        time.sleep(0.5)
        print("\nMengirim perintah tidak dikenal...")
        response = send_command_and_get_response("TEST_UNKNOWN_COMMAND", expected_ack_prefix="UNKNOWN_CMD")
        if response == "UNKNOWN_CMD":
            print("Respons perintah tidak dikenal diterima.")
        else:
            print(f"Tes perintah tidak dikenal gagal. Respons diterima: {response}")

    except KeyboardInterrupt:
        print("\nProgram dihentikan oleh pengguna.")
    except Exception as e_main:
        print(f"Terjadi error pada program utama: {e_main}")
    finally:
        if ser and ser.isOpen():
            ser.close()
            print("\nKoneksi serial ditutup.")

```

**Perubahan Kunci pada `rpi_serial_master.py` (Revisi untuk Sinkronisasi):**
1.  **Pembersihan Buffer Awal Lebih Baik:** Setelah `time.sleep(2)` saat inisialisasi, buffer RPi dibersihkan.
2.  **Fungsi `send_command_and_get_response` Baru:**
    *   Membersihkan buffer input RPi *sebelum* setiap perintah dikirim.
    *   Membaca karakter per karakter untuk membangun baris, mencari newline (`\n`) sebagai delimiter akhir baris.
    *   Memiliki parameter `expected_ack_prefix` untuk hanya mengembalikan baris jika dimulai dengan prefix yang diharapkan (misalnya, "PONG_TO_RPI", "ACK_LED_ON"). Jika tidak ada prefix yang diharapkan, ia akan mengembalikan baris valid pertama yang diterima.
    *   Timeout baca yang lebih terkontrol.

**Langkah Selanjutnya:**

1.  Gunakan kode `rpi_serial_master.py` yang sudah direvisi di atas di Raspberry Pi Anda.
2.  Pastikan ESP32 Anda sudah di-flash dengan kode `main.c` yang sudah kita revisi (yang mengontrol LED).
3.  **TUTUP** Serial Monitor PlatformIO.
4.  Jalankan skrip Python di RPi.

Amati outputnya. Dengan pembersihan buffer dan pembacaan yang lebih hati-hati, kita berharap RPi hanya akan memproses respons yang sebenarnya ditujukan untuknya, bukan log internal ESP32. Perhatikan juga apakah LED di ESP32 merespons dengan benar.