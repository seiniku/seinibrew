#
# Copyright (c) 2012 Stephen P. Smith
#
# Permission is hereby granted, free of charge, to any person obtaining 
# a copy of this software and associated documentation files 
# (the "Software"), to deal in the Software without restriction, 
# including without limitation the rights to use, copy, modify, 
# merge, publish, distribute, sublicense, and/or sell copies of the Software, 
# and to permit persons to whom the Software is furnished to do so, 
# subject to the following conditions:

# The above copyright notice and this permission notice shall be included 
# in all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS 
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, 
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE 
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, 
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR 
# IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.


from multiprocessing import Process, Pipe, Queue, current_process, Value
from subprocess import Popen, PIPE, call
from datetime import datetime
import web, time, random, json, serial, os
import RPi.GPIO as GPIO
#from pid import pid as PIDController
from pid import pidpy as PIDController
import ConfigParser
import io
from ctypes import Structure, c_double, c_char_p, c_int, c_float

sample_config = """
;to add a probe use the value in /sys/bus/w1/devices/<address>/
; or look in /sys/bus/w1/devices/w1_bus_master1/w1_master_slaves
; or whereever your appropriate master bus
; set the address under the value "probe" under the appropriate section
; for the GPIO output, you have to define the GPIO (can't use 0, sorry)
; that the SSRs/output is connected to
; I've included examples under HLT 

[hlt]
;Sets the SSR output at GPIO7 and and 1wire address
;gpio = 7
;probe = 28-0000032c449f

[mlt]

[kettle]
"""



class param(Structure):
    _fields_ = [('mode', c_char_p), 
                ('cycle_time', c_double),
                ('duty_cycle', c_double),
                ('set_point', c_double),
                ('k_param', c_double),
                ('i_param', c_double),
                ('d_param', c_double),
                ('temp', c_double),
                ('probe', c_char_p),
                ('gpio', c_int),
                ('elapsed', c_float),
                ('name', c_char_p)]



def add_global_hook(parent_conn, statusQ):
    
    g = web.storage({"parent_conn" : parent_conn, "statusQ" : statusQ})
    def _wrapper(handler):
        web.ctx.globals = g
        return handler()
    return _wrapper
            

class raspibrew: 
    def __init__(self):
                
        self.mode = param.mode
        self.cycle_time = param.cycle_time
        self.duty_cycle = param.duty_cycle
        self.set_point = param.set_point
        self.k_param = param.k_param
        self.i_param = param.i_param
        self.d_param = param.d_param
        
        
    def GET(self):
       
        return render.raspibrew(self.mode, self.set_point, self.duty_cycle, self.cycle_time, \
                                self.k_param,self.i_param,self.d_param)
        
    def POST(self):
        data = web.data()
        #print data
        datalist = data.split("&")
        for item in datalist:
            datalistkey = item.split("=")
            
            if datalistkey[0] == "form":
                controller = datalistkey[1]
            if datalistkey[0] == "mode":
                mode = datalistkey[1]
            if datalistkey[0] == "setpoint":
                set_point = float(datalistkey[1])
            if datalistkey[0] == "dutycycle":
                duty_cycle = float(datalistkey[1])
            if datalistkey[0] == "cycletime":
                cycle_time = float(datalistkey[1])
            if datalistkey[0] == "k":
                k_param = float(datalistkey[1])
            if datalistkey[0] == "i":
                i_param = float(datalistkey[1])
            if datalistkey[0] == "d":
                d_param = float(datalistkey[1])
         
        
        # iterated through the list, now put the data in the correct location
        if controller == "hlt":
            hlt_param.mode = mode
            hlt_param.set_point = set_point
            hlt_param.duty_cycle = duty_cycle
            hlt_param.cycle_time = cycle_time
            hlt_param.k_param = k_param
            hlt_param.i_param = i_param
            hlt_param.d_param = d_param
        if controller == "mlt":
            mlt_param.mode = mode
            mlt_param.set_point = set_point
            mlt_param.duty_cycle = duty_cycle
            mlt_param.cycle_time = cycle_time
            mlt_param.k_param = k_param
            mlt_param.i_param = i_param
            mlt_param.d_param = d_param
        if controller == "kettle":
            kettle_param.mode = mode
            kettle_param.set_point = set_point
            kettle_param.duty_cycle = duty_cycle
            kettle_param.cycle_time = cycle_time
            kettle_param.k_param = k_param
            kettle_param.i_param = i_param
            kettle_param.d_param = d_param
        
            
        web.ctx.globals.parent_conn.send([mode, cycle_time, duty_cycle, set_point, \
                              k_param, i_param, d_param])  
        
             
 
def getrandProc(conn):
    p = current_process()
    print 'Starting:', p.name, p.pid
    while (True):
        #t = time.time()
        num = randomnum()
        #elapsed = time.time() - t
        time.sleep(.5) 
        #print num
        conn.send(num)

        
def gettempProc(params, conn):
    p = current_process()
    print 'Starting:', p.name, p.pid, params.probe
    while (True):
        t = time.time()
        time.sleep(.5) #.1+~.83 = ~1.33 seconds
        num = tempdata(params.probe) 
        params.elapsed = (time.time() - t)
        conn.send([num, params.elapsed])
    
        

def getonofftime(cycle_time, duty_cycle):
    duty = duty_cycle/100.0
    on_time = cycle_time*(duty)
    off_time = cycle_time*(1.0-duty)   
    return [on_time, off_time]
        
def heatProctest(cycle_time, duty_cycle, conn):
    #p = current_process()
    #print 'Starting:', p.name, p.pid
    while (True):
        if (conn.poll()):
            cycle_time, duty_cycle = conn.recv()
            
        on_time, off_time = getonofftime(cycle_time, duty_cycle)
        #print on_time
        # led on
        time.sleep(on_time)
        #print off_time
        # led off
        time.sleep(off_time)
        conn.send([cycle_time, duty_cycle]) #shows its alive
        
        
def heatProc(gpio, cycle_time, duty_cycle, conn):
    p = current_process()
    print "GPIO: " + str(gpio)
    if gpio <= 0:
        return 
    print 'Starting:', p.name, p.pid
    
    GPIO.setup(gpio, GPIO.OUT)
    #set I/0 to write
    while (True):
        while (conn.poll()): #get last
            cycle_time, duty_cycle = conn.recv()
        conn.send([cycle_time, duty_cycle])  
        if duty_cycle == 0:
            GPIO.output(gpio, GPIO.LOW)
            time.sleep(cycle_time)
        elif duty_cycle == 100:
            GPIO.output(gpio, GPIO.HIGH)
            time.sleep(cycle_time)
        else:
            on_time, off_time = getonofftime(cycle_time, duty_cycle)
            GPIO.output(gpio, GPIO.HIGH)
            time.sleep(on_time)
            GPIO.output(gpio, GPIO.LOW)
            time.sleep(off_time)
        
        #y = datetime.now()
        #time_sec = y.second + y.microsecond/1000000.0
        #print "%s Thread time (sec) after LED off: %.2f" % (self.getName(), time_sec)

def tempControlProcTest(mode, cycle_time, duty_cycle, set_point, k_param, i_param, d_param, conn):
    
        p = current_process()
        print 'Starting:', p.name, p.pid
        parent_conn_temp, child_conn_temp = Pipe()            
        ptemp = Process(name = "getrandProc", target=getrandProc, args=(child_conn_temp,))
        #ptemp.daemon = True
        ptemp.start()   
        parent_conn_heat, child_conn_heat = Pipe()           
        pheat = Process(name = "heatProctest", target=heatProctest, args=(cycle_time, duty_cycle, child_conn_heat))
        #pheat.daemon = True
        pheat.start()  
        
        while (True):
            if parent_conn_temp.poll():
                randnum = parent_conn_temp.recv() #non blocking receive
                conn.send([randnum, mode, cycle_time, duty_cycle, set_point, k_param, i_param, d_param])
            if parent_conn_heat.poll():
                cycle_time, duty_cycle = parent_conn_heat.recv()
                #duty_cycle = on_time/offtime*100.0
                #cycle_time = on_time + off_time
            if conn.poll():
                mode, cycle_time, duty_cycle, set_point, k_param, i_param, d_param = conn.recv()
                #conn.send([mode, cycle_time, duty_cycle])
                #if mode == "manual": 
                parent_conn_heat.send([cycle_time, duty_cycle])
            
#controls 

def tempControlProc(hlt_param, kettle_param, mlt_param, statusQ, conn):
    
    if hlt_param.probe != 0:
        print "Starting HLT Proc in mode " + str(hlt_param.mode) + str(hlt_param.probe)
        hlt_parent_conn_temp, hlt_child_conn_temp = Pipe()   
        hlt_proc = Process(name = "tempControlHLT", target=tempControlChild, args=(hlt_param, statusQ, hlt_child_conn_temp,))
        #hlt_proc.daemon = True
        hlt_proc.start()   
        print "HLT Proc Started"
        
    if mlt_param.probe:
        print "Starting MLT Proc in mode " + str(mlt_param.mode) + str(mlt_param.probe)
        mlt_parent_conn_temp, mlt_child_conn_temp = Pipe()   
        mlt_proc = Process(name = "tempControlMLT", target=tempControlChild, args=(mlt_param, statusQ, mlt_child_conn_temp,))
        #mlt_proc.daemon = True
        mlt_proc.start()   
        print "MLT Proc Started"
        
    if kettle_param.probe != 0:
        print "Starting Kettle Proc in mode " + str(kettle_param.mode) + str(kettle_param.probe)
        kettle_parent_conn_temp, kettle_child_conn_temp = Pipe()   
        kettle_proc = Process(name = "tempControlKettle", target=tempControlChild, args=(kettle_param, statusQ, kettle_child_conn_temp,))
        #kettle_proc.daemon = True
        kettle_proc.start()   
        print "Kettle Proc Started"
        
def tempControlChild(thisparam,  statusQ, conn):
  
    p = current_process()
    print 'Starting:', p.name, p.pid
    parent_conn_temp, child_conn_temp = Pipe()      
        
              
    ptemp = Process(name = "gettempProc", target=gettempProc, args=(thisparam, child_conn_temp,))
    ptemp.daemon = True
    ptemp.start()   
    
    
    parent_conn_heat, child_conn_heat = Pipe()           
    pheat = Process(name = "heatProc", target=heatProc, args=(thisparam.gpio, thisparam.cycle_time, thisparam.duty_cycle, child_conn_heat))
    pheat.daemon = True
    pheat.start() 
 
    temp_F_ma_list = []
    temp_F_ma = 0.0
    temp_C = -100
    
    while (True):
        readytemp = False
        while parent_conn_temp.poll():
            temp_C_temp, elapsed = parent_conn_temp.recv() #non blocking receive
            
            
            if temp_C_temp != -100:
                temp_C = temp_C_temp
                
            try:
                temp_F = (9.0/5.0)*temp_C + 32
            except:
                temp_F = 0.0
                
            if thisparam.name == "kettle" :
                
                kettle_param.temp = temp_F
                
            if thisparam.name == "mlt" :
                
                mlt_param.temp = temp_F
            if thisparam.name == "hlt" :
                
                hlt_param.temp = temp_F
                

            thisparam.temp = temp_F
            temp_F_ma_list.append(temp_F) 
            
            #print temp_F_ma_list
            #smooth temp data
            #
            if (len(temp_F_ma_list) == 1):
                temp_F_ma = temp_F_ma_list[0]
            elif (len(temp_F_ma_list) == 2):
                temp_F_ma = (temp_F_ma_list[0] + temp_F_ma_list[1]) / 2.0
            elif (len(temp_F_ma_list) == 3):
                temp_F_ma = (temp_F_ma_list[0] + temp_F_ma_list[1] + temp_F_ma_list[2]) / 3.0
            elif (len(temp_F_ma_list) == 4):
                temp_F_ma = (temp_F_ma_list[0] + temp_F_ma_list[1] + temp_F_ma_list[2] + temp_F_ma_list[3]) / 4.0
            else:    
                temp_F_ma = (temp_F_ma_list[0] + temp_F_ma_list[1] + temp_F_ma_list[2] + temp_F_ma_list[3] + \
                                                                                        temp_F_ma_list[4]) / 5.0
                temp_F_ma_list.pop(0) #remove oldest element in list
                #print "Temp F MA %.2f" % temp_F_ma
            
            temp_C_str = "%3.2f" % temp_C
            temp_F_str = "%3.2f" % temp_F
            readytemp = True
        if readytemp == True:
            if thisparam.mode == "auto":
                #calculate PID every cycle - alwyas get latest temp
                #duty_cycle = pid.calcPID(float(temp), set_point, True)
                #set_point_C = (5.0/9.0)*(set_point - 32)
                print "Temp F MA %.2f" % temp_F_ma
                thisparam.duty_cycle = pid.calcPID_reg4(temp_F_ma, thisparam.set_point, True)
                #send to heat process every cycle
                parent_conn_heat.send([thisparam.cycle_time, thisparam.duty_cycle])   
            if (not statusQ.full()):    
                statusQ.put([thisparam.name, thisparam.temp]) #GET request
            readytemp == False   
            
        while parent_conn_heat.poll(): #non blocking receive
            cycle_time, duty_cycle = parent_conn_heat.recv()
                 
        readyPOST = False
        while conn.poll(): #POST settings
            mode, cycle_time, duty_cycle_temp, set_point, k_param, i_param, d_param = conn.recv()
            readyPOST = True
        if readyPOST == True:
            if mode == "auto":
                #pid = PIDController.PID(cycle_time, k_param, i_param, d_param) #init pid
                #duty_cycle = pid.calcPID(float(temp), set_point, True)
                pid = PIDController.pidpy(thisparam.cycle_time, thisparam.k_param, thisparam.i_param, thisparam.d_param) #init pid
                #set_point_C = (5.0/9.0)*(set_point - 32)
                thisparam.duty_cycle = pid.calcPID_reg4(temp_F_ma, thisparam.set_point, True)
                parent_conn_heat.send([thisparam.cycle_time, thisparam.duty_cycle])  
            if mode == "manual": 
                thisparam.duty_cycle = thisparam.duty_cycle_temp
                parent_conn_heat.send([thisparam.cycle_time, thisparam.duty_cycle])    
            if mode == "off":
                duty_cycle = 0
                parent_conn_heat.send([thisparam.cycle_time, thisparam.duty_cycle])
            readyPOST = False
        time.sleep(.01)
        
                    
class getrand:
    def __init__(self):
        pass
    def GET(self):
        #global parent_conn  
        while parent_conn.poll(): #get last
            randnum, mode, cycle_time, duty_cycle, set_point, k_param, i_param, d_param = parent_conn.recv()
        #controlData = parent_conn.recv()
        out = json.dumps({"temp" : randnum,
                          "mode" : mode,
                    "cycle_time" : cycle_time,
                    "duty_cycle" : duty_cycle,
                     "set_point" : set_point,
                       "k_param" : k_param,
                       "i_param" : i_param,
                       "d_param" : d_param})  
        return out
        #return randomnum()
        
    def POST(self):
        pass

class getstatus:
    
    def __init__(self):
        pass    

    def GET(self):
        #blocking receive
 
        #if (statusQ.full()): #remove old data
        #    for i in range(statusQ.qsize()):
        #        hlt, mlt, kettle = web.ctx.globals.statusQ.get() 
        #name, temp, elapsed, mode, cycle_time, duty_cycle, set_point, k_param, i_param, d_param = web.ctx.globals.statusQ.get()
        
        
                        
        if (mlt_param.temp != -1) | (hlt_param.temp != -1)  | (kettle_param.temp != -1) :
            
            
            out = json.dumps({"hlt_temp": hlt_param.temp,
                              "mlt_temp" : mlt_param.temp,
                           "kettle_temp" : kettle_param.temp,
                           "elapsed" : kettle_param.elapsed,
                           #hlt PID
                           'hlt_mode': hlt_param.mode ,
                           'hlt_cycle_time': hlt_param.cycle_time,
                           'hlt_duty_cycle': hlt_param.duty_cycle,
                           'hlt_set_point': hlt_param.set_point,
                           'hlt_k_param': hlt_param.k_param,
                           'hlt_i_param': hlt_param.i_param,
                           'hlt_d_param': hlt_param.d_param,
                           'hlt_gpio': hlt_param.gpio,
                           #mlt PID
                           'mlt_mode': mlt_param.mode ,
                           'mlt_cycle_time': mlt_param.cycle_time,
                           'mlt_duty_cycle': mlt_param.duty_cycle,
                           'mlt_set_point': mlt_param.set_point,
                           'mlt_k_param': mlt_param.k_param,
                           'mlt_i_param': mlt_param.i_param,
                           'mlt_d_param': mlt_param.d_param,
                           'mlt_gpio': mlt_param.gpio,
                           #kettle PID
                           'kettle_mode': kettle_param.mode ,
                           'kettle_cycle_time': kettle_param.cycle_time,
                           'kettle_duty_cycle': kettle_param.duty_cycle,
                           'kettle_set_point': kettle_param.set_point,
                           'kettle_k_param': kettle_param.k_param,
                           'kettle_i_param': kettle_param.i_param,
                           'kettle_d_param': kettle_param.d_param,
                           'kettle_gpio': kettle_param.gpio
                              })  
            return out
        #return tempdata(
        return
       
    def POST(self):
        pass
    
def randomnum():
    time.sleep(.5)
    return random.randint(50,220)

'''
Requires full path to 1wire sensor temperature file.
ie: /mnt/1wire/28.0000000000/temperature
'''
def tempdata(wire_addr):
    if wire_addr:
        try:
            pipe = Popen(["cat",str(w1_addr)], stdout=PIPE)
        except:
            temp_C = 0.0
            return
    else:
        temp_C = 0.0
        return
    
    result = pipe.communicate()[0]
    result_list = result.split("=")
    temp_C = -100
    
    if result.find("NO") == -1: 
        try:
            temp_C = float(result_list[-1]) # temp in Celcius
            if temp_c > 1000: #if the sensor is hooked up directly to the gpio pin it returns a something
                              #like 2874 for 2.874 degrees c. owfs would return 2.874
                temp_c = temp_c/1000
            
        except:
            temp_C = 0.0
            
    return temp_C

def storeConfig():
    #Store the parameters to the config file
    return
    
if __name__ == '__main__':
    
    # Check for Config file
    config = ConfigParser.RawConfigParser()
    try:    
        #Can we open the file for read append? I.e. check it exists
        with open('rpibrew.cfg', 'r+') as cFile:        
            cFile.close()
            cFile = open('rpibrew.cfg', 'r+')    
            pass
    except IOError as e:
        print 'no config: ' + os.curdir
        config.readfp(io.BytesIO(sample_config))
        cFile = open('rpibrew.cfg', 'w+')
        config.write(cFile)
    
    config.readfp(cFile)
    
    #Check to see if the HLT is enabled
    
    hlt_probe = 0
    hlt_gpio = -1
    hlt_enabled = 0
    mlt_enabled = 0
    kettle_enabled = 0
    
    if config.has_section("hlt") :
        hlt_enabled = 1
        
        hlt_probe = config.get("hlt", "probe")
        if config.has_option("hlt", "gpio"): 
            hlt_gpio = int(config.get("hlt", "gpio"))
            
        else: 
            hlt_gpio = -1

   
        if hlt_probe == '0':
            print 'No 1wire Address set, please modify your rpibrew.cfg to include the full path to the sensor temperature!'
        if hlt_gpio == -1:
            print 'No HLT GPIO Address set, please modify your rpibrew.cfg!'
        
    if config.has_section("mlt") :
        mlt_enabled = 1
        
        mlt_probe = config.get("mlt", "probe")
        if config.has_option("mlt", "gpio"): 
            mlt_gpio = int(config.get("mlt", "gpio"))
            
        else: 
            mlt_gpio = -1

   
        if mlt_probe == '0':
            print 'No 1wire Address set, please modify your rpibrew.cfg to include the full path to the sensor temperature!'
        if mlt_gpio == -1:
            print 'No MLT GPIO Address set, please modify your rpibrew.cfg!'
            
    if config.has_section("kettle") :
        kettle_enabled = 1
        
        kettle_probe = config.get("kettle", "probe")
        if config.has_option("kettle", "gpio"): 
            kettle_gpio = int(config.get("kettle", "gpio"))
            
        else: 
            kettle_gpio = -1

   
        if kettle_probe == '0':
            print 'No 1wire Address set, please modify your rpibrew.cfg to include the full path to the sensor temperature!'
        if kettle_gpio == -1:
            print 'No Kettle GPIO Address set, please modify your rpibrew.cfg!'
        
    
    
    
    os.chdir("/var/www")
     
    call(["modprobe", "w1-gpio"])
    call(["modprobe", "i2c-dev"])
    
    urls = ("/", "raspibrew",
        "/getrand", "getrand",
        "/getstatus", "getstatus")

    render = web.template.render("/var/www/templates/")

    app = web.application(urls, globals()) 
    
    GPIO.setmode(GPIO.BOARD)

    
    hlt_param = Value(param)
    mlt_param = Value(param)
    kettle_param = Value(param)

    if hlt_enabled == 1:
              
        hlt_param.gpio = hlt_gpio
        hlt_param.probe = hlt_probe
        hlt_param.name = "hlt"
    else:
        hlt_param.probe = 0
        hlt_param.gpio = -1
        

    if mlt_enabled == 1:
        mlt_param.gpio = mlt_gpio
        mlt_param.probe = mlt_probe
        mlt_param.name = "mlt"
    else:
        mlt_param.probe = 0
        mlt_param.gpio = -1

    if kettle_enabled == 1:
        kettle_param.gpio = kettle_gpio
        kettle_param.probe = kettle_probe
        kettle_param.name = "kettle"
    else:
        kettle_param.probe = 0
        kettle_param.probe = -1
        
    # do we even have enough to start?
    if kettle_enabled != 1 & mlt_enabled != 1 & hlt_enabled != 1:
        print "No sensors defined, exiting"
    else:
    
        # ten should be enough
        # this will need to be removed
        statusQ = Queue(3)       
        parent_conn, child_conn = Pipe()
        p = Process(name = "tempControlProc", target=tempControlProc, args=(hlt_param, kettle_param, mlt_param, statusQ, child_conn))
        p.start()
        
        app.add_processor(add_global_hook(parent_conn, statusQ))
         
         
        app.run()


