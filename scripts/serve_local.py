import os
import sys
import socket
import functools
import webbrowser
import http.server
import socketserver

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def find_free_port(start=8899):
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return 8899

def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def main():
    no_open = "--no-open" in sys.argv
    port = find_free_port(8899)
    ip = get_lan_ip()
    local_url = f"http://localhost:{port}/index.html"
    lan_url = f"http://{ip}:{port}/index.html"

    print("=" * 60, flush=True)
    print(" 🍥 NARUTO 疾風伝・忍界大戦ビンゴ大会 プレビューサーバー起動完了", flush=True)
    print(f" 💻 PC用URL         : {local_url}", flush=True)
    print(f" 📱 タブレット用URL : {lan_url} (同じWi-Fiで接続)", flush=True)
    print("=" * 60, flush=True)

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT_DIR)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("0.0.0.0", port), handler) as httpd:
        if not no_open:
            webbrowser.open(local_url)
        httpd.serve_forever()

if __name__ == "__main__":
    main()
