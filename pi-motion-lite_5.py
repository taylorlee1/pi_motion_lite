
import Motion
import picamera
import queue
import logging
import threading

fmt = '%(asctime)-15s %(threadName)-8s %(message)s'
logging.basicConfig(
    level=logging.DEBUG,
    format=fmt,
    )

def setupCamera(c):
    c.annotate_background = picamera.color.Color('#000') # black
    pass

if __name__ == '__main__':
    Q = queue.Queue()
    writer = Motion.Writer(
        Q=Q,
        )
    
    writeThread = threading.Thread(
        target=writer.writeOut,
        daemon=True,
        name='Writer',
        )
    writeThread.start()

    with picamera.PiCamera() as camera:
        m = Motion.Motion(
            camera=camera,
            Q=Q,
            )

        setupCamera(camera)
        
        camThread = threading.Thread(
            target=m.run,
            daemon=True,
            name='Motion',
            )
        camThread.start()

        ## won't ever join, so blocks forever
        camThread.join()
        writeThread.join()
