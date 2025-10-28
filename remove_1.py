#!/usr/bin/env python3
"""
secure_delivery_sim.py

Single-file simulation of microservice interactions (Sender_MS, UI_MS, Controller_MS,
IDGen_MS, Storage_MS, Log_MS, Car_MS) with security features:
 - HMAC-signed messages (per-service shared secrets)
 - Timestamp + nonce replay protection window
 - Encrypted-at-rest fields stored in SQLite using Fernet (cryptography)
 - Separate databases: Database_1 (deliveries), Database_2 (ids), Database_3 (logs)
 - Input validation, acknowledgements, robust error handling
 - At the bottom: a run_simulation() executes the exact flow described by the user.

Requires: cryptography
pip install cryptography
"""
import sqlite3
import json
import time
import hmac
import hashlib
import secrets
import base64
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, Tuple
from cryptography.fernet import Fernet, InvalidToken

# ---------------------------
# Security utilities
# ---------------------------

def now_ts() -> int:
    return int(time.time())

def generate_secret_key() -> bytes:
    # HMAC key
    return secrets.token_bytes(32)

def generate_fernet_key() -> bytes:
    return Fernet.generate_key()

def hmac_sign(key: bytes, message: bytes) -> str:
    mac = hmac.new(key, message, hashlib.sha256).digest()
    return base64.b64encode(mac).decode()

def hmac_verify(key: bytes, message: bytes, signature_b64: str) -> bool:
    try:
        expected = base64.b64decode(signature_b64.encode())
    except Exception:
        return False
    return hmac.compare_digest(hmac.new(key, message, hashlib.sha256).digest(), expected)

# ---------------------------
# Message model (signed)
# ---------------------------

@dataclass
class Message:
    sender: str
    recipient: str
    payload: Dict[str, Any]
    ts: int
    nonce: str
    signature: Optional[str] = None  # filled after signing

    def to_wire(self) -> bytes:
        """Canonical serialization for signing."""
        core = {
            "sender": self.sender,
            "recipient": self.recipient,
            "payload": self.payload,
            "ts": self.ts,
            "nonce": self.nonce,
        }
        return json.dumps(core, sort_keys=True, separators=(',', ':')).encode()

    def sign_with(self, key: bytes):
        sig = hmac_sign(key, self.to_wire())
        self.signature = sig

    def verify_signature(self, key: bytes) -> bool:
        if not self.signature:
            return False
        return hmac_verify(key, self.to_wire(), self.signature)

# ---------------------------
# Base service
# ---------------------------

class Service:
    def __init__(self, name: str, hmac_key: bytes, fernet: Optional[Fernet] = None):
        self.name = name
        self.hmac_key = hmac_key
        self.fernet = fernet
        # simple replay protection store: {nonce: ts}
        self.seen_nonces: Dict[str, int] = {}
        # allow 60s window for messages to be considered fresh
        self.allowed_skew = 60

    def sign_message(self, msg: Message):
        if msg.sender != self.name:
            raise ValueError("Sender mismatch when signing")
        msg.sign_with(self.hmac_key)

    def verify_incoming(self, msg: Message, expected_sender_key: bytes) -> Tuple[bool, str]:
        # check signature
        if not msg.verify_signature(expected_sender_key):
            return False, "invalid signature"
        # check timestamp freshness
        if abs(now_ts() - msg.ts) > self.allowed_skew:
            return False, f"stale or future timestamp (ts={msg.ts})"
        # check nonce replay
        if msg.nonce in self.seen_nonces:
            return False, "replay detected (nonce already seen)"
        self.seen_nonces[msg.nonce] = msg.ts
        # keep nonce store small
        if len(self.seen_nonces) > 1000:
            # drop oldest
            oldest = min(self.seen_nonces, key=self.seen_nonces.get)
            del self.seen_nonces[oldest]
        return True, "ok"

    def encrypt(self, plaintext: bytes) -> bytes:
        if self.fernet is None:
            raise RuntimeError("No Fernet provided for encryption")
        return self.fernet.encrypt(plaintext)

    def decrypt(self, token: bytes) -> bytes:
        if self.fernet is None:
            raise RuntimeError("No Fernet provided for decryption")
        return self.fernet.decrypt(token)

# ---------------------------
# Storage (Database_1, Database_2, Database_3)
# ---------------------------

class StorageMS(Service):
    def __init__(self, name: str, hmac_key: bytes, fernet_key: bytes):
        super().__init__(name, hmac_key, Fernet(fernet_key))
        # Database_1: deliveries
        self.db1 = sqlite3.connect("database_1_deliveries.sqlite", check_same_thread=False)
        # Database_2: ids (parcel ids, car ids)
        self.db2 = sqlite3.connect("database_2_ids.sqlite", check_same_thread=False)
        # Database_3 is for logs but LogMS also writes there; Storage doesn't write logs directly (but may)
        self._init_dbs()

    def _init_dbs(self):
        c1 = self.db1.cursor()
        c1.execute("""
            CREATE TABLE IF NOT EXISTS deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                delivery_json BLOB NOT NULL,
                mac TEXT NOT NULL,
                ts INTEGER NOT NULL
            )
        """)
        self.db1.commit()
        c2 = self.db2.cursor()
        c2.execute("""
            CREATE TABLE IF NOT EXISTS ids (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_type TEXT NOT NULL,  -- 'parcel' or 'car'
                id_encrypted BLOB NOT NULL,
                mac TEXT NOT NULL,
                ts INTEGER NOT NULL
            )
        """)
        self.db2.commit()

    def store_id(self, id_type: str, id_value: str) -> Dict[str, Any]:
        """
        Encrypt and store an id (parcel or car) in Database_2.
        Returns ack data.
        """
        if id_type not in ("parcel", "car"):
            raise ValueError("invalid id_type")
        # validate id_value small
        if not isinstance(id_value, str) or len(id_value) > 256:
            raise ValueError("invalid id value")
        b = id_value.encode()
        token = self.encrypt(b)
        mac = hmac_sign(self.hmac_key, token)  # MAC for integrity at rest
        ts = now_ts()
        cur = self.db2.cursor()
        cur.execute("INSERT INTO ids (id_type, id_encrypted, mac, ts) VALUES (?, ?, ?, ?)",
                    (id_type, token, mac, ts))
        self.db2.commit()
        return {"status": "ok", "stored_ts": ts, "id_type": id_type}

    def retrieve_latest_id(self, id_type: str) -> Optional[str]:
        cur = self.db2.cursor()
        cur.execute("SELECT id_encrypted, mac FROM ids WHERE id_type=? ORDER BY id DESC LIMIT 1", (id_type,))
        r = cur.fetchone()
        if not r:
            return None
        token, mac = r
        # verify mac
        if not hmac_verify(self.hmac_key, token, mac):
            raise RuntimeError("Integrity check failed for stored id")
        try:
            plaintext = self.decrypt(token)
        except InvalidToken:
            raise RuntimeError("Decryption failed (bad key or corrupted token)")
        return plaintext.decode()

    def store_delivery(self, delivery_obj: Dict[str, Any]) -> Dict[str, Any]:
        # validate minimal fields
        if "parcel_id" not in delivery_obj or "car_id" not in delivery_obj:
            raise ValueError("delivery must include parcel_id and car_id")
        raw = json.dumps(delivery_obj, sort_keys=True).encode()
        token = self.encrypt(raw)
        mac = hmac_sign(self.hmac_key, token)
        ts = now_ts()
        cur = self.db1.cursor()
        cur.execute("INSERT INTO deliveries (delivery_json, mac, ts) VALUES (?, ?, ?)",
                    (token, mac, ts))
        self.db1.commit()
        return {"status": "ok", "stored_ts": ts}

    def store_delivery_update(self, delivery_update: Dict[str, Any]) -> Dict[str, Any]:
        # For simplicity, just append to deliveries as a new record (audit-style)
        return self.store_delivery(delivery_update)

# ---------------------------
# LogMS (stores logs in Database_3)
# ---------------------------

class LogMS(Service):
    def __init__(self, name: str, hmac_key: bytes, fernet_key: bytes):
        super().__init__(name, hmac_key, Fernet(fernet_key))
        self.db3 = sqlite3.connect("database_3_logs.sqlite", check_same_thread=False)
        self._init_db()

    def _init_db(self):
        c = self.db3.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT NOT NULL,
                action TEXT NOT NULL,
                details_encrypted BLOB NOT NULL,
                mac TEXT NOT NULL,
                ts INTEGER NOT NULL
            )
        """)
        self.db3.commit()

    def store_log(self, service: str, action: str, details: Dict[str, Any]) -> Dict[str, Any]:
        payload = {"service": service, "action": action, "details": details}
        raw = json.dumps(payload, sort_keys=True).encode()
        token = self.encrypt(raw)
        mac = hmac_sign(self.hmac_key, token)
        ts = now_ts()
        cur = self.db3.cursor()
        cur.execute("INSERT INTO logs (service, action, details_encrypted, mac, ts) VALUES (?, ?, ?, ?, ?)",
                    (service, action, token, mac, ts))
        self.db3.commit()
        return {"status": "ok", "ts": ts}

# ---------------------------
# IDGenMS
# ---------------------------

class IDGenMS(Service):
    def __init__(self, name: str, hmac_key: bytes):
        # IDGen doesn't need fernet itself (storage will keep encrypted), but we'll keep None
        super().__init__(name, hmac_key)

    def generate_parcel_id(self) -> str:
        # cryptographically secure unique id
        return "P-" + secrets.token_urlsafe(12)

# ---------------------------
# CarMS (simulates car checks and acknowledges)
# ---------------------------

class CarMS(Service):
    def __init__(self, name: str, hmac_key: bytes):
        super().__init__(name, hmac_key)
        # maintain a simple registry of car IDs that "exist"
        self.registered_cars = set()

    def register_car(self, car_id: str):
        self.registered_cars.add(car_id)

    def check_car(self, car_id: str) -> bool:
        return car_id in self.registered_cars

# ---------------------------
# ControllerMS (orchestrator)
# ---------------------------

class ControllerMS(Service):
    def __init__(self, name: str, hmac_key: bytes, services_keys: Dict[str, bytes], storage: StorageMS, logms: LogMS):
        super().__init__(name, hmac_key)
        # map of other services' hmac keys for signature verification
        self.services_keys = services_keys
        self.storage = storage
        self.logms = logms

    def request_parcel_id(self, idgen: IDGenMS) -> str:
        # build request
        msg = Message(sender=self.name, recipient=idgen.name, payload={"action": "request_parcel_id"}, ts=now_ts(), nonce=secrets.token_hex(8))
        self.sign_message(msg)
        # idgen verifies
        ok, reason = idgen.verify_incoming(msg, self.hmac_key)
        if not ok:
            raise RuntimeError(f"IDGen rejected controller request: {reason}")
        # idgen generates id
        parcel_id = idgen.generate_parcel_id()
        # idgen sends back parcel id message (signed by idgen)
        reply = Message(sender=idgen.name, recipient=self.name, payload={"parcel_id": parcel_id}, ts=now_ts(), nonce=secrets.token_hex(8))
        reply.sign_with(idgen.hmac_key)
        # controller verifies reply
        ok, reason = self.verify_incoming(reply, idgen.hmac_key)
        if not ok:
            raise RuntimeError(f"Invalid reply from IDGen: {reason}")
        # persist to Storage_MS
        # build storage message
        store_msg = Message(sender=self.name, recipient=self.storage.name, payload={"action": "store_parcel_id", "parcel_id": parcel_id}, ts=now_ts(), nonce=secrets.token_hex(8))
        self.sign_message(store_msg)
        ok, reason = self.storage.verify_incoming(store_msg, self.hmac_key)
        if not ok:
            raise RuntimeError(f"Storage rejected controller store request: {reason}")
        ack = self.storage.store_id("parcel", parcel_id)
        # storage acknowledges via ack message back to IDGen (as per flow): Storage_MS acknowledges IDGen_MS.
        ack_msg = Message(sender=self.storage.name, recipient=idgen.name, payload={"ack": ack}, ts=now_ts(), nonce=secrets.token_hex(8))
        ack_msg.sign_with(self.storage.hmac_key)
        ok, reason = idgen.verify_incoming(ack_msg, self.storage.hmac_key)
        if not ok:
            raise RuntimeError("IDGen rejected storage ack")
        # IDGen acknowledges Controller_MS
        ack2 = Message(sender=idgen.name, recipient=self.name, payload={"ack": "parcel_id_received"}, ts=now_ts(), nonce=secrets.token_hex(8))
        ack2.sign_with(idgen.hmac_key)
        ok, reason = self.verify_incoming(ack2, idgen.hmac_key)
        if not ok:
            raise RuntimeError("Controller failed to verify IDGen ACK")
        # log
        self.logms.store_log(self.name, "parcel_id_generated", {"parcel_id": parcel_id})
        return parcel_id

    def request_car_id_and_check(self, carms: CarMS) -> str:
        # Controller requests a car id (for the sake of sim, controller asks carms to return a car id?)
        # We'll simulate CarMS being asked to provide its id, but spec: Controller_MS requests car ID from Car_MS; Car_MS checks car ID; Car_MS shares car ID with Storage_MS.
        msg = Message(sender=self.name, recipient=carms.name, payload={"action": "request_car_id"}, ts=now_ts(), nonce=secrets.token_hex(8))
        self.sign_message(msg)
        ok, reason = carms.verify_incoming(msg, self.hmac_key)
        if not ok:
            raise RuntimeError("CarMS rejected request")
        # CarMS selects a registered car (if none, create one)
        if not carms.registered_cars:
            # create one car id and register it
            car_id = "C-" + secrets.token_urlsafe(8)
            carms.register_car(car_id)
        else:
            car_id = next(iter(carms.registered_cars))
        # CarMS checks car id
        check_ok = carms.check_car(car_id)
        if not check_ok:
            raise RuntimeError("CarMS reports car invalid")
        # CarMS shares car id with Storage_MS
        msg_cs = Message(sender=carms.name, recipient=self.storage.name, payload={"action": "share_car_id", "car_id": car_id}, ts=now_ts(), nonce=secrets.token_hex(8))
        msg_cs.sign_with(carms.hmac_key)
        ok, reason = self.storage.verify_incoming(msg_cs, carms.hmac_key)
        if not ok:
            raise RuntimeError("Storage rejected CarMS share")
        ack = self.storage.store_id("car", car_id)
        # Storage acknowledges Car_MS
        ack_msg = Message(sender=self.storage.name, recipient=carms.name, payload={"ack": ack}, ts=now_ts(), nonce=secrets.token_hex(8))
        ack_msg.sign_with(self.storage.hmac_key)
        ok, reason = carms.verify_incoming(ack_msg, self.storage.hmac_key)
        if not ok:
            raise RuntimeError("CarMS rejected storage ack")
        # Car_MS acknowledges Controller_MS
        ack2 = Message(sender=carms.name, recipient=self.name, payload={"ack": "car_stored"}, ts=now_ts(), nonce=secrets.token_hex(8))
        ack2.sign_with(carms.hmac_key)
        ok, reason = self.verify_incoming(ack2, carms.hmac_key)
        if not ok:
            raise RuntimeError("Controller rejected CarMS ack")
        # log
        self.logms.store_log(self.name, "car_id_recorded", {"car_id": car_id})
        return car_id

    def assign_delivery(self, parcel_id: str, car_id: str) -> Dict[str, Any]:
        # Controller requests parcel and car from storage (as per flow)
        # Here we call storage.retrieve_latest_id
        p = self.storage.retrieve_latest_id("parcel")
        if p is None or p != parcel_id:
            raise RuntimeError("Parcel ID mismatch or none in storage")
        c = self.storage.retrieve_latest_id("car")
        if c is None or c != car_id:
            raise RuntimeError("Car ID mismatch or none in storage")
        # assign delivery
        delivery = {
            "parcel_id": parcel_id,
            "car_id": car_id,
            "assigned_at": now_ts(),
            "status": "assigned"
        }
        store_ack = self.storage.store_delivery(delivery)
        # storage acknowledges controller
        self.logms.store_log(self.name, "delivery_assigned", {"parcel_id": parcel_id, "car_id": car_id, "store_ack": store_ack})
        # Storage_MS acknowledges Controller_MS (we simulate return ack)
        return {"status": "ok", "delivery": delivery}

    def notify_car(self, carms: CarMS, delivery: Dict[str,Any]) -> None:
        msg = Message(sender=self.name, recipient=carms.name, payload={"action": "notify_delivery", "delivery": delivery}, ts=now_ts(), nonce=secrets.token_hex(8))
        self.sign_message(msg)
        ok, reason = carms.verify_incoming(msg, self.hmac_key)
        if not ok:
            raise RuntimeError("CarMS rejected notification")
        # CarMS acknowledges Controller_MS
        ack = Message(sender=carms.name, recipient=self.name, payload={"ack": "notified"}, ts=now_ts(), nonce=secrets.token_hex(8))
        ack.sign_with(carms.hmac_key)
        ok, reason = self.verify_incoming(ack, carms.hmac_key)
        if not ok:
            raise RuntimeError("Controller failed to verify car ack")
        self.logms.store_log(self.name, "car_notified", {"car_id": delivery["car_id"], "parcel_id": delivery["parcel_id"]})

    def notify_ui_and_sender(self, ui_ms: 'UIMS', sender_ms: 'SenderMS', delivery: Dict[str,Any]):
        # Notify UI
        msg_ui = Message(sender=self.name, recipient=ui_ms.name, payload={"action": "notify_sender", "delivery": delivery}, ts=now_ts(), nonce=secrets.token_hex(8))
        self.sign_message(msg_ui)
        ok, reason = ui_ms.verify_incoming(msg_ui, self.hmac_key)
        if not ok:
            raise RuntimeError("UI rejected notification")
        # UI notifies sender
        ui_ms.notify_sender(sender_ms, delivery)
        # UI acknowledges Controller_MS
        ack = Message(sender=ui_ms.name, recipient=self.name, payload={"ack": "ui_ack"}, ts=now_ts(), nonce=secrets.token_hex(8))
        ack.sign_with(ui_ms.hmac_key)
        ok, reason = self.verify_incoming(ack, ui_ms.hmac_key)
        if not ok:
            raise RuntimeError("Controller failed to verify UI ack")
        self.logms.store_log(self.name, "ui_notified", {"parcel_id": delivery["parcel_id"]})

    def handle_car_update(self, carms: CarMS, update: Dict[str,Any], ui_ms: 'UIMS', sender_ms: 'SenderMS'):
        # Car requests delivery update from Controller
        msg = Message(sender=carms.name, recipient=self.name, payload={"action": "request_update"}, ts=now_ts(), nonce=secrets.token_hex(8))
        msg.sign_with(carms.hmac_key)
        ok, reason = self.verify_incoming(msg, carms.hmac_key)
        if not ok:
            raise RuntimeError("Controller rejected car request_update")
        # Controller acknowledges Car_MS
        ack = Message(sender=self.name, recipient=carms.name, payload={"ack": "update_ack"}, ts=now_ts(), nonce=secrets.token_hex(8))
        self.sign_message(ack)
        ok, reason = carms.verify_incoming(ack, self.hmac_key)
        if not ok:
            raise RuntimeError("CarMS failed to verify controller ack")
        # Controller shares delivery update with Storage_MS
        store_msg = Message(sender=self.name, recipient=self.storage.name, payload={"action": "store_delivery_update", "update": update}, ts=now_ts(), nonce=secrets.token_hex(8))
        self.sign_message(store_msg)
        ok, reason = self.storage.verify_incoming(store_msg, self.hmac_key)
        if not ok:
            raise RuntimeError("Storage rejected delivery update")
        self.storage.store_delivery_update(update)
        # storage acknowledges controller
        self.logms.store_log(self.name, "delivery_update_stored", {"update": update})
        # Controller notifies UI then UI notifies Sender
        self.notify_ui_and_sender(ui_ms, sender_ms, update)

# ---------------------------
# UI and Sender
# ---------------------------

class UIMS(Service):
    def __init__(self, name: str, hmac_key: bytes):
        super().__init__(name, hmac_key)

    def forward_request_to_controller(self, controller: ControllerMS, request_payload: Dict[str,Any]):
        msg = Message(sender=self.name, recipient=controller.name, payload=request_payload, ts=now_ts(), nonce=secrets.token_hex(8))
        self.sign_message(msg)
        ok, reason = controller.verify_incoming(msg, self.hmac_key)
        if not ok:
            raise RuntimeError("Controller rejected UI request")
        # the controller will handle the request, for simulation we just return ack
        return {"status": "forwarded"}

    def notify_sender(self, sender_ms: 'SenderMS', delivery: Dict[str,Any]):
        msg = Message(sender=self.name, recipient=sender_ms.name, payload={"action": "delivery_notification", "delivery": delivery}, ts=now_ts(), nonce=secrets.token_hex(8))
        self.sign_message(msg)
        ok, reason = sender_ms.verify_incoming(msg, self.hmac_key)
        if not ok:
            raise RuntimeError("Sender rejected UI notification")
        # Sender acknowledges UI_MS
        ack = Message(sender=sender_ms.name, recipient=self.name, payload={"ack": "sender_received"}, ts=now_ts(), nonce=secrets.token_hex(8))
        ack.sign_with(sender_ms.hmac_key)
        ok, reason = self.verify_incoming(ack, sender_ms.hmac_key)
        if not ok:
            raise RuntimeError("UI failed to verify sender ack")
        # UI acknowledges Controller_MS (this is done in Controller flow by sending ack back; when called from Controller, Controller builds ack)
        return {"status": "sender_notified"}

class SenderMS(Service):
    def __init__(self, name: str, hmac_key: bytes):
        super().__init__(name, hmac_key)

# ---------------------------
# Simulation wiring + run
# ---------------------------

def run_simulation():
    # generate keys for services (in a realistic env these are stored in KMS)
    keys = {}
    services = ["Sender_MS", "UI_MS", "Controller_MS", "IDGen_MS", "Storage_MS", "Log_MS", "Car_MS"]
    for s in services:
        keys[s] = generate_secret_key()
    # fernet keys for storage and logs (encryption at rest)
    fernet_storage_key = generate_fernet_key()
    fernet_log_key = generate_fernet_key()

    # instantiate services
    storage = StorageMS("Storage_MS", keys["Storage_MS"], fernet_storage_key)
    logms = LogMS("Log_MS", keys["Log_MS"], fernet_log_key)
    idgen = IDGenMS("IDGen_MS", keys["IDGen_MS"])
    carms = CarMS("Car_MS", keys["Car_MS"])
    controller = ControllerMS("Controller_MS", keys["Controller_MS"], services_keys={k:v for k,v in keys.items()}, storage=storage, logms=logms)
    ui = UIMS("UI_MS", keys["UI_MS"])
    sender = SenderMS("Sender_MS", keys["Sender_MS"])

    # --- Start sequence following the spec exactly (with ack and logs) ---

    print("1) Sender_MS requests delivery from UI_MS.")
    # Sender -> UI
    msg_s_ui = Message(sender=sender.name, recipient=ui.name, payload={"action":"request_delivery"}, ts=now_ts(), nonce=secrets.token_hex(8))
    msg_s_ui.sign_with(sender.hmac_key)
    ok, reason = ui.verify_incoming(msg_s_ui, sender.hmac_key)
    assert ok, reason

    print("2) UI_MS forwards 'request delivery' to Controller_MS.")
    ui.forward_request_to_controller(controller, {"action":"request_delivery"})

    print("3) Controller_MS requests parcel ID from IDGen_MS.")
    parcel_id = controller.request_parcel_id(idgen)
    print(f"   parcel_id generated: {parcel_id}")

    print("4..11) Storage acknowledged IDGen, IDGen ack Controller, Controller logs to Log_MS.")
    # Already performed within request_parcel_id which logged

    print("12) Controller_MS requests car ID from Car_MS.")
    car_id = controller.request_car_id_and_check(carms)
    print(f"   car_id: {car_id}")

    print("13..20) Car stored id in Storage_MS and ack chain logged.")
    # Done within request_car_id_and_check

    print("21) Controller_MS requests parcel ID from Storage_MS.")
    stored_parcel = storage.retrieve_latest_id("parcel")
    print(f"   retrieved parcel from storage: {stored_parcel}")

    print("22) Controller_MS requests car ID from Storage_MS.")
    stored_car = storage.retrieve_latest_id("car")
    print(f"   retrieved car from storage: {stored_car}")

    print("23..27) Controller_MS assigns delivery and stores it in Database_1.")
    assign_result = controller.assign_delivery(parcel_id, car_id)
    delivery = assign_result["delivery"]
    print("   delivery assigned and stored.")

    print("28..36) Controller notifies Car_MS, Car_MS ack, controller logs, notifies UI_MS, UI_MS notifies Sender_MS, ack chain.")
    controller.notify_car(carms, delivery)
    controller.notify_ui_and_sender(ui, sender, delivery)

    print("37..44) Car_MS requests delivery update from Controller_MS.")
    # Simulate a delivery update
    update = {"parcel_id": parcel_id, "car_id": car_id, "status": "in_transit", "ts": now_ts()}
    controller.handle_car_update(carms, update, ui, sender)

    print("Simulation complete. Now show stored DB counts and some sample logs (decrypted).")

    # Print some DB summaries
    # Database_1 deliveries
    c1 = storage.db1.cursor()
    c1.execute("SELECT id, delivery_json, mac, ts FROM deliveries ORDER BY id")
    all_deliveries = c1.fetchall()
    print(f"\nDatabase_1 (deliveries) count: {len(all_deliveries)}")
    for did, token, mac, ts in all_deliveries:
        try:
            if not hmac_verify(storage.hmac_key, token, mac):
                print(f"  delivery {did}: MAC FAIL")
                continue
            plain = storage.decrypt(token)
            print(f"  delivery {did} (ts={ts}): {plain.decode()}")
        except Exception as e:
            print(f"  delivery {did}: error decrypting - {e}")

    # Database_2 ids
    c2 = storage.db2.cursor()
    c2.execute("SELECT id, id_type, id_encrypted, mac, ts FROM ids ORDER BY id")
    all_ids = c2.fetchall()
    print(f"\nDatabase_2 (ids) count: {len(all_ids)}")
    for iid, id_type, token, mac, ts in all_ids:
        try:
            if not hmac_verify(storage.hmac_key, token, mac):
                print(f"  id {iid}: MAC FAIL")
                continue
            plain = storage.decrypt(token)
            print(f"  id {iid} ({id_type}, ts={ts}): {plain.decode()}")
        except Exception as e:
            print(f"  id {iid}: error decrypting - {e}")

    # Database_3 logs (LogMS)
    c3 = logms.db3.cursor()
    c3.execute("SELECT id, service, action, details_encrypted, mac, ts FROM logs ORDER BY id")
    all_logs = c3.fetchall()
    print(f"\nDatabase_3 (logs) count: {len(all_logs)}")
    for lid, service, action, token, mac, ts in all_logs:
        try:
            if not hmac_verify(logms.hmac_key, token, mac):
                print(f"  log {lid}: MAC FAIL")
                continue
            plain = logms.decrypt(token)
            print(f"  log {lid} (service={service} action={action} ts={ts}): {plain.decode()}")
        except Exception as e:
            print(f"  log {lid}: error decrypting - {e}")

if __name__ == "__main__":
    print("Starting secure delivery microservices simulation...\n")
    run_simulation()
