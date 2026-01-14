"""MQTT-based Room Comfort Analysis dengan Rule Engine + LLM."""
import json
import time
import os
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

from models import SensorData, ComfortAnalysisResponse, Recommendation
from rule_engine import evaluate
from llm_service import LLMService

# Load environment variables
load_dotenv()

# MQTT Configuration from .env
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", None)
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", None)

# Multiple input topics from .env (comma-separated, supports wildcards like topic/#)
MQTT_TOPICS_INPUT = [topic.strip() for topic in os.getenv("MQTT_TOPIC_INPUT", "").split(",") if topic.strip()]
# Extract base topic names (remove /# wildcard) for data storage
MQTT_BASE_TOPICS = [topic.replace("/#", "").replace("/*", "") for topic in MQTT_TOPICS_INPUT]
MQTT_TOPIC_OUTPUT = os.getenv("MQTT_TOPIC_OUTPUT", "response_LLM")
FETCH_INTERVAL = int(os.getenv("FETCH_INTERVAL", 60))  # seconds
DATA_COLLECTION_TIME = int(os.getenv("DATA_COLLECTION_TIME", 5))  # seconds to wait for data

# Initialize LLM service (hanya untuk narasi)
llm_service = LLMService()

# Global persistent storage untuk data sensor (retain data antar fetch)
# Berguna untuk data event-based seperti entrance yang hanya kirim saat ada perubahan
persistent_data = {topic: None for topic in MQTT_BASE_TOPICS}


def analyze_comfort(sensor_data: SensorData) -> ComfortAnalysisResponse:
    """
    Analisis tingkat kenyamanan ruangan berdasarkan data sensor.
    
    Flow:
    1. Rule Engine menghitung score, status, dan AC control (DETERMINISTIK)
    2. LLM generate narasi/reason (HANYA PENJELASAN)
    """
    # Step 1: Rule Engine - Kalkulasi deterministik
    rule_result = evaluate(sensor_data)
    
    # Step 2: LLM - Generate narasi/reason saja
    reason = llm_service.generate_reason(sensor_data, rule_result)
    
    # Step 3: Build response
    response = ComfortAnalysisResponse(
        Comfort=rule_result.comfort,
        Recommendation=Recommendation(
            ac_control=rule_result.ac_control,
            reason=reason
        )
    )
    
    return response


def fetch_and_process():
    """Fetch data dari MQTT sekali, proses, dan publish response."""
    global persistent_data
    
    # Data storage untuk sesi ini
    collected_data = {topic: None for topic in MQTT_BASE_TOPICS}
    data_received = False
    
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            # Subscribe ke semua topics
            for topic in MQTT_TOPICS_INPUT:
                client.subscribe(topic)
    
    def on_message(client, userdata, msg):
        nonlocal collected_data, data_received
        try:
            payload = json.loads(msg.payload.decode())
            base_topic = msg.topic.split('/')[0]
            
            print(f"[MQTT] Received from {msg.topic} (base: {base_topic}): {payload}")
            
            if base_topic in collected_data:
                if collected_data[base_topic] is None:
                    collected_data[base_topic] = {}
                collected_data[base_topic].update(payload)
                data_received = True
            else:
                print(f"[MQTT] Warning: base_topic '{base_topic}' not in {list(collected_data.keys())}")
                
        except Exception as e:
            print(f"[MQTT] Error: {e}")
    
    # Setup MQTT Client
    client = mqtt.Client()
    
    if MQTT_USERNAME and MQTT_PASSWORD:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    
    client.on_connect = on_connect
    client.on_message = on_message
    
    try:
        # Connect dan collect data
        print(f"[Fetch] Connecting to {MQTT_BROKER}:{MQTT_PORT}...")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        
        # Start network loop in background
        client.loop_start()
        
        # Wait untuk collect data
        print(f"[Fetch] Collecting data for {DATA_COLLECTION_TIME} seconds...")
        time.sleep(DATA_COLLECTION_TIME)
        
        # Stop dan disconnect
        client.loop_stop()
        client.disconnect()
        
        # Update persistent_data dengan data baru yang diterima
        for topic, data in collected_data.items():
            if data is not None:
                if persistent_data[topic] is None:
                    persistent_data[topic] = {}
                persistent_data[topic].update(data)
                print(f"[Fetch] New data from {topic}: {data}")
        
        # Gabungkan semua data dari persistent storage
        combined_data = {}
        for topic, data in persistent_data.items():
            if data is not None:
                combined_data.update(data)
                print(f"[Fetch] Using {topic}: {data}")
        
        if not combined_data:
            print("[Fetch] No sensor data available yet")
            return
        
        # Convert to SensorData
        sensor_data = SensorData(
            hum=combined_data.get("hum", combined_data.get("humidity")),
            temp=combined_data.get("temp", combined_data.get("temperature")),
            noise=combined_data.get("noise", combined_data.get("noise_level", 40)),
            light_level=combined_data.get("light_level", combined_data.get("lux", 300)),
            occupancy=combined_data.get("occupancy", 1)
        )
        
        print(f"[Process] Combined sensor data: {sensor_data}")
        
        # Analyze comfort
        response = analyze_comfort(sensor_data)
        response_json = response.model_dump()
        
        # Publish response ke topic: response_LLM/device-1/data
        publish_topic = f"{MQTT_TOPIC_OUTPUT}/device-1/data"
        client.reconnect()
        result = client.publish(publish_topic, json.dumps(response_json, indent=2))
        client.disconnect()
        
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            print(f"[MQTT] Response published to '{publish_topic}':")
            print(json.dumps(response_json, indent=2))
        else:
            print(f"[MQTT] Failed to publish, error: {result.rc}")
            
    except Exception as e:
        print(f"[Fetch] Error: {e}")
        try:
            client.disconnect()
        except:
            pass


def main():
    """Main function - fetch data setiap interval."""
    print("=" * 60)
    print("Room Comfort Analysis - MQTT Service (Periodic Fetch)")
    print("=" * 60)
    print(f"Broker: {MQTT_BROKER}:{MQTT_PORT}")
    print(f"Input Topics: {', '.join(MQTT_TOPICS_INPUT)}")
    print(f"Output Topic: {MQTT_TOPIC_OUTPUT}")
    print(f"Fetch Interval: {FETCH_INTERVAL} seconds")
    print(f"Data Collection Time: {DATA_COLLECTION_TIME} seconds")
    print("=" * 60)
    
    try:
        while True:
            print(f"\n[Scheduler] Fetching data...")
            fetch_and_process()
            print(f"[Scheduler] Next fetch in {FETCH_INTERVAL} seconds...")
            time.sleep(FETCH_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n[Main] Shutting down...")


if __name__ == "__main__":
    main()
