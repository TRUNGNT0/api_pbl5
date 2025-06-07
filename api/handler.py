import os
import cv2
import numpy as np
import torch
import torch.nn as nn
from torchvision import models, transforms
from ultralytics import YOLO
from typing import List, Dict

# Thiết bị
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Tải mô hình YOLO
MODEL_YOLO_PATH = 'best.pt'
if not os.path.exists(MODEL_YOLO_PATH):
    raise FileNotFoundError(f"Mô hình YOLO không tồn tại tại: {MODEL_YOLO_PATH}")
yolo_model = YOLO(MODEL_YOLO_PATH)

# Tải mô hình ResNet18
num_classes = 5
resnet_model = models.resnet18(weights=None)
for param in resnet_model.parameters():
    param.requires_grad = False
for param in resnet_model.layer2.parameters():
    param.requires_grad = True
for param in resnet_model.layer3.parameters():
    param.requires_grad = True
for param in resnet_model.layer4.parameters():
    param.requires_grad = True

num_ftrs = resnet_model.fc.in_features
resnet_model.fc = nn.Sequential(
    nn.BatchNorm1d(num_ftrs),
    nn.Dropout(0.5),
    nn.Linear(num_ftrs, 512),
    nn.ReLU(),
    nn.BatchNorm1d(512),
    nn.Dropout(0.4),
    nn.Linear(512, 256),
    nn.ReLU(),
    nn.BatchNorm1d(256),
    nn.Dropout(0.4),
    nn.Linear(256, num_classes)
)

MODEL_RESNET_PATH = 'pbl5_ver4.pth'
resnet_model.load_state_dict(torch.load(MODEL_RESNET_PATH, map_location=device))
resnet_model.eval()
resnet_model = resnet_model.to(device)

# Tiền xử lý ảnh
transform = transforms.Compose([
    transforms.ToPILImage(),
    transforms.Resize((448, 448)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
])

# Danh sách lớp và độ ưu tiên
class_names = ['Anthracnose', 'Bacterial-Spot', 'Downy-Mildew', 'Healthy-Leaf', 'Pest-Damage']
priority = {
    'Anthracnose': 1,
    'Downy-Mildew': 2,
    'Bacterial-Spot': 3,
    'Pest-Damage': 4,
    'Healthy-Leaf': 5
}

def process_leaf_image(image_path: str) -> List[Dict]:
    """Xử lý ảnh và dự đoán bệnh lá cây"""
    try:
        # Đọc và chuyển đổi ảnh
        img = cv2.imread(image_path)
        if img is None:
            raise Exception(f"Không thể đọc ảnh tại: {image_path}")
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w = img.shape[:2]
    except Exception as e:
        raise Exception(f"Lỗi khi đọc ảnh: {e}")

    # Phát hiện lá bằng YOLO
    results = yolo_model.predict(source=img, imgsz=640, conf=0.5)
    boxes = results[0].boxes.xyxy.cpu().numpy()
    confidences = results[0].boxes.conf.cpu().numpy()

    if len(boxes) == 0:
        return [{"predicted_class": "Tình trạng cây: Không phát hiện được lá", "confidence": 0.0}]

    # Dictionary để đếm tần suất và tính tổng xác suất các bệnh
    disease_scores = {name: {"count": 0, "total_confidence": 0.0, "avg_confidence": 0.0} for name in class_names}
    total_leaves = 0

    # Cắt và dự đoán từng lá
    for i, box in enumerate(boxes):
        x1, y1, x2, y2 = map(int, box)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        
        leaf = img[y1:y2, x1:x2]
        
        # Tiền xử lý và dự đoán
        input_tensor = transform(leaf).unsqueeze(0).to(device)
        with torch.no_grad():
            output = resnet_model(input_tensor)
            probabilities = torch.softmax(output, dim=1)
            pred_class = torch.argmax(output, dim=1).item()
            confidence = float(probabilities[0][pred_class])
        
        disease_name = class_names[pred_class]
        disease_scores[disease_name]["count"] += 1
        disease_scores[disease_name]["total_confidence"] += confidence
        total_leaves += 1

    # Tính trung bình xác suất cho mỗi bệnh
    for disease in disease_scores:
        if disease_scores[disease]["count"] > 0:
            disease_scores[disease]["avg_confidence"] = (
                disease_scores[disease]["total_confidence"] / disease_scores[disease]["count"]
            )

    # Tìm bệnh có độ ưu tiên cao nhất trong các bệnh được phát hiện
    detected_diseases = [disease for disease in disease_scores if disease_scores[disease]["count"] > 0]
    if not detected_diseases:
        return [{"predicted_class": "Tình trạng cây: Không phát hiện được bệnh", "confidence": 0.0}]

    # Sắp xếp theo độ ưu tiên và lấy bệnh có ưu tiên cao nhất
    highest_priority_disease = min(detected_diseases, key=lambda x: priority[x])
    
    # Tạo kết quả chi tiết
    result = {
        "predicted_class": f"Tình trạng cây: {highest_priority_disease}",
        "confidence": float(disease_scores[highest_priority_disease]["avg_confidence"]),
        "details": f"Phát hiện {disease_scores[highest_priority_disease]['count']} trên tổng số {total_leaves} lá"
    }

    return [result]