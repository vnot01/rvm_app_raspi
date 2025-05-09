# loopback_test.py
import serial
import time
SERIAL_PORT = '/dev/serial0' # atau /dev/ttyS0
BAUD_RATE = 115200
try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
    print(f"Port {SERIAL_PORT} terbuka untuk loopback test.")
    test_string = "RPi Loopback Test!\n"
    ser.write(test_string.encode('utf-8'))
    print(f"Mengirim: {test_string.strip()}")
    time.sleep(0.1)
    received_data = ser.read(len(test_string) + 5) # Baca sedikit lebih banyak
    if received_data:
        print(f"Menerima: {received_data.decode('utf-8').strip()}")
        if test_string.strip() in received_data.decode('utf-8'):
            print("LOOPBACK TEST BERHASIL!")
        else:
            print("LOOPBACK TEST GAGAL: Data tidak cocok.")
    else:
        print("LOOPBACK TEST GAGAL: Tidak ada data diterima.")
    ser.close()
except Exception as e:
    print(f"Error: {e}")