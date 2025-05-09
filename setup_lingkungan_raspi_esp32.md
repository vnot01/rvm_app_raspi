# Dokumentasi Progres Pengembangan Sistem RVM (Hingga Komunikasi RPi-ESP32)

Dokumen ini mencatat progres pengembangan sistem RVM, dengan fokus pada Fase 3: Pengembangan Aplikasi RVM (Perangkat Lunak di Mesin Fisik), khususnya setup lingkungan Raspberry Pi 4B sebagai pengganti sementara Jetson Orin Nano, dan implementasi komunikasi serial awal antara Raspberry Pi (RPi) dan ESP32 (menggunakan ESP-IDF).

## Revisi Arsitektur Sementara (Fase 3)

*   **Unit Pemrosesan Utama RVM:** Raspberry Pi 4B (menggantikan Jetson Orin Nano untuk pengembangan awal).
*   **Kontroler Hardware Level Rendah:** ESP32 WROVER Dev (menggunakan PlatformIO dengan framework ESP-IDF).
*   **Komunikasi RPi <-> ESP32:** Serial UART.

## Status Progres Saat Ini: 60%

**Target yang Telah Selesai:**

*   **Fase 1: Pondasi Backend Inti & Desain Database (0% - 25%)** - *SELESAI*
*   **Fase 2: Pengembangan API Backend Inti (Termasuk Layanan CV Terpusat) (25% - 55%)** - *SELESAI*
    *   Termasuk implementasi `GeminiVisionService`, endpoint API RVM (`/deposit`, `/authenticate`, `/validate-user-token`), endpoint API User (`/auth/*`, `/user/*`), dan endpoint dasar Admin (`/admin/stats`, `/admin/vision-test`).
*   **Fase 3 (Bagian Awal): Setup Lingkungan RPi & Komunikasi Awal RPi <-> ESP32 (55% - 60%)** - *SELESAI*
    *   Setup Raspberry Pi 4B (OS, Python, virtual environment, library `pyserial`).
    *   Setup proyek ESP32 di PlatformIO dengan framework ESP-IDF.
    *   Implementasi komunikasi serial dua arah ("Ping-Pong") antara RPi dan ESP32 menggunakan UART0 ESP32 (GPIO1 TX, GPIO3 RX) dan serial port utama RPi (`/dev/serial0`).
    *   Implementasi kontrol LED Built-in ESP32 (GPIO2) melalui perintah serial dari RPi.
    *   Berhasil mengatasi masalah sinkronisasi dan pembacaan buffer serial di sisi RPi yang disebabkan oleh tercampurnya log `ESP_LOGI` dengan data respons aktual dari ESP32.

## Detail Implementasi Komunikasi RPi <-> ESP32

### 1. Koneksi Fisik

*   **RPi GND** <-> **ESP32 GND**
*   **RPi TXD (GPIO14)** <-> **ESP32 RXD (GPIO3 / U0RXD)**
*   **RPi RXD (GPIO15)** <-> **ESP32 TXD (GPIO1 / U0TXD)**
*   Level logika 3.3V untuk kedua perangkat, koneksi langsung aman.

### 2. Konfigurasi Raspberry Pi

*   Sistem Operasi: Raspberry Pi OS.
*   Bahasa: Python 3.
*   Virtual Environment: Dibuat dan diaktifkan.
*   Library Utama: `pyserial`.
*   Konfigurasi Serial Port (`sudo raspi-config`):
    *   Login shell over serial: **No**
    *   Serial port hardware: **Yes**
*   Konfigurasi `/boot/config.txt` (atau `/boot/firmware/config.txt`):
    *   `enable_uart=1`
    *   `dtoverlay=disable-bt` (untuk memastikan `/dev/serial0` mengarah ke UART PL011 yang lebih stabil di GPIO14/15).
*   Skrip Python (`rpi_serial_master.py`): Bertindak sebagai master yang mengirim perintah dan membaca respons. Mengimplementasikan logika untuk membersihkan buffer dan memfilter respons yang diharapkan dari log ESP32.

### 3. Konfigurasi ESP32 (ESP-IDF via PlatformIO)

*   Board: ESP32 WROVER Dev Module (atau yang kompatibel).
*   Framework: `espidf`.
*   UART untuk Komunikasi: `UART_NUM_0` (pin default GPIO1 TX, GPIO3 RX).
    *   **Catatan:** `ESP_LOGI` dan fungsi logging standar ESP-IDF juga menggunakan `UART_NUM_0` secara default. Ini berarti log debugging ESP32 dikirim melalui jalur serial yang sama dengan data komunikasi ke RPi.
*   Skrip C (`src/main.c`):
    *   Menginisialisasi UART0 untuk menerima perintah dari RPi dan mengirim respons.
    *   Mengimplementasikan task FreeRTOS untuk menangani event UART secara non-blocking.
    *   Mengontrol LED Built-in (GPIO2) berdasarkan perintah.
    *   Mengirim pesan acknowledgment (ACK) atau respons spesifik kembali ke RPi.

### 4. Penjelasan Istilah Perintah dan Respons Serial

Dalam skrip komunikasi "Ping-Pong" dan kontrol LED, kita menggunakan beberapa string perintah dan respons sederhana yang dikirim melalui serial. Semua perintah dan respons diakhiri dengan karakter newline (`\n`) untuk memudahkan parsing `readline()` di Python atau pembacaan buffer di C.

*   **Perintah dari RPi ke ESP32:**
    *   `PING_FROM_RPI`:
        *   **Guna:** Perintah dasar untuk menguji konektivitas dua arah. RPi mengirim ini untuk memastikan ESP32 hidup dan merespons.
    *   `LED_ON`:
        *   **Guna:** Perintah untuk meminta ESP32 menyalakan LED Built-in (atau LED eksternal yang terhubung ke pin yang ditentukan di masa depan).
    *   `LED_OFF`:
        *   **Guna:** Perintah untuk meminta ESP32 mematikan LED Built-in.
    *   `TEST_UNKNOWN_COMMAND` (atau string acak lainnya):
        *   **Guna:** Perintah yang sengaja dibuat tidak dikenal oleh ESP32 untuk menguji bagaimana ESP32 menangani input yang tidak valid.

*   **Respons dari ESP32 ke RPi:**
    *   `PONG_TO_RPI\n`:
        *   **Guna:** Respons dari ESP32 setelah menerima perintah `PING_FROM_RPI`. Mengkonfirmasi bahwa ESP32 menerima ping dan mengirim "pong" kembali.
    *   `ACK_LED_ON\n`:
        *   **Guna:** **ACKnowledgment** (Pemberitahuan) bahwa ESP32 telah menerima dan berhasil memproses perintah `LED_ON`. "ACK" adalah singkatan umum dalam protokol komunikasi yang berarti pesan telah diterima dan dipahami.
    *   `ACK_LED_OFF\n`:
        *   **Guna:** **ACKnowledgment** bahwa ESP32 telah menerima dan berhasil memproses perintah `LED_OFF`.
    *   `UNKNOWN_CMD\n`:
        *   **Guna:** Respons dari ESP32 jika menerima perintah yang tidak ada dalam daftar perintah yang dikenalinya (misalnya, setelah menerima `TEST_UNKNOWN_COMMAND`).

*   **Istilah Lainnya:**
    *   **UART (Universal Asynchronous Receiver/Transmitter):** Protokol komunikasi serial standar yang digunakan antara RPi dan ESP32.
    *   **TXD (Transmit Data):** Pin yang digunakan untuk mengirim data. TXD RPi terhubung ke RXD ESP32.
    *   **RXD (Receive Data):** Pin yang digunakan untuk menerima data. RXD RPi terhubung ke TXD ESP32.
    *   **Baud Rate:** Kecepatan transfer data serial (dalam bit per detik). Kedua perangkat harus menggunakan baud rate yang sama (dalam kasus kita, `115200`).
    *   **ESP-IDF (Espressif IoT Development Framework):** Framework pengembangan resmi dari Espressif untuk mikrokontroler ESP32, memberikan kontrol level rendah dan akses ke fitur RTOS (FreeRTOS).
    *   **PlatformIO:** Ekosistem pengembangan open-source untuk IoT, mendukung banyak board dan framework, termasuk ESP32 dengan ESP-IDF.
    *   **`ESP_LOGI(TAG, ...)`:** Fungsi logging standar di ESP-IDF untuk mencetak informasi (Info level) ke konsol serial (defaultnya UART0). `TAG` adalah string untuk mengidentifikasi sumber log.
    *   **Buffer Serial:** Area memori sementara tempat data serial yang masuk disimpan sebelum diproses. Penting untuk membersihkan (flush) buffer atau membaca dengan benar agar tidak ada data lama yang tercampur.

## Tantangan yang Diatasi

*   **Kegagalan Loopback Test Awal di RPi:** Diatasi dengan memastikan konfigurasi `raspi-config` benar dan mungkin memerlukan beberapa kali percobaan atau `sudo` awal untuk port serial RPi agar berfungsi stabil.
*   **Sinkronisasi Komunikasi RPi-ESP32:** Awalnya, RPi membaca log `ESP_LOGI` dari ESP32 sebagai data valid, menyebabkan kebingungan. Diatasi dengan:
    *   Memperbaiki logika pembacaan di skrip Python (`rpi_serial_master.py`) agar lebih tangguh dalam memfilter dan mencari respons spesifik yang diharapkan (`PONG_TO_RPI`, `ACK_LED_ON`, dll.) di antara semua output serial dari ESP32.
    *   Membersihkan buffer serial di RPi sebelum mengirim perintah baru.

## Rekomendasi Jangka Panjang (Jika Masalah Sinkronisasi Muncul Lagi)

*   **Pisahkan UART Komunikasi dari UART Logging di ESP32:**
    *   Gunakan `UART_NUM_1` atau `UART_NUM_2` di ESP32 khusus untuk komunikasi data dengan RPi (memerlukan pemilihan dan konfigurasi pin GPIO yang berbeda).
    *   Biarkan `ESP_LOGI` dan logging standar menggunakan `UART_NUM_0` untuk debugging ke PC via USB.
    *   Ini akan memberikan jalur komunikasi yang bersih dan mencegah log debugging tercampur dengan data penting.

---