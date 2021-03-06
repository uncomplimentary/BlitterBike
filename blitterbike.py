from twisted.internet.protocol import Factory
from twisted.protocols.basic import LineReceiver
from twisted.internet import reactor
from twisted.python import log
from threading import Timer

import images2gif
import inspect, os, sys, pkgutil, socket, time, datetime
from multiprocessing import Process, Value

try:
    from PIL import Image, ImageDraw, ImageFont, Image
except ImportError:
    import Image, ImageDraw, ImageFont, Image


BLITTER_BIKE_PATH = os.environ["BLITTERBIKEPATH"]
MODE_BUTTON = "mode"
UP_BUTTON = "up"
DOWN_BUTTON = "down"
LEFT_BUTTON = "left"
RIGHT_BUTTON = "right"

A_BUTTON = "a"
B_BUTTON = "b"
C_BUTTON = "c"  
D_BUTTON = "d"
E_BUTTON = "e"
F_BUTTON = "f"
G_BUTTON = "g"
H_BUTTON = "h"

SPEED_PREDICTOR = 1.2
SPEED_DAMPING = 0.95

GAMMA_TABLE =  [0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0, 
                0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  1,  1,  1,  1,
                1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  2,  2,  2,  2,
                2,  2,  2,  2,  2,  3,  3,  3,  3,  3,  3,  3,  3,  4,  4,  4,
                4,  4,  4,  4,  5,  5,  5,  5,  5,  6,  6,  6,  6,  6,  7,  7,
                7,  7,  7,  8,  8,  8,  8,  9,  9,  9,  9, 10, 10, 10, 10, 11,
                11, 11, 12, 12, 12, 13, 13, 13, 13, 14, 14, 14, 15, 15, 16, 16,
                16, 17, 17, 17, 18, 18, 18, 19, 19, 20, 20, 21, 21, 21, 22, 22,
                23, 23, 24, 24, 24, 25, 25, 26, 26, 27, 27, 28, 28, 29, 29, 30,
                30, 31, 32, 32, 33, 33, 34, 34, 35, 35, 36, 37, 37, 38, 38, 39,
                40, 40, 41, 41, 42, 43, 43, 44, 45, 45, 46, 47, 47, 48, 49, 50,
                50, 51, 52, 52, 53, 54, 55, 55, 56, 57, 58, 58, 59, 60, 61, 62,
                62, 63, 64, 65, 66, 67, 67, 68, 69, 70, 71, 72, 73, 74, 74, 75,
                76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91,
                92, 93, 94, 95, 96, 97, 98, 99,100,101,102,104,105,106,107,108,
                109,110,111,113,114,115,116,117,118,120,121,122,123,125,126,127]

LATCH = [0] * 48

# The core BlitterBike application
# It loads in all of the modes and flips between them as the user hits the mode button
class BlitterBike:
    
    def start(self):
        self.modeList = []

        pkg = 'modes'
        __import__(pkg)
        package = sys.modules[pkg]
        prefix = pkg + "."

        for importer,modname,ispkg in pkgutil.iter_modules(package.__path__,prefix):
            module = __import__(modname,locals(),[],-1)
            for name,cls in inspect.getmembers(module):
                if inspect.isclass(cls):
                    self.modeList.append(cls())


        self.modeIndex = 0
        self.mode = self.modeList[self.modeIndex]
        self.delayTimer = None
        self.speed = 0

        reactor.callInThread(self.run)
        self.isRunning = True

        if socket.gethostname() == "blitterbike":
            import spi
            self.spi_conn = spi.SPI(2, 0)
            self.spi_conn.msh = 1000000

            self.blit = self.blitScreen

            open('/sys/kernel/debug/omap_mux/lcd_data0', 'wb').write("%X" % 39)
            try:
                # check to see if the pin is already exported
                open('/sys/class/gpio/gpio70/direction').read()
            except:
                open('/sys/class/gpio/export', 'w').write('70')

            # set Port 8 Pin 3 for output
            open('/sys/class/gpio/gpio70/direction', 'w').write('in')

            self.speed = Value("f", 0.0)
            self.sensor = Process(target=self.readSensor, args=(self.speed,))
            self.sensor.start()

            self.isBlitterBike = True

            self.clear()

        else:
            self.isBlitterBike = False;

        self.onChangeMode()

    def run(self):
        while self.isRunning:
            if self.mode != None:
                if self.mode.isBooting:
                    im = self.mode.updateBoot()
                else:
                    im = self.mode.update(self.speed.value)
            
                if im != None:
                    self.blit(im)

    def stop(self):
        self.isRunning = False
        self.sensor.terminate()
        open('/sys/class/gpio/unexport', 'w').write('70')        

        if self.mode != None:
            self.mode.stop()

        self.clear()

    def readSensor(self, speed):
        lastValue = 1
        lastMagnet = 0
        halfCirc = 23.56194490
        lastSpeed = 0
        lastDelta = 0

        while 1:

            value = int(open('/sys/class/gpio/gpio70/value', 'r').read())

            if value == 0 and lastValue == 1:
                magnet = time.time()
                if lastMagnet > 0:
                    lastDelta = magnet - lastMagnet      
                    speed.value  =  (halfCirc/lastDelta)
                    lastDelta *= SPEED_PREDICTOR
                lastMagnet = magnet
            else:

                if time.time() - lastMagnet > lastDelta:
                    speed.value *= SPEED_DAMPING

                if speed.value < 5:
                    speed.value = 0

            lastValue = value
            time.sleep(0.005)

    def onChangeMode(self):
        self.mode.stop()
        self.modeIndex += 1
        if self.modeIndex == len(self.modeList):
            self.modeIndex = 0

        self.mode = self.modeList[self.modeIndex]
        self.mode.boot()

    def onButtonDown(self, button):
        if self.mode != None:
            self.mode.onButtonDown(button)

    def onButtonUp(self, button):
        if self.mode != None:
            self.mode.onButtonUp(button)

    def blitTk(self, im):
        pass

    def blitScreen(self, im):
        y = 31;
        x = 0;
        dir = 1
        data = []

        for i in range(1024):
            pixel = im[(y*32) + x]

            red = GAMMA_TABLE[pixel[0]] | 128
            green = GAMMA_TABLE[pixel[1]] | 128
            blue = GAMMA_TABLE[pixel[2]] | 128
            
            data.append(green)
            data.append(red)
            data.append(blue)

            x += dir
            if dir == 1 and x == 32:
                x = 31
                y -= 1
                dir = -1
            elif dir == -1 and x == -1:
                x = 0
                y -= 1
                dir = 1

        self.writeToStrip(data)
        self.writeToStrip(LATCH)

    def writeToStrip(self, data):
        for index in range(0, len(data), 32):
            self.spi_conn.writebytes(data[index:(index+32)])

    def fill(self, color):
        self.blit([color] * 1024)

    def clear(self):
        self.writeToStrip(LATCH)

        self.fill((0, 0, 0))

class BlitterBikeMode:

    def __init__(self):
        self.isBooting = False
        self.lastTime = 0
        self.bootIndex = 0
        self.bootImage = None

    def boot(self):
        self.isBooting = True
        self.lastTime = 0

        self.bootImage = Image.open(self.bootGif)
        self.bootFrame = Image.new("RGBA", (32, 32), (0,0,0))

        next = self.bootImage.convert("RGBA")
        self.bootFrame.paste(next, next.getbbox())
        self.bootIndex = 0

        try:
            self.bootDelay = self.bootImage.info['duration']
        except KeyError:
            self.bootDelay = 20

        if self.bootDelay < 20:
            self.bootDelay = 100;

    def updateBoot(self):

        result = None

        try:
            if not self.bootImage == None:
                currentTime = int(round(time.time() * 1000))
                elapsed = currentTime - self.lastTime

                if self.bootIndex == 0:
                    result = self.bootFrame.convert("RGB").getdata()
                    self.bootIndex += 1

                elif elapsed >= self.bootDelay and self.bootDelay > 0:
                    self.lastTime = currentTime
                    self.nextBootFrame()
                    result = self.bootFrame.convert("RGB").getdata()
        except:
            pass

        return result

    def nextBootFrame(self):
        try:
            self.bootImage.seek(self.bootImage.tell() + 1)
            self.bootIndex += 1
            self.bootImage.palette.dirty = 1
            self.bootImage.palette.rawmode = "RGB"

            next = self.bootImage.convert("RGBA")
            
            self.bootFrame.paste(next, next.getbbox(), mask=next)

            try:
                self.bootDelay = self.bootImage.info['duration']
            except KeyError:
                self.bootDelay = 100


            if self.bootDelay < 20:
                self.bootDelay = 100

        except EOFError:
            self.isBooting = False
            self.start()                   

    def start(self):
        pass

    def stop(self):
        pass

    def update(self):
        pass

    def onButtonDown(self, button):
        pass

    def onButtonUp(self, button):
        pass

class BlitterBikeServer(LineReceiver):

    def __init__(self, blitterbike):
        self.blitterbike = blitterbike
        log.msg(BLITTER_BIKE_PATH)

    def lineReceived(self, command):
        commandList = command.split("|")
	log.msg(command)

        if commandList[0] == "c":
            now = datetime.datetime.now()
            name = BLITTER_BIKE_PATH + "/gifs/crawl/crawl_%d-%d-%d_%d:%d:%d.gif" % (now.year, now.month, now.day, now.hour, now.minute, now.second)
            text = commandList[1]
            font = ImageFont.truetype(BLITTER_BIKE_PATH + commandList[2], 24)
            fill = (int(commandList[3]), int(commandList[4]), int(commandList[5]))
            frames = self.makeCrawl(text, font, fill, 2)
            images2gif.writeGif(name, frames, subRectangles=False, duration=0.05, dispose=1)

        elif commandList[0] == "d":
            if commandList[1] == MODE_BUTTON:
                self.blitterbike.onChangeMode()
            else:
                self.blitterbike.onButtonDown(commandList[1])
        elif commandList[0] == "u":
            if commandList[1] != MODE_BUTTON:
                self.blitterbike.onButtonUp(commandList[1])

    def makeCrawl(self, text, font, fill, step):
        frames = []
        im = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(im)
        size = draw.textsize(text, font=font)
        count = int((size[0] + 32) / step)
        offset = 32


        for i in range(count):
            im = Image.new('RGB', (32, 32), (0,0,0))
            draw = ImageDraw.Draw(im)
            draw.text((offset, 3), text, font=font, fill=fill)
            offset -= step
            frames.append(im)

        return frames


class BlitterBikeServerFactory(Factory):

    def __init__(self):
        self.blitterbike = BlitterBike()

    def buildProtocol(self, addr):
        return BlitterBikeServer(self.blitterbike)

    def startFactory(self):
        self.blitterbike.start()

    def stopFactory(self):
        self.blitterbike.stop()

