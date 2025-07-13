
from flask import Flask
from threading import Thread
import time

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

@app.route('/status')
def status():
    return {
        "status": "running",
        "timestamp": time.time(),
        "message": "Telegram Video Downloader Bot is active"
    }

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
  
