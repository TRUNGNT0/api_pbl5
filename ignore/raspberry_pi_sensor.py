import time
import threading
import json
import RPi.GPIO as GPIO
import Adafruit_DHT
import smbus
import board
import busio
from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn
import paho.mqtt.client as mqtt
from datetime import datetime

# --- Cấu hình GPIO cho động cơ và servo ---
GPIO.setmode(GPIO.BCM)
MOTOR1_IN1 = 20  # Quạt: IN1 (OUT1/OUT2)
MOTOR1_IN2 = 21  # Quạt: IN2 (LOW)
MOTOR2_IN3 = 26  # Máy bơm: IN3 (OUT3/OUT4)
MOTOR2_IN4 = 19  # Máy bơm: IN4 (LOW)
SERVO_PIN = 22   # Servo: PWM

GPIO.setup(MOTOR1_IN1, GPIO.OUT)
GPIO.setup(MOTOR1_IN2, GPIO.OUT)
GPIO.setup(MOTOR2_IN3, GPIO.OUT)
GPIO.setup(MOTOR2_IN4, GPIO.OUT)
GPIO.setup(SERVO_PIN, GPIO.OUT)

# Đặt IN2 và IN4 luôn LOW
GPIO.output(MOTOR1_IN2, GPIO.LOW)
GPIO.output(MOTOR2_IN4, GPIO.LOW)

# PWM cho servo (50Hz)
servo_pwm = GPIO.PWM(SERVO_PIN, 50)
servo_pwm.start(0)

# Hàm điều khiển động cơ


def control_motor(motor, state):
    pin = MOTOR1_IN1 if motor == 1 else MOTOR2_IN3
    if state == "run":
        GPIO.output(pin, GPIO.HIGH)
        print(
            f"Motor {motor} {'(Quạt)' if motor == 1 else '(Máy bơm)'} đang chạy")
    else:  # stop
        GPIO.output(pin, GPIO.LOW)
        print(
            f"Motor {motor} {'(Quạt)' if motor == 1 else '(Máy bơm)'} đã dừng")

# Hàm điều khiển servo


def set_servo_angle(angle):
    if 0 <= angle <= 150:
        # Ánh xạ góc 0-150 độ sang duty cycle 2.5-12.5%
        duty = 2.5 + (angle / 150) * (12.5 - 2.5)
        servo_pwm.ChangeDutyCycle(duty)
        print(f"Servo set to {angle} degrees")
        time.sleep(0.5)  # Đợi servo di chuyển
        servo_pwm.ChangeDutyCycle(0)  # Tắt PWM để tránh rung
    else:
        print(f"Invalid angle: {angle}. Must be 0-150 degrees")


# --- DHT11 ---
DHT_SENSOR = Adafruit_DHT.DHT11
DHT_PIN = 17  # GPIO17 (pin 11)

# --- BH1750 ---
BH1750_ADDR = 0x23
bus = smbus.SMBus(1)


def read_bh1750():
    try:
        bus.write_byte(BH1750_ADDR, 0x10)
        time.sleep(0.2)
        data = bus.read_i2c_block_data(BH1750_ADDR, 0x10)
        lux = (data[1] + (256 * data[0])) / 1.2
        return lux
    except Exception as e:
        print(f"Error reading BH1750: {e}")
        return 0


# --- ADS1115 - Độ ẩm đất ---
i2c_adc = busio.I2C(board.SCL, board.SDA)
ads = ADS1115(i2c_adc)
soil_channel = AnalogIn(ads, 0)  # Cảm biến nối A0


def read_soil_percent():
    try:
        raw = soil_channel.value
        voltage = soil_channel.voltage
        # Ánh xạ: 0% tại 3.3V, 100% tại 1.5V
        moisture_percent = max(
            0, min(100, int((3.3 - voltage) / (3.3 - 1.5) * 100)))
        return moisture_percent, raw, voltage
    except Exception as e:
        print(f"Error reading ADS1115: {e}")
        return 0, 0, 0


# --- MQTT ---
MQTT_BROKER = "localhost"  # Thay bằng IP nếu broker không trên Pi
MQTT_PORT = 1883

client = mqtt.Client("Pi-Sensor")
try:
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
except Exception as e:
    print(f"Failed to connect to MQTT broker: {e}")
    exit(1)

# Hàm gửi message theo định dạng mới (Sensor Messages)


def publish_sensor_message(sensor_type, device_id, value):
    try:
        message = {
            "type": sensor_type,
            "device_id": device_id,
            "value": value,
            "time": datetime.now().isoformat()
        }
        topic = f"sensor/{device_id}"
        client.publish(topic, json.dumps(message))
        print(f"Published {sensor_type}: {message}")
    except Exception as e:
        print(f"Error publishing sensor data: {e}")

# Hàm gửi message trạng thái thiết bị (Device Status Messages)


def publish_device_status(device_type, device_id, status):
    try:
        message = {
            "type": device_type,
            "device_id": device_id,
            "status": status,
            "time": datetime.now().isoformat()
        }
        topic = f"device/{device_id}"
        client.publish(topic, json.dumps(message))
        print(f"Published device status: {message}")
    except Exception as e:
        print(f"Error publishing device status: {e}")


def on_connect(client, userdata, flags, rc):
    print(f"Connected to MQTT broker with code {rc}")
    client.subscribe("motor/control")
    client.subscribe("servo/control")


def on_message(client, userdata, message):
    try:
        payload = json.loads(message.payload.decode())
        if message.topic == "motor/control":
            motor = payload.get("motor")
            state = payload.get("state")
            if motor in [1, 2] and state in ["run", "stop"]:
                control_motor(motor, state)
                # Gửi thông báo trạng thái thiết bị
                device_type = "Fan" if motor == 1 else "Pump"
                device_id = "fan1" if motor == 1 else "pump1"
                status = "OPEN" if state == "run" else "CLOSED"
                publish_device_status(device_type, device_id, status)
        elif message.topic == "servo/control":
            angle = payload.get("angle")
            if isinstance(angle, (int, float)) and 0 <= angle <= 150:
                set_servo_angle(angle)
                # Gửi thông báo trạng thái servo
                publish_device_status("Cover", "cover1", f"ANGLE_{angle}")
            else:
                print(f"Invalid servo angle: {angle}")
    except Exception as e:
        print(f"Error processing MQTT message: {e}")


client.on_connect = on_connect
client.on_message = on_message
client.loop_start()

# --- Kiểm tra cảm biến định kỳ ---


def sensor_check():
    while True:
        # Đọc DHT11
        humidity, temperature = Adafruit_DHT.read_retry(DHT_SENSOR, DHT_PIN)
        if humidity is not None and temperature is not None:
            # Gửi dữ liệu nhiệt độ theo định dạng mới
            publish_sensor_message(
                "Temperature", "temp1", round(temperature, 1))
            # Gửi dữ liệu độ ẩm theo định dạng mới
            publish_sensor_message("Humidity", "hum1", round(humidity, 1))

            # Kiểm tra độ ẩm cho quạt
            if humidity > 70:
                control_motor(1, "run")  # Bật quạt
                publish_device_status("Fan", "fan1", "OPEN")
                time.sleep(10)           # Chạy 10 giây
                control_motor(1, "stop")
                publish_device_status("Fan", "fan1", "CLOSED")
        else:
            print("DHT11: Read failed")

        # Đọc BH1750
        lux = read_bh1750()
        # Gửi dữ liệu ánh sáng theo định dạng mới
        publish_sensor_message("Light", "light1", round(lux, 1))

        # Đọc độ ẩm đất
        percent, raw, voltage = read_soil_percent()
        # Gửi dữ liệu độ ẩm đất theo định dạng mới
        publish_sensor_message("Soil_Moisture", "soil1", percent)

        # Kiểm tra độ ẩm đất cho máy bơm
        if percent < 60:
            control_motor(2, "run")  # Bật máy bơm
            publish_device_status("Pump", "pump1", "OPEN")
            time.sleep(5)            # Chạy 5 giây
            control_motor(2, "stop")
            publish_device_status("Pump", "pump1", "CLOSED")

        time.sleep(30)  # Kiểm tra mỗi 30 giây


# --- Chạy luồng cảm biến ---
sensor_thread = threading.Thread(target=sensor_check, daemon=True)
sensor_thread.start()

try:
    while True:
        time.sleep(1)  # Giữ chương trình chạy
except KeyboardInterrupt:
    print("Program stopped.")
finally:
    servo_pwm.stop()
    client.loop_stop()
    client.disconnect()
    GPIO.cleanup()
