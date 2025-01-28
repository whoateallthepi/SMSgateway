#
# A simple server to receive input messages via a socket, stick them in a queue and then 
# push them out to a SMS modem (SIM7600 in this case).
#
# Thread one adds any messages to be sent to a Queue object
# Thread two processes the queue and stuffs them to the modem. It also
# checks for any incoming sms messages and stuffs them in a queue for Thread 3.
# Thread three takes incoming messages off the queue and sends them to the webserver API for 
# action.
#
#
#
#
#
#
#

import socket
import json
import sys
import requests
import logging
import argparse
from datetime import datetime

from queue import Queue
from threading import Thread, Event
from time import sleep
from textwrap import wrap

from configparser import ConfigParser
from config import config_sms 
from config import config_api

from atlib import *

base_url = 'http://webdev:8000/api/message/'

version = '1.00'
# do the arguments

parser = argparse.ArgumentParser()
parser.add_argument("--loglevel", help="log level - suggest <info> when it is working",
                    default="DEBUG")

parser.add_argument("--debug", help="helps us debug default is true",
                    action="store_true")

parser.add_argument("--log_file", help="Location of log file - defauits to ''",
                    default="/var/log/sms_gateway.log")

parser.add_argument("--message_log_file", help="Location of message log file - defauits to ''",
                    default="/var/log/sms_message.log")

args = parser.parse_args()
loglevel = args.loglevel

numeric_level = getattr(logging, loglevel.upper(), None)

api_params = config_api()
sms_params = config_sms()

timestamp = '%Y-%m-%d %H:%M:%S'

# configure log file and message log 

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(threadName)s - %(levelname)s - %(message)s',
    datefmt= timestamp,
    filename=args.log_file,
    level=numeric_level)

logger = logging.getLogger('SMSgateway')

if args.debug:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    # simpler formatter for console
    formatter = logging.Formatter('%(name)-12s: %(levelname)-8s %(message)s')
    console_handler.setFormatter(formatter)
    logging.getLogger('').addHandler(console_handler)
    #logger.addHandler(console_handler)
    logger.debug('Running in debug mode')
    
logger.info('Version {} starting'.format(version))

logger.info('configuring message log')

try:
    with open(args.message_log_file, 'at') as message_log: # append
        now = datetime.now().strftime(timestamp)
        message_log.write('{} Starting SMSgateway.py\n'.format(now)) 
except Exception as error:
    logger.error('failed to access message log {} with error {}'.format(args.message_log_file, error))    

debug = args.debug

def main():
    '''
    Establish the shared Queue object and start the threads
    '''
    logger.info ('Initialising queues')
    
    send_message_queue = Queue() # messages to be sent out by thread 2
    received_message_queue = Queue() # incoming messages to be dealt with by thread 3
    message_received_event = Event()
    messages_to_send_event = Event()

    t1 = Thread(target=messages_to_send, args=(send_message_queue,messages_to_send_event))
    t2 = Thread(target=process_messages, args=(send_message_queue,
                                               received_message_queue,
                                               message_received_event,
                                               messages_to_send_event,))
    t3 = Thread(target=process_received_SMS, args=(received_message_queue,message_received_event,))

    t1.start()
    t2.start()
    t3.start()

def send (gsm_device, message):
    def pretty_status (status):
        if status == Status.OK:
            return 'SUCCESS'
        else:
            return 'FAILED '
    
    gsm = GSM_Device(sms_params['gsm_device'])
    
    m = message['message']
    num = message['number'].strip('+')
    if len(m) <= 144:
        message_list = [m] #convert to a list for below
    else:
        message_list = wrap(m,width=138)
    
    l = len(message_list)        
    for i, m in enumerate (message_list):
        if i < l - 1:
            m = m + ' [...]'
        status = gsm.send_sms(message['number'].strip('+'), m)
        if status != Status.OK:
            logger.error("Error sending SMS. Status {}".format(status))
        else:
            logger.info("Message {} sent to {}".format(m, message['number']))

        try:
            with open(args.message_log_file, 'at') as message_log: # append
                now = datetime.now().strftime(timestamp)
                message_log.write('{} SEND {} to {}. Message: {}\n'.format(now, pretty_status(status),
                                                                        message['number'],
                                                                        m )) 
        except Exception as error:
            logger.error('failed to open message log {} with error {}'.format(args.message_log_file, error))    


#==========================  Thread 1 ========================================#
def messages_to_send (q, send_event):
    # Create and connect to socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((sms_params['listen'], int(sms_params['port'])))
    server_socket.listen(1)
    logger.info('Server listening on {}:{}'.format(sms_params['listen'], sms_params['port']))
    while True:
        logger.info('Waiting....')
        client_socket, addr = server_socket.accept()
        
        try: 
            logger.info('Connection from {}'.format(addr))
            ## Receive data from the client
            data = client_socket.recv(1024)
            data_dict = json.loads(data.decode())
            logger.info('Received'.format(data_dict))

            for m in data_dict['messages']:
                q.put(m)
             
            if len(data_dict['messages']) > 0:  
                send_event.set()

            ## Send a response to the client
            response_dict = {'message': 'Hello, client!'}
            response_data = json.dumps(response_dict).encode()
            client_socket.sendall(response_data)
        except Exception as e:
            logger.error("Exception receiving data {} - ignoring for now".format(e))
        finally:
            client_socket.close()

#========================== Thread 2 =========================================#
def process_messages(qsend, qreceived, received_event, send_event):
    gsm = GSM_Device("/dev/ttyAMA0")
    while True:
        logger.info("Waiting for messages")
        if send_event.wait(timeout=5):
            send_event.clear()
            while not qsend.empty():
                entry = qsend.get()
                logger.info('Sending queue entry {}'.format(entry))
                send(gsm, entry)

        # check for any incoming SMSs
        incoming = gsm.receive_sms()

        logger.info('Incoming SMS message(s) {}'.format(incoming))
        for i in incoming:
            qreceived.put(i)
            try:
                with open(args.message_log_file, 'at') as message_log: # append
                        now = datetime.now().strftime(timestamp)
                        message_log.write('{} RECEIVED from {}. Message: {}\n'.format(now,
                                                                                i[0],
                                                                                i[3]))
            except Exception as error:
                logger.error('failed to open message log {} with error {}'.format(args.message_log_file, error))  

        gsm.delete_read_sms() # keep sim tidy
        
        if len(incoming) > 0:
            received_event.set() 

    return # runs forever

#================================== Thread 3 =================================#
def process_received_SMS(q, message_available):

    while True:
        while not message_available.wait(timeout=10):
            logger.info("Waiting for messages")
        
        if message_available:
            message_available.clear()
        
        while not q.empty():
            
            message = q.get()
            logger.info("SMS received: {}".format(message))

            try:
                r = requests.post(api_params['url'],
                    json = {
                        'message': message[3],
                        'number' : message [0],
                        },
                    auth = (api_params['user'], api_params['password'])
                )
                logger.info("Response from post: {}".format(r.status_code))
            except Exception as error:
                logger.error('Failed to write to {} with error {}'.
                             format(api_params['url'], error))

if __name__ == "__main__":

    sys.exit(main())
