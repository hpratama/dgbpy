#
# (C) dGB Beheer B.V.; (LICENSE) http://opendtect.org/OpendTect_license.txt
# AUTHOR   : Wayne Mogg
# DATE     : January 2020
#
# Service Manager
#
# 
import json
import os
import io
import psutil
import signal
import socket
import struct
import sys
import threading
import odpy.common as odcommon
from tornado.iostream import StreamClosedError
from tornado import gen
import tornado.tcpserver

class ServiceMgr(tornado.tcpserver.TCPServer):
  def __init__(self, cmdserver, ppid, serviceID=None):
    super(ServiceMgr, self).__init__()
    self.host = None
    self.port = None
    self.serviceID = serviceID
    if '@' in cmdserver:
      info = cmdserver.split('@')
      cmdserver = info[1]
    if ':' in cmdserver:
      info = cmdserver.split(':')
      self.host = info[0]
      self.port = int(info[1])

    self._parentproc = None
    if ppid > 0:
      self._parentproc = psutil.Process(ppid)
      tornado.ioloop.PeriodicCallback(self._parentChkCB, 1000)

    self._startServer()
    self._actions = dict()
    
  def __enter__(self):
    return self
  
  def __exit__(self, exc_type, exc_value, traceback):
    pass
#    self.stop()
    
  def _startServer(self, attempts=20):
    port = self.port+1
    while attempts:
      attempts -=1
      try:
        self.listen(port)
        self._register(port)
        return
      except OSError as ex:
        if "Address already in use" in str(ex):
          port += 1
        else:
          raise ex
    raise Exception("Failed to find available port");

  def _register(self, port):
    Message().sendObject(self.host, self.port,
                   'register', {'servicename': self.serviceID,
                                'hostname': socket.gethostname(),
                                'port': port,
                                'pid': os.getpid()
                                })
    
  def _parentChkCB(self):
    if self._parentproc != None and not self._parentproc.is_running():
      odcommon.std_msg('Found dead parent, exiting')
      self.stop()
      os.kill(psutil.Process().pid, signal.SIGINT)
      
  async def handle_stream(self, stream, address):
    hdrlen = 10
    while True:
      try:
        odhdr = await stream.read_bytes(hdrlen)
        payload_len = struct.unpack('=i', odhdr[0:4])[0]
        packetbody = await stream.read_bytes(payload_len)
        inpacket = Packet(odhdr + packetbody)
        resp_packet = self._processPacket(inpacket)
        await stream.write(resp_packet.packet)
      except StreamClosedError:
        break
      
  def _processPacket(self, inpacket):
    payload = inpacket.getTextPayload()
    result = {}
    for key, params in payload.items():
      result = self._actions.get(key)(params)
      
    obj = dict()
    obj[key] = result
    inpacket.setTextPayload(obj)
    return inpacket

  def addAction(self, key, action):
    self._actions[key] = action

    
class Message:
  def parseAddress(self, address):
    host = None
    port = None
    if '@' in address:
      info = address.split('@')
      address = info[1]
    if ':' in address:
      info = address.split(':')
      host = info[0]
      port = int(info[1])
    return host, port
        
  def sendObject(self, host, port, objkey, jsonobj):
    packet = Packet()
    packet.setIsNewRequest()
    obj = dict()
    obj[objkey] = jsonobj
    packet.setTextPayload(obj)
    tornado.ioloop.IOLoop.current().add_callback(self._send, host, port, packet)
    
  def sendObjectToAddress(self, address, objkey, jsonobj):
    host, port = self.parseAddress(address)
    self.sendObject(host, port, objkey, jsonobj)

  def sendEvent(self, host, port, eventstr):
    packet = Packet()
    packet.setIsNewRequest()
    action = {'action': eventstr}
    packet.setTextPayload(action)
    tornado.ioloop.IOLoop.current().add_callback(self._send, host, port, packet)

  def sendEventToAddress(self, address, eventstr):
    host, port = self.parseAddress(address)
    self.sendEvent(host, port, eventstr)

  async def _send(self, host, port, packet):
    client = tornado.tcpclient.TCPClient()
    stream = await client.connect(host, port)
    await stream.write(packet.packet)


class Packet:
  _curreqid = 0
  def __init__(self, packet=None):
    self._reqid = None
    self._subid = None
    self.jsonheader = None
    self.packet = packet
    self._lock = threading.Lock()

  def setIsNewRequest(self):
    with self._lock:
      self._curreqid += 1
    self._reqid = self._curreqid
    self._subid = -1
    return self._reqid
    
  def setTextPayload(self, jsonobj):
    content_encoding = 'utf-8'
    payload = {
          'content_bytes': self._json_encode(jsonobj, content_encoding),
          'content_type': 'text/json',
          'content_encoding': content_encoding,
          'arrsize': None,
    }
    self._createPacket(payload)
    
  def getTextPayload(self):
    content_encoding = 'utf-8'
    payload_bytes = self._odhdr_decode()
    self.jsonheader, data = self._json_decode(payload_bytes, content_encoding)

    for reqhdr in (
        "byteorder",
        "content-length",
        "content-type",
        "content-encoding",
      ):
      if reqhdr not in self.jsonheader:
        raise ValueError(f'Missing required header "{reqhdr}".')
    
    content_len = self.jsonheader['content-length']
    if len(data)!=content_len:
        raise ValueError(f'Message payload size error, expected "{content_len}" got "{len(data)}".')
    
    if self.jsonheader['content-type']=='text/json':
      payload, data = self._json_decode(data, content_encoding)
      
    return payload

  def _createPacket(self, payload):
    jsonheader = {
        'byteorder': sys.byteorder,
        'content-type': payload['content_type'],
        'content-encoding': payload['content_encoding'],
        'content-length': len(payload['content_bytes']),
        }
    if payload['arrsize'] != None:
      jsonheader.update({ 'array-shape': payload['arrsize'] })

    jsonheader_bytes = self._json_encode(jsonheader, 'utf-8')
    payload_bytes = jsonheader_bytes + payload['content_bytes']
    od_hdr = struct.pack('=i',len(payload_bytes)) \
             + struct.pack('=i',self._reqid) \
             + struct.pack('=h',self._subid)
    self.packet = od_hdr + payload_bytes

  def _json_encode(self, obj, encoding):
    json_hdr = json.dumps(obj, ensure_ascii=False).encode(encoding)
    return struct.pack('=i',len(json_hdr)) + json_hdr

  def _odhdr_decode(self):
    hdrlen = 10
    if self.packet==None or len(self.packet)<hdrlen:
      return False
    self._reqid = struct.unpack('=i',self.packet[4:8])[0]
    self._subid = struct.unpack('=h',self.packet[8:hdrlen])[0]
    return self.packet[hdrlen:]
    
    
  def _json_decode(self, json_bytes, encoding):
    hdrlen = 4
    jsonobj_len = struct.unpack('=i',json_bytes[:hdrlen])[0]
    tiow = io.TextIOWrapper(
      io.BytesIO(json_bytes[hdrlen:hdrlen+jsonobj_len]), encoding=encoding, newline=""
    )
    jsonobj = json.load(tiow)
    tiow.close()

    return (jsonobj, json_bytes[hdrlen+jsonobj_len:])
