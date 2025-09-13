# server.py
import socket
import threading
import json
import struct
import base64
import sys
from cryptography.fernet import Fernet
import hashlib

def key_from_password(password: str) -> bytes:
    """Paroladan Fernet key türetir"""
    h = hashlib.sha256(password.encode()).digest()
    return base64.urlsafe_b64encode(h)

def send_frame(sock: socket.socket, data: bytes):
    sock.sendall(struct.pack("!I", len(data)) + data)

def recv_frame(sock: socket.socket):
    header = sock.recv(4)
    if not header:
        return None
    length = struct.unpack("!I", header)[0]
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            return None
        data += chunk
    return data

clients_lock = threading.Lock()
clients = {}   # sock -> {username, cipher, channel}
channels = {}  # channel_name -> set(sockets)

def broadcast_to_channel(channel_name: str, from_sock: socket.socket, plaintext: str):
    with clients_lock:
        if channel_name not in channels:
            return
        for r in channels[channel_name]:
            if r == from_sock:
                continue
            cinfo = clients[r]
            payload = cinfo["cipher"].encrypt(plaintext.encode())
            envelope = {"type":"msg","from":clients[from_sock]["username"],
                        "channel":channel_name,"payload":base64.b64encode(payload).decode()}
            try:
                send_frame(r, json.dumps(envelope).encode())
            except:
                remove_client(r)

def send_user_list(channel_name: str):
    with clients_lock:
        users = [clients[s]["username"] for s in channels.get(channel_name,set())]
        envelope = {"type":"user_list","channel":channel_name,"users":users}
        for s in channels.get(channel_name,set()):
            try:
                send_frame(s,json.dumps(envelope).encode())
            except:
                remove_client(s)

def remove_client(sock: socket.socket):
    with clients_lock:
        info = clients.pop(sock, None)
        if info:
            ch = info.get("channel")
            if ch in channels and sock in channels[ch]:
                channels[ch].remove(sock)
                if not channels[ch]:
                    channels.pop(ch)
                else:
                    send_user_list(ch)
        try:
            sock.close()
        except:
            pass

def handle_client(sock: socket.socket, addr, server_password: str):
    print(f"[CONNECTED] {addr}")
    try:
        data = recv_frame(sock)
        if not data:
            remove_client(sock)
            return
        obj = json.loads(data.decode())
        if obj.get("type") != "join":
            remove_client(sock)
            return
        username = obj.get("username", "Unknown")
        password = obj.get("password", "")
        channel = obj.get("channel", "Genel")

        if password != server_password:
            send_frame(sock,json.dumps({"type":"error","message":"Invalid password"}).encode())
            remove_client(sock)
            return

        cipher = Fernet(key_from_password(password))

        with clients_lock:
            clients[sock] = {"username": username, "cipher": cipher, "channel": channel}
            channels.setdefault(channel,set()).add(sock)

        send_frame(sock,json.dumps({"type":"joined","channel":channel}).encode())
        send_user_list(channel)

        while True:
            framed = recv_frame(sock)
            if framed is None:
                break
            msgobj = json.loads(framed.decode())
            mtype = msgobj.get("type")
            if mtype == "msg":
                payload_b64 = msgobj.get("payload")
                if not payload_b64:
                    continue
                try:
                    plaintext = cipher.decrypt(base64.b64decode(payload_b64)).decode()
                except:
                    continue
                broadcast_to_channel(clients[sock]["channel"], sock, plaintext)
            elif mtype == "join_channel":
                newch = msgobj.get("channel","Genel")
                with clients_lock:
                    old = clients[sock]["channel"]
                    channels[old].remove(sock)
                    channels.setdefault(newch,set()).add(sock)
                    clients[sock]["channel"] = newch
                send_user_list(old)
                send_user_list(newch)
                send_frame(sock,json.dumps({"type":"joined","channel":newch}).encode())
            elif mtype == "leave":
                break
    except Exception as e:
        print("Client handler exception:", e)
    finally:
        remove_client(sock)
        print(f"[DISCONNECTED] {addr}")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python server.py <bind_host> <port> <server_password>")
        sys.exit(1)
    host = sys.argv[1]
    port = int(sys.argv[2])
    server_password = sys.argv[3]

    serv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    serv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR,1)
    serv.bind((host, port))
    serv.listen(100)
    print(f"[SERVER STARTED] {host}:{port}  (password required)")

    try:
        while True:
            client_sock, addr = serv.accept()
            threading.Thread(target=handle_client,args=(client_sock,addr,server_password),daemon=True).start()
    except KeyboardInterrupt:
        print("Server kapatılıyor...")
    finally:
        serv.close()
