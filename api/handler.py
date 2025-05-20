
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
MODEL_YOLO_PATH = 'D:/USER/fastAPI/PBL5/api/best.pt'
if not os.path.exists(MODEL_YOLO_PATH):
    raise FileNotFoundError(f"Mô hình YOLO không tồn tại tại: {MODEL_YOLO_PATH}")
yolo_model = YOLO(MODEL_YOLO_PATH)

# Tải mô hình ResNet18
num_classes = 5
resnet_model = models.resnet18(pretrained=False)
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

MODEL_RESNET_PATH = 'D:/USER/fastAPI/PBL5/api/pbl5_ver4.pth'
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

# Danh sách lớp
class_names = ['Anthracnose', 'Bacterial-Spot', 'Downy-Mildew', 'Healthy-Leaf', 'Pest-Damage']

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

    leaves = []
    results_list = []

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
            pred_class = torch.argmax(output, dim=1).item()
        
        results_list.append({
            "predicted_class": class_names[pred_class],
            "confidence": float(confidences[i])
        })
        leaves.append(leaf)

    return results_list