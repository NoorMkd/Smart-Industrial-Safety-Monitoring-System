from machine import Pin, ADC
import utime
import dht
import urequests
import json
import network

# --- Configuration WiFi ---
WIFI_SSID = ""      # ← CHANGEZ ICI
WIFI_PASSWORD = ""  # ← CHANGEZ ICI

# --- Configuration Dashboard AWS ---
DASHBOARD_URL = "http.../api/data"

# --- Configuration Firebase ---
FIREBASE_URL = "https://.....firebaseio.com/"  # ← CHANGEZ ICI
FIREBASE_SECRET = ""  # ← CHANGEZ ICI

# --- Capteurs ---
dht11 = dht.DHT11(Pin(22))
mq7 = ADC(27)               # MQ-7 analogique
sound = ADC(28)             # Sound sensor analogique
tilt = Pin(21, Pin.IN, Pin.PULL_UP)     # KY-017 vibration
button = Pin(26, Pin.IN, Pin.PULL_UP)   # KY-018 étincelle
trig = Pin(18, Pin.OUT)                  # HC-SR04 trig
echo = Pin(19, Pin.IN)                   # HC-SR04 echo

# --- Actionneurs ---
led_red = Pin(10, Pin.OUT)    # LED1 rouge
led_green = Pin(11, Pin.OUT)  # LED2 verte
relay = Pin(12, Pin.OUT)
buzzer = Pin(13, Pin.OUT)

# --- Variables d'état ---
led_red_state = False
buzzer_state = False
motor_state = True  # Moteur ON par défaut

# --- Seuils ---
SOUND_THRESHOLD = 30000  # Seuil pour le capteur de son
GAS_THRESHOLD = 30000    # Seuil pour le capteur de gaz

# --- Fonctions ---
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    if not wlan.isconnected():
        print('Connexion au WiFi...')
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        
        timeout = 0
        while not wlan.isconnected():
            utime.sleep(1)
            timeout += 1
            print('.', end='')
            if timeout > 20:
                print('\n Timeout connexion WiFi')
                return False
                
    print('\n WiFi connecté:', wlan.ifconfig())
    return True

def distance_cm():
    trig.low()
    utime.sleep_us(2)
    trig.high()
    utime.sleep_us(10)
    trig.low()
    
    timeout = utime.ticks_us() + 30000  # Timeout de 30ms
    
    # Attendre que echo passe à HIGH
    signaloff = utime.ticks_us()
    while echo.value() == 0:
        if utime.ticks_us() > timeout:
            return 1000  # Retourne une grande distance en cas d'erreur
        signaloff = utime.ticks_us()
    
    # Attendre que echo passe à LOW
    signalon = utime.ticks_us()
    while echo.value() == 1:
        if utime.ticks_us() > timeout:
            return 1000  # Retourne une grande distance en cas d'erreur
        signalon = utime.ticks_us()
    
    timepassed = signalon - signaloff
    distance = (timepassed * 0.0343) / 2
    
    # Limiter la distance à 500cm maximum
    if distance > 500:
        return 500
    return distance

def send_to_dashboard():
    try:
        # Lecture distance
        dist = distance_cm()
        
        # Préparer les données pour le dashboard AWS
        data = {
            'temperature': temp if temp is not None else 0,
            'humidity': hum if hum is not None else 0,
            'gas': co_level,
            'sound': sound_level,
            'vibration': tilt_detected,
            'spark': spark_detected,
            'distance': dist,
            'motor_state': motor_state,
            'system_ok': not (tilt_detected or spark_detected or co_level > GAS_THRESHOLD or sound_detected)
        }
        
        # Envoyer au dashboard AWS
        headers = {'Content-Type': 'application/json'}
        response = urequests.post(DASHBOARD_URL, json=data, headers=headers)
        response.close()
        print(" Données envoyées au dashboard AWS")
        
    except Exception as e:
        print("Erreur envoi dashboard:", e)

def send_to_firebase():
    try:
        # Lecture distance (déjà fait pour dashboard, mais on refait pour être sûr)
        dist = distance_cm()
        
        # Préparer les données avec timestamp pour Firebase
        timestamp = utime.time()
        data = {
            'timestamp': timestamp,
            'sensors': {
                'temperature': temp if temp is not None else 0,
                'humidity': hum if hum is not None else 0,
                'gas': co_level,
                'sound': sound_level,
                'vibration': tilt_detected,
                'spark': spark_detected,
                'distance': dist
            },
            'actuators': {
                'led_red': led_red_state,
                'led_green': not led_red_state,  # Verte est l'inverse de rouge
                'buzzer': buzzer_state,
                'motor': motor_state
            },
            'alerts': {
                'sound_alert': sound_detected,
                'gas_alert': co_level > GAS_THRESHOLD,
                'vibration_alert': tilt_detected,
                'spark_alert': spark_detected,
                'system_ok': not (tilt_detected or spark_detected or co_level > GAS_THRESHOLD or sound_detected)
            }
        }
        
        # URL pour Firebase avec le secret d'authentification
        url = f"{FIREBASE_URL}/sensor_data/{timestamp}.json?auth={FIREBASE_SECRET}"
        
        # Envoyer à Firebase
        headers = {'Content-Type': 'application/json'}
        response = urequests.put(url, json=data, headers=headers)
        
        if response.status_code == 200:
            print("Données envoyées à Firebase")
        else:
            print(f" Erreur Firebase: {response.status_code}")
        
        response.close()
        
    except Exception as e:
        print(" Erreur envoi Firebase:", e)

def send_data_to_both_platforms():
    """Envoie les données aux deux plateformes"""
    send_to_dashboard()   # Envoi au dashboard AWS
    send_to_firebase()    # Envoi à Firebase

# --- Initialisation ---
print("Démarrage du système de sécurité industrielle...")

# Connexion WiFi
if connect_wifi():
    print("Envoi des données vers Dashboard AWS et Firebase")
else:
    print("⚠ Mode hors ligne - Pas d'envoi aux plateformes")

# Initialisation actionneurs
led_green.value(1)  # LED verte ON au démarrage
led_red.value(0)    # LED rouge OFF
buzzer.value(0)     # Buzzer OFF
relay.value(1)      # Moteur ON

# --- Variables pour timing envoi données ---
last_send_time = 0
send_interval = 5000  # Envoyer toutes les 5 secondes

# --- Boucle principale ---
while True:
    current_time = utime.ticks_ms()
    
    # --- Lire DHT11 ---
    try:
        dht11.measure()
        temp = dht11.temperature()
        hum = dht11.humidity()
    except:
        temp = hum = None
        print("Erreur DHT11")

    # --- Lire capteurs analogiques ---
    co_level = mq7.read_u16()
    sound_level = sound.read_u16()

    # --- Lire capteurs digitaux ---
    tilt_detected = tilt.value() == 0
    spark_detected = button.value() == 0
    
    # --- Détection son ---
    sound_detected = sound_level > SOUND_THRESHOLD

    # --- Scénario 1 : DHT11 + Gaz + Sound → LED rouge, LED verte OFF ---
    if (temp is not None and hum is not None) and (co_level > GAS_THRESHOLD or sound_detected):
        led_red.value(1)      # LED rouge ON
        led_green.value(0)    # LED verte OFF
        buzzer.value(0)       # Buzzer OFF pour ce scénario
        led_red_state = True
        buzzer_state = False
        motor_state = True
        print("Scénario 1 activé: DHT11 + Gaz + Sound")

    # --- Scénario 2 : Étincelle + Vibration + Sound → LED rouge + Buzzer ON ---
    elif spark_detected or tilt_detected or sound_detected:
        led_red.value(1)      # LED rouge ON
        led_green.value(0)    # LED verte OFF
        buzzer.value(1)       # Buzzer ON
        led_red_state = True
        buzzer_state = True
        motor_state = True
        print("Scénario 2 activé: Étincelle OU Vibration OU Sound")

    # --- État normal : LED verte ON (quand PAS de vibration ET PAS d'étincelle) ---
    elif not tilt_detected and not spark_detected:
        led_red.value(0)      # LED rouge OFF
        led_green.value(1)    # LED verte ON
        buzzer.value(0)       # Buzzer OFF
        led_red_state = False
        buzzer_state = False
        relay.value(1)        # Moteur ON
        motor_state = True
        print("État normal: Pas de vibration ni d'étincelle")

    # --- Scénario 3 : Si LED rouge + Buzzer ON et ultrason détecte quelqu'un de proche → Relay OFF (moteur OFF) ---
    if led_red_state and buzzer_state:
        dist = distance_cm()
        print(f"Distance ultrason: {dist} cm")
        
        if dist < 50:  # Si quelqu'un à moins de 50cm
            relay.value(0)  # Moteur OFF
            motor_state = False
            print("Personne détectée près de la machine - Moteur arrêté!")
        else:
            relay.value(1)  # Moteur ON
            motor_state = True

    # --- Envoi des données aux deux plateformes (seulement si WiFi connecté) ---
    if current_time - last_send_time >= send_interval:
        send_data_to_both_platforms()  # Envoi aux deux plateformes
        last_send_time = current_time

    # --- Affichage debug ---
    print(f"Temp: {temp}°C, Hum: {hum}%, CO: {co_level}, Sound: {sound_level}")
    print(f"Sound détecté: {sound_detected}, Vibration: {tilt_detected}, Spark: {spark_detected}")
    print(f"LED Rouge: {led_red_state}, Buzzer: {buzzer_state}, Moteur: {motor_state}")
    print("---")
    
    utime.sleep(1)
