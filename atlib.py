#--- Python ATlib. ---#
# Allows reading and writing to an AT interface style port.
# Writing is performed with no checks. Reading is performed with header
# analysis based on replies and returns an array.
# 
# Supports the basic AT commands and even prompts from AT+CMGS.
# Implement the error handling logic in your applications.
# Most methods return a boolean that is true if there is an error.
#
# Written by swordstrike1.
# 
# Downloaded from https://github.com/arceryz/ATlib subsequently tweaked by Tom Cooper to 
# work with the Wavesure SIM7600E-H hat on a Pi https://www.waveshare.com/wiki/SIM7600E-H_4G_HAT 
# There are some very minor textual differences in responses which took a while to figure out.
# The bulk of the work was done by swordstrike1 - many thanks.

from serial import *
from time import *

import logging

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

class SMS_Group:
    UNREAD = "REC UNREAD"
    READ = "REC READ"
    STORED_UNSENT = "STO UNSENT"
    STORED_SENT = "STO SENT"
    ALL = "ALL"


class Status:
    OK = "OK"
    PROMPT = "> "
    TIMEOUT = "TIMEOUT"
    ERROR_SIM_PUK = "ERORR_SIM_PUK"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class AT_Device:
    """ Base class for all device with AT commands. 
    For higher level GSM features, use GSM_Device."""

    def __init__(self, path, baudrate=115200):
        """ Open AT device. Nothing else."""
        self.serial = Serial(path, timeout=0.5, baudrate=baudrate)
        log.debug("AT serial device opened at {:s}".format(path))
    
    def __del__(self):
        """ Close AT device. """
        self.serial.close()

    def write(self, cmd):
        """ Write a single line to the serial port. """
        encoded = (cmd + "\r\n").encode()
        self.serial.write(encoded)
        log.debug("WRITE: {}".format(cmd))
        return Status.OK

    def write_ctrlz(self):
        """ Write the terminating CTRL-Z to end a prompt. """
        self.serial.write(bytes([26]))
        log.debug("WRITE: Ctrl-Z")
        return Status.OK


    def has_terminator(response, stopterm=""):
        """ Return True if response is final. """
        # If the string ends with one of these terms, then we stop reading.
        endterms = ["\r\nOK\r\n", "\r\nERROR\r\n", "> " ]

        # We can stop reading if either an endterm is detected or
        # the stopterm is inside the string which causes immediate halt.
        can_terminate = stopterm != "" and stopterm in response
        for s in endterms:
            if response.endswith(s):
                can_terminate = True
                break
        return can_terminate


    def tokenize_response(response):
        """ Chop a response in pieces for parsing. """
        # First split by newline.
        table = response.split("\r\n")
        final_table = []

        for i in range(len(table)):
            # Remove trailing "\r".
            el = table[i].replace("\r", "")
            # Take only nonempty entries".
            if el != "":
                final_table.append(el)
        return final_table


    def read(self, timeout=10, stopterm=""):
        """ Read a single whole response from an AT command.
        Returns a list of tokens for parsing. """
        resp = ""
        start_time = time()
        delay = 0.01
        while True:
            avail = self.serial.in_waiting
            if(avail > 0):
                # Read bytes and check if terminator is contained.
                # If it is not a utf-8 string, return error.
                try:
                    resp += self.serial.read(avail).decode("utf-8")
                except:
                    log.debug("READ: {}".format(resp))
                    return [ resp, Status.ERROR ] 
                if AT_Device.has_terminator(resp, stopterm):
                    log.debug("READ: {}".format(resp))
                    table = AT_Device.tokenize_response(resp)
                    return table

            if time() - start_time > timeout:
                log.debug("READ: {}".format(resp))
                return [ resp, Status.TIMEOUT ]
            sleep(delay)


    def read_status(self, msg=""):
        """ Returns status of latest response. """
        status = self.read()[-1]
        if status != Status.OK and status != Status.PROMPT:
            log.debug("Status:{:s}: {:s}".format(status, msg))
        return status


    def sync_baudrate(self, retry=True):
        """ Synchronize the device baudrate to the port. 
        You should always call this first. Returns status."""
        log.debug("Performing baudrate sync, retry={:s}".format(str(retry)))
        # Write AT and test whether received OK response.
        # A broken serial port will not reply.
        while True:
            self.write("AT")
            status = self.read(timeout=5)[-1]
            if status == Status.OK:
                log.debug("Sync sucuccesful")
                return status
            elif retry:
                log.debug("-> Retrying sync")
            else:
                log.debug("Failure to sync baudrate")


    def reset_state(self):
        """ Ensures the state of the AT device is on par for a new environment. """
        # Read all remaining bytes.
        if self.serial.in_waiting > 0:
            self.serial.read(self.serial.in_waiting)
        # Write AT status message.
        for i in range(0, 10):
            self.write("AT")
            status = self.read_status()
            if status == Status.OK:
                break


class GSM_Device(AT_Device):
    """ A class that provides higher level GSM features such
    as sending/receiving SMS and unlocking sim pin."""


    def __init__(self, path):
        """ Open GSM Device. Device sim still needs to be unlocked. """
        log.debug("Opening GSM device")
        super().__init__(path)
        while self.sync_baudrate() != Status.OK:
            sleep(1)


    def reboot(self):
        """ Reboot the GSM device. Returns status. """
        log.debug("Rebooting GSM device")
        self.write("AT+CFUN=1,1")
        return self.read_status("Rebooting")


    def get_sim_status(self):
        """ Returns status of sim lock. True of locked. """
        self.reset_state()
        self.write("AT+CPIN?")
        resp = self.read()
        if "READY" in resp[1]: return Status.OK
        if "SIM PUK" in resp[1]: return Status.ERROR_SIM_PUK
        return Status.UNKNOWN


    def unlock_sim(self, pin):
        """ Unlocks the sim card using pin. Can block for a long time.
        Returns status."""
        self.reset_state()
        # Test whether sim is already unlocked.
        if self.get_sim_status() == Status.OK: return Status.OK

        # Unlock sim.
        log.debug("Trying SIM pin={:s}".format(pin))
        self.write("AT+CPIN={:s}".format(pin))
        status = self.read_status("Setting pin")
        if status != Status.OK: return status

        # Wait until unlocked.
        log.debug("Awaiting SMS ready status")
        self.read(stopterm="SMS Ready")
        log.debug("Sim unlocked")
        return Status.OK


    def send_sms(self, nr, msg):
        """ Sends a text message to specified number. 
        Returns status."""
        self.reset_state()
        # Set text mode.
        log.debug("Sending \"{:s}\" to {:s}.".format(msg, nr))
        self.write("AT+CMGF=1")
        status = self.read_status("Text mode")
        
        if status != Status.OK: return status
       
        # Write message.
        
        self.write("AT+CMGS=\"{:s}\"".format(nr))
        status = self.read_status("Set number")
        if status != Status.PROMPT: return status
        self.write(msg)
        #self.read()
        self.write_ctrlz()
        status = self.read_status("Sending message")

        log.debug("Message sent.")
        return status


    def receive_sms(self, group=SMS_Group.UNREAD):
        """ Receive text messages. See types of message from SMS_Group class. """
        self.reset_state()
        # Read unread. After reading they will not show up here anymore!
        log.debug("Scanning {:s} messages...".format(group))
        self.write("AT+CMGF=1")
        status = self.read_status("Text mode")
        if status != Status.OK: return status

        # Read the messages.
        self.write("AT+CMGL=\"{:s}\"".format(group))
        resp = self.read()
        if resp[-1] != Status.OK: return resp[-1]
        
        table = []

        if len(resp) == 2:
            # all we have is the ['AT+CMGL="REC UNREAD"', 'OK'] so there are no unread messages
            # return an empty table
            log.debug("No unread messages on SIM.")
            return table

        # TotalElements = 2 + 2 * TotalMessages.
        # First and last elements are echo/result.
        
        for i in range(1, len(resp) - 2, 2):
            header = resp[i].split(",")
            message = resp[i + 1]
            # Extract elements and strip garbage.
            sender = header[2].replace("\"", "")
            date = header[4].replace("\"", "")
            time = header[5].split("+")[0]
            el = [sender, date, time, message]
            table.append(el)
        
        return table


    def delete_read_sms(self):
        """ Delete all messages except unread. Including drafts. """
        self.reset_state()
        self.write("AT+CMGD=1,3")
        return self.read_status("Deleting message")