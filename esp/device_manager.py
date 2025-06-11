from datetime import datetime
import threading
from typing import Dict, Optional

class DeviceStateManager:
    def __init__(self):
        self._states: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        
    def set_device_state(self, device_id: str, state: str, 
                        controller: str = "raspberry"):
        with self._lock:
            self._states[device_id] = {
                "state": state,
                "controller": controller,
                "timestamp": datetime.now()
            }
            
    def get_device_state(self, device_id: str) -> Optional[Dict]:
        with self._lock:
            return self._states.get(device_id)
            
    def is_device_free(self, device_id: str) -> bool:
        with self._lock:
            if device_id not in self._states:
                return True
            state = self._states[device_id]
            if (state["controller"] == "raspberry" and 
                state["state"] == "OPEN"):
                return False
            return True
