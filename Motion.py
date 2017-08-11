
import sys
import time
import logging
import threading
import os
import io
import picamera
import picamera.array
import numpy as np
from collections import deque

log = logging.getLogger(__name__)

class DetectMotion(picamera.array.PiMotionAnalysis):
    def __init__(self, *args, **kwargs):
        self.camera = kwargs.get('camera', None)
        self.size = kwargs.get('size', None)
        self.motionDetectEvent = kwargs.get('motionDetectEvent')
        self.mask = kwargs.get('mask', None)
        self.debugQ = kwargs.get('debugQ', None)
        self.threshold = kwargs.get('threshold', 10)
        self.sensitivity = kwargs.get('sensitivity', 60)
        self.motionHistQ = kwargs.get('motionHistQ')

        super(DetectMotion, self).__init__(self.camera, self.size)

    def analyse(self, frame):
        frame = np.square( frame['x'].astype(np.uint8) ) + \
                np.square( frame['y'].astype(np.uint8) )
        
        frame = frame.clip(0,255).astype(np.uint8)

        if (frame > self.sensitivity).sum() > self.threshold:
            self.motionHistQ.append(1)
            self.motionDetectEvent.set()
            #log.debug("DetectMotion.analyse() append 1")
        else:
            self.motionHistQ.append(0)
            #log.debug("DetectMotion.analyse() append 0")

class Motion():
    def __init__(self, *args, **kwargs):
        self.camera = kwargs.get('camera')
        self.outQ = kwargs.get('Q')
        self.motionWidth = kwargs.get('motionWidth', 160)
        self.motionHeight = kwargs.get('motionHeight', 120)
        self.preSeconds = kwargs.get('preSeconds', 5)
        self.motionDetectEvent = threading.Event()
        self.motionHistQ = deque(maxlen=120)
        self.stream = picamera.PiCameraCircularIO(
            self.camera,
            seconds=self.preSeconds,
            )

        self.startRecording()
    
    def startRecording(self):
        self.camera.start_recording(
            self.stream,
            format='h264',
            splitter_port=1,
            )
        log.debug("Motion.startRecording() started saving " +
            "full res video to circular buffer")

        self.camera.start_recording(
            '/dev/null',
            splitter_port=2,
            resize=(self.motionWidth, self.motionHeight),
            format='h264',
            motion_output=DetectMotion(
                camera=self.camera,
                motionDetectEvent=self.motionDetectEvent,
                size=(self.motionWidth, self.motionHeight),
                motionHistQ=self.motionHistQ,
                )
            )
        log.debug("Motion.startRecording() started analyzing " +
            "motion info")

        self.camera.wait_recording(2, splitter_port=1)

    def getPrevid(self):
        bytes = io.BytesIO()
        log.debug("Motion.getPrevid() save pre motion video bytes")
        with self.stream.lock:
            count = 0
            for frame in self.stream.frames:
                log.debug("Motion.getPrevid() frame count %s" % count)
                if frame.frame_type == picamera.PiVideoFrameType.sps_header:
                    self.stream.seek(frame.position)
                    log.debug("Motion.getPrevid() seek %s" % (frame.position))
                    break
                count += 1

            while True:
                buf = self.stream.read1()
                bytes.write(buf)
                if not buf:
                    break

            self.stream.seek(0)
            self.stream.truncate()
    
        buf = bytes.getvalue()
        bytes.close()
        log.debug("Motion.getPrevid() saved pre motion video len %s" % len(buf))
        return(buf)

    def savePostvid(self):
        tmpFileName = time.strftime('%s', time.localtime()) + '.h264'
        with open(tmpFileName, 'wb') as f:
            log.debug("Motion.getPostvid() split real-time video to file %s" % tmpFileName)
            self.camera.annotate_text = time.strftime('%Y%m%d-%H%M%S', time.localtime())
            self.camera.split_recording(f, splitter_port=1)

            count = 0
            while True:
                s = sum(list(self.motionHistQ))
                log.debug("Motion.getPostvid() still recording ( %s seconds ) (%s)" % 
                    (count, s))
                self.camera.wait_recording(1, splitter_port=1)
                count += 1
                if s == 0:
                    self.camera.wait_recording(1, splitter_port=1)
                    self.camera.annotate_text = '' # does this help performance?
                    self.camera.split_recording(self.stream, splitter_port=1)
                    break
        
        log.debug("Motion.getPostvid() recording stopped")
        return(tmpFileName)
        
    def run(self):
        while True:
            self.motionDetectEvent.wait()
            self.saveVideo()
            self.motionDetectEvent.clear()

    def saveVideo(self):
        log.debug("Motion.saveVideo() start")

        preBuf = b''

        try:
            preBuf = self.getPrevid()
        except Exception as e:
            log.error("Motion.saveVideo() previd error %s" % e) 

        try:
            filename = self.savePostvid()
        except Exception as e:
            log.error("Motion.saveVideo() postvid error %s" % e) 

        try:
            self.outQ.put((preBuf, filename))
        except Exception as e:
            log.error("Motion.saveVideo() put error %s" % e)
    
        log.debug("Motion.saveVideo() done")

class Writer():
    def __init__(self, *args, **kwargs):
        self.bytesQ = kwargs.get('Q')
        self.saveDir = kwargs.get('saveDir', './')

    def getFileName(self):
        return time.strftime('%Y%m%d-%H%M%S', time.localtime()) + '.h264'
        
    def writeOut(self):
        while True:
            buf,fn = self.bytesQ.get()
            outfile = os.path.join(self.saveDir, self.getFileName())
            log.debug("Writer.writeOut() outfile %s" % outfile)
            log.debug("Writer.writeOut() bufsize: %s" % len(buf))
            log.debug("Writer.writeOut() infile: %s" % fn)
            
            log.debug("Writer.writeOut() writing %s" % outfile)
            with open(outfile, 'wb') as output:
                output.write(buf)
        
                with open(fn, 'rb') as input:
                    output.write(input.read())

                os.remove(fn)
                log.debug("Writer.writeOut() removed %s" % fn)

            log.debug("wrote %s" % outfile)
