#include "esp_camera.h"
#include <WiFi.h>
#include <HTTPClient.h>

// Thay bằng SSID/Pass của bạn
const char *ssid = "Tuan Hanh 2";
const char *password = "18197911";

// Địa chỉ server trên laptop, ví dụ chạy Flask trên cổng 5000
// Thay đổi địa chỉ IP này thành địa chỉ IP của laptop của bạn
const char *serverUrl = "http://192.168.3.14:5000/upload";

//
// Cấu hình chân camera (AI Thinker module)
//
camera_config_t config = {
    .pin_pwdn = 32,
    .pin_reset = -1,
    .pin_xclk = 0,
    .pin_sscb_sda = 26,
    .pin_sscb_scl = 27,
    .pin_d7 = 35,
    .pin_d6 = 34,
    .pin_d5 = 39,
    .pin_d4 = 36,
    .pin_d3 = 21,
    .pin_d2 = 19,
    .pin_d1 = 18,
    .pin_d0 = 5,
    .pin_vsync = 25,
    .pin_href = 23,
    .pin_pclk = 22,
    .xclk_freq_hz = 20000000,
    .ledc_timer = LEDC_TIMER_0,
    .ledc_channel = LEDC_CHANNEL_0,
    .pixel_format = PIXFORMAT_JPEG,
    .frame_size = FRAMESIZE_VGA,
    .jpeg_quality = 12,
    .fb_count = 1};

void setup()
{
    Serial.begin(115200);
    IPAddress local_IP(192, 168, 141, 100); // IP tĩnh
    IPAddress gateway(192, 168, 141, 1);    // Gateway của router
    IPAddress subnet(255, 255, 255, 0);
    WiFi.config(local_IP, gateway, subnet);
    WiFi.begin(ssid, password);
    // Khởi camera
    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK)
    {
        Serial.printf("Camera init failed with error 0x%x", err);
        while (true)
            ;
    }
    // Kết nối WiFi
    WiFi.begin(ssid, password);
    Serial.print("Connecting to WiFi");
    while (WiFi.status() != WL_CONNECTED)
    {
        delay(500);
        Serial.print(".");
    }
    Serial.println("\nWiFi connected!");
    Serial.print("ESP32-CAM IP Address: ");
    Serial.println(WiFi.localIP()); // In địa chỉ IP của ESP32-CAM
}

void loop()
{
    if (WiFi.status() == WL_CONNECTED)
    {
        // Chụp ảnh
        camera_fb_t *fb = esp_camera_fb_get();
        if (!fb)
        {
            Serial.println("Camera capture failed");
            delay(1000);
            return;
        }

        Serial.println("Chụp ảnh thành công");
        Serial.printf("Kích thước ảnh: %d bytes\n", fb->len);

        // Gửi POST
        HTTPClient http;
        http.begin(serverUrl);
        http.addHeader("Content-Type", "image/jpeg");
        int httpCode = http.POST(fb->buf, fb->len);
        if (httpCode > 0)
        {
            Serial.printf("Upload HTTP code: %d\n", httpCode);
            String response = http.getString();
            Serial.println("Server response: " + response);
        }
        else
        {
            Serial.printf("Upload failed: %s\n", http.errorToString(httpCode).c_str());
        }
        http.end();
        esp_camera_fb_return(fb);

        Serial.println("Đã gửi ảnh lên server");
    }
    else
    {
        Serial.println("WiFi lost connection");
        // Thử kết nối lại WiFi
        WiFi.reconnect();
    }
    delay(5000); // chụp gửi mỗi 5s
}