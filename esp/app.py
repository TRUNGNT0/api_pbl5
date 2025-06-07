from flask import Flask, render_template, jsonify, send_from_directory, request
from flask_cors import CORS
import paho.mqtt.client as mqtt
import sqlite3
import os
import requests
from datetime import datetime
import time
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import requests.exceptions

app = Flask(__name__)
CORS(app)

# Create directory for storing images
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ESP32 Webcam server URL
# Sử dụng URL với tham số chất lượng cao hơn (nếu ESP32-CAM hỗ trợ)
ESP32_WEBCAM_URL = "http://192.168.141.171/capture?quality=10&resolution=UXGA"
# UXGA = 1600x1200, chất lượng: giá trị thấp hơn = chất lượng cao hơn (10-63)

# AI API URL
AI_API_URL = "http://127.0.0.1:8000/predict"

# Khởi tạo SQLite


def init_db():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    
    # Create tables with proper schema
    c.executescript('''
        DROP TABLE IF EXISTS sensor_data;
        DROP TABLE IF EXISTS leaf_images;
        
        CREATE TABLE sensor_data (
            timestamp TEXT,
            temperature REAL,
            humidity REAL,
            light REAL,
            moisture INTEGER
        );
        
        CREATE TABLE leaf_images (
            timestamp TEXT,
            image TEXT,
            analysis TEXT
        );
    ''')
    
    conn.commit()
    conn.close()


def process_image_with_ai(image_path):
    try:
        if not os.path.exists(image_path):
            print(f"Error: File {image_path} không tồn tại")
            return None
        
        if not image_path.lower().endswith(('.jpg', '.jpeg', '.png')):
            print("Error: File phải là ảnh (jpg, jpeg, hoặc png)")
            return None
            
        session = create_session_with_retries()
        with open(image_path, "rb") as f:
            files = {"file": (os.path.basename(image_path), f, "image/jpeg")}
            response = session.post(AI_API_URL, files=files, timeout=30)
        
        if response.status_code == 200:
            return response.json()
        else:
            error_detail = response.json().get("detail", "Không có chi tiết lỗi")
            print(f"Error from AI API: Server trả về mã lỗi {response.status_code}")
            print(f"Chi tiết lỗi: {error_detail}")
            return None
            
    except requests.exceptions.Timeout:
        print("Error: API xử lý ảnh timeout")
        return None
    except requests.exceptions.ConnectionError:
        print("Error: Không thể kết nối đến API xử lý ảnh")
        return None
    except Exception as e:
        print(f"Error processing image with AI: {str(e)}")
        return None


# Create a session with retry logic
def create_session_with_retries():
    session = requests.Session()
    retries = Retry(
        total=3,  # number of retries
        backoff_factor=0.5,  # wait 0.5, 1, 2... seconds between retries
        status_forcelist=[408, 409, 429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


def save_image_from_esp32():
    try:
        session = create_session_with_retries()
        # Try to capture image from ESP32 with timeout
        response = session.get(ESP32_WEBCAM_URL, timeout=(5, 10))  # (connect timeout, read timeout)
        if response.status_code == 200:
            # Generate unique filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_filename = f"leaf_{timestamp}.jpg"
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], image_filename)

            # Save the image
            with open(image_path, 'wb') as f:
                f.write(response.content)

            # Process with AI
            analysis_results = process_image_with_ai(image_path)

            # Save to database
            conn = sqlite3.connect("database.db")
            c = conn.cursor()
            c.execute(
                "INSERT INTO leaf_images (timestamp, image, analysis) VALUES (datetime('now'), ?, ?)",
                (image_filename, str(analysis_results))
            )
            conn.commit()
            conn.close()

            return image_filename, analysis_results
        else:
            print(f"Failed to capture image. Status code: {response.status_code}")
            return None, None

    except requests.exceptions.Timeout:
        print("Connection to ESP32 camera timed out. Please check if the camera is accessible.")
        return None, None
    except requests.exceptions.ConnectionError:
        print("Failed to connect to ESP32 camera. Please check if the camera is on the correct IP and network.")
        return None, None
    except Exception as e:
        print(f"Error capturing image: {str(e)}")
        return None, None


# Cấu hình MQTT
latest_data = {"temperature": 0, "humidity": 0, "light": 0, "moisture": 0}
client = mqtt.Client()


def on_connect(client, userdata, flags, rc):
    print("Connected to MQTT with code", rc)
    client.subscribe("sensor/dht11")
    client.subscribe("sensor/bh1750")
    client.subscribe("sensor/mh_soil")
    client.subscribe("image/leaf")


def on_message(client, userdata, msg):
    global latest_data
    if msg.topic == "sensor/dht11":
        data = msg.payload.decode()
        try:
            temp = float(data.split("temp:")[1].split("C")[0])
            hum = float(data.split("humidity:")[1].split("%")[0])
            latest_data["temperature"] = temp
            latest_data["humidity"] = hum
            print(
                f"Received DHT11 data: Temperature={temp}°C, Humidity={hum}%")
        except Exception as e:
            print(f"Error parsing DHT11 data: {data}, Error: {e}")
    elif msg.topic == "sensor/bh1750":
        data = msg.payload.decode()
        try:
            # Handle both formats: "light:100lux" and "light:100,lux"
            if "," in data:
                light = float(data.split("light:")[1].split(",")[0])
            else:
                light = float(data.split("light:")[1].split("lux")[0])
            latest_data["light"] = light
            print(f"Received light data: {light} lux")
        except Exception as e:
            print(f"Error parsing BH1750 data: {data}, Error: {e}")
    elif msg.topic == "sensor/mh_soil":
        data = msg.payload.decode()
        try:
            moisture = int(data.split("moisture:")[1])
            latest_data["moisture"] = moisture
            print(f"Received soil moisture data: {moisture}")
        except Exception as e:
            print(f"Error parsing soil moisture data: {data}, Error: {e}")
    elif msg.topic == "image/leaf":
        image = msg.payload.decode()
        conn = sqlite3.connect("database.db")
        c = conn.cursor()
        c.execute(
            "INSERT INTO leaf_images (timestamp, image) VALUES (datetime('now'), ?)", (image,))
        conn.commit()
        conn.close()

    # Lưu tất cả dữ liệu vào SQLite
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("INSERT INTO sensor_data (timestamp, temperature, humidity, light, moisture) VALUES (datetime('now'), ?, ?, ?, ?)",
              (latest_data["temperature"], latest_data["humidity"], latest_data["light"], latest_data["moisture"]))
    conn.commit()
    conn.close()


client.on_connect = on_connect
client.on_message = on_message

mqtt_enabled = False
try:
    # Thay đổi địa chỉ IP này thành IP mới của Raspberry Pi
    RASPBERRY_PI_IP = "192.168.141.250"  # Cập nhật IP này sau khi kiểm tra
    client.connect(RASPBERRY_PI_IP, 1883, 60)
    client.loop_start()
    mqtt_enabled = True
    print(f"Connected to MQTT broker at {RASPBERRY_PI_IP}")
except Exception as e:
    print(f"Failed to connect to MQTT broker: {e}")
    print("MQTT functionality is disabled")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def get_data():
    return latest_data


@app.route("/api/debug")
def get_debug():
    # Return information useful for debugging
    debug_info = {
        "mqtt_enabled": mqtt_enabled,
        "mqtt_connected": mqtt_enabled and client.is_connected(),
        "latest_data": latest_data,
        "upload_folder_exists": os.path.exists(UPLOAD_FOLDER),
        "image_count": len([f for f in os.listdir(UPLOAD_FOLDER) if f.endswith('.jpg')]) if os.path.exists(UPLOAD_FOLDER) else 0,
        "ai_api_url": AI_API_URL
    }
    return jsonify(debug_info)


@app.route("/api/leaf")
def get_leaf():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT * FROM leaf_images ORDER BY timestamp DESC LIMIT 1")
    data = c.fetchone()
    conn.close()
    return {"timestamp": data[0], "image": data[1]} if data else {"timestamp": "", "image": ""}


@app.route("/api/take_photo")
def take_photo():
    if not mqtt_enabled:
        return jsonify({
            "status": "error",
            "message": "MQTT is not enabled. Cannot take photo via MQTT."
        })
    client.publish("camera/control", "Take Photo")
    return {"status": "success"}


@app.route('/capture-image')
def capture_image():
    try:
        # Lấy các tham số từ request
        # Mặc định UXGA (1600x1200)
        resolution = request.args.get('resolution', 'UXGA')
        # Mặc định chất lượng 10 (cao nhất)
        quality = request.args.get('quality', '10')

        # Xây dựng URL với các tham số
        camera_url = f"http://192.168.141.171/capture?resolution={resolution}&quality={quality}"

        # Send request to get image from ESP32 camera
        print(f"Requesting ESP32 camera image with URL: {camera_url}")
        response = requests.get(camera_url, timeout=10)

        if response.status_code == 200:
            # Create filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_filename = f"esp32cam_{timestamp}.jpg"
            image_path = os.path.join(
                app.config['UPLOAD_FOLDER'], image_filename)

            # Save image to directory
            with open(image_path, 'wb') as f:
                f.write(response.content)

            return jsonify({
                "status": "success",
                "message": "Image captured and saved successfully",
                "filename": image_filename,
                "url": f"/images/{image_filename}"
            })
        else:
            return jsonify({
                "status": "error",
                "message": f"Failed to capture image: HTTP {response.status_code}"
            }), 500

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Error capturing image: {str(e)}"
        }), 500


@app.route('/images/<filename>')
def get_image(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/latest-image')
def get_latest_image():
    try:
        # Get all files in the uploads directory
        files = os.listdir(app.config['UPLOAD_FOLDER'])
        # Filter for jpg files only
        image_files = [f for f in files if f.endswith('.jpg')]

        if not image_files:
            return jsonify({"status": "error", "message": "No images found"})

        # Sort by creation time, get the newest file
        latest_image = sorted(image_files, key=lambda x: os.path.getmtime(
            os.path.join(app.config['UPLOAD_FOLDER'], x)), reverse=True)[0]

        return jsonify({
            "status": "success",
            "filename": latest_image,
            "url": f"/images/{latest_image}",
            "timestamp": os.path.getmtime(os.path.join(app.config['UPLOAD_FOLDER'], latest_image))
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Error getting latest image: {str(e)}"
        })


def get_latest_image_path():
    try:
        # Get all files in the uploads directory
        files = os.listdir(app.config['UPLOAD_FOLDER'])
        # Filter for jpg files only
        image_files = [f for f in files if f.endswith('.jpg')]

        if not image_files:
            print("No images found in uploads directory")
            return None

        # Sort by creation time, get the newest file
        latest_image = sorted(image_files, key=lambda x: os.path.getmtime(
            os.path.join(app.config['UPLOAD_FOLDER'], x)), reverse=True)[0]
            
        return os.path.join(app.config['UPLOAD_FOLDER'], latest_image)

    except Exception as e:
        print(f"Error getting latest image path: {str(e)}")
        return None


@app.route('/api/capture-and-analyze', methods=['POST'])
def capture_and_analyze():
    try:
        # Get the latest image path
        image_path = get_latest_image_path()
        if not image_path:
            return jsonify({
                'status': 'error',
                'message': 'No images found in uploads directory'
            })
        
        # Process with AI
        analysis_results = process_image_with_ai(image_path)
        if analysis_results:
            # Get relative path for response
            image_filename = os.path.basename(image_path)
            
            # Save to database
            conn = sqlite3.connect("database.db")
            c = conn.cursor()
            c.execute(
                "INSERT INTO leaf_images (timestamp, image, analysis) VALUES (datetime('now'), ?, ?)",
                (image_filename, str(analysis_results))
            )
            conn.commit()
            conn.close()
            
            return jsonify({
                'status': 'success',
                'image': f'/static/uploads/{image_filename}',
                'analysis': analysis_results
            })
            
        return jsonify({
            'status': 'error',
            'message': 'Failed to process image with AI. Please check if AI service is running properly.'
        })
    except requests.exceptions.Timeout:
        return jsonify({
            'status': 'error',
            'message': 'ESP32 camera connection timed out. Please check if the camera is accessible.'
        })
    except requests.exceptions.ConnectionError:
        return jsonify({
            'status': 'error',
            'message': 'Cannot connect to ESP32 camera. Please check if the camera is on the correct IP (192.168.141.171) and network.'
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'An error occurred: {str(e)}'
        })


@app.route('/api/camera-status')
def check_camera_status():
    try:
        session = create_session_with_retries()
        response = session.get(ESP32_WEBCAM_URL, timeout=(2, 5))
        if response.status_code == 200:
            return jsonify({
                'status': 'online',
                'message': 'ESP32 camera is accessible'
            })
        return jsonify({
            'status': 'error',
            'message': f'Camera returned status code: {response.status_code}'
        })
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
        return jsonify({
            'status': 'offline',
            'message': 'ESP32 camera is not accessible'
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Error checking camera: {str(e)}'
        })


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)