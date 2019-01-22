#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from htheatpump.htheatpump import HtHeatpump
from htheatpump.htparams import HtDataTypes, HtParams
from timeit import default_timer as timer
import paho.mqtt.client as mqtt
import time
import logging
_logger = logging.getLogger(__name__)

HELIOTHERM_MQTT_PREFIX = 'heliotherm'
BROKER_HOST = 'localhost'
BROKER_PORT = 1883
FREQUENCY = 300

def connheatpump():
    global hp
    try:
        hp = HtHeatpump("/dev/ttyAMA0", baudrate=115200)
        hp.open_connection()
        hp.login()
        rid = hp.get_serial_number()
        _logger.info("connected successfully to heat pump with serial number "+str(rid))
        mqttc.publish("{}/global/connectorstatus".format(HELIOTHERM_MQTT_PREFIX), "Heliotherm Connector: CONNECTED", retain=True)
    except Exception as ex:
        _logger.error(ex)
        sys.exit(1)

def readall():
    result = {}
    start = timer()
    try:
        for name in HtParams.keys():
            value = hp.get_param(name)
            if HtParams[name].data_type == HtDataTypes.BOOL:
                value = 1 if value else 0
            result.update({name: value})
    except Exception as ex:
        _logger.error(ex)
        raise
    end = timer()
    _logger.debug("readall execution time: {:.2f} sec".format(end - start))
    return result

def readspecific(param):
    result = {}
    start = timer()
    try:
        if param in HtParams.keys():
            value = hp.get_param(param)
            result.update({param: value})
        else:
            _logger.error("unknown parameter requested: "+str(param))
    except Exception as ex:
        _logger.error(ex)
        raise
    end = timer()
    _logger.debug("readspecific execution time: {:.2f} sec".format(end - start))
    return result

def setspecific(param, value):
    result = {}
    verify = {}
    start = timer()
    try:
        if param in HtParams.keys():
            setval = HtParams[param].from_str(value)
            newval = hp.set_param(param, setval)
            if HtParams[param].data_type == HtDataTypes.BOOL:
                newval = 1 if newval else 0
            result.update({param: newval})
            verify = readspecific(param)
            if result != verify:
                _logger.error("setting parameter "+param+" failed")
                verify = {}
        else:
            _logger.error("unknown parameter requested: "+str(param))
    except Exception as ex:
        _logger.error(ex)
        raise
    end = timer()
    _logger.debug("setspecific execution time: {:.2f} sec".format(end - start))
    return verify

def closeconn():
    try:
        hp.logout()
        hp.close_connection()
        mqttc.publish("{}/global/connectorstatus".format(HELIOTHERM_MQTT_PREFIX), "Heliotherm Connector: DISCONNECTED", retain=True)
    except Exception as ex:
        _logger.error(ex)
        sys.exit(1)

def on_message(client, userdata, message):
    _logger.info("received message "+str(message.payload.decode("utf-8"))+" on topic "+str(message.topic))
    if str(message.topic).endswith("/get"):
        param = str(message.topic)[len(HELIOTHERM_MQTT_PREFIX)+1:-4]
        _logger.info("get "+param+" requested")
        connheatpump()
        values = readspecific(param)
        for k, v in values.items():
           (result, mid) = mqttc.publish("{}/{}".format(HELIOTHERM_MQTT_PREFIX, k), str(v), 0)
        closeconn()
    elif str(message.topic).endswith("/set") and str(message.payload.decode("utf-8")) != '':
        param = str(message.topic)[len(HELIOTHERM_MQTT_PREFIX)+1:-4]
        value = str(message.payload.decode("utf-8"))
        _logger.info("set parameter "+param+" with value "+value+" requested")
        connheatpump()
        newval = setspecific(param, value)
        for k, v in newval.items():
            (result, mid) = mqttc.publish("{}/{}".format(HELIOTHERM_MQTT_PREFIX, k), str(v), 0)
        closeconn()
    else:
        _logger.error("no handling defined for MQTT topic "+str(message.topic))

def main():
    global mqttc
    mqttc = mqtt.Client('heliotherm-connector', clean_session=True)
    mqttc.will_set("{}/global/connectorstatus".format(HELIOTHERM_MQTT_PREFIX), "Heliotherm Connector: LOST_CONNECTION", 0, retain=True)
    mqttc.connect(BROKER_HOST, BROKER_PORT, 60)
    mqttc.publish("{}/global/connectorstatus".format(HELIOTHERM_MQTT_PREFIX), "Heliotherm Connector: ON-LINE", retain=True)
    mqttc.loop_start()

    mqttw = mqtt.Client('heliotherm-watcher', clean_session=True)
    mqttw.on_message=on_message
    mqttw.connect(BROKER_HOST, BROKER_PORT, 60)
    mqttw.loop_start()
    mqttw.subscribe([("{}/sensor/+/get".format(HELIOTHERM_MQTT_PREFIX), 0),("{}/param/+/set".format(HELIOTHERM_MQTT_PREFIX),0)])

    oldvalues = {}
    while True:
        try:
            connheatpump()
            values = readall()
            for k, v in values.items():
                if v != oldvalues.get(k, ''):
                    (result, mid) = mqttc.publish("{}/{}".format(HELIOTHERM_MQTT_PREFIX, k), str(v), 0)
            closeconn()
            oldvalues = values
            time.sleep(FREQUENCY)
        except KeyboardInterrupt:
            mqttc.disconnect()
            mqttc.loop_stop()
            mqttw.disconnect()
            mqttw.loop_stop()
            break
        except Exception as ex:
            _logger.error(ex)
            mqttc.disconnect()
            mqttc.loop_stop()
            mqttw.disconnect()
            mqttw.loop_stop()
            sys.exit(1)

if __name__ == "__main__":
    main()

