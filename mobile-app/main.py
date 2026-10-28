from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.graphics.texture import Texture
from kivy.clock import Clock
import requests
import cv2
import webbrowser
import time
import os
from urllib.parse import urlencode

BACKEND_URL = "http://127.0.0.1:8000"  # use your laptop's network IP instead if testing from a phone
CHECKOUT_HTML_PATH = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'checkout.html')
)


class LoginScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout = BoxLayout(orientation='vertical', padding=40, spacing=20)
        layout.add_widget(Label(text='Login', font_size='28sp', size_hint_y=0.2))

        self.phone_input = TextInput(hint_text='Phone number', multiline=False, size_hint_y=0.15)
        layout.add_widget(self.phone_input)

        self.status_label = Label(text='', size_hint_y=0.15)
        layout.add_widget(self.status_label)

        login_btn = Button(text='Login', size_hint_y=0.15)
        login_btn.bind(on_press=self.do_login)
        layout.add_widget(login_btn)

        signup_btn = Button(text="New here? Sign up", size_hint_y=0.15)
        signup_btn.bind(on_press=self.go_to_signup)
        layout.add_widget(signup_btn)

        self.add_widget(layout)

    def do_login(self, instance):
        phone = self.phone_input.text.strip()
        if not phone:
            self.status_label.text = "Enter a phone number"
            return
        try:
            res = requests.post(f"{BACKEND_URL}/login", params={"phone": phone}, timeout=5)
            if res.status_code == 200:
                data = res.json()
                app = App.get_running_app()
                app.user_id = data["user_id"]
                app.user_name = data["name"]
                app.wallet_balance = data["wallet_balance"]
                self.manager.get_screen('home').refresh()
                self.manager.current = 'home'
            else:
                self.status_label.text = "User not found. Please sign up."
        except Exception as e:
            self.status_label.text = f"Error: {e}"

    def go_to_signup(self, instance):
        self.manager.current = 'signup'


class SignupScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout = BoxLayout(orientation='vertical', padding=40, spacing=20)
        layout.add_widget(Label(text='Sign Up', font_size='28sp', size_hint_y=0.2))

        self.name_input = TextInput(hint_text='Full name', multiline=False, size_hint_y=0.15)
        layout.add_widget(self.name_input)

        self.phone_input = TextInput(hint_text='Phone number', multiline=False, size_hint_y=0.15)
        layout.add_widget(self.phone_input)

        self.status_label = Label(text='', size_hint_y=0.15)
        layout.add_widget(self.status_label)

        signup_btn = Button(text='Create Account', size_hint_y=0.15)
        signup_btn.bind(on_press=self.do_signup)
        layout.add_widget(signup_btn)

        back_btn = Button(text="Back to login", size_hint_y=0.15)
        back_btn.bind(on_press=self.go_back)
        layout.add_widget(back_btn)

        self.add_widget(layout)

    def do_signup(self, instance):
        name = self.name_input.text.strip()
        phone = self.phone_input.text.strip()
        if not name or not phone:
            self.status_label.text = "Fill in both fields"
            return
        try:
            res = requests.post(f"{BACKEND_URL}/signup", params={"name": name, "phone": phone}, timeout=5)
            if res.status_code == 200:
                data = res.json()
                app = App.get_running_app()
                app.user_id = data["user_id"]
                app.user_name = name
                app.wallet_balance = data["wallet_balance"]
                self.manager.get_screen('home').refresh()
                self.manager.current = 'home'
            else:
                self.status_label.text = res.json().get("detail", "Signup failed")
        except Exception as e:
            self.status_label.text = f"Error: {e}"

    def go_back(self, instance):
        self.manager.current = 'login'


class HomeScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.layout = BoxLayout(orientation='vertical', padding=40, spacing=20)
        self.welcome_label = Label(text='', font_size='22sp', size_hint_y=0.2)
        self.balance_label = Label(text='', font_size='26sp', size_hint_y=0.2)
        self.layout.add_widget(self.welcome_label)
        self.layout.add_widget(self.balance_label)

        scan_btn = Button(text='Scan & Pay', size_hint_y=0.15)
        scan_btn.bind(on_press=self.go_to_scan)
        self.layout.add_widget(scan_btn)

        logout_btn = Button(text='Logout', size_hint_y=0.15)
        logout_btn.bind(on_press=self.do_logout)
        self.layout.add_widget(logout_btn)

        self.add_widget(self.layout)

    def refresh(self):
        app = App.get_running_app()
        self.welcome_label.text = f"Welcome, {app.user_name}"
        self.balance_label.text = f"Wallet: Rs {app.wallet_balance}"

    def go_to_scan(self, instance):
        self.manager.current = 'scan'

    def do_logout(self, instance):
        app = App.get_running_app()
        app.user_id = None
        app.user_name = None
        app.wallet_balance = None
        self.manager.current = 'login'


class ScanScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.layout = BoxLayout(orientation='vertical')
        self.img_widget = Image()
        self.result_label = Label(text='Point camera at a QR code', size_hint_y=0.2, font_size='16sp')
        self.confirm_btn = Button(text='Pay Anyway', size_hint_y=0.1)
        self.confirm_btn.bind(on_press=self.confirm_payment)
        back_btn = Button(text='Back', size_hint_y=0.1)
        back_btn.bind(on_press=self.go_back)

        self.layout.add_widget(self.img_widget)
        self.layout.add_widget(self.result_label)
        self.layout.add_widget(back_btn)
        self.add_widget(self.layout)

        self.capture = None
        self.detector = cv2.QRCodeDetector()
        self.last_scanned = None
        self.last_scan_time = 0
        self.event = None
        self.pending_payload = None

    def on_enter(self):
        self.capture = cv2.VideoCapture(0)
        self.result_label.text = 'Point camera at a QR code'
        self.last_scanned = None
        self.pending_payload = None
        if self.confirm_btn.parent:
            self.layout.remove_widget(self.confirm_btn)
        self.event = Clock.schedule_interval(self.update, 1.0 / 30.0)

    def on_leave(self):
        if self.event:
            self.event.cancel()
        if self.capture:
            self.capture.release()
            self.capture = None

    def update(self, dt):
        if not self.capture:
            return
        ret, frame = self.capture.read()
        if not ret:
            return

        data, bbox, _ = self.detector.detectAndDecode(frame)
        if data and data != self.last_scanned and (time.time() - self.last_scan_time) > 3:
            self.last_scanned = data
            self.last_scan_time = time.time()
            self.process_qr(data)

        buf = cv2.flip(frame, 0).tobytes()
        texture = Texture.create(size=(frame.shape[1], frame.shape[0]), colorfmt='bgr')
        texture.blit_buffer(buf, colorfmt='bgr', bufferfmt='ubyte')
        self.img_widget.texture = texture

    def process_qr(self, payload, confirm=False):
        app = App.get_running_app()
        self.result_label.text = "Verifying..."
        try:
            params = {"payload": payload, "user_id": app.user_id}
            if confirm:
                params["confirm"] = "true"
            res = requests.get(f"{BACKEND_URL}/create-payment", params=params, timeout=5)
            data = res.json()

            if res.status_code != 200:
                self.result_label.text = f"Error: {data.get('detail', 'Unknown error')}"
                return

            if data.get("status") == "flagged":
                reasons = "; ".join(data.get("reasons", []))
                self.result_label.text = f"Flagged (risk {data['risk_score']}): {reasons}"
                self.pending_payload = payload
                if not self.confirm_btn.parent:
                    self.layout.add_widget(self.confirm_btn, index=1)
                return

            if self.confirm_btn.parent:
                self.layout.remove_widget(self.confirm_btn)

            query = urlencode({
                "order_id": data['order_id'],
                "amount": data['amount'],
                "merchant_id": data['merchant_id'],
                "razorpay_key": data['razorpay_key'],
                "user_id": data['user_id'],
                "backend_url": BACKEND_URL
            })
            checkout_url = f"file:///{CHECKOUT_HTML_PATH.replace(os.sep, '/')}?{query}"
            print(f"DEBUG: Opening URL: {checkout_url}")
            print(f"DEBUG: File exists: {os.path.exists(CHECKOUT_HTML_PATH)}")
            webbrowser.open(checkout_url)
            self.result_label.text = f"Opening checkout for Rs {data['amount']} to {data['merchant_id']}..."

        except Exception as e:
            self.result_label.text = f"Error: {e}"

    def confirm_payment(self, instance):
        if self.pending_payload:
            self.process_qr(self.pending_payload, confirm=True)

    def go_back(self, instance):
        self.manager.current = 'home'


class PaymentApp(App):
    user_id = None
    user_name = None
    wallet_balance = None

    def build(self):
        sm = ScreenManager()
        sm.add_widget(LoginScreen(name='login'))
        sm.add_widget(SignupScreen(name='signup'))
        sm.add_widget(HomeScreen(name='home'))
        sm.add_widget(ScanScreen(name='scan'))
        return sm


PaymentApp().run()