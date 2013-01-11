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


from multiprocessing import Process, Pipe, Queue, current_process
from subprocess import Popen, PIPE, call
from datetime import datetime
import web, time, random, json, serial, os
import RPi.GPIO as GPIO
#from pid import pid as PIDController
from pid import pidpy as PIDController
import ConfigParser
import io

sample_config = """
[rpibrew]
hlt_gpio = -1
hlt_probe = 0
"""



class param:
    mode = "off"
    cycle_time = 2.0
    duty_cycle = 0.0
    set_point = 0.0
    k_param = 44
    i_param = 165
    d_param = 4
    temp = -1
    probe = -1
    name = "off"


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
            if datalistkey[0] == "mode":
                self.mode = datalistkey[1]
            if datalistkey[0] == "setpoint":
                self.set_point = float(datalistkey[1])
            if datalistkey[0] == "dutycycle":
                self.duty_cycle = float(datalistkey[1])
            if datalistkey[0] == "cycletime":
                self.cycle_time = float(datalistkey[1])
            if datalistkey[0] == "k":
                self.k_param = float(datalistkey[1])
            if datalistkey[0] == "i":
                self.i_param = float(datalistkey[1])
            if datalistkey[0] == "d":
                self.d_param = float(datalistkey[1])
         
        web.ctx.globals.parent_conn.send([self.mode, self.cycle_time, self.duty_cycle, self.set_point, \
                              self.k_param, self.i_param, self.d_param])  
             
 
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
        elapsed = "%.2f" % (time.time() - t)
        conn.send([num, elapsed])
    
        

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
    print "HLT Param: " + str(hlt_param)
    print "MLT Param: " + str(mlt_param)
    if hlt_param.probe != 0:
        print "Starting HLT Proc in mode " + hlt_param.mode + hlt_param.probe
        hlt_parent_conn_temp, hlt_child_conn_temp = Pipe()   
        hlt_proc = Process(name = "tempControlHLT", target=tempControlChild, args=(hlt_param, hlt_param.probe, hlt_param.gpio, hlt_param.mode, hlt_param.cycle_time, hlt_param.duty_cycle, hlt_param.set_point, hlt_param.k_param, hlt_param.i_param, hlt_param.d_param, statusQ, hlt_child_conn_temp,))
        #hlt_proc.daemon = True
        hlt_proc.start()   
        print "HLT Proc Started"
        
def tempControlChild(thisparam, probe, gpio, mode, cycle_time, duty_cycle, set_point, k_param, i_param, d_param, statusQ, conn):
            
    p = current_process()
    print 'Starting:', p.name, p.pid
    parent_conn_temp, child_conn_temp = Pipe()      
        
              
    ptemp = Process(name = "gettempProc", target=gettempProc, args=(thisparam, child_conn_temp,))
    ptemp.daemon = True
    ptemp.start()   
    parent_conn_heat, child_conn_heat = Pipe()           
    pheat = Process(name = "heatProc", target=heatProc, args=(gpio, cycle_time, duty_cycle, child_conn_heat))
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
                
            
            temp_F = (9.0/5.0)*temp_C + 32
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
            if mode == "auto":
                #calculate PID every cycle - alwyas get latest temp
                #duty_cycle = pid.calcPID(float(temp), set_point, True)
                #set_point_C = (5.0/9.0)*(set_point - 32)
                print "Temp F MA %.2f" % temp_F_ma
                duty_cycle = pid.calcPID_reg4(temp_F_ma, set_point, True)
                #send to heat process every cycle
                parent_conn_heat.send([cycle_time, duty_cycle])   
            if (not statusQ.full()):    
                statusQ.put([thisparam.name, thisparam.temp, elapsed, mode, cycle_time, duty_cycle, set_point, k_param, i_param, d_param]) #GET request
            readytemp == False   
            
        while parent_conn_heat.poll(): #non blocking receive
            cycle_time, duty_cycle = parent_conn_heat.recv()
                 
        readyPOST = False
        while conn.poll(): #POST settings
            mode, cycle_time, duty_cycle_temp, set_point, k_param, i_param, d_param = conn.recv()
            readyPOST = True
        if readyPOST == True:
            if mode == "auto":
                print "auto selected"
                #pid = PIDController.PID(cycle_time, k_param, i_param, d_param) #init pid
                #duty_cycle = pid.calcPID(float(temp), set_point, True)
                pid = PIDController.pidpy(cycle_time, k_param, i_param, d_param) #init pid
                #set_point_C = (5.0/9.0)*(set_point - 32)
                duty_cycle = pid.calcPID_reg4(temp_F_ma, set_point, True)
                parent_conn_heat.send([cycle_time, duty_cycle])  
            if mode == "manual": 
                print "manual selected"
                duty_cycle = duty_cycle_temp
                parent_conn_heat.send([cycle_time, duty_cycle])    
            if mode == "off":
                print "off selected"
                duty_cycle = 0
                parent_conn_heat.send([cycle_time, duty_cycle])
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
 
        if (statusQ.full()): #remove old data
            for i in range(statusQ.qsize()):
                name, temp, elapsed, mode, cycle_time, duty_cycle, set_point, k_param, i_param, d_param = web.ctx.globals.statusQ.get() 
        name, temp, elapsed, mode, cycle_time, duty_cycle, set_point, k_param, i_param, d_param = web.ctx.globals.statusQ.get() 
            
        global hlt_param
        print "HLT: " + str(hlt_param.temp)
        out = json.dumps({"name": name,
                          "temp" : temp,
                       "elapsed" : elapsed,
                          "mode" : mode,
                    "cycle_time" : cycle_time,
                    "duty_cycle" : duty_cycle,
                     "set_point" : set_point,
                       "k_param" : k_param,
                       "i_param" : i_param,
                       "d_param" : d_param})  
        return out
        #return tempdata()
       
    def POST(self):
        pass
    
def randomnum():
    time.sleep(.5)
    return random.randint(50,220)

def tempdata(wire_addr):
    #change 28-000002b2fa07 to your own temp sensor id
    #pipe = Popen(["cat","/sys/bus/w1/devices/w1_bus_master1/28-000002b2fa07/w1_slave"], stdout=PIPE)
    w1_slave = "/sys/bus/w1/devices/w1_bus_master1/" + wire_addr + "/w1_slave"
    pipe = Popen(["cat",w1_slave], stdout=PIPE)
    result = pipe.communicate()[0]
    result_list = result.split("=")
    temp_C = -100
    
    if result.find("NO") == -1: 
        temp_C = float(result_list[-1])/1000 # temp in Celcius
    #temp_F = (9.0/5.0)*temp_C + 32
    #return "%3.2f" % temp_C
    return temp_C

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
        hlt_gpio = int(config.get("hlt", "gpio"))

   
        if hlt_probe == '0':
            print 'No 1wire Address set, please modify your rpibrew.cfg!'
            pipe = Popen(["cat", "/sys/bus/w1/devices/w1_bus_master1/w1_master_slaves"], stdout=PIPE)
            result = pipe.communicate()[0]
            result_list = result.split("\n")
            for addr in result_list:
                if addr != "":
                    print 'Found address: ' + addr + " with a value of: " + str(tempdata(addr))             
        
        
        if hlt_gpio == -1:
            print 'No HLT GPIO Address set, please modify your rpibrew.cfg!'
        
        
    
    
    
    os.chdir("/var/www")
     
    call(["modprobe", "w1-gpio"])
    call(["modprobe", "i2c-dev"])
    
    urls = ("/", "raspibrew",
        "/getrand", "getrand",
        "/getstatus", "getstatus")

    render = web.template.render("/var/www/templates/")

    app = web.application(urls, globals()) 
    
    GPIO.setmode(GPIO.BOARD)

    if hlt_enabled == 1:
        global hlt_param
        hlt_param = param()
        hlt_param.gpio = hlt_gpio
        hlt_param.probe = hlt_probe
        hlt_param.name = "hlt"
    else:
        hlt_param = param()
        hlt_param.probe = -1
        

    if mlt_enabled == 1:
        mlt_param = param()
        mlt_param.gpio = mlt_gpio
        mlt_param.probe = mlt_probe
        mlt_param.name = "mlt"
    else:
        mlt_param = param()
        mlt_param.probe = 0

    if kettle_enabled == 1:
        kettle_param = param()
        kettle_param.gpio = kettle_gpio
        kettle_param.probe = kettle_probe
        kettle_param.name = "kettle"
    else:
        kettle_param = param()
        kettle_param.probe = 0
        
    
        
    statusQ = Queue(2)       
    parent_conn, child_conn = Pipe()
    p = Process(name = "tempControlProc", target=tempControlProc, args=(hlt_param, kettle_param, mlt_param, statusQ, child_conn))
    p.start()
    
    app.add_processor(add_global_hook(parent_conn, statusQ))
     
     
    app.run()


