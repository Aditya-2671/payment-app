from fastapi import FastAPI
app = FastAPI()
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {"status": "running"}

import qrcode
import io
import hashlib
import hmac
import time
import sqlite3
import numpy as np
from sklearn.ensemble import IsolationForest
from fastapi.responses import StreamingResponse

SECRET_KEY = "replace-this-with-a-long-random-secret"

def init_db():
    conn = sqlite3.connect("payments.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id TEXT,
            amount REAL,
            payment_id TEXT,
            order_id TEXT,
            status TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT UNIQUE,
            wallet_balance REAL DEFAULT 10000.0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()
import razorpay

RAZORPAY_KEY_ID = "rzp_test_Tmu9HTCuMPlXYz"
RAZORPAY_KEY_SECRET = "XzBDqFxkNyWasGIDKKN7vhzU"

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

def sign_payload(merchant_id: str, amount: float, timestamp: int) -> str:
    message = f"{merchant_id}|{amount}|{timestamp}"
    return hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()

def check_fraud(user_id: int, amount: float, merchant_id: str) -> dict:
    conn = sqlite3.connect("payments.db")
    cursor = conn.cursor()

    cursor.execute(
        "SELECT amount FROM transactions WHERE status = 'success' ORDER BY created_at DESC LIMIT 20"
    )
    past_amounts = [row[0] for row in cursor.fetchall()]

    cursor.execute(
        "SELECT COUNT(*) FROM transactions WHERE merchant_id = ? AND status = 'success'",
        (merchant_id,)
    )
    merchant_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM transactions")
    recent_count = cursor.fetchone()[0]

    conn.close()

    reasons = []
    risk_score = 0

    if merchant_count == 0 and amount > 1000:
        reasons.append("First-time payment to this merchant with a high amount")
        risk_score += 30

    if recent_count >= 1:
        reasons.append("Multiple transactions in a short time window")
        risk_score += 40

    if len(past_amounts) >= 5:
        X = np.array(past_amounts).reshape(-1, 1)
        model = IsolationForest(contamination=0.2, random_state=42)
        model.fit(X)
        prediction = model.predict([[amount]])[0]
        if prediction == -1:
            reasons.append("Amount is statistically unusual compared to your past spending")
            risk_score += 30

    if amount > 10000:
        reasons.append("Very high transaction amount")
        risk_score += 20

    is_suspicious = risk_score >= 30

    # DEBUG PRINT
    print(f"DEBUG: merchant_count={merchant_count}, recent_count={recent_count}, risk_score={risk_score}, is_suspicious={is_suspicious}")

    return {
        "is_suspicious": is_suspicious,
        "risk_score": risk_score,
        "reasons": reasons
    }
@app.get("/generate-qr")
def generate_qr(merchant_id: str, amount: float):
    timestamp = int(time.time())
    signature = sign_payload(merchant_id, amount, timestamp)

    payload = f"{merchant_id}|{amount}|{timestamp}|{signature}"
    print(payload)  # For debugging purposes; remove in production
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return StreamingResponse(buf, media_type="image/png")

from fastapi import HTTPException

@app.get("/verify-qr")
def verify_qr(payload: str):
    try:
        merchant_id, amount_str, timestamp_str, signature = payload.split("|")
        amount = float(amount_str)
        timestamp = int(timestamp_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Malformed QR payload")

    expected_signature = sign_payload(merchant_id, amount, timestamp)

    if not hmac.compare_digest(expected_signature, signature):
        return {"valid": False, "reason": "Signature mismatch — possible fake/tampered QR"}

    # Optional: reject QR codes older than 5 minutes (replay protection)
    current_time = int(time.time())
    if current_time - timestamp > 1800:
        return {"valid": False, "reason": "QR expired"}

    return {
        "valid": True,
        "merchant_id": merchant_id,
        "amount": amount
    }

@app.get("/create-payment")
def create_payment(payload: str, user_id: int):
    verification = verify_qr(payload)
    if not verification["valid"]:
        raise HTTPException(status_code=400, detail=verification["reason"])

    amount = verification["amount"]
    merchant_id = verification["merchant_id"]

    # Check wallet balance
    conn = sqlite3.connect("payments.db")
    cursor = conn.cursor()
    cursor.execute("SELECT wallet_balance FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    if row[0] < amount:
        raise HTTPException(status_code=400, detail="Insufficient wallet balance")

    # Fraud check
    fraud_result = check_fraud(user_id, amount, merchant_id)
    if fraud_result["is_suspicious"]:
        return {
            "status": "flagged",
            "risk_score": fraud_result["risk_score"],
            "reasons": fraud_result["reasons"],
            "message": "This transaction looks suspicious. Proceed with caution or cancel."
        }

    amount_paise = int(amount * 100)

    order = razorpay_client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "payment_capture": 1
    })

    return {
        "order_id": order["id"],
        "amount": amount,
        "merchant_id": merchant_id,
        "razorpay_key": RAZORPAY_KEY_ID,
        "user_id": user_id
    }
@app.post("/verify-payment")
def verify_payment(razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str, user_id: int, amount: float, merchant_id: str):
    try:
        razorpay_client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature
        })

        conn = sqlite3.connect("payments.db")
        cursor = conn.cursor()

        # Deduct from wallet
        cursor.execute("UPDATE users SET wallet_balance = wallet_balance - ? WHERE id = ?", (amount, user_id))

        # Save transaction
        cursor.execute(
            "INSERT INTO transactions (merchant_id, amount, payment_id, order_id, status) VALUES (?, ?, ?, ?, ?)",
            (merchant_id, amount, razorpay_payment_id, razorpay_order_id, "success")
        )
        conn.commit()
        conn.close()

        return {"status": "success", "payment_id": razorpay_payment_id}
    except razorpay.errors.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Payment verification failed")
        
@app.get("/transactions")
def get_transactions():
    conn = sqlite3.connect("payments.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return {"transactions": rows}

@app.post("/signup")
def signup(name: str, phone: str):
    conn = sqlite3.connect("payments.db")
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (name, phone) VALUES (?, ?)",
            (name, phone)
        )
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return {"status": "success", "user_id": user_id, "wallet_balance": 10000.0}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Phone number already registered")


@app.post("/login")
def login(phone: str):
    conn = sqlite3.connect("payments.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, phone, wallet_balance FROM users WHERE phone = ?", (phone,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "user_id": row[0],
        "name": row[1],
        "phone": row[2],
        "wallet_balance": row[3]
    }


@app.get("/wallet/{user_id}")
def get_wallet(user_id: int):
    conn = sqlite3.connect("payments.db")
    cursor = conn.cursor()
    cursor.execute("SELECT wallet_balance FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    return {"user_id": user_id, "wallet_balance": row[0]}