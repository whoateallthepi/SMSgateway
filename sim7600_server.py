#
# A simple server to receive input messages via a socket, stick them in a queue and then 
# push them out to a SMS modem (SIM7600 in this case).
#
# Thread one adds any messages to be sent to a Queue object
# Thread two processes the queue and stuffs them to the modem
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

from queue import Queue
from threading import Thread
from time import sleep

from atlib import *

def initialise():
    '''
    Establish the shared Queue object and start the threads
    '''
    message_queue = Queue()

    t1 = Thread(target=messages_in, args=(message_queue,))
    t2 = Thread(target=messages_out, args=(message_queue,))

    t1.start()
    t2.start()

def send (message):
    gsm = GSM_Device("/dev/ttyAMA0")

    status = gsm.send_sms(message['number'].strip('+'), message['message'])

    if status != Status.OK:
        print("T2: Error sending SMS")
    else:
        print("T2: message {} sent to {}".format(message['message'], message['number'].strip('+')))    

def messages_in (q):
    # Create and connect to socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(('0.0.0.0', 8001))
    server_socket.listen(1)
    print('T1: Server listening on localhost:8001')
    while True:
        print('T1: waiting....')
        client_socket, addr = server_socket.accept()
        print(f'T1: Connection from {addr}')

        ## Receive data from the client
        data = client_socket.recv(1024)
        data_dict = json.loads(data.decode())
        print(f'T1: Received: {data_dict}')
        for m in data_dict['messages']:
            q.put(m)

        ## Send a response to the client
        response_dict = {'message': 'Hello, client!'}
        response_data = json.dumps(response_dict).encode()
        client_socket.sendall(response_data)

        client_socket.close()
    return

def messages_out(q):
    while True:
        if q.empty():
            print("T2: Empty queue ... sleeping")
            sleep(10)
        else:
            while not q.empty():
                entry = q.get()
                print("\nT2: Processing queue entry")
                print(entry)
                send(entry)

    return

if __name__ == "__main__":

    sys.exit(initialise())
