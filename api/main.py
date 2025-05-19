
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import os
from handler import process_leaf_image
from pydantic import BaseModel
from typing import List, Dict

app = FastAPI()

# Thư mục lưu ảnh upload
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

class PredictionResult(BaseModel):
    leaf_index: int
    predicted_class: str
    confidence: float

@app.post("/predict", response_model=List[PredictionResult])
async def predict_leaves(file: UploadFile = File(...)):
    # Kiểm tra loại file
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File phải là ảnh")
    
    # Lưu file tạm thời
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        f.write(await file.read())
    
    try:
        # Gọi hàm xử lý từ handler
        results = process_leaf_image(file_path)
        return [
            PredictionResult(
                leaf_index=i+1,
                predicted_class=result["predicted_class"],
                confidence=result["confidence"]
            )
            for i, result in enumerate(results)
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi xử lý: {str(e)}")
    finally:
        # Xóa file tạm thời
        if os.path.exists(file_path):
            os.remove(file_path)

@app.get("/")
async def root():
    return {"message": "API nhận diện bệnh lá cây"}
