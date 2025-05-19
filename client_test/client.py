
import requests
import os

def send_image_to_server(image_path: str, server_url: str = "http://127.0.0.1:8000/predict"):
    """
    Gửi file ảnh đến server FastAPI và nhận kết quả dự đoán.
    
    Args:
        image_path (str): Đường dẫn đến file ảnh
        server_url (str): URL của endpoint predict
    """
    # Kiểm tra file tồn tại
    if not os.path.exists(image_path):
        print(f"Error: File {image_path} không tồn tại")
        return
    
    # Kiểm tra định dạng file
    if not image_path.lower().endswith(('.jpg', '.jpeg', '.png')):
        print("Error: Vui lòng chọn file ảnh (jpg, jpeg, hoặc png)")
        return
    
    try:
        # Gửi yêu cầu POST với file ảnh
        with open(image_path, "rb") as f:
            files = {"file": (os.path.basename(image_path), f, "image/jpeg")}
            response = requests.post(server_url, files=files)
        
        # Kiểm tra trạng thái phản hồi
        if response.status_code == 200:
            results = response.json()
            print("\nKết quả dự đoán:")
            for result in results:
                print(f"Lá {result['leaf_index']}: {result['predicted_class']} "
                      f"(Độ tin cậy: {result['confidence']:.2f})")
        else:
            print(f"Error: Server trả về mã lỗi {response.status_code}")
            print(response.json().get("detail", "Không có chi tiết lỗi"))
    
    except requests.exceptions.RequestException as e:
        print(f"Error: Không thể kết nối đến server - {str(e)}")

if __name__ == "__main__":
    # Ví dụ sử dụng
    image_path = input("Nhập đường dẫn file ảnh (jpg, jpeg, png): ")
    send_image_to_server(image_path)
