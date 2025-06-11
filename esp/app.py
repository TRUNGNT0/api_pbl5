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
import json
import cv2
import numpy as np
from smart_controller import SmartController
from device_manager import DeviceStateManager
import threading

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
    c.execute('''CREATE TABLE IF NOT EXISTS sensor_data (
        timestamp TEXT,
        temperature REAL,
        humidity REAL,
        light REAL,
        moisture INTEGER
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS leaf_images (
        timestamp TEXT,
        image TEXT,
        analysis TEXT
    )''')

    # Create table for device status tracking
    c.execute('''CREATE TABLE IF NOT EXISTS device_status (
        timestamp TEXT,
        device_type TEXT,
        device_id TEXT,
        status TEXT
    )''')

    conn.commit()
    conn.close()


def rotate_image_180(image_path):
    """
    Rotate an image 180 degrees and save it back to the same path

    Args:
        image_path (str): Path to the image file

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Read the image
        img = cv2.imread(image_path)
        if img is None:
            print(f"Error: Could not read image from {image_path}")
            return False

        # Rotate 180 degrees (equivalent to flipping both vertically and horizontally)
        # Flip both vertically and horizontally = 180° rotation
        rotated_img = cv2.flip(img, -1)

        # Save the rotated image back to the same path
        success = cv2.imwrite(image_path, rotated_img)
        if success:
            print(f"Image rotated 180° and saved successfully: {image_path}")
            return True
        else:
            print(f"Error: Failed to save rotated image to {image_path}")
            return False

    except Exception as e:
        print(f"Error rotating image {image_path}: {str(e)}")
        return False


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
            print(
                f"Error from AI API: Server trả về mã lỗi {response.status_code}")
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
        # (connect timeout, read timeout)
        response = session.get(ESP32_WEBCAM_URL, timeout=(5, 10))
        if response.status_code == 200:
            # Generate unique filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_filename = f"leaf_{timestamp}.jpg"
            image_path = os.path.join(
                app.config['UPLOAD_FOLDER'], image_filename)

            # Save the image
            with open(image_path, 'wb') as f:
                f.write(response.content)

            # Rotate the image 180 degrees
            rotate_success = rotate_image_180(image_path)
            if not rotate_success:
                print(f"Warning: Failed to rotate image {image_filename}")

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
            print(
                f"Failed to capture image. Status code: {response.status_code}")
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
    # Subscribe to sensor topics with device IDs
    client.subscribe("sensor/temp1")
    client.subscribe("sensor/hum1")
    client.subscribe("sensor/light1")
    client.subscribe("sensor/soil1")
    # Subscribe to device status topics
    client.subscribe("device/fan1")
    client.subscribe("device/pump1")
    client.subscribe("device/cover1")
    client.subscribe("image/leaf")


def publish_sensor_data(sensor_type, device_id, value):
    try:
        message = {
            "type": sensor_type,
            "device_id": device_id,
            "value": value,
            "time": datetime.now().isoformat()
        }
        client.publish(f"sensor/{device_id}", json.dumps(message))
        print(f"Published {sensor_type} data: {message}")
    except Exception as e:
        print(f"Error publishing sensor data: {e}")


def on_message(client, userdata, msg):
    global latest_data
    try:
        data = json.loads(msg.payload.decode())
        topic = msg.topic

        # Handle sensor messages
        if topic.startswith("sensor/") and "type" in data and "device_id" in data and "value" in data and "time" in data:
            if data["type"] == "Temperature":
                latest_data["temperature"] = data["value"]
            elif data["type"] == "Humidity":
                latest_data["humidity"] = data["value"]
            elif data["type"] == "Light":
                latest_data["light"] = data["value"]
            elif data["type"] == "Soil_Moisture":
                latest_data["moisture"] = data["value"]

        # Handle device status messages
        elif topic.startswith("device/") and "type" in data and "device_id" in data and "status" in data and "time" in data:
            # Update device state
            device_manager.set_device_state(data["device_id"], data["status"], "raspberry")

    except Exception as e:
        print(f"Error processing MQTT message: {e}")


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

# Initialize device manager and smart controller
device_manager = DeviceStateManager()
smart_controller = SmartController(client)  # Initialize with MQTT client


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def get_data():
    return latest_data


@app.route("/api/data/history")
def get_sensor_history():
    try:
        # Get query parameters for filtering
        limit = request.args.get('limit', 100, type=int)
        hours = request.args.get('hours', 24, type=int)

        conn = sqlite3.connect("database.db")
        c = conn.cursor()

        # Get sensor data from the last N hours
        c.execute("""
            SELECT timestamp, temperature, humidity, light, moisture 
            FROM sensor_data 
            WHERE datetime(timestamp) >= datetime('now', '-{} hours')
            ORDER BY timestamp DESC 
            LIMIT ?
        """.format(hours), (limit,))

        rows = c.fetchall()
        conn.close()

        # Convert to list of dictionaries
        history = []
        for row in rows:
            history.append({
                'timestamp': row[0],
                'temperature': row[1],
                'humidity': row[2],
                'light': row[3],
                'moisture': row[4]
            })

        return jsonify({
            'status': 'success',
            'data': history,
            'count': len(history),
            'latest': latest_data
        })

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Error retrieving sensor history: {str(e)}'
        }), 500


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

            # Rotate the image 180 degrees
            rotate_success = rotate_image_180(image_path)
            if not rotate_success:
                print(f"Warning: Failed to rotate image {image_filename}")

            return jsonify({
                "status": "success",
                "message": "Image captured and saved successfully",
                "filename": image_filename,
                "url": f"/images/{image_filename}",
                "rotated": rotate_success
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


@app.route('/api/analyze-uploaded', methods=['POST'])
def analyze_uploaded_image():
    """
    Phân tích ảnh đã upload từ máy tính
    """
    try:
        data = request.get_json()
        filename = data.get('filename')

        if not filename:
            return jsonify({
                'status': 'error',
                'message': 'No filename provided'
            }), 400

        image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        if not os.path.exists(image_path):
            return jsonify({
                'status': 'error',
                'message': 'Image file not found'
            }), 404

        # Process with AI
        analysis_results = process_image_with_ai(image_path)

        if analysis_results:
            # Cập nhật kết quả phân tích vào database
            conn = sqlite3.connect("database.db")
            c = conn.cursor()
            c.execute(
                "UPDATE leaf_images SET analysis = ? WHERE image = ?",
                (str(analysis_results), filename)
            )
            conn.commit()
            conn.close()

            return jsonify({
                'status': 'success',
                'filename': filename,
                'analysis': analysis_results
            })
        else:
            # Fallback to mock data if AI is not available
            analysis_results = [
                {
                    'predicted_class': 'Healthy Leaf',
                    'confidence': 0.85,
                    'details': 'The leaf appears to be in good condition with no visible diseases.'
                },
                {
                    'predicted_class': 'No Disease Detected',
                    'confidence': 0.92,
                    'details': 'Analysis shows normal leaf structure and coloration.'
                }
            ]

            # Cập nhật kết quả phân tích vào database
            conn = sqlite3.connect("database.db")
            c = conn.cursor()
            c.execute(
                "UPDATE leaf_images SET analysis = ? WHERE image = ?",
                (str(analysis_results), filename)
            )
            conn.commit()
            conn.close()

            return jsonify({
                'status': 'success',
                'filename': filename,
                'analysis': analysis_results,
                'note': 'Using mock data - AI service may not be available'
            })

    except Exception as e:
        print(f"Error analyzing uploaded image: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Error analyzing image: {str(e)}'
        }), 500


@app.route('/api/upload-file', methods=['POST'])
def upload_file_from_computer():
    """
    Route cho upload ảnh từ máy tính
    """
    try:
        if 'file' not in request.files:
            return jsonify({'status': 'error', 'message': 'No file provided'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'status': 'error', 'message': 'No file selected'}), 400

        # Kiểm tra định dạng file
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif'}
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in allowed_extensions:
            return jsonify({
                'status': 'error',
                'message': f'Invalid file type. Allowed: {", ".join(allowed_extensions)}'
            }), 400

        # Đọc dữ liệu ảnh
        image_data = file.read()

        # Tạo tên file với timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"computer_{timestamp}{file_ext}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        # Lưu file
        with open(file_path, 'wb') as f:
            f.write(image_data)

        print(
            f"Image uploaded from computer: {filename}, Size: {len(image_data)} bytes")

        # Lưu vào database
        conn = sqlite3.connect("database.db")
        c = conn.cursor()
        c.execute(
            "INSERT INTO leaf_images (timestamp, image, analysis) VALUES (datetime('now'), ?, ?)",
            (filename, 'Uploaded from computer')
        )
        conn.commit()
        conn.close()

        return jsonify({
            'status': 'success',
            'filename': filename,
            'url': f'/images/{filename}',
            'size': len(image_data)
        }), 200

    except Exception as e:
        print(f"Computer upload error: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Error uploading image: {str(e)}'
        }), 500


@app.route('/upload', methods=['POST'])
def upload_from_esp32():
    try:
        # Nhận dữ liệu ảnh từ ESP32-CAM
        image_data = request.get_data()

        if not image_data:
            return jsonify({
                'status': 'error',
                'message': 'No image data received'
            }), 400

        # Tạo tên file với timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"esp32auto_{timestamp}.jpg"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        # Lưu ảnh vào thư mục
        with open(filepath, 'wb') as f:
            f.write(image_data)

        # Rotate the image 180 degrees
        rotate_success = rotate_image_180(filepath)
        if not rotate_success:
            print(
                f"Warning: Failed to rotate ESP32 auto-uploaded image {filename}")

        print(f"ESP32 auto upload saved: {filename} ({len(image_data)} bytes)")

        # Lưu vào database
        conn = sqlite3.connect("database.db")
        c = conn.cursor()
        c.execute(
            "INSERT INTO leaf_images (timestamp, image) VALUES (datetime('now'), ?)",
            (filename,)
        )
        conn.commit()
        conn.close()

        return jsonify({
            'status': 'success',
            'filename': filename,
            'size': len(image_data)
        }), 200

    except Exception as e:
        print(f"ESP32 upload error: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Error uploading image: {str(e)}'
        }), 500


@app.route('/api/capture-esp32-and-analyze', methods=['POST'])
def capture_esp32_and_analyze():
    try:
        # Capture image from ESP32-CAM
        resolution = request.args.get('resolution', 'UXGA')
        quality = request.args.get('quality', '10')
        camera_url = f"http://192.168.141.171/capture?resolution={resolution}&quality={quality}"

        print(f"Capturing image from ESP32-CAM: {camera_url}")
        response = requests.get(camera_url, timeout=10)

        if response.status_code != 200:
            return jsonify({
                'status': 'error',
                'message': f'Failed to capture image from ESP32-CAM: HTTP {response.status_code}'
            }), 500

        # Save image
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_filename = f"esp32cam_{timestamp}.jpg"
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], image_filename)

        with open(image_path, 'wb') as f:
            f.write(response.content)

        # Rotate the image 180 degrees (only for ESP32 camera images)
        rotate_success = rotate_image_180(image_path)
        if not rotate_success:
            print(f"Warning: Failed to rotate ESP32 image {image_filename}")

        print(f"Image saved and rotated: {image_filename}")

        # Process with AI - skip for now since AI API may not be available
        analysis_results = None

        return jsonify({
            'status': 'success',
            'image': f'/images/{image_filename}',
            'filename': image_filename,
            'analysis': analysis_results,
            'rotated': rotate_success
        })

    except requests.exceptions.Timeout:
        return jsonify({
            'status': 'error',
            'message': 'ESP32 camera connection timed out'
        }), 500
    except requests.exceptions.ConnectionError:
        return jsonify({
            'status': 'error',
            'message': 'Cannot connect to ESP32 camera'
        }), 500
    except Exception as e:
        print(f"Error in capture_esp32_and_analyze: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Error: {str(e)}'
        }), 500


@app.route('/api/motor/control', methods=['POST'])
def control_motor():
    if not mqtt_enabled:
        return jsonify({
            "status": "error",
            "message": "MQTT is not enabled. Cannot control motors."
        }), 500

    try:
        data = request.get_json()
        motor = data.get('motor')  # 1 for fan, 2 for pump
        state = data.get('state')  # "run" or "stop"

        if motor not in [1, 2]:
            return jsonify({
                "status": "error",
                "message": "Invalid motor number. Use 1 for fan or 2 for pump."
            }), 400

        if state not in ["run", "stop"]:
            return jsonify({
                "status": "error",
                "message": "Invalid state. Use 'run' or 'stop'."
            }), 400

        # Publish MQTT message to control motor
        message = json.dumps({"motor": motor, "state": state})
        client.publish("motor/control", message)

        motor_name = "Fan" if motor == 1 else "Pump"
        print(f"Motor control command sent: {motor_name} -> {state}")

        return jsonify({
            "status": "success",
            "message": f"{motor_name} {state} command sent successfully"
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Error controlling motor: {str(e)}"
        }), 500


@app.route('/api/motor/status')
def get_motor_status():
    # This endpoint can be used to get current motor status
    # For now, we'll return a basic response since we don't track motor state
    return jsonify({
        "mqtt_enabled": mqtt_enabled,
        "mqtt_connected": mqtt_enabled and client.is_connected(),
        "message": "Motor control is available" if mqtt_enabled else "MQTT not available"
    })


@app.route('/api/servo/control', methods=['POST'])
def control_servo():
    if not mqtt_enabled:
        return jsonify({
            "status": "error",
            "message": "MQTT is not enabled. Cannot control servo."
        }), 500

    try:
        data = request.get_json()
        angle = data.get('angle')

        if angle is None:
            return jsonify({
                "status": "error",
                "message": "Angle parameter is required."
            }), 400

        if not isinstance(angle, (int, float)) or not (0 <= angle <= 150):
            return jsonify({
                "status": "error",
                "message": "Invalid angle. Must be between 0 and 150 degrees."
            }), 400

        # Publish MQTT message to control servo
        message = json.dumps({"angle": angle})
        client.publish("servo/control", message)

        print(f"Servo control command sent: {angle} degrees")

        return jsonify({
            "status": "success",
            "message": f"Servo set to {angle} degrees successfully",
            "angle": angle
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Error controlling servo: {str(e)}"
        }), 500


@app.route('/api/servo/status')
def get_servo_status():
    # Return servo control availability status
    return jsonify({
        "mqtt_enabled": mqtt_enabled,
        "mqtt_connected": mqtt_enabled and client.is_connected(),
        "min_angle": 0,
        "max_angle": 150,
        "message": "Servo control is available" if mqtt_enabled else "MQTT not available"
    })


@app.route('/api/devices/status')
def get_devices_status():
    """Get recent device status history"""
    try:
        limit = request.args.get('limit', 50, type=int)

        conn = sqlite3.connect("database.db")
        c = conn.cursor()

        c.execute("""
            SELECT timestamp, device_type, device_id, status 
            FROM device_status 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (limit,))

        rows = c.fetchall()
        conn.close()

        # Convert to list of dictionaries
        device_history = []
        for row in rows:
            device_history.append({
                'timestamp': row[0],
                'device_type': row[1],
                'device_id': row[2],
                'status': row[3]
            })

        return jsonify({
            'status': 'success',
            'devices': device_history,
            'count': len(device_history)
        })

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Error retrieving device status: {str(e)}'
        }), 500


from logger_config import smart_garden_logger as logger

@app.route('/api/smart-control', methods=['POST'])
def smart_control():
    try:
        logger.info("Smart control request received")
        # Get latest analysis
        conn = sqlite3.connect("database.db")
        c = conn.cursor()
        c.execute("""
            SELECT analysis FROM leaf_images 
            ORDER BY timestamp DESC LIMIT 1
        """)
        analysis = c.fetchone()
        conn.close()

        if not analysis:
            return jsonify({
                "status": "error", 
                "message": "No analysis found"
            })

        # Convert string to dict
        analysis_data = eval(analysis[0])
        
        # Get current sensor data
        sensor_data = {
            "temperature": latest_data["temperature"],
            "humidity": latest_data["humidity"],
            "soil_moisture": latest_data["moisture"],
            "light": latest_data["light"]
        }

        # Process with smart controller
        actions = smart_controller.process_analysis(analysis_data, sensor_data)
        
        if not actions:
            return jsonify({
                "status": "success",
                "message": "No actions needed"
            })

        # Execute each action
        for action in actions:
            # Execute in a new thread to not block
            threading.Thread(
                target=smart_controller.execute_action,
                args=(action,),
                daemon=True
            ).start()

        return jsonify({
            "status": "success",
            "actions": actions
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
