# client.py
import sys, socket, threading, json, struct, base64
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QHBoxLayout,QTextEdit,QLineEdit,QPushButton,QLabel,QListWidget,QMessageBox
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt
from cryptography.fernet import Fernet
import hashlib, base64 as b64

def send_frame(sock,data:bytes): sock.sendall(struct.pack("!I",len(data))+data)
def recv_frame(sock):
    header = sock.recv(4)
    if not header: return None
    length = struct.unpack("!I",header)[0]
    data=b""
    while len(data)<length:
        chunk=sock.recv(length-len(data))
        if not chunk: return None
        data+=chunk
    return data

def key_from_password(password:str)->bytes:
    h = hashlib.sha256(password.encode()).digest()
    return b64.urlsafe_b64encode(h)

class ChatClient(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("L122S")
        self.setGeometry(150,100,900,650)

        main=QHBoxLayout(self)
        left=QVBoxLayout(); mid=QVBoxLayout(); right=QVBoxLayout()

        self.title=QLabel("Lanux Chat"); self.title.setFont(QFont("Arial",18,QFont.Weight.Bold)); self.title.setAlignment(Qt.AlignCenter)
        self.username_input=QLineEdit(); self.username_input.setPlaceholderText("Kullanıcı Adı")
        self.server_input=QLineEdit(); self.server_input.setPlaceholderText("Sunucu IP (örn:127.0.0.1:5555)")
        self.password_input=QLineEdit(); self.password_input.setPlaceholderText("Sunucu Parolası"); self.password_input.setEchoMode(QLineEdit.Password)
        self.connect_btn=QPushButton("Bağlan"); self.disconnect_btn=QPushButton("Ayrıl"); self.disconnect_btn.setEnabled(False)
        self.channel_list=QListWidget(); self.channel_list.addItem("Genel"); self.channel_list.itemDoubleClicked.connect(self.ui_join_channel)

        left.addWidget(self.title); left.addWidget(self.username_input); left.addWidget(self.server_input)
        left.addWidget(self.password_input); left.addWidget(self.connect_btn); left.addWidget(self.disconnect_btn)
        left.addWidget(QLabel("Kanallar (çift tıkla geçiş)")); left.addWidget(self.channel_list)

        self.header=QLabel("Durum: Bağlı Değil"); self.chat_area=QTextEdit(); self.chat_area.setReadOnly(True)
        self.msg_input=QLineEdit(); self.msg_input.setPlaceholderText("Mesaj yaz... (/join KanalAdi)")
        self.send_btn=QPushButton("Gönder"); mid.addWidget(self.header); mid.addWidget(self.chat_area)
        input_row=QHBoxLayout(); input_row.addWidget(self.msg_input); input_row.addWidget(self.send_btn); mid.addLayout(input_row)

        right.addWidget(QLabel("Çevrimiçi")); self.user_list=QListWidget(); right.addWidget(self.user_list)

        main.addLayout(left,2); main.addLayout(mid,5); main.addLayout(right,2)

        self.setStyleSheet("""
            QWidget{background-color:#2f3136;color:#fff;font-family:Arial;}
            QLineEdit{background:#40444b;border-radius:6px;padding:6px;color:#fff;}
            QTextEdit{background:#36393f;border-radius:6px;padding:8px;color:#fff;}
            QListWidget{background:#2e2f33;border-radius:6px;padding:6px;color:#fff;}
            QPushButton{background:#5865f2;border-radius:6px;padding:8px;color:#fff;font-weight:bold;}
            QPushButton:disabled{background:#3a3b40;color:#9aa0ff;}
        """)

        self.connect_btn.clicked.connect(self.connect_to_server)
        self.disconnect_btn.clicked.connect(self.disconnect)
        self.send_btn.clicked.connect(self.send_msg)
        self.msg_input.returnPressed.connect(self.send_msg)

        self.sock=None; self.listener_thread=None; self.cipher=None; self.current_channel="Genel"

    def show_error(self,txt): QMessageBox.critical(self,"Hata",txt)

    def connect_to_server(self):
        if self.sock: self.show_error("Zaten bağlısın!"); return
        username=self.username_input.text().strip()
        server_raw=self.server_input.text().strip()
        password=self.password_input.text().strip()
        if not username or not server_raw or not password: self.show_error("Kullanıcı adı, sunucu IP ve parola gerekli."); return
        if ":" in server_raw: host,port_s=server_raw.split(":",1); port=int(port_s)
        else: host=server_raw; port=5555
        try: self.sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM); self.sock.connect((host,port))
        except Exception as e: self.show_error(f"Sunucuya bağlanılamadı: {e}"); self.sock=None; return
        self.cipher=Fernet(key_from_password(password))
        join_obj={"type":"join","username":username,"password":password,"channel":self.current_channel}
        send_frame(self.sock,json.dumps(join_obj).encode())
        framed=recv_frame(self.sock)
        if framed is None: self.show_error("Sunucudan cevap alınamadı."); self.sock.close(); self.sock=None; return
        resp=json.loads(framed.decode())
        if resp.get("type")=="error": self.show_error("Sunucu hatası: "+resp.get("message","")); self.sock.close(); self.sock=None; return
        if resp.get("type")=="joined":
            self.header.setText(f"Bağlı: {host}:{port} Kanal: {resp.get('channel')}")
            self.connect_btn.setEnabled(False); self.disconnect_btn.setEnabled(True)
            self.username_input.setEnabled(False); self.server_input.setEnabled(False); self.password_input.setEnabled(False)
            self.chat_area.append("[Sunucuya bağlanıldı]")
            self.listener_thread=threading.Thread(target=self.listen_loop,daemon=True)
            self.listener_thread.start()

    def listen_loop(self):
        try:
            while True:
                framed=recv_frame(self.sock)
                if framed is None: break
                obj=json.loads(framed.decode())
                t=obj.get("type")
                if t=="msg":
                    payload_b64=obj.get("payload")
                    if not payload_b64: continue
                    try: plaintext=self.cipher.decrypt(base64.b64decode(payload_b64)).decode()
                    except: self.chat_area.append("[Şifre çözme hatası]"); continue
                    sender=obj.get("from","unknown"); ch=obj.get("channel","")
                    self.chat_area.append(f"{sender} (@{ch}): {plaintext}")
                elif t=="user_list":
                    ch=obj.get("channel",""); users=obj.get("users",[])
                    if ch==self.current_channel: self.user_list.clear(); [self.user_list.addItem(u) for u in users]
                elif t=="joined":
                    self.current_channel=obj.get("channel",self.current_channel)
                    self.header.setText(f"Bağlı: {self.server_input.text()} Kanal: {self.current_channel}")
        except Exception as e:
            self.chat_area.append(f"[Listen loop hatası: {e}]")
        finally:
            if self.sock: self.sock.close()
            self.sock=None
            self.connect_btn.setEnabled(True)
            self.disconnect_btn.setEnabled(False)
            self.username_input.setEnabled(True)
            self.server_input.setEnabled(True)
            self.password_input.setEnabled(True)
            self.chat_area.append("[Sunucudan ayrıldınız]")

    def send_msg(self):
        if not self.sock: self.show_error("Bağlı değilsin!"); return
        txt=self.msg_input.text().strip()
        if not txt: return
        if txt.startswith("/join "):
            newch=txt[6:].strip()
            if newch:
                send_frame(self.sock,json.dumps({"type":"join_channel","channel":newch}).encode())
            self.msg_input.clear()
            return
        payload=self.cipher.encrypt(txt.encode())
        send_frame(self.sock,json.dumps({"type":"msg","payload":base64.b64encode(payload).decode()}).encode())
        self.chat_area.append(f"Ben (@{self.current_channel}): {txt}")
        self.msg_input.clear()

    def disconnect(self):
        if self.sock:
            try:
                send_frame(self.sock,json.dumps({"type":"leave"}).encode())
            except: pass
            self.sock.close()
        self.sock=None
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.username_input.setEnabled(True)
        self.server_input.setEnabled(True)
        self.password_input.setEnabled(True)
        self.chat_area.append("[Sunucudan ayrıldınız]")

    def ui_join_channel(self,item):
        ch=item.text()
        send_frame(self.sock,json.dumps({"type":"join_channel","channel":ch}).encode())

if __name__=="__main__":
    app=QApplication(sys.argv)
    w=ChatClient(); w.show()
    sys.exit(app.exec())
