# MQTT Message Format Update - Implementation Guide

## Overview
This document describes the changes made to implement the new MQTT message format as specified in the requirements image.

## Changes Made

### 1. Raspberry Pi Code (`raspberry_pi_sensor.py`)

#### New Message Format Functions:
- `publish_sensor_message()`: Sends sensor data in the new format
- `publish_device_status()`: Sends device status in the new format

#### Sensor Messages Format:
```json
{
    "type": "Temperature|Humidity|Light|Soil_Moisture",
    "device_id": "temp1|hum1|light1|soil1",
    "value": numeric_value,
    "time": "2025-06-11T08:30:15"
}
```

#### Device Status Messages Format:
```json
{
    "type": "Fan|Pump|Cover",
    "device_id": "fan1|pump1|cover1",
    "status": "OPEN|CLOSED|HALF|ANGLE_X",
    "time": "2025-06-11T08:30:15"
}
```

#### Device ID Mapping:
- Temperature sensor: `temp1`
- Humidity sensor: `hum1`
- Light sensor: `light1`
- Soil moisture sensor: `soil1`
- Fan: `fan1`
- Pump: `pump1`
- Servo cover: `cover1`

### 2. Flask Application (`esp/app.py`)

#### Updated MQTT Subscription:
- Now subscribes to specific device topics: `sensor/temp1`, `sensor/hum1`, etc.
- Added device status subscriptions: `device/fan1`, `device/pump1`, `device/cover1`

#### Enhanced Message Processing:
- Handles both sensor messages and device status messages
- Extracts data based on message type and device ID
- Improved error handling and logging

#### New Database Table:
- Added `device_status` table to track device state changes
- Stores timestamp, device_type, device_id, and status

#### New API Endpoints:
- `/api/data/history` - Get historical sensor data
- `/api/devices/status` - Get device status history

### 3. Test Script (`test_mqtt_format.py`)
Created a test script to verify the new message format works correctly.

## Testing Instructions

### 1. Update Raspberry Pi Code
```bash
# Copy the new raspberry_pi_sensor.py to your Raspberry Pi
scp raspberry_pi_sensor.py pi@192.168.141.250:~/
```

### 2. Start the Updated Flask Application
```powershell
cd d:\CodeBase\api_pbl5-main-new\esp
python app.py
```

### 3. Test Message Format (Optional)
```powershell
cd d:\CodeBase\api_pbl5-main-new
python test_mqtt_format.py
```

### 4. Start Raspberry Pi Sensor Code
```bash
# On Raspberry Pi
python3 raspberry_pi_sensor.py
```

## API Endpoints for Testing

### Get Current Sensor Data
```
GET http://localhost:5000/api/data
```

### Get Sensor History
```
GET http://localhost:5000/api/data/history?limit=50&hours=24
```

### Get Device Status History
```
GET http://localhost:5000/api/devices/status?limit=20
```

### Control Motors
```
POST http://localhost:5000/api/motor/control
Content-Type: application/json

{
    "motor": 1,  // 1 for fan, 2 for pump
    "state": "run"  // "run" or "stop"
}
```

### Control Servo
```
POST http://localhost:5000/api/servo/control
Content-Type: application/json

{
    "angle": 75  // 0-150 degrees
}
```

## Message Examples

### Sensor Data Examples:
- **Temperature**: `{"type": "Temperature", "device_id": "temp1", "value": 25.5, "time": "2025-06-11T08:30:15"}`
- **Humidity**: `{"type": "Humidity", "device_id": "hum1", "value": 65.0, "time": "2025-06-11T08:30:15"}`
- **Light**: `{"type": "Light", "device_id": "light1", "value": 8500, "time": "2025-06-11T08:30:15"}`
- **Soil Moisture**: `{"type": "Soil_Moisture", "device_id": "soil1", "value": 70, "time": "2025-06-11T08:30:15"}`

### Device Status Examples:
- **Fan**: `{"type": "Fan", "device_id": "fan1", "status": "OPEN", "time": "2025-06-11T08:30:15"}`
- **Pump**: `{"type": "Pump", "device_id": "pump1", "status": "CLOSED", "time": "2025-06-11T08:30:15"}`
- **Cover**: `{"type": "Cover", "device_id": "cover1", "status": "HALF", "time": "2025-06-11T08:30:15"}`

## Troubleshooting

### 1. MQTT Connection Issues
- Verify Raspberry Pi IP address (currently set to 192.168.141.250)
- Check if MQTT broker is running on Raspberry Pi
- Ensure firewall allows MQTT traffic on port 1883

### 2. Message Not Received
- Check Flask app logs for MQTT connection status
- Verify topic names match between publisher and subscriber
- Use MQTT client tools like `mosquitto_pub` and `mosquitto_sub` for testing

### 3. Database Issues
- Database tables are auto-created on first run
- Check file permissions for `database.db`
- Use SQLite browser to inspect data

## Automatic Device Control

The Raspberry Pi code includes automatic control logic:
- **Fan**: Automatically runs for 10 seconds when humidity > 70%
- **Pump**: Automatically runs for 5 seconds when soil moisture < 60%

These actions will also publish device status messages to track when devices are activated.

## Future Enhancements

1. **Web Dashboard**: Create a real-time dashboard showing sensor data and device status
2. **Historical Charts**: Add graphs showing sensor trends over time
3. **Alerts**: Implement threshold-based alerts for critical sensor values
4. **Remote Control**: Enhance web interface for manual device control
5. **Data Export**: Add functionality to export sensor data to CSV/Excel
