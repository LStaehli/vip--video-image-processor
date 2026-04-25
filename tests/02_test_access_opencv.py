import asyncio, logging, sys, time

logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s %(message)s")
sys.path.insert(0, '.')
from app.stream.reader import StreamReader

url = "http://admin:Rousse26Mars@192.168.1.248:8080/stream/mjpeg"
loop = asyncio.new_event_loop()
reader = StreamReader(source=url, loop=loop)
reader.start()

time.sleep(6)
print("Connected:", reader.connected, "| Queue:", reader.queue.qsize())
reader.stop()
loop.close()