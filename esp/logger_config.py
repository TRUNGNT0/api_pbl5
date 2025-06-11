import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler

class CustomLogger:
    def __init__(self):
        # Tạo thư mục logs nếu chưa tồn tại
        self.log_dir = "logs"
        os.makedirs(self.log_dir, exist_ok=True)

        # Tạo logger
        self.logger = logging.getLogger('smart_garden')
        self.logger.setLevel(logging.INFO)

        # Định dạng log
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        # File handler cho error logs
        error_handler = RotatingFileHandler(
            os.path.join(self.log_dir, 'error.log'),
            maxBytes=1024*1024,  # 1MB
            backupCount=5
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)

        # File handler cho device logs
        device_handler = RotatingFileHandler(
            os.path.join(self.log_dir, 'device.log'),
            maxBytes=1024*1024,
            backupCount=5
        )
        device_handler.setLevel(logging.INFO)
        device_handler.setFormatter(formatter)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)

        # Thêm handlers
        self.logger.addHandler(error_handler)
        self.logger.addHandler(device_handler)
        self.logger.addHandler(console_handler)

    def log_device_action(self, device_id, action, controller, duration=None):
        """Log hành động điều khiển thiết bị"""
        message = f"Device: {device_id}, Action: {action}, Controller: {controller}"
        if duration:
            message += f", Duration: {duration}s"
        self.logger.info(message)

    def log_error(self, error_type, message, details=None):
        """Log lỗi"""
        error_message = f"Type: {error_type}, Message: {message}"
        if details:
            error_message += f", Details: {details}"
        self.logger.error(error_message)

    def log_analysis(self, disease, confidence, actions):
        """Log kết quả phân tích và hành động"""
        self.logger.info(
            f"Analysis - Disease: {disease}, Confidence: {confidence:.2f}, "
            f"Actions: {actions}"
        )

    def log_sensor_data(self, sensor_data):
        """Log dữ liệu cảm biến"""
        self.logger.info(f"Sensor Data: {sensor_data}")

# Tạo instance logger global
smart_garden_logger = CustomLogger().logger
