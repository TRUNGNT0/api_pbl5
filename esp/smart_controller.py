from device_manager import DeviceStateManager
import paho.mqtt.client as mqtt
import json
import threading
import time
from datetime import datetime
from logger_config import smart_garden_logger as logger

class SmartController:
    def __init__(self, mqtt_client):
        self.device_manager = DeviceStateManager()
        self.mqtt_client = mqtt_client
        self.disease_controls = {
            "Anthracnose": {  # Bệnh thán thư
                "humidity_threshold": 70,
                "soil_moisture_threshold": 65,
                "fan_duration": 300,  # 5 phút
                "pump_duration": 3
            },
            "Bacterial Spot": {  # Bệnh đốm vi khuẩn  
                "humidity_threshold": 65,
                "soil_moisture_threshold": 60,
                "fan_duration": 600,  # 10 phút
                "pump_duration": 2
            },
            "Downy Mildew": {  # Bệnh sương mai
                "humidity_threshold": 60,
                "soil_moisture_threshold": 55,
                "fan_duration": 900,  # 15 phút
                "pump_duration": 2
            },
            "Pest Damage": {
                "humidity_threshold": 65,
                "fan_duration": 300,
                "pump_duration": 3
            }
        }

    def process_analysis(self, analysis_result, sensor_data):
        if not analysis_result or not isinstance(analysis_result, list):
            return None
            
        disease = analysis_result[0].get("predicted_class")
        confidence = analysis_result[0].get("confidence", 0)
        
        if confidence < 0.45 or disease not in self.disease_controls:
            return None

        control = self.disease_controls[disease]
        actions = []

        # Kiểm tra thiết bị có đang được Raspberry sử dụng không
        fan_free = self.device_manager.is_device_free("fan1")
        pump_free = self.device_manager.is_device_free("pump1")

        current_hour = datetime.now().hour
        
        # Xử lý quạt dựa trên độ ẩm
        if (fan_free and 
            sensor_data["humidity"] > control["humidity_threshold"]):
            actions.append({
                "device": "fan",
                "duration": control["fan_duration"],
                "priority": "high" if disease in ["Downy Mildew", "Bacterial Spot"] else "medium"
            })

        # Xử lý bơm nước (chỉ ban ngày 6h-18h)
        if (pump_free and 
            6 <= current_hour <= 18 and
            "soil_moisture_threshold" in control and
            sensor_data["soil_moisture"] < control["soil_moisture_threshold"]):
            actions.append({
                "device": "pump",
                "duration": control["pump_duration"],
                "priority": "medium"
            })

        return actions

    def execute_action(self, action):
        """Thực thi một hành động điều khiển"""
        device_id = f"{action['device']}1"
        motor_num = 1 if action["device"] == "fan" else 2
        
        if self.device_manager.is_device_free(device_id):
            # Bật thiết bị
            self.mqtt_client.publish("motor/control",
                json.dumps({"motor": motor_num, "state": "run"}))
            self.device_manager.set_device_state(device_id, "OPEN", "smart")
            
            # Tự động tắt sau thời gian định sẵn
            def auto_stop():
                time.sleep(action["duration"])
                self.mqtt_client.publish("motor/control",
                    json.dumps({"motor": motor_num, "state": "stop"}))
                self.device_manager.set_device_state(device_id, "CLOSED", "smart")
                
            threading.Thread(target=auto_stop, daemon=True).start()
